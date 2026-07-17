"""Private authenticated link-audit routes."""

# ruff: noqa: ANN401, C901, FBT001, PLR0913, TRY003

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from musimack_tools.api.dependencies import create_access_dependency
from musimack_tools.api.schemas import ApiErrorEnvelope, ApiSchema
from musimack_tools.domain.api import ApiErrorCode, InternalApiConfiguration, InternalApiError
from musimack_tools.domain.link_audit import (
    AUDIT_ORDERING,
    CHAIN_ORDERING,
    FINDING_ORDERING,
    LINK_AUDIT_API_VERSION,
    OCCURRENCE_ORDERING,
    RECOMMENDATION_ORDERING,
    TARGET_ORDERING,
    BrokenLinkReason,
    BrokenLinkState,
    Confidence,
    ExportFormat,
    RecommendationAction,
    RedirectState,
    Severity,
    decode_cursor,
    encode_cursor,
    filter_fingerprint,
)
from musimack_tools.security.correlation import current_request_id

if TYPE_CHECKING:
    from musimack_tools.link_audit.service import LinkAuditService


class LinkAuditCreateRequest(ApiSchema):
    run_id: str = Field(min_length=1, max_length=64)


class LinkAuditExportRequest(ApiSchema):
    format: ExportFormat


class LinkAuditResponse(ApiSchema):
    link_audit_api_version: str = LINK_AUDIT_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: Any


def create_link_audit_router(
    service: LinkAuditService, configuration: InternalApiConfiguration
) -> APIRouter:
    if not service.configuration.enabled:
        raise ValueError("link audit routes require enabled configuration")
    include = (
        configuration.include_internal_routes_in_schema
        and configuration.include_internal_endpoints_in_docs
    )
    router = APIRouter(
        prefix=f"{configuration.route_prefix}/audits/links",
        dependencies=[Depends(create_access_dependency(configuration))],
        include_in_schema=include,
    )
    errors: dict[int | str, dict[str, Any]] = {
        code: {"model": ApiErrorEnvelope} for code in (400, 401, 403, 404, 409, 503)
    }

    @router.get("/evidence/{run_id}", response_model=LinkAuditResponse, responses=errors)
    async def evidence(run_id: str) -> LinkAuditResponse:
        return _response(lambda: service.evidence_status(run_id))

    @router.post("", response_model=LinkAuditResponse, responses=errors)
    async def create(request: LinkAuditCreateRequest) -> LinkAuditResponse:
        return _response(lambda: service.create_audit(request.run_id))

    @router.get("", response_model=LinkAuditResponse, responses=errors)
    async def audits(
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
    ) -> LinkAuditResponse:
        return _page_call(service, "audits", AUDIT_ORDERING, page_size, cursor, service.list_audits)

    @router.post("/{audit_id}/execute", response_model=LinkAuditResponse, responses=errors)
    async def execute(audit_id: str) -> LinkAuditResponse:
        try:
            return LinkAuditResponse(data=await service.execute_audit(audit_id))
        except ValueError as error:
            raise _api_error(error) from None

    @router.get("/{audit_id}", response_model=LinkAuditResponse, responses=errors)
    async def detail(audit_id: str) -> LinkAuditResponse:
        return _response(lambda: service.get(audit_id))

    @router.get("/{audit_id}/summary", response_model=LinkAuditResponse, responses=errors)
    async def summary(audit_id: str) -> LinkAuditResponse:
        return _response(lambda: service.summary(audit_id))

    @router.get("/{audit_id}/targets", response_model=LinkAuditResponse, responses=errors)
    async def targets(
        audit_id: str,
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
        broken_state: BrokenLinkState | None = None,
        redirect_state: RedirectState | None = None,
        severity: Severity | None = None,
        action: RecommendationAction | None = None,
        reason: BrokenLinkReason | None = None,
        http_status: Annotated[int | None, Query(ge=100, le=599)] = None,
        status_class: Annotated[int | None, Query(ge=1, le=5)] = None,
        content_type: Annotated[str | None, Query(max_length=128)] = None,
        in_scope: bool | None = None,
        sitewide: bool | None = None,
        minimum_sources: Annotated[int | None, Query(ge=1)] = None,
        url: Annotated[str | None, Query(max_length=512)] = None,
    ) -> LinkAuditResponse:
        filters = _filters(locals(), "audit_id", "page_size", "cursor")
        return _resource_page(
            service,
            audit_id,
            "targets",
            TARGET_ORDERING,
            page_size,
            cursor,
            service.list_targets,
            filters,
        )

    @router.get("/{audit_id}/occurrences", response_model=LinkAuditResponse, responses=errors)
    async def occurrences(
        audit_id: str,
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
        source: Annotated[str | None, Query(max_length=512)] = None,
        target: Annotated[str | None, Query(max_length=512)] = None,
        anchor: Annotated[str | None, Query(max_length=512)] = None,
        source_page: Annotated[str | None, Query(max_length=64)] = None,
        target_state: BrokenLinkState | None = None,
        internal: bool | None = None,
        nofollow: bool | None = None,
    ) -> LinkAuditResponse:
        filters = _filters(locals(), "audit_id", "page_size", "cursor")
        return _resource_page(
            service,
            audit_id,
            "occurrences",
            OCCURRENCE_ORDERING,
            page_size,
            cursor,
            service.list_occurrences,
            filters,
        )

    @router.get("/{audit_id}/chains", response_model=LinkAuditResponse, responses=errors)
    async def chains(
        audit_id: str,
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
        loop: bool | None = None,
        severity: Severity | None = None,
        minimum_hops: Annotated[int | None, Query(ge=1)] = None,
        final_status: Annotated[int | None, Query(ge=100, le=599)] = None,
        entry: Annotated[str | None, Query(max_length=512)] = None,
        destination: Annotated[str | None, Query(max_length=512)] = None,
    ) -> LinkAuditResponse:
        filters = _filters(locals(), "audit_id", "page_size", "cursor")
        return _resource_page(
            service,
            audit_id,
            "chains",
            CHAIN_ORDERING,
            page_size,
            cursor,
            service.list_chains,
            filters,
        )

    @router.get("/{audit_id}/loops", response_model=LinkAuditResponse, responses=errors)
    async def loops(
        audit_id: str,
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
    ) -> LinkAuditResponse:
        return _resource_page(
            service,
            audit_id,
            "loops",
            CHAIN_ORDERING,
            page_size,
            cursor,
            service.list_chains,
            {"loop": True},
        )

    @router.get("/{audit_id}/findings", response_model=LinkAuditResponse, responses=errors)
    async def findings(
        audit_id: str,
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
        severity: Severity | None = None,
        code: Annotated[str | None, Query(max_length=64)] = None,
    ) -> LinkAuditResponse:
        filters = _filters(locals(), "audit_id", "page_size", "cursor")
        return _resource_page(
            service,
            audit_id,
            "findings",
            FINDING_ORDERING,
            page_size,
            cursor,
            service.list_findings,
            filters,
        )

    @router.get("/{audit_id}/recommendations", response_model=LinkAuditResponse, responses=errors)
    async def recommendations(
        audit_id: str,
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
        action: RecommendationAction | None = None,
        confidence: Confidence | None = None,
        severity: Severity | None = None,
        human_review: bool | None = None,
        source: Annotated[str | None, Query(max_length=512)] = None,
        destination: Annotated[str | None, Query(max_length=512)] = None,
    ) -> LinkAuditResponse:
        filters = _filters(locals(), "audit_id", "page_size", "cursor")
        return _resource_page(
            service,
            audit_id,
            "recommendations",
            RECOMMENDATION_ORDERING,
            page_size,
            cursor,
            service.list_recommendations,
            filters,
        )

    @router.post("/{audit_id}/exports", response_model=LinkAuditResponse, responses=errors)
    async def export(audit_id: str, request: LinkAuditExportRequest) -> LinkAuditResponse:
        return _response(lambda: service.create_export(audit_id, request.format))

    @router.get("/{audit_id}/exports", response_model=LinkAuditResponse, responses=errors)
    async def exports(audit_id: str) -> LinkAuditResponse:
        return _response(lambda: {"items": service.list_exports(audit_id)})

    return router


