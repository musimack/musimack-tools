"""Environment-backed production settings and startup validation."""

import pytest
from pydantic import ValidationError

from musimack_tools.deployment.settings import ProductionSettings
from musimack_tools.domain.deployment import StartupValidationOutcome
from musimack_tools.domain.security import SecurityReadinessState
from musimack_tools.security.validation import security_readiness, validate_production_startup


def test_internal_api_is_disabled_by_default_without_secret() -> None:
    settings = ProductionSettings()
    assert not settings.enabled
    assert settings.bearer_token is None
    assert not settings.cors_enabled
    assert not settings.include_openapi


def test_enabled_settings_require_nonempty_credential() -> None:
    for value in (None, ""):
        with pytest.raises(ValidationError) as raised:
            ProductionSettings.model_validate({"enabled": True, "bearer_token": value})
        assert "credential" not in str(raised.value).lower() or value in {None, ""}


def test_secret_is_redacted_from_repr_and_dump() -> None:
    secret = "test-secret-never-log"  # noqa: S105 - inert test value.
    settings = ProductionSettings.model_validate({"enabled": True, "bearer_token": secret})
    assert secret not in repr(settings)
    assert secret not in str(settings.model_dump())
    assert settings.bearer_token is not None
    assert settings.bearer_token.get_secret_value() == secret


def test_secret_is_redacted_from_validation_errors() -> None:
    secret = "never-echo-" + ("x" * 600)
    with pytest.raises(ValidationError) as raised:
        ProductionSettings.model_validate(
            {
                "enabled": True,
                "bearer_token": secret,
                "cors_enabled": True,
            }
        )
    assert secret not in str(raised.value)


def test_overlong_secret_is_rejected_by_safe_startup_report() -> None:
    secret = "never-echo-" + ("x" * 600)
    settings = ProductionSettings.model_validate({"enabled": True, "bearer_token": secret})
    report = validate_production_startup(settings, object())  # type: ignore[arg-type]
    assert report.outcome is StartupValidationOutcome.INVALID
    assert [issue.code for issue in report.issues] == ["security_credential_invalid"]
    assert secret not in repr(report)


def test_expected_environment_variables_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MUSIMACK_INTERNAL_API_ENABLED", "true")
    monkeypatch.setenv("MUSIMACK_INTERNAL_API_BEARER_TOKEN", "environment-test-token")
    monkeypatch.setenv("MUSIMACK_INTERNAL_API_TOKEN_ID", "operator-1")
    monkeypatch.setenv("MUSIMACK_INTERNAL_API_TRUSTED_PROXIES", "10.0.0.0/8,2001:db8::/32")
    monkeypatch.setenv("MUSIMACK_INTERNAL_API_TRUSTED_NETWORKS", "192.168.1.0/24")
    settings = ProductionSettings()
    assert settings.enabled
    assert settings.token_id == "operator-1"  # noqa: S105 - identifier, not a credential.
    assert settings.trusted_proxies == ("10.0.0.0/8", "2001:db8::/32")
    assert settings.trusted_networks == ("192.168.1.0/24",)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"token_id": "bad identity"},
        {"request_id_header": "X Request"},
        {"trusted_proxies": ("not-a-cidr",)},
        {"trusted_networks": ("example.com",)},
        {"allowed_origins": ("*",)},
        {"allowed_origins": ("https://user@example.test",)},
        {"allowed_origins": ("https://example.test/path",)},
        {"cors_enabled": True},
        {"maximum_forwarded_hops": 0},
        {"maximum_forwarded_header_length": 9},
    ],
)
def test_invalid_security_settings_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ProductionSettings.model_validate(kwargs)


def test_unrelated_environment_is_not_inferred(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEARER_TOKEN", "unrelated-secret")
    monkeypatch.setenv("INTERNAL_API_ENABLED", "true")
    settings = ProductionSettings()
    assert not settings.enabled
    assert settings.bearer_token is None


def test_invalid_environment_boolean_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MUSIMACK_INTERNAL_API_ENABLED", "not-a-boolean")
    with pytest.raises(ValidationError):
        ProductionSettings()


def test_startup_validation_is_ordered_and_secret_free() -> None:
    settings = ProductionSettings()
    report = validate_production_startup(settings, None)
    assert report.outcome is StartupValidationOutcome.INVALID
    assert [issue.code for issue in report.issues] == [
        "internal_api_disabled",
        "security_credential_missing",
        "application_service_missing",
    ]
    assert "secret" not in repr(report).lower()


def test_security_readiness_reports_ready_and_degraded() -> None:
    ready = security_readiness(
        ProductionSettings.model_validate({"enabled": True, "bearer_token": "test-token"})
    )
    degraded = security_readiness(
        ProductionSettings.model_validate(
            {
                "enabled": True,
                "bearer_token": "test-token",
                "access_logging": False,
            }
        )
    )
    assert ready.state is SecurityReadinessState.READY
    assert degraded.state is SecurityReadinessState.DEGRADED


def test_startup_validation_reports_nonblocking_degraded_configuration() -> None:
    settings = ProductionSettings.model_validate(
        {
            "enabled": True,
            "bearer_token": "test-token",
            "access_logging": False,
            "security_headers": False,
        }
    )
    report = validate_production_startup(settings, object())  # type: ignore[arg-type]
    assert report.outcome is StartupValidationOutcome.DEGRADED
    assert [issue.code for issue in report.issues] == [
        "access_logging_disabled",
        "security_headers_disabled",
    ]
    assert not any(issue.blocking for issue in report.issues)
