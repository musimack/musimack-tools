"""Contract tests for deterministic URL normalization."""

import pytest

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.domain.urls import UrlErrorCode, UrlNormalizationError


@pytest.mark.parametrize(
    ("submitted", "expected"),
    [
        ("http://example.com/path", "http://example.com/path"),
        ("https://example.com/path", "https://example.com/path"),
        ("HTTP://example.com/path", "http://example.com/path"),
        ("https://ExAmPlE.CoM/path", "https://example.com/path"),
        ("https://example.com/CaseSensitive", "https://example.com/CaseSensitive"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com/path#section", "https://example.com/path"),
        ("http://example.com:80/path", "http://example.com/path"),
        ("https://example.com:443/path", "https://example.com/path"),
        ("http://example.com:8080/path", "http://example.com:8080/path"),
        ("https://example.com:8443/path", "https://example.com:8443/path"),
        ("https://example.com/a/./b/../c", "https://example.com/a/c"),
        ("https://example.com/a/./b/../c/", "https://example.com/a/c/"),
        ("https://example.com/path/", "https://example.com/path/"),
        ("https://example.com/path", "https://example.com/path"),
        ("https://example.com/?b=2&a=1", "https://example.com/?b=2&a=1"),
        ("https://example.com/?a=1&a=2", "https://example.com/?a=1&a=2"),
        ("https://example.com/?empty=&flag", "https://example.com/?empty=&flag"),
        ("https://example.com/a%2fb?q=%3f", "https://example.com/a%2Fb?q=%3F"),
        ("https://bücher.example/", "https://xn--bcher-kva.example/"),
        ("https://XN--BCHER-KVA.EXAMPLE/", "https://xn--bcher-kva.example/"),
        ("https://example.com/?Value=MiXeD", "https://example.com/?Value=MiXeD"),
        ("https://example.com/a//b", "https://example.com/a//b"),
        ("https://example.com/a//../b", "https://example.com/a/b"),
    ],
)
def test_absolute_url_normalization(submitted: str, expected: str) -> None:
    result = normalize_url(submitted)

    assert result.original == submitted
    assert result.normalized == expected


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("child", "https://example.com/a/b/child"),
        ("../child", "https://example.com/a/child"),
        ("/child", "https://example.com/child"),
        ("?new=1&new=2", "https://example.com/a/b/index.html?new=1&new=2"),
        ("#section", "https://example.com/a/b/index.html?old=1"),
        ("//cdn.example.com/asset", "https://cdn.example.com/asset"),
    ],
)
def test_relative_reference_normalization(reference: str, expected: str) -> None:
    base = normalize_url("https://example.com/a/b/index.html?old=1")

    result = normalize_url(reference, base=base)

    assert result.original == reference
    assert result.normalized == expected


@pytest.mark.parametrize(
    ("submitted", "code"),
    [
        ("https://user@example.com/", UrlErrorCode.EMBEDDED_CREDENTIALS),
        ("https://user:password@example.com/", UrlErrorCode.EMBEDDED_CREDENTIALS),
        ("ftp://example.com/", UrlErrorCode.UNSUPPORTED_SCHEME),
        ("file:///tmp/example", UrlErrorCode.UNSUPPORTED_SCHEME),
        ("example.com/path", UrlErrorCode.MISSING_SCHEME),
        ("//example.com/path", UrlErrorCode.MISSING_SCHEME),
        ("https:///path", UrlErrorCode.MISSING_HOSTNAME),
        ("https://example.com:not-a-port/", UrlErrorCode.INVALID_PORT),
        ("https://bad_host.example/", UrlErrorCode.INVALID_HOSTNAME),
        ("https://example.com/%zz", UrlErrorCode.INVALID_PERCENT_ENCODING),
        ("https://example.com/a path", UrlErrorCode.INVALID_CHARACTER),
        ("", UrlErrorCode.EMPTY_URL),
    ],
)
def test_invalid_url_rejection(submitted: str, code: UrlErrorCode) -> None:
    with pytest.raises(UrlNormalizationError) as captured:
        normalize_url(submitted)

    assert captured.value.code is code


@pytest.mark.parametrize(
    "submitted",
    [
        "http://example.com",
        "HTTPS://BÜCHER.EXAMPLE:443/a/../b/?z=1&z=2#fragment",
        "https://example.com/a%2fb?q=%3f",
        "https://example.com/path/",
    ],
)
def test_normalization_is_idempotent(submitted: str) -> None:
    first = normalize_url(submitted)
    second = normalize_url(first.normalized)

    assert second.normalized == first.normalized
    assert second.scheme == first.scheme
    assert second.hostname == first.hostname
    assert second.effective_port == first.effective_port
    assert second.origin == first.origin


def test_normalized_url_exposes_origin_and_effective_port() -> None:
    result = normalize_url("https://example.com:8443/path")

    assert result.scheme == "https"
    assert result.hostname == "example.com"
    assert result.effective_port == 8443
    assert result.origin == "https://example.com:8443"
