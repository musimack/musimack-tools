"""Crawl request defaults and hard-limit validation tests."""

from dataclasses import FrozenInstanceError

import pytest

from musimack_tools.core.config import Settings
from musimack_tools.crawl.limits import (
    CrawlHardLimits,
    CrawlRequestValidationError,
    configuration_snapshot,
    create_crawl_request,
)
from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import create_scope_policy
from musimack_tools.domain.crawl import CrawlExclusionRule, CrawlRequest, ExclusionRuleType


def _request(**overrides: object) -> CrawlRequest:
    seed = normalize_url("https://example.test/")
    values: dict[str, object] = {
        "seed_url": seed,
        "scope_policy": create_scope_policy(seed),
        "maximum_unique_urls": 10,
        "maximum_depth": 3,
        "maximum_duration_seconds": 60,
        "maximum_total_fetched_bytes": 1_000,
        "maximum_concurrent_fetches": 2,
        "maximum_queued_urls": 20,
        "minimum_per_origin_delay_seconds": 0,
    }
    values.update(overrides)
    return CrawlRequest(**values)  # type: ignore[arg-type]


def _hard_limits() -> CrawlHardLimits:
    return CrawlHardLimits(100, 10, 600, 10_000, 8, 200)


def test_settings_factory_uses_conservative_defaults() -> None:
    settings = Settings.model_validate({})
    seed = normalize_url("https://example.test/")

    request = create_crawl_request(settings, seed, create_scope_policy(seed))

    assert request.maximum_unique_urls == 5_000
    assert request.maximum_depth == 10
    assert request.maximum_duration_seconds == 1_800
    assert request.maximum_total_fetched_bytes == 500_000_000
    assert request.maximum_concurrent_fetches == 4
    assert request.maximum_queued_urls == 10_000
    assert request.minimum_per_origin_delay_seconds == 0.5
    assert request.query_urls_allowed is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("maximum_unique_urls", 101),
        ("maximum_depth", 11),
        ("maximum_duration_seconds", 601),
        ("maximum_total_fetched_bytes", 10_001),
        ("maximum_concurrent_fetches", 9),
        ("maximum_queued_urls", 201),
    ],
)
def test_hard_limits_reject_ordinary_request_overrides(field: str, value: int) -> None:
    with pytest.raises(CrawlRequestValidationError, match="hard maximum"):
        _hard_limits().validate(_request(**{field: value}))


def test_request_at_every_hard_limit_is_valid() -> None:
    request = _request(
        maximum_unique_urls=100,
        maximum_depth=10,
        maximum_duration_seconds=600,
        maximum_total_fetched_bytes=10_000,
        maximum_concurrent_fetches=8,
        maximum_queued_urls=200,
    )

    _hard_limits().validate(request)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("maximum_unique_urls", 0),
        ("maximum_depth", -1),
        ("maximum_duration_seconds", 0),
        ("maximum_total_fetched_bytes", 0),
        ("maximum_concurrent_fetches", 0),
        ("maximum_queued_urls", 0),
        ("minimum_per_origin_delay_seconds", -0.1),
    ],
)
def test_request_rejects_invalid_local_bounds(field: str, value: float) -> None:
    with pytest.raises(ValueError):
        _request(**{field: value})


def test_request_and_configuration_snapshot_are_immutable() -> None:
    request = _request()
    snapshot = configuration_snapshot(request)

    with pytest.raises(FrozenInstanceError):
        request.maximum_depth = 99  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        snapshot.maximum_depth = 99  # type: ignore[misc]


def test_configuration_snapshot_preserves_rules_and_query_policy() -> None:
    rule = CrawlExclusionRule(ExclusionRuleType.PATH_PREFIX, "/private")
    request = _request(query_urls_allowed=False, exclusion_rules=(rule,))

    snapshot = configuration_snapshot(request)

    assert snapshot.query_urls_allowed is False
    assert snapshot.exclusion_rules == (rule,)


def test_exclusion_rule_value_cannot_be_empty() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        CrawlExclusionRule(ExclusionRuleType.EXACT_PATH, "")
