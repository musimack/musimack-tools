"""Phase 21 sitemap discovery, XML security, parsing, and comparison tests."""

from __future__ import annotations

import json

import pytest

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import create_scope_policy
from musimack_tools.domain.page_evidence import (
    ContentTypeCategory,
    IndexabilityEvidenceState,
    PageEvidenceState,
)
from musimack_tools.domain.sitemap_audit import (
    ComparisonAction,
    ComparisonInput,
    ComparisonReason,
    ComparisonState,
    DiscoveryOptions,
    ExportFormat,
    ParsedSitemap,
    ParseState,
    SitemapAuditConfiguration,
    SitemapRootType,
    ValidationCode,
    audit_identity,
    compare_evidence,
    decode_cursor,
    encode_cursor,
    filter_fingerprint,
    parse_sitemap,
)
from musimack_tools.sitemap_audit.service import _export_bytes

_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _parse(body: str | bytes, *, content_type: str = "application/xml") -> ParsedSitemap:
    payload = body.encode() if isinstance(body, str) else body
    return parse_sitemap(
        payload,
        content_type=content_type,
        document_url="https://example.com/sitemap.xml",
        scope=create_scope_policy(normalize_url("https://example.com/")),
        configuration=SitemapAuditConfiguration(enabled=True),
    )


def _page(  # noqa: PLR0913 - evidence variations are explicit in tests.
    identity: str,
    *,
    redirect: int = 0,
    noindex: bool = False,
    canonical: str | None = None,
    category: ContentTypeCategory = ContentTypeCategory.HTML,
    parsed: bool = True,
    failed: bool = False,
    status: int | None = 200,
    evidence_state: PageEvidenceState | None = None,
    indexability_state: IndexabilityEvidenceState = IndexabilityEvidenceState.AVAILABLE,
) -> ComparisonInput:
    return ComparisonInput(
        evidence_id=f"evidence-{identity.rsplit('/', 1)[-1]}",
        requested_url=identity,
        requested_identity=identity,
        final_url="https://example.com/final" if redirect else identity,
        final_identity="https://example.com/final" if redirect else identity,
        fetch_failed=failed,
        http_status=None if failed else status,
        redirect_count=redirect,
        content_type="text/html" if category is ContentTypeCategory.HTML else "application/pdf",
        content_type_category=category,
        parsed_as_html=parsed,
        canonical_url=canonical,
        canonical_identity=canonical,
        indexability_json=json.dumps({"directives": ["noindex"] if noindex else ["index"]}),
        indexability_state=indexability_state,
        evidence_state=(
            evidence_state
            or (PageEvidenceState.FETCH_FAILED if failed else PageEvidenceState.COMPLETE)
        ),
    )


def test_configuration_and_identity_are_bounded_and_deterministic() -> None:
    configuration = SitemapAuditConfiguration(enabled=True)
    options = DiscoveryOptions("https://example.com/sitemap.xml")
    assert audit_identity("run-1", options, configuration) == audit_identity(
        "run-1", options, configuration
    )
    with pytest.raises(ValueError, match="configuration_invalid"):
        SitemapAuditConfiguration(maximum_documents=0)
    with pytest.raises(ValueError, match="version_unsupported"):
        SitemapAuditConfiguration(audit_version="invented")


@pytest.mark.parametrize(
    ("declaration", "code"),
    [
        ("<!DOCTYPE urlset>", ValidationCode.DOCTYPE_FORBIDDEN),
        ("<!EnTiTy x SYSTEM 'file:///etc/passwd'>", ValidationCode.ENTITY_DECLARATION_FORBIDDEN),
    ],
)
def test_dangerous_xml_declarations_are_rejected(declaration: str, code: ValidationCode) -> None:
    parsed = _parse(f"{declaration}<urlset xmlns='{_NS}'/>")
    assert parsed.parse_state is ParseState.INVALID
    assert parsed.findings[0].code is code


