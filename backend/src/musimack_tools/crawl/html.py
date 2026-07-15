"""Deterministic, network-free HTML metadata and navigable-link extraction."""

from __future__ import annotations

import codecs
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag
from lxml import etree  # type: ignore[import-untyped]  # lxml has no inline typing.

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import evaluate_scope
from musimack_tools.domain.fetching import FetchOutcome, FetchResult
from musimack_tools.domain.html import (
    BaseUrlEvidence,
    CanonicalEvidence,
    EncodingSource,
    HtmlParseOutcome,
    HtmlParseReasonCode,
    HtmlParseResult,
    HtmlWarning,
    HtmlWarningCode,
    LinkRecord,
    MetaRobotsRecord,
    RobotsDirective,
    TextMetadataEvidence,
    TextObservation,
    UrlObservation,
    WarningSeverity,
)
from musimack_tools.domain.urls import UrlNormalizationError

if TYPE_CHECKING:
    from musimack_tools.domain.urls import CrawlScopePolicy, NormalizedUrl

_LOGGER = logging.getLogger(__name__)
_HTML_MEDIA_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_SNIFFABLE_MEDIA_TYPES = frozenset({None, "", "application/octet-stream"})
_HTML_SNIFF_PATTERN = re.compile(
    rb"^\s*(?:\xef\xbb\xbf)?(?:<!doctype\s+html\b|<html\b|<head\b|<body\b|<title\b|<meta\b)",
    re.IGNORECASE,
)
_CHARSET_PARAMETER = re.compile(r"(?:^|;)\s*charset\s*=\s*[\"']?([^;\s\"']+)", re.I)
_ENCODING_SCAN_BYTES = 4096
_TITLE_MIN_LENGTH = 15
_TITLE_MAX_LENGTH = 60
_DESCRIPTION_MIN_LENGTH = 70
_DESCRIPTION_MAX_LENGTH = 160
_SUCCESS_STATUS_MIN = 200
_SUCCESS_STATUS_MAX = 300
_PARSER_NAME = "beautifulsoup4+lxml"
_KNOWN_ROBOTS_DIRECTIVES = frozenset(
    {
        "index",
        "noindex",
        "follow",
        "nofollow",
        "none",
        "noarchive",
        "nosnippet",
        "noimageindex",
        "notranslate",
        "max-snippet",
        "max-image-preview",
        "max-video-preview",
        "unavailable_after",
    }
)
_PARAMETERIZED_ROBOTS_DIRECTIVES = frozenset(
    {"max-snippet", "max-image-preview", "max-video-preview", "unavailable_after"}
)
_ROBOTS_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
_UNSUPPORTED_LINK_SCHEMES = frozenset({"mailto", "tel", "sms", "javascript", "data"})
_RECOVERY_SENSITIVE_ELEMENTS = ("title", "head", "body", "html")

Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class _TextRules:
    missing: HtmlWarningCode
    empty: HtmlWarningCode
    multiple: HtmlWarningCode
    conflicting: HtmlWarningCode
    short: HtmlWarningCode
    long: HtmlWarningCode
    minimum_length: int
    maximum_length: int
    label: str
    attribute: str | None = None


