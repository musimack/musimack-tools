"""Title, description, canonical, base, and robots extraction tests."""

from __future__ import annotations

import pytest

from musimack_tools.crawl.html import HtmlMetadataParser
from musimack_tools.domain.fetching import FetchOutcome, FetchResult, ResponseHeaders
from musimack_tools.domain.html import HtmlParseResult, HtmlWarningCode

_URL = "https://example.test/directory/page"


def _parse(html: str, *, url: str = _URL) -> HtmlParseResult:
    body = html.encode()
    fetch = FetchResult(
        requested_url=url,
        final_url=url,
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
    return HtmlMetadataParser().parse(fetch)


def _codes(result: HtmlParseResult) -> set[HtmlWarningCode]:
    return {warning.code for warning in result.warnings}


def test_normal_title_and_description_are_extracted() -> None:
    result = _parse(
        "<title>A practical metadata page title</title>"
        '<meta name="description" content="A useful page description with enough detail for a '
        'human metadata review workflow and reporting.">'
    )

    assert result.title.selected_value == "A practical metadata page title"
    assert result.title.selected_length == 31
    assert result.title.count == 1
    assert result.meta_description.selected_value is not None
    assert result.meta_description.selected_value.startswith("A useful page description")
    assert result.meta_description.count == 1


def test_title_text_normalizes_whitespace_and_entities() -> None:
    result = _parse("<title>  Music &amp;  <span>artist</span>\n tools </title>")

    assert result.title.selected_value == "Music & artist tools"
    assert result.title.observations[0].raw_value != result.title.selected_value


@pytest.mark.parametrize(
    ("html", "warning"),
    [
        ("<html></html>", HtmlWarningCode.MISSING_TITLE),
        ("<title>   </title>", HtmlWarningCode.EMPTY_TITLE),
        (f"<title>{'x' * 14}</title>", HtmlWarningCode.SHORT_TITLE),
        (f"<title>{'x' * 61}</title>", HtmlWarningCode.LONG_TITLE),
    ],
)
def test_title_quality_warnings(html: str, warning: HtmlWarningCode) -> None:
    assert warning in _codes(_parse(html))


def test_multiple_identical_titles_are_preserved_without_conflict() -> None:
    result = _parse(
        "<title>Identical metadata title</title><title>Identical metadata title</title>"
    )

    assert result.title.count == 2
    assert HtmlWarningCode.MULTIPLE_TITLES in _codes(result)
    assert HtmlWarningCode.CONFLICTING_TITLES not in _codes(result)


def test_multiple_conflicting_titles_are_preserved() -> None:
    result = _parse("<title>First metadata title</title><title>Second metadata title</title>")

    assert [item.normalized_value for item in result.title.observations] == [
        "First metadata title",
        "Second metadata title",
    ]
    assert HtmlWarningCode.CONFLICTING_TITLES in _codes(result)


@pytest.mark.parametrize(
    ("html", "warning"),
    [
        ("<title>Good metadata title</title>", HtmlWarningCode.MISSING_META_DESCRIPTION),
        ('<meta name="description">', HtmlWarningCode.EMPTY_META_DESCRIPTION),
        ('<meta name="description" content="">', HtmlWarningCode.EMPTY_META_DESCRIPTION),
        ('<meta name="description" content="short">', HtmlWarningCode.SHORT_META_DESCRIPTION),
        (
            f'<meta name="description" content="{"x" * 161}">',
            HtmlWarningCode.LONG_META_DESCRIPTION,
        ),
    ],
)
def test_description_quality_warnings(html: str, warning: HtmlWarningCode) -> None:
    assert warning in _codes(_parse(html))


def test_description_attribute_order_case_entities_and_whitespace() -> None:
    result = _parse(
        '<meta content="  Music &amp; artist   metadata for a detailed and useful page review '
        'workflow today.  " NAME="DeScRiPtIoN">'
    )

    assert result.meta_description.selected_value == (
        "Music & artist metadata for a detailed and useful page review workflow today."
    )


def test_multiple_description_conflicts_are_preserved() -> None:
    result = _parse(
        '<meta name="description" content="First description value for this page and its review '
        'workflow."><meta name="description" content="Second description value for this page and '
        'a different review workflow.">'
    )

    assert result.meta_description.count == 2
    assert HtmlWarningCode.MULTIPLE_META_DESCRIPTIONS in _codes(result)
    assert HtmlWarningCode.CONFLICTING_META_DESCRIPTIONS in _codes(result)


def test_multiple_identical_descriptions_are_not_marked_conflicting() -> None:
    description = "Identical description retained for a deterministic metadata review workflow."
    result = _parse(
        f'<meta name="description" content="{description}">'
        f'<meta name="description" content="{description}">'
    )

    assert result.meta_description.count == 2
    assert HtmlWarningCode.MULTIPLE_META_DESCRIPTIONS in _codes(result)
    assert HtmlWarningCode.CONFLICTING_META_DESCRIPTIONS not in _codes(result)


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("https://example.test/canonical", "https://example.test/canonical"),
        ("child", "https://example.test/directory/child"),
        ("/root", "https://example.test/root"),
        ("/directory/page#section", _URL),
    ],
)
def test_canonical_urls_are_normalized(href: str, expected: str) -> None:
    result = _parse(f'<link rel="canonical" href="{href}">')

    assert result.canonical.selected_url == expected
    assert result.canonical.observations[0].raw_value == href


