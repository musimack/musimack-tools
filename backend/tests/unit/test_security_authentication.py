"""Strict bearer parsing and constant-time verifier contracts."""

from ipaddress import ip_network

import pytest
from starlette.requests import Request

from musimack_tools.api.dependencies import create_access_dependency
from musimack_tools.domain.api import (
    AccessDenialReason,
    AccessOutcome,
    InternalApiConfiguration,
    InternalApiError,
)
from musimack_tools.domain.security import TrustedNetworkConfiguration, TrustedProxyConfiguration
from musimack_tools.security.authentication import (
    BearerAccessVerifier,
    CredentialComparator,
    constant_time_matches,
    extract_bearer_credential,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Bearer test-token", "test-token"),
        (None, None),
        ("Basic test-token", None),
        ("Bearer", None),
        ("Bearer ", None),
        ("Bearer token extra", None),
        ("Bearer token\tvalue", None),
        ("bearer test-token", None),
        (f"Bearer {'x' * 513}", None),
        ("Bearer tést", None),
    ],
)
def test_bearer_parsing_is_strict(value: str | None, expected: str | None) -> None:
    assert extract_bearer_credential(value) == expected


@pytest.mark.parametrize(
    ("provided", "expected", "matches"),
    [
        ("same", "same", True),
        ("xxxx", "same", False),
        ("short", "longer-value", False),
        ("tést", "tést", False),
    ],
)
def test_constant_time_comparison_contract(
    provided: str,
    expected: str,
    matches: bool,  # noqa: FBT001
) -> None:
    assert constant_time_matches(provided, expected) is matches


def _request(*, authorization: str | None = None, client: str = "203.0.113.9") -> Request:
    headers = [] if authorization is None else [(b"authorization", authorization.encode("ascii"))]
    return Request(
        {"type": "http", "method": "GET", "path": "/", "headers": headers, "client": (client, 1)}
    )


def _request_with_authorization_values(*values: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"authorization", value.encode("ascii")) for value in values],
            "client": ("203.0.113.9", 1),
        }
    )


def _verifier(
    *,
    enabled: bool = True,
    networks: tuple[str, ...] = (),
    comparator: CredentialComparator = constant_time_matches,
) -> BearerAccessVerifier:
    return BearerAccessVerifier(
        enabled=enabled,
        expected_credential="expected-token",
        credential_id="operator-1",
        trusted_networks=TrustedNetworkConfiguration(
            tuple(ip_network(value) for value in networks)
        ),
        trusted_proxies=TrustedProxyConfiguration(),
        comparator=comparator,
    )


@pytest.mark.anyio
async def test_verifier_allows_valid_credential_with_safe_identity() -> None:
    decision = await _verifier().verify(_request(authorization="Bearer expected-token"))
    assert decision.outcome is AccessOutcome.ALLOWED
    assert decision.caller is not None
    assert decision.caller.caller_id == "operator-1"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("authorization", "reason"),
    [
        (None, AccessDenialReason.AUTHENTICATION_REQUIRED),
        ("Basic expected-token", AccessDenialReason.AUTHENTICATION_FAILED),
        ("Bearer incorrect", AccessDenialReason.AUTHENTICATION_FAILED),
    ],
)
async def test_verifier_denies_missing_or_invalid_credentials(
    authorization: str | None, reason: AccessDenialReason
) -> None:
    decision = await _verifier().verify(_request(authorization=authorization))
    assert decision.outcome is AccessOutcome.DENIED
    assert decision.reason is reason


@pytest.mark.anyio
async def test_verifier_uses_injected_comparison_boundary() -> None:
    calls: list[tuple[str, str]] = []

    def compare(provided: str, expected: str) -> bool:
        calls.append((provided, expected))
        return True

    decision = await _verifier(comparator=compare).verify(
        _request(authorization="Bearer supplied-token")
    )
    assert decision.outcome is AccessOutcome.ALLOWED
    assert calls == [("supplied-token", "expected-token")]


@pytest.mark.anyio
async def test_multiple_authorization_headers_are_rejected() -> None:
    decision = await _verifier().verify(
        _request_with_authorization_values("Bearer expected-token", "Bearer expected-token")
    )
    assert decision.reason is AccessDenialReason.AUTHENTICATION_REQUIRED


@pytest.mark.anyio
async def test_comparator_failure_becomes_typed_unavailability() -> None:
    error_message = "secret comparison evidence"

    def broken_comparator(provided: str, expected: str) -> bool:
        del provided, expected
        raise RuntimeError(error_message)

    decision = await _verifier(comparator=broken_comparator).verify(
        _request(authorization="Bearer supplied-token")
    )
    assert decision.outcome is AccessOutcome.UNAVAILABLE
    assert decision.reason is AccessDenialReason.SECURITY_CONFIGURATION_UNAVAILABLE


@pytest.mark.anyio
async def test_production_verifier_unavailability_maps_to_safe_503() -> None:
    def broken_comparator(provided: str, expected: str) -> bool:
        del provided, expected
        raise RuntimeError

    dependency = create_access_dependency(
        InternalApiConfiguration(access_verifier=_verifier(comparator=broken_comparator))
    )
    with pytest.raises(InternalApiError) as raised:
        await dependency(_request(authorization="Bearer supplied-token"))
    assert raised.value.status_code == 503
    assert raised.value.code.value == "security_configuration_unavailable"


@pytest.mark.anyio
async def test_network_allowlist_is_explicit() -> None:
    allowed = await _verifier(networks=("203.0.113.0/24",)).verify(
        _request(authorization="Bearer expected-token")
    )
    denied = await _verifier(networks=("10.0.0.0/8",)).verify(
        _request(authorization="Bearer expected-token")
    )
    assert allowed.outcome is AccessOutcome.ALLOWED
    assert denied.reason is AccessDenialReason.TRUSTED_NETWORK_REQUIRED
