"""End-to-end CSA-04 projection over durable crawl/page/artifact authorities."""

# ruff: noqa: FBT003 - immutable test projections are intentionally positional.

from __future__ import annotations

import json
from dataclasses import asdict, replace
from typing import TYPE_CHECKING, cast

import pytest
from sqlalchemy import select

from musimack_tools.artifacts.repository import SQLAlchemyArtifactRepository
from musimack_tools.artifacts.service import ArtifactService
from musimack_tools.domain.application import (
    ApplicationCancellationResult,
    ApplicationJobStatus,
    ApplicationOutcomeCode,
    ApplicationPreflightResult,
    ApplicationRecommendationPage,
    ApplicationResultProjection,
    ApplicationSubmissionResult,
    ApplicationValidationReport,
    PreflightState,
    RecommendationItemProjection,
)
from musimack_tools.domain.artifacts import (
    ArtifactStorageConfiguration,
    ArtifactStorageRootConfiguration,
)
from musimack_tools.domain.job_registry import (
    JobRegistryConfiguration,
    JobRegistryCounters,
    JobRegistrySnapshot,
    RegistryState,
)
from musimack_tools.domain.page_evidence import (
    PageEvidenceConfiguration,
    PageEvidenceListItem,
    PageEvidenceSummary,
    project_crawl_result,
)
from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.domain.site_audit_orchestration import (
    OrchestrationState,
    SiteAuditOrchestrationError,
    SiteAuditStage,
)
from musimack_tools.domain.site_audit_persistence import AuditLifecycle
from musimack_tools.domain.site_audit_settings import default_global_settings
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.migrations import upgrade_to_head
from musimack_tools.persistence.page_evidence_repository import SQLAlchemyPageEvidenceRepository
from musimack_tools.persistence.repositories import SQLAlchemyPersistenceRepository
from musimack_tools.persistence.site_audit_models import SiteAuditDiscoverySourceModel
from musimack_tools.persistence.site_audit_orchestration_repository import (
    SQLAlchemySiteAuditOrchestrationRepository,
)
from musimack_tools.persistence.site_audit_repository import SQLAlchemySiteAuditRepository
from musimack_tools.persistence.site_audit_settings_repository import (
    SQLAlchemySiteAuditSettingsRepository,
)
from musimack_tools.site_audit.orchestration import SiteAuditOrchestrationService, _url_values
from musimack_tools.site_audit.specialists import SpecialistEvidence, SpecialistRequest
from musimack_tools.site_audit_settings.service import (
    SiteAuditSettingsConfiguration,
    SiteAuditSettingsService,
)
from page_evidence_helpers import PageRecordOptions, crawl_result, page_record
from persistence_helpers import BACKEND_ROOT, sample_request, sample_snapshot

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from musimack_tools.domain.application import RawApplicationCrawlRequest
    from musimack_tools.persistence.engine import PersistenceRuntime


def test_only_executed_fetches_project_into_the_fetched_population() -> None:
    page = cast(
        "PageEvidenceListItem",
        project_crawl_result(
            "job-fetch-state",
            "run-fetch-state",
            crawl_result((page_record(),)),
            PageEvidenceConfiguration(enabled=True),
        ).pages[0],
    )

    assert _url_values(page, None)["fetch_state"] == "fetched"
    assert _url_values(replace(page, fetch_outcome="failure"), None)["fetch_state"] == "fetched"
    assert (
        _url_values(
            replace(page, fetch_outcome="robots_denied", http_status=None),
            None,
        )["fetch_state"]
        == "not_fetched"
    )
    assert (
        _url_values(replace(page, fetch_outcome="skipped", http_status=None), None)["fetch_state"]
        == "not_fetched"
    )


