"""Phase 25 structured-data lifecycle, persistence, export, and API coverage."""

# ruff: noqa: PLR0915, TRY003

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
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
from musimack_tools.domain.page_evidence import PageEvidenceConfiguration
from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.domain.structured_data_audit import (
    FINDING_CODES,
    RECOMMENDATION_ACTIONS,
    StructuredDataAuditConfiguration,
    StructuredDataExportFormat,
)
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.migrations import upgrade_to_head
from musimack_tools.persistence.repositories import SQLAlchemyPersistenceRepository
from musimack_tools.persistence.structured_data_models import (
    CrawlStructuredDataEvidenceModel,
    StructuredDataEventModel,
    StructuredDataProfileModel,
)
from musimack_tools.persistence.structured_data_repository import (
    SQLAlchemyStructuredDataAuditRepository,
)
from musimack_tools.structured_data_audit.service import StructuredDataAuditService
from page_evidence_helpers import PageRecordOptions, crawl_result, page_record
from persistence_helpers import BACKEND_ROOT, sample_request, sample_result, sample_snapshot

if TYPE_CHECKING:
    from pathlib import Path

    from musimack_tools.persistence.engine import PersistenceRuntime


def _service(tmp_path: Path) -> tuple[PersistenceRuntime, StructuredDataAuditService, str]:
    database = tmp_path / "structured-data.db"
    upgrade_to_head(f"sqlite+pysqlite:///{database.as_posix()}", backend_root=BACKEND_ROOT)
    configuration = StructuredDataAuditConfiguration(
        enabled=True, default_page_size=2, maximum_page_size=50, minimum_sitewide_pages=2
    )
    runtime = create_persistence_runtime(
        PersistenceConfiguration(
            enabled=True,
            database_path=database,
            page_evidence=PageEvidenceConfiguration(enabled=True),
            structured_data_audit=configuration,
        )
    )
    request = sample_request()
    snapshot = sample_snapshot(request)
    persistence = SQLAlchemyPersistenceRepository(runtime)
    assert persistence.record_submission(snapshot, request).succeeded
    root = page_record(
        options=PageRecordOptions(
            body="""
            <script type="application/ld+json">
            {"@context":"https://schema.org","@type":"Organization","@id":"#org",
             "name":"Example","url":"https://example.com"}
            </script>
            <script type="application/ld+json">{"@type":"Product","name":""}</script>
            <article itemscope itemtype="Article">
              <meta itemprop="headline" content="News">
            </article>
            """,
            x_robots=(),
        )
    )
    second = page_record(
        "https://example.com/about",
        PageRecordOptions(
            body="""<script type="application/ld+json">
            {"@context":"https://schema.org","@type":"Organization","@id":"#org",
             "name":"Different","url":"/relative"}</script>""",
            discovery_order=1,
            x_robots=(),
        ),
    )
    result = replace(sample_result(request), crawl_result=crawl_result((root, second)))
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
            roots=(ArtifactStorageRootConfiguration("phase25", artifact_root),),
            default_root_id="phase25",
            allow_csv=True,
        ),
        SQLAlchemyArtifactRepository(runtime),
    )
    return (
        runtime,
        StructuredDataAuditService(
            configuration, SQLAlchemyStructuredDataAuditRepository(runtime), artifacts
        ),
        snapshot.run_id,
    )


