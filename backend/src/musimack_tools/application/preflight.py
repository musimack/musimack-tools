"""Advisory, read-only registry and filesystem preflight checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from musimack_tools.domain.application import (
    ApplicationPreflightResult,
    PreflightCode,
    PreflightFinding,
    PreflightState,
    PreparedApplicationRequest,
    ValidationSeverity,
)
from musimack_tools.domain.job import JobLookupOutcome
from musimack_tools.domain.job_registry import (
    DuplicateSubmissionPolicy,
    RegistryState,
)
from musimack_tools.domain.run_summary import RUN_SUMMARY_JSON_NAME, RUN_SUMMARY_MARKDOWN_NAME
from musimack_tools.domain.sitemap_publication import (
    SITEMAP_MANIFEST_LOGICAL_NAME,
    ExistingFilePolicy,
)
from musimack_tools.sitemap.publication import is_unsafe_link_path

if TYPE_CHECKING:
    from pathlib import Path

    from musimack_tools.domain.application import ApplicationValidationReport
    from musimack_tools.jobs.service import InternalJobService


class ApplicationPreflightService:
    """Inspect likely submission and output conditions without reserving resources."""

    def __init__(self, jobs: InternalJobService) -> None:
        self._jobs = jobs

    async def inspect(  # noqa: C901 - ordered advisory checks remain explicit.
        self,
        prepared: PreparedApplicationRequest,
        validation: ApplicationValidationReport,
    ) -> ApplicationPreflightResult:
        registry = await self._jobs.snapshot()
        findings: list[PreflightFinding] = []
        duplicate_id = await self._active_duplicate(
            prepared.run_id,
            registry.active_job_ids + registry.queued_job_ids,
        )
        state = PreflightState.READY
        queue_position = None

        if registry.state in {RegistryState.SHUTTING_DOWN, RegistryState.CLOSED}:
            findings.append(
                _finding(ValidationSeverity.ERROR, PreflightCode.REGISTRY_NOT_ACCEPTING)
            )
            state = PreflightState.BLOCKED
        elif (
            duplicate_id is not None
            and registry.configuration.duplicate_policy
            is DuplicateSubmissionPolicy.REJECT_ACTIVE_DUPLICATE
        ):
            findings.append(_finding(ValidationSeverity.ERROR, PreflightCode.ACTIVE_DUPLICATE))
            state = PreflightState.BLOCKED
        elif duplicate_id is not None:
            findings.append(_finding(ValidationSeverity.WARNING, PreflightCode.ACTIVE_DUPLICATE))
        elif registry.counters.active_jobs < registry.configuration.maximum_concurrent_jobs:
            findings.append(_finding(ValidationSeverity.INFO, PreflightCode.IMMEDIATE_CAPACITY))
        elif registry.counters.queued_jobs >= registry.configuration.maximum_queued_jobs:
            findings.append(_finding(ValidationSeverity.ERROR, PreflightCode.QUEUE_FULL))
            state = PreflightState.BLOCKED
        else:
            queue_position = registry.counters.queued_jobs + 1
            findings.append(_finding(ValidationSeverity.WARNING, PreflightCode.LIKELY_QUEUED))
            state = PreflightState.LIKELY_QUEUED

        publication = prepared.publication_configuration
        if publication is not None:
            output_findings = _root_findings(
                publication.output_root,
                publication.create_output_directory,
                publication.existing_file_policy,
                ("sitemap.xml", SITEMAP_MANIFEST_LOGICAL_NAME),
            )
            findings.extend(output_findings)
            if any(item.severity is ValidationSeverity.ERROR for item in output_findings):
                state = PreflightState.BLOCKED
            if publication.mode.value == "dry_run":
                findings.append(_finding(ValidationSeverity.INFO, PreflightCode.DRY_RUN))

        summary = prepared.summary_configuration
        if summary is not None:
            output_findings = _root_findings(
                summary.output_root,
                summary.create_output_directory,
                summary.existing_file_policy,
                (RUN_SUMMARY_JSON_NAME, RUN_SUMMARY_MARKDOWN_NAME),
            )
            findings.extend(output_findings)
            if any(item.severity is ValidationSeverity.ERROR for item in output_findings):
                state = PreflightState.BLOCKED
            if summary.dry_run:
                findings.append(_finding(ValidationSeverity.INFO, PreflightCode.DRY_RUN))

        findings.append(_finding(ValidationSeverity.INFO, PreflightCode.ADVISORY_ONLY))
        return ApplicationPreflightResult(
            state,
            validation,
            tuple(findings),
            registry,
            duplicate_id,
            queue_position,
        )

    async def _active_duplicate(
        self,
        run_id: str,
        active_ids: tuple[str, ...],
    ) -> str | None:
        for job_id in active_ids:
            result = await self._jobs.status(job_id)
            if (
                result.outcome is JobLookupOutcome.FOUND
                and result.snapshot is not None
                and result.snapshot.run_id == run_id
            ):
                return job_id
        return None


def _root_findings(
    root: Path,
    create: bool,  # noqa: FBT001 - immutable configuration flag.
    policy: ExistingFilePolicy,
    logical_names: tuple[str, ...],
) -> tuple[PreflightFinding, ...]:
    if not root.is_absolute() or any(part.casefold() == ".git" for part in root.parts):
        return (_finding(ValidationSeverity.ERROR, PreflightCode.OUTPUT_ROOT_BLOCKED),)
    if root.exists() and (not root.is_dir() or is_unsafe_link_path(root)):
        return (_finding(ValidationSeverity.ERROR, PreflightCode.OUTPUT_ROOT_BLOCKED),)
    for ancestor in _existing_ancestors(root):
        if is_unsafe_link_path(ancestor):
            return (_finding(ValidationSeverity.ERROR, PreflightCode.OUTPUT_ROOT_BLOCKED),)
    if not root.exists():
        severity = ValidationSeverity.WARNING if create else ValidationSeverity.ERROR
        return (_finding(severity, PreflightCode.OUTPUT_ROOT_CREATION_REQUIRED),)
    conflicts = tuple(name for name in logical_names if (root / name).exists())
    if conflicts and policy is ExistingFilePolicy.FAIL_IF_EXISTS:
        return (_finding(ValidationSeverity.ERROR, PreflightCode.TARGET_CONFLICT),)
    return (_finding(ValidationSeverity.INFO, PreflightCode.OUTPUT_ROOT_READY),)


def _existing_ancestors(path: Path) -> tuple[Path, ...]:
    current = path
    found: list[Path] = []
    while True:
        if current.exists():
            found.append(current)
        if current.parent == current:
            break
        current = current.parent
    return tuple(found)


def _finding(severity: ValidationSeverity, code: PreflightCode) -> PreflightFinding:
    messages = {
        PreflightCode.IMMEDIATE_CAPACITY: "Active capacity is currently available",
        PreflightCode.LIKELY_QUEUED: "Submission is currently likely to enter the FIFO queue",
        PreflightCode.QUEUE_FULL: "The waiting queue is currently full",
        PreflightCode.ACTIVE_DUPLICATE: "A non-terminal job has the same deterministic run ID",
        PreflightCode.REGISTRY_NOT_ACCEPTING: "The registry is not accepting submissions",
        PreflightCode.OUTPUT_ROOT_READY: "The requested output root is structurally ready",
        PreflightCode.OUTPUT_ROOT_CREATION_REQUIRED: "Output directory creation would be required",
        PreflightCode.OUTPUT_ROOT_BLOCKED: "The requested output root is structurally unsafe",
        PreflightCode.TARGET_CONFLICT: "A known output target already exists",
        PreflightCode.DRY_RUN: "Publication or summary writing is configured as dry run",
        PreflightCode.ADVISORY_ONLY: "Preflight reserves no capacity; submission is authoritative",
    }
    return PreflightFinding(severity, code, messages[code])
