"""Deployment preflight, backup, restore, and runtime composition behavior."""

from __future__ import annotations

import asyncio
import json
import socket
import sqlite3
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import URL

import musimack_tools.operations.runtime as runtime_module
from musimack_tools.core.config import Environment, Settings
from musimack_tools.deployment.artifacts import ArtifactStorageSettings
from musimack_tools.deployment.durable import DurableExecutionSettings
from musimack_tools.deployment.history import HistorySettings
from musimack_tools.deployment.persistence import PersistenceSettings
from musimack_tools.deployment.settings import ProductionSettings
from musimack_tools.domain.artifacts import ArtifactStorageRootConfiguration
from musimack_tools.domain.authentication import AuthenticationMode
from musimack_tools.domain.durable_execution import WorkerIdentity, WorkerState
from musimack_tools.main import create_app
from musimack_tools.operations.backup import (
    BACKUP_FORMAT_VERSION,
    MANIFEST_NAME,
    BackupError,
    create_backup,
    read_manifest,
    restore_backup,
)
from musimack_tools.operations.configuration import ApplicationRole, OperationsSettings
from musimack_tools.operations.preflight import (
    PreflightCode,
    PreflightReport,
    PreflightStatus,
    run_preflight,
)
from musimack_tools.operations.runtime import RuntimeSettings, compose_web_runtime, run_worker
from musimack_tools.persistence.durable_repository import SQLAlchemyDurableExecutionRepository
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.migrations import PERSISTENCE_HEAD_REVISION, upgrade_to_head

if TYPE_CHECKING:
    from collections.abc import Iterator

_TOKEN = "operations-integration-token"  # noqa: S105 - inert test credential.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REPOSITORY_ROOT = _BACKEND_ROOT.parent


@pytest.fixture
def operations_environment(tmp_path: Path) -> Iterator[RuntimeSettings]:
    database_parent = tmp_path / "state"
    database_parent.mkdir()
    database = database_parent / "musimack.db"
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    frontend = tmp_path / "frontend-dist"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html><div id='root'></div>", encoding="utf-8")
    persistence = PersistenceSettings.model_validate(
        {
            "enabled": True,
            "database_path": database,
            "auto_migrate": False,
            "page_evidence_enabled": True,
        }
    )
    upgrade_to_head(
        str(URL.create("sqlite+pysqlite", database=str(database))),
        backend_root=_BACKEND_ROOT,
    )
    durable = DurableExecutionSettings.model_validate(
        {
            "durable_execution_enabled": True,
            "worker_enabled": True,
            "worker_id": "worker-integration",
        }
    )
    runtime = create_persistence_runtime(persistence.to_configuration())
    try:
        durable_repository = SQLAlchemyDurableExecutionRepository(
            runtime, durable.to_configuration()
        )
        durable_repository.register_worker(WorkerIdentity("worker-integration"), 1)
        durable_repository.set_worker_state("worker-integration", WorkerState.READY)
    finally:
        runtime.dispose()
    yield RuntimeSettings(
        Settings(environment=Environment.PRODUCTION),
        ProductionSettings.model_validate(
            {
                "enabled": True,
                "bearer_token": _TOKEN,
                "authentication_enabled": True,
                "authentication_mode": AuthenticationMode.HYBRID,
                "trusted_networks": ("127.0.0.1/32",),
                "trusted_proxies": ("127.0.0.1/32",),
            }
        ),
        persistence,
        durable,
        ArtifactStorageSettings.model_validate(
            {
                "enabled": True,
                "default_root_id": "primary",
                "storage_roots": (f"primary={artifact_root}",),
            }
        ),
        HistorySettings.model_validate({"enabled": True}),
        OperationsSettings.model_validate(
            {
                "public_origin": "https://seo.internal.test",
                "trusted_hosts": ("testserver", "seo.internal.test"),
                "frontend_build_path": frontend,
            }
        ),
    )


def _preflight(
    settings: RuntimeSettings, *, allow_pending_migrations: bool = False
) -> PreflightReport:
    return run_preflight(
        settings.application,
        settings.production,
        settings.persistence,
        settings.durable,
        settings.artifacts,
        settings.operations,
        repository_root=_REPOSITORY_ROOT,
        backend_root=_BACKEND_ROOT,
        role=ApplicationRole.WEB,
        allow_pending_migrations=allow_pending_migrations,
    )


