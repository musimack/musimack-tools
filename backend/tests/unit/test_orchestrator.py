"""Deterministic integration-style tests for in-memory crawl orchestration."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import FrozenInstanceError, dataclass, replace
from typing import TYPE_CHECKING, Any

import pytest

from musimack_tools.crawl.cancellation import CrawlCancellationToken
from musimack_tools.crawl.html import HtmlMetadataParser
from musimack_tools.crawl.limits import CrawlHardLimits
from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.orchestrator import SingleSiteCrawlOrchestrator
from musimack_tools.crawl.robots import RobotsTxtService
from musimack_tools.crawl.scope import create_scope_policy
from musimack_tools.domain.crawl import (
    CrawlErrorCode,
    CrawlExclusionRule,
    CrawlRequest,
    CrawlResult,
    CrawlState,
    ExclusionRuleType,
    FrontierState,
    LimitKind,
    LinkAdmissionReason,
    ProgressSnapshot,
    UrlCrawlOutcome,
)
from musimack_tools.domain.fetching import (
    FetchFailureCode,
    FetchOutcome,
    FetchRequest,
    FetchResult,
    RedirectHop,
    ResponseHeaders,
)
from musimack_tools.domain.html import HtmlParseResult, HtmlWarningCode
from musimack_tools.domain.indexability import IndexabilityWarningCode
from musimack_tools.domain.robots import (
    CrawlPermissionDecision,
    CrawlPermissionReason,
    RobotsFetchOutcome,
    RobotsOriginRecord,
    RobotsParseOutcome,
    RobotsWarningCode,
)
from musimack_tools.domain.urls import CrawlScopePolicy, NormalizedUrl, ScopeMode

if TYPE_CHECKING:
    from collections.abc import Callable

_SEED = "https://example.test/"
_WORKER_FAILURE = "synthetic worker boundary failure"
_OBSERVER_FAILURE = "synthetic observer failure"
_PARSER_FAILURE = "synthetic parser boundary failure"


@dataclass(frozen=True, slots=True)
class _Page:
    body: str | bytes | None = "<html><title>A useful seed page title</title></html>"
    content_type: str | None = "text/html; charset=utf-8"
    outcome: FetchOutcome = FetchOutcome.SUCCESS
    status: int | None = 200
    final_url: str | None = None
    actual_bytes: int | None = None
    failure_code: FetchFailureCode | None = None
    redirect_from: str | None = None
    x_robots_tag: tuple[str, ...] = ()


class _FakeClock:
    def __init__(self) -> None:
        self.current = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.advance(seconds)
        await asyncio.sleep(0)


class _SequenceClock:
    def __init__(self, values: tuple[float, ...]) -> None:
        self._values = iter(values)
        self._last = values[-1]

    def __call__(self) -> float:
        self._last = next(self._values, self._last)
        return self._last


class _FakeFetcher:
    def __init__(
        self,
        pages: dict[str, _Page],
        *,
        clock: Callable[[], float],
        on_fetch: Callable[[str], None] | None = None,
        raise_for: frozenset[str] = frozenset(),
    ) -> None:
        self.pages = pages
        self.clock = clock
        self.on_fetch = on_fetch
        self.raise_for = raise_for
        self.calls: list[str] = []
        self.start_times: list[tuple[str, float]] = []
        self.active = 0
        self.maximum_active = 0

    async def fetch(self, request: FetchRequest, scope: CrawlScopePolicy) -> FetchResult:
        del scope
        url = request.url.normalized
        self.calls.append(url)
        self.start_times.append((url, self.clock()))
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            await asyncio.sleep(0)
            if self.on_fetch is not None:
                self.on_fetch(url)
            if url in self.raise_for:
                raise RuntimeError(_WORKER_FAILURE)
            page = self.pages[url]
            body = page.body.encode() if isinstance(page.body, str) else page.body
            actual_bytes = (
                page.actual_bytes
                if page.actual_bytes is not None
                else (len(body) if body is not None else 0)
            )
            final_url = page.final_url or url
            redirects = (
                (
                    RedirectHop(
                        source_url=page.redirect_from,
                        status_code=301,
                        raw_location=final_url,
                        destination_url=final_url,
                        allowed=True,
                        failure_code=None,
                        explanation="Synthetic accepted redirect",
                    ),
                )
                if page.redirect_from is not None
                else ()
            )
            return FetchResult(
                requested_url=url,
                final_url=final_url,
                outcome=page.outcome,
                status_code=page.status,
                headers=ResponseHeaders(
                    content_type=page.content_type,
                    x_robots_tag=page.x_robots_tag,
                ),
                content_type=page.content_type,
                declared_content_length=len(body) if body is not None else None,
                actual_bytes_read=actual_bytes,
                body_truncated=page.failure_code is FetchFailureCode.RESPONSE_TOO_LARGE,
                redirect_chain=redirects,
                request_duration_seconds=0.01,
                dns_evidence=(),
                failure_code=page.failure_code,
                failure_explanation=(
                    "Synthetic fetch failure" if page.outcome is FetchOutcome.FAILURE else None
                ),
                body=body,
            )
        finally:
            self.active -= 1


class _Observer:
    def __init__(self, *, fail: bool = False) -> None:
        self.snapshots: list[ProgressSnapshot] = []
        self.fail = fail

    async def on_progress(self, snapshot: ProgressSnapshot) -> None:
        self.snapshots.append(snapshot)
        if self.fail:
            raise RuntimeError(_OBSERVER_FAILURE)


class _RaisingParser:
    def parse(
        self,
        fetch: FetchResult,
        *,
        scope: CrawlScopePolicy | None = None,
    ) -> HtmlParseResult:
        del fetch, scope
        raise RuntimeError(_PARSER_FAILURE)


class _CancellingParser:
    def __init__(self, token: CrawlCancellationToken, clock: Callable[[], float]) -> None:
        self._token = token
        self._delegate = HtmlMetadataParser(clock=clock)

    def parse(
        self,
        fetch: FetchResult,
        *,
        scope: CrawlScopePolicy | None = None,
    ) -> HtmlParseResult:
        result = self._delegate.parse(fetch, scope=scope)
        self._token.cancel()
        return result


class AllowAllRobotsServiceForTests:
    """Explicit test-only policy for orchestration scenarios unrelated to robots."""

    def create_session(self) -> _AllowAllRobotsSessionForTests:
        return _AllowAllRobotsSessionForTests()


class _AllowAllRobotsSessionForTests:
    async def evaluate(
        self,
        url: NormalizedUrl,
        scope: CrawlScopePolicy,
        correlation_id: str | None = None,
    ) -> CrawlPermissionDecision:
        del scope, correlation_id
        return CrawlPermissionDecision(
            evaluated_url=url.normalized,
            origin=url.origin,
            robots_url=f"{url.origin}/robots.txt",
            fetch_outcome=RobotsFetchOutcome.NO_POLICY,
            parse_outcome=RobotsParseOutcome.NOT_APPLICABLE,
            selected_group_index=None,
            matched_rule=None,
            allowed=True,
            reason_code=CrawlPermissionReason.ALLOWED_TEST_POLICY,
            explanation="The explicitly injected test-only robots policy allows this URL",
            cache_hit=False,
            warnings=(),
            temporary_unavailability=False,
            newly_fetched_bytes=0,
            evaluation_duration_seconds=0.0,
        )

    def origin_records(self) -> tuple[RobotsOriginRecord, ...]:
        return ()


def _hard_limits() -> CrawlHardLimits:
    return CrawlHardLimits(1_000, 50, 7_200, 5_000_000_000, 16, 1_000)


def _scope(
    *,
    mode: ScopeMode = ScopeMode.EXACT_HOST,
    approved: tuple[str, ...] = (),
) -> CrawlScopePolicy:
    seed = normalize_url(_SEED)
    return create_scope_policy(seed, mode=mode, approved_hosts=approved)


def _request(scope: CrawlScopePolicy | None = None, **overrides: object) -> CrawlRequest:
    policy = scope or _scope()
    values: dict[str, object] = {
        "seed_url": policy.seed,
        "scope_policy": policy,
        "maximum_unique_urls": 100,
        "maximum_depth": 5,
        "maximum_duration_seconds": 60,
        "maximum_total_fetched_bytes": 1_000_000,
        "maximum_concurrent_fetches": 2,
        "maximum_queued_urls": 100,
        "minimum_per_origin_delay_seconds": 0,
    }
    values.update(overrides)
    return CrawlRequest(**values)  # type: ignore[arg-type]


def _run(  # noqa: PLR0913 - central test harness exposes every injected boundary.
    pages: dict[str, _Page],
    *,
    request: CrawlRequest | None = None,
    clock: _FakeClock | _SequenceClock | None = None,
    token: CrawlCancellationToken | None = None,
    observer: _Observer | None = None,
    on_fetch: Callable[[str], None] | None = None,
    raise_for: frozenset[str] = frozenset(),
    parser: object | None = None,
    enable_robots: bool = False,
) -> tuple[CrawlResult, _FakeFetcher, _FakeClock | _SequenceClock]:
    selected_clock = clock or _FakeClock()
    fetcher = _FakeFetcher(
        pages,
        clock=selected_clock,
        on_fetch=on_fetch,
        raise_for=raise_for,
    )
    robots_service = (
        RobotsTxtService(fetcher, clock=selected_clock)
        if enable_robots
        else AllowAllRobotsServiceForTests()
    )
    orchestrator = SingleSiteCrawlOrchestrator(
        fetcher,
        parser or HtmlMetadataParser(clock=selected_clock),  # type: ignore[arg-type]
        _hard_limits(),
        robots_service,
        clock=selected_clock,
        sleep=(selected_clock.sleep if isinstance(selected_clock, _FakeClock) else asyncio.sleep),
        observer=observer,
        cancellation=token,
    )
    return asyncio.run(orchestrator.crawl(request or _request())), fetcher, selected_clock


def _html(*links: str, canonical: str | None = None) -> str:
    canonical_tag = f'<link rel="canonical" href="{canonical}">' if canonical else ""
    link_tags = "".join(links)
    return (
        "<html><head><title>A useful crawl page title</title>"
        '<meta name="description" content="A useful crawl page description retained for review '
        f'and deterministic test evidence.">{canonical_tag}</head><body>{link_tags}</body></html>'
    )


def test_robots_service_is_a_required_constructor_dependency() -> None:
    parameter = inspect.signature(SingleSiteCrawlOrchestrator).parameters["robots_service"]
    assert parameter.default is inspect.Parameter.empty

    constructor: Any = SingleSiteCrawlOrchestrator
    fetcher = _FakeFetcher({_SEED: _Page()}, clock=_FakeClock())
    with pytest.raises(TypeError, match="robots_service"):
        constructor(fetcher, HtmlMetadataParser(), _hard_limits())


def test_explicit_test_only_allow_policy_permits_unrelated_orchestration_test() -> None:
    result, fetcher, _clock = _run({_SEED: _Page(body=_html())})

    assert result.state is CrawlState.COMPLETED
    assert fetcher.calls == [_SEED]
    permission = result.url_records[0].robots_permission
    assert permission is not None
    assert permission.reason_code is CrawlPermissionReason.ALLOWED_TEST_POLICY


def test_seed_only_crawl_returns_immutable_completed_result() -> None:
    result, fetcher, _clock = _run({_SEED: _Page(body=_html())})

    assert result.state is CrawlState.COMPLETED
    assert fetcher.calls == [_SEED]
    assert len(result.url_records) == 1
    assert result.url_records[0].outcome is UrlCrawlOutcome.PARSED
    assert result.counters.urls_fetched == 1
    with pytest.raises(FrozenInstanceError):
        result.state = CrawlState.FAILED  # type: ignore[misc]


def test_one_page_discovers_one_child() -> None:
    child = "https://example.test/child"
    result, fetcher, _clock = _run(
        {_SEED: _Page(body=_html('<a href="/child">Child</a>')), child: _Page(body=_html())}
    )

    assert fetcher.calls == [_SEED, child]
    assert [record.discovery_depth for record in result.url_records] == [0, 1]
    assert result.discoveries[0].reason is LinkAdmissionReason.ADMITTED
    assert result.url_records[0].discovered_link_count == 1
    assert result.url_records[0].admitted_link_count == 1
    assert result.url_records[0].rejected_link_count == 0
    assert result.counters.total_links_observed == 1
    assert result.counters.links_admitted == 1


def test_three_level_crawl_fetches_in_breadth_first_order() -> None:
    pages = {
        _SEED: _Page(body=_html('<a href="/a">A</a>', '<a href="/b">B</a>')),
        "https://example.test/a": _Page(body=_html('<a href="/deep-a">Deep A</a>')),
        "https://example.test/b": _Page(body=_html('<a href="/deep-b">Deep B</a>')),
        "https://example.test/deep-a": _Page(body=_html()),
        "https://example.test/deep-b": _Page(body=_html()),
    }

    result, fetcher, _clock = _run(pages)

    assert fetcher.calls == [
        _SEED,
        "https://example.test/a",
        "https://example.test/b",
        "https://example.test/deep-a",
        "https://example.test/deep-b",
    ]
    assert [record.discovery_depth for record in result.url_records] == [0, 1, 1, 2, 2]


def test_duplicate_link_is_fetched_once() -> None:
    child = "https://example.test/child"
    result, fetcher, _clock = _run(
        {
            _SEED: _Page(
                body=_html(
                    '<a href="/child">First</a>',
                    '<a href="/child#fragment">Second</a>',
                )
            ),
            child: _Page(body=_html()),
        }
    )

    assert fetcher.calls.count(child) == 1
    assert result.counters.duplicate_discoveries == 1


def test_cross_host_link_is_rejected() -> None:
    result, fetcher, _clock = _run(
        {_SEED: _Page(body=_html('<a href="https://other.test/page">Other</a>'))}
    )

    assert fetcher.calls == [_SEED]
    assert result.discoveries[0].reason is LinkAdmissionReason.SCOPE_DENIED
    assert result.counters.urls_excluded_by_scope == 1


def test_absolute_same_host_link_is_admitted() -> None:
    child = "https://example.test/absolute"
    result, fetcher, _clock = _run(
        {_SEED: _Page(body=_html(f'<a href="{child}">Absolute</a>')), child: _Page(body=_html())}
    )

    assert fetcher.calls == [_SEED, child]
    assert result.discoveries[0].reason is LinkAdmissionReason.ADMITTED


def test_true_subdomain_is_denied_by_exact_host_scope() -> None:
    result, fetcher, _clock = _run(
        {_SEED: _Page(body=_html('<a href="https://news.example.test/page">News</a>'))}
    )

    assert fetcher.calls == [_SEED]
    assert result.discoveries[0].reason is LinkAdmissionReason.SCOPE_DENIED


def test_true_subdomain_is_admitted_by_subdomain_scope() -> None:
    child = "https://news.example.test/page"
    scope = _scope(mode=ScopeMode.INCLUDE_SUBDOMAINS)
    result, fetcher, _clock = _run(
        {_SEED: _Page(body=_html(f'<a href="{child}">News</a>')), child: _Page(body=_html())},
        request=_request(scope),
    )

    assert fetcher.calls == [_SEED, child]
    assert result.discoveries[0].reason is LinkAdmissionReason.ADMITTED


def test_different_port_is_denied_by_scope() -> None:
    result, fetcher, _clock = _run(
        {_SEED: _Page(body=_html('<a href="https://example.test:8443/page">Port</a>'))}
    )

    assert fetcher.calls == [_SEED]
    assert result.discoveries[0].reason is LinkAdmissionReason.SCOPE_DENIED


@pytest.mark.parametrize(
    ("href", "expected_reason"),
    [
        ("javascript:void(0)", LinkAdmissionReason.UNSUPPORTED_SCHEME),
        ("mailto:team@example.test", LinkAdmissionReason.UNSUPPORTED_SCHEME),
        ("", LinkAdmissionReason.EMPTY_HREF),
        ("#section", LinkAdmissionReason.FRAGMENT_ONLY),
    ],
)
def test_non_fetchable_link_forms_are_rejected_with_stable_reasons(
    href: str,
    expected_reason: LinkAdmissionReason,
) -> None:
    result, fetcher, _clock = _run({_SEED: _Page(body=_html(f'<a href="{href}">Link</a>'))})

    assert fetcher.calls == [_SEED]
    assert result.discoveries[0].reason is expected_reason


def test_same_document_absolute_link_is_rejected() -> None:
    result, fetcher, _clock = _run({_SEED: _Page(body=_html(f'<a href="{_SEED}">Same</a>'))})

    assert fetcher.calls == [_SEED]
    assert result.discoveries[0].reason is LinkAdmissionReason.SAME_DOCUMENT


def test_query_urls_preserve_order_and_repetition() -> None:
    first = "https://example.test/page?a=1&a=2&b="
    second = "https://example.test/page?b=&a=2&a=1"
    result, fetcher, _clock = _run(
        {
            _SEED: _Page(body=_html(f'<a href="{first}">One</a>', f'<a href="{second}">Two</a>')),
            first: _Page(body=_html()),
            second: _Page(body=_html()),
        }
    )

    assert fetcher.calls == [_SEED, first, second]
    assert result.counters.unique_urls_discovered == 3


def test_query_urls_can_be_explicitly_disabled() -> None:
    result, fetcher, _clock = _run(
        {_SEED: _Page(body=_html('<a href="/page?utm_source=test">Query</a>'))},
        request=_request(query_urls_allowed=False),
    )

    assert fetcher.calls == [_SEED]
    assert result.discoveries[0].reason is LinkAdmissionReason.QUERY_URL_DISALLOWED


def test_trailing_slash_variants_are_fetched_separately() -> None:
    result, fetcher, _clock = _run(
        {
            _SEED: _Page(body=_html('<a href="/page">One</a>', '<a href="/page/">Two</a>')),
            "https://example.test/page": _Page(body=_html()),
            "https://example.test/page/": _Page(body=_html()),
        }
    )

    assert fetcher.calls[-2:] == ["https://example.test/page", "https://example.test/page/"]
    assert result.counters.unique_urls_discovered == 3


def test_nofollow_link_is_still_admitted() -> None:
    child = "https://example.test/child"
    result, fetcher, _clock = _run(
        {
            _SEED: _Page(body=_html('<a href="/child" rel="nofollow">Child</a>')),
            child: _Page(body=_html()),
        }
    )

    assert child in fetcher.calls
    assert result.discoveries[0].nofollow is True
    assert result.discoveries[0].admitted is True


def test_canonical_does_not_replace_discovered_url() -> None:
    child = "https://example.test/child"
    result, fetcher, _clock = _run(
        {
            _SEED: _Page(body=_html('<a href="/child">Child</a>', canonical="/canonical")),
            child: _Page(body=_html()),
        }
    )

    assert fetcher.calls == [_SEED, child]
    assert result.url_records[0].parse_result is not None
    assert result.url_records[0].parse_result.canonical.selected_url == (
        "https://example.test/canonical"
    )


def test_fetch_failure_is_preserved_without_crashing_crawl() -> None:
    failed = "https://example.test/failure"
    result, _fetcher, _clock = _run(
        {
            _SEED: _Page(body=_html('<a href="/failure">Failure</a>')),
            failed: _Page(
                body=None,
                outcome=FetchOutcome.FAILURE,
                status=None,
                failure_code=FetchFailureCode.TRANSPORT_ERROR,
            ),
        }
    )

    assert result.state is CrawlState.COMPLETED_WITH_ERRORS
    record = next(item for item in result.url_records if item.requested_url == failed)
    assert record.outcome is UrlCrawlOutcome.FETCH_FAILED
    assert record.fetch_result is not None
    assert record.fetch_result.failure_code is FetchFailureCode.TRANSPORT_ERROR


def test_non_html_response_is_preserved_as_parser_skip() -> None:
    asset = "https://example.test/data.json"
    result, _fetcher, _clock = _run(
        {
            _SEED: _Page(body=_html('<a href="/data.json">Data</a>')),
            asset: _Page(body='{"ok":true}', content_type="application/json"),
        }
    )

    record = next(item for item in result.url_records if item.requested_url == asset)
    assert record.outcome is UrlCrawlOutcome.PARSE_SKIPPED
    assert record.parse_result is not None
    assert record.parse_result.reason_code.value == "non_html_content"
    assert result.counters.non_html_responses == 1


def test_parser_warnings_are_preserved_without_crawl_failure() -> None:
    result, _fetcher, _clock = _run({_SEED: _Page(body="<html></html>")})

    parse = result.url_records[0].parse_result
    assert parse is not None
    assert HtmlWarningCode.MISSING_TITLE in {warning.code for warning in parse.warnings}
    assert result.state is CrawlState.COMPLETED


def test_redirect_evidence_is_preserved_and_pending_final_is_not_refetched() -> None:
    redirected = "https://example.test/redirected"
    source = "https://example.test/source"
    result, fetcher, _clock = _run(
        {
            _SEED: _Page(
                body=_html('<a href="/source">Source</a>', '<a href="/redirected">Final</a>')
            ),
            source: _Page(
                body=_html(),
                final_url=redirected,
                redirect_from=source,
            ),
            redirected: _Page(body=_html()),
        },
        request=_request(maximum_concurrent_fetches=1),
    )

    assert fetcher.calls == [_SEED, source]
    source_record = next(item for item in result.url_records if item.requested_url == source)
    final_record = next(item for item in result.url_records if item.requested_url == redirected)
    assert source_record.fetch_result is not None
    assert len(source_record.fetch_result.redirect_chain) == 1
    assert final_record.skip_reason is LinkAdmissionReason.REDIRECT_FINAL_ALREADY_SEEN


def test_concurrency_is_bounded_and_worker_tasks_shut_down() -> None:
    pages = {
        _SEED: _Page(body=_html(*[f'<a href="/{index}">{index}</a>' for index in range(6)])),
        **{f"https://example.test/{index}": _Page(body=_html()) for index in range(6)},
    }
    request = _request(maximum_concurrent_fetches=3)

    result, fetcher, _clock = _run(pages, request=request)

    assert fetcher.maximum_active == 3
    assert fetcher.active == 0
    assert result.maximum_active_worker_count == 3


def test_progress_snapshots_are_immutable_and_meaningful() -> None:
    observer = _Observer()
    child = "https://example.test/child"
    result, _fetcher, _clock = _run(
        {_SEED: _Page(body=_html('<a href="/child">Child</a>')), child: _Page(body=_html())},
        observer=observer,
    )

    assert observer.snapshots[0].state is CrawlState.RUNNING
    assert observer.snapshots[-1].state is CrawlState.COMPLETED
    assert observer.snapshots[-1].counters.urls_fetched == 2
    with pytest.raises(FrozenInstanceError):
        observer.snapshots[0].queue_size = 99  # type: ignore[misc]
    assert result.errors == ()


def test_observer_failure_is_isolated_as_typed_error() -> None:
    observer = _Observer(fail=True)

    result, _fetcher, _clock = _run({_SEED: _Page(body=_html())}, observer=observer)

    assert result.state is CrawlState.COMPLETED_WITH_ERRORS
    assert all(error.code is CrawlErrorCode.PROGRESS_OBSERVER_FAILURE for error in result.errors)


def test_fetcher_exception_maps_to_worker_failure() -> None:
    result, fetcher, _clock = _run(
        {_SEED: _Page(body=_html())},
        raise_for=frozenset({_SEED}),
    )

    assert fetcher.active == 0
    assert result.state is CrawlState.FAILED
    assert result.errors[0].code is CrawlErrorCode.WORKER_FAILURE
    assert result.errors[0].internal_exception_type == "RuntimeError"


def test_parser_exception_maps_to_worker_failure() -> None:
    result, _fetcher, _clock = _run({_SEED: _Page(body=_html())}, parser=_RaisingParser())

    assert result.state is CrawlState.FAILED
    assert result.url_records[0].fetch_result is not None
    assert result.errors[0].code is CrawlErrorCode.WORKER_FAILURE


def test_url_limit_stops_admission_and_marks_pending_urls() -> None:
    result, fetcher, _clock = _run(
        {_SEED: _Page(body=_html('<a href="/one">One</a>', '<a href="/two">Two</a>'))},
        request=_request(maximum_unique_urls=2),
    )

    assert result.state is CrawlState.LIMIT_REACHED
    assert fetcher.calls == [_SEED]
    assert result.limit_events[0].kind is LimitKind.URLS
    assert any(record.frontier_state is FrontierState.SKIPPED for record in result.url_records)


def test_depth_limit_rejects_children_without_ending_crawl() -> None:
    result, fetcher, _clock = _run(
        {_SEED: _Page(body=_html('<a href="/child">Child</a>'))},
        request=_request(maximum_depth=0),
    )

    assert result.state is CrawlState.COMPLETED
    assert fetcher.calls == [_SEED]
    assert result.discoveries[0].reason is LinkAdmissionReason.DEPTH_EXCEEDED
    assert result.counters.urls_excluded_by_depth == 1


def test_duration_limit_can_stop_before_seed_fetch() -> None:
    clock = _SequenceClock((0.0, 61.0, 61.0, 61.0))
    result, fetcher, _clock = _run(
        {_SEED: _Page(body=_html())},
        request=_request(maximum_duration_seconds=60),
        clock=clock,
    )

    assert fetcher.calls == []
    assert result.state is CrawlState.LIMIT_REACHED
    assert result.limit_events[0].kind is LimitKind.DURATION


def test_duration_limit_during_crawl_preserves_completed_fetch() -> None:
    clock = _FakeClock()

    def advance_after_fetch(_url: str) -> None:
        clock.advance(61)

    result, fetcher, _clock = _run(
        {_SEED: _Page(body=_html('<a href="/child">Child</a>'))},
        request=_request(maximum_duration_seconds=60),
        clock=clock,
        on_fetch=advance_after_fetch,
    )

    assert fetcher.calls == [_SEED]
    assert result.state is CrawlState.LIMIT_REACHED
    assert result.url_records[0].fetch_result is not None


def test_total_byte_limit_is_distinct_and_preserves_active_results() -> None:
    pages = {
        _SEED: _Page(body=_html('<a href="/a">A</a>', '<a href="/b">B</a>'), actual_bytes=1),
        "https://example.test/a": _Page(body=_html(), actual_bytes=10),
        "https://example.test/b": _Page(body=_html(), actual_bytes=10),
    }
    result, fetcher, _clock = _run(
        pages,
        request=_request(maximum_total_fetched_bytes=15, maximum_concurrent_fetches=2),
    )

    assert result.state is CrawlState.LIMIT_REACHED
    assert fetcher.calls == [_SEED, "https://example.test/a", "https://example.test/b"]
    assert result.total_accepted_bytes == 21
    assert result.limit_events[0].kind is LimitKind.BYTES


def test_queue_limit_returns_typed_limit_without_deadlock() -> None:
    result, fetcher, _clock = _run(
        {
            _SEED: _Page(
                body=_html(
                    '<a href="/one">One</a>',
                    '<a href="/two">Two</a>',
                    '<a href="/three">Three</a>',
                )
            )
        },
        request=_request(maximum_queued_urls=2),
    )

    assert result.state is CrawlState.LIMIT_REACHED
    assert fetcher.calls == [_SEED]
    assert result.limit_events[0].kind is LimitKind.QUEUE
    assert result.maximum_observed_queue_size == 2


def test_per_response_size_failure_does_not_become_total_byte_limit() -> None:
    result, _fetcher, _clock = _run(
        {
            _SEED: _Page(
                body=None,
                outcome=FetchOutcome.FAILURE,
                status=None,
                actual_bytes=5,
                failure_code=FetchFailureCode.RESPONSE_TOO_LARGE,
            )
        },
        request=_request(maximum_total_fetched_bytes=100),
    )

    assert result.state is CrawlState.COMPLETED_WITH_ERRORS
    assert result.limit_events == ()
    assert result.url_records[0].fetch_result is not None
    assert result.url_records[0].fetch_result.failure_code is FetchFailureCode.RESPONSE_TOO_LARGE


@pytest.mark.parametrize(
    ("rule", "href"),
    [
        (CrawlExclusionRule(ExclusionRuleType.EXACT_PATH, "/private"), "/private"),
        (CrawlExclusionRule(ExclusionRuleType.PATH_PREFIX, "/admin"), "/admin/users"),
        (
            CrawlExclusionRule(ExclusionRuleType.QUERY_PARAMETER, "session"),
            "/page?session=abc",
        ),
    ],
)
def test_explicit_exclusion_rules_are_deterministic(
    rule: CrawlExclusionRule,
    href: str,
) -> None:
    result, fetcher, _clock = _run(
        {_SEED: _Page(body=_html(f'<a href="{href}">Excluded</a>'))},
        request=_request(exclusion_rules=(rule,)),
    )

    assert fetcher.calls == [_SEED]
    assert result.discoveries[0].reason is LinkAdmissionReason.EXCLUDED_BY_RULE


def test_same_origin_minimum_delay_is_shared_across_workers() -> None:
    clock = _FakeClock()
    pages = {
        _SEED: _Page(body=_html('<a href="/a">A</a>', '<a href="/b">B</a>')),
        "https://example.test/a": _Page(body=_html()),
        "https://example.test/b": _Page(body=_html()),
    }
    _result, fetcher, _clock = _run(
        pages,
        request=_request(minimum_per_origin_delay_seconds=0.5),
        clock=clock,
    )

    assert fetcher.start_times == [
        (_SEED, 0.0),
        ("https://example.test/a", 0.5),
        ("https://example.test/b", 1.0),
    ]
    assert clock.sleeps == [0.5, 0.5]


def test_different_origins_have_independent_pacing() -> None:
    clock = _FakeClock()
    policy = _scope(mode=ScopeMode.APPROVED_HOSTS, approved=("other.test",))
    other = "https://other.test/page"
    same = "https://example.test/page"
    pages = {
        _SEED: _Page(body=_html(f'<a href="{other}">Other</a>', '<a href="/page">Same</a>')),
        other: _Page(body=_html()),
        same: _Page(body=_html()),
    }
    _result, fetcher, _clock = _run(
        pages,
        request=_request(scope=policy, minimum_per_origin_delay_seconds=0.5),
        clock=clock,
    )

    starts = dict(fetcher.start_times)
    assert starts[other] == 0.0
    assert starts[same] == 0.5


def test_zero_delay_never_sleeps_or_calculates_negative_delay() -> None:
    clock = _FakeClock()
    child = "https://example.test/child"
    _result, _fetcher, _clock = _run(
        {_SEED: _Page(body=_html('<a href="/child">Child</a>')), child: _Page(body=_html())},
        clock=clock,
    )

    assert clock.sleeps == []


def test_cancel_before_start_marks_seed_skipped_and_fetches_nothing() -> None:
    token = CrawlCancellationToken()
    token.cancel()

    result, fetcher, _clock = _run({_SEED: _Page(body=_html())}, token=token)

    assert result.state is CrawlState.CANCELLED
    assert fetcher.calls == []
    assert result.url_records[0].skip_reason is LinkAdmissionReason.CANCELLED
    assert result.cancellation is not None


def test_cancel_after_fetch_preserves_fetch_evidence_and_skips_parse() -> None:
    token = CrawlCancellationToken()

    def cancel_after_fetch(_url: str) -> None:
        token.cancel()

    result, fetcher, _clock = _run(
        {_SEED: _Page(body=_html('<a href="/child">Child</a>'))},
        request=_request(minimum_per_origin_delay_seconds=0.5),
        token=token,
        on_fetch=cancel_after_fetch,
    )

    assert result.state is CrawlState.CANCELLED
    assert fetcher.calls == [_SEED]
    assert result.url_records[0].fetch_result is not None
    assert result.url_records[0].parse_result is None
    assert isinstance(_clock, _FakeClock)
    assert _clock.sleeps == []


def test_cancellation_before_link_admission_stops_frontier_additions() -> None:
    token = CrawlCancellationToken()
    clock = _FakeClock()
    result, fetcher, _clock = _run(
        {_SEED: _Page(body=_html('<a href="/a">A</a>', '<a href="/b">B</a>'))},
        token=token,
        clock=clock,
        parser=_CancellingParser(token, clock),
    )

    assert result.state is CrawlState.CANCELLED
    assert fetcher.calls == [_SEED]
    assert len(result.discoveries) == 2
    assert all(item.reason is LinkAdmissionReason.CRAWL_STOPPING for item in result.discoveries)
    assert result.counters.links_admitted == 0


def test_cancellation_with_active_workers_retains_all_started_fetches() -> None:
    token = CrawlCancellationToken()
    pages = {
        _SEED: _Page(body=_html('<a href="/a">A</a>', '<a href="/b">B</a>')),
        "https://example.test/a": _Page(body=_html()),
        "https://example.test/b": _Page(body=_html()),
    }

    def cancel_first_child(url: str) -> None:
        if url.endswith("/a"):
            token.cancel()

    result, fetcher, _clock = _run(
        pages,
        request=_request(maximum_concurrent_fetches=2),
        token=token,
        on_fetch=cancel_first_child,
    )

    assert result.state is CrawlState.CANCELLED
    assert fetcher.calls == [_SEED, "https://example.test/a", "https://example.test/b"]
    assert result.counters.urls_fetched == 3
    assert fetcher.active == 0


def test_cancellation_with_queued_items_stops_new_fetches_and_retains_records() -> None:
    token = CrawlCancellationToken()
    pages = {
        _SEED: _Page(body=_html('<a href="/a">A</a>', '<a href="/b">B</a>', '<a href="/c">C</a>')),
        "https://example.test/a": _Page(body=_html()),
        "https://example.test/b": _Page(body=_html()),
        "https://example.test/c": _Page(body=_html()),
    }

    def cancel_on_first_child(url: str) -> None:
        if url.endswith("/a"):
            token.cancel()

    result, fetcher, _clock = _run(
        pages,
        request=_request(maximum_concurrent_fetches=1),
        token=token,
        on_fetch=cancel_on_first_child,
    )

    assert result.state is CrawlState.CANCELLED
    assert fetcher.calls == [_SEED, "https://example.test/a"]
    skipped = [
        record for record in result.url_records if record.frontier_state is FrontierState.SKIPPED
    ]
    assert len(skipped) == 2
    assert all(record.skip_reason is LinkAdmissionReason.CANCELLED for record in skipped)
    assert result.cancellation is not None
    assert result.cancellation.queued_urls_skipped == 2


def test_cancellation_has_precedence_over_simultaneous_byte_limit() -> None:
    token = CrawlCancellationToken()

    def cancel(_url: str) -> None:
        token.cancel()

    result, _fetcher, _clock = _run(
        {_SEED: _Page(body=_html(), actual_bytes=10)},
        request=_request(maximum_total_fetched_bytes=10),
        token=token,
        on_fetch=cancel,
    )

    assert result.state is CrawlState.CANCELLED
    assert result.limit_events == ()


def test_invalid_request_over_hard_limit_returns_typed_failed_result() -> None:
    request = _request(maximum_unique_urls=1_001)
    result, fetcher, _clock = _run({_SEED: _Page(body=_html())}, request=request)

    assert result.state is CrawlState.FAILED
    assert fetcher.calls == []
    assert result.errors[0].code is CrawlErrorCode.INVALID_CRAWL_REQUEST


def test_seed_outside_scope_returns_typed_failure_without_fetch() -> None:
    seed = normalize_url("https://other.test/")
    request = replace(_request(), seed_url=seed)

    result, fetcher, _clock = _run({_SEED: _Page(body=_html())}, request=request)

    assert result.state is CrawlState.FAILED
    assert fetcher.calls == []
    assert result.errors[0].code is CrawlErrorCode.SEED_SCOPE_DENIED


def test_robots_allowed_seed_is_fetched_after_permission_evaluation() -> None:
    robots = "https://example.test/robots.txt"
    result, fetcher, _clock = _run(
        {
            robots: _Page(body="User-agent: *\nAllow: /", content_type="text/plain"),
            _SEED: _Page(body=_html()),
        },
        enable_robots=True,
    )

    assert fetcher.calls == [robots, _SEED]
    assert result.url_records[0].robots_permission is not None
    assert result.url_records[0].robots_permission.allowed is True
    assert result.counters.robots_fetches == 1


def test_robots_denied_seed_is_not_fetched() -> None:
    robots = "https://example.test/robots.txt"
    result, fetcher, _clock = _run(
        {
            robots: _Page(body="User-agent: *\nDisallow: /", content_type="text/plain"),
            _SEED: _Page(body=_html()),
        },
        enable_robots=True,
    )

    assert fetcher.calls == [robots]
    assert result.url_records[0].outcome is UrlCrawlOutcome.ROBOTS_DENIED
    assert result.url_records[0].skip_reason is LinkAdmissionReason.ROBOTS_DENIED
    assert result.counters.robots_denied_urls == 1


def test_child_denied_by_cached_robots_is_not_fetched() -> None:
    robots = "https://example.test/robots.txt"
    child = "https://example.test/private"
    result, fetcher, _clock = _run(
        {
            robots: _Page(
                body="User-agent: *\nDisallow: /private",
                content_type="text/plain",
            ),
            _SEED: _Page(body=_html('<a href="/private">Private</a>')),
            child: _Page(body=_html()),
        },
        enable_robots=True,
    )

    assert fetcher.calls == [robots, _SEED]
    child_record = next(item for item in result.url_records if item.requested_url == child)
    assert child_record.outcome is UrlCrawlOutcome.ROBOTS_DENIED
    assert child_record.robots_permission is not None
    assert child_record.robots_permission.cache_hit is True


def test_missing_robots_allows_pages_and_records_warning_counter() -> None:
    robots = "https://example.test/robots.txt"
    result, fetcher, _clock = _run(
        {
            robots: _Page(body="", content_type="text/plain", status=404),
            _SEED: _Page(body=_html()),
        },
        enable_robots=True,
    )

    assert fetcher.calls == [robots, _SEED]
    assert result.counters.robots_warnings == 1
    assert RobotsWarningCode.NOT_FOUND in {item.code for item in result.robots_origins[0].warnings}


def test_temporary_robots_failure_blocks_page_and_records_recoverable_error() -> None:
    robots = "https://example.test/robots.txt"
    result, fetcher, _clock = _run(
        {
            robots: _Page(body="", content_type="text/plain", status=500),
            _SEED: _Page(body=_html()),
        },
        enable_robots=True,
    )

    assert fetcher.calls == [robots]
    assert result.state is CrawlState.COMPLETED_WITH_ERRORS
    assert result.counters.robots_unavailable_origins == 1
    assert result.errors[0].code is CrawlErrorCode.ROBOTS_UNAVAILABLE


def test_robots_is_fetched_once_for_multiple_same_origin_pages() -> None:
    robots = "https://example.test/robots.txt"
    child = "https://example.test/child"
    result, fetcher, _clock = _run(
        {
            robots: _Page(body="User-agent: *\nAllow: /", content_type="text/plain"),
            _SEED: _Page(body=_html('<a href="/child">Child</a>')),
            child: _Page(body=_html()),
        },
        enable_robots=True,
    )

    assert fetcher.calls.count(robots) == 1
    assert result.counters.robots_fetches == 1
    assert result.counters.robots_cache_hits == 1


def test_approved_subdomain_gets_separate_origin_robots_policy() -> None:
    seed_robots = "https://example.test/robots.txt"
    child = "https://news.example.test/page"
    child_robots = "https://news.example.test/robots.txt"
    scope = _scope(mode=ScopeMode.INCLUDE_SUBDOMAINS)
    result, fetcher, _clock = _run(
        {
            seed_robots: _Page(body="User-agent: *\nAllow: /", content_type="text/plain"),
            _SEED: _Page(body=_html(f'<a href="{child}">News</a>')),
            child_robots: _Page(body="User-agent: *\nAllow: /", content_type="text/plain"),
            child: _Page(body=_html()),
        },
        request=_request(scope),
        enable_robots=True,
    )

    assert seed_robots in fetcher.calls
    assert child_robots in fetcher.calls
    assert result.counters.robots_origins_evaluated == 2
    assert len(result.robots_origins) == 2


def test_robots_bytes_count_separately_and_toward_total() -> None:
    robots = "https://example.test/robots.txt"
    robots_body = "User-agent: *\nAllow: /"
    result, _fetcher, _clock = _run(
        {
            robots: _Page(body=robots_body, content_type="text/plain"),
            _SEED: _Page(body=_html(), actual_bytes=10),
        },
        enable_robots=True,
    )

    assert result.counters.robots_bytes == len(robots_body.encode())
    assert result.total_accepted_bytes == len(robots_body.encode()) + 10
    assert result.url_records[0].accepted_response_bytes == 10


def test_x_robots_and_meta_evidence_are_attached_with_conflict() -> None:
    robots = "https://example.test/robots.txt"
    body = _html().replace(
        "</head>",
        '<meta name="robots" content="index"></head>',
    )
    result, _fetcher, _clock = _run(
        {
            robots: _Page(body="User-agent: *\nAllow: /", content_type="text/plain"),
            _SEED: _Page(body=body, x_robots_tag=("noindex",)),
        },
        enable_robots=True,
    )

    record = result.url_records[0]
    assert record.x_robots_tag is not None
    assert record.indexability_evidence is not None
    assert IndexabilityWarningCode.META_HEADER_INDEX_CONFLICT in {
        item.code for item in record.indexability_evidence.warnings
    }


def test_noindex_page_still_discovers_links() -> None:
    robots = "https://example.test/robots.txt"
    child = "https://example.test/child"
    result, fetcher, _clock = _run(
        {
            robots: _Page(body="User-agent: *\nAllow: /", content_type="text/plain"),
            _SEED: _Page(
                body=_html('<a href="/child">Child</a>'),
                x_robots_tag=("noindex",),
            ),
            child: _Page(body=_html()),
        },
        enable_robots=True,
    )

    assert child in fetcher.calls
    assert result.counters.links_admitted == 1


def test_cancellation_during_robots_retrieval_stops_page_fetch() -> None:
    robots = "https://example.test/robots.txt"
    token = CrawlCancellationToken()

    def cancel_during_robots(url: str) -> None:
        if url == robots:
            token.cancel()

    result, fetcher, _clock = _run(
        {
            robots: _Page(body="User-agent: *\nAllow: /", content_type="text/plain"),
            _SEED: _Page(body=_html()),
        },
        token=token,
        on_fetch=cancel_during_robots,
        enable_robots=True,
    )

    assert result.state is CrawlState.CANCELLED
    assert fetcher.calls == [robots]
    assert result.url_records[0].robots_permission is not None


def test_duration_limit_during_robots_retrieval_stops_page_fetch() -> None:
    robots = "https://example.test/robots.txt"
    clock = _FakeClock()

    def advance_during_robots(url: str) -> None:
        if url == robots:
            clock.advance(61)

    result, fetcher, _clock = _run(
        {
            robots: _Page(body="User-agent: *\nAllow: /", content_type="text/plain"),
            _SEED: _Page(body=_html()),
        },
        request=_request(maximum_duration_seconds=60),
        clock=clock,
        on_fetch=advance_during_robots,
        enable_robots=True,
    )

    assert result.state is CrawlState.LIMIT_REACHED
    assert fetcher.calls == [robots]
    assert result.limit_events[0].kind is LimitKind.DURATION


def test_progress_snapshots_include_robots_counters_consistently() -> None:
    robots = "https://example.test/robots.txt"
    observer = _Observer()
    result, _fetcher, _clock = _run(
        {
            robots: _Page(body="User-agent: *\nAllow: /", content_type="text/plain"),
            _SEED: _Page(body=_html()),
        },
        observer=observer,
        enable_robots=True,
    )

    assert observer.snapshots[-1].counters.robots_fetches == 1
    assert observer.snapshots[-1].total_accepted_bytes == result.total_accepted_bytes


def test_real_robots_policy_preserves_breadth_first_page_order() -> None:
    robots = "https://example.test/robots.txt"
    pages = {
        robots: _Page(body="User-agent: *\nAllow: /", content_type="text/plain"),
        _SEED: _Page(body=_html('<a href="/a">A</a>', '<a href="/b">B</a>')),
        "https://example.test/a": _Page(body=_html('<a href="/deep">Deep</a>')),
        "https://example.test/b": _Page(body=_html()),
        "https://example.test/deep": _Page(body=_html()),
    }
    _result, fetcher, _clock = _run(
        pages,
        request=_request(maximum_concurrent_fetches=1),
        enable_robots=True,
    )

    assert fetcher.calls == [
        robots,
        _SEED,
        "https://example.test/a",
        "https://example.test/b",
        "https://example.test/deep",
    ]
