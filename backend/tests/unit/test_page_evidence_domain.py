"""Bounded page-evidence projection and query-contract tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from musimack_tools.domain.crawl import CrawlState, FrontierState, UrlCrawlOutcome
from musimack_tools.domain.fetching import FetchFailureCode
from musimack_tools.domain.page_evidence import (
    PAGE_EVIDENCE_ORDERING,
    PAGE_EVIDENCE_PAGINATION_VERSION,
    ContentTypeCategory,
    MetadataPresence,
    PageEvidenceConfiguration,
    PageEvidenceFilters,
    PageEvidenceReasonCode,
    PageEvidenceState,
    decode_cursor,
    encode_cursor,
    project_crawl_result,
)
from page_evidence_helpers import PageRecordOptions, crawl_result, page_record


def test_versions_and_disabled_default_are_exact() -> None:
    configuration = PageEvidenceConfiguration()
    assert not configuration.enabled
    assert configuration.evidence_version == "seo-toolkit-page-crawl-evidence-v1"
    assert configuration.persistence_version == "seo-toolkit-page-crawl-evidence-persistence-v1"
    assert configuration.query_version == "seo-toolkit-page-crawl-evidence-query-v1"
    assert configuration.retention_version == "seo-toolkit-page-crawl-evidence-retention-v1"


def test_unknown_version_is_rejected() -> None:
    with pytest.raises(ValueError, match=PageEvidenceReasonCode.VERSION_UNSUPPORTED):
        PageEvidenceConfiguration(evidence_version="unknown")


@pytest.mark.parametrize(
    ("body", "presence", "count"),
    [
        ("<p>none</p>", MetadataPresence.MISSING, 0),
        ("<title> </title>", MetadataPresence.EMPTY, 1),
        ("<title>One</title><title>Two</title>", MetadataPresence.MULTIPLE, 2),
    ],
)
def test_title_presence_is_preserved(body: str, presence: MetadataPresence, count: int) -> None:
    page = project_crawl_result(
        "job",
        "run",
        crawl_result((page_record(options=PageRecordOptions(body=body)),)),
        PageEvidenceConfiguration(),
    ).pages[0]
    assert page.title_presence is presence
    assert page.title_count == count


def test_complete_html_evidence_excludes_body_and_headers() -> None:
    page = project_crawl_result(
        "job", "run", crawl_result((page_record(),)), PageEvidenceConfiguration()
    ).pages[0]
    assert page.evidence_state is PageEvidenceState.COMPLETE
    assert page.content_type_category is ContentTypeCategory.HTML
    assert page.title_value == "Durable evidence"
    assert "noindex" in page.x_robots_json
    assert not hasattr(page, "body") and not hasattr(page, "headers")


def test_non_html_does_not_fabricate_html_metadata() -> None:
    page = project_crawl_result(
        "job",
        "run",
        crawl_result(
            (page_record(options=PageRecordOptions(body=None, content_type="application/pdf")),)
        ),
        PageEvidenceConfiguration(),
    ).pages[0]
    assert page.evidence_state is PageEvidenceState.NOT_HTML
    assert page.title_presence is MetadataPresence.UNAVAILABLE


def test_failed_fetch_is_distinct_from_missing_metadata() -> None:
    page = project_crawl_result(
        "job",
        "run",
        crawl_result(
            (
                page_record(
                    options=PageRecordOptions(
                        body=None, failure=FetchFailureCode.CONNECT_TIMEOUT, status=None
                    )
                ),
            )
        ),
        PageEvidenceConfiguration(),
    ).pages[0]
    assert page.evidence_state is PageEvidenceState.FETCH_FAILED
    assert page.http_status is None
    assert page.title_presence is MetadataPresence.UNAVAILABLE


def test_redirect_and_cross_host_evidence_is_bounded() -> None:
    page = project_crawl_result(
        "job",
        "run",
        crawl_result(
            (page_record(options=PageRecordOptions(final_url="https://other.example/final")),)
        ),
        PageEvidenceConfiguration(),
    ).pages[0]
    assert page.redirect_count == 1
    assert page.redirects[0].cross_host
    assert page.redirects[0].terminal


def test_metadata_truncation_is_explicit() -> None:
    record = page_record(options=PageRecordOptions(body=f"<title>{'x' * 100}</title>"))
    page = project_crawl_result(
        "job",
        "run",
        crawl_result((record,)),
        PageEvidenceConfiguration(maximum_metadata_characters=64),
    ).pages[0]
    assert page.title_value == "x" * 64
    assert page.title_truncated and page.value_truncated
    assert page.evidence_state is PageEvidenceState.TRUNCATED


def test_identity_and_order_are_stable() -> None:
    crawl = crawl_result(
        (
            page_record("https://example.com/b", PageRecordOptions(discovery_order=2)),
            page_record("https://example.com/a", PageRecordOptions(discovery_order=1)),
        )
    )
    first = project_crawl_result("job", "run", crawl, PageEvidenceConfiguration())
    second = project_crawl_result("job", "run", crawl, PageEvidenceConfiguration())
    assert [page.requested_url for page in first.pages] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert [page.evidence_id for page in first.pages] == [page.evidence_id for page in second.pages]
    assert first.ordering == PAGE_EVIDENCE_ORDERING


def test_projection_limit_is_explicit() -> None:
    crawl = crawl_result(
        (
            page_record("https://example.com/a", PageRecordOptions(discovery_order=1)),
            page_record("https://example.com/b", PageRecordOptions(discovery_order=2)),
        )
    )
    projection = project_crawl_result(
        "job", "run", crawl, PageEvidenceConfiguration(maximum_pages_per_run=1)
    )
    assert projection.truncated and projection.source_page_count == 2 and len(projection.pages) == 1


def test_cancelled_partial_page_is_explicit() -> None:
    skipped = replace(
        page_record(),
        frontier_state=FrontierState.SKIPPED,
        outcome=UrlCrawlOutcome.SKIPPED,
        fetch_result=None,
        parse_result=None,
        final_fetched_url=None,
    )
    cancelled = replace(crawl_result((skipped,)), state=CrawlState.CANCELLED)
    page = project_crawl_result("job", "run", cancelled, PageEvidenceConfiguration()).pages[0]
    assert page.evidence_state is PageEvidenceState.CANCELLED


def test_cursor_is_opaque_and_filter_bound() -> None:
    filters = PageEvidenceFilters(run_id="run")
    cursor = encode_cursor(3, "a" * 64, filters.fingerprint())
    assert PAGE_EVIDENCE_PAGINATION_VERSION not in cursor
    assert decode_cursor(cursor, filters.fingerprint()) == (3, "a" * 64)
    with pytest.raises(ValueError, match=PageEvidenceReasonCode.CURSOR_FILTER_MISMATCH):
        decode_cursor(cursor, replace(filters, run_id="other").fingerprint())