class HtmlMetadataParser:
    """Parse one completed fetch result without performing any network activity."""

    def __init__(self, *, clock: Clock = time.monotonic) -> None:
        self._clock = clock

    def parse(
        self,
        fetch: FetchResult,
        *,
        scope: CrawlScopePolicy | None = None,
    ) -> HtmlParseResult:
        """Return typed metadata, link, encoding, and warning evidence."""
        started_at = self._clock()
        document_url = normalize_url(fetch.final_url)
        warnings: list[HtmlWarning] = []
        _LOGGER.info(
            "html_parse_started",
            extra={"url": _safe_url_summary(document_url)},
        )

        skip = self._preflight(fetch, document_url, warnings, started_at)
        if skip is not None:
            return skip

        body = cast("bytes", fetch.body)
        declared_media_type = _media_type(fetch.content_type)
        inferred = declared_media_type not in _HTML_MEDIA_TYPES
        effective_media_type = "text/html" if inferred else declared_media_type
        if inferred:
            warnings.append(
                _warning(
                    HtmlWarningCode.MEDIA_TYPE_INFERRED,
                    "HTML media type was inferred from a bounded body prefix",
                    WarningSeverity.INFO,
                )
            )

        decoded, encoding, source, replacement = _decode_body(
            body,
            fetch.content_type,
            warnings,
        )
        soup, recovered = _parse_document(decoded)
        if recovered:
            warnings.append(
                _warning(
                    HtmlWarningCode.PARSER_RECOVERY_USED,
                    "The HTML parser recovered from malformed document markup",
                    WarningSeverity.INFO,
                )
            )
            _LOGGER.info(
                "html_parser_recovery",
                extra={"url": _safe_url_summary(document_url)},
            )

        base = _extract_base(soup, document_url, warnings)
        title = _extract_text_metadata(
            soup.find_all("title"),
            warnings=warnings,
            rules=_TextRules(
                missing=HtmlWarningCode.MISSING_TITLE,
                empty=HtmlWarningCode.EMPTY_TITLE,
                multiple=HtmlWarningCode.MULTIPLE_TITLES,
                conflicting=HtmlWarningCode.CONFLICTING_TITLES,
                short=HtmlWarningCode.SHORT_TITLE,
                long=HtmlWarningCode.LONG_TITLE,
                minimum_length=_TITLE_MIN_LENGTH,
                maximum_length=_TITLE_MAX_LENGTH,
                label="title",
            ),
        )
        descriptions = _description_tags(soup)
        description = _extract_text_metadata(
            descriptions,
            warnings=warnings,
            rules=_TextRules(
                missing=HtmlWarningCode.MISSING_META_DESCRIPTION,
                empty=HtmlWarningCode.EMPTY_META_DESCRIPTION,
                multiple=HtmlWarningCode.MULTIPLE_META_DESCRIPTIONS,
                conflicting=HtmlWarningCode.CONFLICTING_META_DESCRIPTIONS,
                short=HtmlWarningCode.SHORT_META_DESCRIPTION,
                long=HtmlWarningCode.LONG_META_DESCRIPTION,
                minimum_length=_DESCRIPTION_MIN_LENGTH,
                maximum_length=_DESCRIPTION_MAX_LENGTH,
                label="meta description",
                attribute="content",
            ),
        )
        canonical = _extract_canonical(soup, document_url, base, warnings)
        robots = _extract_robots(soup, warnings)
        links = _extract_links(soup, document_url, base, scope, warnings)
        duration = max(0.0, self._clock() - started_at)
        result = HtmlParseResult(
            final_document_url=document_url.normalized,
            outcome=HtmlParseOutcome.PARSED,
            reason_code=HtmlParseReasonCode.PARSED,
            declared_media_type=declared_media_type,
            effective_media_type=effective_media_type,
            media_type_inferred=inferred,
            selected_encoding=encoding,
            encoding_source=source,
            decode_replacement_used=replacement,
            title=title,
            meta_description=description,
            canonical=canonical,
            meta_robots=robots,
            base_url=base,
            links=links,
            warnings=tuple(warnings),
            parser_name=_PARSER_NAME,
            body_byte_count=len(body),
            parse_duration_seconds=duration,
        )
        _LOGGER.info(
            "html_parse_completed",
            extra={
                "url": _safe_url_summary(document_url),
                "duration_seconds": duration,
                "warning_count": len(warnings),
                "link_count": len(links),
            },
        )
        return result

    def _preflight(
        self,
        fetch: FetchResult,
        document_url: NormalizedUrl,
        warnings: list[HtmlWarning],
        started_at: float,
    ) -> HtmlParseResult | None:
        reason: HtmlParseReasonCode | None = None
        code: HtmlWarningCode | None = None
        explanation = ""
        if fetch.outcome is FetchOutcome.FAILURE:
            reason = HtmlParseReasonCode.FETCH_FAILED
            code = HtmlWarningCode.MISSING_BODY
            explanation = "Failed fetch evidence cannot be parsed as a successful HTML page"
        elif fetch.body_truncated:
            reason = HtmlParseReasonCode.RESPONSE_TRUNCATED
            code = HtmlWarningCode.RESPONSE_TRUNCATED
            explanation = "A response truncated by the fetch byte limit is not parsed"
        elif fetch.body is None:
            reason = HtmlParseReasonCode.MISSING_BODY
            code = HtmlWarningCode.MISSING_BODY
            explanation = "No retained response body is available for parsing"
        elif fetch.status_code is None or not (
            _SUCCESS_STATUS_MIN <= fetch.status_code < _SUCCESS_STATUS_MAX
        ):
            reason = HtmlParseReasonCode.HTTP_ERROR_RESPONSE
            code = HtmlWarningCode.HTTP_ERROR_RESPONSE
            explanation = "Non-success HTTP evidence is not parsed as successful page metadata"
        elif not fetch.body:
            reason = HtmlParseReasonCode.EMPTY_BODY
            code = HtmlWarningCode.EMPTY_BODY
            explanation = "The retained response body is empty"
        else:
            media_type = _media_type(fetch.content_type)
            if media_type not in _HTML_MEDIA_TYPES and (
                media_type not in _SNIFFABLE_MEDIA_TYPES or not _looks_like_html(fetch.body)
            ):
                reason = HtmlParseReasonCode.NON_HTML_CONTENT
                code = HtmlWarningCode.NON_HTML_CONTENT
                explanation = "The response media type and bounded body prefix are not HTML"

        if reason is None or code is None:
            return None
        warnings.append(_warning(code, explanation, WarningSeverity.WARNING))
        if reason is HtmlParseReasonCode.NON_HTML_CONTENT:
            _LOGGER.info(
                "html_parse_skipped_non_html",
                extra={"url": _safe_url_summary(document_url)},
            )
        return _skipped_result(
            fetch,
            document_url,
            reason,
            warnings,
            max(0.0, self._clock() - started_at),
        )


