"""CSA-02 deterministic settings and URL-governance domain coverage."""

from __future__ import annotations

from dataclasses import replace

import pytest

from musimack_tools.domain.site_audit_settings import (
    MAXIMUM_RULE_TEST_URLS,
    TRACKING_PARAMETERS,
    DecisionLayer,
    PlatformPresetId,
    RuleAction,
    RuleMatchType,
    RuleScope,
    RuleSource,
    SiteAuditSettingsError,
    UrlGovernanceRule,
    broad_rule_warning,
    builtin_presets,
    decision_layers,
    normalize_governed_url,
    preset_for,
    resolve_effective_rules,
    rule_from_mapping,
    rule_matches,
)
from musimack_tools.domain.site_audit_settings import (
    test_rule_set as evaluate_rule_set,
)

_NOW = "2026-07-20T00:00:00+00:00"


def _rule(  # noqa: PLR0913
    match_type: RuleMatchType,
    match_value: str,
    action: RuleAction = RuleAction.MARK_FOR_REVIEW,
    *,
    rule_id: str = "test.rule",
    source: RuleSource = RuleSource.PER_AUDIT,
    overrides: tuple[str, ...] = (),
    case_sensitive: bool = True,
    scope: RuleScope | None = None,
) -> UrlGovernanceRule:
    return rule_from_mapping(
        {
            "rule_id": rule_id,
            "name": rule_id,
            "description": "Bounded test rule",
            "enabled": True,
            "match_type": match_type.value,
            "match_value": match_value,
            "case_sensitive": case_sensitive,
            "action": action.value,
            "reason": "Direct regression evidence",
            "reason_code": rule_id.replace(".", "_"),
            "priority": 10,
            "scope": scope.value if scope else None,
            "overrides_rule_ids": list(overrides),
        },
        source=source,
        created_by="tester",
        now=_NOW,
    )


@pytest.mark.parametrize(
    ("match_type", "match_value", "url", "expected"),
    (
        (
            RuleMatchType.EXACT_URL,
            "https://EXAMPLE.com:443/a?b=2&a=1",
            "https://example.com/a?a=1&b=2#x",
            True,
        ),
        (RuleMatchType.EXACT_PATH, "/Products/", "https://example.com/Products/?x=1", True),
        (RuleMatchType.PATH_STARTS_WITH, "/shop/", "https://example.com/shop/item", True),
        (RuleMatchType.PATH_CONTAINS, "/category/", "https://example.com/a/category/b", True),
        (RuleMatchType.PATH_ENDS_WITH, "/a.pdf", "https://example.com/files/a.pdf", True),
        (RuleMatchType.QUERY_PARAMETER_EXISTS, "tag", "https://example.com/?tag=", True),
        (
            RuleMatchType.QUERY_PARAMETER_EQUALS,
            "tag=blue",
            "https://example.com/?tag=red&tag=blue",
            True,
        ),
        (RuleMatchType.EXACT_PATH, "/Products/", "https://example.com/products/", False),
    ),
)
def test_all_initial_match_types_have_exact_bounded_semantics(
    match_type: RuleMatchType,
    match_value: str,
    url: str,
    expected: bool,  # noqa: FBT001
) -> None:
    assert rule_matches(_rule(match_type, match_value), url) is expected


