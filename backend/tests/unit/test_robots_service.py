"""Network-free robots retrieval, caching, and permission tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace

import pytest

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.robots import RobotsCrawlSession, RobotsTxtService
from musimack_tools.crawl.scope import create_scope_policy
from musimack_tools.domain.fetching import (
    FetchFailureCode,
    FetchOutcome,
    FetchRequest,
    FetchResult,
    RedirectHop,
    ResponseHeaders,
)
from musimack_tools.domain.robots import (
    CrawlPermissionDecision,
    CrawlPermissionReason,
    RobotsFetchOutcome,
    RobotsRuleKind,
    RobotsWarningCode,
)
from musimack_tools.domain.urls import CrawlScopePolicy, ScopeMode

_SEED = "https://example.test/"
_ROBOTS = "https://example.test/robots.txt"


@dataclass(slots=True)
class _FakeFetcher:
    results: dict[str, FetchResult]
    calls: list[str]

    def __init__(self, results: dict[str, FetchResult]) -> None:
        self.results = results
        self.calls = []

    async def fetch(self, request: FetchRequest, scope: CrawlScopePolicy) -> FetchResult:
        del scope
        self.calls.append(request.url.normalized)
        await asyncio.sleep(0)
        return self.results[request.url.normalized]


def _fetch_result(  # noqa: PLR0913 - central fixture exposes response dimensions.
    *,
    status: int | None = 200,
    body: bytes | None = b"User-agent: *\nAllow: /",
    content_type: str | None = "text/plain; charset=utf-8",
    outcome: FetchOutcome = FetchOutcome.SUCCESS,
    failure: FetchFailureCode | None = None,
    final_url: str = _ROBOTS,
    redirects: tuple[RedirectHop, ...] = (),
    actual_bytes: int | None = None,
) -> FetchResult:
    return FetchResult(
        requested_url=_ROBOTS,
        final_url=final_url,
        outcome=outcome,
        status_code=status,
        headers=ResponseHeaders(content_type=content_type),
        content_type=content_type,
        declared_content_length=len(body) if body is not None else None,
        actual_bytes_read=(len(body) if body is not None else 0)
        if actual_bytes is None
        else actual_bytes,
        body_truncated=failure is FetchFailureCode.RESPONSE_TOO_LARGE,
        redirect_chain=redirects,
        request_duration_seconds=0.01,
        dns_evidence=(),
        failure_code=failure,
        failure_explanation="Synthetic failure" if failure is not None else None,
        body=body,
    )


def _scope(*, approved: tuple[str, ...] = ()) -> CrawlScopePolicy:
    return create_scope_policy(
        normalize_url(_SEED),
        mode=ScopeMode.APPROVED_HOSTS if approved else ScopeMode.EXACT_HOST,
        approved_hosts=approved,
    )


def _evaluate(
    fetch: FetchResult,
    url: str = _SEED,
    *,
    maximum_body_bytes: int = 1_000_000,
) -> tuple[CrawlPermissionDecision, RobotsCrawlSession, _FakeFetcher]:
    fetcher = _FakeFetcher({_ROBOTS: fetch})
    session = RobotsTxtService(fetcher, maximum_body_bytes=maximum_body_bytes).create_session()
    decision = asyncio.run(session.evaluate(normalize_url(url), _scope()))
    return decision, session, fetcher


def test_200_valid_robots_is_parsed_and_applied() -> None:
    decision, session, fetcher = _evaluate(
        _fetch_result(body=b"User-agent: MusimackSEOToolkit\nDisallow: /private"),
        "https://example.test/private",
    )

    assert decision.allowed is False
    assert decision.reason_code is CrawlPermissionReason.DENIED_BY_DISALLOW_RULE
    assert session.origin_records()[0].fetch_outcome is RobotsFetchOutcome.FETCHED
    assert fetcher.calls == [_ROBOTS]


@pytest.mark.parametrize("status", [204, 400, 404])
def test_no_policy_statuses_allow_crawling(status: int) -> None:
    decision, _session, _fetcher = _evaluate(_fetch_result(status=status, body=b""))

    assert decision.allowed is True
    assert decision.reason_code is CrawlPermissionReason.ALLOWED_NO_ROBOTS_FILE


@pytest.mark.parametrize("status", [401, 403])
def test_access_denied_statuses_conservatively_deny(status: int) -> None:
    decision, _session, _fetcher = _evaluate(_fetch_result(status=status, body=b""))

    assert decision.allowed is False
    assert decision.reason_code is CrawlPermissionReason.DENIED_ROBOTS_ACCESS_FORBIDDEN


@pytest.mark.parametrize("status", [429, 500, 503, 599])
def test_temporary_statuses_block_without_silent_allow(status: int) -> None:
    decision, _session, _fetcher = _evaluate(_fetch_result(status=status, body=b""))

    assert decision.allowed is False
    assert decision.temporary_unavailability is True
    assert decision.reason_code is CrawlPermissionReason.DENIED_ROBOTS_TEMPORARILY_UNAVAILABLE


@pytest.mark.parametrize(
    "failure",
    [
        FetchFailureCode.CONNECT_TIMEOUT,
        FetchFailureCode.READ_TIMEOUT,
        FetchFailureCode.TRANSPORT_ERROR,
    ],
)
def test_transient_fetch_failures_block_temporarily(failure: FetchFailureCode) -> None:
    decision, _session, _fetcher = _evaluate(
        _fetch_result(status=None, body=None, outcome=FetchOutcome.FAILURE, failure=failure)
    )

    assert decision.allowed is False
    assert decision.temporary_unavailability is True


def test_oversized_body_is_denied_by_robots_specific_limit() -> None:
    decision, session, _fetcher = _evaluate(_fetch_result(body=b"x" * 11), maximum_body_bytes=10)

    assert decision.allowed is False
    assert session.origin_records()[0].fetch_outcome is RobotsFetchOutcome.RESPONSE_TOO_LARGE
    assert RobotsWarningCode.RESPONSE_TOO_LARGE in {item.code for item in decision.warnings}


def test_safe_fetch_size_failure_is_preserved_as_robots_size_failure() -> None:
    decision, session, _fetcher = _evaluate(
        _fetch_result(
            status=None,
            body=None,
            outcome=FetchOutcome.FAILURE,
            failure=FetchFailureCode.RESPONSE_TOO_LARGE,
            actual_bytes=5,
        )
    )

    assert decision.allowed is False
    assert session.origin_records()[0].fetch_outcome is RobotsFetchOutcome.RESPONSE_TOO_LARGE


def test_invalid_content_type_is_not_parsed_as_robots() -> None:
    decision, _session, _fetcher = _evaluate(_fetch_result(content_type="text/html"))

    assert decision.allowed is False
    assert RobotsWarningCode.INVALID_CONTENT_TYPE in {item.code for item in decision.warnings}


@pytest.mark.parametrize("content_type", [None, "application/octet-stream", "text/plain"])
def test_missing_or_plain_text_compatible_content_type_is_accepted(
    content_type: str | None,
) -> None:
    decision, _session, _fetcher = _evaluate(_fetch_result(content_type=content_type))

    assert decision.allowed is True


def test_invalid_encoding_records_warning_and_parses_conservatively() -> None:
    decision, _session, _fetcher = _evaluate(
        _fetch_result(body=b"User-agent: *\nDisallow: /bad-\xff")
    )

    assert RobotsWarningCode.DECODE_WARNING in {item.code for item in decision.warnings}


def test_redirect_evidence_and_final_robots_url_are_preserved() -> None:
    final = "https://example.test/policy.txt"
    hop = RedirectHop(
        source_url=_ROBOTS,
        status_code=301,
        raw_location="/policy.txt",
        destination_url=final,
        allowed=True,
        failure_code=None,
        explanation="Allowed",
    )
    decision, session, _fetcher = _evaluate(_fetch_result(final_url=final, redirects=(hop,)))

    assert decision.allowed is True
    assert session.origin_records()[0].requested_url == _ROBOTS
    assert session.origin_records()[0].final_url == final


def test_redirect_to_explicitly_approved_host_is_preserved() -> None:
    final = "https://policy.test/robots.txt"
    hop = RedirectHop(
        source_url=_ROBOTS,
        status_code=302,
        raw_location=final,
        destination_url=final,
        allowed=True,
        failure_code=None,
        explanation="Approved host",
    )
    fetcher = _FakeFetcher({_ROBOTS: _fetch_result(final_url=final, redirects=(hop,))})
    session = RobotsTxtService(fetcher).create_session()

    decision = asyncio.run(
        session.evaluate(normalize_url(_SEED), _scope(approved=("policy.test",)))
    )

    assert decision.allowed is True
    assert session.origin_records()[0].final_url == final


@pytest.mark.parametrize(
    "failure",
    [
        FetchFailureCode.REDIRECT_SCOPE_DENIED,
        FetchFailureCode.REDIRECT_UNSAFE_DESTINATION,
    ],
)
def test_blocked_redirect_failure_is_not_silently_allowed(failure: FetchFailureCode) -> None:
    decision, _session, _fetcher = _evaluate(
        _fetch_result(status=None, body=None, outcome=FetchOutcome.FAILURE, failure=failure)
    )

    assert decision.allowed is False
    assert decision.reason_code is CrawlPermissionReason.DENIED_INVALID_ROBOTS_RESPONSE


def test_cached_success_fetches_once_and_marks_second_lookup() -> None:
    fetcher = _FakeFetcher({_ROBOTS: _fetch_result()})
    session = RobotsTxtService(fetcher).create_session()

    first = asyncio.run(session.evaluate(normalize_url(_SEED), _scope()))
    second = asyncio.run(session.evaluate(normalize_url("https://example.test/child"), _scope()))

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.newly_fetched_bytes == 0
    assert fetcher.calls == [_ROBOTS]


@pytest.mark.parametrize("status", [404, 403, 503])
def test_not_found_denied_and_failure_results_are_cached(status: int) -> None:
    fetcher = _FakeFetcher({_ROBOTS: _fetch_result(status=status, body=b"")})
    session = RobotsTxtService(fetcher).create_session()

    async def evaluate_twice() -> tuple[CrawlPermissionDecision, CrawlPermissionDecision]:
        first, second = await asyncio.gather(
            session.evaluate(normalize_url(_SEED), _scope()),
            session.evaluate(normalize_url("https://example.test/child"), _scope()),
        )
        return first, second

    first, second = asyncio.run(evaluate_twice())

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert fetcher.calls == [_ROBOTS]


def test_concurrent_same_origin_lookup_uses_single_flight() -> None:
    fetcher = _FakeFetcher({_ROBOTS: _fetch_result()})
    session = RobotsTxtService(fetcher).create_session()

    async def evaluate_concurrently() -> tuple[CrawlPermissionDecision, CrawlPermissionDecision]:
        first, second = await asyncio.gather(
            session.evaluate(normalize_url(_SEED), _scope()),
            session.evaluate(normalize_url("https://example.test/child"), _scope()),
        )
        return first, second

    first, second = asyncio.run(evaluate_concurrently())

    assert {first.cache_hit, second.cache_hit} == {False, True}
    assert fetcher.calls == [_ROBOTS]


@pytest.mark.parametrize(
    ("body", "url", "allowed", "reason", "winning_kind"),
    [
        (
            b"User-agent: *\nDisallow: /private\nAllow: /private/public",
            "https://example.test/private/public",
            True,
            CrawlPermissionReason.ALLOWED_BY_ALLOW_RULE,
            RobotsRuleKind.ALLOW,
        ),
        (
            b"User-agent: *\nDisallow: /",
            "https://example.test/page",
            False,
            CrawlPermissionReason.DENIED_BY_DISALLOW_RULE,
            RobotsRuleKind.DISALLOW,
        ),
        (
            b"User-agent: *\nDisallow: /same\nAllow: /same",
            "https://example.test/same",
            True,
            CrawlPermissionReason.ALLOWED_BY_ALLOW_RULE,
            RobotsRuleKind.ALLOW,
        ),
        (
            b"User-agent: *\nDisallow: /*.pdf$",
            "https://example.test/files/report.pdf",
            False,
            CrawlPermissionReason.DENIED_BY_DISALLOW_RULE,
            RobotsRuleKind.DISALLOW,
        ),
        (
            b"User-agent: *\nDisallow: /search?private=1",
            "https://example.test/search?private=1",
            False,
            CrawlPermissionReason.DENIED_BY_DISALLOW_RULE,
            RobotsRuleKind.DISALLOW,
        ),
        (
            b"User-agent: *\nDisallow: /encoded/%2F",
            "https://example.test/encoded/%2F",
            False,
            CrawlPermissionReason.DENIED_BY_DISALLOW_RULE,
            RobotsRuleKind.DISALLOW,
        ),
    ],
)
def test_rule_matching_contract(
    body: bytes,
    url: str,
    allowed: object,
    reason: CrawlPermissionReason,
    winning_kind: RobotsRuleKind,
) -> None:
    decision, _session, _fetcher = _evaluate(_fetch_result(body=body), url)

    assert decision.allowed is allowed
    assert decision.reason_code is reason
    assert decision.matched_rule is not None
    assert decision.matched_rule.kind is winning_kind
    assert decision.explanation


def test_rule_matching_is_case_sensitive() -> None:
    decision, _session, _fetcher = _evaluate(
        _fetch_result(body=b"User-agent: *\nDisallow: /Case"),
        "https://example.test/case",
    )

    assert decision.allowed is True
    assert decision.matched_rule is None


def test_exact_product_group_beats_wildcard_group_case_insensitively() -> None:
    body = b"User-agent: *\nDisallow: /\nUser-agent: musimackseotoolkit\nAllow: /"
    decision, _session, _fetcher = _evaluate(_fetch_result(body=body))

    assert decision.allowed is True
    assert decision.selected_group_index == 1


def test_no_matching_group_allows_with_explicit_warning() -> None:
    decision, _session, _fetcher = _evaluate(
        _fetch_result(body=b"User-agent: OtherBot\nDisallow: /")
    )

    assert decision.allowed is True
    assert decision.reason_code is CrawlPermissionReason.ALLOWED_NO_MATCHING_GROUP
    assert RobotsWarningCode.NO_MATCHING_GROUP in {item.code for item in decision.warnings}


def test_repeated_matching_group_later_in_file_is_not_merged() -> None:
    body = b"User-agent: MusimackSEOToolkit\nAllow: /\nUser-agent: MusimackSEOToolkit\nDisallow: /"
    decision, _session, _fetcher = _evaluate(_fetch_result(body=body))

    assert decision.allowed is True
    assert decision.selected_group_index == 0


def test_non_default_port_constructs_a_distinct_robots_origin() -> None:
    robots = "https://example.test:8443/robots.txt"
    fetch = _fetch_result(final_url=robots)
    fetch = replace(fetch, requested_url=robots)
    fetcher = _FakeFetcher({robots: fetch})
    seed = normalize_url("https://example.test:8443/")
    scope = create_scope_policy(seed)
    session = RobotsTxtService(fetcher).create_session()

    decision = asyncio.run(session.evaluate(seed, scope))

    assert decision.robots_url == robots
    assert fetcher.calls == [robots]
