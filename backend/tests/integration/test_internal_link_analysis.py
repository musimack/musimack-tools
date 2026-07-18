"""Phase 23 durable graph, lifecycle, API, and migration integration coverage."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient
from test_production_security import _SecurityTestService

from musimack_tools.api.dependencies import permission_for_request
from musimack_tools.artifacts.repository import SQLAlchemyArtifactRepository
from musimack_tools.artifacts.service import ArtifactService
from musimack_tools.core.config import Settings
from musimack_tools.deployment.application import create_production_app
from musimack_tools.deployment.settings import ProductionSettings
from musimack_tools.domain.artifacts import (
    ArtifactStorageConfiguration,
    ArtifactStorageRootConfiguration,
)
from musimack_tools.domain.authentication import Permission, UserRole, permissions_for_role
from musimack_tools.domain.internal_link import InternalLinkConfiguration
from musimack_tools.domain.job import JobState
from musimack_tools.domain.page_evidence import PageEvidenceConfiguration
from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.internal_link.service import InternalLinkAuditService
from musimack_tools.main import create_app
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.internal_link_repository import SQLAlchemyInternalLinkRepository
from musimack_tools.persistence.migrations import (
    INTERNAL_LINK_ANALYSIS_REVISION,
    PERSISTENCE_HEAD_REVISION,
    upgrade_to_head,
)
from musimack_tools.persistence.repositories import SQLAlchemyPersistenceRepository
from page_evidence_helpers import PageRecordOptions, crawl_result, page_record
from persistence_helpers import BACKEND_ROOT, sample_request, sample_result, sample_snapshot

if TYPE_CHECKING:
    from pathlib import Path

    from musimack_tools.persistence.engine import PersistenceRuntime


def _service(tmp_path: Path) -> tuple[PersistenceRuntime, InternalLinkAuditService, str]:
    database = tmp_path / "internal-links.db"
    upgrade_to_head(f"sqlite+pysqlite:///{database.as_posix()}", backend_root=BACKEND_ROOT)
    configuration = InternalLinkConfiguration(
        enabled=True,
        default_page_size=2,
        maximum_page_size=20,
        minimum_hub_destinations=2,
        minimum_authority_referrers=2,
        minimum_sitewide_pages=2,
    )
    runtime = create_persistence_runtime(
        PersistenceConfiguration(
            enabled=True,
            database_path=database,
            page_evidence=PageEvidenceConfiguration(enabled=True),
            internal_link=configuration,
        )
    )
    request = sample_request()
    snapshot = sample_snapshot(request)
    persistence = SQLAlchemyPersistenceRepository(runtime)
    assert persistence.record_submission(snapshot, request).succeeded
    root = page_record(
        options=PageRecordOptions(
            body="""
            <a href='/about'>About us</a><a href='/about'>About</a>
            <a href='/old' rel='nofollow'>click here</a>
            <a href='/missing'>Missing</a><a href='https://outside.example/x'>Outside</a>
            """,
            x_robots=(),
        )
    )
    crawl = crawl_result(
        (
            root,
            page_record(
                "https://example.com/about",
                PageRecordOptions(
                    body="<a href='/deep'>Deep guide</a>",
                    discovery_order=1,
                    x_robots=(),
                ),
            ),
            page_record(
                "https://example.com/deep",
                PageRecordOptions(body="<title>Deep</title>", discovery_order=2, x_robots=()),
            ),
            page_record(
                "https://example.com/orphan",
                PageRecordOptions(body="<title>Orphan</title>", discovery_order=3, x_robots=()),
            ),
            page_record(
                "https://example.com/old",
                PageRecordOptions(
                    final_url="https://example.com/about", discovery_order=4, x_robots=()
                ),
            ),
            page_record(
                "https://example.com/missing",
                PageRecordOptions(status=404, discovery_order=5, x_robots=()),
            ),
        )
    )
    result = replace(sample_result(request), crawl_result=crawl)
    terminal = replace(
        snapshot,
        state=JobState.COMPLETED,
        run_lifecycle=result.lifecycle,
        final_result_available=True,
        terminal=True,
    )
    assert persistence.record_terminal(terminal, result, (), None).succeeded
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    artifacts = ArtifactService(
        ArtifactStorageConfiguration(
            enabled=True,
            roots=(ArtifactStorageRootConfiguration("phase23", artifact_root),),
            default_root_id="phase23",
            allow_csv=True,
        ),
        SQLAlchemyArtifactRepository(runtime),
    )
    service = InternalLinkAuditService(
        configuration, SQLAlchemyInternalLinkRepository(runtime), artifacts
    )
    return runtime, service, snapshot.run_id


def test_internal_link_analysis_is_durable_deterministic_and_network_free(
    tmp_path: Path,
) -> None:
    runtime, service, run_id = _service(tmp_path)
    try:
        assert service.evidence_status(run_id)["compatible"]
        audit = service.create_audit(run_id)
        completed = asyncio.run(service.execute_audit(str(audit["audit_id"])))
        assert completed["state"] in {"completed", "completed_with_warnings"}
        assert completed["eligible_page_count"] >= 3
        audit_id = str(completed["audit_id"])
        assert service.list_pages(audit_id)["items"]
        assert service.list_edges(audit_id)["items"]
        assert service.list_reachability(audit_id)["items"]
        assert service.list_orphans(audit_id)["items"]
        assert service.list_anchors(audit_id)["items"]
        assert service.list_opportunities(audit_id)["items"]
    finally:
        runtime.dispose()


def test_internal_link_routes_are_private_opt_in_and_authorized(tmp_path: Path) -> None:
    runtime, service, run_id = _service(tmp_path)
    token = "phase-23-internal-link-test-token-123456789"  # noqa: S105
    settings = ProductionSettings.model_validate(
        {"enabled": True, "bearer_token": token, "include_openapi": True}
    )
    app = create_production_app(
        _SecurityTestService(), settings, Settings(), internal_link_audits=service
    )
    client = TestClient(app, client=("203.0.113.10", 50_000))
    headers = {"Authorization": f"Bearer {token}"}
    try:
        paths = app.openapi()["paths"]
        internal_paths = [path for path in paths if "/audits/internal-links" in path]
        assert len(internal_paths) == 15
        assert len(create_app(Settings()).openapi()["paths"]) == 1
        assert client.get("/api/internal/v1/audits/internal-links").status_code == 401
        assert client.get("/api/audits/internal-links", headers=headers).status_code == 404
        base = "/api/internal/v1/audits/internal-links"
        assert client.get(f"{base}/evidence/{run_id}", headers=headers).status_code == 200
        created = client.post(base, json={"run_id": run_id}, headers=headers)
        assert created.status_code == 200
        audit_id = created.json()["data"]["audit_id"]
        duplicate = client.post(base, json={"run_id": run_id}, headers=headers)
        assert duplicate.status_code == 200
        assert duplicate.json()["data"]["audit_id"] == audit_id
        assert client.post(f"{base}/{audit_id}/execute", headers=headers).status_code == 200
        assert client.post(f"{base}/{audit_id}/execute", headers=headers).status_code == 409
        operations = {
            ("GET", base),
            ("GET", f"{base}/{audit_id}"),
            ("GET", f"{base}/{audit_id}/summary"),
            *(
                ("GET", f"{base}/{audit_id}/{resource}")
                for resource in (
                    "pages",
                    "edges",
                    "orphans",
                    "hubs",
                    "authorities",
                    "reachability",
                    "findings",
                    "anchors",
                    "opportunities",
                    "exports",
                )
            ),
        }
        for method, path in operations:
            assert client.request(method, path, headers=headers).status_code == 200
        page = client.get(
            f"{base}/{audit_id}/pages",
            params={
                "page_size": 1,
                "eligibility": "eligible",
                "severity": "high",
                "url": "example",
            },
            headers=headers,
        )
        assert page.status_code == 200
        cursor = page.json()["data"]["next_cursor"]
        if cursor:
            assert (
                client.get(
                    f"{base}/{audit_id}/pages",
                    params={"cursor": cursor, "eligibility": "excluded_broken"},
                    headers=headers,
                ).status_code
                == 400
            )
        assert (
            client.get(
                f"{base}/{audit_id}/pages", params={"cursor": "not-a-cursor"}, headers=headers
            ).status_code
            == 400
        )
        exported = client.post(
            f"{base}/{audit_id}/exports", json={"format": "json"}, headers=headers
        )
        assert exported.status_code == 200
        assert client.get(f"{base}/{audit_id}/exports", headers=headers).json()["data"]["items"]
        assert client.get(f"{base}/missing-audit", headers=headers).status_code == 404
        assert client.get(f"{base}/evidence/missing-run", headers=headers).status_code == 404

        read_path = f"{base}/{audit_id}/pages"
        write_path = f"{base}/{audit_id}/exports"
        assert permission_for_request("GET", read_path) is Permission.RUNS_VIEW
        assert permission_for_request("POST", write_path) is Permission.JOBS_SUBMIT
        for role in UserRole:
            grants = permissions_for_role(role)
            assert Permission.RUNS_VIEW in grants
            assert (Permission.JOBS_SUBMIT in grants) is (role is not UserRole.VIEWER)
    finally:
        runtime.dispose()


def test_internal_link_migration_is_registered_before_blog_strategy_head() -> None:
    assert INTERNAL_LINK_ANALYSIS_REVISION == "0010_internal_link_analysis"
    assert PERSISTENCE_HEAD_REVISION == "0011_blog_strategy"
