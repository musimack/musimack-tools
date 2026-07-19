"""Typed validation for the production operations boundary."""

# ruff: noqa: PLR0915, TRY003

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from ipaddress import ip_network
from pathlib import Path
from typing import TYPE_CHECKING, Annotated
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from musimack_tools.core.config import Environment
from musimack_tools.domain.authentication import AuthenticationMode

if TYPE_CHECKING:
    from musimack_tools.core.config import Settings
    from musimack_tools.deployment.artifacts import ArtifactStorageSettings
    from musimack_tools.deployment.durable import DurableExecutionSettings
    from musimack_tools.deployment.persistence import PersistenceSettings
    from musimack_tools.deployment.settings import ProductionSettings

OPERATIONS_VERSION = "seo-toolkit-production-operations-v1"
StringTuple = Annotated[tuple[str, ...], NoDecode]
_HOST = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|localhost)$")
_PLACEHOLDER_FRAGMENTS = (
    "change-me",
    "changeme",
    "replace-me",
    "placeholder",
    "provide-through",
    "your-secret",
    "example-secret",
)
_MAXIMUM_TRUSTED_HOSTS = 32
IssueRecorder = Callable[[str, str, str, str], None]


class ApplicationRole(StrEnum):
    """Supported independently supervised process roles."""

    WEB = "web"
    WORKER = "worker"


class ConfigurationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class ConfigurationIssue:
    code: str
    setting: str
    description: str
    remediation: str
    severity: ConfigurationSeverity = ConfigurationSeverity.ERROR


class ProductionOperationsConfigurationError(RuntimeError):
    """Secret-free aggregate configuration failure."""

    def __init__(self, issues: tuple[ConfigurationIssue, ...]) -> None:
        super().__init__("Production operations configuration is invalid.")
        self.issues = issues


