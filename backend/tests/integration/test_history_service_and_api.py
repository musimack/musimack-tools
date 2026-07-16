"""Restart-safe repository, cursor, projection, related history, and private API tests."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from test_production_security import _SecurityTestService

from musimack_tools.artifacts.repository import SQLAlchemyArtifactRepository
from musimack_tools.artifacts.service import ArtifactService
from musimack_tools.core.config import Settings
from musimack_tools.deployment.application import create_production_app
from musimack_tools.deployment.settings import ProductionSettings
from musimack_tools.domain.artifacts import (
    ArtifactStorageConfiguration,
    ArtifactStorageRootConfiguration,
)
from musimack_tools.domain.history import (
    HISTORY_JOB_ORDERING,
    HISTORY_PAGINATION_VERSION,
    HistoryConfiguration,
    HistoryError,
    HistoryFailureCode,
    HistoryPageRequest,
    JobHistoryFilter,
    RunHistoryFilter,
)
from musimack_tools.domain.job import JobState
from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.history.service import HistoryService
from musimack_tools.main import create_app
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.history_repository import SQLAlchemyHistoryRepository
from musimack_tools.persistence.migrations import upgrade_to_head
from musimack_tools.persistence.models import ArtifactRecordModel, ArtifactStorageRootModel
from musimack_tools.persistence.repositories import SQLAlchemyPersistenceRepository
from persistence_helpers import (
    BACKEND_ROOT,
    cleanup_persistence_test_artifacts,  # noqa: F401
    sample_request,
    sample_result,
    sample_snapshot,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from musimack_tools.persistence.engine import PersistenceRuntime

_TOKEN = "history-test-token"  # noqa: S105 - inert test credential.


@pytest.fixture
def history_runtime(tmp_path: Path) -> Iterator[tuple[PersistenceRuntime, HistoryService]]:
    database = tmp_path / "history.sqlite"
    configuration = PersistenceConfiguration(enabled=True, database_path=database)
    upgrade_to_head(f"sqlite+pysqlite:///{database.as_posix()}", backend_root=BACKEND_ROOT)
    runtime = create_persistence_runtime(configuration)
    service = HistoryService(
        HistoryConfiguration(enabled=True, default_page_size=2, maximum_page_size=2),
        SQLAlchemyHistoryRepository(runtime),
    )
    yield runtime, service
    runtime.dispose()


def _seed(runtime: PersistenceRuntime, count: int = 3) -> tuple[str, ...]:
    repository = SQLAlchemyPersistenceRepository(runtime)
    identifiers = []
    for index in range(count):
        request = sample_request(f"/history-{index}")
        snapshot = sample_snapshot(request)
        assert repository.record_submission(snapshot, request).succeeded
        identifiers.append(snapshot.job_id)
    return tuple(identifiers)


def test_job_and_run_history_are_ordered_filtered_paginated_and_restart_safe(
    history_runtime: tuple[PersistenceRuntime, HistoryService],
) -> None:
    runtime, service = history_runtime
    identifiers = _seed(runtime)
    first = service.list_jobs(JobHistoryFilter(), HistoryPageRequest(2))
    assert tuple(item.job_id for item in first.items) == identifiers[::-1][:2]
    assert first.ordering == HISTORY_JOB_ORDERING
    assert first.version == HISTORY_PAGINATION_VERSION
    assert first.has_more and first.next_cursor
    second = service.list_jobs(JobHistoryFilter(), HistoryPageRequest(2, first.next_cursor))
    assert tuple(item.job_id for item in second.items) == identifiers[:1]
    assert not second.has_more and second.next_cursor is None
    assert not ({item.job_id for item in first.items} & {item.job_id for item in second.items})
    filtered = service.list_jobs(JobHistoryFilter(job_id=identifiers[1]), HistoryPageRequest(2))
    assert [item.job_id for item in filtered.items] == [identifiers[1]]
    runs = service.list_runs(RunHistoryFilter(), HistoryPageRequest(2))
    assert runs.returned_count == 2
    restarted = HistoryService(
        service.configuration,
        SQLAlchemyHistoryRepository(runtime),
    )
    assert restarted.get_job(identifiers[0]).job_id == identifiers[0]


def test_cursor_rejects_malformed_filter_mismatch_and_page_overflow(
    history_runtime: tuple[PersistenceRuntime, HistoryService],
) -> None:
    runtime, service = history_runtime
    _seed(runtime)
    with pytest.raises(HistoryError) as malformed:
        service.list_jobs(JobHistoryFilter(), HistoryPageRequest(1, "not-a-cursor"))
    assert malformed.value.code is HistoryFailureCode.INVALID_CURSOR
    first = service.list_jobs(JobHistoryFilter(), HistoryPageRequest(1))
    with pytest.raises(HistoryError) as mismatch:
        service.list_jobs(
            JobHistoryFilter(state="accepted"), HistoryPageRequest(1, first.next_cursor)
        )
    assert mismatch.value.code is HistoryFailureCode.CURSOR_FILTER_MISMATCH
    with pytest.raises(HistoryError) as oversized:
        service.list_jobs(JobHistoryFilter(), HistoryPageRequest(3))
    assert oversized.value.code is HistoryFailureCode.INVALID_PAGE_SIZE


def test_cursor_is_deterministic_versioned_and_has_stable_empty_boundary(
    history_runtime: tuple[PersistenceRuntime, HistoryService],
) -> None:
    runtime, service = history_runtime
    _seed(runtime, 2)
    first = service.list_jobs(JobHistoryFilter(), HistoryPageRequest(1))
    restarted = HistoryService(service.configuration, SQLAlchemyHistoryRepository(runtime))
    repeated = restarted.list_jobs(JobHistoryFilter(), HistoryPageRequest(1))
    assert repeated.next_cursor == first.next_cursor
    second = service.list_jobs(JobHistoryFilter(), HistoryPageRequest(1, first.next_cursor))
    assert second.returned_count == 1 and not second.has_more
    assert second.next_cursor is None
    assert service.list_jobs(JobHistoryFilter(job_id="missing"), HistoryPageRequest(2)).items == ()
    assert first.next_cursor is not None
    padded = first.next_cursor + "=" * (-len(first.next_cursor) % 4)
    value = json.loads(base64.urlsafe_b64decode(padded))
    value["version"] = "unsupported"
    altered = (
        base64.urlsafe_b64encode(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    with pytest.raises(HistoryError) as unsupported:
        service.list_jobs(JobHistoryFilter(), HistoryPageRequest(1, altered))
    assert unsupported.value.code is HistoryFailureCode.CURSOR_VERSION_UNSUPPORTED


def test_terminal_metadata_stage_and_artifact_projections_are_safe_and_bounded(
    history_runtime: tuple[PersistenceRuntime, HistoryService],
) -> None:
    runtime, service = history_runtime
    request = sample_request("/complete")
    accepted = sample_snapshot(request)
    repository = SQLAlchemyPersistenceRepository(runtime)
    assert repository.record_submission(accepted, request).succeeded
    terminal = sample_snapshot(request, state=JobState.COMPLETED)
    assert repository.record_terminal(terminal, sample_result(request), (), None).succeeded
    now = datetime(2030, 1, 1, tzinfo=UTC)
    with runtime.transaction() as session:
        session.add(
            ArtifactStorageRootModel(
                root_id="history-root",
                enabled=True,
                readiness_state="ready",
                readable=True,
                writable=True,
                last_checked_at=now,
                reason_code=None,
                storage_version="seo-toolkit-artifact-storage-v1",
            )
        )
    with runtime.transaction() as session:
        session.add(
            ArtifactRecordModel(
                artifact_id="artifact-history-safe",
                job_id=terminal.job_id,
                run_id=terminal.run_id,
                artifact_type="run_summary_json",
                root_id="history-root",
                relative_path="private/never-exposed.json",
                safe_filename="summary.json",
                content_type="application/json",
                lifecycle_state="available",
                integrity_state="verified",
                expected_byte_count=42,
                observed_byte_count=42,
                expected_sha256="a" * 64,
                observed_sha256="a" * 64,
                created_at=now,
                available_at=now,
                last_verified_at=now,
                expires_at=None,
                deleted_at=None,
                retention_state="normal",
                reason_code=None,
                storage_version="seo-toolkit-artifact-storage-v1",
                retrieval_version="seo-toolkit-artifact-retrieval-v1",
                reconciliation_version="seo-toolkit-artifact-reconciliation-v1",
            )
        )
    job = service.get_job(terminal.job_id)
    run = service.get_run(terminal.run_id)
    assert job.submitted_at is not None and job.terminal_at is not None
    assert run.terminal_at is not None
    assert service.stages(run.run_id).items[0].stage == "crawl"
    artifact = service.artifacts(run.run_id).items[0]
    assert artifact.filename == "summary.json"
    assert artifact.download_available
    assert not hasattr(artifact, "relative_path")
    assert not hasattr(artifact, "root_id")
    assert not hasattr(artifact, "expected_sha256")


def test_not_found_is_distinct_from_metadata_only(
    history_runtime: tuple[PersistenceRuntime, HistoryService],
) -> None:
    runtime, service = history_runtime
    identifier = _seed(runtime, 1)[0]
    assert service.get_job(identifier).availability.value == "result_unavailable"
    with pytest.raises(HistoryError) as missing:
        service.get_job("job-000000000000-9999")
    assert missing.value.code is HistoryFailureCode.JOB_NOT_FOUND


def test_history_routes_are_private_and_mount_only_when_explicitly_enabled(
    history_runtime: tuple[PersistenceRuntime, HistoryService],
) -> None:
    runtime, history = history_runtime
    identifier = _seed(runtime, 1)[0]
    settings = ProductionSettings.model_validate(
        {"enabled": True, "bearer_token": _TOKEN, "include_openapi": True}
    )
    application = create_production_app(
        _SecurityTestService(), settings, Settings(), history=history
    )
    paths = sorted(application.openapi()["paths"])
    assert len(paths) == 21
    assert len([path for path in paths if path.startswith("/api/internal/v1/history")]) == 10
    client = TestClient(application, client=("203.0.113.10", 50_000), raise_server_exceptions=False)
    assert client.get("/api/internal/v1/history/jobs").status_code == 401
    response = client.get(
        f"/api/internal/v1/history/jobs/{identifier}",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["job_id"] == identifier
    assert "lease_token" not in response.text
    assert "relative_path" not in response.text
    assert response.headers["x-content-type-options"] == "nosniff"


def test_diagnostics_are_bounded_versioned_and_migration_ready(
    history_runtime: tuple[PersistenceRuntime, HistoryService],
) -> None:
    runtime, service = history_runtime
    _seed(runtime, 2)
    service.list_jobs(JobHistoryFilter(), HistoryPageRequest(1))
    diagnostics = service.diagnostics()
    assert diagnostics.historical_job_count == 2
    assert diagnostics.historical_run_count == 2
    assert diagnostics.migration_ready and diagnostics.database_ready
    assert diagnostics.last_successful_query_at is not None


def test_exact_route_matrix_for_default_and_optional_private_features(
    history_runtime: tuple[PersistenceRuntime, HistoryService], tmp_path: Path
) -> None:
    runtime, history = history_runtime
    root = tmp_path / "artifact-root"
    root.mkdir()
    artifacts = ArtifactService(
        ArtifactStorageConfiguration(
            enabled=True,
            roots=(ArtifactStorageRootConfiguration("matrix-root", root),),
            default_root_id="matrix-root",
        ),
        SQLAlchemyArtifactRepository(runtime),
    )
    settings = ProductionSettings.model_validate(
        {"enabled": True, "bearer_token": _TOKEN, "include_openapi": True}
    )
    service = _SecurityTestService()
    applications = {
        "default": create_app(Settings()),
        "production": create_production_app(service, settings, Settings()),
        "artifacts": create_production_app(service, settings, Settings(), artifacts=artifacts),
        "history": create_production_app(service, settings, Settings(), history=history),
        "both": create_production_app(
            service,
            settings,
            Settings(),
            artifacts=artifacts,
            history=history,
        ),
    }
    assert {
        name: len(application.openapi()["paths"]) for name, application in applications.items()
    } == {"default": 1, "production": 11, "artifacts": 14, "history": 21, "both": 24}
