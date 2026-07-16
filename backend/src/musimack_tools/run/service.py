"""Framework-independent composition of one internal crawl run."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Protocol

from musimack_tools.crawl.cancellation import CancellationToken, NeverCancelledToken
from musimack_tools.domain.crawl import CrawlRequest, CrawlResult, CrawlState, ProgressSnapshot
from musimack_tools.domain.run import (
    CrawlRunRequest,
    CrawlRunResult,
    RunFailure,
    RunFailureCode,
    RunLifecycle,
    RunStage,
    RunStageRecord,
    RunStageState,
    RunWarning,
    validate_stage_transition,
)
from musimack_tools.domain.run_progress import (
    RunEventCode,
    RunProgressEvent,
    RunProgressSnapshot,
)
from musimack_tools.domain.run_summary import (
    RunSummaryArtifact,
    RunSummaryWriteResult,
    RunSummaryWriteState,
)
from musimack_tools.domain.sitemap_publication import (
    PublicationPlanState,
    PublicationState,
    SitemapPublicationPlan,
    SitemapPublicationResult,
)
from musimack_tools.recommendation.sitemap import SitemapRecommendationEngine
from musimack_tools.run.identity import configuration_snapshot, run_identity
from musimack_tools.run.progress import NoOpRunProgressSink, RunProgressSink
from musimack_tools.run.summary import RunSummaryWriter, serialize_summaries
from musimack_tools.sitemap.publication import SitemapPublicationExecutor, plan_publication
from musimack_tools.sitemap.xml import SitemapXmlGenerator

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from typing import NoReturn

    from musimack_tools.crawl.orchestrator import ProgressObserver
    from musimack_tools.domain.sitemap import SitemapRecommendationProjection
    from musimack_tools.domain.sitemap_publication import SitemapPublicationConfiguration
    from musimack_tools.domain.sitemap_xml import SitemapXmlBundle
    from musimack_tools.sitemap.limits import SitemapXmlConfiguration

Clock = Callable[[], float]


class CrawlRunner(Protocol):
    async def crawl(
        self,
        request: CrawlRequest,
        *,
        observer: ProgressObserver | None = None,
    ) -> CrawlResult: ...


class RecommendationProjector(Protocol):
    def project(self, crawl: CrawlResult) -> SitemapRecommendationProjection: ...


class XmlBundleGenerator(Protocol):
    def generate(self, projection: SitemapRecommendationProjection) -> SitemapXmlBundle: ...


class PublicationPlanner(Protocol):
    def __call__(
        self,
        bundle: SitemapXmlBundle,
        recommendation_rule_set_version: str,
        configuration: SitemapPublicationConfiguration,
    ) -> SitemapPublicationPlan: ...


class _ProgressEmitter:
    def __init__(self, sink: RunProgressSink) -> None:
        self._sink = sink
        self.sequence = 0
        self.failed = False

    async def emit(
        self,
        code: RunEventCode,
        snapshot: RunProgressSnapshot,
        explanation: str,
    ) -> bool:
        self.sequence += 1
        event = RunProgressEvent(self.sequence, code, snapshot, explanation)
        if self.failed:
            return False
        try:
            await self._sink.on_progress(event)
        except Exception:  # noqa: BLE001 - progress is deliberately non-blocking.
            self.failed = True
            return True
        return False


class _CrawlProgressAdapter:
    """Translate accepted crawler snapshots without changing crawl semantics."""

    def __init__(self, callback: Callable[[ProgressSnapshot], Awaitable[None]]) -> None:
        self._callback = callback

    async def on_progress(self, snapshot: ProgressSnapshot) -> None:
        await self._callback(snapshot)


class CrawlRunService:
    """Compose accepted stage services while preserving every completed output."""

    def __init__(  # noqa: PLR0913 - each dependency is an explicit test boundary.
        self,
        crawler: CrawlRunner,
        *,
        recommendation: RecommendationProjector | None = None,
        xml_generator_factory: Callable[[SitemapXmlConfiguration], XmlBundleGenerator]
        | None = None,
        publication_planner: PublicationPlanner = plan_publication,
        publication_executor: SitemapPublicationExecutor | None = None,
        summary_writer: RunSummaryWriter | None = None,
        progress_sink: RunProgressSink | None = None,
        cancellation: CancellationToken | None = None,
        clock: Clock = time.monotonic,
    ) -> None:
        self._crawler = crawler
        self._recommendation = recommendation
        self._xml_generator_factory = xml_generator_factory or SitemapXmlGenerator
        self._publication_planner = publication_planner
        self._publication_executor = publication_executor or SitemapPublicationExecutor()
        self._summary_writer = summary_writer or RunSummaryWriter()
        self._emitter = _ProgressEmitter(progress_sink or NoOpRunProgressSink())
        self._cancellation = cancellation or NeverCancelledToken()
        self._clock = clock

    async def execute(self, request: CrawlRunRequest) -> CrawlRunResult:  # noqa: C901, PLR0912, PLR0915
        """Execute requested stages sequentially with cooperative boundary checks."""
        started = self._clock()
        self._emitter.sequence = 0
        self._emitter.failed = False
        run_id, digest = run_identity(request)
        configuration = configuration_snapshot(request)
        stages = {
            stage: (
                RunStageState.PENDING
                if stage in request.requested_stages
                else RunStageState.NOT_REQUESTED
            )
            for stage in RunStage
        }
        explanations: dict[RunStage, str | None] = dict.fromkeys(RunStage)
        warnings: list[RunWarning] = []
        failures: list[RunFailure] = []
        crawl: CrawlResult | None = None
        projection: SitemapRecommendationProjection | None = None
        bundle: SitemapXmlBundle | None = None
        plan: SitemapPublicationPlan | None = None
        publication: SitemapPublicationResult | None = None
        summaries: tuple[RunSummaryArtifact, ...] = ()
        summary_write: RunSummaryWriteResult | None = None
        last_crawl_snapshot: ProgressSnapshot | None = None

        def records() -> tuple[RunStageRecord, ...]:
            return tuple(
                RunStageRecord(stage, stages[stage], explanations[stage]) for stage in RunStage
            )

        def result(lifecycle: RunLifecycle) -> CrawlRunResult:
            return CrawlRunResult(
                run_id,
                digest,
                request.caller_label,
                lifecycle,
                records(),
                configuration,
                crawl,
                projection,
                bundle,
                plan,
                publication,
                summaries,
                summary_write,
                tuple(warnings),
                tuple(failures),
                max(0.0, self._clock() - started),
            )

        async def emit(
            code: RunEventCode,
            lifecycle: RunLifecycle,
            stage: RunStage | None,
            explanation: str,
            crawl_progress: ProgressSnapshot | None = None,
        ) -> None:
            sink_failed = await self._emitter.emit(
                code,
                _snapshot(
                    lifecycle,
                    stage,
                    stages.get(stage) if stage is not None else None,
                    crawl,
                    projection,
                    bundle,
                    publication,
                    warnings,
                    failures,
                    self._cancellation.is_cancelled(),
                    max(0.0, self._clock() - started),
                    crawl_progress,
                ),
                explanation,
            )
            if sink_failed:
                warnings.append(
                    RunWarning(
                        RunFailureCode.PROGRESS_SINK_FAILED.value,
                        stage or RunStage.CRAWL,
                        "The progress sink failed; further progress delivery was suppressed",
                    )
                )

        def transition(
            stage: RunStage, state: RunStageState, explanation: str | None = None
        ) -> None:
            validate_stage_transition(stages[stage], state)
            stages[stage] = state
            explanations[stage] = explanation

        async def start_stage(stage: RunStage) -> bool:
            if stages[stage] is not RunStageState.PENDING:
                return False
            if self._cancellation.is_cancelled():
                transition(stage, RunStageState.CANCELLED, "Cooperative cancellation observed")
                failures.append(
                    RunFailure(
                        RunFailureCode.CANCELLATION_OBSERVED,
                        stage,
                        "Cancellation was observed before the stage began",
                    )
                )
                await emit(
                    RunEventCode.CANCELLATION_OBSERVED,
                    RunLifecycle.CANCELLING,
                    stage,
                    "Cancellation observed",
                )
                await emit(
                    RunEventCode.STAGE_CANCELLED, RunLifecycle.CANCELLING, stage, "Stage cancelled"
                )
                _block_dependents(stages, explanations, stage)
                return False
            transition(stage, RunStageState.RUNNING)
            await emit(RunEventCode.STAGE_STARTED, RunLifecycle.RUNNING, stage, "Stage started")
            return True

        await emit(RunEventCode.RUN_ACCEPTED, RunLifecycle.PENDING, None, "Run accepted")
        await emit(RunEventCode.RUN_STARTED, RunLifecycle.RUNNING, None, "Run started")

        if await start_stage(RunStage.CRAWL):
            try:

                async def on_crawl_progress(snapshot: ProgressSnapshot) -> None:
                    nonlocal last_crawl_snapshot
                    last_crawl_snapshot = snapshot
                    await emit(
                        RunEventCode.CRAWL_PROGRESS,
                        RunLifecycle.RUNNING,
                        RunStage.CRAWL,
                        "Live crawl progress",
                        snapshot,
                    )

                crawl = await self._crawler.crawl(
                    request.crawl_request,
                    observer=_CrawlProgressAdapter(on_crawl_progress),
                )
                if _crawl_progress_differs(last_crawl_snapshot, crawl):
                    await emit(
                        RunEventCode.CRAWL_PROGRESS,
                        RunLifecycle.RUNNING,
                        RunStage.CRAWL,
                        "Final crawl counters reconciled",
                    )
                if crawl.state is CrawlState.CANCELLED:
                    transition(
                        RunStage.CRAWL, RunStageState.CANCELLED, "Crawl cooperatively cancelled"
                    )
                    failures.append(
                        RunFailure(
                            RunFailureCode.CRAWL_CANCELLED, RunStage.CRAWL, "Crawl cancelled"
                        )
                    )
                    _block_dependents(stages, explanations, RunStage.CRAWL)
                    await emit(
                        RunEventCode.CANCELLATION_OBSERVED,
                        RunLifecycle.CANCELLING,
                        RunStage.CRAWL,
                        "Crawl cancellation observed",
                    )
                    await emit(
                        RunEventCode.STAGE_CANCELLED,
                        RunLifecycle.CANCELLING,
                        RunStage.CRAWL,
                        "Crawl cancelled",
                    )
                elif crawl.state is CrawlState.FAILED:
                    transition(RunStage.CRAWL, RunStageState.FAILED, "Crawl failed")
                    failures.append(
                        RunFailure(RunFailureCode.CRAWL_FAILED, RunStage.CRAWL, "Crawl failed")
                    )
                    _block_dependents(stages, explanations, RunStage.CRAWL)
                    await emit(
                        RunEventCode.STAGE_FAILED,
                        RunLifecycle.PARTIALLY_COMPLETED,
                        RunStage.CRAWL,
                        "Crawl failed",
                    )
                else:
                    crawl_warning = crawl.state in {
                        CrawlState.COMPLETED_WITH_ERRORS,
                        CrawlState.LIMIT_REACHED,
                    }
                    transition(
                        RunStage.CRAWL,
                        RunStageState.COMPLETED_WITH_WARNINGS
                        if crawl_warning
                        else RunStageState.COMPLETED,
                    )
                    warnings.extend(
                        RunWarning(error.code.value, RunStage.CRAWL, error.explanation, error.url)
                        for error in crawl.errors
                    )
                    await emit(
                        RunEventCode.STAGE_COMPLETED,
                        RunLifecycle.RUNNING,
                        RunStage.CRAWL,
                        "Crawl completed",
                    )
            except Exception as error:  # noqa: BLE001 - stage boundary returns typed failure.
                transition(
                    RunStage.CRAWL, RunStageState.FAILED, "Crawl raised a controlled stage failure"
                )
                failures.append(_unexpected(RunFailureCode.CRAWL_FAILED, RunStage.CRAWL, error))
                _block_dependents(stages, explanations, RunStage.CRAWL)

        if await start_stage(RunStage.RECOMMEND):
            try:
                if crawl is None:
                    _missing_evidence("crawl evidence")
                engine = self._recommendation or SitemapRecommendationEngine(
                    request.recommendation_policy
                )
                projection = engine.project(crawl)
                warnings.extend(
                    RunWarning(
                        item.code,
                        RunStage.RECOMMEND,
                        item.explanation,
                        recommendation.evaluated_url,
                    )
                    for recommendation in projection.recommendations
                    for item in (*recommendation.warnings, *recommendation.metadata_warnings)
                )
                state = (
                    RunStageState.COMPLETED_WITH_WARNINGS if warnings else RunStageState.COMPLETED
                )
                transition(RunStage.RECOMMEND, state)
                await emit(
                    RunEventCode.STAGE_COMPLETED,
                    RunLifecycle.RUNNING,
                    RunStage.RECOMMEND,
                    "Recommendations completed",
                )
            except Exception as error:  # noqa: BLE001
                transition(
                    RunStage.RECOMMEND, RunStageState.FAILED, "Recommendation projection failed"
                )
                failures.append(
                    _unexpected(RunFailureCode.RECOMMENDATION_FAILED, RunStage.RECOMMEND, error)
                )
                _block_dependents(stages, explanations, RunStage.RECOMMEND)

        if await start_stage(RunStage.GENERATE_XML):
            try:
                if projection is None:
                    _missing_evidence("recommendation evidence")
                bundle = self._xml_generator_factory(request.xml_configuration).generate(projection)
                warnings.extend(
                    RunWarning(item.code.value, RunStage.GENERATE_XML, item.explanation)
                    for item in bundle.warnings
                )
                transition(
                    RunStage.GENERATE_XML,
                    RunStageState.COMPLETED_WITH_WARNINGS
                    if bundle.warnings
                    else RunStageState.COMPLETED,
                )
                await emit(
                    RunEventCode.STAGE_COMPLETED,
                    RunLifecycle.RUNNING,
                    RunStage.GENERATE_XML,
                    "XML generation completed",
                )
            except Exception as error:  # noqa: BLE001
                transition(RunStage.GENERATE_XML, RunStageState.FAILED, "XML generation failed")
                failures.append(
                    _unexpected(RunFailureCode.XML_GENERATION_FAILED, RunStage.GENERATE_XML, error)
                )
                _block_dependents(stages, explanations, RunStage.GENERATE_XML)

        publication_stage = (
            RunStage.PLAN_PUBLICATION
            if RunStage.PLAN_PUBLICATION in request.requested_stages
            else RunStage.PUBLISH
        )
        if await start_stage(publication_stage):
            try:
                if bundle is None or projection is None:
                    _missing_evidence("XML or recommendation evidence")
                if request.publication_configuration is None:
                    _missing_evidence("publication configuration")
                plan = self._publication_planner(
                    bundle,
                    projection.rule_set_version,
                    request.publication_configuration,
                )
                if plan.state is PublicationPlanState.BLOCKED:
                    transition(
                        publication_stage, RunStageState.FAILED, "Publication planning blocked"
                    )
                    failures.append(
                        RunFailure(
                            RunFailureCode.PUBLICATION_PLANNING_FAILED,
                            publication_stage,
                            "Publication plan was blocked",
                        )
                    )
                elif publication_stage is RunStage.PLAN_PUBLICATION:
                    transition(publication_stage, RunStageState.COMPLETED)
                elif self._cancellation.is_cancelled():
                    transition(
                        publication_stage,
                        RunStageState.CANCELLED,
                        "Cancelled before publication mutation",
                    )
                    failures.append(
                        RunFailure(
                            RunFailureCode.CANCELLATION_OBSERVED,
                            publication_stage,
                            "Cancellation was observed before publication",
                        )
                    )
                else:
                    publication = self._publication_executor.execute(plan)
                    if publication.state is PublicationState.BLOCKED:
                        transition(publication_stage, RunStageState.FAILED, "Publication blocked")
                        failures.append(
                            RunFailure(
                                RunFailureCode.PUBLICATION_BLOCKED,
                                publication_stage,
                                "Publication was blocked",
                            )
                        )
                    elif publication.state is PublicationState.PARTIALLY_FAILED:
                        transition(
                            publication_stage, RunStageState.FAILED, "Publication partially failed"
                        )
                        failures.append(
                            RunFailure(
                                RunFailureCode.PUBLICATION_PARTIALLY_FAILED,
                                publication_stage,
                                "Publication partially failed",
                            )
                        )
                    else:
                        transition(publication_stage, RunStageState.COMPLETED)
                await emit(
                    RunEventCode.STAGE_COMPLETED,
                    RunLifecycle.RUNNING,
                    publication_stage,
                    "Publication stage finished",
                )
            except Exception as error:  # noqa: BLE001
                transition(publication_stage, RunStageState.FAILED, "Publication stage failed")
                failures.append(
                    _unexpected(
                        RunFailureCode.PUBLICATION_PLANNING_FAILED, publication_stage, error
                    )
                )

        if stages[RunStage.WRITE_SUMMARY] is RunStageState.PENDING:
            transition(RunStage.WRITE_SUMMARY, RunStageState.RUNNING)
            await emit(
                RunEventCode.STAGE_STARTED,
                RunLifecycle.RUNNING,
                RunStage.WRITE_SUMMARY,
                "Summary serialization started",
            )
            try:
                provisional = replace(
                    result(_reconcile(stages, warnings, failures)),
                    stages=tuple(
                        RunStageRecord(
                            item.stage,
                            (
                                RunStageState.COMPLETED
                                if item.stage is RunStage.WRITE_SUMMARY
                                else item.state
                            ),
                            item.explanation,
                        )
                        for item in records()
                    ),
                )
                summaries = serialize_summaries(provisional)
                if request.summary_configuration is not None:
                    summary_write = self._summary_writer.write(
                        summaries, request.summary_configuration
                    )
                if summary_write is not None and summary_write.state in {
                    RunSummaryWriteState.BLOCKED,
                    RunSummaryWriteState.PARTIALLY_FAILED,
                }:
                    transition(
                        RunStage.WRITE_SUMMARY, RunStageState.FAILED, "Summary writing failed"
                    )
                    failures.append(
                        RunFailure(
                            RunFailureCode.SUMMARY_WRITING_FAILED,
                            RunStage.WRITE_SUMMARY,
                            "Summary writing failed",
                        )
                    )
                    summaries = serialize_summaries(result(_reconcile(stages, warnings, failures)))
                else:
                    transition(RunStage.WRITE_SUMMARY, RunStageState.COMPLETED)
                await emit(
                    RunEventCode.STAGE_COMPLETED,
                    RunLifecycle.RUNNING,
                    RunStage.WRITE_SUMMARY,
                    "Summary stage finished",
                )
            except Exception as error:  # noqa: BLE001
                transition(
                    RunStage.WRITE_SUMMARY, RunStageState.FAILED, "Summary serialization failed"
                )
                failures.append(
                    _unexpected(
                        RunFailureCode.SUMMARY_SERIALIZATION_FAILED, RunStage.WRITE_SUMMARY, error
                    )
                )

        lifecycle = _reconcile(stages, warnings, failures)
        final_code = {
            RunLifecycle.CANCELLED: RunEventCode.RUN_CANCELLED,
            RunLifecycle.FAILED: RunEventCode.RUN_FAILED,
        }.get(lifecycle, RunEventCode.RUN_COMPLETED)
        await emit(final_code, lifecycle, None, "Run finished")
        return result(_reconcile(stages, warnings, failures))


def _block_dependents(
    stages: dict[RunStage, RunStageState],
    explanations: dict[RunStage, str | None],
    failed: RunStage,
) -> None:
    order = (
        RunStage.CRAWL,
        RunStage.RECOMMEND,
        RunStage.GENERATE_XML,
        RunStage.PLAN_PUBLICATION,
        RunStage.PUBLISH,
    )
    if failed not in order:
        return
    for stage in order[order.index(failed) + 1 :]:
        if stages[stage] is RunStageState.PENDING:
            stages[stage] = RunStageState.BLOCKED
            explanations[stage] = f"Blocked because {failed.value} did not complete"


def _reconcile(
    stages: dict[RunStage, RunStageState],
    warnings: list[RunWarning],
    failures: list[RunFailure],
) -> RunLifecycle:
    terminal = tuple(state for state in stages.values() if state is not RunStageState.NOT_REQUESTED)
    if any(state is RunStageState.CANCELLED for state in terminal):
        return RunLifecycle.CANCELLED
    if any(state is RunStageState.FAILED for state in terminal):
        completed = any(
            state in {RunStageState.COMPLETED, RunStageState.COMPLETED_WITH_WARNINGS}
            for state in terminal
        )
        return RunLifecycle.PARTIALLY_COMPLETED if completed else RunLifecycle.FAILED
    if warnings or any(state is RunStageState.COMPLETED_WITH_WARNINGS for state in terminal):
        return RunLifecycle.COMPLETED_WITH_WARNINGS
    if failures:
        return RunLifecycle.PARTIALLY_COMPLETED
    return RunLifecycle.COMPLETED


def _unexpected(code: RunFailureCode, stage: RunStage, error: Exception) -> RunFailure:
    return RunFailure(code, stage, "The internal stage failed", type(error).__name__)


def _snapshot(  # noqa: PLR0913 - mirrors the immutable progress record.
    lifecycle: RunLifecycle,
    stage: RunStage | None,
    stage_state: RunStageState | None,
    crawl: CrawlResult | None,
    projection: SitemapRecommendationProjection | None,
    bundle: SitemapXmlBundle | None,
    publication: SitemapPublicationResult | None,
    warnings: list[RunWarning],
    failures: list[RunFailure],
    cancelled: bool,  # noqa: FBT001 - mirrors the public cancellation flag.
    elapsed: float,
    crawl_progress: ProgressSnapshot | None,
) -> RunProgressSnapshot:
    counters = (
        crawl_progress.counters if crawl_progress is not None else crawl.counters if crawl else None
    )
    return RunProgressSnapshot(
        lifecycle=lifecycle,
        active_stage=stage,
        stage_state=stage_state,
        crawl_progress=crawl_progress,
        urls_discovered=counters.unique_urls_discovered if counters else 0,
        urls_queued=counters.urls_queued if counters else 0,
        urls_fetched=counters.urls_fetched if counters else 0,
        urls_parsed=counters.html_pages_parsed if counters else 0,
        bytes_fetched=(
            crawl_progress.total_accepted_bytes
            if crawl_progress
            else crawl.total_accepted_bytes
            if crawl
            else 0
        ),
        queue_size=crawl_progress.queue_size if crawl_progress else 0,
        active_count=crawl_progress.active_count if crawl_progress else 0,
        current_depth=crawl_progress.current_depth if crawl_progress else None,
        recommendation_counts=(
            None
            if projection is None
            else (
                projection.included_url_count,
                projection.excluded_url_count,
                projection.review_count,
                projection.indeterminate_count,
            )
        ),
        xml_document_count=bundle.total_documents if bundle else None,
        xml_entry_count=bundle.total_entries if bundle else None,
        publication_file_count=publication.published_file_count if publication else None,
        warning_count=len(warnings),
        failure_count=len(failures),
        cancellation_requested=cancelled,
        recent_crawl_error_code=(
            crawl_progress.recent_error_code.value
            if crawl_progress is not None and crawl_progress.recent_error_code is not None
            else None
        ),
        elapsed_seconds=elapsed,
    )


def _crawl_progress_differs(snapshot: ProgressSnapshot | None, crawl: CrawlResult) -> bool:
    """Return whether the last callback trails authoritative final crawl evidence."""
    if snapshot is None:
        return True
    counters = snapshot.counters
    final = crawl.counters
    return (
        counters.unique_urls_discovered != final.unique_urls_discovered
        or counters.urls_queued != final.urls_queued
        or counters.urls_fetched != final.urls_fetched
        or counters.html_pages_parsed != final.html_pages_parsed
        or snapshot.total_accepted_bytes != crawl.total_accepted_bytes
        or snapshot.queue_size != 0
        or snapshot.active_count != 0
    )


def _missing_evidence(label: str) -> NoReturn:
    message = f"{label} is unavailable"
    raise RuntimeError(message)
