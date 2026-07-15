"""Deterministic in-memory XML sitemap serializer over recommendation projections."""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.domain.sitemap import RecommendationState, SitemapRecommendationProjection
from musimack_tools.domain.sitemap_xml import (
    SITEMAP_XML_DECLARATION,
    SITEMAP_XML_FORMAT_VERSION,
    SITEMAP_XML_NAMESPACE,
    SITEMAP_XML_NEWLINE,
    GeneratedSitemapDocument,
    GeneratedSitemapIndex,
    SitemapBundleWarning,
    SitemapBundleWarningCode,
    SitemapEntryRejectionReason,
    SitemapIndexEntry,
    SitemapSerializationCounts,
    SitemapSerializationRejection,
    SitemapSplitEvent,
    SitemapSplitReason,
    SitemapUrlEntry,
    SitemapXmlBundle,
)
from musimack_tools.domain.urls import UrlErrorCode, UrlNormalizationError
from musimack_tools.sitemap.limits import SitemapXmlConfiguration

_XML_ESCAPE_ENTITIES = {'"': "&quot;", "'": "&apos;"}
_XML_LEGAL_CONTROLS = frozenset({0x09, 0x0A, 0x0D})
_XML_BASIC_MIN = 0x20
_XML_BASIC_MAX = 0xD7FF
_XML_BMP_SUPPLEMENT_MIN = 0xE000
_XML_BMP_SUPPLEMENT_MAX = 0xFFFD
_XML_ASTRAL_MIN = 0x10000
_XML_ASTRAL_MAX = 0x10FFFF


@dataclass(frozen=True, slots=True)
class _EntryGroup:
    entries: tuple[SitemapUrlEntry, ...]
    xml_bytes: bytes


class SitemapXmlGenerator:
    """Serialize only accepted include recommendations into immutable XML bytes."""

    def __init__(self, configuration: SitemapXmlConfiguration | None = None) -> None:
        self._configuration = configuration or SitemapXmlConfiguration()

    def generate(self, projection: SitemapRecommendationProjection) -> SitemapXmlBundle:
        """Generate a deterministic in-memory bundle without mutating recommendation evidence."""
        valid_entries: list[SitemapUrlEntry] = []
        rejections: list[SitemapSerializationRejection] = []
        seen: set[str] = set()
        include_inputs = 0
        duplicates = 0

        for index, recommendation in enumerate(projection.recommendations):
            if recommendation.state is not RecommendationState.INCLUDE:
                continue
            include_inputs += 1
            validated = _validate_entry(
                recommendation.evaluated_url,
                index,
                self._configuration.url_maximum_characters,
            )
            if isinstance(validated, SitemapSerializationRejection):
                rejections.append(validated)
                continue
            if validated.location in seen:
                duplicates += 1
                continue
            seen.add(validated.location)
            valid_entries.append(validated)

        groups, split_events, size_rejections = _split_entries(
            tuple(valid_entries),
            self._configuration,
        )
        rejections.extend(size_rejections)
        documents = _documents(groups, self._configuration)
        index_document, warnings = _index_document(documents, self._configuration)
        emitted_count = sum(item.entry_count for item in documents)
        counts = SitemapSerializationCounts(
            considered_recommendations=len(projection.recommendations),
            include_recommendation_inputs=include_inputs,
            skipped_non_include=len(projection.recommendations) - include_inputs,
            unique_entries_emitted=emitted_count,
            duplicate_suppression_count=duplicates,
            rejected_entry_count=len(rejections),
            document_count=len(documents),
        )
        return SitemapXmlBundle(
            documents=documents,
            index_document=index_document,
            rejections=tuple(rejections),
            warnings=warnings,
            split_events=split_events,
            counts=counts,
            configuration_snapshot=self._configuration,
            format_version=SITEMAP_XML_FORMAT_VERSION,
        )


