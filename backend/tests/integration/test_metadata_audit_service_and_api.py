"""Phase 20 durable service, export, private API, and route-matrix tests."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient
from test_authentication_service_and_api import _service as _authentication_service
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
from musimack_tools.domain.authentication import Permission, UserRole, is_authorized
from musimack_tools.domain.history import HistoryConfiguration
from musimack_tools.domain.job import JobState
from musimack_tools.domain.metadata_audit import ExportFormat, MetadataAuditConfiguration
from musimack_tools.domain.page_evidence import PageEvidenceConfiguration
from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.history.service import HistoryService
from musimack_tools.main import create_app
from musimack_tools.metadata_audit.service import MetadataAuditService
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.history_repository import SQLAlchemyHistoryRepository
from musimack_tools.persistence.metadata_audit_repository import SQLAlchemyMetadataAuditRepository
from musimack_tools.persistence.migrations import upgrade_to_head
from musimack_tools.persistence.repositories import SQLAlchemyPersistenceRepository
from page_evidence_helpers import PageRecordOptions, crawl_result, page_record
from persistence_helpers import BACKEND_ROOT, sample_request, sample_result, sample_snapshot

if TYPE_CHECKING:
    from pathlib import Path

    from musimack_tools.persistence.engine import PersistenceRuntime

_TOKEN = "phase-20-internal-test-token-value-123456789"  # noqa: S105


def _service(
    tmp_path: Path, *, artifacts: bool = False
) -> tuple[PersistenceRuntime, MetadataAuditService, str, ArtifactService | None]:
    database = tmp_path / "metadata-audit.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    upgrade_to_head(url, backend_root=BACKEND_ROOT)
    audit_configuration = MetadataAuditConfiguration(
        enabled=True, default_page_size=2, maximum_page_size=20
    )
    runtime = create_persistence_runtime(
        PersistenceConfiguration(
            enabled=True,
            database_path=database,
            page_evidence=PageEvidenceConfiguration(enabled=True),
            metadata_audit=audit_configuration,
        )
    )
    request = sample_request()
    snapshot = sample_snapshot(request)
    persistence = SQLAlchemyPersistenceRepository(runtime)
    assert persistence.record_submission(snapshot, request).succeeded
    result = replace(
        sample_result(request),
        crawl_result=crawl_result(
            (
                page_record(options=PageRecordOptions(body="<title>Same</title>")),
                page_record(
                    "https://example.com/two",
                    PageRecordOptions(body="<title>Same</title>", discovery_order=1),
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
    return (
        runtime,
        MetadataAuditService(
            audit_configuration, SQLAlchemyMetadataAuditRepository(runtime), artifact_service
        ),
        snapshot.run_id,
        artifact_service,
    )


def test_audit_execution_is_durable_idempotent_and_summarized(tmp_path: Path) -> None:
    runtime, service, run_id, _artifacts = _service(tmp_path)
    try:
        audit = service.create_and_run_audit(run_id)
        repeated = service.create_and_run_audit(run_id)
        assert audit.audit_id == repeated.audit_id
        assert audit.page_count == 2
        assert audit.issue_count > 0
        summary = service.get_summary(audit.audit_id)
        assert summary["duplicate_title_group_count"] == 1
        assert summary["total_pages"] == 2
        assert service.list_issues(audit.audit_id, page_size=20)
        assert service.list_pages(audit.audit_id, page_size=20)
    finally:
        runtime.dispose()


def test_run_candidates_are_newest_first_and_explain_ineligible_evidence(
    tmp_path: Path,
) -> None:
    runtime, service, run_id, _artifacts = _service(tmp_path)
    try:
        pending_request = sample_request("/pending")
        pending = sample_snapshot(pending_request)
        assert (
            SQLAlchemyPersistenceRepository(runtime)
            .record_submission(pending, pending_request)
            .succeeded
        )

        candidates = service.run_candidates()

        assert [item.run_id for item in candidates] == [run_id, pending.run_id]
        selected = candidates[0]
        assert selected.eligible
        assert selected.seed_url == "https://example.com/"
        assert selected.completed_at is not None
        assert selected.job_status == "completed"
        assert selected.page_evidence_count == 2
        assert selected.evidence_state == "complete"
        assert selected.crawl_profile == "custom"
        assert selected.ineligibility_reason is None
        assert not candidates[1].eligible
        assert candidates[1].page_evidence_count == 0
        assert candidates[1].ineligibility_reason == "The crawl has not reached a terminal state."
        assert is_authorized(UserRole.ADMINISTRATOR, Permission.JOBS_SUBMIT)
        assert is_authorized(UserRole.OPERATOR, Permission.JOBS_SUBMIT)
        assert not is_authorized(UserRole.VIEWER, Permission.JOBS_SUBMIT)
    finally:
        runtime.dispose()


def test_exports_are_bounded_registered_verified_and_reused(tmp_path: Path) -> None:
    runtime, service, run_id, artifacts = _service(tmp_path, artifacts=True)
    try:
        audit = service.create_and_run_audit(run_id)
        for export_format in ExportFormat:
            created = service.create_export(audit.audit_id, export_format)
            repeated = service.create_export(audit.audit_id, export_format)
            assert created == repeated
            assert created["artifact_id"]
            assert artifacts is not None
            descriptor = artifacts.prepare_download(str(created["artifact_id"]))
            payload = b"".join(descriptor.iterator_factory())
            assert payload
            assert b"<html" not in payload.lower()
    finally:
        runtime.dispose()


def test_routes_are_private_and_add_exactly_ten_operations_on_nine_paths(tmp_path: Path) -> None:
    runtime, service, _run_id, _artifacts = _service(tmp_path)
    try:
        settings = ProductionSettings.model_validate(
            {"enabled": True, "bearer_token": _TOKEN, "include_openapi": True}
        )
        application = create_production_app(
            _SecurityTestService(), settings, Settings(), metadata_audits=service
        )
        paths = application.openapi()["paths"]
        metadata_operations = {
            "/api/internal/v1/audits/metadata": {"get", "post"},
            "/api/internal/v1/audits/metadata/run-candidates": {"get"},
            "/api/internal/v1/audits/metadata/{audit_id}": {"get"},
            "/api/internal/v1/audits/metadata/{audit_id}/summary": {"get"},
            "/api/internal/v1/audits/metadata/{audit_id}/pages": {"get"},
            "/api/internal/v1/audits/metadata/{audit_id}/pages/{page_id}": {"get"},
            "/api/internal/v1/audits/metadata/{audit_id}/issues": {"get"},
            "/api/internal/v1/audits/metadata/{audit_id}/duplicates": {"get"},
            "/api/internal/v1/audits/metadata/{audit_id}/duplicates/{group_id}": {"get"},
            "/api/internal/v1/audits/metadata/{audit_id}/exports": {"post"},
        }
        assert {
            path: set(paths[path]).intersection({"get", "post", "put", "patch", "delete"})
            for path in metadata_operations
        } == metadata_operations
        assert not any(path.startswith("/api/audits/metadata") for path in paths)
        assert len(paths) == 23
        assert (
            len([path for path in paths if path.startswith("/api/internal/v1/audits/metadata")])
            == 10
        )
        root = tmp_path / "route-artifacts"
        root.mkdir()
        artifacts = ArtifactService(
            ArtifactStorageConfiguration(
                enabled=True,
                roots=(ArtifactStorageRootConfiguration("route-root", root),),
                default_root_id="route-root",
            ),
            SQLAlchemyArtifactRepository(runtime),
        )
        history = HistoryService(
            HistoryConfiguration(enabled=True), SQLAlchemyHistoryRepository(runtime)
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
            "metadata": len(paths),
            "artifacts_metadata": len(
                create_production_app(
                    _SecurityTestService(),
                    settings,
                    Settings(),
                    artifacts=artifacts,
                    metadata_audits=service,
                ).openapi()["paths"]
            ),
            "history_metadata": len(
                create_production_app(
                    _SecurityTestService(),
                    settings,
                    Settings(),
                    history=history,
                    metadata_audits=service,
                ).openapi()["paths"]
            ),
            "all": len(
                create_production_app(
                    _SecurityTestService(),
                    settings,
                    Settings(),
                    artifacts=artifacts,
                    history=history,
                    metadata_audits=service,
                ).openapi()["paths"]
            ),
        }
        assert bearer_counts == {
            "default": 1,
            "production": 13,
            "artifacts": 16,
            "history": 23,
            "metadata": 23,
            "artifacts_metadata": 26,
            "history_metadata": 33,
            "all": 36,
        }
        authentication, _factory = _authentication_service()
        authentication.bootstrap_administrator(
            "admin@example.com", "Administrator", "correct horse battery staple"
        )
        expanded = ProductionSettings.model_validate(
            {
                "enabled": True,
                "authentication_enabled": True,
                "authentication_mode": "user_session",
                "include_openapi": True,
            }
        )
        assert (
            len(
                create_production_app(
                    _SecurityTestService(),
                    expanded,
                    Settings(),
                    authentication=authentication,
                    metadata_audits=service,
                ).openapi()["paths"]
            )
            == 37
        )
        assert (
            len(
                create_production_app(
                    _SecurityTestService(),
                    expanded,
                    Settings(),
                    artifacts=artifacts,
                    history=history,
                    authentication=authentication,
                    metadata_audits=service,
                ).openapi()["paths"]
            )
            == 50
        )
        client = TestClient(application, client=("203.0.113.10", 50_000))
        assert client.get("/api/internal/v1/audits/metadata").status_code == 401
        assert client.get("/api/audits/metadata").status_code == 404
        assert (
            client.get(
                "/api/internal/v1/audits/metadata", headers={"Authorization": f"Bearer {_TOKEN}"}
            ).status_code
            == 200
        )
        candidates = client.get(
            "/api/internal/v1/audits/metadata/run-candidates",
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
        assert candidates.status_code == 200
        assert candidates.json()["data"][0]["page_evidence_count"] == 2
        assert (
            permission_for_request("POST", "/api/internal/v1/audits/metadata")
            is Permission.JOBS_SUBMIT
        )
        assert (
            permission_for_request("GET", "/api/internal/v1/audits/metadata")
            is Permission.RUNS_VIEW
        )
        assert (
            permission_for_request("POST", "/api/internal/v1/audits/metadata/audit-1/exports")
            is Permission.ARTIFACTS_VIEW
        )
        assert (
            permission_for_request("GET", "/api/internal/v1/artifacts/artifact-1/download")
            is Permission.ARTIFACTS_DOWNLOAD
        )

        network_settings = ProductionSettings.model_validate(
            {
                "enabled": True,
                "bearer_token": _TOKEN,
                "trusted_networks": ("203.0.113.0/24",),
            }
        )
        network_application = create_production_app(
            _SecurityTestService(), network_settings, Settings(), metadata_audits=service
        )
        authorization = {"Authorization": f"Bearer {_TOKEN}"}
        assert (
            TestClient(network_application, client=("203.0.113.10", 50_000))
            .get("/api/internal/v1/audits/metadata", headers=authorization)
            .status_code
            == 200
        )
        assert (
            TestClient(network_application, client=("198.51.100.10", 50_000))
            .get("/api/internal/v1/audits/metadata", headers=authorization)
            .status_code
            == 403
        )

        proxy_settings = ProductionSettings.model_validate(
            {
                "enabled": True,
                "bearer_token": _TOKEN,
                "trusted_proxies": ("10.0.0.0/8",),
                "trusted_networks": ("198.51.100.0/24",),
            }
        )
        proxy_application = create_production_app(
            _SecurityTestService(), proxy_settings, Settings(), metadata_audits=service
        )
        forwarded_headers = {
            **authorization,
            "X-Forwarded-For": "198.51.100.7",
        }
        assert (
            TestClient(proxy_application, client=("10.0.0.8", 50_000))
            .get("/api/internal/v1/audits/metadata", headers=forwarded_headers)
            .status_code
            == 200
        )
        assert (
            TestClient(proxy_application, client=("203.0.113.8", 50_000))
            .get("/api/internal/v1/audits/metadata", headers=forwarded_headers)
            .status_code
            == 403
        )
    finally:
        runtime.dispose()


def test_default_application_remains_health_only() -> None:
    assert list(create_app(Settings()).openapi()["paths"]) == ["/api/health"]
