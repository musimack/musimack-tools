"""Focused Phase 23 lifecycle, persistence, pagination, export, and artifact tests."""

# ruff: noqa: ANN401, S105, SLF001

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from test_internal_link_analysis import _service
from test_production_security import _SecurityTestService

from musimack_tools.core.config import Settings
from musimack_tools.deployment.application import create_production_app
from musimack_tools.deployment.settings import ProductionSettings
from musimack_tools.domain.artifacts import ArtifactIntegrityState
from musimack_tools.domain.internal_link import InternalLinkExportFormat
from musimack_tools.internal_link.service import InternalLinkAuditService
from musimack_tools.persistence.internal_link_models import (
    InternalLinkAnchorModel,
    InternalLinkAuditModel,
    InternalLinkEdgeModel,
    InternalLinkEventModel,
    InternalLinkFindingModel,
    InternalLinkOpportunityModel,
    InternalLinkPageMetricModel,
    InternalLinkReachabilityModel,
)
from musimack_tools.persistence.internal_link_repository import SQLAlchemyInternalLinkRepository

if TYPE_CHECKING:
    from pathlib import Path


def _completed(tmp_path: Path) -> tuple[Any, InternalLinkAuditService, str, str]:
    runtime, service, run_id = _service(tmp_path)
    audit = service.create_audit(run_id)
    audit_id = str(audit["audit_id"])
    completed = asyncio.run(service.execute_audit(audit_id))
    assert completed["state"] == "completed"
    return runtime, service, run_id, audit_id


def test_atomic_claim_duplicate_execution_events_and_terminal_success(tmp_path: Path) -> None:
    runtime, service, run_id = _service(tmp_path)
    repository = SQLAlchemyInternalLinkRepository(runtime)
    try:
        audit_id = str(service.create_audit(run_id)["audit_id"])
        assert repository.claim_execution(audit_id)
        assert not repository.claim_execution(audit_id)
        with pytest.raises(ValueError, match="already_executing"):
            asyncio.run(service.execute_audit(audit_id))
        repository.fail_if_running(audit_id, "test_reset")

        with runtime.transaction() as session:
            states = tuple(
                session.scalars(
                    select(InternalLinkEventModel.event_type)
                    .where(InternalLinkEventModel.audit_id == audit_id)
                    .order_by(InternalLinkEventModel.sequence)
                )
            )
        assert states == ("created", "claiming", "failed")
        assert repository.get(audit_id)["state"] == "failed"  # type: ignore[index]
    finally:
        runtime.dispose()


def test_incremental_lifecycle_persistence_sequences_and_completed_with_warnings(
    tmp_path: Path,
) -> None:
    runtime, _service_instance, _run_id, audit_id = _completed(tmp_path)
    try:
        with runtime.transaction() as session:
            events = tuple(
                session.scalars(
                    select(InternalLinkEventModel)
                    .where(InternalLinkEventModel.audit_id == audit_id)
                    .order_by(InternalLinkEventModel.sequence)
                )
            )
            assert tuple(row.sequence for row in events) == tuple(range(len(events)))
            assert tuple(row.event_type for row in events) == (
                "created",
                "claiming",
                "building_graph",
                "computing_metrics",
                "analyzing_reachability",
                "analyzing_anchors",
                "building_opportunities",
                "completed",
            )
            counts = {
                model.__tablename__: int(
                    session.scalar(
                        select(text("count(*)"))
                        .select_from(model)
                        .where(model.audit_id == audit_id)
                    )
                    or 0
                )
                for model in (
                    InternalLinkPageMetricModel,
                    InternalLinkEdgeModel,
                    InternalLinkReachabilityModel,
                    InternalLinkFindingModel,
                    InternalLinkAnchorModel,
                    InternalLinkOpportunityModel,
                )
            }
        assert counts["internal_link_page_metrics"] > 0
        assert counts["internal_link_edges"] > 0
        assert counts["internal_link_reachability"] > 0
        assert counts["internal_link_findings"] > 0
        assert counts["internal_link_anchor_aggregates"] > 0
        assert counts["internal_link_opportunities"] > 0

        repository = SQLAlchemyInternalLinkRepository(runtime)
        # Finalization policy is exercised independently because one deterministic
        # audit identity per run intentionally prevents duplicate audit creation.
        with runtime.transaction() as session:
            row = session.get(InternalLinkAuditModel, audit_id)
            assert row is not None
            row.state = "building_opportunities"
            row.completed_at = None
        warning = repository.finalize(audit_id, warning_count=1)
        assert warning["state"] == "completed_with_warnings"
        assert warning["warning_count"] == 1
    finally:
        runtime.dispose()


