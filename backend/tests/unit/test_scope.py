"""Contract tests for host- and port-sensitive crawl scope."""

import pytest

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import create_scope_policy, evaluate_scope
from musimack_tools.domain.urls import AllowedOrigin, ScopeMode, ScopeReasonCode


def test_exact_host_is_allowed_by_default() -> None:
    policy = create_scope_policy(normalize_url("https://example.com"))

    decision = evaluate_scope(policy, "https://example.com/page")

    assert decision.allowed is True
    assert decision.reason_code is ScopeReasonCode.ALLOWED_EXACT_HOST
    assert decision.evaluated_hostname == "example.com"
    assert decision.evaluated_effective_port == 443
    assert decision.configured_host == "example.com"
    assert decision.configured_origin == "https://example.com"


def test_hostname_case_is_normalized_before_scope_evaluation() -> None:
    policy = create_scope_policy(normalize_url("https://EXAMPLE.com"))

    assert evaluate_scope(policy, "https://ExAmPlE.CoM/page").allowed is True


@pytest.mark.parametrize(
    "destination", ["https://www.example.com", "https://example.com.evil.test"]
)
def test_exact_policy_denies_other_hosts(destination: str) -> None:
    policy = create_scope_policy(normalize_url("https://example.com"))

    decision = evaluate_scope(policy, destination)

    assert decision.allowed is False
    assert decision.reason_code is ScopeReasonCode.DENIED_HOST_MISMATCH


def test_apex_and_www_are_not_equivalent() -> None:
    policy = create_scope_policy(normalize_url("https://www.example.com"))

    assert evaluate_scope(policy, "https://example.com").allowed is False


@pytest.mark.parametrize("hostname", ["blog.example.com", "deep.news.example.com"])
def test_true_subdomains_are_allowed_by_subdomain_policy(hostname: str) -> None:
    policy = create_scope_policy(
        normalize_url("https://example.com"),
        mode=ScopeMode.INCLUDE_SUBDOMAINS,
    )

    decision = evaluate_scope(policy, f"https://{hostname}/")

    assert decision.allowed is True
    assert decision.reason_code is ScopeReasonCode.ALLOWED_SUBDOMAIN


def test_true_subdomain_is_denied_by_exact_policy() -> None:
    policy = create_scope_policy(normalize_url("https://example.com"))

    assert evaluate_scope(policy, "https://blog.example.com").allowed is False


def test_false_suffix_is_denied_with_specific_evidence() -> None:
    policy = create_scope_policy(
        normalize_url("https://example.com"),
        mode=ScopeMode.INCLUDE_SUBDOMAINS,
    )

    decision = evaluate_scope(policy, "https://badexample.com")

    assert decision.allowed is False
    assert decision.reason_code is ScopeReasonCode.DENIED_FALSE_SUFFIX_MATCH


@pytest.mark.parametrize("destination", ["https://example.com", "https://blog.example.com"])
def test_subdomain_seed_does_not_broaden_to_parent_or_sibling(destination: str) -> None:
    policy = create_scope_policy(
        normalize_url("https://shop.example.com"),
        mode=ScopeMode.INCLUDE_SUBDOMAINS,
    )

    assert evaluate_scope(policy, destination).allowed is False


def test_subdomain_of_subdomain_seed_is_allowed() -> None:
    policy = create_scope_policy(
        normalize_url("https://shop.example.com"),
        mode=ScopeMode.INCLUDE_SUBDOMAINS,
    )

    assert evaluate_scope(policy, "https://news.shop.example.com").allowed is True


def test_explicit_approved_host_is_allowed_after_normalization() -> None:
    policy = create_scope_policy(
        normalize_url("https://example.com"),
        mode=ScopeMode.APPROVED_HOSTS,
        approved_hosts=["BLOG.Example.COM"],
    )

    decision = evaluate_scope(policy, "https://blog.example.com/page")

    assert decision.allowed is True
    assert decision.reason_code is ScopeReasonCode.ALLOWED_APPROVED_HOST
    assert decision.configured_host == "blog.example.com"


def test_unapproved_host_is_denied() -> None:
    policy = create_scope_policy(
        normalize_url("https://example.com"),
        mode=ScopeMode.APPROVED_HOSTS,
        approved_hosts=["blog.example.com"],
    )

    assert evaluate_scope(policy, "https://shop.example.com").allowed is False


def test_approved_host_policy_does_not_infer_subdomains() -> None:
    policy = create_scope_policy(
        normalize_url("https://example.com"),
        mode=ScopeMode.APPROVED_HOSTS,
        approved_hosts=["blog.example.com"],
    )

    assert evaluate_scope(policy, "https://news.blog.example.com").allowed is False


def test_default_port_is_equivalent_to_implicit_port() -> None:
    policy = create_scope_policy(normalize_url("https://example.com"))

    assert evaluate_scope(policy, "https://example.com:443/page").allowed is True


def test_non_default_port_is_denied_by_default() -> None:
    policy = create_scope_policy(normalize_url("https://example.com"))

    decision = evaluate_scope(policy, "https://example.com:8443/page")

    assert decision.allowed is False
    assert decision.reason_code is ScopeReasonCode.DENIED_PORT_MISMATCH


def test_explicit_non_default_port_can_be_allowed() -> None:
    policy = create_scope_policy(
        normalize_url("https://example.com"),
        allowed_origins=[AllowedOrigin("https", 8443)],
    )

    assert evaluate_scope(policy, "https://example.com:8443/page").allowed is True


def test_http_and_https_are_distinct_scope_origins() -> None:
    policy = create_scope_policy(normalize_url("https://example.com"))

    decision = evaluate_scope(policy, "http://example.com")

    assert decision.allowed is False
    assert decision.reason_code is ScopeReasonCode.DENIED_SCHEME


def test_invalid_destination_returns_structured_denial() -> None:
    policy = create_scope_policy(normalize_url("https://example.com"))

    decision = evaluate_scope(policy, "not a URL")

    assert decision.allowed is False
    assert decision.reason_code is ScopeReasonCode.DENIED_INVALID_URL
    assert decision.evaluated_hostname is None
    assert decision.evaluated_effective_port is None


def test_unsupported_destination_scheme_returns_structured_denial() -> None:
    policy = create_scope_policy(normalize_url("https://example.com"))

    decision = evaluate_scope(policy, "ftp://example.com/file")

    assert decision.allowed is False
    assert decision.reason_code is ScopeReasonCode.DENIED_SCHEME


def test_reason_code_values_are_stable() -> None:
    assert {code.value for code in ScopeReasonCode} == {
        "allowed_exact_host",
        "allowed_subdomain",
        "allowed_approved_host",
        "denied_host_mismatch",
        "denied_false_suffix_match",
        "denied_port_mismatch",
        "denied_scheme",
        "denied_invalid_url",
    }