class _Gateway:
    def __init__(self, job_id: str, run_id: str) -> None:
        self.job_id = job_id
        self.run_id = run_id
        self.result_job_id = job_id
        self.result_run_id = run_id
        self.state = "completed"
        self.crawl_counts = (
            ("unique_urls_discovered", 2),
            ("urls_admitted", 2),
            ("urls_over_limit", 1),
            ("urls_fetched", 2),
        )
        self.submissions = 0
        self.cancellations = 0
        self.requests: list[RawApplicationCrawlRequest] = []

    def validate(self, request: RawApplicationCrawlRequest) -> ApplicationValidationReport:
        self.requests.append(request)
        return ApplicationValidationReport(
            True,
            (),
            request.seed_url,
            str(request.crawl_profile),
            ("crawl",),
            None,
            "exact host",
            False,
            False,
            self.run_id,
            (),
        )

    async def preflight(self, request: RawApplicationCrawlRequest) -> ApplicationPreflightResult:
        self.requests.append(request)
        return ApplicationPreflightResult(
            PreflightState.READY,
            self.validate(request),
            (),
            JobRegistrySnapshot(
                RegistryState.RUNNING,
                JobRegistryConfiguration(),
                JobRegistryCounters(*(0 for _ in range(13))),
                (),
                (),
                (),
            ),
            None,
            None,
        )

    async def submit(self, request: RawApplicationCrawlRequest) -> ApplicationSubmissionResult:
        self.submissions += 1
        self.requests.append(request)
        return ApplicationSubmissionResult(
            ApplicationOutcomeCode.ACCEPTED,
            ApplicationValidationReport(
                True,
                (),
                request.seed_url,
                str(request.crawl_profile),
                ("crawl",),
                None,
                "exact host",
                False,
                False,
                self.run_id,
                (),
            ),
            self._status(),
            (),
            "accepted",
        )

    async def status(self, job_id: str) -> ApplicationJobStatus:
        assert job_id == self.job_id
        return self._status()

    async def result(self, job_id: str) -> ApplicationResultProjection:
        assert job_id == self.job_id
        return ApplicationResultProjection(
            ApplicationOutcomeCode.FOUND,
            self.result_job_id,
            self.result_run_id,
            1,
            "completed",
            "completed",
            (("crawl", "completed"),),
            self.crawl_counts,
            (),
            (("include", 1), ("exclude", 1)),
            1,
            1,
            None,
            0,
            (),
            None,
            (),
            (),
            (),
            True,
            True,
            "test",
            (),
            crawl_elapsed_seconds=10,
            outbound_request_count=4,
            outbound_redirect_count=1,
            rejected_destination_count=1,
            resolved_address_fingerprints=("parent-fingerprint",),
            robots_outcome_counts=(("success", 1),),
            dns_resolution_count=3,
            robots_request_count=1,
            page_request_count=3,
            accepted_byte_count=1000,
            scope_denial_count=1,
        )

    async def cancel(self, job_id: str) -> ApplicationCancellationResult:
        assert job_id == self.job_id
        self.cancellations += 1
        return ApplicationCancellationResult(
            ApplicationOutcomeCode.FOUND, self._status(), "terminal"
        )

    async def recommendations(
        self, job_id: str, *, offset: int, limit: int
    ) -> ApplicationRecommendationPage:
        assert job_id == self.job_id
        items = (
            RecommendationItemProjection(
                0,
                "https://example.com/",
                "https://example.com/",
                "https://example.com/",
                "include",
                "determinate",
                "eligible",
                "Eligible page",
                200,
                "text/html",
                None,
                "https://example.com/",
                False,
                False,
                0,
                None,
                True,
                True,
                "allowed",
                (),
                (),
                False,
                (),
            ),
            RecommendationItemProjection(
                1,
                "https://example.com/missing-title",
                "https://example.com/missing-title",
                "https://example.com/missing-title",
                "exclude",
                "determinate",
                "noindex",
                "Excluded page",
                200,
                "text/html",
                None,
                None,
                False,
                False,
                0,
                None,
                True,
                True,
                "allowed",
                (),
                (),
                False,
                (),
            ),
        )
        selected = items[offset : offset + limit]
        return ApplicationRecommendationPage(
            ApplicationOutcomeCode.FOUND,
            self.job_id,
            self.run_id,
            offset,
            limit,
            len(items),
            len(selected),
            offset + len(selected) < len(items),
            selected,
            "test",
        )

    def _status(self) -> ApplicationJobStatus:
        return ApplicationJobStatus(
            ApplicationOutcomeCode.FOUND,
            self.job_id,
            self.run_id,
            1,
            self.state,
            None,
            None,
            "completed" if self.state == "completed" else "failed",
            2,
            2,
            (1, 1, 0, 0),
            1,
            1,
            0,
            0,
            0,
            False,
            True,
            True,
            "test",
        )


class _Specialists:
    async def resolve(self, request: SpecialistRequest) -> SpecialistEvidence:
        if request.module is SiteAuditStage.EXISTING_SITEMAP:
            return SpecialistEvidence(
                module=request.module,
                specialist_audit_id="sitemap-fixture",
                execution_source="eligible_prior",
                eligibility_state="eligible",
                eligibility_reason="same_crawl_run",
                freshness_state="current",
                lifecycle_state="completed",
                partial=False,
                evidence_count=0,
                safety_envelope=asdict(request.safety_envelope),
                operational_accounting={
                    "request_count": 8,
                    "dns_operation_count": 2,
                    "accepted_byte_count": 500,
                    "redirect_count": 1,
                    "rejected_destination_count": 0,
                    "scope_denial_count": 1,
                    "robots_request_count": 1,
                    "sitemap_request_count": 7,
                    "retry_count": 0,
                    "timeout_count": 0,
                    "response_size_rejection_count": 0,
                    "resolved_address_fingerprints": ["specialist-fingerprint"],
                    "robots_outcomes": {"success": 1},
                    "sitemap_outcomes": {"success": 7},
                },
            )
        return SpecialistEvidence(
            module=request.module,
            specialist_audit_id=None,
            execution_source="unavailable",
            eligibility_state="unavailable",
            eligibility_reason="no_compatible_specialist_audit",
            freshness_state="unknown",
            lifecycle_state="unavailable",
            partial=False,
            evidence_count=0,
        )


