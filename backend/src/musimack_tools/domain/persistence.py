"""Immutable contracts for optional durable persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from musimack_tools.domain.metadata_audit import MetadataAuditConfiguration
from musimack_tools.domain.page_evidence import PageEvidenceConfiguration

if TYPE_CHECKING:
    from pathlib import Path

PERSISTENCE_VERSION = "seo-toolkit-persistence-v1"
DATABASE_SCHEMA_VERSION = "seo-toolkit-database-schema-v1"
_INVALID_RETENTION = "persistence retention limits cannot be negative"
_UNSUPPORTED_PERSISTENCE = "unsupported persistence version"
_UNSUPPORTED_SCHEMA = "unsupported database schema version"
_MISSING_PATH = "an explicit database path is required when persistence is enabled"
_RELATIVE_PATH = "database path must be absolute"
_INVALID_BUSY_TIMEOUT = "busy timeout must be between 100 and 120000 milliseconds"
_INVALID_CONNECTION_TIMEOUT = "connection timeout must be between 0.1 and 120 seconds"
_MINIMUM_BUSY_TIMEOUT = 100
_MAXIMUM_BUSY_TIMEOUT = 120_000
_MINIMUM_CONNECTION_TIMEOUT = 0.1
_MAXIMUM_CONNECTION_TIMEOUT = 120.0


class SQLiteJournalMode(StrEnum):
    WAL = "WAL"
    DELETE = "DELETE"


class SQLiteSynchronousMode(StrEnum):
    NORMAL = "NORMAL"
    FULL = "FULL"


class PersistenceFailureCode(StrEnum):
    DISABLED = "persistence_disabled"
    CONFIGURATION_INVALID = "persistence_configuration_invalid"
    DATABASE_UNAVAILABLE = "database_unavailable"
    DATABASE_LOCKED = "database_locked"
    DATABASE_WRITE_FAILED = "database_write_failed"
    DATABASE_READ_FAILED = "database_read_failed"
    DATABASE_INTEGRITY_ERROR = "database_integrity_error"
    SCHEMA_VERSION_MISMATCH = "schema_version_mismatch"
    MIGRATION_REQUIRED = "migration_required"
    MIGRATION_FAILED = "migration_failed"
    RECONCILIATION_FAILED = "reconciliation_failed"
    RETENTION_FAILED = "retention_failed"
    CLEANUP_FAILED = "cleanup_failed"
    RECORD_NOT_FOUND = "persistence_record_not_found"


class PersistenceReadinessState(StrEnum):
    DISABLED = "disabled"
    READY = "ready"
    DEGRADED = "degraded"
    NOT_READY = "not_ready"


class ReconciliationState(StrEnum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    COMPLETED = "completed"
    FAILED = "failed"


class RetentionState(StrEnum):
    RETAINED = "retained"
    EVICTED = "evicted"
    METADATA_ONLY = "metadata_only"


class ArtifactType(StrEnum):
    SITEMAP_XML = "sitemap_xml"
    SITEMAP_INDEX = "sitemap_index"
    SITEMAP_MANIFEST = "sitemap_manifest"
    RUN_SUMMARY_JSON = "run_summary_json"
    RUN_SUMMARY_MARKDOWN = "run_summary_markdown"


@dataclass(frozen=True, slots=True)
class PersistenceRetentionPolicy:
    maximum_terminal_jobs: int = 100
    maximum_progress_rows_per_job: int = 100
    maximum_warning_rows_per_parent: int = 100
    maximum_failure_rows_per_parent: int = 100
    maximum_artifact_rows_per_run: int = 100
    maximum_summary_rows_per_run: int = 2
    retain_evicted_job_metadata: bool = True
    retain_interrupted_job_metadata: bool = True

    def __post_init__(self) -> None:
        values = (
            self.maximum_terminal_jobs,
            self.maximum_progress_rows_per_job,
            self.maximum_warning_rows_per_parent,
            self.maximum_failure_rows_per_parent,
            self.maximum_artifact_rows_per_run,
            self.maximum_summary_rows_per_run,
        )
        if any(value < 0 for value in values):
            raise ValueError(_INVALID_RETENTION)


@dataclass(frozen=True, slots=True)
class PersistenceConfiguration:
    enabled: bool = False
    database_path: Path | None = None
    echo_sql: bool = False
    foreign_keys: bool = True
    busy_timeout_milliseconds: int = 5_000
    journal_mode: SQLiteJournalMode = SQLiteJournalMode.WAL
    synchronous_mode: SQLiteSynchronousMode = SQLiteSynchronousMode.NORMAL
    connection_timeout_seconds: float = 10.0
    auto_migrate: bool = False
    reconcile_on_startup: bool = True
    create_parent_directory: bool = False
    retention: PersistenceRetentionPolicy = field(default_factory=PersistenceRetentionPolicy)
    page_evidence: PageEvidenceConfiguration = field(default_factory=PageEvidenceConfiguration)
    metadata_audit: MetadataAuditConfiguration = field(default_factory=MetadataAuditConfiguration)
    persistence_version: str = PERSISTENCE_VERSION
    schema_version: str = DATABASE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.persistence_version != PERSISTENCE_VERSION:
            raise ValueError(_UNSUPPORTED_PERSISTENCE)
        if self.schema_version != DATABASE_SCHEMA_VERSION:
            raise ValueError(_UNSUPPORTED_SCHEMA)
        if self.enabled and self.database_path is None:
            raise ValueError(_MISSING_PATH)
        if self.database_path is not None and not self.database_path.is_absolute():
            raise ValueError(_RELATIVE_PATH)
        if not _MINIMUM_BUSY_TIMEOUT <= self.busy_timeout_milliseconds <= _MAXIMUM_BUSY_TIMEOUT:
            raise ValueError(_INVALID_BUSY_TIMEOUT)
        if not (
            _MINIMUM_CONNECTION_TIMEOUT
            <= self.connection_timeout_seconds
            <= _MAXIMUM_CONNECTION_TIMEOUT
        ):
            raise ValueError(_INVALID_CONNECTION_TIMEOUT)


@dataclass(frozen=True, slots=True)
class PersistenceOperationResult:
    succeeded: bool
    failure_code: PersistenceFailureCode | None = None
    explanation: str | None = None


@dataclass(frozen=True, slots=True)
class PersistenceDiagnostics:
    state: PersistenceReadinessState
    enabled: bool
    database_reachable: bool
    sqlite_version: str | None
    foreign_keys_enabled: bool | None
    journal_mode: str | None
    schema_current: bool
    pending_migration: bool
    repository_ready: bool
    reconciliation: ReconciliationState
    failure_code: PersistenceFailureCode | None = None
    persistence_version: str = PERSISTENCE_VERSION
    schema_version: str = DATABASE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    state: ReconciliationState
    inspected_jobs: int
    interrupted_jobs: int
    preserved_terminal_jobs: int
    highest_attempts: tuple[tuple[str, int], ...]
    failure_code: PersistenceFailureCode | None = None
    interruption_code: str = "process_restart_interrupted"


@dataclass(frozen=True, slots=True)
class CleanupResult:
    progress_rows_removed: int
    warning_rows_removed: int
    failure_rows_removed: int
    artifact_rows_removed: int
    summary_rows_removed: int
    terminal_jobs_evicted: int
    orphan_rows_removed: int
    failure_code: PersistenceFailureCode | None = None


@dataclass(frozen=True, slots=True)
class PersistedJobMetadata:
    job_id: str
    run_id: str
    attempt_number: int
    state: str
    terminal: bool
    result_available: bool
    warning_count: int
    failure_count: int
    latest_progress_sequence: int | None
