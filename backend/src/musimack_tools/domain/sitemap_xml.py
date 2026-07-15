"""Immutable contracts for deterministic in-memory XML sitemap generation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from musimack_tools.sitemap.limits import SitemapXmlConfiguration

SITEMAP_XML_FORMAT_VERSION = "sitemap-xml-v1"
SITEMAP_XML_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"
SITEMAP_XML_MEDIA_TYPE = "application/xml; charset=utf-8"
SITEMAP_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'
SITEMAP_XML_NEWLINE = "\n"
PROTOCOL_MAX_URL_ENTRIES = 50_000
PROTOCOL_MAX_DOCUMENT_BYTES = 52_428_800
PROTOCOL_MAX_INDEX_ENTRIES = 50_000
PROTOCOL_MAX_INDEX_BYTES = 52_428_800
PROTOCOL_MAX_LOCATION_CHARACTERS = 2_048


class SitemapEntryRejectionReason(StrEnum):
    """Stable reasons an included recommendation cannot be serialized."""

    INVALID_URL = "invalid_url"
    UNSUPPORTED_SCHEME = "unsupported_scheme"
    MISSING_HOST = "missing_host"
    URL_TOO_LONG = "url_too_long"
    XML_ILLEGAL_CHARACTER = "xml_illegal_character"
    ENTRY_EXCEEDS_DOCUMENT_BYTE_LIMIT = "entry_exceeds_document_byte_limit"


class SitemapBundleWarningCode(StrEnum):
    """Stable non-entry conditions that block optional index generation."""

    INDEX_BLOCKED_MISSING_BASE_URL = "index_blocked_missing_base_url"
    INDEX_BLOCKED_ENTRY_LIMIT = "index_blocked_entry_limit"
    INDEX_BLOCKED_BYTE_LIMIT = "index_blocked_byte_limit"


class SitemapSplitReason(StrEnum):
    """Stable reason a following URL document was started."""

    ENTRY_LIMIT = "entry_limit"
    BYTE_LIMIT = "byte_limit"


@dataclass(frozen=True, slots=True)
class SitemapUrlEntry:
    """One validated normalized URL selected for XML serialization."""

    location: str
    source_recommendation_index: int


@dataclass(frozen=True, slots=True)
class SitemapSerializationRejection:
    """One non-fatal included-input rejection in recommendation order."""

    source_recommendation_index: int
    supplied_url: str
    reason: SitemapEntryRejectionReason
    explanation: str


@dataclass(frozen=True, slots=True)
class SitemapBundleWarning:
    """One typed bundle-level warning in deterministic evaluation order."""

    code: SitemapBundleWarningCode
    explanation: str


@dataclass(frozen=True, slots=True)
class SitemapSplitEvent:
    """Evidence explaining one deterministic URL-document boundary."""

    completed_document_number: int
    reason: SitemapSplitReason
    next_location: str


@dataclass(frozen=True, slots=True)
class GeneratedSitemapDocument:
    """One immutable in-memory URL sitemap document."""

    logical_name: str
    entries: tuple[SitemapUrlEntry, ...]
    xml_bytes: bytes
    byte_count: int
    entry_count: int
    media_type: str = SITEMAP_XML_MEDIA_TYPE


@dataclass(frozen=True, slots=True)
class SitemapIndexEntry:
    """One ordered public location in a sitemap index."""

    document_logical_name: str
    location: str


@dataclass(frozen=True, slots=True)
class GeneratedSitemapIndex:
    """One immutable in-memory sitemap index document."""

    logical_name: str
    entries: tuple[SitemapIndexEntry, ...]
    xml_bytes: bytes
    byte_count: int
    entry_count: int
    media_type: str = SITEMAP_XML_MEDIA_TYPE


@dataclass(frozen=True, slots=True)
class SitemapSerializationCounts:
    """Stable counters covering every recommendation input and output."""

    considered_recommendations: int
    include_recommendation_inputs: int
    skipped_non_include: int
    unique_entries_emitted: int
    duplicate_suppression_count: int
    rejected_entry_count: int
    document_count: int


@dataclass(frozen=True, slots=True)
class SitemapXmlBundle:
    """Complete immutable in-memory XML sitemap output projection."""

    documents: tuple[GeneratedSitemapDocument, ...]
    index_document: GeneratedSitemapIndex | None
    rejections: tuple[SitemapSerializationRejection, ...]
    warnings: tuple[SitemapBundleWarning, ...]
    split_events: tuple[SitemapSplitEvent, ...]
    counts: SitemapSerializationCounts
    configuration_snapshot: SitemapXmlConfiguration
    format_version: str = SITEMAP_XML_FORMAT_VERSION

    @property
    def total_entries(self) -> int:
        return self.counts.unique_entries_emitted

    @property
    def total_documents(self) -> int:
        return self.counts.document_count