class _SitemapSpecialists(_Specialists):
    async def resolve(self, request: SpecialistRequest) -> SpecialistEvidence:
        result = await super().resolve(request)
        if request.module is not SiteAuditStage.EXISTING_SITEMAP:
            return result
        return SpecialistEvidence(
            module=request.module,
            specialist_audit_id="sitemap-fixture",
            execution_source="linked_child",
            eligibility_state="eligible",
            eligibility_reason="linked_specialist_audit",
            freshness_state="current",
            lifecycle_state="completed",
            partial=False,
            evidence_count=1,
            documents=(
                {
                    "document_id": "sitemap-root",
                    "parse_state": "valid",
                    "depth": 0,
                },
            ),
            entries=(
                {
                    "entry_id": "sitemap-entry",
                    "document_id": "sitemap-root",
                    "raw_location": "https://example.com/sitemap-only",
                    "normalized_identity": "https://example.com/sitemap-only",
                    "entry_sequence": 0,
                    "in_scope": True,
                    "validation_state": "valid",
                    "duplicate": False,
                    "is_child_reference": False,
                },
                {
                    "entry_id": "sitemap-external-entry",
                    "document_id": "sitemap-root",
                    "raw_location": "https://external.example/sitemap-only",
                    "normalized_identity": "https://external.example/sitemap-only",
                    "entry_sequence": 1,
                    "in_scope": False,
                    "validation_state": "out_of_scope",
                    "duplicate": False,
                    "is_child_reference": False,
                },
            ),
        )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def service(
    tmp_path: Path,
) -> Iterator[
    tuple[
        SiteAuditOrchestrationService, SQLAlchemySiteAuditRepository, _Gateway, PersistenceRuntime
    ]
]:
    database = tmp_path / "service.sqlite3"
    upgrade_to_head(f"sqlite+pysqlite:///{database.as_posix()}", backend_root=BACKEND_ROOT)
    runtime = create_persistence_runtime(
        PersistenceConfiguration(
            enabled=True,
            database_path=database,
            page_evidence=PageEvidenceConfiguration(enabled=True),
        )
    )
    request = sample_request("/")
    durable_snapshot = sample_snapshot(request)
    assert (
        SQLAlchemyPersistenceRepository(runtime)
        .record_submission(durable_snapshot, request)
        .succeeded
    )
    pages = SQLAlchemyPageEvidenceRepository(runtime)
    pages.persist_run_page_evidence(
        durable_snapshot.job_id,
        durable_snapshot.run_id,
        crawl_result(
            (
                page_record(
                    "https://example.com/",
                    PageRecordOptions(
                        body=(
                            f"<title>{'A' * 80}</title>"
                            "<meta name='description' content='Stored description'>"
                            "<link rel='canonical' href='/'>"
                        ),
                        x_robots=(),
                    ),
                ),
                page_record(
                    "https://example.com/missing-title",
                    PageRecordOptions(
                        body="<meta name='description' content='Description'>",
                        discovery_order=1,
                        x_robots=(),
                    ),
                ),
            )
        ),
    )
    site = SQLAlchemySiteAuditRepository(runtime)
    gateway = _Gateway(durable_snapshot.job_id, durable_snapshot.run_id)
    root = tmp_path / "artifacts"
    root.mkdir()
    artifacts = ArtifactService(
        ArtifactStorageConfiguration(
            enabled=True,
            roots=(ArtifactStorageRootConfiguration("default", root),),
            allow_csv=True,
        ),
        SQLAlchemyArtifactRepository(runtime),
    )
    assert artifacts.readiness()[0].ready
    try:
        settings = SiteAuditSettingsService(
            SiteAuditSettingsConfiguration(enabled=True),
            SQLAlchemySiteAuditSettingsRepository(runtime),
        )
        enabled_settings = default_global_settings().to_dict()
        enabled_settings["real_site_operations"] = {
            **enabled_settings["real_site_operations"],
            "enabled": True,
        }
        settings.update_settings(enabled_settings, expected_version=0, actor="administrator")
        yield (
            SiteAuditOrchestrationService(
                site,
                SQLAlchemySiteAuditOrchestrationRepository(runtime),
                pages,
                gateway,
                artifacts,
                _Specialists(),
                settings=settings,
            ),
            site,
            gateway,
            runtime,
        )
    finally:
        runtime.dispose()


def _ready_snapshot(site: SQLAlchemySiteAuditRepository) -> None:
    audit = site.create_audit(
        "audit-service",
        audit_name="Service fixture",
        site_label="Example",
        seed_url="https://example.com/",
        normalized_seed_url="https://example.com/",
        draft={"approved_hosts": ["example.com"]},
        created_by="operator",
    )
    for lifecycle in (
        AuditLifecycle.VALIDATING,
        AuditLifecycle.VALIDATED,
        AuditLifecycle.PREFLIGHTING,
        AuditLifecycle.READY,
    ):
        audit = site.transition(
            "audit-service", lifecycle, expected_revision=cast("int", audit["revision"])
        )
    site.create_snapshot(
        "audit-service",
        "snapshot-service",
        {
            "approved_hosts": ["example.com"],
            "scope_policy": {"mode": "exact_host"},
            "crawl_profile": "standard_crawl",
            "crawl_limits": {
                "maximum_urls": 25,
                "maximum_depth": 2,
                "maximum_duration_seconds": 120,
                "maximum_accepted_bytes": 40_000_000,
                "maximum_concurrency": 1,
                "maximum_queue_size": 100,
                "minimum_request_delay_seconds": 2,
                "maximum_redirect_hops": 5,
                "maximum_response_bytes": 3_000_000,
            },
            "enabled_modules": ["images_and_alt_text", "structured_data"],
            "application_version": "test",
        },
        expected_revision=cast("int", audit["revision"]),
    )


@pytest.mark.anyio
async def test_exact_host_draft_derives_snapshot_approved_host(
    service: tuple[
        SiteAuditOrchestrationService,
        SQLAlchemySiteAuditRepository,
        _Gateway,
        PersistenceRuntime,
    ],
) -> None:
    orchestration, repository, gateway, _runtime = service
    audit = orchestration.create_draft(
        {
            "audit_name": "Exact-host fixture",
            "seed_url": "https://Example.com/path",
            "scope_policy": {"mode": "exact_host"},
            "approved_hosts": [],
        },
        actor="operator",
    )
    assert audit["draft"]["approved_hosts"] == ["example.com"]
    validation = orchestration.validate_draft(
        str(audit["audit_id"]), expected_revision=cast("int", audit["revision"])
    )
    assert validation["validation"]["valid"] is True
    audit = validation["audit"]
    for lifecycle in (
        AuditLifecycle.PREFLIGHTING,
        AuditLifecycle.READY,
    ):
        audit = repository.transition(
            str(audit["audit_id"]),
            lifecycle,
            expected_revision=cast("int", audit["revision"]),
        )

    submitted = await orchestration.submit(str(audit["audit_id"]), actor="operator")

    assert submitted["audit"]["lifecycle"] == AuditLifecycle.QUEUED.value
    assert gateway.submissions == 1
    snapshot = repository.snapshot(str(audit["audit_id"]))
    assert snapshot is not None
    assert snapshot["configuration"]["approved_hosts"] == ["example.com"]


