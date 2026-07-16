"""Immutable contracts for the private internal HTTP adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from musimack_tools.api.access import InternalAccessVerifier

INTERNAL_API_VERSION = "seo-toolkit-internal-api-v1"
INTERNAL_API_PREFIX = "/api/internal/v1"
_INVALID_API_VERSION = "unsupported internal API version"
_INVALID_API_PREFIX = "unsupported internal API route prefix"
_INVALID_API_BOUND = "internal API bounds must be positive"
_ALLOWED_WITH_REASON = "allowed access decisions cannot include a denial reason"
_DENIED_WITHOUT_REASON = "denied access decisions require a stable reason"


class AccessOutcome(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


class AccessDenialReason(StrEnum):
    ACCESS_NOT_CONFIGURED = "access_not_configured"
    ACCESS_DENIED = "access_denied"
    ACCESS_VERIFIER_UNAVAILABLE = "access_verifier_unavailable"
    AUTHENTICATION_REQUIRED = "authentication_required"
    AUTHENTICATION_FAILED = "authentication_failed"
    TRUSTED_NETWORK_REQUIRED = "trusted_network_required"
    SECURITY_CONFIGURATION_UNAVAILABLE = "security_configuration_unavailable"
    INVALID_FORWARDED_HEADER = "invalid_forwarded_header"
    INTERNAL_API_DISABLED = "internal_api_disabled"
    AUTHORIZATION_DENIED = "authorization_denied"


class ApiErrorCode(StrEnum):
    ACCESS_DENIED = "access_denied"
    ACCESS_VERIFIER_UNAVAILABLE = "access_verifier_unavailable"
    REQUEST_VALIDATION_FAILED = "request_validation_failed"
    REQUEST_BODY_TOO_LARGE = "request_body_too_large"
    APPLICATION_VALIDATION_FAILED = "application_validation_failed"
    PREFLIGHT_BLOCKED = "preflight_blocked"
    ACTIVE_DUPLICATE = "active_duplicate"
    QUEUE_CAPACITY_REACHED = "queue_capacity_reached"
    REGISTRY_CLOSED = "registry_closed"
    REGISTRY_SHUTTING_DOWN = "registry_shutting_down"
    JOB_ID_INVALID = "job_id_invalid"
    JOB_NOT_FOUND = "job_not_found"
    JOB_RESULT_UNAVAILABLE = "job_result_unavailable"
    JOB_ALREADY_TERMINAL = "job_already_terminal"
    JOB_CANCELLATION_ALREADY_REQUESTED = "job_cancellation_already_requested"
    INTERNAL_SERVICE_UNAVAILABLE = "internal_service_unavailable"
    INTERNAL_API_ERROR = "internal_api_error"
    AUTHENTICATION_REQUIRED = "authentication_required"
    AUTHENTICATION_FAILED = "authentication_failed"
    TRUSTED_NETWORK_REQUIRED = "trusted_network_required"
    SECURITY_CONFIGURATION_UNAVAILABLE = "security_configuration_unavailable"
    INVALID_FORWARDED_HEADER = "invalid_forwarded_header"
    INTERNAL_API_DISABLED = "internal_api_disabled"
    AUTHORIZATION_DENIED = "authorization_denied"
    AUTHENTICATION_DISABLED = "authentication_disabled"
    AUTHENTICATION_MODE_UNSUPPORTED = "authentication_mode_unsupported"
    AUTHENTICATION_VERSION_UNSUPPORTED = "authentication_version_unsupported"
    AUTHENTICATION_INVALID_CREDENTIALS = "authentication_invalid_credentials"
    AUTHENTICATION_ACCOUNT_INACTIVE = "authentication_account_inactive"
    AUTHENTICATION_ACCOUNT_DISABLED = "authentication_account_disabled"
    AUTHENTICATION_ACCOUNT_LOCKED = "authentication_account_locked"
    AUTHENTICATION_RATE_LIMITED = "authentication_rate_limited"
    AUTHENTICATION_SESSION_MISSING = "authentication_session_missing"
    AUTHENTICATION_SESSION_INVALID = "authentication_session_invalid"
    AUTHENTICATION_SESSION_EXPIRED = "authentication_session_expired"
    AUTHENTICATION_SESSION_REVOKED = "authentication_session_revoked"
    AUTHENTICATION_SESSION_ROTATION_REQUIRED = "authentication_session_rotation_required"
    AUTHENTICATION_PASSWORD_INVALID = "authentication_password_invalid"  # noqa: S105
    AUTHENTICATION_PASSWORD_REUSED = "authentication_password_reused"  # noqa: S105
    AUTHENTICATION_PASSWORD_CHANGE_REQUIRED = "authentication_password_change_required"  # noqa: S105
    AUTHORIZATION_ROLE_INVALID = "authorization_role_invalid"
    AUTHORIZATION_PERMISSION_INVALID = "authorization_permission_invalid"
    USER_NOT_FOUND = "user_not_found"
    USER_EMAIL_CONFLICT = "user_email_conflict"
    USER_STATE_INVALID = "user_state_invalid"
    USER_ROLE_INVALID = "user_role_invalid"
    USER_BOOTSTRAP_NOT_ALLOWED = "user_bootstrap_not_allowed"
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_REVOCATION_NOT_ALLOWED = "session_revocation_not_allowed"
    AUTH_AUDIT_QUERY_INVALID = "auth_audit_query_invalid"
    AUTH_QUERY_FAILED = "auth_query_failed"
    ARTIFACT_NOT_FOUND = "artifact_not_found"
    ARTIFACT_NOT_AVAILABLE = "artifact_not_available"
    ARTIFACT_RETRIEVAL_FAILED = "artifact_retrieval_failed"
    HISTORY_DISABLED = "history_disabled"
    HISTORY_INVALID_PAGE_SIZE = "history_invalid_page_size"
    HISTORY_INVALID_CURSOR = "history_invalid_cursor"
    HISTORY_CURSOR_VERSION_UNSUPPORTED = "history_cursor_version_unsupported"
    HISTORY_CURSOR_FILTER_MISMATCH = "history_cursor_filter_mismatch"
    HISTORY_JOB_NOT_FOUND = "history_job_not_found"
    HISTORY_RUN_NOT_FOUND = "history_run_not_found"
    HISTORY_QUERY_FAILED = "history_query_failed"


class ResponseDiagnosticsPolicy(StrEnum):
    OMIT = "omit"
    BOUNDED = "bounded"


@dataclass(frozen=True, slots=True)
class InternalCallerContext:
    caller_id: str | None = None


@dataclass(frozen=True, slots=True)
class AccessDecision:
    outcome: AccessOutcome
    reason: AccessDenialReason | None = None
    caller: InternalCallerContext | None = None

    def __post_init__(self) -> None:
        if self.outcome is AccessOutcome.ALLOWED and self.reason is not None:
            raise ValueError(_ALLOWED_WITH_REASON)
        if self.outcome is not AccessOutcome.ALLOWED and self.reason is None:
            raise ValueError(_DENIED_WITHOUT_REASON)


@dataclass(frozen=True, slots=True)
class InternalApiConfiguration:
    mount_internal_routes: bool = False
    include_internal_routes_in_schema: bool = False
    include_internal_endpoints_in_docs: bool = False
    maximum_request_body_bytes: int = 65_536
    maximum_validation_details: int = 25
    maximum_approved_hosts: int = 32
    maximum_url_characters: int = 4_096
    maximum_history_events: int = 50
    response_diagnostics_policy: ResponseDiagnosticsPolicy = ResponseDiagnosticsPolicy.OMIT
    access_verifier: InternalAccessVerifier | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    api_version: str = INTERNAL_API_VERSION
    route_prefix: str = INTERNAL_API_PREFIX

    def __post_init__(self) -> None:
        if self.api_version != INTERNAL_API_VERSION:
            raise ValueError(_INVALID_API_VERSION)
        if self.route_prefix != INTERNAL_API_PREFIX:
            raise ValueError(_INVALID_API_PREFIX)
        bounds = (
            self.maximum_request_body_bytes,
            self.maximum_validation_details,
            self.maximum_approved_hosts,
            self.maximum_url_characters,
            self.maximum_history_events,
        )
        if any(value < 1 for value in bounds):
            raise ValueError(_INVALID_API_BOUND)


@dataclass(frozen=True, slots=True)
class InternalApiError(Exception):
    status_code: int
    code: ApiErrorCode
    message: str
    details: tuple[ApiErrorDetail, ...] = ()
    headers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ApiErrorDetail:
    code: str
    message: str
    field: str | None = None
    source_code: str | None = None
