"""Immutable contracts for one bounded, in-memory, single-site crawl."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from musimack_tools.domain.fetching import FetchResult
    from musimack_tools.domain.html import HtmlParseResult
    from musimack_tools.domain.indexability import CombinedIndexabilityEvidence, XRobotsTagEvidence
    from musimack_tools.domain.robots import CrawlPermissionDecision, RobotsOriginRecord
    from musimack_tools.domain.urls import CrawlScopePolicy, NormalizedUrl

_INVALID_UNIQUE_URLS = "maximum unique URLs must be at least 1"
_INVALID_DEPTH = "maximum depth cannot be negative"
_INVALID_DURATION = "maximum duration must be positive"
_INVALID_TOTAL_BYTES = "maximum total fetched bytes must be at least 1"
_INVALID_CONCURRENCY = "maximum concurrent fetches must be at least 1"
_INVALID_QUEUE = "maximum queued URLs must be at least 1"
_INVALID_DELAY = "minimum per-origin delay cannot be negative"


class CrawlState(StrEnum):
    """Stable crawl lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    LIMIT_REACHED = "limit_reached"
    FAILED = "failed"


class FrontierState(StrEnum):
    """Lifecycle state of one normalized crawl key."""

    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class UrlCrawlOutcome(StrEnum):
    """Stable terminal outcome for one URL record."""

    PARSED = "parsed"
    FETCHED = "fetched"
    FETCH_FAILED = "fetch_failed"
    PARSE_SKIPPED = "parse_skipped"
    SKIPPED = "skipped"
    ROBOTS_DENIED = "robots_denied"
    WORKER_FAILED = "worker_failed"


class CrawlErrorCode(StrEnum):
    """Stable orchestration-level error and terminal reason codes."""

    INVALID_CRAWL_REQUEST = "invalid_crawl_request"
    SEED_SCOPE_DENIED = "seed_scope_denied"
    ROBOTS_UNAVAILABLE = "robots_unavailable"
    URL_LIMIT_REACHED = "url_limit_reached"
    DURATION_LIMIT_REACHED = "duration_limit_reached"
    BYTE_LIMIT_REACHED = "byte_limit_reached"
    QUEUE_LIMIT_REACHED = "queue_limit_reached"
    CANCELLED = "cancelled"
    FRONTIER_INVARIANT_VIOLATION = "frontier_invariant_violation"
    WORKER_FAILURE = "worker_failure"
    PROGRESS_OBSERVER_FAILURE = "progress_observer_failure"
    UNEXPECTED_ORCHESTRATION_ERROR = "unexpected_orchestration_error"


class LinkAdmissionReason(StrEnum):
    """Stable reason for admitting or rejecting one discovered link."""

    ADMITTED = "admitted"
    UPDATED_BETTER_DEPTH = "updated_better_depth"
    DUPLICATE_URL = "duplicate_url"
    INVALID_URL = "invalid_url"
    UNSUPPORTED_SCHEME = "unsupported_scheme"
    EMPTY_HREF = "empty_href"
    FRAGMENT_ONLY = "fragment_only"
    SAME_DOCUMENT = "same_document"
    SCOPE_DENIED = "scope_denied"
    DEPTH_EXCEEDED = "depth_exceeded"
    EXCLUDED_BY_RULE = "excluded_by_rule"
    QUERY_URL_DISALLOWED = "query_url_disallowed"
    URL_LIMIT_REACHED = "url_limit_reached"
    QUEUE_LIMIT_REACHED = "queue_limit_reached"
    CRAWL_STOPPING = "crawl_stopping"
    REDIRECT_FINAL_ALREADY_SEEN = "redirect_final_already_seen"
    CANCELLED = "cancelled"
    ROBOTS_DENIED = "robots_denied"
    ROBOTS_UNAVAILABLE = "robots_unavailable"


class ExclusionRuleType(StrEnum):
    """Simple deterministic URL exclusion rule types."""

    EXACT_PATH = "exact_path"
    PATH_PREFIX = "path_prefix"
    QUERY_PARAMETER = "query_parameter"


class LimitKind(StrEnum):
    """Hard crawl resource limits that can terminate admission."""

    URLS = "urls"
    DURATION = "duration"
    BYTES = "bytes"
    QUEUE = "queue"


@dataclass(frozen=True, slots=True)
class CrawlExclusionRule:
    """One explicit deterministic URL exclusion rule."""

    rule_type: ExclusionRuleType
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            message = "crawl exclusion rule values cannot be empty"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class CrawlRequest:
    """One immutable crawl request validated against server hard limits at execution."""

    seed_url: NormalizedUrl
    scope_policy: CrawlScopePolicy
    maximum_unique_urls: int = 5_000
    maximum_depth: int = 10
    maximum_duration_seconds: float = 1_800
    maximum_total_fetched_bytes: int = 500_000_000
    maximum_concurrent_fetches: int = 4
    maximum_queued_urls: int = 10_000
    minimum_per_origin_delay_seconds: float = 0.5
    query_urls_allowed: bool = True
    exclusion_rules: tuple[CrawlExclusionRule, ...] = ()
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        if self.maximum_unique_urls < 1:
            raise ValueError(_INVALID_UNIQUE_URLS)
        if self.maximum_depth < 0:
            raise ValueError(_INVALID_DEPTH)
        if self.maximum_duration_seconds <= 0:
            raise ValueError(_INVALID_DURATION)
        if self.maximum_total_fetched_bytes < 1:
            raise ValueError(_INVALID_TOTAL_BYTES)
        if self.maximum_concurrent_fetches < 1:
            raise ValueError(_INVALID_CONCURRENCY)
        if self.maximum_queued_urls < 1:
            raise ValueError(_INVALID_QUEUE)
        if self.minimum_per_origin_delay_seconds < 0:
            raise ValueError(_INVALID_DELAY)


