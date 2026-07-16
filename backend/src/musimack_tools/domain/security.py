"""Immutable contracts for internal transport security and authentication."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from ipaddress import IPv4Network, IPv6Network

SECURITY_VERSION = "seo-toolkit-security-v1"


class AuthenticationOutcome(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


class AuthenticationFailureReason(StrEnum):
    AUTHENTICATION_REQUIRED = "authentication_required"
    AUTHENTICATION_FAILED = "authentication_failed"
    TRUSTED_NETWORK_REQUIRED = "trusted_network_required"
    SECURITY_CONFIGURATION_UNAVAILABLE = "security_configuration_unavailable"
    INVALID_FORWARDED_HEADER = "invalid_forwarded_header"
    INTERNAL_API_DISABLED = "internal_api_disabled"


class SecurityReadinessState(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    NOT_READY = "not_ready"


@dataclass(frozen=True, slots=True)
class CallerIdentity:
    credential_id: str


@dataclass(frozen=True, slots=True)
class CredentialSourceConfiguration:
    credential_id: str
    credential_configured: bool


@dataclass(frozen=True, slots=True)
class InternalAuthenticationConfiguration:
    enabled: bool
    credential_source: CredentialSourceConfiguration


@dataclass(frozen=True, slots=True)
class AuthenticationDecision:
    outcome: AuthenticationOutcome
    reason: AuthenticationFailureReason | None = None
    caller: CallerIdentity | None = None
    client_address: str | None = None
    security_version: str = SECURITY_VERSION


@dataclass(frozen=True, slots=True)
class SecurityWarning:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class SecurityFailure:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class TrustedNetworkConfiguration:
    networks: tuple[IPv4Network | IPv6Network, ...] = ()


@dataclass(frozen=True, slots=True)
class TrustedProxyConfiguration:
    networks: tuple[IPv4Network | IPv6Network, ...] = ()
    maximum_forwarded_hops: int = 5
    maximum_forwarded_header_length: int = 1_024


@dataclass(frozen=True, slots=True)
class CorsConfiguration:
    enabled: bool = False
    allowed_origins: tuple[str, ...] = ()
    maximum_age_seconds: int = 600


@dataclass(frozen=True, slots=True)
class CorrelationConfiguration:
    header_name: str = "X-Request-ID"
    maximum_length: int = 64


@dataclass(frozen=True, slots=True)
class SecurityHeaderConfiguration:
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class AccessLogConfiguration:
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class SecurityReadinessReport:
    state: SecurityReadinessState
    checks: Mapping[str, str]
    security_version: str = SECURITY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "checks", MappingProxyType(dict(self.checks)))