def test_gzip_url_and_magic_are_rejected() -> None:
    scope = create_scope_policy(normalize_url("https://example.com/"))
    for url, body, media_type in (
        ("https://example.com/sitemap.xml.gz", b"content", "application/xml"),
        ("https://example.com/sitemap.xml", b"\x1f\x8bcontent", "application/gzip"),
    ):
        parsed = parse_sitemap(
            body,
            content_type=media_type,
            document_url=url,
            scope=scope,
            configuration=SitemapAuditConfiguration(enabled=True),
        )
        assert parsed.findings[0].code is ValidationCode.GZIP_NOT_SUPPORTED


def test_valid_urlset_preserves_order_normalizes_and_deduplicates() -> None:
    parsed = _parse(
        f"""<?xml version='1.0'?>
        <urlset xmlns='{_NS}'>
          <url><loc>https://example.com/a</loc></url>
          <url><loc>https://example.com/a</loc></url>
          <url><loc>https://example.com/b</loc></url>
        </urlset>"""
    )
    assert parsed.root_type is SitemapRootType.URLSET
    assert [item.normalized_url for item in parsed.entries] == [
        "https://example.com/a",
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert parsed.entries[1].duplicate
    assert ValidationCode.DUPLICATE_LOCATION in {item.code for item in parsed.findings}


def test_index_namespace_and_child_order_are_retained() -> None:
    parsed = _parse(
        """<sitemapindex>
        <sitemap><loc>https://example.com/one.xml</loc></sitemap>
        <sitemap><loc>https://example.com/two.xml</loc></sitemap>
        </sitemapindex>"""
    )
    assert parsed.root_type is SitemapRootType.SITEMAP_INDEX
    assert [item.entry_sequence for item in parsed.children] == [0, 1]
    assert ValidationCode.INVALID_NAMESPACE in {item.code for item in parsed.findings}


@pytest.mark.parametrize(
    ("member", "code"),
    [
        ("<url/>", ValidationCode.MISSING_LOCATION),
        ("<url><loc> </loc></url>", ValidationCode.EMPTY_LOCATION),
        ("<url><loc>relative</loc></url>", ValidationCode.INVALID_LOCATION),
        ("<url><loc>ftp://example.com/a</loc></url>", ValidationCode.UNSUPPORTED_SCHEME),
        ("<url><loc>https://other.example/a</loc></url>", ValidationCode.OUT_OF_SCOPE_LOCATION),
    ],
)
def test_invalid_locations_remain_inspectable(member: str, code: ValidationCode) -> None:
    parsed = _parse(f"<urlset xmlns='{_NS}'>{member}</urlset>")
    assert parsed.entries
    assert code in {item.code for item in parsed.findings}


def test_html_error_page_is_not_accepted_as_sitemap() -> None:
    parsed = _parse("<html><body>not found</body></html>", content_type="text/html")
    assert parsed.findings[0].code is ValidationCode.UNEXPECTED_CONTENT_TYPE


def test_valid_xml_with_imperfect_content_type_is_parsed_with_warning() -> None:
    parsed = _parse(f"<urlset xmlns='{_NS}'/>", content_type="text/plain")
    assert parsed.root_type is SitemapRootType.URLSET
    assert ValidationCode.UNEXPECTED_CONTENT_TYPE in {item.code for item in parsed.findings}


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("<urlset>", ValidationCode.INVALID_XML),
        ("<rss/>", ValidationCode.UNSUPPORTED_ROOT_ELEMENT),
        (f"<urlset xmlns='{_NS}'/>", ValidationCode.EMPTY_URL_SET),
        (f"<sitemapindex xmlns='{_NS}'/>", ValidationCode.EMPTY_SITEMAP_INDEX),
    ],
)
def test_malformed_unsupported_and_empty_documents_are_explicit(
    body: str, code: ValidationCode
) -> None:
    parsed = _parse(body)
    assert code in {item.code for item in parsed.findings}


@pytest.mark.parametrize("namespace", [None, "https://example.com/nonstandard-sitemap"])
def test_namespace_variants_are_warnings(namespace: str | None) -> None:
    attribute = "" if namespace is None else f" xmlns='{namespace}'"
    parsed = _parse(f"<urlset{attribute}><url><loc>https://example.com/a</loc></url></urlset>")
    assert parsed.entries[0].valid
    assert ValidationCode.INVALID_NAMESPACE in {item.code for item in parsed.findings}