def test_structured_data_audit_is_durable_deterministic_and_exportable(tmp_path: Path) -> None:
    runtime, service, run_id = _service(tmp_path)
    try:
        evidence = service.evidence_status(run_id)
        assert evidence["ready"] and evidence["block_count"] == 4
        audit = service.create_audit(run_id)
        completed = asyncio.run(service.execute_audit(str(audit["audit_id"])))
        assert completed["state"] == "completed_with_warnings"
        assert completed["total_pages"] == 2
        assert completed["total_blocks"] == 4
        audit_id = str(completed["audit_id"])
        assert service.list_resource(audit_id, "blocks", None, 20)["items"]
        assert service.list_resource(audit_id, "entities", None, 20)["items"]
        assert service.list_resource(audit_id, "properties", None, 20)["items"]
        assert service.list_resource(audit_id, "profiles", None, 20)["items"]
        finding_codes = {
            item["code"]
            for name in ("parse-findings", "consistency-findings")
            for item in service.list_resource(audit_id, name, None, 50)["items"]
        }
        assert finding_codes <= FINDING_CODES
        assert {"json_ld_missing_context", "property_empty_value"} <= finding_codes
        for resource_name in ("parse-findings", "consistency-findings"):
            for finding in service.list_resource(audit_id, resource_name, None, 50)["items"]:
                assert finding["confidence"] in {"high", "medium", "low", "indeterminate"}
                assert isinstance(finding["requires_human_review"], bool)
        actions = {
            item["action"]
            for item in service.list_resource(audit_id, "recommendations", None, 50)["items"]
        }
        assert actions <= RECOMMENDATION_ACTIONS
        recommendations = service.list_resource(audit_id, "recommendations", None, 50)["items"]
        assert recommendations
        for recommendation in recommendations:
            assert recommendation["requires_human_review"] is True
            assert recommendation["scope"] in {"page", "entity", "site"}
            assert recommendation["occurrence_count"] >= 1
            assert recommendation["affected_page_count"] >= 0
            assert isinstance(json.loads(recommendation["supporting_finding_ids_json"]), list)
            assert isinstance(json.loads(recommendation["supporting_evidence_json"]), dict)
        json_content = service._render_export(  # noqa: SLF001
            audit_id, StructuredDataExportFormat.JSON
        )[0]
        json_export = json.loads(json_content)
        assert json_export["schema_name"] == "musimack-structured-data-audit"
        assert json_export["schema_version"] == "1.0"
        assert json_export["audit"]["audit_id"] == audit_id
        assert json_export["evidence_version"] == "seo-toolkit-structured-data-evidence-v1"
        assert set(json_export) == {
            "audit",
            "blocks",
            "duplicate_groups",
            "entities",
            "evidence_version",
            "findings",
            "page_summaries",
            "profiles",
            "properties",
            "recommendations",
            "references",
            "schema_name",
            "schema_version",
            "scope",
            "summary",
            "truncation",
            "warnings",
        }
        assert set(json_export["truncation"]) == {
            "collection_cap",
            "collections",
            "field_cap",
            "omitted_counts",
            "truncated",
        }
        markdown = service._render_export(  # noqa: SLF001
            audit_id, StructuredDataExportFormat.MARKDOWN
        )[0]
        for heading in (
            "Executive Summary",
            "Scope",
            "Evidence Readiness",
            "Format Distribution",
            "Type Distribution",
            "Parse and Syntax Findings",
            "Entity Consistency Findings",
            "Page-Level Findings",
            "Sitewide Findings",
            "Duplicate Groups",
            "Profile Observations",
            "Recommendations",
            "Limitations",
            "Human-Review Notes",
        ):
            assert f"## {heading}" in markdown
        for export_format in StructuredDataExportFormat:
            exported = service.create_export(audit_id, export_format)
            assert exported["artifact_id"]
            assert exported["state"] == "completed"
        assert len(service.list_exports(audit_id)) == 8
        with runtime.transaction() as session:
            retained = session.query(CrawlStructuredDataEvidenceModel).all()
            assert len(retained) == 4
            assert all("<script" not in row.raw_value for row in retained)
            assert all(row.diagnostics_json is not None for row in retained)
            for index, state in enumerate(
                (
                    "present",
                    "missing",
                    "empty",
                    "invalid",
                    "conflicting",
                    "not_applicable",
                    "indeterminate",
                )
            ):
                session.add(
                    StructuredDataProfileModel(
                        id=f"profile-state-{index}",
                        audit_id=audit_id,
                        entity_id="profile-contract-entity",
                        profile_name="Organization",
                        profile_version="seo-toolkit-structured-data-profiles-v1",
                        property_name=f"contract-{index}",
                        observation_state=state,
                        explanation="Non-certifying persistence round trip.",
                        created_at=datetime.now(UTC),
                    )
                )
        profile_states = {
            item["observation_state"]
            for item in service.list_resource(audit_id, "profiles", None, 50)["items"]
            if str(item["id"]).startswith("profile-state-")
        }
        assert profile_states == {
            "present",
            "missing",
            "empty",
            "invalid",
            "conflicting",
            "not_applicable",
            "indeterminate",
        }
    finally:
        runtime.dispose()