def _skipped_result(
    fetch: FetchResult,
    document_url: NormalizedUrl,
    reason: HtmlParseReasonCode,
    warnings: list[HtmlWarning],
    duration: float,
) -> HtmlParseResult:
    empty_text = TextMetadataEvidence(None, None, ())
    return HtmlParseResult(
        final_document_url=document_url.normalized,
        outcome=HtmlParseOutcome.SKIPPED,
        reason_code=reason,
        declared_media_type=_media_type(fetch.content_type),
        effective_media_type=None,
        media_type_inferred=False,
        selected_encoding=None,
        encoding_source=None,
        decode_replacement_used=False,
        title=empty_text,
        meta_description=empty_text,
        canonical=CanonicalEvidence(None, ()),
        meta_robots=(),
        base_url=BaseUrlEvidence(
            document_url=document_url.normalized,
            effective_url=document_url.normalized,
            selected_base_url=None,
            observations=(),
        ),
        links=(),
        warnings=tuple(warnings),
        parser_name=_PARSER_NAME,
        body_byte_count=len(fetch.body) if fetch.body is not None else 0,
        parse_duration_seconds=duration,
    )


def _media_type(content_type: str | None) -> str | None:
    if content_type is None:
        return None
    value = content_type.split(";", 1)[0].strip().lower()
    return value or None


def _looks_like_html(body: bytes) -> bool:
    return _HTML_SNIFF_PATTERN.search(body[:1024]) is not None


