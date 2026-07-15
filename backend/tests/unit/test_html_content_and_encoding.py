"""Content gating, decoding, and parser outcome tests."""

from __future__ import annotations

import codecs

import pytest

from musimack_tools.crawl.html import HtmlMetadataParser
from musimack_tools.domain.fetching import (
    FetchFailureCode,
    FetchOutcome,
    FetchResult,
    ResponseHeaders,
)
from musimack_tools.domain.html import (
    EncodingSource,
    HtmlParseOutcome,
    HtmlParseReasonCode,
    HtmlWarningCode,
)

_URL = "https://example.test/page"


def _fetch(
    body: bytes | str | None,
    *,
    content_type: str | None = "text/html",
    outcome: FetchOutcome = FetchOutcome.SUCCESS,
    status: int | None = 200,
    truncated: bool = False,
) -> FetchResult:
    encoded = body.encode() if isinstance(body, str) else body
    return FetchResult(
        requested_url=_URL,
        final_url=_URL,
        outcome=outcome,
        status_code=status,
        headers=ResponseHeaders(content_type=content_type),
        content_type=content_type,
        declared_content_length=len(encoded) if encoded is not None else None,
        actual_bytes_read=len(encoded) if encoded is not None else 0,
        body_truncated=truncated,
        redirect_chain=(),
        request_duration_seconds=0.1,
        dns_evidence=(),
        failure_code=(
            FetchFailureCode.TRANSPORT_ERROR if outcome is FetchOutcome.FAILURE else None
        ),
        failure_explanation=("Synthetic failure" if outcome is FetchOutcome.FAILURE else None),
        body=encoded,
    )


def _codes(result: object) -> set[HtmlWarningCode]:
    return {warning.code for warning in result.warnings}  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("content_type", "declared"),
    [
        ("text/html", "text/html"),
        ("text/html; charset=utf-8", "text/html"),
        ("TEXT/HTML; Charset=UTF-8", "text/html"),
        ("application/xhtml+xml", "application/xhtml+xml"),
    ],
)
def test_html_media_types_are_parsed(content_type: str, declared: str) -> None:
    result = HtmlMetadataParser().parse(
        _fetch("<html><title>A useful page title</title></html>", content_type=content_type)
    )

    assert result.outcome is HtmlParseOutcome.PARSED
    assert result.declared_media_type == declared
    assert result.effective_media_type == declared
    assert result.media_type_inferred is False


@pytest.mark.parametrize(
    "content_type",
    [
        "application/json",
        "application/pdf",
        "image/png",
        "text/css",
        "text/javascript",
        "text/plain",
    ],
)
def test_clearly_non_html_media_types_are_skipped(content_type: str) -> None:
    result = HtmlMetadataParser().parse(
        _fetch("<html><title>Ignored</title></html>", content_type=content_type)
    )

    assert result.outcome is HtmlParseOutcome.SKIPPED
    assert result.reason_code is HtmlParseReasonCode.NON_HTML_CONTENT
    assert HtmlWarningCode.NON_HTML_CONTENT in _codes(result)


@pytest.mark.parametrize("content_type", [None, "application/octet-stream"])
def test_structural_html_can_be_inferred_for_ambiguous_media_type(content_type: str | None) -> None:
    result = HtmlMetadataParser().parse(
        _fetch("<!doctype html><title>Inferred HTML title</title>", content_type=content_type)
    )

    assert result.outcome is HtmlParseOutcome.PARSED
    assert result.effective_media_type == "text/html"
    assert result.media_type_inferred is True
    assert HtmlWarningCode.MEDIA_TYPE_INFERRED in _codes(result)


def test_missing_content_type_plain_body_is_skipped() -> None:
    result = HtmlMetadataParser().parse(_fetch("ordinary plain text", content_type=None))

    assert result.reason_code is HtmlParseReasonCode.NON_HTML_CONTENT


@pytest.mark.parametrize(
    ("fetch", "reason", "warning"),
    [
        (_fetch(b""), HtmlParseReasonCode.EMPTY_BODY, HtmlWarningCode.EMPTY_BODY),
        (_fetch(None), HtmlParseReasonCode.MISSING_BODY, HtmlWarningCode.MISSING_BODY),
        (
            _fetch(None, outcome=FetchOutcome.FAILURE, status=None),
            HtmlParseReasonCode.FETCH_FAILED,
            HtmlWarningCode.MISSING_BODY,
        ),
        (
            _fetch(b"partial", truncated=True),
            HtmlParseReasonCode.RESPONSE_TRUNCATED,
            HtmlWarningCode.RESPONSE_TRUNCATED,
        ),
        (
            _fetch("<html><title>Error page</title></html>", status=404),
            HtmlParseReasonCode.HTTP_ERROR_RESPONSE,
            HtmlWarningCode.HTTP_ERROR_RESPONSE,
        ),
    ],
)
def test_non_page_fetch_evidence_is_distinguished(
    fetch: FetchResult,
    reason: HtmlParseReasonCode,
    warning: HtmlWarningCode,
) -> None:
    result = HtmlMetadataParser().parse(fetch)

    assert result.outcome is HtmlParseOutcome.SKIPPED
    assert result.reason_code is reason
    assert warning in _codes(result)
    assert result.links == ()


