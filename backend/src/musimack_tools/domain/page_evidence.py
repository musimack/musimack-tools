"""Bounded durable projections of accepted page-level crawl evidence."""

from __future__ import annotations

import base64
import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from musimack_tools.domain.crawl import CrawlResult, UrlCrawlRecord
    from musimack_tools.domain.fetching import FetchResult
    from musimack_tools.domain.html import HtmlParseResult, TextMetadataEvidence

PAGE_EVIDENCE_VERSION = "seo-toolkit-page-crawl-evidence-v1"
PAGE_EVIDENCE_PERSISTENCE_VERSION = "seo-toolkit-page-crawl-evidence-persistence-v1"
PAGE_EVIDENCE_QUERY_VERSION = "seo-toolkit-page-crawl-evidence-query-v1"
PAGE_EVIDENCE_RETENTION_VERSION = "seo-toolkit-page-crawl-evidence-retention-v1"
PAGE_EVIDENCE_PROJECTION_VERSION = "seo-toolkit-page-crawl-evidence-projection-v1"
PAGE_EVIDENCE_PAGINATION_VERSION = "seo-toolkit-page-crawl-evidence-pagination-v1"
PAGE_EVIDENCE_ORDERING = "crawl_discovery_sequence_asc_url_identity_asc-v1"
LINK_EVIDENCE_VERSION = "seo-toolkit-link-evidence-v1"
IMAGE_EVIDENCE_VERSION = "seo-toolkit-image-evidence-v1"
_MAX_BATCH_SIZE = 10_000
_MAX_PAGE_SIZE = 1_000
_MAX_PAGES_PER_RUN = 1_000_000
_MAX_REDIRECT_HOPS = 100
_MAX_WARNINGS = 1_000
_MAX_SRCSET_CANDIDATES = 100
_MIN_METADATA_CHARS = 64
_MAX_METADATA_CHARS = 65_536
_MAX_RETENTION_DAYS = 3_650
_INVALID_BATCH = "page evidence batch size must be between 1 and 10000"
_INVALID_PAGE_SIZES = "page evidence page sizes are invalid"
_INVALID_RUN_LIMIT = "page evidence run limit is invalid"
_INVALID_REDIRECT_LIMIT = "page evidence redirect limit is invalid"
_INVALID_WARNING_LIMIT = "page evidence warning limit is invalid"
_INVALID_METADATA_BOUND = "page evidence metadata bound is invalid"
_INVALID_RETENTION = "page evidence retention is invalid"
_INVALID_CLEANUP_BATCH = "page evidence cleanup batch size is invalid"


