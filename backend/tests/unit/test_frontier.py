"""Deterministic breadth-first frontier tests."""

from musimack_tools.crawl.frontier import CrawlFrontier, FrontierAdmission
from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.domain.crawl import FrontierState, LinkAdmissionReason


def _admit(
    frontier: CrawlFrontier,
    value: str,
    *,
    depth: int,
    referrer: str | None = None,
) -> FrontierAdmission:
    return frontier.admit(
        normalize_url(value),
        discovered_value=value,
        referrer=referrer,
        depth=depth,
    )


def test_seed_is_admitted_at_depth_zero() -> None:
    frontier = CrawlFrontier(maximum_queued_urls=10)

    admission = _admit(frontier, "https://example.test/", depth=0)
    item = frontier.pop_depth_batch(1)[0]

    assert admission.reason is LinkAdmissionReason.ADMITTED
    assert item.best_known_depth == 0
    assert item.discovery_order == 0
    assert frontier.state_of(item.url.normalized) is FrontierState.ACTIVE


def test_breadth_first_order_uses_depth_then_discovery_order() -> None:
    frontier = CrawlFrontier(maximum_queued_urls=10)
    _admit(frontier, "https://example.test/deep", depth=2)
    _admit(frontier, "https://example.test/first", depth=1)
    _admit(frontier, "https://example.test/second", depth=1)

    first_batch = frontier.pop_depth_batch(10)
    for item in first_batch:
        frontier.complete(item.url.normalized)
    second_batch = frontier.pop_depth_batch(10)

    assert [item.url.normalized for item in first_batch] == [
        "https://example.test/first",
        "https://example.test/second",
    ]
    assert [item.url.normalized for item in second_batch] == ["https://example.test/deep"]


def test_duplicate_discovery_retains_first_and_adds_bounded_referrer() -> None:
    frontier = CrawlFrontier(maximum_queued_urls=10, maximum_referrers=2)
    _admit(frontier, "https://example.test/page", depth=1, referrer="https://example.test/a")
    duplicate = _admit(
        frontier,
        "https://example.test/page",
        depth=1,
        referrer="https://example.test/b",
    )
    _admit(
        frontier,
        "https://example.test/page",
        depth=2,
        referrer="https://example.test/c",
    )

    assert duplicate.reason is LinkAdmissionReason.DUPLICATE_URL
    assert duplicate.item.first_referrer == "https://example.test/a"
    assert frontier.items_in_discovery_order()[0].referring_urls == (
        "https://example.test/a",
        "https://example.test/b",
    )


def test_better_depth_rediscovery_updates_pending_priority() -> None:
    frontier = CrawlFrontier(maximum_queued_urls=10)
    _admit(frontier, "https://example.test/page", depth=4)

    admission = _admit(frontier, "https://example.test/page", depth=2)

    assert admission.reason is LinkAdmissionReason.UPDATED_BETTER_DEPTH
    assert frontier.pop_depth_batch(1)[0].best_known_depth == 2


def test_worse_depth_rediscovery_does_not_change_priority() -> None:
    frontier = CrawlFrontier(maximum_queued_urls=10)
    _admit(frontier, "https://example.test/page", depth=1)

    admission = _admit(frontier, "https://example.test/page", depth=3)

    assert admission.reason is LinkAdmissionReason.DUPLICATE_URL
    assert frontier.pop_depth_batch(1)[0].best_known_depth == 1


def test_fragment_variants_collapse_through_accepted_normalization() -> None:
    frontier = CrawlFrontier(maximum_queued_urls=10)
    _admit(frontier, "https://example.test/page#one", depth=1)

    duplicate = _admit(frontier, "https://example.test/page#two", depth=1)

    assert duplicate.reason is LinkAdmissionReason.DUPLICATE_URL
    assert frontier.unique_count == 1


def test_query_order_and_repetition_remain_distinct() -> None:
    frontier = CrawlFrontier(maximum_queued_urls=10)
    values = (
        "https://example.test/page?a=1&b=2",
        "https://example.test/page?b=2&a=1",
        "https://example.test/page?a=1&a=2",
        "https://example.test/page?a=2&a=1",
    )
    for value in values:
        _admit(frontier, value, depth=1)

    assert frontier.unique_count == 4
    assert [item.url.normalized for item in frontier.pop_depth_batch(10)] == list(values)


def test_trailing_slash_variants_remain_distinct() -> None:
    frontier = CrawlFrontier(maximum_queued_urls=10)
    _admit(frontier, "https://example.test/page", depth=1)
    _admit(frontier, "https://example.test/page/", depth=1)

    assert frontier.unique_count == 2


def test_queue_maximum_returns_typed_rejection_without_blocking() -> None:
    frontier = CrawlFrontier(maximum_queued_urls=1)
    _admit(frontier, "https://example.test/first", depth=1)

    rejected = _admit(frontier, "https://example.test/second", depth=1)

    assert rejected.reason is LinkAdmissionReason.QUEUE_LIMIT_REACHED
    assert rejected.queued is False
    assert frontier.state_of("https://example.test/second") is FrontierState.SKIPPED


def test_active_and_completed_urls_are_never_requeued() -> None:
    frontier = CrawlFrontier(maximum_queued_urls=10)
    _admit(frontier, "https://example.test/page", depth=1)
    item = frontier.pop_depth_batch(1)[0]

    active_duplicate = _admit(frontier, item.url.normalized, depth=1)
    frontier.complete(item.url.normalized)
    completed_duplicate = _admit(frontier, item.url.normalized, depth=0)

    assert active_duplicate.reason is LinkAdmissionReason.DUPLICATE_URL
    assert completed_duplicate.reason is LinkAdmissionReason.DUPLICATE_URL
    assert frontier.pending_count == 0


def test_skip_and_drain_preserve_discovery_order() -> None:
    frontier = CrawlFrontier(maximum_queued_urls=10)
    _admit(frontier, "https://example.test/one", depth=1)
    _admit(frontier, "https://example.test/two", depth=1)
    _admit(frontier, "https://example.test/three", depth=1)

    skipped = frontier.skip_pending("https://example.test/two")
    drained = frontier.drain_pending()

    assert skipped is not None
    assert skipped.discovery_order == 1
    assert [item.discovery_order for item in drained] == [0, 2]
    assert frontier.pending_count == 0


def test_frontier_maximum_observed_queue_size_is_retained() -> None:
    frontier = CrawlFrontier(maximum_queued_urls=5)
    for index in range(3):
        _admit(frontier, f"https://example.test/{index}", depth=1)
    frontier.pop_depth_batch(2)

    assert frontier.maximum_observed_queue_size == 3