def test_mixed_case_multitoken_canonical_rel_is_recognized() -> None:
    result = _parse('<link rel="Alternate CANONICAL" href="/chosen">')

    assert result.canonical.selected_url == "https://example.test/chosen"


def test_relative_canonical_uses_effective_base() -> None:
    result = _parse('<base href="/products/"><link rel="canonical" href="item">')

    assert result.base_url.selected_base_url == "https://example.test/products/"
    assert result.canonical.selected_url == "https://example.test/products/item"


def test_first_valid_base_wins_after_invalid_base() -> None:
    result = _parse('<base href="javascript:bad"><base href="/valid/"><a href="child">Child</a>')

    assert result.base_url.selected_base_url == "https://example.test/valid/"
    assert result.links[0].normalized_url == "https://example.test/valid/child"
    assert HtmlWarningCode.INVALID_BASE_HREF in _codes(result)
    assert HtmlWarningCode.MULTIPLE_BASE_ELEMENTS in _codes(result)


@pytest.mark.parametrize(
    ("html", "warning"),
    [
        ("<base>", HtmlWarningCode.EMPTY_BASE_HREF),
        ('<base href="">', HtmlWarningCode.EMPTY_BASE_HREF),
        ('<base href="https://other.test/path/">', HtmlWarningCode.CROSS_HOST_BASE_HREF),
        ('<base href="http://example.test/path/">', HtmlWarningCode.BASE_ORIGIN_DIFFERS),
        ('<base href="https://user:pass@example.test/">', HtmlWarningCode.INVALID_BASE_HREF),
    ],
)
def test_base_warnings_are_evidence_only(html: str, warning: HtmlWarningCode) -> None:
    assert warning in _codes(_parse(html))


def test_base_fragment_is_removed_without_changing_document_identity() -> None:
    result = _parse('<base href="/base/#fragment"><a href="child">Child</a>')

    assert result.final_document_url == _URL
    assert result.base_url.effective_url == "https://example.test/base/"


def test_identical_multiple_canonicals_remain_selectable() -> None:
    result = _parse(
        '<link rel="canonical" href="/chosen"><link rel="canonical" href="https://example.test/chosen">'
    )

    assert result.canonical.selected_url == "https://example.test/chosen"
    assert HtmlWarningCode.MULTIPLE_CANONICALS in _codes(result)
    assert HtmlWarningCode.CONFLICTING_CANONICALS not in _codes(result)


