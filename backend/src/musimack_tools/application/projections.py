"""Bounded application-facing projections over accepted job and run evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from musimack_tools.domain.application import (
    ApplicationJobStatus,
    ApplicationOutcomeCode,
    ApplicationResultProjection,
    ApplicationServiceConfiguration,
    ApplicationWarning,
    ValidationSeverity,
)
from musimack_tools.domain.job import JobLookupOutcome

if TYPE_CHECKING:
    from collections.abc import Iterable

    from musimack_tools.domain.job import JobLookupResult, JobResultView, JobSnapshot


def project_status(result: JobLookupResult) -> ApplicationJobStatus:
    if result.outcome is JobLookupOutcome.NOT_FOUND or result.snapshot is None:
        return _missing_status()
    return status_from_snapshot(result.snapshot)


def status_from_snapshot(snapshot: JobSnapshot) -> ApplicationJobStatus:
    progress = snapshot.latest_progress
    return ApplicationJobStatus(
        ApplicationOutcomeCode.FOUND,
        snapshot.job_id,
        snapshot.run_id,
        snapshot.attempt_number,
        snapshot.state.value,
        snapshot.queue_position,
        snapshot.active_stage.value if snapshot.active_stage is not None else None,
        snapshot.run_lifecycle.value if snapshot.run_lifecycle is not None else None,
        progress.urls_discovered if progress is not None else 0,
        progress.urls_fetched if progress is not None else 0,
        progress.recommendation_counts if progress is not None else None,
        progress.xml_document_count if progress is not None else None,
        progress.xml_entry_count if progress is not None else None,
        progress.publication_file_count if progress is not None else None,
        snapshot.warning_count,
        snapshot.failure_count,
        snapshot.cancellation_requested,
        snapshot.terminal,
        snapshot.final_result_available or snapshot.summary_artifact_count > 0,
        snapshot.registry_version,
    )


def project_result(
    view: JobResultView,
    configuration: ApplicationServiceConfiguration,
) -> ApplicationResultProjection:
    snapshot = view.snapshot
    if view.outcome is JobLookupOutcome.NOT_FOUND or snapshot is None:
        return _missing_result()
    run = view.full_result
    if run is None:
        durable = view.durable_projection
        if durable is not None:
            return ApplicationResultProjection(
                ApplicationOutcomeCode.FOUND,
                snapshot.job_id,
                snapshot.run_id,
                snapshot.attempt_number,
                snapshot.state.value,
                durable.run_lifecycle,
                durable.stage_states,
                durable.crawl_counts,
                _bounded_unique(durable.crawl_error_codes, configuration.maximum_projection_codes),
                durable.recommendation_counts,
                durable.xml_document_count,
                durable.xml_entry_count,
                durable.publication_state,
                durable.published_file_count,
                durable.publication_filenames[: configuration.maximum_projection_filenames],
                durable.manifest_sha256,
                durable.summary_hashes,
                _bounded_unique(
                    (
                        *durable.warning_codes,
                        *(item.code for item in view.coordination_warnings),
                    ),
                    configuration.maximum_projection_codes,
                ),
                _bounded_unique(
                    (
                        *durable.failure_codes,
                        *(
                            (view.coordination_failure.code.value,)
                            if view.coordination_failure is not None
                            else ()
                        ),
                    ),
                    configuration.maximum_projection_codes,
                ),
                False,  # noqa: FBT003 - durable projection is retained, not the full object.
                False,  # noqa: FBT003 - summary bodies are not retained here.
                snapshot.registry_version,
                (("job_registry", snapshot.registry_version), *durable.downstream_versions),
            )
        return ApplicationResultProjection(
            ApplicationOutcomeCode.RESULT_UNAVAILABLE,
            snapshot.job_id,
            snapshot.run_id,
            snapshot.attempt_number,
            snapshot.state.value,
            snapshot.run_lifecycle.value if snapshot.run_lifecycle is not None else None,
            (),
            (),
            (),
            (),
            snapshot.latest_progress.xml_document_count if snapshot.latest_progress else None,
            snapshot.latest_progress.xml_entry_count if snapshot.latest_progress else None,
            None,
            0,
            (),
            None,
            tuple((item.logical_name, item.sha256) for item in view.summaries),
            _bounded_unique(
                (item.code for item in view.coordination_warnings),
                configuration.maximum_projection_codes,
            ),
            (
                (view.coordination_failure.code.value,)
                if view.coordination_failure is not None
                else ()
            ),
            False,  # noqa: FBT003 - frozen projection field.
            bool(view.summaries),
            snapshot.registry_version,
            (("job_registry", snapshot.registry_version),),
        )
    crawl = run.crawl_result
    recommendations = run.recommendation_projection
    xml = run.xml_bundle
    publication = run.publication_result
    warning_codes = _bounded_unique(
        (
            *(item.code for item in run.warnings),
            *(item.code for item in view.coordination_warnings),
        ),
        configuration.maximum_projection_codes,
    )
    failure_codes = _bounded_unique(
        (
            *(item.code.value for item in run.failures),
            *(
                (view.coordination_failure.code.value,)
                if view.coordination_failure is not None
                else ()
            ),
        ),
        configuration.maximum_projection_codes,
    )
    versions = (
        ("job_registry", snapshot.registry_version),
        ("run", run.orchestration_version),
        ("recommendation", run.configuration.recommendation_rule_set_version),
        ("xml", run.configuration.xml_format_version),
        ("publication", run.configuration.publication_version),
        ("manifest", run.configuration.manifest_version),
    )
    return ApplicationResultProjection(
        ApplicationOutcomeCode.FOUND,
        snapshot.job_id,
        snapshot.run_id,
        snapshot.attempt_number,
        snapshot.state.value,
        run.lifecycle.value,
        tuple((item.stage.value, item.state.value) for item in run.stages),
        (
            ()
            if crawl is None
            else (
                ("urls_discovered", crawl.counters.unique_urls_discovered),
                ("urls_fetched", crawl.counters.urls_fetched),
                ("urls_parsed", crawl.counters.html_pages_parsed),
                ("accepted_bytes", crawl.total_accepted_bytes),
            )
        ),
        _bounded_unique(
            (() if crawl is None else (item.code.value for item in crawl.errors)),
            configuration.maximum_projection_codes,
        ),
        (
            ()
            if recommendations is None
            else (
                ("include", recommendations.included_url_count),
                ("exclude", recommendations.excluded_url_count),
                ("review", recommendations.review_count),
                ("indeterminate", recommendations.indeterminate_count),
            )
        ),
        xml.total_documents if xml is not None else None,
        xml.total_entries if xml is not None else None,
        publication.state.value if publication is not None else None,
        publication.published_file_count if publication is not None else 0,
        (
            ()
            if publication is None
            else tuple(
                item.logical_name
                for item in publication.published_files[
                    : configuration.maximum_projection_filenames
                ]
            )
        ),
        publication.manifest_sha256 if publication is not None else None,
        tuple((item.logical_name, item.sha256) for item in view.summaries),
        warning_codes,
        failure_codes,
        True,  # noqa: FBT003 - frozen projection field.
        bool(view.summaries),
        snapshot.registry_version,
        versions,
    )


def normalize_warnings(
    validation_warnings: Iterable[object],
) -> tuple[ApplicationWarning, ...]:
    """Deduplicate exact bounded warnings while preserving first-source order."""
    found: list[ApplicationWarning] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    for value in validation_warnings:
        code = str(getattr(value, "code", "application_warning"))
        message = str(getattr(value, "message", getattr(value, "explanation", code)))
        source = str(getattr(value, "source_layer", "application"))
        source_code = str(getattr(value, "source_code", code))
        url_value = getattr(value, "url", None)
        url = str(url_value) if url_value is not None else None
        key = (source, source_code, message, url)
        if key in seen:
            continue
        seen.add(key)
        found.append(
            ApplicationWarning(code, source, source_code, ValidationSeverity.WARNING, message, url)
        )
    return tuple(found)


def _bounded_unique(values: Iterable[str], maximum: int) -> tuple[str, ...]:
    found: list[str] = []
    for value in values:
        normalized = str(value)
        if normalized not in found:
            found.append(normalized)
        if len(found) == maximum:
            break
    return tuple(found)


def _missing_status() -> ApplicationJobStatus:
    return ApplicationJobStatus(
        ApplicationOutcomeCode.JOB_NOT_FOUND,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        0,
        0,
        None,
        None,
        None,
        None,
        0,
        0,
        False,  # noqa: FBT003 - frozen projection field.
        False,  # noqa: FBT003 - frozen projection field.
        False,  # noqa: FBT003 - frozen projection field.
        None,
    )


def _missing_result() -> ApplicationResultProjection:
    return ApplicationResultProjection(
        ApplicationOutcomeCode.JOB_NOT_FOUND,
        None,
        None,
        None,
        None,
        None,
        (),
        (),
        (),
        (),
        None,
        None,
        None,
        0,
        (),
        None,
        (),
        (),
        (),
        False,  # noqa: FBT003 - frozen projection field.
        False,  # noqa: FBT003 - frozen projection field.
        None,
        (),
    )
