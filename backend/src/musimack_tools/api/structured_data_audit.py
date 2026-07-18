"""Private authenticated structured-data audit routes."""

# ruff: noqa: ANN401, C901, PLR0913, TRY003

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from musimack_tools.api.dependencies import create_access_dependency
from musimack_tools.api.schemas import ApiErrorEnvelope, ApiSchema
from musimack_tools.domain.api import ApiErrorCode, InternalApiConfiguration, InternalApiError
from musimack_tools.domain.structured_data_audit import (
    STRUCTURED_DATA_API_VERSION,
    StructuredDataExportFormat,
)
from musimack_tools.security.correlation import current_request_id

if TYPE_CHECKING:
    from musimack_tools.structured_data_audit.service import StructuredDataAuditService


class StructuredDataAuditCreateRequest(ApiSchema):
    run_id: str = Field(min_length=1, max_length=64)


class StructuredDataExportRequest(ApiSchema):
    format: StructuredDataExportFormat


class StructuredDataAuditResponse(ApiSchema):
    structured_data_api_version: str = STRUCTURED_DATA_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: Any


def create_structured_data_audit_router(
    service: StructuredDataAuditService, configuration: InternalApiConfiguration
) -> APIRouter:
    if not service.configuration.enabled:
        raise ValueError("structured-data audit routes require enabled configuration")
    include = (
        configuration.include_internal_routes_in_schema
        and configuration.include_internal_endpoints_in_docs
    )
    router = APIRouter(
        prefix=f"{configuration.route_prefix}/audits/structured-data",
        dependencies=[Depends(create_access_dependency(configuration))],
        include_in_schema=include,
    )
    errors: dict[int | str, dict[str, Any]] = {
        code: {"model": ApiErrorEnvelope} for code in (400, 401, 403, 404, 409, 503)
    }

    def response(factory: Any) -> StructuredDataAuditResponse:
        try:
            return StructuredDataAuditResponse(data=factory())
        except ValueError as error:
            raise _api_error(error) from None

    @router.get("/evidence/{run_id}", response_model=StructuredDataAuditResponse, responses=errors)
    async def evidence(run_id: str) -> StructuredDataAuditResponse:
        return response(lambda: service.evidence_status(run_id))

    @router.get("", response_model=StructuredDataAuditResponse, responses=errors)
    async def audits(
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
    ) -> StructuredDataAuditResponse:
        return response(lambda: service.list_audits(cursor, page_size))

    @router.post("", response_model=StructuredDataAuditResponse, responses=errors)
    async def create(request: StructuredDataAuditCreateRequest) -> StructuredDataAuditResponse:
        return response(lambda: service.create_audit(request.run_id))

    @router.get("/{audit_id}", response_model=StructuredDataAuditResponse, responses=errors)
    async def detail(audit_id: str) -> StructuredDataAuditResponse:
        return response(lambda: service.get(audit_id))

    @router.post(
        "/{audit_id}/execute", response_model=StructuredDataAuditResponse, responses=errors
    )
    async def execute(audit_id: str) -> StructuredDataAuditResponse:
        try:
            return StructuredDataAuditResponse(data=await service.execute_audit(audit_id))
        except ValueError as error:
            raise _api_error(error) from None

    @router.get("/{audit_id}/summary", response_model=StructuredDataAuditResponse, responses=errors)
    async def summary(audit_id: str) -> StructuredDataAuditResponse:
        return response(lambda: service.summary(audit_id))

    def add_resource(path: str) -> None:
        async def endpoint(
            audit_id: str,
            page_size: Annotated[int | None, Query(ge=1)] = None,
            cursor: Annotated[str | None, Query(max_length=2048)] = None,
            page_url: Annotated[str | None, Query(max_length=4096)] = None,
            code: Annotated[str | None, Query(max_length=128)] = None,
            severity: Annotated[str | None, Query(max_length=32)] = None,
            confidence: Annotated[str | None, Query(max_length=32)] = None,
            requires_human_review: Annotated[bool | None, Query()] = None,
            scope: Annotated[str | None, Query(max_length=32)] = None,
            format_name: Annotated[str | None, Query(alias="format", max_length=32)] = None,
            entity_type: Annotated[str | None, Query(max_length=256)] = None,
            property_name: Annotated[str | None, Query(max_length=512)] = None,
            profile_name: Annotated[str | None, Query(max_length=128)] = None,
            observation_state: Annotated[str | None, Query(max_length=32)] = None,
            action: Annotated[str | None, Query(max_length=128)] = None,
            search: Annotated[str | None, Query(max_length=512)] = None,
        ) -> StructuredDataAuditResponse:
            filters = {
                key: value
                for key, value in {
                    "page_url": page_url,
                    "code": code,
                    "severity": severity,
                    "confidence": confidence,
                    "requires_human_review": requires_human_review,
                    "scope": scope,
                    "format": format_name,
                    "entity_type": entity_type,
                    "property_name": property_name,
                    "profile_name": profile_name,
                    "observation_state": observation_state,
                    "action": action,
                    "search": search,
                }.items()
                if value is not None
            }
            return response(
                lambda: service.list_resource(audit_id, path, cursor, page_size, filters)
            )

        router.add_api_route(
            f"/{{audit_id}}/{path}",
            endpoint,
            methods=["GET"],
            response_model=StructuredDataAuditResponse,
            responses=errors,
        )

    for name in (
        "blocks",
        "entities",
        "properties",
        "pages",
        "parse-findings",
        "consistency-findings",
        "duplicate-groups",
        "profiles",
        "recommendations",
    ):
        add_resource(name)

    @router.get("/{audit_id}/exports", response_model=StructuredDataAuditResponse, responses=errors)
    async def exports(audit_id: str) -> StructuredDataAuditResponse:
        return response(lambda: {"items": service.list_exports(audit_id)})

    @router.post(
        "/{audit_id}/exports", response_model=StructuredDataAuditResponse, responses=errors
    )
    async def export(
        audit_id: str, request: StructuredDataExportRequest
    ) -> StructuredDataAuditResponse:
        return response(lambda: service.create_export(audit_id, request.format))

    return router


def _api_error(error: ValueError) -> InternalApiError:
    raw = str(error)
    try:
        code = ApiErrorCode(raw)
    except ValueError:
        code = ApiErrorCode.STRUCTURED_DATA_AUDIT_QUERY_FAILED
    status = (
        404
        if raw.endswith(("run_not_found", "audit_not_found"))
        else 409
        if raw.endswith(("already_terminal", "run_not_terminal"))
        else 400
        if "invalid" in raw or "mismatch" in raw
        else 503
    )
    return InternalApiError(
        status, code, "The structured-data audit request could not be completed."
    )