def test_response_and_index_child_limits_retain_bounded_evidence() -> None:
    oversized = parse_sitemap(
        b"<urlset/>",
        content_type="application/xml",
        document_url="https://example.com/sitemap.xml",
        scope=create_scope_policy(normalize_url("https://example.com/")),
        configuration=SitemapAuditConfiguration(enabled=True, maximum_response_bytes=4),
    )
    assert oversized.findings[0].code is ValidationCode.RESPONSE_TOO_LARGE
    index = parse_sitemap(
        (
            f"<sitemapindex xmlns='{_NS}'>"
            "<sitemap><loc>https://example.com/one.xml</loc></sitemap>"
            "<sitemap><loc>https://example.com/two.xml</loc></sitemap>"
            "</sitemapindex>"
        ).encode(),
        content_type="application/xml",
        document_url="https://example.com/sitemap.xml",
        scope=create_scope_policy(normalize_url("https://example.com/")),
        configuration=SitemapAuditConfiguration(enabled=True, maximum_index_children=1),
    )
    assert len(index.children) == 1
    assert ValidationCode.CHILD_COUNT_LIMIT_EXCEEDED in {item.code for item in index.findings}


def test_parser_enforces_url_and_child_limits_with_partial_evidence() -> None:
    body = (
        f"<urlset xmlns='{_NS}'>"
        + "".join(f"<url><loc>https://example.com/{index}</loc></url>" for index in range(3))
        + "</urlset>"
    )
    parsed = parse_sitemap(
        body.encode(),
        content_type="application/xml",
        document_url="https://example.com/sitemap.xml",
        scope=create_scope_policy(normalize_url("https://example.com/")),
        configuration=SitemapAuditConfiguration(enabled=True, maximum_urlset_entries=2),
    )
    assert len(parsed.entries) == 2
    assert ValidationCode.URL_COUNT_LIMIT_EXCEEDED in {item.code for item in parsed.findings}


def test_comparison_covers_add_remove_review_and_unchanged_with_precedence() -> None:
    present = {
        "https://example.com/ok": ("entry-ok", "https://example.com/ok"),
        "https://example.com/redirect": ("entry-redirect", "https://example.com/redirect"),
        "https://example.com/noindex": ("entry-noindex", "https://example.com/noindex"),
        "https://example.com/canonical": ("entry-canonical", "https://example.com/canonical"),
        "https://example.com/pdf": ("entry-pdf", "https://example.com/pdf"),
        "https://example.com/review": ("entry-review", "https://example.com/review"),
        "https://example.com/unknown": ("entry-unknown", "https://example.com/unknown"),
    }
    pages = (
        _page("https://example.com/ok"),
        _page("https://example.com/missing"),
        _page("https://example.com/redirect", redirect=1),
        _page("https://example.com/noindex", noindex=True),
        _page("https://example.com/canonical", canonical="https://example.com/target"),
        _page("https://example.com/pdf", category=ContentTypeCategory.PDF, parsed=False),
        _page("https://example.com/review", status=404),
    )
    records = {item.url_identity: item for item in compare_evidence(present, pages)}
    assert records["https://example.com/ok"].action is ComparisonAction.UNCHANGED
    assert records["https://example.com/missing"].action is ComparisonAction.ADD
    assert (
        records["https://example.com/redirect"].comparison_state
        is ComparisonState.REDIRECTED_SITEMAP_URL
    )
    assert records["https://example.com/noindex"].reason is ComparisonReason.NOINDEX_URL
    assert (
        records["https://example.com/canonical"].comparison_state
        is ComparisonState.CANONICALIZED_SITEMAP_URL
    )
    assert (
        records["https://example.com/pdf"].comparison_state is ComparisonState.NON_HTML_SITEMAP_URL
    )
    assert (
        records["https://example.com/review"].comparison_state
        is ComparisonState.IN_SITEMAP_BUT_EXCLUDED
    )
    assert records["https://example.com/unknown"].action is ComparisonAction.REVIEW


