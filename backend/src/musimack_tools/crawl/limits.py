"""Server-owned crawl defaults and non-overridable hard-limit validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from musimack_tools.domain.crawl import CrawlConfigurationSnapshot, CrawlErrorCode, CrawlRequest

if TYPE_CHECKING:
    from musimack_tools.core.config import Settings
    from musimack_tools.domain.urls import CrawlScopePolicy, NormalizedUrl


class CrawlRequestValidationError(ValueError):
    """A crawl request that exceeds a server-owned hard boundary."""

    def __init__(self, explanation: str) -> None:
        super().__init__(explanation)
        self.code = CrawlErrorCode.INVALID_CRAWL_REQUEST
        self.explanation = explanation

    @classmethod
    def hard_limit_exceeded(cls, label: str) -> CrawlRequestValidationError:
        return cls(f"Requested {label} exceeds the configured hard maximum")


@dataclass(frozen=True, slots=True)
class CrawlHardLimits:
    """Hard server limits that ordinary crawl requests cannot override."""

    maximum_unique_urls: int
    maximum_depth: int
    maximum_duration_seconds: float
    maximum_total_fetched_bytes: int
    maximum_concurrent_fetches: int
    maximum_queued_urls: int

    @classmethod
    def from_settings(cls, settings: Settings) -> CrawlHardLimits:
        return cls(
            maximum_unique_urls=settings.crawl_hard_maximum_urls,
            maximum_depth=settings.crawl_hard_maximum_depth,
            maximum_duration_seconds=settings.crawl_hard_maximum_duration_seconds,
            maximum_total_fetched_bytes=settings.crawl_hard_maximum_total_fetched_bytes,
            maximum_concurrent_fetches=settings.crawl_hard_maximum_concurrent_fetches,
            maximum_queued_urls=settings.crawl_hard_maximum_queued_urls,
        )

    def validate(self, request: CrawlRequest) -> None:
        checks: tuple[tuple[int | float, int | float, str], ...] = (
            (request.maximum_unique_urls, self.maximum_unique_urls, "unique URLs"),
            (request.maximum_depth, self.maximum_depth, "crawl depth"),
            (request.maximum_duration_seconds, self.maximum_duration_seconds, "duration"),
            (
                request.maximum_total_fetched_bytes,
                self.maximum_total_fetched_bytes,
                "total fetched bytes",
            ),
            (
                request.maximum_concurrent_fetches,
                self.maximum_concurrent_fetches,
                "concurrent fetches",
            ),
            (request.maximum_queued_urls, self.maximum_queued_urls, "queued URLs"),
        )
        exceeded = next((label for value, hard, label in checks if value > hard), None)
        if exceeded is not None:
            raise CrawlRequestValidationError.hard_limit_exceeded(exceeded)


def create_crawl_request(
    settings: Settings,
    seed_url: NormalizedUrl,
    scope_policy: CrawlScopePolicy,
) -> CrawlRequest:
    """Build a request from conservative server defaults."""
    return CrawlRequest(
        seed_url=seed_url,
        scope_policy=scope_policy,
        maximum_unique_urls=settings.default_maximum_urls,
        maximum_depth=settings.default_maximum_crawl_depth,
        maximum_duration_seconds=settings.crawl_maximum_duration_seconds,
        maximum_total_fetched_bytes=settings.crawl_maximum_total_fetched_bytes,
        maximum_concurrent_fetches=settings.crawl_maximum_concurrent_fetches,
        maximum_queued_urls=settings.crawl_maximum_queued_urls,
        minimum_per_origin_delay_seconds=settings.default_minimum_request_delay_seconds,
        query_urls_allowed=settings.crawl_query_urls_allowed,
    )


def configuration_snapshot(request: CrawlRequest) -> CrawlConfigurationSnapshot:
    """Freeze the effective request controls into result evidence."""
    return CrawlConfigurationSnapshot(
        maximum_unique_urls=request.maximum_unique_urls,
        maximum_depth=request.maximum_depth,
        maximum_duration_seconds=request.maximum_duration_seconds,
        maximum_total_fetched_bytes=request.maximum_total_fetched_bytes,
        maximum_concurrent_fetches=request.maximum_concurrent_fetches,
        maximum_queued_urls=request.maximum_queued_urls,
        minimum_per_origin_delay_seconds=request.minimum_per_origin_delay_seconds,
        query_urls_allowed=request.query_urls_allowed,
        exclusion_rules=request.exclusion_rules,
        strip_query_parameters=request.strip_query_parameters,
    )
