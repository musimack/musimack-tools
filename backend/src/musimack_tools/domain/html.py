"""Immutable evidence produced by one-document HTML metadata extraction."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class HtmlParseOutcome(StrEnum):
    """Top-level result of attempting to parse fetched response evidence."""

    PARSED = "parsed"
    SKIPPED = "skipped"


class HtmlParseReasonCode(StrEnum):
    """Stable reason explaining why parsing did or did not occur."""

    PARSED = "parsed"
    FETCH_FAILED = "fetch_failed"
    HTTP_ERROR_RESPONSE = "http_error_response"
    RESPONSE_TRUNCATED = "response_truncated"
    MISSING_BODY = "missing_body"
    EMPTY_BODY = "empty_body"
    NON_HTML_CONTENT = "non_html_content"


class EncodingSource(StrEnum):
    """Stable source used to select a character encoding."""

    HTTP_HEADER = "http_header"
    BOM = "bom"
    META_CHARSET = "meta_charset"
    META_HTTP_EQUIV = "meta_http_equiv"
    FALLBACK = "fallback"


class WarningSeverity(StrEnum):
    """Review severity for parse evidence; no severity decides indexability."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class HtmlWarningCode(StrEnum):
    """Stable machine-readable HTML warning codes."""

    NON_HTML_CONTENT = "non_html_content"
    MISSING_BODY = "missing_body"
    EMPTY_BODY = "empty_body"
    HTTP_ERROR_RESPONSE = "http_error_response"
    RESPONSE_TRUNCATED = "response_truncated"
    MEDIA_TYPE_INFERRED = "media_type_inferred"
    INVALID_CHARSET = "invalid_charset"
    ENCODING_DECLARATION_IGNORED = "encoding_declaration_ignored"
    DECODE_REPLACEMENT_USED = "decode_replacement_used"
    PARSER_RECOVERY_USED = "parser_recovery_used"
    MISSING_TITLE = "missing_title"
    EMPTY_TITLE = "empty_title"
    MULTIPLE_TITLES = "multiple_titles"
    CONFLICTING_TITLES = "conflicting_titles"
    SHORT_TITLE = "short_title"
    LONG_TITLE = "long_title"
    MISSING_META_DESCRIPTION = "missing_meta_description"
    EMPTY_META_DESCRIPTION = "empty_meta_description"
    MULTIPLE_META_DESCRIPTIONS = "multiple_meta_descriptions"
    CONFLICTING_META_DESCRIPTIONS = "conflicting_meta_descriptions"
    SHORT_META_DESCRIPTION = "short_meta_description"
    LONG_META_DESCRIPTION = "long_meta_description"
    MISSING_CANONICAL = "missing_canonical"
    EMPTY_CANONICAL = "empty_canonical"
    MULTIPLE_CANONICALS = "multiple_canonicals"
    CONFLICTING_CANONICALS = "conflicting_canonicals"
    INVALID_CANONICAL = "invalid_canonical"
    CROSS_HOST_CANONICAL = "cross_host_canonical"
    CANONICAL_URL_DIFFERS = "canonical_url_differs"
    CANONICAL_ORIGIN_DIFFERS = "canonical_origin_differs"
    EMPTY_META_ROBOTS = "empty_meta_robots"
    CONFLICTING_META_ROBOTS = "conflicting_meta_robots"
    UNKNOWN_META_ROBOTS_DIRECTIVE = "unknown_meta_robots_directive"
    INVALID_META_ROBOTS_DIRECTIVE = "invalid_meta_robots_directive"
    MULTIPLE_BASE_ELEMENTS = "multiple_base_elements"
    EMPTY_BASE_HREF = "empty_base_href"
    INVALID_BASE_HREF = "invalid_base_href"
    CROSS_HOST_BASE_HREF = "cross_host_base_href"
    BASE_ORIGIN_DIFFERS = "base_origin_differs"
    EMPTY_LINK_HREF = "empty_link_href"
    INVALID_LINK_HREF = "invalid_link_href"
    JAVASCRIPT_LINK = "javascript_link"
    UNSUPPORTED_LINK_SCHEME = "unsupported_link_scheme"


@dataclass(frozen=True, slots=True)
class HtmlWarning:
    """One reviewable parse warning with bounded contextual evidence."""

    code: HtmlWarningCode
    explanation: str
    severity: WarningSeverity
    occurrence_index: int | None = None
    observed_value: str | None = None


