"""Integration coverage for the public health contract."""

import logging

from fastapi.testclient import TestClient

from musimack_tools.core.config import Settings
from musimack_tools.main import create_app


def test_health_endpoint_returns_minimal_typed_response() -> None:
    application = create_app(Settings.model_validate({}))

    with TestClient(application) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "application": "Musimack SEO Toolkit",
        "status": "healthy",
    }


def test_health_endpoint_uses_configured_application_name() -> None:
    application = create_app(Settings.model_validate({"application_name": "Configured Toolkit"}))

    with TestClient(application) as client:
        response = client.get("/api/health")

    assert response.json() == {"application": "Configured Toolkit", "status": "healthy"}


def test_no_arbitrary_fetch_api_is_exposed() -> None:
    application = create_app(Settings.model_validate({}))

    paths = set(application.openapi()["paths"])

    assert paths == {"/api/health"}


def test_application_suppresses_httpx_query_bearing_info_logs() -> None:
    create_app(Settings.model_validate({}))

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