@pytest.mark.anyio
async def test_wordpress_rules_resolve_before_validation_preflight_and_submission(
    service: tuple[
        SiteAuditOrchestrationService,
        SQLAlchemySiteAuditRepository,
        _Gateway,
        PersistenceRuntime,
    ],
) -> None:
    orchestration, repository, gateway, _runtime = service
    audit = orchestration.create_draft(
        {
            "audit_name": "WordPress effective rules",
            "seed_url": "https://example.com/",
            "platform_preset_id": "wordpress",
            "platform_preset_version": "wordpress-1",
            "preset_accepted": True,
            "tracking_parameters_accepted": True,
            "scope_policy": {"mode": "exact_host"},
        },
        actor="operator",
    )

    validation = orchestration.validate_draft(
        str(audit["audit_id"]), expected_revision=cast("int", audit["revision"])
    )
    validation_rules = validation["effective_settings"]["effective_rules"]
    assert len(validation_rules) == 19
    assert sum(item["source"] == "preset" for item in validation_rules) == 19
    assert any(item["rule_id"] == "wordpress.cdn_cgi" for item in validation_rules)
    assert not any(item["rule_id"] == "wordpress.wp_json" for item in validation_rules)
    assert any(item["rule_id"] == "tracking.utm_source" for item in validation_rules)

    validated = validation["audit"]
    preflight = await orchestration.preflight_draft(
        str(audit["audit_id"]), expected_revision=cast("int", validated["revision"])
    )
    assert preflight["effective_settings"]["effective_rules"] == validation_rules
    assert preflight["audit"]["lifecycle"] == AuditLifecycle.READY.value

    await orchestration.submit(str(audit["audit_id"]), actor="operator")
    snapshot = repository.snapshot(str(audit["audit_id"]))
    assert snapshot is not None
    assert snapshot["configuration"]["resolution"]["effective_rules"] == validation_rules
    assert len(snapshot["rules"]) == 19
    assert snapshot["configuration"]["operation_mode"] == "real_site"
    assert snapshot["configuration"]["submitted_by"] == "operator"
    assert snapshot["configuration"]["real_site_authorization"]["authorized_by"] == (
        "administrator"
    )
    assert snapshot["configuration"]["outbound_policy_version"] == (
        "seo-toolkit-outbound-destination-policy-v1"
    )
    assert snapshot["configuration"]["crawl_limits"]["maximum_urls"] == 100
    cdn = next(item for item in snapshot["rules"] if item["stable_rule_id"] == "wordpress.cdn_cgi")
    assert cdn["rule_source"] == "preset"
    assert cdn["source_id"] == "wordpress"
    assert cdn["source_version"] == "wordpress-1"
    submitted_request = gateway.requests[-1]
    assert any(item.value == "/cdn-cgi/" for item in submitted_request.exclusion_rules)
    assert not any(item.value == "/wp-json/" for item in submitted_request.exclusion_rules)
    assert "utm_source" in submitted_request.strip_query_parameters


def test_invalid_version_fails_before_validation_transition_or_snapshot(
    service: tuple[
        SiteAuditOrchestrationService,
        SQLAlchemySiteAuditRepository,
        _Gateway,
        PersistenceRuntime,
    ],
) -> None:
    orchestration, repository, gateway, _runtime = service
    audit = orchestration.create_draft(
        {
            "audit_name": "Invalid preset version",
            "seed_url": "https://example.com/",
            "platform_preset_id": "wordpress",
            "platform_preset_version": "wordpress-missing",
            "preset_accepted": True,
        },
        actor="operator",
    )

    with pytest.raises(SiteAuditOrchestrationError, match="site_audit_preset_version_not_found"):
        orchestration.validate_draft(
            str(audit["audit_id"]), expected_revision=cast("int", audit["revision"])
        )

    retained = repository.audit(str(audit["audit_id"]))
    assert retained is not None
    assert retained["lifecycle"] == AuditLifecycle.DRAFT.value
    assert repository.snapshot(str(audit["audit_id"])) is None
    assert gateway.requests == []


def test_global_suspension_blocks_new_real_site_validation_but_not_fixture_validation(
    service: tuple[
        SiteAuditOrchestrationService,
        SQLAlchemySiteAuditRepository,
        _Gateway,
        PersistenceRuntime,
    ],
) -> None:
    orchestration, _repository, _gateway, _runtime = service
    settings = orchestration._settings  # noqa: SLF001 - verifies the composed authority boundary.
    assert settings is not None
    current = settings.settings()
    configuration = dict(cast("dict[str, object]", current["configuration"]))
    operations = dict(cast("dict[str, object]", configuration["real_site_operations"]))
    operations["enabled"] = False
    configuration["real_site_operations"] = operations
    settings.update_settings(
        configuration, expected_version=cast("int", current["version"]), actor="administrator"
    )
    real_audit = orchestration.create_draft(
        {"audit_name": "Suspended", "seed_url": "https://example.com/"}, actor="operator"
    )

    with pytest.raises(SiteAuditOrchestrationError, match="globally suspended"):
        orchestration.validate_draft(
            str(real_audit["audit_id"]), expected_revision=cast("int", real_audit["revision"])
        )

    fixture_audit = orchestration.create_draft(
        {"audit_name": "Fixture", "seed_url": "http://127.0.0.1:13765/"},
        actor="operator",
    )
    result = orchestration.validate_draft(
        str(fixture_audit["audit_id"]),
        expected_revision=cast("int", fixture_audit["revision"]),
    )
    assert result["audit"]["lifecycle"] == "validated"


