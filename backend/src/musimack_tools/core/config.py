"""Typed, non-secret application configuration."""

from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Recognized deployment environment labels."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Supported application log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


PositiveTimeout = Annotated[float, Field(gt=0, le=300)]
RequestDelay = Annotated[float, Field(ge=0.1, le=60)]


class Settings(BaseSettings):
    """Application settings loaded from environment variables or a local `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MUSIMACK_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    application_name: str = Field(default="Musimack SEO Toolkit", min_length=1, max_length=100)
    environment: Environment = Environment.DEVELOPMENT
    log_level: LogLevel = LogLevel.INFO
    crawler_user_agent: str = Field(
        default="MusimackSEOToolkit/0.1",
        min_length=3,
        max_length=200,
    )
    default_maximum_urls: int = Field(default=5_000, ge=1, le=1_000_000)
    default_maximum_crawl_depth: int = Field(default=10, ge=0, le=100)
    default_request_timeout_seconds: PositiveTimeout = 20
    default_per_host_concurrency: int = Field(default=2, ge=1, le=32)
    default_global_crawl_concurrency: int = Field(default=4, ge=1, le=128)
    default_minimum_request_delay_seconds: RequestDelay = 0.5
    include_subdomains_by_default: bool = False

    @model_validator(mode="after")
    def validate_concurrency_relationship(self) -> Settings:
        """Ensure a per-host limit cannot exceed the global worker limit."""
        if self.default_per_host_concurrency > self.default_global_crawl_concurrency:
            message = "default per-host concurrency cannot exceed global crawl concurrency"
            raise ValueError(message)
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings singleton."""
    return Settings()
