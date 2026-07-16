"""Deterministic temporary persistence fixtures shared by focused tests."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import create_scope_policy
from musimack_tools.domain.crawl import CrawlRequest
from musimack_tools.domain.job import JobSnapshot, JobState
from musimack_tools.domain.persistence import (
    PersistenceConfiguration,
    PersistenceRetentionPolicy,
)
from musimack_tools.domain.run import (
    CrawlRunRequest,
    CrawlRunResult,
    RunLifecycle,
    RunStage,
    RunStageRecord,
    RunStageState,
)
from musimack_tools.domain.run_progress import (
    RunEventCode,
    RunProgressEvent,
    RunProgressSnapshot,
)
from musimack_tools.jobs.identity import job_identifier
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.migrations import upgrade_to_head
from musimack_tools.persistence.repositories import SQLAlchemyPersistenceRepository
from musimack_tools.run.identity import configuration_snapshot, run_identity

BACKEND_ROOT = Path(__file__).parents[1]

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def cleanup_persistence_test_artifacts(tmp_path: Path) -> Iterator[None]:
    """Remove SQLite and offline-SQL artifacts instead of relying on Pytest retention."""
    yield
    for candidate in tmp_path.rglob("*"):
        if candidate.is_file() and (
            candidate.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".sql"}
            or candidate.name.endswith(("-wal", "-shm"))
        ):
            candidate.unlink()


def sample_request(path: str = "/") -> CrawlRunRequest:
    seed = normalize_url(f"https://example.com{path}")
    return CrawlRunRequest(
        CrawlRequest(seed, create_scope_policy(seed), maximum_unique_urls=10),
        (RunStage.CRAWL,),
    )


def sample_snapshot(
    request: CrawlRunRequest,
    *,
    state: JobState = JobState.ACCEPTED,
    attempt: int = 1,
) -> JobSnapshot:
    run_id, _ = run_identity(request)
    lifecycle = RunLifecycle.COMPLETED if state.terminal else None
    return JobSnapshot(
        job_id=job_identifier(run_id, attempt),
        run_id=run_id,
        attempt_number=attempt,
        state=state,
        queue_position=None,
        run_lifecycle=lifecycle,
        active_stage=None,
        latest_progress=None,
        warning_count=0,
        failure_count=0,
        cancellation_requested=False,
        final_result_available=state.terminal,
        summary_artifact_count=0,
        terminal=state.terminal,
        registry_version="crawl-job-registry-v1",
    )


def sample_progress(sequence: int = 1) -> RunProgressEvent:
    return RunProgressEvent(
        sequence,
        RunEventCode.STAGE_STARTED,
        RunProgressSnapshot(
            RunLifecycle.RUNNING,
            RunStage.CRAWL,
            RunStageState.RUNNING,
            urls_discovered=sequence,
            urls_queued=sequence,
            elapsed_seconds=float(sequence),
        ),
        "Crawl stage started",
    )


def sample_result(request: CrawlRunRequest) -> CrawlRunResult:
    run_id, digest = run_identity(request)
    return CrawlRunResult(
        run_id,
        digest,
        request.caller_label,
        RunLifecycle.COMPLETED,
        (RunStageRecord(RunStage.CRAWL, RunStageState.COMPLETED),),
        configuration_snapshot(request),
    )


def repository_for(
    root: Path,
    *,
    retention: PersistenceRetentionPolicy | None = None,
) -> SQLAlchemyPersistenceRepository:
    database = root / "persistence.db"
    configuration = PersistenceConfiguration(
        enabled=True,
        database_path=database,
        retention=retention or PersistenceRetentionPolicy(),
    )
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    upgrade_to_head(url, backend_root=BACKEND_ROOT)
    runtime = create_persistence_runtime(configuration)
    return SQLAlchemyPersistenceRepository(runtime)