def _validate_entry(
    value: str,
    source_index: int,
    maximum_characters: int,
) -> SitemapUrlEntry | SitemapSerializationRejection:
    if not value:
        return _rejection(
            source_index, value, SitemapEntryRejectionReason.INVALID_URL, "URL is empty"
        )
    if any(not _is_xml_legal(character) for character in value):
        return _rejection(
            source_index,
            value,
            SitemapEntryRejectionReason.XML_ILLEGAL_CHARACTER,
            "URL contains a character prohibited by XML 1.0",
        )
    if len(value) > maximum_characters:
        return _rejection(
            source_index,
            value,
            SitemapEntryRejectionReason.URL_TOO_LONG,
            f"URL exceeds the configured {maximum_characters}-character location limit",
        )
    try:
        normalized = normalize_url(value)
    except UrlNormalizationError as error:
        reason = (
            SitemapEntryRejectionReason.UNSUPPORTED_SCHEME
            if error.code is UrlErrorCode.UNSUPPORTED_SCHEME
            else SitemapEntryRejectionReason.MISSING_HOST
            if error.code is UrlErrorCode.MISSING_HOSTNAME
            else SitemapEntryRejectionReason.INVALID_URL
        )
        return _rejection(source_index, value, reason, "URL is invalid at the XML boundary")
    if normalized.normalized != value:
        return _rejection(
            source_index,
            value,
            SitemapEntryRejectionReason.INVALID_URL,
            "URL is not the accepted deterministic normalized identity",
        )
    return SitemapUrlEntry(value, source_index)


def _split_entries(
    entries: tuple[SitemapUrlEntry, ...],
    configuration: SitemapXmlConfiguration,
) -> tuple[
    tuple[_EntryGroup, ...],
    tuple[SitemapSplitEvent, ...],
    tuple[SitemapSerializationRejection, ...],
]:
    groups: list[_EntryGroup] = []
    split_events: list[SitemapSplitEvent] = []
    rejections: list[SitemapSerializationRejection] = []
    current: list[SitemapUrlEntry] = []
    empty_document_size = len(_urlset_xml(()))
    current_byte_size = empty_document_size

    for entry in entries:
        entry_byte_size = len(_url_entry_xml(entry))
        count_exceeded = len(current) + 1 > configuration.url_entries_per_document_limit
        bytes_exceeded = current_byte_size + entry_byte_size > configuration.url_document_byte_limit
        if not count_exceeded and not bytes_exceeded:
            current.append(entry)
            current_byte_size += entry_byte_size
            continue
        if empty_document_size + entry_byte_size > configuration.url_document_byte_limit:
            rejections.append(
                _rejection(
                    entry.source_recommendation_index,
                    entry.location,
                    SitemapEntryRejectionReason.ENTRY_EXCEEDS_DOCUMENT_BYTE_LIMIT,
                    "One URL entry cannot fit in an otherwise empty sitemap document",
                )
            )
            continue
        if current:
            groups.append(_EntryGroup(tuple(current), _urlset_xml(tuple(current))))
            reason = (
                SitemapSplitReason.ENTRY_LIMIT if count_exceeded else SitemapSplitReason.BYTE_LIMIT
            )
            split_events.append(SitemapSplitEvent(len(groups), reason, entry.location))
        current = [entry]
        current_byte_size = empty_document_size + entry_byte_size

    if current:
        groups.append(_EntryGroup(tuple(current), _urlset_xml(tuple(current))))
    if not groups:
        empty = _urlset_xml(())
        groups.append(_EntryGroup((), empty))
    return tuple(groups), tuple(split_events), tuple(rejections)


def _documents(
    groups: tuple[_EntryGroup, ...],
    configuration: SitemapXmlConfiguration,
) -> tuple[GeneratedSitemapDocument, ...]:
    multiple = len(groups) > 1
    return tuple(
        GeneratedSitemapDocument(
            logical_name=(
                f"{configuration.split_document_prefix}-{index}.xml"
                if multiple
                else configuration.single_document_name
            ),
            entries=group.entries,
            xml_bytes=group.xml_bytes,
            byte_count=len(group.xml_bytes),
            entry_count=len(group.entries),
        )
        for index, group in enumerate(groups, start=1)
    )


