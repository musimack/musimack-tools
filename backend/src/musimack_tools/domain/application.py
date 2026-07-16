"""Immutable contracts for the internal application-service boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from musimack_tools.domain.sitemap_publication import ExistingFilePolicy

if TYPE_CHECKING:
    from pathlib import Path

    from musimack_tools.domain.job import JobProgressView
    from musimack_tools.domain.job_registry import JobRegistrySnapshot, JobShutdownResult
    from musimack_tools.domain.run import CrawlRunRequest
    from musimack_tools.domain.run_summary import RunSummaryConfiguration
    from musimack_tools.domain.sitemap_publication import SitemapPublicationConfiguration

APPLICATION_SERVICE_VERSION = "seo-toolkit-application-service-v1"
_UNSUPPORTED_SERVICE_VERSION = "unsupported application service version"
_INVALID_PROJECTION_BOUNDS = "projection bounds must be positive"


class CrawlProfileName(StrEnum):
    QUICK_AUDIT = "quick_audit"
    STANDARD_CRAWL = "standard_crawl"
    DEEP_CRAWL = "deep_crawl"
    SITEMAP_ONLY = "sitemap_only"


class ScopeProfile(StrEnum):
    EXACT_HOST = "exact_host"
    INCLUDE_SUBDOMAINS = "include_subdomains"
    APPROVED_HOSTS = "approved_hosts"


class RecommendationProfile(StrEnum):
    STANDARD = "standard"
    STRICT = "strict"


class ValidationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationIssueCode(StrEnum):
    INVALID_SEED_URL = "invalid_seed_url"
    UNSUPPORTED_SCHEME = "unsupported_scheme"
    MISSING_HOST = "missing_host"
    UNSUPPORTED_PROFILE = "unsupported_profile"
    INVALID_APPROVED_HOST = "invalid_approved_host"
    DUPLICATE_APPROVED_HOST = "duplicate_approved_host"
    CONFLICTING_SCOPE_OPTIONS = "conflicting_scope_options"
    OVERRIDE_ABOVE_MAXIMUM = "override_above_maximum"
    OVERRIDE_BELOW_MINIMUM = "override_below_minimum"
    INVALID_OVERRIDE = "invalid_override"
    INVALID_STAGE_DEPENDENCY = "invalid_stage_dependency"
    PUBLICATION_ROOT_MISSING = "publication_root_missing"
    SUMMARY_ROOT_MISSING = "summary_root_missing"
    UNSAFE_OUTPUT_ROOT = "unsafe_output_root"
    INVALID_CALLER_LABEL = "invalid_caller_label"
    PUBLICATION_DISABLED = "publication_disabled"
    SUMMARY_DISABLED = "summary_disabled"
    DEEP_PROFILE_SELECTED = "deep_profile_selected"
    CROSS_HOST_SCOPE_ENABLED = "cross_host_scope_enabled"
    LARGE_CRAWL_CONFIGURATION = "large_crawl_configuration"
    PUBLICATION_OVERWRITE_ENABLED = "publication_overwrite_enabled"
    REQUEST_PREPARED = "request_prepared"


class PreflightState(StrEnum):
    READY = "ready"
    LIKELY_QUEUED = "likely_queued"
    BLOCKED = "blocked"


class PreflightCode(StrEnum):
    VALIDATION_FAILED = "validation_failed"
    IMMEDIATE_CAPACITY = "immediate_capacity"
    LIKELY_QUEUED = "likely_queued"
    QUEUE_FULL = "queue_full"
    ACTIVE_DUPLICATE = "active_duplicate"
    REGISTRY_NOT_ACCEPTING = "registry_not_accepting"
    OUTPUT_ROOT_READY = "output_root_ready"
    OUTPUT_ROOT_CREATION_REQUIRED = "output_root_creation_required"
    OUTPUT_ROOT_BLOCKED = "output_root_blocked"
    TARGET_CONFLICT = "target_conflict"
    DRY_RUN = "dry_run"
    ADVISORY_ONLY = "advisory_only"


class ReadinessState(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    NOT_READY = "not_ready"


class ReadinessCheckCode(StrEnum):
    SERVICE_INITIALIZED = "service_initialized"
    REGISTRY_ACCEPTING = "registry_accepting"
    REGISTRY_SHUTTING_DOWN = "registry_shutting_down"
    REGISTRY_CLOSED = "registry_closed"
    COORDINATOR_AVAILABLE = "coordinator_available"
    CRAWL_AVAILABLE = "crawl_available"
    ROBOTS_AVAILABLE = "robots_available"
    RECOMMENDATION_AVAILABLE = "recommendation_available"
    XML_AVAILABLE = "xml_available"
    PUBLICATION_AVAILABLE = "publication_available"
    SUMMARY_AVAILABLE = "summary_available"
    VERSIONS_RECOGNIZED = "versions_recognized"
    QUEUE_CAPACITY_AVAILABLE = "queue_capacity_available"
    QUEUE_FULL = "queue_full"
    RETENTION_DISABLED = "retention_disabled"


class ApplicationOutcomeCode(StrEnum):
    FOUND = "found"
    ACCEPTED = "accepted"
    QUEUED = "queued"
    DUPLICATE_RETURNED = "duplicate_returned"
    VALIDATION_FAILED = "validation_failed"
    PREFLIGHT_BLOCKED = "preflight_blocked"
    REGISTRY_CLOSED = "registry_closed"
    ACTIVE_DUPLICATE = "active_duplicate"
    QUEUE_CAPACITY_REACHED = "queue_capacity_reached"
    JOB_NOT_FOUND = "job_not_found"
    CANCELLATION_REQUESTED = "cancellation_requested"
    CANCELLED_WHILE_QUEUED = "cancelled_while_queued"
    ALREADY_REQUESTED = "already_requested"
    ALREADY_TERMINAL = "already_terminal"
    RESULT_UNAVAILABLE = "result_unavailable"
    INTERNAL_SERVICE_UNAVAILABLE = "internal_service_unavailable"


@dataclass(frozen=True, slots=True)
class CrawlLimitOverrides:
    maximum_urls: int | None = None
    maximum_depth: int | None = None
    maximum_duration_seconds: float | None = None
    maximum_accepted_bytes: int | None = None
    maximum_concurrency: int | None = None
    maximum_queue_size: int | None = None
    minimum_request_delay_seconds: float | None = None
    maximum_redirect_hops: int | None = None
    maximum_response_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class ApplicationCrawlLimits:
    maximum_urls: int
    maximum_depth: int
    maximum_duration_seconds: float
    maximum_accepted_bytes: int
    maximum_concurrency: int
    maximum_queue_size: int
    minimum_request_delay_seconds: float
    maximum_redirect_hops: int
    maximum_response_bytes: int


@dataclass(frozen=True, slots=True)
class CrawlProfile:
    name: CrawlProfileName
    limits: ApplicationCrawlLimits
    recommendation_requested: bool
    xml_requested: bool
    summary_requested: bool
    publication_requested: bool = False


@dataclass(frozen=True, slots=True)
class RawApplicationCrawlRequest:
    seed_url: str
    scope_profile: ScopeProfile | str = ScopeProfile.EXACT_HOST
    approved_hosts: tuple[str, ...] = ()
    crawl_profile: CrawlProfileName | str = CrawlProfileName.STANDARD_CRAWL
    overrides: CrawlLimitOverrides = field(default_factory=CrawlLimitOverrides)
    recommendation_profile: RecommendationProfile | str = RecommendationProfile.STANDARD
    recommendation_requested: bool | None = None
    xml_generation_requested: bool | None = None
    publication_requested: bool = False
    publication_dry_run: bool = False
    publication_root: Path | None = None
    existing_file_policy: ExistingFilePolicy = ExistingFilePolicy.FAIL_IF_EXISTS
    create_publication_directory: bool = False
    summary_writing_requested: bool | None = None
    summary_root: Path | None = None
    create_summary_directory: bool = False
    summary_dry_run: bool = False
    caller_label: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: ValidationSeverity
    code: ValidationIssueCode
    message: str
    field: str | None = None
    supplied_value: str | int | float | bool | None = None


@dataclass(frozen=True, slots=True)
class PreparedApplicationRequest:
    run_request: CrawlRunRequest
    run_id: str
    normalized_seed_url: str
    selected_profile: CrawlProfileName
    effective_limits: ApplicationCrawlLimits
    requested_stages: tuple[str, ...]
    scope_summary: str
    publication_configuration: SitemapPublicationConfiguration | None
    summary_configuration: RunSummaryConfiguration | None
    application_service_version: str = APPLICATION_SERVICE_VERSION


@dataclass(frozen=True, slots=True)
class ApplicationValidationReport:
    valid: bool
    issues: tuple[ValidationIssue, ...]
    normalized_seed_url: str | None
    selected_profile: str
    requested_stages: tuple[str, ...]
    effective_limits: ApplicationCrawlLimits | None
    scope_summary: str | None
    publication_requested: bool
    summary_requested: bool
    run_id: str | None
    downstream_versions: tuple[tuple[str, str], ...]
    application_service_version: str = APPLICATION_SERVICE_VERSION

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(item for item in self.issues if item.severity is ValidationSeverity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(item for item in self.issues if item.severity is ValidationSeverity.WARNING)

    @property
    def information(self) -> tuple[ValidationIssue, ...]:
        return tuple(item for item in self.issues if item.severity is ValidationSeverity.INFO)


@dataclass(frozen=True, slots=True)
class ApplicationPreparationResult:
    report: ApplicationValidationReport
    prepared: PreparedApplicationRequest | None


@dataclass(frozen=True, slots=True)
class PreflightFinding:
    severity: ValidationSeverity
    code: PreflightCode
    message: str


@dataclass(frozen=True, slots=True)
class ApplicationPreflightResult:
    state: PreflightState
    validation: ApplicationValidationReport
    findings: tuple[PreflightFinding, ...]
    registry_snapshot: JobRegistrySnapshot
    active_duplicate_job_id: str | None
    likely_queue_position: int | None
    application_service_version: str = APPLICATION_SERVICE_VERSION


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    code: ReadinessCheckCode
    state: ReadinessState
    message: str


@dataclass(frozen=True, slots=True)
class ApplicationReadinessReport:
    state: ReadinessState
    checks: tuple[ReadinessCheck, ...]
    active_jobs: int
    queued_jobs: int
    retained_terminal_jobs: int
    application_service_version: str = APPLICATION_SERVICE_VERSION


@dataclass(frozen=True, slots=True)
class ApplicationWarning:
    code: str
    source_layer: str
    source_code: str
    severity: ValidationSeverity
    message: str
    url: str | None = None


@dataclass(frozen=True, slots=True)
class ApplicationJobStatus:
    outcome: ApplicationOutcomeCode
    job_id: str | None
    run_id: str | None
    attempt_number: int | None
    state: str | None
    queue_position: int | None
    active_stage: str | None
    run_lifecycle: str | None
    urls_discovered: int
    urls_fetched: int
    recommendation_counts: tuple[int, int, int, int] | None
    xml_document_count: int | None
    xml_entry_count: int | None
    publication_file_count: int | None
    warning_count: int
    failure_count: int
    cancellation_requested: bool
    terminal: bool
    result_available: bool
    registry_version: str | None
    application_service_version: str = APPLICATION_SERVICE_VERSION


@dataclass(frozen=True, slots=True)
class ApplicationJobList:
    items: tuple[ApplicationJobStatus, ...]
    truncated: bool
    maximum: int
    application_service_version: str = APPLICATION_SERVICE_VERSION


@dataclass(frozen=True, slots=True)
class RecommendationItemProjection:
    url: str
    requested_url: str
    final_url: str | None
    state: str
    determinacy: str
    primary_reason: str
    explanation: str
    http_status: int | None
    content_type: str | None
    fetch_failure_code: str | None
    canonical_url: str | None
    canonical_conflicting: bool
    redirect_source: bool
    redirect_hops: int
    redirect_final_url: str | None
    robots_available: bool
    robots_allowed: bool | None
    robots_reason_code: str | None
    generic_directives: tuple[str, ...]
    crawler_specific_directives: tuple[str, ...]
    indexability_conflict: bool
    configured_exclusions: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ApplicationRecommendationPage:
    outcome: ApplicationOutcomeCode
    job_id: str | None
    run_id: str | None
    offset: int
    limit: int
    total: int
    returned_count: int
    has_more: bool
    items: tuple[RecommendationItemProjection, ...]
    rule_set_version: str | None
    application_service_version: str = APPLICATION_SERVICE_VERSION


@dataclass(frozen=True, slots=True)
class ApplicationResultProjection:
    outcome: ApplicationOutcomeCode
    job_id: str | None
    run_id: str | None
    attempt_number: int | None
    job_state: str | None
    run_lifecycle: str | None
    stage_states: tuple[tuple[str, str], ...]
    crawl_counts: tuple[tuple[str, int], ...]
    crawl_error_codes: tuple[str, ...]
    recommendation_counts: tuple[tuple[str, int], ...]
    xml_document_count: int | None
    xml_entry_count: int | None
    publication_state: str | None
    published_file_count: int
    publication_filenames: tuple[str, ...]
    manifest_sha256: str | None
    summary_hashes: tuple[tuple[str, str], ...]
    warning_codes: tuple[str, ...]
    failure_codes: tuple[str, ...]
    full_result_retained: bool
    summary_payloads_retained: bool
    registry_version: str | None
    downstream_versions: tuple[tuple[str, str], ...]
    application_service_version: str = APPLICATION_SERVICE_VERSION


@dataclass(frozen=True, slots=True)
class ApplicationSubmissionResult:
    outcome: ApplicationOutcomeCode
    validation: ApplicationValidationReport
    status: ApplicationJobStatus | None
    warnings: tuple[ApplicationWarning, ...]
    message: str
    application_service_version: str = APPLICATION_SERVICE_VERSION


@dataclass(frozen=True, slots=True)
class ApplicationServiceConfiguration:
    maxima: ApplicationCrawlLimits
    maximum_projection_codes: int = 100
    maximum_projection_filenames: int = 100
    maximum_job_list_items: int = 100
    maximum_recommendation_page_size: int = 100
    coordinator_available: bool = True
    crawl_service_available: bool = True
    robots_service_available: bool = True
    recommendation_service_available: bool = True
    xml_service_available: bool = True
    publication_service_available: bool = True
    summary_service_available: bool = True
    application_service_version: str = APPLICATION_SERVICE_VERSION

    def __post_init__(self) -> None:
        if self.application_service_version != APPLICATION_SERVICE_VERSION:
            raise ValueError(_UNSUPPORTED_SERVICE_VERSION)
        if (
            self.maximum_projection_codes < 1
            or self.maximum_projection_filenames < 1
            or self.maximum_job_list_items < 1
            or self.maximum_recommendation_page_size < 1
        ):
            raise ValueError(_INVALID_PROJECTION_BOUNDS)


@dataclass(frozen=True, slots=True)
class ApplicationRegistryStatus:
    snapshot: JobRegistrySnapshot
    readiness: ApplicationReadinessReport


@dataclass(frozen=True, slots=True)
class ApplicationCancellationResult:
    outcome: ApplicationOutcomeCode
    status: ApplicationJobStatus | None
    message: str


@dataclass(frozen=True, slots=True)
class ApplicationProgressResult:
    outcome: ApplicationOutcomeCode
    progress: JobProgressView | None


@dataclass(frozen=True, slots=True)
class ApplicationShutdownResult:
    result: JobShutdownResult
    readiness: ApplicationReadinessReport
