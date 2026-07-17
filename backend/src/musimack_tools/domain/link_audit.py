"""Deterministic broken-link and redirect-analysis contracts and policies."""

# ruff: noqa: ANN401, C901, PLR0911, PLR0913, PLR2004, TRY003, TRY004

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

LINK_EVIDENCE_VERSION = "seo-toolkit-link-evidence-v1"
LINK_AUDIT_VERSION = "seo-toolkit-link-audit-v1"
LINK_ANALYSIS_POLICY_VERSION = "seo-toolkit-link-analysis-v1"
REDIRECT_ANALYSIS_POLICY_VERSION = "seo-toolkit-redirect-analysis-v1"
LINK_AUDIT_EXPORT_VERSION = "seo-toolkit-link-audit-export-v1"
LINK_AUDIT_API_VERSION = "seo-toolkit-link-audit-api-v1"
LINK_AUDIT_PAGINATION_VERSION = "seo-toolkit-link-audit-pagination-v1"
TARGET_ORDERING = "target_sequence_asc_target_identity_asc-v1"
OCCURRENCE_ORDERING = "source_discovery_sequence_asc_link_sequence_asc-v1"
CHAIN_ORDERING = "chain_sequence_asc_chain_identity_asc-v1"
FINDING_ORDERING = "finding_sequence_asc-v1"
RECOMMENDATION_ORDERING = "recommendation_sequence_asc-v1"
AUDIT_ORDERING = "created_at_desc_audit_id_desc-v1"


class LinkAuditLifecycle(StrEnum):
    ACCEPTED = "accepted"
    CLAIMING = "claiming"
    BUILDING_GRAPH = "building_graph"
    CLASSIFYING_LINKS = "classifying_links"
    EXPANDING_REDIRECTS = "expanding_redirects"
    DETECTING_LOOPS = "detecting_loops"
    BUILDING_RECOMMENDATIONS = "building_recommendations"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"


class LinkType(StrEnum):
    HTTP = "http"
    MAILTO = "mailto"
    TEL = "tel"
    JAVASCRIPT = "javascript"
    DATA = "data"
    FRAGMENT = "fragment"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"


class BrokenLinkState(StrEnum):
    WORKING_INTERNAL_LINK = "working_internal_link"
    BROKEN_INTERNAL_LINK = "broken_internal_link"
    REDIRECTING_INTERNAL_LINK = "redirecting_internal_link"
    UNVERIFIED_INTERNAL_LINK = "unverified_internal_link"
    OUT_OF_SCOPE_INTERNAL_TARGET = "out_of_scope_internal_target"
    EXTERNAL_LINK_NOT_AUDITED = "external_link_not_audited"
    SOURCE_PAGE_UNAVAILABLE = "source_page_unavailable"
    TARGET_FETCH_FAILED = "target_fetch_failed"
    TARGET_NON_HTML = "target_non_html"


class BrokenLinkReason(StrEnum):
    WORKING = "working"
    TARGET_404 = "target_404"
    TARGET_410 = "target_410"
    TARGET_OTHER_4XX = "target_other_4xx"
    TARGET_5XX = "target_5xx"
    TARGET_FETCH_FAILED = "target_fetch_failed"
    TARGET_TIMEOUT = "target_timeout"
    TARGET_DNS_FAILURE = "target_dns_failure"
    TARGET_BLOCKED = "target_blocked"
    TARGET_NOT_CRAWLED = "target_not_crawled"
    TARGET_OUT_OF_SCOPE = "target_out_of_scope"
    TARGET_NON_HTML = "target_non_html"
    SOURCE_FETCH_FAILED = "source_fetch_failed"
    SOURCE_PARSE_PARTIAL = "source_parse_partial"
    INVALID_HREF = "invalid_href"
    UNSUPPORTED_SCHEME = "unsupported_scheme"
    FRAGMENT_ONLY_LINK = "fragment_only_link"
    MAILTO_LINK = "mailto_link"
    TEL_LINK = "tel_link"
    JAVASCRIPT_LINK = "javascript_link"
    DATA_LINK = "data_link"
    EXTERNAL_TARGET = "external_target"
    REDIRECT = "redirect"


