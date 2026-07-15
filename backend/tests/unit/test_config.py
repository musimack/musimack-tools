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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("default_maximum_urls", 0),
        ("default_maximum_crawl_depth", -1),
        ("default_request_timeout_seconds", 0),
        ("default_per_host_concurrency", 0),
        ("default_global_crawl_concurrency", 129),
        ("default_minimum_request_delay_seconds", 0),
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