def test_real_site_defaults_never_raise_a_smaller_selected_profile(
    service: tuple[
        SiteAuditOrchestrationService,
        SQLAlchemySiteAuditRepository,
        _Gateway,
        PersistenceRuntime,
    ],
) -> None:
    orchestration, _repository, _gateway, _runtime = service
    audit = orchestration.create_draft(
        {
            "audit_name": "Quick bounded real site",
            "seed_url": "https://example.com/",
            "crawl_profile": "quick_audit",
        },
        actor="operator",
    )

    result = orchestration.validate_draft(
        str(audit["audit_id"]), expected_revision=cast("int", audit["revision"])
    )
    limits = result["effective_settings"]["crawl_limits"]

    assert limits["maximum_urls"] == 100
    assert limits["maximum_duration_seconds"] == 60
    assert limits["maximum_accepted_bytes"] == 25_000_000
    assert limits["maximum_concurrency"] == 1
    assert limits["minimum_request_delay_seconds"] == 1.0


@pytest.mark.anyio
async def test_invalid_snapshot_configuration_is_rejected_before_persistence(
    service: tuple[
        SiteAuditOrchestrationService,
        SQLAlchemySiteAuditRepository,
        _Gateway,
        PersistenceRuntime,
    ],
) -> None:
    orchestration, repository, gateway, _runtime = service
    audit = orchestration.create_draft(
        {
            "audit_name": "Missing approved hosts",
            "seed_url": "https://example.com/",
            "scope_policy": {"mode": "approved_hosts"},
            "approved_hosts": [],
        },
        actor="operator",
    )
    for lifecycle in (
        AuditLifecycle.VALIDATING,
        AuditLifecycle.VALIDATED,
        AuditLifecycle.PREFLIGHTING,
        AuditLifecycle.READY,
    ):
        audit = repository.transition(
            str(audit["audit_id"]),
            lifecycle,
            expected_revision=cast("int", audit["revision"]),
        )

    with pytest.raises(SiteAuditOrchestrationError, match="At least one approved host"):
        await orchestration.submit(str(audit["audit_id"]), actor="operator")

    assert repository.snapshot(str(audit["audit_id"])) is None
    assert gateway.submissions == 0


@pytest.mark.anyio
async def test_submission_projection_restart_and_artifacts_are_idempotent(
    service: tuple[
        SiteAuditOrchestrationService,
        SQLAlchemySiteAuditRepository,
        _Gateway,
        PersistenceRuntime,
    ],
) -> None:
    orchestration, site, gateway, runtime = service
    _ready_snapshot(site)
    first = await orchestration.submit("audit-service", actor="operator")
    second = await orchestration.submit("audit-service", actor="operator")
    assert first["orchestration"]["crawl_job_id"] == gateway.job_id
    assert second["orchestration"]["crawl_job_id"] == gateway.job_id
    assert gateway.submissions == 1
    completed = await orchestration.reconcile("audit-service")
    assert completed["orchestration"]["state"] in {
        "completed",
        "completed_with_warnings",
        "partially_completed",
    }
    assert orchestration.summary("audit-service")["urls_discovered"] == 2
    accounting = orchestration.summary("audit-service")["operational_accounting"]
    assert accounting["request_count"] == 12
    assert accounting["accepted_byte_count"] == 1500
    assert accounting["redirect_count"] == 2
    assert accounting["scope_denial_count"] == 2
    assert accounting["robots_request_count"] == 2
    assert accounting["sitemap_request_count"] == 7
    assert accounting["resolved_address_fingerprints"] == [
        "parent-fingerprint",
        "specialist-fingerprint",
    ]
    assert accounting["url_admission"] == {
        "admitted": 2,
        "definition": (
            "Over-limit discoveries are retained as rejected admission evidence; "
            "already-queued URLs continue processing."
        ),
        "fetched": 2,
        "over_limit": 1,
    }
    assert orchestration.pages("audit-service")["total"] == 2
    homepage = orchestration.page_detail("audit-service", 0)
    assert homepage["title"] == "A" * 80
    assert homepage["title_length"] == 80
    assert homepage["description"] == "Stored description"
    assert homepage["description_length"] == 18
    assert homepage["canonical"] == "https://example.com/"
    assert orchestration.issues("audit-service")["items"]
    long_title = next(
        item
        for item in orchestration.issues("audit-service")["items"]
        if item["code"] == "long_title"
    )
    assert long_title["affected_url_count"] == 1
    assert len(orchestration.artifact_associations("audit-service")) == 10
    artifacts = {
        item["purpose"]: item for item in orchestration.artifact_associations("audit-service")
    }
    executive = b"".join(
        orchestration._artifacts.prepare_download(  # noqa: SLF001
            str(artifacts["executive_markdown"]["artifact_id"])
        ).iterator_factory()
    ).decode()
    assert f"Lifecycle: {completed['audit']['lifecycle']}" in executive
    assert "1 additional unique discoveries were not admitted" in executive
    configuration = json.loads(
        b"".join(
            orchestration._artifacts.prepare_download(  # noqa: SLF001
                str(artifacts["configuration_snapshot_json"]["artifact_id"])
            ).iterator_factory()
        )
    )
    evidence = json.loads(
        b"".join(
            orchestration._artifacts.prepare_download(  # noqa: SLF001
                str(artifacts["full_evidence_json"]["artifact_id"])
            ).iterator_factory()
        )
    )
    assert configuration["operational_accounting"] == accounting
    assert evidence["operational_accounting"] == accounting
    assert accounting["crawl_elapsed_seconds"] == 10
    assert "crawl_started_at_seconds" not in accounting
    assert "crawl_completed_at_seconds" not in accounting
    restarted = SiteAuditOrchestrationService(
        SQLAlchemySiteAuditRepository(runtime),
        SQLAlchemySiteAuditOrchestrationRepository(runtime),
        SQLAlchemyPageEvidenceRepository(runtime),
        gateway,
        orchestration._artifacts,  # noqa: SLF001 - explicit cross-process test boundary.
        _Specialists(),
        settings=orchestration._settings,  # noqa: SLF001 - restart uses the same authority.
    )
    again = await restarted.reconcile("audit-service")
    assert again["orchestration"]["state"] == completed["orchestration"]["state"]
    assert len(restarted.artifact_associations("audit-service")) == 10
    assert restarted.summary("audit-service")["operational_accounting"] == accounting