@pytest.mark.parametrize(
    ("action", "layers"),
    (
        (RuleAction.EXCLUDE_FROM_DISCOVERY, (DecisionLayer.DISCOVERY,)),
        (RuleAction.EXCLUDE_FROM_METADATA, (DecisionLayer.DISCOVERY, DecisionLayer.METADATA)),
        (RuleAction.EXCLUDE_FROM_SITEMAP, (DecisionLayer.DISCOVERY, DecisionLayer.SITEMAP)),
        (RuleAction.MARK_FOR_REVIEW, (DecisionLayer.DISCOVERY,)),
        (RuleAction.STRIP_QUERY_PARAMETER, (DecisionLayer.NORMALIZATION,)),
    ),
)
def test_all_initial_actions_map_only_to_their_decision_layers(
    action: RuleAction, layers: tuple[DecisionLayer, ...]
) -> None:
    match_type = (
        RuleMatchType.QUERY_PARAMETER_EXISTS
        if action is RuleAction.STRIP_QUERY_PARAMETER
        else RuleMatchType.PATH_STARTS_WITH
    )
    match_value = "campaign" if action is RuleAction.STRIP_QUERY_PARAMETER else "/shop/"
    assert decision_layers(_rule(match_type, match_value, action)) == layers


def test_normalization_preserves_original_repeats_and_empty_values_but_strips_accepted_names() -> (
    None
):
    value = normalize_governed_url(
        "HTTPS://Exämple.com:443/a/%7e?q=2&utm_source=&q=1&utm_source=x#fragment",
        strip_parameters=("utm_source",),
    )
    assert value["original_url"].endswith("#fragment")
    assert value["syntax_normalized_url"] == (
        "https://xn--exmple-cua.com/a/~?q=1&q=2&utm_source=&utm_source=x"
    )
    assert value["normalized_url"] == "https://xn--exmple-cua.com/a/~?q=1&q=2"
    assert value["removed_parameters"] == ["utm_source", "utm_source"]
    assert value["fragment_removed"] is True


def test_path_case_trailing_slash_and_reserved_percent_encoding_remain_significant() -> None:
    insensitive = _rule(
        RuleMatchType.EXACT_PATH,
        "/Products/",
        case_sensitive=False,
    )
    assert rule_matches(insensitive, "https://example.com/products/")
    assert not rule_matches(insensitive, "https://example.com/products")
    normalized = normalize_governed_url("https://example.com/a%2fb/%41")
    assert normalized["normalized_url"] == "https://example.com/a%2Fb/A"


def test_tracking_acceptance_exceptions_and_collisions_are_explicit_and_network_free() -> None:
    result = evaluate_rule_set(
        (),
        (
            "https://example.com/a?utm_source=one&id=2",
            "https://example.com/a?id=2&utm_source=two",
        ),
        tracking_parameters=TRACKING_PARAMETERS,
        tracking_accepted=True,
    )
    assert result["network_access"] is False
    assert result["discoveries_created"] is False
    assert all(item["normalized_url"] == "https://example.com/a?id=2" for item in result["results"])
    assert all(item["collision_group"] is not None for item in result["results"])

    excepted = evaluate_rule_set(
        (),
        ("https://example.com/a?utm_source=one",),
        tracking_parameters=TRACKING_PARAMETERS,
        tracking_accepted=True,
        parameter_exceptions=("utm_source",),
    )
    assert excepted["results"][0]["normalized_url"].endswith("utm_source=one")


def test_wordpress_preset_is_versioned_visible_optional_and_contract_exact() -> None:
    presets = builtin_presets()
    assert [item.preset_id for item in presets] == list(PlatformPresetId)
    wordpress = preset_for("wordpress", "wordpress-1")
    by_id = {item.rule_id: item for item in wordpress.rules}
    assert by_id["wordpress.wp_json"].enabled is False
    assert by_id["wordpress.pagination.sitemap_review"].scope is RuleScope.SITEMAP
    assert not any("category" in item.rule_id for item in wordpress.rules)
    assert wordpress.tracking_parameters == TRACKING_PARAMETERS
    for family in ("tag", "author", "date"):
        assert by_id[f"wordpress.{family}.metadata"].enabled
        assert by_id[f"wordpress.{family}.sitemap"].enabled


