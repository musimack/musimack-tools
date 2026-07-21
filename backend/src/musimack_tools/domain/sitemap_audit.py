"""Typed existing-sitemap discovery, parsing, comparison, and export contracts."""

# ruff: noqa: ANN401, C901, FBT001, FBT003, PLR0911, PLR2004, TRY004

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from lxml import etree  # type: ignore[import-untyped]  # lxml has no inline typing.

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import evaluate_scope
from musimack_tools.domain.fetching import (
    CRAWLER_USER_AGENT,
    OUTBOUND_DESTINATION_POLICY_VERSION,
)
from musimack_tools.domain.page_evidence import (
    ContentTypeCategory,
    IndexabilityEvidenceState,
    PageEvidenceRecord,
    PageEvidenceState,
)
from musimack_tools.domain.sitemap import RecommendationState
from musimack_tools.domain.urls import CrawlScopePolicy, UrlErrorCode, UrlNormalizationError

if TYPE_CHECKING:
    from collections.abc import Iterable

SITEMAP_AUDIT_VERSION = "seo-toolkit-sitemap-audit-v1"
SITEMAP_AUDIT_PARSER_VERSION = "seo-toolkit-sitemap-parser-v1"
SITEMAP_COMPARISON_POLICY_VERSION = "seo-toolkit-sitemap-comparison-v1"
SITEMAP_AUDIT_PERSISTENCE_VERSION = "seo-toolkit-sitemap-audit-persistence-v1"
SITEMAP_AUDIT_API_VERSION = "seo-toolkit-sitemap-audit-api-v1"
SITEMAP_AUDIT_EXPORT_VERSION = "seo-toolkit-sitemap-audit-export-v1"
SITEMAP_AUDIT_PAGINATION_VERSION = "seo-toolkit-sitemap-audit-pagination-v1"
SITEMAP_AUDIT_UI_VERSION = "seo-toolkit-sitemap-audit-ui-v1"

AUDIT_ORDERING = "created_at_desc_audit_id_desc-v1"
DOCUMENT_ORDERING = "discovery_sequence_asc_document_id_asc-v1"
ENTRY_ORDERING = "document_sequence_asc_entry_sequence_asc_entry_id_asc-v1"
FINDING_ORDERING = "finding_sequence_asc_finding_id_asc-v1"
COMPARISON_ORDERING = "action_asc_sequence_asc_url_identity_asc-v1"

SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"
COMMON_SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml")
_FORBIDDEN_DOCTYPE = re.compile(rb"<!\s*DOCTYPE", re.IGNORECASE)
_FORBIDDEN_ENTITY = re.compile(rb"<!\s*ENTITY", re.IGNORECASE)
_XML_CONTENT_TYPES = frozenset(
    {"application/xml", "text/xml", "application/sitemap+xml", "application/rss+xml"}
)


class AuditLifecycle(StrEnum):
    ACCEPTED = "accepted"
    DISCOVERING = "discovering"
    FETCHING = "fetching"
    PARSING = "parsing"
    COMPARING = "comparing"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DiscoverySource(StrEnum):
    EXPLICIT = "explicit"
    ROBOTS = "robots"
    COMMON_LOCATION = "common_location"
    CHILD_INDEX = "child_index"


class SitemapRootType(StrEnum):
    URLSET = "urlset"
    SITEMAP_INDEX = "sitemapindex"
    UNSUPPORTED = "unsupported"


class FetchState(StrEnum):
    PENDING = "pending"
    FETCHED = "fetched"
    FAILED = "failed"
    SKIPPED = "skipped"


class ParseState(StrEnum):
    PENDING = "pending"
    PARSED = "parsed"
    PARSED_WITH_WARNINGS = "parsed_with_warnings"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"
    NOT_APPLICABLE = "not_applicable"


class ValidationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFORMATION = "information"


