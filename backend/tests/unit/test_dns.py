"""Deterministic tests for the injectable system DNS boundary."""

import asyncio
import socket
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence

from musimack_tools.crawl.dns import DnsResolutionError, SystemAsyncResolver
from musimack_tools.domain.fetching import FetchFailureCode

_SYNTHETIC_DNS_ERROR = "synthetic failure"


class _FakeLoop:
    def __init__(self, answers: Sequence[tuple[object, ...]]) -> None:
        self.answers = answers

    async def getaddrinfo(self, *args: object, **kwargs: object) -> list[tuple[object, ...]]:
        del args, kwargs
        return [tuple(answer) for answer in self.answers]


def test_system_resolver_deduplicates_ipv4_and_ipv6(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800:220:1::1", 0)),
    ]
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: _FakeLoop(answers))

    evidence = asyncio.run(SystemAsyncResolver().resolve("example.test", maximum_answers=4))

    assert evidence.hostname == "example.test"
    assert evidence.addresses == ("93.184.216.34", "2606:2800:220:1::1")


def test_system_resolver_enforces_answer_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.35", 0)),
    ]
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: _FakeLoop(answers))

    with pytest.raises(DnsResolutionError) as captured:
        asyncio.run(SystemAsyncResolver().resolve("example.test", maximum_answers=1))

    assert captured.value.code is FetchFailureCode.DNS_ANSWER_LIMIT_EXCEEDED


def test_system_resolver_maps_resolution_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailingLoop:
        async def getaddrinfo(self, *args: object, **kwargs: object) -> list[tuple[object, ...]]:
            del args, kwargs
            raise socket.gaierror(_SYNTHETIC_DNS_ERROR)

    monkeypatch.setattr(asyncio, "get_running_loop", _FailingLoop)

    with pytest.raises(DnsResolutionError) as captured:
        asyncio.run(SystemAsyncResolver().resolve("missing.test", maximum_answers=4))

    assert captured.value.code is FetchFailureCode.DNS_RESOLUTION_FAILED
    assert captured.value.exception_type == "gaierror"
