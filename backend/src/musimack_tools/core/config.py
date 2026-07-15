"""Typed, non-secret application configuration."""

from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
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
_MAX_CONFIGURED_PORTS = 16
_MAX_PORT = 65_535


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
    fetch_maximum_redirect_hops: int = Field(default=10, ge=0, le=20)
    fetch_maximum_response_body_bytes: int = Field(default=5_000_000, ge=1, le=50_000_000)
    fetch_maximum_response_header_bytes: int = Field(default=65_536, ge=1_024, le=1_048_576)
    fetch_maximum_dns_answers: int = Field(default=16, ge=1, le=64)
    fetch_connect_timeout_seconds: PositiveTimeout = 10
    fetch_read_timeout_seconds: PositiveTimeout = 20
    fetch_write_timeout_seconds: PositiveTimeout = 10
    fetch_pool_timeout_seconds: PositiveTimeout = 10
    fetch_total_request_deadline_seconds: PositiveTimeout = 30
    fetch_retry_count: int = Field(default=1, ge=0, le=3)
    fetch_permitted_production_ports: tuple[int, ...] = (80, 443)
    fetch_http_allowed: bool = True
    fetch_https_allowed: bool = True
    fetch_trust_environment_proxies: bool = False

    @field_validator("fetch_permitted_production_ports")
    @classmethod
    def validate_fetch_ports(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        """Require a short, unique list of valid production ports."""
        if not value or len(value) > _MAX_CONFIGURED_PORTS:
            message = "fetch permitted ports must contain between 1 and 16 entries"
            raise ValueError(message)
        if any(port < 1 or port > _MAX_PORT for port in value):
            message = "fetch permitted ports must be between 1 and 65535"
            raise ValueError(message)
        if len(set(value)) != len(value):
            message = "fetch permitted ports must not contain duplicates"
            raise ValueError(message)
        return value

    @model_validator(mode="after")
    def validate_concurrency_relationship(self) -> Settings:
        """Ensure a per-host limit cannot exceed the global worker limit."""
        if self.default_per_host_concurrency > self.default_global_crawl_concurrency:
            message = "default per-host concurrency cannot exceed global crawl concurrency"
            raise ValueError(message)
        if not self.fetch_http_allowed and not self.fetch_https_allowed:
            message = "at least one fetch scheme must be allowed"
            raise ValueError(message)
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings singleton."""
    return Settings()