class ValidationCode(StrEnum):
    INVALID_XML = "invalid_xml"
    DOCTYPE_FORBIDDEN = "doctype_forbidden"
    ENTITY_DECLARATION_FORBIDDEN = "entity_declaration_forbidden"
    INVALID_NAMESPACE = "invalid_namespace"
    UNSUPPORTED_ROOT_ELEMENT = "unsupported_root_element"
    MISSING_LOCATION = "missing_location"
    EMPTY_LOCATION = "empty_location"
    INVALID_LOCATION = "invalid_location"
    UNSUPPORTED_SCHEME = "unsupported_scheme"
    OUT_OF_SCOPE_LOCATION = "out_of_scope_location"
    DUPLICATE_LOCATION = "duplicate_location"
    UNEXPECTED_CONTENT_TYPE = "unexpected_content_type"
    RESPONSE_TOO_LARGE = "response_too_large"
    URL_COUNT_LIMIT_EXCEEDED = "url_count_limit_exceeded"
    CHILD_COUNT_LIMIT_EXCEEDED = "child_count_limit_exceeded"
    TOTAL_URL_LIMIT_EXCEEDED = "total_url_limit_exceeded"
    SITEMAP_DOCUMENT_LIMIT_EXCEEDED = "sitemap_document_limit_exceeded"
    MAXIMUM_DEPTH_EXCEEDED = "maximum_depth_exceeded"
    CHILD_FETCH_FAILED = "child_fetch_failed"
    SITEMAP_INDEX_LOOP = "sitemap_index_loop"
    EMPTY_URL_SET = "empty_url_set"
    EMPTY_SITEMAP_INDEX = "empty_sitemap_index"
    GZIP_NOT_SUPPORTED = "gzip_not_supported"
    FETCH_FAILED = "fetch_failed"
    HTTP_ERROR = "http_error"
    REDIRECT_ALIAS_DUPLICATE = "redirect_alias_duplicate"
    ROBOTS_SITEMAP_INVALID = "robots_sitemap_invalid"


class ComparisonAction(StrEnum):
    ADD = "add"
    REMOVE = "remove"
    REVIEW = "review"
    UNCHANGED = "unchanged"


class ComparisonState(StrEnum):
    IN_SITEMAP_AND_ELIGIBLE = "in_sitemap_and_eligible"
    IN_SITEMAP_BUT_EXCLUDED = "in_sitemap_but_excluded"
    MISSING_FROM_SITEMAP = "missing_from_sitemap"
    REDIRECTED_SITEMAP_URL = "redirected_sitemap_url"
    NOINDEX_SITEMAP_URL = "noindex_sitemap_url"
    CANONICALIZED_SITEMAP_URL = "canonicalized_sitemap_url"
    NON_HTML_SITEMAP_URL = "non_html_sitemap_url"
    SITEMAP_ONLY_UNVERIFIED = "sitemap_only_unverified"


class ComparisonReason(StrEnum):
    ELIGIBLE_ALREADY_PRESENT = "eligible_already_present"
    ELIGIBLE_MISSING_FROM_SITEMAP = "eligible_missing_from_sitemap"
    RECOMMENDATION_EXCLUDE = "recommendation_exclude"
    RECOMMENDATION_REVIEW = "recommendation_review"
    RECOMMENDATION_INDETERMINATE = "recommendation_indeterminate"
    REDIRECTED_URL = "redirected_url"
    NOINDEX_URL = "noindex_url"
    CANONICAL_POINTS_ELSEWHERE = "canonical_points_elsewhere"
    NON_HTML_CONTENT = "non_html_content"
    NOT_OBSERVED_IN_SELECTED_CRAWL = "not_observed_in_selected_crawl"
    CRAWL_EVIDENCE_FAILED = "crawl_evidence_failed"
    INVALID_SITEMAP_LOCATION = "invalid_sitemap_location"
    OUT_OF_SCOPE_SITEMAP_LOCATION = "out_of_scope_sitemap_location"
    REDIRECT_TARGET_REQUIRES_REVIEW = "redirect_target_requires_review"
    CANONICAL_TARGET_REQUIRES_REVIEW = "canonical_target_requires_review"


class ExportFormat(StrEnum):
    CSV = "csv"
    JSON = "json"
    MARKDOWN = "markdown"


