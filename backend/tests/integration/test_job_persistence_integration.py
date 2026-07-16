"""In-memory registry observation, failure isolation, and restart bootstrap tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from musimack_tools.domain.job import (
    JobCoordinationWarning,
    JobState,
    JobSubmissionOutcome,
    JobSubmissionRequest,
)
from musimack_tools.domain.persistence import (
    PersistedJobMetadata,
    PersistenceFailureCode,
    PersistenceOperationResult,
)
from musimack_tools.jobs.registry import InMemoryJobRegistry
from persistence_helpers import sample_request, sample_result

if TYPE_CHECKING:
    from musimack_tools.crawl.cancellation import CancellationToken
    from musimack_tools.domain.job import (
        JobCoordinationFailure,
        JobSnapshot,
    )
    from musimack_tools.domain.run import CrawlRunRequest, CrawlRunResult
    from musimack_tools.domain.run_progress import RunProgressEvent
    from musimack_tools.run.progress import RunProgressSink


@dataclass
class RecordingPersistence:
    submissions: list[str] = field(default_factory=list)
    transitions: list[str] = field(default_factory=list)
    progress_events: list[int] = field(default_factory=list)
    terminals: list[str] = field(default_factory=list)
    fail_terminal: bool = False

    def record_submission(
        self, snapshot: JobSnapshot, request: CrawlRunRequest
    ) -> PersistenceOperationResult:
        del request
        self.submissions.append(snapshot.job_id)
        return PersistenceOperationResult(succeeded=True)

    def record_transition(self, snapshot: JobSnapshot) -> PersistenceOperationResult:
        self.transitions.append(snapshot.state.value)
        return PersistenceOperationResult(succeeded=True)

    def record_progress(
        self,
        job_id: str,
        run_id: str,
        event: RunProgressEvent,
    ) -> PersistenceOperationResult:
        del job_id, run_id
        self.progress_events.append(event.sequence)
        return PersistenceOperationResult(succeeded=True)

    def record_terminal(
        self,
        snapshot: JobSnapshot,
        result: CrawlRunResult | None,
        warnings: tuple[JobCoordinationWarning, ...],
        failure: JobCoordinationFailure | None,
    ) -> PersistenceOperationResult:
        del result, warnings, failure
        self.terminals.append(snapshot.state.value)
        if self.fail_terminal:
            return PersistenceOperationResult(
                succeeded=False,
                failure_code=PersistenceFailureCode.DATABASE_WRITE_FAILED,
            )
        return PersistenceOperationResult(succeeded=True)


class ImmediateExecutor:
    async def execute(self, request: CrawlRunRequest) -> CrawlRunResult:
        return sample_result(request)


def _factory(
    cancellation: CancellationToken,
    progress_sink: RunProgressSink,
) -> ImmediateExecutor:
    del cancellation, progress_sink
    return ImmediateExecutor()


@pytest.mark.anyio
async def test_registry_persists_submission_transition_and_terminal() -> None:
    persistence = RecordingPersistence()
    registry = InMemoryJobRegistry(_factory, persistence=persistence)
    result = await registry.submit(JobSubmissionRequest(sample_request()))
    assert result.outcome is JobSubmissionOutcome.ACCEPTED
    assert result.snapshot is not None
    completed = await registry.wait_for_completion(result.snapshot.job_id)
    assert completed.result is not None
    assert persistence.submissions == [result.snapshot.job_id]
    assert persistence.transitions == ["running"]
    assert persistence.terminals == ["completed"]
    await registry.shutdown()


@pytest.mark.anyio
async def test_terminal_persistence_failure_preserves_in_memory_result() -> None:
    persistence = RecordingPersistence(fail_terminal=True)
    registry = InMemoryJobRegistry(_factory, persistence=persistence)
    submission = await registry.submit(JobSubmissionRequest(sample_request()))
    assert submission.snapshot is not None
    completed = await registry.wait_for_completion(submission.snapshot.job_id)
    assert completed.result is not None
    assert completed.result.full_result is not None
    assert completed.result.coordination_warnings == (
        JobCoordinationWarning(
            "database_write_failed",
            "Durable persistence did not record accepted evidence",
        ),
    )
    await registry.shutdown()


@pytest.mark.anyio
async def test_recovered_attempt_counter_allocates_next_attempt() -> None:
    request = sample_request()
    from musimack_tools.run.identity import run_identity  # noqa: PLC0415

    run_id, _ = run_identity(request)
    registry = InMemoryJobRegistry(_factory, recovered_attempts=((run_id, 4),))
    submission = await registry.submit(JobSubmissionRequest(request))
    assert submission.snapshot is not None
    assert submission.snapshot.attempt_number == 5
    assert submission.snapshot.job_id.endswith("-0005")
    await registry.wait_for_completion(submission.snapshot.job_id)
    await registry.shutdown()


@pytest.mark.anyio
async def test_persisted_terminal_metadata_bootstraps_without_task_or_result() -> None:
    metadata = PersistedJobMetadata(
        job_id="job-0123456789ab-0001",
        run_id="run-0123456789ab",
        attempt_number=1,
        state=JobState.COMPLETED.value,
        terminal=True,
        result_available=True,
        warning_count=2,
        failure_count=0,
        latest_progress_sequence=9,
    )
    registry = InMemoryJobRegistry(_factory, persisted_terminal_jobs=(metadata,))
    lookup = await registry.lookup(metadata.job_id)
    result = await registry.result(metadata.job_id)
    snapshot = await registry.snapshot()
    assert lookup.snapshot is not None and lookup.snapshot.terminal
    assert result.full_result is None
    assert result.summaries == ()
    assert snapshot.active_job_ids == ()
    assert snapshot.queued_job_ids == ()
    await registry.shutdown()
