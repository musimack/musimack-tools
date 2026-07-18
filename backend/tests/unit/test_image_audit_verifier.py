"""Image verification remains an adapter over the accepted safe fetcher."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import create_scope_policy
from musimack_tools.domain.fetching import (
    FetchFailureCode,
    FetchOutcome,
    FetchRequest,
    FetchResult,
    ResponseHeaders,
)
from musimack_tools.image_audit.verifier import SafeFetchImageVerifier

if TYPE_CHECKING:
    from musimack_tools.domain.urls import CrawlScopePolicy


class _Fetcher:
    def __init__(self) -> None:
        self.calls: list[tuple[FetchRequest, CrawlScopePolicy]] = []

    async def fetch(self, request: FetchRequest, scope: CrawlScopePolicy) -> FetchResult:
        self.calls.append((request, scope))
        return FetchResult(
            requested_url=request.url.normalized,
            final_url="https://example.com/final.png",
            outcome=FetchOutcome.SUCCESS,
            status_code=200,
            headers=ResponseHeaders(content_type="image/png"),
            content_type="image/png",
            declared_content_length=500,
            actual_bytes_read=500,
            body_truncated=False,
            redirect_chain=(),
            request_duration_seconds=0.01,
            dns_evidence=(),
            failure_code=None,
            failure_explanation=None,
            body=b"bounded",
        )


def test_safe_fetch_adapter_preserves_scope_and_caps_response_evidence() -> None:
    seed = normalize_url("https://example.com/")
    scope = create_scope_policy(seed)
    fetcher = _Fetcher()
    result = asyncio.run(
        SafeFetchImageVerifier(fetcher, scope).verify(
            "https://example.com/image.png", maximum_bytes=100
        )
    )
    assert len(fetcher.calls) == 1 and fetcher.calls[0][1] is scope
    assert result["fetch_state"] == "response_limit_exceeded"
    assert result["response_byte_count"] == 100


class _FailureFetcher:
    def __init__(self, failure: FetchFailureCode) -> None:
        self.failure = failure
        self.calls = 0

    async def fetch(self, request: FetchRequest, scope: CrawlScopePolicy) -> FetchResult:
        del scope
        self.calls += 1
        return FetchResult(
            requested_url=request.url.normalized,
            final_url=request.url.normalized,
            outcome=FetchOutcome.FAILURE,
            status_code=None,
            headers=ResponseHeaders(),
            content_type=None,
            declared_content_length=None,
            actual_bytes_read=0,
            body_truncated=False,
            redirect_chain=(),
            request_duration_seconds=0.01,
            dns_evidence=(),
            failure_code=self.failure,
            failure_explanation="safe bounded failure",
            body=None,
        )


@pytest.mark.parametrize(
    "failure",
    [
        FetchFailureCode.CONNECT_TIMEOUT,
        FetchFailureCode.DNS_RESOLUTION_FAILED,
        FetchFailureCode.UNSAFE_RESOLVED_ADDRESS,
        FetchFailureCode.SCOPE_DENIED,
        FetchFailureCode.REDIRECT_UNSAFE_DESTINATION,
        FetchFailureCode.REDIRECT_LIMIT_EXCEEDED,
        FetchFailureCode.RESPONSE_TOO_LARGE,
    ],
)
def test_safe_fetch_failure_taxonomy_is_preserved_without_retry(
    failure: FetchFailureCode,
) -> None:
    seed = normalize_url("https://example.com/")
    fetcher = _FailureFetcher(failure)
    result = asyncio.run(
        SafeFetchImageVerifier(fetcher, create_scope_policy(seed)).verify(
            "https://example.com/image.png", maximum_bytes=1_000
        )
    )
    assert result["fetch_state"] == failure.value
    assert fetcher.calls == 1
