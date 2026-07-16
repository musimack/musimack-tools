"""Fail-closed startup validation and bounded security-readiness reporting."""

from __future__ import annotations

from typing import TYPE_CHECKING

from musimack_tools.domain.api import INTERNAL_API_PREFIX, INTERNAL_API_VERSION
from musimack_tools.domain.authentication import AuthenticationMode
from musimack_tools.domain.deployment import (
    PRODUCTION_APPLICATION_VERSION,
    StartupValidationIssue,
    StartupValidationOutcome,
    StartupValidationReport,
)
from musimack_tools.domain.security import (
    SECURITY_VERSION,
    SecurityReadinessReport,
    SecurityReadinessState,
)

if TYPE_CHECKING:
    from musimack_tools.api.dependencies import InternalApiApplication
    from musimack_tools.deployment.settings import ProductionSettings

_MAXIMUM_CREDENTIAL_LENGTH = 512


def validate_production_startup(  # noqa: C901, PLR0913 - explicit version boundaries.
    settings: ProductionSettings,
    service: InternalApiApplication | None,
    *,
    security_version: str = SECURITY_VERSION,
    production_version: str = PRODUCTION_APPLICATION_VERSION,
    api_version: str = INTERNAL_API_VERSION,
    route_prefix: str = INTERNAL_API_PREFIX,
) -> StartupValidationReport:
    issues: list[StartupValidationIssue] = []
    if not settings.enabled:
        issues.append(
            StartupValidationIssue(
                "internal_api_disabled", "Internal API is disabled.", blocking=True
            )
        )
    bearer_required = (
        not settings.authentication_enabled
        or settings.authentication_mode is not AuthenticationMode.USER_SESSION
    )
    if bearer_required and (
        settings.bearer_token is None or not settings.bearer_token.get_secret_value()
    ):
        issues.append(
            StartupValidationIssue(
                "security_credential_missing",
                "Internal authentication is unavailable.",
                blocking=True,
            )
        )
    elif (
        settings.bearer_token is not None
        and len(settings.bearer_token.get_secret_value()) > _MAXIMUM_CREDENTIAL_LENGTH
    ):
        issues.append(
            StartupValidationIssue(
                "security_credential_invalid",
                "Internal authentication is unavailable.",
                blocking=True,
            )
        )
    if service is None:
        issues.append(
            StartupValidationIssue(
                "application_service_missing",
                "The internal application service is unavailable.",
                blocking=True,
            )
        )
    versions = (
        (api_version, INTERNAL_API_VERSION, "internal_api_version_invalid"),
        (route_prefix, INTERNAL_API_PREFIX, "internal_api_prefix_invalid"),
        (security_version, SECURITY_VERSION, "security_version_invalid"),
        (production_version, PRODUCTION_APPLICATION_VERSION, "production_version_invalid"),
    )
    for actual, expected, code in versions:
        if actual != expected:
            issues.append(
                StartupValidationIssue(code, "A component version is unsupported.", blocking=True)
            )
    if not settings.access_logging:
        issues.append(
            StartupValidationIssue(
                "access_logging_disabled",
                "Internal access logging is explicitly disabled.",
                blocking=False,
            )
        )
    if not settings.security_headers:
        issues.append(
            StartupValidationIssue(
                "security_headers_disabled",
                "Internal security headers are explicitly disabled.",
                blocking=False,
            )
        )
    if any(issue.blocking for issue in issues):
        outcome = StartupValidationOutcome.INVALID
    elif issues:
        outcome = StartupValidationOutcome.DEGRADED
    else:
        outcome = StartupValidationOutcome.VALID
    return StartupValidationReport(outcome, tuple(issues))


def security_readiness(settings: ProductionSettings) -> SecurityReadinessReport:
    authentication_ready = settings.enabled and (
        settings.bearer_token is not None
        or (
            settings.authentication_enabled
            and settings.authentication_mode is AuthenticationMode.USER_SESSION
        )
    )
    checks = {
        "security_configuration": "ready",
        "authentication": "ready" if authentication_ready else "not_ready",
        "internal_api": "enabled" if settings.enabled else "disabled",
        "trusted_proxy_policy": "ready",
        "trusted_network_policy": "ready",
        "correlation": "ready",
        "access_logging": "enabled" if settings.access_logging else "disabled",
        "cors": "enabled" if settings.cors_enabled else "disabled",
        "security_headers": "enabled" if settings.security_headers else "disabled",
        "production_application_version": PRODUCTION_APPLICATION_VERSION,
    }
    state = (
        SecurityReadinessState.NOT_READY
        if not authentication_ready
        else SecurityReadinessState.DEGRADED
        if not settings.access_logging or not settings.security_headers
        else SecurityReadinessState.READY
    )
    return SecurityReadinessReport(state, checks)
