"""File-backed Alembic upgrade, downgrade, revision, and offline-SQL tests."""

from __future__ import annotations

import logging
from io import StringIO
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from musimack_tools.persistence.migrations import (
    INITIAL_PERSISTENCE_REVISION,
    alembic_configuration,
    current_revision,
    downgrade_to_base,
    schema_is_current,
    upgrade_to_head,
)
from persistence_helpers import BACKEND_ROOT, cleanup_persistence_test_artifacts  # noqa: F401

if TYPE_CHECKING:
    from pathlib import Path


def _url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path.as_posix()}"


def test_upgrade_current_downgrade_and_reupgrade(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    url = _url(database)
    upgrade_to_head(url, backend_root=BACKEND_ROOT)
    engine = create_engine(url)
    try:
        assert current_revision(engine) == INITIAL_PERSISTENCE_REVISION
        assert schema_is_current(engine)
        assert "jobs" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            metadata = connection.execute(
                text("select schema_version, persistence_version from persistence_metadata")
            ).one()
        assert tuple(metadata) == (
            "seo-toolkit-database-schema-v1",
            "seo-toolkit-persistence-v1",
        )
    finally:
        engine.dispose()
    downgrade_to_base(url, backend_root=BACKEND_ROOT)
    engine = create_engine(url)
    try:
        assert inspect(engine).get_table_names() == ["alembic_version"]
        assert current_revision(engine) is None
    finally:
        engine.dispose()
    upgrade_to_head(url, backend_root=BACKEND_ROOT)
    engine = create_engine(url)
    try:
        assert schema_is_current(engine)
    finally:
        engine.dispose()


def test_empty_database_reports_pending_migration(tmp_path: Path) -> None:
    engine = create_engine(_url(tmp_path / "empty.db"))
    try:
        assert current_revision(engine) is None
        assert not schema_is_current(engine)
    finally:
        engine.dispose()


def test_migrated_schema_has_expected_tables_constraints_indexes_and_revision(
    tmp_path: Path,
) -> None:
    url = _url(tmp_path / "audit.db")
    config = alembic_configuration(url, backend_root=BACKEND_ROOT)
    upgrade_to_head(url, backend_root=BACKEND_ROOT)
    engine = create_engine(url)
    try:
        database = inspect(engine)
        assert set(database.get_table_names()) == {
            "alembic_version",
            "artifact_metadata",
            "configuration_snapshots",
            "failures",
            "jobs",
            "persistence_metadata",
            "progress_snapshots",
            "runs",
            "run_stages",
            "summary_metadata",
            "warnings",
        }
        foreign_keys = {
            (table, constraint["referred_table"])
            for table in database.get_table_names()
            for constraint in database.get_foreign_keys(table)
        }
        assert foreign_keys == {
            ("artifact_metadata", "jobs"),
            ("artifact_metadata", "runs"),
            ("jobs", "configuration_snapshots"),
            ("jobs", "runs"),
            ("progress_snapshots", "jobs"),
            ("progress_snapshots", "runs"),
            ("runs", "configuration_snapshots"),
            ("run_stages", "runs"),
            ("summary_metadata", "runs"),
        }
        unique_names = {
            constraint["name"]
            for table in database.get_table_names()
            for constraint in database.get_unique_constraints(table)
        }
        assert {
            "uq_artifact_run",
            "uq_jobs_run_attempt",
            "uq_progress_job_sequence",
            "uq_run_stages_run_stage",
            "uq_summary_run_filename",
            "uq_warning_exact",
        } <= unique_names
        index_names = {
            index["name"]
            for table in database.get_table_names()
            for index in database.get_indexes(table)
        }
        assert {
            "ix_artifacts_run_sequence",
            "ix_failures_parent_sequence",
            "ix_jobs_state_sequence",
            "ix_progress_job_sequence",
            "ix_runs_lifecycle",
            "ix_run_stages_run_order",
            "ix_warnings_parent_sequence",
        } <= index_names
    finally:
        engine.dispose()
    script = ScriptDirectory.from_config(config).get_revision(INITIAL_PERSISTENCE_REVISION)
    assert script is not None
    assert script.revision == "0001_persistence"
    assert script.doc == "create persistence foundation"


def test_offline_sql_contains_authorized_schema(tmp_path: Path) -> None:
    output = StringIO()
    config = alembic_configuration(_url(tmp_path / "offline.db"), backend_root=BACKEND_ROOT)
    config.attributes["output_buffer"] = output
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE jobs" in sql
    assert "CREATE TABLE artifact_metadata" in sql
    assert "INSERT INTO persistence_metadata" in sql
    assert not (tmp_path / "offline.db").exists()


def test_alembic_configuration_has_no_repository_relative_fallback() -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    assert config.get_main_option("sqlalchemy.url") == ""


def test_upgrade_is_idempotent_at_head(tmp_path: Path) -> None:
    database = tmp_path / "idempotent.db"
    url = _url(database)
    upgrade_to_head(url, backend_root=BACKEND_ROOT)
    upgrade_to_head(url, backend_root=BACKEND_ROOT)
    engine = create_engine(url)
    try:
        assert schema_is_current(engine)
    finally:
        engine.dispose()


def test_migration_does_not_disable_existing_application_loggers(tmp_path: Path) -> None:
    logger = logging.getLogger("musimack_tools.persistence.migration-test")
    logger.disabled = False
    upgrade_to_head(_url(tmp_path / "logger.db"), backend_root=BACKEND_ROOT)
    assert not logger.disabled