def test_conflicting_canonicals_have_no_selected_value() -> None:
    result = _parse('<link rel="canonical" href="/one"><link rel="canonical" href="/two">')

    assert result.canonical.selected_url is None
    assert HtmlWarningCode.CONFLICTING_CANONICALS in _codes(result)


@pytest.mark.parametrize(
    ("html", "warning"),
    [
        ("<html></html>", HtmlWarningCode.MISSING_CANONICAL),
        ("<link rel=canonical>", HtmlWarningCode.EMPTY_CANONICAL),
        ('<link rel=canonical href="ftp://example.test/file">', HtmlWarningCode.INVALID_CANONICAL),
        (
            '<link rel=canonical href="https://user:pass@example.test/">',
            HtmlWarningCode.INVALID_CANONICAL,
        ),
        ('<link rel=canonical href="https://other.test/">', HtmlWarningCode.CROSS_HOST_CANONICAL),
        (
            '<link rel=canonical href="https://example.test:bad/">',
            HtmlWarningCode.INVALID_CANONICAL,
        ),
        ('<link rel=canonical href="https://example.test/%ZZ">', HtmlWarningCode.INVALID_CANONICAL),
    ],
)
def test_canonical_warnings_are_preserved(html: str, warning: HtmlWarningCode) -> None:
    assert warning in _codes(_parse(html))


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("index,follow", [("index", None), ("follow", None)]),
        ("NOINDEX NOFOLLOW", [("noindex", None), ("nofollow", None)]),
        ("none", [("none", None)]),
        ("max-snippet:50", [("max-snippet", "50")]),
        (
            "unavailable_after: 25 Jun 2030 15:00:00 PST",
            [("unavailable_after", "25 Jun 2030 15:00:00 PST")],
        ),
    ],
)
def test_meta_robots_directives_are_normalized(
    content: str,
    expected: list[tuple[str, str | None]],
) -> None:
    result = _parse(f'<meta name="robots" content="{content}">')

    assert [(item.name, item.value) for item in result.meta_robots[0].directives] == expected
    assert result.meta_robots[0].raw_content == content


def test_crawler_specific_robots_record_is_preserved_separately() -> None:
    result = _parse(
        '<meta name="robots" content="index,follow"><meta name="googlebot" content="noindex">'
    )

    assert [record.agent_name for record in result.meta_robots] == ["robots", "googlebot"]
    assert HtmlWarningCode.CONFLICTING_META_ROBOTS in _codes(result)


@pytest.mark.parametrize(
    ("content", "warning"),
    [
        ("", HtmlWarningCode.EMPTY_META_ROBOTS),
        ("index,,follow", HtmlWarningCode.INVALID_META_ROBOTS_DIRECTIVE),
        ("futurebotdirective", HtmlWarningCode.UNKNOWN_META_ROBOTS_DIRECTIVE),
        ("max-snippet:", HtmlWarningCode.INVALID_META_ROBOTS_DIRECTIVE),
        ("index,noindex", HtmlWarningCode.CONFLICTING_META_ROBOTS),
        ("follow,nofollow", HtmlWarningCode.CONFLICTING_META_ROBOTS),
    ],
)
def test_meta_robots_warnings(content: str, warning: HtmlWarningCode) -> None:
    assert warning in _codes(_parse(f'<meta name="robots" content="{content}">'))


@pytest.mark.parametrize(
    "html",
    [
        "<html><head><title>Recovered metadata title<body><p>missing close",
        "<html><head></head><head><title>Duplicate head title</title></head><body></body></html>",
        "<html><body><div><b>nested <i>invalid</b> markup</i></div></body></html>",
        "<html><body></body><body><a href='/second'>Second body link</a></body></html>",
    ],
)
def test_malformed_or_duplicate_document_structures_parse_deterministically(html: str) -> None:
    result = _parse(html)

    assert result.reason_code.value == "parsed"
