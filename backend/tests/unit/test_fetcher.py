"""Bounded single-request fetch tests using mocked transport and DNS only."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx
import pytest

from musimack_tools.core.config import Settings
from musimack_tools.crawl.fetcher import SafeSingleUrlFetcher
from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.safety import DestinationSafetyValidator
from musimack_tools.crawl.scope import create_scope_policy
from musimack_tools.domain.fetching import (
    DnsEvidence,
    FetchFailureCode,
    FetchOutcome,
    FetchRequest,
    FetchResult,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_SAFE_ADDRESS = "93.184.216.34"
_SYNTHETIC_TIMEOUT = "synthetic timeout"
_SYNTHETIC_TRANSPORT_ERROR = "sensitive synthetic detail"
_FIRST_ATTEMPT_ERROR = "first attempt"
_Handler = (
    Callable[[httpx.Request], httpx.Response]
    | Callable[[httpx.Request], Coroutine[None, None, httpx.Response]]
)


@dataclass
class _FakeResolver:
    answers: tuple[str, ...] = (_SAFE_ADDRESS,)
    calls: list[str] = field(default_factory=list)

    async def resolve(self, hostname: str, *, maximum_answers: int) -> DnsEvidence:
        del maximum_answers
        self.calls.append(hostname)
        return DnsEvidence(hostname, self.answers)


class _TrackingStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def _settings(**overrides: object) -> Settings:
    return Settings.model_validate(overrides)


def _run_fetch(
    handler: _Handler,
    *,
    settings: Settings | None = None,
    resolver: _FakeResolver | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> tuple[FetchResult, _FakeResolver, SafeSingleUrlFetcher]:
    selected_settings = settings or _settings()
    selected_resolver = resolver or _FakeResolver()
    transport = httpx.MockTransport(handler)
    fetcher = SafeSingleUrlFetcher(
        selected_settings,
        DestinationSafetyValidator(selected_settings, selected_resolver),
        transport=transport,
        sleep=sleep,
    )
    url = normalize_url("https://example.test/")
    result = asyncio.run(fetcher.fetch(FetchRequest(url), create_scope_policy(url)))
    return result, selected_resolver, fetcher


def test_successful_200_retains_bounded_response_evidence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(
            200,
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "Content-Length": "5",
                "X-Robots-Tag": "noarchive",
                "ETag": '"abc"',
                "Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT",
            },
            content=b"hello",
        )

    result, resolver, _ = _run_fetch(handler)

    assert result.outcome is FetchOutcome.SUCCESS
    assert result.status_code == 200
    assert result.content_type == "text/html; charset=utf-8"
    assert result.declared_content_length == 5
    assert result.actual_bytes_read == 5
    assert result.body == b"hello"
    assert result.headers is not None
    assert result.headers.x_robots_tag == ("noarchive",)
    assert result.headers.etag == '"abc"'
    assert resolver.calls == ["example.test"]


def test_request_headers_are_identifiable_and_do_not_include_credentials() -> None:
    observed: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["user_agent"] = request.headers.get("user-agent")
        observed["accept"] = request.headers.get("accept")
        observed["cookie"] = request.headers.get("cookie")
        observed["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, content=b"")

    _, _, fetcher = _run_fetch(handler)

    assert observed == {
        "user_agent": "MusimackSEOToolkit/0.1",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "cookie": None,
        "authorization": None,
    }
    assert fetcher.trusts_environment_proxies is False


def test_empty_body_is_successful() -> None:
    result, _, _ = _run_fetch(lambda _request: httpx.Response(204, content=b""))

    assert result.outcome is FetchOutcome.SUCCESS
    assert result.body == b""
    assert result.actual_bytes_read == 0


def test_utf8_body_is_retained_as_unparsed_bytes() -> None:
    body = "café".encode()

    result, _, _ = _run_fetch(lambda _request: httpx.Response(200, content=body))

    assert result.body == body


@pytest.mark.parametrize(
    ("exception_type", "expected_code"),
    [
        (httpx.ConnectTimeout, FetchFailureCode.CONNECT_TIMEOUT),
        (httpx.ReadTimeout, FetchFailureCode.READ_TIMEOUT),
        (httpx.WriteTimeout, FetchFailureCode.WRITE_TIMEOUT),
        (httpx.PoolTimeout, FetchFailureCode.POOL_TIMEOUT),
    ],
)
def test_timeout_types_map_to_stable_failures(
    exception_type: type[httpx.TimeoutException],
    expected_code: FetchFailureCode,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception_type(_SYNTHETIC_TIMEOUT, request=request)

    result, _, _ = _run_fetch(handler, settings=_settings(fetch_retry_count=0))

    assert result.failure_code is expected_code
    assert result.internal_exception_type == exception_type.__name__
    assert "synthetic" not in (result.failure_explanation or "")


def test_transport_error_maps_without_raw_exception_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(_SYNTHETIC_TRANSPORT_ERROR, request=request)

    result, _, _ = _run_fetch(handler, settings=_settings(fetch_retry_count=0))

    assert result.failure_code is FetchFailureCode.TRANSPORT_ERROR
    assert result.failure_explanation == "The HTTP transport failed"


def test_one_bounded_retry_revalidates_dns_and_then_succeeds() -> None:
    request_count = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            raise httpx.ConnectError(_FIRST_ATTEMPT_ERROR, request=request)
        return httpx.Response(200, content=b"ok")

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    result, resolver, _ = _run_fetch(handler, sleep=fake_sleep)

    assert result.outcome is FetchOutcome.SUCCESS
    assert request_count == 2
    assert resolver.calls == ["example.test", "example.test"]
    assert sleeps == [0.1]


@pytest.mark.parametrize("status", [429, 503])
def test_http_status_responses_are_not_retried(status: int) -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        nonlocal request_count
        request_count += 1
        return httpx.Response(status)

    result, _, _ = _run_fetch(handler)

    assert result.outcome is FetchOutcome.SUCCESS
    assert result.status_code == status
    assert request_count == 1


def test_safety_failure_is_not_retried_or_sent() -> None:
    request_count = 0
    resolver = _FakeResolver(answers=("10.0.0.1",))

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        nonlocal request_count
        request_count += 1
        return httpx.Response(200)

    result, _, _ = _run_fetch(handler, resolver=resolver)

    assert result.failure_code is FetchFailureCode.UNSAFE_RESOLVED_ADDRESS
    assert request_count == 0
    assert resolver.calls == ["example.test"]


def test_scope_denial_is_not_resolved_retried_or_sent() -> None:
    request_count = 0
    resolver = _FakeResolver()
    settings = _settings()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        nonlocal request_count
        request_count += 1
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    fetcher = SafeSingleUrlFetcher(
        settings,
        DestinationSafetyValidator(settings, resolver),
        transport=transport,
    )
    seed = normalize_url("https://seed.test/")
    destination = normalize_url("https://outside.test/")

    result = asyncio.run(fetcher.fetch(FetchRequest(destination), create_scope_policy(seed)))

    assert result.failure_code is FetchFailureCode.SCOPE_DENIED
    assert resolver.calls == []
    assert request_count == 0


def test_declared_oversized_response_is_rejected_before_body_read() -> None:
    stream = _TrackingStream([b"not-read"])

    result, _, _ = _run_fetch(
        lambda _request: httpx.Response(200, headers={"Content-Length": "6"}, stream=stream),
        settings=_settings(fetch_maximum_response_body_bytes=5),
    )

    assert result.failure_code is FetchFailureCode.RESPONSE_TOO_LARGE
    assert result.actual_bytes_read == 0
    assert result.body is None
    assert result.body_truncated is True
    assert stream.closed is True


def test_undeclared_streaming_overflow_stops_at_limit_and_closes() -> None:
    stream = _TrackingStream([b"123", b"456"])

    result, _, _ = _run_fetch(
        lambda _request: httpx.Response(200, stream=stream),
        settings=_settings(fetch_maximum_response_body_bytes=5),
    )

    assert result.failure_code is FetchFailureCode.RESPONSE_TOO_LARGE
    assert result.actual_bytes_read == 5
    assert result.body is None
    assert result.body_truncated is True
    assert stream.closed is True


def test_body_exactly_at_limit_is_successful() -> None:
    result, _, _ = _run_fetch(
        lambda _request: httpx.Response(200, content=b"12345"),
        settings=_settings(fetch_maximum_response_body_bytes=5),
    )

    assert result.outcome is FetchOutcome.SUCCESS
    assert result.body == b"12345"


@pytest.mark.parametrize("content_length", ["invalid", "-1", "1,2"])
def test_invalid_content_length_is_rejected(content_length: str) -> None:
    result, _, _ = _run_fetch(
        lambda _request: httpx.Response(
            200,
            headers={"Content-Length": content_length},
            stream=_TrackingStream([]),
        )
    )

    assert result.failure_code is FetchFailureCode.INVALID_CONTENT_LENGTH


def test_oversized_headers_are_rejected() -> None:
    result, _, _ = _run_fetch(
        lambda _request: httpx.Response(200, headers={"X-Large": "x" * 2_000}),
        settings=_settings(fetch_maximum_response_header_bytes=1_024),
    )

    assert result.failure_code is FetchFailureCode.RESPONSE_HEADERS_TOO_LARGE


def test_total_deadline_maps_to_stable_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        await asyncio.sleep(0.05)
        return httpx.Response(200)

    result, _, _ = _run_fetch(
        handler,
        settings=_settings(fetch_total_request_deadline_seconds=0.01),
    )

    assert result.failure_code is FetchFailureCode.REQUEST_DEADLINE_EXCEEDED


def test_total_deadline_includes_dns_resolution() -> None:
    class _SlowResolver(_FakeResolver):
        async def resolve(self, hostname: str, *, maximum_answers: int) -> DnsEvidence:
            await asyncio.sleep(0.05)
            return await super().resolve(hostname, maximum_answers=maximum_answers)

    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        nonlocal request_count
        request_count += 1
        return httpx.Response(200)

    result, _, _ = _run_fetch(
        handler,
        resolver=_SlowResolver(),
        settings=_settings(fetch_total_request_deadline_seconds=0.01),
    )

    assert result.failure_code is FetchFailureCode.REQUEST_DEADLINE_EXCEEDED
    assert request_count == 0


def test_duration_evidence_uses_injected_clock() -> None:
    values = iter([10.0, 10.25])
    settings = _settings()
    resolver = _FakeResolver()
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=b"ok"))
    fetcher = SafeSingleUrlFetcher(
        settings,
        DestinationSafetyValidator(settings, resolver),
        transport=transport,
        clock=lambda: next(values, 10.25),
    )
    url = normalize_url("https://example.test/")

    result = asyncio.run(fetcher.fetch(FetchRequest(url), create_scope_policy(url)))

    assert result.request_duration_seconds == 0.25


def test_structured_logs_do_not_retain_query_values(caplog: pytest.LogCaptureFixture) -> None:
    settings = _settings()
    resolver = _FakeResolver()
    transport = httpx.MockTransport(lambda _request: httpx.Response(200))
    fetcher = SafeSingleUrlFetcher(
        settings,
        DestinationSafetyValidator(settings, resolver),
        transport=transport,
    )
    url = normalize_url("https://example.test/path?token=never-log-this")

    with caplog.at_level(logging.INFO, logger="musimack_tools.crawl.fetcher"):
        asyncio.run(fetcher.fetch(FetchRequest(url, "request-1"), create_scope_policy(url)))

    assert "never-log-this" not in caplog.text
    safe_urls = [getattr(record, "safe_url", None) for record in caplog.records]
    assert "https://example.test/path" in safe_urls


def test_global_and_per_host_concurrency_are_enforced() -> None:
    settings = _settings(default_global_crawl_concurrency=1, default_per_host_concurrency=1)
    resolver = _FakeResolver()
    active = 0
    maximum_active = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0)
        active -= 1
        return httpx.Response(200)

    fetcher = SafeSingleUrlFetcher(
        settings,
        DestinationSafetyValidator(settings, resolver),
        transport=httpx.MockTransport(handler),
    )
    url = normalize_url("https://example.test/")
    scope = create_scope_policy(url)

    async def run_both() -> None:
        await asyncio.gather(
            fetcher.fetch(FetchRequest(url, "one"), scope),
            fetcher.fetch(FetchRequest(url, "two"), scope),
        )

    asyncio.run(run_both())

    assert maximum_active == 1