@dataclass(frozen=True, slots=True)
class SitemapAuditConfiguration:
    enabled: bool = False
    maximum_response_bytes: int = 5_000_000
    maximum_urlset_entries: int = 50_000
    maximum_index_children: int = 50_000
    maximum_documents: int = 100
    maximum_depth: int = 3
    maximum_total_urls: int = 250_000
    maximum_duration_seconds: float = 300.0
    maximum_accepted_bytes: int = 50_000_000
    minimum_request_delay_seconds: float = 0.0
    maximum_redirect_hops: int = 5
    dns_timeout_seconds: float = 5.0
    destination_policy_version: str = OUTBOUND_DESTINATION_POLICY_VERSION
    crawler_user_agent: str = CRAWLER_USER_AGENT
    authorization_enabled: bool = False
    authorization_version: int | None = None
    retry_policy: str = "none"
    recovery_policy: str = "reuse_immutable_configuration"
    default_page_size: int = 50
    maximum_page_size: int = 200
    maximum_export_rows: int = 100_000
    retention_days: int = 180
    csv_enabled: bool = True
    json_enabled: bool = True
    markdown_enabled: bool = True
    audit_version: str = SITEMAP_AUDIT_VERSION
    parser_version: str = SITEMAP_AUDIT_PARSER_VERSION
    comparison_version: str = SITEMAP_COMPARISON_POLICY_VERSION
    persistence_version: str = SITEMAP_AUDIT_PERSISTENCE_VERSION
    api_version: str = SITEMAP_AUDIT_API_VERSION
    export_version: str = SITEMAP_AUDIT_EXPORT_VERSION
    pagination_version: str = SITEMAP_AUDIT_PAGINATION_VERSION

    def __post_init__(self) -> None:
        expected = (
            (self.audit_version, SITEMAP_AUDIT_VERSION),
            (self.parser_version, SITEMAP_AUDIT_PARSER_VERSION),
            (self.comparison_version, SITEMAP_COMPARISON_POLICY_VERSION),
            (self.persistence_version, SITEMAP_AUDIT_PERSISTENCE_VERSION),
            (self.api_version, SITEMAP_AUDIT_API_VERSION),
            (self.export_version, SITEMAP_AUDIT_EXPORT_VERSION),
            (self.pagination_version, SITEMAP_AUDIT_PAGINATION_VERSION),
        )
        if any(actual != supported for actual, supported in expected):
            raise ValueError("sitemap_audit_version_unsupported")
        bounds = (
            (self.maximum_response_bytes, 1, 50_000_000),
            (self.maximum_urlset_entries, 1, 50_000),
            (self.maximum_index_children, 1, 50_000),
            (self.maximum_documents, 1, 1_000),
            (self.maximum_depth, 0, 10),
            (self.maximum_total_urls, 1, 1_000_000),
            (self.maximum_duration_seconds, 1, 86_400),
            (self.maximum_accepted_bytes, 1, 1_000_000_000),
            (self.minimum_request_delay_seconds, 0, 60),
            (self.maximum_redirect_hops, 0, 20),
            (self.dns_timeout_seconds, 0.1, 60),
            (self.default_page_size, 1, 1_000),
            (self.maximum_page_size, 1, 1_000),
            (self.maximum_export_rows, 1, 1_000_000),
            (self.retention_days, 1, 3_650),
        )
        if any(not low <= value <= high for value, low, high in bounds):
            raise ValueError("sitemap_audit_configuration_invalid")
        if self.default_page_size > self.maximum_page_size:
            raise ValueError("sitemap_audit_configuration_invalid")
        if self.destination_policy_version != OUTBOUND_DESTINATION_POLICY_VERSION:
            raise ValueError("sitemap_audit_configuration_invalid")
        if self.crawler_user_agent != CRAWLER_USER_AGENT:
            raise ValueError("sitemap_audit_configuration_invalid")
        if self.retry_policy != "none" or self.recovery_policy != "reuse_immutable_configuration":
            raise ValueError("sitemap_audit_configuration_invalid")

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DiscoveryOptions:
    explicit_url: str | None = None
    discover_robots: bool = True
    discover_common_locations: bool = True


