"""Typed private HTTP routes for users, sessions, and authentication audit."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic resolves annotations at runtime.

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import Field, SecretStr

from musimack_tools.api.dependencies import create_access_dependency
from musimack_tools.api.schemas import ApiSchema
from musimack_tools.authentication.service import (
    AuthenticationError,
    AuthenticationService,
    SessionRecord,
    UserRecord,
)
from musimack_tools.domain.api import (
    INTERNAL_API_PREFIX,
    AccessOutcome,
    ApiErrorCode,
    InternalApiConfiguration,
    InternalApiError,
)
from musimack_tools.domain.authentication import (
    AUTH_AUDIT_VERSION,
    AUTHENTICATION_VERSION,
    AUTHORIZATION_VERSION,
    SESSION_VERSION,
    AuthenticatedPrincipal,
    UserRole,
    UserState,
)

_RATE_LIMIT_STATUS = 429


class SignInRequest(ApiSchema):
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr


class PrincipalSchema(ApiSchema):
    user_id: str | None
    email: str | None
    display_name: str | None
    role: UserRole
    permissions: tuple[str, ...]
    authentication_method: str
    session_created_at: datetime | None
    session_expires_at: datetime | None
    session_absolute_expires_at: datetime | None
    password_change_available: bool
    authentication_version: str = AUTHENTICATION_VERSION
    authorization_version: str = AUTHORIZATION_VERSION
    session_version: str = SESSION_VERSION


class SignInResponse(ApiSchema):
    principal: PrincipalSchema


class SignOutResponse(ApiSchema):
    signed_out: bool = True


class PasswordChangeRequest(ApiSchema):
    current_password: SecretStr
    new_password: SecretStr


class SessionSummary(ApiSchema):
    session_id: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    absolute_expires_at: datetime
    authentication_method: str
    current: bool
    revoked: bool
    client_label: str | None


class SessionListResponse(ApiSchema):
    sessions: tuple[SessionSummary, ...]
    session_version: str = SESSION_VERSION


class UserCreateRequest(ApiSchema):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=128)
    role: UserRole
    password: SecretStr
    state: UserState


class UserUpdateRequest(ApiSchema):
    email: str | None = Field(default=None, min_length=3, max_length=320)
    display_name: str | None = Field(default=None, min_length=1, max_length=128)


class RoleChangeRequest(ApiSchema):
    role: UserRole


class LifecycleChangeRequest(ApiSchema):
    state: UserState


class PermissionSummary(ApiSchema):
    permissions: tuple[str, ...]
    authorization_version: str = AUTHORIZATION_VERSION


class AuthenticationDiagnosticsSchema(ApiSchema):
    enabled: bool
    mode: str
    authentication_version: str
    authorization_version: str
    session_version: str
    auth_audit_version: str
    shared_bearer_compatibility_enabled: bool
    user_session_capable: bool
    active_users: int
    administrators: int
    active_sessions: int
    expired_sessions: int
    revoked_sessions: int
    locked_users: int
    recent_login_failures: int
    audit_ready: bool
    migration_ready: bool
    database_ready: bool
    cookie_security_ready: bool
    bootstrap_ready: bool


class UserSchema(ApiSchema):
    user_id: str
    email: str
    display_name: str
    state: UserState
    role: UserRole
    created_at: datetime
    updated_at: datetime


class UserListResponse(ApiSchema):
    users: tuple[UserSchema, ...]


class AuditEventSchema(ApiSchema):
    event_id: str
    event_type: str
    actor_principal_type: str | None
    actor_user_id: str | None
    target_user_id: str | None
    session_id: str | None
    role: str | None
    permission: str | None
    success: bool
    reason_code: str | None
    occurred_at: datetime
    audit_version: str = AUTH_AUDIT_VERSION


class AuditPageResponse(ApiSchema):
    events: tuple[AuditEventSchema, ...]
    next_before_sequence: int | None


def create_authentication_router(  # noqa: C901, PLR0915 - explicit route composition.
    service: AuthenticationService,
    configuration: InternalApiConfiguration,
) -> APIRouter:
    access = create_access_dependency(configuration)

    async def require_sign_in_network(request: Request) -> None:
        verifier = configuration.access_verifier
        network_check = getattr(verifier, "verify_sign_in_network", None)
        if not callable(network_check):
            return
        decision = await network_check(request)
        if decision.outcome is not AccessOutcome.ALLOWED:
            raise InternalApiError(
                403,
                ApiErrorCode.ACCESS_DENIED,
                "Internal API access is denied.",
            )

    router = APIRouter(
        prefix=INTERNAL_API_PREFIX,
        include_in_schema=configuration.include_internal_routes_in_schema,
    )

    @router.post(
        "/auth/sign-in",
        response_model=SignInResponse,
        dependencies=[Depends(require_sign_in_network)],
    )
    def sign_in(payload: SignInRequest, request: Request, response: Response) -> SignInResponse:
        try:
            issued = service.sign_in(
                str(payload.email),
                payload.password.get_secret_value(),
                client_key=request.client.host if request.client else "unknown",
            )
        except AuthenticationError as error:
            status = _RATE_LIMIT_STATUS if error.code == "authentication_rate_limited" else 401
            headers = (
                (("Retry-After", str(service.configuration.login_rate_limit_window_seconds)),)
                if status == _RATE_LIMIT_STATUS
                else (("WWW-Authenticate", "Session"),)
            )
            code = (
                ApiErrorCode.AUTHENTICATION_RATE_LIMITED
                if status == _RATE_LIMIT_STATUS
                else ApiErrorCode.AUTHENTICATION_INVALID_CREDENTIALS
            )
            raise InternalApiError(status, code, "Invalid credentials.", headers=headers) from None
        response.set_cookie(
            service.configuration.session_cookie_name,
            issued.raw_token,
            max_age=service.configuration.session_lifetime_minutes * 60,
            httponly=True,
            secure=service.configuration.require_secure_cookie,
            samesite="strict",
            path=INTERNAL_API_PREFIX,
        )
        return SignInResponse(principal=_principal_schema(issued.principal))

    @router.post("/auth/sign-out", response_model=SignOutResponse, dependencies=[Depends(access)])
    def sign_out(request: Request, response: Response) -> SignOutResponse:
        principal = _principal(request)
        token = getattr(request.state, "authenticated_session_token", "")
        if hasattr(request.state, "session_replacement_token"):
            del request.state.session_replacement_token
        service.sign_out(token, actor=principal)
        response.delete_cookie(
            service.configuration.session_cookie_name,
            path=INTERNAL_API_PREFIX,
            secure=service.configuration.require_secure_cookie,
            httponly=True,
            samesite="strict",
        )
        return SignOutResponse()

    @router.get("/auth/me", response_model=PrincipalSchema, dependencies=[Depends(access)])
    def me(request: Request) -> PrincipalSchema:
        return _principal_schema(_principal(request))

    @router.post(
        "/auth/change-password", response_model=SignOutResponse, dependencies=[Depends(access)]
    )
    def change_password(payload: PasswordChangeRequest, request: Request) -> SignOutResponse:
        try:
            service.change_password(
                _principal(request),
                payload.current_password.get_secret_value(),
                payload.new_password.get_secret_value(),
            )
        except AuthenticationError as error:
            raise HTTPException(400, error.code) from None
        return SignOutResponse(signed_out=False)

    @router.get(
        "/auth/sessions", response_model=SessionListResponse, dependencies=[Depends(access)]
    )
    def sessions(request: Request) -> SessionListResponse:
        principal = _principal(request)
        if principal.user_id is None:
            raise HTTPException(403, "authorization_denied")
        return SessionListResponse(
            sessions=tuple(
                _session_schema(row)
                for row in service.list_sessions(
                    principal.user_id, current_session_id=principal.session_id
                )
            )
        )

    @router.delete(
        "/auth/sessions/{session_id}",
        response_model=SignOutResponse,
        dependencies=[Depends(access)],
    )
    def revoke_session(session_id: str, request: Request) -> SignOutResponse:
        principal = _principal(request)
        if principal.user_id is None:
            raise HTTPException(403, "authorization_denied")
        try:
            service.revoke_session(session_id, principal.user_id, actor=principal)
        except AuthenticationError as error:
            raise HTTPException(404, error.code) from None
        return SignOutResponse(signed_out=session_id == principal.session_id)

    @router.get("/auth/audit", response_model=AuditPageResponse, dependencies=[Depends(access)])
    def audit(
        limit: int = Query(50, ge=1, le=100), before_sequence: int | None = Query(None, ge=1)
    ) -> AuditPageResponse:
        rows = service.audit_page(limit=limit, before_sequence=before_sequence)
        return AuditPageResponse(
            events=tuple(
                AuditEventSchema.model_validate(row, from_attributes=True) for row in rows
            ),
            next_before_sequence=rows[-1].sequence if len(rows) == limit else None,
        )

    @router.get("/users", response_model=UserListResponse, dependencies=[Depends(access)])
    def users(
        limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
    ) -> UserListResponse:
        return UserListResponse(
            users=tuple(_user_schema(row) for row in service.list_users(limit=limit, offset=offset))
        )

    @router.post("/users", response_model=UserSchema, dependencies=[Depends(access)])
    def create_user(payload: UserCreateRequest, request: Request) -> UserSchema:
        try:
            row = service.create_user(
                str(payload.email),
                payload.display_name,
                payload.role,
                payload.password.get_secret_value(),
                payload.state,
                actor=_principal(request),
            )
        except (AuthenticationError, ValueError) as error:
            raise HTTPException(
                409 if str(error) == "user_email_conflict" else 400, str(error)
            ) from None
        return _user_schema(row)

    @router.get("/users/{user_id}", response_model=UserSchema, dependencies=[Depends(access)])
    def get_user(user_id: str) -> UserSchema:
        try:
            return _user_schema(service.get_user(user_id))
        except AuthenticationError as error:
            raise HTTPException(404, error.code) from None

    @router.patch("/users/{user_id}", response_model=UserSchema, dependencies=[Depends(access)])
    def update_user(user_id: str, payload: UserUpdateRequest, request: Request) -> UserSchema:
        try:
            return _user_schema(
                service.update_user(
                    user_id,
                    email=str(payload.email) if payload.email else None,
                    display_name=payload.display_name,
                    actor=_principal(request),
                )
            )
        except AuthenticationError as error:
            raise HTTPException(
                404 if error.code == "user_not_found" else 409, error.code
            ) from None

    def lifecycle(user_id: str, state: UserState, request: Request) -> UserSchema:
        try:
            return _user_schema(service.set_user_state(user_id, state, actor=_principal(request)))
        except AuthenticationError as error:
            raise HTTPException(404, error.code) from None

    @router.post(
        "/users/{user_id}/activate", response_model=UserSchema, dependencies=[Depends(access)]
    )
    def activate(user_id: str, request: Request) -> UserSchema:
        return lifecycle(user_id, UserState.ACTIVE, request)

    @router.post(
        "/users/{user_id}/deactivate", response_model=UserSchema, dependencies=[Depends(access)]
    )
    def deactivate(user_id: str, request: Request) -> UserSchema:
        return lifecycle(user_id, UserState.INACTIVE, request)

    @router.post(
        "/users/{user_id}/disable", response_model=UserSchema, dependencies=[Depends(access)]
    )
    def disable(user_id: str, request: Request) -> UserSchema:
        return lifecycle(user_id, UserState.DISABLED, request)

    @router.post("/users/{user_id}/role", response_model=UserSchema, dependencies=[Depends(access)])
    def role(user_id: str, payload: RoleChangeRequest, request: Request) -> UserSchema:
        try:
            return _user_schema(
                service.change_role(user_id, payload.role, actor=_principal(request))
            )
        except AuthenticationError as error:
            raise HTTPException(404, error.code) from None

    @router.post(
        "/users/{user_id}/revoke-sessions",
        response_model=SignOutResponse,
        dependencies=[Depends(access)],
    )
    def revoke_user_sessions(user_id: str, request: Request) -> SignOutResponse:
        try:
            service.revoke_user_sessions(user_id, actor=_principal(request))
        except AuthenticationError as error:
            raise HTTPException(404, error.code) from None
        return SignOutResponse(signed_out=False)

    return router


def _principal(request: Request) -> AuthenticatedPrincipal:
    principal = getattr(request.state, "authenticated_principal", None)
    if not isinstance(principal, AuthenticatedPrincipal):
        raise HTTPException(401, "authentication_required")
    return principal


def _principal_schema(value: AuthenticatedPrincipal) -> PrincipalSchema:
    return PrincipalSchema(
        user_id=value.user_id,
        email=value.email,
        display_name=value.display_name,
        role=value.role,
        permissions=tuple(sorted(permission.value for permission in value.permissions)),
        authentication_method=value.authentication_method.value,
        session_created_at=value.session_created_at,
        session_expires_at=value.session_expires_at,
        session_absolute_expires_at=value.session_absolute_expires_at,
        password_change_available=value.user_id is not None,
    )


def _user_schema(value: UserRecord) -> UserSchema:
    return UserSchema.model_validate(value, from_attributes=True)


def _session_schema(value: SessionRecord) -> SessionSummary:
    return SessionSummary.model_validate(value, from_attributes=True)
