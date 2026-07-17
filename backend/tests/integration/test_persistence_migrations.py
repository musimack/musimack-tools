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
    ARTIFACT_STORAGE_REVISION,
    AUTHENTICATION_AUTHORIZATION_REVISION,
    DURABLE_EXECUTION_REVISION,
    INITIAL_PERSISTENCE_REVISION,
    METADATA_AUDIT_REVISION,
    PAGE_CRAWL_EVIDENCE_REVISION,
    PERSISTENCE_HEAD_REVISION,
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
        assert current_revision(engine) == PERSISTENCE_HEAD_REVISION
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
            "artifact_storage_roots",
            "artifact_records",
            "artifact_integrity_checks",
            "artifact_lifecycle_events",
            "artifact_cleanup_events",
            "artifact_reconciliation_events",
            "configuration_snapshots",
            "durable_jobs",
            "durable_recovery_events",
            "durable_sequences",
            "failures",
            "job_execution_attempts",
            "job_leases",
            "jobs",
            "persistence_metadata",
            "progress_snapshots",
            "crawl_page_evidence",
            "crawl_page_redirect_hops",
            "crawl_page_parse_warnings",
            "crawl_page_evidence_summaries",
            "crawl_page_evidence_events",
            "metadata_audits",
            "metadata_audit_pages",
            "metadata_audit_issues",
            "metadata_duplicate_groups",
            "metadata_duplicate_group_members",
            "metadata_audit_summaries",
            "metadata_audit_exports",
            "metadata_audit_events",
            "runs",
            "run_stages",
            "summary_metadata",
            "warnings",
            "workers",
            "users",
            "user_credentials",
            "authentication_sessions",
            "authentication_audit_events",
            "login_attempts",
        }
        foreign_keys = {
            (table, constraint["referred_table"])
            for table in database.get_table_names()
            for constraint in database.get_foreign_keys(table)
        }
        assert foreign_keys == {
            ("artifact_metadata", "jobs"),
            ("artifact_metadata", "runs"),
            ("artifact_records", "jobs"),
            ("artifact_records", "runs"),
            ("artifact_records", "artifact_storage_roots"),
            ("artifact_integrity_checks", "artifact_records"),
            ("artifact_lifecycle_events", "artifact_records"),
            ("artifact_cleanup_events", "artifact_records"),
            ("artifact_reconciliation_events", "artifact_storage_roots"),
            ("artifact_reconciliation_events", "artifact_records"),
            ("jobs", "configuration_snapshots"),
            ("jobs", "runs"),
            ("durable_jobs", "jobs"),
            ("durable_jobs", "workers"),
            ("durable_recovery_events", "jobs"),
            ("durable_recovery_events", "workers"),
            ("job_execution_attempts", "jobs"),
            ("job_execution_attempts", "workers"),
            ("job_leases", "jobs"),
            ("job_leases", "workers"),
            ("progress_snapshots", "jobs"),
            ("progress_snapshots", "runs"),
            ("crawl_page_evidence", "jobs"),
            ("crawl_page_evidence", "runs"),
            ("crawl_page_redirect_hops", "crawl_page_evidence"),
            ("crawl_page_parse_warnings", "crawl_page_evidence"),
            ("crawl_page_evidence_summaries", "jobs"),
            ("crawl_page_evidence_summaries", "runs"),
            ("crawl_page_evidence_events", "jobs"),
            ("crawl_page_evidence_events", "runs"),
            ("metadata_audits", "jobs"),
            ("metadata_audits", "runs"),
            ("metadata_audit_pages", "metadata_audits"),
            ("metadata_audit_pages", "crawl_page_evidence"),
            ("metadata_audit_issues", "metadata_audits"),
            ("metadata_audit_issues", "metadata_audit_pages"),
            ("metadata_duplicate_groups", "metadata_audits"),
            ("metadata_duplicate_group_members", "metadata_duplicate_groups"),
            ("metadata_duplicate_group_members", "metadata_audit_pages"),
            ("metadata_audit_summaries", "metadata_audits"),
            ("metadata_audit_exports", "metadata_audits"),
            ("metadata_audit_exports", "artifact_records"),
            ("metadata_audit_events", "metadata_audits"),
            ("runs", "configuration_snapshots"),
            ("run_stages", "runs"),
            ("summary_metadata", "runs"),
            ("user_credentials", "users"),
            ("authentication_sessions", "users"),
        }
        unique_names = {
            constraint["name"]
            for table in database.get_table_names()
            for constraint in database.get_unique_constraints(table)
        }
        assert {
            "uq_artifact_run",
            "uq_artifact_record",
            "uq_jobs_run_attempt",
            "uq_progress_job_sequence",
            "uq_run_stages_run_stage",
            "uq_summary_run_filename",
            "uq_warning_exact",
            "uq_page_evidence_run_sequence",
            "uq_page_evidence_run_url",
            "uq_page_redirect_evidence_sequence",
            "uq_page_warning_evidence_sequence",
            "uq_metadata_audit_identity",
            "uq_metadata_audit_page_evidence",
            "uq_metadata_audit_issue_code",
            "uq_metadata_duplicate_value",
            "uq_metadata_audit_export",
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
            "ix_page_evidence_run_order",
            "ix_page_evidence_expiry",
            "ix_page_evidence_indexability",
            "ix_page_redirect_evidence",
            "ix_page_warning_evidence",
            "ix_metadata_audits_order",
            "ix_metadata_audit_pages_order",
            "ix_metadata_audit_issues_order",
            "ix_metadata_duplicate_order",
        } <= index_names
    finally:
        engine.dispose()
    script = ScriptDirectory.from_config(config).get_revision(INITIAL_PERSISTENCE_REVISION)
    assert script is not None
    assert script.revision == "0001_persistence"
    assert script.doc == "create persistence foundation"
    durable_script = ScriptDirectory.from_config(config).get_revision(DURABLE_EXECUTION_REVISION)
    assert durable_script is not None
    assert durable_script.revision == "0002_durable_execution"
    assert durable_script.down_revision == INITIAL_PERSISTENCE_REVISION
    assert durable_script.doc == "add durable execution coordination"
    artifact_script = ScriptDirectory.from_config(config).get_revision(ARTIFACT_STORAGE_REVISION)
    assert artifact_script is not None
    assert artifact_script.revision == "0003_artifact_storage"
    assert artifact_script.down_revision == DURABLE_EXECUTION_REVISION
    assert artifact_script.doc == "add durable artifact storage"
    authentication_script = ScriptDirectory.from_config(config).get_revision(
        AUTHENTICATION_AUTHORIZATION_REVISION
    )
    assert authentication_script is not None
    assert authentication_script.revision == "0005_authentication_authorization"
    assert authentication_script.down_revision == "0004_history_api"
    assert authentication_script.doc == "add internal authentication and authorization"
    page_script = ScriptDirectory.from_config(config).get_revision(PAGE_CRAWL_EVIDENCE_REVISION)
    assert page_script is not None
    assert page_script.revision == "0006_page_crawl_evidence"
    assert page_script.down_revision == AUTHENTICATION_AUTHORIZATION_REVISION
    assert page_script.doc == "add durable page crawl evidence"
    audit_script = ScriptDirectory.from_config(config).get_revision(METADATA_AUDIT_REVISION)
    assert audit_script is not None
    assert audit_script.revision == "0007_metadata_audit"
    assert audit_script.down_revision == PAGE_CRAWL_EVIDENCE_REVISION
    assert audit_script.doc == "add durable metadata audit"


