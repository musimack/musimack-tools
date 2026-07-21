"""Typed contracts for safe single-URL fetching and redirect evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from musimack_tools.domain.urls import NormalizedUrl

OUTBOUND_DESTINATION_POLICY_VERSION = "seo-toolkit-outbound-destination-policy-v1"
CRAWLER_USER_AGENT = "Musimack SEO Toolkit/1.0"


class FetchOutcome(StrEnum):
    """Top-level result of a fetch operation."""

    SUCCESS = "success"
    FAILURE = "failure"


class FetchFailureCode(StrEnum):
    """Stable machine-readable safe-fetch failure codes."""

    UNSUPPORTED_SCHEME = "unsupported_scheme"
    CREDENTIALS_NOT_ALLOWED = "credentials_not_allowed"
    INVALID_HOSTNAME = "invalid_hostname"
    IP_LITERAL_NOT_ALLOWED = "ip_literal_not_allowed"
    UNSAFE_HOSTNAME = "unsafe_hostname"
    DNS_RESOLUTION_FAILED = "dns_resolution_failed"
    DNS_RESOLUTION_TIMEOUT = "dns_resolution_timeout"
    DNS_ANSWER_LIMIT_EXCEEDED = "dns_answer_limit_exceeded"
    UNSAFE_RESOLVED_ADDRESS = "unsafe_resolved_address"
    MIXED_SAFE_UNSAFE_DNS_ANSWERS = "mixed_safe_unsafe_dns_answers"
    PORT_NOT_ALLOWED = "port_not_allowed"
    SCOPE_DENIED = "scope_denied"
    CONNECT_TIMEOUT = "connect_timeout"
    READ_TIMEOUT = "read_timeout"
    WRITE_TIMEOUT = "write_timeout"
    POOL_TIMEOUT = "pool_timeout"
    REQUEST_DEADLINE_EXCEEDED = "request_deadline_exceeded"
    TRANSPORT_ERROR = "transport_error"
    REDIRECT_MISSING_LOCATION = "redirect_missing_location"
    REDIRECT_INVALID_LOCATION = "redirect_invalid_location"
    REDIRECT_LOOP = "redirect_loop"
    REDIRECT_LIMIT_EXCEEDED = "redirect_limit_exceeded"
    REDIRECT_SCOPE_DENIED = "redirect_scope_denied"
    REDIRECT_UNSAFE_DESTINATION = "redirect_unsafe_destination"
    RESPONSE_TOO_LARGE = "response_too_large"
    RESPONSE_HEADERS_TOO_LARGE = "response_headers_too_large"
    INVALID_CONTENT_LENGTH = "invalid_content_length"


@dataclass(frozen=True, slots=True)
class DnsEvidence:
    """Bounded DNS result used to support a safety decision."""

    hostname: str
    addresses: tuple[str, ...]

    @property
    def answer_count(self) -> int:
        return len(self.addresses)


@dataclass(frozen=True, slots=True)
class NetworkSafetyDecision:
    """Independent network-safety approval or denial."""

    allowed: bool
    failure_code: FetchFailureCode | None
    explanation: str
    hostname: str
    effective_port: int
    dns_evidence: DnsEvidence | None = None
    selected_address: str | None = None
    internal_exception_type: str | None = None


@dataclass(frozen=True, slots=True)
class FetchRequest:
    """A single normalized URL fetch request."""

    url: NormalizedUrl
    correlation_id: str | None = None
    maximum_response_bytes: int | None = None
    maximum_redirect_hops: int | None = None
    maximum_duration_seconds: float | None = None
    user_agent: str | None = None


@dataclass(frozen=True, slots=True)
class ResponseHeaders:
    """Response headers retained for later SEO modules without interpretation."""

    content_type: str | None = None
    content_length: str | None = None
    location: str | None = None
    x_robots_tag: tuple[str, ...] = ()
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True, slots=True)
class RedirectHop:
    """Evidence for one observed redirect response and its evaluated target."""

    source_url: str
    status_code: int
    raw_location: str | None
    destination_url: str | None
    allowed: bool
    failure_code: FetchFailureCode | None
    explanation: str


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Complete bounded evidence returned by the safe-fetch boundary."""

    requested_url: str
    final_url: str
    outcome: FetchOutcome
    status_code: int | None
    headers: ResponseHeaders | None
    content_type: str | None
    declared_content_length: int | None
    actual_bytes_read: int
    body_truncated: bool
    redirect_chain: tuple[RedirectHop, ...]
    request_duration_seconds: float
    dns_evidence: tuple[DnsEvidence, ...]
    failure_code: FetchFailureCode | None
    failure_explanation: str | None
    body: bytes | None
    internal_exception_type: str | None = None
    attempt_count: int = 1
