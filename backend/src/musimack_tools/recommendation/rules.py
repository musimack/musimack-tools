"""Deterministic sitemap recommendation rule helpers."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

from musimack_tools.domain.crawl import CrawlExclusionRule, ExclusionRuleType
from musimack_tools.domain.fetching import FetchFailureCode
from musimack_tools.domain.sitemap import ConfiguredExclusionEvidence, SitemapReasonCode

REDIRECT_FAILURE_CODES = frozenset(
    {
        FetchFailureCode.REDIRECT_MISSING_LOCATION,
        FetchFailureCode.REDIRECT_INVALID_LOCATION,
        FetchFailureCode.REDIRECT_LOOP,
        FetchFailureCode.REDIRECT_LIMIT_EXCEEDED,
        FetchFailureCode.REDIRECT_SCOPE_DENIED,
        FetchFailureCode.REDIRECT_UNSAFE_DESTINATION,
    }
)

HTML_MEDIA_TYPES = frozenset({"text/html", "application/xhtml+xml"})

METADATA_WARNING_CODES = frozenset(
    {
        "missing_title",
        "empty_title",
        "short_title",
        "long_title",
        "multiple_titles",
        "conflicting_titles",
        "missing_meta_description",
        "empty_meta_description",
        "short_meta_description",
        "long_meta_description",
        "multiple_meta_descriptions",
        "conflicting_meta_descriptions",
    }
)


def fetch_failure_reason(code: FetchFailureCode | None) -> SitemapReasonCode:
    """Map accepted fetch failures without discarding the original code."""
    if code is FetchFailureCode.RESPONSE_TOO_LARGE:
        return SitemapReasonCode.RESPONSE_TOO_LARGE
    if code in REDIRECT_FAILURE_CODES:
        return SitemapReasonCode.REDIRECT_FAILED
    return SitemapReasonCode.FETCH_FAILED


def configured_exclusion_matches(
    normalized_url: str,
    rules: tuple[CrawlExclusionRule, ...],
) -> tuple[ConfiguredExclusionEvidence, ...]:
    """Return every matching accepted crawl exclusion rule in configured order."""
    parts = urlsplit(normalized_url)
    query_names = {name for name, _value in parse_qsl(parts.query, keep_blank_values=True)}
    matches: list[ConfiguredExclusionEvidence] = []
    for rule in rules:
        matched = (
            (rule.rule_type is ExclusionRuleType.EXACT_PATH and parts.path == rule.value)
            or (
                rule.rule_type is ExclusionRuleType.PATH_PREFIX
                and _path_prefix_matches(parts.path, rule.value)
            )
            or (rule.rule_type is ExclusionRuleType.QUERY_PARAMETER and rule.value in query_names)
        )
        if matched:
            matches.append(ConfiguredExclusionEvidence(rule.rule_type.value, rule.value))
    return tuple(matches)


def _path_prefix_matches(path: str, configured_prefix: str) -> bool:
    """Match a path prefix on segment boundaries without changing path case or encoding."""
    if configured_prefix == "/":
        return path.startswith("/")
    segment_prefix = configured_prefix.rstrip("/")
    return path == segment_prefix or path.startswith(f"{segment_prefix}/")