def test_offline_sql_contains_authorized_schema(tmp_path: Path) -> None:
    output = StringIO()
    config = alembic_configuration(_url(tmp_path / "offline.db"), backend_root=BACKEND_ROOT)
    config.attributes["output_buffer"] = output
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE jobs" in sql
    assert "CREATE TABLE artifact_metadata" in sql
    assert "CREATE TABLE durable_jobs" in sql
    assert "CREATE TABLE job_leases" in sql
    assert "CREATE TABLE artifact_records" in sql
    assert "CREATE TABLE users" in sql
    assert "CREATE TABLE authentication_sessions" in sql
    assert "CREATE TABLE crawl_page_evidence" in sql
    assert "CREATE TABLE metadata_audits" in sql
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


def test_authentication_migration_downgrades_only_phase_27_tables(tmp_path: Path) -> None:
    database = tmp_path / "authentication-migration.db"
    url = _url(database)
    configuration = alembic_configuration(url, backend_root=BACKEND_ROOT)
    command.upgrade(configuration, AUTHENTICATION_AUTHORIZATION_REVISION)
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert current_revision(engine) == AUTHENTICATION_AUTHORIZATION_REVISION
        assert "authentication_sessions" in inspector.get_table_names()
        assert {index["name"] for index in inspector.get_indexes("authentication_sessions")} >= {
            "ix_sessions_user",
            "ix_sessions_expiry",
            "ix_sessions_revoked",
        }
        assert {constraint["name"] for constraint in inspector.get_unique_constraints("users")} == {
            "uq_users_normalized_email"
        }
    finally:
        engine.dispose()
    command.downgrade(configuration, "0004_history_api")
    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert current_revision(engine) == "0004_history_api"
        assert "jobs" in tables and "artifact_records" in tables
        assert "users" not in tables and "authentication_sessions" not in tables
    finally:
        engine.dispose()
    command.upgrade(configuration, AUTHENTICATION_AUTHORIZATION_REVISION)
    engine = create_engine(url)
    try:
        assert current_revision(engine) == AUTHENTICATION_AUTHORIZATION_REVISION
    finally:
        engine.dispose()


