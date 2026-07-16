"""Immutable contracts for single-machine durable job execution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

DURABLE_EXECUTION_VERSION = "seo-toolkit-durable-execution-v1"
WORKER_PROTOCOL_VERSION = "seo-toolkit-worker-protocol-v1"
_WORKER_ID = re.compile(r"worker-[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?\Z")
_INVALID_WORKER_ID = "worker ID must use the bounded worker-<safe-label> format"
_UNSUPPORTED_DURABLE_VERSION = "unsupported durable execution version"
_UNSUPPORTED_WORKER_VERSION = "unsupported worker protocol version"
_MODE_MISMATCH = "durable enabled state and scheduler mode must agree"
_WORKER_CONFIGURATION_REQUIRED = "an explicit worker ID and durable mode are required"
_POSITIVE_BOUNDS = "durable execution bounds must be positive"
_HEARTBEAT_BOUND = "heartbeat interval must be less than lease duration"
_STALE_BOUND = "stale threshold must be at least the lease duration"
_CLAIM_BOUND = "claim batch cannot exceed worker concurrency"
_RETRY_BOUND = "base retry delay cannot exceed the maximum delay"
_RETRY_NUMBER = "retry number must be positive"
_UTC_REQUIRED = "durable timestamps must be timezone-aware UTC values"


class SchedulerMode(StrEnum):
    IN_MEMORY = "in_memory"
    DURABLE = "durable"


class WorkerState(StrEnum):
    STARTING = "starting"
    READY = "ready"
    DRAINING = "draining"
    STOPPED = "stopped"
    FAILED = "failed"
    STALE = "stale"

    @property
    def terminal(self) -> bool:
        return self in {WorkerState.STOPPED, WorkerState.FAILED, WorkerState.STALE}


class DurableJobState(StrEnum):
    ACCEPTED = "accepted"
    QUEUED = "queued"
    CLAIMED = "claimed"
    STARTING = "starting"
    RUNNING = "running"
    CANCELLING = "cancelling"
    RETRY_WAIT = "retry_wait"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    PARTIALLY_COMPLETED = "partially_completed"

    @property
    def terminal(self) -> bool:
        return self in {
            DurableJobState.CANCELLED,
            DurableJobState.COMPLETED,
            DurableJobState.COMPLETED_WITH_WARNINGS,
            DurableJobState.FAILED,
            DurableJobState.PARTIALLY_COMPLETED,
        }


class RetryPolicy(StrEnum):
    NEVER = "never"
    RETRY_TRANSIENT = "retry_transient"
    RETRY_SELECTED = "retry_selected"


class RetryDelaySchedule(StrEnum):
    FIXED = "fixed"
    LINEAR = "linear"


class RetryDecision(StrEnum):
    RETRY = "retry"
    DO_NOT_RETRY = "do_not_retry"
    CANCEL = "cancel"
    TERMINAL = "terminal"


class OrphanedLeasePolicy(StrEnum):
    RECOVER = "recover"
    FAIL = "fail"


class WorkerShutdownPolicy(StrEnum):
    DRAIN_ACTIVE_AND_STOP_CLAIMING = "drain_active_and_stop_claiming"
    REQUEST_ACTIVE_CANCELLATION = "request_active_cancellation"


class LeaseOutcome(StrEnum):
    ACCEPTED = "accepted"
    NOT_FOUND = "not_found"
    WRONG_WORKER = "wrong_worker"
    WRONG_TOKEN = "wrong_token"  # noqa: S105 - stable outcome code, not a credential.
    STALE_GENERATION = "stale_generation"
    RELEASED = "released"
    EXPIRED = "expired"


class DurableFailureCode(StrEnum):
    PERSISTENCE_REQUIRED = "durable_persistence_required"
    MIGRATION_REQUIRED = "durable_migration_required"
    WORKER_ID_REQUIRED = "worker_id_required"
    WORKER_PROTOCOL_MISMATCH = "worker_protocol_mismatch"
    CLAIM_FAILED = "durable_claim_failed"
    HEARTBEAT_FAILED = "worker_heartbeat_failed"
    LEASE_NOT_FOUND = "worker_lease_not_found"
    LEASE_WRONG_WORKER = "worker_lease_wrong_worker"
    LEASE_WRONG_TOKEN = "worker_lease_wrong_token"  # noqa: S105 - stable failure code.
    LEASE_STALE_GENERATION = "worker_lease_stale_generation"
    LEASE_RELEASED = "worker_lease_released"
    LEASE_EXPIRED = "worker_lease_expired"
    EXECUTION_FAILED = "durable_execution_failed"
    TERMINAL_PERSISTENCE_FAILED = "durable_terminal_persistence_failed"
    CANCELLATION_REQUESTED = "durable_cancellation_requested"
    WORKER_STALE = "worker_stale"
    RECOVERY_FAILED = "durable_recovery_failed"


@dataclass(frozen=True, slots=True)
class WorkerIdentity:
    value: str

    def __post_init__(self) -> None:
        if not _WORKER_ID.fullmatch(self.value):
            raise ValueError(_INVALID_WORKER_ID)


@dataclass(frozen=True, slots=True)
class DurableExecutionConfiguration:
    enabled: bool = False
    worker_enabled: bool = False
    worker_id: WorkerIdentity | None = None
    scheduler_mode: SchedulerMode = SchedulerMode.IN_MEMORY
    maximum_concurrent_claimed_jobs: int = 1
    poll_interval_seconds: float = 1.0
    lease_duration_seconds: float = 30.0
    heartbeat_interval_seconds: float = 10.0
    stale_after_seconds: float = 45.0
    maximum_claim_batch: int = 1
    retry_policy: RetryPolicy = RetryPolicy.NEVER
    retry_delay_schedule: RetryDelaySchedule = RetryDelaySchedule.FIXED
    retry_delay_seconds: float = 5.0
    maximum_retry_delay_seconds: float = 60.0
    maximum_attempts: int = 3
    retryable_failure_codes: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "database_locked",
                "temporary_network_failure",
                "worker_lease_expired",
                "internal_service_temporarily_unavailable",
            }
        )
    )
    shutdown_grace_period_seconds: float = 30.0
    startup_stale_job_recovery: bool = True
    orphaned_lease_policy: OrphanedLeasePolicy = OrphanedLeasePolicy.RECOVER
    shutdown_policy: WorkerShutdownPolicy = WorkerShutdownPolicy.DRAIN_ACTIVE_AND_STOP_CLAIMING
    maximum_consecutive_heartbeat_failures: int = 3
    durable_execution_version: str = DURABLE_EXECUTION_VERSION
    worker_protocol_version: str = WORKER_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if self.durable_execution_version != DURABLE_EXECUTION_VERSION:
            raise ValueError(_UNSUPPORTED_DURABLE_VERSION)
        if self.worker_protocol_version != WORKER_PROTOCOL_VERSION:
            raise ValueError(_UNSUPPORTED_WORKER_VERSION)
        if self.enabled != (self.scheduler_mode is SchedulerMode.DURABLE):
            raise ValueError(_MODE_MISMATCH)
        if self.worker_enabled and (not self.enabled or self.worker_id is None):
            raise ValueError(_WORKER_CONFIGURATION_REQUIRED)
        positive = (
            self.maximum_concurrent_claimed_jobs,
            self.poll_interval_seconds,
            self.lease_duration_seconds,
            self.heartbeat_interval_seconds,
            self.stale_after_seconds,
            self.maximum_claim_batch,
            self.retry_delay_seconds,
            self.maximum_retry_delay_seconds,
            self.maximum_attempts,
            self.shutdown_grace_period_seconds,
            self.maximum_consecutive_heartbeat_failures,
        )
        if any(value <= 0 for value in positive):
            raise ValueError(_POSITIVE_BOUNDS)
        if self.heartbeat_interval_seconds >= self.lease_duration_seconds:
            raise ValueError(_HEARTBEAT_BOUND)
        if self.stale_after_seconds < self.lease_duration_seconds:
            raise ValueError(_STALE_BOUND)
        if self.maximum_claim_batch > self.maximum_concurrent_claimed_jobs:
            raise ValueError(_CLAIM_BOUND)
        if self.retry_delay_seconds > self.maximum_retry_delay_seconds:
            raise ValueError(_RETRY_BOUND)

    def retry_delay(self, retry_number: int) -> timedelta:
        if retry_number < 1:
            raise ValueError(_RETRY_NUMBER)
        multiplier = retry_number if self.retry_delay_schedule is RetryDelaySchedule.LINEAR else 1
        seconds = min(self.retry_delay_seconds * multiplier, self.maximum_retry_delay_seconds)
        return timedelta(seconds=seconds)


@dataclass(frozen=True, slots=True)
class DurableClaim:
    job_id: str
    run_id: str
    submission_attempt: int
    execution_number: int
    worker_id: str
    lease_token: str
    lease_generation: int
    acquired_sequence: int
    expires_at: datetime
    request_json: str
    durable_execution_version: str = DURABLE_EXECUTION_VERSION
    worker_protocol_version: str = WORKER_PROTOCOL_VERSION


@dataclass(frozen=True, slots=True)
class DurableJobStatus:
    job_id: str
    run_id: str
    submission_attempt: int
    state: DurableJobState
    queue_position: int | None
    retry_count: int
    maximum_attempts: int
    cancellation_requested: bool
    latest_progress_sequence: int | None
    final_result_available: bool
    terminal: bool
    last_failure_code: str | None
    durable_execution_version: str = DURABLE_EXECUTION_VERSION


@dataclass(frozen=True, slots=True)
class LeaseOperationResult:
    outcome: LeaseOutcome
    failure_code: DurableFailureCode | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RetryEvaluation:
    decision: RetryDecision
    retryable: bool
    next_eligible_at: datetime | None
    explanation: str


@dataclass(frozen=True, slots=True)
class DurableRecoveryReport:
    stale_workers: int
    stale_leases: int
    jobs_retried: int
    jobs_cancelled: int
    jobs_failed: int
    recovered_job_ids: tuple[str, ...]
    recovery_complete: bool
    durable_execution_version: str = DURABLE_EXECUTION_VERSION
    worker_protocol_version: str = WORKER_PROTOCOL_VERSION


@dataclass(frozen=True, slots=True)
class WorkerStartupReport:
    worker_id: str
    registered: bool
    recovery: DurableRecoveryReport
    polling_ready: bool
    durable_execution_version: str = DURABLE_EXECUTION_VERSION
    worker_protocol_version: str = WORKER_PROTOCOL_VERSION


@dataclass(frozen=True, slots=True)
class WorkerShutdownReport:
    worker_id: str
    active_jobs_completed: int
    cancellations_requested: int
    leases_released: int
    orphan_tasks: int
    repeated: bool
    final_state: WorkerState


@dataclass(frozen=True, slots=True)
class DurableDiagnostics:
    enabled: bool
    worker_enabled: bool
    worker_registered: bool
    worker_state: WorkerState | None
    queue_depth: int
    claimable_jobs: int
    claimed_jobs: int
    retry_wait_jobs: int
    stale_workers: int
    stale_leases: int
    heartbeat_healthy: bool
    persistence_ready: bool
    migration_current: bool
    recovery_complete: bool
    cancellation_backlog: int
    lease_expiration_count: int
    retry_count: int
    durable_execution_version: str = DURABLE_EXECUTION_VERSION
    worker_protocol_version: str = WORKER_PROTOCOL_VERSION


def utc_now() -> datetime:
    return datetime.now(UTC)


def require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(_UTC_REQUIRED)
    return value.astimezone(UTC)