@pytest.mark.anyio
async def test_site_audit_submission_carries_unique_execution_identity(
    service: tuple[
        SiteAuditOrchestrationService,
        SQLAlchemySiteAuditRepository,
        _Gateway,
        PersistenceRuntime,
    ],
) -> None:
    orchestration, site, gateway, _runtime = service
    _ready_snapshot(site)

    await orchestration.submit("audit-service", actor="operator")

    submitted = gateway.requests[-1]
    assert submitted.execution_identity == "site-audit:audit-service"
    assert submitted.caller_label == "site-audit:audit-service"


@pytest.mark.anyio
async def test_terminal_persistence_failure_never_projects_historical_evidence(
    service: tuple[
        SiteAuditOrchestrationService,
        SQLAlchemySiteAuditRepository,
        _Gateway,
        PersistenceRuntime,
    ],
) -> None:
    orchestration, site, gateway, _runtime = service
    _ready_snapshot(site)
    await orchestration.submit("audit-service", actor="operator")
    gateway.state = "failed"

    failed = await orchestration.reconcile("audit-service")

    assert failed["orchestration"]["state"] == "failed"
    assert failed["orchestration"]["failure_code"] == "site_audit_terminal_persistence_failed"
    assert failed["audit"]["lifecycle"] == "failed"
    assert orchestration.pages("audit-service")["total"] == 0
    assert orchestration.artifact_associations("audit-service") == ()


@pytest.mark.anyio
async def test_result_owner_mismatch_fails_closed_and_retry_preserves_execution(
    service: tuple[
        SiteAuditOrchestrationService,
        SQLAlchemySiteAuditRepository,
        _Gateway,
        PersistenceRuntime,
    ],
) -> None:
    orchestration, site, gateway, _runtime = service
    _ready_snapshot(site)
    submitted = await orchestration.submit("audit-service", actor="operator")
    run_id = submitted["orchestration"]["crawl_run_id"]
    gateway.result_run_id = "run-historical"

    failed = await orchestration.reconcile("audit-service")

    assert failed["orchestration"]["failure_code"] == "site_audit_execution_owner_mismatch"
    assert orchestration.artifact_associations("audit-service") == ()
    gateway.result_run_id = gateway.run_id
    recovered = await orchestration.retry("audit-service")
    assert recovered["orchestration"]["crawl_run_id"] == run_id
    assert recovered["orchestration"]["retry_count"] == 1
    assert len(orchestration.artifact_associations("audit-service")) == 10


