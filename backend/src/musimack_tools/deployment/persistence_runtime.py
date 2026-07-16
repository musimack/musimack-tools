"""Explicit startup ordering for optional persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from musimack_tools.domain.persistence import (
    PersistenceDiagnostics,
    PersistenceReadinessState,
    ReconciliationReport,
    ReconciliationState,
)
from musimack_tools.domain.storage import NullPersistenceRepository, PersistenceRepository
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.migrations import upgrade_to_head
from musimack_tools.persistence.reconciliation import PersistenceBootstrap, reconcile_and_bootstrap
from musimack_tools.persistence.repositories import SQLAlchemyPersistenceRepository

if TYPE_CHECKING:
    from pathlib import Path

    from musimack_tools.deployment.persistence import PersistenceSettings

_NOT_READY = "persistence is not ready; migration or configuration required"
_RECONCILIATION_FAILED = "persistence restart reconciliation failed"


@dataclass(frozen=True, slots=True)
class PreparedPersistence:
    repository: PersistenceRepository
    diagnostics: PersistenceDiagnostics
    bootstrap: PersistenceBootstrap | None


class PersistenceStartupError(RuntimeError):
    pass


def prepare_persistence(
    settings: PersistenceSettings,
    *,
    backend_root: Path,
    repository_root: Path,
    durable_queue_authority: bool = False,
) -> PreparedPersistence:
    configuration = settings.to_configuration()
    if not configuration.enabled:
        repository: PersistenceRepository = NullPersistenceRepository()
        return PreparedPersistence(repository, repository.diagnostics(), None)
    runtime = create_persistence_runtime(configuration, repository_root=repository_root)
    if configuration.auto_migrate:
        upgrade_to_head(str(runtime.engine.url), backend_root=backend_root)
    repository = SQLAlchemyPersistenceRepository(runtime)
    diagnostics = repository.diagnostics()
    if diagnostics.state is not PersistenceReadinessState.READY:
        repository.dispose()
        raise PersistenceStartupError(_NOT_READY)
    bootstrap = (
        reconcile_and_bootstrap(repository)
        if configuration.reconcile_on_startup and not durable_queue_authority
        else PersistenceBootstrap(
            repository.reconcile_interrupted()
            if diagnostics.reconciliation is ReconciliationState.REQUIRED
            and not durable_queue_authority
            else ReconciliationReport(ReconciliationState.NOT_REQUIRED, 0, 0, 0, ()),
            repository.highest_attempts(),
            repository.retained_terminal_jobs(),
        )
    )
    if bootstrap.reconciliation.state is ReconciliationState.FAILED:
        repository.dispose()
        raise PersistenceStartupError(_RECONCILIATION_FAILED)
    return PreparedPersistence(repository, repository.diagnostics(), bootstrap)
