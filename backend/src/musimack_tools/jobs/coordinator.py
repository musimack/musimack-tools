"""Injected execution boundary used by the process-local job coordinator."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from musimack_tools.crawl.cancellation import CancellationToken
    from musimack_tools.domain.run import CrawlRunRequest, CrawlRunResult
    from musimack_tools.run.progress import RunProgressSink


class JobRunExecutor(Protocol):
    async def execute(self, request: CrawlRunRequest) -> CrawlRunResult: ...


class JobRunServiceFactory(Protocol):
    def __call__(
        self,
        cancellation: CancellationToken,
        progress_sink: RunProgressSink,
    ) -> JobRunExecutor: ...
