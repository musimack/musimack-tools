"""Private internal API composition, access, endpoint, and security contracts."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from musimack_tools.api.dependencies import permission_for_request
from musimack_tools.api.internal import mount_internal_api
from musimack_tools.application.preparation import ApplicationRequestPreparer
from musimack_tools.application.readiness import capability_report
from musimack_tools.application.service import SeoToolkitApplicationService
from musimack_tools.domain.api import (
    AccessDecision,
    AccessDenialReason,
    AccessOutcome,
    InternalApiConfiguration,
    InternalCallerContext,
)
from musimack_tools.domain.application import (
    ApplicationCancellationResult,
    ApplicationJobList,
    ApplicationJobStatus,
    ApplicationOutcomeCode,
    ApplicationPreflightResult,
    ApplicationProgressResult,
    ApplicationReadinessReport,
    ApplicationRecommendationDetail,
    ApplicationRecommendationPage,
    ApplicationRegistryStatus,
    ApplicationResultProjection,
    ApplicationSubmissionResult,
    ApplicationValidationReport,
    PreflightCode,
    PreflightFinding,
    PreflightState,
    RawApplicationCrawlRequest,
    ReadinessState,
    RecommendationItemProjection,
    ValidationSeverity,
)
from musimack_tools.domain.authentication import Permission, UserRole, permissions_for_role
from musimack_tools.domain.crawl import (
    CrawlConfigurationSnapshot,
    CrawlCounters,
    CrawlRequest,
    CrawlResult,
    CrawlState,
)
from musimack_tools.domain.job import (
    DurableRecommendation,
    DurableRecommendationDetail,
    JobLookupOutcome,
    JobProgressView,
    RecommendationDirectiveGroup,
    RecommendationRuleDetail,
    RecommendationWarningDetail,
)
from musimack_tools.domain.job_registry import (
    JobRegistryConfiguration,
    JobRegistryCounters,
    JobRegistrySnapshot,
    RegistryState,
)
from musimack_tools.domain.run import RunLifecycle, RunStage, RunStageState
from musimack_tools.domain.run_progress import RunEventCode, RunProgressEvent, RunProgressSnapshot
from musimack_tools.jobs.registry import InMemoryJobRegistry
from musimack_tools.jobs.service import InternalJobService
from musimack_tools.main import create_app
from musimack_tools.run.service import CrawlRunService

if TYPE_CHECKING:
    from fastapi import Request

    from musimack_tools.crawl.cancellation import CancellationToken
    from musimack_tools.crawl.orchestrator import ProgressObserver
    from musimack_tools.domain.capabilities import ApplicationCapabilityReport
    from musimack_tools.run.progress import RunProgressSink

_JOB_ID = "job-4f82d76a1b42-0001"
_UNKNOWN_JOB_ID = "job-000000000000-9999"


class _AllowVerifier:
    async def verify(self, request: Request) -> AccessDecision:
        del request
        return AccessDecision(
            AccessOutcome.ALLOWED,
            caller=InternalCallerContext("test-suite"),
        )


class _DenyVerifier:
    async def verify(self, request: Request) -> AccessDecision:
        del request
        return AccessDecision(AccessOutcome.DENIED, AccessDenialReason.ACCESS_DENIED)


class _BrokenVerifier:
    async def verify(self, request: Request) -> AccessDecision:
        del request
        raise RuntimeError("credential-token-must-not-leak")


class _AcceptedFakeCrawler:
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
            counters=CrawlCounters(
                unique_urls_discovered=1,
                urls_queued=1,
                urls_fetched=1,
            ),
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
        _AcceptedFakeCrawler(),
        cancellation=cancellation,
        progress_sink=progress_sink,
    )


class _FakeApplication:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.submission_outcome = ApplicationOutcomeCode.ACCEPTED
        self.preflight_state = PreflightState.READY
        self.readiness_state = ReadinessState.READY
        self.result_outcome = ApplicationOutcomeCode.FOUND
        self.recommendation_detail_outcome = ApplicationOutcomeCode.FOUND
        self.cancellation_outcome = ApplicationOutcomeCode.CANCELLATION_REQUESTED
        self.raise_unexpected = False

    def validate_request(self, raw: RawApplicationCrawlRequest) -> ApplicationValidationReport:
        self.calls.append("validate")
        if self.raise_unexpected:
            raise RuntimeError("sensitive-internal-exception")
        return ApplicationRequestPreparer().prepare(raw).report

    async def preflight(self, raw: RawApplicationCrawlRequest) -> ApplicationPreflightResult:
        self.calls.append("preflight")
        validation = ApplicationRequestPreparer().prepare(raw).report
        code = (
            PreflightCode.IMMEDIATE_CAPACITY
            if self.preflight_state is PreflightState.READY
            else PreflightCode.QUEUE_FULL
        )
        severity = (
            ValidationSeverity.INFO
            if self.preflight_state is PreflightState.READY
            else ValidationSeverity.ERROR
        )
        return ApplicationPreflightResult(
            self.preflight_state,
            validation,
            (PreflightFinding(severity, code, "Bounded preflight finding"),),
            _registry_snapshot(),
            None,
            None,
        )

    async def submit(self, raw: RawApplicationCrawlRequest) -> ApplicationSubmissionResult:
        self.calls.append("submit")
        validation = ApplicationRequestPreparer().prepare(raw).report
        outcome = (
            self.submission_outcome
            if validation.valid
            else ApplicationOutcomeCode.VALIDATION_FAILED
        )
        status = (
            _status()
            if outcome
            in {
                ApplicationOutcomeCode.ACCEPTED,
                ApplicationOutcomeCode.QUEUED,
                ApplicationOutcomeCode.DUPLICATE_RETURNED,
            }
            else None
        )
        return ApplicationSubmissionResult(outcome, validation, status, (), "Bounded submission")

    async def get_job_status(self, job_id: str) -> ApplicationJobStatus:
        self.calls.append("status")
        return _status() if job_id == _JOB_ID else _missing_status()

    async def list_jobs(self) -> ApplicationJobList:
        self.calls.append("list")
        return ApplicationJobList(items=(_status(),), truncated=False, maximum=100)

    async def get_job_progress(self, job_id: str) -> ApplicationProgressResult:
        self.calls.append("progress")
        if job_id != _JOB_ID:
            return ApplicationProgressResult(ApplicationOutcomeCode.JOB_NOT_FOUND, None)
        event1 = _progress_event(1)
        event2 = _progress_event(2)
        return ApplicationProgressResult(
            ApplicationOutcomeCode.FOUND,
            JobProgressView(
                JobLookupOutcome.FOUND,
                event2,
                (event1, event2),
                history_truncated=False,
            ),
        )

    async def get_job_result(self, job_id: str) -> ApplicationResultProjection:
        self.calls.append("result")
        if job_id != _JOB_ID:
            return _result(ApplicationOutcomeCode.JOB_NOT_FOUND)
        return _result(self.result_outcome)

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
        self.calls.append(f"recommendations:{state}:{reason}:{text}")
        if job_id != _JOB_ID:
            return ApplicationRecommendationPage(
                outcome=ApplicationOutcomeCode.JOB_NOT_FOUND,
                job_id=None,
                run_id=None,
                offset=offset,
                limit=limit,
                total=0,
                returned_count=0,
                has_more=False,
                items=(),
                rule_set_version=None,
            )
        item = RecommendationItemProjection(
            sequence=1,
            url="https://example.test/guide",
            requested_url="https://example.test/guide",
            final_url="https://example.test/guide",
            state="include",
            determinacy="determinate",
            primary_reason="eligible",
            explanation="The URL is eligible.",
            http_status=200,
            content_type="text/html",
            fetch_failure_code=None,
            canonical_url="https://example.test/guide",
            canonical_conflicting=False,
            redirect_source=False,
            redirect_hops=0,
            redirect_final_url=None,
            robots_available=True,
            robots_allowed=True,
            robots_reason_code="allowed",
            generic_directives=(),
            crawler_specific_directives=(),
            indexability_conflict=False,
            configured_exclusions=(),
        )
        return ApplicationRecommendationPage(
            outcome=ApplicationOutcomeCode.FOUND,
            job_id=_JOB_ID,
            run_id="run-4f82d76a1b42",
            offset=offset,
            limit=limit,
            total=1,
            returned_count=1,
            has_more=False,
            items=(item,),
            rule_set_version="sitemap-recommendation-v1",
        )

    async def get_job_recommendation_detail(
        self, job_id: str, sequence: int
    ) -> ApplicationRecommendationDetail:
        self.calls.append(f"recommendation_detail:{sequence}")
        if job_id != _JOB_ID:
            return ApplicationRecommendationDetail(ApplicationOutcomeCode.JOB_NOT_FOUND, None)
        if self.recommendation_detail_outcome is not ApplicationOutcomeCode.FOUND:
            return ApplicationRecommendationDetail(self.recommendation_detail_outcome, None)
        if sequence != 1:
            return ApplicationRecommendationDetail(
                ApplicationOutcomeCode.RECOMMENDATION_NOT_FOUND, None
            )
        recommendation = DurableRecommendation(
            sequence=1,
            url="https://example.test/guide",
            requested_url="https://example.test/guide",
            final_url="https://example.test/guide",
            state="exclude",
            determinacy="determinate",
            primary_reason="generic_noindex",
            explanation="Generic indexability evidence contains noindex.",
            http_status=200,
            content_type="text/html",
            fetch_failure_code=None,
            canonical_url="https://example.test/guide",
            canonical_conflicting=False,
            redirect_source=False,
            redirect_hops=0,
            redirect_final_url=None,
            robots_available=True,
            robots_allowed=True,
            robots_reason_code="allowed",
            generic_directives=("noindex",),
            crawler_specific_directives=(),
            indexability_conflict=False,
            configured_exclusions=(),
        )
        return ApplicationRecommendationDetail(
            ApplicationOutcomeCode.FOUND,
            DurableRecommendationDetail(
                recommendation=recommendation,
                reason_codes=("generic_noindex",),
                rule_evidence=(
                    RecommendationRuleDetail(
                        "08_generic_indexability",
                        "hard_exclusion",
                        "generic_noindex",
                        "Trustworthy generic indexability evidence contains noindex",
                    ),
                ),
                warning_details=(
                    RecommendationWarningDetail(
                        "short_title", "The title is short", "html_metadata"
                    ),
                ),
                metadata_warning_codes=("short_title",),
                evidence_id="evidence-safe-1",
                crawl_depth=1,
                fetch_outcome="success",
                evidence_state="complete",
                page_failure_code=None,
                title_presence="single",
                title="Guide",
                description_presence="single",
                meta_description="A safe description.",
                canonical_presence="single",
                meta_robots=(RecommendationDirectiveGroup("robots", ("noindex",)),),
                x_robots_tag=(),
                redirect_chain=(),
                redirect_truncated=False,
                redirect_loop=False,
                sitemap_membership=None,
            ),
        )

    async def cancel_job(self, job_id: str) -> ApplicationCancellationResult:
        self.calls.append("cancel")
        if job_id != _JOB_ID:
            return ApplicationCancellationResult(
                ApplicationOutcomeCode.JOB_NOT_FOUND,
                None,
                "Not found",
            )
        return ApplicationCancellationResult(
            self.cancellation_outcome,
            _status(),
            "Bounded cancellation",
        )

    async def get_registry_status(self) -> ApplicationRegistryStatus:
        self.calls.append("registry")
        readiness = _readiness(self.readiness_state)
        return ApplicationRegistryStatus(_registry_snapshot(), readiness)

    async def get_readiness(self) -> ApplicationReadinessReport:
        self.calls.append("readiness")
        return _readiness(self.readiness_state)

    def get_capabilities(self) -> ApplicationCapabilityReport:
        self.calls.append("capabilities")
        return capability_report()


def _registry_snapshot(state: RegistryState = RegistryState.RUNNING) -> JobRegistrySnapshot:
    counters = JobRegistryCounters(2, 1, 1, 1, 0, 1, 1, 0, 0, 0, 0, 0, 1)
    return JobRegistrySnapshot(
        state,
        JobRegistryConfiguration(),
        counters,
        (_JOB_ID,),
        (),
        (),
    )


def _status() -> ApplicationJobStatus:
    return ApplicationJobStatus(
        outcome=ApplicationOutcomeCode.FOUND,
        job_id=_JOB_ID,
        run_id="run-4f82d76a1b42",
        attempt_number=1,
        state="running",
        queue_position=None,
        active_stage="crawl",
        run_lifecycle="running",
        urls_discovered=4,
        urls_fetched=3,
        recommendation_counts=(1, 1, 1, 1),
        xml_document_count=0,
        xml_entry_count=0,
        publication_file_count=0,
        warning_count=1,
        failure_count=0,
        cancellation_requested=False,
        terminal=False,
        result_available=False,
        registry_version="crawl-job-registry-v1",
    )


def _missing_status() -> ApplicationJobStatus:
    return ApplicationJobStatus(
        outcome=ApplicationOutcomeCode.JOB_NOT_FOUND,
        job_id=None,
        run_id=None,
        attempt_number=None,
        state=None,
        queue_position=None,
        active_stage=None,
        run_lifecycle=None,
        urls_discovered=0,
        urls_fetched=0,
        recommendation_counts=None,
        xml_document_count=None,
        xml_entry_count=None,
        publication_file_count=None,
        warning_count=0,
        failure_count=0,
        cancellation_requested=False,
        terminal=False,
        result_available=False,
        registry_version=None,
    )


def _progress_event(sequence: int) -> RunProgressEvent:
    return RunProgressEvent(
        sequence,
        RunEventCode.CRAWL_PROGRESS,
        RunProgressSnapshot(
            RunLifecycle.RUNNING,
            RunStage.CRAWL,
            RunStageState.RUNNING,
            urls_discovered=sequence,
            urls_fetched=sequence,
            elapsed_seconds=float(sequence),
        ),
        "Bounded progress",
    )


def _result(outcome: ApplicationOutcomeCode) -> ApplicationResultProjection:
    return ApplicationResultProjection(
        outcome=outcome,
        job_id=_JOB_ID if outcome is not ApplicationOutcomeCode.JOB_NOT_FOUND else None,
        run_id=(
            "run-4f82d76a1b42" if outcome is not ApplicationOutcomeCode.JOB_NOT_FOUND else None
        ),
        attempt_number=1 if outcome is not ApplicationOutcomeCode.JOB_NOT_FOUND else None,
        job_state="completed" if outcome is ApplicationOutcomeCode.FOUND else None,
        run_lifecycle="completed" if outcome is ApplicationOutcomeCode.FOUND else None,
        stage_states=(("crawl", "completed"),) if outcome is ApplicationOutcomeCode.FOUND else (),
        crawl_counts=(("urls_fetched", 1),) if outcome is ApplicationOutcomeCode.FOUND else (),
        crawl_error_codes=(),
        recommendation_counts=(
            (("include", 1),) if outcome is ApplicationOutcomeCode.FOUND else ()
        ),
        xml_document_count=1 if outcome is ApplicationOutcomeCode.FOUND else None,
        xml_entry_count=1 if outcome is ApplicationOutcomeCode.FOUND else None,
        publication_state="published" if outcome is ApplicationOutcomeCode.FOUND else None,
        published_file_count=1 if outcome is ApplicationOutcomeCode.FOUND else 0,
        publication_filenames=(("sitemap.xml",) if outcome is ApplicationOutcomeCode.FOUND else ()),
        manifest_sha256="a" * 64 if outcome is ApplicationOutcomeCode.FOUND else None,
        summary_hashes=(),
        warning_codes=(),
        failure_codes=(),
        full_result_retained=outcome is ApplicationOutcomeCode.FOUND,
        summary_payloads_retained=False,
        registry_version=(
            "crawl-job-registry-v1" if outcome is not ApplicationOutcomeCode.JOB_NOT_FOUND else None
        ),
        downstream_versions=(("job_registry", "crawl-job-registry-v1"),),
    )


def _readiness(state: ReadinessState) -> ApplicationReadinessReport:
    return ApplicationReadinessReport(state, (), 1, 0, 1)


def _client(
    service: _FakeApplication,
    *,
    verifier: object | None = None,
    include_schema: bool = True,
    maximum_body: int = 65_536,
) -> TestClient:
    application = FastAPI()
    configuration = InternalApiConfiguration(
        mount_internal_routes=True,
        include_internal_routes_in_schema=include_schema,
        include_internal_endpoints_in_docs=include_schema,
        maximum_request_body_bytes=maximum_body,
        access_verifier=verifier,  # type: ignore[arg-type]
    )
    assert mount_internal_api(application, service, configuration)
    return TestClient(application, raise_server_exceptions=False)


def _request_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "seed_url": "https://example.com",
        "crawl_profile": "quick_audit",
    }
    payload.update(changes)
    return payload


def test_default_app_remains_health_only_without_internal_schema_or_verifier() -> None:
    application = create_app()
    client = TestClient(application)
    assert client.get("/api/health").json() == {
        "application": "Musimack SEO Toolkit",
        "status": "healthy",
    }
    assert sorted(application.openapi()["paths"]) == ["/api/health"]
    assert not any(
        name.startswith("ApplicationRequest")
        for name in application.openapi()["components"]["schemas"]
    )


def test_mount_requires_explicit_configuration() -> None:
    application = FastAPI()
    service = _FakeApplication()
    assert not mount_internal_api(application, service)
    assert not any(
        getattr(route, "path", "").startswith("/api/internal/v1") for route in application.routes
    )
    assert service.calls == []


def test_explicit_routes_are_exact_and_shutdown_is_not_exposed() -> None:
    service = _FakeApplication()
    client = _client(service, verifier=_AllowVerifier())
    paths = set(cast("FastAPI", client.app).openapi()["paths"])
    assert paths == {
        "/api/internal/v1/requests/validate",
        "/api/internal/v1/requests/preflight",
        "/api/internal/v1/jobs",
        "/api/internal/v1/jobs/{job_id}",
        "/api/internal/v1/jobs/{job_id}/progress",
        "/api/internal/v1/jobs/{job_id}/result",
        "/api/internal/v1/jobs/{job_id}/recommendations",
        "/api/internal/v1/jobs/{job_id}/recommendations/{sequence}",
        "/api/internal/v1/jobs/{job_id}/cancel",
        "/api/internal/v1/registry",
        "/api/internal/v1/readiness",
        "/api/internal/v1/capabilities",
    }
    assert all("shutdown" not in path for path in paths)


def test_explicit_routes_can_be_hidden_from_openapi_while_remaining_mounted() -> None:
    service = _FakeApplication()
    client = _client(service, verifier=_AllowVerifier(), include_schema=False)
    assert cast("FastAPI", client.app).openapi()["paths"] == {}
    assert client.get("/api/internal/v1/capabilities").status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/internal/v1/requests/validate"),
        ("post", "/api/internal/v1/requests/preflight"),
        ("post", "/api/internal/v1/jobs"),
        ("get", "/api/internal/v1/jobs"),
        ("get", f"/api/internal/v1/jobs/{_JOB_ID}"),
        ("get", f"/api/internal/v1/jobs/{_JOB_ID}/progress"),
        ("get", f"/api/internal/v1/jobs/{_JOB_ID}/result"),
        ("get", f"/api/internal/v1/jobs/{_JOB_ID}/recommendations"),
        ("get", f"/api/internal/v1/jobs/{_JOB_ID}/recommendations/1"),
        ("post", f"/api/internal/v1/jobs/{_JOB_ID}/cancel"),
        ("get", "/api/internal/v1/registry"),
        ("get", "/api/internal/v1/readiness"),
        ("get", "/api/internal/v1/capabilities"),
    ],
)
def test_missing_verifier_denies_before_service_invocation(method: str, path: str) -> None:
    service = _FakeApplication()
    client = _client(service)
    response = client.request(method, path, json=_request_payload())
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "access_denied"
    assert service.calls == []


def test_deny_and_broken_verifiers_fail_closed_without_secret_echo() -> None:
    for verifier, code in (
        (_DenyVerifier(), "access_denied"),
        (_BrokenVerifier(), "access_verifier_unavailable"),
    ):
        service = _FakeApplication()
        response = _client(service, verifier=verifier).get(
            f"/api/internal/v1/jobs/{_UNKNOWN_JOB_ID}"
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == code
        assert "credential-token" not in response.text
        assert service.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"seed_url": "https://example.com", "crawl_profile": "invalid"},
        {"seed_url": "https://example.com", "approved_hosts": ["x"] * 33},
        {"seed_url": "https://example.com", "unknown": {"secret": "not-echoed"}},
    ],
)
def test_request_validation_errors_use_bounded_standard_envelope(
    payload: dict[str, object],
) -> None:
    service = _FakeApplication()
    response = _client(service, verifier=_AllowVerifier()).post(
        "/api/internal/v1/requests/validate",
        json=payload,
    )
    assert response.status_code == 400
    body = response.json()
    assert body["api_version"] == "seo-toolkit-internal-api-v1"
    assert body["error"]["code"] == "request_validation_failed"
    assert len(body["error"]["details"]) <= 25
    assert "not-echoed" not in response.text
    assert service.calls == []


def test_valid_validation_response_is_exact_and_side_effect_free() -> None:
    service = _FakeApplication()
    response = _client(service, verifier=_AllowVerifier()).post(
        "/api/internal/v1/requests/validate",
        json=_request_payload(),
    )
    assert response.status_code == 200
    body = response.json()
    assert tuple(body) == ("api_version", "request_id", "data", "warnings")
    assert body["api_version"] == "seo-toolkit-internal-api-v1"
    assert body["request_id"] is None
    assert body["data"]["valid"]
    assert service.calls == ["validate"]


@pytest.mark.parametrize(
    "payload",
    [
        _request_payload(seed_url="not-a-url"),
        _request_payload(overrides={"maximum_urls": 50_001}),
        _request_payload(publication_requested=True),
    ],
)
def test_application_validation_failures_are_structured(payload: dict[str, object]) -> None:
    service = _FakeApplication()
    response = _client(service, verifier=_AllowVerifier()).post(
        "/api/internal/v1/requests/validate",
        json=payload,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "application_validation_failed"
    assert response.json()["error"]["details"]


def test_preflight_ready_and_blocked_are_deterministic() -> None:
    service = _FakeApplication()
    client = _client(service, verifier=_AllowVerifier())
    ready = client.post("/api/internal/v1/requests/preflight", json=_request_payload())
    assert ready.status_code == 200
    assert ready.json()["data"]["state"] == "ready"
    service.preflight_state = PreflightState.BLOCKED
    blocked = client.post("/api/internal/v1/requests/preflight", json=_request_payload())
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "preflight_blocked"


@pytest.mark.parametrize(
    ("outcome", "status", "code"),
    [
        (ApplicationOutcomeCode.ACCEPTED, 202, None),
        (ApplicationOutcomeCode.QUEUED, 202, None),
        (ApplicationOutcomeCode.DUPLICATE_RETURNED, 200, None),
        (ApplicationOutcomeCode.ACTIVE_DUPLICATE, 409, "active_duplicate"),
        (ApplicationOutcomeCode.QUEUE_CAPACITY_REACHED, 429, "queue_capacity_reached"),
        (ApplicationOutcomeCode.REGISTRY_CLOSED, 503, "registry_closed"),
        (ApplicationOutcomeCode.INTERNAL_SERVICE_UNAVAILABLE, 503, "internal_service_unavailable"),
    ],
)
def test_submission_outcomes_have_stable_http_mapping(
    outcome: ApplicationOutcomeCode,
    status: int,
    code: str | None,
) -> None:
    service = _FakeApplication()
    service.submission_outcome = outcome
    response = _client(service, verifier=_AllowVerifier()).post(
        "/api/internal/v1/jobs",
        json=_request_payload(),
    )
    assert response.status_code == status
    if code is None:
        assert response.json()["data"]["outcome"] == outcome.value
    else:
        assert response.json()["error"]["code"] == code


@pytest.mark.parametrize(
    "job_id",
    ["", "JOB-4f82d76a1b42-0001", "job%2Fbad", "job id", "x" * 100],
)
def test_malformed_job_ids_return_structured_400(job_id: str) -> None:
    service = _FakeApplication()
    path = f"/api/internal/v1/jobs/{job_id}" if job_id else "/api/internal/v1/jobs/%00"
    response = _client(service, verifier=_AllowVerifier()).get(path)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "job_id_invalid"
    assert "status" not in service.calls


def test_status_unknown_and_found_do_not_leak_internal_objects() -> None:
    service = _FakeApplication()
    client = _client(service, verifier=_AllowVerifier())
    unknown = client.get(f"/api/internal/v1/jobs/{_UNKNOWN_JOB_ID}")
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "job_not_found"
    found = client.get(f"/api/internal/v1/jobs/{_JOB_ID}")
    assert found.status_code == 200
    text = found.text.lower()
    assert all(word not in text for word in ("task", "lock", "token", "callback", "exception"))


def test_live_job_list_is_bounded_and_projects_only_safe_status() -> None:
    service = _FakeApplication()
    response = _client(service, verifier=_AllowVerifier()).get("/api/internal/v1/jobs")
    assert response.status_code == 200
    assert response.json()["data"]["maximum"] == 100
    assert response.json()["data"]["items"][0]["job_id"] == _JOB_ID
    assert all(word not in response.text.lower() for word in ("task", "lock", "token", "callback"))


def test_progress_is_latest_only_by_default_and_history_is_bounded_ordered() -> None:
    service = _FakeApplication()
    client = _client(service, verifier=_AllowVerifier())
    latest = client.get(f"/api/internal/v1/jobs/{_JOB_ID}/progress")
    assert latest.status_code == 200
    assert latest.json()["data"]["latest"]["sequence"] == 2
    assert latest.json()["data"]["history"] == []
    history = client.get(f"/api/internal/v1/jobs/{_JOB_ID}/progress?history_limit=1")
    assert [item["sequence"] for item in history.json()["data"]["history"]] == [2]
    excessive = client.get(f"/api/internal/v1/jobs/{_JOB_ID}/progress?history_limit=51")
    assert excessive.status_code == 400


def test_result_found_unavailable_unknown_and_bounded() -> None:
    service = _FakeApplication()
    client = _client(service, verifier=_AllowVerifier())
    found = client.get(f"/api/internal/v1/jobs/{_JOB_ID}/result")
    assert found.status_code == 200
    assert found.json()["data"]["publication_filenames"] == ["sitemap.xml"]
    assert "xml_bytes" not in found.text
    service.result_outcome = ApplicationOutcomeCode.RESULT_UNAVAILABLE
    unavailable = client.get(f"/api/internal/v1/jobs/{_JOB_ID}/result")
    assert unavailable.status_code == 409
    assert unavailable.json()["error"]["code"] == "job_result_unavailable"
    unknown = client.get(f"/api/internal/v1/jobs/{_UNKNOWN_JOB_ID}/result")
    assert unknown.status_code == 404


def test_recommendation_page_is_bounded_filterable_and_safe() -> None:
    service = _FakeApplication()
    client = _client(service, verifier=_AllowVerifier())
    response = client.get(
        f"/api/internal/v1/jobs/{_JOB_ID}/recommendations",
        params={"limit": 500, "state": "include", "reason": " Eligible ", "text": "guide"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1
    assert response.json()["data"]["items"][0]["url"] == "https://example.test/guide"
    assert service.calls[-1] == "recommendations:include: Eligible :guide"
    assert all(word not in response.text.lower() for word in ("html_body", "storage_path", "token"))
    maximum = client.get(f"/api/internal/v1/jobs/{_JOB_ID}/recommendations?limit=50000")
    assert maximum.status_code == 200
    excessive = client.get(f"/api/internal/v1/jobs/{_JOB_ID}/recommendations?limit=50001")
    assert excessive.status_code == 400
    unknown = client.get(f"/api/internal/v1/jobs/{_UNKNOWN_JOB_ID}/recommendations")
    assert unknown.status_code == 404


def test_recommendation_detail_is_restart_safe_bounded_and_body_free() -> None:
    service = _FakeApplication()
    client = _client(service, verifier=_AllowVerifier())
    response = client.get(f"/api/internal/v1/jobs/{_JOB_ID}/recommendations/1")
    assert response.status_code == 200
    detail = response.json()["data"]
    assert detail["recommendation"]["sequence"] == 1
    assert detail["recommendation"]["state"] == "exclude"
    assert detail["reason_codes"] == ["generic_noindex"]
    assert detail["meta_robots"][0]["directives"] == ["noindex"]
    assert detail["title"] == "Guide"
    assert detail["evidence_id"] == "evidence-safe-1"
    assert all(
        value not in response.text.lower()
        for value in ("html_body", "raw_html", "storage_path", "token", "secret")
    )
    assert client.get(f"/api/internal/v1/jobs/{_JOB_ID}/recommendations/2").status_code == 404
    service.recommendation_detail_outcome = ApplicationOutcomeCode.RESULT_UNAVAILABLE
    legacy = client.get(f"/api/internal/v1/jobs/{_JOB_ID}/recommendations/1")
    assert legacy.status_code == 409
    assert legacy.json()["error"]["code"] == "job_result_unavailable"


def test_recommendation_detail_authorization_matches_the_list_for_every_supported_role() -> None:
    list_path = f"/api/internal/v1/jobs/{_JOB_ID}/recommendations"
    detail_path = f"{list_path}/1"
    assert permission_for_request("GET", list_path) is Permission.RUNS_VIEW
    assert permission_for_request("GET", detail_path) is Permission.RUNS_VIEW
    for role in UserRole:
        assert Permission.RUNS_VIEW in permissions_for_role(role)


@pytest.mark.parametrize(
    ("outcome", "status", "code"),
    [
        (ApplicationOutcomeCode.CANCELLATION_REQUESTED, 202, None),
        (ApplicationOutcomeCode.CANCELLED_WHILE_QUEUED, 202, None),
        (ApplicationOutcomeCode.ALREADY_REQUESTED, 200, None),
        (ApplicationOutcomeCode.ALREADY_TERMINAL, 409, "job_already_terminal"),
        (ApplicationOutcomeCode.REGISTRY_CLOSED, 503, "registry_closed"),
    ],
)
def test_cancellation_outcomes_are_cooperative_and_stable(
    outcome: ApplicationOutcomeCode,
    status: int,
    code: str | None,
) -> None:
    service = _FakeApplication()
    service.cancellation_outcome = outcome
    response = _client(service, verifier=_AllowVerifier()).post(
        f"/api/internal/v1/jobs/{_JOB_ID}/cancel"
    )
    assert response.status_code == status
    assert "task.cancel" not in response.text.lower()
    if code is not None:
        assert response.json()["error"]["code"] == code


def test_registry_readiness_and_capabilities_are_bounded() -> None:
    service = _FakeApplication()
    client = _client(service, verifier=_AllowVerifier())
    registry = client.get("/api/internal/v1/registry")
    assert registry.status_code == 200
    assert registry.json()["data"]["registry"]["active_jobs"] == 1
    assert "active_job_ids" not in registry.text
    assert client.get("/api/internal/v1/readiness").status_code == 200
    service.readiness_state = ReadinessState.DEGRADED
    assert client.get("/api/internal/v1/readiness").status_code == 200
    service.readiness_state = ReadinessState.NOT_READY
    assert client.get("/api/internal/v1/readiness").status_code == 503
    capabilities = client.get("/api/internal/v1/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["data"]["supported"][0] == "crawl"
    assert capabilities.json()["data"]["unsupported"][0] == "public_api"


def test_unexpected_exception_is_safe_and_request_body_is_not_echoed() -> None:
    service = _FakeApplication()
    service.raise_unexpected = True
    response = _client(service, verifier=_AllowVerifier()).post(
        "/api/internal/v1/requests/validate",
        json=_request_payload(seed_url="https://example.com/?token=secret-value"),
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_api_error"
    assert "sensitive-internal-exception" not in response.text
    assert "secret-value" not in response.text


def test_declared_request_body_limit_is_enforced_after_access() -> None:
    service = _FakeApplication()
    client = _client(service, verifier=_AllowVerifier(), maximum_body=10)
    response = client.post(
        "/api/internal/v1/requests/validate",
        json=_request_payload(),
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_body_too_large"
    assert service.calls == []


def test_end_to_end_api_uses_accepted_job_and_run_services() -> None:
    registry = InMemoryJobRegistry(_accepted_run_factory)
    service = SeoToolkitApplicationService(InternalJobService(registry))
    application = FastAPI()
    configuration = InternalApiConfiguration(
        mount_internal_routes=True,
        include_internal_routes_in_schema=True,
        include_internal_endpoints_in_docs=True,
        access_verifier=_AllowVerifier(),
    )
    assert mount_internal_api(application, service, configuration)
    with TestClient(application) as client:
        validation = client.post(
            "/api/internal/v1/requests/validate",
            json=_request_payload(),
        )
        assert validation.status_code == 200
        preflight = client.post(
            "/api/internal/v1/requests/preflight",
            json=_request_payload(),
        )
        assert preflight.status_code == 200
        submitted = client.post("/api/internal/v1/jobs", json=_request_payload())
        assert submitted.status_code == 202
        job_id = submitted.json()["data"]["status"]["job_id"]
        status_body: dict[str, object] = {}
        for _attempt in range(20):
            status = client.get(f"/api/internal/v1/jobs/{job_id}")
            assert status.status_code == 200
            status_body = status.json()["data"]
            if status_body["terminal"]:
                break
        assert status_body["terminal"]
        progress = client.get(f"/api/internal/v1/jobs/{job_id}/progress")
        assert progress.status_code == 200
        result = client.get(f"/api/internal/v1/jobs/{job_id}/result")
        assert result.status_code == 200
        assert result.json()["data"]["crawl_counts"] == [
            {"name": "urls_discovered", "count": 1},
            {"name": "urls_fetched", "count": 1},
            {"name": "urls_parsed", "count": 0},
            {"name": "accepted_bytes", "count": 10},
        ]
        assert client.get("/api/internal/v1/registry").status_code == 200
        assert client.get("/api/internal/v1/readiness").status_code == 200
        assert client.get("/api/internal/v1/capabilities").status_code == 200
        assert client.post("/api/internal/v1/shutdown").status_code == 404