def _decode_body(
    body: bytes,
    content_type: str | None,
    warnings: list[HtmlWarning],
) -> tuple[str, str, EncodingSource, bool]:
    encoding, source, meta_found_in_scan = _choose_encoding(body, content_type, warnings)
    if not meta_found_in_scan and len(body) > _ENCODING_SCAN_BYTES:
        remainder = body[_ENCODING_SCAN_BYTES:].lower()
        if b"<meta" in remainder and b"charset" in remainder:
            warnings.append(
                _warning(
                    HtmlWarningCode.ENCODING_DECLARATION_IGNORED,
                    "An encoding declaration outside the bounded pre-scan was ignored",
                    WarningSeverity.INFO,
                )
            )

    try:
        decoded = body.decode(encoding, errors="strict")
        replacement = False
    except UnicodeDecodeError:
        decoded = body.decode(encoding, errors="replace")
        replacement = True
        warnings.append(
            _warning(
                HtmlWarningCode.DECODE_REPLACEMENT_USED,
                "Invalid byte sequences required replacement characters during decoding",
                WarningSeverity.WARNING,
            )
        )
    return decoded, encoding, source, replacement


def _choose_encoding(
    body: bytes,
    content_type: str | None,
    warnings: list[HtmlWarning],
) -> tuple[str, EncodingSource, bool]:
    header_charset = _header_charset(content_type)
    if header_charset is not None:
        encoding = _validated_encoding(header_charset, warnings, EncodingSource.HTTP_HEADER)
        if encoding is not None:
            return encoding, EncodingSource.HTTP_HEADER, False

    bom_encoding = _bom_encoding(body)
    if bom_encoding is not None:
        return bom_encoding, EncodingSource.BOM, False

    meta_encoding, meta_source = _meta_encoding(body[:_ENCODING_SCAN_BYTES])
    meta_found_in_scan = meta_encoding is not None
    if meta_encoding is not None and meta_source is not None:
        encoding = _validated_encoding(meta_encoding, warnings, meta_source)
        if encoding is not None:
            return encoding, meta_source, meta_found_in_scan

    encoding = "cp1252"
    _LOGGER.info("html_decode_fallback", extra={"encoding": encoding})
    return encoding, EncodingSource.FALLBACK, meta_found_in_scan


def _header_charset(content_type: str | None) -> str | None:
    if content_type is None:
        return None
    match = _CHARSET_PARAMETER.search(content_type)
    return match.group(1) if match is not None else None


def _validated_encoding(
    value: str,
    warnings: list[HtmlWarning],
    source: EncodingSource,
) -> str | None:
    try:
        return codecs.lookup(value.strip()).name
    except LookupError:
        warnings.append(
            _warning(
                HtmlWarningCode.INVALID_CHARSET,
                f"The {source.value} character encoding declaration is not recognized",
                WarningSeverity.WARNING,
                observed_value=value[:80],
            )
        )
        return None


def _bom_encoding(body: bytes) -> str | None:
    for marker, encoding in (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    ):
        if body.startswith(marker):
            return encoding
    return None


def _meta_encoding(prefix: bytes) -> tuple[str | None, EncodingSource | None]:
    scan = prefix.decode("latin-1", errors="ignore")
    soup = BeautifulSoup(scan, "html.parser")
    for tag in soup.find_all("meta"):
        charset = _attribute(tag, "charset")
        if charset:
            return charset, EncodingSource.META_CHARSET
        http_equiv = (_attribute(tag, "http-equiv") or "").strip().lower()
        content = _attribute(tag, "content")
        if http_equiv == "content-type" and content:
            charset = _header_charset(content)
            if charset:
                return charset, EncodingSource.META_HTTP_EQUIV
    return None, None


def _parse_document(decoded: str) -> tuple[BeautifulSoup, bool]:
    parser = etree.HTMLParser(recover=True)
    try:
        etree.fromstring(decoded.encode("utf-8"), parser=parser)
    except etree.XMLSyntaxError:
        recovered = True
    else:
        recovered = any(entry.level_name in {"ERROR", "FATAL"} for entry in parser.error_log)
    lowered = decoded.lower()
    recovered = recovered or any(
        len(re.findall(rf"<{name}(?:\s|>)", lowered)) > len(re.findall(rf"</{name}\s*>", lowered))
        for name in _RECOVERY_SENSITIVE_ELEMENTS
    )
    return BeautifulSoup(decoded, "lxml"), recovered


