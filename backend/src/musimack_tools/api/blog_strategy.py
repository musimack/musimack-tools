"""Private authenticated BS-01 API routes."""

# ruff: noqa: ANN401, C901 - FastAPI handlers deliberately use bounded dynamic envelopes.

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import Field

from musimack_tools.api.dependencies import create_access_dependency
from musimack_tools.api.schemas import ApiErrorEnvelope, ApiSchema
from musimack_tools.domain.api import ApiErrorCode, InternalApiConfiguration, InternalApiError
from musimack_tools.security.correlation import current_request_id


class Body(ApiSchema):
    data: dict[str, Any] = Field(default_factory=dict)
    revision: int | None = Field(default=None, ge=1)


class BlogStrategyResponse(ApiSchema):
    blog_strategy_version: str = "blog-strategy-bs01-v1"
    request_id: str | None = Field(default_factory=current_request_id)
    data: Any


def create_blog_strategy_router(service: Any, configuration: InternalApiConfiguration) -> APIRouter:
    include = (
        configuration.include_internal_routes_in_schema
        and configuration.include_internal_endpoints_in_docs
    )
    router = APIRouter(
        prefix=f"{configuration.route_prefix}/blog-strategy",
        dependencies=[Depends(create_access_dependency(configuration))],
        include_in_schema=include,
    )
    errors: dict[int | str, dict[str, Any]] = {
        code: {"model": ApiErrorEnvelope} for code in (400, 401, 403, 404, 409, 503)
    }

    @router.get("/projects", response_model=BlogStrategyResponse, responses=errors)
    async def projects() -> BlogStrategyResponse:
        return BlogStrategyResponse(data=service.repository.projects())

    @router.post("/projects", response_model=BlogStrategyResponse, responses=errors)
    async def create_project(body: Body, request: Request) -> BlogStrategyResponse:
        return _response(lambda: service.create_project(body.data, _actor(request)))

    @router.get("/projects/{project_id}", response_model=BlogStrategyResponse, responses=errors)
    async def project(project_id: str) -> BlogStrategyResponse:
        return _response(lambda: service.repository.project(project_id))

    @router.patch("/projects/{project_id}", response_model=BlogStrategyResponse, responses=errors)
    async def update_project(project_id: str, body: Body, request: Request) -> BlogStrategyResponse:
        return _response(
            lambda: service.update_project(project_id, body.data, _revision(body), _actor(request))
        )

    @router.get(
        "/projects/{project_id}/pages", response_model=BlogStrategyResponse, responses=errors
    )
    async def pages(project_id: str) -> BlogStrategyResponse:
        return _response(lambda: service.repository.pages(project_id))

    @router.post(
        "/projects/{project_id}/pages", response_model=BlogStrategyResponse, responses=errors
    )
    async def add_page(project_id: str, body: Body, request: Request) -> BlogStrategyResponse:
        return _response(lambda: service.add_page(project_id, body.data, _actor(request)))

    @router.patch(
        "/projects/{project_id}/pages/{page_id}",
        response_model=BlogStrategyResponse,
        responses=errors,
    )
    async def update_page(
        project_id: str, page_id: str, body: Body, request: Request
    ) -> BlogStrategyResponse:
        if "approved" in body.data:
            raise _api_error(ValueError("blog_strategy_approval_endpoint_required"))
        return _response(
            lambda: service.update_page(
                project_id, page_id, body.data, _revision(body), _actor(request)
            )
        )

    @router.post(
        "/projects/{project_id}/pages/{page_id}/approve",
        response_model=BlogStrategyResponse,
        responses=errors,
    )
    async def approve_page(
        project_id: str, page_id: str, body: Body, request: Request
    ) -> BlogStrategyResponse:
        return _response(
            lambda: service.update_page(
                project_id,
                page_id,
                {"approved": bool(body.data.get("approved", True))},
                _revision(body),
                _actor(request),
            )
        )

    @router.post(
        "/projects/{project_id}/import-preview",
        response_model=BlogStrategyResponse,
        responses=errors,
    )
    async def preview(project_id: str, body: Body) -> BlogStrategyResponse:
        service.repository.project(project_id)
        return _response(
            lambda: [asdict(item) for item in service.preview_import(body.data["source_reference"])]
        )

    @router.post(
        "/projects/{project_id}/import", response_model=BlogStrategyResponse, responses=errors
    )
    async def import_pages(project_id: str, body: Body, request: Request) -> BlogStrategyResponse:
        return _response(
            lambda: asdict(
                service.import_pages(
                    project_id,
                    body.data["source_reference"],
                    body.data["selected_urls"],
                    _actor(request),
                )
            )
        )

    @router.get(
        "/projects/{project_id}/topic-families",
        response_model=BlogStrategyResponse,
        responses=errors,
    )
    async def families(project_id: str) -> BlogStrategyResponse:
        return _response(lambda: service.repository.families(project_id))

    @router.post(
        "/projects/{project_id}/topic-families",
        response_model=BlogStrategyResponse,
        responses=errors,
    )
    async def create_family(project_id: str, body: Body, request: Request) -> BlogStrategyResponse:
        return _response(lambda: service.create_family(project_id, body.data, _actor(request)))

    @router.patch(
        "/projects/{project_id}/topic-families/{family_id}",
        response_model=BlogStrategyResponse,
        responses=errors,
    )
    async def update_family(
        project_id: str, family_id: str, body: Body, request: Request
    ) -> BlogStrategyResponse:
        return _response(
            lambda: service.update_family(
                project_id, family_id, body.data, _revision(body), _actor(request)
            )
        )

    @router.post(
        "/projects/{project_id}/topic-families/{family_id}/merge",
        response_model=BlogStrategyResponse,
        responses=errors,
    )
    async def merge_family(
        project_id: str, family_id: str, body: Body, request: Request
    ) -> BlogStrategyResponse:
        return _response(
            lambda: service.repository.merge_family(
                project_id,
                family_id,
                body.data["destination_family_id"],
                _revision(body),
                _actor(request),
            )
        )

    @router.get(
        "/projects/{project_id}/overlaps", response_model=BlogStrategyResponse, responses=errors
    )
    async def overlaps(project_id: str) -> BlogStrategyResponse:
        return _response(lambda: service.repository.overlaps(project_id))

    @router.post(
        "/projects/{project_id}/overlaps", response_model=BlogStrategyResponse, responses=errors
    )
    async def create_overlap(project_id: str, body: Body, request: Request) -> BlogStrategyResponse:
        return _response(lambda: service.create_overlap(project_id, body.data, _actor(request)))

    @router.patch(
        "/projects/{project_id}/overlaps/{overlap_id}",
        response_model=BlogStrategyResponse,
        responses=errors,
    )
    async def update_overlap(
        project_id: str, overlap_id: str, body: Body, request: Request
    ) -> BlogStrategyResponse:
        return _response(
            lambda: service.update_overlap(
                project_id, overlap_id, body.data, _revision(body), _actor(request)
            )
        )

    @router.get(
        "/projects/{project_id}/readiness", response_model=BlogStrategyResponse, responses=errors
    )
    async def readiness(project_id: str) -> BlogStrategyResponse:
        return _response(lambda: asdict(service.readiness(project_id)))

    @router.post("/projects/{project_id}/export", responses=errors)
    async def export(project_id: str, body: Body) -> Response:
        try:
            filename, payload, _validation = service.export(
                project_id, acknowledge_warnings=bool(body.data.get("acknowledge_warnings"))
            )
        except (KeyError, TypeError, ValueError) as error:
            raise _api_error(error) from None
        return Response(
            payload,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router


def _revision(body: Body) -> int:
    if body.revision is None:
        raise _api_error(ValueError("blog_strategy_revision_required"))
    return body.revision


def _actor(request: Request) -> str | None:
    principal = getattr(request.state, "authenticated_principal", None)
    return getattr(principal, "user_id", None) or getattr(principal, "email", None)


def _response(factory: Any) -> BlogStrategyResponse:
    try:
        return BlogStrategyResponse(data=factory())
    except (KeyError, TypeError, ValueError) as error:
        raise _api_error(error) from None


def _api_error(error: Exception) -> InternalApiError:
    raw = str(error)
    if raw.endswith("not_found"):
        return InternalApiError(
            404, ApiErrorCode.BLOG_STRATEGY_NOT_FOUND, "The Blog Strategy record was not found."
        )
    if raw.endswith(("conflict", "duplicate_url")) or "transition" in raw:
        return InternalApiError(
            409,
            ApiErrorCode.BLOG_STRATEGY_CONFLICT,
            "The Blog Strategy request conflicts with current state.",
        )
    if "unavailable" in raw:
        return InternalApiError(
            503,
            ApiErrorCode.BLOG_STRATEGY_UNAVAILABLE,
            "The requested evidence provider is unavailable.",
        )
    return InternalApiError(
        400, ApiErrorCode.BLOG_STRATEGY_INVALID, "The Blog Strategy request is invalid."
    )
