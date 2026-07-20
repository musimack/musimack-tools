"""Cookie-session and explicit hybrid internal access verification."""

from __future__ import annotations

from typing import TYPE_CHECKING

from musimack_tools.authentication.service import AuthenticationError, AuthenticationService
from musimack_tools.domain.api import (
    AccessDecision,
    AccessDenialReason,
    AccessOutcome,
    InternalCallerContext,
)
from musimack_tools.domain.authentication import AuthenticationConfiguration, AuthenticationMode
from musimack_tools.domain.security import TrustedNetworkConfiguration, TrustedProxyConfiguration
from musimack_tools.security.client_address import address_is_trusted, resolve_client_address

if TYPE_CHECKING:
    from fastapi import Request

    from musimack_tools.api.access import InternalAccessVerifier

_MAXIMUM_SESSION_COOKIE_CANDIDATES = 8


class SessionAccessVerifier:
    def __init__(
        self,
        service: AuthenticationService,
        configuration: AuthenticationConfiguration,
        *,
        bearer_verifier: InternalAccessVerifier | None = None,
        trusted_networks: TrustedNetworkConfiguration | None = None,
        trusted_proxies: TrustedProxyConfiguration | None = None,
    ) -> None:
        self._service = service
        self._configuration = configuration
        self._bearer = bearer_verifier
        self._trusted_networks = trusted_networks or TrustedNetworkConfiguration()
        self._trusted_proxies = trusted_proxies or TrustedProxyConfiguration()

    async def verify_sign_in_network(self, request: Request) -> AccessDecision:
        if not self._trusted_networks.networks and not self._trusted_proxies.networks:
            return AccessDecision(AccessOutcome.ALLOWED, caller=InternalCallerContext())
        evidence = resolve_client_address(request, self._trusted_proxies)
        if evidence.failure_code is not None or evidence.address is None:
            return AccessDecision(AccessOutcome.DENIED, AccessDenialReason.INVALID_FORWARDED_HEADER)
        if self._trusted_networks.networks and not address_is_trusted(
            evidence.address, self._trusted_networks.networks
        ):
            return AccessDecision(AccessOutcome.DENIED, AccessDenialReason.TRUSTED_NETWORK_REQUIRED)
        return AccessDecision(AccessOutcome.ALLOWED, caller=InternalCallerContext())

    async def verify(self, request: Request) -> AccessDecision:
        tokens = _session_cookie_tokens(request, self._configuration.session_cookie_name)
        if tokens:
            if len(tokens) > _MAXIMUM_SESSION_COOKIE_CANDIDATES:
                return AccessDecision(
                    AccessOutcome.DENIED, AccessDenialReason.AUTHENTICATION_FAILED
                )
            valid_tokens: list[str] = []
            for candidate in tokens:
                try:
                    self._service.authenticate_session(candidate)
                except AuthenticationError:
                    continue
                valid_tokens.append(candidate)
            if len(valid_tokens) != 1:
                return AccessDecision(
                    AccessOutcome.DENIED, AccessDenialReason.AUTHENTICATION_FAILED
                )
            token = valid_tokens[0]
            try:
                issued = self._service.authenticate_and_rotate(token)
            except AuthenticationError:
                return AccessDecision(
                    AccessOutcome.DENIED, AccessDenialReason.AUTHENTICATION_FAILED
                )
            principal = issued.principal
            request.state.authenticated_principal = principal
            request.state.authenticated_session_token = issued.raw_token
            if issued.raw_token != token:
                request.state.session_replacement_token = issued.raw_token
            request.state.authentication_outcome = "allowed"
            request.state.caller_id = principal.user_id
            return AccessDecision(
                AccessOutcome.ALLOWED, caller=InternalCallerContext(principal.user_id)
            )
        if (
            self._configuration.mode is AuthenticationMode.HYBRID
            and self._configuration.shared_bearer_compatibility_enabled
            and self._bearer is not None
        ):
            decision = await self._bearer.verify(request)
            if decision.outcome is AccessOutcome.ALLOWED:
                self._service.record_shared_bearer_use()
            return decision
        return AccessDecision(AccessOutcome.DENIED, AccessDenialReason.AUTHENTICATION_REQUIRED)

    def record_authorization_denied(self, principal: object, permission: str) -> None:
        from musimack_tools.domain.authentication import AuthenticatedPrincipal  # noqa: PLC0415

        if isinstance(principal, AuthenticatedPrincipal):
            self._service.record_authorization_denied(principal, permission)


def _session_cookie_tokens(request: Request, cookie_name: str) -> tuple[str, ...]:
    """Return bounded distinct same-name values without framework order collapse."""
    tokens: list[str] = []
    seen: set[str] = set()
    candidate_count = 0
    for header_name, header_value in request.scope.get("headers", ()):
        if header_name.lower() != b"cookie":
            continue
        for segment in header_value.decode("latin-1").split(";"):
            name, separator, value = segment.strip().partition("=")
            token = value.strip()
            if separator and name == cookie_name:
                candidate_count += 1
                if candidate_count > _MAXIMUM_SESSION_COOKIE_CANDIDATES:
                    return (token,) * (_MAXIMUM_SESSION_COOKIE_CANDIDATES + 1)
            if separator and name == cookie_name and token not in seen:
                seen.add(token)
                tokens.append(token)
    return tuple(tokens)
