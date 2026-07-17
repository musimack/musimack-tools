"""Deterministic metadata-audit rules over durable page evidence."""

# ruff: noqa: C420, C901, PLR0912, PLR0913, PLR0915, PLR2004, TRY003, TRY004

from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from musimack_tools.domain.page_evidence import (
    ContentTypeCategory,
    MetadataPresence,
    PageEvidenceRecord,
    PageEvidenceState,
)

if TYPE_CHECKING:
    from datetime import datetime

METADATA_AUDIT_VERSION = "seo-toolkit-metadata-audit-v1"
METADATA_ISSUE_TAXONOMY_VERSION = "seo-toolkit-metadata-issue-taxonomy-v1"
METADATA_SEVERITY_VERSION = "seo-toolkit-audit-severity-v1"
METADATA_AUDIT_PERSISTENCE_VERSION = "seo-toolkit-metadata-audit-persistence-v1"
METADATA_AUDIT_API_VERSION = "seo-toolkit-metadata-audit-api-v1"
METADATA_AUDIT_EXPORT_VERSION = "seo-toolkit-metadata-audit-export-v1"
METADATA_AUDIT_UI_VERSION = "seo-toolkit-metadata-audit-ui-v1"
METADATA_DUPLICATE_NORMALIZATION_VERSION = "seo-toolkit-metadata-duplicate-normalization-v1"
METADATA_AUDIT_PAGINATION_VERSION = "seo-toolkit-metadata-audit-pagination-v1"
AUDIT_ORDERING = "created_at_desc_audit_id_desc-v1"
PAGE_ORDERING = "highest_severity_desc_url_identity_asc-v1"
ISSUE_ORDERING = "severity_desc_category_asc_code_asc_url_identity_asc-v1"
DUPLICATE_ORDERING = "member_count_desc_group_id_asc-v1"


