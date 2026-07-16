"""Immutable configuration and aggregate records for the in-memory job registry."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

CRAWL_JOB_REGISTRY_VERSION = "crawl-job-registry-v1"


class RegistryState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    SHUTTING_DOWN = "shutting_down"
    CLOSED = "closed"


class DuplicateSubmissionPolicy(StrEnum):
    ALLOW = "allow"
    REJECT_ACTIVE_DUPLICATE = "reject_active_duplicate"
    RETURN_ACTIVE_DUPLICATE = "return_active_duplicate"


class TerminalRetentionPolicy(StrEnum):
    OLDEST_TERMINAL_FIRST = "oldest_terminal_first"


class PayloadRetentionPolicy(StrEnum):
    FULL_RESULT = "full_result"
    SUMMARY_ONLY = "summary_only"
    METADATA_ONLY = "metadata_only"


class ShutdownPolicy(StrEnum):
    CANCEL_QUEUED_AND_REQUEST_ACTIVE = "cancel_queued_and_request_active"
    WAIT_FOR_ACTIVE = "wait_for_active"


class EvictionReason(StrEnum):
    TERMINAL_RETENTION_LIMIT = "terminal_retention_limit"
    TERMINAL_RETENTION_DISABLED = "terminal_retention_disabled"


@dataclass(frozen=True, slots=True)
class JobRegistryConfiguration:
    maximum_concurrent_jobs: int = 2
    maximum_queued_jobs: int = 10
    maximum_retained_terminal_jobs: int = 100
    duplicate_policy: DuplicateSubmissionPolicy = DuplicateSubmissionPolicy.REJECT_ACTIVE_DUPLICATE
    terminal_retention_policy: TerminalRetentionPolicy = (
        TerminalRetentionPolicy.OLDEST_TERMINAL_FIRST
    )
    retain_completed_result_payloads: bool = True
    payload_retention_policy: PayloadRetentionPolicy = PayloadRetentionPolicy.FULL_RESULT
    retain_progress_history: bool = False
    maximum_retained_progress_events: int = 100
    shutdown_policy: ShutdownPolicy = ShutdownPolicy.CANCEL_QUEUED_AND_REQUEST_ACTIVE
    registry_version: str = CRAWL_JOB_REGISTRY_VERSION

    def __post_init__(self) -> None:
        if self.maximum_concurrent_jobs < 1:
            message = "maximum concurrent jobs must be positive"
            raise ValueError(message)
        if self.maximum_queued_jobs < 0:
            message = "maximum queued jobs cannot be negative"
            raise ValueError(message)
        if self.maximum_retained_terminal_jobs < 0:
            message = "maximum retained terminal jobs cannot be negative"
            raise ValueError(message)
        if self.retain_progress_history and self.maximum_retained_progress_events < 1:
            message = "progress history limit must be positive when history is retained"
            raise ValueError(message)
        if self.registry_version != CRAWL_JOB_REGISTRY_VERSION:
            message = "unsupported job registry version"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class JobRegistryCounters:
    submitted_jobs: int
    accepted_jobs: int
    rejected_jobs: int
    active_jobs: int
    queued_jobs: int
    terminal_jobs_retained: int
    completed_jobs: int
    cancelled_jobs: int
    failed_jobs: int
    partially_completed_jobs: int
    evicted_jobs: int
    duplicate_rejections: int
    queue_capacity_rejections: int


@dataclass(frozen=True, slots=True)
class JobRegistrySnapshot:
    state: RegistryState
    configuration: JobRegistryConfiguration
    counters: JobRegistryCounters
    active_job_ids: tuple[str, ...]
    queued_job_ids: tuple[str, ...]
    retained_terminal_job_ids: tuple[str, ...]
    registry_version: str = CRAWL_JOB_REGISTRY_VERSION


@dataclass(frozen=True, slots=True)
class JobShutdownResult:
    state: RegistryState
    queued_jobs_cancelled: int
    active_cancellations_requested: int
    terminal_jobs_retained: int
    orphan_task_count: int
    repeated: bool
    registry_version: str = CRAWL_JOB_REGISTRY_VERSION
