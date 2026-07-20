"""Framework-independent facade for internal crawl-run job coordination."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from musimack_tools.domain.job import (
        JobCancellationResult,
        JobLookupResult,
        JobProgressView,
        JobRecommendationDetail,
        JobRecommendationPage,
        JobResultView,
        JobSubmissionRequest,
        JobSubmissionResult,
        JobWaitResult,
    )
    from musimack_tools.domain.job_registry import JobRegistrySnapshot, JobShutdownResult
    from musimack_tools.jobs.registry import InMemoryJobRegistry


class InternalJobService:
    """Thin internal service over one explicitly injected process-local registry."""

    def __init__(self, registry: InMemoryJobRegistry) -> None:
        self._registry = registry

    async def submit(self, request: JobSubmissionRequest) -> JobSubmissionResult:
        return await self._registry.submit(request)

    async def status(self, job_id: str) -> JobLookupResult:
        return await self._registry.lookup(job_id)

    async def progress(self, job_id: str) -> JobProgressView:
        return await self._registry.progress(job_id)

    async def result(self, job_id: str) -> JobResultView:
        return await self._registry.result(job_id)

    async def recommendations(  # noqa: PLR0913 - bounded filter contract.
        self,
        job_id: str,
        *,
        offset: int,
        limit: int,
        state: str | None = None,
        reason: str | None = None,
        text: str | None = None,
    ) -> JobRecommendationPage:
        from musimack_tools.jobs.recommendations import (  # noqa: PLC0415
            recommendations_from_result,
        )

        return recommendations_from_result(
            await self._registry.result(job_id),
            offset=offset,
            limit=limit,
            state=state,
            reason=reason,
            text=text,
        )

    async def recommendation_detail(self, job_id: str, sequence: int) -> JobRecommendationDetail:
        from musimack_tools.jobs.recommendations import (  # noqa: PLC0415
            recommendation_detail_from_result,
        )

        return recommendation_detail_from_result(
            await self._registry.result(job_id), sequence=sequence
        )

    async def cancel(self, job_id: str) -> JobCancellationResult:
        return await self._registry.cancel(job_id)

    async def wait(
        self,
        job_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> JobWaitResult:
        return await self._registry.wait_for_completion(
            job_id,
            timeout_seconds=timeout_seconds,
        )

    async def snapshot(self) -> JobRegistrySnapshot:
        return await self._registry.snapshot()

    async def shutdown(self) -> JobShutdownResult:
        return await self._registry.shutdown()
