"""Validated URL and crawl-scope domain values."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Self

MAX_PORT = 65_535


class UrlErrorCode(StrEnum):
    """Stable error codes produced while validating and normalizing URLs."""

    EMPTY_URL = "empty_url"
    MISSING_SCHEME = "missing_scheme"
    UNSUPPORTED_SCHEME = "unsupported_scheme"
    MISSING_HOSTNAME = "missing_hostname"
    EMBEDDED_CREDENTIALS = "embedded_credentials"
    INVALID_HOSTNAME = "invalid_hostname"
    INVALID_PORT = "invalid_port"
    INVALID_PERCENT_ENCODING = "invalid_percent_encoding"
    INVALID_CHARACTER = "invalid_character"
    INVALID_URL = "invalid_url"


class UrlNormalizationError(ValueError):
    """A URL validation failure with a stable machine-readable code."""

    def __init__(self, code: UrlErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


_NORMALIZED_URL_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class NormalizedUrl:
    """An absolute URL that can only be constructed by the normalization boundary."""

    original: str
    normalized: str
    scheme: str
    hostname: str
    effective_port: int
    origin: str

    def __init__(  # noqa: PLR0913 - explicit fields protect the validated value boundary.
        self,
        *,
        original: str,
        normalized: str,
        scheme: str,
        hostname: str,
        effective_port: int,
        origin: str,
        _token: object,
    ) -> None:
        if _token is not _NORMALIZED_URL_TOKEN:
            message = "NormalizedUrl values must be created by normalize_url()"
            raise TypeError(message)
        object.__setattr__(self, "original", original)
        object.__setattr__(self, "normalized", normalized)
        object.__setattr__(self, "scheme", scheme)
        object.__setattr__(self, "hostname", hostname)
        object.__setattr__(self, "effective_port", effective_port)
        object.__setattr__(self, "origin", origin)

    @classmethod
    def _from_validated_parts(  # noqa: PLR0913 - mirrors the explicit immutable fields.
        cls,
        *,
        original: str,
        normalized: str,
        scheme: str,
        hostname: str,
        effective_port: int,
        origin: str,
    ) -> Self:
        return cls(
            original=original,
            normalized=normalized,
            scheme=scheme,
            hostname=hostname,
            effective_port=effective_port,
            origin=origin,
            _token=_NORMALIZED_URL_TOKEN,
        )

    def __str__(self) -> str:
        return self.normalized


class ScopeMode(StrEnum):
    """Supported host-matching policies."""

    EXACT_HOST = "exact_host"
    INCLUDE_SUBDOMAINS = "include_subdomains"
    APPROVED_HOSTS = "approved_hosts"


class ScopeReasonCode(StrEnum):
    """Stable evidence codes returned by crawl-scope evaluation."""

    ALLOWED_EXACT_HOST = "allowed_exact_host"
    ALLOWED_SUBDOMAIN = "allowed_subdomain"
    ALLOWED_APPROVED_HOST = "allowed_approved_host"
    DENIED_HOST_MISMATCH = "denied_host_mismatch"
    DENIED_FALSE_SUFFIX_MATCH = "denied_false_suffix_match"
    DENIED_PORT_MISMATCH = "denied_port_mismatch"
    DENIED_SCHEME = "denied_scheme"
    DENIED_INVALID_URL = "denied_invalid_url"


@dataclass(frozen=True, slots=True)
class AllowedOrigin:
    """An allowed scheme/effective-port pair for a crawl scope."""

    scheme: str
    effective_port: int

    def __post_init__(self) -> None:
        if self.scheme not in {"http", "https"}:
            message = "allowed origin scheme must be http or https"
            raise ValueError(message)
        if not 1 <= self.effective_port <= MAX_PORT:
            message = "allowed origin port must be between 1 and 65535"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class CrawlScopePolicy:
    """Validated crawl-scope configuration."""

    seed: NormalizedUrl
    mode: ScopeMode
    approved_hosts: frozenset[str]
    allowed_origins: frozenset[AllowedOrigin]


@dataclass(frozen=True, slots=True)
class CrawlScopeDecision:
    """Structured evidence explaining a scope evaluation."""

    allowed: bool
    reason_code: ScopeReasonCode
    explanation: str
    evaluated_hostname: str | None
    evaluated_effective_port: int | None
    configured_host: str
    configured_origin: str
