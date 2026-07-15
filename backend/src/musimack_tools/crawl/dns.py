"""Injectable asynchronous DNS resolution boundary."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Protocol

from musimack_tools.domain.fetching import DnsEvidence, FetchFailureCode


class DnsResolutionError(Exception):
    """Internal resolver failure mapped to a stable public failure code."""

    def __init__(
        self,
        code: FetchFailureCode,
        explanation: str,
        *,
        exception_type: str | None = None,
    ) -> None:
        super().__init__(explanation)
        self.code = code
        self.explanation = explanation
        self.exception_type = exception_type


class AsyncResolver(Protocol):
    """Resolver interface that tests can replace without public DNS access."""

    async def resolve(self, hostname: str, *, maximum_answers: int) -> DnsEvidence:
        """Resolve and return a bounded, deduplicated address set."""
        ...


class SystemAsyncResolver:
    """Production resolver backed by the event loop's system resolver."""

    async def resolve(self, hostname: str, *, maximum_answers: int) -> DnsEvidence:
        try:
            answers = await asyncio.get_running_loop().getaddrinfo(
                hostname,
                None,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            )
        except (OSError, UnicodeError) as error:
            raise DnsResolutionError(
                FetchFailureCode.DNS_RESOLUTION_FAILED,
                "The destination hostname could not be resolved",
                exception_type=type(error).__name__,
            ) from error

        addresses: list[str] = []
        seen: set[str] = set()
        for answer in answers:
            raw_address = answer[4][0]
            try:
                address = ipaddress.ip_address(raw_address).compressed.lower()
            except ValueError as error:
                raise DnsResolutionError(
                    FetchFailureCode.DNS_RESOLUTION_FAILED,
                    "The resolver returned an invalid address",
                    exception_type=type(error).__name__,
                ) from error
            if address in seen:
                continue
            seen.add(address)
            addresses.append(address)
            if len(addresses) > maximum_answers:
                raise DnsResolutionError(
                    FetchFailureCode.DNS_ANSWER_LIMIT_EXCEEDED,
                    "The destination returned more DNS answers than the configured limit",
                )

        if not addresses:
            raise DnsResolutionError(
                FetchFailureCode.DNS_RESOLUTION_FAILED,
                "The destination hostname resolved to no usable addresses",
            )
        return DnsEvidence(hostname=hostname, addresses=tuple(addresses))
