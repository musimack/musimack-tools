"""Phase 22 deterministic domain, taxonomy, cursor, and evidence tests."""

from __future__ import annotations

import pytest

from musimack_tools.domain.link_audit import (
    BrokenLinkReason,
    BrokenLinkState,
    LinkAuditConfiguration,
    RedirectReason,
    RedirectState,
    TargetEvidence,
    classify_target,
    decode_cursor,
    encode_cursor,
    filter_fingerprint,
    stable_identity,
)
from musimack_tools.domain.page_evidence import PageEvidenceConfiguration, project_crawl_result
from page_evidence_helpers import PageRecordOptions, crawl_result, page_record


@pytest.mark.parametrize(
    ("evidence", "state", "reason"),
    [
        (
            TargetEvidence("https://example.com/ok", http_status=200),
            BrokenLinkState.WORKING_INTERNAL_LINK,
            BrokenLinkReason.WORKING,
        ),
        (
            TargetEvidence("https://example.com/missing", http_status=404),
            BrokenLinkState.BROKEN_INTERNAL_LINK,
            BrokenLinkReason.TARGET_404,
        ),
        (
            TargetEvidence("https://example.com/gone", http_status=410),
            BrokenLinkState.BROKEN_INTERNAL_LINK,
            BrokenLinkReason.TARGET_410,
        ),
        (
            TargetEvidence("https://example.com/error", http_status=503),
            BrokenLinkState.BROKEN_INTERNAL_LINK,
            BrokenLinkReason.TARGET_5XX,
        ),
        (
            TargetEvidence(
                "https://example.com/timeout", fetch_failed=True, failure_code="read_timeout"
            ),
            BrokenLinkState.TARGET_FETCH_FAILED,
            BrokenLinkReason.TARGET_TIMEOUT,
        ),
        (
            TargetEvidence(
                "https://example.com/dns", fetch_failed=True, failure_code="dns_failure"
            ),
            BrokenLinkState.TARGET_FETCH_FAILED,
            BrokenLinkReason.TARGET_DNS_FAILURE,
        ),
        (
            TargetEvidence(
                "https://example.com/blocked", fetch_failed=True, failure_code="robots_blocked"
            ),
            BrokenLinkState.TARGET_FETCH_FAILED,
            BrokenLinkReason.TARGET_BLOCKED,
        ),
        (
            TargetEvidence(
                "https://example.com/file.pdf", http_status=200, content_type_category="pdf"
            ),
            BrokenLinkState.TARGET_NON_HTML,
            BrokenLinkReason.TARGET_NON_HTML,
        ),
        (
            TargetEvidence("https://example.com/x", source_available=False),
            BrokenLinkState.SOURCE_PAGE_UNAVAILABLE,
            BrokenLinkReason.SOURCE_FETCH_FAILED,
        ),
        (
            TargetEvidence("https://example.com/x", source_partial=True),
            BrokenLinkState.SOURCE_PAGE_UNAVAILABLE,
            BrokenLinkReason.SOURCE_PARSE_PARTIAL,
        ),
        (
            TargetEvidence("https://example.com/unknown"),
            BrokenLinkState.UNVERIFIED_INTERNAL_LINK,
            BrokenLinkReason.TARGET_NOT_CRAWLED,
        ),
        (
            TargetEvidence("https://outside.example/path", internal=False),
            BrokenLinkState.EXTERNAL_LINK_NOT_AUDITED,
            BrokenLinkReason.EXTERNAL_TARGET,
        ),
        (
            TargetEvidence("https://example.com/private", in_scope=False),
            BrokenLinkState.OUT_OF_SCOPE_INTERNAL_TARGET,
            BrokenLinkReason.TARGET_OUT_OF_SCOPE,
        ),
    ],
)
def test_broken_link_classification_matrix(
    evidence: TargetEvidence, state: BrokenLinkState, reason: BrokenLinkReason
) -> None:
    result = classify_target(evidence)
    assert result.broken_state is state
    assert result.broken_reason is reason


def test_redirect_precedence_preserves_loop_and_broken_destination_reasons() -> None:
    loop = classify_target(
        TargetEvidence(
            "https://example.com/a",
            redirect_loop=True,
            redirect_hops=({"status_code": 301}, {"status_code": 302}),
        )
    )
    assert loop.redirect_state is RedirectState.REDIRECT_LOOP
    assert loop.redirect_reason is RedirectReason.REDIRECT_LOOP_DETECTED
    broken = classify_target(
        TargetEvidence(
            "https://example.com/old",
            redirect_hops=({"status_code": 301},),
            final_url="https://example.com/missing",
            final_status=404,
        )
    )
    assert broken.redirect_state is RedirectState.REDIRECT_TO_BROKEN_TARGET
    assert broken.redirect_reason is RedirectReason.REDIRECT_TARGET_404