class AuditState(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IssueCategory(StrEnum):
    TITLE = "title"
    META_DESCRIPTION = "meta_description"
    CANONICAL = "canonical"
    ROBOTS = "robots"
    INDEXABILITY = "indexability"
    STATUS = "status"
    CONTENT_TYPE = "content_type"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATION = "information"


class Determinacy(StrEnum):
    DETERMINATE = "determinate"
    PARTIAL = "partial"
    INDETERMINATE = "indeterminate"


class DuplicateType(StrEnum):
    TITLE = "title"
    META_DESCRIPTION = "meta_description"


class ExportFormat(StrEnum):
    CSV = "csv"
    JSON = "json"
    MARKDOWN = "markdown"


ISSUE_CATEGORY: dict[str, IssueCategory] = {
    **{
        code: IssueCategory.TITLE
        for code in (
            "title_missing",
            "title_empty",
            "title_multiple",
            "title_duplicate",
            "title_short",
            "title_long",
            "title_conflicting",
        )
    },
    **{
        code: IssueCategory.META_DESCRIPTION
        for code in (
            "meta_description_missing",
            "meta_description_empty",
            "meta_description_multiple",
            "meta_description_duplicate",
            "meta_description_short",
            "meta_description_long",
        )
    },
    **{
        code: IssueCategory.CANONICAL
        for code in (
            "canonical_missing",
            "canonical_invalid",
            "canonical_self",
            "canonical_elsewhere",
            "canonical_multiple",
            "canonical_conflicting",
            "canonical_cross_host",
            "canonical_cross_scheme",
            "canonical_cross_port",
            "canonical_target_redirected",
            "canonical_target_unavailable",
        )
    },
    **{
        code: IssueCategory.ROBOTS
        for code in (
            "robots_denied",
            "meta_robots_noindex",
            "x_robots_tag_noindex",
            "crawler_specific_directive",
            "unsupported_robots_directive",
        )
    },
    **{
        code: IssueCategory.INDEXABILITY
        for code in (
            "robots_indexability_conflict",
            "indexability_indeterminate",
            "indexability_recommendation_mismatch",
        )
    },
    **{
        code: IssueCategory.STATUS
        for code in (
            "status_redirect",
            "status_4xx",
            "status_5xx",
            "status_missing",
            "redirect_loop",
            "redirect_chain",
            "redirect_cross_host",
        )
    },
    **{
        code: IssueCategory.CONTENT_TYPE
        for code in (
            "content_type_missing",
            "content_type_ambiguous",
            "content_type_unexpected",
            "content_type_non_html",
        )
    },
}

ISSUE_SEVERITY: dict[str, Severity] = {
    **{
        code: Severity.MEDIUM
        for code in (
            "title_missing",
            "title_empty",
            "title_multiple",
            "title_duplicate",
            "title_conflicting",
            "meta_description_missing",
            "meta_description_empty",
            "meta_description_multiple",
            "meta_description_duplicate",
            "canonical_missing",
            "canonical_elsewhere",
            "canonical_multiple",
            "canonical_target_redirected",
            "meta_robots_noindex",
            "x_robots_tag_noindex",
            "robots_denied",
            "indexability_indeterminate",
            "redirect_chain",
            "redirect_cross_host",
            "content_type_unexpected",
        )
    },
    **{
        code: Severity.LOW
        for code in (
            "title_short",
            "title_long",
            "meta_description_short",
            "meta_description_long",
            "canonical_cross_host",
            "canonical_cross_scheme",
            "canonical_cross_port",
            "crawler_specific_directive",
            "content_type_missing",
            "content_type_ambiguous",
        )
    },
    **{
        code: Severity.INFORMATION
        for code in (
            "canonical_self",
            "status_redirect",
            "content_type_non_html",
            "unsupported_robots_directive",
        )
    },
    **{
        code: Severity.HIGH
        for code in (
            "canonical_invalid",
            "canonical_conflicting",
            "canonical_target_unavailable",
            "robots_indexability_conflict",
            "indexability_recommendation_mismatch",
            "status_4xx",
            "status_missing",
        )
    },
    **{code: Severity.CRITICAL for code in ("status_5xx", "redirect_loop")},
}

SEVERITY_RANK = {
    Severity.CRITICAL: 5,
    Severity.HIGH: 4,
    Severity.MEDIUM: 3,
    Severity.LOW: 2,
    Severity.INFORMATION: 1,
}


@dataclass(frozen=True, slots=True)
class MetadataAuditConfiguration:
    enabled: bool = False
    title_short_threshold: int = 20
    title_long_threshold: int = 60
    description_short_threshold: int = 70
    description_long_threshold: int = 160
    batch_size: int = 250
    default_page_size: int = 50
    maximum_page_size: int = 200
    maximum_pages: int = 100_000
    maximum_issues_per_page: int = 100
    maximum_export_rows: int = 100_000
    duplicate_sample_size: int = 20
    csv_enabled: bool = True
    json_enabled: bool = True
    markdown_enabled: bool = True
    audit_version: str = METADATA_AUDIT_VERSION
    taxonomy_version: str = METADATA_ISSUE_TAXONOMY_VERSION
    severity_version: str = METADATA_SEVERITY_VERSION
    persistence_version: str = METADATA_AUDIT_PERSISTENCE_VERSION
    api_version: str = METADATA_AUDIT_API_VERSION
    export_version: str = METADATA_AUDIT_EXPORT_VERSION
    duplicate_version: str = METADATA_DUPLICATE_NORMALIZATION_VERSION
    pagination_version: str = METADATA_AUDIT_PAGINATION_VERSION

    def __post_init__(self) -> None:
        supported = (
            (self.audit_version, METADATA_AUDIT_VERSION),
            (self.taxonomy_version, METADATA_ISSUE_TAXONOMY_VERSION),
            (self.severity_version, METADATA_SEVERITY_VERSION),
            (self.persistence_version, METADATA_AUDIT_PERSISTENCE_VERSION),
            (self.api_version, METADATA_AUDIT_API_VERSION),
            (self.export_version, METADATA_AUDIT_EXPORT_VERSION),
            (self.duplicate_version, METADATA_DUPLICATE_NORMALIZATION_VERSION),
            (self.pagination_version, METADATA_AUDIT_PAGINATION_VERSION),
        )
        if any(actual != expected for actual, expected in supported):
            raise ValueError("metadata_audit_version_unsupported")
        if not 1 <= self.title_short_threshold < self.title_long_threshold <= 1_000:
            raise ValueError("metadata audit title thresholds are invalid")
        if not 1 <= self.description_short_threshold < self.description_long_threshold <= 2_000:
            raise ValueError("metadata audit description thresholds are invalid")
        if not 1 <= self.batch_size <= 10_000:
            raise ValueError("metadata audit batch size is invalid")
        if not 1 <= self.default_page_size <= self.maximum_page_size <= 1_000:
            raise ValueError("metadata audit page sizes are invalid")
        if not 1 <= self.maximum_pages <= 1_000_000:
            raise ValueError("metadata audit page limit is invalid")
        if not 1 <= self.maximum_issues_per_page <= 1_000:
            raise ValueError("metadata audit issue limit is invalid")
        if not 1 <= self.maximum_export_rows <= 1_000_000:
            raise ValueError("metadata audit export limit is invalid")
        if not 1 <= self.duplicate_sample_size <= 1_000:
            raise ValueError("metadata audit duplicate sample limit is invalid")

    def canonical_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class AuditIssue:
    issue_id: str
    audit_id: str
    audit_page_id: str
    code: str
    category: IssueCategory
    severity: Severity
    summary: str
    detail: str
    determinacy: Determinacy
    evidence_json: str
    duplicate_group_id: str | None = None


@dataclass(frozen=True, slots=True)
class MetadataAudit:
    audit_id: str
    job_id: str
    run_id: str
    seed_url: str
    state: AuditState
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    page_count: int
    issue_count: int
    partial: bool
    failure_code: str | None
    export_available: bool
    configuration_json: str


@dataclass(frozen=True, slots=True)
class AuditPage:
    audit_page_id: str
    audit_id: str
    evidence_id: str
    url: str
    final_url: str | None
    fetch_outcome: str
    http_status: int | None
    content_type: str | None
    content_type_category: str
    title_value: str | None
    title_presence: str
    description_value: str | None
    description_presence: str
    canonical_value: str | None
    canonical_state: str
    robots_allowed: bool | None
    indexability_state: str
    recommendation_state: str | None
    issue_count: int
    highest_severity: Severity | None
    partial: bool


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    group_id: str
    audit_id: str
    duplicate_type: DuplicateType
    normalized_value_hash: str
    sample_value: str
    member_count: int
    sample_members: tuple[str, ...]
    created_at: datetime


def audit_identity(run_id: str, configuration: MetadataAuditConfiguration) -> str:
    payload = "\0".join((run_id, configuration.canonical_json()))
    return "audit-" + hashlib.sha256(payload.encode()).hexdigest()[:32]


def audit_page_identity(audit_id: str, evidence_id: str) -> str:
    return "page-" + hashlib.sha256(f"{audit_id}\0{evidence_id}".encode()).hexdigest()[:32]


def duplicate_normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    return re.sub(r"\s+", " ", normalized).casefold()


def duplicate_group_identity(audit_id: str, kind: DuplicateType, normalized: str) -> str:
    digest = hashlib.sha256(normalized.encode()).hexdigest()
    return (
        "duplicate-"
        + hashlib.sha256(f"{audit_id}\0{kind.value}\0{digest}".encode()).hexdigest()[:32]
    )


def evaluate_page(
    audit_id: str,
    page: PageEvidenceRecord,
    configuration: MetadataAuditConfiguration,
    canonical_targets: dict[str, tuple[int | None, int]] | None = None,
) -> tuple[AuditIssue, ...]:
    page_id = audit_page_identity(audit_id, page.evidence_id)
    codes: list[tuple[str, dict[str, Any]]] = []
    partial = (
        page.evidence_state
        in {
            PageEvidenceState.PARTIAL,
            PageEvidenceState.CANCELLED,
            PageEvidenceState.TRUNCATED,
            PageEvidenceState.UNAVAILABLE,
        }
        or page.value_truncated
    )

    # Status applies to attempted URLs, while missing HTML evidence never becomes empty evidence.
    if page.http_status is None:
        codes.append(("status_missing", {"fetch_outcome": page.fetch_outcome}))
    elif page.http_status is not None:
        if 400 <= page.http_status <= 499:
            codes.append(("status_4xx", {"status": page.http_status}))
        elif page.http_status >= 500:
            codes.append(("status_5xx", {"status": page.http_status}))
        elif 300 <= page.http_status <= 399 or page.redirect_count:
            codes.append(("status_redirect", {"status": page.http_status}))
    if page.redirect_loop:
        codes.append(("redirect_loop", {"redirect_count": page.redirect_count}))
    if page.redirect_count > 1:
        codes.append(("redirect_chain", {"redirect_count": page.redirect_count}))
    if any(hop.cross_host for hop in page.redirects):
        codes.append(("redirect_cross_host", {"redirect_count": page.redirect_count}))

    if page.content_type_category is ContentTypeCategory.MISSING and not page.fetch_failed:
        codes.append(("content_type_missing", {}))
    elif page.content_type_category is ContentTypeCategory.AMBIGUOUS:
        codes.append(("content_type_ambiguous", {"content_type": page.content_type}))
    elif page.content_type_category not in {ContentTypeCategory.HTML, ContentTypeCategory.MISSING}:
        codes.append(("content_type_non_html", {"content_type": page.content_type}))

    if page.parsed_as_html:
        _metadata_codes(
            codes,
            "title",
            page.title_presence,
            page.title_count,
            page.title_length,
            configuration.title_short_threshold,
            configuration.title_long_threshold,
        )
        _metadata_codes(
            codes,
            "meta_description",
            page.description_presence,
            page.description_count,
            page.description_length,
            configuration.description_short_threshold,
            configuration.description_long_threshold,
        )
        if page.canonical_presence is MetadataPresence.MISSING:
            codes.append(("canonical_missing", {}))
        elif page.canonical_presence is MetadataPresence.EMPTY:
            codes.append(("canonical_invalid", {}))
        elif page.canonical_url:
            if page.canonical_url_identity == page.final_url_identity or (
                page.final_url_identity is None
                and page.canonical_url_identity == page.requested_url_identity
            ):
                codes.append(("canonical_self", {}))
            else:
                codes.append(("canonical_elsewhere", {}))
                target = (canonical_targets or {}).get(page.canonical_url_identity or "")
                if target is None:
                    codes.append(("canonical_target_unavailable", {}))
                elif target[1] > 0 or (target[0] is not None and 300 <= target[0] <= 399):
                    codes.append(("canonical_target_redirected", {"status": target[0]}))
        if page.canonical_count > 1:
            codes.append(("canonical_multiple", {"count": page.canonical_count}))
        if page.canonical_conflicting:
            codes.append(("canonical_conflicting", {"count": page.canonical_count}))
        for condition, code in (
            (page.canonical_cross_host, "canonical_cross_host"),
            (page.canonical_cross_scheme, "canonical_cross_scheme"),
            (page.canonical_cross_port, "canonical_cross_port"),
        ):
            if condition:
                codes.append((code, {}))

    meta = page.meta_robots_json.casefold()
    xrobots = page.x_robots_json.casefold()
    if page.robots_allowed is False:
        codes.append(("robots_denied", {"reason": page.robots_reason_code}))
    if "noindex" in meta:
        codes.append(("meta_robots_noindex", {}))
    if "noindex" in xrobots:
        codes.append(("x_robots_tag_noindex", {}))
    if "crawler" in meta or "user_agent" in meta or "crawler" in xrobots:
        codes.append(("crawler_specific_directive", {}))
    if "unsupported" in meta or "unknown" in meta or "unsupported" in xrobots:
        codes.append(("unsupported_robots_directive", {}))
    if page.indexability_state.value == "conflicting":
        codes.append(("robots_indexability_conflict", {}))
    elif page.indexability_state.value == "unavailable" and not page.fetch_failed:
        codes.append(("indexability_indeterminate", {}))
    if page.parsed_as_html and page.content_type_category is not ContentTypeCategory.HTML:
        codes.append(("content_type_unexpected", {"content_type": page.content_type}))

    determinacy = Determinacy.PARTIAL if partial else Determinacy.DETERMINATE
    return tuple(
        _issue(audit_id, page_id, code, determinacy, evidence)
        for code, evidence in codes[: configuration.maximum_issues_per_page]
    )


def _metadata_codes(
    output: list[tuple[str, dict[str, Any]]],
    prefix: str,
    presence: MetadataPresence,
    count: int,
    length: int | None,
    short: int,
    long: int,
) -> None:
    if presence is MetadataPresence.MISSING:
        output.append((f"{prefix}_missing", {}))
    elif presence is MetadataPresence.EMPTY:
        output.append((f"{prefix}_empty", {}))
    elif presence is MetadataPresence.MULTIPLE:
        output.append((f"{prefix}_multiple", {"count": count}))
        if prefix == "title":
            output.append(("title_conflicting", {"count": count}))
    if presence in {MetadataPresence.SINGLE, MetadataPresence.MULTIPLE} and length is not None:
        if length < short:
            output.append((f"{prefix}_short", {"length": length, "threshold": short}))
        elif length > long:
            output.append((f"{prefix}_long", {"length": length, "threshold": long}))


def _issue(
    audit_id: str,
    page_id: str,
    code: str,
    determinacy: Determinacy,
    evidence: dict[str, Any],
    duplicate_group_id: str | None = None,
) -> AuditIssue:
    if code not in ISSUE_CATEGORY or code not in ISSUE_SEVERITY:
        raise ValueError("metadata audit issue code is unsupported")
    issue_id = "issue-" + hashlib.sha256(f"{audit_id}\0{page_id}\0{code}".encode()).hexdigest()[:32]
    label = code.replace("_", " ")
    return AuditIssue(
        issue_id,
        audit_id,
        page_id,
        code,
        ISSUE_CATEGORY[code],
        ISSUE_SEVERITY[code],
        label.capitalize(),
        f"Deterministic audit finding: {label}.",
        determinacy,
        json.dumps(evidence, sort_keys=True, separators=(",", ":")),
        duplicate_group_id,
    )


def filter_fingerprint(values: dict[str, Any]) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def encode_cursor(kind: str, ordering: str, fingerprint: str, key: list[Any]) -> str:
    payload = {
        "v": METADATA_AUDIT_PAGINATION_VERSION,
        "k": kind,
        "o": ordering,
        "f": fingerprint,
        "c": key,
    }
    return (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )


def decode_cursor(cursor: str, kind: str, ordering: str, fingerprint: str) -> list[Any]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except ValueError, TypeError, json.JSONDecodeError:
        raise ValueError("metadata_audit_invalid_cursor") from None
    if payload.get("v") != METADATA_AUDIT_PAGINATION_VERSION:
        raise ValueError("metadata_audit_cursor_version_unsupported")
    if payload.get("k") != kind or payload.get("o") != ordering:
        raise ValueError("metadata_audit_invalid_cursor")
    if payload.get("f") != fingerprint:
        raise ValueError("metadata_audit_cursor_filter_mismatch")
    key = payload.get("c")
    if not isinstance(key, list):
        raise ValueError("metadata_audit_invalid_cursor")
    return key


def severity_max(issues: tuple[AuditIssue, ...]) -> Severity | None:
    return max(
        (issue.severity for issue in issues), key=lambda value: SEVERITY_RANK[value], default=None
    )
