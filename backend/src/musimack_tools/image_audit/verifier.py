"""Adapter from image verification to the accepted SSRF-safe fetch boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.domain.fetching import FetchOutcome, FetchRequest, FetchResult

if TYPE_CHECKING:
    from musimack_tools.domain.urls import CrawlScopePolicy


class _SafeFetcher(Protocol):
    async def fetch(self, request: FetchRequest, scope: CrawlScopePolicy) -> FetchResult: ...


class SafeFetchImageVerifier:
    """Verify a resource without creating a raw HTTP client or bypassing scope/safety."""

    def __init__(self, fetcher: _SafeFetcher, scope: CrawlScopePolicy) -> None:
        self._fetcher = fetcher
        self._scope = scope

    async def verify(self, url: str, *, maximum_bytes: int) -> dict[str, object]:
        result = await self._fetcher.fetch(FetchRequest(normalize_url(url)), self._scope)
        oversized = result.actual_bytes_read > maximum_bytes
        return {
            "fetch_state": (
                "response_limit_exceeded"
                if oversized
                else "verified"
                if result.outcome is FetchOutcome.SUCCESS
                else result.failure_code.value
                if result.failure_code is not None
                else "failed"
            ),
            "http_status": result.status_code,
            "content_type": result.content_type,
            "final_url": result.final_url,
            "response_byte_count": min(result.actual_bytes_read, maximum_bytes),
            "redirect_count": len(result.redirect_chain),
        }