@pytest.mark.parametrize(
    ("evidence", "state", "reason"),
    [
        (
            TargetEvidence(
                "https://example.com/old",
                redirect_hops=({"status_code": 301},),
                final_url="https://example.com/new",
                final_status=200,
            ),
            RedirectState.SINGLE_REDIRECT,
            RedirectReason.PERMANENT_REDIRECT,
        ),
        (
            TargetEvidence(
                "https://example.com/old",
                redirect_hops=({"status_code": 302},),
                final_url="https://example.com/new",
                final_status=200,
            ),
            RedirectState.SINGLE_REDIRECT,
            RedirectReason.TEMPORARY_REDIRECT,
        ),
        (
            TargetEvidence(
                "https://example.com/old",
                redirect_hops=({"status_code": 301}, {"status_code": 302}),
                final_url="https://example.com/new",
                final_status=200,
            ),
            RedirectState.REDIRECT_CHAIN,
            RedirectReason.MIXED_REDIRECT_CHAIN,
        ),
        (
            TargetEvidence(
                "https://example.com/old",
                redirect_hops=({"status_code": 301},),
                final_url="https://outside.example/new",
                final_status=200,
                final_internal=False,
                final_in_scope=False,
            ),
            RedirectState.REDIRECT_TO_EXTERNAL_TARGET,
            RedirectReason.REDIRECT_TARGET_EXTERNAL,
        ),
        (
            TargetEvidence(
                "https://example.com/old",
                redirect_hops=({"status_code": 301},),
                final_url="https://example.com:8443/new",
                final_status=200,
                final_in_scope=False,
            ),
            RedirectState.REDIRECT_TO_OUT_OF_SCOPE_TARGET,
            RedirectReason.REDIRECT_TARGET_OUT_OF_SCOPE,
        ),
        (
            TargetEvidence(
                "https://example.com/old",
                redirect_hops=({"status_code": 301},),
                final_url="https://example.com/file.pdf",
                final_status=200,
                final_content_type_category="pdf",
            ),
            RedirectState.REDIRECT_TO_NON_HTML_TARGET,
            RedirectReason.REDIRECT_TARGET_NON_HTML,
        ),
        (
            TargetEvidence(
                "https://example.com/old", redirect_hops=({"status_code": 301},), fetch_failed=True
            ),
            RedirectState.REDIRECT_UNVERIFIED,
            RedirectReason.REDIRECT_TARGET_FETCH_FAILED,
        ),
        (
            TargetEvidence(
                "https://example.com/old",
                redirect_hops=({"status_code": 301},),
                chain_too_long=True,
            ),
            RedirectState.REDIRECT_CHAIN,
            RedirectReason.REDIRECT_CHAIN_TOO_LONG,
        ),
    ],
)
def test_redirect_classification_matrix(
    evidence: TargetEvidence, state: RedirectState, reason: RedirectReason
) -> None:
    result = classify_target(evidence)
    assert result.redirect_state is state
    assert result.redirect_reason is reason


def test_link_evidence_projection_keeps_occurrences_fragments_rel_and_schemes() -> None:
    body = """
    <a href='/ok#details' rel='nofollow sponsored'> First </a>
    <a href='/ok#other'>Duplicate target</a>
    <a href='#local'>Fragment</a><a href='mailto:a@example.com'>Mail</a>
    <a href='tel:+15551234567'>Phone</a><a href='javascript:void(0)'>JS</a>
    <a href='data:text/plain,x'>Data</a><a href='https://outside.example/x'>External</a>
    """
    projection = project_crawl_result(
        "job",
        "run",
        crawl_result((page_record(options=PageRecordOptions(body=body)),)),
        PageEvidenceConfiguration(enabled=True),
    )
    assert len(projection.links) == 8
    assert [item.link_sequence for item in projection.links] == list(range(8))
    first = projection.links[0]
    assert first.raw_href == "/ok#details"
    assert first.fragment == "details"
    assert first.anchor_text == "First"
    assert first.nofollow
    assert first.rel_values_json == '["nofollow","sponsored"]'
    assert [item.link_type for item in projection.links[2:7]] == [
        "fragment",
        "mailto",
        "tel",
        "javascript",
        "data",
    ]
    assert projection.links[0].target_url_identity == projection.links[1].target_url_identity
    assert projection.links[0].link_id != projection.links[1].link_id


def test_cursor_is_versioned_filter_bound_and_deterministic() -> None:
    filters = filter_fingerprint({"severity": "high"})
    cursor = encode_cursor("targets", "stable-v1", filters, 25)
    assert decode_cursor(cursor, "targets", "stable-v1", filters) == 25
    with pytest.raises(ValueError, match="link_audit_cursor_filter_mismatch"):
        decode_cursor(cursor, "targets", "stable-v1", filter_fingerprint({}))
    assert stable_identity("a", 1) == stable_identity("a", 1)


def test_configuration_rejects_unsafe_bounds() -> None:
    with pytest.raises(ValueError, match="page sizes"):
        LinkAuditConfiguration(default_page_size=201, maximum_page_size=200)