class RedirectState(StrEnum):
    NO_REDIRECT = "no_redirect"
    SINGLE_REDIRECT = "single_redirect"
    REDIRECT_CHAIN = "redirect_chain"
    REDIRECT_LOOP = "redirect_loop"
    REDIRECT_TO_BROKEN_TARGET = "redirect_to_broken_target"
    REDIRECT_TO_EXTERNAL_TARGET = "redirect_to_external_target"
    REDIRECT_TO_OUT_OF_SCOPE_TARGET = "redirect_to_out_of_scope_target"
    REDIRECT_TO_NON_HTML_TARGET = "redirect_to_non_html_target"
    REDIRECT_UNVERIFIED = "redirect_unverified"


class RedirectReason(StrEnum):
    NONE = "no_redirect"
    PERMANENT_REDIRECT = "permanent_redirect"
    TEMPORARY_REDIRECT = "temporary_redirect"
    MIXED_REDIRECT_CHAIN = "mixed_redirect_chain"
    REDIRECT_CHAIN_TOO_LONG = "redirect_chain_too_long"
    REDIRECT_LOOP_DETECTED = "redirect_loop_detected"
    REDIRECT_TARGET_404 = "redirect_target_404"
    REDIRECT_TARGET_410 = "redirect_target_410"
    REDIRECT_TARGET_OTHER_4XX = "redirect_target_other_4xx"
    REDIRECT_TARGET_5XX = "redirect_target_5xx"
    REDIRECT_TARGET_FETCH_FAILED = "redirect_target_fetch_failed"
    REDIRECT_TARGET_EXTERNAL = "redirect_target_external"
    REDIRECT_TARGET_OUT_OF_SCOPE = "redirect_target_out_of_scope"
    REDIRECT_TARGET_NON_HTML = "redirect_target_non_html"
    REDIRECT_TARGET_UNVERIFIED = "redirect_target_unverified"


class RecommendationAction(StrEnum):
    FIX_LINK = "fix_link"
    UPDATE_LINK_TO_FINAL_DESTINATION = "update_link_to_final_destination"
    REMOVE_LINK = "remove_link"
    CREATE_REDIRECT = "create_redirect"
    REPLACE_REDIRECT = "replace_redirect"
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


class ExportFormat(StrEnum):
    BROKEN_LINKS_CSV = "broken_links_csv"
    REDIRECT_CHAINS_CSV = "redirect_chains_csv"
    REDIRECT_MAP_CSV = "redirect_map_csv"
    JSON = "json"
    MARKDOWN = "markdown"


@dataclass(frozen=True, slots=True)
class LinkAuditConfiguration:
    enabled: bool = False
    default_page_size: int = 50
    maximum_page_size: int = 200
    maximum_export_rows: int = 100_000
    maximum_redirect_chain_depth: int = 10
    minimum_sitewide_source_pages: int = 5
    minimum_sitewide_crawl_pages: int = 10
    sitewide_ratio: float = 0.5
    retention_days: int = 180

    def __post_init__(self) -> None:
        if not 1 <= self.default_page_size <= self.maximum_page_size <= 1_000:
            raise ValueError("link audit page sizes are invalid")
        if not 1 <= self.maximum_export_rows <= 1_000_000:
            raise ValueError("link audit export limit is invalid")
        if not 1 <= self.maximum_redirect_chain_depth <= 20:
            raise ValueError("link audit redirect depth is invalid")
        if self.minimum_sitewide_source_pages < 2 or self.minimum_sitewide_crawl_pages < 2:
            raise ValueError("link audit sitewide thresholds are invalid")
        if not 0 < self.sitewide_ratio <= 1:
            raise ValueError("link audit sitewide ratio is invalid")
        if not 1 <= self.retention_days <= 3_650:
            raise ValueError("link audit retention is invalid")

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TargetEvidence:
    target_url: str
    http_status: int | None = None
    fetch_failed: bool = False
    failure_code: str | None = None
    content_type_category: str | None = None
    in_scope: bool | None = True
    internal: bool | None = True
    source_available: bool = True
    source_partial: bool = False
    redirect_hops: tuple[dict[str, Any], ...] = ()
    redirect_loop: bool = False
    final_url: str | None = None
    final_status: int | None = None
    final_content_type_category: str | None = None
    final_in_scope: bool | None = True
    final_internal: bool | None = True
    chain_too_long: bool = False