@dataclass(frozen=True, slots=True)
class TextObservation:
    """Raw and normalized value from one title or description element."""

    raw_value: str
    normalized_value: str
    occurrence_index: int


@dataclass(frozen=True, slots=True)
class TextMetadataEvidence:
    """Selected text plus every document-order observation."""

    selected_value: str | None
    selected_length: int | None
    observations: tuple[TextObservation, ...]

    @property
    def count(self) -> int:
        return len(self.observations)


@dataclass(frozen=True, slots=True)
class UrlObservation:
    """One raw URL-valued metadata observation and its validation result."""

    raw_value: str | None
    normalized_url: str | None
    occurrence_index: int
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalEvidence:
    """Canonical candidates; selection is absent when valid targets conflict."""

    selected_url: str | None
    observations: tuple[UrlObservation, ...]

    @property
    def count(self) -> int:
        return len(self.observations)


@dataclass(frozen=True, slots=True)
class BaseUrlEvidence:
    """All base elements and the first valid effective base, if present."""

    document_url: str
    effective_url: str
    selected_base_url: str | None
    observations: tuple[UrlObservation, ...]


@dataclass(frozen=True, slots=True)
class RobotsDirective:
    """One normalized robots token with its unmodified source token."""

    name: str
    value: str | None
    raw_value: str
    known: bool


@dataclass(frozen=True, slots=True)
class MetaRobotsRecord:
    """One crawler-named meta robots element in document order."""

    agent_name: str
    raw_content: str | None
    directives: tuple[RobotsDirective, ...]
    occurrence_index: int


@dataclass(frozen=True, slots=True)
class LinkRecord:
    """One observed navigable link; records remain in document order."""

    occurrence_index: int
    element_type: str
    raw_href: str | None
    normalized_url: str | None
    anchor_text: str | None
    rel_tokens: tuple[str, ...]
    nofollow: bool
    href_empty: bool
    fragment_only: bool
    unsupported_scheme: bool
    javascript: bool
    malformed: bool
    same_document: bool | None
    same_host: bool | None
    in_scope: bool | None
    scope_reason_code: str | None


@dataclass(frozen=True, slots=True)
class ImageRecord:
    """One bounded parser-owned image occurrence in document order."""

    occurrence_index: int
    element_type: str
    source_kind: str
    raw_src: str | None
    normalized_url: str | None
    raw_srcset: str | None
    srcset_candidates: tuple[tuple[str, str | None], ...]
    sizes: str | None
    alt_present: bool
    alt_value: str | None
    title_value: str | None
    width: str | None
    height: str | None
    loading: str | None
    decoding: str | None
    fetch_priority: str | None
    linked: bool
    parent_link_url: str | None
    decorative_explicit: bool
    role: str | None
    aria_hidden: str | None
    in_scope: bool | None
    scope_reason_code: str | None
    unsupported_scheme: bool
    data_image: bool
    parse_warning: str | None


@dataclass(frozen=True, slots=True)
class StructuredDataRecord:
    """One bounded, inert structured-data block in document order."""

    occurrence_index: int
    format: str
    source_locator: str
    script_type: str | None
    raw_value: str
    raw_length: int
    parse_status: str
    parse_error: str | None
    contexts: tuple[str, ...]
    types: tuple[str, ...]
    identifiers: tuple[str, ...]
    properties_json: str
    references: tuple[str, ...]
    raw_fingerprint: str
    normalized_fingerprint: str | None
    duplicate_keys: tuple[str, ...]
    diagnostics: tuple[str, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class HtmlParseResult:
    """Complete deterministic evidence from one fetched HTML document."""

    final_document_url: str
    outcome: HtmlParseOutcome
    reason_code: HtmlParseReasonCode
    declared_media_type: str | None
    effective_media_type: str | None
    media_type_inferred: bool
    selected_encoding: str | None
    encoding_source: EncodingSource | None
    decode_replacement_used: bool
    title: TextMetadataEvidence
    meta_description: TextMetadataEvidence
    canonical: CanonicalEvidence
    meta_robots: tuple[MetaRobotsRecord, ...]
    base_url: BaseUrlEvidence
    links: tuple[LinkRecord, ...]
    warnings: tuple[HtmlWarning, ...]
    parser_name: str
    body_byte_count: int
    parse_duration_seconds: float
    images: tuple[ImageRecord, ...] = ()
    structured_data: tuple[StructuredDataRecord, ...] = ()
