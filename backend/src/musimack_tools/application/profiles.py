"""Immutable named crawl profiles and application safety maxima."""

from __future__ import annotations

from musimack_tools.domain.application import (
    ApplicationCrawlLimits,
    CrawlProfile,
    CrawlProfileName,
)

APPLICATION_HARD_MAXIMA = ApplicationCrawlLimits(
    maximum_urls=50_000,
    maximum_depth=50,
    maximum_duration_seconds=7_200,
    maximum_accepted_bytes=5_000_000_000,
    maximum_concurrency=16,
    maximum_queue_size=100_000,
    minimum_request_delay_seconds=0.1,
    maximum_redirect_hops=20,
    maximum_response_bytes=50_000_000,
)

_PROFILES = (
    CrawlProfile(
        CrawlProfileName.QUICK_AUDIT,
        ApplicationCrawlLimits(100, 3, 60, 25_000_000, 2, 500, 0.5, 5, 2_000_000),
        recommendation_requested=True,
        xml_requested=False,
        summary_requested=False,
    ),
    CrawlProfile(
        CrawlProfileName.STANDARD_CRAWL,
        ApplicationCrawlLimits(5_000, 10, 1_800, 500_000_000, 4, 10_000, 0.5, 10, 5_000_000),
        recommendation_requested=True,
        xml_requested=True,
        summary_requested=False,
    ),
    CrawlProfile(
        CrawlProfileName.DEEP_CRAWL,
        ApplicationCrawlLimits(25_000, 25, 3_600, 2_000_000_000, 8, 50_000, 0.5, 10, 10_000_000),
        recommendation_requested=True,
        xml_requested=True,
        summary_requested=False,
    ),
    CrawlProfile(
        CrawlProfileName.SITEMAP_ONLY,
        ApplicationCrawlLimits(10_000, 15, 2_400, 1_000_000_000, 4, 20_000, 0.5, 10, 5_000_000),
        recommendation_requested=True,
        xml_requested=True,
        summary_requested=True,
    ),
)
_MAXIMA_TOO_HIGH = "configured application maxima exceed absolute safety maxima"
_DELAY_TOO_LOW = "configured minimum request delay weakens the absolute safety minimum"
_MAXIMA_INVALID = "configured application maxima must remain positive and usable"


def profiles() -> tuple[CrawlProfile, ...]:
    """Return the stable profile catalog in declared order."""
    return _PROFILES


def profile_for(value: CrawlProfileName | str) -> CrawlProfile | None:
    """Resolve one named profile without mutating shared definitions."""
    try:
        name = value if isinstance(value, CrawlProfileName) else CrawlProfileName(value)
    except ValueError:
        return None
    return next(item for item in _PROFILES if item.name is name)


def validate_application_maxima(value: ApplicationCrawlLimits) -> None:
    """Reject service ceilings that weaken the accepted absolute application boundary."""
    upper_pairs = (
        (value.maximum_urls, APPLICATION_HARD_MAXIMA.maximum_urls),
        (value.maximum_depth, APPLICATION_HARD_MAXIMA.maximum_depth),
        (value.maximum_duration_seconds, APPLICATION_HARD_MAXIMA.maximum_duration_seconds),
        (value.maximum_accepted_bytes, APPLICATION_HARD_MAXIMA.maximum_accepted_bytes),
        (value.maximum_concurrency, APPLICATION_HARD_MAXIMA.maximum_concurrency),
        (value.maximum_queue_size, APPLICATION_HARD_MAXIMA.maximum_queue_size),
        (value.maximum_redirect_hops, APPLICATION_HARD_MAXIMA.maximum_redirect_hops),
        (value.maximum_response_bytes, APPLICATION_HARD_MAXIMA.maximum_response_bytes),
    )
    if (
        value.maximum_urls < 1
        or value.maximum_depth < 0
        or value.maximum_duration_seconds <= 0
        or value.maximum_accepted_bytes < 1
        or value.maximum_concurrency < 1
        or value.maximum_queue_size < 1
        or value.maximum_redirect_hops < 0
        or value.maximum_response_bytes < 1
    ):
        raise ValueError(_MAXIMA_INVALID)
    if any(configured > absolute for configured, absolute in upper_pairs):
        raise ValueError(_MAXIMA_TOO_HIGH)
    if value.minimum_request_delay_seconds < APPLICATION_HARD_MAXIMA.minimum_request_delay_seconds:
        raise ValueError(_DELAY_TOO_LOW)
