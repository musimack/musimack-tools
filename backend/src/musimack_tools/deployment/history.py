"""Immutable environment-backed settings for durable history queries."""

# ruff: noqa: TRY003 - startup configuration failures use stable safe text.

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from musimack_tools.domain.history import (
    HISTORY_API_VERSION,
    HISTORY_PAGINATION_VERSION,
    HISTORY_SERVICE_VERSION,
    HistoryConfiguration,
)
from musimack_tools.history.service import HistoryService
from musimack_tools.persistence.history_repository import SQLAlchemyHistoryRepository
from musimack_tools.persistence.migrations import schema_is_current

if TYPE_CHECKING:
    from musimack_tools.persistence.engine import PersistenceRuntime


class HistorySettings(BaseSettings):
    """History is disabled unless explicitly composed with durable persistence."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MUSIMACK_HISTORY_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    enabled: bool = False
    service_version: str = HISTORY_SERVICE_VERSION
    api_version: str = HISTORY_API_VERSION
    pagination_version: str = HISTORY_PAGINATION_VERSION
    default_page_size: int = Field(default=25, ge=1, le=500)
    maximum_page_size: int = Field(default=100, ge=1, le=500)
    maximum_attempts_per_job: int = Field(default=50, ge=1, le=1_000)
    maximum_stages_per_run: int = Field(default=100, ge=1, le=1_000)
    maximum_warnings_per_run: int = Field(default=250, ge=1, le=1_000)
    maximum_failures_per_run: int = Field(default=250, ge=1, le=1_000)
    maximum_artifacts_per_run: int = Field(default=250, ge=1, le=1_000)
    include_attempts_by_default: bool = False
    include_stages_by_default: bool = True
    include_warnings_by_default: bool = True
    include_failures_by_default: bool = True
    include_artifacts_by_default: bool = True

    @model_validator(mode="after")
    def validate_page_sizes(self) -> HistorySettings:
        if self.default_page_size > self.maximum_page_size:
            raise ValueError("history default page size exceeds maximum page size")
        return self

    def to_configuration(self) -> HistoryConfiguration:
        return HistoryConfiguration(
            enabled=self.enabled,
            default_page_size=self.default_page_size,
            maximum_page_size=self.maximum_page_size,
            maximum_attempts_per_job=self.maximum_attempts_per_job,
            maximum_stages_per_run=self.maximum_stages_per_run,
            maximum_warnings_per_run=self.maximum_warnings_per_run,
            maximum_failures_per_run=self.maximum_failures_per_run,
            maximum_artifacts_per_run=self.maximum_artifacts_per_run,
            include_attempts_by_default=self.include_attempts_by_default,
            include_stages_by_default=self.include_stages_by_default,
            include_warnings_by_default=self.include_warnings_by_default,
            include_failures_by_default=self.include_failures_by_default,
            include_artifacts_by_default=self.include_artifacts_by_default,
            service_version=self.service_version,
            api_version=self.api_version,
            pagination_version=self.pagination_version,
        )


def prepare_history(
    settings: HistorySettings, runtime: PersistenceRuntime
) -> HistoryService | None:
    """Compose history explicitly; never create a database or task as a fallback."""
    configuration = settings.to_configuration()
    if not configuration.enabled:
        return None
    if not runtime.configuration.enabled or not schema_is_current(runtime.engine):
        raise ValueError("history requires current durable persistence")
    return HistoryService(configuration, SQLAlchemyHistoryRepository(runtime))
