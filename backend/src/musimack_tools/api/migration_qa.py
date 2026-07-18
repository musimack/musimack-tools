"""Private authenticated website migration QA routes."""

# ruff: noqa: ANN401, C901, FBT001, PLR0913, TRY003

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from musimack_tools.api.dependencies import create_access_dependency
from musimack_tools.api.schemas import ApiErrorEnvelope, ApiSchema
from musimack_tools.domain.api import ApiErrorCode, InternalApiConfiguration, InternalApiError
from musimack_tools.domain.migration_qa import (
    MIGRATION_QA_API_VERSION,
    MigrationQaExportFormat,
    MigrationQaMode,
    MigrationType,
)
from musimack_tools.security.correlation import current_request_id

if TYPE_CHECKING:
    from musimack_tools.migration_qa.service import MigrationQaService


class MigrationQaCreateRequest(ApiSchema):
    name: str = Field(min_length=1, max_length=256)
    destination_run_id: str = Field(min_length=1, max_length=64)
    destination_origin: str = Field(min_length=1, max_length=4096)
    mode: MigrationQaMode
    migration_type: MigrationType
    source_run_id: str | None = Field(default=None, max_length=64)
    source_origin: str | None = Field(default=None, max_length=4096)
    policy: dict[str, bool] | None = None


class MigrationQaIngestRequest(ApiSchema):
    content: str = Field(min_length=1)


class MigrationQaPreviewRequest(ApiSchema):
    kind: str = Field(pattern="^(source_inventory|redirect_map)$")
    content: str = Field(min_length=1)


class MigrationQaExportRequest(ApiSchema):
    format: MigrationQaExportFormat


class MigrationQaResponse(ApiSchema):
    migration_qa_api_version: str = MIGRATION_QA_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: Any