@dataclass(frozen=True, slots=True)
class SitemapCandidate:
    normalized_url: str
    discovery_source: DiscoverySource
    discovery_sequence: int
    provenance: tuple[DiscoverySource, ...]
    raw_url: str


@dataclass(frozen=True, slots=True)
class SitemapFinding:
    code: ValidationCode
    severity: ValidationSeverity
    message: str
    sequence: int
    raw_url: str | None = None
    normalized_url: str | None = None
    entry_sequence: int | None = None
    context: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedEntry:
    raw_location: str | None
    normalized_url: str | None
    entry_sequence: int
    in_scope: bool | None
    valid: bool
    duplicate: bool


@dataclass(frozen=True, slots=True)
class ParsedSitemap:
    root_type: SitemapRootType
    parse_state: ParseState
    namespace: str | None
    entries: tuple[ParsedEntry, ...]
    children: tuple[ParsedEntry, ...]
    findings: tuple[SitemapFinding, ...]


@dataclass(frozen=True, slots=True)
class ComparisonInput:
    evidence_id: str
    requested_url: str
    requested_identity: str
    final_url: str | None
    final_identity: str | None
    fetch_failed: bool
    http_status: int | None
    redirect_count: int
    content_type: str | None
    content_type_category: ContentTypeCategory
    parsed_as_html: bool
    canonical_url: str | None
    canonical_identity: str | None
    indexability_json: str
    indexability_state: IndexabilityEvidenceState
    evidence_state: PageEvidenceState


@dataclass(frozen=True, slots=True)
class ComparisonRecord:
    url_identity: str
    url: str
    in_sitemap: bool
    representative_entry_id: str | None
    evidence_id: str | None
    recommendation_state: RecommendationState | None
    comparison_state: ComparisonState
    action: ComparisonAction
    reason: ComparisonReason
    http_status: int | None
    redirect_target: str | None
    canonical_target: str | None
    indexability_state: str | None
    content_type: str | None
    crawl_evidence_state: str | None
    sequence: int


