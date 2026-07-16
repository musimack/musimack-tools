"""End-to-end internal crawl-run composition with controlled in-memory evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from musimack_tools.crawl.cancellation import CrawlCancellationToken
from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import create_scope_policy
from musimack_tools.domain.crawl import (
    CrawlConfigurationSnapshot,
    CrawlCounters,
    CrawlError,
    CrawlErrorCode,
    CrawlRequest,
    CrawlResult,
    CrawlState,
    ProgressSnapshot,
)
from musimack_tools.domain.run import (
    CrawlRunRequest,
    CrawlRunResult,
    RunFailureCode,
    RunLifecycle,
    RunStage,
    RunStageState,
)
from musimack_tools.domain.run_progress import RunEventCode, RunProgressEvent
from musimack_tools.domain.run_summary import RunSummaryConfiguration, RunSummaryWriteState
from musimack_tools.domain.sitemap_publication import (
    PublicationMode,
    PublicationState,
    SitemapPublicationConfiguration,
)
from musimack_tools.run.progress import RecordingRunProgressSink
from musimack_tools.run.service import CrawlRunService

if TYPE_CHECKING:
    from pathlib import Path

    from musimack_tools.crawl.orchestrator import ProgressObserver


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _crawl_result(
    state: CrawlState = CrawlState.COMPLETED,
    *,
    errors: tuple[CrawlError, ...] = (),
) -> CrawlResult:
    seed = normalize_url("https://example.com/")
    return CrawlResult(
        seed_url=seed.normalized,
        scope_policy=create_scope_policy(seed),
        started_at_seconds=0,
        ended_at_seconds=1,
        duration_seconds=1,
        state=state,
        url_records=(),
        discoveries=(),
        counters=CrawlCounters(unique_urls_discovered=1, urls_queued=1, urls_fetched=1),
        limit_events=(),
        errors=errors,
        cancellation=None,
        total_accepted_bytes=10,
        maximum_observed_queue_size=1,
        maximum_active_worker_count=1,
        configuration=CrawlConfigurationSnapshot(
            maximum_unique_urls=50,
            maximum_depth=5,
            maximum_duration_seconds=60,
            maximum_total_fetched_bytes=1_000_000,
            maximum_concurrent_fetches=2,
            maximum_queued_urls=100,
            minimum_per_origin_delay_seconds=0,
            query_urls_allowed=True,
            exclusion_rules=(),
        ),
    )


class FakeCrawler:
    def __init__(
        self,
        result: CrawlResult | None = None,
        *,
        cancellation: CrawlCancellationToken | None = None,
        error: Exception | None = None,
        snapshots: tuple[ProgressSnapshot, ...] = (),
    ) -> None:
        self.result = result or _crawl_result()
        self.cancellation = cancellation
        self.error = error
        self.snapshots = snapshots
        self.calls = 0

    async def crawl(
        self,
        request: CrawlRequest,
        *,
        observer: ProgressObserver | None = None,
    ) -> CrawlResult:
        del request
        self.calls += 1
        if observer is not None:
            for snapshot in self.snapshots:
                await observer.on_progress(snapshot)
        if self.cancellation is not None:
            self.cancellation.cancel()
        if self.error is not None:
            raise self.error
        return self.result


class FailingProjector:
    def project(self, crawl: CrawlResult) -> object:
        del crawl
        message = "private projector detail"
        raise RuntimeError(message)


class FailingSink:
    def __init__(self) -> None:
        self.calls = 0

    async def on_progress(self, event: object) -> None:
        del event
        self.calls += 1
        message = "sink failed"
        raise RuntimeError(message)


class LiveProgressFailingSink:
    def __init__(self) -> None:
        self.attempted_codes: list[RunEventCode] = []

    async def on_progress(self, event: RunProgressEvent) -> None:
        code = event.code
        self.attempted_codes.append(code)
        if code is RunEventCode.CRAWL_PROGRESS:
            message = "live progress failed"
            raise RuntimeError(message)


def _progress(  # noqa: PLR0913 - explicit fields verify the progress mapping.
    *,
    discovered: int,
    queued: int,
    fetched: int,
    parsed: int,
    byte_count: int,
    queue_size: int,
    active_count: int,
    depth: int | None,
    state: CrawlState = CrawlState.RUNNING,
) -> ProgressSnapshot:
    return ProgressSnapshot(
        state=state,
        counters=CrawlCounters(
            unique_urls_discovered=discovered,
            urls_queued=queued,
            urls_fetched=fetched,
            html_pages_parsed=parsed,
        ),
        queue_size=queue_size,
        active_count=active_count,
        current_depth=depth,
        total_accepted_bytes=byte_count,
        elapsed_seconds=1.0,
    )


def _request(
    stages: tuple[RunStage, ...],
    *,
    publication: SitemapPublicationConfiguration | None = None,
    summary: RunSummaryConfiguration | None = None,
) -> CrawlRunRequest:
    seed = normalize_url("https://example.com/")
    return CrawlRunRequest(
        CrawlRequest(seed, create_scope_policy(seed), maximum_unique_urls=50),
        stages,
        publication_configuration=publication,
        summary_configuration=summary,
    )


def _stage(result: CrawlRunResult, stage: RunStage) -> RunStageState:
    return next(item.state for item in result.stages if item.stage is stage)


@pytest.mark.anyio
async def test_successful_crawl_only_run() -> None:
    result = await CrawlRunService(FakeCrawler()).execute(_request((RunStage.CRAWL,)))
    assert result.lifecycle is RunLifecycle.COMPLETED
    assert result.crawl_result is not None
    assert result.recommendation_projection is None
    assert _stage(result, RunStage.CRAWL) is RunStageState.COMPLETED


@pytest.mark.anyio
async def test_empty_full_generation_run_preserves_all_outputs() -> None:
    stages = (RunStage.CRAWL, RunStage.RECOMMEND, RunStage.GENERATE_XML)
    result = await CrawlRunService(FakeCrawler()).execute(_request(stages))
    assert result.recommendation_projection is not None
    assert result.recommendation_projection.recommendations == ()
    assert result.xml_bundle is not None
    assert result.xml_bundle.total_entries == 0
    assert result.lifecycle is RunLifecycle.COMPLETED


@pytest.mark.anyio
async def test_full_dry_run_publication_writes_nothing(tmp_path: Path) -> None:
    stages = (RunStage.CRAWL, RunStage.RECOMMEND, RunStage.GENERATE_XML, RunStage.PUBLISH)
    publication = SitemapPublicationConfiguration(tmp_path, mode=PublicationMode.DRY_RUN)
    result = await CrawlRunService(FakeCrawler()).execute(_request(stages, publication=publication))
    assert result.publication_result is not None
    assert result.publication_result.state is PublicationState.DRY_RUN
    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.anyio
async def test_full_actual_publication_and_summary(tmp_path: Path) -> None:
    publication_root = tmp_path / "sitemap"
    summary_root = tmp_path / "summary"
    stages = (
        RunStage.CRAWL,
        RunStage.RECOMMEND,
        RunStage.GENERATE_XML,
        RunStage.PUBLISH,
        RunStage.WRITE_SUMMARY,
    )
    result = await CrawlRunService(FakeCrawler()).execute(
        _request(
            stages,
            publication=SitemapPublicationConfiguration(
                publication_root,
                create_output_directory=True,
            ),
            summary=RunSummaryConfiguration(summary_root, create_output_directory=True),
        )
    )
    assert result.lifecycle is RunLifecycle.COMPLETED
    assert result.publication_result is not None
    assert result.publication_result.state is PublicationState.PUBLISHED
    assert result.summary_write_result is not None
    assert result.summary_write_result.state is RunSummaryWriteState.WRITTEN
    assert (summary_root / "run-summary.json").exists()
    assert len(result.summaries) == 2


@pytest.mark.anyio
async def test_plan_only_preserves_plan_without_publication(tmp_path: Path) -> None:
    stages = (
        RunStage.CRAWL,
        RunStage.RECOMMEND,
        RunStage.GENERATE_XML,
        RunStage.PLAN_PUBLICATION,
    )
    result = await CrawlRunService(FakeCrawler()).execute(
        _request(stages, publication=SitemapPublicationConfiguration(tmp_path))
    )
    assert result.publication_plan is not None
    assert result.publication_result is None
    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.anyio
async def test_cancellation_before_start_skips_crawler_and_blocks_dependents() -> None:
    token = CrawlCancellationToken()
    token.cancel()
    crawler = FakeCrawler()
    sink = RecordingRunProgressSink()
    stages = (RunStage.CRAWL, RunStage.RECOMMEND, RunStage.GENERATE_XML, RunStage.WRITE_SUMMARY)
    result = await CrawlRunService(crawler, cancellation=token, progress_sink=sink).execute(
        _request(stages)
    )
    assert crawler.calls == 0
    assert result.lifecycle is RunLifecycle.CANCELLED
    assert _stage(result, RunStage.CRAWL) is RunStageState.CANCELLED
    assert _stage(result, RunStage.RECOMMEND) is RunStageState.BLOCKED
    assert len(result.summaries) == 2
    assert RunEventCode.CRAWL_PROGRESS not in {item.code for item in sink.events}


@pytest.mark.anyio
async def test_cancelled_crawl_preserves_partial_result_and_blocks_dependents() -> None:
    stages = (RunStage.CRAWL, RunStage.RECOMMEND, RunStage.GENERATE_XML)
    result = await CrawlRunService(FakeCrawler(_crawl_result(CrawlState.CANCELLED))).execute(
        _request(stages)
    )
    assert result.crawl_result is not None
    assert result.lifecycle is RunLifecycle.CANCELLED
    assert _stage(result, RunStage.RECOMMEND) is RunStageState.BLOCKED


@pytest.mark.anyio
async def test_cancellation_after_crawl_cancels_recommendation() -> None:
    token = CrawlCancellationToken()
    crawler = FakeCrawler(cancellation=token)
    sink = RecordingRunProgressSink()
    stages = (RunStage.CRAWL, RunStage.RECOMMEND, RunStage.GENERATE_XML)
    result = await CrawlRunService(crawler, cancellation=token, progress_sink=sink).execute(
        _request(stages)
    )
    assert result.crawl_result is not None
    assert _stage(result, RunStage.CRAWL) is RunStageState.COMPLETED
    assert _stage(result, RunStage.RECOMMEND) is RunStageState.CANCELLED
    assert _stage(result, RunStage.GENERATE_XML) is RunStageState.BLOCKED
    crawl_completed = next(
        item.sequence
        for item in sink.events
        if item.code is RunEventCode.STAGE_COMPLETED
        and item.snapshot.active_stage is RunStage.CRAWL
    )
    cancellation = next(
        item.sequence for item in sink.events if item.code is RunEventCode.CANCELLATION_OBSERVED
    )
    assert crawl_completed < cancellation


@pytest.mark.anyio
async def test_crawl_failure_blocks_downstream_and_preserves_typed_failure() -> None:
    stages = (RunStage.CRAWL, RunStage.RECOMMEND, RunStage.GENERATE_XML)
    result = await CrawlRunService(FakeCrawler(_crawl_result(CrawlState.FAILED))).execute(
        _request(stages)
    )
    assert result.lifecycle is RunLifecycle.FAILED
    assert result.failures[0].code is RunFailureCode.CRAWL_FAILED
    assert _stage(result, RunStage.RECOMMEND) is RunStageState.BLOCKED


@pytest.mark.anyio
async def test_unexpected_crawl_exception_does_not_expose_raw_message() -> None:
    result = await CrawlRunService(
        FakeCrawler(error=RuntimeError("secret internal detail"))
    ).execute(_request((RunStage.CRAWL,)))
    assert result.lifecycle is RunLifecycle.FAILED
    assert result.failures[0].internal_exception_type == "RuntimeError"
    assert "secret" not in result.failures[0].explanation


@pytest.mark.anyio
async def test_recommendation_failure_preserves_crawl_and_blocks_xml() -> None:
    stages = (RunStage.CRAWL, RunStage.RECOMMEND, RunStage.GENERATE_XML)
    result = await CrawlRunService(
        FakeCrawler(),
        recommendation=FailingProjector(),  # type: ignore[arg-type]
    ).execute(_request(stages))
    assert result.crawl_result is not None
    assert result.recommendation_projection is None
    assert result.lifecycle is RunLifecycle.PARTIALLY_COMPLETED
    assert _stage(result, RunStage.GENERATE_XML) is RunStageState.BLOCKED


@pytest.mark.anyio
async def test_crawl_warnings_produce_completed_with_warnings() -> None:
    error = CrawlError(CrawlErrorCode.PROGRESS_OBSERVER_FAILURE, "Observer failed")
    crawl = _crawl_result(CrawlState.COMPLETED_WITH_ERRORS, errors=(error,))
    result = await CrawlRunService(FakeCrawler(crawl)).execute(_request((RunStage.CRAWL,)))
    assert result.lifecycle is RunLifecycle.COMPLETED_WITH_WARNINGS
    assert result.warnings[0].code == CrawlErrorCode.PROGRESS_OBSERVER_FAILURE.value


@pytest.mark.anyio
async def test_progress_sequence_is_monotonic_and_contains_final_crawl_counts() -> None:
    sink = RecordingRunProgressSink()
    result = await CrawlRunService(FakeCrawler(), progress_sink=sink).execute(
        _request((RunStage.CRAWL,))
    )
    assert result.lifecycle is RunLifecycle.COMPLETED
    assert [event.sequence for event in sink.events] == list(range(1, len(sink.events) + 1))
    assert any(event.snapshot.urls_discovered == 1 for event in sink.events)


@pytest.mark.anyio
async def test_progress_sink_failure_is_one_warning_and_core_run_continues() -> None:
    sink = FailingSink()
    result = await CrawlRunService(
        FakeCrawler(),
        progress_sink=sink,
    ).execute(_request((RunStage.CRAWL,)))
    assert result.crawl_result is not None
    assert result.lifecycle is RunLifecycle.COMPLETED_WITH_WARNINGS
    assert sink.calls == 1
    assert [item.code for item in result.warnings] == [RunFailureCode.PROGRESS_SINK_FAILED.value]


@pytest.mark.anyio
async def test_summary_write_failure_preserves_in_memory_summaries(tmp_path: Path) -> None:
    target = tmp_path / "run-summary.json"
    target.write_text("existing")
    stages = (RunStage.CRAWL, RunStage.WRITE_SUMMARY)
    result = await CrawlRunService(FakeCrawler()).execute(
        _request(stages, summary=RunSummaryConfiguration(tmp_path))
    )
    assert result.crawl_result is not None
    assert len(result.summaries) == 2
    assert result.lifecycle is RunLifecycle.PARTIALLY_COMPLETED
    assert _stage(result, RunStage.WRITE_SUMMARY) is RunStageState.FAILED


@pytest.mark.anyio
async def test_equal_evidence_produces_equal_portable_results() -> None:
    request = _request((RunStage.CRAWL, RunStage.WRITE_SUMMARY))
    first = await CrawlRunService(FakeCrawler(), clock=lambda: 1.0).execute(request)
    second = await CrawlRunService(FakeCrawler(), clock=lambda: 1.0).execute(request)
    assert first.run_id == second.run_id
    assert first.summaries == second.summaries


@pytest.mark.anyio
async def test_multiple_live_snapshots_are_translated_in_callback_order() -> None:
    snapshots = (
        _progress(
            discovered=1,
            queued=1,
            fetched=0,
            parsed=0,
            byte_count=0,
            queue_size=1,
            active_count=0,
            depth=0,
        ),
        _progress(
            discovered=1,
            queued=1,
            fetched=1,
            parsed=0,
            byte_count=10,
            queue_size=0,
            active_count=1,
            depth=0,
        ),
        _progress(
            discovered=1,
            queued=1,
            fetched=1,
            parsed=0,
            byte_count=10,
            queue_size=0,
            active_count=0,
            depth=None,
            state=CrawlState.COMPLETED,
        ),
    )
    sink = RecordingRunProgressSink()
    await CrawlRunService(FakeCrawler(snapshots=snapshots), progress_sink=sink).execute(
        _request((RunStage.CRAWL,))
    )
    events = sink.events
    progress = [item for item in events if item.code is RunEventCode.CRAWL_PROGRESS]
    assert [item.snapshot.urls_fetched for item in progress] == [0, 1, 1]
    assert [item.snapshot.active_count for item in progress] == [0, 1, 0]
    assert all(
        item.snapshot.crawl_progress is source
        for item, source in zip(progress, snapshots, strict=True)
    )
    started = next(
        index for index, item in enumerate(events) if item.code is RunEventCode.STAGE_STARTED
    )
    completed = next(
        index for index, item in enumerate(events) if item.code is RunEventCode.STAGE_COMPLETED
    )
    assert started < min(events.index(item) for item in progress) < completed
    assert [item.sequence for item in events] == list(range(1, len(events) + 1))


@pytest.mark.anyio
async def test_final_progress_reconciles_when_last_callback_trails_result() -> None:
    early = _progress(
        discovered=1,
        queued=1,
        fetched=0,
        parsed=0,
        byte_count=0,
        queue_size=1,
        active_count=0,
        depth=0,
    )
    sink = RecordingRunProgressSink()
    result = await CrawlRunService(FakeCrawler(snapshots=(early,)), progress_sink=sink).execute(
        _request((RunStage.CRAWL, RunStage.WRITE_SUMMARY))
    )
    progress = [item for item in sink.events if item.code is RunEventCode.CRAWL_PROGRESS]
    assert len(progress) == 2
    final = progress[-1]
    assert final.explanation == "Final crawl counters reconciled"
    assert final.snapshot.crawl_progress is None
    crawl = result.crawl_result
    assert crawl is not None
    assert final.snapshot.urls_fetched == crawl.counters.urls_fetched
    assert final.snapshot.bytes_fetched == crawl.total_accepted_bytes
    assert b'"urls_fetched": 1' in result.summaries[0].content


@pytest.mark.anyio
async def test_live_progress_sink_failure_isolated_and_suppressed() -> None:
    snapshots = (
        _progress(
            discovered=1,
            queued=1,
            fetched=0,
            parsed=0,
            byte_count=0,
            queue_size=1,
            active_count=0,
            depth=0,
        ),
        _progress(
            discovered=1,
            queued=1,
            fetched=1,
            parsed=0,
            byte_count=10,
            queue_size=0,
            active_count=0,
            depth=None,
        ),
    )
    sink = LiveProgressFailingSink()
    result = await CrawlRunService(FakeCrawler(snapshots=snapshots), progress_sink=sink).execute(
        _request((RunStage.CRAWL,))
    )
    assert result.crawl_result is not None
    assert result.lifecycle is RunLifecycle.COMPLETED_WITH_WARNINGS
    assert sink.attempted_codes.count(RunEventCode.CRAWL_PROGRESS) == 1
    assert [item.code for item in result.warnings] == [RunFailureCode.PROGRESS_SINK_FAILED.value]


@pytest.mark.anyio
async def test_cancellation_during_crawl_orders_observation_after_live_progress() -> None:
    token = CrawlCancellationToken()
    snapshot = _progress(
        discovered=1,
        queued=1,
        fetched=0,
        parsed=0,
        byte_count=0,
        queue_size=1,
        active_count=0,
        depth=0,
    )
    sink = RecordingRunProgressSink()
    result = await CrawlRunService(
        FakeCrawler(
            _crawl_result(CrawlState.CANCELLED),
            cancellation=token,
            snapshots=(snapshot,),
        ),
        cancellation=token,
        progress_sink=sink,
    ).execute(_request((RunStage.CRAWL, RunStage.RECOMMEND)))
    codes = [item.code for item in sink.events]
    assert codes.index(RunEventCode.CRAWL_PROGRESS) < codes.index(
        RunEventCode.CANCELLATION_OBSERVED
    )
    assert result.crawl_result is not None
    assert result.lifecycle is RunLifecycle.CANCELLED
    assert _stage(result, RunStage.RECOMMEND) is RunStageState.BLOCKED


def test_run_progress_snapshots_are_immutable() -> None:
    snapshot = _progress(
        discovered=1,
        queued=1,
        fetched=0,
        parsed=0,
        byte_count=0,
        queue_size=1,
        active_count=0,
        depth=0,
    )
    with pytest.raises(AttributeError):
        snapshot.queue_size = 2  # type: ignore[misc]
