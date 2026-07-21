"""Bounded asynchronous orchestration for one in-memory single-site crawl."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, fields, replace
from typing import TYPE_CHECKING, Protocol, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from musimack_tools.crawl.cancellation import CancellationToken, NeverCancelledToken
from musimack_tools.crawl.frontier import CrawlFrontier
from musimack_tools.crawl.indexability import IndexabilityEvidenceParser
from musimack_tools.crawl.limits import (
    CrawlHardLimits,
    CrawlRequestValidationError,
    configuration_snapshot,
)
from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import evaluate_scope
from musimack_tools.domain.crawl import (
    CancellationEvidence,
    CrawlCounters,
    CrawlError,
    CrawlErrorCode,
    CrawlExclusionRule,
    CrawlRequest,
    CrawlResult,
    CrawlState,
    ExclusionRuleType,
    FrontierItem,
    FrontierState,
    LimitEvent,
    LimitKind,
    LinkAdmissionReason,
    LinkDiscoveryEvidence,
    ProgressSnapshot,
    UrlCrawlOutcome,
    UrlCrawlRecord,
)
from musimack_tools.domain.fetching import FetchOutcome, FetchRequest, FetchResult
from musimack_tools.domain.html import (
    HtmlParseOutcome,
    HtmlParseReasonCode,
    HtmlParseResult,
    LinkRecord,
)
from musimack_tools.domain.robots import CrawlPermissionDecision, CrawlPermissionReason

if TYPE_CHECKING:
    from musimack_tools.crawl.robots import RobotsCrawlSession, RobotsSessionFactory
    from musimack_tools.domain.urls import CrawlScopePolicy, NormalizedUrl

_LOGGER = logging.getLogger(__name__)

Clock = Callable[[], float]
Sleeper = Callable[[float], Awaitable[None]]

_ALLOWED_TRANSITIONS = {
    CrawlState.PENDING: {CrawlState.RUNNING, CrawlState.CANCELLED, CrawlState.FAILED},
    CrawlState.RUNNING: {
        CrawlState.CANCELLING,
        CrawlState.COMPLETED,
        CrawlState.COMPLETED_WITH_ERRORS,
        CrawlState.LIMIT_REACHED,
        CrawlState.FAILED,
    },
    CrawlState.CANCELLING: {CrawlState.CANCELLED, CrawlState.FAILED},
    CrawlState.LIMIT_REACHED: {CrawlState.CANCELLING, CrawlState.CANCELLED, CrawlState.FAILED},
}


class CrawlFetcher(Protocol):
    """Minimal accepted fetch boundary required by the orchestrator."""

    async def fetch(self, request: FetchRequest, scope: CrawlScopePolicy) -> FetchResult:
        """Fetch one already-normalized and in-scope URL."""
        ...


class CrawlHtmlParser(Protocol):
    """Minimal accepted parser boundary required by the orchestrator."""

    def parse(
        self,
        fetch: FetchResult,
        *,
        scope: CrawlScopePolicy | None = None,
    ) -> HtmlParseResult:
        """Parse one completed fetch result without networking."""
        ...


class ProgressObserver(Protocol):
    """Optional asynchronous recipient of immutable crawl snapshots."""

    async def on_progress(self, snapshot: ProgressSnapshot) -> None:
        """Observe progress without controlling crawl execution."""
        ...


@dataclass(slots=True)
class _MutableCounters:
    unique_urls_discovered: int = 0
    urls_queued: int = 0
    urls_fetched: int = 0
    fetch_successes: int = 0
    fetch_failures: int = 0
    html_pages_parsed: int = 0
    non_html_responses: int = 0
    parser_skips: int = 0
    urls_excluded_by_scope: int = 0
    urls_excluded_by_depth: int = 0
    urls_excluded_by_rule: int = 0
    duplicate_discoveries: int = 0
    redirect_responses: int = 0
    total_links_observed: int = 0
    links_admitted: int = 0
    links_rejected: int = 0
    urls_over_limit: int = 0
    robots_origins_evaluated: int = 0
    robots_fetches: int = 0
    robots_cache_hits: int = 0
    robots_unavailable_origins: int = 0
    robots_denied_urls: int = 0
    robots_warnings: int = 0
    robots_bytes: int = 0
    indexability_warnings: int = 0

    def freeze(self) -> CrawlCounters:
        values = {field.name: getattr(self, field.name) for field in fields(self)}
        return CrawlCounters(**values)


@dataclass(slots=True)
class _Runtime:
    request: CrawlRequest
    started_at: float
    frontier: CrawlFrontier
    robots_session: RobotsCrawlSession
    progress_observer: ProgressObserver | None
    state: CrawlState = CrawlState.PENDING
    counters: _MutableCounters = field(default_factory=_MutableCounters)
    records: dict[str, UrlCrawlRecord] = field(default_factory=dict)
    discoveries: list[LinkDiscoveryEvidence] = field(default_factory=list)
    limit_events: list[LimitEvent] = field(default_factory=list)
    errors: list[CrawlError] = field(default_factory=list)
    final_urls_seen: set[str] = field(default_factory=set)
    total_bytes: int = 0
    maximum_active: int = 0
    queued_cancelled: int = 0

    def transition(self, state: CrawlState) -> None:
        if state is self.state:
            return
        allowed = _ALLOWED_TRANSITIONS.get(self.state, set())
        if state not in allowed:
            message = f"invalid crawl state transition: {self.state} -> {state}"
            raise RuntimeError(message)
        self.state = state


@dataclass(frozen=True, slots=True)
class _FetchExecution:
    item: FrontierItem
    fetch_result: FetchResult | None
    started_at: float | None
    ended_at: float
    robots_permission: CrawlPermissionDecision | None = None
    stopping_limit: LimitKind | None = None
    cancelled_before_fetch: bool = False
    error: BaseException | None = None


class _OriginPacer:
    def __init__(self, delay: float, clock: Clock, sleep: Sleeper) -> None:
        self._delay = delay
        self._clock = clock
        self._sleep = sleep
        self._next_start: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, url: NormalizedUrl, cancellation: CancellationToken) -> float | None:
        lock = self._locks.setdefault(url.origin, asyncio.Lock())
        async with lock:
            if cancellation.is_cancelled():
                return None
            now = self._clock()
            delay = max(0.0, self._next_start.get(url.origin, now) - now)
            if delay > 0:
                await self._sleep(delay)
            if cancellation.is_cancelled():
                return None
            started = self._clock()
            self._next_start[url.origin] = started + self._delay
            return started


class SingleSiteCrawlOrchestrator:
    """Run one deterministic breadth-first crawl with bounded asynchronous fetch batches."""

    def __init__(  # noqa: PLR0913 - explicit injected boundaries keep orchestration testable.
        self,
        fetcher: CrawlFetcher,
        parser: CrawlHtmlParser,
        hard_limits: CrawlHardLimits,
        robots_service: RobotsSessionFactory,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleeper = asyncio.sleep,
        observer: ProgressObserver | None = None,
        cancellation: CancellationToken | None = None,
        indexability_parser: IndexabilityEvidenceParser | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._parser = parser
        self._hard_limits = hard_limits
        self._clock = clock
        self._sleep = sleep
        self._observer = observer
        self._cancellation = cancellation or NeverCancelledToken()
        self._robots_service = robots_service
        self._indexability = indexability_parser or IndexabilityEvidenceParser()

    async def crawl(
        self,
        request: CrawlRequest,
        *,
        observer: ProgressObserver | None = None,
    ) -> CrawlResult:
        """Execute one crawl and return complete immutable in-memory evidence."""
        started = self._clock()
        frontier = CrawlFrontier(maximum_queued_urls=request.maximum_queued_urls)
        runtime = _Runtime(
            request=request,
            started_at=started,
            frontier=frontier,
            robots_session=self._robots_service.create_session(),
            progress_observer=observer if observer is not None else self._observer,
        )
        try:
            self._hard_limits.validate(request)
        except CrawlRequestValidationError as error:
            runtime.errors.append(CrawlError(error.code, error.explanation))
            runtime.transition(CrawlState.FAILED)
            return self._result(runtime)

        seed_scope = evaluate_scope(request.scope_policy, request.seed_url)
        if not seed_scope.allowed:
            runtime.errors.append(
                CrawlError(
                    CrawlErrorCode.SEED_SCOPE_DENIED,
                    "The seed URL is outside the immutable crawl scope policy",
                    url=_safe_url_summary(request.seed_url),
                )
            )
            runtime.transition(CrawlState.FAILED)
            return self._result(runtime)

        seed_admission = frontier.admit(
            request.seed_url,
            discovered_value=request.seed_url.original,
            referrer=None,
            depth=0,
        )
        runtime.counters.urls_queued = 1 if seed_admission.queued else 0
        runtime.counters.unique_urls_discovered = frontier.unique_count
        runtime.transition(CrawlState.RUNNING)
        _LOGGER.info(
            "crawl_started",
            extra={
                "correlation_id": request.correlation_id,
                "url": _safe_url_summary(request.seed_url),
            },
        )
        await self._emit(runtime, current_depth=0)

        pacer = _OriginPacer(request.minimum_per_origin_delay_seconds, self._clock, self._sleep)
        while runtime.frontier.pending_count:
            self._check_stopping_conditions(runtime)
            if runtime.state is not CrawlState.RUNNING:
                break
            batch = runtime.frontier.pop_depth_batch(request.maximum_concurrent_fetches)
            if not batch:
                self._fail_invariant(
                    runtime, "The frontier reported pending URLs but yielded no work"
                )
                break
            runtime.maximum_active = max(runtime.maximum_active, len(batch))
            executions = await self._run_batch(
                batch,
                request,
                pacer,
                runtime.robots_session,
                runtime.started_at,
                runtime.total_bytes,
            )
            for execution in executions:
                await self._process_execution(runtime, execution)
            await self._emit(runtime, current_depth=batch[0].best_known_depth)

        self._finish(runtime)
        await self._emit(runtime, current_depth=None)
        result = self._result(runtime)
        _LOGGER.info(
            "crawl_completed",
            extra={
                "correlation_id": request.correlation_id,
                "state": result.state.value,
                "duration_seconds": result.duration_seconds,
                "url_count": len(result.url_records),
            },
        )
        return result

    async def _run_batch(  # noqa: PLR0913 - explicit batch context avoids shared mutable state.
        self,
        batch: tuple[FrontierItem, ...],
        request: CrawlRequest,
        pacer: _OriginPacer,
        robots_session: RobotsCrawlSession,
        crawl_started_at: float,
        accepted_bytes_before_batch: int,
    ) -> tuple[_FetchExecution, ...]:
        tasks = [
            asyncio.create_task(
                self._fetch_item(
                    item,
                    request,
                    pacer,
                    robots_session,
                    crawl_started_at,
                    accepted_bytes_before_batch,
                )
            )
            for item in batch
        ]
        results = await asyncio.gather(*tasks)
        return tuple(results)

    async def _fetch_item(  # noqa: PLR0911, PLR0913 - bounded stops return typed evidence.
        self,
        item: FrontierItem,
        request: CrawlRequest,
        pacer: _OriginPacer,
        robots_session: RobotsCrawlSession,
        crawl_started_at: float,
        accepted_bytes_before_batch: int,
    ) -> _FetchExecution:
        if self._cancellation.is_cancelled():
            return _FetchExecution(
                item=item,
                fetch_result=None,
                started_at=None,
                ended_at=self._clock(),
                cancelled_before_fetch=True,
            )
        robots_started = self._clock()
        try:
            permission = await robots_session.evaluate(
                item.url,
                request.scope_policy,
                request.correlation_id,
            )
        except Exception as error:  # noqa: BLE001 - injected robots boundary maps safely.
            return _FetchExecution(item, None, robots_started, self._clock(), error=error)
        if self._cancellation.is_cancelled():
            return _FetchExecution(
                item,
                None,
                robots_started,
                self._clock(),
                robots_permission=permission,
                cancelled_before_fetch=True,
            )
        if self._clock() - crawl_started_at >= request.maximum_duration_seconds:
            return _FetchExecution(
                item,
                None,
                robots_started,
                self._clock(),
                robots_permission=permission,
                stopping_limit=LimitKind.DURATION,
            )
        if (
            accepted_bytes_before_batch + permission.newly_fetched_bytes
            >= request.maximum_total_fetched_bytes
        ):
            return _FetchExecution(
                item,
                None,
                robots_started,
                self._clock(),
                robots_permission=permission,
                stopping_limit=LimitKind.BYTES,
            )
        if not permission.allowed:
            return _FetchExecution(
                item,
                None,
                robots_started,
                self._clock(),
                robots_permission=permission,
            )
        started = await pacer.wait(item.url, self._cancellation)
        if started is None:
            return _FetchExecution(
                item=item,
                fetch_result=None,
                started_at=None,
                ended_at=self._clock(),
                robots_permission=permission,
                cancelled_before_fetch=True,
            )
        _LOGGER.info(
            "crawl_url_fetch_started",
            extra={
                "correlation_id": request.correlation_id,
                "url": _safe_url_summary(item.url),
                "depth": item.best_known_depth,
            },
        )
        try:
            fetch = await self._fetcher.fetch(
                FetchRequest(item.url, request.correlation_id),
                request.scope_policy,
            )
        except Exception as error:  # noqa: BLE001 - worker boundary maps injected failures.
            return _FetchExecution(
                item,
                None,
                started,
                self._clock(),
                robots_permission=permission,
                error=error,
            )
        return _FetchExecution(
            item,
            fetch,
            started,
            self._clock(),
            robots_permission=permission,
        )

    async def _process_execution(  # noqa: C901, PLR0912, PLR0915 - ordered evidence pipeline.
        self,
        runtime: _Runtime,
        execution: _FetchExecution,
    ) -> None:
        item = execution.item
        permission = execution.robots_permission
        if permission is not None:
            self._account_robots(runtime, permission)
        if execution.error is not None:
            self._record_worker_failure(
                runtime,
                item,
                execution.error,
                robots_permission=permission,
            )
            return
        if execution.stopping_limit is not None:
            runtime.frontier.complete(item.url.normalized)
            reason = LinkAdmissionReason.CRAWL_STOPPING
            runtime.records[item.url.normalized] = _robots_skipped_record(
                item,
                reason,
                execution.ended_at,
                permission,
            )
            if execution.stopping_limit is LimitKind.DURATION:
                self._set_limit(
                    runtime,
                    LimitKind.DURATION,
                    CrawlErrorCode.DURATION_LIMIT_REACHED,
                    runtime.request.maximum_duration_seconds,
                    self._elapsed(runtime),
                    "The maximum crawl duration was reached during robots evaluation",
                )
            else:
                self._set_limit(
                    runtime,
                    LimitKind.BYTES,
                    CrawlErrorCode.BYTE_LIMIT_REACHED,
                    runtime.request.maximum_total_fetched_bytes,
                    runtime.total_bytes,
                    "The maximum crawl byte count was reached during robots evaluation",
                )
            return
        if execution.cancelled_before_fetch:
            runtime.frontier.complete(item.url.normalized)
            runtime.records[item.url.normalized] = _robots_skipped_record(
                item,
                LinkAdmissionReason.CANCELLED,
                execution.ended_at,
                permission,
            )
            self._request_cancellation(runtime)
            return

        if permission is not None and not permission.allowed:
            runtime.frontier.complete(item.url.normalized)
            reason = (
                LinkAdmissionReason.ROBOTS_UNAVAILABLE
                if permission.temporary_unavailability
                else LinkAdmissionReason.ROBOTS_DENIED
            )
            runtime.records[item.url.normalized] = _robots_skipped_record(
                item,
                reason,
                execution.ended_at,
                permission,
            )
            if permission.temporary_unavailability and not any(
                error.code is CrawlErrorCode.ROBOTS_UNAVAILABLE and error.url == item.url.origin
                for error in runtime.errors
            ):
                runtime.errors.append(
                    CrawlError(
                        CrawlErrorCode.ROBOTS_UNAVAILABLE,
                        "robots.txt was temporarily unavailable for an origin",
                        url=item.url.origin,
                    )
                )
            return

        fetch = cast("FetchResult", execution.fetch_result)
        runtime.counters.urls_fetched += 1
        runtime.counters.redirect_responses += len(fetch.redirect_chain)
        runtime.total_bytes += fetch.actual_bytes_read
        if fetch.outcome is FetchOutcome.SUCCESS:
            runtime.counters.fetch_successes += 1
        else:
            runtime.counters.fetch_failures += 1

        self._check_post_fetch_stopping(runtime)
        x_robots = self._indexability.parse_x_robots_tag(
            fetch.headers.x_robots_tag if fetch.headers is not None else ()
        )
        parse: HtmlParseResult | None = None
        if fetch.outcome is FetchOutcome.SUCCESS and not self._cancellation.is_cancelled():
            try:
                parse = self._parser.parse(fetch, scope=runtime.request.scope_policy)
            except Exception as error:  # noqa: BLE001 - boundary maps unexpected parser failures.
                self._record_worker_failure(
                    runtime,
                    item,
                    error,
                    fetch=fetch,
                    robots_permission=permission,
                )
                return
            if parse.outcome is HtmlParseOutcome.PARSED:
                runtime.counters.html_pages_parsed += 1
            else:
                runtime.counters.parser_skips += 1
                if parse.reason_code is HtmlParseReasonCode.NON_HTML_CONTENT:
                    runtime.counters.non_html_responses += 1
        combined = self._indexability.combine(
            parse.meta_robots if parse is not None else (),
            x_robots,
        )
        runtime.counters.indexability_warnings += len(combined.warnings)

        if self._cancellation.is_cancelled():
            self._request_cancellation(runtime)

        discovered_count = len(parse.links) if parse is not None else 0
        admitted_count = 0
        rejected_count = 0
        if parse is not None:
            for link in parse.links:
                admitted = self._admit_link(runtime, fetch.final_url, item.best_known_depth, link)
                admitted_count += int(admitted)
                rejected_count += int(not admitted)

        runtime.frontier.complete(item.url.normalized)
        final_url = normalize_url(fetch.final_url)
        runtime.final_urls_seen.add(final_url.normalized)
        outcome = _url_outcome(fetch, parse)
        runtime.records[item.url.normalized] = UrlCrawlRecord(
            requested_url=item.url.normalized,
            first_discovered_value=item.first_discovered_value,
            first_referrer=item.first_referrer,
            referring_urls=item.referring_urls,
            discovery_depth=item.first_discovered_depth,
            best_known_depth=item.best_known_depth,
            discovery_order=item.discovery_order,
            frontier_state=FrontierState.COMPLETED,
            outcome=outcome,
            fetch_result=fetch,
            parse_result=parse,
            final_fetched_url=fetch.final_url,
            discovered_link_count=discovered_count,
            admitted_link_count=admitted_count,
            rejected_link_count=rejected_count,
            skip_reason=(
                LinkAdmissionReason.CANCELLED if self._cancellation.is_cancelled() else None
            ),
            started_at_seconds=execution.started_at,
            ended_at_seconds=execution.ended_at,
            accepted_response_bytes=fetch.actual_bytes_read,
            robots_permission=permission,
            x_robots_tag=x_robots,
            indexability_evidence=combined,
            robots_warning_count=len(permission.warnings) if permission is not None else 0,
            indexability_warning_count=len(combined.warnings),
        )
        self._deduplicate_redirect_final(runtime, item, final_url)
        _LOGGER.info(
            "crawl_url_completed",
            extra={
                "correlation_id": runtime.request.correlation_id,
                "url": _safe_url_summary(item.url),
                "depth": item.best_known_depth,
                "outcome": outcome.value,
            },
        )

    def _admit_link(
        self,
        runtime: _Runtime,
        source_url: str,
        source_depth: int,
        link: LinkRecord,
    ) -> bool:
        runtime.counters.total_links_observed += 1
        candidate_depth = source_depth + 1
        if self._cancellation.is_cancelled():
            self._request_cancellation(runtime)
        reason = self._pre_admission_reason(runtime, link, candidate_depth)
        normalized: NormalizedUrl | None = None
        if reason is None and link.normalized_url is not None:
            normalized = _normalize_discovered_url(
                link.normalized_url, runtime.request.strip_query_parameters
            )
            reason = self._policy_admission_reason(runtime, normalized, candidate_depth)

        admitted = False
        if reason is None and normalized is not None:
            if normalized.normalized in runtime.final_urls_seen:
                reason = LinkAdmissionReason.DUPLICATE_URL
            elif (
                not runtime.frontier.contains(normalized.normalized)
                and runtime.frontier.unique_count >= runtime.request.maximum_unique_urls
            ):
                reason = LinkAdmissionReason.URL_LIMIT_REACHED
                runtime.counters.urls_over_limit += 1
                self._record_admission_limit(runtime)
            else:
                admission = runtime.frontier.admit(
                    normalized,
                    discovered_value=link.raw_href or normalized.normalized,
                    referrer=source_url,
                    depth=candidate_depth,
                )
                reason = admission.reason
                admitted = reason in {
                    LinkAdmissionReason.ADMITTED,
                    LinkAdmissionReason.UPDATED_BETTER_DEPTH,
                }
                if admission.new_url:
                    runtime.counters.unique_urls_discovered = runtime.frontier.unique_count
                if admission.queued and admission.new_url:
                    runtime.counters.urls_queued += 1
                if reason is LinkAdmissionReason.QUEUE_LIMIT_REACHED:
                    self._record_frontier_skip(runtime, admission.item, reason)
                    self._set_limit(
                        runtime,
                        LimitKind.QUEUE,
                        CrawlErrorCode.QUEUE_LIMIT_REACHED,
                        runtime.request.maximum_queued_urls,
                        runtime.frontier.pending_count,
                        "The maximum pending URL queue size was reached",
                    )

        final_reason = reason or LinkAdmissionReason.INVALID_URL
        runtime.discoveries.append(
            LinkDiscoveryEvidence(
                source_url=source_url,
                raw_href=link.raw_href,
                normalized_url=(
                    normalized.normalized if normalized is not None else link.normalized_url
                ),
                candidate_depth=candidate_depth,
                occurrence_index=link.occurrence_index,
                nofollow=link.nofollow,
                admitted=admitted,
                reason=final_reason,
            )
        )
        if admitted:
            runtime.counters.links_admitted += 1
            _LOGGER.info(
                "crawl_url_admitted",
                extra={
                    "correlation_id": runtime.request.correlation_id,
                    "url": _safe_url_summary(cast("NormalizedUrl", normalized)),
                    "depth": candidate_depth,
                    "queue_size": runtime.frontier.pending_count,
                },
            )
        else:
            runtime.counters.links_rejected += 1
            self._count_rejection(runtime, final_reason)
            _LOGGER.info(
                "crawl_url_skipped",
                extra={
                    "correlation_id": runtime.request.correlation_id,
                    "source_url": source_url.split("?", maxsplit=1)[0],
                    "depth": candidate_depth,
                    "failure_code": final_reason.value,
                },
            )
        return admitted

    def _pre_admission_reason(
        self,
        runtime: _Runtime,
        link: LinkRecord,
        candidate_depth: int,
    ) -> LinkAdmissionReason | None:
        reason: LinkAdmissionReason | None = None
        if runtime.state is not CrawlState.RUNNING or self._cancellation.is_cancelled():
            reason = LinkAdmissionReason.CRAWL_STOPPING
        elif link.href_empty:
            reason = LinkAdmissionReason.EMPTY_HREF
        elif link.unsupported_scheme or link.javascript:
            reason = LinkAdmissionReason.UNSUPPORTED_SCHEME
        elif link.malformed or link.normalized_url is None:
            reason = LinkAdmissionReason.INVALID_URL
        elif link.fragment_only:
            reason = LinkAdmissionReason.FRAGMENT_ONLY
        elif link.same_document:
            reason = LinkAdmissionReason.SAME_DOCUMENT
        elif candidate_depth > runtime.request.maximum_depth:
            reason = LinkAdmissionReason.DEPTH_EXCEEDED
        return reason

    def _policy_admission_reason(
        self,
        runtime: _Runtime,
        normalized: NormalizedUrl,
        candidate_depth: int,
    ) -> LinkAdmissionReason | None:
        if candidate_depth > runtime.request.maximum_depth:
            return LinkAdmissionReason.DEPTH_EXCEEDED
        if not evaluate_scope(runtime.request.scope_policy, normalized).allowed:
            return LinkAdmissionReason.SCOPE_DENIED
        if not runtime.request.query_urls_allowed and urlsplit(normalized.normalized).query:
            return LinkAdmissionReason.QUERY_URL_DISALLOWED
        if _matches_exclusion_rule(normalized, runtime.request.exclusion_rules):
            return LinkAdmissionReason.EXCLUDED_BY_RULE
        return None

    def _check_stopping_conditions(self, runtime: _Runtime) -> None:
        if self._cancellation.is_cancelled():
            self._request_cancellation(runtime)
            return
        elapsed = self._elapsed(runtime)
        if elapsed >= runtime.request.maximum_duration_seconds:
            self._set_limit(
                runtime,
                LimitKind.DURATION,
                CrawlErrorCode.DURATION_LIMIT_REACHED,
                runtime.request.maximum_duration_seconds,
                elapsed,
                "The maximum crawl duration was reached",
            )
        elif runtime.total_bytes >= runtime.request.maximum_total_fetched_bytes:
            self._set_limit(
                runtime,
                LimitKind.BYTES,
                CrawlErrorCode.BYTE_LIMIT_REACHED,
                runtime.request.maximum_total_fetched_bytes,
                runtime.total_bytes,
                "The maximum total accepted response bytes were reached",
            )

    def _check_post_fetch_stopping(self, runtime: _Runtime) -> None:
        if self._cancellation.is_cancelled():
            self._request_cancellation(runtime)
            return
        if runtime.total_bytes >= runtime.request.maximum_total_fetched_bytes:
            self._set_limit(
                runtime,
                LimitKind.BYTES,
                CrawlErrorCode.BYTE_LIMIT_REACHED,
                runtime.request.maximum_total_fetched_bytes,
                runtime.total_bytes,
                "The maximum total accepted response bytes were reached",
            )
        elif self._elapsed(runtime) >= runtime.request.maximum_duration_seconds:
            self._set_limit(
                runtime,
                LimitKind.DURATION,
                CrawlErrorCode.DURATION_LIMIT_REACHED,
                runtime.request.maximum_duration_seconds,
                self._elapsed(runtime),
                "The maximum crawl duration was reached",
            )

    def _set_limit(  # noqa: PLR0913 - mirrors explicit immutable limit evidence fields.
        self,
        runtime: _Runtime,
        kind: LimitKind,
        code: CrawlErrorCode,
        configured: float,
        observed: float,
        explanation: str,
    ) -> None:
        if runtime.state is not CrawlState.RUNNING:
            return
        runtime.limit_events.append(
            LimitEvent(kind, code, explanation, configured, observed, self._elapsed(runtime))
        )
        runtime.transition(CrawlState.LIMIT_REACHED)
        _LOGGER.warning(
            "crawl_limit_reached",
            extra={
                "correlation_id": runtime.request.correlation_id,
                "failure_code": code.value,
                "observed_value": observed,
            },
        )

    def _record_admission_limit(self, runtime: _Runtime) -> None:
        """Retain a URL-ceiling warning without stopping already-admitted work."""

        if not any(item.kind is LimitKind.URLS for item in runtime.limit_events):
            runtime.limit_events.append(
                LimitEvent(
                    LimitKind.URLS,
                    CrawlErrorCode.URL_LIMIT_REACHED,
                    "The unique URL admission ceiling was reached; admitted work continued",
                    runtime.request.maximum_unique_urls,
                    runtime.frontier.unique_count,
                    self._elapsed(runtime),
                )
            )
            runtime.errors.append(
                CrawlError(
                    CrawlErrorCode.URL_LIMIT_REACHED,
                    "Additional unique discoveries were not admitted after the URL ceiling",
                )
            )
            _LOGGER.warning(
                "crawl_url_admission_limit_reached",
                extra={
                    "correlation_id": runtime.request.correlation_id,
                    "failure_code": CrawlErrorCode.URL_LIMIT_REACHED.value,
                    "observed_value": runtime.frontier.unique_count,
                },
            )

    def _request_cancellation(self, runtime: _Runtime) -> None:
        if runtime.state in {CrawlState.RUNNING, CrawlState.LIMIT_REACHED}:
            runtime.transition(CrawlState.CANCELLING)
        if runtime.state is CrawlState.CANCELLING:
            _LOGGER.info(
                "crawl_cancellation_requested",
                extra={"correlation_id": runtime.request.correlation_id},
            )

    def _finish(self, runtime: _Runtime) -> None:
        if runtime.state in {CrawlState.CANCELLING, CrawlState.LIMIT_REACHED, CrawlState.FAILED}:
            reason = (
                LinkAdmissionReason.CANCELLED
                if runtime.state is CrawlState.CANCELLING
                else LinkAdmissionReason.CRAWL_STOPPING
            )
            for item in runtime.frontier.drain_pending():
                self._record_frontier_skip(runtime, item, reason)
                if reason is LinkAdmissionReason.CANCELLED:
                    runtime.queued_cancelled += 1
        if runtime.state is CrawlState.CANCELLING:
            runtime.transition(CrawlState.CANCELLED)
        elif runtime.state is CrawlState.RUNNING:
            terminal = (
                CrawlState.COMPLETED_WITH_ERRORS
                if runtime.counters.fetch_failures or runtime.errors
                else CrawlState.COMPLETED
            )
            runtime.transition(terminal)

    def _record_frontier_skip(
        self,
        runtime: _Runtime,
        item: FrontierItem,
        reason: LinkAdmissionReason,
    ) -> None:
        runtime.records[item.url.normalized] = _skipped_record(item, reason, self._clock())
        _LOGGER.info(
            "crawl_url_skipped",
            extra={
                "correlation_id": runtime.request.correlation_id,
                "url": _safe_url_summary(item.url),
                "depth": item.best_known_depth,
                "failure_code": reason.value,
            },
        )

    def _deduplicate_redirect_final(
        self,
        runtime: _Runtime,
        requested: FrontierItem,
        final_url: NormalizedUrl,
    ) -> None:
        if final_url.normalized == requested.url.normalized:
            return
        skipped = runtime.frontier.skip_pending(final_url.normalized)
        if skipped is not None:
            self._record_frontier_skip(
                runtime,
                skipped,
                LinkAdmissionReason.REDIRECT_FINAL_ALREADY_SEEN,
            )
            runtime.counters.duplicate_discoveries += 1

    def _record_worker_failure(
        self,
        runtime: _Runtime,
        item: FrontierItem,
        error: BaseException,
        *,
        fetch: FetchResult | None = None,
        robots_permission: CrawlPermissionDecision | None = None,
    ) -> None:
        runtime.frontier.complete(item.url.normalized)
        runtime.records[item.url.normalized] = UrlCrawlRecord(
            requested_url=item.url.normalized,
            first_discovered_value=item.first_discovered_value,
            first_referrer=item.first_referrer,
            referring_urls=item.referring_urls,
            discovery_depth=item.first_discovered_depth,
            best_known_depth=item.best_known_depth,
            discovery_order=item.discovery_order,
            frontier_state=FrontierState.COMPLETED,
            outcome=UrlCrawlOutcome.WORKER_FAILED,
            fetch_result=fetch,
            parse_result=None,
            final_fetched_url=fetch.final_url if fetch is not None else None,
            discovered_link_count=0,
            admitted_link_count=0,
            rejected_link_count=0,
            skip_reason=None,
            started_at_seconds=None,
            ended_at_seconds=self._clock(),
            accepted_response_bytes=fetch.actual_bytes_read if fetch is not None else 0,
            robots_permission=robots_permission,
            robots_warning_count=(
                len(robots_permission.warnings) if robots_permission is not None else 0
            ),
        )
        runtime.errors.append(
            CrawlError(
                CrawlErrorCode.WORKER_FAILURE,
                "A crawl worker failed at an injected boundary",
                url=_safe_url_summary(item.url),
                internal_exception_type=type(error).__name__,
            )
        )
        if runtime.state in {
            CrawlState.RUNNING,
            CrawlState.CANCELLING,
            CrawlState.LIMIT_REACHED,
        }:
            runtime.transition(CrawlState.FAILED)
        _LOGGER.error(
            "crawl_worker_failed",
            extra={
                "correlation_id": runtime.request.correlation_id,
                "url": _safe_url_summary(item.url),
                "failure_code": CrawlErrorCode.WORKER_FAILURE.value,
            },
        )

    def _fail_invariant(self, runtime: _Runtime, explanation: str) -> None:
        runtime.errors.append(CrawlError(CrawlErrorCode.FRONTIER_INVARIANT_VIOLATION, explanation))
        if runtime.state in {
            CrawlState.RUNNING,
            CrawlState.CANCELLING,
            CrawlState.LIMIT_REACHED,
        }:
            runtime.transition(CrawlState.FAILED)

    @staticmethod
    def _account_robots(runtime: _Runtime, permission: CrawlPermissionDecision) -> None:
        if permission.reason_code is CrawlPermissionReason.ALLOWED_TEST_POLICY:
            return
        if permission.cache_hit:
            runtime.counters.robots_cache_hits += 1
        else:
            runtime.counters.robots_origins_evaluated += 1
            runtime.counters.robots_fetches += 1
            runtime.counters.robots_bytes += permission.newly_fetched_bytes
            runtime.total_bytes += permission.newly_fetched_bytes
            runtime.counters.robots_warnings += len(permission.warnings)
            if permission.temporary_unavailability:
                runtime.counters.robots_unavailable_origins += 1
        if not permission.allowed:
            runtime.counters.robots_denied_urls += 1

    async def _emit(self, runtime: _Runtime, *, current_depth: int | None) -> None:
        observer = runtime.progress_observer
        if observer is None:
            return
        snapshot = ProgressSnapshot(
            state=runtime.state,
            counters=runtime.counters.freeze(),
            queue_size=runtime.frontier.pending_count,
            active_count=sum(
                runtime.frontier.state_of(item.url.normalized) is FrontierState.ACTIVE
                for item in runtime.frontier.items_in_discovery_order()
            ),
            current_depth=current_depth,
            total_accepted_bytes=runtime.total_bytes,
            elapsed_seconds=self._elapsed(runtime),
            recent_error_code=runtime.errors[-1].code if runtime.errors else None,
        )
        try:
            await observer.on_progress(snapshot)
        except Exception as error:  # noqa: BLE001 - observer failures are isolated evidence.
            runtime.errors.append(
                CrawlError(
                    CrawlErrorCode.PROGRESS_OBSERVER_FAILURE,
                    "The progress observer raised an exception",
                    internal_exception_type=type(error).__name__,
                )
            )
            _LOGGER.warning(
                "crawl_observer_failed",
                extra={
                    "correlation_id": runtime.request.correlation_id,
                    "failure_code": CrawlErrorCode.PROGRESS_OBSERVER_FAILURE.value,
                },
            )

    def _result(self, runtime: _Runtime) -> CrawlResult:
        ended = self._clock()
        frontier_items = {
            item.url.normalized: item for item in runtime.frontier.items_in_discovery_order()
        }
        records = tuple(
            replace(
                record,
                first_referrer=frontier_items[url].first_referrer,
                referring_urls=frontier_items[url].referring_urls,
                best_known_depth=frontier_items[url].best_known_depth,
            )
            for url, record in sorted(
                runtime.records.items(),
                key=lambda pair: pair[1].discovery_order,
            )
        )
        runtime.counters.unique_urls_discovered = runtime.frontier.unique_count
        cancellation = (
            CancellationEvidence(
                requested=True,
                queued_urls_skipped=runtime.queued_cancelled,
                elapsed_seconds=self._elapsed(runtime),
            )
            if runtime.state is CrawlState.CANCELLED
            else None
        )
        return CrawlResult(
            seed_url=runtime.request.seed_url.normalized,
            scope_policy=runtime.request.scope_policy,
            started_at_seconds=runtime.started_at,
            ended_at_seconds=ended,
            duration_seconds=max(0.0, ended - runtime.started_at),
            state=runtime.state,
            url_records=records,
            discoveries=tuple(runtime.discoveries),
            counters=runtime.counters.freeze(),
            limit_events=tuple(runtime.limit_events),
            errors=tuple(runtime.errors),
            cancellation=cancellation,
            total_accepted_bytes=runtime.total_bytes,
            maximum_observed_queue_size=runtime.frontier.maximum_observed_queue_size,
            maximum_active_worker_count=runtime.maximum_active,
            configuration=configuration_snapshot(runtime.request),
            robots_origins=runtime.robots_session.origin_records(),
        )

    def _elapsed(self, runtime: _Runtime) -> float:
        return max(0.0, self._clock() - runtime.started_at)

    @staticmethod
    def _count_rejection(runtime: _Runtime, reason: LinkAdmissionReason) -> None:
        if reason is LinkAdmissionReason.SCOPE_DENIED:
            runtime.counters.urls_excluded_by_scope += 1
        elif reason is LinkAdmissionReason.DEPTH_EXCEEDED:
            runtime.counters.urls_excluded_by_depth += 1
        elif reason in {
            LinkAdmissionReason.EXCLUDED_BY_RULE,
            LinkAdmissionReason.QUERY_URL_DISALLOWED,
        }:
            runtime.counters.urls_excluded_by_rule += 1
        elif reason is LinkAdmissionReason.DUPLICATE_URL:
            runtime.counters.duplicate_discoveries += 1


def _url_outcome(fetch: FetchResult, parse: HtmlParseResult | None) -> UrlCrawlOutcome:
    if fetch.outcome is FetchOutcome.FAILURE:
        return UrlCrawlOutcome.FETCH_FAILED
    if parse is None:
        return UrlCrawlOutcome.FETCHED
    if parse.outcome is HtmlParseOutcome.PARSED:
        return UrlCrawlOutcome.PARSED
    return UrlCrawlOutcome.PARSE_SKIPPED


def _skipped_record(
    item: FrontierItem,
    reason: LinkAdmissionReason,
    ended_at: float,
) -> UrlCrawlRecord:
    return UrlCrawlRecord(
        requested_url=item.url.normalized,
        first_discovered_value=item.first_discovered_value,
        first_referrer=item.first_referrer,
        referring_urls=item.referring_urls,
        discovery_depth=item.first_discovered_depth,
        best_known_depth=item.best_known_depth,
        discovery_order=item.discovery_order,
        frontier_state=FrontierState.SKIPPED,
        outcome=UrlCrawlOutcome.SKIPPED,
        fetch_result=None,
        parse_result=None,
        final_fetched_url=None,
        discovered_link_count=0,
        admitted_link_count=0,
        rejected_link_count=0,
        skip_reason=reason,
        started_at_seconds=None,
        ended_at_seconds=ended_at,
        accepted_response_bytes=0,
    )


def _robots_skipped_record(
    item: FrontierItem,
    reason: LinkAdmissionReason,
    ended_at: float,
    permission: CrawlPermissionDecision | None,
) -> UrlCrawlRecord:
    return UrlCrawlRecord(
        requested_url=item.url.normalized,
        first_discovered_value=item.first_discovered_value,
        first_referrer=item.first_referrer,
        referring_urls=item.referring_urls,
        discovery_depth=item.first_discovered_depth,
        best_known_depth=item.best_known_depth,
        discovery_order=item.discovery_order,
        frontier_state=FrontierState.COMPLETED,
        outcome=(
            UrlCrawlOutcome.ROBOTS_DENIED
            if reason in {LinkAdmissionReason.ROBOTS_DENIED, LinkAdmissionReason.ROBOTS_UNAVAILABLE}
            else UrlCrawlOutcome.SKIPPED
        ),
        fetch_result=None,
        parse_result=None,
        final_fetched_url=None,
        discovered_link_count=0,
        admitted_link_count=0,
        rejected_link_count=0,
        skip_reason=reason,
        started_at_seconds=None,
        ended_at_seconds=ended_at,
        accepted_response_bytes=0,
        robots_permission=permission,
        robots_warning_count=len(permission.warnings) if permission is not None else 0,
    )


def _matches_exclusion_rule(
    url: NormalizedUrl,
    rules: tuple[CrawlExclusionRule, ...],
) -> bool:
    parts = urlsplit(url.normalized)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query_names = {name for name, _value in query}
    return any(
        (rule.rule_type is ExclusionRuleType.EXACT_URL and url.normalized == rule.value)
        or (rule.rule_type is ExclusionRuleType.EXACT_PATH and parts.path == rule.value)
        or (rule.rule_type is ExclusionRuleType.PATH_PREFIX and parts.path.startswith(rule.value))
        or (rule.rule_type is ExclusionRuleType.PATH_CONTAINS and rule.value in parts.path)
        or (rule.rule_type is ExclusionRuleType.PATH_SUFFIX and parts.path.endswith(rule.value))
        or (rule.rule_type is ExclusionRuleType.QUERY_PARAMETER and rule.value in query_names)
        or (
            rule.rule_type is ExclusionRuleType.QUERY_PARAMETER_EQUALS
            and tuple(rule.value.split("=", 1)) in query
        )
        for rule in rules
    )


def _normalize_discovered_url(value: str, strip_query_parameters: tuple[str, ...]) -> NormalizedUrl:
    normalized = normalize_url(value)
    if not strip_query_parameters:
        return normalized
    parts = urlsplit(normalized.normalized)
    stripped = frozenset(strip_query_parameters)
    query = urlencode(
        [
            (name, item)
            for name, item in parse_qsl(parts.query, keep_blank_values=True)
            if name not in stripped
        ],
        doseq=True,
    )
    return normalize_url(urlunsplit((parts.scheme, parts.netloc, parts.path, query, "")))


def _safe_url_summary(url: NormalizedUrl) -> str:
    path = urlsplit(url.normalized).path or "/"
    return f"{url.origin}{path}"