def _extract_text_metadata(
    tags: list[Tag],
    *,
    warnings: list[HtmlWarning],
    rules: _TextRules,
) -> TextMetadataEvidence:
    observations: list[TextObservation] = []
    for index, tag in enumerate(tags):
        raw = (
            tag.get_text(" ", strip=False)
            if rules.attribute is None
            else (_attribute(tag, rules.attribute) or "")
        )
        observations.append(TextObservation(raw, _normalize_text(raw), index))
    if not observations:
        warnings.append(
            _warning(
                rules.missing,
                f"The document has no {rules.label} element",
                WarningSeverity.WARNING,
            )
        )
        return TextMetadataEvidence(None, None, ())

    selected = observations[0].normalized_value or None
    if any(not observation.normalized_value for observation in observations):
        warnings.append(
            _warning(
                rules.empty,
                f"At least one {rules.label} value is empty",
                WarningSeverity.WARNING,
            )
        )
    if len(observations) > 1:
        warnings.append(
            _warning(
                rules.multiple,
                f"The document contains multiple {rules.label} values",
                WarningSeverity.WARNING,
            )
        )
    nonempty = {item.normalized_value for item in observations if item.normalized_value}
    if len(nonempty) > 1:
        warnings.append(
            _warning(
                rules.conflicting,
                f"The document contains conflicting nonempty {rules.label} values",
                WarningSeverity.WARNING,
            )
        )
    if selected is not None and len(selected) < rules.minimum_length:
        warnings.append(
            _warning(
                rules.short,
                f"The selected {rules.label} is shorter than {rules.minimum_length} characters",
                WarningSeverity.INFO,
            )
        )
    if selected is not None and len(selected) > rules.maximum_length:
        warnings.append(
            _warning(
                rules.long,
                f"The selected {rules.label} is longer than {rules.maximum_length} characters",
                WarningSeverity.INFO,
            )
        )
    return TextMetadataEvidence(
        selected, len(selected) if selected is not None else None, tuple(observations)
    )


def _description_tags(soup: BeautifulSoup) -> list[Tag]:
    return [
        tag
        for tag in soup.find_all("meta")
        if (_attribute(tag, "name") or "").strip().lower() == "description"
    ]


def _extract_base(
    soup: BeautifulSoup,
    document_url: NormalizedUrl,
    warnings: list[HtmlWarning],
) -> BaseUrlEvidence:
    tags = list(soup.find_all("base"))
    if len(tags) > 1:
        warnings.append(
            _warning(
                HtmlWarningCode.MULTIPLE_BASE_ELEMENTS,
                "The document contains multiple base elements; the first valid value is effective",
                WarningSeverity.WARNING,
            )
        )
    observations: list[UrlObservation] = []
    selected: NormalizedUrl | None = None
    for index, tag in enumerate(tags):
        raw = _attribute(tag, "href")
        if raw is None or not raw.strip():
            observations.append(UrlObservation(raw, None, index, "empty_url"))
            warnings.append(
                _warning(
                    HtmlWarningCode.EMPTY_BASE_HREF,
                    "A base element has no usable href",
                    WarningSeverity.WARNING,
                    occurrence_index=index,
                )
            )
            continue
        try:
            candidate = normalize_url(raw, base=document_url)
        except UrlNormalizationError as error:
            observations.append(UrlObservation(raw, None, index, error.code.value))
            warnings.append(
                _warning(
                    HtmlWarningCode.INVALID_BASE_HREF,
                    "A base href is invalid or uses an unsupported URL scheme",
                    WarningSeverity.WARNING,
                    occurrence_index=index,
                    observed_value=_safe_raw_url(raw),
                )
            )
            continue
        observations.append(UrlObservation(raw, candidate.normalized, index))
        if selected is None:
            selected = candidate
            if candidate.hostname != document_url.hostname:
                warnings.append(
                    _warning(
                        HtmlWarningCode.CROSS_HOST_BASE_HREF,
                        "The effective base URL points to another hostname",
                        WarningSeverity.WARNING,
                        occurrence_index=index,
                        observed_value=_safe_url_summary(candidate),
                    )
                )
            if candidate.origin != document_url.origin:
                warnings.append(
                    _warning(
                        HtmlWarningCode.BASE_ORIGIN_DIFFERS,
                        "The effective base URL uses another scheme or port",
                        WarningSeverity.WARNING,
                        occurrence_index=index,
                        observed_value=_safe_url_summary(candidate),
                    )
                )
    effective = selected or document_url
    return BaseUrlEvidence(
        document_url=document_url.normalized,
        effective_url=effective.normalized,
        selected_base_url=selected.normalized if selected is not None else None,
        observations=tuple(observations),
    )


