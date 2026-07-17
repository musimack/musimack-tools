"""Private authenticated sitemap-audit resource routes."""

# ruff: noqa: ANN401, C901, FBT001, PLR0913, TRY003 - FastAPI signatures are contracts.

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from musimack_tools.api.dependencies import create_access_dependency
from musimack_tools.api.schemas import ApiErrorEnvelope, ApiSchema
from musimack_tools.domain.api import ApiErrorCode, InternalApiConfiguration, InternalApiError
from musimack_tools.domain.page_evidence import IndexabilityEvidenceState  # noqa: TC001
from musimack_tools.domain.sitemap import RecommendationState  # noqa: TC001
from musimack_tools.domain.sitemap_audit import (
    AUDIT_ORDERING,
    COMPARISON_ORDERING,
    DOCUMENT_ORDERING,
    ENTRY_ORDERING,
    FINDING_ORDERING,
    SITEMAP_AUDIT_API_VERSION,
    ComparisonAction,
    ComparisonReason,
    ComparisonState,
    DiscoveryOptions,
    DiscoverySource,
    ExportFormat,
    ParseState,
    ValidationCode,
    ValidationSeverity,
    decode_cursor,
    encode_cursor,
    filter_fingerprint,
)
from musimack_tools.security.correlation import current_request_id

if TYPE_CHECKING:
    from musimack_tools.sitemap_audit.service import SitemapAuditService


class SitemapAuditCreateRequest(ApiSchema):
    run_id: str = Field(min_length=1, max_length=64)
    explicit_sitemap_url: str | None = Field(default=None, max_length=4096)
    discover_robots: bool = True
    discover_common_locations: bool = True


class SitemapAuditExportRequest(ApiSchema):
    format: ExportFormat


class SitemapAuditResponse(ApiSchema):
    sitemap_audit_api_version: str = SITEMAP_AUDIT_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: Any


def create_sitemap_audit_router(
    service: SitemapAuditService, configuration: InternalApiConfiguration
) -> APIRouter:
    if not service.configuration.enabled:
        raise ValueError("sitemap audit routes require enabled configuration")
    include = (
        configuration.include_internal_routes_in_schema
        and configuration.include_internal_endpoints_in_docs
    )
    router = APIRouter(
        prefix=f"{configuration.route_prefix}/audits/sitemaps",
        dependencies=[Depends(create_access_dependency(configuration))],
        include_in_schema=include,
    )
    errors: dict[int | str, dict[str, Any]] = {
        code: {"model": ApiErrorEnvelope} for code in (400, 401, 403, 404, 409, 503)
    }

    @router.post("/discover", response_model=SitemapAuditResponse, responses=errors)
    async def discover(request: SitemapAuditCreateRequest) -> SitemapAuditResponse:
        try:
            candidates, findings = await service.discover(request.run_id, _options(request))
            return SitemapAuditResponse(
                data={
                    "candidates": [
                        {
                            "normalized_url": item.normalized_url,
                            "discovery_source": item.discovery_source,
                            "discovery_sequence": item.discovery_sequence,
                            "provenance": item.provenance,
                            "raw_url": item.raw_url,
                        }
                        for item in candidates
                    ],
                    "findings": [
                        {
                            "code": item.code,
                            "severity": item.severity,
                            "message": item.message,
                            "sequence": item.sequence,
                        }
                        for item in findings
                    ],
                }
            )
        except ValueError as error:
            raise _api_error(error) from None

    @router.post("", response_model=SitemapAuditResponse, responses=errors)
    async def create(request: SitemapAuditCreateRequest) -> SitemapAuditResponse:
        return _response(lambda: service.create_audit(request.run_id, _options(request)))

    @router.post("/{audit_id}/execute", response_model=SitemapAuditResponse, responses=errors)
    async def execute(audit_id: str) -> SitemapAuditResponse:
        try:
            return SitemapAuditResponse(data=await service.execute_audit(audit_id))
        except ValueError as error:
            raise _api_error(error) from None

    @router.get("", response_model=SitemapAuditResponse, responses=errors)
    async def audits(
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
    ) -> SitemapAuditResponse:
        return _listed(
            service, "audits", AUDIT_ORDERING, {}, page_size, cursor, service.list_audits
        )

    @router.get("/{audit_id}", response_model=SitemapAuditResponse, responses=errors)
    async def detail(audit_id: str) -> SitemapAuditResponse:
        return _response(lambda: service.get(audit_id))

    @router.get("/{audit_id}/summary", response_model=SitemapAuditResponse, responses=errors)
    async def summary(audit_id: str) -> SitemapAuditResponse:
        return _response(lambda: service.summary(audit_id))

    @router.get("/{audit_id}/documents", response_model=SitemapAuditResponse, responses=errors)
    async def documents(
        audit_id: str,
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
        root: bool | None = None,
        parse_state: ParseState | None = None,
        depth: Annotated[int | None, Query(ge=0)] = None,
        discovery_source: DiscoverySource | None = None,
        url: Annotated[str | None, Query(max_length=512)] = None,
    ) -> SitemapAuditResponse:
        filters = {
            key: value.value if hasattr(value, "value") else value
            for key, value in {
                "root": root,
                "parse_state": parse_state,
                "depth": depth,
                "discovery_source": discovery_source,
                "url": url,
            }.items()
            if value is not None
        }
        return _resource_list(
            service,
            audit_id,
            "documents",
            DOCUMENT_ORDERING,
            page_size,
            cursor,
            service.list_documents,
            filters,
        )

    @router.get("/{audit_id}/entries", response_model=SitemapAuditResponse, responses=errors)
    async def entries(
        audit_id: str,
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
    ) -> SitemapAuditResponse:
        return _resource_list(
            service, audit_id, "entries", ENTRY_ORDERING, page_size, cursor, service.list_entries
        )

    @router.get("/{audit_id}/findings", response_model=SitemapAuditResponse, responses=errors)
    async def findings(
        audit_id: str,
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
        severity: ValidationSeverity | None = None,
        code: ValidationCode | None = None,
        document_id: str | None = None,
        url: Annotated[str | None, Query(max_length=512)] = None,
    ) -> SitemapAuditResponse:
        filters = {
            key: value.value if hasattr(value, "value") else value
            for key, value in {
                "severity": severity,
                "code": code,
                "document_id": document_id,
                "url": url,
            }.items()
            if value is not None
        }
        return _resource_list(
            service,
            audit_id,
            "findings",
            FINDING_ORDERING,
            page_size,
            cursor,
            service.list_findings,
            filters,
        )

    @router.get("/{audit_id}/comparisons", response_model=SitemapAuditResponse, responses=errors)
    async def comparisons(
        audit_id: str,
        page_size: Annotated[int | None, Query(ge=1)] = None,
        cursor: Annotated[str | None, Query(max_length=2048)] = None,
        action: ComparisonAction | None = None,
        state: ComparisonState | None = None,
        reason: ComparisonReason | None = None,
        recommendation: RecommendationState | None = None,
        http_status: Annotated[int | None, Query(ge=100, le=599)] = None,
        status_class: Annotated[int | None, Query(ge=1, le=5)] = None,
        content_type: Annotated[str | None, Query(max_length=256)] = None,
        indexability: IndexabilityEvidenceState | None = None,
        document_id: str | None = None,
        url: Annotated[str | None, Query(max_length=512)] = None,
    ) -> SitemapAuditResponse:
        filters = {
            key: value
            for key, value in {
                "action": action,
                "state": state,
                "reason": reason,
                "recommendation": recommendation,
                "http_status": http_status,
                "status_class": status_class,
                "content_type": content_type,
                "indexability": indexability,
                "document_id": document_id,
                "url": url,
            }.items()
            if value is not None
        }
        filters = {
            key: value.value if hasattr(value, "value") else value for key, value in filters.items()
        }
        size = page_size or service.configuration.default_page_size
        offset = _offset(cursor, "comparisons", COMPARISON_ORDERING, filters)
        items = service.list_comparisons(audit_id, offset, size, filters)
        return _page(items, offset, size, "comparisons", COMPARISON_ORDERING, filters)

    @router.post("/{audit_id}/exports", response_model=SitemapAuditResponse, responses=errors)
    async def export(audit_id: str, request: SitemapAuditExportRequest) -> SitemapAuditResponse:
        return _response(lambda: service.create_export(audit_id, request.format))

    @router.get("/{audit_id}/exports", response_model=SitemapAuditResponse, responses=errors)
    async def exports(audit_id: str) -> SitemapAuditResponse:
        return _response(lambda: {"items": service.list_exports(audit_id)})

    return router


