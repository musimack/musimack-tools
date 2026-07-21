"""Private authenticated CSA-04 execution and bounded inspection routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
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


class SiteAuditDraftRequest(ApiSchema):
    draft: dict[str, Any]


class SiteAuditDraftUpdateRequest(ApiSchema):
    revision: int = Field(ge=1)
    draft: dict[str, Any]


class SiteAuditRevisionRequest(ApiSchema):
    revision: int = Field(ge=1)


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

    @router.get("", response_model=SiteAuditExecutionResponse, responses=errors)
    async def history(
        offset: Annotated[int, Query(ge=0)] = 0,
        page_size: Annotated[int, Query(ge=1, le=500)] = 50,
        lifecycle: str | None = None,
        search: str | None = None,
    ) -> SiteAuditExecutionResponse:
        return _response(
            lambda: service.history(
                offset=offset,
                page_size=page_size,
                lifecycle=lifecycle,
                search=search,
            )
        )

    @router.post("", response_model=SiteAuditExecutionResponse, responses=errors)
    async def create_draft(
        payload: SiteAuditDraftRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> SiteAuditExecutionResponse:
        return _response(
            lambda: service.create_draft(
                payload.draft,
                actor=_actor(request),
                idempotency_key=idempotency_key,
            )
        )

    @router.get("/{audit_id}", response_model=SiteAuditExecutionResponse, responses=errors)
    async def audit_detail(audit_id: str) -> SiteAuditExecutionResponse:
        return _response(lambda: service.audit_detail(audit_id))

    @router.patch("/{audit_id}/draft", response_model=SiteAuditExecutionResponse, responses=errors)
    async def update_draft(
        audit_id: str, payload: SiteAuditDraftUpdateRequest
    ) -> SiteAuditExecutionResponse:
        return _response(
            lambda: service.update_draft(
                audit_id, payload.draft, expected_revision=payload.revision
            )
        )

    @router.post(
        "/{audit_id}/validate", response_model=SiteAuditExecutionResponse, responses=errors
    )
    async def validate_draft(
        audit_id: str, payload: SiteAuditRevisionRequest
    ) -> SiteAuditExecutionResponse:
        return _response(
            lambda: service.validate_draft(audit_id, expected_revision=payload.revision)
        )

    @router.post(
        "/{audit_id}/preflight", response_model=SiteAuditExecutionResponse, responses=errors
    )
    async def preflight_draft(
        audit_id: str, payload: SiteAuditRevisionRequest
    ) -> SiteAuditExecutionResponse:
        return await _async_response(
            service.preflight_draft(audit_id, expected_revision=payload.revision)
        )

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
    async def pages(  # noqa: PLR0913
        audit_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        page_size: Annotated[int, Query(ge=1, le=500)] = 50,
        url: Annotated[str | None, Query(max_length=256)] = None,
        http_status: Annotated[int | None, Query(ge=100, le=599)] = None,
        content_type: Annotated[str | None, Query(max_length=256)] = None,
        fetch_state: Annotated[str | None, Query(max_length=32)] = None,
        indexability: Annotated[str | None, Query(max_length=32)] = None,
        canonical: Annotated[str | None, Query(max_length=32)] = None,
        existing_sitemap: Annotated[str | None, Query(max_length=32)] = None,
        recommended_sitemap: Annotated[str | None, Query(max_length=32)] = None,
        metadata_eligibility: Annotated[str | None, Query(max_length=64)] = None,
        issue_category: Annotated[str | None, Query(max_length=64)] = None,
        severity: Annotated[str | None, Query(max_length=24)] = None,
        business_importance: Annotated[str | None, Query(max_length=24)] = None,
        exclusion_reason: Annotated[str | None, Query(max_length=128)] = None,
        query_parameter: Annotated[bool, Query()] = False,  # noqa: FBT002
        crawl_depth: Annotated[int | None, Query(ge=0)] = None,
        partial: Annotated[bool | None, Query()] = None,
        only_actionable: Annotated[bool, Query()] = False,  # noqa: FBT002
        only_sitemap_issues: Annotated[bool, Query()] = False,  # noqa: FBT002
        only_metadata_issues: Annotated[bool, Query()] = False,  # noqa: FBT002
        only_excluded: Annotated[bool, Query()] = False,  # noqa: FBT002
        sort: Annotated[
            str, Query(pattern="^(sequence|url|status|severity|depth|issues)$")
        ] = "sequence",
        direction: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    ) -> SiteAuditExecutionResponse:
        filters = {
            "url": url,
            "http_status": http_status,
            "content_type": content_type,
            "fetch_state": fetch_state,
            "indexability": indexability,
            "canonical": canonical,
            "existing_sitemap": existing_sitemap,
            "recommended_sitemap": recommended_sitemap,
            "metadata_eligibility": metadata_eligibility,
            "issue_category": issue_category,
            "severity": severity,
            "business_importance": business_importance,
            "exclusion_reason": exclusion_reason,
            "query_parameter": query_parameter,
            "crawl_depth": crawl_depth,
            "partial": partial,
            "only_actionable": only_actionable,
            "only_sitemap_issues": only_sitemap_issues,
            "only_metadata_issues": only_metadata_issues,
            "only_excluded": only_excluded,
        }
        return _response(
            lambda: service.pages(
                audit_id,
                offset=offset,
                page_size=page_size,
                filters=filters,
                sort=sort,
                direction=direction,
            )
        )

    @router.get(
        "/{audit_id}/pages/{sequence}",
        response_model=SiteAuditExecutionResponse,
        responses=errors,
    )
    async def page_detail(audit_id: str, sequence: int) -> SiteAuditExecutionResponse:
        return _response(lambda: service.page_detail(audit_id, sequence))

    @router.get("/{audit_id}/issues", response_model=SiteAuditExecutionResponse, responses=errors)
    async def issues(  # noqa: PLR0913
        audit_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        page_size: Annotated[int, Query(ge=1, le=500)] = 50,
        search: Annotated[str | None, Query(max_length=256)] = None,
        category: Annotated[str | None, Query(max_length=64)] = None,
        module: Annotated[str | None, Query(max_length=64)] = None,
        severity: Annotated[str | None, Query(max_length=24)] = None,
        priority: Annotated[str | None, Query(max_length=24)] = None,
        business_importance: Annotated[str | None, Query(max_length=24)] = None,
        sitemap_impact: Annotated[bool, Query()] = False,  # noqa: FBT002
        metadata_impact: Annotated[bool, Query()] = False,  # noqa: FBT002
        indexability_impact: Annotated[bool, Query()] = False,  # noqa: FBT002
        confidence: Annotated[str | None, Query(max_length=24)] = None,
        determinacy: Annotated[str | None, Query(max_length=24)] = None,
        actionable: Annotated[bool, Query()] = False,  # noqa: FBT002
    ) -> SiteAuditExecutionResponse:
        return _response(
            lambda: service.issues(
                audit_id,
                offset=offset,
                page_size=page_size,
                filters={
                    "search": search,
                    "category": category,
                    "module": module,
                    "severity": severity,
                    "priority": priority,
                    "business_importance": business_importance,
                    "sitemap_impact": sitemap_impact,
                    "metadata_impact": metadata_impact,
                    "indexability_impact": indexability_impact,
                    "confidence": confidence,
                    "determinacy": determinacy,
                    "actionable": actionable,
                },
            )
        )

    @router.get(
        "/{audit_id}/issues/{group_id}",
        response_model=SiteAuditExecutionResponse,
        responses=errors,
    )
    async def issue_detail(
        audit_id: str,
        group_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    ) -> SiteAuditExecutionResponse:
        return _response(
            lambda: service.issue_detail(audit_id, group_id, offset=offset, page_size=page_size)
        )

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

    @router.get(
        "/{audit_id}/sitemap-comparisons",
        response_model=SiteAuditExecutionResponse,
        responses=errors,
    )
    async def sitemap_comparisons(  # noqa: PLR0913
        audit_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        page_size: Annotated[int, Query(ge=1, le=500)] = 50,
        url: Annotated[str | None, Query(max_length=256)] = None,
        state: Annotated[str | None, Query(max_length=32)] = None,
        partial: Annotated[bool | None, Query()] = None,
    ) -> SiteAuditExecutionResponse:
        return _response(
            lambda: service.sitemap_comparison(
                audit_id,
                offset=offset,
                page_size=page_size,
                filters={"url": url, "state": state, "partial": partial},
            )
        )

    @router.get(
        "/{audit_id}/sitemap-documents",
        response_model=SiteAuditExecutionResponse,
        responses=errors,
    )
    async def sitemap_documents(  # noqa: PLR0913
        audit_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        page_size: Annotated[int, Query(ge=1, le=500)] = 50,
        document_type: Annotated[str | None, Query(max_length=32)] = None,
        parse_state: Annotated[str | None, Query(max_length=32)] = None,
        partial: Annotated[bool | None, Query()] = None,
        url: Annotated[str | None, Query(max_length=256)] = None,
    ) -> SiteAuditExecutionResponse:
        return _response(
            lambda: service.sitemap_documents(
                audit_id,
                offset=offset,
                page_size=page_size,
                filters={
                    "document_type": document_type,
                    "parse_state": parse_state,
                    "partial": partial,
                    "url": url,
                },
            )
        )

    @router.get(
        "/{audit_id}/exclusions", response_model=SiteAuditExecutionResponse, responses=errors
    )
    async def exclusions(  # noqa: PLR0913
        audit_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        page_size: Annotated[int, Query(ge=1, le=500)] = 50,
        url: Annotated[str | None, Query(max_length=256)] = None,
        decision_layer: Annotated[str | None, Query(max_length=32)] = None,
        action: Annotated[str | None, Query(max_length=64)] = None,
        reason: Annotated[str | None, Query(max_length=256)] = None,
        enqueued: Annotated[str | None, Query(max_length=32)] = None,
        fetched: Annotated[str | None, Query(max_length=32)] = None,
        override: Annotated[bool, Query()] = False,  # noqa: FBT002
        conflict: Annotated[bool, Query()] = False,  # noqa: FBT002
        partial: Annotated[bool, Query()] = False,  # noqa: FBT002
    ) -> SiteAuditExecutionResponse:
        return _response(
            lambda: service.exclusions(
                audit_id,
                offset=offset,
                page_size=page_size,
                filters={
                    "url": url,
                    "decision_layer": decision_layer,
                    "action": action,
                    "reason": reason,
                    "enqueued": enqueued,
                    "fetched": fetched,
                    "override": override,
                    "conflict": conflict,
                    "partial": partial,
                },
            )
        )

    @router.get("/{audit_id}/evidence", response_model=SiteAuditExecutionResponse, responses=errors)
    async def evidence(audit_id: str) -> SiteAuditExecutionResponse:
        return _response(lambda: service.evidence(audit_id))

    @router.get("/{audit_id}/snapshot", response_model=SiteAuditExecutionResponse, responses=errors)
    async def snapshot(audit_id: str) -> SiteAuditExecutionResponse:
        return _response(lambda: service.settings_snapshot(audit_id))

    @router.post("/{audit_id}/archive", response_model=SiteAuditExecutionResponse, responses=errors)
    async def archive(audit_id: str) -> SiteAuditExecutionResponse:
        return _response(lambda: service.archive(audit_id))

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
            ApiErrorCode.SITE_AUDIT_REAL_SITE_OPERATIONS_SUSPENDED,
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
    "site_audit_settings_unavailable": ApiErrorCode.SITE_AUDIT_SETTINGS_DISABLED,
    "site_audit_real_site_operations_suspended": (
        ApiErrorCode.SITE_AUDIT_REAL_SITE_OPERATIONS_SUSPENDED
    ),
    "site_audit_global_settings_version_not_found": ApiErrorCode.SITE_AUDIT_SETTINGS_INVALID,
    "site_audit_preset_version_not_found": ApiErrorCode.SITE_AUDIT_PRESET_NOT_FOUND,
    "site_audit_preset_not_found": ApiErrorCode.SITE_AUDIT_PRESET_NOT_FOUND,
    "site_profile_not_found": ApiErrorCode.SITE_PROFILE_NOT_FOUND,
    "site_profile_version_not_found": ApiErrorCode.SITE_PROFILE_NOT_FOUND,
    "site_audit_preset_acceptance_invalid": ApiErrorCode.SITE_AUDIT_SETTINGS_INVALID,
    "site_audit_tracking_acceptance_invalid": ApiErrorCode.SITE_AUDIT_SETTINGS_INVALID,
    "site_audit_disabled_rule_invalid": ApiErrorCode.SITE_AUDIT_SETTINGS_INVALID,
    "site_audit_rule_limit": ApiErrorCode.SITE_AUDIT_SETTINGS_INVALID,
}