def _extract_canonical(
    soup: BeautifulSoup,
    document_url: NormalizedUrl,
    base: BaseUrlEvidence,
    warnings: list[HtmlWarning],
) -> CanonicalEvidence:
    tags = [tag for tag in soup.find_all("link") if "canonical" in _rel_tokens(tag)]
    if not tags:
        warnings.append(
            _warning(
                HtmlWarningCode.MISSING_CANONICAL,
                "The document has no canonical link element",
                WarningSeverity.INFO,
            )
        )
        return CanonicalEvidence(None, ())
    if len(tags) > 1:
        warnings.append(
            _warning(
                HtmlWarningCode.MULTIPLE_CANONICALS,
                "The document contains multiple canonical link elements",
                WarningSeverity.WARNING,
            )
        )
    effective_base = normalize_url(base.effective_url)
    observations: list[UrlObservation] = []
    valid: list[NormalizedUrl] = []
    for index, tag in enumerate(tags):
        raw = _attribute(tag, "href")
        if raw is None or not raw.strip():
            observations.append(UrlObservation(raw, None, index, "empty_url"))
            warnings.append(
                _warning(
                    HtmlWarningCode.EMPTY_CANONICAL,
                    "A canonical link has no usable href",
                    WarningSeverity.WARNING,
                    occurrence_index=index,
                )
            )
            continue
        try:
            candidate = normalize_url(raw, base=effective_base)
        except UrlNormalizationError as error:
            observations.append(UrlObservation(raw, None, index, error.code.value))
            warnings.append(
                _warning(
                    HtmlWarningCode.INVALID_CANONICAL,
                    "A canonical target is invalid or uses an unsupported URL scheme",
                    WarningSeverity.WARNING,
                    occurrence_index=index,
                    observed_value=_safe_raw_url(raw),
                )
            )
            _LOGGER.info("html_invalid_canonical", extra={"value": _safe_raw_url(raw)})
            continue
        observations.append(UrlObservation(raw, candidate.normalized, index))
        valid.append(candidate)
        if candidate.hostname != document_url.hostname:
            warnings.append(
                _warning(
                    HtmlWarningCode.CROSS_HOST_CANONICAL,
                    "A canonical target points to another hostname",
                    WarningSeverity.WARNING,
                    occurrence_index=index,
                    observed_value=_safe_url_summary(candidate),
                )
            )
        if candidate.origin != document_url.origin:
            warnings.append(
                _warning(
                    HtmlWarningCode.CANONICAL_ORIGIN_DIFFERS,
                    "A canonical target uses another scheme or port",
                    WarningSeverity.WARNING,
                    occurrence_index=index,
                    observed_value=_safe_url_summary(candidate),
                )
            )
        if candidate.normalized != document_url.normalized:
            warnings.append(
                _warning(
                    HtmlWarningCode.CANONICAL_URL_DIFFERS,
                    "A canonical target differs from the fetched document URL",
                    WarningSeverity.INFO,
                    occurrence_index=index,
                    observed_value=_safe_url_summary(candidate),
                )
            )
    unique = {item.normalized for item in valid}
    if len(unique) > 1:
        warnings.append(
            _warning(
                HtmlWarningCode.CONFLICTING_CANONICALS,
                "Valid canonical elements identify conflicting normalized targets",
                WarningSeverity.WARNING,
            )
        )
    selected = next(iter(unique)) if len(unique) == 1 else None
    return CanonicalEvidence(selected, tuple(observations))