@dataclass(frozen=True, slots=True)
class CrawlConfigurationSnapshot:
    """Validated effective crawl settings retained with the result."""

    maximum_unique_urls: int
    maximum_depth: int
    maximum_duration_seconds: float
    maximum_total_fetched_bytes: int
    maximum_concurrent_fetches: int
    maximum_queued_urls: int
    minimum_per_origin_delay_seconds: float
    query_urls_allowed: bool
    exclusion_rules: tuple[CrawlExclusionRule, ...]


@dataclass(frozen=True, slots=True)
class FrontierItem:
    """Immutable scheduling view of one pending URL."""

    url: NormalizedUrl
    first_discovered_value: str
    first_referrer: str | None
    referring_urls: tuple[str, ...]
    first_discovered_depth: int
    best_known_depth: int
    discovery_order: int


@dataclass(frozen=True, slots=True)
class LinkDiscoveryEvidence:
    """One document-order link admission decision."""

    source_url: str
    raw_href: str | None
    normalized_url: str | None
    candidate_depth: int
    occurrence_index: int
    nofollow: bool
    admitted: bool
    reason: LinkAdmissionReason


@dataclass(frozen=True, slots=True)
class UrlCrawlRecord:
    """Terminal evidence for one attempted or frontier-skipped crawl key."""

    requested_url: str
    first_discovered_value: str
    first_referrer: str | None
    referring_urls: tuple[str, ...]
    discovery_depth: int
    best_known_depth: int
    discovery_order: int
    frontier_state: FrontierState
    outcome: UrlCrawlOutcome
    fetch_result: FetchResult | None
    parse_result: HtmlParseResult | None
    final_fetched_url: str | None
    discovered_link_count: int
    admitted_link_count: int
    rejected_link_count: int
    skip_reason: LinkAdmissionReason | None
    started_at_seconds: float | None
    ended_at_seconds: float
    accepted_response_bytes: int
    robots_permission: CrawlPermissionDecision | None = None
    x_robots_tag: XRobotsTagEvidence | None = None
    indexability_evidence: CombinedIndexabilityEvidence | None = None
    robots_warning_count: int = 0
    indexability_warning_count: int = 0


@dataclass(frozen=True, slots=True)
class CrawlCounters:
    """Derived crawl totals with stable meanings."""

    unique_urls_discovered: int = 0
    urls_queued: int = 0
    urls_fetched: int = 0
    fetch_successes: int = 0
    fetch_failures: int = 0
    html_pages_parsed: int = 0
    non_html_responses: int = 0
    parser_skips: int = 0
    urls_excluded_by_scope: int = 0
    urls_excluded_by_depth: int = 0
    urls_excluded_by_rule: int = 0
    duplicate_discoveries: int = 0
    redirect_responses: int = 0
    total_links_observed: int = 0
    links_admitted: int = 0
    links_rejected: int = 0
    robots_origins_evaluated: int = 0
    robots_fetches: int = 0
    robots_cache_hits: int = 0
    robots_unavailable_origins: int = 0
    robots_denied_urls: int = 0
    robots_warnings: int = 0
    robots_bytes: int = 0
    indexability_warnings: int = 0


@dataclass(frozen=True, slots=True)
class LimitEvent:
    """Evidence that a configured resource bound affected the crawl."""

    kind: LimitKind
    code: CrawlErrorCode
    explanation: str
    configured_limit: int | float
    observed_value: int | float
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class CrawlError:
    """Controlled crawl-level error evidence."""

    code: CrawlErrorCode
    explanation: str
    url: str | None = None
    internal_exception_type: str | None = None


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    """Immutable progress view emitted after meaningful state changes."""

    state: CrawlState
    counters: CrawlCounters
    queue_size: int
    active_count: int
    current_depth: int | None
    total_accepted_bytes: int
    elapsed_seconds: float
    recent_error_code: CrawlErrorCode | None = None


@dataclass(frozen=True, slots=True)
class CancellationEvidence:
    """Evidence that cooperative cancellation affected the crawl."""

    requested: bool
    queued_urls_skipped: int
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class CrawlResult:
    """Complete immutable in-memory result for one bounded crawl."""

    seed_url: str
    scope_policy: CrawlScopePolicy
    started_at_seconds: float
    ended_at_seconds: float
    duration_seconds: float
    state: CrawlState
    url_records: tuple[UrlCrawlRecord, ...]
    discoveries: tuple[LinkDiscoveryEvidence, ...]
    counters: CrawlCounters
    limit_events: tuple[LimitEvent, ...]
    errors: tuple[CrawlError, ...]
    cancellation: CancellationEvidence | None
    total_accepted_bytes: int
    maximum_observed_queue_size: int
    maximum_active_worker_count: int
    configuration: CrawlConfigurationSnapshot
    robots_origins: tuple[RobotsOriginRecord, ...] = ()
