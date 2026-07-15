"""Regression tests for the suite's external-network safeguard."""

import socket

import pytest


def test_dns_resolution_is_blocked() -> None:
    with pytest.raises(AssertionError, match="network-free"):
        socket.getaddrinfo("example.com", 443)


def test_non_loopback_connection_is_blocked_before_os_access() -> None:
    with socket.socket() as test_socket, pytest.raises(AssertionError, match="network-free"):
        test_socket.connect(("192.0.2.1", 443))
