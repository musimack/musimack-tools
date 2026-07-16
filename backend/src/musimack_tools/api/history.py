"""Authenticated internal API schemas and routes for durable history."""

# ruff: noqa: C901, FBT001, PLR0913, TRY003 - FastAPI query signatures are contracts.

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - FastAPI resolves annotations at runtime.
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import ConfigDict, Field

from musimack_tools.api.dependencies import create_access_dependency
from musimack_tools.api.schemas import ApiErrorEnvelope, ApiSchema
from musimack_tools.domain.api import ApiErrorCode, InternalApiConfiguration, InternalApiError
from musimack_tools.domain.history import (
    HISTORY_API_VERSION,
    HistoricalJob,
    HistoricalRun,
    HistoryError,
    HistoryFailureCode,
    HistoryPage,
    HistoryPageRequest,
    JobHistoryFilter,
    RelatedHistory,
    RunHistoryFilter,
)
from musimack_tools.security.correlation import current_request_id

if TYPE_CHECKING:
    from collections.abc import Callable

    from musimack_tools.history.service import HistoryService


class HistorySchema(ApiSchema):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)


class HistoricalJobSchema(HistorySchema):
    job_id: str
    run_id: str
    seed: str
    scheduler_mode: str
    state: str
    queue_state: str | None
    attempt_count: int
    maximum_attempts: int | None
    retry_eligible_at: datetime | None
    cancellation_requested: bool
    submitted_at: datetime | None
    started_at: datetime | None
    terminal_at: datetime | None
    last_failure_code: str | None
    terminal_disposition: str | None
    interrupted: bool
    recovered: bool
    retention_state: str
    result_available: bool
    artifact_available: bool
    summary_available: bool
    availability: str
    projection_version: str


class HistoricalRunSchema(HistorySchema):
    run_id: str
    job_id: str
    seed: str
    lifecycle: str
    started_at: datetime | None
    terminal_at: datetime | None
    duration_seconds: float | None
    current_stage: str | None
    stage_count: int
    completed_stage_count: int
    failed_stage_count: int
    skipped_stage_count: int
    crawl_count: int
    crawl_byte_count: int | None
    recommendation_count: int
    xml_count: int
    publication_count: int
    warning_count: int
    failure_count: int
    artifact_count: int
    summary_json_available: bool
    summary_markdown_available: bool
    partial: bool
    interrupted: bool
    retention_state: str
    availability: str
    projection_version: str


class AttemptSchema(HistorySchema):
    attempt_number: int
    execution_number: int
    state: str
    started_at: datetime
    terminal_at: datetime | None
    worker_id: str
    lease_generation: int
    retryable: bool
    failure_code: str | None
    terminal_disposition: str | None
    cancellation_observed: bool
    duration_seconds: float | None


class StageSchema(HistorySchema):
    stage: str
    order: int
    state: str
    started_at: datetime | None
    terminal_at: datetime | None
    duration_seconds: float | None
    warning_count: int
    failure_count: int
    result_available: bool
    partial: bool
    version: str


class MessageSchema(HistorySchema):
    code: str
    stage: str | None
    severity: str
    summary: str
    occurred_at: datetime | None
    related_url: str | None


class ArtifactReferenceSchema(HistorySchema):
    artifact_id: str
    artifact_type: str
    lifecycle_state: str
    integrity_state: str
    filename: str
    content_type: str
    byte_count: int
    created_at: datetime
    last_verified_at: datetime | None
    download_available: bool


class HistoryDiagnosticsSchema(HistorySchema):
    enabled: bool
    default_page_size: int
    maximum_page_size: int
    historical_job_count: int
    historical_run_count: int
    terminal_job_count: int
    interrupted_job_count: int
    retry_attempt_count: int
    metadata_only_count: int
    runs_with_artifacts: int
    runs_with_missing_artifacts: int
    last_successful_query_at: datetime | None
    last_failure_reason: str | None
    migration_ready: bool
    database_ready: bool
    service_version: str
    api_version: str
    pagination_version: str


class HistoryPageMetadataSchema(HistorySchema):
    page_size: int
    returned_count: int
    has_more: bool
    next_cursor: str | None
    applied_filters: tuple[tuple[str, str], ...]
    ordering: str
    version: str


class JobPageDataSchema(HistoryPageMetadataSchema):
    items: tuple[HistoricalJobSchema, ...]


class RunPageDataSchema(HistoryPageMetadataSchema):
    items: tuple[HistoricalRunSchema, ...]


