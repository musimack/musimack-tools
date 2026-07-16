"""Transactional durable job, run, progress, metadata, and retention tests."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from musimack_tools.domain.job import JobCoordinationWarning, JobState
from musimack_tools.domain.persistence import (
    PersistenceFailureCode,
    PersistenceReadinessState,
    PersistenceRetentionPolicy,
    ReconciliationState,
)
from musimack_tools.domain.run import RunFailure, RunFailureCode, RunStage, RunWarning
from musimack_tools.domain.run_summary import RunSummaryArtifact, RunSummaryFormat
from musimack_tools.persistence.models import (
    ArtifactMetadataModel,
    ConfigurationSnapshotModel,
    FailureModel,
    JobModel,
    ProgressSnapshotModel,
    RunModel,
    RunStageModel,
    SummaryMetadataModel,
    WarningModel,
)
from persistence_helpers import (
    cleanup_persistence_test_artifacts,  # noqa: F401
    repository_for,
    sample_progress,
    sample_request,
    sample_result,
    sample_snapshot,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_submission_persists_job_run_and_deduplicated_configuration(tmp_path: Path) -> None:
    repository = repository_for(tmp_path)
    request = sample_request()
    first = sample_snapshot(request)
    second = sample_snapshot(request, attempt=2)
    try:
        assert repository.record_submission(first, request).succeeded
        assert repository.record_submission(second, request).succeeded
        with repository._runtime.transaction() as session:  # noqa: SLF001 - storage audit.
            assert session.scalar(select(func.count()).select_from(JobModel)) == 2
            assert session.scalar(select(func.count()).select_from(RunModel)) == 1
            assert session.scalar(select(func.count()).select_from(ConfigurationSnapshotModel)) == 1
            run = session.get(RunModel, first.run_id)
            assert run is not None
            assert "?" not in run.normalized_seed_url
    finally:
        repository.dispose()


def test_transition_updates_job_without_partial_rows(tmp_path: Path) -> None:
    repository = repository_for(tmp_path)
    request = sample_request()
    snapshot = sample_snapshot(request)
    try:
        repository.record_submission(snapshot, request)
        running = replace(snapshot, state=JobState.RUNNING)
        assert repository.record_transition(running).succeeded
        with repository._runtime.transaction() as session:  # noqa: SLF001
            job = session.get(JobModel, snapshot.job_id)
            assert job is not None
            assert job.state == "running"
            assert job.started_sequence == job.created_sequence
    finally:
        repository.dispose()


def test_unknown_transition_has_stable_failure(tmp_path: Path) -> None:
    repository = repository_for(tmp_path)
    try:
        result = repository.record_transition(sample_snapshot(sample_request()))
        assert not result.succeeded
        assert result.failure_code is PersistenceFailureCode.RECORD_NOT_FOUND
    finally:
        repository.dispose()


def test_progress_is_persisted_and_oldest_rows_are_truncated(tmp_path: Path) -> None:
    retention = PersistenceRetentionPolicy(maximum_progress_rows_per_job=2)
    repository = repository_for(tmp_path, retention=retention)
    request = sample_request()
    snapshot = sample_snapshot(request)
    try:
        repository.record_submission(snapshot, request)
        for sequence in range(1, 5):
            assert repository.record_progress(
                snapshot.job_id, snapshot.run_id, sample_progress(sequence)
            ).succeeded
        with repository._runtime.transaction() as session:  # noqa: SLF001
            rows = tuple(
                session.scalars(
                    select(ProgressSnapshotModel)
                    .where(ProgressSnapshotModel.job_id == snapshot.job_id)
                    .order_by(ProgressSnapshotModel.sequence)
                )
            )
            assert [row.sequence for row in rows] == [3, 4]
            stages = tuple(session.scalars(select(RunStageModel)))
            assert [(item.stage, item.state) for item in stages] == [("crawl", "running")]
    finally:
        repository.dispose()


def test_terminal_transaction_persists_run_warnings_failures_and_summaries(
    tmp_path: Path,
) -> None:
    repository = repository_for(tmp_path)
    request = sample_request()
    submitted = sample_snapshot(request)
    summary = RunSummaryArtifact("run-summary.json", RunSummaryFormat.JSON, b"{}", 2, "a" * 64)
    run_result = replace(
        sample_result(request),
        summaries=(summary,),
        warnings=(RunWarning("metadata_warning", RunStage.CRAWL, "Safe warning"),),
        failures=(RunFailure(RunFailureCode.CRAWL_FAILED, RunStage.CRAWL, "Safe failure"),),
    )
    terminal = sample_snapshot(request, state=JobState.COMPLETED_WITH_WARNINGS)
    try:
        repository.record_submission(submitted, request)
        outcome = repository.record_terminal(
            terminal,
            run_result,
            (JobCoordinationWarning("coordination_warning", "Safe coordination warning"),),
            None,
        )
        assert outcome.succeeded
        with repository._runtime.transaction() as session:  # noqa: SLF001
            job = session.get(JobModel, terminal.job_id)
            run = session.get(RunModel, terminal.run_id)
            assert job is not None and job.terminal
            assert run is not None and run.final_result_available and run.summary_available
            assert session.scalar(select(func.count()).select_from(WarningModel)) == 2
            assert session.scalar(select(func.count()).select_from(FailureModel)) == 1
            assert session.scalar(select(func.count()).select_from(SummaryMetadataModel)) == 1
            assert session.scalar(select(func.count()).select_from(ArtifactMetadataModel)) == 1
            assert session.scalar(select(SummaryMetadataModel.sha256)) == "a" * 64
    finally:
        repository.dispose()


def test_diagnostics_are_ready_after_migration(tmp_path: Path) -> None:
    repository = repository_for(tmp_path)
    try:
        diagnostics = repository.diagnostics()
        assert diagnostics.state is PersistenceReadinessState.READY
        assert diagnostics.schema_current
        assert diagnostics.foreign_keys_enabled
        assert diagnostics.journal_mode == "WAL"
        assert "tmp" not in repr(diagnostics).lower()
    finally:
        repository.dispose()


def test_restart_reconciliation_marks_running_job_failed_and_recovers_attempt(
    tmp_path: Path,
) -> None:
    repository = repository_for(tmp_path)
    request = sample_request()
    submitted = sample_snapshot(request)
    try:
        repository.record_submission(submitted, request)
        repository.record_transition(replace(submitted, state=JobState.RUNNING))
        report = repository.reconcile_interrupted()
        assert report.state is ReconciliationState.COMPLETED
        assert report.interrupted_jobs == 1
        assert report.interruption_code == "process_restart_interrupted"
        assert report.highest_attempts == ((submitted.run_id, 1),)
        with repository._runtime.transaction() as session:  # noqa: SLF001
            job = session.get(JobModel, submitted.job_id)
            assert job is not None
            assert job.state == "failed"
            assert job.terminal
            assert session.scalar(select(FailureModel.stable_code)) == (
                "process_restart_interrupted"
            )
    finally:
        repository.dispose()


def test_terminal_bootstrap_is_metadata_only(tmp_path: Path) -> None:
    repository = repository_for(tmp_path)
    request = sample_request()
    submitted = sample_snapshot(request)
    terminal = sample_snapshot(request, state=JobState.COMPLETED)
    try:
        repository.record_submission(submitted, request)
        repository.record_terminal(terminal, sample_result(request), (), None)
        records = repository.retained_terminal_jobs()
        assert len(records) == 1
        assert records[0].job_id == terminal.job_id
        assert records[0].terminal
        assert records[0].result_available
        assert repository.highest_attempts() == ((terminal.run_id, 1),)
    finally:
        repository.dispose()


def test_cleanup_marks_oldest_terminal_metadata_evicted(tmp_path: Path) -> None:
    retention = PersistenceRetentionPolicy(maximum_terminal_jobs=1)
    repository = repository_for(tmp_path, retention=retention)
    try:
        for path in ("/one", "/two"):
            request = sample_request(path)
            submitted = sample_snapshot(request)
            repository.record_submission(submitted, request)
            repository.record_terminal(
                sample_snapshot(request, state=JobState.COMPLETED),
                sample_result(request),
                (),
                None,
            )
        cleanup = repository.cleanup()
        assert cleanup.terminal_jobs_evicted == 1
        with repository._runtime.transaction() as session:  # noqa: SLF001
            states = tuple(
                session.scalars(select(JobModel.eviction_state).order_by(JobModel.created_sequence))
            )
            assert states == ("evicted", "retained")
    finally:
        repository.dispose()


def test_cleanup_is_idempotent(tmp_path: Path) -> None:
    repository = repository_for(tmp_path)
    try:
        first = repository.cleanup()
        second = repository.cleanup()
        assert first == second
        assert first.progress_rows_removed == 0
    finally:
        repository.dispose()
