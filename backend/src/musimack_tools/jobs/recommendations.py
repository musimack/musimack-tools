"""Bounded process-local recommendation paging compatible with durable reads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from musimack_tools.domain.job import (
    MAXIMUM_RECOMMENDATION_PAGE_SIZE,
    DurableRecommendation,
    DurableRecommendationDetail,
    JobLookupOutcome,
    JobRecommendationDetail,
    JobRecommendationPage,
    JobResultView,
    RecommendationRuleDetail,
    RecommendationWarningDetail,
    normalize_recommendation_reason_filter,
)

if TYPE_CHECKING:
    from musimack_tools.domain.sitemap import SitemapRecommendation


def recommendations_from_result(  # noqa: PLR0913 - mirrors the bounded API filters.
    view: JobResultView,
    *,
    offset: int,
    limit: int,
    state: str | None = None,
    reason: str | None = None,
    text: str | None = None,
) -> JobRecommendationPage:
    bounded_limit = min(max(limit, 0), MAXIMUM_RECOMMENDATION_PAGE_SIZE)
    bounded_offset = max(offset, 0)
    if view.outcome is JobLookupOutcome.NOT_FOUND or view.snapshot is None:
        return JobRecommendationPage(
            outcome=JobLookupOutcome.NOT_FOUND,
            details_available=False,
            job_id=None,
            run_id=None,
            offset=bounded_offset,
            limit=bounded_limit,
            total=0,
            items=(),
            rule_set_version=None,
        )
    projection = view.full_result.recommendation_projection if view.full_result else None
    if projection is None:
        return JobRecommendationPage(
            outcome=JobLookupOutcome.FOUND,
            details_available=False,
            job_id=view.snapshot.job_id,
            run_id=view.snapshot.run_id,
            offset=bounded_offset,
            limit=bounded_limit,
            total=0,
            items=(),
            rule_set_version=None,
        )
    normalized_text = text.casefold().strip() if text else None
    normalized_reason = normalize_recommendation_reason_filter(reason)
    indexed = tuple(enumerate(projection.recommendations, start=1))
    filtered = tuple(
        (sequence, item)
        for sequence, item in indexed
        if (state is None or item.state.value == state)
        and (normalized_reason is None or normalized_reason in item.primary_reason.value.casefold())
        and (normalized_text is None or normalized_text in item.evaluated_url.casefold())
    )
    page = filtered[bounded_offset : bounded_offset + bounded_limit]
    return JobRecommendationPage(
        outcome=JobLookupOutcome.FOUND,
        details_available=True,
        job_id=view.snapshot.job_id,
        run_id=view.snapshot.run_id,
        offset=bounded_offset,
        limit=bounded_limit,
        total=len(filtered),
        items=tuple(_recommendation(item, sequence) for sequence, item in page),
        rule_set_version=projection.rule_set_version,
    )


def recommendation_detail_from_result(
    view: JobResultView, *, sequence: int
) -> JobRecommendationDetail:
    if view.outcome is JobLookupOutcome.NOT_FOUND or view.snapshot is None:
        return JobRecommendationDetail(
            outcome=JobLookupOutcome.NOT_FOUND, details_available=False, item=None
        )
    projection = view.full_result.recommendation_projection if view.full_result else None
    if projection is None:
        return JobRecommendationDetail(
            outcome=JobLookupOutcome.FOUND, details_available=False, item=None
        )
    if not 1 <= sequence <= len(projection.recommendations):
        return JobRecommendationDetail(
            outcome=JobLookupOutcome.FOUND, details_available=True, item=None
        )
    item = projection.recommendations[sequence - 1]
    reasons = tuple(
        dict.fromkeys(
            (
                item.primary_reason.value,
                *(value.value for value in item.hard_exclusion_reasons),
                *(value.value for value in item.review_reasons),
            )
        )
    )
    warnings = tuple(
        RecommendationWarningDetail(value.code, value.explanation, value.source)
        for value in (*item.warnings, *item.metadata_warnings)
    )
    detail = DurableRecommendationDetail(
        recommendation=_recommendation(item, sequence),
        reason_codes=reasons,
        rule_evidence=tuple(
            RecommendationRuleDetail(
                value.rule_id,
                value.outcome.value,
                value.reason_code.value if value.reason_code else None,
                value.explanation,
            )
            for value in item.rule_results
        ),
        warning_details=warnings,
        metadata_warning_codes=tuple(value.code for value in item.metadata_warnings),
        evidence_id=None,
        crawl_depth=None,
        fetch_outcome=None,
        evidence_state=None,
        page_failure_code=None,
        title_presence=None,
        title=None,
        description_presence=None,
        meta_description=None,
        canonical_presence=None,
        meta_robots=(),
        x_robots_tag=(),
        redirect_chain=(),
        redirect_truncated=None,
        redirect_loop=None,
        sitemap_membership=None,
    )
    return JobRecommendationDetail(
        outcome=JobLookupOutcome.FOUND, details_available=True, item=detail
    )


def _recommendation(item: SitemapRecommendation, sequence: int) -> DurableRecommendation:
    return DurableRecommendation(
        sequence=sequence,
        url=item.evaluated_url,
        requested_url=item.requested_url,
        final_url=item.final_url,
        state=item.state.value,
        determinacy=item.determinacy.value,
        primary_reason=item.primary_reason.value,
        explanation=item.explanation,
        http_status=item.http_status,
        content_type=item.content_type,
        fetch_failure_code=item.fetch_failure_code,
        canonical_url=item.canonical.selected_url,
        canonical_conflicting=item.canonical.conflicting,
        redirect_source=item.redirect.is_redirect_source,
        redirect_hops=item.redirect.hop_count,
        redirect_final_url=item.redirect.final_url,
        robots_available=item.robots.available,
        robots_allowed=item.robots.allowed,
        robots_reason_code=item.robots.reason_code,
        generic_directives=item.indexability.generic_directives,
        crawler_specific_directives=item.indexability.crawler_specific_directives,
        indexability_conflict=item.indexability.generic_index_conflict,
        configured_exclusions=tuple(
            (value.rule_type, value.value) for value in item.configured_exclusions
        ),
    )