def audit_identity(
    run_id: str, options: DiscoveryOptions, config: SitemapAuditConfiguration
) -> str:
    canonical = json.dumps(
        {"run_id": run_id, "options": asdict(options), "configuration": config.snapshot()},
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sitemap-audit-" + hashlib.sha256(canonical.encode()).hexdigest()[:32]


def document_identity(audit_id: str, normalized_url: str) -> str:
    return (
        "sitemap-doc-" + hashlib.sha256(f"{audit_id}\0{normalized_url}".encode()).hexdigest()[:32]
    )


def entry_identity(document_id: str, sequence: int, raw_location: str | None) -> str:
    value = raw_location or ""
    return (
        "sitemap-entry-"
        + hashlib.sha256(f"{document_id}\0{sequence}\0{value}".encode()).hexdigest()[:32]
    )


def finding_identity(audit_id: str, document_id: str | None, finding: SitemapFinding) -> str:
    return (
        "sitemap-finding-"
        + hashlib.sha256(
            f"{audit_id}\0{document_id or ''}\0{finding.sequence}\0{finding.code.value}".encode()
        ).hexdigest()[:32]
    )


def comparison_identity(audit_id: str, url_identity: str) -> str:
    return (
        "sitemap-comparison-"
        + hashlib.sha256(f"{audit_id}\0{url_identity}".encode()).hexdigest()[:32]
    )


def parse_sitemap(
    body: bytes,
    *,
    content_type: str | None,
    document_url: str,
    scope: CrawlScopePolicy,
    configuration: SitemapAuditConfiguration,
) -> ParsedSitemap:
    """Parse one already-bounded response without network or external entity access."""
    findings: list[SitemapFinding] = []
    if document_url.lower().split("?", 1)[0].endswith(".gz") or _is_gzip(content_type, body):
        return _invalid(ValidationCode.GZIP_NOT_SUPPORTED, "Gzip sitemaps are not supported")
    if len(body) > configuration.maximum_response_bytes:
        return _invalid(ValidationCode.RESPONSE_TOO_LARGE, "Sitemap response exceeded the limit")
    if _FORBIDDEN_DOCTYPE.search(body):
        return _invalid(ValidationCode.DOCTYPE_FORBIDDEN, "DOCTYPE declarations are forbidden")
    if _FORBIDDEN_ENTITY.search(body):
        return _invalid(
            ValidationCode.ENTITY_DECLARATION_FORBIDDEN,
            "Entity declarations are forbidden",
        )
    media_type = _media_type(content_type)
    if media_type == "text/html" and _looks_html(body):
        return _invalid(
            ValidationCode.UNEXPECTED_CONTENT_TYPE,
            "An HTML response is not accepted as a sitemap",
        )
    if media_type and media_type not in _XML_CONTENT_TYPES and not media_type.endswith("+xml"):
        findings.append(
            SitemapFinding(
                ValidationCode.UNEXPECTED_CONTENT_TYPE,
                ValidationSeverity.WARNING,
                "Valid XML may be parsed despite an imperfect content type",
                1,
                context=(("content_type", media_type[:128]),),
            )
        )
    try:
        parser = etree.XMLParser(
            resolve_entities=False,
            load_dtd=False,
            no_network=True,
            recover=False,
            huge_tree=False,
            remove_comments=False,
        )
        root = etree.fromstring(body, parser=parser)
    except etree.XMLSyntaxError, ValueError:
        return _invalid(ValidationCode.INVALID_XML, "The sitemap XML is invalid")
    qualified = etree.QName(root)
    namespace = qualified.namespace
    try:
        root_type = SitemapRootType(qualified.localname.lower())
    except ValueError:
        return _invalid(
            ValidationCode.UNSUPPORTED_ROOT_ELEMENT,
            "Only urlset and sitemapindex roots are supported",
        )
    if namespace != SITEMAP_NAMESPACE:
        findings.append(
            SitemapFinding(
                ValidationCode.INVALID_NAMESPACE,
                ValidationSeverity.WARNING,
                "The sitemap namespace is missing or unsupported",
                len(findings) + 1,
                context=(("namespace", namespace or "missing"),),
            )
        )
    member_name = "url" if root_type is SitemapRootType.URLSET else "sitemap"
    limit = (
        configuration.maximum_urlset_entries
        if root_type is SitemapRootType.URLSET
        else configuration.maximum_index_children
    )
    parsed: list[ParsedEntry] = []
    seen: dict[str, int] = {}
    members = [child for child in root if etree.QName(child).localname.lower() == member_name]
    if len(members) > limit:
        findings.append(
            SitemapFinding(
                (
                    ValidationCode.URL_COUNT_LIMIT_EXCEEDED
                    if root_type is SitemapRootType.URLSET
                    else ValidationCode.CHILD_COUNT_LIMIT_EXCEEDED
                ),
                ValidationSeverity.ERROR,
                "The sitemap entry limit was reached; partial evidence was retained",
                len(findings) + 1,
                context=(("observed", str(len(members))), ("limit", str(limit))),
            )
        )
        members = members[:limit]
    for sequence, member in enumerate(members):
        parsed.append(_parse_member(member, sequence, scope, seen, findings))
    if not parsed:
        findings.append(
            SitemapFinding(
                (
                    ValidationCode.EMPTY_URL_SET
                    if root_type is SitemapRootType.URLSET
                    else ValidationCode.EMPTY_SITEMAP_INDEX
                ),
                ValidationSeverity.WARNING,
                "The sitemap document contains no location entries",
                len(findings) + 1,
            )
        )
    warning = bool(findings)
    entries = tuple(parsed) if root_type is SitemapRootType.URLSET else ()
    children = tuple(parsed) if root_type is SitemapRootType.SITEMAP_INDEX else ()
    return ParsedSitemap(
        root_type,
        ParseState.PARSED_WITH_WARNINGS if warning else ParseState.PARSED,
        namespace,
        entries,
        children,
        tuple(findings),
    )


def comparison_input(page: PageEvidenceRecord) -> ComparisonInput:
    return ComparisonInput(
        page.evidence_id,
        page.requested_url,
        page.requested_url_identity,
        page.final_url,
        page.final_url_identity,
        page.fetch_failed,
        page.http_status,
        page.redirect_count,
        page.content_type,
        page.content_type_category,
        page.parsed_as_html,
        page.canonical_url,
        page.canonical_url_identity,
        page.indexability_evidence_json,
        page.indexability_state,
        page.evidence_state,
    )


def compare_evidence(
    sitemap_entries: dict[str, tuple[str, str]],
    pages: Iterable[ComparisonInput],
) -> tuple[ComparisonRecord, ...]:
    """Compare the deterministic union of sitemap and durable page evidence."""
    page_map = {page.requested_identity: page for page in pages}
    identities = sorted(set(sitemap_entries) | set(page_map))
    records: list[ComparisonRecord] = []
    for sequence, identity in enumerate(identities):
        page = page_map.get(identity)
        entry = sitemap_entries.get(identity)
        present = entry is not None
        recommendation = _recommendation(page)
        state, action, reason = _classification(present, page, recommendation)
        records.append(
            ComparisonRecord(
                identity,
                entry[1] if entry else page.requested_url if page else identity,
                present,
                entry[0] if entry else None,
                page.evidence_id if page else None,
                recommendation,
                state,
                action,
                reason,
                page.http_status if page else None,
                page.final_url if page and page.redirect_count else None,
                page.canonical_url if page else None,
                page.indexability_state.value if page else None,
                page.content_type if page else None,
                page.evidence_state.value if page else None,
                sequence,
            )
        )
    return tuple(records)


def filter_fingerprint(values: dict[str, Any]) -> str:
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def encode_cursor(kind: str, ordering: str, fingerprint: str, offset: int) -> str:
    payload = json.dumps(
        {
            "version": SITEMAP_AUDIT_PAGINATION_VERSION,
            "kind": kind,
            "ordering": ordering,
            "filter": fingerprint,
            "offset": offset,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    import base64  # noqa: PLC0415 - keeps encoding beside decoding.

    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(value: str, kind: str, ordering: str, fingerprint: str) -> int:
    import base64  # noqa: PLC0415 - keeps encoding beside decoding.

    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding))
    except ValueError, TypeError, json.JSONDecodeError:
        raise ValueError("sitemap_audit_invalid_cursor") from None
    if not isinstance(payload, dict):
        raise ValueError("sitemap_audit_invalid_cursor")
    if payload.get("version") != SITEMAP_AUDIT_PAGINATION_VERSION:
        raise ValueError("sitemap_audit_cursor_version_unsupported")
    if payload.get("kind") != kind or payload.get("ordering") != ordering:
        raise ValueError("sitemap_audit_invalid_cursor")
    if payload.get("filter") != fingerprint:
        raise ValueError("sitemap_audit_cursor_filter_mismatch")
    offset = payload.get("offset")
    if not isinstance(offset, int) or offset < 0:
        raise ValueError("sitemap_audit_invalid_cursor")
    return offset


def now_utc() -> datetime:
    return datetime.now(UTC)


def _parse_member(
    member: Any,
    sequence: int,
    scope: CrawlScopePolicy,
    seen: dict[str, int],
    findings: list[SitemapFinding],
) -> ParsedEntry:
    locs = [child for child in member if etree.QName(child).localname.lower() == "loc"]
    if not locs:
        findings.append(
            SitemapFinding(
                ValidationCode.MISSING_LOCATION,
                ValidationSeverity.ERROR,
                "A sitemap record has no loc element",
                len(findings) + 1,
                entry_sequence=sequence,
            )
        )
        return ParsedEntry(None, None, sequence, None, False, False)
    raw = locs[0].text
    cleaned = raw.strip() if raw is not None else ""
    if not cleaned:
        findings.append(
            SitemapFinding(
                ValidationCode.EMPTY_LOCATION,
                ValidationSeverity.ERROR,
                "A sitemap loc value is empty",
                len(findings) + 1,
                raw_url=raw,
                entry_sequence=sequence,
            )
        )
        return ParsedEntry(raw, None, sequence, None, False, False)
    try:
        normalized = normalize_url(cleaned)
    except UrlNormalizationError as error:
        code = (
            ValidationCode.UNSUPPORTED_SCHEME
            if error.code is UrlErrorCode.UNSUPPORTED_SCHEME
            else ValidationCode.INVALID_LOCATION
        )
        findings.append(
            SitemapFinding(
                code,
                ValidationSeverity.ERROR,
                "A sitemap loc value is not a supported absolute HTTP URL",
                len(findings) + 1,
                raw_url=cleaned[:4096],
                entry_sequence=sequence,
            )
        )
        return ParsedEntry(cleaned[:4096], None, sequence, None, False, False)
    scope_decision = evaluate_scope(scope, normalized)
    if not scope_decision.allowed:
        findings.append(
            SitemapFinding(
                ValidationCode.OUT_OF_SCOPE_LOCATION,
                ValidationSeverity.WARNING,
                "A sitemap loc value is outside the selected crawl scope",
                len(findings) + 1,
                raw_url=cleaned[:4096],
                normalized_url=normalized.normalized,
                entry_sequence=sequence,
            )
        )
        return ParsedEntry(cleaned[:4096], normalized.normalized, sequence, False, False, False)
    duplicate = normalized.normalized in seen
    if duplicate:
        findings.append(
            SitemapFinding(
                ValidationCode.DUPLICATE_LOCATION,
                ValidationSeverity.INFORMATION,
                "A normalized sitemap location is duplicated",
                len(findings) + 1,
                raw_url=cleaned[:4096],
                normalized_url=normalized.normalized,
                entry_sequence=sequence,
                context=(("first_sequence", str(seen[normalized.normalized])),),
            )
        )
    else:
        seen[normalized.normalized] = sequence
    return ParsedEntry(cleaned[:4096], normalized.normalized, sequence, True, True, duplicate)


def _invalid(code: ValidationCode, message: str) -> ParsedSitemap:
    state = (
        ParseState.UNSUPPORTED if code is ValidationCode.GZIP_NOT_SUPPORTED else ParseState.INVALID
    )
    return ParsedSitemap(
        SitemapRootType.UNSUPPORTED,
        state,
        None,
        (),
        (),
        (SitemapFinding(code, ValidationSeverity.ERROR, message, 1),),
    )


def _media_type(content_type: str | None) -> str | None:
    return content_type.split(";", 1)[0].strip().lower() if content_type else None


def _looks_html(body: bytes) -> bool:
    sample = body[:512].lstrip().lower()
    return sample.startswith((b"<!doctype html", b"<html", b"<head", b"<body"))


def _is_gzip(content_type: str | None, body: bytes) -> bool:
    media = _media_type(content_type)
    return media in {"application/gzip", "application/x-gzip"} or body.startswith(b"\x1f\x8b")


def _recommendation(page: ComparisonInput | None) -> RecommendationState | None:
    if page is None:
        return None
    if page.fetch_failed or page.evidence_state in {
        PageEvidenceState.FETCH_FAILED,
        PageEvidenceState.UNAVAILABLE,
    }:
        return RecommendationState.INDETERMINATE
    if page.redirect_count:
        return RecommendationState.EXCLUDE
    if _is_noindex(page.indexability_json):
        return RecommendationState.EXCLUDE
    if page.canonical_identity and page.canonical_identity != page.requested_identity:
        return RecommendationState.EXCLUDE
    if page.content_type_category is not ContentTypeCategory.HTML or not page.parsed_as_html:
        return RecommendationState.EXCLUDE
    if page.http_status == 200:
        return RecommendationState.INCLUDE
    return RecommendationState.REVIEW


def _classification(
    present: bool,
    page: ComparisonInput | None,
    recommendation: RecommendationState | None,
) -> tuple[ComparisonState, ComparisonAction, ComparisonReason]:
    if page is None:
        return (
            ComparisonState.SITEMAP_ONLY_UNVERIFIED,
            ComparisonAction.REVIEW,
            ComparisonReason.NOT_OBSERVED_IN_SELECTED_CRAWL,
        )
    if present and page.redirect_count:
        deterministic = bool(page.final_identity)
        return (
            ComparisonState.REDIRECTED_SITEMAP_URL,
            ComparisonAction.REMOVE if deterministic else ComparisonAction.REVIEW,
            (
                ComparisonReason.REDIRECTED_URL
                if deterministic
                else ComparisonReason.REDIRECT_TARGET_REQUIRES_REVIEW
            ),
        )
    if present and _is_noindex(page.indexability_json):
        return (
            ComparisonState.NOINDEX_SITEMAP_URL,
            ComparisonAction.REMOVE,
            ComparisonReason.NOINDEX_URL,
        )
    if present and page.canonical_identity and page.canonical_identity != page.requested_identity:
        deterministic = bool(page.canonical_url)
        return (
            ComparisonState.CANONICALIZED_SITEMAP_URL,
            ComparisonAction.REMOVE if deterministic else ComparisonAction.REVIEW,
            (
                ComparisonReason.CANONICAL_POINTS_ELSEWHERE
                if deterministic
                else ComparisonReason.CANONICAL_TARGET_REQUIRES_REVIEW
            ),
        )
    if (
        present
        and page.content_type_category is not ContentTypeCategory.MISSING
        and (page.content_type_category is not ContentTypeCategory.HTML or not page.parsed_as_html)
    ):
        return (
            ComparisonState.NON_HTML_SITEMAP_URL,
            ComparisonAction.REMOVE,
            ComparisonReason.NON_HTML_CONTENT,
        )
    if page.fetch_failed:
        return (
            ComparisonState.SITEMAP_ONLY_UNVERIFIED,
            ComparisonAction.REVIEW,
            ComparisonReason.CRAWL_EVIDENCE_FAILED,
        )
    if present and recommendation is RecommendationState.EXCLUDE:
        return (
            ComparisonState.IN_SITEMAP_BUT_EXCLUDED,
            ComparisonAction.REMOVE,
            ComparisonReason.RECOMMENDATION_EXCLUDE,
        )
    if present and recommendation is RecommendationState.REVIEW:
        return (
            ComparisonState.IN_SITEMAP_BUT_EXCLUDED,
            ComparisonAction.REVIEW,
            ComparisonReason.RECOMMENDATION_REVIEW,
        )
    if present and recommendation is RecommendationState.INDETERMINATE:
        return (
            ComparisonState.IN_SITEMAP_BUT_EXCLUDED,
            ComparisonAction.REVIEW,
            ComparisonReason.RECOMMENDATION_INDETERMINATE,
        )
    if present:
        return (
            ComparisonState.IN_SITEMAP_AND_ELIGIBLE,
            ComparisonAction.UNCHANGED,
            ComparisonReason.ELIGIBLE_ALREADY_PRESENT,
        )
    if recommendation is RecommendationState.INCLUDE:
        return (
            ComparisonState.MISSING_FROM_SITEMAP,
            ComparisonAction.ADD,
            ComparisonReason.ELIGIBLE_MISSING_FROM_SITEMAP,
        )
    reason = (
        ComparisonReason.RECOMMENDATION_EXCLUDE
        if recommendation is RecommendationState.EXCLUDE
        else ComparisonReason.RECOMMENDATION_REVIEW
        if recommendation is RecommendationState.REVIEW
        else ComparisonReason.RECOMMENDATION_INDETERMINATE
    )
    return ComparisonState.IN_SITEMAP_BUT_EXCLUDED, ComparisonAction.REVIEW, reason


def _is_noindex(value: str) -> bool:
    lowered = value.casefold()
    return '"noindex"' in lowered or "noindex" in lowered
