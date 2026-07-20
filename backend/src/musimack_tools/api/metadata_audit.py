"""Private authenticated metadata-audit API routes."""

# ruff: noqa: ANN401, C901, FBT001, PLR0913, TRY003 - FastAPI query signatures are contracts.

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from musimack_tools.api.dependencies import create_access_dependency
from musimack_tools.api.schemas import ApiErrorEnvelope, ApiSchema
from musimack_tools.domain.api import ApiErrorCode, InternalApiConfiguration, InternalApiError
from musimack_tools.domain.metadata_audit import (
    AUDIT_ORDERING,
    DUPLICATE_ORDERING,
    ISSUE_ORDERING,
    METADATA_AUDIT_API_VERSION,
    PAGE_ORDERING,
    ExportFormat,
    decode_cursor,
    encode_cursor,
    filter_fingerprint,
)
from musimack_tools.security.correlation import current_request_id

if TYPE_CHECKING:
    from musimack_tools.metadata_audit.service import MetadataAuditService


class MetadataAuditCreateRequest(ApiSchema):
    run_id: str = Field(min_length=1, max_length=64)


class MetadataAuditExportRequest(ApiSchema):
    format: ExportFormat


class MetadataAuditResponse(ApiSchema):
    metadata_audit_api_version: str = METADATA_AUDIT_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: Any