def test_page_evidence_migration_downgrades_only_page_evidence_tables(tmp_path: Path) -> None:
    database = tmp_path / "page-evidence-migration.db"
    url = _url(database)
    configuration = alembic_configuration(url, backend_root=BACKEND_ROOT)
    command.upgrade(configuration, PAGE_CRAWL_EVIDENCE_REVISION)
    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert current_revision(engine) == PAGE_CRAWL_EVIDENCE_REVISION
        assert "crawl_page_evidence" in tables
        assert "authentication_sessions" in tables
    finally:
        engine.dispose()


def test_metadata_audit_migration_downgrades_only_phase_20_tables(  # noqa: PLR0915
    tmp_path: Path,
) -> None:
    database = tmp_path / "metadata-audit-migration.db"
    url = _url(database)
    configuration = alembic_configuration(url, backend_root=BACKEND_ROOT)
    command.upgrade(configuration, METADATA_AUDIT_REVISION)
    phase_tables = {
        "metadata_audits",
        "metadata_audit_pages",
        "metadata_audit_issues",
        "metadata_duplicate_groups",
        "metadata_duplicate_group_members",
        "metadata_audit_summaries",
        "metadata_audit_exports",
        "metadata_audit_events",
    }
    engine = create_engine(url)
    try:
        assert phase_tables <= set(inspect(engine).get_table_names())
        assert current_revision(engine) == METADATA_AUDIT_REVISION
    finally:
        engine.dispose()
    command.downgrade(configuration, PAGE_CRAWL_EVIDENCE_REVISION)
    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert phase_tables.isdisjoint(tables)
        assert "crawl_page_evidence" in tables
        assert current_revision(engine) == PAGE_CRAWL_EVIDENCE_REVISION
    finally:
        engine.dispose()
    command.upgrade(configuration, METADATA_AUDIT_REVISION)
    engine = create_engine(url)
    try:
        assert schema_is_current(engine)
        assert phase_tables <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    command.downgrade(configuration, AUTHENTICATION_AUTHORIZATION_REVISION)
    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert current_revision(engine) == AUTHENTICATION_AUTHORIZATION_REVISION
        assert "crawl_page_evidence" not in tables
        assert "authentication_sessions" in tables
    finally:
        engine.dispose()
    command.upgrade(configuration, PAGE_CRAWL_EVIDENCE_REVISION)
    engine = create_engine(url)
    try:
        assert not schema_is_current(engine)
    finally:
        engine.dispose()
    command.upgrade(configuration, METADATA_AUDIT_REVISION)
    engine = create_engine(url)
    try:
        assert schema_is_current(engine)
    finally:
        engine.dispose()


def test_artifact_migration_upgrades_downgrades_and_reupgrades_from_durable(
    tmp_path: Path,
) -> None:
    database = tmp_path / "artifact-migration.db"
    url = _url(database)
    configuration = alembic_configuration(url, backend_root=BACKEND_ROOT)
    command.upgrade(configuration, DURABLE_EXECUTION_REVISION)
    command.upgrade(configuration, ARTIFACT_STORAGE_REVISION)
    engine = create_engine(url)
    try:
        assert current_revision(engine) == ARTIFACT_STORAGE_REVISION
        assert "artifact_records" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
    command.downgrade(configuration, DURABLE_EXECUTION_REVISION)
    engine = create_engine(url)
    try:
        assert current_revision(engine) == DURABLE_EXECUTION_REVISION
        assert "artifact_records" not in inspect(engine).get_table_names()
        assert "jobs" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
    command.upgrade(configuration, ARTIFACT_STORAGE_REVISION)
    engine = create_engine(url)
    try:
        assert current_revision(engine) == ARTIFACT_STORAGE_REVISION
    finally:
        engine.dispose()


def test_migration_does_not_disable_existing_application_loggers(tmp_path: Path) -> None:
    logger = logging.getLogger("musimack_tools.persistence.migration-test")
    logger.disabled = False
    upgrade_to_head(_url(tmp_path / "logger.db"), backend_root=BACKEND_ROOT)
    assert not logger.disabled
