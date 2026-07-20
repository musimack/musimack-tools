"""CSA-04 stage graph, lifecycle, priority, and artifact contracts."""

from __future__ import annotations

import pytest

from musimack_tools.domain.site_audit_orchestration import (
    ARTIFACT_FILENAMES,
    CORE_REQUIRED_MODULES,
    OPTIONAL_MODULES,
    STAGE_DEPENDENCIES,
    ArtifactPurpose,
    PriorityInputs,
    SiteAuditOrchestrationError,
    SiteAuditStage,
    enabled_stage_graph,
    priority_explanation,
    priority_key,
    validate_snapshot_integrity,
)
from musimack_tools.domain.site_audit_persistence import snapshot_hash
from musimack_tools.site_audit.orchestration import _crawl_request, _inventory_url


def test_stage_graph_is_stable_acyclic_and_explicitly_required() -> None:
    visited: set[SiteAuditStage] = set()
    for stage in SiteAuditStage:
        assert all(dependency in visited for dependency in STAGE_DEPENDENCIES[stage])
        visited.add(stage)
    graph = dict(enabled_stage_graph(["images_and_alt_text"]))
    assert set(CORE_REQUIRED_MODULES).issubset(graph)
    assert graph[SiteAuditStage.IMAGES] is False
    assert SiteAuditStage.STRUCTURED_DATA not in graph
    assert CORE_REQUIRED_MODULES.isdisjoint(OPTIONAL_MODULES)


def test_priority_is_explainable_stable_and_protects_security_severity() -> None:
    ordinary = PriorityInputs(security=False, severity="critical", business_importance="critical")
    security = PriorityInputs(security=True, severity="low", business_importance="not_assigned")
    assert priority_key(security, code="security_header", group_id="b") < priority_key(
        ordinary, code="metadata_title", group_id="a"
    )
    explanation = priority_explanation(security)
    assert "low severity" in explanation
    assert "model=site-audit-orchestration-v1" in explanation
    assert priority_key(ordinary, code="a", group_id="a") == priority_key(
        ordinary, code="a", group_id="a"
    )


def test_snapshot_integrity_and_required_hosts_are_enforced() -> None:
    configuration = {"approved_hosts": ["example.com"], "crawl_limits": {"maximum_urls": 25}}
    validate_snapshot_integrity(
        {"configuration": configuration, "sha256": snapshot_hash(configuration)}
    )
    with pytest.raises(SiteAuditOrchestrationError) as changed:
        validate_snapshot_integrity(
            {
                "configuration": {**configuration, "crawl_limits": {}},
                "sha256": snapshot_hash(configuration),
            }
        )
    assert changed.value.code == "site_audit_snapshot_integrity_invalid"
    no_hosts: dict[str, object] = {"approved_hosts": []}
    with pytest.raises(SiteAuditOrchestrationError) as missing:
        validate_snapshot_integrity({"configuration": no_hosts, "sha256": snapshot_hash(no_hosts)})
    assert missing.value.code == "site_audit_approved_hosts_missing"


def test_all_first_release_artifact_purposes_have_safe_stable_filenames() -> None:
    assert set(ARTIFACT_FILENAMES) == set(ArtifactPurpose)
    assert len(set(ARTIFACT_FILENAMES.values())) == 10
    assert all("/" not in value and "\\" not in value for value in ARTIFACT_FILENAMES.values())


def test_inventory_normalization_uses_immutable_tracking_acceptance_and_exceptions() -> None:
    snapshot = {
        "configuration": {
            "tracking_parameters_accepted": True,
            "tracking_parameters": ["utm_source", "utm_campaign"],
            "tracking_parameter_exceptions": ["utm_campaign"],
        },
        "rules": (
            {
                "enabled": True,
                "action": "strip_query_parameter",
                "match_value": "tracking_id",
            },
        ),
    }
    assert (
        _inventory_url(
            snapshot,
            "https://example.com/page?utm_source=one&utm_campaign=keep&tracking_id=&id=2&id=3",
        )
        == "https://example.com/page?id=2&id=3&utm_campaign=keep"
    )


def test_immutable_snapshot_governance_is_propagated_to_the_crawl_frontier() -> None:
    snapshot = {
        "configuration": {
            "approved_hosts": ["example.com"],
            "scope_policy": {"mode": "exact_host"},
            "tracking_parameters_accepted": True,
            "tracking_parameters": ["utm_source", "functional"],
            "tracking_parameter_exceptions": ["functional"],
        },
        "rules": (
            {
                "enabled": True,
                "match_type": "exact_url",
                "match_value": "https://example.com/private",
                "action": "exclude_from_discovery",
            },
            {
                "enabled": True,
                "match_type": "query_parameter_exists",
                "match_value": "tracking_id",
                "action": "strip_query_parameter",
            },
            {
                "enabled": True,
                "match_type": "exact_path",
                "match_value": "/review",
                "action": "crawl_and_mark_for_review",
            },
        ),
    }
    request = _crawl_request(
        {"audit_id": "audit-1", "normalized_seed_url": "https://example.com/"},
        snapshot,
    )

    assert request.strip_query_parameters == ("tracking_id", "utm_source")
    assert [(item.rule_type.value, item.value) for item in request.exclusion_rules] == [
        ("exact_url", "https://example.com/private")
    ]
