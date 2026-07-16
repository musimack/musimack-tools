"""Immutable contracts for restart-safe durable job and run history."""

# ruff: noqa: TRY003 - validation and typed error messages are stable contract text.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

HISTORY_SERVICE_VERSION = "seo-toolkit-history-service-v1"
HISTORY_API_VERSION = "seo-toolkit-history-api-v1"
HISTORY_PAGINATION_VERSION = "seo-toolkit-history-pagination-v1"
HISTORY_JOB_ORDERING = "submitted_sequence_desc_job_id_desc-v1"
HISTORY_RUN_ORDERING = "submitted_sequence_desc_run_id_desc-v1"
_MAX_PAGE_SIZE = 500
_MAX_RELATED = 1_000


class HistoryAvailability(StrEnum):
    FULL = "full"
    METADATA_ONLY = "metadata_only"
    ARTIFACT_MISSING = "artifact_missing"
    ARTIFACT_EXPIRED = "artifact_expired"
    ARTIFACT_DELETED = "artifact_deleted"
    RESULT_UNAVAILABLE = "result_unavailable"
    EVICTED = "evicted"
    INTERRUPTED = "interrupted"
    RETAINED = "retained"


class HistoryFailureCode(StrEnum):
    DISABLED = "history_disabled"
    VERSION_UNSUPPORTED = "history_version_unsupported"
    INVALID_PAGE_SIZE = "history_invalid_page_size"
    INVALID_CURSOR = "history_invalid_cursor"
    CURSOR_VERSION_UNSUPPORTED = "history_cursor_version_unsupported"
    CURSOR_FILTER_MISMATCH = "history_cursor_filter_mismatch"
    CURSOR_ORDER_MISMATCH = "history_cursor_order_mismatch"
    JOB_NOT_FOUND = "history_job_not_found"
    RUN_NOT_FOUND = "history_run_not_found"
    QUERY_FAILED = "history_query_failed"
    PROJECTION_FAILED = "history_projection_failed"


