"""Private authenticated image and alt-text audit routes."""

# ruff: noqa: C901, FBT001, PLR0913, TRY003

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from musimack_tools.api.dependencies import create_access_dependency
from musimack_tools.api.schemas import ApiErrorEnvelope, ApiSchema
from musimack_tools.domain.api import ApiErrorCode, InternalApiConfiguration, InternalApiError
from musimack_tools.domain.image_audit import IMAGE_API_VERSION, ImageExportFormat
from musimack_tools.security.correlation import current_request_id

if TYPE_CHECKING:
    from collections.abc import Callable

    from musimack_tools.image_audit.service import ImageAuditService


class ImageAuditCreateRequest(ApiSchema):
    run_id: str = Field(min_length=1, max_length=64)


class ImageAuditExportRequest(ApiSchema):
    format: ImageExportFormat


class ImageAuditResponse(ApiSchema):
    image_api_version: str = IMAGE_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: Any


def create_image_audit_router(
    service: ImageAuditService, configuration: InternalApiConfiguration
) -> APIRouter:
    if not service.configuration.enabled:
        raise ValueError("image-audit routes require enabled configuration")
    include = (
        configuration.include_internal_routes_in_schema
        and configuration.include_internal_endpoints_in_docs
    )
    router = APIRouter(
        prefix=f"{configuration.route_prefix}/audits/images",
        dependencies=[Depends(create_access_dependency(configuration))],
        include_in_schema=include,
    )
    errors: dict[int | str, dict[str, Any]] = {
        code: {"model": ApiErrorEnvelope} for code in (400, 401, 403, 404, 409, 503)
    }

    @router.get("/evidence/{run_id}", response_model=ImageAuditResponse, responses=errors)
    async def evidence(run_id: str) -> ImageAuditResponse:
        return _response(lambda: service.evidence_status(run_id))

    @router.post("", response_model=ImageAuditResponse, responses=errors)
    async def create(request: ImageAuditCreateRequest) -> ImageAuditResponse:
        return _response(lambda: service.create_audit(request.run_id))

    @router.get("", response_model=ImageAuditResponse, responses=errors)
    async def audits(
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
    ) -> ImageAuditResponse:
        return _response(lambda: service.list_audits(cursor, page_size))

    @router.post("/{audit_id}/execute", response_model=ImageAuditResponse, responses=errors)
    async def execute(audit_id: str) -> ImageAuditResponse:
        try:
            return ImageAuditResponse(data=await service.execute_audit(audit_id))
        except ValueError as error:
            raise _api_error(error) from None

    @router.get("/{audit_id}", response_model=ImageAuditResponse, responses=errors)
    async def detail(audit_id: str) -> ImageAuditResponse:
        return _response(lambda: service.get(audit_id))

    @router.get("/{audit_id}/summary", response_model=ImageAuditResponse, responses=errors)
    async def summary(audit_id: str) -> ImageAuditResponse:
        return _response(lambda: service.summary(audit_id))

    def add_list_route(path: str, loader: Callable[..., dict[str, Any]]) -> None:
        async def endpoint(
            audit_id: str,
            page_size: Annotated[int | None, Query(ge=1)] = None,
            cursor: Annotated[str | None, Query(max_length=2048)] = None,
            resource_state: Annotated[str | None, Query(max_length=48)] = None,
            http_status: Annotated[int | None, Query(ge=100, le=599)] = None,
            status_class: Annotated[int | None, Query(ge=1, le=5)] = None,
            content_type: Annotated[str | None, Query(max_length=256)] = None,
            redirect_state: Annotated[str | None, Query(max_length=32)] = None,
            scope_state: Annotated[str | None, Query(max_length=32)] = None,
            sitewide_state: Annotated[str | None, Query(max_length=32)] = None,
            alt_state: Annotated[str | None, Query(max_length=48)] = None,
            dimension_state: Annotated[str | None, Query(max_length=40)] = None,
            loading_state: Annotated[str | None, Query(max_length=40)] = None,
            linked_image: bool | None = None,
            decorative: bool | None = None,
            severity: Annotated[str | None, Query(max_length=16)] = None,
            group_type: Annotated[str | None, Query(max_length=48)] = None,
            action: Annotated[str | None, Query(max_length=48)] = None,
            confidence: Annotated[str | None, Query(max_length=16)] = None,
            human_review_state: Annotated[str | None, Query(max_length=32)] = None,
            source_page: Annotated[str | None, Query(max_length=512)] = None,
            url_search: Annotated[str | None, Query(alias="url", max_length=512)] = None,
            alt_search: Annotated[str | None, Query(alias="alt", max_length=1024)] = None,
            minimum_source_page_count: Annotated[int | None, Query(ge=1)] = None,
            minimum_image_count: Annotated[int | None, Query(ge=1)] = None,
        ) -> ImageAuditResponse:
            filters = {
                key: value
                for key, value in {
                    "resource_state": resource_state,
                    "http_status": http_status,
                    "status_class": status_class,
                    "content_type": content_type,
                    "redirect_state": redirect_state,
                    "scope_state": scope_state,
                    "sitewide_state": sitewide_state,
                    "alt_state": alt_state,
                    "dimension_state": dimension_state,
                    "loading_state": loading_state,
                    "linked_image": linked_image,
                    "decorative": decorative,
                    "severity": severity,
                    "group_type": group_type,
                    "action": action,
                    "confidence": confidence,
                    "human_review_state": human_review_state,
                    "source_page": source_page,
                    "url_search": url_search,
                    "alt_search": alt_search,
                    "minimum_source_page_count": minimum_source_page_count,
                    "minimum_image_count": minimum_image_count,
                }.items()
                if value is not None
            }
            return _response(lambda: loader(audit_id, cursor, page_size, filters))

        router.add_api_route(
            f"/{{audit_id}}/{path}",
            endpoint,
            methods=["GET"],
            response_model=ImageAuditResponse,
            responses=errors,
        )

    for path, loader in (
        ("resources", service.list_resources),
        ("occurrences", service.list_occurrences),
        ("pages", service.list_pages),
        ("duplicate-groups", service.list_groups),
        ("recommendations", service.list_recommendations),
    ):
        add_list_route(path, loader)

    def add_simple_route(
        path: str, loader: Callable[..., dict[str, Any]], kind: str | None = None
    ) -> None:
        async def endpoint(
            audit_id: str,
            page_size: Annotated[int | None, Query(ge=1)] = None,
            cursor: Annotated[str | None, Query(max_length=2048)] = None,
        ) -> ImageAuditResponse:
            return _response(
                lambda: (
                    loader(audit_id, kind, cursor, page_size)
                    if kind
                    else loader(audit_id, cursor, page_size)
                )
            )

        router.add_api_route(
            f"/{{audit_id}}/{path}",
            endpoint,
            methods=["GET"],
            response_model=ImageAuditResponse,
            responses=errors,
        )

    add_simple_route("broken", service.list_broken)
    add_simple_route("redirecting", service.list_redirecting)
    for path, kind in (
        ("alt-findings", "alt"),
        ("dimensions", "dimension"),
        ("loading", "loading"),
    ):
        add_simple_route(path, service.list_findings, kind)

    @router.post("/{audit_id}/exports", response_model=ImageAuditResponse, responses=errors)
    async def export(audit_id: str, request: ImageAuditExportRequest) -> ImageAuditResponse:
        return _response(lambda: service.create_export(audit_id, request.format))

    @router.get("/{audit_id}/exports", response_model=ImageAuditResponse, responses=errors)
    async def exports(audit_id: str) -> ImageAuditResponse:
        return _response(lambda: {"items": service.list_exports(audit_id)})

    return router


def _response(factory: Callable[[], Any]) -> ImageAuditResponse:
    try:
        return ImageAuditResponse(data=factory())
    except ValueError as error:
        raise _api_error(error) from None


def _api_error(error: ValueError) -> InternalApiError:
    raw = str(error)
    try:
        code = ApiErrorCode(raw)
    except ValueError:
        code = ApiErrorCode.IMAGE_AUDIT_QUERY_FAILED
    status = (
        404
        if raw in {"image_audit_run_not_found", "image_audit_not_found"}
        else 409
        if raw.endswith(("already_exists", "already_executing", "already_terminal", "conflict"))
        or raw == "image_audit_run_not_terminal"
        else 400
        if "invalid" in raw or "unsupported" in raw or raw.endswith("filter_mismatch")
        else 503
    )
    return InternalApiError(status, code, "The image-audit request could not be completed.")
