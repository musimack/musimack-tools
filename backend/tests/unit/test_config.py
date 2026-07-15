"""Tests for typed application configuration."""

import pytest
from pydantic import ValidationError

from musimack_tools.core.config import Environment, LogLevel, Settings


def test_settings_defaults_are_conservative() -> None:
    settings = Settings.model_validate({})

    assert settings.application_name == "Musimack SEO Toolkit"
    assert settings.environment is Environment.DEVELOPMENT
    assert settings.log_level is LogLevel.INFO
    assert settings.crawler_user_agent == "MusimackSEOToolkit/0.1"
    assert settings.default_maximum_urls == 5_000
    assert settings.default_maximum_crawl_depth == 10
    assert settings.default_request_timeout_seconds == 20
    assert settings.default_per_host_concurrency == 2
    assert settings.default_global_crawl_concurrency == 4
    assert settings.default_minimum_request_delay_seconds == 0.5
    assert settings.include_subdomains_by_default is False
    assert settings.fetch_maximum_redirect_hops == 10
    assert settings.fetch_maximum_response_body_bytes == 5_000_000
    assert settings.fetch_maximum_response_header_bytes == 65_536
    assert settings.fetch_maximum_dns_answers == 16
    assert settings.fetch_connect_timeout_seconds == 10
    assert settings.fetch_read_timeout_seconds == 20
    assert settings.fetch_write_timeout_seconds == 10
    assert settings.fetch_pool_timeout_seconds == 10
    assert settings.fetch_total_request_deadline_seconds == 30
    assert settings.fetch_retry_count == 1
    assert settings.fetch_permitted_production_ports == (80, 443)
    assert settings.fetch_http_allowed is True
    assert settings.fetch_https_allowed is True
    assert settings.fetch_trust_environment_proxies is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("default_maximum_urls", 0),
        ("default_maximum_crawl_depth", -1),
        ("default_request_timeout_seconds", 0),
        ("default_per_host_concurrency", 0),
        ("default_global_crawl_concurrency", 129),
        ("default_minimum_request_delay_seconds", 0),
        ("fetch_maximum_redirect_hops", 21),
        ("fetch_maximum_response_body_bytes", 0),
        ("fetch_maximum_response_header_bytes", 100),
        ("fetch_maximum_dns_answers", 65),
        ("fetch_retry_count", 4),
    ],
)
def test_settings_reject_out_of_bounds_values(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({field: value})


def test_settings_reject_per_host_concurrency_above_global_limit() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        Settings.model_validate(
            {
                "default_per_host_concurrency": 5,
                "default_global_crawl_concurrency": 4,
            }
        )


@pytest.mark.parametrize("ports", [(), (0,), (443, 443), tuple(range(1, 18))])
def test_settings_reject_invalid_fetch_port_lists(ports: tuple[int, ...]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"fetch_permitted_production_ports": ports})


def test_settings_require_at_least_one_fetch_scheme() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        Settings.model_validate({"fetch_http_allowed": False, "fetch_https_allowed": False})
