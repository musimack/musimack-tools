"""Fail-closed access-verifier boundary for explicitly mounted internal routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from musimack_tools.domain.api import (
    AccessDecision,
    AccessDenialReason,
    AccessOutcome,
)

if TYPE_CHECKING:
    from fastapi import Request


class InternalAccessVerifier(Protocol):
    async def verify(self, request: Request) -> AccessDecision:
        """Return a bounded decision without exposing credential evidence."""


class DenyAllAccessVerifier:
    """Safe fallback used whenever no deployment verifier was injected."""

    async def verify(self, request: Request) -> AccessDecision:
        del request
        return AccessDecision(
            AccessOutcome.DENIED,
            AccessDenialReason.ACCESS_NOT_CONFIGURED,
        )
