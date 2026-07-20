"""End-to-end CSA-04 projection over durable crawl/page/artifact authorities."""

# ruff: noqa: FBT003 - immutable test projections are intentionally positional.

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from sqlalchemy import select

from musimack_tools.artifacts.repository import SQLAlchemyArtifactRepository
from musimack_tools.artifacts.service import ArtifactService
from musimack_tools.domain.application import (
    ApplicationCancellationResult,
    ApplicationJobStatus,
    ApplicationOutcomeCode,
    ApplicationRecommendationPage,
    ApplicationResultProjection,
    ApplicationSubmissionResult,
    ApplicationValidationReport,
    RecommendationItemProjection,
)
from musimack_tools.domain.artifacts import (
    ArtifactStorageConfiguration,
    ArtifactStorageRootConfiguration,
)
from musimack_tools.domain.page_evidence import PageEvidenceConfiguration
from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.domain.site_audit_orchestration import OrchestrationState, SiteAuditStage
from musimack_tools.domain.site_audit_persistence import AuditLifecycle
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.migrations import upgrade_to_head
from musimack_tools.persistence.page_evidence_repository import SQLAlchemyPageEvidenceRepository
from musimack_tools.persistence.repositories import SQLAlchemyPersistenceRepository
from musimack_tools.persistence.site_audit_models import SiteAuditDiscoverySourceModel
from musimack_tools.persistence.site_audit_orchestration_repository import (
    SQLAlchemySiteAuditOrchestrationRepository,
)
from musimack_tools.persistence.site_audit_repository import SQLAlchemySiteAuditRepository
from musimack_tools.site_audit.orchestration import SiteAuditOrchestrationService
from musimack_tools.site_audit.specialists import SpecialistEvidence, SpecialistRequest
from page_evidence_helpers import PageRecordOptions, crawl_result, page_record
from persistence_helpers import BACKEND_ROOT, sample_request, sample_snapshot

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from musimack_tools.domain.application import RawApplicationCrawlRequest
    from musimack_tools.persistence.engine import PersistenceRuntime


class _Gateway:
    def __init__(self, job_id: str, run_id: str) -> None:
        self.job_id = job_id
        self.run_id = run_id
        self.submissions = 0
        self.cancellations = 0

    async def submit(self, request: RawApplicationCrawlRequest) -> ApplicationSubmissionResult:
        self.submissions += 1
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
            self.job_id,
            self.run_id,
            1,
            "completed",
            "completed",
            (("crawl", "completed"),),
            (("unique_urls_discovered", 2), ("urls_fetched", 2)),
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
            "completed",
            None,
            None,
            "completed",
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
                page_record("https://example.com/", PageRecordOptions(x_robots=())),
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
        yield (
            SiteAuditOrchestrationService(
                site,
                SQLAlchemySiteAuditOrchestrationRepository(runtime),
                pages,
                gateway,
                artifacts,
                _Specialists(),
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
    assert orchestration.pages("audit-service")["total"] == 2
    assert orchestration.issues("audit-service")["items"]
    assert len(orchestration.artifact_associations("audit-service")) == 10
    restarted = SiteAuditOrchestrationService(
        SQLAlchemySiteAuditRepository(runtime),
        SQLAlchemySiteAuditOrchestrationRepository(runtime),
        SQLAlchemyPageEvidenceRepository(runtime),
        gateway,
        orchestration._artifacts,  # noqa: SLF001 - explicit cross-process test boundary.
        _Specialists(),
    )
    again = await restarted.reconcile("audit-service")
    assert again["orchestration"]["state"] == completed["orchestration"]["state"]
    assert len(restarted.artifact_associations("audit-service")) == 10


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
    assert pages["total"] == 3
    assert sitemap_only["existing_sitemap_state"] == "present"
    assert sitemap_only["fetch_state"] == "not_fetched"
    assert sitemap_only["enqueued_state"] == "not_enqueued"
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
                            "<html><title>Seed</title><a href='/missing-title'>Excluded</a></html>"
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
