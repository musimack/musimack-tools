"""Framework-independent facade over preparation, jobs, projections, and diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from musimack_tools.application.diagnostics import serialize_json, serialize_markdown
from musimack_tools.application.preflight import ApplicationPreflightService
from musimack_tools.application.preparation import ApplicationRequestPreparer
from musimack_tools.application.profiles import (
    APPLICATION_HARD_MAXIMA,
    validate_application_maxima,
)
from musimack_tools.application.projections import (
    normalize_warnings,
    project_result,
    project_status,
    status_from_snapshot,
)
from musimack_tools.application.readiness import capability_report, readiness_report
from musimack_tools.domain.application import (
    ApplicationCancellationResult,
    ApplicationOutcomeCode,
    ApplicationPreflightResult,
    ApplicationPreparationResult,
    ApplicationProgressResult,
    ApplicationRegistryStatus,
    ApplicationServiceConfiguration,
    ApplicationShutdownResult,
    ApplicationSubmissionResult,
    ApplicationValidationReport,
    PreflightCode,
    PreflightFinding,
    PreflightState,
    RawApplicationCrawlRequest,
    ValidationSeverity,
)
from musimack_tools.domain.job import (
    JobCancellationOutcome,
    JobSubmissionFailureCode,
    JobSubmissionOutcome,
    JobSubmissionRequest,
)

if TYPE_CHECKING:
    from musimack_tools.domain.application import (
        ApplicationJobStatus,
        ApplicationReadinessReport,
        ApplicationResultProjection,
        PreparedApplicationRequest,
    )
    from musimack_tools.domain.capabilities import ApplicationCapabilityReport
    from musimack_tools.domain.diagnostics import DiagnosticArtifact
    from musimack_tools.jobs.service import InternalJobService


class SeoToolkitApplicationService:
    """Stable internal facade intended for future authenticated adapters."""

    def __init__(
        self,
        jobs: InternalJobService,
        configuration: ApplicationServiceConfiguration | None = None,
        preparer: ApplicationRequestPreparer | None = None,
    ) -> None:
        self._jobs = jobs
        self._configuration = configuration or ApplicationServiceConfiguration(
            APPLICATION_HARD_MAXIMA
        )
        validate_application_maxima(self._configuration.maxima)
        self._preparer = preparer or ApplicationRequestPreparer(self._configuration.maxima)
        self._preflight = ApplicationPreflightService(jobs)

    def validate_request(self, raw: RawApplicationCrawlRequest) -> ApplicationValidationReport:
        return self._preparer.prepare(raw).report

    def prepare_request(self, raw: RawApplicationCrawlRequest) -> ApplicationPreparationResult:
        return self._preparer.prepare(raw)

    async def preflight(self, raw: RawApplicationCrawlRequest) -> ApplicationPreflightResult:
        preparation = self._preparer.prepare(raw)
        if preparation.prepared is None:
            snapshot = await self._jobs.snapshot()
            return ApplicationPreflightResult(
                PreflightState.BLOCKED,
                preparation.report,
                (
                    PreflightFinding(
                        ValidationSeverity.ERROR,
                        PreflightCode.VALIDATION_FAILED,
                        "Request validation failed before operational preflight",
                    ),
                    PreflightFinding(
                        ValidationSeverity.INFO,
                        PreflightCode.ADVISORY_ONLY,
                        "Preflight reserves no capacity; submission is authoritative",
                    ),
                ),
                snapshot,
                None,
                None,
            )
        return await self._preflight.inspect(preparation.prepared, preparation.report)

    async def submit(self, raw: RawApplicationCrawlRequest) -> ApplicationSubmissionResult:
        preparation = self._preparer.prepare(raw)
        warnings = normalize_warnings(preparation.report.warnings)
        if preparation.prepared is None:
            return ApplicationSubmissionResult(
                ApplicationOutcomeCode.VALIDATION_FAILED,
                preparation.report,
                None,
                warnings,
                "The request was not submitted because validation failed",
            )
        submitted = await self._jobs.submit(JobSubmissionRequest(preparation.prepared.run_request))
        if submitted.snapshot is not None:
            status = status_from_snapshot(submitted.snapshot)
            outcome = (
                ApplicationOutcomeCode.DUPLICATE_RETURNED
                if submitted.outcome is JobSubmissionOutcome.DUPLICATE_RETURNED
                else ApplicationOutcomeCode.QUEUED
                if submitted.snapshot.queue_position is not None
                else ApplicationOutcomeCode.ACCEPTED
            )
            return ApplicationSubmissionResult(
                outcome,
                preparation.report,
                status,
                warnings,
                submitted.explanation,
            )
        failure_code = submitted.failure_code
        failure_outcomes = {
            JobSubmissionFailureCode.REGISTRY_CLOSED: ApplicationOutcomeCode.REGISTRY_CLOSED,
            JobSubmissionFailureCode.ACTIVE_DUPLICATE: ApplicationOutcomeCode.ACTIVE_DUPLICATE,
            JobSubmissionFailureCode.QUEUE_CAPACITY_REACHED: (
                ApplicationOutcomeCode.QUEUE_CAPACITY_REACHED
            ),
            JobSubmissionFailureCode.INVALID_REQUEST: ApplicationOutcomeCode.VALIDATION_FAILED,
            JobSubmissionFailureCode.COORDINATOR_UNAVAILABLE: (
                ApplicationOutcomeCode.INTERNAL_SERVICE_UNAVAILABLE
            ),
        }
        code = (
            failure_outcomes.get(
                failure_code,
                ApplicationOutcomeCode.INTERNAL_SERVICE_UNAVAILABLE,
            )
            if failure_code is not None
            else ApplicationOutcomeCode.INTERNAL_SERVICE_UNAVAILABLE
        )
        return ApplicationSubmissionResult(
            code,
            preparation.report,
            None,
            warnings,
            submitted.explanation,
        )

    async def get_job_status(self, job_id: str) -> ApplicationJobStatus:
        return project_status(await self._jobs.status(job_id))

    async def get_job_progress(self, job_id: str) -> ApplicationProgressResult:
        progress = await self._jobs.progress(job_id)
        outcome = (
            ApplicationOutcomeCode.FOUND
            if progress.outcome.value == "found"
            else ApplicationOutcomeCode.JOB_NOT_FOUND
        )
        return ApplicationProgressResult(
            outcome,
            progress if outcome is ApplicationOutcomeCode.FOUND else None,
        )

    async def get_job_result(self, job_id: str) -> ApplicationResultProjection:
        return project_result(await self._jobs.result(job_id), self._configuration)

    async def cancel_job(self, job_id: str) -> ApplicationCancellationResult:
        cancelled = await self._jobs.cancel(job_id)
        outcome = {
            JobCancellationOutcome.REQUESTED: ApplicationOutcomeCode.CANCELLATION_REQUESTED,
            JobCancellationOutcome.CANCELLED_WHILE_QUEUED: (
                ApplicationOutcomeCode.CANCELLED_WHILE_QUEUED
            ),
            JobCancellationOutcome.ALREADY_REQUESTED: ApplicationOutcomeCode.ALREADY_REQUESTED,
            JobCancellationOutcome.ALREADY_TERMINAL: ApplicationOutcomeCode.ALREADY_TERMINAL,
            JobCancellationOutcome.NOT_FOUND: ApplicationOutcomeCode.JOB_NOT_FOUND,
            JobCancellationOutcome.REGISTRY_CLOSED: ApplicationOutcomeCode.REGISTRY_CLOSED,
        }[cancelled.outcome]
        status = (
            status_from_snapshot(cancelled.snapshot) if cancelled.snapshot is not None else None
        )
        return ApplicationCancellationResult(outcome, status, cancelled.explanation)

    async def get_registry_status(self) -> ApplicationRegistryStatus:
        snapshot = await self._jobs.snapshot()
        return ApplicationRegistryStatus(
            snapshot,
            readiness_report(snapshot, self._configuration),
        )

    def get_capabilities(self) -> ApplicationCapabilityReport:
        return capability_report()

    async def get_readiness(self) -> ApplicationReadinessReport:
        return readiness_report(await self._jobs.snapshot(), self._configuration)

    async def shutdown(self) -> ApplicationShutdownResult:
        result = await self._jobs.shutdown()
        readiness = readiness_report(await self._jobs.snapshot(), self._configuration)
        return ApplicationShutdownResult(result, readiness)

    def diagnostics_json(self, value: object) -> DiagnosticArtifact:
        return serialize_json(value)

    def diagnostics_markdown(self, value: object, title: str) -> DiagnosticArtifact:
        return serialize_markdown(value, title)

    async def wait_for_result(
        self,
        job_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ApplicationResultProjection:
        await self._jobs.wait(job_id, timeout_seconds=timeout_seconds)
        return await self.get_job_result(job_id)

    def prepare_or_none(
        self,
        raw: RawApplicationCrawlRequest,
    ) -> PreparedApplicationRequest | None:
        return self._preparer.prepare(raw).prepared
