"""Explicit persistence cleanup service; it never touches filesystem artifacts."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from musimack_tools.domain.persistence import CleanupResult
    from musimack_tools.domain.storage import PersistenceRepository


class PersistenceCleanupService:
    def __init__(self, repository: PersistenceRepository) -> None:
        self._repository = repository

    def execute(self) -> CleanupResult:
        return self._repository.cleanup()