def _options(request: SitemapAuditCreateRequest) -> DiscoveryOptions:
    return DiscoveryOptions(
        request.explicit_sitemap_url,
        request.discover_robots,
        request.discover_common_locations,
    )


def _resource_list(
    service: SitemapAuditService,
    audit_id: str,
    kind: str,
    ordering: str,
    page_size: int | None,
    cursor: str | None,
    factory: Any,
    filters: dict[str, Any] | None = None,
) -> SitemapAuditResponse:
    selected = filters or {}
    size = page_size or service.configuration.default_page_size
    offset = _offset(cursor, kind, ordering, selected)
    return _page(
        factory(audit_id, offset, size, selected),
        offset,
        size,
        kind,
        ordering,
        selected,
    )


def _listed(
    service: SitemapAuditService,
    kind: str,
    ordering: str,
    filters: dict[str, Any],
    page_size: int | None,
    cursor: str | None,
    factory: Any,
) -> SitemapAuditResponse:
    size = page_size or service.configuration.default_page_size
    offset = _offset(cursor, kind, ordering, filters)
    return _page(factory(offset, size), offset, size, kind, ordering, filters)


def _page(
    items: Any, offset: int, size: int, kind: str, ordering: str, filters: dict[str, Any]
) -> SitemapAuditResponse:
    values = list(items)
    fingerprint = filter_fingerprint(filters)
    next_cursor = (
        encode_cursor(kind, ordering, fingerprint, offset + len(values))
        if len(values) == size
        else None
    )
    return SitemapAuditResponse(
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


def _response(factory: Any) -> SitemapAuditResponse:
    try:
        return SitemapAuditResponse(data=factory())
    except ValueError as error:
        raise _api_error(error) from None


def _api_error(error: ValueError) -> InternalApiError:
    raw = str(error)
    try:
        code = ApiErrorCode(raw)
    except ValueError:
        code = ApiErrorCode.SITEMAP_AUDIT_QUERY_FAILED
    status = (
        404
        if raw in {"sitemap_audit_run_not_found", "sitemap_audit_not_found"}
        else 409
        if raw in {"sitemap_audit_run_not_terminal", "sitemap_audit_already_exists"}
        else 400
        if raw
        in {
            "sitemap_audit_invalid_filter",
            "sitemap_audit_invalid_page_size",
            "sitemap_audit_invalid_cursor",
            "sitemap_audit_cursor_version_unsupported",
            "sitemap_audit_cursor_filter_mismatch",
            "sitemap_audit_export_unsupported",
        }
        else 503
    )
    return InternalApiError(status, code, "The sitemap audit request could not be completed.")
