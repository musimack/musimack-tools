"""Bounded asynchronous GET orchestration with manual redirect evidence."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx

from musimack_tools.crawl.redirects import (
    RedirectTargetError,
    is_redirect_status,
    normalize_redirect_target,
)
from musimack_tools.crawl.safety import is_public_address
from musimack_tools.crawl.scope import evaluate_scope
from musimack_tools.domain.fetching import (
    DnsEvidence,
    FetchFailureCode,
    FetchOutcome,
    FetchRequest,
    FetchResult,
    NetworkSafetyDecision,
    RedirectHop,
    ResponseHeaders,
)

if TYPE_CHECKING:
    from musimack_tools.core.config import Settings
    from musimack_tools.crawl.safety import DestinationSafetyValidator
    from musimack_tools.domain.urls import CrawlScopePolicy, NormalizedUrl

_LOGGER = logging.getLogger(__name__)
_ACCEPT_HEADER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_RETRYABLE_FAILURES = frozenset(
    {
        FetchFailureCode.CONNECT_TIMEOUT,
        FetchFailureCode.READ_TIMEOUT,
        FetchFailureCode.WRITE_TIMEOUT,
        FetchFailureCode.POOL_TIMEOUT,
        FetchFailureCode.TRANSPORT_ERROR,
    }
)

Clock = Callable[[], float]
Sleeper = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class _AttemptFailure:
    code: FetchFailureCode
    explanation: str
    exception_type: str | None = None
    status_code: int | None = None
    headers: ResponseHeaders | None = None
    declared_content_length: int | None = None
    actual_bytes_read: int = 0
    body_truncated: bool = False


@dataclass(frozen=True, slots=True)
class _HttpResponseEvidence:
    status_code: int
    headers: ResponseHeaders
    declared_content_length: int | None
    actual_bytes_read: int
    body: bytes | None


@dataclass(slots=True)
class _FetchState:
    requested: NormalizedUrl
    current: NormalizedUrl
    started_at: float
    correlation_id: str | None
    redirects: list[RedirectHop] = field(default_factory=list)
    dns: list[DnsEvidence] = field(default_factory=list)
    attempt_count: int = 0


class SafeSingleUrlFetcher:
    """Fetch one in-scope, network-safe URL with bounded manual redirects."""

    def __init__(
        self,
        settings: Settings,
        safety_validator: DestinationSafetyValidator,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Clock = time.monotonic,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._safety = safety_validator
        self._transport = transport
        self._clock = clock
        self._sleep = sleep
        self._global_semaphore = asyncio.Semaphore(settings.default_global_crawl_concurrency)
        self._host_semaphores: dict[str, asyncio.Semaphore] = {}

    @property
    def trusts_environment_proxies(self) -> bool:
        """Expose the effective proxy policy for configuration verification."""
        return self._settings.fetch_trust_environment_proxies

    async def fetch(self, request: FetchRequest, scope: CrawlScopePolicy) -> FetchResult:
        """Perform one bounded GET operation and retain all redirect evidence."""
        state = _FetchState(
            requested=request.url,
            current=request.url,
            started_at=self._clock(),
            correlation_id=request.correlation_id,
        )
        _LOGGER.info(
            "fetch_started",
            extra=self._log_context(request, request.url),
        )

        scope_decision = evaluate_scope(scope, request.url)
        if not scope_decision.allowed:
            return self._failure(
                state,
                FetchFailureCode.SCOPE_DENIED,
                "The requested URL is outside the approved crawl scope",
            )

        timeout = self._httpx_timeout()
        headers = {
            "User-Agent": request.user_agent or self._settings.crawler_user_agent,
            "Accept": _ACCEPT_HEADER,
        }
        try:
            deadline = self._settings.fetch_total_request_deadline_seconds
            if request.maximum_duration_seconds is not None:
                deadline = min(deadline, request.maximum_duration_seconds)
            async with asyncio.timeout(deadline):
                initial_safety = await self._safety.validate(request.url)
                self._record_dns(state, initial_safety)
                if not initial_safety.allowed:
                    return self._safety_failure(state, initial_safety)
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=timeout,
                    follow_redirects=False,
                    trust_env=self._settings.fetch_trust_environment_proxies,
                    headers=headers,
                    cookies=None,
                    http2=False,
                    limits=httpx.Limits(max_keepalive_connections=0),
                ) as client:
                    return await self._run_redirect_sequence(
                        client,
                        request,
                        scope,
                        state,
                        initial_safety,
                    )
        except TimeoutError:
            return self._failure(
                state,
                FetchFailureCode.REQUEST_DEADLINE_EXCEEDED,
                "The fetch exceeded its total request deadline",
                exception_type="TimeoutError",
            )

    async def _run_redirect_sequence(
        self,
        client: httpx.AsyncClient,
        request: FetchRequest,
        scope: CrawlScopePolicy,
        state: _FetchState,
        initial_safety: NetworkSafetyDecision,
    ) -> FetchResult:
        visited = {state.current.normalized}
        pending_safety = initial_safety

        while True:
            attempt = await self._attempt_with_retries(
                client,
                request,
                state,
                pending_safety,
            )
            if isinstance(attempt, _AttemptFailure):
                return self._attempt_failure_result(state, attempt)

            _LOGGER.info(
                "request_completed",
                extra={
                    **self._log_context(request, state.current),
                    "status_code": attempt.status_code,
                    "duration": self._duration(state),
                },
            )
            if not is_redirect_status(attempt.status_code):
                return self._success(state, attempt)

            redirect_result = await self._process_redirect(
                request,
                scope,
                state,
                attempt,
                visited,
            )
            if isinstance(redirect_result, FetchResult):
                return redirect_result
            state.current, pending_safety = redirect_result
            visited.add(state.current.normalized)

    async def _attempt_with_retries(
        self,
        client: httpx.AsyncClient,
        request: FetchRequest,
        state: _FetchState,
        initial_safety: NetworkSafetyDecision,
    ) -> _HttpResponseEvidence | _AttemptFailure:
        safety = initial_safety
        for attempt_number in range(self._settings.fetch_retry_count + 1):
            if attempt_number > 0:
                safety = await self._safety.validate(state.current)
                self._record_dns(state, safety)
                if not safety.allowed:
                    return _AttemptFailure(
                        code=safety.failure_code or FetchFailureCode.TRANSPORT_ERROR,
                        explanation=safety.explanation,
                    )

            state.attempt_count += 1
            result = await self._send_once(client, state.current, safety, request)
            if not isinstance(result, _AttemptFailure):
                return result
            if (
                result.code not in _RETRYABLE_FAILURES
                or attempt_number >= self._settings.fetch_retry_count
            ):
                return result
            _LOGGER.warning(
                "retry_attempted",
                extra={
                    **self._log_context(request, state.current),
                    "failure_code": result.code.value,
                    "retry_number": attempt_number + 1,
                },
            )
            await self._sleep(min(0.1 * (attempt_number + 1), 1.0))

        return _AttemptFailure(
            code=FetchFailureCode.TRANSPORT_ERROR,
            explanation="The request failed after its bounded retry attempts",
        )

    async def _send_once(  # noqa: PLR0911 - each transport failure remains explicit.
        self,
        client: httpx.AsyncClient,
        destination: NormalizedUrl,
        safety: NetworkSafetyDecision,
        request: FetchRequest,
    ) -> _HttpResponseEvidence | _AttemptFailure:
        selected_address = safety.selected_address
        if selected_address is None or not is_public_address(selected_address):
            return _AttemptFailure(
                code=FetchFailureCode.UNSAFE_RESOLVED_ADDRESS,
                explanation="The validated destination did not retain a public connection address",
            )
        original_url = httpx.URL(destination.normalized)
        connection_url = original_url.copy_with(host=selected_address)
        default_port = 443 if destination.scheme == "https" else 80
        host_header = destination.hostname
        if destination.effective_port != default_port:
            host_header = f"{host_header}:{destination.effective_port}"
        host_semaphore = self._host_semaphores.setdefault(
            destination.hostname,
            asyncio.Semaphore(self._settings.default_per_host_concurrency),
        )
        try:
            async with (
                self._global_semaphore,
                host_semaphore,
                client.stream(
                    "GET",
                    connection_url,
                    headers={"Host": host_header, "Connection": "close"},
                    extensions={"sni_hostname": destination.hostname},
                ) as response,
            ):
                return await self._read_response(
                    response, destination, maximum_response_bytes=request.maximum_response_bytes
                )
        except httpx.ConnectTimeout as error:
            return self._request_error(FetchFailureCode.CONNECT_TIMEOUT, error)
        except httpx.ReadTimeout as error:
            return self._request_error(FetchFailureCode.READ_TIMEOUT, error)
        except httpx.WriteTimeout as error:
            return self._request_error(FetchFailureCode.WRITE_TIMEOUT, error)
        except httpx.PoolTimeout as error:
            return self._request_error(FetchFailureCode.POOL_TIMEOUT, error)
        except httpx.RequestError as error:
            return self._request_error(FetchFailureCode.TRANSPORT_ERROR, error)

    async def _read_response(
        self,
        response: httpx.Response,
        destination: NormalizedUrl,
        *,
        maximum_response_bytes: int | None = None,
    ) -> _HttpResponseEvidence | _AttemptFailure:
        headers = _preserve_headers(response.headers)
        header_bytes = sum(len(name) + len(value) + 4 for name, value in response.headers.raw)
        if header_bytes > self._settings.fetch_maximum_response_header_bytes:
            return _AttemptFailure(
                code=FetchFailureCode.RESPONSE_HEADERS_TOO_LARGE,
                explanation="The response headers exceeded the configured byte limit",
                status_code=response.status_code,
                headers=headers,
            )

        declared = _parse_content_length(headers.content_length)
        if isinstance(declared, _AttemptFailure):
            return _AttemptFailure(
                code=declared.code,
                explanation=declared.explanation,
                status_code=response.status_code,
                headers=headers,
            )
        if is_redirect_status(response.status_code):
            return _HttpResponseEvidence(
                status_code=response.status_code,
                headers=headers,
                declared_content_length=declared,
                actual_bytes_read=0,
                body=None,
            )

        maximum = self._settings.fetch_maximum_response_body_bytes
        if maximum_response_bytes is not None:
            maximum = min(maximum, maximum_response_bytes)
        if declared is not None and declared > maximum:
            _LOGGER.warning(
                "size_limit_reached",
                extra={
                    "safe_url": _safe_url_summary(destination),
                    "host": destination.hostname,
                    "port": destination.effective_port,
                    "failure_code": FetchFailureCode.RESPONSE_TOO_LARGE.value,
                },
            )
            return _AttemptFailure(
                code=FetchFailureCode.RESPONSE_TOO_LARGE,
                explanation="The declared response size exceeded the configured byte limit",
                status_code=response.status_code,
                headers=headers,
                declared_content_length=declared,
                body_truncated=True,
            )

        body = bytearray()
        async for chunk in response.aiter_bytes():
            remaining = maximum - len(body)
            if len(chunk) > remaining:
                accepted_bytes = len(body) + max(remaining, 0)
                body.clear()
                _LOGGER.warning(
                    "size_limit_reached",
                    extra={
                        "safe_url": _safe_url_summary(destination),
                        "host": destination.hostname,
                        "port": destination.effective_port,
                        "failure_code": FetchFailureCode.RESPONSE_TOO_LARGE.value,
                    },
                )
                return _AttemptFailure(
                    code=FetchFailureCode.RESPONSE_TOO_LARGE,
                    explanation="The streamed response exceeded the configured byte limit",
                    status_code=response.status_code,
                    headers=headers,
                    declared_content_length=declared,
                    actual_bytes_read=accepted_bytes,
                    body_truncated=True,
                )
            body.extend(chunk)
        return _HttpResponseEvidence(
            status_code=response.status_code,
            headers=headers,
            declared_content_length=declared,
            actual_bytes_read=len(body),
            body=bytes(body),
        )

    async def _process_redirect(
        self,
        request: FetchRequest,
        scope: CrawlScopePolicy,
        state: _FetchState,
        response: _HttpResponseEvidence,
        visited: set[str],
    ) -> tuple[NormalizedUrl, NetworkSafetyDecision] | FetchResult:
        location = response.headers.location
        _LOGGER.info(
            "redirect_observed",
            extra={
                **self._log_context(request, state.current),
                "status_code": response.status_code,
            },
        )
        try:
            target = normalize_redirect_target(state.current, location)
        except RedirectTargetError as error:
            self._append_redirect(
                state,
                response,
                location,
                None,
                allowed=False,
                code=error.code,
                explanation=error.explanation,
            )
            return self._failure(state, error.code, error.explanation, status=response)

        if target.normalized in visited:
            explanation = "The redirect target repeats a previously visited normalized URL"
            self._append_redirect(
                state,
                response,
                location,
                target,
                allowed=False,
                code=FetchFailureCode.REDIRECT_LOOP,
                explanation=explanation,
            )
            return self._failure(
                state,
                FetchFailureCode.REDIRECT_LOOP,
                explanation,
                status=response,
            )

        redirect_limit = self._settings.fetch_maximum_redirect_hops
        if request.maximum_redirect_hops is not None:
            redirect_limit = min(redirect_limit, request.maximum_redirect_hops)
        if len(state.redirects) >= redirect_limit:
            explanation = "The redirect chain exceeded the configured hop limit"
            self._append_redirect(
                state,
                response,
                location,
                target,
                allowed=False,
                code=FetchFailureCode.REDIRECT_LIMIT_EXCEEDED,
                explanation=explanation,
            )
            return self._failure(
                state,
                FetchFailureCode.REDIRECT_LIMIT_EXCEEDED,
                explanation,
                status=response,
            )

        scope_decision = evaluate_scope(scope, target)
        if not scope_decision.allowed:
            explanation = "The redirect target is outside the approved crawl scope"
            self._append_redirect(
                state,
                response,
                location,
                target,
                allowed=False,
                code=FetchFailureCode.REDIRECT_SCOPE_DENIED,
                explanation=explanation,
            )
            return self._failure(
                state,
                FetchFailureCode.REDIRECT_SCOPE_DENIED,
                explanation,
                status=response,
            )

        safety = await self._safety.validate(target)
        self._record_dns(state, safety)
        if not safety.allowed:
            explanation = f"The redirect target failed network safety: {safety.explanation}"
            self._append_redirect(
                state,
                response,
                location,
                target,
                allowed=False,
                code=safety.failure_code or FetchFailureCode.REDIRECT_UNSAFE_DESTINATION,
                explanation=explanation,
            )
            _LOGGER.warning(
                "redirect_blocked",
                extra={
                    **self._log_context(request, target),
                    "failure_code": FetchFailureCode.REDIRECT_UNSAFE_DESTINATION.value,
                },
            )
            return self._failure(
                state,
                FetchFailureCode.REDIRECT_UNSAFE_DESTINATION,
                explanation,
                status=response,
                exception_type=safety.internal_exception_type,
                final_url=target.normalized,
            )

        self._append_redirect(
            state,
            response,
            location,
            target,
            allowed=True,
            code=None,
            explanation="The redirect target passed scope and network-safety validation",
        )
        return target, safety

    @staticmethod
    def _append_redirect(  # noqa: PLR0913 - explicit evidence fields avoid hidden state.
        state: _FetchState,
        response: _HttpResponseEvidence,
        location: str | None,
        target: NormalizedUrl | None,
        *,
        allowed: bool,
        code: FetchFailureCode | None,
        explanation: str,
    ) -> None:
        state.redirects.append(
            RedirectHop(
                source_url=state.current.normalized,
                status_code=response.status_code,
                raw_location=location,
                destination_url=target.normalized if target is not None else None,
                allowed=allowed,
                failure_code=code,
                explanation=explanation,
            )
        )

    def _success(self, state: _FetchState, response: _HttpResponseEvidence) -> FetchResult:
        return FetchResult(
            requested_url=state.requested.normalized,
            final_url=state.current.normalized,
            outcome=FetchOutcome.SUCCESS,
            status_code=response.status_code,
            headers=response.headers,
            content_type=response.headers.content_type,
            declared_content_length=response.declared_content_length,
            actual_bytes_read=response.actual_bytes_read,
            body_truncated=False,
            redirect_chain=tuple(state.redirects),
            request_duration_seconds=self._duration(state),
            dns_evidence=tuple(state.dns),
            failure_code=None,
            failure_explanation=None,
            body=response.body,
            attempt_count=state.attempt_count,
        )

    def _attempt_failure_result(
        self,
        state: _FetchState,
        failure: _AttemptFailure,
    ) -> FetchResult:
        return self._failure(
            state,
            failure.code,
            failure.explanation,
            status_code=failure.status_code,
            headers=failure.headers,
            declared_content_length=failure.declared_content_length,
            actual_bytes_read=failure.actual_bytes_read,
            body_truncated=failure.body_truncated,
            exception_type=failure.exception_type,
        )

    def _safety_failure(
        self,
        state: _FetchState,
        safety: NetworkSafetyDecision,
    ) -> FetchResult:
        return self._failure(
            state,
            safety.failure_code or FetchFailureCode.TRANSPORT_ERROR,
            safety.explanation,
            exception_type=safety.internal_exception_type,
        )

    def _failure(  # noqa: PLR0913 - centralizes the complete typed failure contract.
        self,
        state: _FetchState,
        code: FetchFailureCode,
        explanation: str,
        *,
        status: _HttpResponseEvidence | None = None,
        status_code: int | None = None,
        headers: ResponseHeaders | None = None,
        declared_content_length: int | None = None,
        actual_bytes_read: int = 0,
        body_truncated: bool = False,
        exception_type: str | None = None,
        final_url: str | None = None,
    ) -> FetchResult:
        _LOGGER.warning(
            "fetch_failed",
            extra={
                "safe_url": _safe_url_summary(state.current),
                "host": state.current.hostname,
                "port": state.current.effective_port,
                "duration": self._duration(state),
                "failure_code": code.value,
                "correlation_id": state.correlation_id,
            },
        )
        resolved_status = status.status_code if status is not None else status_code
        resolved_headers = status.headers if status is not None else headers
        resolved_declared = (
            status.declared_content_length if status is not None else declared_content_length
        )
        return FetchResult(
            requested_url=state.requested.normalized,
            final_url=final_url or state.current.normalized,
            outcome=FetchOutcome.FAILURE,
            status_code=resolved_status,
            headers=resolved_headers,
            content_type=resolved_headers.content_type if resolved_headers is not None else None,
            declared_content_length=resolved_declared,
            actual_bytes_read=actual_bytes_read,
            body_truncated=body_truncated,
            redirect_chain=tuple(state.redirects),
            request_duration_seconds=self._duration(state),
            dns_evidence=tuple(state.dns),
            failure_code=code,
            failure_explanation=explanation,
            body=None,
            internal_exception_type=exception_type,
            attempt_count=max(1, state.attempt_count),
        )

    def _httpx_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self._settings.fetch_connect_timeout_seconds,
            read=self._settings.fetch_read_timeout_seconds,
            write=self._settings.fetch_write_timeout_seconds,
            pool=self._settings.fetch_pool_timeout_seconds,
        )

    def _duration(self, state: _FetchState) -> float:
        return max(0.0, self._clock() - state.started_at)

    @staticmethod
    def _record_dns(state: _FetchState, safety: NetworkSafetyDecision) -> None:
        if safety.dns_evidence is not None:
            state.dns.append(safety.dns_evidence)
            _LOGGER.info(
                "dns_validated",
                extra={
                    "host": safety.hostname,
                    "port": safety.effective_port,
                    "answer_count": safety.dns_evidence.answer_count,
                    "correlation_id": state.correlation_id,
                    "failure_code": (
                        safety.failure_code.value if safety.failure_code is not None else None
                    ),
                },
            )

    @staticmethod
    def _request_error(code: FetchFailureCode, error: httpx.RequestError) -> _AttemptFailure:
        explanations = {
            FetchFailureCode.CONNECT_TIMEOUT: "The connection attempt timed out",
            FetchFailureCode.READ_TIMEOUT: "The response read timed out",
            FetchFailureCode.WRITE_TIMEOUT: "The request write timed out",
            FetchFailureCode.POOL_TIMEOUT: "The connection pool wait timed out",
            FetchFailureCode.TRANSPORT_ERROR: "The HTTP transport failed",
        }
        return _AttemptFailure(
            code=code,
            explanation=explanations[code],
            exception_type=type(error).__name__,
        )

    @staticmethod
    def _log_context(request: FetchRequest, destination: NormalizedUrl) -> dict[str, object]:
        return {
            "safe_url": _safe_url_summary(destination),
            "host": destination.hostname,
            "port": destination.effective_port,
            "correlation_id": request.correlation_id,
        }


def _preserve_headers(headers: httpx.Headers) -> ResponseHeaders:
    return ResponseHeaders(
        content_type=headers.get("content-type"),
        content_length=headers.get("content-length"),
        location=headers.get("location"),
        x_robots_tag=tuple(headers.get_list("x-robots-tag")),
        etag=headers.get("etag"),
        last_modified=headers.get("last-modified"),
    )


def _parse_content_length(value: str | None) -> int | None | _AttemptFailure:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return _AttemptFailure(
            code=FetchFailureCode.INVALID_CONTENT_LENGTH,
            explanation="The response Content-Length header is invalid",
        )
    if parsed < 0:
        return _AttemptFailure(
            code=FetchFailureCode.INVALID_CONTENT_LENGTH,
            explanation="The response Content-Length header is invalid",
        )
    return parsed


def _safe_url_summary(destination: NormalizedUrl) -> str:
    """Return a query-free URL summary suitable for structured logs."""
    return f"{destination.origin}{url_path_without_query(destination)}"


def url_path_without_query(destination: NormalizedUrl) -> str:
    """Extract the already-normalized path without retaining query values."""
    return (
        httpx.URL(destination.normalized)
        .raw_path.decode("ascii", errors="replace")
        .split("?", 1)[0]
    )
