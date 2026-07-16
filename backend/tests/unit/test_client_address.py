"""Trusted proxy, forwarded-header, and network-selection contracts."""

from ipaddress import ip_address, ip_network

import pytest
from starlette.requests import Request

from musimack_tools.domain.security import TrustedProxyConfiguration
from musimack_tools.security.client_address import address_is_trusted, resolve_client_address


def _request(
    *,
    client: str = "203.0.113.20",
    forwarded: tuple[str, ...] = (),
) -> Request:
    headers = [(b"x-forwarded-for", value.encode("ascii")) for value in forwarded]
    return Request(
        {"type": "http", "method": "GET", "path": "/", "headers": headers, "client": (client, 1)}
    )


def _configuration(
    *networks: str,
    hops: int = 5,
    length: int = 1_024,
) -> TrustedProxyConfiguration:
    return TrustedProxyConfiguration(
        tuple(ip_network(value) for value in networks),
        maximum_forwarded_hops=hops,
        maximum_forwarded_header_length=length,
    )


def test_direct_peer_is_authoritative_without_proxy_trust() -> None:
    evidence = resolve_client_address(
        _request(forwarded=("198.51.100.2",)), TrustedProxyConfiguration()
    )
    assert str(evidence.address) == "203.0.113.20"
    assert not evidence.forwarded_header_used


def test_untrusted_peer_spoofed_forwarding_is_ignored() -> None:
    evidence = resolve_client_address(
        _request(client="203.0.113.20", forwarded=("10.0.0.1",)),
        _configuration("10.0.0.0/8"),
    )
    assert str(evidence.address) == "203.0.113.20"
    assert evidence.failure_code is None


@pytest.mark.parametrize(
    ("forwarded", "expected"),
    [
        (("198.51.100.4",), "198.51.100.4"),
        (("198.51.100.4, 10.1.1.1",), "198.51.100.4"),
        (("10.1.1.1, 10.2.2.2",), "10.1.1.1"),
        (("2001:db8::10",), "2001:db8::10"),
    ],
)
def test_trusted_proxy_selects_first_nonproxy_or_leftmost(
    forwarded: tuple[str, ...], expected: str
) -> None:
    evidence = resolve_client_address(
        _request(client="10.0.0.8", forwarded=forwarded),
        _configuration("10.0.0.0/8"),
    )
    assert str(evidence.address) == expected
    assert evidence.forwarded_header_used


@pytest.mark.parametrize(
    ("forwarded", "failure"),
    [
        (("198.51.100.1", "198.51.100.2"), "forwarded_header_multiple"),
        (("198.51.100.1,,10.0.0.1",), "forwarded_address_invalid"),
        (("not-an-ip",), "forwarded_address_invalid"),
        (("fe80::1%eth0",), "forwarded_address_invalid"),
        (("1.1.1.1,2.2.2.2,3.3.3.3",), "forwarded_hop_limit_exceeded"),
    ],
)
def test_malformed_or_excessive_forwarding_fails_closed(
    forwarded: tuple[str, ...], failure: str
) -> None:
    evidence = resolve_client_address(
        _request(client="10.0.0.8", forwarded=forwarded),
        _configuration("10.0.0.0/8", hops=2),
    )
    assert evidence.address is None
    assert evidence.failure_code == failure


def test_forwarded_header_length_is_bounded() -> None:
    evidence = resolve_client_address(
        _request(client="10.0.0.8", forwarded=("1" * 65,)),
        _configuration("10.0.0.0/8", length=64),
    )
    assert evidence.failure_code == "forwarded_header_too_long"


@pytest.mark.parametrize(
    ("address", "network", "trusted"),
    [
        ("10.1.2.3", "10.0.0.0/8", True),
        ("192.168.1.1", "10.0.0.0/8", False),
        ("2001:db8::1", "2001:db8::/32", True),
        ("::1", "2001:db8::/32", False),
    ],
)
def test_trusted_network_supports_ipv4_and_ipv6(
    address: str,
    network: str,
    trusted: bool,  # noqa: FBT001
) -> None:
    assert address_is_trusted(ip_address(address), (ip_network(network),)) is trusted
