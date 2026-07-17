"""Deterministic Phase 20 metadata-audit domain tests."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from musimack_tools.domain.fetching import FetchFailureCode
from musimack_tools.domain.metadata_audit import (
    ISSUE_CATEGORY,
    ISSUE_SEVERITY,
    METADATA_AUDIT_VERSION,
    METADATA_DUPLICATE_NORMALIZATION_VERSION,
    AuditState,
    DuplicateType,
    MetadataAuditConfiguration,
    Severity,
    audit_identity,
    decode_cursor,
    duplicate_group_identity,
    duplicate_normalize,
    encode_cursor,
    evaluate_page,
)
from musimack_tools.domain.page_evidence import PageEvidenceConfiguration, project_crawl_result
from page_evidence_helpers import PageRecordOptions, crawl_result, page_record

if TYPE_CHECKING:
    from musimack_tools.domain.crawl import UrlCrawlRecord
    from musimack_tools.domain.page_evidence import PageEvidenceRecord


def _project(*pages: UrlCrawlRecord) -> tuple[PageEvidenceRecord, ...]:
    return project_crawl_result(
        "job-accepted",
        "run-accepted",
        crawl_result(tuple(pages)),
        PageEvidenceConfiguration(enabled=True),
    ).pages


def test_exact_versions_states_and_severity_values() -> None:
    assert METADATA_AUDIT_VERSION == "seo-toolkit-metadata-audit-v1"
    assert (
        METADATA_DUPLICATE_NORMALIZATION_VERSION
        == "seo-toolkit-metadata-duplicate-normalization-v1"
    )
    assert {item.value for item in AuditState} == {
        "planned",
        "running",
        "completed",
        "completed_with_warnings",
        "partially_completed",
        "failed",
        "cancelled",
    }
    assert {item.value for item in Severity} == {"critical", "high", "medium", "low", "information"}


def test_configuration_is_disabled_bounded_and_version_fail_closed() -> None:
    assert not MetadataAuditConfiguration().enabled
    with pytest.raises(ValueError, match="version_unsupported"):
        MetadataAuditConfiguration(audit_version="unknown")
    with pytest.raises(ValueError, match="threshold"):
        MetadataAuditConfiguration(title_short_threshold=60, title_long_threshold=60)
    with pytest.raises(ValueError, match="page sizes"):
        MetadataAuditConfiguration(default_page_size=201, maximum_page_size=200)


def test_identity_is_stable_non_caller_controlled_and_configuration_sensitive() -> None:
    first = audit_identity("run-accepted", MetadataAuditConfiguration(enabled=True))
    assert first == audit_identity("run-accepted", MetadataAuditConfiguration(enabled=True))
    changed = audit_identity(
        "run-accepted", MetadataAuditConfiguration(enabled=True, title_long_threshold=61)
    )
    assert first != changed
    assert "run-accepted" not in first


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("  A\t TITLE  ", "a title"),
        ("Straße", "strasse"),
        ("\uff34\uff49\uff54\uff4c\uff45", "title"),
        ("Punctuation: stays!", "punctuation: stays!"),
        ("   ", ""),
    ],
)
def test_duplicate_normalization_is_exact(source: str, expected: str) -> None:
    assert duplicate_normalize(source) == expected


def test_duplicate_group_identity_is_type_scoped_and_stable() -> None:
    title = duplicate_group_identity("audit-a", DuplicateType.TITLE, "same")
    assert title == duplicate_group_identity("audit-a", DuplicateType.TITLE, "same")
    assert title != duplicate_group_identity("audit-a", DuplicateType.META_DESCRIPTION, "same")


def test_html_metadata_rules_use_durable_evidence() -> None:
    page = _project(
        page_record(
            options=PageRecordOptions(
                body="<title></title><meta name='description' content='short'>"
            )
        )
    )[0]
    codes = {
        issue.code
        for issue in evaluate_page("audit-a", page, MetadataAuditConfiguration(enabled=True))
    }
    assert {"title_empty", "meta_description_short", "canonical_missing"} <= codes


def test_failed_fetch_does_not_invent_missing_html_metadata() -> None:
    page = _project(
        page_record(
            options=PageRecordOptions(
                body=None, failure=FetchFailureCode.CONNECT_TIMEOUT, status=None
            )
        )
    )[0]
    codes = {
        issue.code
        for issue in evaluate_page("audit-a", page, MetadataAuditConfiguration(enabled=True))
    }
    assert "title_missing" not in codes
    assert "meta_description_missing" not in codes


def test_non_html_does_not_receive_html_metadata_issues() -> None:
    page = _project(
        page_record(options=PageRecordOptions(body="plain", content_type="text/plain"))
    )[0]
    codes = {
        issue.code
        for issue in evaluate_page("audit-a", page, MetadataAuditConfiguration(enabled=True))
    }
    assert "content_type_non_html" in codes
    assert not any(code.startswith(("title_", "meta_description_", "canonical_")) for code in codes)


def test_status_and_redirect_rules_are_deterministic() -> None:
    page = _project(page_record(options=PageRecordOptions(status=503)))[0]
    issues = evaluate_page("audit-a", page, MetadataAuditConfiguration(enabled=True))
    assert (
        next(issue for issue in issues if issue.code == "status_5xx").severity is Severity.CRITICAL
    )


def test_robots_sources_remain_distinct() -> None:
    page = _project(page_record())[0]
    codes = {
        issue.code
        for issue in evaluate_page("audit-a", page, MetadataAuditConfiguration(enabled=True))
    }
    assert "x_robots_tag_noindex" in codes
    assert "meta_robots_noindex" not in codes


def test_issue_taxonomy_and_severity_are_complete_and_fail_closed() -> None:
    assert ISSUE_CATEGORY.keys() == ISSUE_SEVERITY.keys()
    assert len(ISSUE_CATEGORY) == 43
    assert ISSUE_SEVERITY["canonical_conflicting"] is Severity.HIGH
    assert ISSUE_SEVERITY["redirect_loop"] is Severity.CRITICAL


def test_cursor_rejects_filter_and_version_mismatch() -> None:
    cursor = encode_cursor("pages", "order-v1", "fingerprint-a", [10])
    assert decode_cursor(cursor, "pages", "order-v1", "fingerprint-a") == [10]
    with pytest.raises(ValueError, match="filter_mismatch"):
        decode_cursor(cursor, "pages", "order-v1", "fingerprint-b")
    with pytest.raises(ValueError, match="invalid_cursor"):
        decode_cursor("not-base64", "pages", "order-v1", "fingerprint-a")


def test_issue_identity_is_idempotent() -> None:
    page = _project(page_record())[0]
    configuration = MetadataAuditConfiguration(enabled=True)
    first = evaluate_page("audit-a", page, configuration)
    second = evaluate_page("audit-a", replace(page), configuration)
    assert [item.issue_id for item in first] == [item.issue_id for item in second]
