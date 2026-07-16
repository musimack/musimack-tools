"""Internal readiness and static capability reports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from musimack_tools.domain.application import (
    ApplicationReadinessReport,
    ApplicationServiceConfiguration,
    ReadinessCheck,
    ReadinessCheckCode,
    ReadinessState,
)
from musimack_tools.domain.capabilities import ApplicationCapabilityReport
from musimack_tools.domain.job_registry import RegistryState

if TYPE_CHECKING:
    from musimack_tools.domain.job_registry import JobRegistrySnapshot


def capability_report() -> ApplicationCapabilityReport:
    return ApplicationCapabilityReport()


def readiness_report(
    registry: JobRegistrySnapshot,
    configuration: ApplicationServiceConfiguration,
) -> ApplicationReadinessReport:
    checks: list[ReadinessCheck] = [
        _check(ReadinessCheckCode.SERVICE_INITIALIZED, ReadinessState.READY),
    ]
    if registry.state is RegistryState.CLOSED:
        checks.append(_check(ReadinessCheckCode.REGISTRY_CLOSED, ReadinessState.NOT_READY))
    elif registry.state is RegistryState.SHUTTING_DOWN:
        checks.append(_check(ReadinessCheckCode.REGISTRY_SHUTTING_DOWN, ReadinessState.NOT_READY))
    else:
        checks.append(_check(ReadinessCheckCode.REGISTRY_ACCEPTING, ReadinessState.READY))

    required = (
        (ReadinessCheckCode.COORDINATOR_AVAILABLE, configuration.coordinator_available),
        (ReadinessCheckCode.CRAWL_AVAILABLE, configuration.crawl_service_available),
        (ReadinessCheckCode.ROBOTS_AVAILABLE, configuration.robots_service_available),
    )
    optional = (
        (
            ReadinessCheckCode.RECOMMENDATION_AVAILABLE,
            configuration.recommendation_service_available,
        ),
        (ReadinessCheckCode.XML_AVAILABLE, configuration.xml_service_available),
        (ReadinessCheckCode.PUBLICATION_AVAILABLE, configuration.publication_service_available),
        (ReadinessCheckCode.SUMMARY_AVAILABLE, configuration.summary_service_available),
    )
    checks.extend(
        _check(code, ReadinessState.READY if available else ReadinessState.NOT_READY)
        for code, available in required
    )
    checks.extend(
        _check(code, ReadinessState.READY if available else ReadinessState.DEGRADED)
        for code, available in optional
    )
    checks.append(_check(ReadinessCheckCode.VERSIONS_RECOGNIZED, ReadinessState.READY))
    queue_full = (
        registry.counters.active_jobs >= registry.configuration.maximum_concurrent_jobs
        and registry.counters.queued_jobs >= registry.configuration.maximum_queued_jobs
    )
    checks.append(
        _check(
            (
                ReadinessCheckCode.QUEUE_FULL
                if queue_full
                else ReadinessCheckCode.QUEUE_CAPACITY_AVAILABLE
            ),
            ReadinessState.DEGRADED if queue_full else ReadinessState.READY,
        )
    )
    if registry.configuration.maximum_retained_terminal_jobs == 0:
        checks.append(_check(ReadinessCheckCode.RETENTION_DISABLED, ReadinessState.DEGRADED))
    state = (
        ReadinessState.NOT_READY
        if any(item.state is ReadinessState.NOT_READY for item in checks)
        else ReadinessState.DEGRADED
        if any(item.state is ReadinessState.DEGRADED for item in checks)
        else ReadinessState.READY
    )
    return ApplicationReadinessReport(
        state,
        tuple(checks),
        registry.counters.active_jobs,
        registry.counters.queued_jobs,
        registry.counters.terminal_jobs_retained,
    )


def _check(code: ReadinessCheckCode, state: ReadinessState) -> ReadinessCheck:
    return ReadinessCheck(code, state, code.value.replace("_", " ").capitalize())
