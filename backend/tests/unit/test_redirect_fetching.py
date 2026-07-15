"""Manual redirect handling tests with complete mocked evidence."""

import asyncio
from dataclasses import dataclass, field

import httpx
import pytest

from musimack_tools.core.config import Settings
from musimack_tools.crawl.fetcher import SafeSingleUrlFetcher
from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.safety import DestinationSafetyValidator
from musimack_tools.crawl.scope import create_scope_policy
from musimack_tools.domain.fetching import (
    DnsEvidence,
    FetchFailureCode,
    FetchOutcome,
    FetchRequest,
    FetchResult,
)
from musimack_tools.domain.urls import AllowedOrigin, ScopeMode

_SAFE_ADDRESS = "93.184.216.34"


@dataclass
class _Resolver:
    answers: dict[str, tuple[str, ...]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    async def resolve(self, hostname: str, *, maximum_answers: int) -> DnsEvidence:
        del maximum_answers
        self.calls.append(hostname)
        return DnsEvidence(hostname, self.answers.get(hostname, (_SAFE_ADDRESS,)))


def _fetch(
    responses: list[httpx.Response],
    *,
    settings_data: dict[str, object] | None = None,
    resolver: _Resolver | None = None,
    scope_hosts: tuple[str, ...] = (),
    allowed_origins: tuple[AllowedOrigin, ...] = (),
) -> tuple[FetchResult, _Resolver]:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        response = queue.pop(0)
        response.request = request
        return response

    settings = Settings.model_validate(settings_data or {})
    selected_resolver = resolver or _Resolver()
    seed = normalize_url("https://example.test/start")
    mode = ScopeMode.APPROVED_HOSTS if scope_hosts else ScopeMode.EXACT_HOST
    scope = create_scope_policy(
        seed,
        mode=mode,
        approved_hosts=scope_hosts,
        allowed_origins=allowed_origins,
    )
    fetcher = SafeSingleUrlFetcher(
        settings,
        DestinationSafetyValidator(settings, selected_resolver),
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(fetcher.fetch(FetchRequest(seed), scope))
    return result, selected_resolver


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_standard_redirect_statuses_are_followed(status: int) -> None:
    result, _ = _fetch(
        [
            httpx.Response(status, headers={"Location": "/final"}),
            httpx.Response(200, content=b"done"),
        ]
    )

    assert result.outcome is FetchOutcome.SUCCESS
    assert result.final_url == "https://example.test/final"
    assert result.body == b"done"
    assert len(result.redirect_chain) == 1
    assert result.redirect_chain[0].status_code == status


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("child", "https://example.test/child"),
        ("/root", "https://example.test/root"),
        ("https://example.test/absolute", "https://example.test/absolute"),
        ("/fragment#section", "https://example.test/fragment"),
    ],
)
def test_relative_root_absolute_and_fragment_redirects(location: str, expected: str) -> None:
    result, _ = _fetch([httpx.Response(302, headers={"Location": location}), httpx.Response(200)])

    assert result.final_url == expected
    assert result.redirect_chain[0].destination_url == expected


def test_multiple_redirects_retain_complete_chain_and_final_response() -> None:
    result, resolver = _fetch(
        [
            httpx.Response(301, headers={"Location": "/one"}),
            httpx.Response(308, headers={"Location": "/two"}),
            httpx.Response(200, headers={"Content-Type": "text/plain"}, content=b"final"),
        ]
    )

    assert [hop.source_url for hop in result.redirect_chain] == [
        "https://example.test/start",
        "https://example.test/one",
    ]
    assert result.final_url == "https://example.test/two"
    assert result.status_code == 200
    assert result.body == b"final"
    assert resolver.calls == ["example.test", "example.test", "example.test"]


def test_redirect_does_not_read_or_reject_its_declared_body_size() -> None:
    result, _ = _fetch(
        [
            httpx.Response(
                302,
                headers={"Location": "/final", "Content-Length": "9999999"},
            ),
            httpx.Response(200, content=b"final"),
        ],
        settings_data={"fetch_maximum_response_body_bytes": 5},
    )

    assert result.outcome is FetchOutcome.SUCCESS
    assert result.body == b"final"


