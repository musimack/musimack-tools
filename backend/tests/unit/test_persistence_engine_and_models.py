"""Explicit engine lifecycle and normalized ORM schema tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from sqlalchemy import Table, inspect, text

from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.persistence.base import Base
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.models import (
    ArtifactMetadataModel,
    ConfigurationSnapshotModel,
    FailureModel,
    JobModel,
    PersistenceMetadataModel,
    ProgressSnapshotModel,
    RunModel,
    RunStageModel,
    SummaryMetadataModel,
    WarningModel,
)
from persistence_helpers import cleanup_persistence_test_artifacts  # noqa: F401

if TYPE_CHECKING:
    from pathlib import Path


def _configuration(tmp_path: Path) -> PersistenceConfiguration:
    return PersistenceConfiguration(enabled=True, database_path=tmp_path / "data.db")


def test_engine_is_created_only_by_explicit_factory(tmp_path: Path) -> None:
    target = tmp_path / "data.db"
    assert not target.exists()
    runtime = create_persistence_runtime(_configuration(tmp_path))
    assert not target.exists()
    runtime.dispose()


def test_file_engine_applies_sqlite_pragmas(tmp_path: Path) -> None:
    runtime = create_persistence_runtime(_configuration(tmp_path))
    try:
        with runtime.engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            assert connection.execute(text("PRAGMA busy_timeout")).scalar_one() == 5_000
            assert (
                str(connection.execute(text("PRAGMA journal_mode")).scalar_one()).upper() == "WAL"
            )
            assert connection.execute(text("PRAGMA synchronous")).scalar_one() == 1
    finally:
        runtime.dispose()


def test_in_memory_engine_uses_one_shared_database(tmp_path: Path) -> None:
    runtime = create_persistence_runtime(_configuration(tmp_path), in_memory=True)
    try:
        Base.metadata.create_all(runtime.engine)
        with runtime.transaction() as session:
            assert session.execute(text("select count(*) from jobs")).scalar_one() == 0
    finally:
        runtime.dispose()
    assert not (tmp_path / "data.db").exists()


def test_disabled_configuration_cannot_create_runtime() -> None:
    with pytest.raises(ValueError, match="disabled"):
        create_persistence_runtime(PersistenceConfiguration())


def test_transaction_rolls_back_on_failure(tmp_path: Path) -> None:
    runtime = create_persistence_runtime(_configuration(tmp_path), in_memory=True)
    Base.metadata.create_all(runtime.engine)
    try:
        with pytest.raises(RuntimeError, match="rollback"), runtime.transaction() as session:
            session.add(
                ConfigurationSnapshotModel(
                    snapshot_id="a" * 64,
                    snapshot_type="test",
                    schema_version="v1",
                    canonical_json="{}",
                    sha256="a" * 64,
                )
            )
            raise RuntimeError("rollback")
        with runtime.transaction() as session:
            assert session.get(ConfigurationSnapshotModel, "a" * 64) is None
    finally:
        runtime.dispose()


@pytest.mark.parametrize(
    ("model", "table_name"),
    [
        (PersistenceMetadataModel, "persistence_metadata"),
        (ConfigurationSnapshotModel, "configuration_snapshots"),
        (JobModel, "jobs"),
        (RunModel, "runs"),
        (RunStageModel, "run_stages"),
        (ProgressSnapshotModel, "progress_snapshots"),
        (WarningModel, "warnings"),
        (FailureModel, "failures"),
        (SummaryMetadataModel, "summary_metadata"),
        (ArtifactMetadataModel, "artifact_metadata"),
    ],
)
def test_model_table_names_are_stable(model: type[Base], table_name: str) -> None:
    assert model.__tablename__ == table_name


def test_schema_has_only_authorized_application_tables(tmp_path: Path) -> None:
    runtime = create_persistence_runtime(_configuration(tmp_path), in_memory=True)
    try:
        Base.metadata.create_all(runtime.engine)
        assert set(inspect(runtime.engine).get_table_names()) == {
            "persistence_metadata",
            "configuration_snapshots",
            "jobs",
            "runs",
            "run_stages",
            "progress_snapshots",
            "warnings",
            "failures",
            "summary_metadata",
            "artifact_metadata",
        }
    finally:
        runtime.dispose()


def test_models_exclude_secrets_and_prohibited_blobs() -> None:
    names = {column.name for table in Base.metadata.tables.values() for column in table.columns}
    prohibited = {
        "credential",
        "bearer_token",
        "authorization",
        "raw_html",
        "response_body",
        "xml_bytes",
        "manifest_bytes",
        "summary_bytes",
    }
    assert names.isdisjoint(prohibited)


def test_foreign_keys_and_unique_constraints_are_declared() -> None:
    assert JobModel.__table__.foreign_keys
    assert RunStageModel.__table__.foreign_keys
    stage_table = cast("Table", RunStageModel.__table__)
    job_table = cast("Table", JobModel.__table__)
    constraint_names = {item.name for item in stage_table.constraints}
    assert "uq_run_stages_run_stage" in constraint_names
    assert "uq_jobs_run_attempt" in {item.name for item in job_table.constraints}


def test_required_indexes_are_declared() -> None:
    index_names = {index.name for table in Base.metadata.tables.values() for index in table.indexes}
    assert {
        "ix_jobs_state_sequence",
        "ix_runs_lifecycle",
        "ix_run_stages_run_order",
        "ix_progress_job_sequence",
        "ix_warnings_parent_sequence",
        "ix_failures_parent_sequence",
        "ix_artifacts_run_sequence",
    } <= index_names