def test_fully_ready_preflight_is_structured_and_network_free(
    operations_environment: RuntimeSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("DNS called")),
    )
    report = _preflight(operations_environment)
    assert report.ready
    assert report.to_dict()["ready"] is True
    assert all(check.code and check.description for check in report.checks)
    assert not any(check.status is PreflightStatus.FAIL for check in report.checks)


def test_preflight_reports_missing_parent_and_pending_database(
    operations_environment: RuntimeSettings,
) -> None:
    database = operations_environment.persistence.database_path
    assert database is not None
    missing = operations_environment.persistence.model_copy(
        update={"database_path": database.parent / "missing" / "db.sqlite"}
    )
    settings = RuntimeSettings(
        operations_environment.application,
        operations_environment.production,
        missing,
        operations_environment.durable,
        operations_environment.artifacts,
        operations_environment.history,
        operations_environment.operations,
    )
    report = _preflight(settings, allow_pending_migrations=True)
    by_code = {check.code: check for check in report.checks}
    assert by_code[PreflightCode.DATABASE_PARENT].status is PreflightStatus.FAIL
    assert by_code[PreflightCode.MIGRATION_CURRENT].status is PreflightStatus.WARNING
    assert not report.ready


def test_preflight_rejects_ahead_or_incompatible_revision(
    operations_environment: RuntimeSettings,
) -> None:
    database = operations_environment.persistence.database_path
    assert database is not None
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE alembic_version SET version_num='9999_future'")
    report = _preflight(operations_environment, allow_pending_migrations=True)
    current = next(
        check for check in report.checks if check.code == PreflightCode.MIGRATION_CURRENT
    )
    assert current.status is PreflightStatus.FAIL
    assert "incompatible" in current.description


def test_preflight_reports_unwritable_probe(
    operations_environment: RuntimeSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tempfile,
        "mkstemp",
        lambda **_kwargs: (_ for _ in ()).throw(PermissionError()),
    )
    report = _preflight(operations_environment)
    statuses = {
        check.code: check.status
        for check in report.checks
        if check.code in {PreflightCode.DATABASE_WRITABLE, PreflightCode.ARTIFACT_WRITABLE}
    }
    assert statuses == {
        PreflightCode.DATABASE_WRITABLE: PreflightStatus.FAIL,
        PreflightCode.ARTIFACT_WRITABLE: PreflightStatus.FAIL,
    }


