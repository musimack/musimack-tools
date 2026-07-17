"""Deterministic contracts for durable internal-link graph analysis."""

# ruff: noqa: ANN401, PLR2004, TRY003

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

INTERNAL_LINK_AUDIT_VERSION = "seo-toolkit-internal-link-audit-v1"
INTERNAL_LINK_GRAPH_VERSION = "seo-toolkit-internal-link-graph-v1"
INTERNAL_LINK_POLICY_VERSION = "seo-toolkit-internal-link-policy-v1"
INTERNAL_LINK_EXPORT_VERSION = "seo-toolkit-internal-link-export-v1"
INTERNAL_LINK_API_VERSION = "seo-toolkit-internal-link-api-v1"
PAGE_ORDERING = "page_sequence_asc_page_identity_asc-v1"
EDGE_ORDERING = "edge_sequence_asc_edge_id_asc-v1"
FINDING_ORDERING = "finding_sequence_asc-v1"
ANCHOR_ORDERING = "anchor_sequence_asc-v1"
OPPORTUNITY_ORDERING = "opportunity_sequence_asc-v1"
AUDIT_ORDERING = "created_at_desc_audit_id_desc-v1"


class InternalLinkLifecycle(StrEnum):
    ACCEPTED = "accepted"
    CLAIMING = "claiming"
    BUILDING_GRAPH = "building_graph"
    COMPUTING_METRICS = "computing_metrics"
    ANALYZING_REACHABILITY = "analyzing_reachability"
    ANALYZING_ANCHORS = "analyzing_anchors"
    BUILDING_OPPORTUNITIES = "building_opportunities"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EligibilityState(StrEnum):
    ELIGIBLE = "eligible"
    REDIRECT_SOURCE = "redirect_source"
    CANONICAL_DUPLICATE = "canonical_duplicate"
    EXCLUDED_NOINDEX = "excluded_noindex"
    EXCLUDED_NON_HTML = "excluded_non_html"
    EXCLUDED_BROKEN = "excluded_broken"
    EXCLUDED_OUT_OF_SCOPE = "excluded_out_of_scope"
    UNVERIFIED = "unverified"


class PageAnalysisState(StrEnum):
    REACHABLE = "reachable"
    ORPHAN_CANDIDATE = "orphan_candidate"
    LOW_INLINK_COUNT = "low_inlink_count"
    HIGH_OUTLINK_COUNT = "high_outlink_count"
    HUB_CANDIDATE = "hub_candidate"
    AUTHORITY_CANDIDATE = "authority_candidate"
    DEEP_PAGE = "deep_page"
    REDIRECT_SOURCE = "redirect_source"
    CANONICAL_DUPLICATE = "canonical_duplicate"
    EXCLUDED_PAGE = "excluded_page"
    UNVERIFIED_PAGE = "unverified_page"


class OrphanState(StrEnum):
    NOT_ORPHAN = "not_orphan"
    TRUE_ORPHAN = "true_orphan_candidate"
    SITEMAP_ONLY = "sitemap_discovered_without_inlinks"
    SEED_PAGE = "seed_page"
    REDIRECT_ONLY = "redirect_only_inlinks"
    NOFOLLOW_ONLY = "nofollow_only_inlinks"
    EXCLUDED = "excluded_not_orphan"
    UNVERIFIED = "unverified_orphan_state"


class CandidateState(StrEnum):
    CANDIDATE = "candidate"
    NOT_CANDIDATE = "not_candidate"
    INSUFFICIENT_SAMPLE = "insufficient_sample"


class AnchorState(StrEnum):
    HEALTHY = "healthy"
    EMPTY = "empty_anchor"
    GENERIC = "generic_anchor"
    URL = "url_as_anchor"
    CONCENTRATED = "over_concentrated_anchor"
    INCONSISTENT = "inconsistent_anchor_group"
    DUPLICATE_TO_TARGETS = "duplicate_anchor_to_multiple_targets"
    MULTIPLE_TO_TARGET = "multiple_anchors_to_same_target"
    REDIRECTING_TARGET = "redirecting_anchor_target"
    BROKEN_TARGET = "broken_anchor_target"


class OpportunityType(StrEnum):
    LINK_ORPHAN_FROM_HUB = "link_orphan_from_hub"
    STRENGTHEN_LOW_INLINK = "strengthen_low_inlink_page"
    REPLACE_REDIRECTING = "replace_redirecting_link"
    REPLACE_BROKEN = "replace_broken_link"
    REDUCE_EXCESSIVE = "reduce_excessive_outlinks"
    IMPROVE_ANCHOR = "improve_anchor_text"
    PROMOTE_HUB = "promote_hub_page"
    REVIEW_ISOLATION = "review_graph_isolation"


