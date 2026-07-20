"""Private authenticated CSA-02 settings and URL-governance routes."""

# ruff: noqa: C901, TRY003

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field

from musimack_tools.api.dependencies import create_access_dependency
from musimack_tools.api.schemas import ApiErrorEnvelope, ApiSchema
from musimack_tools.domain.api import ApiErrorCode, InternalApiConfiguration, InternalApiError
from musimack_tools.domain.authentication import AuthenticatedPrincipal, UserRole
from musimack_tools.domain.site_audit_settings import (
    MAXIMUM_API_PAGE_SIZE,
    SITE_AUDIT_SETTINGS_API_VERSION,
    ProfileState,
    SiteAuditSettingsError,
)
from musimack_tools.security.correlation import current_request_id

if TYPE_CHECKING:
    from collections.abc import Callable

    from musimack_tools.site_audit_settings.service import SiteAuditSettingsService


class SettingsUpdateRequest(ApiSchema):
    expected_version: int = Field(ge=0)
    configuration: dict[str, Any]


class SiteProfileWriteRequest(ApiSchema):
    expected_version: int | None = Field(default=None, ge=1)
    configuration: dict[str, Any]


class GovernanceRequest(ApiSchema):
    profile_id: str | None = Field(default=None, max_length=64)
    preset_id: str | None = Field(default=None, max_length=64)
    preset_version: str | None = Field(default=None, max_length=64)
    preset_accepted: bool = False
    preset_rule_states: dict[str, bool] = Field(default_factory=dict)
    tracking_parameters_accepted: bool = False
    tracking_parameter_exceptions: list[str] = Field(default_factory=list, max_length=100)
    overrides: dict[str, Any] = Field(default_factory=dict)
    sample_urls: list[str] = Field(default_factory=list, max_length=100)


class RuleValidationRequest(ApiSchema):
    rule: dict[str, Any]


class SiteAuditSettingsResponse(ApiSchema):
    site_audit_settings_api_version: str = SITE_AUDIT_SETTINGS_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: Any


def create_site_audit_settings_router(
    service: SiteAuditSettingsService, configuration: InternalApiConfiguration
) -> APIRouter:
    if not service.configuration.enabled:
        raise ValueError("site-audit settings routes require enabled configuration")
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
        code: {"model": ApiErrorEnvelope} for code in (400, 401, 403, 404, 409, 413, 503)
    }

    @router.get("/settings", response_model=SiteAuditSettingsResponse, responses=errors)
    async def settings() -> SiteAuditSettingsResponse:
        return _response(service.settings)

    @router.put("/settings", response_model=SiteAuditSettingsResponse, responses=errors)
    async def update_settings(
        payload: SettingsUpdateRequest, request: Request
    ) -> SiteAuditSettingsResponse:
        return _response(
            lambda: service.update_settings(
                payload.configuration,
                expected_version=payload.expected_version,
                actor=_actor(request),
            )
        )

    @router.get("/presets", response_model=SiteAuditSettingsResponse, responses=errors)
    async def presets() -> SiteAuditSettingsResponse:
        return _response(service.presets)

    @router.get("/presets/{preset_id}", response_model=SiteAuditSettingsResponse, responses=errors)
    async def preset(
        preset_id: str, version: Annotated[str | None, Query(max_length=64)] = None
    ) -> SiteAuditSettingsResponse:
        return _response(lambda: service.preset(preset_id, version))

    @router.get("/site-profiles", response_model=SiteAuditSettingsResponse, responses=errors)
    async def profiles(
        request: Request,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=MAXIMUM_API_PAGE_SIZE)] = (
            service.configuration.default_page_size
        ),
        include_disabled: Annotated[bool, Query()] = False,  # noqa: FBT002
    ) -> SiteAuditSettingsResponse:
        include = include_disabled and _administrator(request)
        return _response(
            lambda: service.profiles(include_disabled=include, offset=offset, limit=limit)
        )

    @router.post("/site-profiles", response_model=SiteAuditSettingsResponse, responses=errors)
    async def create_profile(
        payload: SiteProfileWriteRequest, request: Request
    ) -> SiteAuditSettingsResponse:
        if payload.expected_version is not None:
            raise _api_error(
                SiteAuditSettingsError(
                    "site_profile_version_invalid", "New profiles cannot have an expected version."
                )
            )
        return _response(
            lambda: service.create_profile(payload.configuration, actor=_actor(request))
        )

    @router.get(
        "/site-profiles/{profile_id}",
        response_model=SiteAuditSettingsResponse,
        responses=errors,
    )
    async def profile(profile_id: str, request: Request) -> SiteAuditSettingsResponse:
        return _response(
            lambda: service.profile(profile_id, include_disabled=_administrator(request))
        )

    @router.get(
        "/site-profiles/{profile_id}/versions",
        response_model=SiteAuditSettingsResponse,
        responses=errors,
    )
    async def profile_versions(profile_id: str) -> SiteAuditSettingsResponse:
        return _response(lambda: service.profile_versions(profile_id))

    @router.put(
        "/site-profiles/{profile_id}",
        response_model=SiteAuditSettingsResponse,
        responses=errors,
    )
    async def update_profile(
        profile_id: str, payload: SiteProfileWriteRequest, request: Request
    ) -> SiteAuditSettingsResponse:
        if payload.expected_version is None:
            raise _api_error(
                SiteAuditSettingsError(
                    "site_profile_version_invalid", "Expected profile version is required."
                )
            )
        return _response(
            lambda: service.update_profile(
                profile_id,
                payload.configuration,
                expected_version=payload.expected_version or 0,
                actor=_actor(request),
            )
        )

    @router.post(
        "/site-profiles/{profile_id}/disable",
        response_model=SiteAuditSettingsResponse,
        responses=errors,
    )
    async def disable_profile(profile_id: str) -> SiteAuditSettingsResponse:
        return _response(lambda: service.set_profile_state(profile_id, ProfileState.DISABLED))

    @router.post(
        "/site-profiles/{profile_id}/archive",
        response_model=SiteAuditSettingsResponse,
        responses=errors,
    )
    async def archive_profile(profile_id: str) -> SiteAuditSettingsResponse:
        return _response(lambda: service.set_profile_state(profile_id, ProfileState.ARCHIVED))

    @router.post("/effective-settings", response_model=SiteAuditSettingsResponse, responses=errors)
    async def effective_settings(
        payload: GovernanceRequest, request: Request
    ) -> SiteAuditSettingsResponse:
        return _response(
            lambda: service.effective_settings(payload.model_dump(), actor=_actor(request))
        )

    @router.post("/rules/validate", response_model=SiteAuditSettingsResponse, responses=errors)
    async def validate_rule(
        payload: RuleValidationRequest, request: Request
    ) -> SiteAuditSettingsResponse:
        return _response(lambda: service.validate_rule(payload.rule, actor=_actor(request)))

    @router.post("/rule-tests", response_model=SiteAuditSettingsResponse, responses=errors)
    async def rule_tests(payload: GovernanceRequest, request: Request) -> SiteAuditSettingsResponse:
        return _response(lambda: service.test_rules(payload.model_dump(), actor=_actor(request)))

    @router.post("/rule-previews", response_model=SiteAuditSettingsResponse, responses=errors)
    async def rule_previews() -> SiteAuditSettingsResponse:
        raise _api_error(
            SiteAuditSettingsError(
                "site_audit_rule_preview_deferred",
                "Retained-evidence preview requires a later eligible-evidence selector.",
            )
        )

    return router