class RelatedDataSchema(HistorySchema):
    items: tuple[dict[str, Any], ...]
    returned_count: int
    truncated: bool
    maximum: int


class HistoryResponse(HistorySchema):
    history_api_version: str = HISTORY_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: dict[str, Any]


class JobPageResponse(HistorySchema):
    history_api_version: str = HISTORY_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: JobPageDataSchema


class RunPageResponse(HistorySchema):
    history_api_version: str = HISTORY_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: RunPageDataSchema


def create_history_router(
    service: HistoryService, configuration: InternalApiConfiguration
) -> APIRouter:
    """Build ten private, authenticated routes only for an enabled history service."""
    if not service.configuration.enabled:
        raise ValueError("history routes require enabled history configuration")
    access = create_access_dependency(configuration)
    include = (
        configuration.include_internal_routes_in_schema
        and configuration.include_internal_endpoints_in_docs
    )
    router = APIRouter(
        prefix=f"{configuration.route_prefix}/history",
        dependencies=[Depends(access)],
        include_in_schema=include,
    )
    errors: dict[int | str, dict[str, Any]] = {
        400: {"model": ApiErrorEnvelope},
        401: {"model": ApiErrorEnvelope},
        403: {"model": ApiErrorEnvelope},
        404: {"model": ApiErrorEnvelope},
        503: {"model": ApiErrorEnvelope},
    }

    @router.get("/jobs", response_model=JobPageResponse, responses=errors)
    async def list_jobs(
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
        job_id: str | None = None,
        run_id: str | None = None,
        state: str | None = None,
        seed: str | None = None,
        scheduler_mode: str | None = None,
        cancellation_requested: bool | None = None,
        retry_eligible: bool | None = None,
        retention_state: str | None = None,
        artifacts_available: bool | None = None,
        interrupted: bool | None = None,
        recovered: bool | None = None,
        submitted_from: datetime | None = None,
        submitted_to: datetime | None = None,
        terminal_from: datetime | None = None,
        terminal_to: datetime | None = None,
    ) -> JobPageResponse:
        try:
            page = service.list_jobs(
                JobHistoryFilter(
                    job_id,
                    run_id,
                    state,
                    seed,
                    scheduler_mode,
                    submitted_from,
                    submitted_to,
                    terminal_from,
                    terminal_to,
                    cancellation_requested,
                    retry_eligible,
                    retention_state,
                    artifacts_available,
                    interrupted,
                    recovered,
                ),
                HistoryPageRequest(page_size or service.configuration.default_page_size, cursor),
            )
            return JobPageResponse(data=_job_page(page))
        except (HistoryError, ValueError) as error:
            raise _api_error(error) from None

    @router.get("/jobs/{job_id}", response_model=HistoryResponse, responses=errors)
    async def get_job(job_id: str) -> HistoryResponse:
        return _response(
            lambda: HistoricalJobSchema.model_validate(service.get_job(job_id)).model_dump(
                mode="json"
            )
        )

    @router.get("/jobs/{job_id}/attempts", response_model=HistoryResponse, responses=errors)
    async def attempts(job_id: str) -> HistoryResponse:
        return _response(lambda: _related(service.attempts(job_id), AttemptSchema))

    @router.get("/runs", response_model=RunPageResponse, responses=errors)
    async def list_runs(
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
        run_id: str | None = None,
        job_id: str | None = None,
        state: str | None = None,
        completion_state: str | None = None,
        stage_state: str | None = None,
        has_warnings: bool | None = None,
        has_failures: bool | None = None,
        has_artifacts: bool | None = None,
        partial: bool | None = None,
        interrupted: bool | None = None,
        retention_state: str | None = None,
        started_from: datetime | None = None,
        started_to: datetime | None = None,
        terminal_from: datetime | None = None,
        terminal_to: datetime | None = None,
    ) -> RunPageResponse:
        try:
            page = service.list_runs(
                RunHistoryFilter(
                    run_id,
                    job_id,
                    state,
                    completion_state,
                    stage_state,
                    started_from,
                    started_to,
                    terminal_from,
                    terminal_to,
                    has_warnings,
                    has_failures,
                    has_artifacts,
                    partial,
                    interrupted,
                    retention_state,
                ),
                HistoryPageRequest(page_size or service.configuration.default_page_size, cursor),
            )
            return RunPageResponse(data=_run_page(page))
        except (HistoryError, ValueError) as error:
            raise _api_error(error) from None

    @router.get("/runs/{run_id}", response_model=HistoryResponse, responses=errors)
    async def get_run(run_id: str) -> HistoryResponse:
        return _response(
            lambda: HistoricalRunSchema.model_validate(service.get_run(run_id)).model_dump(
                mode="json"
            )
        )

    @router.get("/runs/{run_id}/stages", response_model=HistoryResponse, responses=errors)
    async def stages(run_id: str) -> HistoryResponse:
        return _response(lambda: _related(service.stages(run_id), StageSchema))

    @router.get("/runs/{run_id}/warnings", response_model=HistoryResponse, responses=errors)
    async def warnings(run_id: str) -> HistoryResponse:
        return _response(lambda: _related(service.warnings(run_id), MessageSchema))

    @router.get("/runs/{run_id}/failures", response_model=HistoryResponse, responses=errors)
    async def failures(run_id: str) -> HistoryResponse:
        return _response(lambda: _related(service.failures(run_id), MessageSchema))

    @router.get("/runs/{run_id}/artifacts", response_model=HistoryResponse, responses=errors)
    async def artifacts(run_id: str) -> HistoryResponse:
        return _response(lambda: _related(service.artifacts(run_id), ArtifactReferenceSchema))

    @router.get("/diagnostics", response_model=HistoryResponse, responses=errors)
    async def diagnostics() -> HistoryResponse:
        return _response(
            lambda: HistoryDiagnosticsSchema.model_validate(service.diagnostics()).model_dump(
                mode="json"
            )
        )

    return router


