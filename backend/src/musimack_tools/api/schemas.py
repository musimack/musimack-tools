"""Bounded Pydantic schemas for the private internal API adapter."""

from __future__ import annotations

from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StringConstraints,
)

from musimack_tools.domain.api import INTERNAL_API_VERSION
from musimack_tools.domain.application import (
    CrawlProfileName,
    RecommendationProfile,
    ScopeProfile,
)
from musimack_tools.domain.sitemap_publication import ExistingFilePolicy
from musimack_tools.security.correlation import current_request_id

BoundedUrl = Annotated[str, StringConstraints(min_length=1, max_length=4_096)]
BoundedHost = Annotated[str, StringConstraints(min_length=1, max_length=253)]
BoundedPath = Annotated[str, StringConstraints(min_length=1, max_length=4_096)]
BoundedCaller = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CrawlLimitOverridesRequest(ApiSchema):
    maximum_urls: StrictInt | None = None
    maximum_depth: StrictInt | None = None
    maximum_duration_seconds: StrictFloat | StrictInt | None = None
    maximum_accepted_bytes: StrictInt | None = None
    maximum_concurrency: StrictInt | None = None
    maximum_queue_size: StrictInt | None = None
    minimum_request_delay_seconds: StrictFloat | StrictInt | None = None
    maximum_redirect_hops: StrictInt | None = None
    maximum_response_bytes: StrictInt | None = None


class ApplicationRequestSchema(ApiSchema):
    seed_url: BoundedUrl
    scope_profile: ScopeProfile = ScopeProfile.EXACT_HOST
    approved_hosts: tuple[BoundedHost, ...] = Field(default=(), max_length=32)
    crawl_profile: CrawlProfileName = CrawlProfileName.STANDARD_CRAWL
    overrides: CrawlLimitOverridesRequest = Field(default_factory=CrawlLimitOverridesRequest)
    recommendation_profile: RecommendationProfile = RecommendationProfile.STANDARD
    recommendation_requested: StrictBool | None = None
    xml_generation_requested: StrictBool | None = None
    publication_requested: StrictBool = False
    publication_dry_run: StrictBool = False
    publication_root: BoundedPath | None = None
    existing_file_policy: ExistingFilePolicy = ExistingFilePolicy.FAIL_IF_EXISTS
    create_publication_directory: StrictBool = False
    summary_writing_requested: StrictBool | None = None
    summary_root: BoundedPath | None = None
    create_summary_directory: StrictBool = False
    summary_dry_run: StrictBool = False
    caller_label: BoundedCaller | None = None


class ApiWarningSchema(ApiSchema):
    code: str
    source_layer: str
    message: str
    url: str | None = None
    source_code: str | None = None


class ApiErrorDetailSchema(ApiSchema):
    code: str
    message: str
    field: str | None = None
    source_code: str | None = None


class ApiErrorDataSchema(ApiSchema):
    code: str
    message: str
    details: tuple[ApiErrorDetailSchema, ...] = ()


class ApiErrorEnvelope(ApiSchema):
    api_version: str = INTERNAL_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    error: ApiErrorDataSchema


class CrawlLimitsSchema(ApiSchema):
    maximum_urls: int
    maximum_depth: int
    maximum_duration_seconds: float
    maximum_accepted_bytes: int
    maximum_concurrency: int
    maximum_queue_size: int
    minimum_request_delay_seconds: float
    maximum_redirect_hops: int
    maximum_response_bytes: int


class ValidationIssueSchema(ApiSchema):
    severity: str
    code: str
    message: str
    field: str | None = None


class VersionSchema(ApiSchema):
    component: str
    version: str


class ValidationReportSchema(ApiSchema):
    valid: bool
    issues: tuple[ValidationIssueSchema, ...]
    normalized_seed_url: str | None
    selected_profile: str
    requested_stages: tuple[str, ...]
    effective_limits: CrawlLimitsSchema | None
    scope_summary: str | None
    publication_requested: bool
    summary_requested: bool
    run_id: str | None
    downstream_versions: tuple[VersionSchema, ...]
    application_service_version: str


class PreflightFindingSchema(ApiSchema):
    severity: str
    code: str
    message: str


class RegistryCountsSchema(ApiSchema):
    state: str
    active_jobs: int
    queued_jobs: int
    retained_terminal_jobs: int
    submitted_jobs: int
    accepted_jobs: int
    rejected_jobs: int
    completed_jobs: int
    cancelled_jobs: int
    failed_jobs: int
    partially_completed_jobs: int
    evicted_jobs: int
    duplicate_rejections: int
    queue_capacity_rejections: int
    registry_version: str


class PreflightReportSchema(ApiSchema):
    state: str
    validation: ValidationReportSchema
    findings: tuple[PreflightFindingSchema, ...]
    registry: RegistryCountsSchema
    active_duplicate_job_id: str | None
    likely_queue_position: int | None
    application_service_version: str


class JobStatusSchema(ApiSchema):
    outcome: str
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
    application_service_version: str


class JobListSchema(ApiSchema):
    items: tuple[JobStatusSchema, ...]
    truncated: bool
    maximum: int
    application_service_version: str


class RecommendationItemSchema(ApiSchema):
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


