"""Deterministic accepted crawl evidence fixtures for Phase 20A tests."""

from __future__ import annotations

from dataclasses import dataclass

from musimack_tools.crawl.html import HtmlMetadataParser
from musimack_tools.crawl.indexability import IndexabilityEvidenceParser
from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import create_scope_policy
from musimack_tools.domain.crawl import (
    CrawlConfigurationSnapshot,
    CrawlCounters,
    CrawlResult,
    CrawlState,
    FrontierState,
    UrlCrawlOutcome,
    UrlCrawlRecord,
)
from musimack_tools.domain.fetching import (
    FetchFailureCode,
    FetchOutcome,
    FetchResult,
    RedirectHop,
    ResponseHeaders,
)
from musimack_tools.domain.robots import (
    CrawlPermissionDecision,
    CrawlPermissionReason,
    RobotsFetchOutcome,
    RobotsParseOutcome,
)


@dataclass(frozen=True, slots=True)
class PageRecordOptions:
    body: str | None = (
        "<title>Durable evidence</title>"
        "<meta name='description' content='Stored description'>"
        "<link rel='canonical' href='/'>"
    )
    content_type: str | None = "text/html; charset=utf-8"
    status: int | None = 200
    failure: FetchFailureCode | None = None
    final_url: str | None = None
    discovery_order: int = 0
    x_robots: tuple[str, ...] = ("noindex",)


def page_record(
    url: str = "https://example.com/", options: PageRecordOptions | None = None
) -> UrlCrawlRecord:
    selected = options or PageRecordOptions()
    target = selected.final_url or url
    payload = selected.body.encode() if selected.body is not None else None
    redirect_chain = (
        (
            RedirectHop(
                source_url=url,
                status_code=301,
                raw_location=target,
                destination_url=target,
                allowed=True,
                failure_code=None,
                explanation="accepted redirect",
            ),
        )
        if selected.final_url is not None
        else ()
    )
    fetch = FetchResult(
        requested_url=url,
        final_url=target,
        outcome=FetchOutcome.FAILURE if selected.failure else FetchOutcome.SUCCESS,
        status_code=selected.status,
        headers=ResponseHeaders(content_type=selected.content_type, x_robots_tag=selected.x_robots),
        content_type=selected.content_type,
        declared_content_length=len(payload) if payload else None,
        actual_bytes_read=len(payload) if payload else 0,
        body_truncated=selected.failure is FetchFailureCode.RESPONSE_TOO_LARGE,
        redirect_chain=redirect_chain,
        request_duration_seconds=0.01,
        dns_evidence=(),
        failure_code=selected.failure,
        failure_explanation="accepted failure" if selected.failure else None,
        body=payload,
    )
    parse = (
        HtmlMetadataParser().parse(fetch)
        if payload is not None and selected.failure is None
        else None
    )
    x_evidence = IndexabilityEvidenceParser().parse_x_robots_tag(selected.x_robots)
    combined = (
        IndexabilityEvidenceParser().combine(parse.meta_robots, x_evidence) if parse else None
    )
    permission = CrawlPermissionDecision(
        evaluated_url=url,
        origin="https://example.com",
        robots_url="https://example.com/robots.txt",
        fetch_outcome=RobotsFetchOutcome.NO_POLICY,
        parse_outcome=RobotsParseOutcome.NOT_APPLICABLE,
        selected_group_index=None,
        matched_rule=None,
        allowed=True,
        reason_code=CrawlPermissionReason.ALLOWED_NO_ROBOTS_FILE,
        explanation="accepted decision",
        cache_hit=False,
        warnings=(),
        temporary_unavailability=False,
        newly_fetched_bytes=0,
        evaluation_duration_seconds=0.0,
    )
    return UrlCrawlRecord(
        requested_url=url,
        first_discovered_value=url,
        first_referrer=None,
        referring_urls=(),
        discovery_depth=0,
        best_known_depth=0,
        discovery_order=selected.discovery_order,
        frontier_state=FrontierState.COMPLETED,
        outcome=(
            UrlCrawlOutcome.FETCH_FAILED
            if selected.failure
            else UrlCrawlOutcome.PARSED
            if parse
            else UrlCrawlOutcome.FETCHED
        ),
        fetch_result=fetch,
        parse_result=parse,
        final_fetched_url=target,
        discovered_link_count=0,
        admitted_link_count=0,
        rejected_link_count=0,
        skip_reason=None,
        started_at_seconds=0.0,
        ended_at_seconds=0.01,
        accepted_response_bytes=len(payload) if payload else 0,
        robots_permission=permission,
        x_robots_tag=x_evidence,
        indexability_evidence=combined,
    )


def crawl_result(records: tuple[UrlCrawlRecord, ...]) -> CrawlResult:
    seed = normalize_url("https://example.com/")
    return CrawlResult(
        seed_url=seed.normalized,
        scope_policy=create_scope_policy(seed),
        started_at_seconds=0.0,
        ended_at_seconds=1.0,
        duration_seconds=1.0,
        state=CrawlState.COMPLETED,
        url_records=records,
        discoveries=(),
        counters=CrawlCounters(),
        limit_events=(),
        errors=(),
        cancellation=None,
        total_accepted_bytes=0,
        maximum_observed_queue_size=1,
        maximum_active_worker_count=1,
        configuration=CrawlConfigurationSnapshot(
            maximum_unique_urls=100,
            maximum_depth=5,
            maximum_duration_seconds=60,
            maximum_total_fetched_bytes=1_000_000,
            maximum_concurrent_fetches=2,
            maximum_queued_urls=100,
            minimum_per_origin_delay_seconds=0,
            query_urls_allowed=True,
            exclusion_rules=(),
        ),
    )