class OperationsSettings(BaseSettings):
    """Process-neutral settings shared by preflight, web, worker, and recovery commands."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MUSIMACK_OPERATIONS_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    debug: bool = False
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65_535)
    public_origin: str = "https://musimack.invalid"
    trusted_hosts: StringTuple = ()
    frontend_build_path: Path | None = None
    shutdown_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    allow_insecure_loopback_validation: bool = False
    operations_version: str = OPERATIONS_VERSION

    @field_validator("trusted_hosts", mode="before")
    @classmethod
    def parse_trusted_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        candidate = value.strip()
        if candidate not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("operations host must be loopback")
        return candidate

    @field_validator("trusted_hosts")
    @classmethod
    def validate_trusted_hosts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) > _MAXIMUM_TRUSTED_HOSTS:
            raise ValueError("one to 32 explicit trusted hosts are required")
        for host in value:
            if host == "*" or _HOST.fullmatch(host) is None:
                raise ValueError("trusted hosts must be explicit hostnames")
        return value

    @field_validator("public_origin")
    @classmethod
    def validate_public_origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("public origin must be one explicit HTTP or HTTPS origin")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_loopback_override(self) -> OperationsSettings:
        parsed = urlsplit(self.public_origin)
        loopback_origin = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        if self.allow_insecure_loopback_validation and not loopback_origin:
            raise ValueError("insecure validation is restricted to an explicit loopback origin")
        if not self.allow_insecure_loopback_validation and parsed.scheme != "https":
            raise ValueError("production public origin must use HTTPS")
        if self.operations_version != OPERATIONS_VERSION:
            raise ValueError("operations version is unsupported")
        return self


def validate_production_configuration(  # noqa: C901, PLR0912, PLR0913
    application: Settings,
    production: ProductionSettings,
    persistence: PersistenceSettings,
    durable: DurableExecutionSettings,
    artifacts: ArtifactStorageSettings,
    operations: OperationsSettings,
    *,
    repository_root: Path,
    role: ApplicationRole | None = None,
) -> tuple[ConfigurationIssue, ...]:
    """Return ordered, secret-free production contract violations."""
    issues: list[ConfigurationIssue] = []

    def reject(code: str, setting: str, description: str, remediation: str) -> None:
        issues.append(ConfigurationIssue(code, setting, description, remediation))

    if application.environment is not Environment.PRODUCTION:
        reject(
            "environment_not_production",
            "MUSIMACK_ENVIRONMENT",
            "The application environment is not production.",
            "Set MUSIMACK_ENVIRONMENT=production.",
        )
    if operations.debug:
        reject(
            "debug_enabled",
            "MUSIMACK_OPERATIONS_DEBUG",
            "Debug behavior is enabled.",
            "Disable debug behavior for production operations.",
        )
    if urlsplit(operations.public_origin).hostname == "musimack.invalid":
        reject(
            "public_origin_placeholder",
            "MUSIMACK_OPERATIONS_PUBLIC_ORIGIN",
            "The public origin is still the example placeholder.",
            "Configure the private HTTPS ingress origin.",
        )
    if not production.enabled:
        reject(
            "internal_api_disabled",
            "MUSIMACK_INTERNAL_API_ENABLED",
            "The private API is disabled.",
            "Explicitly enable the internal API.",
        )
    if not production.authentication_enabled:
        reject(
            "user_authentication_disabled",
            "MUSIMACK_INTERNAL_API_AUTHENTICATION_ENABLED",
            "User authentication is disabled.",
            "Enable persisted user authentication for the private application.",
        )
    bearer_required = production.authentication_mode in {
        AuthenticationMode.SHARED_BEARER,
        AuthenticationMode.HYBRID,
    }
    raw_secret = (
        production.bearer_token.get_secret_value() if production.bearer_token is not None else ""
    )
    if bearer_required and not raw_secret:
        reject(
            "bearer_credential_missing",
            "MUSIMACK_INTERNAL_API_BEARER_TOKEN",
            "The selected authentication mode requires a bearer credential.",
            "Supply the credential through the process secret store.",
        )
    if raw_secret and _looks_like_placeholder(raw_secret):
        reject(
            "bearer_credential_placeholder",
            "MUSIMACK_INTERNAL_API_BEARER_TOKEN",
            "The bearer credential appears to be a placeholder.",
            "Replace the placeholder through the process secret store.",
        )
    if (
        production.authentication_mode is AuthenticationMode.USER_SESSION
        and production.shared_bearer_compatibility_enabled
    ):
        reject(
            "bearer_compatibility_unneeded",
            "MUSIMACK_INTERNAL_API_SHARED_BEARER_COMPATIBILITY_ENABLED",
            "Shared-bearer compatibility is enabled for session-only authentication.",
            "Disable shared-bearer compatibility or select hybrid mode.",
        )
    if not production.require_secure_cookie and not operations.allow_insecure_loopback_validation:
        reject(
            "secure_cookie_required",
            "MUSIMACK_INTERNAL_API_REQUIRE_SECURE_COOKIE",
            "Secure session cookies are disabled.",
            "Enable Secure cookies for the HTTPS production path.",
        )
    _validate_network_policy(production.trusted_networks, "trusted_networks", reject)
    _validate_network_policy(production.trusted_proxies, "trusted_proxies", reject)
    if not persistence.enabled or persistence.database_path is None:
        reject(
            "persistence_required",
            "MUSIMACK_PERSISTENCE_DATABASE_PATH",
            "Production persistence requires an explicit database path.",
            "Enable persistence and configure an absolute durable database path.",
        )
    else:
        _validate_durable_path(
            persistence.database_path,
            "database_path",
            repository_root,
            reject,
        )
    if persistence.auto_migrate:
        reject(
            "automatic_migration_forbidden",
            "MUSIMACK_PERSISTENCE_AUTO_MIGRATE",
            "Ordinary startup is configured to apply migrations automatically.",
            "Disable auto-migrate and use the explicit operations migrate command.",
        )
    if not durable.durable_execution_enabled:
        reject(
            "durable_execution_required",
            "MUSIMACK_DURABLE_EXECUTION_ENABLED",
            "The durable queue is disabled.",
            "Enable durable execution for supervised web and worker processes.",
        )
    if role is ApplicationRole.WORKER and not durable.worker_enabled:
        reject(
            "worker_disabled",
            "MUSIMACK_WORKER_ENABLED",
            "The worker role is not enabled.",
            "Enable the worker and configure a unique worker ID.",
        )
    if role is ApplicationRole.WORKER and not durable.worker_id:
        reject(
            "worker_id_missing",
            "MUSIMACK_WORKER_ID",
            "The worker role has no identity.",
            "Configure a stable unique worker ID.",
        )
    try:
        durable.to_configuration()
    except ValueError:
        reject(
            "durable_configuration_invalid",
            "MUSIMACK_WORKER_ID",
            "The durable worker configuration is invalid.",
            "Use a bounded worker-<safe-label> identity and valid queue relationships.",
        )
    if durable.worker_heartbeat_interval_seconds >= durable.worker_lease_duration_seconds:
        reject(
            "worker_heartbeat_invalid",
            "MUSIMACK_WORKER_HEARTBEAT_INTERVAL_SECONDS",
            "The heartbeat interval is not shorter than the lease duration.",
            "Use a heartbeat interval shorter than the lease duration.",
        )
    if operations.shutdown_timeout_seconds < durable.worker_shutdown_grace_period_seconds:
        reject(
            "shutdown_timeout_too_short",
            "MUSIMACK_OPERATIONS_SHUTDOWN_TIMEOUT_SECONDS",
            "The process shutdown timeout is shorter than the worker grace period.",
            "Increase the process timeout or reduce the worker grace period.",
        )
    artifact_roots: tuple[Path, ...] = ()
    try:
        artifact_configuration = artifacts.to_configuration()
        artifact_roots = tuple(item.path for item in artifact_configuration.roots)
    except ValueError:
        reject(
            "artifact_configuration_invalid",
            "MUSIMACK_ARTIFACT_STORAGE_ROOTS",
            "Artifact root specifications are invalid.",
            "Use unique root-id=absolute-path entries.",
        )
    if not artifacts.enabled or not artifact_roots:
        reject(
            "artifact_storage_required",
            "MUSIMACK_ARTIFACT_STORAGE_ROOTS",
            "Production artifact storage requires explicit roots.",
            "Enable artifact storage with at least one durable absolute root.",
        )
    for root in artifact_roots:
        _validate_durable_path(root, "artifact_root", repository_root, reject)
    if persistence.database_path is not None:
        database = persistence.database_path.resolve(strict=False)
        for root in artifact_roots:
            resolved_root = root.resolve(strict=False)
            if database == resolved_root or resolved_root in database.parents:
                reject(
                    "database_artifact_collision",
                    "MUSIMACK_PERSISTENCE_DATABASE_PATH",
                    "The database is inside an artifact root.",
                    "Use separate durable locations for database and artifact state.",
                )
    if operations.frontend_build_path is None:
        reject(
            "frontend_build_path_missing",
            "MUSIMACK_OPERATIONS_FRONTEND_BUILD_PATH",
            "The static frontend build path is not configured.",
            "Configure the absolute Vite dist directory served by private ingress.",
        )
    elif not operations.frontend_build_path.is_absolute():
        reject(
            "frontend_build_path_relative",
            "MUSIMACK_OPERATIONS_FRONTEND_BUILD_PATH",
            "The static frontend build path is relative.",
            "Configure an absolute frontend build path.",
        )
    else:
        frontend = operations.frontend_build_path.resolve(strict=False)
        repository = repository_root.resolve(strict=False)
        if frontend == repository or repository in frontend.parents:
            reject(
                "frontend_build_inside_repository",
                "MUSIMACK_OPERATIONS_FRONTEND_BUILD_PATH",
                "The production frontend build is inside the source repository.",
                "Deploy the Vite build to an immutable location outside the checkout.",
            )
    return tuple(issues)


def require_production_configuration(*args: object, **kwargs: object) -> None:
    """Raise one stable, secret-free exception when production settings are unsafe."""
    issues = validate_production_configuration(*args, **kwargs)  # type: ignore[arg-type]
    if issues:
        raise ProductionOperationsConfigurationError(issues)


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.strip().casefold()
    return (
        not lowered
        or lowered.startswith("<")
        or lowered.endswith(">")
        or any(fragment in lowered for fragment in _PLACEHOLDER_FRAGMENTS)
    )


def _validate_network_policy(
    values: tuple[str, ...],
    label: str,
    reject: IssueRecorder,
) -> None:
    if not values:
        reject(
            f"{label}_missing",
            f"MUSIMACK_INTERNAL_API_{label.upper()}",
            f"The {label.replace('_', ' ')} policy is empty.",
            "Configure explicit CIDR entries for the private ingress topology.",
        )
        return
    for value in values:
        network = ip_network(value, strict=False)
        if network.prefixlen == 0:
            reject(
                f"{label}_wildcard",
                f"MUSIMACK_INTERNAL_API_{label.upper()}",
                f"The {label.replace('_', ' ')} policy trusts every address.",
                "Replace wildcard trust with explicit private CIDRs.",
            )


def _validate_durable_path(
    path: Path,
    label: str,
    repository_root: Path,
    reject: IssueRecorder,
) -> None:
    if not path.is_absolute():
        reject(
            f"{label}_relative",
            label,
            f"The {label.replace('_', ' ')} is relative.",
            "Use an absolute durable path.",
        )
        return
    resolved = path.resolve(strict=False)
    repository = repository_root.resolve(strict=False)
    if resolved == Path(resolved.anchor):
        reject(
            f"{label}_filesystem_root",
            label,
            f"The {label.replace('_', ' ')} is a filesystem root.",
            "Use a dedicated durable subdirectory.",
        )
        return
    if resolved == repository or repository in resolved.parents:
        reject(
            f"{label}_inside_repository",
            label,
            f"The {label.replace('_', ' ')} is inside the source repository.",
            "Move production state to a durable location outside the checkout.",
        )
