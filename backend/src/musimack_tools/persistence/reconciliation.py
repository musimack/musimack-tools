"""Restart reconciliation and attempt/bootstrap recovery composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from musimack_tools.domain.persistence import PersistedJobMetadata, ReconciliationReport
    from musimack_tools.domain.storage import PersistenceRepository


@dataclass(frozen=True, slots=True)
class PersistenceBootstrap:
    reconciliation: ReconciliationReport
    recovered_attempts: tuple[tuple[str, int], ...]
    retained_terminal_jobs: tuple[PersistedJobMetadata, ...]


def reconcile_and_bootstrap(repository: PersistenceRepository) -> PersistenceBootstrap:
    report = repository.reconcile_interrupted()
    return PersistenceBootstrap(
        report,
        repository.highest_attempts(),
        repository.retained_terminal_jobs(),
    )
