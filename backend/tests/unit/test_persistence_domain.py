"""Persistence versions, configuration, path safety, and null behavior."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from musimack_tools.deployment.persistence import PersistenceSettings
from musimack_tools.domain.persistence import (
    DATABASE_SCHEMA_VERSION,
    PERSISTENCE_VERSION,
    ArtifactType,
    PersistenceConfiguration,
    PersistenceFailureCode,
    PersistenceReadinessState,
    PersistenceRetentionPolicy,
    ReconciliationState,
    RetentionState,
    SQLiteJournalMode,
    SQLiteSynchronousMode,
)
from musimack_tools.domain.storage import NullPersistenceRepository
from musimack_tools.persistence.path_safety import (
    prepare_database_parent,
    validate_database_path,
)
from musimack_tools.persistence.retention import oldest_excess_sequences

if TYPE_CHECKING:
    from enum import StrEnum


def test_persistence_versions_are_exact() -> None:
    assert PERSISTENCE_VERSION == "seo-toolkit-persistence-v1"
    assert DATABASE_SCHEMA_VERSION == "seo-toolkit-database-schema-v1"


@pytest.mark.parametrize(
    "value",
    [
        *PersistenceFailureCode,
        *PersistenceReadinessState,
        *ReconciliationState,
        *RetentionState,
        *ArtifactType,
        *SQLiteJournalMode,
        *SQLiteSynchronousMode,
    ],
)
def test_persistence_enum_values_are_stable(value: StrEnum) -> None:
    assert value.value


def test_configuration_defaults_are_disabled_and_bounded() -> None:
    configuration = PersistenceConfiguration()
    assert not configuration.enabled
    assert configuration.database_path is None
    assert configuration.foreign_keys
    assert configuration.journal_mode is SQLiteJournalMode.WAL
    assert configuration.synchronous_mode is SQLiteSynchronousMode.NORMAL
    assert not configuration.auto_migrate
    assert configuration.reconcile_on_startup


def test_configuration_is_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        PersistenceConfiguration().enabled = True  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"enabled": True},
        {"database_path": Path("relative.db")},
        {"busy_timeout_milliseconds": 99},
        {"busy_timeout_milliseconds": 120_001},
        {"connection_timeout_seconds": 0.09},
        {"connection_timeout_seconds": 121.0},
        {"persistence_version": "other"},
        {"schema_version": "other"},
    ],
)
def test_invalid_configuration_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        PersistenceConfiguration(**overrides)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field",
    [
        "maximum_terminal_jobs",
        "maximum_progress_rows_per_job",
        "maximum_warning_rows_per_parent",
        "maximum_failure_rows_per_parent",
        "maximum_artifact_rows_per_run",
        "maximum_summary_rows_per_run",
    ],
)
def test_negative_retention_limits_are_rejected(field: str) -> None:
    with pytest.raises(ValueError):
        PersistenceRetentionPolicy(**{field: -1})  # type: ignore[arg-type]


def test_settings_disabled_without_path() -> None:
    settings = PersistenceSettings.model_validate({})
    assert not settings.enabled
    assert settings.database_path is None


def test_settings_enabled_requires_path() -> None:
    with pytest.raises(ValidationError):
        PersistenceSettings.model_validate({"enabled": True})


def test_settings_convert_without_secret_or_machine_fields(tmp_path: Path) -> None:
    settings = PersistenceSettings.model_validate(
        {"enabled": True, "database_path": tmp_path / "data.db"}
    )
    configuration = settings.to_configuration()
    assert configuration.enabled
    assert configuration.database_path == tmp_path / "data.db"
    assert "credential" not in repr(configuration).lower()


def test_path_validation_rejects_relative_path() -> None:
    with pytest.raises(ValueError, match="absolute"):
        validate_database_path(Path("data.db"))


def test_path_validation_rejects_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="directory"):
        validate_database_path(tmp_path)


def test_path_validation_rejects_linked_database_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "linked.db"
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == target or original(path))
    with pytest.raises(ValueError, match="symlink or junction"):
        validate_database_path(target)


def test_path_validation_rejects_git_directory(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    with pytest.raises(ValueError, match=r"\.git"):
        validate_database_path(git / "data.db", repository_root=tmp_path)


def test_path_validation_does_not_create_missing_parent(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "data.db"
    validate_database_path(target)
    assert not target.parent.exists()


def test_prepare_parent_requires_explicit_creation(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "data.db"
    with pytest.raises(ValueError, match="does not exist"):
        prepare_database_parent(target, create_parent=False)
    assert not target.parent.exists()


def test_prepare_parent_can_create_explicit_parent(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "data.db"
    prepare_database_parent(target, create_parent=True)
    assert target.parent.is_dir()
    assert not target.exists()


def test_null_repository_reports_disabled() -> None:
    repository = NullPersistenceRepository()
    diagnostics = repository.diagnostics()
    assert diagnostics.state is PersistenceReadinessState.DISABLED
    assert not diagnostics.enabled
    assert repository.highest_attempts() == ()
    assert repository.retained_terminal_jobs() == ()


@pytest.mark.parametrize(
    ("sequences", "maximum", "expected"),
    [
        ((), 3, ()),
        ((3, 1, 2), 3, ()),
        ((3, 1, 2), 2, (1,)),
        ((3, 1, 2), 0, (1, 2, 3)),
    ],
)
def test_oldest_excess_sequences(
    sequences: tuple[int, ...], maximum: int, expected: tuple[int, ...]
) -> None:
    assert oldest_excess_sequences(sequences, maximum) == expected
