"""Versioned, immutable authentication and authorization contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

AUTHENTICATION_VERSION = "seo-toolkit-authentication-v1"
AUTHORIZATION_VERSION = "seo-toolkit-authorization-v1"
SESSION_VERSION = "seo-toolkit-session-v1"
AUTH_AUDIT_VERSION = "seo-toolkit-auth-audit-v1"
AUTH_COMPATIBILITY_VERSION = "seo-toolkit-auth-compatibility-v1"
PASSWORD_ALGORITHM = "pbkdf2-hmac-sha256"  # noqa: S105 - algorithm identifier.
PASSWORD_FORMAT_VERSION = "password-hash-v1"  # noqa: S105 - version identifier.
SESSION_TOKEN_ALGORITHM = "sha256"  # noqa: S105 - algorithm identifier.
SESSION_COOKIE_NAME = "musimack_session"
_MINIMUM_PASSWORD_LENGTH = 8
_MAXIMUM_PASSWORD_LENGTH = 1024
_MINIMUM_HASH_ITERATIONS = 600_000
_MINUTES_PER_DAY = 1440
_MINUTES_PER_WEEK = 10_080
_MAXIMUM_POLICY_COUNT = 100
_MAXIMUM_RATE_WINDOW = 86_400
_MAXIMUM_RATE_ATTEMPTS = 1000
_MAXIMUM_EMAIL_LENGTH = 320
_CONTROL_CHARACTER_BOUNDARY = 32


class AuthenticationMode(StrEnum):
    SHARED_BEARER = "shared_bearer"
    USER_SESSION = "user_session"
    HYBRID = "hybrid"


class UserRole(StrEnum):
    ADMINISTRATOR = "administrator"
    OPERATOR = "operator"
    VIEWER = "viewer"


class UserState(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DISABLED = "disabled"


class PrincipalType(StrEnum):
    USER = "user"
    SHARED_BEARER = "shared_bearer"


class AuthenticationMethod(StrEnum):
    PASSWORD_SESSION = "password_session"  # noqa: S105 - method identifier.
    SHARED_BEARER = "shared_bearer"


class Permission(StrEnum):
    JOBS_SUBMIT = "jobs.submit"
    JOBS_CANCEL = "jobs.cancel"
    JOBS_VIEW = "jobs.view"
    RUNS_VIEW = "runs.view"
    HISTORY_VIEW = "history.view"
    ARTIFACTS_VIEW = "artifacts.view"
    ARTIFACTS_DOWNLOAD = "artifacts.download"
    DIAGNOSTICS_VIEW = "diagnostics.view"
    DIAGNOSTICS_VIEW_SENSITIVE = "diagnostics.view_sensitive"
    USERS_VIEW = "users.view"
    USERS_CREATE = "users.create"
    USERS_UPDATE = "users.update"
    USERS_ACTIVATE = "users.activate"
    USERS_DEACTIVATE = "users.deactivate"
    USERS_CHANGE_ROLE = "users.change_role"
    SESSIONS_VIEW_OWN = "sessions.view_own"
    SESSIONS_REVOKE_OWN = "sessions.revoke_own"
    SESSIONS_REVOKE_ANY = "sessions.revoke_any"
    PASSWORD_CHANGE_OWN = "password.change_own"  # noqa: S105 - permission identifier.
    PASSWORD_RESET_OTHER = "password.reset_other"  # noqa: S105 - permission identifier.
    AUTH_AUDIT_VIEW = "auth_audit.view"
    SETTINGS_VIEW = "settings.view"
    SETTINGS_MANAGE = "settings.manage"


_VIEWER = frozenset(
    {
        Permission.JOBS_VIEW,
        Permission.RUNS_VIEW,
        Permission.HISTORY_VIEW,
        Permission.ARTIFACTS_VIEW,
        Permission.ARTIFACTS_DOWNLOAD,
        Permission.DIAGNOSTICS_VIEW,
        Permission.SESSIONS_VIEW_OWN,
        Permission.SESSIONS_REVOKE_OWN,
        Permission.PASSWORD_CHANGE_OWN,
        Permission.SETTINGS_VIEW,
    }
)
_OPERATOR = _VIEWER | {Permission.JOBS_SUBMIT, Permission.JOBS_CANCEL}
ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.VIEWER: _VIEWER,
    UserRole.OPERATOR: _OPERATOR,
    UserRole.ADMINISTRATOR: frozenset(Permission),
}


def permissions_for_role(role: UserRole | str) -> frozenset[Permission]:
    """Return the centralized mapping, denying unknown roles."""
    try:
        parsed = UserRole(role)
    except ValueError:
        return frozenset()
    return ROLE_PERMISSIONS.get(parsed, frozenset())


def is_authorized(role: UserRole | str, permission: Permission | str) -> bool:
    """Deny unknown roles and permissions by default."""
    try:
        parsed = Permission(permission)
    except ValueError:
        return False
    return parsed in permissions_for_role(role)


@dataclass(frozen=True, slots=True)
class AuthenticationConfiguration:
    enabled: bool = False
    mode: AuthenticationMode = AuthenticationMode.SHARED_BEARER
    authentication_version: str = AUTHENTICATION_VERSION
    authorization_version: str = AUTHORIZATION_VERSION
    session_version: str = SESSION_VERSION
    auth_audit_version: str = AUTH_AUDIT_VERSION
    compatibility_version: str = AUTH_COMPATIBILITY_VERSION
    session_cookie_name: str = SESSION_COOKIE_NAME
    session_lifetime_minutes: int = 480
    session_idle_timeout_minutes: int = 60
    session_rotation_minutes: int = 30
    session_absolute_max_minutes: int = 1440
    session_max_active_per_user: int = 10
    password_min_length: int = 14
    password_max_length: int = 256
    password_hash_iterations: int = 600_000
    password_max_failed_attempts: int = 10
    password_lockout_minutes: int = 15
    login_rate_limit_window_seconds: int = 300
    login_rate_limit_max_attempts: int = 20
    shared_bearer_compatibility_enabled: bool = True
    shared_bearer_compatibility_admin: bool = True
    require_secure_cookie: bool = True
    same_site_policy: str = "strict"

    def __post_init__(self) -> None:  # noqa: C901, PLR0912
        versions = (
            (self.authentication_version, AUTHENTICATION_VERSION),
            (self.authorization_version, AUTHORIZATION_VERSION),
            (self.session_version, SESSION_VERSION),
            (self.auth_audit_version, AUTH_AUDIT_VERSION),
            (self.compatibility_version, AUTH_COMPATIBILITY_VERSION),
        )
        if any(actual != expected for actual, expected in versions):
            raise ValueError("authentication_version_unsupported")
        if not 1 <= self.session_lifetime_minutes <= _MINUTES_PER_DAY:
            raise ValueError("authentication_session_lifetime_invalid")
        if not 1 <= self.session_idle_timeout_minutes < self.session_absolute_max_minutes:
            raise ValueError("authentication_session_idle_timeout_invalid")
        if not 1 <= self.session_rotation_minutes < self.session_lifetime_minutes:
            raise ValueError("authentication_session_rotation_invalid")
        if not (
            self.session_lifetime_minutes <= self.session_absolute_max_minutes <= _MINUTES_PER_WEEK
        ):
            raise ValueError("authentication_session_absolute_lifetime_invalid")
        if not 1 <= self.session_max_active_per_user <= _MAXIMUM_POLICY_COUNT:
            raise ValueError("authentication_session_limit_invalid")
        if not (
            _MINIMUM_PASSWORD_LENGTH
            <= self.password_min_length
            <= self.password_max_length
            <= _MAXIMUM_PASSWORD_LENGTH
        ):
            raise ValueError("authentication_password_bounds_invalid")
        if self.password_hash_iterations < _MINIMUM_HASH_ITERATIONS:
            raise ValueError("authentication_password_iterations_invalid")
        if not 1 <= self.password_max_failed_attempts <= _MAXIMUM_POLICY_COUNT:
            raise ValueError("authentication_failed_attempt_limit_invalid")
        if not 1 <= self.password_lockout_minutes <= _MINUTES_PER_DAY:
            raise ValueError("authentication_lockout_invalid")
        if not 1 <= self.login_rate_limit_window_seconds <= _MAXIMUM_RATE_WINDOW:
            raise ValueError("authentication_rate_window_invalid")
        if not 1 <= self.login_rate_limit_max_attempts <= _MAXIMUM_RATE_ATTEMPTS:
            raise ValueError("authentication_rate_limit_invalid")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.session_cookie_name):
            raise ValueError("authentication_cookie_name_invalid")
        if self.same_site_policy != "strict":
            raise ValueError("authentication_cookie_same_site_invalid")


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    principal_type: PrincipalType
    authentication_method: AuthenticationMethod
    role: UserRole
    permissions: frozenset[Permission]
    user_id: str | None = None
    email: str | None = None
    display_name: str | None = None
    session_id: str | None = None
    session_created_at: datetime | None = None
    session_expires_at: datetime | None = None
    session_absolute_expires_at: datetime | None = None

    def allows(self, permission: Permission | str) -> bool:
        try:
            return Permission(permission) in self.permissions
        except ValueError:
            return False


@dataclass(frozen=True, slots=True)
class PasswordHash:
    encoded_hash: str
    salt_hex: str
    iterations: int
    algorithm: str = PASSWORD_ALGORITHM
    version: str = PASSWORD_FORMAT_VERSION


@dataclass(frozen=True, slots=True)
class AuthenticationDiagnostics:
    enabled: bool
    mode: AuthenticationMode
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


def normalize_email(value: str) -> str:
    normalized = value.strip().casefold()
    if len(normalized) > _MAXIMUM_EMAIL_LENGTH or not re.fullmatch(r"[^@\s]+@[^@\s]+", normalized):
        raise ValueError("authentication_email_invalid")
    return normalized


def validate_password(
    password: str,
    *,
    email: str,
    display_name: str,
    configuration: AuthenticationConfiguration,
) -> None:
    if not configuration.password_min_length <= len(password) <= configuration.password_max_length:
        raise ValueError("authentication_password_invalid")
    if not password.strip() or any(
        ord(character) < _CONTROL_CHARACTER_BOUNDARY for character in password
    ):
        raise ValueError("authentication_password_invalid")
    comparable = password.strip().casefold()
    if comparable in {normalize_email(email), display_name.strip().casefold()}:
        raise ValueError("authentication_password_invalid")
    if comparable in {"password", "password123", "changeme", "letmein"}:
        raise ValueError("authentication_password_invalid")
