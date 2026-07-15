"""Destination hostname, address, scheme, and port safety policy."""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from musimack_tools.crawl.dns import AsyncResolver, DnsResolutionError
from musimack_tools.domain.fetching import (
    DnsEvidence,
    FetchFailureCode,
    NetworkSafetyDecision,
)

if TYPE_CHECKING:
    from musimack_tools.core.config import Settings
    from musimack_tools.domain.urls import NormalizedUrl

_UNSAFE_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata",
        "instance-data",
        "metadata.google.internal",
        "metadata.aws.internal",
    }
)
_UNSAFE_HOSTNAME_SUFFIXES = (".localhost", ".local", ".internal", ".home", ".lan")
_SUPPLEMENTAL_UNSAFE_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "100.64.0.0/10",
        "169.254.0.0/16",
        "192.0.2.0/24",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "2001:db8::/32",
        "fc00::/7",
        "fe80::/10",
        "fec0::/10",
    )
)


class DestinationSafetyValidator:
    """Validate a normalized destination independently from crawl scope."""

    def __init__(self, settings: Settings, resolver: AsyncResolver) -> None:
        self._settings = settings
        self._resolver = resolver

    async def validate(self, destination: NormalizedUrl) -> NetworkSafetyDecision:
        defensive_failure = self._validate_url_boundary(destination)
        if defensive_failure is not None:
            return defensive_failure

        try:
            ipaddress.ip_address(destination.hostname)
        except ValueError:
            pass
        else:
            return self._denied(
                destination,
                FetchFailureCode.IP_LITERAL_NOT_ALLOWED,
                "IP-literal destinations are not allowed by the production fetch policy",
            )

        hostname = destination.hostname.rstrip(".").lower()
        if hostname in _UNSAFE_HOSTNAMES or hostname.endswith(_UNSAFE_HOSTNAME_SUFFIXES):
            return self._denied(
                destination,
                FetchFailureCode.UNSAFE_HOSTNAME,
                "The destination hostname belongs to a prohibited local or metadata class",
            )

        try:
            evidence = await self._resolver.resolve(
                destination.hostname,
                maximum_answers=self._settings.fetch_maximum_dns_answers,
            )
        except DnsResolutionError as error:
            return self._denied(
                destination,
                error.code,
                error.explanation,
                internal_exception_type=error.exception_type,
            )

        return self._evaluate_addresses(destination, evidence)

    def _evaluate_addresses(
        self,
        destination: NormalizedUrl,
        evidence: DnsEvidence,
    ) -> NetworkSafetyDecision:
        unsafe = tuple(address for address in evidence.addresses if not is_public_address(address))
        if unsafe and len(unsafe) != len(evidence.addresses):
            return self._denied(
                destination,
                FetchFailureCode.MIXED_SAFE_UNSAFE_DNS_ANSWERS,
                "The hostname resolved to a mixture of public and prohibited addresses",
                dns_evidence=evidence,
            )
        if unsafe:
            return self._denied(
                destination,
                FetchFailureCode.UNSAFE_RESOLVED_ADDRESS,
                "The hostname resolved only to prohibited network addresses",
                dns_evidence=evidence,
            )
        return NetworkSafetyDecision(
            allowed=True,
            failure_code=None,
            explanation="The destination passed scheme, credential, host, port, and address checks",
            hostname=destination.hostname,
            effective_port=destination.effective_port,
            dns_evidence=evidence,
        )

    def _validate_url_boundary(
        self,
        destination: NormalizedUrl,
    ) -> NetworkSafetyDecision | None:
        try:
            parts = urlsplit(destination.normalized)
        except ValueError:
            return self._denied(
                destination,
                FetchFailureCode.INVALID_HOSTNAME,
                "The normalized destination could not be parsed safely",
            )
        if parts.scheme not in {"http", "https"}:
            return self._denied(
                destination,
                FetchFailureCode.UNSUPPORTED_SCHEME,
                "Only HTTP and HTTPS destinations are supported",
            )
        if parts.username is not None or parts.password is not None or "@" in parts.netloc:
            return self._denied(
                destination,
                FetchFailureCode.CREDENTIALS_NOT_ALLOWED,
                "Destination URL credentials are not allowed",
            )
        if parts.hostname is None or parts.hostname.lower() != destination.hostname.lower():
            return self._denied(
                destination,
                FetchFailureCode.INVALID_HOSTNAME,
                "The normalized destination hostname is invalid or inconsistent",
            )
        return self._validate_scheme_and_port(destination)

    def _validate_scheme_and_port(
        self,
        destination: NormalizedUrl,
    ) -> NetworkSafetyDecision | None:
        if destination.scheme == "http" and not self._settings.fetch_http_allowed:
            return self._denied(
                destination,
                FetchFailureCode.UNSUPPORTED_SCHEME,
                "HTTP requests are disabled by configuration",
            )
        if destination.scheme == "https" and not self._settings.fetch_https_allowed:
            return self._denied(
                destination,
                FetchFailureCode.UNSUPPORTED_SCHEME,
                "HTTPS requests are disabled by configuration",
            )
        if destination.effective_port not in self._settings.fetch_permitted_production_ports:
            return self._denied(
                destination,
                FetchFailureCode.PORT_NOT_ALLOWED,
                "The destination effective port is not approved for production requests",
            )
        return None

    @staticmethod
    def _denied(
        destination: NormalizedUrl,
        code: FetchFailureCode,
        explanation: str,
        *,
        dns_evidence: DnsEvidence | None = None,
        internal_exception_type: str | None = None,
    ) -> NetworkSafetyDecision:
        return NetworkSafetyDecision(
            allowed=False,
            failure_code=code,
            explanation=explanation,
            hostname=destination.hostname,
            effective_port=destination.effective_port,
            dns_evidence=dns_evidence,
            internal_exception_type=internal_exception_type,
        )


def is_public_address(value: str) -> bool:
    """Return whether an address is globally routable under the conservative policy."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False

    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return is_public_address(str(address.ipv4_mapped))
    if any(address in network for network in _SUPPLEMENTAL_UNSAFE_NETWORKS):
        return False
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.is_site_local:
        return False
    return address.is_global
