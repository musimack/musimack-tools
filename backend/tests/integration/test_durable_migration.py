"""Focused migration 0002 schema, downgrade, and offline-SQL validation."""

from __future__ import annotations

from io import StringIO
from typing import TYPE_CHECKING

from alembic import command
from sqlalchemy import create_engine, inspect

from musimack_tools.persistence.migrations import (
    DURABLE_EXECUTION_REVISION,
    INITIAL_PERSISTENCE_REVISION,
    alembic_configuration,
    current_revision,
)
from persistence_helpers import BACKEND_ROOT, cleanup_persistence_test_artifacts  # noqa: F401

if TYPE_CHECKING:
    from pathlib import Path


def _url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path.as_posix()}"


def test_upgrade_0001_to_0002_downgrade_and_reupgrade(tmp_path: Path) -> None:
    url = _url(tmp_path / "durable-migration.db")
    configuration = alembic_configuration(url, backend_root=BACKEND_ROOT)
    command.upgrade(configuration, INITIAL_PERSISTENCE_REVISION)
    engine = create_engine(url)
    try:
        assert current_revision(engine) == INITIAL_PERSISTENCE_REVISION
        assert "durable_jobs" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
    command.upgrade(configuration, DURABLE_EXECUTION_REVISION)
    engine = create_engine(url)
    try:
        assert current_revision(engine) == DURABLE_EXECUTION_REVISION
        assert "durable_jobs" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
    command.downgrade(configuration, INITIAL_PERSISTENCE_REVISION)
    engine = create_engine(url)
    try:
        assert current_revision(engine) == INITIAL_PERSISTENCE_REVISION
        assert "durable_jobs" not in inspect(engine).get_table_names()
        assert "jobs" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
    command.upgrade(configuration, DURABLE_EXECUTION_REVISION)
    engine = create_engine(url)
    try:
        assert current_revision(engine) == DURABLE_EXECUTION_REVISION
    finally:
        engine.dispose()


def test_durable_migration_offline_sql_has_tables_constraints_and_indexes(
    tmp_path: Path,
) -> None:
    output = StringIO()
    configuration = alembic_configuration(
        _url(tmp_path / "offline-durable.db"), backend_root=BACKEND_ROOT
    )
    configuration.attributes["output_buffer"] = output
    command.upgrade(configuration, "head", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE workers" in sql
    assert "CREATE TABLE durable_jobs" in sql
    assert "CREATE TABLE job_leases" in sql
    assert "CREATE TABLE job_execution_attempts" in sql
    assert "CREATE UNIQUE INDEX uq_job_leases_one_active" in sql
    assert "CREATE INDEX ix_durable_jobs_claim" in sql
    assert not (tmp_path / "offline-durable.db").exists()
