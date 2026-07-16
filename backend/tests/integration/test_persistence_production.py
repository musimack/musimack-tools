"""Optional startup composition and health-only isolation tests."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from musimack_tools.core.config import Settings
from musimack_tools.deployment.application import create_production_app
from musimack_tools.deployment.persistence import PersistenceSettings
from musimack_tools.deployment.persistence_runtime import (
    PersistenceStartupError,
    PreparedPersistence,
    prepare_persistence,
)
from musimack_tools.deployment.settings import ProductionSettings
from musimack_tools.domain.persistence import PersistenceReadinessState
from musimack_tools.domain.storage import NullPersistenceRepository
from musimack_tools.main import create_app
from persistence_helpers import cleanup_persistence_test_artifacts  # noqa: F401

if TYPE_CHECKING:
    from musimack_tools.api.dependencies import InternalApiApplication

_TOKEN = "persistence-production-test-token"  # noqa: S105 - inert test value.


def test_health_only_app_creates_no_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(Settings())
    assert list(app.openapi()["paths"]) == ["/api/health"]
    assert not tuple(tmp_path.glob("*.db"))


def test_disabled_persistence_requires_no_path(tmp_path: Path) -> None:
    prepared = prepare_persistence(
        PersistenceSettings.model_validate({}),
        backend_root=Path(__file__).parents[2],
        repository_root=tmp_path,
    )
    assert prepared.diagnostics.state is PersistenceReadinessState.DISABLED
    assert prepared.bootstrap is None


def test_enabled_persistence_with_pending_migration_fails(tmp_path: Path) -> None:
    with pytest.raises(PersistenceStartupError, match="migration"):
        prepare_persistence(
            PersistenceSettings.model_validate(
                {"enabled": True, "database_path": tmp_path / "pending.db"}
            ),
            backend_root=Path(__file__).parents[2],
            repository_root=tmp_path,
        )


def test_auto_migrated_persistence_is_ready(tmp_path: Path) -> None:
    prepared = prepare_persistence(
        PersistenceSettings.model_validate(
            {
                "enabled": True,
                "database_path": tmp_path / "ready.db",
                "auto_migrate": True,
            }
        ),
        backend_root=Path(__file__).parents[2],
        repository_root=tmp_path,
    )
    try:
        assert prepared.diagnostics.state is PersistenceReadinessState.READY
        assert prepared.bootstrap is not None
        assert prepared.bootstrap.recovered_attempts == ()
    finally:
        prepared.repository.dispose()


def test_production_app_accepts_explicit_disabled_persistence_without_new_routes() -> None:
    repository = NullPersistenceRepository()
    prepared = PreparedPersistence(repository, repository.diagnostics(), None)
    service = cast("InternalApiApplication", object())
    settings = ProductionSettings.model_validate(
        {"enabled": True, "bearer_token": _TOKEN, "include_openapi": True}
    )
    app = create_production_app(service, settings, Settings(), persistence=prepared)
    internal = [path for path in app.openapi()["paths"] if path.startswith("/api/internal/")]
    assert len(internal) == 11
    assert app.state.persistence_readiness.state is PersistenceReadinessState.DISABLED