class PageEvidenceState(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FETCH_FAILED = "fetch_failed"
    NOT_HTML = "not_html"
    CANCELLED = "cancelled"
    TRUNCATED = "truncated"
    UNAVAILABLE = "unavailable"


class MetadataPresence(StrEnum):
    MISSING = "missing"
    EMPTY = "empty"
    SINGLE = "single"
    MULTIPLE = "multiple"
    UNAVAILABLE = "unavailable"


class ContentTypeCategory(StrEnum):
    HTML = "html"
    PDF = "pdf"
    IMAGE = "image"
    JSON = "json"
    PLAIN_TEXT = "plain_text"
    XML = "xml"
    OTHER = "other"
    AMBIGUOUS = "ambiguous"
    MISSING = "missing"


class PageEvidenceRetentionState(StrEnum):
    ACTIVE = "active"
    RETAINED = "retained"
    EXPIRED = "expired"
    CLEANUP_PENDING = "cleanup_pending"
    DELETED = "deleted"
    METADATA_ONLY = "metadata_only"


class IndexabilityEvidenceState(StrEnum):
    AVAILABLE = "available"
    CONFLICTING = "conflicting"
    UNAVAILABLE = "unavailable"


class PageEvidenceReasonCode(StrEnum):
    DISABLED = "page_evidence_disabled"
    VERSION_UNSUPPORTED = "page_evidence_version_unsupported"
    RUN_NOT_FOUND = "page_evidence_run_not_found"
    JOB_NOT_FOUND = "page_evidence_job_not_found"
    CRAWL_RESULT_UNAVAILABLE = "page_evidence_crawl_result_unavailable"
    LIMIT_EXCEEDED = "page_evidence_limit_exceeded"
    PERSISTENCE_FAILED = "page_evidence_persistence_failed"
    PARTIAL = "page_evidence_partial"
    CONFLICT = "page_evidence_conflict"
    NOT_FOUND = "page_evidence_not_found"
    INVALID_FILTER = "page_evidence_invalid_filter"
    INVALID_PAGE_SIZE = "page_evidence_invalid_page_size"
    INVALID_CURSOR = "page_evidence_invalid_cursor"
    CURSOR_VERSION_UNSUPPORTED = "page_evidence_cursor_version_unsupported"
    CURSOR_FILTER_MISMATCH = "page_evidence_cursor_filter_mismatch"
    QUERY_FAILED = "page_evidence_query_failed"
    RETENTION_INVALID = "page_evidence_retention_invalid"
    CLEANUP_FAILED = "page_evidence_cleanup_failed"
    RECONCILIATION_FAILED = "page_evidence_reconciliation_failed"
    TRUNCATED = "page_evidence_truncated"


@dataclass(frozen=True, slots=True)
class PageEvidenceConfiguration:
    enabled: bool = False
    evidence_version: str = PAGE_EVIDENCE_VERSION
    persistence_version: str = PAGE_EVIDENCE_PERSISTENCE_VERSION
    query_version: str = PAGE_EVIDENCE_QUERY_VERSION
    retention_version: str = PAGE_EVIDENCE_RETENTION_VERSION
    projection_version: str = PAGE_EVIDENCE_PROJECTION_VERSION
    batch_size: int = 250
    default_page_size: int = 50
    maximum_page_size: int = 200
    maximum_pages_per_run: int = 100_000
    maximum_redirect_hops: int = 20
    maximum_parse_warnings_per_page: int = 50
    maximum_metadata_characters: int = 4_096
    retention_days: int = 180
    preserve_terminal_failures: bool = True
    persist_partial_runs: bool = True
    cleanup_batch_size: int = 500

    def __post_init__(self) -> None:
        expected = (
            (self.evidence_version, PAGE_EVIDENCE_VERSION),
            (self.persistence_version, PAGE_EVIDENCE_PERSISTENCE_VERSION),
            (self.query_version, PAGE_EVIDENCE_QUERY_VERSION),
            (self.retention_version, PAGE_EVIDENCE_RETENTION_VERSION),
            (self.projection_version, PAGE_EVIDENCE_PROJECTION_VERSION),
        )
        if any(actual != supported for actual, supported in expected):
            raise ValueError(PageEvidenceReasonCode.VERSION_UNSUPPORTED)
        if not 1 <= self.batch_size <= _MAX_BATCH_SIZE:
            raise ValueError(_INVALID_BATCH)
        if not 1 <= self.default_page_size <= self.maximum_page_size <= _MAX_PAGE_SIZE:
            raise ValueError(_INVALID_PAGE_SIZES)
        if not 1 <= self.maximum_pages_per_run <= _MAX_PAGES_PER_RUN:
            raise ValueError(_INVALID_RUN_LIMIT)
        if not 1 <= self.maximum_redirect_hops <= _MAX_REDIRECT_HOPS:
            raise ValueError(_INVALID_REDIRECT_LIMIT)
        if not 1 <= self.maximum_parse_warnings_per_page <= _MAX_WARNINGS:
            raise ValueError(_INVALID_WARNING_LIMIT)
        if not _MIN_METADATA_CHARS <= self.maximum_metadata_characters <= _MAX_METADATA_CHARS:
            raise ValueError(_INVALID_METADATA_BOUND)
        if not 1 <= self.retention_days <= _MAX_RETENTION_DAYS:
            raise ValueError(_INVALID_RETENTION)
        if not 1 <= self.cleanup_batch_size <= _MAX_BATCH_SIZE:
            raise ValueError(_INVALID_CLEANUP_BATCH)


@dataclass(frozen=True, slots=True)
class PageParseWarningEvidence:
    warning_id: str
    sequence: int
    code: str
    category: str
    safe_summary: str


@dataclass(frozen=True, slots=True)
class PageRedirectEvidence:
    sequence: int
    source_url: str
    target_url: str | None
    status_code: int
    cross_host: bool
    terminal: bool
    loop: bool
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class PageEvidenceRecord:
    evidence_id: str
    job_id: str
    run_id: str
    requested_url: str
    requested_url_identity: str
    final_url: str | None
    final_url_identity: str | None
    discovery_sequence: int
    crawl_depth: int
    referrer_url: str | None
    frontier_state: str
    fetch_outcome: str
    http_status: int | None
    status_class: int | None
    fetch_failed: bool
    redirect_count: int
    redirect_truncated: bool
    redirect_loop: bool
    content_type: str | None
    content_type_category: ContentTypeCategory
    charset: str | None
    parsed_as_html: bool
    parse_outcome: str | None
    title_presence: MetadataPresence
    title_value: str | None
    title_normalized_hash: str | None
    title_count: int
    title_length: int | None
    title_truncated: bool
    description_presence: MetadataPresence
    description_value: str | None
    description_normalized_hash: str | None
    description_count: int
    description_length: int | None
    description_truncated: bool
    canonical_presence: MetadataPresence
    canonical_url: str | None
    canonical_url_identity: str | None
    canonical_count: int
    canonical_conflicting: bool
    canonical_cross_host: bool
    canonical_cross_scheme: bool
    canonical_cross_port: bool
    canonical_truncated: bool
    meta_robots_json: str
    x_robots_json: str
    robots_allowed: bool | None
    robots_reason_code: str | None
    robots_evidence_json: str
    indexability_evidence_json: str
    indexability_state: IndexabilityEvidenceState
    parse_warning_count: int
    parse_warnings_truncated: bool
    evidence_state: PageEvidenceState
    failure_code: str | None
    value_truncated: bool
    created_at: datetime
    evidence_version: str = PAGE_EVIDENCE_VERSION
    projection_version: str = PAGE_EVIDENCE_PROJECTION_VERSION
    redirects: tuple[PageRedirectEvidence, ...] = ()
    warnings: tuple[PageParseWarningEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class PageLinkEvidenceRecord:
    """One bounded parser-authoritative source-link occurrence."""

    link_id: str
    job_id: str
    run_id: str
    source_evidence_id: str
    source_requested_url: str
    source_final_url: str | None
    source_url_identity: str
    source_discovery_sequence: int
    source_crawl_depth: int
    link_sequence: int
    discovery_sequence: int
    element_type: str
    raw_href: str | None
    resolved_url: str | None
    target_url_identity: str | None
    target_scheme: str | None
    target_host: str | None
    internal: bool | None
    in_scope: bool | None
    scope_reason_code: str | None
    anchor_text: str | None
    rel_values_json: str
    nofollow: bool
    fragment: str | None
    link_type: str
    resolution_warning: str | None
    created_at: datetime
    evidence_version: str = LINK_EVIDENCE_VERSION


@dataclass(frozen=True, slots=True)
class PageImageEvidenceRecord:
    """One bounded parser-authoritative image occurrence; bodies are never retained."""

    image_id: str
    job_id: str
    run_id: str
    source_evidence_id: str
    source_requested_url: str
    source_final_url: str | None
    source_url_identity: str
    source_discovery_sequence: int
    source_crawl_depth: int
    element_sequence: int
    occurrence_sequence: int
    element_type: str
    source_kind: str
    raw_src: str | None
    resolved_src: str | None
    image_identity: str | None
    raw_srcset: str | None
    srcset_candidates_json: str
    primary_candidate: str | None
    sizes: str | None
    alt_present: bool
    alt_raw: str | None
    alt_normalized: str | None
    title_value: str | None
    width_value: str | None
    height_value: str | None
    loading_value: str | None
    decoding_value: str | None
    fetch_priority: str | None
    linked: bool
    parent_link_url: str | None
    decorative_explicit: bool
    role_value: str | None
    aria_hidden_value: str | None
    in_scope: bool | None
    scope_reason_code: str | None
    source_scheme: str | None
    data_media_type: str | None
    data_byte_length_estimate: int | None
    data_fingerprint: str | None
    unsupported_scheme: bool
    parse_warning: str | None
    value_truncated: bool
    created_at: datetime
    evidence_version: str = IMAGE_EVIDENCE_VERSION


@dataclass(frozen=True, slots=True)
class PageEvidenceRunProjection:
    job_id: str
    run_id: str
    pages: tuple[PageEvidenceRecord, ...]
    source_page_count: int
    truncated: bool
    links: tuple[PageLinkEvidenceRecord, ...] = ()
    images: tuple[PageImageEvidenceRecord, ...] = ()
    ordering: str = PAGE_EVIDENCE_ORDERING


@dataclass(frozen=True, slots=True)
class _ProjectionContext:
    job_id: str
    run_id: str
    configuration: PageEvidenceConfiguration
    persisted_at: datetime
    crawl_cancelled: bool


@dataclass(frozen=True, slots=True)
class PageEvidenceFilters:
    run_id: str | None = None
    job_id: str | None = None
    url_text: str | None = None
    http_status: int | None = None
    status_class: int | None = None
    content_type_category: ContentTypeCategory | None = None
    parsed_as_html: bool | None = None
    robots_allowed: bool | None = None
    crawl_depth: int | None = None
    evidence_state: PageEvidenceState | None = None
    indexability_state: IndexabilityEvidenceState | None = None
    fetch_failed: bool | None = None
    redirected: bool | None = None
    has_parse_warnings: bool | None = None
    has_title: bool | None = None
    has_description: bool | None = None
    has_canonical: bool | None = None

    def fingerprint(self) -> str:
        return filter_fingerprint(
            {
                name: value.value if isinstance(value, StrEnum) else value
                for name, value in (
                    ("run_id", self.run_id),
                    ("job_id", self.job_id),
                    ("url_text", self.url_text),
                    ("http_status", self.http_status),
                    ("status_class", self.status_class),
                    ("content_type_category", self.content_type_category),
                    ("parsed_as_html", self.parsed_as_html),
                    ("robots_allowed", self.robots_allowed),
                    ("crawl_depth", self.crawl_depth),
                    ("evidence_state", self.evidence_state),
                    ("indexability_state", self.indexability_state),
                    ("fetch_failed", self.fetch_failed),
                    ("redirected", self.redirected),
                    ("has_parse_warnings", self.has_parse_warnings),
                    ("has_title", self.has_title),
                    ("has_description", self.has_description),
                    ("has_canonical", self.has_canonical),
                )
            }
        )


@dataclass(frozen=True, slots=True)
class PageEvidenceListItem:
    evidence_id: str
    job_id: str
    run_id: str
    requested_url: str
    final_url: str | None
    discovery_sequence: int
    crawl_depth: int
    fetch_outcome: str
    http_status: int | None
    redirect_count: int
    content_type: str | None
    content_type_category: ContentTypeCategory
    parsed_as_html: bool
    title_presence: MetadataPresence
    title_value: str | None
    description_presence: MetadataPresence
    canonical_presence: MetadataPresence
    canonical_url: str | None
    robots_allowed: bool | None
    robots_reason_code: str | None
    indexability_evidence_json: str
    indexability_state: IndexabilityEvidenceState
    parse_warning_count: int
    evidence_state: PageEvidenceState
    value_truncated: bool
    persisted_at: datetime
    evidence_version: str


@dataclass(frozen=True, slots=True)
class PageEvidencePage:
    items: tuple[PageEvidenceListItem, ...]
    next_cursor: str | None
    page_size: int
    ordering: str = PAGE_EVIDENCE_ORDERING
    query_version: str = PAGE_EVIDENCE_QUERY_VERSION


@dataclass(frozen=True, slots=True)
class PageEvidenceSummary:
    run_id: str
    job_id: str
    total_records: int
    completed_records: int
    partial_records: int
    failed_records: int
    html_records: int
    non_html_records: int
    redirect_records: int
    parse_warning_count: int
    truncated_records: int
    title_evidence_count: int
    description_evidence_count: int
    canonical_evidence_count: int
    status_class_counts_json: str
    content_type_counts_json: str
    robots_permission_counts_json: str
    indexability_counts_json: str
    source_page_count: int
    projection_truncated: bool
    persisted_at: datetime
    retention_state: PageEvidenceRetentionState


@dataclass(frozen=True, slots=True)
class PageEvidenceCleanupResult:
    planned: int
    deleted: int
    dry_run: bool


@dataclass(frozen=True, slots=True)
class PageEvidenceReconciliationReport:
    inspected: int
    mismatched: int
    reason_codes: tuple[str, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class PageEvidenceDiagnostics:
    enabled: bool
    persistence_ready: bool
    runs_with_evidence: int
    page_records: int
    partial_records: int
    failed_records: int
    html_records: int
    non_html_records: int
    truncated_records: int
    parse_warning_count: int
    retained_records: int
    expired_records: int
    cleanup_pending_records: int
    evidence_version: str = PAGE_EVIDENCE_VERSION
    persistence_version: str = PAGE_EVIDENCE_PERSISTENCE_VERSION
    query_version: str = PAGE_EVIDENCE_QUERY_VERSION
    retention_version: str = PAGE_EVIDENCE_RETENTION_VERSION


def project_crawl_result(
    job_id: str,
    run_id: str,
    crawl: CrawlResult,
    configuration: PageEvidenceConfiguration,
    *,
    now: datetime | None = None,
) -> PageEvidenceRunProjection:
    """Project accepted crawl records without fetching, parsing, or retaining bodies."""
    persisted_at = now or datetime.now(UTC)
    ordered = sorted(crawl.url_records, key=lambda item: (item.discovery_order, item.requested_url))
    selected = ordered[: configuration.maximum_pages_per_run]
    context = _ProjectionContext(
        job_id=job_id,
        run_id=run_id,
        configuration=configuration,
        persisted_at=persisted_at,
        crawl_cancelled=crawl.state.value == "cancelled",
    )
    pages = tuple(_project_page(context, record) for record in selected)
    links: list[PageLinkEvidenceRecord] = []
    images: list[PageImageEvidenceRecord] = []
    for record, page in zip(selected, pages, strict=True):
        links.extend(_project_links(context, record, page, len(links)))
        images.extend(_project_images(context, record, page, len(images)))
    return PageEvidenceRunProjection(
        job_id=job_id,
        run_id=run_id,
        pages=pages,
        source_page_count=len(ordered),
        truncated=len(selected) != len(ordered),
        links=tuple(links),
        images=tuple(images),
    )


def _project_images(
    context: _ProjectionContext,
    record: UrlCrawlRecord,
    page: PageEvidenceRecord,
    start_sequence: int,
) -> tuple[PageImageEvidenceRecord, ...]:
    parse = record.parse_result
    if parse is None:
        return ()
    values: list[PageImageEvidenceRecord] = []
    for offset, image in enumerate(parse.images):
        raw_src, raw_truncated = _bounded(image.raw_src, 4_096)
        scheme = urlsplit(image.normalized_url or image.raw_src or "").scheme.casefold() or None
        media_type: str | None = None
        byte_length: int | None = None
        data_fingerprint: str | None = None
        if image.data_image and image.raw_src:
            header, _, payload = image.raw_src.partition(",")
            media_type = _bounded(header[5:].split(";", 1)[0] or None, 128)[0]
            byte_length = len(payload)
            data_fingerprint = hashlib.sha256(image.raw_src.encode()).hexdigest()[:24]
            raw_src = (
                f"data:{media_type or 'unknown'};length={byte_length};sha256={data_fingerprint}"
            )
        resolved, resolved_truncated = _bounded(image.normalized_url, 4_096)
        raw_srcset, srcset_truncated = _bounded(image.raw_srcset, 8_192)
        sizes, sizes_truncated = _bounded(image.sizes, 2_048)
        alt_raw, alt_truncated = _bounded(image.alt_value, 1_024)
        title, title_truncated = _bounded(image.title_value, 1_024)
        candidates = [
            [url[:4_096], descriptor]
            for url, descriptor in image.srcset_candidates[:_MAX_SRCSET_CANDIDATES]
        ]
        primary = resolved or (candidates[0][0] if len(candidates) == 1 else None)
        values.append(
            PageImageEvidenceRecord(
                image_id=hashlib.sha256(
                    f"{page.evidence_id}\0{image.occurrence_index}\0{raw_src or ''}".encode()
                ).hexdigest(),
                job_id=context.job_id,
                run_id=context.run_id,
                source_evidence_id=page.evidence_id,
                source_requested_url=page.requested_url,
                source_final_url=page.final_url,
                source_url_identity=page.requested_url_identity,
                source_discovery_sequence=page.discovery_sequence,
                source_crawl_depth=page.crawl_depth,
                element_sequence=image.occurrence_index,
                occurrence_sequence=start_sequence + offset,
                element_type=_bounded(image.element_type, 32)[0] or "img",
                source_kind=_bounded(image.source_kind, 32)[0] or "src",
                raw_src=raw_src,
                resolved_src=resolved,
                image_identity=_url_identity(resolved) if resolved else data_fingerprint,
                raw_srcset=raw_srcset,
                srcset_candidates_json=_safe_json(candidates, 16_384),
                primary_candidate=_bounded(primary, 4_096)[0],
                sizes=sizes,
                alt_present=image.alt_present,
                alt_raw=alt_raw,
                alt_normalized=_bounded(
                    " ".join((image.alt_value or "").strip().split())
                    if image.alt_present
                    else None,
                    1_024,
                )[0],
                title_value=title,
                width_value=_bounded(image.width, 64)[0],
                height_value=_bounded(image.height, 64)[0],
                loading_value=_bounded(image.loading, 32)[0],
                decoding_value=_bounded(image.decoding, 32)[0],
                fetch_priority=_bounded(image.fetch_priority, 32)[0],
                linked=image.linked,
                parent_link_url=_bounded(image.parent_link_url, 4_096)[0],
                decorative_explicit=image.decorative_explicit,
                role_value=_bounded(image.role, 64)[0],
                aria_hidden_value=_bounded(image.aria_hidden, 16)[0],
                in_scope=image.in_scope,
                scope_reason_code=_bounded(image.scope_reason_code, 64)[0],
                source_scheme=scheme,
                data_media_type=media_type,
                data_byte_length_estimate=byte_length,
                data_fingerprint=data_fingerprint,
                unsupported_scheme=image.unsupported_scheme,
                parse_warning=_bounded(image.parse_warning, 64)[0],
                value_truncated=any(
                    (
                        raw_truncated,
                        resolved_truncated,
                        srcset_truncated,
                        sizes_truncated,
                        alt_truncated,
                        title_truncated,
                        len(image.srcset_candidates) > _MAX_SRCSET_CANDIDATES,
                    )
                ),
                created_at=context.persisted_at,
            )
        )
    return tuple(values)


def _project_links(
    context: _ProjectionContext,
    record: UrlCrawlRecord,
    page: PageEvidenceRecord,
    start_sequence: int,
) -> tuple[PageLinkEvidenceRecord, ...]:
    parse = record.parse_result
    if parse is None:
        return ()
    values: list[PageLinkEvidenceRecord] = []
    for offset, link in enumerate(parse.links):
        resolved = _bounded(link.normalized_url, 4096)[0]
        raw = _bounded(link.raw_href, 4096)[0]
        split = urlsplit(resolved or raw or "")
        raw_split = urlsplit(raw or "")
        link_type = (
            "fragment"
            if link.fragment_only
            else "javascript"
            if link.javascript
            else "invalid"
            if link.malformed or link.href_empty
            else "mailto"
            if split.scheme.casefold() == "mailto"
            else "tel"
            if split.scheme.casefold() == "tel"
            else "data"
            if split.scheme.casefold() == "data"
            else "http"
            if split.scheme.casefold() in {"http", "https"}
            else "unsupported"
        )
        warning = (
            "invalid_href"
            if link.malformed or link.href_empty
            else "unsupported_scheme"
            if link.unsupported_scheme
            else "fragment_only_link"
            if link.fragment_only
            else None
        )
        anchor = _bounded(link.anchor_text, 512)[0]
        values.append(
            PageLinkEvidenceRecord(
                link_id=hashlib.sha256(
                    f"{page.evidence_id}\0{link.occurrence_index}\0{raw or ''}".encode()
                ).hexdigest(),
                job_id=context.job_id,
                run_id=context.run_id,
                source_evidence_id=page.evidence_id,
                source_requested_url=page.requested_url,
                source_final_url=page.final_url,
                source_url_identity=page.requested_url_identity,
                source_discovery_sequence=page.discovery_sequence,
                source_crawl_depth=page.crawl_depth,
                link_sequence=link.occurrence_index,
                discovery_sequence=start_sequence + offset,
                element_type=_bounded(link.element_type, 16)[0] or "a",
                raw_href=raw,
                resolved_url=resolved,
                target_url_identity=_url_identity(resolved) if resolved else None,
                target_scheme=_bounded(split.scheme.casefold() or None, 32)[0],
                target_host=_bounded(split.hostname.casefold() if split.hostname else None, 255)[0],
                internal=link.same_host,
                in_scope=link.in_scope,
                scope_reason_code=_bounded(link.scope_reason_code, 64)[0],
                anchor_text=anchor,
                rel_values_json=_safe_json(list(link.rel_tokens), 1024),
                nofollow=link.nofollow,
                fragment=_bounded(raw_split.fragment or split.fragment or None, 512)[0],
                link_type=link_type,
                resolution_warning=warning,
                created_at=context.persisted_at,
            )
        )
    return tuple(values)


def _project_page(
    context: _ProjectionContext,
    record: UrlCrawlRecord,
) -> PageEvidenceRecord:
    job_id = context.job_id
    run_id = context.run_id
    configuration = context.configuration
    now = context.persisted_at
    fetch = record.fetch_result
    parse = record.parse_result
    requested_identity = _url_identity(record.requested_url)
    final_url = record.final_fetched_url or (fetch.final_url if fetch is not None else None)
    final_identity = _url_identity(final_url) if final_url else None
    evidence_id = hashlib.sha256(
        f"{run_id}\0{record.discovery_order}\0{requested_identity}".encode()
    ).hexdigest()
    title = _text_evidence(parse.title if parse else None, configuration)
    description = _text_evidence(parse.meta_description if parse else None, configuration)
    canonical = _canonical_evidence(record.requested_url, parse, configuration)
    redirects, redirect_truncated = _redirects(fetch, configuration)
    warnings, warning_truncated, warning_count = _warnings(evidence_id, parse, configuration)
    content_type = _bounded(
        (fetch.content_type if fetch else None) or (parse.effective_media_type if parse else None),
        256,
    )[0]
    category = _content_category(content_type)
    charset = _bounded(parse.selected_encoding if parse else None, 64)[0]
    robots_json = _robots_json(record, configuration)
    meta_json = _meta_robots_json(parse, configuration)
    x_json = _x_robots_json(record, configuration)
    index_json = _indexability_json(record, configuration)
    indexability_state = (
        IndexabilityEvidenceState.UNAVAILABLE
        if record.indexability_evidence is None
        else IndexabilityEvidenceState.CONFLICTING
        if record.indexability_evidence.conflicts
        else IndexabilityEvidenceState.AVAILABLE
    )
    state = _evidence_state(
        record,
        category,
        crawl_cancelled=context.crawl_cancelled,
        truncated=(
            redirect_truncated or warning_truncated or title[5] or description[5] or canonical[8]
        ),
    )
    failure_code = (
        fetch.failure_code.value
        if fetch is not None and fetch.failure_code is not None
        else record.skip_reason.value
        if record.skip_reason is not None
        else None
    )
    redirect_loop = bool(
        fetch is not None
        and fetch.failure_code is not None
        and fetch.failure_code.value == "redirect_loop"
    )
    return PageEvidenceRecord(
        evidence_id=evidence_id,
        job_id=job_id,
        run_id=run_id,
        requested_url=_bounded(record.requested_url, 4096)[0] or "",
        requested_url_identity=requested_identity,
        final_url=_bounded(final_url, 4096)[0],
        final_url_identity=final_identity,
        discovery_sequence=record.discovery_order,
        crawl_depth=record.best_known_depth,
        referrer_url=_bounded(record.first_referrer, 4096)[0],
        frontier_state=record.frontier_state.value,
        fetch_outcome=fetch.outcome.value if fetch else record.outcome.value,
        http_status=fetch.status_code if fetch else None,
        status_class=(fetch.status_code // 100 if fetch and fetch.status_code else None),
        fetch_failed=fetch is None or fetch.outcome.value == "failure",
        redirect_count=len(fetch.redirect_chain) if fetch else 0,
        redirect_truncated=redirect_truncated,
        redirect_loop=redirect_loop,
        content_type=content_type,
        content_type_category=category,
        charset=charset,
        parsed_as_html=parse is not None and parse.outcome.value == "parsed",
        parse_outcome=parse.outcome.value if parse else None,
        title_presence=title[0],
        title_value=title[1],
        title_normalized_hash=title[2],
        title_count=title[3],
        title_length=title[4],
        title_truncated=title[5],
        description_presence=description[0],
        description_value=description[1],
        description_normalized_hash=description[2],
        description_count=description[3],
        description_length=description[4],
        description_truncated=description[5],
        canonical_presence=canonical[0],
        canonical_url=canonical[1],
        canonical_url_identity=canonical[2],
        canonical_count=canonical[3],
        canonical_conflicting=canonical[4],
        canonical_cross_host=canonical[5],
        canonical_cross_scheme=canonical[6],
        canonical_cross_port=canonical[7],
        canonical_truncated=canonical[8],
        meta_robots_json=meta_json,
        x_robots_json=x_json,
        robots_allowed=record.robots_permission.allowed if record.robots_permission else None,
        robots_reason_code=(
            record.robots_permission.reason_code.value if record.robots_permission else None
        ),
        robots_evidence_json=robots_json,
        indexability_evidence_json=index_json,
        indexability_state=indexability_state,
        parse_warning_count=warning_count,
        parse_warnings_truncated=warning_truncated,
        evidence_state=state,
        failure_code=failure_code,
        value_truncated=title[5]
        or description[5]
        or canonical[8]
        or redirect_truncated
        or warning_truncated,
        created_at=now,
        redirects=redirects,
        warnings=warnings,
    )


def _text_evidence(
    evidence: TextMetadataEvidence | None, configuration: PageEvidenceConfiguration
) -> tuple[MetadataPresence, str | None, str | None, int, int | None, bool]:
    if evidence is None:
        return MetadataPresence.UNAVAILABLE, None, None, 0, None, False
    count = evidence.count
    selected = evidence.selected_value
    presence = (
        MetadataPresence.MISSING
        if count == 0
        else MetadataPresence.MULTIPLE
        if count > 1
        else MetadataPresence.EMPTY
        if not (selected or "").strip()
        else MetadataPresence.SINGLE
    )
    value, truncated = _bounded(selected, configuration.maximum_metadata_characters)
    normalized_hash = None
    if selected is not None:
        normalized = " ".join(unicodedata.normalize("NFKC", selected).casefold().split())
        normalized_hash = hashlib.sha256(normalized.encode()).hexdigest()
    return presence, value, normalized_hash, count, evidence.selected_length, truncated


def _canonical_evidence(
    requested_url: str, parse: HtmlParseResult | None, configuration: PageEvidenceConfiguration
) -> tuple[MetadataPresence, str | None, str | None, int, bool, bool, bool, bool, bool]:
    if parse is None:
        return MetadataPresence.UNAVAILABLE, None, None, 0, False, False, False, False, False
    evidence = parse.canonical
    count = evidence.count
    selected = evidence.selected_url
    presence = (
        MetadataPresence.MISSING
        if count == 0
        else MetadataPresence.MULTIPLE
        if count > 1
        else MetadataPresence.EMPTY
        if not selected
        else MetadataPresence.SINGLE
    )
    value, truncated = _bounded(selected, configuration.maximum_metadata_characters)
    requested = urlsplit(requested_url)
    target = urlsplit(selected) if selected else None
    valid_values = {item.normalized_url for item in evidence.observations if item.normalized_url}
    return (
        presence,
        value,
        _url_identity(selected) if selected else None,
        count,
        len(valid_values) > 1,
        bool(target and target.hostname != requested.hostname),
        bool(target and target.scheme != requested.scheme),
        bool(target and target.port != requested.port),
        truncated,
    )


def _redirects(
    fetch: FetchResult | None, configuration: PageEvidenceConfiguration
) -> tuple[tuple[PageRedirectEvidence, ...], bool]:
    if fetch is None:
        return (), False
    selected = fetch.redirect_chain[: configuration.maximum_redirect_hops]
    result = tuple(
        PageRedirectEvidence(
            sequence=index,
            source_url=_bounded(hop.source_url, 4096)[0] or "",
            target_url=_bounded(hop.destination_url, 4096)[0],
            status_code=hop.status_code,
            cross_host=bool(
                hop.destination_url
                and urlsplit(hop.source_url).hostname != urlsplit(hop.destination_url).hostname
            ),
            terminal=index == len(fetch.redirect_chain),
            loop=bool(hop.failure_code and hop.failure_code.value == "redirect_loop"),
            failure_code=hop.failure_code.value if hop.failure_code else None,
        )
        for index, hop in enumerate(selected, start=1)
    )
    return result, len(selected) != len(fetch.redirect_chain)


def _warnings(
    evidence_id: str, parse: HtmlParseResult | None, configuration: PageEvidenceConfiguration
) -> tuple[tuple[PageParseWarningEvidence, ...], bool, int]:
    source = parse.warnings if parse else ()
    selected = source[: configuration.maximum_parse_warnings_per_page]
    result = tuple(
        PageParseWarningEvidence(
            warning_id=hashlib.sha256(
                f"{evidence_id}\0{index}\0{item.code.value}".encode()
            ).hexdigest(),
            sequence=index,
            code=item.code.value,
            category="html_parse",
            safe_summary=_bounded(item.explanation, 512)[0] or item.code.value,
        )
        for index, item in enumerate(selected, start=1)
    )
    return result, len(selected) != len(source), len(source)


def _meta_robots_json(
    parse: HtmlParseResult | None, configuration: PageEvidenceConfiguration
) -> str:
    records = (
        []
        if parse is None
        else [
            {
                "agent": item.agent_name,
                "directives": [
                    {"name": d.name, "value": d.value, "known": d.known}
                    for d in item.directives[:50]
                ],
            }
            for item in parse.meta_robots[:50]
        ]
    )
    return _safe_json(records, configuration.maximum_metadata_characters * 4)


def _x_robots_json(record: UrlCrawlRecord, configuration: PageEvidenceConfiguration) -> str:
    evidence = record.x_robots_tag
    records = (
        []
        if evidence is None
        else [
            {
                "agent": item.agent_name,
                "directives": [
                    {"name": d.name, "value": d.value, "known": d.known}
                    for d in item.directives[:50]
                ],
            }
            for item in evidence.records[:50]
        ]
    )
    return _safe_json(records, configuration.maximum_metadata_characters * 4)


def _robots_json(record: UrlCrawlRecord, configuration: PageEvidenceConfiguration) -> str:
    item = record.robots_permission
    if item is None:
        return "{}"
    value = {
        "fetch_outcome": item.fetch_outcome.value,
        "parse_outcome": item.parse_outcome.value,
        "selected_group": item.selected_group_index,
        "allowed": item.allowed,
        "reason": item.reason_code.value,
        "temporary_unavailability": item.temporary_unavailability,
        "matched_rule": None
        if item.matched_rule is None
        else {
            "kind": item.matched_rule.kind.value,
            "pattern": item.matched_rule.pattern[:512],
            "specificity": item.matched_rule.specificity,
        },
    }
    return _safe_json(value, configuration.maximum_metadata_characters * 2)


def _indexability_json(record: UrlCrawlRecord, configuration: PageEvidenceConfiguration) -> str:
    item = record.indexability_evidence
    if item is None:
        return "{}"
    value = {
        "conflicts": [
            {
                "kind": conflict.kind.value,
                "directive": conflict.directive_name,
                "values": list(conflict.observed_values[:20]),
                "sources": [source.value for source in conflict.sources],
            }
            for conflict in item.conflicts[:50]
        ],
        "warnings": [warning.code.value for warning in item.warnings[:50]],
        "crawler_specific": any(
            meta_record.agent_name != "robots" for meta_record in item.meta_robots
        ),
    }
    return _safe_json(value, configuration.maximum_metadata_characters * 4)


def _evidence_state(
    record: UrlCrawlRecord,
    category: ContentTypeCategory,
    *,
    crawl_cancelled: bool,
    truncated: bool,
) -> PageEvidenceState:
    if truncated:
        return PageEvidenceState.TRUNCATED
    if record.outcome.value == "fetch_failed":
        return PageEvidenceState.FETCH_FAILED
    if crawl_cancelled and record.outcome.value in {"skipped", "worker_failed"}:
        return PageEvidenceState.CANCELLED
    if (
        category not in {ContentTypeCategory.HTML, ContentTypeCategory.MISSING}
        and record.parse_result is None
    ):
        return PageEvidenceState.NOT_HTML
    if record.frontier_state.value == "skipped" or record.outcome.value in {
        "skipped",
        "worker_failed",
    }:
        return PageEvidenceState.PARTIAL
    return PageEvidenceState.COMPLETE


def _content_category(value: str | None) -> ContentTypeCategory:
    if not value:
        return ContentTypeCategory.MISSING
    media = value.split(";", 1)[0].strip().casefold()
    exact = {
        "text/html": ContentTypeCategory.HTML,
        "application/xhtml+xml": ContentTypeCategory.HTML,
        "application/pdf": ContentTypeCategory.PDF,
        "application/json": ContentTypeCategory.JSON,
        "text/plain": ContentTypeCategory.PLAIN_TEXT,
        "application/xml": ContentTypeCategory.XML,
        "text/xml": ContentTypeCategory.XML,
    }
    category = exact.get(media)
    if category is None:
        if media.startswith("image/"):
            category = ContentTypeCategory.IMAGE
        elif media.endswith("+json"):
            category = ContentTypeCategory.JSON
        elif media.endswith("+xml"):
            category = ContentTypeCategory.XML
        elif "/" not in media:
            category = ContentTypeCategory.AMBIGUOUS
        else:
            category = ContentTypeCategory.OTHER
    return category


def _url_identity(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _bounded(value: str | None, maximum: int) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    return value[:maximum], len(value) > maximum


def _safe_json(value: object, maximum: int) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return (
        encoded
        if len(encoded) <= maximum
        else json.dumps({"truncated": True}, separators=(",", ":"))
    )


def filter_fingerprint(filters: dict[str, object]) -> str:
    payload = json.dumps(filters, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def encode_cursor(sequence: int, url_identity: str, fingerprint: str) -> str:
    payload = {
        "v": PAGE_EVIDENCE_PAGINATION_VERSION,
        "o": PAGE_EVIDENCE_ORDERING,
        "s": sequence,
        "u": url_identity,
        "f": fingerprint,
    }
    return (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        )
        .decode()
        .rstrip("=")
    )


def decode_cursor(value: str, fingerprint: str) -> tuple[int, str]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        payload = json.loads(raw)
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(PageEvidenceReasonCode.INVALID_CURSOR) from error
    if (
        payload.get("v") != PAGE_EVIDENCE_PAGINATION_VERSION
        or payload.get("o") != PAGE_EVIDENCE_ORDERING
    ):
        raise ValueError(PageEvidenceReasonCode.CURSOR_VERSION_UNSUPPORTED)
    if payload.get("f") != fingerprint:
        raise ValueError(PageEvidenceReasonCode.CURSOR_FILTER_MISMATCH)
    if not isinstance(payload.get("s"), int) or not isinstance(payload.get("u"), str):
        raise TypeError(PageEvidenceReasonCode.INVALID_CURSOR)
    return payload["s"], payload["u"]