def _extract_robots(
    soup: BeautifulSoup,
    warnings: list[HtmlWarning],
) -> tuple[MetaRobotsRecord, ...]:
    records: list[MetaRobotsRecord] = []
    for tag in soup.find_all("meta"):
        agent = (_attribute(tag, "name") or "").strip().lower()
        if agent != "robots" and not agent.endswith("bot"):
            continue
        raw = _attribute(tag, "content")
        directives = _parse_robots_directives(raw, len(records), warnings)
        records.append(MetaRobotsRecord(agent, raw, directives, len(records)))

    names = {directive.name for record in records for directive in record.directives}
    if ({"index", "noindex"} <= names) or ({"follow", "nofollow"} <= names):
        warnings.append(
            _warning(
                HtmlWarningCode.CONFLICTING_META_ROBOTS,
                "Meta robots records contain conflicting index or follow directives",
                WarningSeverity.WARNING,
            )
        )
    return tuple(records)


def _parse_robots_directives(
    raw: str | None,
    occurrence_index: int,
    warnings: list[HtmlWarning],
) -> tuple[RobotsDirective, ...]:
    if raw is None or not raw.strip():
        warnings.append(
            _warning(
                HtmlWarningCode.EMPTY_META_ROBOTS,
                "A meta robots element has empty content",
                WarningSeverity.WARNING,
                occurrence_index=occurrence_index,
            )
        )
        return ()
    tokens: list[str] = []
    for chunk in raw.split(","):
        stripped = chunk.strip()
        if not stripped:
            warnings.append(
                _warning(
                    HtmlWarningCode.INVALID_META_ROBOTS_DIRECTIVE,
                    "Meta robots content contains an empty directive",
                    WarningSeverity.WARNING,
                    occurrence_index=occurrence_index,
                )
            )
            continue
        leading_name = stripped.split(":", 1)[0].strip().lower()
        if ":" in stripped and leading_name in _PARAMETERIZED_ROBOTS_DIRECTIVES:
            tokens.append(stripped)
        else:
            tokens.extend(stripped.split())

    directives: list[RobotsDirective] = []
    for token in tokens:
        name_part, separator, value_part = token.partition(":")
        name = name_part.strip().lower()
        value = value_part.strip() if separator else None
        valid = bool(_ROBOTS_NAME_PATTERN.fullmatch(name)) and not (separator and not value)
        known = name in _KNOWN_ROBOTS_DIRECTIVES
        directives.append(RobotsDirective(name, value, token, known))
        if not valid:
            warnings.append(
                _warning(
                    HtmlWarningCode.INVALID_META_ROBOTS_DIRECTIVE,
                    "A meta robots directive has invalid syntax",
                    WarningSeverity.WARNING,
                    occurrence_index=occurrence_index,
                    observed_value=token[:80],
                )
            )
        elif not known:
            warnings.append(
                _warning(
                    HtmlWarningCode.UNKNOWN_META_ROBOTS_DIRECTIVE,
                    "A meta robots directive is not in the recognized directive set",
                    WarningSeverity.INFO,
                    occurrence_index=occurrence_index,
                    observed_value=name[:80],
                )
            )
    return tuple(directives)