class OpportunityAction(StrEnum):
    ADD_INTERNAL_LINK = "add_internal_link"
    STRENGTHEN_EXISTING_LINK = "strengthen_existing_link"
    UPDATE_LINK_DESTINATION = "update_link_destination"
    REMOVE_OR_REPLACE_LINK = "remove_or_replace_link"
    REDUCE_EXCESSIVE_LINKS = "reduce_excessive_links"
    PROMOTE_AS_HUB = "promote_as_hub"
    REVIEW = "review"
    NO_ACTION = "no_action"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class InternalLinkExportFormat(StrEnum):
    PAGE_METRICS_CSV = "page_metrics_csv"
    ORPHANS_CSV = "orphan_candidates_csv"
    HUBS_AUTHORITIES_CSV = "hubs_authorities_csv"
    ANCHORS_CSV = "anchor_findings_csv"
    OPPORTUNITIES_CSV = "opportunities_csv"
    JSON = "json"
    MARKDOWN = "markdown"


@dataclass(frozen=True, slots=True)
class InternalLinkConfiguration:
    enabled: bool = False
    default_page_size: int = 50
    maximum_page_size: int = 200
    maximum_export_rows: int = 100_000
    maximum_path_depth: int = 64
    minimum_hub_destinations: int = 10
    minimum_authority_referrers: int = 5
    maximum_graph_depth: int = 4
    maximum_outlinks: int = 100
    low_inlink_threshold: int = 2
    dominant_anchor_share: float = 0.80
    minimum_sitewide_pages: int = 5
    sitewide_source_ratio: float = 0.50
    retention_days: int = 180

    def __post_init__(self) -> None:
        if not 1 <= self.default_page_size <= self.maximum_page_size <= 1_000:
            raise ValueError("internal-link page sizes are invalid")
        if not 1 <= self.maximum_export_rows <= 1_000_000:
            raise ValueError("internal-link export limit is invalid")
        if not 1 <= self.maximum_path_depth <= 256:
            raise ValueError("internal-link path depth is invalid")
        if (
            min(
                self.minimum_hub_destinations,
                self.minimum_authority_referrers,
                self.maximum_graph_depth,
                self.maximum_outlinks,
                self.low_inlink_threshold,
                self.minimum_sitewide_pages,
                self.retention_days,
            )
            < 1
        ):
            raise ValueError("internal-link thresholds must be positive")
        if not 0 < self.dominant_anchor_share <= 1 or not 0 < self.sitewide_source_ratio <= 1:
            raise ValueError("internal-link ratios are invalid")

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


GENERIC_ANCHORS = frozenset({"click here", "read more", "learn more", "more", "here", "this page"})
_WHITESPACE = re.compile(r"\s+")


def normalize_anchor(value: str | None, *, maximum_length: int = 512) -> str:
    """Normalize anchor grouping without inferring meaning."""
    return _WHITESPACE.sub(" ", (value or "").strip()).casefold()[:maximum_length]


def is_url_anchor(value: str) -> bool:
    lowered = value.casefold()
    return lowered.startswith(("http://", "https://", "www."))


def stable_identity(*values: object) -> str:
    return hashlib.sha256("\0".join(str(value) for value in values).encode()).hexdigest()


def audit_identity(run_id: str, configuration: InternalLinkConfiguration) -> str:
    payload = json.dumps(configuration.snapshot(), sort_keys=True, separators=(",", ":"))
    return f"internal-link-audit-{stable_identity(run_id, payload)[:24]}"


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def filter_fingerprint(values: dict[str, Any]) -> str:
    return stable_identity(stable_json(values))[:24]


def encode_cursor(kind: str, ordering: str, fingerprint: str, offset: int) -> str:
    payload = stable_json({"f": fingerprint, "k": kind, "o": offset, "v": ordering}).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(value: str, kind: str, ordering: str, fingerprint: str) -> int:
    try:
        payload = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        offset = int(payload["o"])
    except KeyError, TypeError, ValueError, json.JSONDecodeError:
        raise ValueError("internal_link_cursor_invalid") from None
    if payload != {"f": fingerprint, "k": kind, "o": payload["o"], "v": ordering}:
        raise ValueError("internal_link_cursor_filter_mismatch")
    if offset < 0:
        raise ValueError("internal_link_cursor_invalid")
    return offset