def _filters(values: dict[str, Any], *excluded: str) -> dict[str, Any]:
    return {
        key: value.value if hasattr(value, "value") else value
        for key, value in values.items()
        if key not in {*excluded, "service"} and value is not None
    }


def _page_call(
    service: LinkAuditService,
    kind: str,
    ordering: str,
    page_size: int | None,
    cursor: str | None,
    factory: Any,
) -> LinkAuditResponse:
    try:
        size = page_size or service.configuration.default_page_size
        offset = _offset(cursor, kind, ordering, {})
        return _page(factory(offset, size), offset, size, kind, ordering, {})
    except ValueError as error:
        raise _api_error(error) from None


def _resource_page(
    service: LinkAuditService,
    audit_id: str,
    kind: str,
    ordering: str,
    page_size: int | None,
    cursor: str | None,
    factory: Any,
    filters: dict[str, Any],
) -> LinkAuditResponse:
    try:
        size = page_size or service.configuration.default_page_size
        offset = _offset(cursor, kind, ordering, filters)
        return _page(
            factory(audit_id, offset, size, filters),
            offset,
            size,
            kind,
            ordering,
            filters,
        )
    except ValueError as error:
        raise _api_error(error) from None


def _page(
    items: Any,
    offset: int,
    size: int,
    kind: str,
    ordering: str,
    filters: dict[str, Any],
) -> LinkAuditResponse:
    values = list(items)
    fingerprint = filter_fingerprint(filters)
    next_cursor = (
        encode_cursor(kind, ordering, fingerprint, offset + len(values))
        if len(values) == size
        else None
    )
    return LinkAuditResponse(
        data={
            "items": values,
            "page_size": size,
            "returned_count": len(values),
            "next_cursor": next_cursor,
            "ordering": ordering,
            "filters": filters,
        }
    )


def _offset(cursor: str | None, kind: str, ordering: str, filters: dict[str, Any]) -> int:
    if cursor is None:
        return 0
    try:
        return decode_cursor(cursor, kind, ordering, filter_fingerprint(filters))
    except ValueError as error:
        raise _api_error(error) from None


def _response(factory: Any) -> LinkAuditResponse:
    try:
        return LinkAuditResponse(data=factory())
    except ValueError as error:
        raise _api_error(error) from None


def _api_error(error: ValueError) -> InternalApiError:
    raw = str(error)
    try:
        code = ApiErrorCode(raw)
    except ValueError:
        code = ApiErrorCode.LINK_AUDIT_QUERY_FAILED
    status = (
        404
        if raw in {"link_audit_run_not_found", "link_audit_not_found"}
        else 409
        if raw
        in {
            "link_audit_run_not_terminal",
            "link_audit_already_exists",
            "link_audit_already_executing",
            "link_audit_already_terminal",
            "link_audit_export_conflict",
            "link_audit_version_unsupported",
        }
        else 400
        if raw
        in {
            "link_audit_invalid_filter",
            "link_audit_invalid_page_size",
            "link_audit_invalid_cursor",
            "link_audit_cursor_version_unsupported",
            "link_audit_cursor_filter_mismatch",
            "link_audit_export_unsupported",
        }
        else 503
    )
    return InternalApiError(status, code, "The link audit request could not be completed.")
