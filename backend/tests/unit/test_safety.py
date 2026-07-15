"""Safety-policy tests using inert DNS evidence only."""

import asyncio
from dataclasses import dataclass, field

import pytest

from musimack_tools.core.config import Settings
from musimack_tools.crawl.dns import DnsResolutionError
from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.safety import DestinationSafetyValidator, is_public_address
from musimack_tools.domain.fetching import (
    DnsEvidence,
    FetchFailureCode,
    NetworkSafetyDecision,
)
from musimack_tools.domain.urls import NormalizedUrl

_SAFE_ADDRESS = "93.184.216.34"


@dataclass
class _FakeResolver:
    answers: dict[str, tuple[str, ...]] = field(default_factory=dict)
    failure: DnsResolutionError | None = None
    calls: list[tuple[str, int]] = field(default_factory=list)

    async def resolve(self, hostname: str, *, maximum_answers: int) -> DnsEvidence:
        self.calls.append((hostname, maximum_answers))
        if self.failure is not None:
            raise self.failure
        return DnsEvidence(hostname, self.answers.get(hostname, (_SAFE_ADDRESS,)))


def _settings(**overrides: object) -> Settings:
    return Settings.model_validate(overrides)


def _validate(
    url: str,
    resolver: _FakeResolver | None = None,
    **settings: object,
) -> NetworkSafetyDecision:
    selected_resolver = resolver or _FakeResolver()
    validator = DestinationSafetyValidator(_settings(**settings), selected_resolver)
    return asyncio.run(validator.validate(normalize_url(url)))


@pytest.mark.parametrize(
    "hostname",
    [
        "localhost",
        "api.localhost",
        "printer.local",
        "service.internal",
        "router.home",
        "device.lan",
        "metadata.google.internal",
        "instance-data",
    ],
)
def test_prohibited_hostname_classes_are_rejected_without_dns(hostname: str) -> None:
    resolver = _FakeResolver()

    decision = _validate(f"https://{hostname}/", resolver)

    assert decision.allowed is False
    assert decision.failure_code is FetchFailureCode.UNSAFE_HOSTNAME
    assert resolver.calls == []


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "::1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.0.1",
        "169.254.1.1",
        "fe80::1",
        "169.254.169.254",
        "100.64.0.1",
        "192.0.2.1",
        "198.51.100.1",
        "203.0.113.1",
        "224.0.0.1",
        "0.0.0.0",  # noqa: S104 - inert address classification input, never bound.
        "240.0.0.1",
        "::ffff:127.0.0.1",
        "fc00::1",
        "fec0::1",
        "2001:db8::1",
    ],
)
def test_prohibited_resolved_addresses_are_rejected(address: str) -> None:
    resolver = _FakeResolver(answers={"example.test": (address,)})

    decision = _validate("https://example.test/", resolver)

    assert decision.allowed is False
    assert decision.failure_code is FetchFailureCode.UNSAFE_RESOLVED_ADDRESS


def test_mixed_safe_and_unsafe_answers_are_rejected() -> None:
    resolver = _FakeResolver(answers={"example.test": (_SAFE_ADDRESS, "10.0.0.1")})

    decision = _validate("https://example.test/", resolver)

    assert decision.failure_code is FetchFailureCode.MIXED_SAFE_UNSAFE_DNS_ANSWERS
    assert decision.dns_evidence is not None
    assert decision.dns_evidence.answer_count == 2


def test_ip_literal_is_rejected_before_resolution() -> None:
    resolver = _FakeResolver()

    decision = _validate("https://93.184.216.34/", resolver)

    assert decision.failure_code is FetchFailureCode.IP_LITERAL_NOT_ALLOWED
    assert resolver.calls == []


def test_disallowed_port_is_rejected_before_resolution() -> None:
    resolver = _FakeResolver()

    decision = _validate("https://example.test:8443/", resolver)

    assert decision.failure_code is FetchFailureCode.PORT_NOT_ALLOWED
    assert resolver.calls == []


def test_disabled_scheme_is_rejected() -> None:
    decision = _validate("http://example.test/", fetch_http_allowed=False)

    assert decision.failure_code is FetchFailureCode.UNSUPPORTED_SCHEME


def test_dns_failure_is_mapped_without_raw_message() -> None:
    resolver = _FakeResolver(
        failure=DnsResolutionError(
            FetchFailureCode.DNS_RESOLUTION_FAILED,
            "The destination hostname could not be resolved",
            exception_type="gaierror",
        )
    )

    decision = _validate("https://example.test/", resolver)

    assert decision.failure_code is FetchFailureCode.DNS_RESOLUTION_FAILED
    assert decision.internal_exception_type == "gaierror"
    assert "synthetic" not in decision.explanation


def test_dns_answer_limit_failure_is_preserved() -> None:
    resolver = _FakeResolver(
        failure=DnsResolutionError(
            FetchFailureCode.DNS_ANSWER_LIMIT_EXCEEDED,
            "The destination returned more DNS answers than the configured limit",
        )
    )

    decision = _validate("https://example.test/", resolver)

    assert decision.failure_code is FetchFailureCode.DNS_ANSWER_LIMIT_EXCEEDED


def test_public_style_inert_address_is_allowed() -> None:
    decision = _validate("https://example.test/")

    assert decision.allowed is True
    assert decision.failure_code is None
    assert is_public_address(_SAFE_ADDRESS) is True


def test_network_boundary_defensively_rejects_credentials() -> None:
    destination = NormalizedUrl._from_validated_parts(  # noqa: SLF001
        original="https://user:password@example.test/",
        normalized="https://user:password@example.test/",
        scheme="https",
        hostname="example.test",
        effective_port=443,
        origin="https://example.test",
    )
    validator = DestinationSafetyValidator(_settings(), _FakeResolver())

    decision = asyncio.run(validator.validate(destination))

    assert decision.failure_code is FetchFailureCode.CREDENTIALS_NOT_ALLOWED


def test_network_boundary_defensively_rejects_unsupported_scheme() -> None:
    destination = NormalizedUrl._from_validated_parts(  # noqa: SLF001
        original="ftp://example.test/file",
        normalized="ftp://example.test/file",
        scheme="ftp",
        hostname="example.test",
        effective_port=21,
        origin="ftp://example.test:21",
    )
    validator = DestinationSafetyValidator(_settings(), _FakeResolver())

    decision = asyncio.run(validator.validate(destination))

    assert decision.failure_code is FetchFailureCode.UNSUPPORTED_SCHEME


def test_network_boundary_rejects_inconsistent_hostname_evidence() -> None:
    destination = NormalizedUrl._from_validated_parts(  # noqa: SLF001
        original="https://example.test/",
        normalized="https://different.test/",
        scheme="https",
        hostname="example.test",
        effective_port=443,
        origin="https://example.test",
    )
    validator = DestinationSafetyValidator(_settings(), _FakeResolver())

    decision = asyncio.run(validator.validate(destination))

    assert decision.failure_code is FetchFailureCode.INVALID_HOSTNAME
