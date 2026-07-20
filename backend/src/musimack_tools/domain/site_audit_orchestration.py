"""Durable, deterministic contracts for CSA-04 orchestration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

SITE_AUDIT_ORCHESTRATION_VERSION = "site-audit-orchestration-v1"
SITE_AUDIT_STAGE_GRAPH_VERSION = "site-audit-stage-graph-v1"
SITE_AUDIT_ISSUE_DEFINITION_VERSION = "site-audit-issues-v1"
SITE_AUDIT_ARTIFACT_VERSION = "site-audit-artifacts-v1"
MAXIMUM_RECONCILIATION_ROWS = 100_000
MAXIMUM_ARTIFACT_ROWS = 100_000
MAXIMUM_STAGE_RETRIES = 3


class SiteAuditOrchestrationError(RuntimeError):
    """Safe stable failure exposed at the CSA orchestration boundary."""

    def __init__(self, code: str, explanation: str) -> None:
        super().__init__(explanation)
        self.code = code
        self.explanation = explanation


class OrchestrationState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    RECOVERY_REQUIRED = "recovery_required"


class StageState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"

    @property
    def terminal(self) -> bool:
        return self in {
            self.COMPLETED,
            self.PARTIAL,
            self.UNAVAILABLE,
            self.FAILED,
            self.CANCELLED,
            self.BLOCKED,
        }


class SiteAuditStage(StrEnum):
    CRAWL = "crawl_inventory"
    INGEST = "url_ingestion"
    GOVERNANCE = "url_governance"
    POPULATIONS = "population_classification"
    STATUS_REDIRECTS = "status_and_redirects"
    ROBOTS_INDEXABILITY = "robots_and_indexability"
    CANONICALS = "canonicals"
    METADATA = "metadata"
    EXISTING_SITEMAP = "existing_sitemap"
    SITEMAP_RECOMMENDATIONS = "sitemap_recommendations"
    BROKEN_LINKS = "broken_links"
    INTERNAL_LINKS = "internal_links"
    IMAGES = "images_and_alt_text"
    STRUCTURED_DATA = "structured_data"
    ISSUE_AGGREGATION = "issue_aggregation"
    SUMMARY = "summary_rebuild"
    ARTIFACTS = "artifact_generation"


CORE_REQUIRED_MODULES = frozenset(
    {
        SiteAuditStage.CRAWL,
        SiteAuditStage.INGEST,
        SiteAuditStage.GOVERNANCE,
        SiteAuditStage.POPULATIONS,
        SiteAuditStage.STATUS_REDIRECTS,
        SiteAuditStage.ROBOTS_INDEXABILITY,
        SiteAuditStage.CANONICALS,
        SiteAuditStage.METADATA,
        SiteAuditStage.EXISTING_SITEMAP,
        SiteAuditStage.SITEMAP_RECOMMENDATIONS,
        SiteAuditStage.ISSUE_AGGREGATION,
        SiteAuditStage.SUMMARY,
        SiteAuditStage.ARTIFACTS,
    }
)

OPTIONAL_MODULES = frozenset(
    {
        SiteAuditStage.BROKEN_LINKS,
        SiteAuditStage.INTERNAL_LINKS,
        SiteAuditStage.IMAGES,
        SiteAuditStage.STRUCTURED_DATA,
    }
)

STAGE_DEPENDENCIES: dict[SiteAuditStage, tuple[SiteAuditStage, ...]] = {
    SiteAuditStage.CRAWL: (),
    SiteAuditStage.INGEST: (SiteAuditStage.CRAWL,),
    SiteAuditStage.GOVERNANCE: (SiteAuditStage.INGEST,),
    SiteAuditStage.POPULATIONS: (SiteAuditStage.GOVERNANCE,),
    SiteAuditStage.STATUS_REDIRECTS: (SiteAuditStage.INGEST,),
    SiteAuditStage.ROBOTS_INDEXABILITY: (SiteAuditStage.INGEST,),
    SiteAuditStage.CANONICALS: (SiteAuditStage.INGEST,),
    SiteAuditStage.METADATA: (SiteAuditStage.POPULATIONS,),
    SiteAuditStage.EXISTING_SITEMAP: (SiteAuditStage.POPULATIONS,),
    SiteAuditStage.SITEMAP_RECOMMENDATIONS: (
        SiteAuditStage.POPULATIONS,
        SiteAuditStage.EXISTING_SITEMAP,
    ),
    SiteAuditStage.BROKEN_LINKS: (SiteAuditStage.INGEST,),
    SiteAuditStage.INTERNAL_LINKS: (SiteAuditStage.INGEST,),
    SiteAuditStage.IMAGES: (SiteAuditStage.INGEST,),
    SiteAuditStage.STRUCTURED_DATA: (SiteAuditStage.INGEST,),
    SiteAuditStage.ISSUE_AGGREGATION: (
        SiteAuditStage.POPULATIONS,
        SiteAuditStage.METADATA,
        SiteAuditStage.SITEMAP_RECOMMENDATIONS,
    ),
    SiteAuditStage.SUMMARY: (SiteAuditStage.ISSUE_AGGREGATION,),
    SiteAuditStage.ARTIFACTS: (SiteAuditStage.SUMMARY,),
}


class ArtifactPurpose(StrEnum):
    EXECUTIVE = "executive_markdown"
    PAGE_INVENTORY = "page_inventory_csv"
    EVIDENCE = "full_evidence_json"
    ISSUES = "grouped_issues_csv"
    SITEMAP_COMPARISON = "sitemap_comparison_csv"
    EXCLUSIONS = "excluded_urls_csv"
    RULES = "applied_rules_csv"
    SITEMAP_XML = "recommended_sitemap_xml"
    ACTION_PLAN = "action_plan_csv"
    CONFIGURATION = "configuration_snapshot_json"


ARTIFACT_FILENAMES: dict[ArtifactPurpose, str] = {
    ArtifactPurpose.EXECUTIVE: "site-audit-executive.md",
    ArtifactPurpose.PAGE_INVENTORY: "site-audit-pages.csv",
    ArtifactPurpose.EVIDENCE: "site-audit-evidence.json",
    ArtifactPurpose.ISSUES: "site-audit-issues.csv",
    ArtifactPurpose.SITEMAP_COMPARISON: "site-audit-sitemap-comparison.csv",
    ArtifactPurpose.EXCLUSIONS: "site-audit-exclusions.csv",
    ArtifactPurpose.RULES: "site-audit-applied-rules.csv",
    ArtifactPurpose.SITEMAP_XML: "site-audit-sitemap.xml",
    ArtifactPurpose.ACTION_PLAN: "site-audit-action-plan.csv",
    ArtifactPurpose.CONFIGURATION: "site-audit-configuration.json",
}


@dataclass(frozen=True, slots=True)
class PriorityInputs:
    security: bool
    severity: str
    business_importance: str = "not_assigned"
    indexability_impact: bool = False
    sitemap_impact: bool = False
    internal_link_impact: bool = False
    affected_count: int = 1
    pattern_state: str = "none"
    confidence: str = "high"
    determinacy: str = "determinate"


_SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}
_IMPORTANCE = {"critical": 0, "high": 1, "medium": 2, "low": 3, "not_assigned": 4}
_PATTERN = {"confirmed": 0, "candidate": 1, "none": 2}
_CONFIDENCE = {"high": 0, "medium": 1, "low": 2}


def priority_key(inputs: PriorityInputs, *, code: str, group_id: str) -> str:
    """Return a lexicographically sortable and fully disclosed priority key."""
    values = (
        0 if inputs.security else 1,
        _SEVERITY.get(inputs.severity, 5),
        _IMPORTANCE.get(inputs.business_importance, 4),
        0 if inputs.indexability_impact else 1,
        0 if inputs.sitemap_impact else 1,
        0 if inputs.internal_link_impact else 1,
        MAXIMUM_ARTIFACT_ROWS - min(max(inputs.affected_count, 0), MAXIMUM_ARTIFACT_ROWS),
        _PATTERN.get(inputs.pattern_state, 2),
        _CONFIDENCE.get(inputs.confidence, 2),
        0 if inputs.determinacy == "determinate" else 1,
        code,
        group_id,
    )
    return "|".join(f"{value:06d}" if isinstance(value, int) else value for value in values)


def priority_explanation(inputs: PriorityInputs) -> str:
    return (
        f"{inputs.severity} severity; {inputs.business_importance} business importance; "
        f"indexability impact={str(inputs.indexability_impact).lower()}; "
        f"sitemap impact={str(inputs.sitemap_impact).lower()}; "
        f"internal-link impact={str(inputs.internal_link_impact).lower()}; "
        f"{inputs.affected_count} affected URL(s); {inputs.pattern_state} leverage; "
        f"{inputs.confidence} confidence; {inputs.determinacy}; "
        f"model={SITE_AUDIT_ORCHESTRATION_VERSION}."
    )


def stable_identifier(*parts: object) -> str:
    return hashlib.sha256("\0".join(str(part) for part in parts).encode()).hexdigest()


def validate_snapshot_integrity(snapshot: dict[str, Any]) -> None:
    configuration = snapshot.get("configuration")
    expected = snapshot.get("sha256")
    if not isinstance(configuration, dict) or not isinstance(expected, str):
        raise SiteAuditOrchestrationError(
            "site_audit_snapshot_missing", "The immutable Site Audit snapshot is unavailable."
        )
    actual = hashlib.sha256(
        json.dumps(configuration, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    if actual != expected:
        raise SiteAuditOrchestrationError(
            "site_audit_snapshot_integrity_invalid",
            "The immutable Site Audit snapshot did not pass its integrity check.",
        )
    hosts = configuration.get("approved_hosts")
    if not isinstance(hosts, list) or not hosts:
        raise SiteAuditOrchestrationError(
            "site_audit_approved_hosts_missing", "At least one approved host is required."
        )


def enabled_stage_graph(enabled_modules: object) -> tuple[tuple[SiteAuditStage, bool], ...]:
    names = (
        {str(item) for item in enabled_modules}
        if isinstance(enabled_modules, list)
        else {str(key) for key, value in enabled_modules.items() if value}
        if isinstance(enabled_modules, dict)
        else set()
    )
    result: list[tuple[SiteAuditStage, bool]] = []
    for stage in SiteAuditStage:
        if stage in OPTIONAL_MODULES and stage.value not in names:
            continue
        result.append((stage, stage in CORE_REQUIRED_MODULES))
    return tuple(result)
