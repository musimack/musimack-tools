"""SQLite-backed durable queue, lease, heartbeat, cancellation, and recovery repository."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from logging import getLogger
from typing import TYPE_CHECKING

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from musimack_tools.domain.durable_execution import (
    DURABLE_EXECUTION_VERSION,
    WORKER_PROTOCOL_VERSION,
    DurableClaim,
    DurableDiagnostics,
    DurableExecutionConfiguration,
    DurableFailureCode,
    DurableJobState,
    DurableJobStatus,
    DurableRecoveryReport,
    LeaseOperationResult,
    LeaseOutcome,
    OrphanedLeasePolicy,
    RetryDecision,
    WorkerIdentity,
    WorkerState,
    require_aware_utc,
    utc_now,
)
from musimack_tools.domain.job import (
    JobCancellationOutcome,
    JobCancellationResult,
    JobLookupOutcome,
    JobLookupResult,
    JobProgressView,
    JobResultView,
    JobSnapshot,
    JobState,
    JobSubmissionFailureCode,
    JobSubmissionOutcome,
    JobSubmissionRequest,
    JobSubmissionResult,
)
from musimack_tools.domain.job_registry import (
    CRAWL_JOB_REGISTRY_VERSION,
    JobRegistryConfiguration,
    JobRegistryCounters,
    JobRegistrySnapshot,
    RegistryState,
)
from musimack_tools.domain.persistence import PersistenceReadinessState
from musimack_tools.domain.run import CrawlRunResult, RunLifecycle, RunStage, RunStageState
from musimack_tools.domain.run_progress import RunEventCode, RunProgressEvent, RunProgressSnapshot
from musimack_tools.durable.retry import classify_retry
from musimack_tools.durable.serialization import deserialize_run_request, serialize_run_request
from musimack_tools.jobs.identity import job_identifier
from musimack_tools.persistence.durable_models import (
    DurableJobModel,
    DurableRecoveryEventModel,
    DurableSequenceModel,
    JobExecutionAttemptModel,
    JobLeaseModel,
    WorkerModel,
)
from musimack_tools.persistence.models import (
    JobModel,
    ProgressSnapshotModel,
    RunModel,
    RunStageModel,
)
from musimack_tools.persistence.repositories import SQLAlchemyPersistenceRepository
from musimack_tools.run.identity import run_identity

if TYPE_CHECKING:
    from collections.abc import Iterator

    from musimack_tools.domain.run import CrawlRunRequest
    from musimack_tools.persistence.engine import PersistenceRuntime

UtcClock = Callable[[], datetime]
LeaseTokenFactory = Callable[[], str]
_DURABLE_REPOSITORY_DISABLED = "durable repository requires durable execution mode"
_LOGGER = getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DurableSubmission:
    result: JobSubmissionResult
    request_json: str | None


class SQLAlchemyDurableExecutionRepository:
    def __init__(
        self,
        runtime: PersistenceRuntime,
        configuration: DurableExecutionConfiguration,
        *,
        clock: UtcClock = utc_now,
        token_factory: LeaseTokenFactory | None = None,
    ) -> None:
        if not configuration.enabled:
            raise ValueError(_DURABLE_REPOSITORY_DISABLED)
        self._runtime = runtime
        self._configuration = configuration
        self._clock = clock
        self._token_factory = token_factory or _lease_token
        self._evidence = SQLAlchemyPersistenceRepository(runtime)

    @property
    def configuration(self) -> DurableExecutionConfiguration:
        return self._configuration

    def submit(self, submission: JobSubmissionRequest) -> DurableSubmission:
        request = submission.run_request
        try:
            run_id, _digest = run_identity(request)
            request_json = serialize_run_request(request)
            with self._immediate_session() as session:
                attempt = self._allocate(session, f"submission_attempt:{run_id}")
                job_id = job_identifier(run_id, attempt)
            snapshot = _job_snapshot(job_id, run_id, attempt, JobState.QUEUED)
        except TypeError, ValueError, SQLAlchemyError:
            return DurableSubmission(
                _submission_failure(
                    JobSubmissionFailureCode.INVALID_REQUEST,
                    "The durable run request could not be accepted",
                ),
                None,
            )
        evidence = self._evidence.record_submission(snapshot, request)
        if not evidence.succeeded:
            return DurableSubmission(
                _submission_failure(
                    JobSubmissionFailureCode.COORDINATOR_UNAVAILABLE,
                    "Durable persistence did not record the submission",
                ),
                None,
            )
        try:
            with self._immediate_session() as session:
                submission_sequence = self._allocate(session, "submission")
                availability_sequence = self._allocate(session, "availability")
                session.add(
                    DurableJobModel(
                        job_id=job_id,
                        durable_state=DurableJobState.QUEUED.value,
                        priority=0,
                        submission_sequence=submission_sequence,
                        availability_sequence=availability_sequence,
                        claimed_worker_id=None,
                        lease_generation=0,
                        cancellation_requested=False,
                        retry_count=0,
                        maximum_attempts=self._configuration.maximum_attempts,
                        retry_eligible=False,
                        next_retry_at=None,
                        last_failure_code=None,
                        terminal_disposition=None,
                        worker_protocol_version=WORKER_PROTOCOL_VERSION,
                        durable_execution_version=DURABLE_EXECUTION_VERSION,
                        request_json=request_json,
                        recovery_count=0,
                    )
                )
        except SQLAlchemyError:
            return DurableSubmission(
                _submission_failure(
                    JobSubmissionFailureCode.COORDINATOR_UNAVAILABLE,
                    "The durable queue did not record the submission",
                ),
                None,
            )
        return DurableSubmission(
            JobSubmissionResult(
                JobSubmissionOutcome.ACCEPTED,
                snapshot,
                None,
                "The job was accepted by the durable queue",
                CRAWL_JOB_REGISTRY_VERSION,
            ),
            request_json,
        )

    def register_worker(self, identity: WorkerIdentity, maximum_concurrency: int) -> WorkerState:
        now = require_aware_utc(self._clock())
        with self._immediate_session() as session:
            worker = session.get(WorkerModel, identity.value)
            sequence = self._allocate(session, "worker_startup")
            if worker is None:
                worker = WorkerModel(
                    worker_id=identity.value,
                    worker_protocol_version=WORKER_PROTOCOL_VERSION,
                    durable_execution_version=DURABLE_EXECUTION_VERSION,
                    state=WorkerState.STARTING.value,
                    maximum_concurrency=maximum_concurrency,
                    current_claimed_count=0,
                    started_sequence=sequence,
                    last_heartbeat_sequence=sequence,
                    last_heartbeat_at=now,
                    shutdown_requested=False,
                    failure_code=None,
                    metadata_version=1,
                )
                session.add(worker)
            else:
                worker.state = WorkerState.STARTING.value
                worker.maximum_concurrency = maximum_concurrency
                worker.current_claimed_count = self._active_worker_leases(session, identity.value)
                worker.started_sequence = sequence
                worker.last_heartbeat_sequence = sequence
                worker.last_heartbeat_at = now
                worker.shutdown_requested = False
                worker.failure_code = None
                worker.metadata_version += 1
                worker.worker_protocol_version = WORKER_PROTOCOL_VERSION
                worker.durable_execution_version = DURABLE_EXECUTION_VERSION
            worker.state = WorkerState.READY.value
        _LOGGER.info(
            "durable_worker_registered",
            extra={"worker_id": identity.value, "maximum_concurrency": maximum_concurrency},
        )
        return WorkerState.READY

    def claim(self, worker_id: str, maximum: int | None = None) -> tuple[DurableClaim, ...]:
        now = require_aware_utc(self._clock())
        limit = min(
            maximum or self._configuration.maximum_claim_batch,
            self._configuration.maximum_claim_batch,
        )
        claims: list[DurableClaim] = []
        with self._immediate_session() as session:
            worker = session.get(WorkerModel, worker_id)
            if worker is None or WorkerState(worker.state) is not WorkerState.READY:
                return ()
            capacity = max(0, worker.maximum_concurrency - worker.current_claimed_count)
            limit = min(limit, capacity)
            if limit == 0:
                return ()
            eligible = or_(
                DurableJobModel.durable_state == DurableJobState.QUEUED.value,
                and_(
                    DurableJobModel.durable_state == DurableJobState.RETRY_WAIT.value,
                    DurableJobModel.next_retry_at.is_not(None),
                    DurableJobModel.next_retry_at <= now,
                ),
            )
            jobs = tuple(
                session.scalars(
                    select(DurableJobModel)
                    .join(JobModel, JobModel.job_id == DurableJobModel.job_id)
                    .where(eligible, DurableJobModel.cancellation_requested.is_(False))
                    .order_by(
                        DurableJobModel.availability_sequence,
                        DurableJobModel.submission_sequence,
                        JobModel.attempt_number,
                        DurableJobModel.job_id,
                    )
                    .limit(limit)
                )
            )
            for job in jobs:
                generation = job.lease_generation + 1
                token = self._token_factory()
                acquired_sequence = self._allocate(session, "claim")
                execution_sequence = self._allocate(session, "execution_attempt")
                execution_number = job.retry_count + 1
                expires = now + timedelta(seconds=self._configuration.lease_duration_seconds)
                job.durable_state = DurableJobState.CLAIMED.value
                job.claimed_worker_id = worker_id
                job.lease_generation = generation
                job.next_retry_at = None
                session.add(
                    JobLeaseModel(
                        job_id=job.job_id,
                        worker_id=worker_id,
                        lease_token=token,
                        lease_generation=generation,
                        acquired_sequence=acquired_sequence,
                        acquired_at=now,
                        expires_at=expires,
                        last_heartbeat_sequence=acquired_sequence,
                        last_heartbeat_at=now,
                        released_at=None,
                        release_reason=None,
                        active=True,
                        worker_protocol_version=WORKER_PROTOCOL_VERSION,
                    )
                )
                session.add(
                    JobExecutionAttemptModel(
                        job_id=job.job_id,
                        execution_number=execution_number,
                        worker_id=worker_id,
                        lease_generation=generation,
                        started_at=now,
                        finished_at=None,
                        outcome=DurableJobState.CLAIMED.value,
                        failure_code=None,
                        retryable=False,
                        cancellation_observed=False,
                        run_lifecycle=None,
                        progress_sequence_start=None,
                        progress_sequence_end=None,
                        created_sequence=execution_sequence,
                    )
                )
                base = session.get(JobModel, job.job_id)
                if base is None:
                    raise LookupError(job.job_id)
                base.state = JobState.STARTING.value
                base.started_sequence = acquired_sequence
                worker.current_claimed_count += 1
                worker.last_heartbeat_sequence = acquired_sequence
                worker.last_heartbeat_at = now
                claims.append(
                    DurableClaim(
                        job.job_id,
                        base.run_id,
                        base.attempt_number,
                        execution_number,
                        worker_id,
                        token,
                        generation,
                        acquired_sequence,
                        expires,
                        job.request_json,
                    )
                )
        for claim in claims:
            _LOGGER.info(
                "durable_job_claimed",
                extra={
                    "job_id": claim.job_id,
                    "worker_id": claim.worker_id,
                    "lease_generation": claim.lease_generation,
                },
            )
        return tuple(claims)

    def mark_running(self, claim: DurableClaim) -> LeaseOperationResult:
        now = require_aware_utc(self._clock())
        with self._immediate_session() as session:
            lease, outcome = self._validated_lease(session, claim)
            if lease is None:
                return outcome
            job = self._required_durable_job(session, claim.job_id)
            job.durable_state = DurableJobState.RUNNING.value
            base = self._required_job(session, claim.job_id)
            base.state = JobState.RUNNING.value
            base.run_lifecycle = RunLifecycle.RUNNING.value
            base.started_at = base.started_at or now
            run = session.get(RunModel, base.run_id)
            if run is not None:
                run.started_at = run.started_at or now
        return LeaseOperationResult(LeaseOutcome.ACCEPTED)

    def heartbeat(self, claim: DurableClaim) -> LeaseOperationResult:
        now = require_aware_utc(self._clock())
        with self._immediate_session() as session:
            lease, outcome = self._validated_lease(session, claim, now=now)
            if lease is None:
                return outcome
            worker = session.get(WorkerModel, claim.worker_id)
            if worker is None:
                return LeaseOperationResult(
                    LeaseOutcome.NOT_FOUND, DurableFailureCode.LEASE_NOT_FOUND
                )
            previous = _as_utc(lease.last_heartbeat_at)
            if (now - previous).total_seconds() >= self._configuration.heartbeat_interval_seconds:
                heartbeat_sequence = self._allocate(session, "heartbeat")
                lease.last_heartbeat_sequence = heartbeat_sequence
                lease.last_heartbeat_at = now
                lease.expires_at = now + timedelta(
                    seconds=self._configuration.lease_duration_seconds
                )
                worker.last_heartbeat_sequence = heartbeat_sequence
                worker.last_heartbeat_at = now
            expires = _as_utc(lease.expires_at)
        return LeaseOperationResult(LeaseOutcome.ACCEPTED, expires_at=expires)

    def worker_heartbeat(self, worker_id: str) -> bool:
        now = require_aware_utc(self._clock())
        with self._immediate_session() as session:
            worker = session.get(WorkerModel, worker_id)
            if worker is None or WorkerState(worker.state).terminal:
                return False
            worker.last_heartbeat_sequence = self._allocate(session, "heartbeat")
            worker.last_heartbeat_at = now
        return True

    def record_progress(self, claim: DurableClaim, event: RunProgressEvent) -> bool:
        with self._runtime.transaction() as session:
            lease, _outcome = self._validated_lease(session, claim)
            if lease is None:
                return False
        result = self._evidence.record_progress(claim.job_id, claim.run_id, event)
        if result.succeeded:
            with self._immediate_session() as session:
                attempt = self._required_attempt(session, claim)
                if attempt.progress_sequence_start is None:
                    attempt.progress_sequence_start = event.sequence
                attempt.progress_sequence_end = event.sequence
        return result.succeeded

    def cancellation_requested(self, job_id: str) -> bool:
        with self._runtime.transaction() as session:
            job = session.get(DurableJobModel, job_id)
            return bool(job is not None and job.cancellation_requested)

    def request_cancellation(self, job_id: str) -> JobCancellationResult:
        now = require_aware_utc(self._clock())
        with self._immediate_session() as session:
            durable = session.get(DurableJobModel, job_id)
            base = session.get(JobModel, job_id)
            if durable is None or base is None:
                return JobCancellationResult(
                    JobCancellationOutcome.NOT_FOUND, None, "Job not found"
                )
            state = DurableJobState(durable.durable_state)
            if state.terminal:
                return JobCancellationResult(
                    JobCancellationOutcome.ALREADY_TERMINAL,
                    self._snapshot(session, durable, base),
                    "The durable job is already terminal",
                )
            if durable.cancellation_requested:
                return JobCancellationResult(
                    JobCancellationOutcome.ALREADY_REQUESTED,
                    self._snapshot(session, durable, base),
                    "Durable cancellation was already requested",
                )
            durable.cancellation_requested = True
            base.cancellation_requested = True
            if state in {
                DurableJobState.ACCEPTED,
                DurableJobState.QUEUED,
                DurableJobState.RETRY_WAIT,
            }:
                durable.durable_state = DurableJobState.CANCELLED.value
                durable.terminal_disposition = DurableJobState.CANCELLED.value
                base.state = JobState.CANCELLED.value
                base.terminal = True
                base.terminal_at = now
                run = session.get(RunModel, base.run_id)
                if run is not None:
                    run.terminal_at = now
                outcome = JobCancellationOutcome.CANCELLED_WHILE_QUEUED
                explanation = "The durable queued job was cancelled before claim"
            else:
                durable.durable_state = DurableJobState.CANCELLING.value
                base.state = JobState.CANCELLING.value
                outcome = JobCancellationOutcome.REQUESTED
                explanation = "Cooperative durable cancellation was requested"
            snapshot = self._snapshot(session, durable, base)
        _LOGGER.info(
            "durable_cancellation_recorded",
            extra={"job_id": job_id, "cancellation_outcome": outcome.value},
        )
        return JobCancellationResult(outcome, snapshot, explanation)

    def status(self, job_id: str) -> DurableJobStatus | None:
        with self._runtime.transaction() as session:
            durable = session.get(DurableJobModel, job_id)
            base = session.get(JobModel, job_id)
            if durable is None or base is None:
                return None
            position = self._queue_position(session, durable)
            latest = session.scalar(
                select(func.max(ProgressSnapshotModel.sequence)).where(
                    ProgressSnapshotModel.job_id == job_id
                )
            )
            state = DurableJobState(durable.durable_state)
            return DurableJobStatus(
                job_id,
                base.run_id,
                base.attempt_number,
                state,
                position,
                durable.retry_count,
                durable.maximum_attempts,
                durable.cancellation_requested,
                int(latest) if latest is not None else None,
                base.result_available,
                state.terminal,
                durable.last_failure_code,
            )

    def lookup(self, job_id: str) -> JobLookupResult:
        with self._runtime.transaction() as session:
            durable = session.get(DurableJobModel, job_id)
            base = session.get(JobModel, job_id)
            if durable is None or base is None:
                return JobLookupResult(JobLookupOutcome.NOT_FOUND, None)
            return JobLookupResult(JobLookupOutcome.FOUND, self._snapshot(session, durable, base))

    def progress(self, job_id: str) -> JobProgressView:
        with self._runtime.transaction() as session:
            base = session.get(JobModel, job_id)
            if base is None:
                return JobProgressView(
                    outcome=JobLookupOutcome.NOT_FOUND,
                    latest=None,
                    history=(),
                    history_truncated=False,
                )
            row = session.scalar(
                select(ProgressSnapshotModel)
                .where(ProgressSnapshotModel.job_id == job_id)
                .order_by(ProgressSnapshotModel.sequence.desc())
                .limit(1)
            )
            if row is None:
                return JobProgressView(
                    outcome=JobLookupOutcome.FOUND,
                    latest=None,
                    history=(),
                    history_truncated=False,
                )
            stage = RunStage(row.active_stage) if row.active_stage is not None else None
            stage_row = (
                session.scalar(
                    select(RunStageModel).where(
                        RunStageModel.run_id == base.run_id,
                        RunStageModel.stage == row.active_stage,
                    )
                )
                if row.active_stage is not None
                else None
            )
            snapshot = RunProgressSnapshot(
                lifecycle=(
                    RunLifecycle(base.run_lifecycle)
                    if base.run_lifecycle is not None
                    else RunLifecycle.PENDING
                ),
                active_stage=stage,
                stage_state=(RunStageState(stage_row.state) if stage_row is not None else None),
                urls_discovered=row.discovered_count,
                urls_queued=row.queued_count,
                urls_fetched=row.fetched_count,
                urls_parsed=row.parsed_count,
                bytes_fetched=row.byte_count,
                queue_size=row.queue_size,
                active_count=row.active_fetch_count,
                current_depth=row.current_depth,
                warning_count=row.warning_count,
                failure_count=row.failure_count,
                cancellation_requested=row.cancellation_requested,
                recent_crawl_error_code=row.recent_safe_error_code,
                elapsed_seconds=row.elapsed_seconds,
            )
            event = RunProgressEvent(
                row.sequence,
                RunEventCode(row.event_code),
                snapshot,
                "Durable progress evidence",
            )
            return JobProgressView(
                outcome=JobLookupOutcome.FOUND,
                latest=event,
                history=(event,),
                history_truncated=False,
            )

    def result(self, job_id: str) -> JobResultView:
        lookup = self.lookup(job_id)
        return JobResultView(lookup.outcome, lookup.snapshot, None, ())

    def registry_snapshot(self) -> JobRegistrySnapshot:
        with self._runtime.transaction() as session:
            rows = tuple(
                session.execute(
                    select(DurableJobModel.job_id, DurableJobModel.durable_state).order_by(
                        DurableJobModel.submission_sequence
                    )
                )
            )
        terminal = tuple(job_id for job_id, state in rows if DurableJobState(state).terminal)
        queued = tuple(
            job_id
            for job_id, state in rows
            if DurableJobState(state) in {DurableJobState.QUEUED, DurableJobState.RETRY_WAIT}
        )
        active = tuple(
            job_id
            for job_id, state in rows
            if DurableJobState(state)
            in {
                DurableJobState.CLAIMED,
                DurableJobState.STARTING,
                DurableJobState.RUNNING,
                DurableJobState.CANCELLING,
            }
        )
        states = [DurableJobState(state) for _job_id, state in rows]
        counters = JobRegistryCounters(
            submitted_jobs=len(rows),
            accepted_jobs=len(rows),
            rejected_jobs=0,
            active_jobs=len(active),
            queued_jobs=len(queued),
            terminal_jobs_retained=len(terminal),
            completed_jobs=sum(
                state in {DurableJobState.COMPLETED, DurableJobState.COMPLETED_WITH_WARNINGS}
                for state in states
            ),
            cancelled_jobs=states.count(DurableJobState.CANCELLED),
            failed_jobs=states.count(DurableJobState.FAILED),
            partially_completed_jobs=states.count(DurableJobState.PARTIALLY_COMPLETED),
            evicted_jobs=0,
            duplicate_rejections=0,
            queue_capacity_rejections=0,
        )
        return JobRegistrySnapshot(
            RegistryState.RUNNING,
            JobRegistryConfiguration(
                maximum_concurrent_jobs=self._configuration.maximum_concurrent_claimed_jobs
            ),
            counters,
            active,
            queued,
            terminal,
        )

    def load_request(self, claim: DurableClaim) -> CrawlRunRequest:
        return deserialize_run_request(claim.request_json)

    def complete(  # noqa: PLR0915 - durable terminal state evidence remains explicit.
        self, claim: DurableClaim, result: CrawlRunResult
    ) -> DurableJobState:
        now = require_aware_utc(self._clock())
        failure_codes = tuple(item.code.value for item in result.failures)
        terminal_success = result.lifecycle in {
            RunLifecycle.COMPLETED,
            RunLifecycle.COMPLETED_WITH_WARNINGS,
        }
        with self._runtime.transaction() as session:
            durable = self._required_durable_job(session, claim.job_id)
            cancellation = durable.cancellation_requested
            retry_count = durable.retry_count
        evaluation = classify_retry(
            self._configuration,
            now=now,
            failure_codes=failure_codes,
            retry_count=retry_count,
            cancellation_requested=cancellation,
            terminal_success=terminal_success,
        )
        state = _state_for_result(result.lifecycle)
        if evaluation.decision is RetryDecision.RETRY:
            state = DurableJobState.RETRY_WAIT
        elif evaluation.decision is RetryDecision.CANCEL:
            state = DurableJobState.CANCELLED
        snapshot_state = (
            JobState.QUEUED if state is DurableJobState.RETRY_WAIT else JobState(state.value)
        )
        snapshot = _job_snapshot(
            claim.job_id,
            claim.run_id,
            claim.submission_attempt,
            snapshot_state,
            lifecycle=result.lifecycle,
            warning_count=len(result.warnings),
            failure_count=len(result.failures),
            result_available=state is not DurableJobState.RETRY_WAIT,
            summary_count=len(result.summaries),
            cancellation=cancellation,
        )
        terminal_write = self._evidence.record_terminal(snapshot, result, (), None)
        if not terminal_write.succeeded:
            _LOGGER.error(
                "durable_terminal_persistence_failed",
                extra={
                    "job_id": claim.job_id,
                    "worker_id": claim.worker_id,
                    "failure_code": DurableFailureCode.TERMINAL_PERSISTENCE_FAILED.value,
                    "persistence_failure_code": (
                        terminal_write.failure_code.value
                        if terminal_write.failure_code is not None
                        else None
                    ),
                },
            )
            return self.fail_execution(claim, DurableFailureCode.TERMINAL_PERSISTENCE_FAILED.value)
        with self._immediate_session() as session:
            durable = self._required_durable_job(session, claim.job_id)
            base = self._required_job(session, claim.job_id)
            attempt = self._required_attempt(session, claim)
            attempt.finished_at = now
            attempt.outcome = state.value
            attempt.failure_code = failure_codes[0] if failure_codes else None
            attempt.retryable = evaluation.retryable
            attempt.cancellation_observed = cancellation
            attempt.run_lifecycle = result.lifecycle.value
            durable.last_failure_code = failure_codes[0] if failure_codes else None
            if state is DurableJobState.RETRY_WAIT:
                durable.retry_count += 1
                durable.retry_eligible = True
                durable.next_retry_at = evaluation.next_eligible_at
                durable.availability_sequence = self._allocate(session, "availability")
                durable.durable_state = state.value
                durable.claimed_worker_id = None
                base.state = JobState.QUEUED.value
                base.terminal = False
                base.result_available = False
                base.terminal_at = None
                run = session.get(RunModel, base.run_id)
                if run is not None:
                    run.terminal_at = None
            else:
                durable.durable_state = state.value
                durable.terminal_disposition = state.value
                durable.claimed_worker_id = None
                base.state = snapshot_state.value
                base.terminal = True
                base.result_available = True
                base.terminal_at = now
            self._release_active_lease(session, claim, now, state.value)
        _LOGGER.info(
            "durable_execution_finished",
            extra={
                "job_id": claim.job_id,
                "worker_id": claim.worker_id,
                "durable_state": state.value,
                "retry_scheduled": state is DurableJobState.RETRY_WAIT,
            },
        )
        return state

    def fail_execution(self, claim: DurableClaim, failure_code: str) -> DurableJobState:
        now = require_aware_utc(self._clock())
        with self._runtime.transaction() as session:
            durable = self._required_durable_job(session, claim.job_id)
            cancellation = durable.cancellation_requested
            retry_count = durable.retry_count
        evaluation = classify_retry(
            self._configuration,
            now=now,
            failure_codes=(failure_code,),
            retry_count=retry_count,
            cancellation_requested=cancellation,
            terminal_success=False,
        )
        state = (
            DurableJobState.RETRY_WAIT
            if evaluation.decision is RetryDecision.RETRY
            else DurableJobState.CANCELLED
            if evaluation.decision is RetryDecision.CANCEL
            else DurableJobState.FAILED
        )
        with self._immediate_session() as session:
            durable = self._required_durable_job(session, claim.job_id)
            base = self._required_job(session, claim.job_id)
            attempt = self._required_attempt(session, claim)
            attempt.finished_at = now
            attempt.outcome = state.value
            attempt.failure_code = failure_code
            attempt.retryable = evaluation.retryable
            attempt.cancellation_observed = cancellation
            durable.last_failure_code = failure_code
            durable.claimed_worker_id = None
            if state is DurableJobState.RETRY_WAIT:
                durable.retry_count += 1
                durable.retry_eligible = True
                durable.next_retry_at = evaluation.next_eligible_at
                durable.availability_sequence = self._allocate(session, "availability")
                base.state = JobState.QUEUED.value
                base.terminal = False
                base.terminal_at = None
            else:
                durable.terminal_disposition = state.value
                base.state = JobState(state.value).value
                base.terminal = True
                base.terminal_at = now
                run = session.get(RunModel, base.run_id)
                if run is not None:
                    run.terminal_at = now
            durable.durable_state = state.value
            self._release_active_lease(session, claim, now, state.value)
        _LOGGER.info(
            "durable_execution_failed",
            extra={
                "job_id": claim.job_id,
                "worker_id": claim.worker_id,
                "failure_code": failure_code,
                "durable_state": state.value,
                "retry_scheduled": state is DurableJobState.RETRY_WAIT,
            },
        )
        return state

    def recover_stale(self) -> DurableRecoveryReport:  # noqa: PLR0915
        now = require_aware_utc(self._clock())
        stale_before = now - timedelta(seconds=self._configuration.stale_after_seconds)
        stale_workers = 0
        stale_leases = 0
        retried = 0
        cancelled = 0
        failed = 0
        recovered: list[str] = []
        with self._immediate_session() as session:
            workers = tuple(
                session.scalars(
                    select(WorkerModel).where(
                        WorkerModel.state.not_in(
                            [state.value for state in WorkerState if state.terminal]
                        ),
                        WorkerModel.last_heartbeat_at < stale_before,
                        WorkerModel.current_claimed_count > 0,
                    )
                )
            )
            stale_ids = {worker.worker_id for worker in workers}
            for worker in workers:
                worker.state = WorkerState.STALE.value
                worker.failure_code = DurableFailureCode.WORKER_STALE.value
                stale_workers += 1
            leases = tuple(
                session.scalars(
                    select(JobLeaseModel).where(
                        JobLeaseModel.active.is_(True),
                        or_(
                            JobLeaseModel.expires_at <= now,
                            JobLeaseModel.worker_id.in_(stale_ids) if stale_ids else false(),
                        ),
                    )
                )
            )
            for lease in leases:
                stale_leases += 1
                durable = self._required_durable_job(session, lease.job_id)
                base = self._required_job(session, lease.job_id)
                attempt = session.scalar(
                    select(JobExecutionAttemptModel).where(
                        JobExecutionAttemptModel.job_id == lease.job_id,
                        JobExecutionAttemptModel.lease_generation == lease.lease_generation,
                    )
                )
                lease.active = False
                lease.released_at = now
                lease.release_reason = DurableFailureCode.LEASE_EXPIRED.value
                durable.claimed_worker_id = None
                durable.recovery_count += 1
                durable.last_failure_code = DurableFailureCode.LEASE_EXPIRED.value
                if attempt is not None and attempt.finished_at is None:
                    attempt.finished_at = now
                    attempt.failure_code = DurableFailureCode.LEASE_EXPIRED.value
                if durable.cancellation_requested:
                    state = DurableJobState.CANCELLED
                    cancelled += 1
                else:
                    evaluation = classify_retry(
                        self._configuration,
                        now=now,
                        failure_codes=(DurableFailureCode.LEASE_EXPIRED.value,),
                        retry_count=durable.retry_count,
                        cancellation_requested=False,
                        terminal_success=False,
                    )
                    if (
                        self._configuration.orphaned_lease_policy is OrphanedLeasePolicy.RECOVER
                        and evaluation.decision is RetryDecision.RETRY
                    ):
                        state = DurableJobState.RETRY_WAIT
                        durable.retry_count += 1
                        durable.retry_eligible = True
                        durable.next_retry_at = evaluation.next_eligible_at
                        durable.availability_sequence = self._allocate(session, "availability")
                        base.state = JobState.QUEUED.value
                        base.terminal = False
                        base.terminal_at = None
                        retried += 1
                    else:
                        partial = self._has_completed_stage(session, base.run_id)
                        state = (
                            DurableJobState.PARTIALLY_COMPLETED
                            if partial
                            else DurableJobState.FAILED
                        )
                        failed += 1
                durable.durable_state = state.value
                if state.terminal:
                    durable.terminal_disposition = state.value
                    base.state = JobState(state.value).value
                    base.terminal = True
                    base.terminal_at = now
                    run = session.get(RunModel, base.run_id)
                    if run is not None:
                        run.terminal_at = now
                if attempt is not None:
                    attempt.outcome = state.value
                    attempt.retryable = state is DurableJobState.RETRY_WAIT
                    attempt.cancellation_observed = durable.cancellation_requested
                sequence = self._allocate(session, "recovery")
                session.add(
                    DurableRecoveryEventModel(
                        job_id=lease.job_id,
                        worker_id=lease.worker_id,
                        event_sequence=sequence,
                        event_code=DurableFailureCode.LEASE_EXPIRED.value,
                        disposition=state.value,
                        occurred_at=now,
                    )
                )
                recovered_worker = session.get(WorkerModel, lease.worker_id)
                if recovered_worker is not None:
                    recovered_worker.current_claimed_count = max(
                        0, recovered_worker.current_claimed_count - 1
                    )
                recovered.append(lease.job_id)
        report = DurableRecoveryReport(
            stale_workers=stale_workers,
            stale_leases=stale_leases,
            jobs_retried=retried,
            jobs_cancelled=cancelled,
            jobs_failed=failed,
            recovered_job_ids=tuple(sorted(recovered)),
            recovery_complete=True,
        )
        _LOGGER.info(
            "durable_recovery_completed",
            extra={
                "stale_workers": stale_workers,
                "stale_leases": stale_leases,
                "jobs_retried": retried,
                "jobs_cancelled": cancelled,
                "jobs_failed": failed,
            },
        )
        return report

    def set_worker_state(self, worker_id: str, state: WorkerState) -> bool:
        with self._immediate_session() as session:
            worker = session.get(WorkerModel, worker_id)
            if worker is None:
                return False
            worker.state = state.value
            worker.shutdown_requested = state is WorkerState.DRAINING
            worker.last_heartbeat_at = require_aware_utc(self._clock())
        return True

    def diagnostics(
        self, worker_id: str | None = None, *, recovery_complete: bool
    ) -> DurableDiagnostics:
        now = require_aware_utc(self._clock())
        stale_before = now - timedelta(seconds=self._configuration.stale_after_seconds)
        with self._runtime.transaction() as session:
            worker = session.get(WorkerModel, worker_id) if worker_id is not None else None

            def count(state: DurableJobState) -> int:
                return int(
                    session.scalar(
                        select(func.count())
                        .select_from(DurableJobModel)
                        .where(DurableJobModel.durable_state == state.value)
                    )
                    or 0
                )

            queue_depth = count(DurableJobState.QUEUED) + count(DurableJobState.RETRY_WAIT)
            claimable = int(
                session.scalar(
                    select(func.count())
                    .select_from(DurableJobModel)
                    .where(
                        DurableJobModel.cancellation_requested.is_(False),
                        or_(
                            DurableJobModel.durable_state == DurableJobState.QUEUED.value,
                            and_(
                                DurableJobModel.durable_state == DurableJobState.RETRY_WAIT.value,
                                DurableJobModel.next_retry_at <= now,
                            ),
                        ),
                    )
                )
                or 0
            )
            stale_workers = int(
                session.scalar(
                    select(func.count())
                    .select_from(WorkerModel)
                    .where(
                        WorkerModel.last_heartbeat_at < stale_before,
                        WorkerModel.current_claimed_count > 0,
                    )
                )
                or 0
            )
            stale_leases = int(
                session.scalar(
                    select(func.count())
                    .select_from(JobLeaseModel)
                    .where(JobLeaseModel.active.is_(True), JobLeaseModel.expires_at <= now)
                )
                or 0
            )
            cancellation_backlog = int(
                session.scalar(
                    select(func.count())
                    .select_from(DurableJobModel)
                    .where(
                        DurableJobModel.cancellation_requested.is_(True),
                        DurableJobModel.durable_state.not_in(
                            [state.value for state in DurableJobState if state.terminal]
                        ),
                    )
                )
                or 0
            )
            expiration_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(DurableRecoveryEventModel)
                    .where(
                        DurableRecoveryEventModel.event_code
                        == DurableFailureCode.LEASE_EXPIRED.value
                    )
                )
                or 0
            )
            retry_count = int(
                session.scalar(select(func.coalesce(func.sum(DurableJobModel.retry_count), 0))) or 0
            )
            claimed_jobs = count(DurableJobState.CLAIMED) + count(DurableJobState.RUNNING)
            retry_wait_jobs = count(DurableJobState.RETRY_WAIT)
        persistence = self._evidence.diagnostics()
        worker_state = WorkerState(worker.state) if worker is not None else None
        return DurableDiagnostics(
            enabled=True,
            worker_enabled=self._configuration.worker_enabled,
            worker_registered=worker is not None,
            worker_state=worker_state,
            queue_depth=queue_depth,
            claimable_jobs=claimable,
            claimed_jobs=claimed_jobs,
            retry_wait_jobs=retry_wait_jobs,
            stale_workers=stale_workers,
            stale_leases=stale_leases,
            heartbeat_healthy=worker is None
            or worker_state in {WorkerState.READY, WorkerState.DRAINING},
            persistence_ready=persistence.state is PersistenceReadinessState.READY,
            migration_current=persistence.schema_current,
            recovery_complete=recovery_complete,
            cancellation_backlog=cancellation_backlog,
            lease_expiration_count=expiration_count,
            retry_count=retry_count,
        )

    @contextmanager
    def _immediate_session(self) -> Iterator[Session]:
        connection = self._runtime.engine.connect()
        session = Session(bind=connection, expire_on_commit=False)
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            yield session
            session.flush()
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            session.close()
            connection.close()

    @staticmethod
    def _allocate(session: Session, name: str) -> int:
        sequence = session.get(DurableSequenceModel, name)
        if sequence is None:
            sequence = DurableSequenceModel(sequence_name=name, current_value=1)
            session.add(sequence)
            session.flush()
            return 1
        sequence.current_value += 1
        session.flush()
        return sequence.current_value

    @staticmethod
    def _required_job(session: Session, job_id: str) -> JobModel:
        job = session.get(JobModel, job_id)
        if job is None:
            raise LookupError(job_id)
        return job

    @staticmethod
    def _required_durable_job(session: Session, job_id: str) -> DurableJobModel:
        job = session.get(DurableJobModel, job_id)
        if job is None:
            raise LookupError(job_id)
        return job

    @staticmethod
    def _required_attempt(session: Session, claim: DurableClaim) -> JobExecutionAttemptModel:
        attempt = session.scalar(
            select(JobExecutionAttemptModel).where(
                JobExecutionAttemptModel.job_id == claim.job_id,
                JobExecutionAttemptModel.lease_generation == claim.lease_generation,
            )
        )
        if attempt is None:
            raise LookupError(claim.job_id)
        return attempt

    def _validated_lease(  # noqa: PLR0911 - each stable lease rejection is explicit.
        self,
        session: Session,
        claim: DurableClaim,
        *,
        now: datetime | None = None,
    ) -> tuple[JobLeaseModel | None, LeaseOperationResult]:
        lease = session.scalar(
            select(JobLeaseModel).where(
                JobLeaseModel.job_id == claim.job_id,
                JobLeaseModel.lease_generation == claim.lease_generation,
            )
        )
        if lease is None:
            return None, LeaseOperationResult(
                LeaseOutcome.NOT_FOUND, DurableFailureCode.LEASE_NOT_FOUND
            )
        if lease.worker_id != claim.worker_id:
            return None, LeaseOperationResult(
                LeaseOutcome.WRONG_WORKER, DurableFailureCode.LEASE_WRONG_WORKER
            )
        if lease.lease_token != claim.lease_token:
            return None, LeaseOperationResult(
                LeaseOutcome.WRONG_TOKEN, DurableFailureCode.LEASE_WRONG_TOKEN
            )
        durable = self._required_durable_job(session, claim.job_id)
        if durable.lease_generation != claim.lease_generation:
            return None, LeaseOperationResult(
                LeaseOutcome.STALE_GENERATION, DurableFailureCode.LEASE_STALE_GENERATION
            )
        if not lease.active:
            return None, LeaseOperationResult(
                LeaseOutcome.RELEASED, DurableFailureCode.LEASE_RELEASED
            )
        checked = require_aware_utc(now or self._clock())
        if _as_utc(lease.expires_at) <= checked:
            return None, LeaseOperationResult(
                LeaseOutcome.EXPIRED, DurableFailureCode.LEASE_EXPIRED
            )
        return lease, LeaseOperationResult(LeaseOutcome.ACCEPTED)

    def _release_active_lease(
        self,
        session: Session,
        claim: DurableClaim,
        now: datetime,
        reason: str,
    ) -> None:
        lease = session.scalar(
            select(JobLeaseModel).where(
                JobLeaseModel.job_id == claim.job_id,
                JobLeaseModel.lease_generation == claim.lease_generation,
            )
        )
        if lease is None or not lease.active or lease.lease_token != claim.lease_token:
            raise LookupError(claim.job_id)
        lease.active = False
        lease.released_at = now
        lease.release_reason = reason
        worker = session.get(WorkerModel, claim.worker_id)
        if worker is not None:
            worker.current_claimed_count = max(0, worker.current_claimed_count - 1)

    @staticmethod
    def _active_worker_leases(session: Session, worker_id: str) -> int:
        return int(
            session.scalar(
                select(func.count())
                .select_from(JobLeaseModel)
                .where(JobLeaseModel.worker_id == worker_id, JobLeaseModel.active.is_(True))
            )
            or 0
        )

    @staticmethod
    def _has_completed_stage(session: Session, run_id: str) -> bool:
        return bool(
            session.scalar(
                select(func.count())
                .select_from(RunStageModel)
                .where(
                    RunStageModel.run_id == run_id,
                    RunStageModel.state.in_(["completed", "completed_with_warnings"]),
                )
            )
            or 0
        )

    def _queue_position(self, session: Session, job: DurableJobModel) -> int | None:
        if DurableJobState(job.durable_state) not in {
            DurableJobState.QUEUED,
            DurableJobState.RETRY_WAIT,
        }:
            return None
        return (
            int(
                session.scalar(
                    select(func.count())
                    .select_from(DurableJobModel)
                    .where(
                        DurableJobModel.durable_state.in_(
                            [DurableJobState.QUEUED.value, DurableJobState.RETRY_WAIT.value]
                        ),
                        DurableJobModel.cancellation_requested.is_(False),
                        DurableJobModel.availability_sequence < job.availability_sequence,
                    )
                )
                or 0
            )
            + 1
        )

    def _snapshot(self, session: Session, durable: DurableJobModel, base: JobModel) -> JobSnapshot:
        state = _project_job_state(DurableJobState(durable.durable_state))
        return _job_snapshot(
            base.job_id,
            base.run_id,
            base.attempt_number,
            state,
            queue_position=self._queue_position(session, durable),
            lifecycle=RunLifecycle(base.run_lifecycle) if base.run_lifecycle else None,
            warning_count=base.warning_count,
            failure_count=base.failure_count,
            result_available=base.result_available,
            cancellation=durable.cancellation_requested,
        )


def _lease_token() -> str:
    return f"lease-{secrets.token_hex(16)}"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _state_for_result(lifecycle: RunLifecycle) -> DurableJobState:
    return {
        RunLifecycle.CANCELLED: DurableJobState.CANCELLED,
        RunLifecycle.COMPLETED: DurableJobState.COMPLETED,
        RunLifecycle.COMPLETED_WITH_WARNINGS: DurableJobState.COMPLETED_WITH_WARNINGS,
        RunLifecycle.PARTIALLY_COMPLETED: DurableJobState.PARTIALLY_COMPLETED,
        RunLifecycle.FAILED: DurableJobState.FAILED,
        RunLifecycle.PENDING: DurableJobState.FAILED,
        RunLifecycle.RUNNING: DurableJobState.FAILED,
        RunLifecycle.CANCELLING: DurableJobState.CANCELLED,
    }[lifecycle]


def _project_job_state(state: DurableJobState) -> JobState:
    if state in {DurableJobState.CLAIMED, DurableJobState.STARTING}:
        return JobState.STARTING
    if state is DurableJobState.RETRY_WAIT:
        return JobState.QUEUED
    return JobState(state.value)


def _job_snapshot(  # noqa: PLR0913 - explicit compatibility projection.
    job_id: str,
    run_id: str,
    attempt: int,
    state: JobState,
    *,
    queue_position: int | None = None,
    lifecycle: RunLifecycle | None = None,
    warning_count: int = 0,
    failure_count: int = 0,
    result_available: bool = False,
    summary_count: int = 0,
    cancellation: bool = False,
) -> JobSnapshot:
    return JobSnapshot(
        job_id,
        run_id,
        attempt,
        state,
        queue_position,
        lifecycle,
        None,
        None,
        warning_count,
        failure_count,
        cancellation,
        result_available,
        summary_count,
        state.terminal,
        CRAWL_JOB_REGISTRY_VERSION,
    )


def _submission_failure(code: JobSubmissionFailureCode, explanation: str) -> JobSubmissionResult:
    return JobSubmissionResult(
        JobSubmissionOutcome.REJECTED,
        None,
        code,
        explanation,
        CRAWL_JOB_REGISTRY_VERSION,
    )