def test_structured_data_routes_are_private_and_permission_mapped(tmp_path: Path) -> None:
    runtime, service, run_id = _service(tmp_path)
    token = "phase-25-structured-data-token-123456789"  # noqa: S105
    settings = ProductionSettings.model_validate(
        {"enabled": True, "bearer_token": token, "include_openapi": True}
    )
    app = create_production_app(
        _SecurityTestService(), settings, Settings(), structured_data_audits=service
    )
    client = TestClient(app, client=("203.0.113.10", 50_000))
    headers = {"Authorization": f"Bearer {token}"}
    base = "/api/internal/v1/audits/structured-data"
    try:
        assert client.get(base).status_code == 401
        assert client.get("/api/audits/structured-data", headers=headers).status_code == 404
        assert client.get(f"{base}/evidence/{run_id}", headers=headers).status_code == 200
        created = client.post(base, json={"run_id": run_id}, headers=headers)
        assert created.status_code == 200
        audit_id = created.json()["data"]["audit_id"]
        assert client.get(f"{base}/{audit_id}", headers=headers).status_code == 200
        assert client.post(f"{base}/{audit_id}/execute", headers=headers).status_code == 200
        resource_responses: dict[str, dict[str, object]] = {}
        for resource in (
            "summary",
            "blocks",
            "entities",
            "properties",
            "pages",
            "parse-findings",
            "consistency-findings",
            "duplicate-groups",
            "profiles",
            "recommendations",
            "exports",
        ):
            resource_response = client.get(f"{base}/{audit_id}/{resource}", headers=headers)
            assert resource_response.status_code == 200
            resource_responses[resource] = resource_response.json()["data"]
        first_finding = resource_responses["parse-findings"]["items"][0]  # type: ignore[index]
        assert {"confidence", "requires_human_review"} <= set(first_finding)
        first_recommendation = resource_responses["recommendations"]["items"][0]  # type: ignore[index]
        assert {
            "confidence",
            "requires_human_review",
            "scope",
            "occurrence_count",
            "affected_page_count",
            "supporting_finding_ids_json",
            "supporting_evidence_json",
        } <= set(first_recommendation)
        assert (
            client.get(
                f"{base}/{audit_id}/parse-findings?confidence={first_finding['confidence']}",
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            client.get(f"{base}/{audit_id}/blocks?cursor=invalid", headers=headers).status_code
            == 400
        )
        assert client.get(f"{base}/missing-audit", headers=headers).status_code == 404
        assert (
            client.post(
                f"{base}/{audit_id}/exports", json={"format": "json"}, headers=headers
            ).status_code
            == 200
        )
        operations = {
            (method.upper(), path)
            for path, definition in app.openapi()["paths"].items()
            if path.startswith(base)
            for method in definition
            if method in {"get", "post", "put", "patch", "delete"}
        }
        assert len(operations) == 17
        for method, path in operations:
            expected = Permission.JOBS_SUBMIT if method == "POST" else Permission.RUNS_VIEW
            assert permission_for_request(method, path) is expected
        protected_paths = [
            f"{base}/evidence/{run_id}",
            base,
            f"{base}/{audit_id}",
            *(f"{base}/{audit_id}/{resource}" for resource in resource_responses),
        ]
        for path in protected_paths:
            assert client.get(path).status_code == 401
        assert client.post(base, json={"run_id": run_id}).status_code == 401
        assert client.post(f"{base}/{audit_id}/execute", json={}).status_code == 401
        assert client.post(f"{base}/{audit_id}/exports", json={"format": "json"}).status_code == 401
    finally:
        runtime.dispose()


def test_structured_data_execution_claim_failure_cancellation_and_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, seeded_service, run_id = _service(tmp_path)
    repository = SQLAlchemyStructuredDataAuditRepository(runtime)
    context = repository.run_context(run_id)
    assert context is not None
    job_id = context[0]
    try:
        claim_config = replace(seeded_service.configuration, maximum_export_rows=90_001)
        claimed = repository.create("audit-claim", job_id, run_id, claim_config)
        assert claimed["state"] == "accepted"
        assert repository.claim_execution("audit-claim") is True
        assert repository.claim_execution("audit-claim") is False

        # A new service performs accepted startup reconciliation for interrupted work.
        reconciled_service = StructuredDataAuditService(claim_config, repository)
        reconciled = reconciled_service.get("audit-claim")
        assert reconciled["state"] == "failed"
        assert reconciled["failure_code"] == "structured_data_audit_interrupted"

        failure_config = replace(seeded_service.configuration, maximum_export_rows=90_002)
        repository.create("audit-failure", job_id, run_id, failure_config)
        failure_service = StructuredDataAuditService(failure_config, repository)

        def fail_analysis(*_args: object) -> dict[str, list[dict[str, object]]]:
            raise RuntimeError("deterministic test failure")

        monkeypatch.setattr(failure_service, "_analyze", fail_analysis)
        with pytest.raises(RuntimeError, match="deterministic test failure"):
            asyncio.run(failure_service.execute_audit("audit-failure"))
        assert failure_service.get("audit-failure")["state"] == "failed"

        cancelled_config = replace(seeded_service.configuration, maximum_export_rows=90_003)
        repository.create("audit-cancelled", job_id, run_id, cancelled_config)
        cancelled_service = StructuredDataAuditService(cancelled_config, repository)

        def cancel_analysis(*_args: object) -> dict[str, list[dict[str, object]]]:
            raise asyncio.CancelledError

        monkeypatch.setattr(cancelled_service, "_analyze", cancel_analysis)
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(cancelled_service.execute_audit("audit-cancelled"))
        assert cancelled_service.get("audit-cancelled")["state"] == "cancelled"

        with runtime.transaction() as session:
            events = tuple(
                session.query(StructuredDataEventModel)
                .filter(StructuredDataEventModel.audit_id == "audit-cancelled")
                .order_by(StructuredDataEventModel.event_id)
            )
            assert [event.state for event in events] == ["accepted", "claiming", "cancelled"]
    finally:
        runtime.dispose()