def _job_page(page: HistoryPage[HistoricalJob]) -> JobPageDataSchema:
    return JobPageDataSchema(
        items=tuple(HistoricalJobSchema.model_validate(item) for item in page.items),
        page_size=page.page_size,
        returned_count=page.returned_count,
        has_more=page.has_more,
        next_cursor=page.next_cursor,
        applied_filters=page.applied_filters,
        ordering=page.ordering,
        version=page.version,
    )


def _run_page(page: HistoryPage[HistoricalRun]) -> RunPageDataSchema:
    return RunPageDataSchema(
        items=tuple(HistoricalRunSchema.model_validate(item) for item in page.items),
        page_size=page.page_size,
        returned_count=page.returned_count,
        has_more=page.has_more,
        next_cursor=page.next_cursor,
        applied_filters=page.applied_filters,
        ordering=page.ordering,
        version=page.version,
    )


def _related[T](items: RelatedHistory[T], schema: type[HistorySchema]) -> dict[str, Any]:
    return {
        "items": [schema.model_validate(item).model_dump(mode="json") for item in items.items],
        "returned_count": items.returned_count,
        "truncated": items.truncated,
        "maximum": items.maximum,
    }


def _response(factory: Callable[[], dict[str, Any]]) -> HistoryResponse:
    try:
        return HistoryResponse(data=factory())
    except (HistoryError, ValueError) as error:
        raise _api_error(error) from None


def _api_error(error: HistoryError | ValueError) -> InternalApiError:
    if isinstance(error, ValueError):
        return InternalApiError(
            400, ApiErrorCode.REQUEST_VALIDATION_FAILED, "The history filters are invalid."
        )
    mapping = {
        HistoryFailureCode.DISABLED: (503, ApiErrorCode.HISTORY_DISABLED),
        HistoryFailureCode.INVALID_PAGE_SIZE: (400, ApiErrorCode.HISTORY_INVALID_PAGE_SIZE),
        HistoryFailureCode.INVALID_CURSOR: (400, ApiErrorCode.HISTORY_INVALID_CURSOR),
        HistoryFailureCode.CURSOR_VERSION_UNSUPPORTED: (
            400,
            ApiErrorCode.HISTORY_CURSOR_VERSION_UNSUPPORTED,
        ),
        HistoryFailureCode.CURSOR_FILTER_MISMATCH: (
            400,
            ApiErrorCode.HISTORY_CURSOR_FILTER_MISMATCH,
        ),
        HistoryFailureCode.CURSOR_ORDER_MISMATCH: (
            400,
            ApiErrorCode.HISTORY_CURSOR_FILTER_MISMATCH,
        ),
        HistoryFailureCode.JOB_NOT_FOUND: (404, ApiErrorCode.HISTORY_JOB_NOT_FOUND),
        HistoryFailureCode.RUN_NOT_FOUND: (404, ApiErrorCode.HISTORY_RUN_NOT_FOUND),
    }
    status, code = mapping.get(error.code, (503, ApiErrorCode.HISTORY_QUERY_FAILED))
    return InternalApiError(status, code, str(error))
