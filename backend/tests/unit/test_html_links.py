"""Navigable link extraction and scope evidence tests."""

from __future__ import annotations

import pytest

from musimack_tools.crawl.html import HtmlMetadataParser
from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import create_scope_policy
from musimack_tools.domain.fetching import FetchOutcome, FetchResult, ResponseHeaders
from musimack_tools.domain.html import HtmlParseResult, HtmlWarningCode
from musimack_tools.domain.urls import ScopeMode

_URL = "https://example.test/directory/page"


def _parse(html: str, *, with_scope: bool = False) -> HtmlParseResult:
    body = html.encode()
    fetch = FetchResult(
        requested_url=_URL,
        final_url=_URL,
        outcome=FetchOutcome.SUCCESS,
        status_code=200,
        headers=ResponseHeaders(content_type="text/html; charset=utf-8"),
        content_type="text/html; charset=utf-8",
        declared_content_length=len(body),
        actual_bytes_read=len(body),
        body_truncated=False,
        redirect_chain=(),
        request_duration_seconds=0.01,
        dns_evidence=(),
        failure_code=None,
        failure_explanation=None,
        body=body,
    )
    scope = (
        create_scope_policy(normalize_url(_URL), mode=ScopeMode.EXACT_HOST) if with_scope else None
    )
    return HtmlMetadataParser().parse(fetch, scope=scope)


def _codes(result: HtmlParseResult) -> set[HtmlWarningCode]:
    return {warning.code for warning in result.warnings}


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("http://example.test/path", "http://example.test/path"),
        ("https://example.test/path", "https://example.test/path"),
        ("child", "https://example.test/directory/child"),
        ("/root", "https://example.test/root"),
        ("../parent", "https://example.test/parent"),
        ("?page=2", "https://example.test/directory/page?page=2"),
        ("#section", _URL),
    ],
)
def test_http_and_relative_links_are_normalized(href: str, expected: str) -> None:
    link = _parse(f'<a href="{href}">Link</a>').links[0]

    assert link.normalized_url == expected
    assert link.raw_href == href


def test_fragment_only_link_is_same_document() -> None:
    link = _parse('<a href="#section">Section</a>').links[0]

    assert link.fragment_only is True
    assert link.same_document is True
    assert link.same_host is True


@pytest.mark.parametrize("html", ["<a>Missing</a>", '<a href="">Empty</a>', '<area href="">'])
def test_empty_or_missing_href_is_recorded(html: str) -> None:
    result = _parse(html)

    assert result.links[0].href_empty is True
    assert result.links[0].normalized_url is None
    assert HtmlWarningCode.EMPTY_LINK_HREF in _codes(result)


@pytest.mark.parametrize(
    ("href", "scheme"),
    [
        ("mailto:hello@example.test", "mailto"),
        ("tel:+15551234567", "tel"),
        ("sms:+15551234567", "sms"),
        ("data:text/plain,hello", "data"),
        ("ftp://example.test/file", "ftp"),
    ],
)
def test_non_http_links_are_preserved_but_not_normalized(href: str, scheme: str) -> None:
    result = _parse(f'<a href="{href}">Link</a>')
    link = result.links[0]

    assert link.raw_href == href
    assert link.normalized_url is None
    assert link.unsupported_scheme is True
    assert link.javascript is False
    assert any(warning.observed_value == scheme for warning in result.warnings)


def test_javascript_link_is_explicitly_flagged_without_execution() -> None:
    result = _parse('<a href="javascript:alert(1)">Unsafe</a>')

    assert result.links[0].javascript is True
    assert result.links[0].normalized_url is None
    assert HtmlWarningCode.JAVASCRIPT_LINK in _codes(result)


@pytest.mark.parametrize(
    "href", ["https://example.test:bad/", "http://[invalid/", "https://example.test/%ZZ"]
)
def test_malformed_links_are_flagged(href: str) -> None:
    result = _parse(f'<a href="{href}">Malformed</a>')

    assert result.links[0].malformed is True
    assert result.links[0].normalized_url is None
    assert HtmlWarningCode.INVALID_LINK_HREF in _codes(result)


def test_effective_base_resolves_links() -> None:
    result = _parse('<base href="/catalog/"><a href="item">Item</a>')

    assert result.links[0].normalized_url == "https://example.test/catalog/item"


def test_anchor_text_combines_descendants_and_normalizes_entities() -> None:
    link = _parse(
        '<a href="/music">  Music <strong>&amp; artists</strong>\n now <img alt="ignored"> </a>'
    ).links[0]

    assert link.anchor_text == "Music & artists now"


def test_rel_tokens_and_nofollow_are_case_normalized() -> None:
    link = _parse('<a href="/path" rel="Sponsored NOFOLLOW external">Link</a>').links[0]

    assert link.rel_tokens == ("sponsored", "nofollow", "external")
    assert link.nofollow is True


def test_same_and_cross_host_evidence() -> None:
    result = _parse(
        '<a href="/internal">Internal</a><a href="https://other.test/path">External</a>'
    )

    assert result.links[0].same_host is True
    assert result.links[1].same_host is False
    assert result.links[1].same_document is False


def test_optional_scope_evidence_uses_existing_policy() -> None:
    result = _parse(
        '<a href="/internal">Internal</a><a href="https://other.test/path">External</a>',
        with_scope=True,
    )

    assert result.links[0].in_scope is True
    assert result.links[0].scope_reason_code == "allowed_exact_host"
    assert result.links[1].in_scope is False
    assert result.links[1].scope_reason_code == "denied_host_mismatch"


def test_scope_evidence_is_absent_when_no_policy_is_supplied() -> None:
    link = _parse('<a href="/internal">Internal</a>').links[0]

    assert link.in_scope is None
    assert link.scope_reason_code is None


def test_repeated_links_remain_in_document_order() -> None:
    result = _parse('<a href="/same">First</a><a href="/same">Second</a><a href="/other">Third</a>')

    assert [link.occurrence_index for link in result.links] == [0, 1, 2]
    assert [link.anchor_text for link in result.links] == ["First", "Second", "Third"]
    assert result.links[0].normalized_url == result.links[1].normalized_url


def test_area_href_is_included_without_anchor_text() -> None:
    link = _parse('<map><area href="/mapped" alt="Map target"></map>').links[0]

    assert link.element_type == "area"
    assert link.normalized_url == "https://example.test/mapped"
    assert link.anchor_text is None


def test_resource_elements_are_excluded() -> None:
    result = _parse(
        '<img src="/image.png"><script src="/app.js"></script><link href="/style.css">'
        '<source src="/media"><video src="/video"><audio src="/audio">'
    )

    assert result.links == ()


def test_metadata_in_body_is_still_observed() -> None:
    result = _parse(
        "<html><body><title>Body metadata title</title>"
        '<meta name="description" content="Body description retained as evidence for later '
        'review workflows.">'
        '<a href="/page">Page</a></body></html>'
    )

    assert result.title.selected_value == "Body metadata title"
    assert result.meta_description.selected_value is not None
    assert len(result.links) == 1
