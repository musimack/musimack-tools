"""Test safeguards shared by every backend test."""

import socket
from ipaddress import ip_address
from typing import TYPE_CHECKING, NoReturn

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

_NETWORK_ERROR = "Automated tests must remain network-free"


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Block DNS and non-loopback connections while allowing local event-loop plumbing."""

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        raise AssertionError(_NETWORK_ERROR)

    def guarded_connect(
        instance: socket.socket,
        address: tuple[str, int] | tuple[str, int, int, int],
    ) -> None:
        if not ip_address(address[0]).is_loopback:
            blocked()
        original_connect(instance, address)

    def guarded_connect_ex(
        instance: socket.socket,
        address: tuple[str, int] | tuple[str, int, int, int],
    ) -> int:
        if not ip_address(address[0]).is_loopback:
            blocked()
        return original_connect_ex(instance, address)

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    yield
