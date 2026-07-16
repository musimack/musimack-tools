"""Explicit mapping between accepted application records and bounded API schemas."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from musimack_tools.api.schemas import (
    ApiErrorDetailSchema,
    ApiWarningSchema,
    ApplicationRequestSchema,
    CancellationSchema,
    CapabilitySchema,
    CrawlLimitsSchema,
    JobProgressSchema,
    JobResultSchema,
    JobStatusSchema,
    NamedCountSchema,
    NamedHashSchema,
    NamedValueSchema,
    PreflightFindingSchema,
    PreflightReportSchema,
    ProgressEventSchema,
    ProgressSnapshotSchema,
    ReadinessCheckSchema,
    ReadinessSchema,
    RegistryCountsSchema,
    RegistryStatusSchema,
    SubmissionSchema,
    ValidationIssueSchema,
    ValidationReportSchema,
    VersionSchema,
)
from musimack_tools.domain.application import (
    ApplicationCrawlLimits,
    ApplicationJobStatus,
    ApplicationPreflightResult,
    ApplicationProgressResult,
    ApplicationReadinessReport,
    ApplicationRegistryStatus,
    ApplicationResultProjection,
    ApplicationSubmissionResult,
    ApplicationValidationReport,
    ApplicationWarning,
    CrawlLimitOverrides,
    RawApplicationCrawlRequest,
    ValidationIssue,
)

if TYPE_CHECKING:
    from musimack_tools.domain.application import ApplicationCancellationResult
    from musimack_tools.domain.capabilities import ApplicationCapabilityReport
    from musimack_tools.domain.job_registry import JobRegistrySnapshot
    from musimack_tools.domain.run_progress import RunProgressEvent, RunProgressSnapshot


def to_raw_request(value: ApplicationRequestSchema) -> RawApplicationCrawlRequest:
    overrides = value.overrides
    return RawApplicationCrawlRequest(
        seed_url=value.seed_url,
        scope_profile=value.scope_profile,
        approved_hosts=value.approved_hosts,
        crawl_profile=value.crawl_profile,
        overrides=CrawlLimitOverrides(
            overrides.maximum_urls,
            overrides.maximum_depth,
            overrides.maximum_duration_seconds,
            overrides.maximum_accepted_bytes,
            overrides.maximum_concurrency,
            overrides.maximum_queue_size,
            overrides.minimum_request_delay_seconds,
            overrides.maximum_redirect_hops,
            overrides.maximum_response_bytes,
        ),
        recommendation_profile=value.recommendation_profile,
        recommendation_requested=value.recommendation_requested,
        xml_generation_requested=value.xml_generation_requested,
        publication_requested=value.publication_requested,
        publication_dry_run=value.publication_dry_run,
        publication_root=(
            Path(value.publication_root) if value.publication_root is not None else None
        ),
        existing_file_policy=value.existing_file_policy,
        create_publication_directory=value.create_publication_directory,
        summary_writing_requested=value.summary_writing_requested,
        summary_root=Path(value.summary_root) if value.summary_root is not None else None,
        create_summary_directory=value.create_summary_directory,
        summary_dry_run=value.summary_dry_run,
        caller_label=value.caller_label,
    )


def validation_schema(value: ApplicationValidationReport) -> ValidationReportSchema:
    return ValidationReportSchema(
        valid=value.valid,
        issues=tuple(_validation_issue(item) for item in value.issues),
        normalized_seed_url=value.normalized_seed_url,
        selected_profile=value.selected_profile,
        requested_stages=value.requested_stages,
        effective_limits=(
            _limits(value.effective_limits) if value.effective_limits is not None else None
        ),
        scope_summary=value.scope_summary,
        publication_requested=value.publication_requested,
        summary_requested=value.summary_requested,
        run_id=value.run_id,
        downstream_versions=tuple(
            VersionSchema(component=name, version=version)
            for name, version in value.downstream_versions
        ),
        application_service_version=value.application_service_version,
    )


def validation_error_details(
    value: ApplicationValidationReport,
    maximum: int,
) -> tuple[ApiErrorDetailSchema, ...]:
    return tuple(
        ApiErrorDetailSchema(
            code=item.code.value,
            message=item.message,
            field=item.field,
            source_code=item.code.value,
        )
        for item in value.errors[:maximum]
    )


def validation_warnings(value: ApplicationValidationReport) -> tuple[ApiWarningSchema, ...]:
    return tuple(
        ApiWarningSchema(
            code=item.code.value,
            source_layer="application",
            message=item.message,
            source_code=item.code.value,
        )
        for item in value.warnings
    )


def application_warnings(values: tuple[ApplicationWarning, ...]) -> tuple[ApiWarningSchema, ...]:
    return tuple(
        ApiWarningSchema(
            code=item.code,
            source_layer=item.source_layer,
            message=item.message,
            url=_safe_warning_url(item.url),
            source_code=item.source_code,
        )
        for item in values
    )


def preflight_schema(value: ApplicationPreflightResult) -> PreflightReportSchema:
    return PreflightReportSchema(
        state=value.state.value,
        validation=validation_schema(value.validation),
        findings=tuple(
            PreflightFindingSchema(
                severity=item.severity.value,
                code=item.code.value,
                message=item.message,
            )
            for item in value.findings
        ),
        registry=registry_counts_schema(value.registry_snapshot),
        active_duplicate_job_id=value.active_duplicate_job_id,
        likely_queue_position=value.likely_queue_position,
        application_service_version=value.application_service_version,
    )


def preflight_error_details(
    value: ApplicationPreflightResult,
    maximum: int,
) -> tuple[ApiErrorDetailSchema, ...]:
    return tuple(
        ApiErrorDetailSchema(
            code=item.code.value,
            message=item.message,
            source_code=item.code.value,
        )
        for item in value.findings[:maximum]
    )


def job_status_schema(value: ApplicationJobStatus) -> JobStatusSchema:
    return JobStatusSchema(
        outcome=value.outcome.value,
        job_id=value.job_id,
        run_id=value.run_id,
        attempt_number=value.attempt_number,
        state=value.state,
        queue_position=value.queue_position,
        active_stage=value.active_stage,
        run_lifecycle=value.run_lifecycle,
        urls_discovered=value.urls_discovered,
        urls_fetched=value.urls_fetched,
        recommendation_counts=value.recommendation_counts,
        xml_document_count=value.xml_document_count,
        xml_entry_count=value.xml_entry_count,
        publication_file_count=value.publication_file_count,
        warning_count=value.warning_count,
        failure_count=value.failure_count,
        cancellation_requested=value.cancellation_requested,
        terminal=value.terminal,
        result_available=value.result_available,
        registry_version=value.registry_version,
        application_service_version=value.application_service_version,
    )


def submission_schema(value: ApplicationSubmissionResult) -> SubmissionSchema:
    return SubmissionSchema(
        outcome=value.outcome.value,
        validation=validation_schema(value.validation),
        status=job_status_schema(value.status) if value.status is not None else None,
        message=value.message,
        application_service_version=value.application_service_version,
    )


def progress_schema(value: ApplicationProgressResult, history_limit: int) -> JobProgressSchema:
    if value.progress is None:
        return JobProgressSchema(
            outcome=value.outcome.value,
            latest=None,
            history=(),
            history_truncated=False,
        )
    history = value.progress.history
    selected = history[-history_limit:] if history_limit else ()
    return JobProgressSchema(
        outcome=value.outcome.value,
        latest=_progress_event(value.progress.latest)
        if value.progress.latest is not None
        else None,
        history=tuple(_progress_event(item) for item in selected),
        history_truncated=(
            value.progress.history_truncated or (history_limit > 0 and len(history) > history_limit)
        ),
    )


def result_schema(value: ApplicationResultProjection) -> JobResultSchema:
    return JobResultSchema(
        outcome=value.outcome.value,
        job_id=value.job_id,
        run_id=value.run_id,
        attempt_number=value.attempt_number,
        job_state=value.job_state,
        run_lifecycle=value.run_lifecycle,
        stage_states=tuple(
            NamedValueSchema(name=name, value=state) for name, state in value.stage_states
        ),
        crawl_counts=tuple(
            NamedCountSchema(name=name, count=count) for name, count in value.crawl_counts
        ),
        crawl_error_codes=value.crawl_error_codes,
        recommendation_counts=tuple(
            NamedCountSchema(name=name, count=count) for name, count in value.recommendation_counts
        ),
        xml_document_count=value.xml_document_count,
        xml_entry_count=value.xml_entry_count,
        publication_state=value.publication_state,
        published_file_count=value.published_file_count,
        publication_filenames=value.publication_filenames,
        manifest_sha256=value.manifest_sha256,
        summary_hashes=tuple(
            NamedHashSchema(name=name, sha256=digest) for name, digest in value.summary_hashes
        ),
        warning_codes=value.warning_codes,
        failure_codes=value.failure_codes,
        full_result_retained=value.full_result_retained,
        summary_payloads_retained=value.summary_payloads_retained,
        registry_version=value.registry_version,
        downstream_versions=tuple(
            VersionSchema(component=name, version=version)
            for name, version in value.downstream_versions
        ),
        application_service_version=value.application_service_version,
    )


def cancellation_schema(value: ApplicationCancellationResult) -> CancellationSchema:
    return CancellationSchema(
        outcome=value.outcome.value,
        status=job_status_schema(value.status) if value.status is not None else None,
        message=value.message,
    )


def registry_counts_schema(value: JobRegistrySnapshot) -> RegistryCountsSchema:
    counters = value.counters
    return RegistryCountsSchema(
        state=value.state.value,
        active_jobs=counters.active_jobs,
        queued_jobs=counters.queued_jobs,
        retained_terminal_jobs=counters.terminal_jobs_retained,
        submitted_jobs=counters.submitted_jobs,
        accepted_jobs=counters.accepted_jobs,
        rejected_jobs=counters.rejected_jobs,
        completed_jobs=counters.completed_jobs,
        cancelled_jobs=counters.cancelled_jobs,
        failed_jobs=counters.failed_jobs,
        partially_completed_jobs=counters.partially_completed_jobs,
        evicted_jobs=counters.evicted_jobs,
        duplicate_rejections=counters.duplicate_rejections,
        queue_capacity_rejections=counters.queue_capacity_rejections,
        registry_version=value.registry_version,
    )


def readiness_schema(value: ApplicationReadinessReport) -> ReadinessSchema:
    return ReadinessSchema(
        state=value.state.value,
        checks=tuple(
            ReadinessCheckSchema(
                code=item.code.value,
                state=item.state.value,
                message=item.message,
            )
            for item in value.checks
        ),
        active_jobs=value.active_jobs,
        queued_jobs=value.queued_jobs,
        retained_terminal_jobs=value.retained_terminal_jobs,
        application_service_version=value.application_service_version,
    )


def registry_status_schema(value: ApplicationRegistryStatus) -> RegistryStatusSchema:
    return RegistryStatusSchema(
        registry=registry_counts_schema(value.snapshot),
        readiness=readiness_schema(value.readiness),
        application_service_version=value.readiness.application_service_version,
    )


def capability_schema(value: ApplicationCapabilityReport) -> CapabilitySchema:
    return CapabilitySchema(
        supported=tuple(item.value for item in value.supported),
        unsupported=tuple(item.value for item in value.unsupported),
        application_service_version=value.application_service_version,
    )


def _limits(value: ApplicationCrawlLimits) -> CrawlLimitsSchema:
    return CrawlLimitsSchema(
        maximum_urls=value.maximum_urls,
        maximum_depth=value.maximum_depth,
        maximum_duration_seconds=value.maximum_duration_seconds,
        maximum_accepted_bytes=value.maximum_accepted_bytes,
        maximum_concurrency=value.maximum_concurrency,
        maximum_queue_size=value.maximum_queue_size,
        minimum_request_delay_seconds=value.minimum_request_delay_seconds,
        maximum_redirect_hops=value.maximum_redirect_hops,
        maximum_response_bytes=value.maximum_response_bytes,
    )


def _validation_issue(value: ValidationIssue) -> ValidationIssueSchema:
    return ValidationIssueSchema(
        severity=value.severity.value,
        code=value.code.value,
        message=value.message,
        field=value.field,
    )


def _progress_event(value: RunProgressEvent) -> ProgressEventSchema:
    return ProgressEventSchema(
        sequence=value.sequence,
        code=value.code.value,
        snapshot=_progress_snapshot(value.snapshot),
        explanation=value.explanation,
    )


def _progress_snapshot(value: RunProgressSnapshot) -> ProgressSnapshotSchema:
    return ProgressSnapshotSchema(
        lifecycle=value.lifecycle.value,
        active_stage=value.active_stage.value if value.active_stage is not None else None,
        stage_state=value.stage_state.value if value.stage_state is not None else None,
        urls_discovered=value.urls_discovered,
        urls_queued=value.urls_queued,
        urls_fetched=value.urls_fetched,
        urls_parsed=value.urls_parsed,
        bytes_fetched=value.bytes_fetched,
        queue_size=value.queue_size,
        active_count=value.active_count,
        current_depth=value.current_depth,
        recommendation_counts=value.recommendation_counts,
        xml_document_count=value.xml_document_count,
        xml_entry_count=value.xml_entry_count,
        publication_file_count=value.publication_file_count,
        warning_count=value.warning_count,
        failure_count=value.failure_count,
        cancellation_requested=value.cancellation_requested,
        recent_crawl_error_code=value.recent_crawl_error_code,
        elapsed_seconds=value.elapsed_seconds,
    )


def _safe_warning_url(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "<redacted-url>"
    query = "redacted" if parsed.query else ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))
