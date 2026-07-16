"""Framework-independent progress sinks and ordered event emission."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from musimack_tools.domain.run_progress import RunProgressEvent


class RunProgressSink(Protocol):
    async def on_progress(self, event: RunProgressEvent) -> None: ...


class NoOpRunProgressSink:
    async def on_progress(self, event: RunProgressEvent) -> None:
        del event


class RecordingRunProgressSink:
    def __init__(self) -> None:
        self._events: list[RunProgressEvent] = []

    @property
    def events(self) -> tuple[RunProgressEvent, ...]:
        return tuple(self._events)

    async def on_progress(self, event: RunProgressEvent) -> None:
        self._events.append(event)


class CallbackRunProgressSink:
    def __init__(
        self,
        callback: Callable[[RunProgressEvent], Awaitable[None]],
    ) -> None:
        self._callback = callback

    async def on_progress(self, event: RunProgressEvent) -> None:
        await self._callback(event)
