"""Dependency composition for the private internal API adapter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol

from fastapi import Request

from musimack_tools.api.access import DenyAllAccessVerifier
from musimack_tools.domain.api import (
    AccessDenialReason,
    AccessOutcome,
    ApiErrorCode,
    InternalApiConfiguration,
    InternalApiError,
    InternalCallerContext,
)
from musimack_tools.domain.authentication import (
    AuthenticatedPrincipal,
    AuthenticationMethod,
    Permission,
    PrincipalType,
    UserRole,
    permissions_for_role,
)

if TYPE_CHECKING:
    from musimack_tools.domain.application import (
        ApplicationCancellationResult,
        ApplicationJobList,
        ApplicationJobStatus,
        ApplicationPreflightResult,
        ApplicationProgressResult,
        ApplicationReadinessReport,
        ApplicationRecommendationPage,
        ApplicationRegistryStatus,
        ApplicationResultProjection,
        ApplicationSubmissionResult,
        ApplicationValidationReport,
        RawApplicationCrawlRequest,
    )
    from musimack_tools.domain.capabilities import ApplicationCapabilityReport

AccessDependency = Callable[[Request], Awaitable[InternalCallerContext | None]]


class InternalApiApplication(Protocol):
    def validate_request(self, raw: RawApplicationCrawlRequest) -> ApplicationValidationReport: ...

    async def preflight(self, raw: RawApplicationCrawlRequest) -> ApplicationPreflightResult: ...

    async def submit(self, raw: RawApplicationCrawlRequest) -> ApplicationSubmissionResult: ...

    async def get_job_status(self, job_id: str) -> ApplicationJobStatus: ...

    async def list_jobs(self) -> ApplicationJobList: ...

    async def get_job_progress(self, job_id: str) -> ApplicationProgressResult: ...

    async def get_job_result(self, job_id: str) -> ApplicationResultProjection: ...

    async def get_job_recommendations(  # noqa: PLR0913 - bounded filter contract.
        self,
        job_id: str,
        *,
        offset: int,
        limit: int,
        state: str | None = None,
        reason: str | None = None,
        text: str | None = None,
    ) -> ApplicationRecommendationPage: ...

    async def cancel_job(self, job_id: str) -> ApplicationCancellationResult: ...

    async def get_registry_status(self) -> ApplicationRegistryStatus: ...

    async def get_readiness(self) -> ApplicationReadinessReport: ...

    def get_capabilities(self) -> ApplicationCapabilityReport: ...


def create_access_dependency(  # noqa: C901 - explicit stable security mappings.
    configuration: InternalApiConfiguration,
) -> AccessDependency:
    """Create a fail-closed dependency bound to one immutable configuration."""
    verifier = configuration.access_verifier or DenyAllAccessVerifier()

    async def require_internal_access(  # noqa: C901, PLR0912 - explicit stable mappings.
        request: Request,
    ) -> InternalCallerContext | None:
        try:
            decision = await verifier.verify(request)
        except Exception:  # noqa: BLE001 - verifier failures must fail closed.
            raise InternalApiError(
                403,
                ApiErrorCode.ACCESS_VERIFIER_UNAVAILABLE,
                "Internal access verification is unavailable.",
            ) from None
        if decision.outcome is AccessOutcome.UNAVAILABLE:
            if decision.reason is AccessDenialReason.SECURITY_CONFIGURATION_UNAVAILABLE:
                raise InternalApiError(
                    503,
                    ApiErrorCode.SECURITY_CONFIGURATION_UNAVAILABLE,
                    "Internal authentication is unavailable.",
                )
            raise InternalApiError(
                403,
                ApiErrorCode.ACCESS_VERIFIER_UNAVAILABLE,
                "Internal access verification is unavailable.",
            )
        if decision.outcome is not AccessOutcome.ALLOWED:
            if decision.reason in {
                AccessDenialReason.AUTHENTICATION_REQUIRED,
                AccessDenialReason.AUTHENTICATION_FAILED,
            }:
                raise InternalApiError(
                    401,
                    ApiErrorCode.AUTHENTICATION_FAILED,
                    "Valid internal authentication is required.",
                    headers=(("WWW-Authenticate", "Bearer"),),
                )
            if decision.reason is AccessDenialReason.TRUSTED_NETWORK_REQUIRED:
                raise InternalApiError(
                    403,
                    ApiErrorCode.TRUSTED_NETWORK_REQUIRED,
                    "Internal API access is denied.",
                )
            if decision.reason is AccessDenialReason.INVALID_FORWARDED_HEADER:
                raise InternalApiError(
                    403,
                    ApiErrorCode.INVALID_FORWARDED_HEADER,
                    "Internal API access is denied.",
                )
            if decision.reason is AccessDenialReason.INTERNAL_API_DISABLED:
                raise InternalApiError(
                    403,
                    ApiErrorCode.INTERNAL_API_DISABLED,
                    "Internal API access is denied.",
                )
            if decision.reason is AccessDenialReason.AUTHORIZATION_DENIED:
                raise InternalApiError(
                    403,
                    ApiErrorCode.AUTHORIZATION_DENIED,
                    "The authenticated principal is not authorized for this operation.",
                )
            if decision.reason is AccessDenialReason.SECURITY_CONFIGURATION_UNAVAILABLE:
                raise InternalApiError(
                    503,
                    ApiErrorCode.SECURITY_CONFIGURATION_UNAVAILABLE,
                    "Internal authentication is unavailable.",
                )
            code = (
                ApiErrorCode.ACCESS_VERIFIER_UNAVAILABLE
                if decision.reason is AccessDenialReason.ACCESS_VERIFIER_UNAVAILABLE
                else ApiErrorCode.ACCESS_DENIED
            )
            raise InternalApiError(403, code, "Internal API access is denied.")
        principal = getattr(request.state, "authenticated_principal", None)
        if principal is None:
            # Access verifiers accepted before Phase 27 represent the explicit
            # shared-bearer compatibility principal.
            principal = AuthenticatedPrincipal(
                PrincipalType.SHARED_BEARER,
                AuthenticationMethod.SHARED_BEARER,
                UserRole.ADMINISTRATOR,
                permissions_for_role(UserRole.ADMINISTRATOR),
            )
            request.state.authenticated_principal = principal
        required = permission_for_request(request.method, request.url.path)
        if required is not None and (
            not isinstance(principal, AuthenticatedPrincipal) or not principal.allows(required)
        ):
            recorder = getattr(verifier, "record_authorization_denied", None)
            if callable(recorder):
                recorder(principal, required.value)
            raise InternalApiError(
                403,
                ApiErrorCode.AUTHORIZATION_DENIED,
                "The authenticated principal is not authorized for this operation.",
            )
        return decision.caller

    return require_internal_access


def permission_for_request(  # noqa: C901, PLR0911, PLR0912
    method: str, path: str
) -> Permission | None:
    """Central resource mapping; an unknown protected operation is denied by the caller."""
    if path.endswith(("/auth/me", "/auth/sessions")):
        return Permission.SESSIONS_VIEW_OWN
    if "/auth/sessions/" in path:
        return Permission.SESSIONS_REVOKE_OWN
    if path.endswith("/auth/change-password"):
        return Permission.PASSWORD_CHANGE_OWN
    if path.endswith("/auth/audit"):
        return Permission.AUTH_AUDIT_VIEW
    if "/users" in path:
        if path.endswith("/role"):
            return Permission.USERS_CHANGE_ROLE
        if path.endswith(("/activate", "/deactivate", "/disable")):
            return (
                Permission.USERS_ACTIVATE
                if path.endswith("/activate")
                else Permission.USERS_DEACTIVATE
            )
        if path.endswith("/revoke-sessions"):
            return Permission.SESSIONS_REVOKE_ANY
        if method == "POST":
            return Permission.USERS_CREATE
        if method == "PATCH":
            return Permission.USERS_UPDATE
        return Permission.USERS_VIEW
    if "/artifacts/" in path and path.endswith("/download"):
        return Permission.ARTIFACTS_DOWNLOAD
    if "/artifacts" in path:
        return Permission.ARTIFACTS_VIEW
    if "/history" in path:
        return Permission.HISTORY_VIEW
    if path.endswith("/jobs"):
        return Permission.JOBS_SUBMIT if method == "POST" else Permission.JOBS_VIEW
    if path.endswith("/recommendations"):
        return Permission.RUNS_VIEW
    if path.endswith("/cancel"):
        return Permission.JOBS_CANCEL
    if "/jobs/" in path:
        return Permission.JOBS_VIEW
    if path.endswith(("/readiness", "/registry", "/capabilities")):
        return Permission.DIAGNOSTICS_VIEW
    if path.endswith(("/validate", "/preflight")):
        return Permission.JOBS_SUBMIT
    return None


def enforce_declared_body_limit(configuration: InternalApiConfiguration) -> AccessDependency:
    """Reject an explicitly oversized Content-Length without consuming the body."""

    async def enforce(request: Request) -> InternalCallerContext | None:
        raw_length = request.headers.get("content-length")
        if raw_length is None:
            return None
        try:
            length = int(raw_length)
        except ValueError:
            raise InternalApiError(
                400,
                ApiErrorCode.REQUEST_VALIDATION_FAILED,
                "The request metadata is invalid.",
            ) from None
        if length < 0:
            raise InternalApiError(
                400,
                ApiErrorCode.REQUEST_VALIDATION_FAILED,
                "The request metadata is invalid.",
            )
        if length > configuration.maximum_request_body_bytes:
            raise InternalApiError(
                413,
                ApiErrorCode.REQUEST_BODY_TOO_LARGE,
                "The request body exceeds the internal API limit.",
            )
        return None

    return enforce
