"""CSA-04 deterministic artifact content and safety coverage."""

from __future__ import annotations

import hashlib
import json

from musimack_tools.domain.site_audit_orchestration import ArtifactPurpose
from musimack_tools.site_audit.artifacts import (
    GeneratedSiteAuditArtifact,
    generate_site_audit_artifacts,
)


def _generated() -> tuple[GeneratedSiteAuditArtifact, ...]:
    audit = {
        "audit_id": "audit-1",
        "audit_name": "Example audit",
        "normalized_seed_url": "https://example.com/",
        "lifecycle": "completed",
        "population_completeness": "complete",
        "module_completeness": "complete",
        "partial": False,
    }
    snapshot = {
        "snapshot_id": "snapshot-1",
        "sha256": "a" * 64,
        "configuration": {"approved_hosts": ["example.com"], "secret": "not-present"},
        "rules": (),
        "disabled_inherited_rules": (),
    }
    summary = {
        "urls_discovered": 1,
        "urls_fetched": 1,
        "html_urls": 1,
        "metadata_scoring_eligible_urls": 1,
        "partial_urls": 0,
    }
    urls = (
        {
            "url_id": "url-1",
            "sequence": 0,
            "original_url": "https://example.com/",
            "requested_url": "https://example.com/",
            "normalized_url": "https://example.com/",
            "final_url": "https://example.com/",
            "fetch_state": "fetched",
            "http_status": 200,
            "content_type": "text/html",
            "indexability_state": "indexable",
            "canonical_state": "canonical",
            "existing_sitemap_state": "present",
            "recommended_sitemap_state": "include",
            "metadata_scoring_decision": "include_in_metadata_scoring",
            "discovery_decision": "enqueue",
            "sitemap_policy_decision": "evidence_derived",
            "highest_severity": None,
            "business_importance": "not_assigned",
            "crawl_depth": 0,
            "partial": False,
            "evidence_id": "evidence-1",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
    )
    evidence = {
        "evidence-1": {
            "title_presence": "single",
            "title_value": "Example",
            "description_presence": "single",
            "description_value": "Description",
            "parse_warning_count": 0,
        }
    }
    return generate_site_audit_artifacts(
        audit=audit,
        snapshot=snapshot,
        summary=summary,
        urls=urls,
        findings=(),
        issue_groups=(),
        rule_matches=(),
        evidence=evidence,
    )


def test_all_ten_artifacts_are_deterministic_bounded_and_hashable() -> None:
    first = _generated()
    second = _generated()
    assert len(first) == 10
    assert [item.purpose for item in first] == [item.purpose for item in second]
    assert [item.content for item in first] == [item.content for item in second]
    assert all(len(hashlib.sha256(item.content).hexdigest()) == 64 for item in first)


def test_full_evidence_is_safe_and_sitemap_is_not_published() -> None:
    generated = {item.purpose: item for item in _generated()}
    evidence = generated[ArtifactPurpose.EVIDENCE].content.decode()
    payload = json.loads(evidence)
    assert "response_body" not in evidence
    assert "raw_html" not in evidence
    assert "filesystem" not in evidence
    assert payload["urls"][0]["url"] == "https://example.com/"
    sitemap = generated[ArtifactPurpose.SITEMAP_XML].content.decode()
    assert "<loc>https://example.com/</loc>" in sitemap
    assert "publish" not in sitemap.casefold()


def test_configuration_snapshot_preserves_exact_immutable_configuration() -> None:
    generated = {item.purpose: item for item in _generated()}
    payload = json.loads(generated[ArtifactPurpose.CONFIGURATION].content.decode())
    assert payload["sha256"] == "a" * 64
    assert payload["configuration"]["approved_hosts"] == ["example.com"]