class RecommendationPageSchema(ApiSchema):
    outcome: str
    job_id: str | None
    run_id: str | None
    offset: int
    limit: int
    total: int
    returned_count: int
    has_more: bool
    items: tuple[RecommendationItemSchema, ...]
    rule_set_version: str | None
    application_service_version: str


class SubmissionSchema(ApiSchema):
    outcome: str
    validation: ValidationReportSchema
    status: JobStatusSchema | None
    message: str
    application_service_version: str


class ProgressSnapshotSchema(ApiSchema):
    lifecycle: str
    active_stage: str | None
    stage_state: str | None
    urls_discovered: int
    urls_queued: int
    urls_fetched: int
    urls_parsed: int
    bytes_fetched: int
    queue_size: int
    active_count: int
    current_depth: int | None
    recommendation_counts: tuple[int, int, int, int] | None
    xml_document_count: int | None
    xml_entry_count: int | None
    publication_file_count: int | None
    warning_count: int
    failure_count: int
    cancellation_requested: bool
    recent_crawl_error_code: str | None
    elapsed_seconds: float


class ProgressEventSchema(ApiSchema):
    sequence: int
    code: str
    snapshot: ProgressSnapshotSchema
    explanation: str


class JobProgressSchema(ApiSchema):
    outcome: str
    latest: ProgressEventSchema | None
    history: tuple[ProgressEventSchema, ...]
    history_truncated: bool


class NamedCountSchema(ApiSchema):
    name: str
    count: int


class NamedValueSchema(ApiSchema):
    name: str
    value: str


class NamedHashSchema(ApiSchema):
    name: str
    sha256: str


class JobResultSchema(ApiSchema):
    outcome: str
    job_id: str | None
    run_id: str | None
    attempt_number: int | None
    job_state: str | None
    run_lifecycle: str | None
    stage_states: tuple[NamedValueSchema, ...]
    crawl_counts: tuple[NamedCountSchema, ...]
    crawl_error_codes: tuple[str, ...]
    recommendation_counts: tuple[NamedCountSchema, ...]
    xml_document_count: int | None
    xml_entry_count: int | None
    publication_state: str | None
    published_file_count: int
    publication_filenames: tuple[str, ...]
    manifest_sha256: str | None
    summary_hashes: tuple[NamedHashSchema, ...]
    warning_codes: tuple[str, ...]
    failure_codes: tuple[str, ...]
    full_result_retained: bool
    summary_payloads_retained: bool
    registry_version: str | None
    downstream_versions: tuple[VersionSchema, ...]
    application_service_version: str


class CancellationSchema(ApiSchema):
    outcome: str
    status: JobStatusSchema | None
    message: str


class ReadinessCheckSchema(ApiSchema):
    code: str
    state: str
    message: str


class ReadinessSchema(ApiSchema):
    state: str
    checks: tuple[ReadinessCheckSchema, ...]
    active_jobs: int
    queued_jobs: int
    retained_terminal_jobs: int
    application_service_version: str


class RegistryStatusSchema(ApiSchema):
    registry: RegistryCountsSchema
    readiness: ReadinessSchema
    application_service_version: str


class CapabilitySchema(ApiSchema):
    supported: tuple[str, ...]
    unsupported: tuple[str, ...]
    application_service_version: str


class ValidationResponse(ApiSchema):
    api_version: str = INTERNAL_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: ValidationReportSchema
    warnings: tuple[ApiWarningSchema, ...] = ()


class PreflightResponse(ApiSchema):
    api_version: str = INTERNAL_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: PreflightReportSchema
    warnings: tuple[ApiWarningSchema, ...] = ()


class SubmissionResponse(ApiSchema):
    api_version: str = INTERNAL_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: SubmissionSchema
    warnings: tuple[ApiWarningSchema, ...] = ()


class JobStatusResponse(ApiSchema):
    api_version: str = INTERNAL_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: JobStatusSchema
    warnings: tuple[ApiWarningSchema, ...] = ()


class JobListResponse(ApiSchema):
    api_version: str = INTERNAL_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: JobListSchema
    warnings: tuple[ApiWarningSchema, ...] = ()


class RecommendationPageResponse(ApiSchema):
    api_version: str = INTERNAL_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: RecommendationPageSchema
    warnings: tuple[ApiWarningSchema, ...] = ()


class JobProgressResponse(ApiSchema):
    api_version: str = INTERNAL_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: JobProgressSchema
    warnings: tuple[ApiWarningSchema, ...] = ()


class JobResultResponse(ApiSchema):
    api_version: str = INTERNAL_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: JobResultSchema
    warnings: tuple[ApiWarningSchema, ...] = ()


class CancellationResponse(ApiSchema):
    api_version: str = INTERNAL_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: CancellationSchema
    warnings: tuple[ApiWarningSchema, ...] = ()


class RegistryStatusResponse(ApiSchema):
    api_version: str = INTERNAL_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: RegistryStatusSchema
    warnings: tuple[ApiWarningSchema, ...] = ()


class ReadinessResponse(ApiSchema):
    api_version: str = INTERNAL_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: ReadinessSchema
    warnings: tuple[ApiWarningSchema, ...] = ()


class CapabilityResponse(ApiSchema):
    api_version: str = INTERNAL_API_VERSION
    request_id: str | None = Field(default_factory=current_request_id)
    data: CapabilitySchema
    warnings: tuple[ApiWarningSchema, ...] = ()
