"""Explicit durable repository and worker composition without import-time tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from musimack_tools.domain.durable_execution import (
    DurableDiagnostics,
    DurableExecutionConfiguration,
)
from musimack_tools.domain.persistence import PersistenceReadinessState
from musimack_tools.durable.worker import DurableWorkerService
from musimack_tools.persistence.durable_repository import (
    SQLAlchemyDurableExecutionRepository,
)

if TYPE_CHECKING:
    from musimack_tools.deployment.durable import DurableExecutionSettings
    from musimack_tools.deployment.persistence_runtime import PreparedPersistence
    from musimack_tools.jobs.coordinator import JobRunServiceFactory
    from musimack_tools.persistence.engine import PersistenceRuntime


@dataclass(frozen=True, slots=True)
class PreparedDurableExecution:
    configuration: DurableExecutionConfiguration
    repository: SQLAlchemyDurableExecutionRepository | None
    worker: DurableWorkerService | None
    diagnostics: DurableDiagnostics


class DurableExecutionStartupError(RuntimeError):
    pass


_PERSISTENCE_REQUIRED = "durable execution requires ready persistence"
_FACTORY_REQUIRED = "enabled worker requires a run-service factory"


def prepare_durable_execution(
    settings: DurableExecutionSettings,
    persistence: PreparedPersistence,
    *,
    runtime: PersistenceRuntime | None = None,
    run_service_factory: JobRunServiceFactory | None = None,
) -> PreparedDurableExecution:
    configuration = settings.to_configuration()
    if not configuration.enabled:
        return PreparedDurableExecution(
            configuration,
            None,
            None,
            DurableDiagnostics(
                enabled=False,
                worker_enabled=False,
                worker_registered=False,
                worker_state=None,
                queue_depth=0,
                claimable_jobs=0,
                claimed_jobs=0,
                retry_wait_jobs=0,
                stale_workers=0,
                stale_leases=0,
                heartbeat_healthy=True,
                persistence_ready=(
                    persistence.diagnostics.state
                    in {PersistenceReadinessState.DISABLED, PersistenceReadinessState.READY}
                ),
                migration_current=persistence.diagnostics.schema_current,
                recovery_complete=True,
                cancellation_backlog=0,
                lease_expiration_count=0,
                retry_count=0,
            ),
        )
    if persistence.diagnostics.state is not PersistenceReadinessState.READY or runtime is None:
        raise DurableExecutionStartupError(_PERSISTENCE_REQUIRED)
    repository = SQLAlchemyDurableExecutionRepository(runtime, configuration)
    worker = None
    if configuration.worker_enabled:
        if run_service_factory is None:
            raise DurableExecutionStartupError(_FACTORY_REQUIRED)
        worker = DurableWorkerService(repository, run_service_factory)
    diagnostics = repository.diagnostics(
        configuration.worker_id.value if configuration.worker_id is not None else None,
        recovery_complete=not configuration.worker_enabled,
    )
    return PreparedDurableExecution(configuration, repository, worker, diagnostics)