@pytest.mark.parametrize("location", [None, "", "   "])
def test_missing_or_empty_location_is_typed_failure(location: str | None) -> None:
    headers = {} if location is None else {"Location": location}

    result, _ = _fetch([httpx.Response(302, headers=headers)])

    assert result.failure_code is FetchFailureCode.REDIRECT_MISSING_LOCATION
    assert len(result.redirect_chain) == 1
    assert result.redirect_chain[0].destination_url is None


@pytest.mark.parametrize(
    "location",
    ["ftp://example.test/file", "https://user:password@example.test/", "/bad%zz"],
)
def test_invalid_unsupported_or_credential_location_is_typed_failure(location: str) -> None:
    result, _ = _fetch([httpx.Response(302, headers={"Location": location})])

    assert result.failure_code is FetchFailureCode.REDIRECT_INVALID_LOCATION
    assert result.redirect_chain[0].raw_location == location


def test_redirect_outside_scope_is_blocked_without_resolving_target() -> None:
    result, resolver = _fetch([httpx.Response(302, headers={"Location": "https://outside.test/"})])

    assert result.failure_code is FetchFailureCode.REDIRECT_SCOPE_DENIED
    assert result.redirect_chain[0].destination_url == "https://outside.test/"
    assert resolver.calls == ["example.test"]


def test_redirect_to_unsafe_hostname_is_blocked() -> None:
    result, _ = _fetch(
        [httpx.Response(302, headers={"Location": "https://localhost/"})],
        scope_hosts=("localhost",),
    )

    assert result.failure_code is FetchFailureCode.REDIRECT_UNSAFE_DESTINATION
    assert result.redirect_chain[0].failure_code is FetchFailureCode.UNSAFE_HOSTNAME


def test_redirect_resolving_to_unsafe_address_is_blocked() -> None:
    resolver = _Resolver(answers={"unsafe.test": ("10.0.0.1",)})

    result, _ = _fetch(
        [httpx.Response(302, headers={"Location": "https://unsafe.test/"})],
        resolver=resolver,
        scope_hosts=("unsafe.test",),
    )

    assert result.failure_code is FetchFailureCode.REDIRECT_UNSAFE_DESTINATION
    assert result.redirect_chain[0].failure_code is FetchFailureCode.UNSAFE_RESOLVED_ADDRESS


def test_redirect_to_disallowed_port_is_blocked_by_network_policy() -> None:
    result, _ = _fetch(
        [httpx.Response(302, headers={"Location": "https://example.test:8443/"})],
        allowed_origins=(AllowedOrigin("https", 8443),),
    )

    assert result.failure_code is FetchFailureCode.REDIRECT_UNSAFE_DESTINATION
    assert result.redirect_chain[0].failure_code is FetchFailureCode.PORT_NOT_ALLOWED


def test_redirect_loop_is_detected_using_normalized_urls() -> None:
    result, _ = _fetch(
        [
            httpx.Response(302, headers={"Location": "/one"}),
            httpx.Response(302, headers={"Location": "/start#ignored"}),
        ]
    )

    assert result.failure_code is FetchFailureCode.REDIRECT_LOOP
    assert len(result.redirect_chain) == 2
    assert result.redirect_chain[-1].allowed is False


def test_redirect_hop_limit_retains_blocked_hop_evidence() -> None:
    result, _ = _fetch(
        [
            httpx.Response(302, headers={"Location": "/one"}),
            httpx.Response(302, headers={"Location": "/two"}),
        ],
        settings_data={"fetch_maximum_redirect_hops": 1},
    )

    assert result.failure_code is FetchFailureCode.REDIRECT_LIMIT_EXCEEDED
    assert len(result.redirect_chain) == 2
    assert result.redirect_chain[0].allowed is True
    assert result.redirect_chain[1].allowed is False


def test_chain_is_retained_when_later_redirect_is_unsafe() -> None:
    result, _ = _fetch(
        [
            httpx.Response(302, headers={"Location": "/one"}),
            httpx.Response(302, headers={"Location": "https://localhost/"}),
        ],
        scope_hosts=("localhost",),
    )

    assert result.failure_code is FetchFailureCode.REDIRECT_UNSAFE_DESTINATION
    assert len(result.redirect_chain) == 2
    assert result.redirect_chain[0].allowed is True
    assert result.redirect_chain[1].allowed is False
