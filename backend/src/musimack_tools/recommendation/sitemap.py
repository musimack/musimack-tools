"""Pure sitemap eligibility recommendation and crawl projection engine."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import evaluate_scope
from musimack_tools.domain.fetching import FetchOutcome
from musimack_tools.domain.html import HtmlParseOutcome, HtmlWarningCode
from musimack_tools.domain.indexability import IndexabilityConflictKind
from musimack_tools.domain.sitemap import (
    CanonicalSummary,
    EvidenceReference,
    GenericIndexabilitySummary,
    ReasonCount,
    RecommendationConfigurationSnapshot,
    RecommendationDeterminacy,
    RecommendationPolicy,
    RecommendationState,
    RecommendationWarning,
    RedirectSummary,
    RobotsPermissionSummary,
    RuleOutcome,
    RuleResult,
    SitemapReasonCode,
    SitemapRecommendation,
    SitemapRecommendationProjection,
    WarningCount,
)
from musimack_tools.domain.urls import ScopeReasonCode, UrlErrorCode, UrlNormalizationError
from musimack_tools.recommendation.rules import (
    HTML_MEDIA_TYPES,
    METADATA_WARNING_CODES,
    configured_exclusion_matches,
    fetch_failure_reason,
)

if TYPE_CHECKING:
    from musimack_tools.domain.crawl import CrawlExclusionRule, CrawlResult, UrlCrawlRecord
    from musimack_tools.domain.sitemap import ConfiguredExclusionEvidence
    from musimack_tools.domain.urls import CrawlScopePolicy

_LOGGER = logging.getLogger(__name__)
_HTTP_OK = 200


@dataclass(slots=True)
class _Evaluation:
    rules: list[RuleResult] = field(default_factory=list)
    hard: list[SitemapReasonCode] = field(default_factory=list)
    review: list[SitemapReasonCode] = field(default_factory=list)
    indeterminate: list[SitemapReasonCode] = field(default_factory=list)
    warnings: list[RecommendationWarning] = field(default_factory=list)

    def add(
        self,
        rule_id: str,
        outcome: RuleOutcome,
        reason: SitemapReasonCode | None,
        explanation: str,
        evidence: tuple[EvidenceReference, ...] = (),
    ) -> None:
        self.rules.append(RuleResult(rule_id, outcome, reason, explanation, evidence))
        if reason is None:
            return
        target = {
            RuleOutcome.HARD_EXCLUSION: self.hard,
            RuleOutcome.REVIEW: self.review,
            RuleOutcome.INDETERMINATE: self.indeterminate,
        }.get(outcome)
        if target is not None and reason not in target:
            target.append(reason)


class SitemapRecommendationEngine:
    """Evaluate accepted crawl evidence without networking, persistence, or framework state."""

    def __init__(
        self,
        policy: RecommendationPolicy | None = None,
        *,
        logger: logging.Logger = _LOGGER,
    ) -> None:
        self._policy = policy or RecommendationPolicy()
        self._logger = logger

    def recommend(
        self,
        record: UrlCrawlRecord,
        scope_policy: CrawlScopePolicy,
        exclusion_rules: tuple[CrawlExclusionRule, ...] = (),
    ) -> SitemapRecommendation:
        """Return one complete recommendation using explicit deterministic precedence."""
        self._logger.info(
            "sitemap_recommendation_started",
            extra={
                "url": _safe_url_summary(record.requested_url),
                "rule_set_version": self._policy.rule_set_version,
            },
        )
        evaluation = _Evaluation()
        normalized = _evaluate_url_and_scope(evaluation, record.requested_url, scope_policy)
        _evaluate_robots(evaluation, record)
        _evaluate_fetch(evaluation, record)
        redirect = _evaluate_redirect(evaluation, record)
        _evaluate_status(evaluation, record)
        _evaluate_content(evaluation, record, self._policy)
        indexability = _evaluate_indexability(evaluation, record, self._policy)
        configured = (
            configured_exclusion_matches(normalized, exclusion_rules)
            if normalized is not None
            else ()
        )
        _evaluate_configured_exclusions(evaluation, configured)
        canonical = _evaluate_canonical(evaluation, record, self._policy)
        metadata_warnings = _metadata_warnings(record)
        _evaluate_evidence_quality(evaluation, record, self._policy)

        state, determinacy, primary = _final_state(evaluation)
        recommendation = SitemapRecommendation(
            evaluated_url=normalized or record.requested_url,
            requested_url=record.requested_url,
            final_url=record.final_fetched_url,
            state=state,
            determinacy=determinacy,
            primary_reason=primary,
            hard_exclusion_reasons=tuple(evaluation.hard),
            review_reasons=tuple(evaluation.review),
            warnings=tuple(evaluation.warnings),
            metadata_warnings=metadata_warnings,
            fetch_failure_code=(
                record.fetch_result.failure_code.value
                if record.fetch_result is not None and record.fetch_result.failure_code is not None
                else None
            ),
            http_status=(
                record.fetch_result.status_code if record.fetch_result is not None else None
            ),
            content_type=_content_type(record),
            robots=_robots_summary(record),
            indexability=indexability,
            canonical=canonical,
            redirect=redirect,
            configured_exclusions=configured,
            rule_results=tuple(evaluation.rules),
            explanation=_explanation(state, primary),
        )
        self._logger.info(
            f"sitemap_url_{state.value}",
            extra={
                "url": _safe_url_summary(recommendation.evaluated_url),
                "state": state.value,
                "primary_reason": primary.value,
                "status": recommendation.http_status,
                "rule_set_version": self._policy.rule_set_version,
            },
        )
        return recommendation

    def project(self, crawl: CrawlResult) -> SitemapRecommendationProjection:
        """Project one complete crawl while preserving evidence order and unique identities."""
        recommendations: list[SitemapRecommendation] = []
        seen: set[str] = set()
        duplicate_count = 0
        records_by_identity: dict[str, UrlCrawlRecord] = {}
        for record in crawl.url_records:
            identity = _identity(record.requested_url)
            if identity in records_by_identity:
                duplicate_count += 1
                continue
            records_by_identity[identity] = record

        for record in crawl.url_records:
            identity = _identity(record.requested_url)
            if identity in seen:
                continue
            seen.add(identity)
            recommendation = self.recommend(
                record,
                crawl.scope_policy,
                crawl.configuration.exclusion_rules,
            )
            target = recommendation.redirect.final_url
            target_identity = _identity(target) if target is not None else None
            target_evaluated = target_identity in records_by_identity if target_identity else None
            recommendation = _with_redirect_target_state(
                recommendation,
                target_evaluated=target_evaluated,
            )
            recommendations.append(recommendation)

        projection = _projection(tuple(recommendations), duplicate_count, self._policy)
        self._logger.info(
            "sitemap_projection_completed",
            extra={
                "included": projection.included_url_count,
                "excluded": projection.excluded_url_count,
                "review": projection.review_count,
                "indeterminate": projection.indeterminate_count,
                "rule_set_version": projection.rule_set_version,
            },
        )
        return projection


def _evaluate_url_and_scope(
    evaluation: _Evaluation,
    requested_url: str,
    scope_policy: CrawlScopePolicy,
) -> str | None:
    try:
        normalized = normalize_url(requested_url)
    except UrlNormalizationError as error:
        reason = (
            SitemapReasonCode.UNSUPPORTED_SCHEME
            if error.code is UrlErrorCode.UNSUPPORTED_SCHEME
            else SitemapReasonCode.INVALID_URL
        )
        evaluation.add("01_url_and_scope", RuleOutcome.HARD_EXCLUSION, reason, str(error))
        return None
    decision = evaluate_scope(scope_policy, normalized)
    if decision.allowed:
        evaluation.add(
            "01_url_and_scope",
            RuleOutcome.PASSED,
            None,
            "The normalized URL is within the approved crawl scope",
        )
    else:
        reason = (
            SitemapReasonCode.DISALLOWED_PORT
            if decision.reason_code is ScopeReasonCode.DENIED_PORT_MISMATCH
            else SitemapReasonCode.UNSUPPORTED_SCHEME
            if decision.reason_code is ScopeReasonCode.DENIED_SCHEME
            else SitemapReasonCode.OUTSIDE_SCOPE
        )
        evaluation.add(
            "01_url_and_scope",
            RuleOutcome.HARD_EXCLUSION,
            reason,
            decision.explanation,
        )
    return normalized.normalized


def _evaluate_robots(evaluation: _Evaluation, record: UrlCrawlRecord) -> None:
    permission = record.robots_permission
    if permission is None:
        evaluation.add(
            "03_robots_permission",
            RuleOutcome.INDETERMINATE,
            SitemapReasonCode.MISSING_REQUIRED_EVIDENCE,
            "No robots crawl-permission decision is available",
        )
    elif not permission.allowed:
        evaluation.add(
            "03_robots_permission",
            RuleOutcome.HARD_EXCLUSION,
            SitemapReasonCode.ROBOTS_DENIED,
            "Robots crawl permission denied retrieval; indexability remains unknown",
            (EvidenceReference("robots", "robots.txt", permission.reason_code.value),),
        )
    else:
        evaluation.add(
            "03_robots_permission",
            RuleOutcome.PASSED,
            None,
            "Robots crawl permission allowed retrieval",
        )


def _evaluate_fetch(evaluation: _Evaluation, record: UrlCrawlRecord) -> None:
    fetch = record.fetch_result
    if fetch is None:
        evaluation.add(
            "04_fetch_outcome",
            RuleOutcome.HARD_EXCLUSION,
            SitemapReasonCode.NOT_FETCHED,
            "The URL has no completed page fetch evidence",
        )
    elif fetch.outcome is FetchOutcome.FAILURE:
        reason = fetch_failure_reason(fetch.failure_code)
        evaluation.add(
            "04_fetch_outcome",
            RuleOutcome.HARD_EXCLUSION,
            reason,
            "The bounded page fetch did not complete successfully",
            (
                EvidenceReference(
                    "fetch_failure",
                    "safe_fetcher",
                    fetch.failure_code.value if fetch.failure_code is not None else None,
                ),
            ),
        )
    else:
        evaluation.add(
            "04_fetch_outcome",
            RuleOutcome.PASSED,
            None,
            "The bounded page fetch completed successfully",
        )


def _evaluate_redirect(evaluation: _Evaluation, record: UrlCrawlRecord) -> RedirectSummary:
    fetch = record.fetch_result
    final_url = record.final_fetched_url or (fetch.final_url if fetch is not None else None)
    redirected = bool(
        fetch is not None
        and fetch.redirect_chain
        and final_url is not None
        and _identity(final_url) != _identity(record.requested_url)
    )
    if redirected:
        evaluation.add(
            "05_redirect_source",
            RuleOutcome.HARD_EXCLUSION,
            SitemapReasonCode.REDIRECT_SOURCE,
            "The requested URL redirects to a different normalized final URL",
            (EvidenceReference("redirect", "safe_fetcher", final_url),),
        )
    else:
        evaluation.add(
            "05_redirect_source",
            RuleOutcome.PASSED,
            None,
            "The requested URL is not a redirect source to another identity",
        )
    return RedirectSummary(
        redirected,
        len(fetch.redirect_chain) if fetch is not None else 0,
        final_url,
        None,
    )


def _evaluate_status(evaluation: _Evaluation, record: UrlCrawlRecord) -> None:
    status = record.fetch_result.status_code if record.fetch_result is not None else None
    if status is None:
        evaluation.add(
            "06_http_status",
            RuleOutcome.HARD_EXCLUSION,
            SitemapReasonCode.MISSING_HTTP_STATUS,
            "No final HTTP status is available",
        )
    elif status != _HTTP_OK:
        evaluation.add(
            "06_http_status",
            RuleOutcome.HARD_EXCLUSION,
            SitemapReasonCode.NON_200_STATUS,
            f"The final HTTP status is {status}, not 200",
            (EvidenceReference("status", "safe_fetcher", str(status)),),
        )
    else:
        evaluation.add(
            "06_http_status",
            RuleOutcome.PASSED,
            None,
            "The final HTTP status is 200",
        )


def _evaluate_content(
    evaluation: _Evaluation,
    record: UrlCrawlRecord,
    policy: RecommendationPolicy,
) -> None:
    parse = record.parse_result
    declared = _media_type(record.fetch_result.content_type) if record.fetch_result else None
    effective = parse.effective_media_type if parse is not None else None
    if (
        parse is not None
        and parse.outcome is HtmlParseOutcome.PARSED
        and effective in HTML_MEDIA_TYPES
    ):
        if declared not in {None, "application/octet-stream", *HTML_MEDIA_TYPES}:
            evaluation.add(
                "07_html_content",
                RuleOutcome.INDETERMINATE,
                SitemapReasonCode.AMBIGUOUS_CONTENT_TYPE,
                "Declared non-HTML content conflicts with parsed HTML evidence",
            )
            return
        if parse.media_type_inferred and policy.ambiguous_sniffed_html_requires_review:
            evaluation.add(
                "07_html_content",
                RuleOutcome.REVIEW,
                SitemapReasonCode.AMBIGUOUS_CONTENT_TYPE,
                "HTML was structurally inferred from an ambiguous media type",
            )
        else:
            evaluation.add(
                "07_html_content",
                RuleOutcome.PASSED,
                None,
                "The accepted parser confirmed HTML content",
            )
        return
    if declared is not None and declared not in HTML_MEDIA_TYPES:
        evaluation.add(
            "07_html_content",
            RuleOutcome.HARD_EXCLUSION,
            SitemapReasonCode.NON_HTML_CONTENT,
            f"The final response media type {declared!r} is not HTML",
        )
    elif declared in HTML_MEDIA_TYPES:
        evaluation.add(
            "07_html_content",
            RuleOutcome.PASSED,
            None,
            "The final response declares an approved HTML media type",
        )
    elif parse is None:
        evaluation.add(
            "07_html_content",
            RuleOutcome.INDETERMINATE,
            SitemapReasonCode.MISSING_REQUIRED_EVIDENCE,
            "HTML parse evidence is missing",
        )
    else:
        evaluation.add(
            "07_html_content",
            RuleOutcome.HARD_EXCLUSION,
            SitemapReasonCode.NON_HTML_CONTENT,
            "The accepted parser did not confirm an HTML page",
        )


def _evaluate_indexability(
    evaluation: _Evaluation,
    record: UrlCrawlRecord,
    policy: RecommendationPolicy,
) -> GenericIndexabilitySummary:
    evidence = record.indexability_evidence
    if evidence is None:
        evaluation.add(
            "08_generic_indexability",
            RuleOutcome.INDETERMINATE,
            SitemapReasonCode.MISSING_REQUIRED_EVIDENCE,
            "Combined meta and X-Robots-Tag evidence is missing",
        )
        return GenericIndexabilitySummary(
            generic_directives=(),
            crawler_specific_directives=(),
            generic_index_conflict=False,
        )
    generic = tuple(
        directive.name
        for item in evidence.meta_robots
        if item.agent_name == "robots"
        for directive in item.directives
    ) + tuple(
        directive.name
        for item in evidence.x_robots_tag.records
        if item.agent_name is None
        for directive in item.directives
    )
    crawler_specific = tuple(
        f"{item.agent_name}:{directive.name}"
        for item in evidence.meta_robots
        if item.agent_name != "robots"
        for directive in item.directives
    ) + tuple(
        f"{item.agent_name}:{directive.name}"
        for item in evidence.x_robots_tag.records
        if item.agent_name is not None
        for directive in item.directives
    )
    conflict = ("index" in generic and "noindex" in generic) or any(
        item.kind is IndexabilityConflictKind.INDEX for item in evidence.conflicts
    )
    if "noindex" in generic:
        evaluation.add(
            "08_generic_indexability",
            RuleOutcome.HARD_EXCLUSION,
            SitemapReasonCode.GENERIC_NOINDEX,
            "Trustworthy generic indexability evidence contains noindex",
        )
        if conflict:
            evaluation.warnings.append(
                RecommendationWarning(
                    SitemapReasonCode.CONFLICTING_GENERIC_INDEXABILITY.value,
                    "Generic index and noindex evidence conflict; noindex remains authoritative",
                    "combined_indexability",
                )
            )
    else:
        evaluation.add(
            "08_generic_indexability",
            RuleOutcome.PASSED,
            None,
            "No generic noindex directive was observed",
        )
    if any(value.endswith(":noindex") for value in crawler_specific):
        evaluation.warnings.append(
            RecommendationWarning(
                SitemapReasonCode.CRAWLER_SPECIFIC_NOINDEX.value,
                "Crawler-specific noindex evidence is preserved but not applied generically",
                "combined_indexability",
            )
        )
        if policy.crawler_specific_noindex_requires_review:
            evaluation.add(
                "08b_crawler_specific_indexability",
                RuleOutcome.REVIEW,
                SitemapReasonCode.CRAWLER_SPECIFIC_NOINDEX,
                "Policy requires review of crawler-specific noindex evidence",
            )
    return GenericIndexabilitySummary(generic, crawler_specific, conflict)


def _evaluate_configured_exclusions(
    evaluation: _Evaluation,
    configured: tuple[ConfiguredExclusionEvidence, ...],
) -> None:
    if configured:
        evaluation.add(
            "09_configured_exclusions",
            RuleOutcome.HARD_EXCLUSION,
            SitemapReasonCode.CONFIGURED_URL_EXCLUSION,
            "The URL matches one or more accepted crawl exclusion rules",
        )
    else:
        evaluation.add(
            "09_configured_exclusions",
            RuleOutcome.PASSED,
            None,
            "No configured crawl exclusion rule matches",
        )


def _evaluate_canonical(  # noqa: C901 - canonical evidence cases remain explicit and ordered.
    evaluation: _Evaluation,
    record: UrlCrawlRecord,
    policy: RecommendationPolicy,
) -> CanonicalSummary:
    canonical = record.parse_result.canonical if record.parse_result is not None else None
    if canonical is None:
        return CanonicalSummary(
            selected_url=None,
            valid_candidates=(),
            invalid_observation_count=0,
            conflicting=False,
        )
    candidates = tuple(
        dict.fromkeys(
            item.normalized_url
            for item in canonical.observations
            if item.normalized_url is not None
        )
    )
    invalid_count = sum(item.error_code is not None for item in canonical.observations)
    conflicting = len(candidates) > 1
    final_url = record.final_fetched_url or (
        record.fetch_result.final_url if record.fetch_result is not None else record.requested_url
    )
    if canonical.selected_url is not None and _identity(canonical.selected_url) != _identity(
        final_url
    ):
        reasons = [SitemapReasonCode.CANONICAL_POINTS_ELSEWHERE]
        selected_parts = urlsplit(canonical.selected_url)
        final_parts = urlsplit(final_url)
        if selected_parts.hostname != final_parts.hostname:
            reasons.append(SitemapReasonCode.CROSS_HOST_CANONICAL)
        if (
            selected_parts.scheme,
            selected_parts.hostname,
            selected_parts.port,
        ) != (final_parts.scheme, final_parts.hostname, final_parts.port):
            reasons.append(SitemapReasonCode.CROSS_ORIGIN_CANONICAL)
        for reason in reasons:
            evaluation.add(
                "10_canonical_elsewhere",
                RuleOutcome.HARD_EXCLUSION,
                reason,
                "The selected canonical points to a different normalized URL",
                (EvidenceReference("canonical", "html", canonical.selected_url),),
            )
    elif conflicting:
        evaluation.add(
            "11_canonical_quality",
            RuleOutcome.REVIEW,
            SitemapReasonCode.CONFLICTING_CANONICALS,
            "Multiple valid canonical candidates disagree",
        )
    elif (
        invalid_count
        and canonical.selected_url is None
        and policy.invalid_canonical_requires_review
    ):
        evaluation.add(
            "11_canonical_quality",
            RuleOutcome.REVIEW,
            SitemapReasonCode.INVALID_CANONICAL,
            "Canonical observations are invalid and no valid canonical was selected",
        )
    elif not canonical.observations and policy.missing_canonical_requires_review:
        evaluation.add(
            "11_canonical_quality",
            RuleOutcome.REVIEW,
            SitemapReasonCode.MISSING_CANONICAL,
            "Policy requires review when a canonical is absent",
        )
    else:
        evaluation.add(
            "11_canonical_quality",
            RuleOutcome.PASSED,
            None,
            "Canonical evidence does not prevent inclusion",
        )
    if invalid_count:
        evaluation.warnings.append(
            RecommendationWarning(
                SitemapReasonCode.INVALID_CANONICAL.value,
                f"{invalid_count} invalid canonical observation(s) were retained",
                "html_canonical",
            )
        )
    if not canonical.observations:
        evaluation.warnings.append(
            RecommendationWarning(
                SitemapReasonCode.MISSING_CANONICAL.value,
                "No canonical observation was present",
                "html_canonical",
            )
        )
    return CanonicalSummary(canonical.selected_url, candidates, invalid_count, conflicting)


def _evaluate_evidence_quality(
    evaluation: _Evaluation,
    record: UrlCrawlRecord,
    policy: RecommendationPolicy,
) -> None:
    parse = record.parse_result
    recovered = bool(
        parse is not None
        and any(item.code is HtmlWarningCode.PARSER_RECOVERY_USED for item in parse.warnings)
    )
    if recovered and policy.severe_parser_recovery_requires_review:
        evaluation.add(
            "11b_evidence_quality",
            RuleOutcome.REVIEW,
            SitemapReasonCode.SEVERE_PARSER_RECOVERY,
            "The HTML parser required recovery from malformed markup",
        )


def _metadata_warnings(record: UrlCrawlRecord) -> tuple[RecommendationWarning, ...]:
    if record.parse_result is None:
        return ()
    return tuple(
        RecommendationWarning(item.code.value, item.explanation, "html_metadata")
        for item in record.parse_result.warnings
        if item.code.value in METADATA_WARNING_CODES
    )


def _final_state(
    evaluation: _Evaluation,
) -> tuple[RecommendationState, RecommendationDeterminacy, SitemapReasonCode]:
    if evaluation.hard:
        return (
            RecommendationState.EXCLUDE,
            RecommendationDeterminacy.DETERMINATE,
            evaluation.hard[0],
        )
    if evaluation.indeterminate:
        determinacy = (
            RecommendationDeterminacy.BLOCKED_CONFLICTING_EVIDENCE
            if evaluation.indeterminate[0] is SitemapReasonCode.AMBIGUOUS_CONTENT_TYPE
            else RecommendationDeterminacy.BLOCKED_MISSING_EVIDENCE
        )
        return RecommendationState.INDETERMINATE, determinacy, evaluation.indeterminate[0]
    if evaluation.review:
        return (
            RecommendationState.REVIEW,
            RecommendationDeterminacy.DETERMINATE,
            evaluation.review[0],
        )
    return (
        RecommendationState.INCLUDE,
        RecommendationDeterminacy.DETERMINATE,
        SitemapReasonCode.ELIGIBLE_HTML_PAGE,
    )


def _robots_summary(record: UrlCrawlRecord) -> RobotsPermissionSummary:
    permission = record.robots_permission
    return RobotsPermissionSummary(
        permission is not None,
        permission.allowed if permission is not None else None,
        permission.reason_code.value if permission is not None else None,
    )


def _content_type(record: UrlCrawlRecord) -> str | None:
    if record.parse_result is not None and record.parse_result.effective_media_type is not None:
        return record.parse_result.effective_media_type
    return (
        _media_type(record.fetch_result.content_type) if record.fetch_result is not None else None
    )


def _media_type(value: str | None) -> str | None:
    return value.split(";", 1)[0].strip().lower() if value else None


def _identity(value: str | None) -> str:
    if value is None:
        return ""
    try:
        return normalize_url(value).normalized
    except UrlNormalizationError:
        return value


def _safe_url_summary(value: str) -> str:
    try:
        url = normalize_url(value)
    except UrlNormalizationError:
        return "invalid-url"
    return f"{url.origin}{urlsplit(url.normalized).path or '/'}"


def _explanation(state: RecommendationState, reason: SitemapReasonCode) -> str:
    return {
        RecommendationState.INCLUDE: "Available evidence supports XML sitemap inclusion",
        RecommendationState.EXCLUDE: f"A hard exclusion applies: {reason.value}",
        RecommendationState.REVIEW: f"Human review is required: {reason.value}",
        RecommendationState.INDETERMINATE: f"Evidence is insufficient: {reason.value}",
    }[state]


def _with_redirect_target_state(
    recommendation: SitemapRecommendation,
    *,
    target_evaluated: bool | None,
) -> SitemapRecommendation:
    if not recommendation.redirect.is_redirect_source:
        return recommendation
    return replace(
        recommendation,
        redirect=RedirectSummary(
            is_redirect_source=True,
            hop_count=recommendation.redirect.hop_count,
            final_url=recommendation.redirect.final_url,
            target_independently_evaluated=target_evaluated,
        ),
        warnings=(
            recommendation.warnings
            if target_evaluated is not False
            else (
                *recommendation.warnings,
                RecommendationWarning(
                    SitemapReasonCode.REDIRECT_TARGET_NOT_INDEPENDENTLY_EVALUATED.value,
                    "The observed redirect target has no independent crawl record",
                    "redirect_evidence",
                ),
            )
        ),
    )


def _projection(
    recommendations: tuple[SitemapRecommendation, ...],
    duplicate_count: int,
    policy: RecommendationPolicy,
) -> SitemapRecommendationProjection:
    states = Counter(item.state for item in recommendations)
    reasons = Counter(item.primary_reason for item in recommendations)
    warnings = Counter(
        warning.code for item in recommendations for warning in item.metadata_warnings
    )
    return SitemapRecommendationProjection(
        recommendations=recommendations,
        included_url_count=states[RecommendationState.INCLUDE],
        excluded_url_count=states[RecommendationState.EXCLUDE],
        review_count=states[RecommendationState.REVIEW],
        indeterminate_count=states[RecommendationState.INDETERMINATE],
        counts_by_primary_reason=tuple(
            ReasonCount(reason, reasons[reason]) for reason in SitemapReasonCode if reasons[reason]
        ),
        metadata_warning_counts=tuple(
            WarningCount(code, count) for code, count in sorted(warnings.items())
        ),
        duplicate_suppression_count=duplicate_count,
        redirect_source_count=sum(item.redirect.is_redirect_source for item in recommendations),
        canonical_exclusion_count=sum(
            SitemapReasonCode.CANONICAL_POINTS_ELSEWHERE in item.hard_exclusion_reasons
            for item in recommendations
        ),
        noindex_exclusion_count=sum(
            SitemapReasonCode.GENERIC_NOINDEX in item.hard_exclusion_reasons
            for item in recommendations
        ),
        robots_denial_count=sum(
            SitemapReasonCode.ROBOTS_DENIED in item.hard_exclusion_reasons
            for item in recommendations
        ),
        non_html_count=sum(
            SitemapReasonCode.NON_HTML_CONTENT in item.hard_exclusion_reasons
            for item in recommendations
        ),
        non_200_count=sum(
            SitemapReasonCode.NON_200_STATUS in item.hard_exclusion_reasons
            or SitemapReasonCode.MISSING_HTTP_STATUS in item.hard_exclusion_reasons
            for item in recommendations
        ),
        configuration=RecommendationConfigurationSnapshot(
            policy.missing_canonical_requires_review,
            policy.invalid_canonical_requires_review,
            policy.ambiguous_sniffed_html_requires_review,
            policy.crawler_specific_noindex_requires_review,
            policy.severe_parser_recovery_requires_review,
            policy.rule_set_version,
        ),
        rule_set_version=policy.rule_set_version,
    )
