"""Production operations configuration contract behavior."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError

from musimack_tools.core.config import Environment, Settings
from musimack_tools.deployment.artifacts import ArtifactStorageSettings
from musimack_tools.deployment.durable import DurableExecutionSettings
from musimack_tools.deployment.persistence import PersistenceSettings
from musimack_tools.deployment.settings import ProductionSettings
from musimack_tools.domain.authentication import AuthenticationMode
from musimack_tools.operations.configuration import (
    ApplicationRole,
    OperationsSettings,
    ProductionOperationsConfigurationError,
    require_production_configuration,
    validate_production_configuration,
)

_TOKEN = "operations-unit-token-value"  # noqa: S105 - inert test credential.


@dataclass(frozen=True, slots=True)
class _SettingsBundle:
    application: Settings
    production: ProductionSettings
    persistence: PersistenceSettings
    durable: DurableExecutionSettings
    artifacts: ArtifactStorageSettings
    operations: OperationsSettings


def _settings(tmp_path: Path) -> _SettingsBundle:
    database = tmp_path / "state" / "musimack.db"
    artifact_root = tmp_path / "artifacts"
    frontend = tmp_path / "frontend-dist"
    return _SettingsBundle(
        Settings(environment=Environment.PRODUCTION),
        ProductionSettings.model_validate(
            {
                "enabled": True,
                "bearer_token": _TOKEN,
                "authentication_enabled": True,
                "authentication_mode": AuthenticationMode.HYBRID,
                "trusted_networks": ("127.0.0.1/32",),
                "trusted_proxies": ("127.0.0.1/32",),
            }
        ),
        PersistenceSettings.model_validate(
            {"enabled": True, "database_path": database, "auto_migrate": False}
        ),
        DurableExecutionSettings.model_validate(
            {
                "durable_execution_enabled": True,
                "worker_enabled": True,
                "worker_id": "worker-unit",
            }
        ),
        ArtifactStorageSettings.model_validate(
            {
                "enabled": True,
                "default_root_id": "primary",
                "storage_roots": (f"primary={artifact_root}",),
            }
        ),
        OperationsSettings.model_validate(
            {
                "public_origin": "https://seo.internal.test",
                "trusted_hosts": ("seo.internal.test",),
                "frontend_build_path": frontend,
            }
        ),
    )


def _issues(  # noqa: PLR0913 - typed fixture overrides mirror the production contract.
    tmp_path: Path,
    *,
    application: Settings | None = None,
    production: ProductionSettings | None = None,
    persistence: PersistenceSettings | None = None,
    durable: DurableExecutionSettings | None = None,
    artifacts: ArtifactStorageSettings | None = None,
    operations: OperationsSettings | None = None,
) -> tuple[str, ...]:
    values = _settings(tmp_path)
    report = validate_production_configuration(
        application or values.application,
        production or values.production,
        persistence or values.persistence,
        durable or values.durable,
        artifacts or values.artifacts,
        operations or values.operations,
        repository_root=tmp_path / "checkout",
        role=ApplicationRole.WORKER,
    )
    return tuple(item.code for item in report)


def test_valid_production_configuration_has_no_issues(tmp_path: Path) -> None:
    assert _issues(tmp_path) == ()


def test_nonproduction_and_debug_are_rejected(tmp_path: Path) -> None:
    values = _settings(tmp_path)
    operations = values.operations.model_copy(update={"debug": True})
    codes = _issues(
        tmp_path,
        application=Settings(environment=Environment.DEVELOPMENT),
        operations=operations,
    )
    assert "environment_not_production" in codes
    assert "debug_enabled" in codes


@pytest.mark.parametrize("secret", ["<replace-me>", "change-me-now", "example-secret-value"])
def test_placeholder_secrets_are_rejected_without_echo(tmp_path: Path, secret: str) -> None:
    values = _settings(tmp_path)
    production = ProductionSettings.model_validate(
        {**values.production.model_dump(), "bearer_token": secret}
    )
    report = validate_production_configuration(
        values.application,
        production,
        values.persistence,
        values.durable,
        values.artifacts,
        values.operations,
        repository_root=tmp_path / "checkout",
        role=ApplicationRole.WORKER,
    )
    assert "bearer_credential_placeholder" in {item.code for item in report}
    assert secret not in repr(report)


def test_missing_bearer_for_hybrid_mode_is_rejected(tmp_path: Path) -> None:
    values = _settings(tmp_path)
    production = values.production.model_copy(update={"bearer_token": None})
    assert "bearer_credential_missing" in _issues(tmp_path, production=production)


def test_session_only_mode_requires_compatibility_to_be_disabled(tmp_path: Path) -> None:
    values = _settings(tmp_path)
    production = values.production.model_copy(
        update={"authentication_mode": AuthenticationMode.USER_SESSION, "bearer_token": None}
    )
    assert "bearer_compatibility_unneeded" in _issues(tmp_path, production=production)


def test_database_and_artifact_paths_must_be_outside_repository(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    values = _settings(tmp_path)
    persistence = values.persistence.model_copy(update={"database_path": checkout / "state.db"})
    artifacts = values.artifacts.model_copy(
        update={
            "default_root_id": "primary",
            "storage_roots": (f"primary={checkout / 'artifacts'}",),
        }
    )
    report = validate_production_configuration(
        values.application,
        values.production,
        persistence,
        values.durable,
        artifacts,
        values.operations,
        repository_root=checkout,
        role=ApplicationRole.WORKER,
    )
    codes = {item.code for item in report}
    assert "database_path_inside_repository" in codes
    assert "artifact_root_inside_repository" in codes


def test_placeholder_origin_frontend_checkout_and_filesystem_root_are_rejected(
    tmp_path: Path,
) -> None:
    values = _settings(tmp_path)
    checkout = tmp_path / "checkout"
    persistence = values.persistence.model_copy(
        update={"database_path": Path(tmp_path.anchor) if tmp_path.anchor else Path("/")}
    )
    operations = values.operations.model_copy(
        update={
            "public_origin": "https://musimack.invalid",
            "frontend_build_path": checkout / "frontend" / "dist",
        }
    )
    report = validate_production_configuration(
        values.application,
        values.production,
        persistence,
        values.durable,
        values.artifacts,
        operations,
        repository_root=checkout,
        role=ApplicationRole.WORKER,
    )
    codes = {item.code for item in report}
    assert "public_origin_placeholder" in codes
    assert "database_path_filesystem_root" in codes
    assert "frontend_build_inside_repository" in codes


def test_database_cannot_be_inside_artifact_root(tmp_path: Path) -> None:
    values = _settings(tmp_path)
    root = tmp_path / "durable"
    persistence = values.persistence.model_copy(update={"database_path": root / "state.db"})
    artifacts = values.artifacts.model_copy(
        update={"default_root_id": "primary", "storage_roots": (f"primary={root}",)}
    )
    assert "database_artifact_collision" in _issues(
        tmp_path, persistence=persistence, artifacts=artifacts
    )


@pytest.mark.parametrize("network", ["0.0.0.0/0", "::/0"])
def test_wildcard_network_and_proxy_trust_are_rejected(tmp_path: Path, network: str) -> None:
    values = _settings(tmp_path)
    production = values.production.model_copy(
        update={"trusted_networks": (network,), "trusted_proxies": (network,)}
    )
    codes = _issues(tmp_path, production=production)
    assert "trusted_networks_wildcard" in codes
    assert "trusted_proxies_wildcard" in codes


def test_automatic_migration_is_rejected(tmp_path: Path) -> None:
    values = _settings(tmp_path)
    persistence = values.persistence.model_copy(update={"auto_migrate": True})
    assert "automatic_migration_forbidden" in _issues(tmp_path, persistence=persistence)


def test_worker_relationship_and_shutdown_timeout_are_rejected(tmp_path: Path) -> None:
    values = _settings(tmp_path)
    durable = values.durable.model_copy(
        update={"worker_heartbeat_interval_seconds": 30.0, "worker_lease_duration_seconds": 30.0}
    )
    operations = values.operations.model_copy(update={"shutdown_timeout_seconds": 10.0})
    codes = _issues(tmp_path, durable=durable, operations=operations)
    assert "worker_heartbeat_invalid" in codes
    assert "shutdown_timeout_too_short" in codes


def test_invalid_worker_identity_is_rejected_before_runtime(tmp_path: Path) -> None:
    values = _settings(tmp_path)
    durable = values.durable.model_copy(update={"worker_id": "unsafe identity"})
    assert "durable_configuration_invalid" in _issues(tmp_path, durable=durable)


def test_configuration_exception_is_bounded_and_secret_free(tmp_path: Path) -> None:
    values = _settings(tmp_path)
    secret = "change-me-never-echo"  # noqa: S105 - inert test secret-redaction evidence.
    production = ProductionSettings.model_validate(
        {**values.production.model_dump(), "bearer_token": secret}
    )
    with pytest.raises(ProductionOperationsConfigurationError) as raised:
        require_production_configuration(
            values.application,
            production,
            values.persistence,
            values.durable,
            values.artifacts,
            values.operations,
            repository_root=tmp_path / "checkout",
            role=ApplicationRole.WORKER,
        )
    assert secret not in str(raised.value)
    assert secret not in repr(raised.value.issues)


@pytest.mark.parametrize(
    "values",
    [
        {"trusted_hosts": ()},
        {"trusted_hosts": ("*",)},
        {"public_origin": "http://seo.internal.test", "trusted_hosts": ("seo.internal.test",)},
        {
            "public_origin": "https://seo.internal.test/path",
            "trusted_hosts": ("seo.internal.test",),
        },
        {
            "public_origin": "https://seo.internal.test",
            "trusted_hosts": ("seo.internal.test",),
            "allow_insecure_loopback_validation": True,
        },
    ],
)
def test_invalid_ingress_settings_fail_closed(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        OperationsSettings.model_validate(values)
