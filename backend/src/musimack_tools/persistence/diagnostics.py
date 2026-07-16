"""Portable persistence diagnostics composition."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from musimack_tools.domain.persistence import PersistenceDiagnostics
    from musimack_tools.domain.storage import PersistenceRepository


def persistence_diagnostics(repository: PersistenceRepository) -> PersistenceDiagnostics:
    return repository.diagnostics()