class HistoryError(RuntimeError):
    """Safe typed history failure that never includes SQL or database details."""

    def __init__(self, code: HistoryFailureCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class HistoryConfiguration:
    enabled: bool = False
    default_page_size: int = 25
    maximum_page_size: int = 100
    maximum_attempts_per_job: int = 50
    maximum_stages_per_run: int = 100
    maximum_warnings_per_run: int = 250
    maximum_failures_per_run: int = 250
    maximum_artifacts_per_run: int = 250
    include_attempts_by_default: bool = False
    include_stages_by_default: bool = True
    include_warnings_by_default: bool = True
    include_failures_by_default: bool = True
    include_artifacts_by_default: bool = True
    service_version: str = HISTORY_SERVICE_VERSION
    api_version: str = HISTORY_API_VERSION
    pagination_version: str = HISTORY_PAGINATION_VERSION

    def __post_init__(self) -> None:
        if self.service_version != HISTORY_SERVICE_VERSION:
            raise ValueError("unsupported history service version")
        if self.api_version != HISTORY_API_VERSION:
            raise ValueError("unsupported history API version")
        if self.pagination_version != HISTORY_PAGINATION_VERSION:
            raise ValueError("unsupported history pagination version")
        if not 1 <= self.default_page_size <= _MAX_PAGE_SIZE:
            raise ValueError("history default page size is invalid")
        if not 1 <= self.maximum_page_size <= _MAX_PAGE_SIZE:
            raise ValueError("history maximum page size is invalid")
        if self.default_page_size > self.maximum_page_size:
            raise ValueError("history default page size exceeds maximum page size")
        related = (
            self.maximum_attempts_per_job,
            self.maximum_stages_per_run,
            self.maximum_warnings_per_run,
            self.maximum_failures_per_run,
            self.maximum_artifacts_per_run,
        )
        if any(value < 1 or value > _MAX_RELATED for value in related):
            raise ValueError("history related-record limit is invalid")


@dataclass(frozen=True, slots=True)
class JobHistoryFilter:
    job_id: str | None = None
    run_id: str | None = None
    state: str | None = None
    seed: str | None = None
    scheduler_mode: str | None = None
    submitted_from: datetime | None = None
    submitted_to: datetime | None = None
    terminal_from: datetime | None = None
    terminal_to: datetime | None = None
    cancellation_requested: bool | None = None
    retry_eligible: bool | None = None
    retention_state: str | None = None
    artifacts_available: bool | None = None
    interrupted: bool | None = None
    recovered: bool | None = None

    def __post_init__(self) -> None:
        _validate_range(self.submitted_from, self.submitted_to, "submission")
        _validate_range(self.terminal_from, self.terminal_to, "terminal")
        if self.scheduler_mode not in {None, "durable", "in_memory"}:
            raise ValueError("history scheduler mode is invalid")

    def canonical(self) -> tuple[tuple[str, str], ...]:
        return _canonical_fields(self)


@dataclass(frozen=True, slots=True)
class RunHistoryFilter:
    run_id: str | None = None
    job_id: str | None = None
    state: str | None = None
    completion_state: str | None = None
    stage_state: str | None = None
    started_from: datetime | None = None
    started_to: datetime | None = None
    terminal_from: datetime | None = None
    terminal_to: datetime | None = None
    has_warnings: bool | None = None
    has_failures: bool | None = None
    has_artifacts: bool | None = None
    partial: bool | None = None
    interrupted: bool | None = None
    retention_state: str | None = None

    def __post_init__(self) -> None:
        _validate_range(self.started_from, self.started_to, "start")
        _validate_range(self.terminal_from, self.terminal_to, "terminal")

    def canonical(self) -> tuple[tuple[str, str], ...]:
        return _canonical_fields(self)


@dataclass(frozen=True, slots=True)
class HistoryPageRequest:
    page_size: int
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class HistoricalJob:
    job_id: str
    run_id: str
    seed: str
    scheduler_mode: str
    state: str
    queue_state: str | None
    attempt_count: int
    maximum_attempts: int | None
    retry_eligible_at: datetime | None
    cancellation_requested: bool
    submitted_at: datetime | None
    started_at: datetime | None
    terminal_at: datetime | None
    last_failure_code: str | None
    terminal_disposition: str | None
    interrupted: bool
    recovered: bool
    retention_state: str
    result_available: bool
    artifact_available: bool
    summary_available: bool
    availability: HistoryAvailability
    projection_version: str = HISTORY_SERVICE_VERSION


@dataclass(frozen=True, slots=True)
class HistoricalRun:
    run_id: str
    job_id: str
    seed: str
    lifecycle: str
    started_at: datetime | None
    terminal_at: datetime | None
    duration_seconds: float | None
    current_stage: str | None
    stage_count: int
    completed_stage_count: int
    failed_stage_count: int
    skipped_stage_count: int
    crawl_count: int
    crawl_byte_count: int | None
    recommendation_count: int
    xml_count: int
    publication_count: int
    warning_count: int
    failure_count: int
    artifact_count: int
    summary_json_available: bool
    summary_markdown_available: bool
    partial: bool
    interrupted: bool
    retention_state: str
    availability: HistoryAvailability
    projection_version: str = HISTORY_SERVICE_VERSION


@dataclass(frozen=True, slots=True)
class HistoricalAttempt:
    attempt_number: int
    execution_number: int
    state: str
    started_at: datetime
    terminal_at: datetime | None
    worker_id: str
    lease_generation: int
    retryable: bool
    failure_code: str | None
    terminal_disposition: str | None
    cancellation_observed: bool
    duration_seconds: float | None


@dataclass(frozen=True, slots=True)
class HistoricalStage:
    stage: str
    order: int
    state: str
    started_at: datetime | None
    terminal_at: datetime | None
    duration_seconds: float | None
    warning_count: int
    failure_count: int
    result_available: bool
    partial: bool
    version: str = HISTORY_SERVICE_VERSION


@dataclass(frozen=True, slots=True)
class HistoricalMessage:
    code: str
    stage: str | None
    severity: str
    summary: str
    occurred_at: datetime | None
    related_url: str | None


@dataclass(frozen=True, slots=True)
class HistoricalArtifact:
    artifact_id: str
    artifact_type: str
    lifecycle_state: str
    integrity_state: str
    filename: str
    content_type: str
    byte_count: int
    created_at: datetime
    last_verified_at: datetime | None
    download_available: bool


@dataclass(frozen=True, slots=True)
class RelatedHistory[T]:
    items: tuple[T, ...]
    returned_count: int
    truncated: bool
    maximum: int


@dataclass(frozen=True, slots=True)
class HistoryPage[T]:
    items: tuple[T, ...]
    page_size: int
    returned_count: int
    has_more: bool
    next_cursor: str | None
    applied_filters: tuple[tuple[str, str], ...]
    ordering: str
    version: str = HISTORY_PAGINATION_VERSION


@dataclass(frozen=True, slots=True)
class HistoryDiagnostics:
    enabled: bool
    default_page_size: int
    maximum_page_size: int
    historical_job_count: int
    historical_run_count: int
    terminal_job_count: int
    interrupted_job_count: int
    retry_attempt_count: int
    metadata_only_count: int
    runs_with_artifacts: int
    runs_with_missing_artifacts: int
    last_successful_query_at: datetime | None
    last_failure_reason: str | None
    migration_ready: bool
    database_ready: bool
    service_version: str = HISTORY_SERVICE_VERSION
    api_version: str = HISTORY_API_VERSION
    pagination_version: str = HISTORY_PAGINATION_VERSION


def duration_seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None or end < start:
        return None
    return (end - start).total_seconds()


def _validate_range(start: datetime | None, end: datetime | None, label: str) -> None:
    if start is not None and end is not None and start > end:
        raise ValueError(f"history {label} range is invalid")


def _canonical_fields(value: object) -> tuple[tuple[str, str], ...]:
    fields: list[tuple[str, str]] = []
    for name in value.__dataclass_fields__:  # type: ignore[attr-defined]
        item = getattr(value, name)
        if item is not None:
            encoded = item.isoformat() if isinstance(item, datetime) else str(item).lower()
            fields.append((name, encoded))
    return tuple(fields)
