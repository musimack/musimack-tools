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
    RECOMMENDATION_NOT_FOUND = "recommendation_not_found"
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
    METADATA_AUDIT_DISABLED = "metadata_audit_disabled"
    METADATA_AUDIT_VERSION_UNSUPPORTED = "metadata_audit_version_unsupported"
    METADATA_AUDIT_RUN_NOT_FOUND = "metadata_audit_run_not_found"
    METADATA_AUDIT_RUN_NOT_TERMINAL = "metadata_audit_run_not_terminal"
    METADATA_AUDIT_PAGE_EVIDENCE_UNAVAILABLE = "metadata_audit_page_evidence_unavailable"
    METADATA_AUDIT_ALREADY_EXISTS = "metadata_audit_already_exists"
    METADATA_AUDIT_CONFLICT = "metadata_audit_conflict"
    METADATA_AUDIT_NOT_FOUND = "metadata_audit_not_found"
    METADATA_AUDIT_PAGE_NOT_FOUND = "metadata_audit_page_not_found"
    METADATA_AUDIT_DUPLICATE_GROUP_NOT_FOUND = "metadata_audit_duplicate_group_not_found"
    METADATA_AUDIT_INVALID_FILTER = "metadata_audit_invalid_filter"
    METADATA_AUDIT_INVALID_PAGE_SIZE = "metadata_audit_invalid_page_size"
    METADATA_AUDIT_INVALID_CURSOR = "metadata_audit_invalid_cursor"
    METADATA_AUDIT_CURSOR_VERSION_UNSUPPORTED = "metadata_audit_cursor_version_unsupported"
    METADATA_AUDIT_CURSOR_FILTER_MISMATCH = "metadata_audit_cursor_filter_mismatch"
    METADATA_AUDIT_EXPORT_UNSUPPORTED = "metadata_audit_export_unsupported"
    METADATA_AUDIT_EXPORT_TOO_LARGE = "metadata_audit_export_too_large"
    METADATA_AUDIT_EXPORT_FAILED = "metadata_audit_export_failed"
    METADATA_AUDIT_PERSISTENCE_FAILED = "metadata_audit_persistence_failed"
    METADATA_AUDIT_QUERY_FAILED = "metadata_audit_query_failed"
    METADATA_AUDIT_PARTIAL = "metadata_audit_partial"
    SITEMAP_AUDIT_DISABLED = "sitemap_audit_disabled"
    SITEMAP_AUDIT_VERSION_UNSUPPORTED = "sitemap_audit_version_unsupported"
    SITEMAP_AUDIT_RUN_NOT_FOUND = "sitemap_audit_run_not_found"
    SITEMAP_AUDIT_RUN_NOT_TERMINAL = "sitemap_audit_run_not_terminal"
    SITEMAP_AUDIT_PAGE_EVIDENCE_UNAVAILABLE = "sitemap_audit_page_evidence_unavailable"
    SITEMAP_AUDIT_NOT_FOUND = "sitemap_audit_not_found"
    SITEMAP_AUDIT_ALREADY_EXISTS = "sitemap_audit_already_exists"
    SITEMAP_AUDIT_INVALID_FILTER = "sitemap_audit_invalid_filter"
    SITEMAP_AUDIT_INVALID_PAGE_SIZE = "sitemap_audit_invalid_page_size"
    SITEMAP_AUDIT_INVALID_CURSOR = "sitemap_audit_invalid_cursor"
    SITEMAP_AUDIT_CURSOR_VERSION_UNSUPPORTED = "sitemap_audit_cursor_version_unsupported"
    SITEMAP_AUDIT_CURSOR_FILTER_MISMATCH = "sitemap_audit_cursor_filter_mismatch"
    SITEMAP_AUDIT_EXPORT_UNSUPPORTED = "sitemap_audit_export_unsupported"
    SITEMAP_AUDIT_EXPORT_FAILED = "sitemap_audit_export_failed"
    SITEMAP_AUDIT_PERSISTENCE_FAILED = "sitemap_audit_persistence_failed"
    SITEMAP_AUDIT_QUERY_FAILED = "sitemap_audit_query_failed"
    SITE_AUDIT_SETTINGS_DISABLED = "site_audit_settings_disabled"
    SITE_AUDIT_SETTINGS_INVALID = "site_audit_settings_invalid"
    SITE_AUDIT_SETTINGS_CONFLICT = "site_audit_settings_conflict"
    SITE_AUDIT_PRESET_NOT_FOUND = "site_audit_preset_not_found"
    SITE_PROFILE_NOT_FOUND = "site_profile_not_found"
    SITE_PROFILE_CONFLICT = "site_profile_conflict"
    SITE_PROFILE_ARCHIVED = "site_profile_archived"
    SITE_AUDIT_RULE_TEST_LIMIT = "site_audit_rule_test_limit"
    SITE_AUDIT_RULE_PREVIEW_DEFERRED = "site_audit_rule_preview_deferred"
    SITE_AUDIT_NOT_FOUND = "site_audit_not_found"
    SITE_AUDIT_NOT_READY = "site_audit_not_ready"
    SITE_AUDIT_STATE_CONFLICT = "site_audit_state_conflict"
    SITE_AUDIT_SNAPSHOT_MISSING = "site_audit_snapshot_missing"
    SITE_AUDIT_SNAPSHOT_INTEGRITY_INVALID = "site_audit_snapshot_integrity_invalid"
    SITE_AUDIT_CRAWL_SUBMISSION_FAILED = "site_audit_crawl_submission_failed"
    SITE_AUDIT_EVIDENCE_UNAVAILABLE = "site_audit_evidence_unavailable"
    SITE_AUDIT_PROJECTION_UNAVAILABLE = "site_audit_projection_unavailable"
    SITE_AUDIT_RETRY_NOT_ALLOWED = "site_audit_retry_not_allowed"
    SITE_AUDIT_CANCELLATION_NOT_ALLOWED = "site_audit_cancellation_not_allowed"
    SITE_AUDIT_ORCHESTRATION_FAILED = "site_audit_orchestration_failed"
    LINK_AUDIT_DISABLED = "link_audit_disabled"
    LINK_AUDIT_VERSION_UNSUPPORTED = "link_audit_version_unsupported"
    LINK_AUDIT_RUN_NOT_FOUND = "link_audit_run_not_found"
    LINK_AUDIT_RUN_NOT_TERMINAL = "link_audit_run_not_terminal"
    LINK_AUDIT_PAGE_EVIDENCE_UNAVAILABLE = "link_audit_page_evidence_unavailable"
    LINK_AUDIT_LINK_EVIDENCE_UNAVAILABLE = "link_audit_link_evidence_unavailable"
    LINK_AUDIT_SCOPE_UNAVAILABLE = "link_audit_scope_unavailable"
    LINK_AUDIT_NOT_FOUND = "link_audit_not_found"
    LINK_AUDIT_ALREADY_EXISTS = "link_audit_already_exists"
    LINK_AUDIT_ALREADY_EXECUTING = "link_audit_already_executing"
    LINK_AUDIT_ALREADY_TERMINAL = "link_audit_already_terminal"
    LINK_AUDIT_INVALID_FILTER = "link_audit_invalid_filter"
    LINK_AUDIT_INVALID_PAGE_SIZE = "link_audit_invalid_page_size"
    LINK_AUDIT_INVALID_CURSOR = "link_audit_invalid_cursor"
    LINK_AUDIT_CURSOR_VERSION_UNSUPPORTED = "link_audit_cursor_version_unsupported"
    LINK_AUDIT_CURSOR_FILTER_MISMATCH = "link_audit_cursor_filter_mismatch"
    LINK_AUDIT_EXPORT_UNSUPPORTED = "link_audit_export_unsupported"
    LINK_AUDIT_EXPORT_CONFLICT = "link_audit_export_conflict"
    LINK_AUDIT_EXPORT_FAILED = "link_audit_export_failed"
    LINK_AUDIT_PERSISTENCE_FAILED = "link_audit_persistence_failed"
    LINK_AUDIT_QUERY_FAILED = "link_audit_query_failed"
    INTERNAL_LINK_DISABLED = "internal_link_disabled"
    INTERNAL_LINK_VERSION_UNSUPPORTED = "internal_link_version_unsupported"
    INTERNAL_LINK_RUN_NOT_FOUND = "internal_link_run_not_found"
    INTERNAL_LINK_RUN_NOT_TERMINAL = "internal_link_run_not_terminal"
    INTERNAL_LINK_PAGE_EVIDENCE_UNAVAILABLE = "internal_link_page_evidence_unavailable"
    INTERNAL_LINK_LINK_EVIDENCE_UNAVAILABLE = "internal_link_link_evidence_unavailable"
    INTERNAL_LINK_SCOPE_UNAVAILABLE = "internal_link_scope_unavailable"
    INTERNAL_LINK_AUDIT_NOT_FOUND = "internal_link_audit_not_found"
    INTERNAL_LINK_ALREADY_EXISTS = "internal_link_already_exists"
    INTERNAL_LINK_ALREADY_EXECUTING = "internal_link_already_executing"
    INTERNAL_LINK_ALREADY_TERMINAL = "internal_link_already_terminal"
    INTERNAL_LINK_INVALID_FILTER = "internal_link_invalid_filter"
    INTERNAL_LINK_INVALID_PAGE_SIZE = "internal_link_invalid_page_size"
    INTERNAL_LINK_INVALID_CURSOR = "internal_link_invalid_cursor"
    INTERNAL_LINK_CURSOR_VERSION_UNSUPPORTED = "internal_link_cursor_version_unsupported"
    INTERNAL_LINK_CURSOR_FILTER_MISMATCH = "internal_link_cursor_filter_mismatch"
    INTERNAL_LINK_EXPORT_UNSUPPORTED = "internal_link_export_unsupported"
    INTERNAL_LINK_EXPORT_CONFLICT = "internal_link_export_conflict"
    INTERNAL_LINK_EXPORT_FAILED = "internal_link_export_failed"
    INTERNAL_LINK_PERSISTENCE_FAILED = "internal_link_persistence_failed"
    INTERNAL_LINK_QUERY_FAILED = "internal_link_query_failed"
    IMAGE_AUDIT_DISABLED = "image_audit_disabled"
    IMAGE_AUDIT_VERSION_UNSUPPORTED = "image_audit_version_unsupported"
    IMAGE_AUDIT_RUN_NOT_FOUND = "image_audit_run_not_found"
    IMAGE_AUDIT_RUN_NOT_TERMINAL = "image_audit_run_not_terminal"
    IMAGE_AUDIT_PAGE_EVIDENCE_UNAVAILABLE = "image_audit_page_evidence_unavailable"
    IMAGE_AUDIT_IMAGE_EVIDENCE_UNAVAILABLE = "image_audit_image_evidence_unavailable"
    IMAGE_AUDIT_SCOPE_UNAVAILABLE = "image_audit_scope_unavailable"
    IMAGE_AUDIT_NOT_FOUND = "image_audit_not_found"
    IMAGE_AUDIT_ALREADY_EXISTS = "image_audit_already_exists"
    IMAGE_AUDIT_ALREADY_EXECUTING = "image_audit_already_executing"
    IMAGE_AUDIT_ALREADY_TERMINAL = "image_audit_already_terminal"
    IMAGE_AUDIT_INVALID_FILTER = "image_audit_invalid_filter"
    IMAGE_AUDIT_INVALID_PAGE_SIZE = "image_audit_invalid_page_size"
    IMAGE_AUDIT_INVALID_CURSOR = "image_audit_invalid_cursor"
    IMAGE_AUDIT_CURSOR_FILTER_MISMATCH = "image_audit_cursor_filter_mismatch"
    IMAGE_AUDIT_EXPORT_UNSUPPORTED = "image_audit_export_unsupported"
    IMAGE_AUDIT_EXPORT_CONFLICT = "image_audit_export_conflict"
    IMAGE_AUDIT_EXPORT_FAILED = "image_audit_export_failed"
    IMAGE_AUDIT_VERIFICATION_LIMIT_EXCEEDED = "image_audit_verification_limit_exceeded"
    IMAGE_AUDIT_UNSAFE_TARGET_BLOCKED = "image_audit_unsafe_target_blocked"
    IMAGE_AUDIT_QUERY_FAILED = "image_audit_query_failed"
    STRUCTURED_DATA_AUDIT_RUN_NOT_FOUND = "structured_data_audit_run_not_found"
    STRUCTURED_DATA_AUDIT_RUN_NOT_TERMINAL = "structured_data_audit_run_not_terminal"
    STRUCTURED_DATA_AUDIT_NOT_FOUND = "structured_data_audit_not_found"
    STRUCTURED_DATA_AUDIT_ALREADY_TERMINAL = "structured_data_audit_already_terminal"
    STRUCTURED_DATA_AUDIT_INVALID_PAGE_SIZE = "structured_data_audit_invalid_page_size"
    STRUCTURED_DATA_AUDIT_INVALID_CURSOR = "structured_data_audit_invalid_cursor"
    STRUCTURED_DATA_AUDIT_CURSOR_FILTER_MISMATCH = "structured_data_audit_cursor_filter_mismatch"
    STRUCTURED_DATA_AUDIT_QUERY_FAILED = "structured_data_audit_query_failed"
    MIGRATION_QA_RUN_NOT_FOUND = "migration_qa_run_not_found"
    MIGRATION_QA_PROJECT_NOT_FOUND = "migration_qa_project_not_found"
    MIGRATION_QA_MISSING_EVIDENCE = "migration_qa_missing_evidence"
    MIGRATION_QA_ALREADY_TERMINAL = "migration_qa_already_terminal"
    MIGRATION_QA_INVALID_PAGE_SIZE = "migration_qa_invalid_page_size"
    MIGRATION_QA_CURSOR_MISMATCH = "migration_qa_cursor_mismatch"
    MIGRATION_QA_QUERY_FAILED = "migration_qa_query_failed"


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
