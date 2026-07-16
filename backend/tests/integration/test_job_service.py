"""Deterministic in-process job submission, coordination, and retention tests."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING, cast

import pytest

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import create_scope_policy
from musimack_tools.domain.crawl import (
    CrawlConfigurationSnapshot,
    CrawlCounters,
    CrawlRequest,
    CrawlResult,
    CrawlState,
)
from musimack_tools.domain.job import (
    JobCancellationOutcome,
    JobCoordinationFailureCode,
    JobLookupOutcome,
    JobState,
    JobSubmissionFailureCode,
    JobSubmissionOutcome,
    JobSubmissionRequest,
    JobWaitOutcome,
)
from musimack_tools.domain.job_registry import (
    DuplicateSubmissionPolicy,
    JobRegistryConfiguration,
    PayloadRetentionPolicy,
    RegistryState,
    ShutdownPolicy,
)
from musimack_tools.domain.run import (
    CrawlRunRequest,
    CrawlRunResult,
    RunLifecycle,
    RunStage,
    RunStageRecord,
    RunStageState,
)
from musimack_tools.domain.run_progress import (
    RunEventCode,
    RunProgressEvent,
    RunProgressSnapshot,
)
from musimack_tools.domain.run_summary import (
    RunSummaryArtifact,
    RunSummaryConfiguration,
    RunSummaryFormat,
    RunSummaryWriteState,
)
from musimack_tools.domain.sitemap_publication import (
    PublicationMode,
    PublicationState,
    SitemapPublicationConfiguration,
)
from musimack_tools.jobs.registry import InMemoryJobRegistry
from musimack_tools.jobs.service import InternalJobService
from musimack_tools.run.identity import configuration_snapshot, run_identity
from musimack_tools.run.service import CrawlRunService

if TYPE_CHECKING:
    from pathlib import Path

    from musimack_tools.crawl.cancellation import CancellationToken
    from musimack_tools.crawl.orchestrator import ProgressObserver
    from musimack_tools.run.progress import RunProgressSink


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _request(path: str = "/") -> CrawlRunRequest:
    seed = normalize_url(f"https://example.com{path}")
    return CrawlRunRequest(
        CrawlRequest(seed, create_scope_policy(seed), maximum_unique_urls=10),
        (RunStage.CRAWL, RunStage.WRITE_SUMMARY),
    )


def _accepted_request(
    stages: tuple[RunStage, ...],
    *,
    publication: SitemapPublicationConfiguration | None = None,
    summary: RunSummaryConfiguration | None = None,
) -> CrawlRunRequest:
    seed = normalize_url("https://example.com/")
    return CrawlRunRequest(
        CrawlRequest(seed, create_scope_policy(seed), maximum_unique_urls=10),
        stages,
        publication_configuration=publication,
        summary_configuration=summary,
    )


def _run_result(request: CrawlRunRequest, lifecycle: RunLifecycle) -> CrawlRunResult:
    run_id, digest = run_identity(request)
    crawl_state = {
        RunLifecycle.CANCELLED: RunStageState.CANCELLED,
        RunLifecycle.FAILED: RunStageState.FAILED,
    }.get(lifecycle, RunStageState.COMPLETED)
    artifact = RunSummaryArtifact(
        "run-summary.json",
        RunSummaryFormat.JSON,
        b"{}\n",
        3,
        "a" * 64,
    )
    return CrawlRunResult(
        run_id=run_id,
        run_digest=digest,
        caller_label=request.caller_label,
        lifecycle=lifecycle,
        stages=tuple(
            RunStageRecord(
                stage,
                crawl_state
                if stage is RunStage.CRAWL
                else RunStageState.COMPLETED
                if stage is RunStage.WRITE_SUMMARY
                else RunStageState.NOT_REQUESTED,
            )
            for stage in RunStage
        ),
        configuration=configuration_snapshot(request),
        summaries=(artifact,),
    )


def _events() -> tuple[RunProgressEvent, ...]:
    first = RunProgressEvent(
        1,
        RunEventCode.CRAWL_PROGRESS,
        RunProgressSnapshot(
            RunLifecycle.RUNNING,
            RunStage.CRAWL,
            RunStageState.RUNNING,
            urls_discovered=1,
        ),
        "progress",
    )
    third = RunProgressEvent(
        2,
        RunEventCode.CRAWL_PROGRESS,
        RunProgressSnapshot(
            RunLifecycle.RUNNING,
            RunStage.CRAWL,
            RunStageState.RUNNING,
            urls_discovered=2,
        ),
        "progress",
    )
    return first, first, third


class _ControlledExecutor:
    def __init__(
        self,
        owner: _ControlledFactory,
        cancellation: CancellationToken,
        sink: RunProgressSink,
        release: asyncio.Event,
        execution_number: int,
    ) -> None:
        self._owner = owner
        self._cancellation = cancellation
        self._sink = sink
        self._release = release
        self._execution_number = execution_number

    async def execute(self, request: CrawlRunRequest) -> CrawlRunResult:
        async with self._owner.condition:
            self._owner.started_requests.append(request)
            self._owner.active += 1
            self._owner.maximum_active = max(self._owner.maximum_active, self._owner.active)
            self._owner.condition.notify_all()
        try:
            for event in _events():
                await self._sink.on_progress(event)
            if self._owner.auto_release:
                self._release.set()
            await self._release.wait()
            if self._execution_number in self._owner.fail_executions:
                message = "private executor failure"
                raise RuntimeError(message)
            lifecycle = (
                RunLifecycle.CANCELLED
                if self._cancellation.is_cancelled()
                else self._owner.lifecycle
            )
            return _run_result(request, lifecycle)
        finally:
            async with self._owner.condition:
                self._owner.active -= 1
                self._owner.condition.notify_all()


class _ControlledFactory:
    def __init__(
        self,
        *,
        auto_release: bool = False,
        lifecycle: RunLifecycle = RunLifecycle.COMPLETED,
        fail_executions: frozenset[int] = frozenset(),
    ) -> None:
        self.auto_release = auto_release
        self.lifecycle = lifecycle
        self.fail_executions = fail_executions
        self.condition = asyncio.Condition()
        self.started_requests: list[CrawlRunRequest] = []
        self.releases: list[asyncio.Event] = []
        self.tokens: list[CancellationToken] = []
        self.active = 0
        self.maximum_active = 0

    def __call__(
        self,
        cancellation: CancellationToken,
        progress_sink: RunProgressSink,
    ) -> _ControlledExecutor:
        release = asyncio.Event()
        self.releases.append(release)
        self.tokens.append(cancellation)
        return _ControlledExecutor(
            self,
            cancellation,
            progress_sink,
            release,
            len(self.releases),
        )

    async def wait_started(self, count: int) -> None:
        async with self.condition:
            await self.condition.wait_for(lambda: len(self.started_requests) >= count)

    def release(self, index: int) -> None:
        self.releases[index].set()

    def release_all(self) -> None:
        for release in self.releases:
            release.set()


class _FakeCrawler:
    async def crawl(
        self,
        request: CrawlRequest,
        *,
        observer: ProgressObserver | None = None,
    ) -> CrawlResult:
        del observer
        return CrawlResult(
            seed_url=request.seed_url.normalized,
            scope_policy=request.scope_policy,
            started_at_seconds=0,
            ended_at_seconds=1,
            duration_seconds=1,
            state=CrawlState.COMPLETED,
            url_records=(),
            discoveries=(),
            counters=CrawlCounters(unique_urls_discovered=1, urls_queued=1, urls_fetched=1),
            limit_events=(),
            errors=(),
            cancellation=None,
            total_accepted_bytes=0,
            maximum_observed_queue_size=1,
            maximum_active_worker_count=1,
            configuration=CrawlConfigurationSnapshot(
                maximum_unique_urls=request.maximum_unique_urls,
                maximum_depth=request.maximum_depth,
                maximum_duration_seconds=request.maximum_duration_seconds,
                maximum_total_fetched_bytes=request.maximum_total_fetched_bytes,
                maximum_concurrent_fetches=request.maximum_concurrent_fetches,
                maximum_queued_urls=request.maximum_queued_urls,
                minimum_per_origin_delay_seconds=request.minimum_per_origin_delay_seconds,
                query_urls_allowed=request.query_urls_allowed,
                exclusion_rules=request.exclusion_rules,
            ),
        )


def _accepted_service_factory(
    cancellation: CancellationToken,
    progress_sink: RunProgressSink,
) -> CrawlRunService:
    return CrawlRunService(
        _FakeCrawler(),
        cancellation=cancellation,
        progress_sink=progress_sink,
    )


class _ProgressFailingRegistry(InMemoryJobRegistry):
    async def record_progress(self, job_id: str, event: RunProgressEvent) -> None:
        del job_id, event
        message = "private progress storage detail"
        raise RuntimeError(message)


def _service(
    factory: _ControlledFactory,
    configuration: JobRegistryConfiguration | None = None,
) -> InternalJobService:
    return InternalJobService(InMemoryJobRegistry(factory, configuration))


async def _submit(service: InternalJobService, request: CrawlRunRequest) -> str:
    result = await service.submit(JobSubmissionRequest(request))
    assert result.outcome is JobSubmissionOutcome.ACCEPTED
    assert result.snapshot is not None
    return result.snapshot.job_id


@pytest.mark.anyio
async def test_immediate_execution_and_wait_retains_full_result() -> None:
    factory = _ControlledFactory(auto_release=True)
    service = _service(factory)
    submission = await service.submit(JobSubmissionRequest(_request()))
    assert submission.snapshot is not None
    assert submission.snapshot.state is JobState.ACCEPTED
    assert submission.snapshot.queue_position is None
    job_id = submission.snapshot.job_id
    waited = await service.wait(job_id)
    assert waited.outcome is JobWaitOutcome.COMPLETED
    assert waited.result is not None
    assert waited.result.snapshot is not None
    assert waited.result.snapshot.state is JobState.COMPLETED
    assert waited.result.full_result is not None
    assert factory.maximum_active == 1
    await service.shutdown()


@pytest.mark.anyio
async def test_concurrency_limit_and_fifo_queue_positions() -> None:
    factory = _ControlledFactory()
    service = _service(factory, JobRegistryConfiguration(maximum_concurrent_jobs=1))
    first = await _submit(service, _request("/one"))
    second = await _submit(service, _request("/two"))
    third = await _submit(service, _request("/three"))
    await factory.wait_started(1)
    second_status = await service.status(second)
    third_status = await service.status(third)
    assert second_status.snapshot is not None and second_status.snapshot.queue_position == 1
    assert third_status.snapshot is not None and third_status.snapshot.queue_position == 2
    factory.release(0)
    await factory.wait_started(2)
    assert factory.started_requests[1].crawl_request.seed_url.normalized.endswith("/two")
    factory.release(1)
    await factory.wait_started(3)
    assert factory.started_requests[2].crawl_request.seed_url.normalized.endswith("/three")
    factory.release(2)
    await service.wait(third)
    assert factory.maximum_active == 1
    assert (await service.status(first)).snapshot is not None
    await service.shutdown()


@pytest.mark.anyio
async def test_two_active_jobs_and_queued_third() -> None:
    factory = _ControlledFactory()
    service = _service(factory, JobRegistryConfiguration(maximum_concurrent_jobs=2))
    jobs = [await _submit(service, _request(f"/{index}")) for index in range(3)]
    await factory.wait_started(2)
    snapshot = await service.snapshot()
    assert snapshot.counters.active_jobs == 2
    assert snapshot.queued_job_ids == (jobs[2],)
    factory.release(0)
    await factory.wait_started(3)
    factory.release(1)
    factory.release(2)
    await service.wait(jobs[2])
    assert factory.maximum_active == 2
    await service.shutdown()


@pytest.mark.anyio
async def test_queue_capacity_rejection_does_not_allocate_attempt() -> None:
    factory = _ControlledFactory()
    service = _service(
        factory,
        JobRegistryConfiguration(maximum_concurrent_jobs=1, maximum_queued_jobs=0),
    )
    first = await _submit(service, _request("/one"))
    rejected = await service.submit(JobSubmissionRequest(_request("/two")))
    assert rejected.failure_code is JobSubmissionFailureCode.QUEUE_CAPACITY_REACHED
    snapshot = await service.snapshot()
    assert snapshot.counters.queue_capacity_rejections == 1
    await factory.wait_started(1)
    factory.release(0)
    await service.wait(first)
    await service.shutdown()


@pytest.mark.anyio
async def test_invalid_request_returns_typed_rejection() -> None:
    service = _service(_ControlledFactory())
    invalid = cast("CrawlRunRequest", object())
    result = await service.submit(JobSubmissionRequest(invalid))
    assert result.failure_code is JobSubmissionFailureCode.INVALID_REQUEST
    assert result.snapshot is None
    await service.shutdown()


@pytest.mark.anyio
async def test_allow_duplicate_allocates_sequential_attempts() -> None:
    factory = _ControlledFactory()
    configuration = JobRegistryConfiguration(
        maximum_concurrent_jobs=2,
        duplicate_policy=DuplicateSubmissionPolicy.ALLOW,
    )
    service = _service(factory, configuration)
    first = await _submit(service, _request())
    second = await _submit(service, _request())
    assert first.endswith("-0001")
    assert second.endswith("-0002")
    await factory.wait_started(2)
    factory.release_all()
    await service.wait(second)
    await service.shutdown()


@pytest.mark.anyio
async def test_reject_active_duplicate_is_concurrency_safe() -> None:
    factory = _ControlledFactory()
    service = _service(factory)
    results = await asyncio.gather(
        service.submit(JobSubmissionRequest(_request())),
        service.submit(JobSubmissionRequest(_request())),
    )
    assert sum(item.outcome is JobSubmissionOutcome.ACCEPTED for item in results) == 1
    assert (
        sum(item.failure_code is JobSubmissionFailureCode.ACTIVE_DUPLICATE for item in results) == 1
    )
    await factory.wait_started(1)
    factory.release_all()
    accepted = next(item for item in results if item.snapshot is not None)
    assert accepted.snapshot is not None
    await service.wait(accepted.snapshot.job_id)
    await service.shutdown()


@pytest.mark.anyio
async def test_return_active_duplicate_returns_same_job() -> None:
    factory = _ControlledFactory()
    service = _service(
        factory,
        JobRegistryConfiguration(
            duplicate_policy=DuplicateSubmissionPolicy.RETURN_ACTIVE_DUPLICATE
        ),
    )
    first = await service.submit(JobSubmissionRequest(_request()))
    second = await service.submit(JobSubmissionRequest(_request()))
    assert second.outcome is JobSubmissionOutcome.DUPLICATE_RETURNED
    assert first.snapshot is not None and second.snapshot is not None
    assert first.snapshot.job_id == second.snapshot.job_id
    await factory.wait_started(1)
    factory.release_all()
    await service.wait(first.snapshot.job_id)
    await service.shutdown()


@pytest.mark.anyio
async def test_terminal_attempt_does_not_block_new_submission() -> None:
    factory = _ControlledFactory(auto_release=True)
    service = _service(factory)
    first = await _submit(service, _request())
    await service.wait(first)
    second = await _submit(service, _request())
    assert second.endswith("-0002")
    await service.wait(second)
    await service.shutdown()


@pytest.mark.anyio
async def test_queued_cancellation_recomputes_positions_and_never_starts_job() -> None:
    factory = _ControlledFactory()
    service = _service(factory, JobRegistryConfiguration(maximum_concurrent_jobs=1))
    first = await _submit(service, _request("/one"))
    second = await _submit(service, _request("/two"))
    third = await _submit(service, _request("/three"))
    cancellation = await service.cancel(second)
    assert cancellation.outcome is JobCancellationOutcome.CANCELLED_WHILE_QUEUED
    third_status = await service.status(third)
    assert third_status.snapshot is not None and third_status.snapshot.queue_position == 1
    await factory.wait_started(1)
    factory.release(0)
    await factory.wait_started(2)
    assert all(
        not item.crawl_request.seed_url.normalized.endswith("/two")
        for item in factory.started_requests
    )
    factory.release(1)
    await service.wait(third)
    assert (await service.status(first)).outcome is JobLookupOutcome.FOUND
    await service.shutdown()


@pytest.mark.anyio
async def test_active_cancellation_is_idempotent_and_uses_registered_token() -> None:
    factory = _ControlledFactory()
    service = _service(factory)
    job_id = await _submit(service, _request())
    await factory.wait_started(1)
    first = await service.cancel(job_id)
    second = await service.cancel(job_id)
    assert first.outcome is JobCancellationOutcome.REQUESTED
    assert second.outcome is JobCancellationOutcome.ALREADY_REQUESTED
    assert factory.tokens[0].is_cancelled()
    factory.release(0)
    waited = await service.wait(job_id)
    assert waited.result is not None and waited.result.snapshot is not None
    assert waited.result.snapshot.state is JobState.CANCELLED
    terminal = await service.cancel(job_id)
    assert terminal.outcome is JobCancellationOutcome.ALREADY_TERMINAL
    await service.shutdown()


@pytest.mark.anyio
async def test_progress_latest_and_bounded_history_preserve_duplicates() -> None:
    factory = _ControlledFactory()
    service = _service(
        factory,
        JobRegistryConfiguration(
            retain_progress_history=True,
            maximum_retained_progress_events=2,
        ),
    )
    job_id = await _submit(service, _request())
    await factory.wait_started(1)
    view = await service.progress(job_id)
    assert view.outcome is JobLookupOutcome.FOUND
    assert view.latest == _events()[-1]
    assert view.history == _events()[-2:]
    assert view.history_truncated
    with pytest.raises(FrozenInstanceError):
        view.history_truncated = False  # type: ignore[misc]
    factory.release(0)
    await service.wait(job_id)
    await service.shutdown()


@pytest.mark.anyio
async def test_progress_history_disabled_retains_latest_separately() -> None:
    factory = _ControlledFactory()
    service = _service(factory)
    job_id = await _submit(service, _request())
    await factory.wait_started(1)
    view = await service.progress(job_id)
    assert view.latest is not None
    assert view.history == ()
    factory.release(0)
    await service.wait(job_id)
    await service.shutdown()


@pytest.mark.anyio
async def test_registry_progress_failure_is_isolated_as_safe_warning() -> None:
    factory = _ControlledFactory(auto_release=True)
    service = InternalJobService(_ProgressFailingRegistry(factory))
    job_id = await _submit(service, _request())
    waited = await service.wait(job_id)
    assert waited.result is not None
    assert waited.result.snapshot is not None
    assert waited.result.snapshot.state is JobState.COMPLETED
    assert waited.result.snapshot.warning_count == 1
    assert len(waited.result.coordination_warnings) == 1
    assert all(
        warning.code is JobCoordinationFailureCode.PROGRESS_RECORDING_FAILED
        for warning in waited.result.coordination_warnings
    )
    assert all(
        "private progress storage detail" not in warning.explanation
        for warning in waited.result.coordination_warnings
    )
    await service.shutdown()


@pytest.mark.anyio
async def test_concurrent_status_and_progress_lookup_does_not_deadlock_delivery() -> None:
    factory = _ControlledFactory()
    service = _service(factory)
    job_id = await _submit(service, _request())
    await factory.wait_started(1)
    statuses = await asyncio.gather(*(service.status(job_id) for _index in range(25)))
    progress_views = await asyncio.gather(*(service.progress(job_id) for _index in range(25)))
    assert all(item.outcome is JobLookupOutcome.FOUND for item in statuses)
    assert all(item.outcome is JobLookupOutcome.FOUND for item in progress_views)
    factory.release(0)
    await service.wait(job_id)
    await service.shutdown()


@pytest.mark.anyio
async def test_wait_timeout_does_not_cancel_job_and_multiple_waiters_complete() -> None:
    factory = _ControlledFactory()
    service = _service(factory)
    job_id = await _submit(service, _request())
    timed_out = await service.wait(job_id, timeout_seconds=0)
    assert timed_out.outcome is JobWaitOutcome.TIMED_OUT
    status = await service.status(job_id)
    assert status.snapshot is not None and not status.snapshot.cancellation_requested
    waiters = [asyncio.create_task(service.wait(job_id)) for _index in range(2)]
    await factory.wait_started(1)
    factory.release(0)
    results = await asyncio.gather(*waiters)
    assert all(item.outcome is JobWaitOutcome.COMPLETED for item in results)
    await service.shutdown()


@pytest.mark.anyio
async def test_oldest_terminal_is_evicted_deterministically() -> None:
    factory = _ControlledFactory(auto_release=True)
    service = _service(
        factory,
        JobRegistryConfiguration(maximum_retained_terminal_jobs=1),
    )
    first = await _submit(service, _request("/one"))
    await service.wait(first)
    second = await _submit(service, _request("/two"))
    await service.wait(second)
    assert (await service.status(first)).outcome is JobLookupOutcome.NOT_FOUND
    assert (await service.status(second)).outcome is JobLookupOutcome.FOUND
    snapshot = await service.snapshot()
    assert snapshot.retained_terminal_job_ids == (second,)
    assert snapshot.counters.evicted_jobs == 1
    await service.shutdown()


@pytest.mark.anyio
async def test_zero_retention_removes_terminal_lookup() -> None:
    factory = _ControlledFactory(auto_release=True)
    service = _service(
        factory,
        JobRegistryConfiguration(maximum_retained_terminal_jobs=0),
    )
    job_id = await _submit(service, _request())
    waited = await service.wait(job_id)
    assert waited.outcome is JobWaitOutcome.COMPLETED
    assert (await service.status(job_id)).outcome is JobLookupOutcome.NOT_FOUND
    await service.shutdown()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("policy", "full", "summary_count"),
    [
        (PayloadRetentionPolicy.FULL_RESULT, True, 1),
        (PayloadRetentionPolicy.SUMMARY_ONLY, False, 1),
        (PayloadRetentionPolicy.METADATA_ONLY, False, 0),
    ],
)
async def test_payload_retention_policies(
    policy: PayloadRetentionPolicy,
    full: bool,  # noqa: FBT001 - parameterized contract expectation.
    summary_count: int,
) -> None:
    factory = _ControlledFactory(auto_release=True)
    service = _service(
        factory,
        JobRegistryConfiguration(payload_retention_policy=policy),
    )
    job_id = await _submit(service, _request())
    await service.wait(job_id)
    view = await service.result(job_id)
    assert (view.full_result is not None) is full
    assert len(view.summaries) == summary_count
    assert view.snapshot is not None and view.snapshot.state is JobState.COMPLETED
    await service.shutdown()


@pytest.mark.anyio
async def test_disabled_result_payload_retention_overrides_full_policy() -> None:
    factory = _ControlledFactory(auto_release=True)
    service = _service(
        factory,
        JobRegistryConfiguration(retain_completed_result_payloads=False),
    )
    job_id = await _submit(service, _request())
    await service.wait(job_id)
    view = await service.result(job_id)
    assert view.snapshot is not None and view.snapshot.state is JobState.COMPLETED
    assert not view.snapshot.final_result_available
    assert view.full_result is None
    assert view.summaries == ()
    await service.shutdown()


@pytest.mark.anyio
async def test_unexpected_run_failure_is_typed_and_next_job_starts() -> None:
    factory = _ControlledFactory(fail_executions=frozenset({1}))
    service = _service(factory, JobRegistryConfiguration(maximum_concurrent_jobs=1))
    first = await _submit(service, _request("/one"))
    second = await _submit(service, _request("/two"))
    await factory.wait_started(1)
    factory.release(0)
    first_result = await service.wait(first)
    assert first_result.result is not None and first_result.result.snapshot is not None
    assert first_result.result.snapshot.state is JobState.FAILED
    assert first_result.result.coordination_failure is not None
    assert (
        first_result.result.coordination_failure.code
        is JobCoordinationFailureCode.RUN_SERVICE_FAILED
    )
    assert "private executor failure" not in first_result.result.coordination_failure.explanation
    await factory.wait_started(2)
    factory.release(1)
    second_result = await service.wait(second)
    assert second_result.result is not None and second_result.result.snapshot is not None
    assert second_result.result.snapshot.state is JobState.COMPLETED
    await service.shutdown()


@pytest.mark.anyio
async def test_shutdown_cancels_queue_requests_active_and_rejects_submission() -> None:
    factory = _ControlledFactory()
    service = _service(factory, JobRegistryConfiguration(maximum_concurrent_jobs=1))
    active = await _submit(service, _request("/active"))
    queued = await _submit(service, _request("/queued"))
    await factory.wait_started(1)
    shutdown_task = asyncio.create_task(service.shutdown())
    await asyncio.sleep(0)
    assert factory.tokens[0].is_cancelled()
    factory.release(0)
    shutdown = await shutdown_task
    assert shutdown.state is RegistryState.CLOSED
    assert shutdown.queued_jobs_cancelled == 1
    assert shutdown.active_cancellations_requested == 1
    assert shutdown.orphan_task_count == 0
    assert (await service.status(queued)).snapshot is not None
    assert (await service.status(active)).snapshot is not None
    rejected = await service.submit(JobSubmissionRequest(_request("/later")))
    assert rejected.failure_code is JobSubmissionFailureCode.REGISTRY_CLOSED
    repeated = await service.shutdown()
    assert repeated.repeated


@pytest.mark.anyio
async def test_wait_for_active_shutdown_drains_fifo_queue() -> None:
    factory = _ControlledFactory()
    service = _service(
        factory,
        JobRegistryConfiguration(
            maximum_concurrent_jobs=1,
            shutdown_policy=ShutdownPolicy.WAIT_FOR_ACTIVE,
        ),
    )
    first = await _submit(service, _request("/one"))
    second = await _submit(service, _request("/two"))
    shutdown_task = asyncio.create_task(service.shutdown())
    await factory.wait_started(1)
    factory.release(0)
    await factory.wait_started(2)
    factory.release(1)
    result = await shutdown_task
    assert result.state is RegistryState.CLOSED
    assert (await service.status(first)).snapshot is not None
    assert (await service.status(second)).snapshot is not None


@pytest.mark.anyio
async def test_unknown_lookup_cancel_progress_result_and_wait_are_typed() -> None:
    service = _service(_ControlledFactory(auto_release=True))
    assert (await service.status("missing")).outcome is JobLookupOutcome.NOT_FOUND
    assert (await service.progress("missing")).outcome is JobLookupOutcome.NOT_FOUND
    assert (await service.result("missing")).outcome is JobLookupOutcome.NOT_FOUND
    assert (await service.cancel("missing")).outcome is JobCancellationOutcome.NOT_FOUND
    assert (await service.wait("missing")).outcome is JobWaitOutcome.NOT_FOUND
    await service.shutdown()
    assert (await service.cancel("missing")).outcome is JobCancellationOutcome.REGISTRY_CLOSED


@pytest.mark.anyio
async def test_registry_snapshot_contains_no_tokens_tasks_or_locks() -> None:
    factory = _ControlledFactory(auto_release=True)
    service = _service(factory)
    job_id = await _submit(service, _request())
    await service.wait(job_id)
    snapshot = await service.snapshot()
    assert snapshot.counters.submitted_jobs == 1
    assert snapshot.counters.accepted_jobs == 1
    assert snapshot.counters.active_jobs == 0
    assert snapshot.counters.queued_jobs == 0
    assert "Task" not in repr(snapshot)
    assert "Lock" not in repr(snapshot)
    assert "Token" not in repr(snapshot)
    await service.shutdown()


@pytest.mark.anyio
async def test_job_service_composes_the_accepted_crawl_run_service() -> None:
    service = InternalJobService(InMemoryJobRegistry(_accepted_service_factory))
    job_id = await _submit(service, _accepted_request((RunStage.CRAWL,)))
    waited = await service.wait(job_id)
    assert waited.outcome is JobWaitOutcome.COMPLETED
    assert waited.result is not None and waited.result.full_result is not None
    assert waited.result.full_result.lifecycle is RunLifecycle.COMPLETED
    assert waited.result.full_result.crawl_result is not None
    assert waited.result.summaries == ()
    await service.shutdown()


@pytest.mark.anyio
async def test_job_service_composes_full_dry_run_without_writing(tmp_path: Path) -> None:
    service = InternalJobService(InMemoryJobRegistry(_accepted_service_factory))
    request = _accepted_request(
        (RunStage.CRAWL, RunStage.RECOMMEND, RunStage.GENERATE_XML, RunStage.PUBLISH),
        publication=SitemapPublicationConfiguration(tmp_path, mode=PublicationMode.DRY_RUN),
    )
    job_id = await _submit(service, request)
    waited = await service.wait(job_id)
    assert waited.result is not None and waited.result.full_result is not None
    publication = waited.result.full_result.publication_result
    assert publication is not None and publication.state is PublicationState.DRY_RUN
    assert tuple(tmp_path.iterdir()) == ()
    await service.shutdown()


@pytest.mark.anyio
async def test_job_service_composes_full_publication_and_summary(tmp_path: Path) -> None:
    publication_root = tmp_path / "sitemap"
    summary_root = tmp_path / "summary"
    service = InternalJobService(InMemoryJobRegistry(_accepted_service_factory))
    request = _accepted_request(
        (
            RunStage.CRAWL,
            RunStage.RECOMMEND,
            RunStage.GENERATE_XML,
            RunStage.PUBLISH,
            RunStage.WRITE_SUMMARY,
        ),
        publication=SitemapPublicationConfiguration(
            publication_root,
            create_output_directory=True,
        ),
        summary=RunSummaryConfiguration(summary_root, create_output_directory=True),
    )
    job_id = await _submit(service, request)
    waited = await service.wait(job_id)
    assert waited.result is not None and waited.result.full_result is not None
    result = waited.result.full_result
    assert result.lifecycle is RunLifecycle.COMPLETED
    assert result.publication_result is not None
    assert result.publication_result.state is PublicationState.PUBLISHED
    assert result.summary_write_result is not None
    assert result.summary_write_result.state is RunSummaryWriteState.WRITTEN
    assert (publication_root / "sitemap.xml").exists()
    assert (summary_root / "run-summary.json").exists()
    await service.shutdown()
