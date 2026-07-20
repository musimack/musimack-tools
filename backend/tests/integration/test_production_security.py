"""Production application authentication, middleware, and isolation contracts."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

import httpx
import pytest
from fastapi.testclient import TestClient

from musimack_tools.application.preparation import ApplicationRequestPreparer
from musimack_tools.application.readiness import capability_report
from musimack_tools.application.service import SeoToolkitApplicationService
from musimack_tools.core.config import Settings
from musimack_tools.deployment.application import create_production_app
from musimack_tools.deployment.settings import ProductionSettings
from musimack_tools.domain.crawl import (
    CrawlConfigurationSnapshot,
    CrawlCounters,
    CrawlRequest,
    CrawlResult,
    CrawlState,
)
from musimack_tools.domain.deployment import ProductionConfigurationError
from musimack_tools.jobs.registry import InMemoryJobRegistry
from musimack_tools.jobs.service import InternalJobService
from musimack_tools.main import create_app
from musimack_tools.run.service import CrawlRunService
from musimack_tools.security.correlation import current_request_id

if TYPE_CHECKING:
    from musimack_tools.crawl.cancellation import CancellationToken
    from musimack_tools.crawl.orchestrator import ProgressObserver
    from musimack_tools.domain.application import (
        ApplicationCancellationResult,
        ApplicationJobList,
        ApplicationJobStatus,
        ApplicationPreflightResult,
        ApplicationProgressResult,
        ApplicationReadinessReport,
        ApplicationRecommendationDetail,
        ApplicationRecommendationPage,
        ApplicationRegistryStatus,
        ApplicationResultProjection,
        ApplicationSubmissionResult,
        ApplicationValidationReport,
        RawApplicationCrawlRequest,
    )
    from musimack_tools.domain.capabilities import ApplicationCapabilityReport
    from musimack_tools.run.progress import RunProgressSink

_TOKEN = "integration-test-token"  # noqa: S105 - inert test credential.
_UNUSED_SERVICE_CALL = "not used by this security boundary test"
_VALID_BODY = {"seed_url": "https://example.com", "crawl_profile": "quick_audit"}
_INTERNAL_PATHS = (
    ("POST", "/api/internal/v1/requests/validate"),
    ("POST", "/api/internal/v1/requests/preflight"),
    ("POST", "/api/internal/v1/jobs"),
    ("GET", "/api/internal/v1/jobs"),
    ("GET", "/api/internal/v1/jobs/job-4f82d76a1b42-0001"),
    ("GET", "/api/internal/v1/jobs/job-4f82d76a1b42-0001/progress"),
    ("GET", "/api/internal/v1/jobs/job-4f82d76a1b42-0001/result"),
    ("GET", "/api/internal/v1/jobs/job-4f82d76a1b42-0001/recommendations"),
    ("GET", "/api/internal/v1/jobs/job-4f82d76a1b42-0001/recommendations/1"),
    ("POST", "/api/internal/v1/jobs/job-4f82d76a1b42-0001/cancel"),
    ("GET", "/api/internal/v1/registry"),
    ("GET", "/api/internal/v1/readiness"),
    ("GET", "/api/internal/v1/capabilities"),
)


class _SecurityTestService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.raise_validate = False

    def validate_request(self, raw: RawApplicationCrawlRequest) -> ApplicationValidationReport:
        self.calls.append("validate")
        if self.raise_validate:
            raise RuntimeError("private-service-evidence")
        return ApplicationRequestPreparer().prepare(raw).report

    async def preflight(self, raw: RawApplicationCrawlRequest) -> ApplicationPreflightResult:
        del raw
        self.calls.append("preflight")
        raise AssertionError(_UNUSED_SERVICE_CALL)

    async def submit(self, raw: RawApplicationCrawlRequest) -> ApplicationSubmissionResult:
        del raw
        self.calls.append("submit")
        raise AssertionError(_UNUSED_SERVICE_CALL)

    async def get_job_status(self, job_id: str) -> ApplicationJobStatus:
        del job_id
        self.calls.append("status")
        raise AssertionError(_UNUSED_SERVICE_CALL)

    async def list_jobs(self) -> ApplicationJobList:
        self.calls.append("list")
        raise AssertionError(_UNUSED_SERVICE_CALL)

    async def get_job_progress(self, job_id: str) -> ApplicationProgressResult:
        del job_id
        self.calls.append("progress")
        raise AssertionError(_UNUSED_SERVICE_CALL)

    async def get_job_result(self, job_id: str) -> ApplicationResultProjection:
        del job_id
        self.calls.append("result")
        raise AssertionError(_UNUSED_SERVICE_CALL)

    async def get_job_recommendations(  # noqa: PLR0913 - mirrors the endpoint contract.
        self,
        job_id: str,
        *,
        offset: int,
        limit: int,
        state: str | None = None,
        reason: str | None = None,
        text: str | None = None,
    ) -> ApplicationRecommendationPage:
        del job_id, offset, limit, state, reason, text
        self.calls.append("recommendations")
        raise AssertionError(_UNUSED_SERVICE_CALL)

    async def get_job_recommendation_detail(
        self, job_id: str, sequence: int
    ) -> ApplicationRecommendationDetail:
        del job_id, sequence
        self.calls.append("recommendation_detail")
        raise AssertionError(_UNUSED_SERVICE_CALL)

    async def cancel_job(self, job_id: str) -> ApplicationCancellationResult:
        del job_id
        self.calls.append("cancel")
        raise AssertionError(_UNUSED_SERVICE_CALL)

    async def get_registry_status(self) -> ApplicationRegistryStatus:
        self.calls.append("registry")
        raise AssertionError(_UNUSED_SERVICE_CALL)

    async def get_readiness(self) -> ApplicationReadinessReport:
        self.calls.append("readiness")
        raise AssertionError(_UNUSED_SERVICE_CALL)

    def get_capabilities(self) -> ApplicationCapabilityReport:
        self.calls.append("capabilities")
        return capability_report()


class _AcceptedCrawler:
    async def crawl(
        self,
        request: CrawlRequest,
        *,
        observer: ProgressObserver | None = None,
    ) -> CrawlResult:
        del observer
        return CrawlResult(
            seed_url=request.seed_url.normalized,
            scope_policy=request.scope_policy,
            started_at_seconds=0,
            ended_at_seconds=1,
            duration_seconds=1,
            state=CrawlState.COMPLETED,
            url_records=(),
            discoveries=(),
            counters=CrawlCounters(unique_urls_discovered=1, urls_queued=1, urls_fetched=1),
            limit_events=(),
            errors=(),
            cancellation=None,
            total_accepted_bytes=10,
            maximum_observed_queue_size=1,
            maximum_active_worker_count=1,
            configuration=CrawlConfigurationSnapshot(
                request.maximum_unique_urls,
                request.maximum_depth,
                request.maximum_duration_seconds,
                request.maximum_total_fetched_bytes,
                request.maximum_concurrent_fetches,
                request.maximum_queued_urls,
                request.minimum_per_origin_delay_seconds,
                request.query_urls_allowed,
                request.exclusion_rules,
            ),
        )


def _accepted_run_factory(
    cancellation: CancellationToken,
    progress_sink: RunProgressSink,
) -> CrawlRunService:
    return CrawlRunService(
        _AcceptedCrawler(), cancellation=cancellation, progress_sink=progress_sink
    )


def _settings(**changes: object) -> ProductionSettings:
    values: dict[str, object] = {"enabled": True, "bearer_token": _TOKEN}
    values.update(changes)
    return ProductionSettings.model_validate(values)


def _client(
    service: _SecurityTestService,
    settings: ProductionSettings | None = None,
    *,
    client_address: str = "203.0.113.10",
) -> TestClient:
    app = create_production_app(
        service,
        settings or _settings(),
        Settings(),
    )
    return TestClient(
        app,
        client=(client_address, 50_000),
        raise_server_exceptions=False,
    )


def test_default_application_remains_health_only_and_secret_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MUSIMACK_INTERNAL_API_ENABLED", "true")
    monkeypatch.setenv("MUSIMACK_INTERNAL_API_BEARER_TOKEN", _TOKEN)
    application = create_app(Settings())
    client = TestClient(application)
    assert client.get("/api/health").json() == {
        "application": "Musimack SEO Toolkit",
        "status": "healthy",
    }
    for path in ("/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"):
        assert client.get(path).status_code == 404
    assert sorted(application.openapi()["paths"]) == ["/api/health"]


def test_production_factory_fails_closed_when_disabled() -> None:
    with pytest.raises(ProductionConfigurationError) as raised:
        create_production_app(
            _SecurityTestService(),
            ProductionSettings(),
            Settings(),
        )
    assert _TOKEN not in str(raised.value)


def test_production_metadata_and_security_readiness_are_versioned() -> None:
    application = create_production_app(
        _SecurityTestService(),
        _settings(),
        Settings(),
    )
    assert application.state.production_configuration.security_version == "seo-toolkit-security-v1"
    assert (
        application.state.production_configuration.production_application_version
        == "seo-toolkit-production-app-v1"
    )
    assert application.state.security_readiness.state.value == "ready"


@pytest.mark.parametrize(("method", "path"), _INTERNAL_PATHS)
def test_all_internal_routes_require_authentication_before_service(method: str, path: str) -> None:
    service = _SecurityTestService()
    response = _client(service).request(method, path, json=_VALID_BODY)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "authentication_failed"
    assert service.calls == []


@pytest.mark.parametrize("authorization", ["Bearer wrong", "Basic integration-test-token"])
def test_invalid_credentials_are_generic_and_never_echoed(authorization: str) -> None:
    response = _client(_SecurityTestService()).get(
        "/api/internal/v1/capabilities", headers={"Authorization": authorization}
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Valid internal authentication is required."
    assert authorization not in response.text


def test_valid_credential_grants_access_and_sets_correlation_envelope() -> None:
    service = _SecurityTestService()
    response = _client(service).post(
        "/api/internal/v1/requests/validate",
        headers={"Authorization": f"Bearer {_TOKEN}", "X-Request-ID": "caller.request-1"},
        json=_VALID_BODY,
    )
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "caller.request-1"
    assert response.json()["request_id"] == "caller.request-1"
    assert service.calls == ["validate"]


@pytest.mark.parametrize("request_id", ["bad id", "../path", "bad\\path", "x" * 65])
def test_invalid_correlation_identifiers_are_replaced(request_id: str) -> None:
    response = _client(_SecurityTestService()).get(
        "/api/internal/v1/capabilities",
        headers={"Authorization": f"Bearer {_TOKEN}", "X-Request-ID": request_id},
    )
    generated = response.headers["x-request-id"]
    assert re.fullmatch(r"req-[0-9a-f]{32}", generated)
    assert response.json()["request_id"] == generated
    assert request_id not in response.text


def test_multiple_correlation_headers_are_replaced() -> None:
    response = _client(_SecurityTestService()).get(
        "/api/internal/v1/capabilities",
        headers=[
            ("Authorization", f"Bearer {_TOKEN}"),
            ("X-Request-ID", "first"),
            ("X-Request-ID", "second"),
        ],
    )
    assert re.fullmatch(r"req-[0-9a-f]{32}", response.headers["x-request-id"])


def test_authentication_error_includes_safe_correlation_identifier() -> None:
    response = _client(_SecurityTestService()).get(
        "/api/internal/v1/capabilities", headers={"X-Request-ID": "denied-request"}
    )
    assert response.status_code == 401
    assert response.json()["request_id"] == "denied-request"
    assert response.headers["x-request-id"] == "denied-request"


def test_trusted_network_allows_and_denies_explicitly() -> None:
    settings = _settings(trusted_networks=("203.0.113.0/24",))
    allowed = _client(_SecurityTestService(), settings).get(
        "/api/internal/v1/capabilities", headers={"Authorization": f"Bearer {_TOKEN}"}
    )
    denied = _client(_SecurityTestService(), settings, client_address="198.51.100.10").get(
        "/api/internal/v1/capabilities", headers={"Authorization": f"Bearer {_TOKEN}"}
    )
    assert allowed.status_code == 200
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "trusted_network_required"


def test_trusted_proxy_forwarding_and_untrusted_spoofing() -> None:
    settings = _settings(
        trusted_proxies=("10.0.0.0/8",),
        trusted_networks=("198.51.100.0/24",),
    )
    forwarded = _client(_SecurityTestService(), settings, client_address="10.0.0.8").get(
        "/api/internal/v1/capabilities",
        headers={"Authorization": f"Bearer {_TOKEN}", "X-Forwarded-For": "198.51.100.7"},
    )
    spoofed = _client(_SecurityTestService(), settings, client_address="203.0.113.8").get(
        "/api/internal/v1/capabilities",
        headers={"Authorization": f"Bearer {_TOKEN}", "X-Forwarded-For": "198.51.100.7"},
    )
    assert forwarded.status_code == 200
    assert spoofed.status_code == 403


def test_malformed_trusted_proxy_chain_fails_closed() -> None:
    settings = _settings(trusted_proxies=("10.0.0.0/8",))
    response = _client(_SecurityTestService(), settings, client_address="10.0.0.8").get(
        "/api/internal/v1/capabilities",
        headers={"Authorization": f"Bearer {_TOKEN}", "X-Forwarded-For": "bad,,chain"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_forwarded_header"


def test_cors_is_explicit_bounded_and_does_not_invoke_service() -> None:
    service = _SecurityTestService()
    client = _client(
        service,
        _settings(cors_enabled=True, allowed_origins=("https://tools.example.test",)),
    )
    allowed = client.options(
        "/api/internal/v1/jobs",
        headers={
            "Origin": "https://tools.example.test",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type,X-Request-ID",
        },
    )
    denied = client.options(
        "/api/internal/v1/jobs",
        headers={
            "Origin": "https://evil.example.test",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://tools.example.test"
    assert allowed.headers["access-control-allow-methods"] == "GET, POST, OPTIONS"
    assert allowed.headers["access-control-allow-headers"] == (
        "Authorization, Content-Type, X-Request-ID"
    )
    assert allowed.headers.get("access-control-allow-credentials") is None
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
    assert service.calls == []


def test_security_headers_apply_without_hsts_and_health_body_is_unchanged() -> None:
    client = _client(_SecurityTestService())
    response = client.get(
        "/api/internal/v1/capabilities", headers={"Authorization": f"Bearer {_TOKEN}"}
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"
    assert "strict-transport-security" not in response.headers
    assert client.get("/api/health").json()["status"] == "healthy"


def test_security_headers_and_access_logging_can_be_explicitly_disabled() -> None:
    client = _client(
        _SecurityTestService(),
        _settings(security_headers=False, access_logging=False),
    )
    response = client.get(
        "/api/internal/v1/capabilities", headers={"Authorization": f"Bearer {_TOKEN}"}
    )
    assert response.status_code == 200
    assert "x-content-type-options" not in response.headers


def test_security_headers_apply_to_validation_errors() -> None:
    response = _client(_SecurityTestService()).post(
        "/api/internal/v1/requests/validate",
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json={},
    )
    assert response.status_code == 400
    assert response.headers["x-content-type-options"] == "nosniff"


def test_unexpected_error_is_safe_correlated_and_header_protected() -> None:
    service = _SecurityTestService()
    service.raise_validate = True
    response = _client(service).post(
        "/api/internal/v1/requests/validate",
        headers={"Authorization": f"Bearer {_TOKEN}", "X-Request-ID": "failed-request"},
        json=_VALID_BODY,
    )
    assert response.status_code == 500
    assert response.json()["request_id"] == "failed-request"
    assert response.json()["error"]["code"] == "internal_api_error"
    assert "private-service-evidence" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_openapi_is_disabled_by_default_and_explicit_when_enabled() -> None:
    hidden = _client(_SecurityTestService())
    shown = _client(_SecurityTestService(), _settings(include_openapi=True))
    assert hidden.get("/openapi.json").status_code == 404
    document = shown.get("/openapi.json").json()
    assert len([path for path in document["paths"] if path.startswith("/api/internal/v1")]) == 12
    assert _TOKEN not in str(document)


def test_access_log_is_correlated_and_excludes_secrets_and_query(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="musimack_tools.security.access")
    response = _client(_SecurityTestService()).get(
        "/api/internal/v1/capabilities?token=query-secret",
        headers={"Authorization": f"Bearer {_TOKEN}", "X-Request-ID": "logged-request"},
    )
    assert response.status_code == 200
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "event=internal_api_request_completed" in messages
    assert "correlation_id=logged-request" in messages
    assert "caller_id=internal-operator" in messages
    assert _TOKEN not in messages
    assert "query-secret" not in messages
    assert "Authorization" not in messages


def test_denied_access_log_uses_stable_event_without_credential(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="musimack_tools.security.access")
    response = _client(_SecurityTestService()).get(
        "/api/internal/v1/capabilities?secret=hidden",
        headers={"Authorization": "Bearer wrong-credential"},
    )
    assert response.status_code == 401
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "event=internal_api_authentication_failed" in messages
    assert "wrong-credential" not in messages
    assert "hidden" not in messages


def test_correlation_context_is_cleaned_after_request() -> None:
    client = _client(_SecurityTestService())
    response = client.get(
        "/api/internal/v1/capabilities", headers={"Authorization": f"Bearer {_TOKEN}"}
    )
    assert response.status_code == 200
    assert current_request_id() is None


@pytest.mark.anyio
async def test_concurrent_correlation_contexts_are_isolated() -> None:
    application = create_production_app(
        _SecurityTestService(),
        _settings(),
        Settings(),
    )
    transport = httpx.ASGITransport(app=application, client=("203.0.113.10", 50_000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first, second = await asyncio.gather(
            client.get(
                "/api/internal/v1/capabilities",
                headers={"Authorization": f"Bearer {_TOKEN}", "X-Request-ID": "first"},
            ),
            client.get(
                "/api/internal/v1/capabilities",
                headers={"Authorization": f"Bearer {_TOKEN}", "X-Request-ID": "second"},
            ),
        )
    assert first.json()["request_id"] == "first"
    assert second.json()["request_id"] == "second"
    assert current_request_id() is None


def test_valid_bearer_reaches_every_internal_endpoint_with_real_services() -> None:
    registry = InMemoryJobRegistry(_accepted_run_factory)
    service = SeoToolkitApplicationService(InternalJobService(registry))
    application = create_production_app(service, _settings(), Settings())
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    with TestClient(
        application,
        client=("203.0.113.10", 50_000),
        raise_server_exceptions=False,
    ) as client:
        assert (
            client.post(
                "/api/internal/v1/requests/validate", headers=headers, json=_VALID_BODY
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/internal/v1/requests/preflight", headers=headers, json=_VALID_BODY
            ).status_code
            == 200
        )
        submission = client.post("/api/internal/v1/jobs", headers=headers, json=_VALID_BODY)
        assert submission.status_code == 202
        job_id = submission.json()["data"]["status"]["job_id"]
        for _attempt in range(20):
            status = client.get(f"/api/internal/v1/jobs/{job_id}", headers=headers)
            assert status.status_code == 200
            if status.json()["data"]["terminal"]:
                break
        assert status.json()["data"]["terminal"]
        assert (
            client.get(f"/api/internal/v1/jobs/{job_id}/progress", headers=headers).status_code
            == 200
        )
        assert (
            client.get(f"/api/internal/v1/jobs/{job_id}/result", headers=headers).status_code == 200
        )
        assert (
            client.post(f"/api/internal/v1/jobs/{job_id}/cancel", headers=headers).status_code
            == 409
        )
        assert client.get("/api/internal/v1/registry", headers=headers).status_code == 200
        assert client.get("/api/internal/v1/readiness", headers=headers).status_code == 200
        assert client.get("/api/internal/v1/capabilities", headers=headers).status_code == 200
