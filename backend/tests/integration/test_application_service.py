"""End-to-end internal application facade tests with controlled accepted services."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from musimack_tools.application.profiles import APPLICATION_HARD_MAXIMA
from musimack_tools.application.service import SeoToolkitApplicationService
from musimack_tools.domain.application import (
    ApplicationOutcomeCode,
    ApplicationServiceConfiguration,
    CrawlProfileName,
    PreflightCode,
    PreflightState,
    RawApplicationCrawlRequest,
    ReadinessState,
)
from musimack_tools.domain.crawl import (
    CrawlConfigurationSnapshot,
    CrawlCounters,
    CrawlRequest,
    CrawlResult,
    CrawlState,
)
from musimack_tools.domain.job_registry import (
    DuplicateSubmissionPolicy,
    JobRegistryConfiguration,
    PayloadRetentionPolicy,
)
from musimack_tools.domain.run import CrawlRunRequest, CrawlRunResult, RunLifecycle
from musimack_tools.domain.sitemap_publication import PublicationState
from musimack_tools.jobs.registry import InMemoryJobRegistry
from musimack_tools.jobs.service import InternalJobService
from musimack_tools.run.service import CrawlRunService

if TYPE_CHECKING:
    from pathlib import Path

    from musimack_tools.crawl.cancellation import CancellationToken
    from musimack_tools.crawl.orchestrator import ProgressObserver
    from musimack_tools.run.progress import RunProgressSink


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _FakeCrawler:
    async def crawl(
        self,
        request: CrawlRequest,
        *,
        observer: ProgressObserver | None = None,
    ) -> CrawlResult:
        del observer
        return _crawl_result(request)


def _run_factory(
    cancellation: CancellationToken,
    progress_sink: RunProgressSink,
) -> CrawlRunService:
    return CrawlRunService(
        _FakeCrawler(),
        cancellation=cancellation,
        progress_sink=progress_sink,
    )


class _BlockingExecutor:
    def __init__(
        self,
        factory: _BlockingFactory,
        release: asyncio.Event,
        cancellation: CancellationToken,
        progress_sink: RunProgressSink,
    ) -> None:
        self._factory = factory
        self._release = release
        self._cancellation = cancellation
        self._progress_sink = progress_sink

    async def execute(self, request: CrawlRunRequest) -> CrawlRunResult:
        self._factory.started += 1
        self._factory.started_event.set()
        await self._release.wait()
        return await CrawlRunService(
            _FakeCrawler(),
            cancellation=self._cancellation,
            progress_sink=self._progress_sink,
        ).execute(request)


class _BlockingFactory:
    def __init__(self) -> None:
        self.started = 0
        self.started_event = asyncio.Event()
        self.releases: list[asyncio.Event] = []

    def __call__(
        self,
        cancellation: CancellationToken,
        progress_sink: RunProgressSink,
    ) -> _BlockingExecutor:
        release = asyncio.Event()
        self.releases.append(release)
        return _BlockingExecutor(self, release, cancellation, progress_sink)

    async def wait_started(self, count: int) -> None:
        while self.started < count:
            await self.started_event.wait()
            self.started_event.clear()


def _application(
    factory: object = _run_factory,
    registry_configuration: JobRegistryConfiguration | None = None,
    application_configuration: ApplicationServiceConfiguration | None = None,
) -> SeoToolkitApplicationService:
    registry = InMemoryJobRegistry(factory, registry_configuration)  # type: ignore[arg-type]
    return SeoToolkitApplicationService(
        InternalJobService(registry),
        application_configuration,
    )


def _crawl_result(request: CrawlRequest) -> CrawlResult:
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
        total_accepted_bytes=10,
        maximum_observed_queue_size=1,
        maximum_active_worker_count=1,
        configuration=CrawlConfigurationSnapshot(
            request.maximum_unique_urls,
            request.maximum_depth,
            request.maximum_duration_seconds,
            request.maximum_total_fetched_bytes,
            request.maximum_concurrent_fetches,
            request.maximum_queued_urls,
            request.minimum_per_origin_delay_seconds,
            request.query_urls_allowed,
            request.exclusion_rules,
        ),
    )


@pytest.mark.anyio
async def test_validate_preflight_submit_status_result_and_diagnostics() -> None:
    application = _application()
    raw = RawApplicationCrawlRequest(
        "HTTPS://EXAMPLE.COM",
        crawl_profile=CrawlProfileName.QUICK_AUDIT,
    )
    validation = application.validate_request(raw)
    assert validation.valid
    preflight = await application.preflight(raw)
    assert preflight.state is PreflightState.READY
    assert preflight.registry_snapshot.counters.submitted_jobs == 0
    submitted = await application.submit(raw)
    assert submitted.outcome is ApplicationOutcomeCode.ACCEPTED
    assert submitted.status is not None and submitted.status.job_id is not None
    projected = await application.wait_for_result(submitted.status.job_id)
    assert projected.outcome is ApplicationOutcomeCode.FOUND
    assert projected.run_lifecycle == RunLifecycle.COMPLETED
    assert dict(projected.crawl_counts)["urls_fetched"] == 1
    status = await application.get_job_status(submitted.status.job_id)
    assert status.terminal
    listed = await application.list_jobs()
    assert [item.job_id for item in listed.items] == [submitted.status.job_id]
    assert not listed.truncated
    recommendations = await application.get_job_recommendations(
        submitted.status.job_id,
        offset=0,
        limit=25,
        state="include",
        text="example",
    )
    assert recommendations.outcome is ApplicationOutcomeCode.FOUND
    assert recommendations.total == 0
    assert recommendations.items == ()
    missing = await application.get_job_recommendations("missing", offset=0, limit=25)
    assert missing.outcome is ApplicationOutcomeCode.JOB_NOT_FOUND
    assert b'"job_id"' in application.diagnostics_json(status).content
    assert application.diagnostics_markdown(projected, "Result").content.endswith(b"\n")
    await application.shutdown()


@pytest.mark.anyio
async def test_invalid_request_never_submits() -> None:
    application = _application()
    result = await application.submit(RawApplicationCrawlRequest("not-a-url"))
    assert result.outcome is ApplicationOutcomeCode.VALIDATION_FAILED
    registry = await application.get_registry_status()
    assert registry.snapshot.counters.submitted_jobs == 0
    await application.shutdown()


@pytest.mark.anyio
async def test_preflight_is_advisory_and_allocates_no_attempt_or_queue_slot() -> None:
    application = _application()
    raw = RawApplicationCrawlRequest("https://example.com")
    first = await application.preflight(raw)
    second = await application.preflight(raw)
    assert first == second
    assert first.registry_snapshot.counters.submitted_jobs == 0
    assert first.registry_snapshot.queued_job_ids == ()
    assert PreflightCode.ADVISORY_ONLY in {item.code for item in first.findings}
    submitted = await application.submit(raw)
    assert submitted.status is not None and submitted.status.job_id is not None
    assert submitted.status.job_id.endswith("-0001")
    await application.wait_for_result(submitted.status.job_id)
    await application.shutdown()


@pytest.mark.anyio
async def test_fifo_queue_preflight_duplicate_capacity_and_queued_cancellation() -> None:
    factory = _BlockingFactory()
    application = _application(
        factory,
        JobRegistryConfiguration(maximum_concurrent_jobs=1, maximum_queued_jobs=1),
    )
    first_raw = RawApplicationCrawlRequest(
        "https://example.com/one",
        crawl_profile=CrawlProfileName.QUICK_AUDIT,
    )
    second_raw = RawApplicationCrawlRequest(
        "https://example.com/two",
        crawl_profile=CrawlProfileName.QUICK_AUDIT,
    )
    first = await application.submit(first_raw)
    assert first.status is not None and first.status.job_id is not None
    await factory.wait_started(1)
    duplicate = await application.preflight(first_raw)
    assert duplicate.state is PreflightState.BLOCKED
    assert duplicate.active_duplicate_job_id == first.status.job_id
    second = await application.submit(second_raw)
    assert second.outcome is ApplicationOutcomeCode.QUEUED
    assert second.status is not None and second.status.queue_position == 1
    queued_duplicate = await application.preflight(second_raw)
    assert queued_duplicate.state is PreflightState.BLOCKED
    assert queued_duplicate.active_duplicate_job_id == second.status.job_id
    full = await application.preflight(
        RawApplicationCrawlRequest(
            "https://example.com/three",
            crawl_profile=CrawlProfileName.QUICK_AUDIT,
        )
    )
    assert full.state is PreflightState.BLOCKED
    assert PreflightCode.QUEUE_FULL in {item.code for item in full.findings}
    rejected = await application.submit(
        RawApplicationCrawlRequest(
            "https://example.com/three",
            crawl_profile=CrawlProfileName.QUICK_AUDIT,
        )
    )
    assert rejected.outcome is ApplicationOutcomeCode.QUEUE_CAPACITY_REACHED
    cancelled = await application.cancel_job(second.status.job_id or "")
    assert cancelled.outcome is ApplicationOutcomeCode.CANCELLED_WHILE_QUEUED
    factory.releases[0].set()
    await application.wait_for_result(first.status.job_id)
    await application.shutdown()


@pytest.mark.anyio
async def test_duplicate_policies_are_preserved() -> None:
    factory = _BlockingFactory()
    application = _application(factory)
    raw = RawApplicationCrawlRequest(
        "https://example.com",
        crawl_profile=CrawlProfileName.QUICK_AUDIT,
    )
    first = await application.submit(raw)
    await factory.wait_started(1)
    rejected = await application.submit(raw)
    assert rejected.outcome is ApplicationOutcomeCode.ACTIVE_DUPLICATE
    factory.releases[0].set()
    assert first.status is not None and first.status.job_id is not None
    await application.wait_for_result(first.status.job_id)
    await application.shutdown()

    returning_factory = _BlockingFactory()
    returning = _application(
        returning_factory,
        JobRegistryConfiguration(
            duplicate_policy=DuplicateSubmissionPolicy.RETURN_ACTIVE_DUPLICATE
        ),
    )
    original = await returning.submit(raw)
    await returning_factory.wait_started(1)
    duplicate = await returning.submit(raw)
    assert duplicate.outcome is ApplicationOutcomeCode.DUPLICATE_RETURNED
    assert original.status is not None and duplicate.status is not None
    assert original.status.job_id == duplicate.status.job_id
    returning_factory.releases[0].set()
    await returning.wait_for_result(original.status.job_id or "")
    await returning.shutdown()


@pytest.mark.anyio
async def test_active_cancellation_uses_the_accepted_cooperative_token() -> None:
    factory = _BlockingFactory()
    application = _application(factory)
    submitted = await application.submit(
        RawApplicationCrawlRequest(
            "https://example.com",
            crawl_profile=CrawlProfileName.QUICK_AUDIT,
        )
    )
    assert submitted.status is not None and submitted.status.job_id is not None
    await factory.wait_started(1)
    cancellation = await application.cancel_job(submitted.status.job_id)
    assert cancellation.outcome is ApplicationOutcomeCode.CANCELLATION_REQUESTED
    factory.releases[0].set()
    result = await application.wait_for_result(submitted.status.job_id)
    assert result.run_lifecycle == RunLifecycle.CANCELLED.value
    terminal = await application.cancel_job(submitted.status.job_id)
    assert terminal.outcome is ApplicationOutcomeCode.ALREADY_TERMINAL
    await application.shutdown()


@pytest.mark.anyio
async def test_publication_and_summary_preflight_never_mutate_filesystem(tmp_path: Path) -> None:
    root = tmp_path / "output"
    application = _application()
    raw = RawApplicationCrawlRequest(
        "https://example.com",
        publication_requested=True,
        publication_dry_run=True,
        publication_root=root,
        create_publication_directory=True,
        summary_writing_requested=True,
        summary_root=root,
        create_summary_directory=True,
        summary_dry_run=True,
    )
    result = await application.preflight(raw)
    assert result.state is PreflightState.READY
    assert not root.exists()
    assert PreflightCode.OUTPUT_ROOT_CREATION_REQUIRED in {item.code for item in result.findings}
    assert PreflightCode.DRY_RUN in {item.code for item in result.findings}
    await application.shutdown()


@pytest.mark.anyio
async def test_actual_publication_and_summary_result_is_bounded(tmp_path: Path) -> None:
    publication = tmp_path / "publication"
    summaries = tmp_path / "summaries"
    application = _application()
    raw = RawApplicationCrawlRequest(
        "https://example.com",
        publication_requested=True,
        publication_root=publication,
        create_publication_directory=True,
        summary_writing_requested=True,
        summary_root=summaries,
        create_summary_directory=True,
    )
    submitted = await application.submit(raw)
    assert submitted.status is not None and submitted.status.job_id is not None
    result = await application.wait_for_result(submitted.status.job_id)
    assert result.publication_state == PublicationState.PUBLISHED.value
    assert result.published_file_count == 2
    assert result.publication_filenames == ("sitemap.xml", "sitemap-manifest.json")
    assert result.manifest_sha256 is not None
    assert {name for name, _hash in result.summary_hashes} == {
        "run-summary.json",
        "run-summary.md",
    }
    serialized = application.diagnostics_json(result).content
    assert str(tmp_path).encode() not in serialized
    assert b"<html" not in serialized.lower()
    await application.shutdown()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("policy", "summary_retained"),
    [
        (PayloadRetentionPolicy.SUMMARY_ONLY, True),
        (PayloadRetentionPolicy.METADATA_ONLY, False),
    ],
)
async def test_bounded_result_reports_payload_retention_policy(
    policy: PayloadRetentionPolicy,
    summary_retained: bool,  # noqa: FBT001 - parameterized policy expectation.
    tmp_path: Path,
) -> None:
    application = _application(
        registry_configuration=JobRegistryConfiguration(payload_retention_policy=policy)
    )
    submitted = await application.submit(
        RawApplicationCrawlRequest(
            "https://example.com",
            crawl_profile=CrawlProfileName.SITEMAP_ONLY,
            summary_root=tmp_path,
            summary_dry_run=True,
        )
    )
    assert submitted.status is not None and submitted.status.job_id is not None
    result = await application.wait_for_result(submitted.status.job_id)
    assert result.outcome is ApplicationOutcomeCode.RESULT_UNAVAILABLE
    assert result.summary_payloads_retained is summary_retained
    assert bool(result.summary_hashes) is summary_retained
    await application.shutdown()


@pytest.mark.anyio
async def test_readiness_capabilities_unknown_lookup_and_shutdown() -> None:
    application = _application(
        application_configuration=ApplicationServiceConfiguration(
            APPLICATION_HARD_MAXIMA,
            publication_service_available=False,
        )
    )
    readiness = await application.get_readiness()
    assert readiness.state is ReadinessState.DEGRADED
    capabilities = application.get_capabilities()
    assert capabilities.supported
    assert application.diagnostics_json(readiness).content.endswith(b"\n")
    assert application.diagnostics_json(capabilities).content.endswith(b"\n")
    assert (
        await application.get_job_status("missing")
    ).outcome is ApplicationOutcomeCode.JOB_NOT_FOUND
    assert (
        await application.get_job_result("missing")
    ).outcome is ApplicationOutcomeCode.JOB_NOT_FOUND
    shutdown = await application.shutdown()
    assert shutdown.readiness.state is ReadinessState.NOT_READY
    closed = await application.submit(RawApplicationCrawlRequest("https://example.com"))
    assert closed.outcome is ApplicationOutcomeCode.REGISTRY_CLOSED


@pytest.mark.anyio
async def test_queue_full_is_degraded_readiness() -> None:
    factory = _BlockingFactory()
    application = _application(
        factory,
        JobRegistryConfiguration(maximum_concurrent_jobs=1, maximum_queued_jobs=0),
    )
    result = await application.submit(
        RawApplicationCrawlRequest(
            "https://example.com",
            crawl_profile=CrawlProfileName.QUICK_AUDIT,
        )
    )
    await factory.wait_started(1)
    assert (await application.get_readiness()).state is ReadinessState.DEGRADED
    factory.releases[0].set()
    assert result.status is not None and result.status.job_id is not None
    await application.wait_for_result(result.status.job_id)
    await application.shutdown()
