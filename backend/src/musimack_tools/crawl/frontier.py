"""Deterministic breadth-first URL frontier with bounded queueing."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from musimack_tools.domain.crawl import FrontierItem, FrontierState, LinkAdmissionReason

if TYPE_CHECKING:
    from musimack_tools.domain.urls import NormalizedUrl

_MAX_REFERRERS = 16
_INVALID_QUEUE_LIMIT = "maximum queued URLs must be at least 1"
_INVALID_REFERRER_LIMIT = "maximum referrers must be at least 1"
_COMPLETE_NON_ACTIVE = "only active frontier items can be completed"
_UNKNOWN_FRONTIER_URL = "frontier URL is not registered"


@dataclass(frozen=True, slots=True)
class FrontierAdmission:
    """Result of attempting to add or rediscover one normalized crawl key."""

    item: FrontierItem
    reason: LinkAdmissionReason
    new_url: bool
    queued: bool


@dataclass(slots=True)
class _FrontierEntry:
    url: NormalizedUrl
    first_discovered_value: str
    first_referrer: str | None
    first_discovered_depth: int
    best_known_depth: int
    discovery_order: int
    state: FrontierState = FrontierState.PENDING
    referring_urls: list[str] = field(default_factory=list)
    version: int = 0


class CrawlFrontier:
    """A bounded deterministic frontier keyed only by accepted normalized URLs."""

    def __init__(
        self, *, maximum_queued_urls: int, maximum_referrers: int = _MAX_REFERRERS
    ) -> None:
        if maximum_queued_urls < 1:
            raise ValueError(_INVALID_QUEUE_LIMIT)
        if maximum_referrers < 1:
            raise ValueError(_INVALID_REFERRER_LIMIT)
        self._maximum_queued_urls = maximum_queued_urls
        self._maximum_referrers = maximum_referrers
        self._entries: dict[str, _FrontierEntry] = {}
        self._heap: list[tuple[int, int, str, int]] = []
        self._next_order = 0
        self._pending_count = 0
        self._maximum_observed_queue_size = 0

    @property
    def unique_count(self) -> int:
        return len(self._entries)

    @property
    def pending_count(self) -> int:
        return self._pending_count

    @property
    def maximum_observed_queue_size(self) -> int:
        return self._maximum_observed_queue_size

    def contains(self, normalized_url: str) -> bool:
        return normalized_url in self._entries

    def state_of(self, normalized_url: str) -> FrontierState | None:
        entry = self._entries.get(normalized_url)
        return entry.state if entry is not None else None

    def admit(
        self,
        url: NormalizedUrl,
        *,
        discovered_value: str,
        referrer: str | None,
        depth: int,
    ) -> FrontierAdmission:
        """Admit a new key or retain bounded rediscovery evidence."""
        existing = self._entries.get(url.normalized)
        if existing is not None:
            self._add_referrer(existing, referrer)
            if existing.state is FrontierState.PENDING and depth < existing.best_known_depth:
                existing.best_known_depth = depth
                existing.version += 1
                self._push(existing)
                return FrontierAdmission(
                    item=self._item(existing),
                    reason=LinkAdmissionReason.UPDATED_BETTER_DEPTH,
                    new_url=False,
                    queued=True,
                )
            return FrontierAdmission(
                item=self._item(existing),
                reason=LinkAdmissionReason.DUPLICATE_URL,
                new_url=False,
                queued=False,
            )

        entry = _FrontierEntry(
            url=url,
            first_discovered_value=discovered_value,
            first_referrer=referrer,
            first_discovered_depth=depth,
            best_known_depth=depth,
            discovery_order=self._next_order,
            referring_urls=[referrer] if referrer is not None else [],
        )
        self._next_order += 1
        self._entries[url.normalized] = entry
        if self._pending_count >= self._maximum_queued_urls:
            entry.state = FrontierState.SKIPPED
            return FrontierAdmission(
                item=self._item(entry),
                reason=LinkAdmissionReason.QUEUE_LIMIT_REACHED,
                new_url=True,
                queued=False,
            )
        self._pending_count += 1
        self._push(entry)
        self._maximum_observed_queue_size = max(
            self._maximum_observed_queue_size,
            self._pending_count,
        )
        return FrontierAdmission(
            item=self._item(entry),
            reason=LinkAdmissionReason.ADMITTED,
            new_url=True,
            queued=True,
        )

    def pop_depth_batch(self, maximum_count: int) -> tuple[FrontierItem, ...]:
        """Activate up to one depth's worth of URLs in stable breadth-first order."""
        if maximum_count < 1:
            return ()
        first = self._pop_valid()
        if first is None:
            return ()
        depth = first.best_known_depth
        entries = [first]
        while len(entries) < maximum_count:
            candidate = self._pop_valid()
            if candidate is None:
                break
            if candidate.best_known_depth != depth:
                self._push(candidate)
                break
            entries.append(candidate)
        for entry in entries:
            entry.state = FrontierState.ACTIVE
            self._pending_count -= 1
        return tuple(self._item(entry) for entry in entries)

    def complete(self, normalized_url: str) -> None:
        entry = self._required_entry(normalized_url)
        if entry.state is not FrontierState.ACTIVE:
            raise RuntimeError(_COMPLETE_NON_ACTIVE)
        entry.state = FrontierState.COMPLETED

    def skip_pending(self, normalized_url: str) -> FrontierItem | None:
        entry = self._entries.get(normalized_url)
        if entry is None or entry.state is not FrontierState.PENDING:
            return None
        entry.state = FrontierState.SKIPPED
        self._pending_count -= 1
        return self._item(entry)

    def drain_pending(self) -> tuple[FrontierItem, ...]:
        """Mark every queued item skipped in stable record order."""
        drained: list[FrontierItem] = []
        for entry in sorted(self._entries.values(), key=lambda value: value.discovery_order):
            if entry.state is FrontierState.PENDING:
                entry.state = FrontierState.SKIPPED
                self._pending_count -= 1
                drained.append(self._item(entry))
        return tuple(drained)

    def items_in_discovery_order(self) -> tuple[FrontierItem, ...]:
        return tuple(
            self._item(entry)
            for entry in sorted(self._entries.values(), key=lambda value: value.discovery_order)
        )

    def _push(self, entry: _FrontierEntry) -> None:
        heapq.heappush(
            self._heap,
            (
                entry.best_known_depth,
                entry.discovery_order,
                entry.url.normalized,
                entry.version,
            ),
        )

    def _pop_valid(self) -> _FrontierEntry | None:
        while self._heap:
            depth, _order, normalized, version = heapq.heappop(self._heap)
            entry = self._entries[normalized]
            if (
                entry.state is FrontierState.PENDING
                and entry.best_known_depth == depth
                and entry.version == version
            ):
                return entry
        return None

    def _add_referrer(self, entry: _FrontierEntry, referrer: str | None) -> None:
        if (
            referrer is not None
            and referrer not in entry.referring_urls
            and len(entry.referring_urls) < self._maximum_referrers
        ):
            entry.referring_urls.append(referrer)

    def _required_entry(self, normalized_url: str) -> _FrontierEntry:
        try:
            return self._entries[normalized_url]
        except KeyError as error:
            raise RuntimeError(_UNKNOWN_FRONTIER_URL) from error

    @staticmethod
    def _item(entry: _FrontierEntry) -> FrontierItem:
        return FrontierItem(
            url=entry.url,
            first_discovered_value=entry.first_discovered_value,
            first_referrer=entry.first_referrer,
            referring_urls=tuple(entry.referring_urls),
            first_discovered_depth=entry.first_discovered_depth,
            best_known_depth=entry.best_known_depth,
            discovery_order=entry.discovery_order,
        )