def test_explicit_inherited_override_resolves_without_last_rule_wins() -> None:
    inherited = _rule(
        RuleMatchType.PATH_STARTS_WITH,
        "/shop/",
        RuleAction.EXCLUDE_FROM_DISCOVERY,
        rule_id="global.shop",
        source=RuleSource.GLOBAL,
    )
    replacement = _rule(
        RuleMatchType.PATH_STARTS_WITH,
        "/shop/",
        RuleAction.MARK_FOR_REVIEW,
        rule_id="audit.shop",
        overrides=("global.shop",),
    )
    effective, disabled, warnings = resolve_effective_rules(
        (inherited,), per_audit_rules=(replacement,)
    )
    assert not disabled and not warnings
    result = evaluate_rule_set(effective, ("https://example.com/shop/item",))
    decision = result["results"][0]["decisions"]["discovery"]
    assert decision["outcome"] == "mark_review_before_enqueue"
    assert decision["primary_rule"] == "audit.shop"
    assert decision["overridden_rules"] == ["global.shop"]


def test_cross_source_overlap_is_visible_and_resolved_by_precedence() -> None:
    global_rule = _rule(
        RuleMatchType.PATH_STARTS_WITH,
        "/shop/",
        RuleAction.EXCLUDE_FROM_DISCOVERY,
        rule_id="global.shop",
        source=RuleSource.GLOBAL,
    )
    audit_rule = _rule(
        RuleMatchType.PATH_STARTS_WITH,
        "/shop/",
        RuleAction.MARK_FOR_REVIEW,
        rule_id="audit.shop",
    )
    result = evaluate_rule_set((global_rule, audit_rule), ("https://example.com/shop/item",))
    decision = result["results"][0]["decisions"]["discovery"]
    assert decision["conflict"] is True
    assert decision["outcome"] == "mark_review_before_enqueue"
    assert decision["primary_rule"] == "audit.shop"


def test_same_source_tie_breaking_is_stable_and_broad_rules_warn() -> None:
    first = _rule(RuleMatchType.PATH_CONTAINS, "/a", rule_id="audit.a")
    second = _rule(RuleMatchType.PATH_CONTAINS, "/a", rule_id="audit.b")
    result = evaluate_rule_set((second, first), ("https://example.com/x/a/y",))
    assert result["results"][0]["primary_rule"] == "audit.a"
    assert (
        broad_rule_warning(_rule(RuleMatchType.PATH_CONTAINS, "/", rule_id="audit.broad"))
        == "site_audit_rule_broad_path_contains"
    )


def test_rule_field_bounds_fail_closed() -> None:
    with pytest.raises(SiteAuditSettingsError, match="site_audit_rule_name_invalid"):
        rule_from_mapping(
            {
                **_rule(RuleMatchType.EXACT_PATH, "/a").to_dict(),
                "name": "x" * 129,
            },
            source=RuleSource.PER_AUDIT,
            created_by="tester",
            now=_NOW,
        )


def test_unknown_same_source_and_per_audit_disable_targets_fail_closed() -> None:
    inherited = _rule(
        RuleMatchType.EXACT_PATH,
        "/a",
        rule_id="global.a",
        source=RuleSource.GLOBAL,
    )
    with pytest.raises(SiteAuditSettingsError, match="site_audit_disabled_rule_invalid"):
        resolve_effective_rules((inherited,), disabled_rule_ids=("missing",))
    audit = replace(inherited, rule_id="audit.a", source=RuleSource.PER_AUDIT)
    with pytest.raises(SiteAuditSettingsError, match="site_audit_disabled_rule_invalid"):
        resolve_effective_rules((), per_audit_rules=(audit,), disabled_rule_ids=("audit.a",))


def test_rule_testing_rejects_excessive_and_malformed_samples() -> None:
    with pytest.raises(SiteAuditSettingsError, match="site_audit_rule_test_limit"):
        evaluate_rule_set(
            (), tuple("https://example.com" for _ in range(MAXIMUM_RULE_TEST_URLS + 1))
        )
    with pytest.raises(SiteAuditSettingsError, match="site_audit_url_invalid"):
        evaluate_rule_set((), ("file:///private",))