def _extract_links(
    soup: BeautifulSoup,
    document_url: NormalizedUrl,
    base: BaseUrlEvidence,
    scope: CrawlScopePolicy | None,
    warnings: list[HtmlWarning],
) -> tuple[LinkRecord, ...]:
    effective_base = normalize_url(base.effective_url)
    records: list[LinkRecord] = []
    invalid_count = 0
    for index, tag in enumerate(soup.find_all(["a", "area"])):
        raw = _attribute(tag, "href")
        stripped = raw.strip() if raw is not None else ""
        empty = not stripped
        fragment_only = stripped.startswith("#") if stripped else False
        malformed = False
        try:
            scheme = urlsplit(stripped).scheme.lower() if stripped else ""
        except ValueError:
            scheme = ""
            malformed = True
        unsupported = bool(scheme and scheme not in {"http", "https"})
        javascript = scheme == "javascript"
        normalized: NormalizedUrl | None = None
        if empty:
            warnings.append(
                _warning(
                    HtmlWarningCode.EMPTY_LINK_HREF,
                    "A navigable link has no usable href",
                    WarningSeverity.INFO,
                    occurrence_index=index,
                )
            )
        elif unsupported:
            warning_code = (
                HtmlWarningCode.JAVASCRIPT_LINK
                if javascript
                else HtmlWarningCode.UNSUPPORTED_LINK_SCHEME
            )
            warnings.append(
                _warning(
                    warning_code,
                    "A link uses JavaScript" if javascript else "A link uses a non-HTTP scheme",
                    WarningSeverity.WARNING if javascript else WarningSeverity.INFO,
                    occurrence_index=index,
                    observed_value=scheme,
                )
            )
        elif not malformed:
            try:
                normalized = normalize_url(stripped, base=effective_base)
            except UrlNormalizationError, ValueError:
                malformed = True
        if malformed:
            invalid_count += 1
            warnings.append(
                _warning(
                    HtmlWarningCode.INVALID_LINK_HREF,
                    "A navigable link href cannot be normalized",
                    WarningSeverity.WARNING,
                    occurrence_index=index,
                    observed_value=_safe_raw_url(stripped),
                )
            )
        rel_tokens = _rel_tokens(tag)
        scope_allowed: bool | None = None
        scope_reason: str | None = None
        if normalized is not None and scope is not None:
            decision = evaluate_scope(scope, normalized)
            scope_allowed = decision.allowed
            scope_reason = decision.reason_code.value
        anchor = _normalize_text(tag.get_text(" ", strip=False)) if tag.name == "a" else None
        records.append(
            LinkRecord(
                occurrence_index=index,
                element_type=tag.name,
                raw_href=raw,
                normalized_url=normalized.normalized if normalized is not None else None,
                anchor_text=anchor,
                rel_tokens=rel_tokens,
                nofollow="nofollow" in rel_tokens,
                href_empty=empty,
                fragment_only=fragment_only,
                unsupported_scheme=unsupported,
                javascript=javascript,
                malformed=malformed,
                same_document=(
                    normalized.normalized == document_url.normalized
                    if normalized is not None
                    else None
                ),
                same_host=(
                    normalized.hostname == document_url.hostname if normalized is not None else None
                ),
                in_scope=scope_allowed,
                scope_reason_code=scope_reason,
            )
        )
    if invalid_count:
        _LOGGER.info("html_invalid_links", extra={"invalid_link_count": invalid_count})
    return tuple(records)


def _attribute(tag: Tag, name: str) -> str | None:
    value = tag.get(name)
    if value is None:
        return None
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def _rel_tokens(tag: Tag) -> tuple[str, ...]:
    value = tag.get("rel")
    if value is None:
        return ()
    raw_tokens = value if isinstance(value, list) else str(value).split()
    return tuple(str(token).lower() for token in raw_tokens)


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _warning(
    code: HtmlWarningCode,
    explanation: str,
    severity: WarningSeverity,
    *,
    occurrence_index: int | None = None,
    observed_value: str | None = None,
) -> HtmlWarning:
    return HtmlWarning(code, explanation, severity, occurrence_index, observed_value)


def _safe_url_summary(value: NormalizedUrl) -> str:
    path = urlsplit(value.normalized).path or "/"
    return f"{value.origin}{path}"


def _safe_raw_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return "[invalid-url]"
    if not parts.scheme or parts.hostname is None:
        return parts.path[:160]
    port = ""
    try:
        if parts.port is not None:
            port = f":{parts.port}"
    except ValueError:
        port = ":[invalid-port]"
    return f"{parts.scheme.lower()}://{parts.hostname.lower()}{port}{parts.path or '/'}"[:200]
