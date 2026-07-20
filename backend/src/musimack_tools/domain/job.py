"""Immutable contracts for process-local crawl-run jobs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from musimack_tools.domain.run import CrawlRunRequest, CrawlRunResult, RunLifecycle, RunStage
    from musimack_tools.domain.run_progress import RunProgressEvent, RunProgressSnapshot
    from musimack_tools.domain.run_summary import RunSummaryArtifact

MAXIMUM_RECOMMENDATION_PAGE_SIZE = 50_000


def normalize_recommendation_reason_filter(value: str | None) -> str | None:
    """Normalize displayed reason text and stored reason codes to one safe search term."""
    if value is None:
        return None
    normalized = "_".join(value.casefold().strip().split())
    return normalized or None


class JobState(StrEnum):
    ACCEPTED = "accepted"
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    PARTIALLY_COMPLETED = "partially_completed"
    EVICTED = "evicted"

    @property
    def terminal(self) -> bool:
        return self in {
            JobState.CANCELLED,
            JobState.COMPLETED,
            JobState.COMPLETED_WITH_WARNINGS,
            JobState.FAILED,
            JobState.PARTIALLY_COMPLETED,
            JobState.EVICTED,
        }


class JobSubmissionOutcome(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE_RETURNED = "duplicate_returned"
    REJECTED = "rejected"


class JobSubmissionFailureCode(StrEnum):
    REGISTRY_CLOSED = "registry_closed"
    INVALID_REQUEST = "invalid_request"
    ACTIVE_DUPLICATE = "active_duplicate"
    QUEUE_CAPACITY_REACHED = "queue_capacity_reached"
    COORDINATOR_UNAVAILABLE = "coordinator_unavailable"


class JobLookupOutcome(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"


class JobCancellationOutcome(StrEnum):
    REQUESTED = "requested"
    CANCELLED_WHILE_QUEUED = "cancelled_while_queued"
    ALREADY_REQUESTED = "already_requested"
    ALREADY_TERMINAL = "already_terminal"
    NOT_FOUND = "not_found"
    REGISTRY_CLOSED = "registry_closed"


class JobWaitOutcome(StrEnum):
    COMPLETED = "completed"
    NOT_FOUND = "not_found"
    TIMED_OUT = "timed_out"


class JobCoordinationFailureCode(StrEnum):
    RUN_SERVICE_FAILED = "run_service_failed_unexpectedly"
    REGISTRY_TRANSITION_INVALID = "registry_transition_invalid"
    PROGRESS_RECORDING_FAILED = "progress_recording_failed"
    COMPLETION_RECORDING_FAILED = "completion_recording_failed"
    SHUTDOWN_INCOMPLETE = "shutdown_incomplete"


@dataclass(frozen=True, slots=True)
class JobCoordinationWarning:
    code: str
    explanation: str


@dataclass(frozen=True, slots=True)
class JobCoordinationFailure:
    code: JobCoordinationFailureCode
    explanation: str
    internal_exception_type: str | None = None


@dataclass(frozen=True, slots=True)
class JobSubmissionRequest:
    run_request: CrawlRunRequest


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    job_id: str
    run_id: str
    attempt_number: int
    state: JobState
    queue_position: int | None
    run_lifecycle: RunLifecycle | None
    active_stage: RunStage | None
    latest_progress: RunProgressSnapshot | None
    warning_count: int
    failure_count: int
    cancellation_requested: bool
    final_result_available: bool
    summary_artifact_count: int
    terminal: bool
    registry_version: str


@dataclass(frozen=True, slots=True)
class JobSubmissionResult:
    outcome: JobSubmissionOutcome
    snapshot: JobSnapshot | None
    failure_code: JobSubmissionFailureCode | None
    explanation: str
    registry_version: str


@dataclass(frozen=True, slots=True)
class JobLookupResult:
    outcome: JobLookupOutcome
    snapshot: JobSnapshot | None


@dataclass(frozen=True, slots=True)
class JobProgressView:
    outcome: JobLookupOutcome
    latest: RunProgressEvent | None
    history: tuple[RunProgressEvent, ...]
    history_truncated: bool


@dataclass(frozen=True, slots=True)
class DurableResultProjection:
    """Restart-safe bounded result data shared by separate web and worker processes."""

    run_lifecycle: str
    stage_states: tuple[tuple[str, str], ...]
    crawl_counts: tuple[tuple[str, int], ...]
    crawl_error_codes: tuple[str, ...]
    recommendation_counts: tuple[tuple[str, int], ...]
    xml_document_count: int | None
    xml_entry_count: int | None
    publication_state: str | None
    published_file_count: int
    publication_filenames: tuple[str, ...]
    manifest_sha256: str | None
    summary_hashes: tuple[tuple[str, str], ...]
    warning_codes: tuple[str, ...]
    failure_codes: tuple[str, ...]
    downstream_versions: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class DurableRecommendation:
    """One bounded URL recommendation retained independently of worker memory."""

    sequence: int
    url: str
    requested_url: str
    final_url: str | None
    state: str
    determinacy: str
    primary_reason: str
    explanation: str
    http_status: int | None
    content_type: str | None
    fetch_failure_code: str | None
    canonical_url: str | None
    canonical_conflicting: bool
    redirect_source: bool
    redirect_hops: int
    redirect_final_url: str | None
    robots_available: bool
    robots_allowed: bool | None
    robots_reason_code: str | None
    generic_directives: tuple[str, ...]
    crawler_specific_directives: tuple[str, ...]
    indexability_conflict: bool
    configured_exclusions: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class RecommendationRuleDetail:
    rule_id: str
    outcome: str
    reason_code: str | None
    explanation: str


@dataclass(frozen=True, slots=True)
class RecommendationWarningDetail:
    code: str
    explanation: str
    source: str


@dataclass(frozen=True, slots=True)
class RecommendationRedirectDetail:
    sequence: int
    source_url: str
    target_url: str | None
    status_code: int
    terminal: bool
    loop: bool
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class RecommendationDirectiveGroup:
    agent: str
    directives: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DurableRecommendationDetail:
    recommendation: DurableRecommendation
    reason_codes: tuple[str, ...]
    rule_evidence: tuple[RecommendationRuleDetail, ...]
    warning_details: tuple[RecommendationWarningDetail, ...]
    metadata_warning_codes: tuple[str, ...]
    evidence_id: str | None
    crawl_depth: int | None
    fetch_outcome: str | None
    evidence_state: str | None
    page_failure_code: str | None
    title_presence: str | None
    title: str | None
    description_presence: str | None
    meta_description: str | None
    canonical_presence: str | None
    meta_robots: tuple[RecommendationDirectiveGroup, ...]
    x_robots_tag: tuple[RecommendationDirectiveGroup, ...]
    redirect_chain: tuple[RecommendationRedirectDetail, ...]
    redirect_truncated: bool | None
    redirect_loop: bool | None
    sitemap_membership: bool | None


@dataclass(frozen=True, slots=True)
class JobRecommendationDetail:
    outcome: JobLookupOutcome
    details_available: bool
    item: DurableRecommendationDetail | None


@dataclass(frozen=True, slots=True)
class JobRecommendationPage:
    outcome: JobLookupOutcome
    details_available: bool
    job_id: str | None
    run_id: str | None
    offset: int
    limit: int
    total: int
    items: tuple[DurableRecommendation, ...]
    rule_set_version: str | None


@dataclass(frozen=True, slots=True)
class JobResultView:
    outcome: JobLookupOutcome
    snapshot: JobSnapshot | None
    full_result: CrawlRunResult | None
    summaries: tuple[RunSummaryArtifact, ...]
    coordination_warnings: tuple[JobCoordinationWarning, ...] = ()
    coordination_failure: JobCoordinationFailure | None = None
    durable_projection: DurableResultProjection | None = None


@dataclass(frozen=True, slots=True)
class JobCancellationResult:
    outcome: JobCancellationOutcome
    snapshot: JobSnapshot | None
    explanation: str


@dataclass(frozen=True, slots=True)
class JobWaitResult:
    outcome: JobWaitOutcome
    result: JobResultView | None
