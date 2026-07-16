"""Deterministic client-address resolution with explicit trusted proxies."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request

    from musimack_tools.domain.security import TrustedProxyConfiguration


@dataclass(frozen=True, slots=True)
class ClientAddressEvidence:
    address: IPv4Address | IPv6Address | None
    forwarded_header_used: bool
    failure_code: str | None = None


def resolve_client_address(  # noqa: C901, PLR0911, PLR0912 - fail-closed parsing branches.
    request: Request,
    configuration: TrustedProxyConfiguration,
) -> ClientAddressEvidence:
    """Resolve a client IP, trusting X-Forwarded-For only from configured peers."""
    if request.client is None:
        return ClientAddressEvidence(
            address=None,
            forwarded_header_used=False,
            failure_code="client_address_unavailable",
        )
    try:
        direct_peer = _parse_address(request.client.host)
    except ValueError:
        return ClientAddressEvidence(
            address=None, forwarded_header_used=False, failure_code="client_address_invalid"
        )

    forwarded_values = request.headers.getlist("x-forwarded-for")
    if not _in_networks(direct_peer, configuration.networks):
        return ClientAddressEvidence(address=direct_peer, forwarded_header_used=False)
    if not forwarded_values:
        return ClientAddressEvidence(address=direct_peer, forwarded_header_used=False)
    if len(forwarded_values) != 1:
        return ClientAddressEvidence(
            address=None, forwarded_header_used=False, failure_code="forwarded_header_multiple"
        )
    raw = forwarded_values[0]
    if len(raw) > configuration.maximum_forwarded_header_length:
        return ClientAddressEvidence(
            address=None, forwarded_header_used=False, failure_code="forwarded_header_too_long"
        )
    entries = raw.split(",")
    if any(not entry.strip() for entry in entries):
        return ClientAddressEvidence(
            address=None,
            forwarded_header_used=False,
            failure_code="forwarded_address_invalid",
        )
    if not entries or len(entries) > configuration.maximum_forwarded_hops:
        return ClientAddressEvidence(
            address=None,
            forwarded_header_used=False,
            failure_code="forwarded_hop_limit_exceeded",
        )
    addresses: list[IPv4Address | IPv6Address] = []
    for entry in entries:
        value = entry.strip()
        if not value or "%" in value:
            return ClientAddressEvidence(
                address=None,
                forwarded_header_used=False,
                failure_code="forwarded_address_invalid",
            )
        try:
            addresses.append(_parse_address(value))
        except ValueError:
            return ClientAddressEvidence(
                address=None,
                forwarded_header_used=False,
                failure_code="forwarded_address_invalid",
            )
    for address in addresses:
        if not _in_networks(address, configuration.networks):
            return ClientAddressEvidence(address=address, forwarded_header_used=True)
    return ClientAddressEvidence(address=addresses[0], forwarded_header_used=True)


def address_is_trusted(
    address: IPv4Address | IPv6Address,
    networks: tuple[IPv4Network | IPv6Network, ...],
) -> bool:
    """Return whether an address belongs to an explicitly configured network."""
    return _in_networks(address, networks)


def _parse_address(value: str) -> IPv4Address | IPv6Address:
    parsed = ip_address(value)
    if not isinstance(parsed, (IPv4Address, IPv6Address)):
        raise TypeError
    return parsed


def _in_networks(
    address: IPv4Address | IPv6Address,
    networks: tuple[IPv4Network | IPv6Network, ...],
) -> bool:
    for network in networks:
        try:
            if address in network:
                return True
        except TypeError:
            continue
    return False
