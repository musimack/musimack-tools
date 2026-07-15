"""Deterministic tests for sitemap eligibility recommendations and projections."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from typing import TYPE_CHECKING

import pytest

from musimack_tools.crawl.html import HtmlMetadataParser
from musimack_tools.crawl.indexability import IndexabilityEvidenceParser
from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import create_scope_policy
from musimack_tools.domain.crawl import (
    CrawlConfigurationSnapshot,
    CrawlCounters,
    CrawlExclusionRule,
    CrawlResult,
    CrawlState,
    ExclusionRuleType,
    FrontierState,
    UrlCrawlOutcome,
    UrlCrawlRecord,
)
from musimack_tools.domain.fetching import (
    FetchFailureCode,
    FetchOutcome,
    FetchResult,
    RedirectHop,
    ResponseHeaders,
)
from musimack_tools.domain.html import HtmlWarning, HtmlWarningCode, WarningSeverity
from musimack_tools.domain.robots import (
    CrawlPermissionDecision,
    CrawlPermissionReason,
    RobotsFetchOutcome,
    RobotsParseOutcome,
)
from musimack_tools.domain.sitemap import (
    SITEMAP_RULE_SET_VERSION,
    RecommendationDeterminacy,
    RecommendationPolicy,
    RecommendationState,
    SitemapReasonCode,
    SitemapRecommendation,
)
from musimack_tools.recommendation.sitemap import SitemapRecommendationEngine

if TYPE_CHECKING:
    from musimack_tools.domain.urls import CrawlScopePolicy

_SEED = "https://example.test/"
_HTML = (
    "<html><head><title>A useful page title for sitemap testing</title>"
    '<meta name="description" content="A useful page description retained as deterministic '
    'metadata evidence for sitemap recommendation testing."></head><body></body></html>'
)


def _permission(
    *,
    allowed: bool = True,
    temporary_unavailability: bool = False,
) -> CrawlPermissionDecision:
    return CrawlPermissionDecision(
        evaluated_url=_SEED,
        origin="https://example.test",
        robots_url="https://example.test/robots.txt",
        fetch_outcome=RobotsFetchOutcome.NO_POLICY,
        parse_outcome=RobotsParseOutcome.NOT_APPLICABLE,
        selected_group_index=None,
        matched_rule=None,
        allowed=allowed,
        reason_code=(
            CrawlPermissionReason.ALLOWED_NO_ROBOTS_FILE
            if allowed
            else CrawlPermissionReason.DENIED_ROBOTS_TEMPORARILY_UNAVAILABLE
            if temporary_unavailability
            else CrawlPermissionReason.DENIED_BY_DISALLOW_RULE
        ),
        explanation="Synthetic robots decision",
        cache_hit=False,
        warnings=(),
        temporary_unavailability=temporary_unavailability,
        newly_fetched_bytes=0,
        evaluation_duration_seconds=0.0,
    )


def _record(  # noqa: PLR0913 - fixture exposes independent accepted evidence dimensions.
    url: str = _SEED,
    *,
    final_url: str | None = None,
    status: int | None = 200,
    content_type: str | None = "text/html; charset=utf-8",
    body: str | None = _HTML,
    failure: FetchFailureCode | None = None,
    robots_allowed: bool = True,
    robots_available: bool = True,
    x_robots: tuple[str, ...] = (),
    redirected: bool = False,
    parse_available: bool = True,
    discovery_order: int = 0,
) -> UrlCrawlRecord:
    destination = final_url or url
    body_bytes = body.encode() if body is not None else None
    outcome = FetchOutcome.FAILURE if failure is not None else FetchOutcome.SUCCESS
    redirect_chain = (
        (
            RedirectHop(
                source_url=url,
                status_code=301,
                raw_location=destination,
                destination_url=destination,
                allowed=True,
                failure_code=None,
                explanation="Synthetic redirect",
            ),
        )
        if redirected
        else ()
    )
    fetch = FetchResult(
        requested_url=url,
        final_url=destination,
        outcome=outcome,
        status_code=status,
        headers=ResponseHeaders(content_type=content_type, x_robots_tag=x_robots),
        content_type=content_type,
        declared_content_length=len(body_bytes) if body_bytes is not None else None,
        actual_bytes_read=len(body_bytes) if body_bytes is not None else 0,
        body_truncated=failure is FetchFailureCode.RESPONSE_TOO_LARGE,
        redirect_chain=redirect_chain,
        request_duration_seconds=0.01,
        dns_evidence=(),
        failure_code=failure,
        failure_explanation="Synthetic failure" if failure is not None else None,
        body=body_bytes,
    )
    parse = (
        HtmlMetadataParser().parse(fetch)
        if parse_available and failure is None and body is not None
        else None
    )
    x_evidence = IndexabilityEvidenceParser().parse_x_robots_tag(x_robots)
    combined = (
        IndexabilityEvidenceParser().combine(parse.meta_robots, x_evidence)
        if parse is not None
        else None
    )
    return UrlCrawlRecord(
        requested_url=url,
        first_discovered_value=url,
        first_referrer=None,
        referring_urls=(),
        discovery_depth=0,
        best_known_depth=0,
        discovery_order=discovery_order,
        frontier_state=FrontierState.COMPLETED,
        outcome=(
            UrlCrawlOutcome.FETCH_FAILED
            if failure is not None
            else UrlCrawlOutcome.PARSED
            if parse is not None
            else UrlCrawlOutcome.FETCHED
        ),
        fetch_result=fetch,
        parse_result=parse,
        final_fetched_url=destination,
        discovered_link_count=0,
        admitted_link_count=0,
        rejected_link_count=0,
        skip_reason=None,
        started_at_seconds=0.0,
        ended_at_seconds=0.01,
        accepted_response_bytes=len(body_bytes) if body_bytes is not None else 0,
        robots_permission=_permission(allowed=robots_allowed) if robots_available else None,
        x_robots_tag=x_evidence,
        indexability_evidence=combined,
    )


def _not_fetched(
    *,
    robots_allowed: bool = False,
    temporary_unavailability: bool = False,
) -> UrlCrawlRecord:
    record = _record()
    return replace(
        record,
        outcome=UrlCrawlOutcome.ROBOTS_DENIED,
        fetch_result=None,
        parse_result=None,
        final_fetched_url=None,
        robots_permission=_permission(
            allowed=robots_allowed,
            temporary_unavailability=temporary_unavailability,
        ),
        x_robots_tag=None,
        indexability_evidence=None,
    )


def _scope() -> CrawlScopePolicy:
    return create_scope_policy(normalize_url(_SEED))


def _recommend(
    record: UrlCrawlRecord,
    policy: RecommendationPolicy | None = None,
) -> SitemapRecommendation:
    return SitemapRecommendationEngine(policy).recommend(record, _scope())


def _crawl(
    records: tuple[UrlCrawlRecord, ...],
    rules: tuple[CrawlExclusionRule, ...] = (),
) -> CrawlResult:
    return CrawlResult(
        seed_url=_SEED,
        scope_policy=_scope(),
        started_at_seconds=0.0,
        ended_at_seconds=1.0,
        duration_seconds=1.0,
        state=CrawlState.COMPLETED,
        url_records=records,
        discoveries=(),
        counters=CrawlCounters(),
        limit_events=(),
        errors=(),
        cancellation=None,
        total_accepted_bytes=0,
        maximum_observed_queue_size=1,
        maximum_active_worker_count=1,
        configuration=CrawlConfigurationSnapshot(
            maximum_unique_urls=100,
            maximum_depth=5,
            maximum_duration_seconds=60,
            maximum_total_fetched_bytes=1_000_000,
            maximum_concurrent_fetches=2,
            maximum_queued_urls=100,
            minimum_per_origin_delay_seconds=0,
            query_urls_allowed=True,
            exclusion_rules=rules,
        ),
    )


@pytest.mark.parametrize(
    "body",
    [
        _HTML,
        _HTML.replace("</head>", '<link rel="canonical" href="/"></head>'),
        _HTML.replace("<title>A useful page title for sitemap testing</title>", ""),
        _HTML.replace(
            '<meta name="description" content="A useful page description retained as '
            'deterministic metadata evidence for sitemap recommendation testing.">',
            "",
        ),
        _HTML.replace("</head>", '<meta name="robots" content="nofollow"></head>'),
        _HTML.replace("</head>", '<meta name="robots" content="noarchive"></head>'),
    ],
)
def test_qualifying_html_pages_are_included_despite_metadata_or_noneligibility_warnings(
    body: str,
) -> None:
    result = _recommend(_record(body=body))

    assert result.state is RecommendationState.INCLUDE
    assert result.primary_reason is SitemapReasonCode.ELIGIBLE_HTML_PAGE


@pytest.mark.parametrize("content_type", [None, "application/octet-stream"])
def test_structurally_sniffed_html_is_included_by_default(content_type: str | None) -> None:
    result = _recommend(_record(content_type=content_type))

    assert result.state is RecommendationState.INCLUDE
    assert result.content_type == "text/html"


def test_metadata_warnings_remain_separate_from_state() -> None:
    record = _record(body="<html><head></head><body></body></html>")
    result = _recommend(record)

    assert result.state is RecommendationState.INCLUDE
    assert {item.code for item in result.metadata_warnings} >= {
        "missing_title",
        "missing_meta_description",
    }
    assert result.review_reasons == ()


def test_included_recommendation_is_determinate() -> None:
    result = _recommend(_record())

    assert result.state is RecommendationState.INCLUDE
    assert result.determinacy is RecommendationDeterminacy.DETERMINATE


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (FetchFailureCode.CONNECT_TIMEOUT, SitemapReasonCode.FETCH_FAILED),
        (FetchFailureCode.READ_TIMEOUT, SitemapReasonCode.FETCH_FAILED),
        (FetchFailureCode.RESPONSE_TOO_LARGE, SitemapReasonCode.RESPONSE_TOO_LARGE),
        (FetchFailureCode.REDIRECT_LOOP, SitemapReasonCode.REDIRECT_FAILED),
        (FetchFailureCode.REDIRECT_LIMIT_EXCEEDED, SitemapReasonCode.REDIRECT_FAILED),
        (FetchFailureCode.REDIRECT_SCOPE_DENIED, SitemapReasonCode.REDIRECT_FAILED),
        (FetchFailureCode.REDIRECT_UNSAFE_DESTINATION, SitemapReasonCode.REDIRECT_FAILED),
    ],
)
def test_fetch_failures_are_hard_exclusions_and_preserve_original_code(
    failure: FetchFailureCode,
    reason: SitemapReasonCode,
) -> None:
    result = _recommend(_record(failure=failure))

    assert result.state is RecommendationState.EXCLUDE
    assert reason in result.hard_exclusion_reasons
    assert result.fetch_failure_code == failure.value


@pytest.mark.parametrize("status", [301, 302, 404, 500])
def test_non_200_final_status_is_excluded(status: int) -> None:
    result = _recommend(_record(status=status))

    assert result.state is RecommendationState.EXCLUDE
    assert SitemapReasonCode.NON_200_STATUS in result.hard_exclusion_reasons
    assert SitemapReasonCode.NON_HTML_CONTENT not in result.hard_exclusion_reasons


def test_missing_http_status_is_excluded() -> None:
    result = _recommend(_record(status=None))

    assert result.state is RecommendationState.EXCLUDE
    assert SitemapReasonCode.MISSING_HTTP_STATUS in result.hard_exclusion_reasons


@pytest.mark.parametrize(
    "content_type",
    ["application/pdf", "application/json", "image/png", "text/plain", "text/css"],
)
def test_non_html_content_is_excluded(content_type: str) -> None:
    result = _recommend(_record(content_type=content_type))

    assert result.state is RecommendationState.EXCLUDE
    assert SitemapReasonCode.NON_HTML_CONTENT in result.hard_exclusion_reasons


def test_robots_denied_is_distinct_from_noindex_and_prevents_eligibility() -> None:
    result = _recommend(_not_fetched())

    assert result.state is RecommendationState.EXCLUDE
    assert result.primary_reason is SitemapReasonCode.ROBOTS_DENIED
    assert SitemapReasonCode.GENERIC_NOINDEX not in result.hard_exclusion_reasons


def test_robots_temporary_unavailability_excludes_unfetched_page() -> None:
    result = _recommend(_not_fetched(temporary_unavailability=True))

    assert result.state is RecommendationState.EXCLUDE
    assert result.primary_reason is SitemapReasonCode.ROBOTS_DENIED
    assert result.robots.reason_code == "denied_robots_temporarily_unavailable"


@pytest.mark.parametrize(
    ("body", "headers"),
    [
        (_HTML.replace("</head>", '<meta name="robots" content="noindex"></head>'), ()),
        (_HTML, ("noindex",)),
        (
            _HTML.replace("</head>", '<meta name="robots" content="index"></head>'),
            ("noindex",),
        ),
        (
            _HTML.replace("</head>", '<meta name="robots" content="noindex"></head>'),
            ("googlebot: index",),
        ),
    ],
)
def test_trustworthy_generic_noindex_is_excluded(body: str, headers: tuple[str, ...]) -> None:
    result = _recommend(_record(body=body, x_robots=headers))

    assert result.state is RecommendationState.EXCLUDE
    assert SitemapReasonCode.GENERIC_NOINDEX in result.hard_exclusion_reasons


def test_crawler_specific_noindex_alone_is_warning_not_exclusion_by_default() -> None:
    result = _recommend(_record(x_robots=("googlebot: noindex",)))

    assert result.state is RecommendationState.INCLUDE
    assert any(item.code == "crawler_specific_noindex" for item in result.warnings)


def test_crawler_specific_noindex_can_be_configured_for_review() -> None:
    policy = RecommendationPolicy(crawler_specific_noindex_requires_review=True)
    result = _recommend(_record(x_robots=("googlebot: noindex",)), policy)

    assert result.state is RecommendationState.REVIEW
    assert result.primary_reason is SitemapReasonCode.CRAWLER_SPECIFIC_NOINDEX


@pytest.mark.parametrize(
    ("canonical", "reason"),
    [
        ("/other", SitemapReasonCode.CANONICAL_POINTS_ELSEWHERE),
        ("/?variant=1", SitemapReasonCode.CANONICAL_POINTS_ELSEWHERE),
        ("/page/", SitemapReasonCode.CANONICAL_POINTS_ELSEWHERE),
        ("https://other.test/", SitemapReasonCode.CROSS_HOST_CANONICAL),
        ("http://example.test/", SitemapReasonCode.CROSS_ORIGIN_CANONICAL),
        ("https://example.test:8443/", SitemapReasonCode.CROSS_ORIGIN_CANONICAL),
    ],
)
def test_canonical_elsewhere_is_excluded(canonical: str, reason: SitemapReasonCode) -> None:
    body = _HTML.replace("</head>", f'<link rel="canonical" href="{canonical}"></head>')
    result = _recommend(_record(body=body))

    assert result.state is RecommendationState.EXCLUDE
    assert reason in result.hard_exclusion_reasons


@pytest.mark.parametrize("canonical", ["/", "https://example.test/"])
def test_relative_or_absolute_self_canonical_is_included(canonical: str) -> None:
    body = _HTML.replace("</head>", f'<link rel="canonical" href="{canonical}"></head>')
    result = _recommend(_record(body=body))

    assert result.state is RecommendationState.INCLUDE


def test_multiple_identical_canonicals_are_included() -> None:
    body = _HTML.replace(
        "</head>",
        '<link rel="canonical" href="/"><link rel="canonical" href="https://example.test/"></head>',
    )
    result = _recommend(_record(body=body))

    assert result.state is RecommendationState.INCLUDE
    assert result.canonical.conflicting is False


def test_conflicting_valid_canonicals_require_review() -> None:
    body = _HTML.replace(
        "</head>",
        '<link rel="canonical" href="/a"><link rel="canonical" href="/b"></head>',
    )
    result = _recommend(_record(body=body))

    assert result.state is RecommendationState.REVIEW
    assert result.primary_reason is SitemapReasonCode.CONFLICTING_CANONICALS


def test_one_invalid_canonical_without_valid_candidate_requires_review() -> None:
    body = _HTML.replace("</head>", '<link rel="canonical" href="http://"></head>')
    result = _recommend(_record(body=body))

    assert result.state is RecommendationState.REVIEW
    assert result.primary_reason is SitemapReasonCode.INVALID_CANONICAL


def test_multiple_invalid_canonicals_without_valid_candidate_require_review() -> None:
    body = _HTML.replace(
        "</head>",
        '<link rel="canonical" href="http://"><link rel="canonical" href="%"></head>',
    )
    result = _recommend(_record(body=body))

    assert result.state is RecommendationState.REVIEW
    assert result.primary_reason is SitemapReasonCode.INVALID_CANONICAL
    assert result.canonical.invalid_observation_count == 2
    assert SitemapReasonCode.INVALID_CANONICAL not in result.hard_exclusion_reasons


def test_invalid_plus_self_canonical_includes_with_warning() -> None:
    body = _HTML.replace(
        "</head>",
        '<link rel="canonical" href="http://"><link rel="canonical" href="/"></head>',
    )
    result = _recommend(_record(body=body))

    assert result.state is RecommendationState.INCLUDE
    assert any(item.code == "invalid_canonical" for item in result.warnings)


def test_invalid_plus_canonical_elsewhere_excludes() -> None:
    body = _HTML.replace(
        "</head>",
        '<link rel="canonical" href="http://"><link rel="canonical" href="/other"></head>',
    )
    result = _recommend(_record(body=body))

    assert result.state is RecommendationState.EXCLUDE
    assert result.primary_reason is SitemapReasonCode.CANONICAL_POINTS_ELSEWHERE


def test_missing_canonical_is_included_with_warning_by_default() -> None:
    result = _recommend(_record())

    assert result.state is RecommendationState.INCLUDE
    assert any(item.code == "missing_canonical" for item in result.warnings)


def test_missing_canonical_policy_can_require_review() -> None:
    result = _recommend(_record(), RecommendationPolicy(missing_canonical_requires_review=True))

    assert result.state is RecommendationState.REVIEW
    assert result.primary_reason is SitemapReasonCode.MISSING_CANONICAL


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirect_source_is_excluded_regardless_of_permanence(status: int) -> None:
    target = "https://example.test/final"
    record = _record(final_url=target, redirected=True)
    assert record.fetch_result is not None
    hop = replace(record.fetch_result.redirect_chain[0], status_code=status)
    record = replace(record, fetch_result=replace(record.fetch_result, redirect_chain=(hop,)))
    result = _recommend(record)

    assert result.state is RecommendationState.EXCLUDE
    assert SitemapReasonCode.REDIRECT_SOURCE in result.hard_exclusion_reasons


def test_redirect_target_with_own_record_is_independently_included() -> None:
    target = "https://example.test/final"
    source = _record(final_url=target, redirected=True, discovery_order=0)
    final = _record(url=target, discovery_order=1)
    projection = SitemapRecommendationEngine().project(_crawl((source, final)))

    assert [item.state for item in projection.recommendations] == [
        RecommendationState.EXCLUDE,
        RecommendationState.INCLUDE,
    ]
    assert projection.recommendations[0].redirect.target_independently_evaluated is True


def test_redirect_target_without_own_record_does_not_create_a_recommendation() -> None:
    target = "https://example.test/final"
    projection = SitemapRecommendationEngine().project(
        _crawl((_record(final_url=target, redirected=True),))
    )

    assert len(projection.recommendations) == 1
    source = projection.recommendations[0]
    assert source.state is RecommendationState.EXCLUDE
    assert source.primary_reason is SitemapReasonCode.REDIRECT_SOURCE
    assert source.redirect.target_independently_evaluated is False
    assert any(
        item.code == "redirect_target_not_independently_evaluated" for item in source.warnings
    )


@pytest.mark.parametrize(
    ("url", "rule"),
    [
        (
            "https://example.test/private",
            CrawlExclusionRule(ExclusionRuleType.EXACT_PATH, "/private"),
        ),
        (
            "https://example.test/admin/users",
            CrawlExclusionRule(ExclusionRuleType.PATH_PREFIX, "/admin"),
        ),
        (
            "https://example.test/page?session=abc",
            CrawlExclusionRule(ExclusionRuleType.QUERY_PARAMETER, "session"),
        ),
    ],
)
def test_configured_exclusion_rules_are_applied(url: str, rule: CrawlExclusionRule) -> None:
    projection = SitemapRecommendationEngine().project(_crawl((_record(url=url),), (rule,)))
    result = projection.recommendations[0]

    assert result.state is RecommendationState.EXCLUDE
    assert result.primary_reason is SitemapReasonCode.CONFIGURED_URL_EXCLUSION
    assert len(result.configured_exclusions) == 1


def test_multiple_configured_exclusion_matches_are_retained() -> None:
    rules = (
        CrawlExclusionRule(ExclusionRuleType.EXACT_PATH, "/private"),
        CrawlExclusionRule(ExclusionRuleType.PATH_PREFIX, "/"),
    )
    projection = SitemapRecommendationEngine().project(
        _crawl((_record(url="https://example.test/private"),), rules)
    )

    assert len(projection.recommendations[0].configured_exclusions) == 2


def test_nonmatching_configured_rule_does_not_change_inclusion() -> None:
    rules = (CrawlExclusionRule(ExclusionRuleType.EXACT_PATH, "/other"),)
    projection = SitemapRecommendationEngine().project(_crawl((_record(),), rules))

    assert projection.recommendations[0].state is RecommendationState.INCLUDE


def test_missing_parse_and_indexability_evidence_is_indeterminate_when_no_exclusion_applies() -> (
    None
):
    result = _recommend(_record(parse_available=False))

    assert result.state is RecommendationState.INDETERMINATE
    assert result.determinacy is RecommendationDeterminacy.BLOCKED_MISSING_EVIDENCE
    assert result.primary_reason is SitemapReasonCode.MISSING_REQUIRED_EVIDENCE


def test_missing_robots_permission_is_indeterminate_when_page_otherwise_qualifies() -> None:
    result = _recommend(_record(robots_available=False))

    assert result.state is RecommendationState.INDETERMINATE
    assert result.primary_reason is SitemapReasonCode.MISSING_REQUIRED_EVIDENCE
    assert result.determinacy is RecommendationDeterminacy.BLOCKED_MISSING_EVIDENCE


def test_contradictory_content_type_and_parse_evidence_is_indeterminate() -> None:
    html_record = _record()
    assert html_record.fetch_result is not None
    contradictory = replace(
        html_record,
        fetch_result=replace(
            html_record.fetch_result,
            content_type="application/json",
            headers=ResponseHeaders(content_type="application/json"),
        ),
    )
    result = _recommend(contradictory)

    assert result.state is RecommendationState.INDETERMINATE
    assert result.primary_reason is SitemapReasonCode.AMBIGUOUS_CONTENT_TYPE
    assert result.determinacy is RecommendationDeterminacy.BLOCKED_CONFLICTING_EVIDENCE


def test_hard_exclusion_precedes_missing_evidence_and_all_reasons_are_retained() -> None:
    result = _recommend(_record(status=404, parse_available=False))

    assert result.state is RecommendationState.EXCLUDE
    assert result.primary_reason is SitemapReasonCode.NON_200_STATUS
    assert result.determinacy is RecommendationDeterminacy.DETERMINATE
    assert SitemapReasonCode.MISSING_REQUIRED_EVIDENCE in {
        item.reason_code for item in result.rule_results
    }


def test_parser_recovery_is_review_when_page_otherwise_qualifies() -> None:
    record = _record()
    warning = HtmlWarning(
        HtmlWarningCode.PARSER_RECOVERY_USED,
        "Synthetic severe parser recovery",
        WarningSeverity.WARNING,
    )
    assert record.parse_result is not None
    parse = replace(record.parse_result, warnings=(*record.parse_result.warnings, warning))
    result = _recommend(replace(record, parse_result=parse))

    assert result.state is RecommendationState.REVIEW
    assert result.primary_reason is SitemapReasonCode.SEVERE_PARSER_RECOVERY
    assert result.determinacy is RecommendationDeterminacy.DETERMINATE


def test_projection_preserves_order_suppresses_duplicates_and_counts_states() -> None:
    included = _record(discovery_order=0)
    duplicate = replace(included, discovery_order=1)
    pdf = _record(
        url="https://example.test/file.pdf",
        content_type="application/pdf",
        discovery_order=2,
    )
    denied = replace(
        _not_fetched(), requested_url="https://example.test/private", discovery_order=3
    )
    projection = SitemapRecommendationEngine().project(_crawl((included, duplicate, pdf, denied)))

    assert [item.evaluated_url for item in projection.recommendations] == [
        _SEED,
        "https://example.test/file.pdf",
        "https://example.test/private",
    ]
    assert projection.duplicate_suppression_count == 1
    assert projection.included_url_count == 1
    assert projection.excluded_url_count == 2
    assert projection.non_html_count == 1
    assert projection.robots_denial_count == 1


def test_projection_counters_and_configuration_are_immutable_and_deterministic() -> None:
    noindex = _record(
        url="https://example.test/noindex",
        body=_HTML.replace("</head>", '<meta name="robots" content="noindex"></head>'),
    )
    canonical = _record(
        url="https://example.test/canonical",
        body=_HTML.replace("</head>", '<link rel="canonical" href="/other"></head>'),
        discovery_order=1,
    )
    non_200 = _record(url="https://example.test/missing", status=404, discovery_order=2)
    projection = SitemapRecommendationEngine().project(_crawl((noindex, canonical, non_200)))

    assert projection.noindex_exclusion_count == 1
    assert projection.canonical_exclusion_count == 1
    assert projection.non_200_count == 1
    assert SITEMAP_RULE_SET_VERSION == "sitemap-eligibility-v1"
    assert projection.rule_set_version == SITEMAP_RULE_SET_VERSION
    assert projection.configuration.rule_set_version == projection.rule_set_version
    assert tuple(item.reason for item in projection.counts_by_primary_reason)
    with pytest.raises(FrozenInstanceError):
        projection.included_url_count = 99  # type: ignore[misc]


def test_metadata_warning_counts_are_separate_from_reason_counts() -> None:
    record = _record(body="<html><head></head><body></body></html>")
    projection = SitemapRecommendationEngine().project(_crawl((record,)))

    counts = {item.warning_code: item.count for item in projection.metadata_warning_counts}
    assert counts["missing_title"] == 1
    assert counts["missing_meta_description"] == 1
    assert projection.recommendations[0].state is RecommendationState.INCLUDE


def test_outside_scope_is_excluded_before_other_rules() -> None:
    result = SitemapRecommendationEngine().recommend(
        _record(url="https://other.test/"),
        _scope(),
    )

    assert result.state is RecommendationState.EXCLUDE
    assert result.primary_reason is SitemapReasonCode.OUTSIDE_SCOPE


def test_unsupported_url_scheme_is_excluded() -> None:
    result = _recommend(replace(_record(), requested_url="ftp://example.test/file"))

    assert result.state is RecommendationState.EXCLUDE
    assert result.primary_reason is SitemapReasonCode.UNSUPPORTED_SCHEME


def test_malformed_url_is_excluded() -> None:
    result = _recommend(replace(_record(), requested_url="not a URL"))

    assert result.state is RecommendationState.EXCLUDE
    assert result.primary_reason is SitemapReasonCode.INVALID_URL


def test_disallowed_effective_port_is_excluded() -> None:
    result = _recommend(replace(_record(), requested_url="https://example.test:8443/"))

    assert result.state is RecommendationState.EXCLUDE
    assert result.primary_reason is SitemapReasonCode.DISALLOWED_PORT


def test_multiple_redirect_sources_do_not_synthesize_missing_target_recommendations() -> None:
    target = "https://example.test/final"
    first = _record(
        url="https://example.test/old-a",
        final_url=target,
        redirected=True,
        discovery_order=0,
    )
    second = _record(
        url="https://example.test/old-b",
        final_url=target,
        redirected=True,
        discovery_order=1,
    )
    projection = SitemapRecommendationEngine().project(_crawl((first, second)))

    assert len(projection.recommendations) == 2
    assert all(item.evaluated_url != target for item in projection.recommendations)
    assert all(item.state is RecommendationState.EXCLUDE for item in projection.recommendations)
    assert all(
        item.redirect.target_independently_evaluated is False for item in projection.recommendations
    )
    assert projection.redirect_source_count == 2


@pytest.mark.parametrize(
    ("path", "matches"),
    [
        ("/blog", True),
        ("/blog/", True),
        ("/blog/post", True),
        ("/blog/post/example", True),
        ("/blogging", False),
        ("/blogs", False),
        ("/blog-old", False),
    ],
)
def test_path_prefix_exclusions_are_segment_aware(path: str, *, matches: bool) -> None:
    rule = CrawlExclusionRule(ExclusionRuleType.PATH_PREFIX, "/blog")
    projection = SitemapRecommendationEngine().project(
        _crawl((_record(url=f"https://example.test{path}"),), (rule,))
    )

    expected = RecommendationState.EXCLUDE if matches else RecommendationState.INCLUDE
    assert projection.recommendations[0].state is expected


@pytest.mark.parametrize("path", ["/blog", "/blog/", "/blog/post"])
def test_trailing_slash_path_prefix_configuration_normalizes_to_segment(path: str) -> None:
    rule = CrawlExclusionRule(ExclusionRuleType.PATH_PREFIX, "/blog/")
    projection = SitemapRecommendationEngine().project(
        _crawl((_record(url=f"https://example.test{path}"),), (rule,))
    )

    assert projection.recommendations[0].state is RecommendationState.EXCLUDE


def test_root_path_prefix_matches_every_absolute_path() -> None:
    rule = CrawlExclusionRule(ExclusionRuleType.PATH_PREFIX, "/")
    projection = SitemapRecommendationEngine().project(
        _crawl((_record(url="https://example.test/anything/here"),), (rule,))
    )

    assert projection.recommendations[0].state is RecommendationState.EXCLUDE


def test_empty_path_prefix_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        CrawlExclusionRule(ExclusionRuleType.PATH_PREFIX, "")


def test_query_string_does_not_change_path_prefix_matching() -> None:
    rule = CrawlExclusionRule(ExclusionRuleType.PATH_PREFIX, "/blog")
    projection = SitemapRecommendationEngine().project(
        _crawl((_record(url="https://example.test/blog?category=seo"),), (rule,))
    )

    assert projection.recommendations[0].state is RecommendationState.EXCLUDE


def test_rule_results_retain_explicit_precedence_order() -> None:
    result = _recommend(_record())

    assert [item.rule_id for item in result.rule_results[:9]] == [
        "01_url_and_scope",
        "03_robots_permission",
        "04_fetch_outcome",
        "05_redirect_source",
        "06_http_status",
        "07_html_content",
        "08_generic_indexability",
        "09_configured_exclusions",
        "11_canonical_quality",
    ]
