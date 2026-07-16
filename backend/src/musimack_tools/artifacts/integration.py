"""Optional observer composition that registers terminal run artifacts."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from musimack_tools.artifacts.service import ArtifactService
    from musimack_tools.domain.job import (
        JobCoordinationFailure,
        JobCoordinationWarning,
        JobSnapshot,
    )
    from musimack_tools.domain.persistence import PersistenceOperationResult
    from musimack_tools.domain.run import CrawlRunRequest, CrawlRunResult
    from musimack_tools.domain.run_progress import RunProgressEvent
    from musimack_tools.domain.storage import JobPersistenceObserver


class ArtifactRegisteringPersistenceObserver:
    """Preserve execution persistence while attaching successful file outputs."""

    def __init__(self, delegate: JobPersistenceObserver, artifacts: ArtifactService) -> None:
        self._delegate = delegate
        self._artifacts = artifacts

    def record_submission(
        self, snapshot: JobSnapshot, request: CrawlRunRequest
    ) -> PersistenceOperationResult:
        return self._delegate.record_submission(snapshot, request)

    def record_transition(self, snapshot: JobSnapshot) -> PersistenceOperationResult:
        return self._delegate.record_transition(snapshot)

    def record_progress(
        self, job_id: str, run_id: str, event: RunProgressEvent
    ) -> PersistenceOperationResult:
        return self._delegate.record_progress(job_id, run_id, event)

    def record_terminal(
        self,
        snapshot: JobSnapshot,
        result: CrawlRunResult | None,
        warnings: tuple[JobCoordinationWarning, ...],
        failure: JobCoordinationFailure | None,
    ) -> PersistenceOperationResult:
        persisted = self._delegate.record_terminal(snapshot, result, warnings, failure)
        if persisted.succeeded and result is not None:
            self._artifacts.register_run_result(snapshot.job_id, result)
        return persisted