@dataclass(frozen=True, slots=True)
class TargetClassification:
    broken_state: BrokenLinkState
    broken_reason: BrokenLinkReason
    redirect_state: RedirectState
    redirect_reason: RedirectReason
    severity: Severity
    action: RecommendationAction
    confidence: Confidence
    final_destination: str | None


def classify_target(evidence: TargetEvidence) -> TargetClassification:
    """Apply specific redirect and target evidence before generic missing states."""
    if not evidence.source_available:
        return _classification(
            BrokenLinkState.SOURCE_PAGE_UNAVAILABLE,
            BrokenLinkReason.SOURCE_FETCH_FAILED,
            severity=Severity.MEDIUM,
            action=RecommendationAction.REVIEW,
            confidence=Confidence.LOW,
        )
    if evidence.source_partial:
        return _classification(
            BrokenLinkState.SOURCE_PAGE_UNAVAILABLE,
            BrokenLinkReason.SOURCE_PARSE_PARTIAL,
            severity=Severity.MEDIUM,
            action=RecommendationAction.REVIEW,
            confidence=Confidence.LOW,
        )
    if evidence.internal is False:
        return _classification(
            BrokenLinkState.EXTERNAL_LINK_NOT_AUDITED,
            BrokenLinkReason.EXTERNAL_TARGET,
            severity=Severity.INFO,
        )
    if evidence.in_scope is False:
        return _classification(
            BrokenLinkState.OUT_OF_SCOPE_INTERNAL_TARGET,
            BrokenLinkReason.TARGET_OUT_OF_SCOPE,
            severity=Severity.MEDIUM,
            action=RecommendationAction.REVIEW,
            confidence=Confidence.LOW,
        )
    if evidence.redirect_hops or evidence.redirect_loop:
        return _redirect_classification(evidence)
    return _terminal_classification(evidence)


