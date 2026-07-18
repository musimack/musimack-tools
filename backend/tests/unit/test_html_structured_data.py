"""Parser-owned bounded structured-data evidence coverage."""

# ruff: noqa: E501

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from musimack_tools.crawl.html import HtmlMetadataParser
from musimack_tools.domain.fetching import FetchOutcome, FetchResult, ResponseHeaders

if TYPE_CHECKING:
    from musimack_tools.domain.html import HtmlParseResult

_URL = "https://example.test/page"


def _parse(html: str) -> HtmlParseResult:
    body = html.encode()
    return HtmlMetadataParser().parse(
        FetchResult(
            requested_url=_URL,
            final_url=_URL,
            outcome=FetchOutcome.SUCCESS,
            status_code=200,
            headers=ResponseHeaders(content_type="text/html"),
            content_type="text/html",
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
    )


def test_json_ld_is_inert_deterministic_and_preserves_parse_diagnostics() -> None:
    valid = _parse(
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"Organization","@id":"#org",'
        '"name":"Example","url":"https://example.test"}</script>'
    ).structured_data[0]
    assert valid.format == "json_ld"
    assert valid.parse_status == "parsed"
    assert valid.contexts == ("https://schema.org",)
    assert valid.types == ("Organization",)
    assert valid.identifiers == ("#org",)
    assert json.loads(valid.properties_json)["name"] == ["Example"]
    assert valid.normalized_fingerprint

    invalid = _parse(
        '<script type="application/ld+json">{"@type":"Thing",}</script>'
    ).structured_data[0]
    assert invalid.parse_status == "invalid"
    assert invalid.parse_error and invalid.parse_error.startswith("JSONDecodeError")
    assert invalid.normalized_fingerprint is None


def test_json_ld_duplicate_keys_and_bounds_are_explicit() -> None:
    block = _parse(
        '<script type="application/ld+json">{"@type":"Thing","name":"a","name":"b"}</script>'
    ).structured_data[0]
    assert block.duplicate_keys == ("name",)
    assert json.loads(block.properties_json)["name"] == ["b"]

    bounded = _parse(
        '<script type="application/ld+json">{"@type":"Thing","name":"'
        + ("x" * 70_000)
        + '"}</script>'
    ).structured_data[0]
    assert bounded.truncated
    assert len(bounded.raw_value) == 65_536
    assert bounded.raw_length > len(bounded.raw_value)


def test_json_ld_like_nonstandard_media_type_is_retained_for_review() -> None:
    block = _parse(
        '<script type="application/json+ld">{"@context":"https://schema.org",'
        '"@type":"Person","name":"Ada"}</script>'
    ).structured_data[0]
    assert block.script_type == "application/json+ld"
    assert block.parse_status == "parsed"


def test_microdata_and_rdfa_are_normalized_without_network_activity() -> None:
    records = _parse(
        '<article itemscope itemtype="Article" itemid="#article">'
        '<meta itemprop="headline" content="News"><a itemprop="url" href="/news">Read</a>'
        '</article><section vocab="https://schema.org/" typeof="Person" about="#person">'
        '<span property="name">Ada</span></section>'
    ).structured_data
    assert [record.format for record in records] == ["microdata", "rdfa"]
    assert records[0].types == ("Article",)
    assert records[0].identifiers == ("#article",)
    assert json.loads(records[0].properties_json) == {"headline": ["News"], "url": ["/news"]}
    assert records[1].contexts == ("https://schema.org/",)
    assert records[1].types == ("Person",)
    assert json.loads(records[1].properties_json) == {"name": ["Ada"]}


@pytest.mark.parametrize(
    ("case", "payload", "types", "identifiers"),
    (
        (
            "object",
            '{"@context":"https://schema.org","@type":"Organization"}',
            ("Organization",),
            (),
        ),
        ("array", '[{"@type":"Person"},{"@type":"Organization"}]', ("Organization", "Person"), ()),
        (
            "graph",
            '{"@context":"https://schema.org","@graph":[{"@type":"Person","@id":"#p"}]}',
            ("Person",),
            ("#p",),
        ),
        (
            "nested",
            '{"@type":"Article","author":{"@type":"Person","@id":"#author"}}',
            ("Article", "Person"),
            ("#author",),
        ),
        ("string-type", '{"@type":"Person"}', ("Person",), ()),
        ("array-type", '{"@type":["Person","Organization"]}', ("Organization", "Person"), ()),
        ("missing-id", '{"@type":"Person"}', ("Person",), ()),
    ),
)
def test_json_ld_common_shapes_are_extracted_in_stable_order(
    case: str, payload: str, types: tuple[str, ...], identifiers: tuple[str, ...]
) -> None:
    del case
    block = _parse(f'<script type="application/ld+json">{payload}</script>').structured_data[0]
    assert block.parse_status == "parsed"
    assert block.types == types
    assert block.identifiers == identifiers


@pytest.mark.parametrize(
    ("case", "payload", "expected_status"),
    (
        ("empty", "", "invalid"),
        ("whitespace", "   ", "invalid"),
        ("malformed", "{", "invalid"),
        ("comments", '{/* comment */"@type":"Person"}', "invalid"),
        ("trailing-comma", '{"@type":"Person",}', "invalid"),
        ("html-contamination", '<div>{"@type":"Person"}</div>', "invalid"),
        ("scalar", "42", "parsed"),
        ("bom", '\ufeff{"@type":"Person"}', "parsed"),
    ),
)
def test_json_ld_edge_cases_are_inert_and_diagnostic(
    case: str, payload: str, expected_status: str
) -> None:
    del case
    block = _parse(f'<script type="application/ld+json">{payload}</script>').structured_data[0]
    assert block.parse_status == expected_status


def test_json_ld_contexts_media_types_multiple_blocks_and_no_execution() -> None:
    records = _parse(
        '<script type="application/ld+json">'
        '{"@context":["https://schema.org","https://external.test"],'
        '"@type":"Person","name":"window.phase25Executed=true"}</script>'
        '<script type="application/json+ld">{"@type":"Organization"}</script>'
        '<script type="text/ld+json">{"@type":"WebSite"}</script>'
    ).structured_data
    assert [record.occurrence_index for record in records] == [0, 1, 2]
    assert records[0].contexts == ("https://external.test", "https://schema.org")
    assert [record.script_type for record in records] == [
        "application/ld+json",
        "application/json+ld",
        "text/ld+json",
    ]
    assert "window.phase25Executed=true" in records[0].raw_value


def test_structured_data_block_cap_is_explicit_and_stable() -> None:
    html = "".join(
        f'<script type="application/ld+json">{{"@type":"Person","name":"{index}"}}</script>'
        for index in range(1_005)
    )
    records = _parse(html).structured_data
    assert len(records) == 1_000
    assert records[0].occurrence_index == 0
    assert records[-1].occurrence_index == 999


def test_microdata_values_references_boundaries_and_diagnostics() -> None:
    records = _parse(
        '<div itemprop="outside">outside</div>'
        '<article itemscope itemtype="Article BlogPosting" itemid="https://example.test/#article" '
        'itemref="extra missing">'
        '<span itemprop="headline">News</span>'
        '<meta itemprop="description" content="Summary">'
        '<a itemprop="url" href="/news">Read</a>'
        '<img itemprop="image" src="/image.jpg">'
        '<time itemprop="datePublished" datetime="2026-01-02"></time>'
        '<data itemprop="wordCount" value="42"></data>'
        '<span itemprop="missingValue"></span>'
        '<div itemscope itemtype="Person"><span itemprop="name">Ada</span></div>'
        "</article>"
        '<div id="extra"><span itemprop="author">David</span></div>'
        '<div itemscope itemtype="Person" itemid=" javascript:bad "><span itemprop="name">Bad</span></div>'
    ).structured_data
    scopes = [record for record in records if record.format == "microdata"]
    article = next(record for record in scopes if "Article" in record.types)
    properties = json.loads(article.properties_json)
    assert article.types == ("Article", "BlogPosting")
    assert article.identifiers == ("https://example.test/#article",)
    assert properties["headline"] == ["News"]
    assert properties["description"] == ["Summary"]
    assert properties["url"] == ["/news"]
    assert properties["image"] == ["/image.jpg"]
    assert properties["datePublished"] == ["2026-01-02"]
    assert properties["wordCount"] == ["42"]
    assert properties["author"] == ["David"]
    assert "microdata_unresolved_itemref:missing" in article.diagnostics
    assert "property_missing_value:missingValue" in article.diagnostics
    outside = next(
        record for record in scopes if "microdata_property_outside_scope" in record.diagnostics
    )
    assert "microdata_property_outside_scope" in outside.diagnostics
    invalid = next(record for record in scopes if "microdata_invalid_itemid" in record.diagnostics)
    assert "microdata_invalid_itemid" in invalid.diagnostics


def test_rdfa_supported_subset_and_unsupported_diagnostics() -> None:
    records = _parse(
        '<section vocab="https://schema.org/" prefix="schema: https://schema.org/" '
        'typeof="Person" about="#person">'
        '<meta property="name" content="Ada">'
        '<a rel="url" href="https://example.test/ada">Profile</a>'
        '<a rev="knows" resource="#other">Other</a>'
        '<span property="birthDate" datatype="xsd:date" content="1815-12-10"></span>'
        "</section>"
        '<section prefix="broken" typeof="Thing" inlist>'
        '<span property="name">Unsupported</span></section>'
    ).structured_data
    supported, unsupported = [record for record in records if record.format == "rdfa"]
    assert supported.contexts == ("https://schema.org/", "schema: https://schema.org/")
    assert supported.types == ("Person",)
    assert supported.identifiers == ("#person",)
    assert json.loads(supported.properties_json) == {
        "birthDate": ["1815-12-10"],
        "knows": ["#other"],
        "name": ["Ada"],
        "url": ["https://example.test/ada"],
    }
    assert unsupported.diagnostics == (
        "rdfa_invalid_prefix_mapping",
        "rdfa_unsupported_pattern",
    )
