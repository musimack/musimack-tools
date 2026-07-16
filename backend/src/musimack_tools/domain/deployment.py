"""Immutable production-composition and startup-validation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from musimack_tools.domain.security import SECURITY_VERSION

if TYPE_CHECKING:
    from musimack_tools.domain.security import (
        AccessLogConfiguration,
        CorrelationConfiguration,
        CorsConfiguration,
        InternalAuthenticationConfiguration,
        SecurityHeaderConfiguration,
        TrustedNetworkConfiguration,
        TrustedProxyConfiguration,
    )

PRODUCTION_APPLICATION_VERSION = "seo-toolkit-production-app-v1"


class StartupValidationOutcome(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class StartupValidationIssue:
    code: str
    message: str
    blocking: bool


@dataclass(frozen=True, slots=True)
class StartupValidationReport:
    outcome: StartupValidationOutcome
    issues: tuple[StartupValidationIssue, ...] = ()
    production_application_version: str = PRODUCTION_APPLICATION_VERSION


@dataclass(frozen=True, slots=True)
class ProductionApplicationConfiguration:
    authentication: InternalAuthenticationConfiguration
    include_openapi: bool
    trusted_networks: TrustedNetworkConfiguration
    trusted_proxies: TrustedProxyConfiguration
    cors: CorsConfiguration
    correlation: CorrelationConfiguration
    security_headers: SecurityHeaderConfiguration
    access_logging: AccessLogConfiguration
    security_version: str = SECURITY_VERSION
    production_application_version: str = PRODUCTION_APPLICATION_VERSION


@dataclass(frozen=True, slots=True)
class ProductionConfigurationError(Exception):
    report: StartupValidationReport

    def __str__(self) -> str:
        return "The production application configuration is invalid."