def test_terminal_failure_cancellation_and_startup_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, service, run_id = _service(tmp_path)
    repository = SQLAlchemyInternalLinkRepository(runtime)
    try:
        failed_id = str(service.create_audit(run_id)["audit_id"])
        with runtime.transaction() as session:
            row = session.get(InternalLinkAuditModel, failed_id)
            assert row is not None
            row.seed_url = "https://example.test/missing-seed"
        with pytest.raises(ValueError, match="seed_unavailable"):
            asyncio.run(service.execute_audit(failed_id))
        assert repository.get(failed_id)["state"] == "failed"  # type: ignore[index]

        with runtime.transaction() as session:
            row = session.get(InternalLinkAuditModel, failed_id)
            assert row is not None
            session.delete(row)
        cancelled_id = str(service.create_audit(run_id)["audit_id"])

        def cancel(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise asyncio.CancelledError

        monkeypatch.setattr(service, "_execute_claimed", cancel)
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(service.execute_audit(cancelled_id))
        assert repository.get(cancelled_id)["state"] == "cancelled"  # type: ignore[index]

        with runtime.transaction() as session:
            row = session.get(InternalLinkAuditModel, cancelled_id)
            assert row is not None
            session.delete(row)
        interrupted_id = str(service.create_audit(run_id)["audit_id"])
        assert repository.claim_execution(interrupted_id)
        InternalLinkAuditService(service.configuration, repository, service._artifacts)
        interrupted = repository.get(interrupted_id)
        assert interrupted is not None
        assert interrupted["state"] == "failed"
        assert interrupted["failure_code"] == "internal_link_audit_interrupted"
    finally:
        runtime.dispose()


def test_constraints_cascade_cleanup_and_source_evidence_preservation(tmp_path: Path) -> None:
    runtime, service, run_id, audit_id = _completed(tmp_path)
    repository = SQLAlchemyInternalLinkRepository(runtime)
    source_count = len(repository.source_links(run_id))
    try:
        with pytest.raises(IntegrityError), runtime.transaction() as session:
            session.execute(
                text(
                    "UPDATE internal_link_page_metrics "
                    "SET inbound_occurrences = -1 WHERE audit_id = :audit_id"
                ),
                {"audit_id": audit_id},
            )
        with pytest.raises(IntegrityError), runtime.transaction() as session:
            metric = session.scalar(
                select(InternalLinkPageMetricModel).where(
                    InternalLinkPageMetricModel.audit_id == audit_id
                )
            )
            assert metric is not None
            session.add(
                InternalLinkPageMetricModel(
                    **{
                        column.name: getattr(metric, column.name)
                        for column in InternalLinkPageMetricModel.__table__.columns
                        if column.name != "metric_id"
                    },
                    metric_id="duplicate-sequence",
                )
            )

        with runtime.transaction() as session:
            session.execute(
                delete(InternalLinkAuditModel).where(InternalLinkAuditModel.audit_id == audit_id)
            )
        assert repository.get(audit_id) is None
        assert len(repository.source_links(run_id)) == source_count

        new_id = str(service.create_audit(run_id)["audit_id"])
        with runtime.transaction() as session:
            row = session.get(InternalLinkAuditModel, new_id)
            assert row is not None
            row.retention_until = datetime.now(UTC) - timedelta(seconds=1)
        assert service.cleanup() == 1
        assert repository.get(new_id) is None
        assert len(repository.source_links(run_id)) == source_count
    finally:
        runtime.dispose()


def test_cursor_pagination_filter_combinations_invalid_and_filter_bound(tmp_path: Path) -> None:
    runtime, service, _run_id, audit_id = _completed(tmp_path)
    try:
        first = service.list_pages(audit_id, page_size=2)
        assert len(first["items"]) == 2
        assert first["next_cursor"]
        second = service.list_pages(audit_id, first["next_cursor"], 2)
        assert {row["metric_id"] for row in first["items"]}.isdisjoint(
            row["metric_id"] for row in second["items"]
        )
        filtered = service.list_pages(
            audit_id,
            filters={"eligibility": "eligible", "severity": "high", "url": "example.com"},
        )
        assert all(row["eligibility"] == "eligible" for row in filtered["items"])
        assert all(row["severity"] == "high" for row in filtered["items"])
        with pytest.raises(ValueError, match="cursor_filter_mismatch"):
            service.list_pages(
                audit_id,
                first["next_cursor"],
                2,
                {"severity": "high"},
            )
        with pytest.raises(ValueError, match="cursor_invalid"):
            service.list_pages(audit_id, "not-a-cursor", 2)
        with pytest.raises(ValueError, match="invalid_page_size"):
            service.list_pages(audit_id, page_size=21)
    finally:
        runtime.dispose()


def test_all_exports_register_verify_download_and_detect_missing_corrupt_unsafe(
    tmp_path: Path,
) -> None:
    runtime, service, _run_id, audit_id = _completed(tmp_path)
    artifacts = service._artifacts
    assert artifacts is not None
    try:
        exported = {
            export_format: service.create_export(audit_id, export_format)
            for export_format in InternalLinkExportFormat
        }
        assert len(service.list_exports(audit_id)) == len(InternalLinkExportFormat)
        for export_format, row in exported.items():
            artifact_id = str(row["artifact_id"])
            verified = artifacts.verify(artifact_id)
            assert verified.integrity_state is ArtifactIntegrityState.VERIFIED
            descriptor = artifacts.prepare_download(artifact_id)
            content = b"".join(descriptor.iterator_factory())
            assert content
            assert descriptor.byte_count == len(content)
            if export_format.value.endswith("_csv"):
                assert content.splitlines()[0]

        missing_id = str(exported[InternalLinkExportFormat.JSON]["artifact_id"])
        missing_record = artifacts.get(missing_id)
        (tmp_path / "artifacts" / missing_record.relative_path).unlink()
        assert artifacts.verify(missing_id).integrity_state is ArtifactIntegrityState.MISSING

        corrupt_id = str(exported[InternalLinkExportFormat.MARKDOWN]["artifact_id"])
        corrupt_record = artifacts.get(corrupt_id)
        (tmp_path / "artifacts" / corrupt_record.relative_path).write_bytes(b"corrupt")
        assert artifacts.verify(corrupt_id).integrity_state in {
            ArtifactIntegrityState.SIZE_MISMATCH,
            ArtifactIntegrityState.HASH_MISMATCH,
        }
    finally:
        runtime.dispose()


def test_authenticated_artifact_download_and_private_export_api(tmp_path: Path) -> None:
    runtime, service, _run_id, audit_id = _completed(tmp_path)
    token = "phase-23-artifact-download-token-123456789"
    settings = ProductionSettings.model_validate(
        {"enabled": True, "bearer_token": token, "include_openapi": True}
    )
    artifacts = service._artifacts
    assert artifacts is not None
    app = create_production_app(
        _SecurityTestService(),
        settings,
        Settings(),
        artifacts=artifacts,
        internal_link_audits=service,
    )
    client = TestClient(app, client=("203.0.113.10", 50_000))
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = client.post(
            f"/api/internal/v1/audits/internal-links/{audit_id}/exports",
            json={"format": "json"},
            headers=headers,
        )
        assert response.status_code == 200
        artifact_id = response.json()["data"]["artifact_id"]
        assert client.get(f"/api/internal/v1/artifacts/{artifact_id}/download").status_code == 401
        downloaded = client.get(
            f"/api/internal/v1/artifacts/{artifact_id}/download", headers=headers
        )
        assert downloaded.status_code == 200
        assert downloaded.content
    finally:
        runtime.dispose()
