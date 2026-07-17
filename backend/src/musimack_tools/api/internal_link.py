"""Private authenticated internal-link analysis routes."""

# ruff: noqa: C901, FBT001, PLR0913, TRY003

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from musimack_tools.api.dependencies import create_access_dependency
from musimack_tools.api.schemas import ApiErrorEnvelope, ApiSchema
from musimack_tools.domain.api import ApiErrorCode, InternalApiConfiguration, InternalApiError
from musimack_tools.domain.internal_link import (
    INTERNAL_LINK_API_VERSION,
    InternalLinkExportFormat,
)
from musimack_tools.security.correlation import current_request_id

if TYPE_CHECKING:
    from collections.abc import Callable

    from musimack_tools.internal_link.service import InternalLinkAuditService


class InternalLinkCreateRequest(ApiSchema):
    run_id: str = Field(min_length=1, max_length=64)


class InternalLinkExportRequest(ApiSchema):
    format: InternalLinkExportFormat


class InternalLinkResponse(ApiSchema):
    internal_link_api_version: str = INTERNAL_LINK_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: Any


def create_internal_link_router(
    service: InternalLinkAuditService, configuration: InternalApiConfiguration
) -> APIRouter:
    """Create the opt-in internal-link router."""
    if not service.configuration.enabled:
        raise ValueError("internal-link routes require enabled configuration")
    include = (
        configuration.include_internal_routes_in_schema
        and configuration.include_internal_endpoints_in_docs
    )
    router = APIRouter(
        prefix=f"{configuration.route_prefix}/audits/internal-links",
        dependencies=[Depends(create_access_dependency(configuration))],
        include_in_schema=include,
    )
    errors: dict[int | str, dict[str, Any]] = {
        code: {"model": ApiErrorEnvelope} for code in (400, 401, 403, 404, 409, 503)
    }

    @router.get("/evidence/{run_id}", response_model=InternalLinkResponse, responses=errors)
    async def evidence(run_id: str) -> InternalLinkResponse:
        return _response(lambda: service.evidence_status(run_id))

    @router.post("", response_model=InternalLinkResponse, responses=errors)
    async def create(request: InternalLinkCreateRequest) -> InternalLinkResponse:
        return _response(lambda: service.create_audit(request.run_id))

    @router.get("", response_model=InternalLinkResponse, responses=errors)
    async def audits(
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
    ) -> InternalLinkResponse:
        return _response(lambda: service.list_audits(cursor, page_size))

    @router.post("/{audit_id}/execute", response_model=InternalLinkResponse, responses=errors)
    async def execute(audit_id: str) -> InternalLinkResponse:
        try:
            return InternalLinkResponse(data=await service.execute_audit(audit_id))
        except ValueError as error:
            raise _api_error(error) from None

    @router.get("/{audit_id}", response_model=InternalLinkResponse, responses=errors)
    async def detail(audit_id: str) -> InternalLinkResponse:
        return _response(lambda: service.get(audit_id))

    @router.get("/{audit_id}/summary", response_model=InternalLinkResponse, responses=errors)
    async def summary(audit_id: str) -> InternalLinkResponse:
        return _response(lambda: service.summary(audit_id))

    def add_page_route(path: str, loader: Callable[..., dict[str, Any]]) -> None:
        async def endpoint(
            audit_id: str,
            page_size: Annotated[int | None, Query(ge=1)] = None,
            cursor: Annotated[str | None, Query(max_length=2048)] = None,
            eligibility: Annotated[str | None, Query(max_length=48)] = None,
            primary_state: Annotated[str | None, Query(max_length=48)] = None,
            reachable: bool | None = None,
            orphan_state: Annotated[str | None, Query(max_length=48)] = None,
            hub_state: Annotated[str | None, Query(max_length=48)] = None,
            authority_state: Annotated[str | None, Query(max_length=48)] = None,
            minimum_inlinks: Annotated[int | None, Query(ge=0)] = None,
            maximum_inlinks: Annotated[int | None, Query(ge=0)] = None,
            minimum_outlinks: Annotated[int | None, Query(ge=0)] = None,
            maximum_outlinks: Annotated[int | None, Query(ge=0)] = None,
            minimum_graph_depth: Annotated[int | None, Query(ge=0)] = None,
            severity: Annotated[str | None, Query(max_length=16)] = None,
            url: Annotated[str | None, Query(max_length=512)] = None,
            source: Annotated[str | None, Query(max_length=512)] = None,
            target: Annotated[str | None, Query(max_length=512)] = None,
            nofollow: bool | None = None,
            redirect_adjusted: bool | None = None,
            canonical_adjusted: bool | None = None,
            sitewide: bool | None = None,
            state: Annotated[str | None, Query(max_length=48)] = None,
            opportunity_type: Annotated[str | None, Query(alias="type", max_length=48)] = None,
            action: Annotated[str | None, Query(max_length=48)] = None,
            confidence: Annotated[str | None, Query(max_length=16)] = None,
            human_review: bool | None = None,
        ) -> InternalLinkResponse:
            filters = {
                key: value
                for key, value in {
                    "eligibility": eligibility,
                    "state": primary_state or state,
                    "reachable": reachable,
                    "orphan": orphan_state,
                    "hub": hub_state,
                    "authority": authority_state,
                    "min_inlinks": minimum_inlinks,
                    "max_inlinks": maximum_inlinks,
                    "min_outlinks": minimum_outlinks,
                    "max_outlinks": maximum_outlinks,
                    "min_depth": minimum_graph_depth,
                    "severity": severity,
                    "url": url,
                    "source": source,
                    "target": target,
                    "nofollow": nofollow,
                    "redirect_adjusted": redirect_adjusted,
                    "canonical_adjusted": canonical_adjusted,
                    "sitewide": sitewide,
                    "type": opportunity_type,
                    "action": action,
                    "confidence": confidence,
                    "review": human_review,
                }.items()
                if value is not None
            }
            if path in {"pages", "edges", "anchors", "opportunities"}:
                return _response(lambda: loader(audit_id, cursor, page_size, filters))
            return _response(lambda: loader(audit_id, cursor, page_size))

        router.add_api_route(
            f"/{{audit_id}}/{path}",
            endpoint,
            methods=["GET"],
            response_model=InternalLinkResponse,
            responses=errors,
        )

    for path, loader in (
        ("pages", service.list_pages),
        ("edges", service.list_edges),
        ("orphans", service.list_orphans),
        ("hubs", service.list_hubs),
        ("authorities", service.list_authorities),
        ("reachability", service.list_reachability),
        ("findings", service.list_findings),
        ("anchors", service.list_anchors),
        ("opportunities", service.list_opportunities),
    ):
        add_page_route(path, loader)

    @router.post("/{audit_id}/exports", response_model=InternalLinkResponse, responses=errors)
    async def export(audit_id: str, request: InternalLinkExportRequest) -> InternalLinkResponse:
        return _response(lambda: service.create_export(audit_id, request.format))

    @router.get("/{audit_id}/exports", response_model=InternalLinkResponse, responses=errors)
    async def exports(audit_id: str) -> InternalLinkResponse:
        return _response(lambda: {"items": service.list_exports(audit_id)})

    return router


def _response(factory: Callable[[], Any]) -> InternalLinkResponse:
    try:
        return InternalLinkResponse(data=factory())
    except ValueError as error:
        raise _api_error(error) from None


def _api_error(error: ValueError) -> InternalApiError:
    raw = str(error)
    try:
        code = ApiErrorCode(raw)
    except ValueError:
        code = ApiErrorCode.INTERNAL_LINK_QUERY_FAILED
    status = (
        404
        if raw in {"internal_link_run_not_found", "internal_link_audit_not_found"}
        else 409
        if raw.endswith(("already_exists", "already_executing", "already_terminal", "conflict"))
        or raw == "internal_link_run_not_terminal"
        else 400
        if "invalid" in raw or "unsupported" in raw
        else 503
    )
    return InternalApiError(status, code, "The internal-link request could not be completed.")