def create_migration_qa_router(
    service: MigrationQaService, configuration: InternalApiConfiguration
) -> APIRouter:
    if not service.configuration.enabled:
        raise ValueError("migration QA routes require enabled configuration")
    include = (
        configuration.include_internal_routes_in_schema
        and configuration.include_internal_endpoints_in_docs
    )
    router = APIRouter(
        prefix=f"{configuration.route_prefix}/migrations/qa",
        dependencies=[Depends(create_access_dependency(configuration))],
        include_in_schema=include,
    )
    errors: dict[int | str, dict[str, Any]] = {
        code: {"model": ApiErrorEnvelope} for code in (400, 401, 403, 404, 409, 503)
    }

    def response(factory: Any) -> MigrationQaResponse:
        try:
            return MigrationQaResponse(data=factory())
        except ValueError as error:
            raise _api_error(error) from None

    @router.get("/evidence/{run_id}", response_model=MigrationQaResponse, responses=errors)
    async def evidence(run_id: str) -> MigrationQaResponse:
        return response(lambda: service.evidence_status(run_id))

    @router.get("", response_model=MigrationQaResponse, responses=errors)
    async def projects(
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
    ) -> MigrationQaResponse:
        return response(lambda: service.list_projects(cursor, page_size))

    @router.post("", response_model=MigrationQaResponse, responses=errors)
    async def create(request: MigrationQaCreateRequest) -> MigrationQaResponse:
        return response(lambda: service.create_project(**request.model_dump()))

    @router.get("/{project_id}", response_model=MigrationQaResponse, responses=errors)
    async def detail(project_id: str) -> MigrationQaResponse:
        return response(lambda: service.get(project_id))

    @router.post(
        "/{project_id}/source-inventory", response_model=MigrationQaResponse, responses=errors
    )
    async def inventory(project_id: str, request: MigrationQaIngestRequest) -> MigrationQaResponse:
        return response(lambda: service.ingest_source_inventory(project_id, request.content))

    @router.post("/{project_id}/preview", response_model=MigrationQaResponse, responses=errors)
    async def preview(project_id: str, request: MigrationQaPreviewRequest) -> MigrationQaResponse:
        return response(lambda: service.preview_input(project_id, request.kind, request.content))

    @router.post("/{project_id}/redirect-map", response_model=MigrationQaResponse, responses=errors)
    async def redirect_map(
        project_id: str, request: MigrationQaIngestRequest
    ) -> MigrationQaResponse:
        return response(lambda: service.ingest_redirect_map(project_id, request.content))

    @router.get("/{project_id}/readiness", response_model=MigrationQaResponse, responses=errors)
    async def readiness(project_id: str) -> MigrationQaResponse:
        return response(lambda: service.readiness(project_id))

    @router.post("/{project_id}/execute", response_model=MigrationQaResponse, responses=errors)
    async def execute(project_id: str) -> MigrationQaResponse:
        try:
            return MigrationQaResponse(data=await service.execute_project(project_id))
        except ValueError as error:
            raise _api_error(error) from None

    @router.post("/{project_id}/cancel", response_model=MigrationQaResponse, responses=errors)
    async def cancel(project_id: str) -> MigrationQaResponse:
        return response(lambda: service.cancel(project_id))

    @router.get("/{project_id}/summary", response_model=MigrationQaResponse, responses=errors)
    async def summary(project_id: str) -> MigrationQaResponse:
        return response(lambda: service.summary(project_id))

    def add_resource(name: str) -> None:
        async def endpoint(
            project_id: str,
            page_size: Annotated[int | None, Query(ge=1)] = None,
            cursor: Annotated[str | None, Query(max_length=2048)] = None,
            code: Annotated[str | None, Query(max_length=128)] = None,
            category: Annotated[str | None, Query(max_length=64)] = None,
            state: Annotated[str | None, Query(max_length=64)] = None,
            confidence: Annotated[str | None, Query(max_length=32)] = None,
            severity: Annotated[str | None, Query(max_length=32)] = None,
            human_review: bool | None = None,
            action: Annotated[str | None, Query(max_length=128)] = None,
            search: Annotated[str | None, Query(max_length=512)] = None,
            source_search: Annotated[str | None, Query(max_length=512)] = None,
            destination_search: Annotated[str | None, Query(max_length=512)] = None,
        ) -> MigrationQaResponse:
            filters = {
                key: value
                for key, value in {
                    "code": code,
                    "category": category,
                    "state": state,
                    "confidence": confidence,
                    "severity": severity,
                    "requires_human_review": human_review,
                    "action": action,
                    "search": search,
                    "source_search": source_search,
                    "destination_search": destination_search,
                }.items()
                if value is not None
            }
            return response(
                lambda: service.list_resource(project_id, name, cursor, page_size, filters)
            )

        router.add_api_route(
            f"/{{project_id}}/{name}",
            endpoint,
            methods=["GET"],
            response_model=MigrationQaResponse,
            responses=errors,
        )

    for resource in (
        "sources",
        "redirect-map",
        "mappings",
        "redirects",
        "comparisons",
        "findings",
        "recommendations",
        "sitewide",
    ):
        add_resource(resource)

    @router.get("/{project_id}/exports", response_model=MigrationQaResponse, responses=errors)
    async def exports(project_id: str) -> MigrationQaResponse:
        return response(lambda: {"items": service.list_exports(project_id)})

    @router.post("/{project_id}/exports", response_model=MigrationQaResponse, responses=errors)
    async def export(project_id: str, request: MigrationQaExportRequest) -> MigrationQaResponse:
        return response(lambda: service.create_export(project_id, request.format))

    return router


def _api_error(error: ValueError) -> InternalApiError:
    raw = str(error)
    try:
        code = ApiErrorCode(raw)
    except ValueError:
        code = ApiErrorCode.MIGRATION_QA_QUERY_FAILED
    status = (
        404
        if raw.endswith(("run_not_found", "project_not_found"))
        else 409
        if raw.endswith(("already_terminal", "export_conflict"))
        else 400
        if any(value in raw for value in ("invalid", "missing", "mismatch", "too_large"))
        else 503
    )
    return InternalApiError(
        status, code, "The website migration QA request could not be completed."
    )
