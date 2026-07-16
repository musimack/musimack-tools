"""Job-service compatibility facade over the durable queue authority."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from musimack_tools.domain.job import (
    JobLookupOutcome,
    JobWaitOutcome,
    JobWaitResult,
)
from musimack_tools.domain.job_registry import JobShutdownResult, RegistryState

if TYPE_CHECKING:
    from musimack_tools.domain.job import (
        JobCancellationResult,
        JobLookupResult,
        JobProgressView,
        JobResultView,
        JobSubmissionRequest,
        JobSubmissionResult,
    )
    from musimack_tools.domain.job_registry import JobRegistrySnapshot
    from musimack_tools.durable.worker import DurableWorkerService
    from musimack_tools.persistence.durable_repository import (
        SQLAlchemyDurableExecutionRepository,
    )

Sleep = Callable[[float], Awaitable[None]]
MonotonicClock = Callable[[], float]


class DurableJobService:
    """Persist submissions without creating process-local execution tasks."""

    def __init__(
        self,
        repository: SQLAlchemyDurableExecutionRepository,
        *,
        worker: DurableWorkerService | None = None,
        sleep: Sleep = asyncio.sleep,
        clock: MonotonicClock = time.monotonic,
    ) -> None:
        self._repository = repository
        self._worker = worker
        self._sleep = sleep
        self._clock = clock
        self._closed = False

    async def submit(self, request: JobSubmissionRequest) -> JobSubmissionResult:
        return self._repository.submit(request).result

    async def status(self, job_id: str) -> JobLookupResult:
        return self._repository.lookup(job_id)

    async def progress(self, job_id: str) -> JobProgressView:
        return self._repository.progress(job_id)

    async def result(self, job_id: str) -> JobResultView:
        return self._repository.result(job_id)

    async def cancel(self, job_id: str) -> JobCancellationResult:
        return self._repository.request_cancellation(job_id)

    async def wait(
        self,
        job_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> JobWaitResult:
        started = self._clock()
        while True:
            result = self._repository.result(job_id)
            if result.outcome is JobLookupOutcome.NOT_FOUND:
                return JobWaitResult(JobWaitOutcome.NOT_FOUND, None)
            if result.snapshot is not None and result.snapshot.terminal:
                return JobWaitResult(JobWaitOutcome.COMPLETED, result)
            if timeout_seconds is not None and self._clock() - started >= timeout_seconds:
                return JobWaitResult(JobWaitOutcome.TIMED_OUT, result)
            await self._sleep(self._repository.configuration.poll_interval_seconds)

    async def snapshot(self) -> JobRegistrySnapshot:
        return self._repository.registry_snapshot()

    async def shutdown(self) -> JobShutdownResult:
        if self._closed:
            snapshot = self._repository.registry_snapshot()
            return JobShutdownResult(
                state=RegistryState.CLOSED,
                queued_jobs_cancelled=0,
                active_cancellations_requested=0,
                terminal_jobs_retained=snapshot.counters.terminal_jobs_retained,
                orphan_task_count=0,
                repeated=True,
            )
        self._closed = True
        worker_shutdown = await self._worker.shutdown() if self._worker is not None else None
        snapshot = self._repository.registry_snapshot()
        return JobShutdownResult(
            state=RegistryState.CLOSED,
            queued_jobs_cancelled=0,
            active_cancellations_requested=(
                worker_shutdown.cancellations_requested if worker_shutdown is not None else 0
            ),
            terminal_jobs_retained=snapshot.counters.terminal_jobs_retained,
            orphan_task_count=worker_shutdown.orphan_tasks if worker_shutdown is not None else 0,
            repeated=False,
        )
