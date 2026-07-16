"""Framework-independent persistence observer and repository protocols."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from musimack_tools.domain.persistence import (
    CleanupResult,
    PersistedJobMetadata,
    PersistenceDiagnostics,
    PersistenceOperationResult,
    ReconciliationReport,
)

if TYPE_CHECKING:
    from musimack_tools.domain.job import (
        JobCoordinationFailure,
        JobCoordinationWarning,
        JobSnapshot,
    )
    from musimack_tools.domain.run import CrawlRunRequest, CrawlRunResult
    from musimack_tools.domain.run_progress import RunProgressEvent


class JobPersistenceObserver(Protocol):
    """Observe accepted in-memory state without becoming its authority."""

    def record_submission(
        self,
        snapshot: JobSnapshot,
        request: CrawlRunRequest,
    ) -> PersistenceOperationResult: ...

    def record_transition(self, snapshot: JobSnapshot) -> PersistenceOperationResult: ...

    def record_progress(
        self,
        job_id: str,
        run_id: str,
        event: RunProgressEvent,
    ) -> PersistenceOperationResult: ...

    def record_terminal(
        self,
        snapshot: JobSnapshot,
        result: CrawlRunResult | None,
        warnings: tuple[JobCoordinationWarning, ...],
        failure: JobCoordinationFailure | None,
    ) -> PersistenceOperationResult: ...


class PersistenceRepository(JobPersistenceObserver, Protocol):
    def diagnostics(self) -> PersistenceDiagnostics: ...

    def reconcile_interrupted(self) -> ReconciliationReport: ...

    def highest_attempts(self) -> tuple[tuple[str, int], ...]: ...

    def retained_terminal_jobs(self) -> tuple[PersistedJobMetadata, ...]: ...

    def cleanup(self) -> CleanupResult: ...

    def dispose(self) -> None: ...


class NullPersistenceRepository:
    """No-op implementation preserving the accepted in-memory execution path."""

    _success = PersistenceOperationResult(succeeded=True)

    def record_submission(
        self,
        snapshot: JobSnapshot,
        request: CrawlRunRequest,
    ) -> PersistenceOperationResult:
        del snapshot, request
        return self._success

    def record_transition(self, snapshot: JobSnapshot) -> PersistenceOperationResult:
        del snapshot
        return self._success

    def record_progress(
        self,
        job_id: str,
        run_id: str,
        event: RunProgressEvent,
    ) -> PersistenceOperationResult:
        del job_id, run_id, event
        return self._success

    def record_terminal(
        self,
        snapshot: JobSnapshot,
        result: CrawlRunResult | None,
        warnings: tuple[JobCoordinationWarning, ...],
        failure: JobCoordinationFailure | None,
    ) -> PersistenceOperationResult:
        del snapshot, result, warnings, failure
        return self._success

    def diagnostics(self) -> PersistenceDiagnostics:
        from musimack_tools.domain.persistence import (  # noqa: PLC0415
            PersistenceReadinessState,
            ReconciliationState,
        )

        return PersistenceDiagnostics(
            state=PersistenceReadinessState.DISABLED,
            enabled=False,
            database_reachable=False,
            sqlite_version=None,
            foreign_keys_enabled=None,
            journal_mode=None,
            schema_current=False,
            pending_migration=False,
            repository_ready=False,
            reconciliation=ReconciliationState.NOT_REQUIRED,
        )

    def reconcile_interrupted(self) -> ReconciliationReport:
        from musimack_tools.domain.persistence import ReconciliationState  # noqa: PLC0415

        return ReconciliationReport(ReconciliationState.NOT_REQUIRED, 0, 0, 0, ())

    def highest_attempts(self) -> tuple[tuple[str, int], ...]:
        return ()

    def retained_terminal_jobs(self) -> tuple[PersistedJobMetadata, ...]:
        return ()

    def cleanup(self) -> CleanupResult:
        return CleanupResult(0, 0, 0, 0, 0, 0, 0)

    def dispose(self) -> None:
        return None
