"""Immutable contracts for process-local crawl-run jobs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from musimack_tools.domain.run import CrawlRunRequest, CrawlRunResult, RunLifecycle, RunStage
    from musimack_tools.domain.run_progress import RunProgressEvent, RunProgressSnapshot
    from musimack_tools.domain.run_summary import RunSummaryArtifact


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
class JobResultView:
    outcome: JobLookupOutcome
    snapshot: JobSnapshot | None
    full_result: CrawlRunResult | None
    summaries: tuple[RunSummaryArtifact, ...]
    coordination_warnings: tuple[JobCoordinationWarning, ...] = ()
    coordination_failure: JobCoordinationFailure | None = None


@dataclass(frozen=True, slots=True)
class JobCancellationResult:
    outcome: JobCancellationOutcome
    snapshot: JobSnapshot | None
    explanation: str


@dataclass(frozen=True, slots=True)
class JobWaitResult:
    outcome: JobWaitOutcome
    result: JobResultView | None