@pytest.mark.anyio
async def test_page_evidence_owner_mismatch_fails_closed(
    service: tuple[
        SiteAuditOrchestrationService,
        SQLAlchemySiteAuditRepository,
        _Gateway,
        PersistenceRuntime,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestration, site, _gateway, _runtime = service
    _ready_snapshot(site)
    await orchestration.submit("audit-service", actor="operator")
    repository = orchestration._page_evidence  # noqa: SLF001
    original = repository.get_summary

    def mismatched(run_id: str) -> PageEvidenceSummary | None:
        summary = original(run_id)
        assert summary is not None
        return replace(summary, job_id="job-historical-0001")

    monkeypatch.setattr(repository, "get_summary", mismatched)

    failed = await orchestration.reconcile("audit-service")

    assert failed["orchestration"]["failure_code"] == "site_audit_evidence_owner_mismatch"
    assert orchestration.pages("audit-service")["total"] == 0
    assert orchestration.artifact_associations("audit-service") == ()


@pytest.mark.anyio
async def test_impossible_population_relationship_fails_before_artifacts(
    service: tuple[
        SiteAuditOrchestrationService,
        SQLAlchemySiteAuditRepository,
        _Gateway,
        PersistenceRuntime,
    ],
) -> None:
    orchestration, site, gateway, _runtime = service
    _ready_snapshot(site)
    await orchestration.submit("audit-service", actor="operator")
    gateway.crawl_counts = (
        ("unique_urls_discovered", 3),
        ("urls_admitted", 1),
        ("urls_fetched", 2),
        ("urls_parsed", 2),
    )

    failed = await orchestration.reconcile("audit-service")

    assert failed["orchestration"]["failure_code"] == "site_audit_population_integrity_failed"
    assert orchestration.artifact_associations("audit-service") == ()


@pytest.mark.anyio
async def test_worker_scan_completes_parent_without_manual_reconcile(
    service: tuple[
        SiteAuditOrchestrationService,
        SQLAlchemySiteAuditRepository,
        _Gateway,
        PersistenceRuntime,
    ],
) -> None:
    orchestration, site, _gateway, _runtime = service
    _ready_snapshot(site)
    await orchestration.submit("audit-service", actor="operator")

    assert await orchestration.reconcile_pending(maximum_parents=1) == 1
    status = orchestration.status("audit-service")
    assert status["orchestration"]["state"] in {
        "completed",
        "completed_with_warnings",
        "partially_completed",
    }
    assert orchestration._orchestration.reconcilable(limit=1) == ()  # noqa: SLF001


@pytest.mark.anyio
async def test_authoritative_sitemap_entries_project_sitemap_only_inventory(
    service: tuple[
        SiteAuditOrchestrationService,
        SQLAlchemySiteAuditRepository,
        _Gateway,
        PersistenceRuntime,
    ],
) -> None:
    orchestration, site, _gateway, _runtime = service
    orchestration._specialists = _SitemapSpecialists()  # noqa: SLF001
    _ready_snapshot(site)
    await orchestration.submit("audit-service", actor="operator")
    await orchestration.reconcile_pending(maximum_parents=1)

    pages = orchestration.pages("audit-service", page_size=50)
    sitemap_only = next(
        item for item in pages["items"] if item["normalized_url"].endswith("sitemap-only")
    )
    assert pages["total"] == 4
    assert sitemap_only["existing_sitemap_state"] == "present"
    assert sitemap_only["fetch_state"] == "not_fetched"
    assert sitemap_only["enqueued_state"] == "not_enqueued"
    external = next(
        item for item in pages["items"] if item["normalized_url"].startswith("https://external")
    )
    assert external["failure_code"] == "scope_denied"
    assert orchestration.summary("audit-service")["failed_urls"] == 0
    assert orchestration.summary("audit-service")["urls_excluded"] == 1
    sitemap = orchestration.sitemap_comparison("audit-service", page_size=50)
    assert sitemap["document_count"] == 0
    assert sitemap["document_preview"] == ()
    assert orchestration.status("audit-service")["specialists"]


@pytest.mark.anyio
async def test_frontier_excluded_link_remains_a_durable_unfetched_discovery(
    tmp_path: Path,
) -> None:
    database = tmp_path / "excluded.sqlite3"
    upgrade_to_head(f"sqlite+pysqlite:///{database.as_posix()}", backend_root=BACKEND_ROOT)
    runtime = create_persistence_runtime(
        PersistenceConfiguration(
            enabled=True,
            database_path=database,
            page_evidence=PageEvidenceConfiguration(enabled=True),
        )
    )
    request = sample_request("/")
    durable_snapshot = sample_snapshot(request)
    SQLAlchemyPersistenceRepository(runtime).record_submission(durable_snapshot, request)
    page_repository = SQLAlchemyPageEvidenceRepository(runtime)
    page_repository.persist_run_page_evidence(
        durable_snapshot.job_id,
        durable_snapshot.run_id,
        crawl_result(
            (
                page_record(
                    "https://example.com/",
                    PageRecordOptions(
                        body=(
                            "<html><title>Seed</title>"
                            "<a href='/missing-title'>Excluded</a>"
                            "<a href='/tracked?utm_source=fixture&amp;id=7'>Tracked</a>"
                            "<a href='/tag/news/'>Overridden tag archive</a>"
                            "</html>"
                        ),
                        x_robots=(),
                    ),
                ),
            )
        ),
    )
    site = SQLAlchemySiteAuditRepository(runtime)
    audit = site.create_audit(
        "audit-excluded",
        audit_name="Excluded fixture",
        site_label="Example",
        seed_url="https://example.com/",
        normalized_seed_url="https://example.com/",
        draft={"approved_hosts": ["example.com"]},
        created_by="operator",
    )
    for lifecycle in (
        AuditLifecycle.VALIDATING,
        AuditLifecycle.VALIDATED,
        AuditLifecycle.PREFLIGHTING,
        AuditLifecycle.READY,
    ):
        audit = site.transition(
            "audit-excluded", lifecycle, expected_revision=cast("int", audit["revision"])
        )
    site.create_snapshot(
        "audit-excluded",
        "snapshot-excluded",
        {
            "approved_hosts": ["example.com"],
            "scope_policy": {"mode": "exact_host"},
            "enabled_modules": [],
            "application_version": "test",
        },
        expected_revision=cast("int", audit["revision"]),
        rules=(
            {
                "stable_rule_id": "exclude-missing-title",
                "rule_source": "site_profile",
                "source_version": "7",
                "decision_layer": "discovery",
                "match_type": "exact_path",
                "match_value": "/missing-title",
                "action": "exclude_from_discovery",
                "enabled": True,
                "priority": 100,
                "specificity": 100,
                "reason_code": "fixture_exclusion",
                "explanation": "The fixture path is excluded before enqueue.",
            },
            {
                "stable_rule_id": "tracking.utm_source",
                "rule_source": "preset",
                "source_version": "wordpress-1",
                "decision_layer": "normalization",
                "match_type": "query_parameter_exists",
                "match_value": "utm_source",
                "action": "strip_query_parameter",
                "enabled": True,
                "priority": 100,
                "specificity": 4,
                "reason_code": "tracking_parameter_strip",
                "explanation": "The accepted tracking parameter is normalized.",
            },
            {
                "stable_rule_id": "wordpress.tag.metadata",
                "rule_source": "preset",
                "source_version": "wordpress-1",
                "decision_layer": "metadata",
                "match_type": "path_starts_with",
                "match_value": "/tag/",
                "action": "crawl_but_exclude_from_metadata_scoring",
                "enabled": True,
                "priority": 100,
                "specificity": 3,
                "reason_code": "wordpress_tag_metadata",
                "explanation": "The inherited tag rule is retained.",
            },
            {
                "stable_rule_id": "audit.tag.review",
                "rule_source": "per_audit",
                "source_version": "1",
                "decision_layer": "discovery",
                "match_type": "path_starts_with",
                "match_value": "/tag/",
                "action": "crawl_and_mark_for_review",
                "enabled": True,
                "priority": 500,
                "specificity": 3,
                "reason_code": "fixture_tag_review",
                "explanation": "The per-audit rule overrides the inherited tag rule.",
                "overrides_rule_ids": ("wordpress.tag.metadata",),
            },
        ),
    )
    root = tmp_path / "excluded-artifacts"
    root.mkdir()
    service = SiteAuditOrchestrationService(
        site,
        SQLAlchemySiteAuditOrchestrationRepository(runtime),
        page_repository,
        _Gateway(durable_snapshot.job_id, durable_snapshot.run_id),
        ArtifactService(
            ArtifactStorageConfiguration(
                enabled=True,
                roots=(ArtifactStorageRootConfiguration("default", root),),
                allow_csv=True,
            ),
            SQLAlchemyArtifactRepository(runtime),
        ),
        _Specialists(),
    )
    try:
        await service.submit("audit-excluded", actor="operator")
        await service.reconcile_pending(maximum_parents=1)
        excluded = next(
            item
            for item in service.pages("audit-excluded")["items"]
            if item["normalized_url"].endswith("missing-title")
        )
        assert excluded["discovery_decision"] == "exclude_from_discovery"
        assert excluded["enqueued_state"] == "not_enqueued"
        assert excluded["fetch_state"] == "not_fetched"
        assert service.rules("audit-excluded")["items"][0]["primary_rule"] is True
        with runtime.transaction() as session:
            source = session.scalar(
                select(SiteAuditDiscoverySourceModel).where(
                    SiteAuditDiscoverySourceModel.audit_id == "audit-excluded",
                    SiteAuditDiscoverySourceModel.source_type == "page_link",
                )
            )
            assert source is not None
            assert source.original_observed_url == "/missing-title"
        assert source.source_evidence_id is not None
        tracked = next(
            item
            for item in service.pages("audit-excluded")["items"]
            if item["normalized_url"].endswith("/tracked?id=7")
        )
        detail = service.page_detail("audit-excluded", int(tracked["sequence"]))
        assert any(
            item["original_observed_url"].endswith("utm_source=fixture&id=7")
            for item in detail["discoveries"]
        )
        assert any(item["decision_layer"] == "normalization" for item in detail["rule_matches"])
        tag = next(
            item
            for item in service.pages("audit-excluded")["items"]
            if item["normalized_url"].endswith("/tag/news/")
        )
        assert tag["discovery_decision"] == "mark_review_before_enqueue"
        assert tag["metadata_scoring_decision"] == "include_in_metadata_scoring"
        tag_detail = service.page_detail("audit-excluded", int(tag["sequence"]))
        assert any(item["primary_rule"] for item in tag_detail["rule_matches"])
        assert any(item["overridden"] for item in tag_detail["rule_matches"])
    finally:
        runtime.dispose()


@pytest.mark.anyio
async def test_failed_parent_retry_uses_same_crawl_and_recovers_audit_lifecycle(
    service: tuple[
        SiteAuditOrchestrationService,
        SQLAlchemySiteAuditRepository,
        _Gateway,
        PersistenceRuntime,
    ],
) -> None:
    orchestration, site, gateway, _runtime = service
    _ready_snapshot(site)
    await orchestration.submit("audit-service", actor="operator")
    orchestration._orchestration.set_state(  # noqa: SLF001 - recovery fixture boundary.
        "audit-service", OrchestrationState.FAILED
    )
    audit = site.audit("audit-service")
    assert audit is not None
    site.transition(
        "audit-service", AuditLifecycle.FAILED, expected_revision=cast("int", audit["revision"])
    )
    recovered = await orchestration.retry("audit-service")
    assert recovered["orchestration"]["retry_count"] == 1
    assert recovered["orchestration"]["state"] in {
        "completed",
        "completed_with_warnings",
        "partially_completed",
    }
    assert recovered["audit"]["lifecycle"] != "failed"
    assert gateway.submissions == 1


@pytest.mark.anyio
async def test_cancellation_is_durable_propagated_and_never_becomes_completion(
    service: tuple[
        SiteAuditOrchestrationService,
        SQLAlchemySiteAuditRepository,
        _Gateway,
        PersistenceRuntime,
    ],
) -> None:
    orchestration, site, gateway, _runtime = service
    _ready_snapshot(site)
    await orchestration.submit("audit-service", actor="operator")
    requested = await orchestration.cancel("audit-service")
    assert requested["orchestration"]["state"] == "cancel_requested"
    assert requested["audit"]["lifecycle"] == "cancel_requested"
    cancelled = await orchestration.reconcile("audit-service")
    assert cancelled["orchestration"]["state"] == "cancelled"
    assert cancelled["audit"]["lifecycle"] == "cancelled"
    assert orchestration.pages("audit-service")["total"] == 0
    assert gateway.cancellations == 2