def test_preflight_rejects_divergent_heads_and_missing_frontend(
    operations_environment: RuntimeSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DivergentScript:
        @staticmethod
        def get_heads() -> tuple[str, ...]:
            return (PERSISTENCE_HEAD_REVISION, "9999_divergent")

    monkeypatch.setattr(
        ScriptDirectory,
        "from_config",
        lambda *_args, **_kwargs: DivergentScript(),
    )
    frontend = operations_environment.operations.frontend_build_path
    assert frontend is not None
    missing_frontend = operations_environment.operations.model_copy(
        update={"frontend_build_path": frontend / "missing"}
    )
    settings = RuntimeSettings(
        operations_environment.application,
        operations_environment.production,
        operations_environment.persistence,
        operations_environment.durable,
        operations_environment.artifacts,
        operations_environment.history,
        missing_frontend,
    )
    report = _preflight(settings)
    by_code = {check.code: check for check in report.checks}
    assert by_code[PreflightCode.MIGRATION_HEAD].status is PreflightStatus.FAIL
    assert dict(by_code[PreflightCode.MIGRATION_HEAD].context)["head_count"] == 2
    assert by_code[PreflightCode.FRONTEND_BUILD].status is PreflightStatus.FAIL
    assert not report.ready


def test_default_health_app_remains_minimal(operations_environment: RuntimeSettings) -> None:
    app = create_app(operations_environment.application)
    assert list(app.openapi()["paths"]) == ["/api/health"]
    response = TestClient(app).get("/api/health")
    assert response.json() == {
        "application": "Musimack SEO Toolkit",
        "status": "healthy",
    }
    assert _TOKEN not in response.text
    assert "database" not in response.text.casefold()


def test_web_runtime_has_authenticated_private_readiness_and_no_hidden_worker(
    operations_environment: RuntimeSettings,
) -> None:
    runtime = compose_web_runtime(operations_environment)
    try:
        assert runtime.app.state.application_role == "web"
        assert not runtime.app.router.on_startup
        client = TestClient(runtime.app, client=("127.0.0.1", 50000))
        health = client.get("/api/health")
        denied = client.get("/api/internal/v1/readiness")
        ready = client.get(
            "/api/internal/v1/readiness",
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
        assert health.status_code == 200
        assert denied.status_code == 401
        assert ready.status_code == 200
        assert ready.json()["data"]["state"] == "ready"
        assert _TOKEN not in ready.text
        assert str(operations_environment.persistence.database_path) not in ready.text
        durable_repository = SQLAlchemyDurableExecutionRepository(
            runtime.persistence, operations_environment.durable.to_configuration()
        )
        durable_repository.set_worker_state("worker-integration", WorkerState.STOPPED)
        unavailable = client.get(
            "/api/internal/v1/readiness",
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
        assert unavailable.status_code == 503
        assert unavailable.json()["data"]["state"] == "not_ready"
        assert _TOKEN not in unavailable.text
    finally:
        runtime.persistence.dispose()


def test_production_worker_registers_and_stops_gracefully(
    operations_environment: RuntimeSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    durable = operations_environment.durable.model_copy(update={"worker_id": "worker-lifecycle"})
    settings = RuntimeSettings(
        operations_environment.application,
        operations_environment.production,
        operations_environment.persistence,
        durable,
        operations_environment.artifacts,
        operations_environment.history,
        operations_environment.operations,
    )
    monkeypatch.setattr(
        runtime_module,
        "_install_stop_signals",
        lambda stop: stop.set(),
    )
    asyncio.run(run_worker(settings))
    persistence = create_persistence_runtime(settings.persistence.to_configuration())
    try:
        repository = SQLAlchemyDurableExecutionRepository(persistence, durable.to_configuration())
        diagnostics = repository.diagnostics("worker-lifecycle", recovery_complete=True)
        assert diagnostics.worker_registered
        assert diagnostics.worker_state is WorkerState.STOPPED
    finally:
        persistence.dispose()


def test_backup_restore_round_trip_includes_database_and_artifacts(
    operations_environment: RuntimeSettings,
    tmp_path: Path,
) -> None:
    database = operations_environment.persistence.database_path
    assert database is not None
    root = operations_environment.artifacts.to_configuration().roots[0]
    first = root.path / "jobs" / "job-one" / "runs" / "run-one" / "artifacts" / "one.json"
    second = root.path / "jobs" / "job-two" / "runs" / "run-two" / "artifacts" / "two.csv"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b'{"safe":true}')
    second.write_bytes(b"a,b\n1,2\n")
    backup = tmp_path / "backup"
    result = create_backup(
        database,
        (root,),
        backup,
        repository_root=_REPOSITORY_ROOT,
        services_stopped=True,
        application_revision="a" * 40,
    )
    assert result.artifact_files == 2
    manifest = read_manifest(backup)
    assert manifest.format_version == BACKUP_FORMAT_VERSION
    assert manifest.migration_revision == PERSISTENCE_HEAD_REVISION
    assert len(manifest.files) == 3
    restored = restore_backup(
        backup,
        tmp_path / "restored",
        repository_root=_REPOSITORY_ROOT,
    )
    assert restored.database_path.is_file()
    restored_root = dict(restored.artifact_roots)["primary"]
    assert (restored_root / first.relative_to(root.path)).read_bytes() == first.read_bytes()
    assert (restored_root / second.relative_to(root.path)).read_bytes() == second.read_bytes()
    assert (backup / MANIFEST_NAME).is_file()


def test_backup_supports_empty_artifact_root(
    operations_environment: RuntimeSettings,
    tmp_path: Path,
) -> None:
    database = operations_environment.persistence.database_path
    assert database is not None
    root = operations_environment.artifacts.to_configuration().roots[0]
    result = create_backup(
        database,
        (root,),
        tmp_path / "empty-backup",
        repository_root=_REPOSITORY_ROOT,
        services_stopped=True,
    )
    assert result.artifact_files == 0
    assert result.total_files == 1
    restored = restore_backup(
        tmp_path / "empty-backup",
        tmp_path / "empty-restored",
        repository_root=_REPOSITORY_ROOT,
    )
    assert dict(restored.artifact_roots)["primary"].is_dir()


def test_backup_requires_stopped_services_and_new_safe_destination(
    operations_environment: RuntimeSettings,
    tmp_path: Path,
) -> None:
    database = operations_environment.persistence.database_path
    assert database is not None
    root = operations_environment.artifacts.to_configuration().roots[0]
    with pytest.raises(BackupError, match="confirmation"):
        create_backup(
            database,
            (root,),
            tmp_path / "backup",
            repository_root=_REPOSITORY_ROOT,
            services_stopped=False,
        )
    destination = tmp_path / "existing"
    destination.mkdir()
    with pytest.raises(BackupError, match="already exists"):
        create_backup(
            database,
            (root,),
            destination,
            repository_root=_REPOSITORY_ROOT,
            services_stopped=True,
        )


def test_restore_rejects_manifest_and_file_tampering(
    operations_environment: RuntimeSettings,
    tmp_path: Path,
) -> None:
    database = operations_environment.persistence.database_path
    assert database is not None
    root = operations_environment.artifacts.to_configuration().roots[0]
    backup = tmp_path / "backup"
    create_backup(
        database,
        (root,),
        backup,
        repository_root=_REPOSITORY_ROOT,
        services_stopped=True,
    )
    database_backup = backup / "database.sqlite3"
    database_backup.write_bytes(database_backup.read_bytes() + b"tampered")
    with pytest.raises(BackupError, match="integrity"):
        restore_backup(backup, tmp_path / "restore-one", repository_root=_REPOSITORY_ROOT)
    assert not (tmp_path / "restore-one").exists()

    database_backup.write_bytes(database.read_bytes())
    manifest_path = backup / MANIFEST_NAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["format_version"] = "future-backup-v9"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BackupError, match="version"):
        restore_backup(backup, tmp_path / "restore-two", repository_root=_REPOSITORY_ROOT)


def test_restore_rejects_unsafe_root_ids_and_artifact_locations(
    operations_environment: RuntimeSettings,
    tmp_path: Path,
) -> None:
    database = operations_environment.persistence.database_path
    assert database is not None
    root = operations_environment.artifacts.to_configuration().roots[0]
    backup = tmp_path / "backup"
    create_backup(
        database,
        (root,),
        backup,
        repository_root=_REPOSITORY_ROOT,
        services_stopped=True,
    )
    manifest_path = backup / MANIFEST_NAME
    original = json.loads(manifest_path.read_text(encoding="utf-8"))
    original["artifact_root_ids"] = ["../unsafe"]
    manifest_path.write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(BackupError, match="root list"):
        read_manifest(backup)

    artifact = root.path / "artifact.json"
    artifact.write_text("{}", encoding="utf-8")
    located_backup = tmp_path / "located-backup"
    create_backup(
        database,
        (root,),
        located_backup,
        repository_root=_REPOSITORY_ROOT,
        services_stopped=True,
    )
    located_manifest = located_backup / MANIFEST_NAME
    payload = json.loads(located_manifest.read_text(encoding="utf-8"))
    entry = next(item for item in payload["files"] if item["kind"] == "artifact")
    entry["path"] = "misplaced/artifact.json"
    located_manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BackupError, match="artifact location"):
        read_manifest(located_backup)


def test_backup_rejects_unsafe_artifact_symlink_when_supported(
    operations_environment: RuntimeSettings,
    tmp_path: Path,
) -> None:
    database = operations_environment.persistence.database_path
    assert database is not None
    root = operations_environment.artifacts.to_configuration().roots[0]
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = root.path / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError as error:
        assert getattr(error, "winerror", None) == 1314
        return
    with pytest.raises(BackupError, match="symlink"):
        create_backup(
            database,
            (root,),
            tmp_path / "unsafe-backup",
            repository_root=_REPOSITORY_ROOT,
            services_stopped=True,
        )


def test_backup_rejects_source_database_outside_expected_revision(
    tmp_path: Path,
) -> None:
    database = tmp_path / "unmigrated.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE example (id INTEGER PRIMARY KEY)")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    with pytest.raises(BackupError, match="migration head"):
        create_backup(
            database,
            (ArtifactStorageRootConfiguration("primary", artifacts),),
            tmp_path / "backup",
            repository_root=_REPOSITORY_ROOT,
            services_stopped=True,
        )
