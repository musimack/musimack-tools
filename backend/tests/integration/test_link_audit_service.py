"""Phase 22 durable, network-free service, filtering, export, and restart tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
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
from musimack_tools.domain.authentication import Permission
from musimack_tools.domain.job import JobState
from musimack_tools.domain.link_audit import ExportFormat, LinkAuditConfiguration
from musimack_tools.domain.page_evidence import PageEvidenceConfiguration
from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.link_audit.service import LinkAuditService
from musimack_tools.main import create_app
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.link_audit_models import LinkAuditModel
from musimack_tools.persistence.link_audit_repository import SQLAlchemyLinkAuditRepository
from musimack_tools.persistence.migrations import upgrade_to_head
from musimack_tools.persistence.repositories import SQLAlchemyPersistenceRepository
from page_evidence_helpers import PageRecordOptions, crawl_result, page_record
from persistence_helpers import BACKEND_ROOT, sample_request, sample_result, sample_snapshot

if TYPE_CHECKING:
    from pathlib import Path

    from musimack_tools.persistence.engine import PersistenceRuntime


def _service(tmp_path: Path) -> tuple[PersistenceRuntime, LinkAuditService, str]:
    database = tmp_path / "link-audit.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    upgrade_to_head(url, backend_root=BACKEND_ROOT)
    configuration = LinkAuditConfiguration(
        enabled=True,
        default_page_size=2,
        maximum_page_size=20,
        minimum_sitewide_source_pages=2,
        minimum_sitewide_crawl_pages=2,
    )
    runtime = create_persistence_runtime(
        PersistenceConfiguration(
            enabled=True,
            database_path=database,
            page_evidence=PageEvidenceConfiguration(enabled=True),
            link_audit=configuration,
        )
    )
    request = sample_request()
    snapshot = sample_snapshot(request)
    repository = SQLAlchemyPersistenceRepository(runtime)
    assert repository.record_submission(snapshot, request).succeeded
    source_body = """
        <a href='/ok'>Working</a><a href='/missing'>Missing</a>
        <a href='/old'>Old</a><a href='/old'>Old duplicate</a>
        <a href='mailto:team@example.com'>Mail</a>
        <a href='https://outside.example/path'>External</a>
    """
    crawl = crawl_result(
        (
            page_record(options=PageRecordOptions(body=source_body)),
            page_record("https://example.com/ok", PageRecordOptions(discovery_order=1)),
            page_record(
                "https://example.com/missing",
                PageRecordOptions(status=404, discovery_order=2),
            ),
            page_record(
                "https://example.com/old",
                PageRecordOptions(final_url="https://example.com/ok", discovery_order=3),
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
    assert repository.record_terminal(terminal, result, (), None).succeeded
    root = tmp_path / "artifacts"
    root.mkdir()
    artifacts = ArtifactService(
        ArtifactStorageConfiguration(
            enabled=True,
            roots=(ArtifactStorageRootConfiguration("link-root", root),),
            default_root_id="link-root",
            allow_csv=True,
        ),
        SQLAlchemyArtifactRepository(runtime),
    )
    service = LinkAuditService(configuration, SQLAlchemyLinkAuditRepository(runtime), artifacts)
    return runtime, service, snapshot.run_id


def test_link_audit_executes_from_durable_evidence_without_network(tmp_path: Path) -> None:
    runtime, service, run_id = _service(tmp_path)
    try:
        status = service.evidence_status(run_id)
        assert status["compatible"]
        assert status["link_evidence_count"] == 6
        audit = service.create_audit(run_id)
        completed = asyncio.run(service.execute_audit(str(audit["audit_id"])))
        assert completed["state"] == "completed"
        assert completed["link_occurrence_count"] == 6
        assert completed["target_count"] == 5
        assert completed["broken_target_count"] == 1
        assert completed["redirect_target_count"] == 1
        audit_id = str(completed["audit_id"])
        assert (
            service.list_targets(audit_id, filters={"http_status": 404})[0]["primary_reason"]
            == "target_404"
        )
        assert len(service.list_occurrences(audit_id, filters={"target": "/old"})) == 2
        assert service.list_chains(audit_id)[0]["hop_count"] == 1
        assert service.list_recommendations(
            audit_id, filters={"action": "update_link_to_final_destination"}
        )
        with pytest.raises(ValueError, match="already_terminal"):
            asyncio.run(service.execute_audit(audit_id))
    finally:
        runtime.dispose()


def test_exports_are_artifacts_idempotent_and_survive_restart(tmp_path: Path) -> None:
    runtime, service, run_id = _service(tmp_path)
    database = tmp_path / "link-audit.db"
    try:
        audit_id = str(service.create_audit(run_id)["audit_id"])
        asyncio.run(service.execute_audit(audit_id))
        for export_format in ExportFormat:
            exported = service.create_export(audit_id, export_format)
            assert exported["state"] == "available"
            assert exported["artifact_id"]
        repeated = service.create_export(audit_id, ExportFormat.JSON)
        assert repeated["export_format"] == "json"
        assert len(service.list_exports(audit_id)) == len(ExportFormat)
    finally:
        runtime.dispose()
    restarted = create_persistence_runtime(
        PersistenceConfiguration(enabled=True, database_path=database)
    )
    try:
        repository = SQLAlchemyLinkAuditRepository(restarted)
        assert repository.get(audit_id)["state"] == "completed"  # type: ignore[index]
        assert len(repository.list_targets(audit_id, 0, 20)) == 5
    finally:
        restarted.dispose()


def test_missing_or_nonterminal_evidence_is_rejected(tmp_path: Path) -> None:
    runtime, service, _run_id = _service(tmp_path)
    try:
        with pytest.raises(ValueError, match="run_not_found"):
            service.create_audit("missing")
        with pytest.raises(ValueError, match="invalid_page_size"):
            service.list_audits(page_size=21)
    finally:
        runtime.dispose()


def test_cleanup_cascades_audit_only_and_startup_reconciles_interruption(tmp_path: Path) -> None:
    runtime, service, run_id = _service(tmp_path)
    repository = SQLAlchemyLinkAuditRepository(runtime)
    try:
        audit_id = str(service.create_audit(run_id)["audit_id"])
        assert repository.claim_execution(audit_id)
        LinkAuditService(service.configuration, repository)
        assert repository.get(audit_id)["failure_code"] == "link_audit_interrupted"  # type: ignore[index]
        with runtime.transaction() as session:
            audit = session.get(LinkAuditModel, audit_id)
            assert audit is not None
            audit.retention_until = datetime.now(UTC) - timedelta(seconds=1)
        source_count = len(repository.source_links(run_id))
        assert service.cleanup() == 1
        assert repository.get(audit_id) is None
        assert len(repository.source_links(run_id)) == source_count
    finally:
        runtime.dispose()


def test_private_api_routes_auth_pagination_filters_and_old_route_absence(
    tmp_path: Path,
) -> None:
    runtime, service, run_id = _service(tmp_path)
    token = "phase-22-link-audit-test-token-value-123456789"  # noqa: S105
    settings = ProductionSettings.model_validate(
        {"enabled": True, "bearer_token": token, "include_openapi": True}
    )
    app = create_production_app(_SecurityTestService(), settings, Settings(), link_audits=service)
    client = TestClient(app, client=("203.0.113.10", 50_000))
    headers = {"Authorization": f"Bearer {token}"}
    try:
        paths = app.openapi()["paths"]
        operations = {
            (method.upper(), path)
            for path, definition in paths.items()
            if path.startswith("/api/internal/v1/audits/links")
            for method in definition
            if method in {"get", "post"}
        }
        assert len(operations) == 14
        assert len(paths) == 25
        assert (
            len(
                create_production_app(_SecurityTestService(), settings, Settings()).openapi()[
                    "paths"
                ]
            )
            == 13
        )
        assert len(create_app(Settings()).openapi()["paths"]) == 1
        assert client.get("/api/internal/v1/audits/links").status_code == 401
        assert client.get("/api/audits/links", headers=headers).status_code == 404
        base = "/api/internal/v1/audits/links"
        evidence = client.get(f"{base}/evidence/{run_id}", headers=headers)
        assert evidence.status_code == 200
        created = client.post(base, json={"run_id": run_id}, headers=headers)
        assert created.status_code == 200
        audit_id = created.json()["data"]["audit_id"]
        assert client.post(f"{base}/{audit_id}/execute", headers=headers).status_code == 200
        for suffix in (
            "",
            "/summary",
            "/targets?page_size=2",
            "/occurrences?internal=true",
            "/chains",
            "/loops",
            "/findings",
            "/recommendations?human_review=true",
            "/exports",
        ):
            assert client.get(f"{base}/{audit_id}{suffix}", headers=headers).status_code == 200
        first = client.get(f"{base}/{audit_id}/targets?page_size=2", headers=headers).json()["data"]
        assert first["next_cursor"]
        second = client.get(
            f"{base}/{audit_id}/targets?page_size=2&cursor={first['next_cursor']}",
            headers=headers,
        )
        assert second.status_code == 200
        mismatch = client.get(
            f"{base}/{audit_id}/targets?page_size=2&severity=high&cursor={first['next_cursor']}",
            headers=headers,
        )
        assert mismatch.status_code == 400
        assert mismatch.json()["error"]["code"] == "link_audit_cursor_filter_mismatch"
        oversized = client.get(f"{base}/{audit_id}/targets?page_size=21", headers=headers)
        assert oversized.status_code == 400
        assert oversized.json()["error"]["code"] == "link_audit_invalid_page_size"
        exported = client.post(
            f"{base}/{audit_id}/exports", json={"format": "json"}, headers=headers
        )
        assert exported.status_code == 200
        assert permission_for_request("POST", base) is Permission.JOBS_SUBMIT
        assert (
            permission_for_request("POST", f"{base}/{audit_id}/exports") is Permission.JOBS_SUBMIT
        )
        assert permission_for_request("GET", f"{base}/{audit_id}") is Permission.RUNS_VIEW
    finally:
        runtime.dispose()
