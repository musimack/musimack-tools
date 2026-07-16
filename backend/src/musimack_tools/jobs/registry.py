"""Concurrency-safe in-memory registry and coordinator for crawl-run jobs."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from musimack_tools.crawl.cancellation import CrawlCancellationToken
from musimack_tools.domain.job import (
    JobCancellationOutcome,
    JobCancellationResult,
    JobCoordinationFailure,
    JobCoordinationFailureCode,
    JobCoordinationWarning,
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
    JobWaitOutcome,
    JobWaitResult,
)
from musimack_tools.domain.job_registry import (
    CRAWL_JOB_REGISTRY_VERSION,
    DuplicateSubmissionPolicy,
    JobRegistryConfiguration,
    JobRegistryCounters,
    JobRegistrySnapshot,
    JobShutdownResult,
    PayloadRetentionPolicy,
    RegistryState,
    ShutdownPolicy,
)
from musimack_tools.domain.run import CrawlRunResult, RunLifecycle
from musimack_tools.jobs.identity import job_identifier
from musimack_tools.run.identity import run_identity

if TYPE_CHECKING:
    from musimack_tools.domain.run import CrawlRunRequest
    from musimack_tools.domain.run_progress import RunProgressEvent
    from musimack_tools.domain.run_summary import RunSummaryArtifact
    from musimack_tools.jobs.coordinator import JobRunServiceFactory


@dataclass(slots=True)
class _MutableJob:
    job_id: str
    run_id: str
    attempt_number: int
    request: CrawlRunRequest
    state: JobState
    cancellation: CrawlCancellationToken
    completion: asyncio.Event = field(default_factory=asyncio.Event)
    latest_progress: RunProgressEvent | None = None
    progress_history: deque[RunProgressEvent] = field(default_factory=deque)
    history_truncated: bool = False
    run_result: CrawlRunResult | None = None
    summaries: tuple[RunSummaryArtifact, ...] = ()
    run_lifecycle: RunLifecycle | None = None
    warning_count: int = 0
    failure_count: int = 0
    coordination_failure: JobCoordinationFailure | None = None
    coordination_warnings: list[JobCoordinationWarning] = field(default_factory=list)
    terminal_sequence: int | None = None
    started: bool = False


@dataclass(slots=True)
class _MutableCounters:
    submitted_jobs: int = 0
    accepted_jobs: int = 0
    rejected_jobs: int = 0
    completed_jobs: int = 0
    cancelled_jobs: int = 0
    failed_jobs: int = 0
    partially_completed_jobs: int = 0
    evicted_jobs: int = 0
    duplicate_rejections: int = 0
    queue_capacity_rejections: int = 0


class _RegistryProgressSink:
    def __init__(self, registry: InMemoryJobRegistry, job_id: str) -> None:
        self._registry = registry
        self._job_id = job_id

    async def on_progress(self, event: RunProgressEvent) -> None:
        try:
            await self._registry.record_progress(self._job_id, event)
        except Exception as error:  # noqa: BLE001 - progress isolation is contractual.
            await self._registry.record_progress_failure(self._job_id, error)


class InMemoryJobRegistry:
    """Own process-local job state, scheduling, retention, and shutdown."""

    def __init__(
        self,
        run_service_factory: JobRunServiceFactory,
        configuration: JobRegistryConfiguration | None = None,
    ) -> None:
        self._factory = run_service_factory
        self._configuration = configuration or JobRegistryConfiguration()
        self._state = RegistryState.CREATED
        self._lock = asyncio.Lock()
        self._jobs: dict[str, _MutableJob] = {}
        self._queue: deque[str] = deque()
        self._active: dict[str, None] = {}
        self._terminal: deque[str] = deque()
        self._attempts: dict[str, int] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._counters = _MutableCounters()
        self._terminal_sequence = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._shutdown_result: JobShutdownResult | None = None
        self._shutdown_queued_cancelled = 0
        self._shutdown_active_requested = 0

    async def submit(self, submission: JobSubmissionRequest) -> JobSubmissionResult:
        """Register one attempt and schedule it without waiting for completion."""
        try:
            run_id, _digest = run_identity(submission.run_request)
        except Exception:  # noqa: BLE001 - invalid request maps to stable evidence.
            async with self._lock:
                self._counters.submitted_jobs += 1
                self._counters.rejected_jobs += 1
            return _submission_failure(
                JobSubmissionFailureCode.INVALID_REQUEST,
                "The run request could not be assigned an accepted run identity",
            )

        async with self._lock:
            self._counters.submitted_jobs += 1
            if self._state in {RegistryState.SHUTTING_DOWN, RegistryState.CLOSED}:
                self._counters.rejected_jobs += 1
                return _submission_failure(
                    JobSubmissionFailureCode.REGISTRY_CLOSED,
                    "The registry is not accepting submissions",
                )
            duplicate = self._active_duplicate(run_id)
            policy = self._configuration.duplicate_policy
            if (
                duplicate is not None
                and policy is DuplicateSubmissionPolicy.REJECT_ACTIVE_DUPLICATE
            ):
                self._counters.rejected_jobs += 1
                self._counters.duplicate_rejections += 1
                return _submission_failure(
                    JobSubmissionFailureCode.ACTIVE_DUPLICATE,
                    "An active job already has the same deterministic run ID",
                )
            if (
                duplicate is not None
                and policy is DuplicateSubmissionPolicy.RETURN_ACTIVE_DUPLICATE
            ):
                return JobSubmissionResult(
                    JobSubmissionOutcome.DUPLICATE_RETURNED,
                    self._snapshot(duplicate),
                    None,
                    "The existing active duplicate was returned",
                    CRAWL_JOB_REGISTRY_VERSION,
                )
            starts_now = len(self._active) < self._configuration.maximum_concurrent_jobs
            if not starts_now and len(self._queue) >= self._configuration.maximum_queued_jobs:
                self._counters.rejected_jobs += 1
                self._counters.queue_capacity_rejections += 1
                return _submission_failure(
                    JobSubmissionFailureCode.QUEUE_CAPACITY_REACHED,
                    "The bounded waiting queue is full",
                )
            attempt = self._attempts.get(run_id, 0) + 1
            self._attempts[run_id] = attempt
            job_id = job_identifier(run_id, attempt)
            state = JobState.STARTING if starts_now else JobState.QUEUED
            job = _MutableJob(
                job_id,
                run_id,
                attempt,
                submission.run_request,
                state,
                CrawlCancellationToken(),
            )
            self._jobs[job_id] = job
            self._counters.accepted_jobs += 1
            self._state = RegistryState.RUNNING
            self._idle.clear()
            if starts_now:
                self._activate(job)
                accepted_snapshot = replace(self._snapshot(job), state=JobState.ACCEPTED)
            else:
                self._queue.append(job_id)
                accepted_snapshot = self._snapshot(job)
            return JobSubmissionResult(
                JobSubmissionOutcome.ACCEPTED,
                accepted_snapshot,
                None,
                "The job was accepted",
                CRAWL_JOB_REGISTRY_VERSION,
            )

    async def lookup(self, job_id: str) -> JobLookupResult:
        async with self._lock:
            job = self._jobs.get(job_id)
            return JobLookupResult(
                JobLookupOutcome.FOUND if job is not None else JobLookupOutcome.NOT_FOUND,
                self._snapshot(job) if job is not None else None,
            )

    async def progress(self, job_id: str) -> JobProgressView:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return JobProgressView(
                    outcome=JobLookupOutcome.NOT_FOUND,
                    latest=None,
                    history=(),
                    history_truncated=False,
                )
            return JobProgressView(
                JobLookupOutcome.FOUND,
                job.latest_progress,
                tuple(job.progress_history),
                job.history_truncated,
            )

    async def result(self, job_id: str) -> JobResultView:
        async with self._lock:
            job = self._jobs.get(job_id)
            return self._result_view(job)

    async def cancel(self, job_id: str) -> JobCancellationResult:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                outcome = (
                    JobCancellationOutcome.REGISTRY_CLOSED
                    if self._state is RegistryState.CLOSED
                    else JobCancellationOutcome.NOT_FOUND
                )
                return JobCancellationResult(outcome, None, "The job is not retained")
            if job.state.terminal:
                return JobCancellationResult(
                    JobCancellationOutcome.ALREADY_TERMINAL,
                    self._snapshot(job),
                    "The job is already terminal",
                )
            if job.cancellation.is_cancelled():
                return JobCancellationResult(
                    JobCancellationOutcome.ALREADY_REQUESTED,
                    self._snapshot(job),
                    "Cancellation was already requested",
                )
            job.cancellation.cancel()
            if job.state is JobState.QUEUED:
                self._queue.remove(job_id)
                job.state = JobState.CANCELLED
                snapshot = self._snapshot(job)
                self._terminalize(job)
                self._start_available()
                return JobCancellationResult(
                    JobCancellationOutcome.CANCELLED_WHILE_QUEUED,
                    snapshot,
                    "The queued job was cancelled before execution",
                )
            job.state = JobState.CANCELLING
            return JobCancellationResult(
                JobCancellationOutcome.REQUESTED,
                self._snapshot(job),
                "Cooperative cancellation was requested",
            )

    async def wait_for_completion(
        self,
        job_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> JobWaitResult:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return JobWaitResult(JobWaitOutcome.NOT_FOUND, None)
            completion = job.completion
        try:
            if timeout_seconds is None:
                await completion.wait()
            else:
                await asyncio.wait_for(completion.wait(), timeout_seconds)
        except TimeoutError:
            return JobWaitResult(JobWaitOutcome.TIMED_OUT, None)
        async with self._lock:
            return JobWaitResult(JobWaitOutcome.COMPLETED, self._result_view(job))

    async def snapshot(self) -> JobRegistrySnapshot:
        async with self._lock:
            return JobRegistrySnapshot(
                self._state,
                self._configuration,
                self._freeze_counters(),
                tuple(self._active),
                tuple(self._queue),
                tuple(self._terminal),
            )

    async def record_progress(self, job_id: str, event: RunProgressEvent) -> None:
        """Record progress without holding the registry lock across run execution."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state.terminal:
                return
            job.latest_progress = event
            if self._configuration.retain_progress_history:
                job.progress_history.append(event)
                limit = self._configuration.maximum_retained_progress_events
                while len(job.progress_history) > limit:
                    job.progress_history.popleft()
                    job.history_truncated = True

    async def record_progress_failure(self, job_id: str, error: Exception) -> None:
        """Retain safe warning evidence without failing the accepted run service."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state.terminal:
                return
            if any(
                warning.code == JobCoordinationFailureCode.PROGRESS_RECORDING_FAILED
                for warning in job.coordination_warnings
            ):
                return
            job.coordination_warnings.append(
                JobCoordinationWarning(
                    JobCoordinationFailureCode.PROGRESS_RECORDING_FAILED,
                    f"Progress recording failed internally ({type(error).__name__})",
                )
            )

    async def shutdown(self) -> JobShutdownResult:
        repeated = False
        async with self._lock:
            if self._state is RegistryState.CLOSED:
                if self._shutdown_result is None:
                    message = "closed registry is missing shutdown evidence"
                    raise RuntimeError(message)
                return replace(self._shutdown_result, repeated=True)
            if self._state is RegistryState.SHUTTING_DOWN:
                repeated = True
            else:
                self._state = RegistryState.SHUTTING_DOWN
                if (
                    self._configuration.shutdown_policy
                    is ShutdownPolicy.CANCEL_QUEUED_AND_REQUEST_ACTIVE
                ):
                    for job_id in tuple(self._queue):
                        job = self._jobs[job_id]
                        job.cancellation.cancel()
                        job.state = JobState.CANCELLED
                        self._terminalize(job)
                        self._shutdown_queued_cancelled += 1
                    self._queue.clear()
                    for job_id in tuple(self._active):
                        job = self._jobs[job_id]
                        if not job.cancellation.is_cancelled():
                            job.cancellation.cancel()
                            self._shutdown_active_requested += 1
                        job.state = JobState.CANCELLING
                if not self._active and not self._queue:
                    self._idle.set()
        await self._idle.wait()
        async with self._lock:
            settling_tasks = tuple(self._tasks.values())
        if settling_tasks:
            await asyncio.gather(*settling_tasks)
        async with self._lock:
            self._state = RegistryState.CLOSED
            result = JobShutdownResult(
                RegistryState.CLOSED,
                self._shutdown_queued_cancelled,
                self._shutdown_active_requested,
                len(self._terminal),
                sum(not task.done() for task in self._tasks.values()),
                repeated,
            )
            self._shutdown_result = result
            return result

    async def _execute(self, job_id: str) -> None:
        try:
            async with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                job.started = True
                if job.state is not JobState.CANCELLING:
                    job.state = JobState.RUNNING
                cancellation = job.cancellation
                request = job.request
            try:
                executor = self._factory(cancellation, _RegistryProgressSink(self, job_id))
                result = await executor.execute(request)
            except Exception as error:  # noqa: BLE001 - one job cannot crash the registry.
                async with self._lock:
                    job = self._jobs.get(job_id)
                    if job is None:
                        return
                    job.coordination_failure = JobCoordinationFailure(
                        JobCoordinationFailureCode.RUN_SERVICE_FAILED,
                        "The run service failed unexpectedly",
                        type(error).__name__,
                    )
                    job.failure_count = 1
                    job.state = JobState.FAILED
                    self._complete(job)
                return
            async with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                job.run_lifecycle = result.lifecycle
                job.warning_count = len(result.warnings) + len(job.coordination_warnings)
                job.failure_count = len(result.failures)
                job.state = _job_state(result.lifecycle)
                if self._configuration.retain_completed_result_payloads:
                    policy = self._configuration.payload_retention_policy
                    if policy is PayloadRetentionPolicy.FULL_RESULT:
                        job.run_result = result
                        job.summaries = result.summaries
                    elif policy is PayloadRetentionPolicy.SUMMARY_ONLY:
                        job.summaries = result.summaries
                self._complete(job)
        finally:
            async with self._lock:
                self._tasks.pop(job_id, None)

    def _activate(self, job: _MutableJob) -> None:
        if job.started or job.job_id in self._tasks:
            message = "job activation attempted more than once"
            raise RuntimeError(message)
        job.state = JobState.STARTING
        self._active[job.job_id] = None
        self._tasks[job.job_id] = asyncio.create_task(self._execute(job.job_id))

    def _start_available(self) -> None:
        if self._state is RegistryState.SHUTTING_DOWN and (
            self._configuration.shutdown_policy is ShutdownPolicy.CANCEL_QUEUED_AND_REQUEST_ACTIVE
        ):
            return
        while self._queue and len(self._active) < self._configuration.maximum_concurrent_jobs:
            job = self._jobs[self._queue.popleft()]
            self._activate(job)

    def _complete(self, job: _MutableJob) -> None:
        self._active.pop(job.job_id, None)
        self._terminalize(job)
        self._start_available()
        if not self._active and not self._queue:
            self._idle.set()

    def _terminalize(self, job: _MutableJob) -> None:
        self._terminal_sequence += 1
        job.terminal_sequence = self._terminal_sequence
        job.completion.set()
        if job.state in {JobState.COMPLETED, JobState.COMPLETED_WITH_WARNINGS}:
            self._counters.completed_jobs += 1
        elif job.state is JobState.CANCELLED:
            self._counters.cancelled_jobs += 1
        elif job.state is JobState.FAILED:
            self._counters.failed_jobs += 1
        elif job.state is JobState.PARTIALLY_COMPLETED:
            self._counters.partially_completed_jobs += 1
        self._terminal.append(job.job_id)
        maximum = self._configuration.maximum_retained_terminal_jobs
        while len(self._terminal) > maximum:
            evicted_id = self._terminal.popleft()
            self._jobs.pop(evicted_id, None)
            self._counters.evicted_jobs += 1

    def _active_duplicate(self, run_id: str) -> _MutableJob | None:
        return next(
            (job for job in self._jobs.values() if job.run_id == run_id and not job.state.terminal),
            None,
        )

    def _snapshot(self, job: _MutableJob) -> JobSnapshot:
        queue_position = self._queue.index(job.job_id) + 1 if job.state is JobState.QUEUED else None
        latest = job.latest_progress.snapshot if job.latest_progress is not None else None
        return JobSnapshot(
            job.job_id,
            job.run_id,
            job.attempt_number,
            job.state,
            queue_position,
            job.run_lifecycle,
            latest.active_stage if latest is not None else None,
            latest,
            job.warning_count,
            job.failure_count,
            job.cancellation.is_cancelled(),
            job.run_result is not None,
            len(job.summaries),
            job.state.terminal,
            CRAWL_JOB_REGISTRY_VERSION,
        )

    def _result_view(self, job: _MutableJob | None) -> JobResultView:
        if job is None:
            return JobResultView(JobLookupOutcome.NOT_FOUND, None, None, ())
        return JobResultView(
            JobLookupOutcome.FOUND,
            self._snapshot(job),
            job.run_result,
            job.summaries,
            tuple(job.coordination_warnings),
            job.coordination_failure,
        )

    def _freeze_counters(self) -> JobRegistryCounters:
        return JobRegistryCounters(
            self._counters.submitted_jobs,
            self._counters.accepted_jobs,
            self._counters.rejected_jobs,
            len(self._active),
            len(self._queue),
            len(self._terminal),
            self._counters.completed_jobs,
            self._counters.cancelled_jobs,
            self._counters.failed_jobs,
            self._counters.partially_completed_jobs,
            self._counters.evicted_jobs,
            self._counters.duplicate_rejections,
            self._counters.queue_capacity_rejections,
        )


def _job_state(lifecycle: RunLifecycle) -> JobState:
    return {
        RunLifecycle.CANCELLED: JobState.CANCELLED,
        RunLifecycle.COMPLETED: JobState.COMPLETED,
        RunLifecycle.COMPLETED_WITH_WARNINGS: JobState.COMPLETED_WITH_WARNINGS,
        RunLifecycle.FAILED: JobState.FAILED,
        RunLifecycle.PARTIALLY_COMPLETED: JobState.PARTIALLY_COMPLETED,
    }.get(lifecycle, JobState.FAILED)


def _submission_failure(
    code: JobSubmissionFailureCode,
    explanation: str,
) -> JobSubmissionResult:
    return JobSubmissionResult(
        JobSubmissionOutcome.REJECTED,
        None,
        code,
        explanation,
        CRAWL_JOB_REGISTRY_VERSION,
    )
