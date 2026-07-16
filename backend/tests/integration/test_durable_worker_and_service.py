"""Single-machine durable worker and job-service integration tests."""

from __future__ import annotations

import asyncio
from functools import wraps
from typing import TYPE_CHECKING

from durable_helpers import durable_configuration, durable_repository
from musimack_tools.domain.durable_execution import DurableJobState, WorkerIdentity, WorkerState
from musimack_tools.domain.job import (
    JobCancellationOutcome,
    JobLookupOutcome,
    JobSubmissionOutcome,
    JobSubmissionRequest,
    JobWaitOutcome,
)
from musimack_tools.durable.service import DurableJobService
from musimack_tools.durable.worker import DurableWorkerService
from persistence_helpers import (
    cleanup_persistence_test_artifacts,  # noqa: F401
    sample_progress,
    sample_request,
    sample_result,
)

_SYNTHETIC_WORKER_FAILURE = "synthetic worker failure"


def run_async[**P](test: Callable[P, Awaitable[None]]) -> Callable[P, None]:
    @wraps(test)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> None:
        asyncio.run(test(*args, **kwargs))

    return wrapper


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from musimack_tools.crawl.cancellation import CancellationToken
    from musimack_tools.domain.run import CrawlRunRequest, CrawlRunResult
    from musimack_tools.run.progress import RunProgressSink


class _Executor:
    def __init__(
        self,
        cancellation: CancellationToken,
        progress: RunProgressSink,
        *,
        gate: asyncio.Event | None = None,
        fail: bool = False,
    ) -> None:
        self.cancellation = cancellation
        self.progress = progress
        self.gate = gate
        self.fail = fail
        self.calls = 0

    async def execute(self, request: CrawlRunRequest) -> CrawlRunResult:
        self.calls += 1
        await self.progress.on_progress(sample_progress())
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise RuntimeError(_SYNTHETIC_WORKER_FAILURE)
        return sample_result(request)


class _Factory:
    def __init__(self, *, gate: asyncio.Event | None = None, fail: bool = False) -> None:
        self.gate = gate
        self.fail = fail
        self.executors: list[_Executor] = []

    def __call__(
        self, cancellation: CancellationToken, progress_sink: RunProgressSink
    ) -> _Executor:
        executor = _Executor(cancellation, progress_sink, gate=self.gate, fail=self.fail)
        self.executors.append(executor)
        return executor


async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


