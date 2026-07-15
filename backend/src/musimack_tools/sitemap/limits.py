"""Sitemap protocol limits and immutable validated XML configuration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.domain.sitemap_xml import (
    PROTOCOL_MAX_DOCUMENT_BYTES,
    PROTOCOL_MAX_INDEX_BYTES,
    PROTOCOL_MAX_INDEX_ENTRIES,
    PROTOCOL_MAX_LOCATION_CHARACTERS,
    PROTOCOL_MAX_URL_ENTRIES,
    SITEMAP_XML_DECLARATION,
    SITEMAP_XML_FORMAT_VERSION,
    SITEMAP_XML_NAMESPACE,
    SITEMAP_XML_NEWLINE,
)
from musimack_tools.domain.urls import UrlNormalizationError

_LOGICAL_FILENAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.xml\Z")
_FILENAME_PREFIX_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
MINIMUM_URL_DOCUMENT_BYTES = len(
    (
        f"{SITEMAP_XML_DECLARATION}{SITEMAP_XML_NEWLINE}"
        f'<urlset xmlns="{SITEMAP_XML_NAMESPACE}">{SITEMAP_XML_NEWLINE}'
        f"</urlset>{SITEMAP_XML_NEWLINE}"
    ).encode()
)
MINIMUM_INDEX_DOCUMENT_BYTES = len(
    (
        f"{SITEMAP_XML_DECLARATION}{SITEMAP_XML_NEWLINE}"
        f'<sitemapindex xmlns="{SITEMAP_XML_NAMESPACE}">{SITEMAP_XML_NEWLINE}'
        f"</sitemapindex>{SITEMAP_XML_NEWLINE}"
    ).encode()
)


@dataclass(frozen=True, slots=True)
class SitemapXmlConfiguration:
    """Validated effective limits and logical naming for one generation run."""

    url_entries_per_document_limit: int = PROTOCOL_MAX_URL_ENTRIES
    url_document_byte_limit: int = PROTOCOL_MAX_DOCUMENT_BYTES
    index_entries_limit: int = PROTOCOL_MAX_INDEX_ENTRIES
    index_document_byte_limit: int = PROTOCOL_MAX_INDEX_BYTES
    url_maximum_characters: int = PROTOCOL_MAX_LOCATION_CHARACTERS
    single_document_name: str = "sitemap.xml"
    split_document_prefix: str = "sitemap"
    index_document_name: str = "sitemap-index.xml"
    sitemap_base_url: str | None = None
    format_version: str = SITEMAP_XML_FORMAT_VERSION

    def __post_init__(self) -> None:
        _bounded_positive(
            "URL entry limit",
            self.url_entries_per_document_limit,
            PROTOCOL_MAX_URL_ENTRIES,
        )
        _bounded_positive(
            "URL document byte limit",
            self.url_document_byte_limit,
            PROTOCOL_MAX_DOCUMENT_BYTES,
            minimum=MINIMUM_URL_DOCUMENT_BYTES,
        )
        _bounded_positive("index entry limit", self.index_entries_limit, PROTOCOL_MAX_INDEX_ENTRIES)
        _bounded_positive(
            "index document byte limit",
            self.index_document_byte_limit,
            PROTOCOL_MAX_INDEX_BYTES,
            minimum=MINIMUM_INDEX_DOCUMENT_BYTES,
        )
        _bounded_positive(
            "URL character limit",
            self.url_maximum_characters,
            PROTOCOL_MAX_LOCATION_CHARACTERS,
        )
        if not _LOGICAL_FILENAME_PATTERN.fullmatch(self.single_document_name):
            message = "single sitemap logical name must be a simple .xml filename"
            raise ValueError(message)
        if not _FILENAME_PREFIX_PATTERN.fullmatch(self.split_document_prefix):
            message = "split sitemap filename prefix contains invalid characters"
            raise ValueError(message)
        if not _LOGICAL_FILENAME_PATTERN.fullmatch(self.index_document_name):
            message = "sitemap index logical name must be a simple .xml filename"
            raise ValueError(message)
        if self.format_version != SITEMAP_XML_FORMAT_VERSION:
            message = f"format version must be {SITEMAP_XML_FORMAT_VERSION}"
            raise ValueError(message)
        if self.sitemap_base_url is not None:
            object.__setattr__(self, "sitemap_base_url", _normalize_base_url(self.sitemap_base_url))


def _bounded_positive(
    label: str,
    value: int,
    maximum: int,
    *,
    minimum: int = 1,
) -> None:
    if value < minimum:
        message = f"{label} must be at least {minimum}"
        raise ValueError(message)
    if value > maximum:
        message = f"{label} cannot exceed protocol maximum {maximum}"
        raise ValueError(message)


def _normalize_base_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.fragment:
        message = "sitemap base URL cannot contain a fragment"
        raise ValueError(message)
    if parts.query:
        message = "sitemap base URL cannot contain a query"
        raise ValueError(message)
    try:
        normalized = normalize_url(value)
    except UrlNormalizationError as error:
        message = "sitemap base URL must be an absolute HTTP or HTTPS URL with a valid host"
        raise ValueError(message) from error
    normalized_parts = urlsplit(normalized.normalized)
    path = (
        normalized_parts.path
        if normalized_parts.path.endswith("/")
        else f"{normalized_parts.path}/"
    )
    return urlunsplit(
        (
            normalized_parts.scheme,
            normalized_parts.netloc,
            path,
            "",
            "",
        )
    )
