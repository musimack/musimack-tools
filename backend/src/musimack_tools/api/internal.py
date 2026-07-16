"""Explicit router and application composition for the private internal API."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated, Any, Never

from fastapi import APIRouter, Depends, FastAPI, Query
from fastapi.responses import JSONResponse

from musimack_tools.api.dependencies import (
    InternalApiApplication,
    create_access_dependency,
    enforce_declared_body_limit,
)
from musimack_tools.api.errors import install_internal_api_error_handlers
from musimack_tools.api.mapping import (
    application_warnings,
    cancellation_schema,
    capability_schema,
    job_status_schema,
    preflight_error_details,
    preflight_schema,
    progress_schema,
    readiness_schema,
    registry_status_schema,
    result_schema,
    submission_schema,
    to_raw_request,
    validation_error_details,
    validation_schema,
    validation_warnings,
)
from musimack_tools.api.schemas import (
    ApiErrorEnvelope,
    ApplicationRequestSchema,
    CancellationResponse,
    CapabilityResponse,
    JobProgressResponse,
    JobResultResponse,
    JobStatusResponse,
    PreflightResponse,
    ReadinessResponse,
    RegistryStatusResponse,
    SubmissionResponse,
    ValidationResponse,
)
from musimack_tools.domain.api import (
    ApiErrorCode,
    ApiErrorDetail,
    InternalApiConfiguration,
    InternalApiError,
)
from musimack_tools.domain.application import (
    ApplicationOutcomeCode,
    ApplicationValidationReport,
    PreflightState,
    ReadinessState,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

_JOB_ID_PATTERN = re.compile(r"^job-[0-9a-f]{12}-[0-9]{4}$")
_JOB_ID_MESSAGE = "The job identifier is invalid."


def create_internal_api_router(  # noqa: C901, PLR0915 - explicit route composition.
    service: InternalApiApplication,
    configuration: InternalApiConfiguration | None = None,
) -> APIRouter:
    """Create an unmounted, explicitly injected router with a fail-closed gate."""
    resolved = configuration or InternalApiConfiguration()
    access_dependency = create_access_dependency(resolved)
    body_limit_dependency = enforce_declared_body_limit(resolved)
    include_in_schema = (
        resolved.include_internal_routes_in_schema and resolved.include_internal_endpoints_in_docs
    )
    router = APIRouter(
        prefix=resolved.route_prefix,
        dependencies=[Depends(access_dependency), Depends(body_limit_dependency)],
        include_in_schema=include_in_schema,
    )
    error_responses: dict[int | str, dict[str, Any]] = {
        401: {"model": ApiErrorEnvelope},
        400: {"model": ApiErrorEnvelope},
        403: {"model": ApiErrorEnvelope},
        404: {"model": ApiErrorEnvelope},
        409: {"model": ApiErrorEnvelope},
        429: {"model": ApiErrorEnvelope},
        500: {"model": ApiErrorEnvelope},
        503: {"model": ApiErrorEnvelope},
    }

    @router.post(
        "/requests/validate",
        response_model=ValidationResponse,
        responses=error_responses,
    )
    async def validate_request(request: ApplicationRequestSchema) -> ValidationResponse:
        _validate_dynamic_request_bounds(request, resolved)
        report = service.validate_request(to_raw_request(request))
        if not report.valid:
            raise InternalApiError(
                400,
                ApiErrorCode.APPLICATION_VALIDATION_FAILED,
                "The request could not be prepared.",
                tuple(
                    ApiErrorDetail(item.code, item.message, item.field, item.source_code)
                    for item in validation_error_details(
                        report, resolved.maximum_validation_details
                    )
                ),
            )
        return ValidationResponse(
            data=validation_schema(report),
            warnings=validation_warnings(report),
        )

    @router.post(
        "/requests/preflight",
        response_model=PreflightResponse,
        responses=error_responses,
    )
    async def preflight(request: ApplicationRequestSchema) -> PreflightResponse:
        _validate_dynamic_request_bounds(request, resolved)
        report = await service.preflight(to_raw_request(request))
        if not report.validation.valid:
            raise InternalApiError(
                400,
                ApiErrorCode.APPLICATION_VALIDATION_FAILED,
                "The request could not be prepared.",
                tuple(
                    ApiErrorDetail(item.code, item.message, item.field, item.source_code)
                    for item in validation_error_details(
                        report.validation,
                        resolved.maximum_validation_details,
                    )
                ),
            )
        if report.state is PreflightState.BLOCKED:
            raise InternalApiError(
                409,
                ApiErrorCode.PREFLIGHT_BLOCKED,
                "Operational preflight currently blocks submission.",
                tuple(
                    ApiErrorDetail(item.code, item.message, item.field, item.source_code)
                    for item in preflight_error_details(report, resolved.maximum_validation_details)
                ),
            )
        return PreflightResponse(
            data=preflight_schema(report),
            warnings=validation_warnings(report.validation),
        )

    @router.post("/jobs", response_model=SubmissionResponse, responses=error_responses)
    async def submit(request: ApplicationRequestSchema) -> JSONResponse:
        _validate_dynamic_request_bounds(request, resolved)
        result = await service.submit(to_raw_request(request))
        if result.outcome in {
            ApplicationOutcomeCode.ACCEPTED,
            ApplicationOutcomeCode.QUEUED,
        }:
            return _json_response(
                202,
                SubmissionResponse(
                    data=submission_schema(result),
                    warnings=application_warnings(result.warnings),
                ),
            )
        if result.outcome is ApplicationOutcomeCode.DUPLICATE_RETURNED:
            return _json_response(
                200,
                SubmissionResponse(
                    data=submission_schema(result),
                    warnings=application_warnings(result.warnings),
                ),
            )
        _raise_submission_outcome(
            result.outcome,
            result.validation,
            resolved.maximum_validation_details,
        )

    @router.get("/jobs/{job_id}", response_model=JobStatusResponse, responses=error_responses)
    async def get_status(job_id: str) -> JobStatusResponse:
        _validate_job_id(job_id)
        status = await service.get_job_status(job_id)
        if status.outcome is ApplicationOutcomeCode.JOB_NOT_FOUND:
            raise InternalApiError(404, ApiErrorCode.JOB_NOT_FOUND, "The job was not found.")
        return JobStatusResponse(data=job_status_schema(status))

    @router.get(
        "/jobs/{job_id}/progress",
        response_model=JobProgressResponse,
        responses=error_responses,
    )
    async def get_progress(
        job_id: str,
        history_limit: Annotated[int, Query(ge=0)] = 0,
    ) -> JobProgressResponse:
        _validate_job_id(job_id)
        if history_limit > resolved.maximum_history_events:
            raise InternalApiError(
                400,
                ApiErrorCode.REQUEST_VALIDATION_FAILED,
                "The requested progress history exceeds the configured limit.",
            )
        progress = await service.get_job_progress(job_id)
        if progress.outcome is ApplicationOutcomeCode.JOB_NOT_FOUND:
            raise InternalApiError(404, ApiErrorCode.JOB_NOT_FOUND, "The job was not found.")
        return JobProgressResponse(data=progress_schema(progress, history_limit))

    @router.get(
        "/jobs/{job_id}/result",
        response_model=JobResultResponse,
        responses=error_responses,
    )
    async def get_result(job_id: str) -> JobResultResponse:
        _validate_job_id(job_id)
        result = await service.get_job_result(job_id)
        if result.outcome is ApplicationOutcomeCode.JOB_NOT_FOUND:
            raise InternalApiError(404, ApiErrorCode.JOB_NOT_FOUND, "The job was not found.")
        if result.outcome is ApplicationOutcomeCode.RESULT_UNAVAILABLE:
            raise InternalApiError(
                409,
                ApiErrorCode.JOB_RESULT_UNAVAILABLE,
                "The retained job metadata does not include a result payload.",
            )
        return JobResultResponse(data=result_schema(result))

    @router.post(
        "/jobs/{job_id}/cancel",
        response_model=CancellationResponse,
        responses=error_responses,
    )
    async def cancel(job_id: str) -> JSONResponse:
        _validate_job_id(job_id)
        result = await service.cancel_job(job_id)
        if result.outcome in {
            ApplicationOutcomeCode.CANCELLATION_REQUESTED,
            ApplicationOutcomeCode.CANCELLED_WHILE_QUEUED,
        }:
            return _json_response(202, CancellationResponse(data=cancellation_schema(result)))
        if result.outcome is ApplicationOutcomeCode.ALREADY_REQUESTED:
            return _json_response(200, CancellationResponse(data=cancellation_schema(result)))
        if result.outcome is ApplicationOutcomeCode.ALREADY_TERMINAL:
            raise InternalApiError(
                409,
                ApiErrorCode.JOB_ALREADY_TERMINAL,
                "The job is already terminal.",
            )
        if result.outcome is ApplicationOutcomeCode.JOB_NOT_FOUND:
            raise InternalApiError(404, ApiErrorCode.JOB_NOT_FOUND, "The job was not found.")
        if result.outcome is ApplicationOutcomeCode.REGISTRY_CLOSED:
            raise InternalApiError(503, ApiErrorCode.REGISTRY_CLOSED, "The registry is closed.")
        raise InternalApiError(
            503,
            ApiErrorCode.INTERNAL_SERVICE_UNAVAILABLE,
            "Cancellation is unavailable.",
        )

    @router.get("/registry", response_model=RegistryStatusResponse, responses=error_responses)
    async def registry() -> RegistryStatusResponse:
        result = await service.get_registry_status()
        return RegistryStatusResponse(data=registry_status_schema(result))

    @router.get("/readiness", response_model=ReadinessResponse, responses=error_responses)
    async def readiness() -> JSONResponse:
        result = await service.get_readiness()
        status_code = 503 if result.state is ReadinessState.NOT_READY else 200
        return _json_response(status_code, ReadinessResponse(data=readiness_schema(result)))

    @router.get("/capabilities", response_model=CapabilityResponse, responses=error_responses)
    async def capabilities() -> CapabilityResponse:
        return CapabilityResponse(data=capability_schema(service.get_capabilities()))

    @router.api_route(
        "/jobs/{invalid_job_path:path}",
        methods=["GET", "POST"],
        include_in_schema=False,
        response_model=None,
    )
    async def reject_path_like_job_id(invalid_job_path: str) -> Never:
        del invalid_job_path
        raise InternalApiError(400, ApiErrorCode.JOB_ID_INVALID, _JOB_ID_MESSAGE)

    return router


def mount_internal_api(
    application: FastAPI,
    service: InternalApiApplication,
    configuration: InternalApiConfiguration | None = None,
) -> bool:
    """Mount internal routes only when the immutable configuration explicitly opts in."""
    resolved = configuration or InternalApiConfiguration()
    if not resolved.mount_internal_routes:
        return False
    install_internal_api_error_handlers(application, resolved)
    application.include_router(create_internal_api_router(service, resolved))
    return True


def _validate_job_id(job_id: str) -> None:
    if _JOB_ID_PATTERN.fullmatch(job_id) is None:
        raise InternalApiError(400, ApiErrorCode.JOB_ID_INVALID, _JOB_ID_MESSAGE)


def _validate_dynamic_request_bounds(
    request: ApplicationRequestSchema,
    configuration: InternalApiConfiguration,
) -> None:
    if len(request.approved_hosts) > configuration.maximum_approved_hosts:
        raise InternalApiError(
            400,
            ApiErrorCode.REQUEST_VALIDATION_FAILED,
            "The approved-host list exceeds the configured limit.",
        )
    if len(request.seed_url) > configuration.maximum_url_characters:
        raise InternalApiError(
            400,
            ApiErrorCode.REQUEST_VALIDATION_FAILED,
            "The seed URL exceeds the configured limit.",
        )


def _raise_submission_outcome(
    outcome: ApplicationOutcomeCode,
    validation: ApplicationValidationReport,
    maximum_details: int,
) -> Never:
    if outcome is ApplicationOutcomeCode.VALIDATION_FAILED:
        raise InternalApiError(
            400,
            ApiErrorCode.APPLICATION_VALIDATION_FAILED,
            "The request could not be prepared.",
            tuple(
                ApiErrorDetail(item.code, item.message, item.field, item.source_code)
                for item in validation_error_details(validation, maximum_details)
            ),
        )
    mappings = {
        ApplicationOutcomeCode.ACTIVE_DUPLICATE: (
            409,
            ApiErrorCode.ACTIVE_DUPLICATE,
            "An active job already represents this run.",
        ),
        ApplicationOutcomeCode.QUEUE_CAPACITY_REACHED: (
            429,
            ApiErrorCode.QUEUE_CAPACITY_REACHED,
            "The internal job queue is full.",
        ),
        ApplicationOutcomeCode.REGISTRY_CLOSED: (
            503,
            ApiErrorCode.REGISTRY_CLOSED,
            "The registry is closed.",
        ),
    }
    status, code, message = mappings.get(
        outcome,
        (
            503,
            ApiErrorCode.INTERNAL_SERVICE_UNAVAILABLE,
            "The internal application service is unavailable.",
        ),
    )
    raise InternalApiError(status, code, message)


def _json_response(status_code: int, value: BaseModel) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=value.model_dump(mode="json"))
