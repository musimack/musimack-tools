"""Immutable sitemap eligibility recommendation and projection contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

SITEMAP_RULE_SET_VERSION = "sitemap-eligibility-v1"


class RecommendationState(StrEnum):
    """Stable final recommendation states."""

    INCLUDE = "include"
    EXCLUDE = "exclude"
    REVIEW = "review"
    INDETERMINATE = "indeterminate"


class RecommendationDeterminacy(StrEnum):
    """Whether sufficient coherent evidence supports the recommendation."""

    DETERMINATE = "determinate"
    BLOCKED_MISSING_EVIDENCE = "blocked_missing_evidence"
    BLOCKED_CONFLICTING_EVIDENCE = "blocked_conflicting_evidence"


class RuleOutcome(StrEnum):
    """Stable result of one ordered recommendation rule."""

    PASSED = "passed"
    HARD_EXCLUSION = "hard_exclusion"
    REVIEW = "review"
    INDETERMINATE = "indeterminate"


class SitemapReasonCode(StrEnum):
    """Stable include, exclusion, review, and evidence reason codes."""

    ELIGIBLE_HTML_PAGE = "eligible_html_page"
    INVALID_URL = "invalid_url"
    UNSUPPORTED_SCHEME = "unsupported_scheme"
    OUTSIDE_SCOPE = "outside_scope"
    DISALLOWED_PORT = "disallowed_port"
    CONFIGURED_URL_EXCLUSION = "configured_url_exclusion"
    NOT_FETCHED = "not_fetched"
    FETCH_FAILED = "fetch_failed"
    REDIRECT_FAILED = "redirect_failed"
    REDIRECT_SOURCE = "redirect_source"
    NON_200_STATUS = "non_200_status"
    MISSING_HTTP_STATUS = "missing_http_status"
    RESPONSE_TOO_LARGE = "response_too_large"
    NON_HTML_CONTENT = "non_html_content"
    ROBOTS_DENIED = "robots_denied"
    GENERIC_NOINDEX = "generic_noindex"
    CONFLICTING_GENERIC_INDEXABILITY = "conflicting_generic_indexability"
    CANONICAL_POINTS_ELSEWHERE = "canonical_points_elsewhere"
    CROSS_HOST_CANONICAL = "cross_host_canonical"
    CROSS_ORIGIN_CANONICAL = "cross_origin_canonical"
    CONFLICTING_CANONICALS = "conflicting_canonicals"
    INVALID_CANONICAL = "invalid_canonical"
    MISSING_CANONICAL = "missing_canonical"
    MISSING_REQUIRED_EVIDENCE = "missing_required_evidence"
    AMBIGUOUS_CONTENT_TYPE = "ambiguous_content_type"
    REDIRECT_TARGET_NOT_INDEPENDENTLY_EVALUATED = "redirect_target_not_independently_evaluated"
    SEVERE_PARSER_RECOVERY = "severe_parser_recovery"
    CRAWLER_SPECIFIC_NOINDEX = "crawler_specific_noindex"


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """One bounded reference to retained crawl evidence."""

    category: str
    source: str
    value: str | None = None


@dataclass(frozen=True, slots=True)
class RuleResult:
    """One ordered rule evaluation and its controlled explanation."""

    rule_id: str
    outcome: RuleOutcome
    reason_code: SitemapReasonCode | None
    explanation: str
    evidence: tuple[EvidenceReference, ...] = ()


@dataclass(frozen=True, slots=True)
class RecommendationWarning:
    """One reviewable warning that does not necessarily change final state."""

    code: str
    explanation: str
    source: str


@dataclass(frozen=True, slots=True)
class RobotsPermissionSummary:
    """Bounded robots permission evidence used by a recommendation."""

    available: bool
    allowed: bool | None
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class GenericIndexabilitySummary:
    """Generic directive evidence; crawler-specific directives remain separate."""

    generic_directives: tuple[str, ...]
    crawler_specific_directives: tuple[str, ...]
    generic_index_conflict: bool


@dataclass(frozen=True, slots=True)
class CanonicalSummary:
    """Bounded canonical evidence without raw markup."""

    selected_url: str | None
    valid_candidates: tuple[str, ...]
    invalid_observation_count: int
    conflicting: bool


@dataclass(frozen=True, slots=True)
class RedirectSummary:
    """Bounded redirect evidence used by a recommendation."""

    is_redirect_source: bool
    hop_count: int
    final_url: str | None
    target_independently_evaluated: bool | None


@dataclass(frozen=True, slots=True)
class ConfiguredExclusionEvidence:
    """One accepted crawl exclusion rule that matched the evaluated URL."""

    rule_type: str
    value: str


@dataclass(frozen=True, slots=True)
class SitemapRecommendation:
    """Complete explainable recommendation for one normalized URL identity."""

    evaluated_url: str
    requested_url: str
    final_url: str | None
    state: RecommendationState
    determinacy: RecommendationDeterminacy
    primary_reason: SitemapReasonCode
    hard_exclusion_reasons: tuple[SitemapReasonCode, ...]
    review_reasons: tuple[SitemapReasonCode, ...]
    warnings: tuple[RecommendationWarning, ...]
    metadata_warnings: tuple[RecommendationWarning, ...]
    fetch_failure_code: str | None
    http_status: int | None
    content_type: str | None
    robots: RobotsPermissionSummary
    indexability: GenericIndexabilitySummary
    canonical: CanonicalSummary
    redirect: RedirectSummary
    configured_exclusions: tuple[ConfiguredExclusionEvidence, ...]
    rule_results: tuple[RuleResult, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class RecommendationPolicy:
    """Typed conservative policy for the first recommendation rule set."""

    missing_canonical_requires_review: bool = False
    invalid_canonical_requires_review: bool = True
    ambiguous_sniffed_html_requires_review: bool = False
    crawler_specific_noindex_requires_review: bool = False
    severe_parser_recovery_requires_review: bool = True
    rule_set_version: str = SITEMAP_RULE_SET_VERSION

    def __post_init__(self) -> None:
        if not self.rule_set_version.strip():
            message = "recommendation rule-set version cannot be empty"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class RecommendationConfigurationSnapshot:
    """Effective immutable policy retained with one projection."""

    missing_canonical_requires_review: bool
    invalid_canonical_requires_review: bool
    ambiguous_sniffed_html_requires_review: bool
    crawler_specific_noindex_requires_review: bool
    severe_parser_recovery_requires_review: bool
    rule_set_version: str


@dataclass(frozen=True, slots=True)
class ReasonCount:
    """Deterministically ordered count for one primary reason."""

    reason: SitemapReasonCode
    count: int


@dataclass(frozen=True, slots=True)
class WarningCount:
    """Deterministically ordered metadata warning count."""

    warning_code: str
    count: int


@dataclass(frozen=True, slots=True)
class SitemapRecommendationProjection:
    """Immutable crawl-level recommendation projection in crawl evidence order."""

    recommendations: tuple[SitemapRecommendation, ...]
    included_url_count: int
    excluded_url_count: int
    review_count: int
    indeterminate_count: int
    counts_by_primary_reason: tuple[ReasonCount, ...]
    metadata_warning_counts: tuple[WarningCount, ...]
    duplicate_suppression_count: int
    redirect_source_count: int
    canonical_exclusion_count: int
    noindex_exclusion_count: int
    robots_denial_count: int
    non_html_count: int
    non_200_count: int
    configuration: RecommendationConfigurationSnapshot
    rule_set_version: str