def create_metadata_audit_router(
    service: MetadataAuditService, configuration: InternalApiConfiguration
) -> APIRouter:
    if not service.configuration.enabled:
        raise ValueError("metadata audit routes require enabled configuration")
    include = (
        configuration.include_internal_routes_in_schema
        and configuration.include_internal_endpoints_in_docs
    )
    router = APIRouter(
        prefix=f"{configuration.route_prefix}/audits/metadata",
        dependencies=[Depends(create_access_dependency(configuration))],
        include_in_schema=include,
    )
    errors: dict[int | str, dict[str, Any]] = {
        code: {"model": ApiErrorEnvelope} for code in (400, 401, 403, 404, 409, 503)
    }

    @router.post("", response_model=MetadataAuditResponse, responses=errors)
    async def create(request: MetadataAuditCreateRequest) -> MetadataAuditResponse:
        return _response(lambda: asdict(service.create_and_run_audit(request.run_id)))

    @router.get("", response_model=MetadataAuditResponse, responses=errors)
    async def audits(
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
    ) -> MetadataAuditResponse:
        size = page_size or service.configuration.default_page_size
        offset = _offset(cursor, "audits", AUDIT_ORDERING, {})
        items = service.list_audits(offset=offset, page_size=size)
        return _page_response(items, offset, size, "audits", AUDIT_ORDERING, {})

    @router.get("/run-candidates", response_model=MetadataAuditResponse, responses=errors)
    async def run_candidates(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> MetadataAuditResponse:
        return _response(lambda: [asdict(item) for item in service.run_candidates(limit=limit)])

    @router.get("/{audit_id}", response_model=MetadataAuditResponse, responses=errors)
    async def detail(audit_id: str) -> MetadataAuditResponse:
        return _response(lambda: asdict(service.get_audit(audit_id)))

    @router.get("/{audit_id}/summary", response_model=MetadataAuditResponse, responses=errors)
    async def summary(audit_id: str) -> MetadataAuditResponse:
        return _response(lambda: service.get_summary(audit_id))

    @router.get("/{audit_id}/pages", response_model=MetadataAuditResponse, responses=errors)
    async def pages(
        audit_id: str,
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
        url: Annotated[str | None, Query(max_length=512)] = None,
        highest_severity: str | None = None,
        has_issues: bool | None = None,
        status: int | None = None,
        status_class: int | None = None,
        content_type: str | None = None,
        indexability: str | None = None,
        robots_allowed: bool | None = None,
        recommendation: str | None = None,
        canonical: str | None = None,
        partial: bool | None = None,
    ) -> MetadataAuditResponse:
        filters = {
            "url": url,
            "highest_severity": highest_severity,
            "has_issues": has_issues,
            "status": status,
            "status_class": status_class,
            "content_type": content_type,
            "indexability": indexability,
            "robots_allowed": robots_allowed,
            "recommendation": recommendation,
            "canonical": canonical,
            "partial": partial,
        }
        return _listed(
            lambda offset, size: service.list_pages(
                audit_id, offset=offset, page_size=size, filters=filters
            ),
            page_size,
            cursor,
            "pages",
            PAGE_ORDERING,
            filters,
            service,
        )

    @router.get(
        "/{audit_id}/pages/{page_id}", response_model=MetadataAuditResponse, responses=errors
    )
    async def page(audit_id: str, page_id: str) -> MetadataAuditResponse:
        return _response(lambda: service.get_page(audit_id, page_id))

    @router.get("/{audit_id}/issues", response_model=MetadataAuditResponse, responses=errors)
    async def issues(
        audit_id: str,
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
        severity: str | None = None,
        category: str | None = None,
        code: str | None = None,
        url: Annotated[str | None, Query(max_length=512)] = None,
        page_id: str | None = None,
        determinacy: str | None = None,
        duplicate_group_id: str | None = None,
        status_class: int | None = None,
        content_type: str | None = None,
    ) -> MetadataAuditResponse:
        filters = {
            "severity": severity,
            "category": category,
            "code": code,
            "url": url,
            "page_id": page_id,
            "determinacy": determinacy,
            "duplicate_group_id": duplicate_group_id,
            "status_class": status_class,
            "content_type": content_type,
        }
        return _listed(
            lambda offset, size: service.list_issues(
                audit_id, offset=offset, page_size=size, filters=filters
            ),
            page_size,
            cursor,
            "issues",
            ISSUE_ORDERING,
            filters,
            service,
        )

    @router.get("/{audit_id}/duplicates", response_model=MetadataAuditResponse, responses=errors)
    async def duplicates(
        audit_id: str,
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
        duplicate_type: str | None = None,
    ) -> MetadataAuditResponse:
        filters = {"duplicate_type": duplicate_type}
        return _listed(
            lambda offset, size: service.list_duplicate_groups(
                audit_id, offset=offset, page_size=size, duplicate_type=duplicate_type
            ),
            page_size,
            cursor,
            "duplicates",
            DUPLICATE_ORDERING,
            filters,
            service,
        )

    @router.get(
        "/{audit_id}/duplicates/{group_id}", response_model=MetadataAuditResponse, responses=errors
    )
    async def duplicate(
        audit_id: str,
        group_id: str,
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
    ) -> MetadataAuditResponse:
        size = page_size or service.configuration.default_page_size
        filters = {"group_id": group_id}
        offset = _offset(cursor, "duplicate_members", PAGE_ORDERING, filters)
        return _response(
            lambda: service.get_duplicate_group(audit_id, group_id, offset=offset, page_size=size)
        )

    @router.post("/{audit_id}/exports", response_model=MetadataAuditResponse, responses=errors)
    async def export(audit_id: str, request: MetadataAuditExportRequest) -> MetadataAuditResponse:
        return _response(lambda: service.create_export(audit_id, request.format))

    return router


def _listed(
    factory: Any,
    page_size: int | None,
    cursor: str | None,
    kind: str,
    ordering: str,
    filters: dict[str, Any],
    service: MetadataAuditService,
) -> MetadataAuditResponse:
    size = page_size or service.configuration.default_page_size
    offset = _offset(cursor, kind, ordering, filters)
    return _page_response(factory(offset, size), offset, size, kind, ordering, filters)


def _page_response(
    items: Any, offset: int, size: int, kind: str, ordering: str, filters: dict[str, Any]
) -> MetadataAuditResponse:
    values = [asdict(item) if hasattr(item, "__dataclass_fields__") else item for item in items]
    fingerprint = filter_fingerprint(filters)
    next_cursor = (
        encode_cursor(kind, ordering, fingerprint, [offset + len(values)])
        if len(values) == size
        else None
    )
    return MetadataAuditResponse(
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
    key = decode_cursor(cursor, kind, ordering, filter_fingerprint(filters))
    if len(key) != 1 or not isinstance(key[0], int) or key[0] < 0:
        raise _api_error(ValueError("metadata_audit_invalid_cursor"))
    return key[0]


def _response(factory: Any) -> MetadataAuditResponse:
    try:
        return MetadataAuditResponse(data=factory())
    except ValueError as error:
        raise _api_error(error) from None


def _api_error(error: ValueError) -> InternalApiError:
    raw = str(error)
    try:
        code = ApiErrorCode(raw)
    except ValueError:
        code = ApiErrorCode.METADATA_AUDIT_QUERY_FAILED
    status = (
        404
        if raw
        in {
            "metadata_audit_run_not_found",
            "metadata_audit_not_found",
            "metadata_audit_page_not_found",
            "metadata_audit_duplicate_group_not_found",
        }
        else 409
        if raw
        in {
            "metadata_audit_already_exists",
            "metadata_audit_conflict",
            "metadata_audit_run_not_terminal",
        }
        else 400
        if raw
        in {
            "metadata_audit_invalid_filter",
            "metadata_audit_invalid_page_size",
            "metadata_audit_invalid_cursor",
            "metadata_audit_cursor_version_unsupported",
            "metadata_audit_cursor_filter_mismatch",
            "metadata_audit_export_unsupported",
        }
        else 503
    )
    return InternalApiError(status, code, "The metadata audit request could not be completed.")
