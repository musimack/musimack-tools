"""Phase 24 durable image analysis, lifecycle, exports, API, and scope coverage."""

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
from musimack_tools.domain.image_audit import (
    ImageAuditConfiguration,
    ImageAuditLifecycle,
    ImageExportFormat,
)
from musimack_tools.domain.job import JobState
from musimack_tools.domain.page_evidence import PageEvidenceConfiguration
from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.image_audit.service import ImageAuditService
from musimack_tools.main import create_app
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.image_audit_models import (
    CrawlImageEvidenceModel,
    ImageAuditModel,
    ImageAuditResourceModel,
)
from musimack_tools.persistence.image_audit_repository import SQLAlchemyImageAuditRepository
from musimack_tools.persistence.migrations import upgrade_to_head
from musimack_tools.persistence.repositories import SQLAlchemyPersistenceRepository
from page_evidence_helpers import PageRecordOptions, crawl_result, page_record
from persistence_helpers import BACKEND_ROOT, sample_request, sample_result, sample_snapshot

if TYPE_CHECKING:
    from pathlib import Path

    from musimack_tools.persistence.engine import PersistenceRuntime


def _service(tmp_path: Path) -> tuple[PersistenceRuntime, ImageAuditService, str]:
    database = tmp_path / "images.db"
    upgrade_to_head(f"sqlite+pysqlite:///{database.as_posix()}", backend_root=BACKEND_ROOT)
    configuration = ImageAuditConfiguration(
        enabled=True, default_page_size=2, maximum_page_size=20, minimum_sitewide_pages=2
    )
    runtime = create_persistence_runtime(
        PersistenceConfiguration(
            enabled=True,
            database_path=database,
            page_evidence=PageEvidenceConfiguration(enabled=True),
            image_audit=configuration,
        )
    )
    request = sample_request()
    snapshot = sample_snapshot(request)
    persistence = SQLAlchemyPersistenceRepository(runtime)
    assert persistence.record_submission(snapshot, request).succeeded
    root = page_record(
        options=PageRecordOptions(
            body="""
      <a href='/buy'><img src='/ok.png' alt='' width='100' height='50'></a>
      <img src='/broken.png' alt='IMG_1234'>
      <img src='/ok.png' alt='Product photo'>
      <img data-src='/lazy.webp' alt='image' loading='lazy'>
      <img src='/other.png' alt='Product photo'>
      <img src='data:image/png;base64,AAAA' alt='' role='presentation'>
      <img src='https://outside.example/cdn.png' alt='External'>
      <img src='/gone.png' alt='Gone'>
      <img src='/error.png' alt='Error'>
      <img src='/old.png' alt='Redirected'>
      <img src='/mismatch.png' alt='Mismatched type'>
      <img src='/placeholder.png' alt='Placeholder'>
      <img src='ftp://example.com/file.png' alt='Unsupported'>
      <img src='/missing-alt.png'>
    """,
            x_robots=(),
        )
    )
    crawl = crawl_result(
        (
            root,
            page_record(
                "https://example.com/ok.png",
                PageRecordOptions(
                    body=None, content_type="image/png", discovery_order=1, x_robots=()
                ),
            ),
            page_record(
                "https://example.com/broken.png",
                PageRecordOptions(
                    body=None, content_type="image/png", status=404, discovery_order=2, x_robots=()
                ),
            ),
            page_record(
                "https://example.com/gone.png",
                PageRecordOptions(
                    body=None, content_type="image/png", status=410, discovery_order=3, x_robots=()
                ),
            ),
            page_record(
                "https://example.com/error.png",
                PageRecordOptions(
                    body=None, content_type="image/png", status=500, discovery_order=4, x_robots=()
                ),
            ),
            page_record(
                "https://example.com/old.png",
                PageRecordOptions(
                    body=None,
                    content_type="image/png",
                    final_url="https://example.com/ok.png",
                    discovery_order=5,
                    x_robots=(),
                ),
            ),
            page_record(
                "https://example.com/mismatch.png",
                PageRecordOptions(
                    body=None, content_type="image/jpeg", discovery_order=6, x_robots=()
                ),
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
            roots=(ArtifactStorageRootConfiguration("phase24", artifact_root),),
            default_root_id="phase24",
            allow_csv=True,
        ),
        SQLAlchemyArtifactRepository(runtime),
    )
    return (
        runtime,
        ImageAuditService(configuration, SQLAlchemyImageAuditRepository(runtime), artifacts),
        snapshot.run_id,
    )


def test_image_audit_is_durable_deterministic_network_free_and_exportable(tmp_path: Path) -> None:
    runtime, service, run_id = _service(tmp_path)
    try:
        assert service.evidence_status(run_id)["compatible"]
        audit = service.create_audit(run_id)
        completed = asyncio.run(service.execute_audit(str(audit["audit_id"])))
        assert completed["state"] in {"completed", "completed_with_warnings"}
        assert completed["image_occurrence_count"] == 14
        assert completed["broken_image_count"] == 3
        assert completed["redirecting_image_count"] == 1
        assert completed["missing_alt_count"] == 1
        audit_id = str(completed["audit_id"])
        assert service.list_resources(audit_id)["items"]
        assert service.list_occurrences(audit_id)["items"]
        assert len(service.list_broken(audit_id, page_size=20)["items"]) == 3
        assert len(service.list_redirecting(audit_id, page_size=20)["items"]) == 1
        assert service.list_groups(audit_id)["items"]
        assert service.list_pages(audit_id)["items"]
        assert service.list_recommendations(audit_id)["items"]
        resources = service.list_resources(audit_id, page_size=20)["items"]
        states = {row["resource_state"] for row in resources}
        assert {
            "valid_image",
            "broken_image",
            "redirecting_image",
            "unverified_image",
            "external_image",
            "data_image",
            "placeholder_image",
            "unsupported_image_source",
        } <= states
        assert all(row["total_occurrence_count"] >= 1 for row in resources)
        assert all("loading_distribution_json" in row for row in resources)
        for export_format in ImageExportFormat:
            exported = service.create_export(audit_id, export_format)
            assert exported["state"] == "completed" and exported["artifact_id"]
        assert len(service.list_exports(audit_id)) == 8
        exported_files = {
            path.name: path for path in (tmp_path / "artifacts").rglob("*") if path.is_file()
        }
        inventory = next(
            path
            for name, path in exported_files.items()
            if name.endswith("image_inventory_csv.csv")
        ).read_text(encoding="utf-8")
        assert inventory.startswith("audit_id,resource_sequence,image_identity,representative_url")
        markdown = next(
            path for name, path in exported_files.items() if name.endswith("markdown.md")
        ).read_text(encoding="utf-8")
        assert "## Broken images" in markdown
        assert "## Loading review" in markdown
        assert "## Version information" in markdown
        complete_json = next(
            path for name, path in exported_files.items() if name.endswith("json.json")
        ).read_text(encoding="utf-8")
        assert '"schema_version": "seo-toolkit-image-export-v1"' in complete_json
        with runtime.transaction() as session:
            inline = next(
                row for row in session.query(CrawlImageEvidenceModel).all() if row.data_fingerprint
            )
            assert inline.raw_src and "base64" not in inline.raw_src and "sha256=" in inline.raw_src
    finally:
        runtime.dispose()


def test_image_routes_are_private_opt_in_and_permission_mapped(tmp_path: Path) -> None:
    runtime, service, run_id = _service(tmp_path)
    token = "phase-24-image-audit-test-token-123456789"  # noqa: S105
    settings = ProductionSettings.model_validate(
        {"enabled": True, "bearer_token": token, "include_openapi": True}
    )
    app = create_production_app(_SecurityTestService(), settings, Settings(), image_audits=service)
    client = TestClient(app, client=("203.0.113.10", 50_000))
    headers = {"Authorization": f"Bearer {token}"}
    try:
        paths = app.openapi()["paths"]
        internal_paths = [path for path in paths if "/audits/images" in path]
        assert len(internal_paths) == 16
        assert len(create_app(Settings()).openapi()["paths"]) == 1
        assert client.get("/api/internal/v1/audits/images").status_code == 401
        assert client.get("/api/audits/images", headers=headers).status_code == 404
        base = "/api/internal/v1/audits/images"
        assert client.get(f"{base}/evidence/{run_id}", headers=headers).status_code == 200
        created = client.post(base, json={"run_id": run_id}, headers=headers)
        audit_id = created.json()["data"]["audit_id"]
        assert client.post(f"{base}/{audit_id}/execute", headers=headers).status_code == 200
        assert client.get(base, headers=headers).status_code == 200
        assert client.get(f"{base}/{audit_id}", headers=headers).status_code == 200
        for resource in (
            "summary",
            "resources",
            "occurrences",
            "pages",
            "broken",
            "redirecting",
            "alt-findings",
            "duplicate-groups",
            "dimensions",
            "loading",
            "recommendations",
            "exports",
        ):
            assert client.get(f"{base}/{audit_id}/{resource}", headers=headers).status_code == 200
        exported = client.post(
            f"{base}/{audit_id}/exports", json={"format": "json"}, headers=headers
        )
        assert exported.status_code == 200
        filtered = client.get(
            f"{base}/{audit_id}/resources",
            params={"page_size": 1, "url": "example"},
            headers=headers,
        )
        assert filtered.status_code == 200
        cursor = filtered.json()["data"]["next_cursor"]
        if cursor:
            mismatched = client.get(
                f"{base}/{audit_id}/resources",
                params={"cursor": cursor, "url": "different"},
                headers=headers,
            )
            assert mismatched.status_code == 400
        assert (
            permission_for_request("POST", f"{base}/{audit_id}/exports") is Permission.JOBS_SUBMIT
        )
        assert permission_for_request("GET", f"{base}/{audit_id}/resources") is Permission.RUNS_VIEW
        operations = {
            (method.upper(), path)
            for path, definition in paths.items()
            if path.startswith(base)
            for method in definition
            if method in {"get", "post", "put", "patch", "delete"}
        }
        assert len(operations) == 18
        for method, path in operations:
            expected = Permission.JOBS_SUBMIT if method == "POST" else Permission.RUNS_VIEW
            assert permission_for_request(method, path) is expected
    finally:
        runtime.dispose()


def test_image_audit_restart_reconciliation_and_retention_cleanup(tmp_path: Path) -> None:
    runtime, service, run_id = _service(tmp_path)
    try:
        audit = service.create_audit(run_id)
        audit_id = str(audit["audit_id"])
        repository = SQLAlchemyImageAuditRepository(runtime)
        assert repository.claim_execution(audit_id)
        repository.transition(audit_id, ImageAuditLifecycle.BUILDING_INVENTORY)
        recovered = ImageAuditService(service.configuration, repository)
        assert recovered.get(audit_id)["state"] == "failed"
        with runtime.transaction() as session:
            row = session.get(ImageAuditModel, audit_id)
            assert row is not None
            row.retention_until = datetime.now(UTC) - timedelta(days=1)
        assert recovered.cleanup() == 1
        with pytest.raises(ValueError, match="not_found"):
            recovered.get(audit_id)
    finally:
        runtime.dispose()


def test_historical_missing_and_unsupported_image_evidence_fail_safely(tmp_path: Path) -> None:
    runtime, service, run_id = _service(tmp_path)
    try:
        with runtime.transaction() as session:
            row = session.query(CrawlImageEvidenceModel).first()
            assert row is not None
            row.evidence_version = "unsupported-image-evidence-v0"
        status = service.evidence_status(run_id)
        assert not status["compatible"]
        with pytest.raises(ValueError, match="evidence_version_unsupported"):
            service.create_audit(run_id)
        with runtime.transaction() as session:
            session.query(CrawlImageEvidenceModel).delete()
        assert service.evidence_status(run_id)["image_evidence_count"] == 0
        with pytest.raises(ValueError, match="image_evidence_unavailable"):
            service.create_audit(run_id)
    finally:
        runtime.dispose()


class _CountingVerifier:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def verify(self, url: str, *, maximum_bytes: int) -> dict[str, object]:
        self.calls.append(url)
        return {
            "fetch_state": "verified",
            "http_status": 200,
            "content_type": "image/png",
            "final_url": url,
            "response_byte_count": min(10, maximum_bytes),
            "redirect_count": 0,
        }


def test_verification_is_deduplicated_and_honors_unique_fetch_limit(tmp_path: Path) -> None:
    runtime, _, run_id = _service(tmp_path)
    verifier = _CountingVerifier()
    configuration = ImageAuditConfiguration(
        enabled=True,
        maximum_unique_image_fetches=1,
        minimum_sitewide_pages=2,
        default_page_size=20,
        maximum_page_size=20,
    )
    service = ImageAuditService(
        configuration,
        SQLAlchemyImageAuditRepository(runtime),
        verifier=verifier,
    )
    try:
        audit = service.create_audit(run_id)
        completed = asyncio.run(service.execute_audit(str(audit["audit_id"])))
        assert completed["state"] == "completed_with_warnings"
        assert len(verifier.calls) == 1
        resources = service.list_resources(str(audit["audit_id"]), page_size=20)["items"]
        assert len(resources) < completed["image_occurrence_count"]
    finally:
        runtime.dispose()


def test_duplicate_claim_terminal_conflict_cancellation_and_cascade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, service, run_id = _service(tmp_path)
    try:
        first = service.create_audit(run_id)
        audit_id = str(first["audit_id"])
        assert SQLAlchemyImageAuditRepository(runtime).claim_execution(audit_id)
        with pytest.raises(ValueError, match="already_executing"):
            asyncio.run(service.execute_audit(audit_id))
        SQLAlchemyImageAuditRepository(runtime).fail_if_running(audit_id, "test_reset")

        alternate = ImageAuditService(
            replace(service.configuration, maximum_alt_length=201),
            SQLAlchemyImageAuditRepository(runtime),
        )
        cancelled_audit = alternate.create_audit(run_id)

        async def cancel_execution(*_args: object) -> dict[str, object]:
            raise asyncio.CancelledError

        monkeypatch.setattr(ImageAuditService, "_execute_claimed", cancel_execution)
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(alternate.execute_audit(str(cancelled_audit["audit_id"])))
        assert alternate.get(str(cancelled_audit["audit_id"]))["state"] == "cancelled"
        monkeypatch.undo()

        completed_service = ImageAuditService(
            replace(service.configuration, maximum_alt_length=202),
            SQLAlchemyImageAuditRepository(runtime),
        )
        completed_audit = completed_service.create_audit(run_id)
        completed_id = str(completed_audit["audit_id"])
        asyncio.run(completed_service.execute_audit(completed_id))
        with pytest.raises(ValueError, match="already_terminal"):
            asyncio.run(completed_service.execute_audit(completed_id))
        with runtime.transaction() as session:
            source_count = session.query(CrawlImageEvidenceModel).count()
            audit_row = session.get(ImageAuditModel, completed_id)
            assert audit_row is not None
            session.delete(audit_row)
        with runtime.transaction() as session:
            assert session.query(CrawlImageEvidenceModel).count() == source_count
            assert (
                session.query(ImageAuditResourceModel)
                .filter(ImageAuditResourceModel.audit_id == completed_id)
                .count()
                == 0
            )
    finally:
        runtime.dispose()