@run_async
async def test_worker_claims_executes_progresses_and_completes(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    factory = _Factory()
    worker = DurableWorkerService(repository, factory)
    try:
        submission = repository.submit(JobSubmissionRequest(sample_request()))
        assert submission.result.snapshot is not None
        job_id = submission.result.snapshot.job_id
        repository.register_worker(WorkerIdentity("worker-test"), 1)
        assert await worker.run_once() == 1
        await _settle()
        status = repository.status(job_id)
        assert status is not None and status.state is DurableJobState.COMPLETED
        assert repository.progress(job_id).latest is not None
        assert len(factory.executors) == 1
    finally:
        await worker.shutdown()
        runtime.dispose()


@run_async
async def test_worker_bounds_concurrency_and_opens_capacity(tmp_path: Path) -> None:
    gate = asyncio.Event()
    configuration = durable_configuration(maximum_concurrent_claimed_jobs=2, maximum_claim_batch=2)
    runtime, repository = durable_repository(tmp_path, configuration=configuration)
    factory = _Factory(gate=gate)
    worker = DurableWorkerService(repository, factory)
    try:
        for path in ("/one", "/two", "/three"):
            repository.submit(JobSubmissionRequest(sample_request(path)))
        repository.register_worker(WorkerIdentity("worker-test"), 2)
        assert await worker.run_once() == 2
        assert await worker.run_once() == 0
        assert len(worker._tasks) == 2  # noqa: SLF001 - bounded worker acceptance evidence.
        gate.set()
        await _settle()
        assert await worker.run_once() == 1
        await _settle()
    finally:
        gate.set()
        await worker.shutdown()
        runtime.dispose()


@run_async
async def test_unexpected_execution_failure_is_mapped_and_queue_survives(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    worker = DurableWorkerService(repository, _Factory(fail=True))
    try:
        submission = repository.submit(JobSubmissionRequest(sample_request()))
        assert submission.result.snapshot is not None
        repository.register_worker(WorkerIdentity("worker-test"), 1)
        await worker.run_once()
        await _settle()
        status = repository.status(submission.result.snapshot.job_id)
        assert status is not None
        assert status.state is DurableJobState.FAILED
        assert status.last_failure_code == "durable_execution_failed"
    finally:
        await worker.shutdown()
        runtime.dispose()


@run_async
async def test_worker_startup_registers_recovers_before_polling_and_is_idempotent(
    tmp_path: Path,
) -> None:
    runtime, repository = durable_repository(tmp_path)
    worker = DurableWorkerService(repository, _Factory())
    try:
        report = await worker.start()
        repeated = await worker.start()
        assert report.worker_id == "worker-test"
        assert report.registered and report.recovery.recovery_complete
        assert report.polling_ready
        assert repeated is report
    finally:
        shutdown = await worker.shutdown()
        assert shutdown.final_state is WorkerState.STOPPED
        runtime.dispose()


@run_async
async def test_worker_shutdown_is_repeatable_and_leaves_no_orphan_tasks(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    worker = DurableWorkerService(repository, _Factory())
    try:
        await worker.start()
        first = await worker.shutdown()
        second = await worker.shutdown()
        assert first.orphan_tasks == 0
        assert not first.repeated
        assert second.repeated
        assert second.final_state is WorkerState.STOPPED
    finally:
        runtime.dispose()


@run_async
async def test_durable_job_service_submits_without_local_task(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    service = DurableJobService(repository)
    try:
        submission = await service.submit(JobSubmissionRequest(sample_request()))
        assert submission.outcome is JobSubmissionOutcome.ACCEPTED
        assert submission.snapshot is not None
        assert repository.status(submission.snapshot.job_id).state is DurableJobState.QUEUED  # type: ignore[union-attr]
        assert not asyncio.all_tasks() - {asyncio.current_task()}
    finally:
        await service.shutdown()
        runtime.dispose()


@run_async
async def test_durable_job_service_status_and_cancellation_survive_restart(tmp_path: Path) -> None:
    configuration = durable_configuration(worker_enabled=False, worker_id=None)
    runtime, repository = durable_repository(tmp_path, configuration=configuration)
    service = DurableJobService(repository)
    submission = await service.submit(JobSubmissionRequest(sample_request()))
    assert submission.snapshot is not None
    job_id = submission.snapshot.job_id
    runtime.dispose()

    runtime, restarted = durable_repository(tmp_path, configuration=configuration)
    restarted_service = DurableJobService(restarted)
    try:
        status = await restarted_service.status(job_id)
        cancellation = await restarted_service.cancel(job_id)
        assert status.outcome is JobLookupOutcome.FOUND
        assert cancellation.outcome is JobCancellationOutcome.CANCELLED_WHILE_QUEUED
    finally:
        await restarted_service.shutdown()
        runtime.dispose()


@run_async
async def test_durable_wait_times_out_without_busy_polling(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)
        await asyncio.sleep(0)

    clock_values = iter((0.0, 0.0, 1.0))
    service = DurableJobService(repository, sleep=sleep, clock=lambda: next(clock_values))
    try:
        submission = await service.submit(JobSubmissionRequest(sample_request()))
        assert submission.snapshot is not None
        result = await service.wait(submission.snapshot.job_id, timeout_seconds=0.5)
        assert result.outcome is JobWaitOutcome.TIMED_OUT
        assert sleeps and set(sleeps) == {repository.configuration.poll_interval_seconds}
    finally:
        await service.shutdown()
        runtime.dispose()


@run_async
async def test_durable_wait_reports_missing_job(tmp_path: Path) -> None:
    runtime, repository = durable_repository(tmp_path)
    service = DurableJobService(repository)
    try:
        assert (await service.wait("job-missing")).outcome is JobWaitOutcome.NOT_FOUND
    finally:
        await service.shutdown()
        runtime.dispose()