def _redirect_classification(
    evidence: TargetEvidence,
) -> TargetClassification:
    hops = evidence.redirect_hops
    permanent = {301, 308}
    temporary = {302, 303, 307}
    statuses = {int(item.get("status_code", 0)) for item in hops}
    final = evidence.final_url
    if evidence.redirect_loop:
        return _classification(
            BrokenLinkState.REDIRECTING_INTERNAL_LINK,
            BrokenLinkReason.REDIRECT,
            RedirectState.REDIRECT_LOOP,
            RedirectReason.REDIRECT_LOOP_DETECTED,
            Severity.CRITICAL,
            RecommendationAction.REPLACE_REDIRECT,
            Confidence.HIGH,
            final,
        )
    if evidence.chain_too_long:
        return _classification(
            BrokenLinkState.REDIRECTING_INTERNAL_LINK,
            BrokenLinkReason.REDIRECT,
            RedirectState.REDIRECT_CHAIN,
            RedirectReason.REDIRECT_CHAIN_TOO_LONG,
            Severity.HIGH,
            RecommendationAction.REPLACE_REDIRECT,
            Confidence.HIGH,
            final,
        )
    if evidence.final_internal is False:
        return _classification(
            BrokenLinkState.REDIRECTING_INTERNAL_LINK,
            BrokenLinkReason.REDIRECT,
            RedirectState.REDIRECT_TO_EXTERNAL_TARGET,
            RedirectReason.REDIRECT_TARGET_EXTERNAL,
            Severity.MEDIUM,
            RecommendationAction.REVIEW,
            Confidence.MEDIUM,
            final,
        )
    if evidence.final_in_scope is False:
        return _classification(
            BrokenLinkState.REDIRECTING_INTERNAL_LINK,
            BrokenLinkReason.REDIRECT,
            RedirectState.REDIRECT_TO_OUT_OF_SCOPE_TARGET,
            RedirectReason.REDIRECT_TARGET_OUT_OF_SCOPE,
            Severity.MEDIUM,
            RecommendationAction.REVIEW,
            Confidence.LOW,
            final,
        )
    if evidence.final_content_type_category not in {None, "html", "missing"}:
        return _classification(
            BrokenLinkState.REDIRECTING_INTERNAL_LINK,
            BrokenLinkReason.REDIRECT,
            RedirectState.REDIRECT_TO_NON_HTML_TARGET,
            RedirectReason.REDIRECT_TARGET_NON_HTML,
            Severity.MEDIUM,
            RecommendationAction.REVIEW,
            Confidence.MEDIUM,
            final,
        )
    if evidence.fetch_failed:
        return _classification(
            BrokenLinkState.TARGET_FETCH_FAILED,
            BrokenLinkReason.TARGET_FETCH_FAILED,
            RedirectState.REDIRECT_UNVERIFIED,
            RedirectReason.REDIRECT_TARGET_FETCH_FAILED,
            Severity.HIGH,
            RecommendationAction.REVIEW,
            Confidence.LOW,
            final,
        )
    final_status = evidence.final_status
    if final_status == 404:
        return _redirect_broken(evidence, RedirectReason.REDIRECT_TARGET_404)
    if final_status == 410:
        return _redirect_broken(evidence, RedirectReason.REDIRECT_TARGET_410)
    if final_status is not None and 400 <= final_status < 500:
        return _redirect_broken(evidence, RedirectReason.REDIRECT_TARGET_OTHER_4XX)
    if final_status is not None and final_status >= 500:
        return _redirect_broken(evidence, RedirectReason.REDIRECT_TARGET_5XX)
    if final_status is None:
        return _classification(
            BrokenLinkState.REDIRECTING_INTERNAL_LINK,
            BrokenLinkReason.REDIRECT,
            RedirectState.REDIRECT_UNVERIFIED,
            RedirectReason.REDIRECT_TARGET_UNVERIFIED,
            Severity.HIGH,
            RecommendationAction.REVIEW,
            Confidence.LOW,
            final,
        )
    reason = (
        RedirectReason.MIXED_REDIRECT_CHAIN
        if statuses & permanent and statuses & temporary
        else RedirectReason.PERMANENT_REDIRECT
        if statuses and statuses <= permanent
        else RedirectReason.TEMPORARY_REDIRECT
    )
    chain = len(hops) > 1
    return _classification(
        BrokenLinkState.REDIRECTING_INTERNAL_LINK,
        BrokenLinkReason.REDIRECT,
        RedirectState.REDIRECT_CHAIN if chain else RedirectState.SINGLE_REDIRECT,
        reason,
        Severity.HIGH if chain else Severity.MEDIUM,
        RecommendationAction.UPDATE_LINK_TO_FINAL_DESTINATION,
        Confidence.HIGH if final else Confidence.LOW,
        final,
    )


def _redirect_broken(evidence: TargetEvidence, reason: RedirectReason) -> TargetClassification:
    return _classification(
        BrokenLinkState.REDIRECTING_INTERNAL_LINK,
        BrokenLinkReason.REDIRECT,
        RedirectState.REDIRECT_TO_BROKEN_TARGET,
        reason,
        Severity.CRITICAL if reason is RedirectReason.REDIRECT_TARGET_5XX else Severity.HIGH,
        RecommendationAction.REVIEW,
        Confidence.HIGH,
        evidence.final_url,
    )


