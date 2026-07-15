"""Injectable cooperative cancellation boundary for in-memory crawls."""

from __future__ import annotations

import asyncio
from typing import Protocol


class CancellationToken(Protocol):
    """Read-only cancellation interface consumed by orchestration."""

    def is_cancelled(self) -> bool:
        """Return whether cooperative cancellation was requested."""
        ...


class CrawlCancellationToken:
    """Process-local token backed by an asyncio event."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        """Request cooperative cancellation without cancelling arbitrary tasks."""
        self._event.set()


class NeverCancelledToken:
    """Default immutable token for callers that do not need cancellation."""

    def is_cancelled(self) -> bool:
        return False
