"""Bounded application-facing projections over accepted job and run evidence."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, TypedDict

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


class _OperationalProjection(TypedDict):
    crawl_elapsed_seconds: float | None
    outbound_request_count: int
    outbound_redirect_count: int
    rejected_destination_count: int
    resolved_address_fingerprints: tuple[str, ...]
    robots_outcome_counts: tuple[tuple[str, int], ...]
    dns_resolution_count: int
    robots_request_count: int
    page_request_count: int
    accepted_byte_count: int
    scope_denial_count: int
    retry_count: int
    timeout_count: int
    response_size_rejection_count: int


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
                crawl_elapsed_seconds=durable.crawl_elapsed_seconds,
                outbound_request_count=durable.outbound_request_count,
                outbound_redirect_count=durable.outbound_redirect_count,
                rejected_destination_count=durable.rejected_destination_count,
                resolved_address_fingerprints=durable.resolved_address_fingerprints,
                robots_outcome_counts=durable.robots_outcome_counts,
                dns_resolution_count=durable.dns_resolution_count,
                robots_request_count=durable.robots_request_count,
                page_request_count=durable.page_request_count,
                accepted_byte_count=durable.accepted_byte_count,
                scope_denial_count=durable.scope_denial_count,
                retry_count=durable.retry_count,
                timeout_count=durable.timeout_count,
                response_size_rejection_count=durable.response_size_rejection_count,
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
                ("urls_admitted", crawl.counters.urls_queued),
                ("urls_over_limit", crawl.counters.urls_over_limit),
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
        **_operational(crawl),
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


def _operational(crawl: object | None) -> _OperationalProjection:
    if crawl is None:
        return {
            "crawl_elapsed_seconds": None,
            "outbound_request_count": 0,
            "outbound_redirect_count": 0,
            "rejected_destination_count": 0,
            "resolved_address_fingerprints": (),
            "robots_outcome_counts": (),
            "dns_resolution_count": 0,
            "robots_request_count": 0,
            "page_request_count": 0,
            "accepted_byte_count": 0,
            "scope_denial_count": 0,
            "retry_count": 0,
            "timeout_count": 0,
            "response_size_rejection_count": 0,
        }
    records = tuple(getattr(crawl, "url_records", ()))
    fetches = tuple(
        fetch for record in records if (fetch := getattr(record, "fetch_result", None)) is not None
    )
    robots = tuple(getattr(crawl, "robots_origins", ()))
    codes = tuple(getattr(getattr(fetch, "failure_code", None), "value", None) for fetch in fetches)
    all_codes = (*codes, *(record.fetch_failure_code for record in robots))
    return {
        "crawl_elapsed_seconds": _elapsed_seconds(
            getattr(crawl, "started_at_seconds", None),
            getattr(crawl, "ended_at_seconds", None),
        ),
        "outbound_request_count": sum(fetch.attempt_count for fetch in fetches)
        + sum(record.request_attempt_count for record in robots),
        "outbound_redirect_count": sum(len(fetch.redirect_chain) for fetch in fetches)
        + sum(record.redirect_count for record in robots),
        "rejected_destination_count": sum(
            code
            in {
                "unsupported_scheme",
                "credentials_not_allowed",
                "invalid_hostname",
                "ip_literal_not_allowed",
                "unsafe_hostname",
                "unsafe_resolved_address",
                "mixed_safe_unsafe_dns_answers",
                "port_not_allowed",
                "redirect_scope_denied",
                "redirect_unsafe_destination",
            }
            for code in all_codes
        ),
        "resolved_address_fingerprints": tuple(
            sorted(
                {
                    hashlib.sha256(address.encode("ascii")).hexdigest()
                    for fetch in fetches
                    for evidence in fetch.dns_evidence
                    for address in evidence.addresses
                }
                | {fingerprint for record in robots for fingerprint in record.address_fingerprints}
            )[:256]
        ),
        "robots_outcome_counts": tuple(
            sorted(
                {
                    outcome: sum(record.fetch_outcome.value == outcome for record in robots)
                    for outcome in {record.fetch_outcome.value for record in robots}
                }.items()
            )
        ),
        "dns_resolution_count": sum(len(fetch.dns_evidence) for fetch in fetches)
        + sum(record.dns_resolution_count for record in robots),
        "robots_request_count": sum(record.request_attempt_count for record in robots),
        "page_request_count": sum(fetch.attempt_count for fetch in fetches),
        "accepted_byte_count": int(getattr(crawl, "total_accepted_bytes", 0)),
        "scope_denial_count": sum(
            code in {"scope_denied", "redirect_scope_denied"} for code in all_codes
        ),
        "retry_count": sum(max(0, fetch.attempt_count - 1) for fetch in fetches)
        + sum(max(0, record.request_attempt_count - 1) for record in robots),
        "timeout_count": sum(
            code
            in {
                "connect_timeout",
                "read_timeout",
                "write_timeout",
                "pool_timeout",
                "request_deadline_exceeded",
                "dns_resolution_timeout",
            }
            for code in all_codes
        ),
        "response_size_rejection_count": sum(code == "response_too_large" for code in all_codes),
    }


def _elapsed_seconds(started: object, ended: object) -> float | None:
    """Convert monotonic crawl markers to a duration without exposing them as instants."""
    if not isinstance(started, (int, float)) or isinstance(started, bool):
        return None
    if not isinstance(ended, (int, float)) or isinstance(ended, bool) or ended < started:
        return None
    return float(ended - started)


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
