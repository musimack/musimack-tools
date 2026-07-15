"""Deterministic tests for bounded robots.txt parsing."""

from __future__ import annotations

import pytest

from musimack_tools.crawl.robots import RobotsTxtParser
from musimack_tools.domain.robots import (
    RobotsParseOutcome,
    RobotsParseResult,
    RobotsRuleKind,
    RobotsWarningCode,
)


def _parse(value: str | bytes) -> RobotsParseResult:
    body = value.encode() if isinstance(value, str) else value
    return RobotsTxtParser().parse(body)


def test_empty_file_has_empty_parse_outcome() -> None:
    result = _parse("")

    assert result.outcome is RobotsParseOutcome.EMPTY
    assert result.groups == ()


def test_comments_inline_comments_and_blank_lines_are_ignored() -> None:
    result = _parse("# heading\n\nUser-agent: * # all\nDisallow: /private # hidden")

    assert result.groups[0].user_agents[0].value == "*"
    assert result.groups[0].rules[0].pattern == "/private"
    assert result.groups[0].rules[0].line_number == 4


def test_utf8_bom_and_mixed_case_fields_are_supported() -> None:
    result = _parse(b"\xef\xbb\xbfUsEr-AgEnT: MusimackSEOToolkit\nDiSaLlOw: /private")

    assert result.groups[0].user_agents[0].value == "MusimackSEOToolkit"
    assert result.groups[0].rules[0].kind is RobotsRuleKind.DISALLOW


def test_consecutive_user_agents_share_one_group() -> None:
    result = _parse("User-agent: Alpha\nUser-agent: MusimackSEOToolkit\nDisallow: /one")

    assert len(result.groups) == 1
    assert [item.value for item in result.groups[0].user_agents] == [
        "Alpha",
        "MusimackSEOToolkit",
    ]


def test_invalid_user_agent_is_warned_and_not_applied() -> None:
    result = _parse("User-agent: invalid agent value\nDisallow: /")

    assert result.groups == ()
    assert RobotsWarningCode.INVALID_USER_AGENT in {item.code for item in result.warnings}


def test_new_user_agent_after_rules_starts_an_independent_group() -> None:
    result = _parse(
        "User-agent: MusimackSEOToolkit\nDisallow: /one\n"
        "User-agent: MusimackSEOToolkit\nDisallow: /two"
    )

    assert len(result.groups) == 2
    assert result.groups[0].rules[0].pattern == "/one"
    assert result.groups[1].rules[0].pattern == "/two"


def test_multiple_user_agent_groups_remain_in_source_order() -> None:
    result = _parse("User-agent: Other\nDisallow: /a\nUser-agent: *\nAllow: /")

    assert [group.group_index for group in result.groups] == [0, 1]
    assert [group.first_line_number for group in result.groups] == [1, 3]


def test_empty_disallow_is_preserved_as_allow_all_evidence() -> None:
    result = _parse("User-agent: *\nDisallow:")

    assert result.groups[0].rules[0].pattern == ""
    assert result.groups[0].rules[0].kind is RobotsRuleKind.DISALLOW


def test_empty_allow_records_invalid_rule_warning() -> None:
    result = _parse("User-agent: *\nAllow:")

    assert RobotsWarningCode.INVALID_RULE in {item.code for item in result.warnings}


@pytest.mark.parametrize("directive", ["Allow", "Disallow"])
def test_rule_values_preserve_case_percent_encoding_wildcards_and_anchor(directive: str) -> None:
    result = _parse(f"User-agent: *\n{directive}: /Case/%2F/*.pdf$")

    assert result.groups[0].rules[0].pattern == "/Case/%2F/*.pdf$"


def test_malformed_line_does_not_crash_parser() -> None:
    result = _parse("User-agent: *\nthis is malformed\nDisallow: /private")

    assert RobotsWarningCode.MALFORMED_LINE in {item.code for item in result.warnings}
    assert result.groups[0].rules[0].pattern == "/private"


def test_unknown_directive_is_preserved() -> None:
    result = _parse("User-agent: *\nHost: example.test")

    assert result.groups[0].unsupported_directives[0].field_name == "host"
    assert RobotsWarningCode.UNKNOWN_DIRECTIVE in {item.code for item in result.warnings}


def test_directive_before_user_agent_is_preserved_as_global_unsupported() -> None:
    result = _parse("Disallow: /private\nUser-agent: *\nAllow: /")

    assert result.unsupported_directives[0].field_name == "disallow"


def test_very_long_line_is_ignored_with_warning() -> None:
    parser = RobotsTxtParser(maximum_line_length=20)
    result = parser.parse(b"User-agent: *\nDisallow: /this-is-far-too-long")

    assert result.groups[0].rules == ()
    assert RobotsWarningCode.LINE_TOO_LONG in {item.code for item in result.warnings}


def test_excessive_line_count_is_bounded() -> None:
    parser = RobotsTxtParser(maximum_line_count=2)
    result = parser.parse(b"User-agent: *\nDisallow: /one\nDisallow: /two")

    assert result.line_count == 2
    assert RobotsWarningCode.LINE_LIMIT_EXCEEDED in {item.code for item in result.warnings}


def test_valid_crawl_delay_is_preserved_as_evidence() -> None:
    result = _parse("User-agent: *\nCrawl-delay: 1.5")

    assert result.groups[0].crawl_delays[0].seconds == 1.5


@pytest.mark.parametrize("value", ["invalid", "-1", "NaN", "Infinity"])
def test_invalid_crawl_delay_is_preserved_with_warning(value: str) -> None:
    result = _parse(f"User-agent: *\nCrawl-delay: {value}")

    assert result.groups[0].crawl_delays[0].seconds is None
    assert RobotsWarningCode.INVALID_CRAWL_DELAY in {item.code for item in result.warnings}


def test_conflicting_crawl_delays_are_reported() -> None:
    result = _parse("User-agent: *\nCrawl-delay: 1\nCrawl-delay: 2")

    assert RobotsWarningCode.CONFLICTING_CRAWL_DELAY in {item.code for item in result.warnings}


def test_valid_and_multiple_sitemaps_are_preserved_without_fetching() -> None:
    result = _parse(
        "Sitemap: https://example.test/sitemap.xml\nSitemap: https://cdn.example.test/index.xml"
    )

    assert [item.normalized_url for item in result.sitemap_directives] == [
        "https://example.test/sitemap.xml",
        "https://cdn.example.test/index.xml",
    ]


@pytest.mark.parametrize("value", ["/sitemap.xml", "ftp://example.test/sitemap.xml", "not a url"])
def test_invalid_relative_or_unsupported_sitemap_is_preserved(value: str) -> None:
    result = _parse(f"Sitemap: {value}")

    assert result.sitemap_directives[0].valid is False
    assert RobotsWarningCode.INVALID_SITEMAP in {item.code for item in result.warnings}


def test_invalid_utf8_uses_replacement_with_warning() -> None:
    result = _parse(b"User-agent: *\nDisallow: /bad-\xff")

    assert RobotsWarningCode.DECODE_WARNING in {item.code for item in result.warnings}