def _index_document(
    documents: tuple[GeneratedSitemapDocument, ...],
    configuration: SitemapXmlConfiguration,
) -> tuple[GeneratedSitemapIndex | None, tuple[SitemapBundleWarning, ...]]:
    if len(documents) <= 1:
        return None, ()
    if configuration.sitemap_base_url is None:
        return None, (
            SitemapBundleWarning(
                SitemapBundleWarningCode.INDEX_BLOCKED_MISSING_BASE_URL,
                "Multiple sitemap documents exist but no public sitemap base URL was configured",
            ),
        )
    if len(documents) > configuration.index_entries_limit:
        return None, (
            SitemapBundleWarning(
                SitemapBundleWarningCode.INDEX_BLOCKED_ENTRY_LIMIT,
                "Generated document count exceeds the configured v1 sitemap-index capacity",
            ),
        )
    entries = tuple(
        SitemapIndexEntry(
            document.logical_name, f"{configuration.sitemap_base_url}{document.logical_name}"
        )
        for document in documents
    )
    xml_bytes = _sitemap_index_xml(entries)
    if len(xml_bytes) > configuration.index_document_byte_limit:
        return None, (
            SitemapBundleWarning(
                SitemapBundleWarningCode.INDEX_BLOCKED_BYTE_LIMIT,
                "Generated sitemap index exceeds the configured uncompressed byte limit",
            ),
        )
    return (
        GeneratedSitemapIndex(
            logical_name=configuration.index_document_name,
            entries=entries,
            xml_bytes=xml_bytes,
            byte_count=len(xml_bytes),
            entry_count=len(entries),
        ),
        (),
    )


def _urlset_xml(entries: tuple[SitemapUrlEntry, ...]) -> bytes:
    opening = (
        f"{SITEMAP_XML_DECLARATION}{SITEMAP_XML_NEWLINE}"
        f'<urlset xmlns="{SITEMAP_XML_NAMESPACE}">{SITEMAP_XML_NEWLINE}'
    ).encode()
    closing = f"</urlset>{SITEMAP_XML_NEWLINE}".encode()
    return opening + b"".join(_url_entry_xml(entry) for entry in entries) + closing


def _url_entry_xml(entry: SitemapUrlEntry) -> bytes:
    return (
        f"  <url>{SITEMAP_XML_NEWLINE}"
        f"    <loc>{_xml_text(entry.location)}</loc>{SITEMAP_XML_NEWLINE}"
        f"  </url>{SITEMAP_XML_NEWLINE}"
    ).encode()


def _sitemap_index_xml(entries: tuple[SitemapIndexEntry, ...]) -> bytes:
    lines = [SITEMAP_XML_DECLARATION, f'<sitemapindex xmlns="{SITEMAP_XML_NAMESPACE}">']
    for entry in entries:
        lines.extend(("  <sitemap>", f"    <loc>{_xml_text(entry.location)}</loc>", "  </sitemap>"))
    lines.append("</sitemapindex>")
    return f"{SITEMAP_XML_NEWLINE.join(lines)}{SITEMAP_XML_NEWLINE}".encode()


def _xml_text(value: str) -> str:
    return escape(value, _XML_ESCAPE_ENTITIES)


def _is_xml_legal(character: str) -> bool:
    value = ord(character)
    return (
        value in _XML_LEGAL_CONTROLS
        or _XML_BASIC_MIN <= value <= _XML_BASIC_MAX
        or _XML_BMP_SUPPLEMENT_MIN <= value <= _XML_BMP_SUPPLEMENT_MAX
        or _XML_ASTRAL_MIN <= value <= _XML_ASTRAL_MAX
    )


def _rejection(
    source_index: int,
    supplied_url: str,
    reason: SitemapEntryRejectionReason,
    explanation: str,
) -> SitemapSerializationRejection:
    return SitemapSerializationRejection(source_index, supplied_url, reason, explanation)