def test_failed_crawl_evidence_is_review_not_remove() -> None:
    identity = "https://example.com/failed"
    record = compare_evidence({identity: ("entry", identity)}, (_page(identity, failed=True),))[0]
    assert record.action is ComparisonAction.REVIEW
    assert record.reason is ComparisonReason.CRAWL_EVIDENCE_FAILED


@pytest.mark.parametrize(
    ("page", "expected_state", "expected_reason"),
    [
        (
            _page("https://example.com/failed-redirect", redirect=1, failed=True),
            ComparisonState.REDIRECTED_SITEMAP_URL,
            ComparisonReason.REDIRECTED_URL,
        ),
        (
            _page(
                "https://example.com/partial-noindex",
                noindex=True,
                evidence_state=PageEvidenceState.PARTIAL,
            ),
            ComparisonState.NOINDEX_SITEMAP_URL,
            ComparisonReason.NOINDEX_URL,
        ),
        (
            _page(
                "https://example.com/partial-canonical",
                canonical="https://example.com/preferred",
                evidence_state=PageEvidenceState.PARTIAL,
            ),
            ComparisonState.CANONICALIZED_SITEMAP_URL,
            ComparisonReason.CANONICAL_POINTS_ELSEWHERE,
        ),
        (
            _page(
                "https://example.com/valid-without-indexability",
                indexability_state=IndexabilityEvidenceState.UNAVAILABLE,
            ),
            ComparisonState.IN_SITEMAP_AND_ELIGIBLE,
            ComparisonReason.ELIGIBLE_ALREADY_PRESENT,
        ),
    ],
)
def test_specific_evidence_precedes_generic_availability(
    page: ComparisonInput,
    expected_state: ComparisonState,
    expected_reason: ComparisonReason,
) -> None:
    record = compare_evidence(
        {page.requested_identity: ("entry", page.requested_url)},
        (page,),
    )[0]
    assert record.comparison_state is expected_state
    assert record.reason is expected_reason


def test_sitemap_only_evidence_remains_unverified() -> None:
    identity = "https://example.com/sitemap-only"
    record = compare_evidence({identity: ("entry", identity)}, ())[0]
    assert record.comparison_state is ComparisonState.SITEMAP_ONLY_UNVERIFIED
    assert record.reason is ComparisonReason.NOT_OBSERVED_IN_SELECTED_CRAWL


def test_cursor_is_filter_bound_and_versioned() -> None:
    fingerprint = filter_fingerprint({"action": "add"})
    cursor = encode_cursor("comparisons", "ordering-v1", fingerprint, 50)
    assert decode_cursor(cursor, "comparisons", "ordering-v1", fingerprint) == 50
    with pytest.raises(ValueError, match="filter_mismatch"):
        decode_cursor(cursor, "comparisons", "ordering-v1", filter_fingerprint({}))


def test_exports_defend_csv_formulas_and_keep_json_markdown_contracts() -> None:
    audit = {"audit_id": "audit-test"}
    rows = [
        {
            "action": "review",
            "url": '=HYPERLINK("unsafe")',
            "comparison_state": "sitemap_only_unverified",
            "reason_code": "not_observed_in_selected_crawl",
            "recommendation_state": None,
            "http_status": None,
            "content_type": None,
        }
    ]
    csv_bytes = _export_bytes(audit, ExportFormat.CSV, rows, truncated=False)
    assert csv_bytes.startswith(b"\xef\xbb\xbf")
    assert b"'=HYPERLINK" in csv_bytes
    json_payload = json.loads(_export_bytes(audit, ExportFormat.JSON, rows, truncated=False))
    assert list(json_payload) == ["audit_id", "comparisons", "truncated", "version"]
    assert json_payload["comparisons"] == rows
    markdown = _export_bytes(audit, ExportFormat.MARKDOWN, rows, truncated=False).decode()
    assert markdown.startswith("# Sitemap audit audit-test\n")
    assert "| Action | URL | State | Reason |" in markdown