def _terminal_classification(evidence: TargetEvidence) -> TargetClassification:
    if evidence.content_type_category not in {None, "html", "missing"}:
        return _classification(
            BrokenLinkState.TARGET_NON_HTML,
            BrokenLinkReason.TARGET_NON_HTML,
            severity=Severity.MEDIUM,
            action=RecommendationAction.REVIEW,
            confidence=Confidence.MEDIUM,
        )
    if evidence.http_status == 404:
        return _broken(BrokenLinkReason.TARGET_404)
    if evidence.http_status == 410:
        return _broken(BrokenLinkReason.TARGET_410)
    if evidence.http_status is not None and 400 <= evidence.http_status < 500:
        return _broken(BrokenLinkReason.TARGET_OTHER_4XX)
    if evidence.http_status is not None and evidence.http_status >= 500:
        return _broken(BrokenLinkReason.TARGET_5XX, Severity.HIGH)
    if evidence.fetch_failed:
        failure = (evidence.failure_code or "").casefold()
        reason = (
            BrokenLinkReason.TARGET_TIMEOUT
            if "timeout" in failure
            else BrokenLinkReason.TARGET_DNS_FAILURE
            if "dns" in failure
            else BrokenLinkReason.TARGET_BLOCKED
            if "block" in failure or "robots" in failure
            else BrokenLinkReason.TARGET_FETCH_FAILED
        )
        return _classification(
            BrokenLinkState.TARGET_FETCH_FAILED,
            reason,
            severity=Severity.MEDIUM,
            action=RecommendationAction.REVIEW,
            confidence=Confidence.MEDIUM,
        )
    if evidence.http_status is None:
        return _classification(
            BrokenLinkState.UNVERIFIED_INTERNAL_LINK,
            BrokenLinkReason.TARGET_NOT_CRAWLED,
            severity=Severity.MEDIUM,
            action=RecommendationAction.REVIEW,
            confidence=Confidence.LOW,
        )
    return _classification(
        BrokenLinkState.WORKING_INTERNAL_LINK,
        BrokenLinkReason.WORKING,
        severity=Severity.INFO,
    )


def _broken(reason: BrokenLinkReason, severity: Severity = Severity.HIGH) -> TargetClassification:
    return _classification(
        BrokenLinkState.BROKEN_INTERNAL_LINK,
        reason,
        severity=severity,
        action=RecommendationAction.REMOVE_LINK,
        confidence=Confidence.HIGH,
    )


def _classification(
    state: BrokenLinkState,
    reason: BrokenLinkReason,
    redirect_state: RedirectState = RedirectState.NO_REDIRECT,
    redirect_reason: RedirectReason = RedirectReason.NONE,
    severity: Severity = Severity.INFO,
    action: RecommendationAction = RecommendationAction.NO_ACTION,
    confidence: Confidence = Confidence.HIGH,
    final: str | None = None,
) -> TargetClassification:
    return TargetClassification(
        state,
        redirect_state=redirect_state,
        broken_reason=reason,
        redirect_reason=redirect_reason,
        severity=severity,
        action=action,
        confidence=confidence,
        final_destination=final,
    )


def stable_identity(*values: object) -> str:
    return hashlib.sha256("\0".join(str(value) for value in values).encode()).hexdigest()


def audit_identity(run_id: str, configuration: LinkAuditConfiguration) -> str:
    payload = json.dumps(configuration.snapshot(), sort_keys=True, separators=(",", ":"))
    return f"link-audit-{stable_identity(run_id, payload)[:24]}"


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def filter_fingerprint(values: dict[str, Any]) -> str:
    return hashlib.sha256(stable_json(values).encode()).hexdigest()


def encode_cursor(kind: str, ordering: str, fingerprint: str, offset: int) -> str:
    payload = stable_json(
        {
            "version": LINK_AUDIT_PAGINATION_VERSION,
            "kind": kind,
            "ordering": ordering,
            "filter": fingerprint,
            "offset": offset,
        }
    )
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(value: str, kind: str, ordering: str, fingerprint: str) -> int:
    try:
        payload = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    except ValueError, TypeError, json.JSONDecodeError:
        raise ValueError("link_audit_invalid_cursor") from None
    if not isinstance(payload, dict):
        raise ValueError("link_audit_invalid_cursor")
    if payload.get("version") != LINK_AUDIT_PAGINATION_VERSION:
        raise ValueError("link_audit_cursor_version_unsupported")
    if payload.get("kind") != kind or payload.get("ordering") != ordering:
        raise ValueError("link_audit_invalid_cursor")
    if payload.get("filter") != fingerprint:
        raise ValueError("link_audit_cursor_filter_mismatch")
    offset = payload.get("offset")
    if not isinstance(offset, int) or offset < 0:
        raise ValueError("link_audit_invalid_cursor")
    return offset
