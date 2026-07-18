"""Phase 21 safe-fetch service, persistence, exports, API, and composition tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_production_security import _SecurityTestService

from musimack_tools.api.dependencies import permission_for_request
from musimack_tools.artifacts.repository import SQLAlchemyArtifactRepository
from musimack_tools.artifacts.service import ArtifactService
from musimack_tools.authentication.service import AuthenticationService
from musimack_tools.blog_strategy.repository import BlogStrategyRepository
from musimack_tools.blog_strategy.service import BlogStrategyService
from musimack_tools.core.config import Settings
from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import create_scope_policy
from musimack_tools.deployment.application import create_production_app
from musimack_tools.deployment.settings import ProductionSettings
from musimack_tools.domain.artifacts import (
    ArtifactStorageConfiguration,
    ArtifactStorageRootConfiguration,
)
from musimack_tools.domain.authentication import (
    AuthenticationConfiguration,
    AuthenticationMode,
    Permission,
)
from musimack_tools.domain.fetching import FetchOutcome, FetchRequest, FetchResult, ResponseHeaders
from musimack_tools.domain.history import HistoryConfiguration
from musimack_tools.domain.internal_link import InternalLinkConfiguration
from musimack_tools.domain.job import JobState
from musimack_tools.domain.link_audit import LinkAuditConfiguration
from musimack_tools.domain.metadata_audit import MetadataAuditConfiguration
from musimack_tools.domain.page_evidence import PageEvidenceConfiguration
from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.domain.sitemap_audit import (
    DiscoveryOptions,
    ExportFormat,
    SitemapAuditConfiguration,
)
from musimack_tools.domain.urls import ScopeMode
from musimack_tools.history.service import HistoryService
from musimack_tools.internal_link.service import InternalLinkAuditService
from musimack_tools.link_audit.service import LinkAuditService
from musimack_tools.main import create_app
from musimack_tools.metadata_audit.service import MetadataAuditService
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.history_repository import SQLAlchemyHistoryRepository
from musimack_tools.persistence.internal_link_repository import SQLAlchemyInternalLinkRepository
from musimack_tools.persistence.link_audit_repository import SQLAlchemyLinkAuditRepository
from musimack_tools.persistence.metadata_audit_repository import SQLAlchemyMetadataAuditRepository
from musimack_tools.persistence.migrations import upgrade_to_head
from musimack_tools.persistence.models import ConfigurationSnapshotModel, RunModel
from musimack_tools.persistence.repositories import SQLAlchemyPersistenceRepository
from musimack_tools.persistence.sitemap_audit_models import (
    SitemapAuditEventModel,
    SitemapAuditModel,
)
from musimack_tools.persistence.sitemap_audit_repository import SQLAlchemySitemapAuditRepository
from musimack_tools.sitemap_audit.service import SitemapAuditService
from page_evidence_helpers import PageRecordOptions, crawl_result, page_record
from persistence_helpers import BACKEND_ROOT, sample_request, sample_result, sample_snapshot

if TYPE_CHECKING:
    from pathlib import Path

    from musimack_tools.domain.run import CrawlRunRequest
    from musimack_tools.domain.urls import CrawlScopePolicy
    from musimack_tools.persistence.engine import PersistenceRuntime

_TOKEN = "phase-21-internal-test-token-value-123456789"  # noqa: S105
_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
_FIXTURE_FAILURE = "deterministic fixture failure"


class FakeFetcher:
    def __init__(self, responses: dict[str, tuple[int, str, bytes]]) -> None:
        self.responses = responses
        self.requests: list[str] = []

    async def fetch(self, request: FetchRequest, scope: CrawlScopePolicy) -> FetchResult:
        del scope
        url = request.url.normalized
        self.requests.append(url)
        status, content_type, body = self.responses.get(url, (404, "text/html", b"not found"))
        return FetchResult(
            requested_url=url,
            final_url=url,
            outcome=FetchOutcome.SUCCESS,
            status_code=status,
            headers=ResponseHeaders(content_type=content_type),
            content_type=content_type,
            declared_content_length=len(body),
            actual_bytes_read=len(body),
            body_truncated=False,
            redirect_chain=(),
            request_duration_seconds=0.01,
            dns_evidence=(),
            failure_code=None,
            failure_explanation=None,
            body=body,
        )


class BlockingFetcher(FakeFetcher):
    def __init__(self, responses: dict[str, tuple[int, str, bytes]]) -> None:
        super().__init__(responses)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def fetch(self, request: FetchRequest, scope: CrawlScopePolicy) -> FetchResult:
        self.started.set()
        await self.release.wait()
        return await super().fetch(request, scope)


class RaisingFetcher(FakeFetcher):
    async def fetch(self, request: FetchRequest, scope: CrawlScopePolicy) -> FetchResult:
        del request, scope
        raise RuntimeError(_FIXTURE_FAILURE)


class RedirectAliasFetcher(FakeFetcher):
    def __init__(
        self,
        responses: dict[str, tuple[int, str, bytes]],
        final_urls: dict[str, str],
    ) -> None:
        super().__init__(responses)
        self.final_urls = final_urls

    async def fetch(self, request: FetchRequest, scope: CrawlScopePolicy) -> FetchResult:
        result = await super().fetch(request, scope)
        return replace(
            result, final_url=self.final_urls.get(request.url.normalized, result.final_url)
        )


def _service(
    tmp_path: Path,
    responses: dict[str, tuple[int, str, bytes]],
    *,
    artifacts: bool = False,
    request: CrawlRunRequest | None = None,
    configuration: SitemapAuditConfiguration | None = None,
) -> tuple[PersistenceRuntime, SitemapAuditService, str, FakeFetcher, ArtifactService | None]:
    database = tmp_path / "sitemap-audit.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    upgrade_to_head(url, backend_root=BACKEND_ROOT)
    selected_configuration = configuration or SitemapAuditConfiguration(
        enabled=True, default_page_size=2, maximum_page_size=20, maximum_documents=10
    )
    runtime = create_persistence_runtime(
        PersistenceConfiguration(
            enabled=True,
            database_path=database,
            page_evidence=PageEvidenceConfiguration(enabled=True),
            sitemap_audit=selected_configuration,
        )
    )
    selected_request = request or sample_request()
    snapshot = sample_snapshot(selected_request)
    persistence = SQLAlchemyPersistenceRepository(runtime)
    assert persistence.record_submission(snapshot, selected_request).succeeded
    result = replace(
        sample_result(selected_request),
        crawl_result=crawl_result(
            (
                page_record(),
                page_record(
                    "https://example.com/two",
                    PageRecordOptions(discovery_order=1),
                ),
            )
        ),
    )
    terminal = replace(
        snapshot,
        state=JobState.COMPLETED,
        run_lifecycle=result.lifecycle,
        final_result_available=True,
        terminal=True,
    )
    assert persistence.record_terminal(terminal, result, (), None).succeeded
    artifact_service = None
    if artifacts:
        root = tmp_path / "artifacts"
        root.mkdir()
        artifact_service = ArtifactService(
            ArtifactStorageConfiguration(
                enabled=True,
                roots=(ArtifactStorageRootConfiguration("audit-root", root),),
                default_root_id="audit-root",
                allow_csv=True,
            ),
            SQLAlchemyArtifactRepository(runtime),
        )
    fetcher = FakeFetcher(responses)
    service = SitemapAuditService(
        selected_configuration,
        SQLAlchemySitemapAuditRepository(runtime),
        fetcher,
        artifact_service,
    )
    return runtime, service, snapshot.run_id, fetcher, artifact_service


def _request_with_scope(mode: ScopeMode, approved_hosts: tuple[str, ...] = ()) -> CrawlRunRequest:
    request = sample_request()
    seed = normalize_url(request.crawl_request.seed_url.normalized)
    crawl = replace(
        request.crawl_request,
        scope_policy=create_scope_policy(seed, mode=mode, approved_hosts=approved_hosts),
    )
    return replace(request, crawl_request=crawl)


def test_audit_fetches_explicit_url_and_compares_durable_evidence(tmp_path: Path) -> None:
    root = "https://example.com/sitemap.xml"
    xml = f'<urlset xmlns="{_NS}"><url><loc>https://example.com/</loc></url></urlset>'.encode()
    runtime, service, run_id, fetcher, _ = _service(tmp_path, {root: (200, "application/xml", xml)})
    try:
        audit = asyncio.run(
            service.create_and_run(
                run_id,
                DiscoveryOptions(root, discover_robots=False, discover_common_locations=False),
            )
        )
        assert audit["document_count"] == 1
        assert audit["comparison_count"] == 2
        assert (
            audit["add_count"]
            + audit["remove_count"]
            + audit["review_count"]
            + audit["unchanged_count"]
            == 2
        )
        assert fetcher.requests == [root]
        assert service.list_documents(audit["audit_id"])
        assert service.list_entries(audit["audit_id"])
        first_page = service.list_comparisons(audit["audit_id"], offset=0, page_size=1)
        second_page = service.list_comparisons(audit["audit_id"], offset=1, page_size=1)
        assert len(first_page) == len(second_page) == 1
        assert first_page[0]["comparison_id"] != second_page[0]["comparison_id"]
        filtered = service.list_comparisons(
            audit["audit_id"],
            page_size=20,
            filters={"action": first_page[0]["action"], "url": "example.com"},
        )
        assert filtered
        assert all(item["action"] == first_page[0]["action"] for item in filtered)
    finally:
        runtime.dispose()


def test_accept_and_execute_are_separate_durable_requests(tmp_path: Path) -> None:
    root = "https://example.com/sitemap.xml"
    xml = f'<urlset xmlns="{_NS}"><url><loc>https://example.com/</loc></url></urlset>'.encode()
    runtime, service, run_id, _fetcher, _ = _service(
        tmp_path, {root: (200, "application/xml", xml)}
    )
    try:
        accepted = service.create_audit(
            run_id,
            DiscoveryOptions(root, discover_robots=False, discover_common_locations=False),
        )
        assert accepted["state"] == "accepted"
        completed = asyncio.run(service.execute_audit(accepted["audit_id"]))
        assert completed["state"] == "completed"
        with pytest.raises(ValueError, match="sitemap_audit_already_exists"):
            asyncio.run(service.execute_audit(accepted["audit_id"]))
    finally:
        runtime.dispose()


def test_duplicate_execution_is_atomically_rejected_and_lifecycle_is_observable(
    tmp_path: Path,
) -> None:
    root = "https://example.com/sitemap.xml"
    xml = f'<urlset xmlns="{_NS}"><url><loc>https://example.com/</loc></url></urlset>'.encode()
    runtime, seeded, run_id, _fetcher, _ = _service(tmp_path, {})
    blocking = BlockingFetcher({root: (200, "application/xml", xml)})
    service = SitemapAuditService(
        seeded.configuration,
        SQLAlchemySitemapAuditRepository(runtime),
        blocking,
    )
    accepted = service.create_audit(
        run_id,
        DiscoveryOptions(root, discover_robots=False, discover_common_locations=False),
    )

    async def scenario() -> None:
        execution = asyncio.create_task(service.execute_audit(accepted["audit_id"]))
        await blocking.started.wait()
        assert service.get(accepted["audit_id"])["state"] == "fetching"
        with pytest.raises(ValueError, match="sitemap_audit_already_exists"):
            await service.execute_audit(accepted["audit_id"])
        blocking.release.set()
        assert (await execution)["state"] == "completed"

    try:
        asyncio.run(scenario())
        with runtime.transaction() as database:
            states = tuple(
                database.scalars(
                    select(SitemapAuditEventModel.event_type)
                    .where(SitemapAuditEventModel.audit_id == accepted["audit_id"])
                    .order_by(SitemapAuditEventModel.sequence)
                )
            )
        assert states[0:3] == ("created", "discovering", "fetching")
        assert states[-1] == "completed"
    finally:
        runtime.dispose()


def test_execution_failure_and_restart_interruption_are_terminal(tmp_path: Path) -> None:
    root = "https://example.com/sitemap.xml"
    runtime, seeded, run_id, _fetcher, _ = _service(tmp_path, {})
    repository = SQLAlchemySitemapAuditRepository(runtime)
    failing = SitemapAuditService(seeded.configuration, repository, RaisingFetcher({}))
    accepted = failing.create_audit(
        run_id,
        DiscoveryOptions(root, discover_robots=False, discover_common_locations=False),
    )
    try:
        with pytest.raises(RuntimeError, match="fixture failure"):
            asyncio.run(failing.execute_audit(accepted["audit_id"]))
        failed = failing.get(accepted["audit_id"])
        assert failed["state"] == "failed"
        assert failed["failure_code"] == "sitemap_audit_execution_failed"

        second = failing.create_audit(
            run_id,
            DiscoveryOptions(
                "https://example.com/other.xml",
                discover_robots=False,
                discover_common_locations=False,
            ),
        )
        assert repository.claim_execution(second["audit_id"])
        restarted = SitemapAuditService(seeded.configuration, repository, FakeFetcher({}))
        interrupted = restarted.get(second["audit_id"])
        assert interrupted["state"] == "failed"
        assert interrupted["failure_code"] == "sitemap_audit_execution_interrupted"
    finally:
        runtime.dispose()


def test_discovery_preserves_explicit_robots_common_order_and_deduplicates(tmp_path: Path) -> None:
    robots = (
        b"Sitemap: https://example.com/robots-map.xml\nSITEMAP:https://example.com/sitemap.xml\n"
    )
    runtime, service, run_id, fetcher, _ = _service(
        tmp_path, {"https://example.com/robots.txt": (200, "text/plain", robots)}
    )
    try:
        candidates, findings = asyncio.run(
            service.discover(run_id, DiscoveryOptions("https://example.com/sitemap.xml"))
        )
        assert not findings
        assert [item.normalized_url for item in candidates] == [
            "https://example.com/sitemap.xml",
            "https://example.com/robots-map.xml",
            "https://example.com/sitemap_index.xml",
            "https://example.com/wp-sitemap.xml",
        ]
        assert candidates[0].provenance == (
            candidates[0].discovery_source,
            candidates[1].discovery_source,
            candidates[2].discovery_source,
        )
        assert fetcher.requests == ["https://example.com/robots.txt"]
    finally:
        runtime.dispose()


def test_nested_index_expands_once_and_preserves_parent_child_inventory(tmp_path: Path) -> None:
    root = "https://example.com/index.xml"
    child = "https://example.com/child.xml"
    index = (
        f'<sitemapindex xmlns="{_NS}"><sitemap><loc>{child}</loc></sitemap></sitemapindex>'.encode()
    )
    urlset = (
        f'<urlset xmlns="{_NS}"><url><loc>https://example.com/two</loc></url></urlset>'.encode()
    )
    runtime, service, run_id, fetcher, _ = _service(
        tmp_path,
        {root: (200, "application/xml", index), child: (200, "application/xml", urlset)},
    )
    try:
        audit = asyncio.run(
            service.create_and_run(
                run_id,
                DiscoveryOptions(root, discover_robots=False, discover_common_locations=False),
            )
        )
        documents = service.list_documents(audit["audit_id"], page_size=20)
        assert len(documents) == 2
        assert documents[1]["parent_document_id"] == documents[0]["document_id"]
        assert fetcher.requests == [root, child]
    finally:
        runtime.dispose()


def test_redirect_aliases_are_fetched_once_per_final_identity(tmp_path: Path) -> None:
    first = "https://example.com/first.xml"
    second = "https://example.com/second.xml"
    final = "https://example.com/canonical.xml"
    robots = f"Sitemap: {first}\nSitemap: {second}\n".encode()
    xml = f'<urlset xmlns="{_NS}"><url><loc>https://example.com/</loc></url></urlset>'.encode()
    runtime, seeded, run_id, _fetcher, _ = _service(tmp_path, {})
    fetcher = RedirectAliasFetcher(
        {
            "https://example.com/robots.txt": (200, "text/plain", robots),
            first: (200, "application/xml", xml),
            second: (200, "application/xml", xml),
        },
        {first: final, second: final},
    )
    service = SitemapAuditService(
        seeded.configuration,
        SQLAlchemySitemapAuditRepository(runtime),
        fetcher,
    )
    try:
        audit = asyncio.run(
            service.create_and_run(
                run_id,
                DiscoveryOptions(
                    discover_robots=True,
                    discover_common_locations=False,
                ),
            )
        )
        assert fetcher.requests == ["https://example.com/robots.txt", first, second]
        assert any(
            item["code"] == "redirect_alias_duplicate"
            for item in service.list_findings(audit["audit_id"], page_size=20)
        )
    finally:
        runtime.dispose()


def test_index_loop_and_partial_child_failure_reach_durable_terminal_states(tmp_path: Path) -> None:
    loop_root = "https://example.com/loop.xml"
    indirect_root = "https://example.com/indirect.xml"
    indirect_child = "https://example.com/indirect-child.xml"
    partial_root = "https://example.com/partial.xml"
    missing_child = "https://example.com/missing-child.xml"
    responses = {
        loop_root: (
            200,
            "application/xml",
            (
                f'<sitemapindex xmlns="{_NS}"><sitemap><loc>{loop_root}</loc>'
                "</sitemap></sitemapindex>"
            ).encode(),
        ),
        indirect_root: (
            200,
            "application/xml",
            (
                f'<sitemapindex xmlns="{_NS}"><sitemap><loc>{indirect_child}</loc>'
                "</sitemap></sitemapindex>"
            ).encode(),
        ),
        indirect_child: (
            200,
            "application/xml",
            (
                f'<sitemapindex xmlns="{_NS}"><sitemap><loc>{indirect_root}</loc>'
                "</sitemap></sitemapindex>"
            ).encode(),
        ),
        partial_root: (
            200,
            "application/xml",
            (
                f'<sitemapindex xmlns="{_NS}"><sitemap><loc>{missing_child}</loc>'
                "</sitemap></sitemapindex>"
            ).encode(),
        ),
    }
    runtime, service, run_id, _fetcher, _ = _service(tmp_path, responses)
    try:
        loop = asyncio.run(
            service.create_and_run(
                run_id,
                DiscoveryOptions(
                    loop_root,
                    discover_robots=False,
                    discover_common_locations=False,
                ),
            )
        )
        assert loop["state"] == "completed_with_warnings"
        assert any(
            item["code"] == "sitemap_index_loop"
            for item in service.list_findings(loop["audit_id"], page_size=20)
        )

        indirect = asyncio.run(
            service.create_and_run(
                run_id,
                DiscoveryOptions(
                    indirect_root,
                    discover_robots=False,
                    discover_common_locations=False,
                ),
            )
        )
        assert any(
            item["code"] == "sitemap_index_loop"
            for item in service.list_findings(indirect["audit_id"], page_size=20)
        )

        partial = asyncio.run(
            service.create_and_run(
                run_id,
                DiscoveryOptions(
                    partial_root,
                    discover_robots=False,
                    discover_common_locations=False,
                ),
            )
        )
        assert partial["state"] == "partially_completed"
        assert any(
            item["code"] == "child_fetch_failed"
            for item in service.list_findings(partial["audit_id"], page_size=20)
        )
    finally:
        runtime.dispose()


@pytest.mark.parametrize(
    ("configuration", "root_body", "finding_code"),
    [
        (
            SitemapAuditConfiguration(enabled=True, maximum_documents=1),
            (
                f'<sitemapindex xmlns="{_NS}"><sitemap><loc>'
                "https://example.com/child.xml</loc></sitemap></sitemapindex>"
            ),
            "sitemap_document_limit_exceeded",
        ),
        (
            SitemapAuditConfiguration(enabled=True, maximum_depth=0),
            (
                f'<sitemapindex xmlns="{_NS}"><sitemap><loc>'
                "https://example.com/child.xml</loc></sitemap></sitemapindex>"
            ),
            "maximum_depth_exceeded",
        ),
        (
            SitemapAuditConfiguration(enabled=True, maximum_total_urls=1),
            (
                f'<urlset xmlns="{_NS}"><url><loc>https://example.com/one</loc></url>'
                "<url><loc>https://example.com/two</loc></url></urlset>"
            ),
            "total_url_limit_exceeded",
        ),
    ],
)
def test_recursive_document_depth_and_total_url_limits_are_durable(
    tmp_path: Path,
    configuration: SitemapAuditConfiguration,
    root_body: str,
    finding_code: str,
) -> None:
    root = "https://example.com/limit.xml"
    runtime, service, run_id, _fetcher, _ = _service(
        tmp_path,
        {root: (200, "application/xml", root_body.encode())},
        configuration=configuration,
    )
    try:
        audit = asyncio.run(
            service.create_and_run(
                run_id,
                DiscoveryOptions(root, discover_robots=False, discover_common_locations=False),
            )
        )
        assert audit["state"] == "partially_completed"
        assert finding_code in {
            item["code"] for item in service.list_findings(audit["audit_id"], page_size=200)
        }
    finally:
        runtime.dispose()


def test_gzip_is_durable_unsupported_finding(tmp_path: Path) -> None:
    root = "https://example.com/sitemap.xml.gz"
    runtime, service, run_id, _fetcher, _ = _service(
        tmp_path, {root: (200, "application/gzip", b"\x1f\x8bunsafe")}
    )
    try:
        audit = asyncio.run(
            service.create_and_run(
                run_id,
                DiscoveryOptions(root, discover_robots=False, discover_common_locations=False),
            )
        )
        findings = service.list_findings(audit["audit_id"], page_size=20)
        assert any(item["code"] == "gzip_not_supported" for item in findings)
    finally:
        runtime.dispose()


def test_audit_fails_only_when_no_valid_root_can_be_ingested(tmp_path: Path) -> None:
    root = "https://example.com/missing.xml"
    runtime, service, run_id, _fetcher, _ = _service(
        tmp_path, {root: (404, "text/html", b"not found")}
    )
    try:
        audit = asyncio.run(
            service.create_and_run(
                run_id,
                DiscoveryOptions(root, discover_robots=False, discover_common_locations=False),
            )
        )
        assert audit["state"] == "failed"
        assert audit["failure_code"] == "sitemap_audit_no_valid_root"
        assert service.list_documents(audit["audit_id"])
        assert service.list_findings(audit["audit_id"])
    finally:
        runtime.dispose()


def test_exports_register_and_verify_all_formats(tmp_path: Path) -> None:
    root = "https://example.com/sitemap.xml"
    xml = f'<urlset xmlns="{_NS}"><url><loc>https://example.com/</loc></url></urlset>'.encode()
    runtime, service, run_id, _fetcher, artifacts = _service(
        tmp_path, {root: (200, "application/xml", xml)}, artifacts=True
    )
    try:
        audit = asyncio.run(
            service.create_and_run(
                run_id,
                DiscoveryOptions(root, discover_robots=False, discover_common_locations=False),
            )
        )
        for export_format in ExportFormat:
            created = service.create_export(audit["audit_id"], export_format)
            assert artifacts is not None
            descriptor = artifacts.prepare_download(created["artifact_id"])
            assert b"".join(descriptor.iterator_factory())
        assert len(service.list_exports(audit["audit_id"])) == 3
    finally:
        runtime.dispose()


def test_retention_cleanup_is_bounded_and_cascades_normalized_evidence(tmp_path: Path) -> None:
    root = "https://example.com/sitemap.xml"
    xml = f'<urlset xmlns="{_NS}"><url><loc>https://example.com/</loc></url></urlset>'.encode()
    runtime, service, run_id, _fetcher, _ = _service(
        tmp_path, {root: (200, "application/xml", xml)}
    )
    try:
        audit = asyncio.run(
            service.create_and_run(
                run_id,
                DiscoveryOptions(root, discover_robots=False, discover_common_locations=False),
            )
        )
        now = datetime.now(UTC)
        with runtime.transaction() as database:
            row = database.get(SitemapAuditModel, audit["audit_id"])
            assert row is not None
            row.retention_until = now - timedelta(seconds=1)
        repository = SQLAlchemySitemapAuditRepository(runtime)
        assert repository.cleanup_expired(now, limit=1) == 1
        assert repository.get(audit["audit_id"]) is None
        assert repository.cleanup_expired(now, limit=1) == 0
    finally:
        runtime.dispose()


def test_routes_are_private_coherent_and_permission_mapped(tmp_path: Path) -> None:
    runtime, service, _run_id, _fetcher, artifacts = _service(tmp_path, {}, artifacts=True)
    try:
        settings = ProductionSettings.model_validate(
            {"enabled": True, "bearer_token": _TOKEN, "include_openapi": True}
        )
        application = create_production_app(
            _SecurityTestService(), settings, Settings(), sitemap_audits=service
        )
        paths = application.openapi()["paths"]
        sitemap_paths = {
            path for path in paths if path.startswith("/api/internal/v1/audits/sitemaps")
        }
        assert len(sitemap_paths) == 10
        operations = {
            (method.upper(), path)
            for path, definition in paths.items()
            if path.startswith("/api/internal/v1/audits/sitemaps")
            for method in definition
            if method in {"get", "post"}
        }
        assert operations == {
            ("POST", "/api/internal/v1/audits/sitemaps/discover"),
            ("POST", "/api/internal/v1/audits/sitemaps"),
            ("GET", "/api/internal/v1/audits/sitemaps"),
            ("POST", "/api/internal/v1/audits/sitemaps/{audit_id}/execute"),
            ("GET", "/api/internal/v1/audits/sitemaps/{audit_id}"),
            ("GET", "/api/internal/v1/audits/sitemaps/{audit_id}/summary"),
            ("GET", "/api/internal/v1/audits/sitemaps/{audit_id}/documents"),
            ("GET", "/api/internal/v1/audits/sitemaps/{audit_id}/entries"),
            ("GET", "/api/internal/v1/audits/sitemaps/{audit_id}/findings"),
            ("GET", "/api/internal/v1/audits/sitemaps/{audit_id}/comparisons"),
            ("POST", "/api/internal/v1/audits/sitemaps/{audit_id}/exports"),
            ("GET", "/api/internal/v1/audits/sitemaps/{audit_id}/exports"),
        }
        assert len(paths) == 22
        blog_strategy = BlogStrategyService(BlogStrategyRepository(runtime))
        assert artifacts is not None
        link_audits = LinkAuditService(
            LinkAuditConfiguration(enabled=True),
            SQLAlchemyLinkAuditRepository(runtime),
            artifacts,
        )
        internal_link_audits = InternalLinkAuditService(
            InternalLinkConfiguration(enabled=True),
            SQLAlchemyInternalLinkRepository(runtime),
            artifacts,
        )
        combined_paths = create_production_app(
            _SecurityTestService(),
            settings,
            Settings(),
            sitemap_audits=service,
            link_audits=link_audits,
            internal_link_audits=internal_link_audits,
            blog_strategy=blog_strategy,
        ).openapi()["paths"]
        assert (
            len(
                {
                    path
                    for path in combined_paths
                    if path.startswith("/api/internal/v1/audits/internal-links")
                }
            )
            == 15
        )
        assert (
            len(
                {
                    path
                    for path in combined_paths
                    if path.startswith("/api/internal/v1/audits/links")
                }
            )
            == 12
        )
        assert (
            len(
                {
                    path
                    for path in combined_paths
                    if path.startswith("/api/internal/v1/audits/sitemaps")
                }
            )
            == 10
        )
        assert (
            len(
                {
                    path
                    for path in combined_paths
                    if path.startswith("/api/internal/v1/blog-strategy")
                }
            )
            == 14
        )
        assert len(combined_paths) == 63
        history = HistoryService(
            HistoryConfiguration(enabled=True), SQLAlchemyHistoryRepository(runtime)
        )
        metadata = MetadataAuditService(
            MetadataAuditConfiguration(enabled=True),
            SQLAlchemyMetadataAuditRepository(runtime),
            artifacts,
        )
        bearer_counts = {
            "default": len(create_app(Settings()).openapi()["paths"]),
            "production": len(
                create_production_app(_SecurityTestService(), settings, Settings()).openapi()[
                    "paths"
                ]
            ),
            "artifacts": len(
                create_production_app(
                    _SecurityTestService(), settings, Settings(), artifacts=artifacts
                ).openapi()["paths"]
            ),
            "history": len(
                create_production_app(
                    _SecurityTestService(), settings, Settings(), history=history
                ).openapi()["paths"]
            ),
            "metadata": len(
                create_production_app(
                    _SecurityTestService(), settings, Settings(), metadata_audits=metadata
                ).openapi()["paths"]
            ),
            "sitemaps": len(paths),
            "metadata_sitemaps": len(
                create_production_app(
                    _SecurityTestService(),
                    settings,
                    Settings(),
                    metadata_audits=metadata,
                    sitemap_audits=service,
                ).openapi()["paths"]
            ),
            "all_before_sitemaps": len(
                create_production_app(
                    _SecurityTestService(),
                    settings,
                    Settings(),
                    artifacts=artifacts,
                    history=history,
                    metadata_audits=metadata,
                ).openapi()["paths"]
            ),
            "all_with_sitemaps": len(
                create_production_app(
                    _SecurityTestService(),
                    settings,
                    Settings(),
                    artifacts=artifacts,
                    history=history,
                    metadata_audits=metadata,
                    sitemap_audits=service,
                ).openapi()["paths"]
            ),
        }
        assert bearer_counts == {
            "default": 1,
            "production": 12,
            "artifacts": 15,
            "history": 22,
            "metadata": 21,
            "sitemaps": 22,
            "metadata_sitemaps": 31,
            "all_before_sitemaps": 34,
            "all_with_sitemaps": 44,
        }
        authentication = AuthenticationService(
            runtime.session_factory,
            AuthenticationConfiguration(
                enabled=True,
                mode=AuthenticationMode.USER_SESSION,
                require_secure_cookie=True,
            ),
        )
        authentication.bootstrap_administrator(
            "sitemap-admin@example.test",
            "Sitemap Administrator",
            "correct horse battery staple",
        )
        expanded = ProductionSettings.model_validate(
            {
                "enabled": True,
                "authentication_enabled": True,
                "authentication_mode": "user_session",
                "include_openapi": True,
            }
        )
        assert {
            "metadata": len(
                create_production_app(
                    _SecurityTestService(),
                    expanded,
                    Settings(),
                    authentication=authentication,
                    metadata_audits=metadata,
                ).openapi()["paths"]
            ),
            "metadata_sitemaps": len(
                create_production_app(
                    _SecurityTestService(),
                    expanded,
                    Settings(),
                    authentication=authentication,
                    metadata_audits=metadata,
                    sitemap_audits=service,
                ).openapi()["paths"]
            ),
            "all_before_sitemaps": len(
                create_production_app(
                    _SecurityTestService(),
                    expanded,
                    Settings(),
                    artifacts=artifacts,
                    history=history,
                    authentication=authentication,
                    metadata_audits=metadata,
                ).openapi()["paths"]
            ),
            "all_with_sitemaps": len(
                create_production_app(
                    _SecurityTestService(),
                    expanded,
                    Settings(),
                    artifacts=artifacts,
                    history=history,
                    authentication=authentication,
                    metadata_audits=metadata,
                    sitemap_audits=service,
                ).openapi()["paths"]
            ),
        } == {
            "metadata": 35,
            "metadata_sitemaps": 45,
            "all_before_sitemaps": 48,
            "all_with_sitemaps": 58,
        }
        assert "/api/audits/sitemaps" not in paths
        client = TestClient(application, client=("203.0.113.10", 50_000))
        assert client.get("/api/internal/v1/audits/sitemaps").status_code == 401
        assert client.get("/api/audits/sitemaps").status_code == 404
        assert (
            permission_for_request("POST", "/api/internal/v1/audits/sitemaps")
            is Permission.JOBS_SUBMIT
        )
        assert (
            permission_for_request("POST", "/api/internal/v1/audits/sitemaps/a/exports")
            is Permission.JOBS_SUBMIT
        )
        assert (
            permission_for_request("GET", "/api/internal/v1/audits/sitemaps")
            is Permission.RUNS_VIEW
        )
    finally:
        runtime.dispose()


def test_all_twelve_private_api_operations_execute_with_authorization(tmp_path: Path) -> None:
    root = "https://example.com/sitemap.xml"
    xml = f'<urlset xmlns="{_NS}"><url><loc>https://example.com/</loc></url></urlset>'.encode()
    runtime, service, run_id, _fetcher, _ = _service(
        tmp_path,
        {root: (200, "application/xml", xml)},
        artifacts=True,
    )
    settings = ProductionSettings.model_validate(
        {"enabled": True, "bearer_token": _TOKEN, "include_openapi": True}
    )
    app = create_production_app(
        _SecurityTestService(), settings, Settings(), sitemap_audits=service
    )
    client = TestClient(app, client=("203.0.113.10", 50_000))
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    payload = {
        "run_id": run_id,
        "explicit_sitemap_url": root,
        "discover_robots": False,
        "discover_common_locations": False,
    }
    try:
        assert (
            client.post(
                "/api/internal/v1/audits/sitemaps/discover", json=payload, headers=headers
            ).status_code
            == 200
        )
        created = client.post(
            "/api/internal/v1/audits/sitemaps", json=payload, headers=headers
        ).json()["data"]
        audit_id = created["audit_id"]
        assert (
            client.post(
                f"/api/internal/v1/audits/sitemaps/{audit_id}/execute", headers=headers
            ).status_code
            == 200
        )
        for suffix in (
            "",
            f"/{audit_id}",
            f"/{audit_id}/summary",
            f"/{audit_id}/documents",
            f"/{audit_id}/entries",
            f"/{audit_id}/findings",
            f"/{audit_id}/comparisons",
            f"/{audit_id}/exports",
        ):
            assert (
                client.get(f"/api/internal/v1/audits/sitemaps{suffix}", headers=headers).status_code
                == 200
            )
        assert (
            client.post(
                f"/api/internal/v1/audits/sitemaps/{audit_id}/exports",
                json={"format": "json"},
                headers=headers,
            ).status_code
            == 200
        )
    finally:
        runtime.dispose()


def test_missing_run_returns_typed_failure(tmp_path: Path) -> None:
    runtime, service, _run_id, _fetcher, _ = _service(tmp_path, {})
    try:
        with pytest.raises(ValueError, match="sitemap_audit_run_not_found"):
            asyncio.run(service.create_and_run("missing-run", DiscoveryOptions()))
    finally:
        runtime.dispose()


def test_invalid_or_out_of_scope_explicit_url_fails_before_sitemap_fetch(tmp_path: Path) -> None:
    runtime, service, run_id, fetcher, _ = _service(tmp_path, {})
    try:
        for value in ("not-a-url", "https://other.example/sitemap.xml"):
            with pytest.raises(ValueError, match="sitemap_audit_invalid_filter"):
                asyncio.run(
                    service.create_and_run(
                        run_id,
                        DiscoveryOptions(
                            value,
                            discover_robots=False,
                            discover_common_locations=False,
                        ),
                    )
                )
        assert fetcher.requests == []
    finally:
        runtime.dispose()


@pytest.mark.parametrize(
    ("mode", "approved_hosts", "sitemap_url"),
    [
        (ScopeMode.EXACT_HOST, (), "https://example.com/sitemap.xml"),
        (ScopeMode.INCLUDE_SUBDOMAINS, (), "https://www.example.com/sitemap.xml"),
        (ScopeMode.APPROVED_HOSTS, ("cdn.example.net",), "https://cdn.example.net/sitemap.xml"),
    ],
)
def test_audit_reuses_every_accepted_durable_scope_mode(
    tmp_path: Path,
    mode: ScopeMode,
    approved_hosts: tuple[str, ...],
    sitemap_url: str,
) -> None:
    request = _request_with_scope(mode, approved_hosts)
    xml = f'<urlset xmlns="{_NS}"><url><loc>{sitemap_url}</loc></url></urlset>'.encode()
    runtime, service, run_id, fetcher, _ = _service(
        tmp_path,
        {sitemap_url: (200, "application/xml", xml)},
        request=request,
    )
    try:
        audit = asyncio.run(
            service.create_and_run(
                run_id,
                DiscoveryOptions(
                    sitemap_url,
                    discover_robots=False,
                    discover_common_locations=False,
                ),
            )
        )
        assert audit["state"] == "completed"
        assert fetcher.requests == [sitemap_url]
    finally:
        runtime.dispose()


def test_unreadable_historical_scope_snapshot_fails_without_exact_host_fallback(
    tmp_path: Path,
) -> None:
    runtime, service, run_id, fetcher, _ = _service(tmp_path, {})
    try:
        with runtime.transaction() as database:
            run = database.get(RunModel, run_id)
            assert run is not None
            snapshot = database.get(ConfigurationSnapshotModel, run.configuration_snapshot_id)
            assert snapshot is not None
            snapshot.canonical_json = "{}"
        with pytest.raises(ValueError, match="sitemap_audit_scope_unavailable"):
            service.create_audit(
                run_id,
                DiscoveryOptions(
                    "https://example.com/sitemap.xml",
                    discover_robots=False,
                    discover_common_locations=False,
                ),
            )
        assert fetcher.requests == []
    finally:
        runtime.dispose()
