"""Private authenticated CSA-04 execution and bounded inspection routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field

from musimack_tools.api.dependencies import create_access_dependency
from musimack_tools.api.schemas import ApiErrorEnvelope, ApiSchema
from musimack_tools.domain.api import ApiErrorCode, InternalApiConfiguration, InternalApiError
from musimack_tools.domain.authentication import AuthenticatedPrincipal
from musimack_tools.domain.site_audit_orchestration import (
    SITE_AUDIT_ORCHESTRATION_VERSION,
    SiteAuditOrchestrationError,
)
from musimack_tools.domain.site_audit_persistence import SiteAuditPersistenceError
from musimack_tools.security.correlation import current_request_id

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from musimack_tools.site_audit.orchestration import SiteAuditOrchestrationService


class SiteAuditExecutionResponse(ApiSchema):
    site_audit_orchestration_version: str = SITE_AUDIT_ORCHESTRATION_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: Any


def create_site_audit_orchestration_router(  # noqa: C901
    service: SiteAuditOrchestrationService, configuration: InternalApiConfiguration
) -> APIRouter:
    include = (
        configuration.include_internal_routes_in_schema
        and configuration.include_internal_endpoints_in_docs
    )
    router = APIRouter(
        prefix=f"{configuration.route_prefix}/site-audits",
        dependencies=[Depends(create_access_dependency(configuration))],
        include_in_schema=include,
    )
    errors: dict[int | str, dict[str, Any]] = {
        code: {"model": ApiErrorEnvelope} for code in (400, 401, 403, 404, 409, 503)
    }

    @router.post("/{audit_id}/submit", response_model=SiteAuditExecutionResponse, responses=errors)
    async def submit(audit_id: str, request: Request) -> SiteAuditExecutionResponse:
        return await _async_response(service.submit(audit_id, actor=_actor(request)))

    @router.post("/{audit_id}/cancel", response_model=SiteAuditExecutionResponse, responses=errors)
    async def cancel(audit_id: str) -> SiteAuditExecutionResponse:
        return await _async_response(service.cancel(audit_id))

    @router.post("/{audit_id}/retry", response_model=SiteAuditExecutionResponse, responses=errors)
    async def retry(audit_id: str) -> SiteAuditExecutionResponse:
        return await _async_response(service.retry(audit_id))

    @router.post(
        "/{audit_id}/reconcile", response_model=SiteAuditExecutionResponse, responses=errors
    )
    async def reconcile(audit_id: str) -> SiteAuditExecutionResponse:
        return await _async_response(service.reconcile(audit_id))

    @router.get("/{audit_id}/status", response_model=SiteAuditExecutionResponse, responses=errors)
    async def status(audit_id: str) -> SiteAuditExecutionResponse:
        return _response(lambda: service.status(audit_id))

    @router.get("/{audit_id}/summary", response_model=SiteAuditExecutionResponse, responses=errors)
    async def summary(audit_id: str) -> SiteAuditExecutionResponse:
        return _response(lambda: service.summary(audit_id))

    @router.get("/{audit_id}/modules", response_model=SiteAuditExecutionResponse, responses=errors)
    async def modules(audit_id: str) -> SiteAuditExecutionResponse:
        return _response(lambda: service.status(audit_id)["modules"])

    @router.get("/{audit_id}/pages", response_model=SiteAuditExecutionResponse, responses=errors)
    async def pages(
        audit_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    ) -> SiteAuditExecutionResponse:
        return _response(lambda: service.pages(audit_id, offset=offset, page_size=page_size))

    @router.get("/{audit_id}/issues", response_model=SiteAuditExecutionResponse, responses=errors)
    async def issues(
        audit_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    ) -> SiteAuditExecutionResponse:
        return _response(lambda: service.issues(audit_id, offset=offset, page_size=page_size))

    @router.get("/{audit_id}/rules", response_model=SiteAuditExecutionResponse, responses=errors)
    async def rules(
        audit_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    ) -> SiteAuditExecutionResponse:
        return _response(lambda: service.rules(audit_id, offset=offset, page_size=page_size))

    @router.get(
        "/{audit_id}/artifacts", response_model=SiteAuditExecutionResponse, responses=errors
    )
    async def artifacts(audit_id: str) -> SiteAuditExecutionResponse:
        return _response(lambda: service.artifact_associations(audit_id))

    @router.post(
        "/{audit_id}/rebuild-summary",
        response_model=SiteAuditExecutionResponse,
        responses=errors,
    )
    async def rebuild_summary(audit_id: str) -> SiteAuditExecutionResponse:
        return _response(lambda: service.rebuild_summary(audit_id))

    return router


async def _async_response(operation: Awaitable[Any]) -> SiteAuditExecutionResponse:
    try:
        return SiteAuditExecutionResponse(data=await operation)
    except (SiteAuditOrchestrationError, SiteAuditPersistenceError) as error:
        raise _api_error(error.code, str(error)) from None
    except KeyError, TypeError, ValueError:
        raise InternalApiError(
            400,
            ApiErrorCode.REQUEST_VALIDATION_FAILED,
            "The Site Audit request is invalid.",
        ) from None


def _response(operation: Callable[[], Any]) -> SiteAuditExecutionResponse:
    try:
        return SiteAuditExecutionResponse(data=operation())
    except (SiteAuditOrchestrationError, SiteAuditPersistenceError) as error:
        raise _api_error(error.code, str(error)) from None
    except KeyError, TypeError, ValueError:
        raise InternalApiError(
            400,
            ApiErrorCode.REQUEST_VALIDATION_FAILED,
            "The Site Audit request is invalid.",
        ) from None


def _api_error(code: str, explanation: str) -> InternalApiError:
    mapped = _ERROR_CODES.get(code, ApiErrorCode.SITE_AUDIT_ORCHESTRATION_FAILED)
    status = (
        404
        if mapped is ApiErrorCode.SITE_AUDIT_NOT_FOUND
        else 409
        if mapped
        in {
            ApiErrorCode.SITE_AUDIT_NOT_READY,
            ApiErrorCode.SITE_AUDIT_STATE_CONFLICT,
            ApiErrorCode.SITE_AUDIT_RETRY_NOT_ALLOWED,
            ApiErrorCode.SITE_AUDIT_CANCELLATION_NOT_ALLOWED,
        }
        else 503
        if mapped
        in {
            ApiErrorCode.SITE_AUDIT_CRAWL_SUBMISSION_FAILED,
            ApiErrorCode.SITE_AUDIT_EVIDENCE_UNAVAILABLE,
        }
        else 400
    )
    return InternalApiError(status, mapped, explanation)


def _actor(request: Request) -> str:
    principal = getattr(request.state, "authenticated_principal", None)
    if isinstance(principal, AuthenticatedPrincipal):
        return principal.user_id or principal.email or principal.principal_type.value
    return "authenticated-principal"


_ERROR_CODES = {
    "site_audit_not_found": ApiErrorCode.SITE_AUDIT_NOT_FOUND,
    "site_audit_not_ready": ApiErrorCode.SITE_AUDIT_NOT_READY,
    "site_audit_submission_conflict": ApiErrorCode.SITE_AUDIT_STATE_CONFLICT,
    "site_audit_snapshot_missing": ApiErrorCode.SITE_AUDIT_SNAPSHOT_MISSING,
    "site_audit_snapshot_integrity_invalid": ApiErrorCode.SITE_AUDIT_SNAPSHOT_INTEGRITY_INVALID,
    "site_audit_crawl_submission_failed": ApiErrorCode.SITE_AUDIT_CRAWL_SUBMISSION_FAILED,
    "site_audit_evidence_unavailable": ApiErrorCode.SITE_AUDIT_EVIDENCE_UNAVAILABLE,
    "site_audit_projection_unavailable": ApiErrorCode.SITE_AUDIT_PROJECTION_UNAVAILABLE,
    "site_audit_retry_not_allowed": ApiErrorCode.SITE_AUDIT_RETRY_NOT_ALLOWED,
    "site_audit_cancellation_not_allowed": ApiErrorCode.SITE_AUDIT_CANCELLATION_NOT_ALLOWED,
}