def test_http_charset_has_highest_precedence() -> None:
    body = '<meta charset="utf-8"><title>Caf\xe9 metadata title</title>'.encode("cp1252")

    result = HtmlMetadataParser().parse(
        _fetch(body, content_type="text/html; charset=windows-1252")
    )

    assert result.selected_encoding == "cp1252"
    assert result.encoding_source is EncodingSource.HTTP_HEADER
    assert result.title.selected_value == "Café metadata title"


@pytest.mark.parametrize(
    ("body", "expected_encoding"),
    [
        (codecs.BOM_UTF8 + b"<title>Unicode title value</title>", "utf-8-sig"),
        ("<title>Unicode title value</title>".encode("utf-16"), "utf-16"),
    ],
)
def test_bom_is_used_when_no_http_charset(body: bytes, expected_encoding: str) -> None:
    result = HtmlMetadataParser().parse(_fetch(body))

    assert result.encoding_source is EncodingSource.BOM
    assert result.selected_encoding == expected_encoding
    assert result.title.selected_value == "Unicode title value"


def test_meta_charset_is_used_from_bounded_prescan() -> None:
    body = '<meta charset="iso-8859-1"><title>Caf\xe9 metadata title</title>'.encode("latin-1")

    result = HtmlMetadataParser().parse(_fetch(body))

    assert result.encoding_source is EncodingSource.META_CHARSET
    assert result.selected_encoding == "iso8859-1"
    assert result.title.selected_value == "Café metadata title"


def test_meta_http_equiv_charset_is_supported() -> None:
    body = (
        '<meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">'
        "<title>Caf\xe9 metadata title</title>"
    ).encode("latin-1")

    result = HtmlMetadataParser().parse(_fetch(body))

    assert result.encoding_source is EncodingSource.META_HTTP_EQUIV
    assert result.title.selected_value == "Café metadata title"


def test_invalid_header_charset_falls_through_to_meta() -> None:
    body = b'<meta charset="utf-8"><title>Valid Unicode title</title>'

    result = HtmlMetadataParser().parse(_fetch(body, content_type="text/html; charset=not-real"))

    assert result.encoding_source is EncodingSource.META_CHARSET
    assert HtmlWarningCode.INVALID_CHARSET in _codes(result)


def test_cp1252_is_the_documented_fallback() -> None:
    body = "<title>Smart “quoted” metadata</title>".encode("cp1252")

    result = HtmlMetadataParser().parse(_fetch(body))

    assert result.encoding_source is EncodingSource.FALLBACK
    assert result.selected_encoding == "cp1252"
    assert "“quoted”" in (result.title.selected_value or "")


def test_invalid_declared_utf8_uses_replacement_with_warning() -> None:
    body = b"<title>Invalid \xff UTF-8 title value</title>"

    result = HtmlMetadataParser().parse(_fetch(body, content_type="text/html; charset=utf-8"))

    assert result.decode_replacement_used is True
    assert "�" in (result.title.selected_value or "")
    assert HtmlWarningCode.DECODE_REPLACEMENT_USED in _codes(result)


def test_encoding_declaration_outside_prescan_is_ignored() -> None:
    body = b"<html><head>" + (b" " * 4200) + b'<meta charset="utf-8"><title>Late title</title>'

    result = HtmlMetadataParser().parse(_fetch(body))

    assert result.encoding_source is EncodingSource.FALLBACK
    assert HtmlWarningCode.ENCODING_DECLARATION_IGNORED in _codes(result)


def test_unicode_title_and_description_are_preserved() -> None:
    html = (
        '<title>Música para mañana</title><meta name="description" '
        'content="Descripción útil para músicos y oyentes de todo el mundo.">'
    )

    result = HtmlMetadataParser().parse(_fetch(html, content_type="text/html; charset=utf-8"))

    assert result.title.selected_value == "Música para mañana"
    assert (
        result.meta_description.selected_value
        == "Descripción útil para músicos y oyentes de todo el mundo."
    )


def test_injected_clock_produces_stable_duration() -> None:
    readings = iter((10.0, 10.25))

    result = HtmlMetadataParser(clock=lambda: next(readings)).parse(
        _fetch("<title>A sufficiently useful title</title>")
    )

    assert result.parse_duration_seconds == 0.25


def test_malformed_html_is_recovered_and_flagged() -> None:
    result = HtmlMetadataParser().parse(
        _fetch("<html><head><title>Recovered metadata title<body><p>broken")
    )

    assert result.outcome is HtmlParseOutcome.PARSED
    assert HtmlWarningCode.PARSER_RECOVERY_USED in _codes(result)