def _response(operation: Callable[[], Any]) -> SiteAuditSettingsResponse:
    try:
        return SiteAuditSettingsResponse(data=operation())
    except SiteAuditSettingsError as error:
        raise _api_error(error) from None
    except KeyError, TypeError, ValueError:
        raise InternalApiError(
            400,
            ApiErrorCode.SITE_AUDIT_SETTINGS_INVALID,
            "Site-audit settings are invalid.",
        ) from None


def _api_error(error: SiteAuditSettingsError) -> InternalApiError:
    code = _ERROR_CODES.get(error.code, ApiErrorCode.SITE_AUDIT_SETTINGS_INVALID)
    status = (
        404
        if code
        in {
            ApiErrorCode.SITE_AUDIT_PRESET_NOT_FOUND,
            ApiErrorCode.SITE_PROFILE_NOT_FOUND,
        }
        else 409
        if "conflict" in code.value or code is ApiErrorCode.SITE_AUDIT_RULE_PREVIEW_DEFERRED
        else 503
        if code is ApiErrorCode.SITE_AUDIT_SETTINGS_DISABLED
        else 400
    )
    return InternalApiError(status, code, error.explanation)


def _actor(request: Request) -> str:
    principal = getattr(request.state, "authenticated_principal", None)
    if isinstance(principal, AuthenticatedPrincipal):
        return principal.user_id or principal.email or principal.principal_type.value
    return "authenticated-principal"


def _administrator(request: Request) -> bool:
    principal = getattr(request.state, "authenticated_principal", None)
    return (
        isinstance(principal, AuthenticatedPrincipal) and principal.role is UserRole.ADMINISTRATOR
    )


_ERROR_CODES = {
    "site_audit_settings_disabled": ApiErrorCode.SITE_AUDIT_SETTINGS_DISABLED,
    "site_audit_settings_version_conflict": ApiErrorCode.SITE_AUDIT_SETTINGS_CONFLICT,
    "site_audit_settings_conflict": ApiErrorCode.SITE_AUDIT_SETTINGS_CONFLICT,
    "site_audit_preset_not_found": ApiErrorCode.SITE_AUDIT_PRESET_NOT_FOUND,
    "site_audit_preset_version_not_found": ApiErrorCode.SITE_AUDIT_PRESET_NOT_FOUND,
    "site_profile_not_found": ApiErrorCode.SITE_PROFILE_NOT_FOUND,
    "site_profile_conflict": ApiErrorCode.SITE_PROFILE_CONFLICT,
    "site_profile_version_conflict": ApiErrorCode.SITE_PROFILE_CONFLICT,
    "site_profile_archived": ApiErrorCode.SITE_PROFILE_ARCHIVED,
    "site_audit_rule_preview_deferred": ApiErrorCode.SITE_AUDIT_RULE_PREVIEW_DEFERRED,
    "site_audit_rule_test_limit": ApiErrorCode.SITE_AUDIT_RULE_TEST_LIMIT,
}
