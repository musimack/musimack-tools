"""Environment-backed settings for optional local persistence."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 -- Pydantic resolves this field type at runtime.

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from musimack_tools.domain.persistence import (
    PersistenceConfiguration,
    PersistenceRetentionPolicy,
    SQLiteJournalMode,
    SQLiteSynchronousMode,
)

_MISSING_PATH = "an explicit database path is required when persistence is enabled"


class PersistenceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MUSIMACK_PERSISTENCE_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    enabled: bool = False
    database_path: Path | None = None
    echo_sql: bool = False
    foreign_keys: bool = True
    busy_timeout_milliseconds: int = Field(default=5_000, ge=100, le=120_000)
    journal_mode: SQLiteJournalMode = SQLiteJournalMode.WAL
    synchronous_mode: SQLiteSynchronousMode = SQLiteSynchronousMode.NORMAL
    connection_timeout_seconds: float = Field(default=10.0, ge=0.1, le=120.0)
    auto_migrate: bool = False
    reconcile_on_startup: bool = True
    create_parent_directory: bool = False
    maximum_terminal_jobs: int = Field(default=100, ge=0, le=100_000)
    maximum_progress_rows_per_job: int = Field(default=100, ge=0, le=10_000)
    maximum_warning_rows_per_parent: int = Field(default=100, ge=0, le=10_000)
    maximum_failure_rows_per_parent: int = Field(default=100, ge=0, le=10_000)
    maximum_artifact_rows_per_run: int = Field(default=100, ge=0, le=10_000)
    maximum_summary_rows_per_run: int = Field(default=2, ge=0, le=100)
    retain_evicted_job_metadata: bool = True
    retain_interrupted_job_metadata: bool = True

    @model_validator(mode="after")
    def validate_enabled_path(self) -> PersistenceSettings:
        if self.enabled and self.database_path is None:
            raise ValueError(_MISSING_PATH)
        return self

    def to_configuration(self) -> PersistenceConfiguration:
        return PersistenceConfiguration(
            enabled=self.enabled,
            database_path=self.database_path,
            echo_sql=self.echo_sql,
            foreign_keys=self.foreign_keys,
            busy_timeout_milliseconds=self.busy_timeout_milliseconds,
            journal_mode=self.journal_mode,
            synchronous_mode=self.synchronous_mode,
            connection_timeout_seconds=self.connection_timeout_seconds,
            auto_migrate=self.auto_migrate,
            reconcile_on_startup=self.reconcile_on_startup,
            create_parent_directory=self.create_parent_directory,
            retention=PersistenceRetentionPolicy(
                maximum_terminal_jobs=self.maximum_terminal_jobs,
                maximum_progress_rows_per_job=self.maximum_progress_rows_per_job,
                maximum_warning_rows_per_parent=self.maximum_warning_rows_per_parent,
                maximum_failure_rows_per_parent=self.maximum_failure_rows_per_parent,
                maximum_artifact_rows_per_run=self.maximum_artifact_rows_per_run,
                maximum_summary_rows_per_run=self.maximum_summary_rows_per_run,
                retain_evicted_job_metadata=self.retain_evicted_job_metadata,
                retain_interrupted_job_metadata=self.retain_interrupted_job_metadata,
            ),
        )
