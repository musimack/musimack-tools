"""Immutable security and deployment domain contracts."""

from dataclasses import FrozenInstanceError

import pytest

from musimack_tools.domain.deployment import (
    PRODUCTION_APPLICATION_VERSION,
    ProductionConfigurationError,
    StartupValidationOutcome,
    StartupValidationReport,
)
from musimack_tools.domain.security import (
    SECURITY_VERSION,
    AuthenticationFailureReason,
    AuthenticationOutcome,
    CallerIdentity,
    CorrelationConfiguration,
    CredentialSourceConfiguration,
    InternalAuthenticationConfiguration,
    SecurityReadinessReport,
    SecurityReadinessState,
)
from musimack_tools.security.correlation import valid_correlation_id


def test_security_and_production_versions_are_exact() -> None:
    assert SECURITY_VERSION == "seo-toolkit-security-v1"
    assert PRODUCTION_APPLICATION_VERSION == "seo-toolkit-production-app-v1"


def test_authentication_enums_are_stable() -> None:
    assert {item.value for item in AuthenticationOutcome} == {"allowed", "denied", "unavailable"}
    assert {item.value for item in AuthenticationFailureReason} == {
        "authentication_required",
        "authentication_failed",
        "trusted_network_required",
        "security_configuration_unavailable",
        "invalid_forwarded_header",
        "internal_api_disabled",
    }


def test_domain_records_are_immutable() -> None:
    identity = CallerIdentity("internal-operator")
    with pytest.raises(FrozenInstanceError):
        identity.credential_id = "changed"  # type: ignore[misc]
    correlation = CorrelationConfiguration()
    assert correlation.header_name == "X-Request-ID"
    assert correlation.maximum_length == 64
    authentication = InternalAuthenticationConfiguration(
        enabled=True,
        credential_source=CredentialSourceConfiguration(
            "internal-operator", credential_configured=True
        ),
    )
    assert authentication.credential_source.credential_configured


def test_readiness_mapping_is_immutable() -> None:
    source = {"authentication": "ready"}
    report = SecurityReadinessReport(SecurityReadinessState.READY, source)
    source["authentication"] = "changed"
    assert report.checks["authentication"] == "ready"
    with pytest.raises(TypeError):
        report.checks["authentication"] = "changed"  # type: ignore[index]


def test_production_configuration_error_is_safe() -> None:
    error = ProductionConfigurationError(StartupValidationReport(StartupValidationOutcome.INVALID))
    assert str(error) == "The production application configuration is invalid."


@pytest.mark.parametrize("value", ["é", "bad id", "../path", "line\nbreak"])
def test_correlation_validation_rejects_nonascii_or_unsafe_values(value: str) -> None:
    assert not valid_correlation_id(value)
