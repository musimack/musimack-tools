"""Strict bearer parsing and fail-closed production access verification."""

from __future__ import annotations

import hmac
import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from musimack_tools.domain.api import (
    AccessDecision,
    AccessDenialReason,
    AccessOutcome,
    InternalCallerContext,
)
from musimack_tools.security.client_address import address_is_trusted, resolve_client_address

if TYPE_CHECKING:
    from fastapi import Request

    from musimack_tools.domain.security import (
        TrustedNetworkConfiguration,
        TrustedProxyConfiguration,
    )

_BEARER_PATTERN = re.compile(r"^Bearer ([\x21-\x7e]+)$")
CredentialComparator = Callable[[str, str], bool]


def extract_bearer_credential(header_value: str | None, *, maximum_length: int = 512) -> str | None:
    """Return a strict ASCII bearer value, without including it in failures."""
    if header_value is None or len(header_value) > maximum_length + 7:
        return None
    match = _BEARER_PATTERN.fullmatch(header_value)
    if match is None:
        return None
    credential = match.group(1)
    if len(credential) > maximum_length or any(character.isspace() for character in credential):
        return None
    return credential


def constant_time_matches(provided: str, expected: str) -> bool:
    """Compare credential bytes with the standard-library constant-time primitive."""
    try:
        return hmac.compare_digest(provided.encode("ascii"), expected.encode("ascii"))
    except UnicodeEncodeError:
        return False


class BearerAccessVerifier:
    """Production verifier compatible with the internal API access protocol."""

    def __init__(  # noqa: PLR0913 - explicit immutable policy dependencies.
        self,
        *,
        enabled: bool,
        expected_credential: str,
        credential_id: str,
        trusted_networks: TrustedNetworkConfiguration,
        trusted_proxies: TrustedProxyConfiguration,
        comparator: CredentialComparator = constant_time_matches,
    ) -> None:
        self._enabled = enabled
        self._expected_credential = expected_credential
        self._credential_id = credential_id
        self._trusted_networks = trusted_networks
        self._trusted_proxies = trusted_proxies
        self._comparator = comparator

    async def verify(  # noqa: PLR0911 - each fail-closed branch returns bounded evidence.
        self, request: Request
    ) -> AccessDecision:
        """Authenticate, resolve the client address, then apply the network allowlist."""
        request.state.authentication_outcome = "denied"
        request.state.caller_id = None
        request.state.client_address = None
        if not self._enabled:
            return self._deny(AccessDenialReason.INTERNAL_API_DISABLED, request)
        header_values = request.headers.getlist("authorization")
        if len(header_values) != 1:
            return self._deny(AccessDenialReason.AUTHENTICATION_REQUIRED, request)
        credential = extract_bearer_credential(header_values[0])
        try:
            credential_matches = credential is not None and self._comparator(
                credential, self._expected_credential
            )
        except Exception:  # noqa: BLE001 - verifier failures must become typed unavailability.
            request.state.authentication_outcome = "unavailable"
            return AccessDecision(
                AccessOutcome.UNAVAILABLE,
                AccessDenialReason.SECURITY_CONFIGURATION_UNAVAILABLE,
            )
        if not credential_matches:
            return self._deny(AccessDenialReason.AUTHENTICATION_FAILED, request)

        evidence = resolve_client_address(request, self._trusted_proxies)
        if evidence.failure_code is not None or evidence.address is None:
            return self._deny(AccessDenialReason.INVALID_FORWARDED_HEADER, request)
        client_address = str(evidence.address)
        request.state.client_address = client_address
        if self._trusted_networks.networks and not address_is_trusted(
            evidence.address, self._trusted_networks.networks
        ):
            return self._deny(AccessDenialReason.TRUSTED_NETWORK_REQUIRED, request)

        request.state.authentication_outcome = "allowed"
        request.state.caller_id = self._credential_id
        return AccessDecision(
            AccessOutcome.ALLOWED,
            caller=InternalCallerContext(self._credential_id),
        )

    @staticmethod
    def _deny(reason: AccessDenialReason, request: Request) -> AccessDecision:
        request.state.authentication_failure_reason = reason.value
        return AccessDecision(AccessOutcome.DENIED, reason)
