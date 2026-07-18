"""Direct readiness and export contracts for migration QA."""

# ruff: noqa: ANN401, ARG005, SLF001

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from musimack_tools.domain.migration_qa import (
    MIGRATION_QA_EXPORT_SCHEMA,
    MigrationQaConfiguration,
    MigrationQaExportFormat,
    stable_json,
)
from musimack_tools.domain.page_evidence import PAGE_EVIDENCE_VERSION
from musimack_tools.migration_qa.service import MigrationQaService

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class ContractRepository:
    def __init__(self) -> None:
        self.project = {
            "project_id": "project-1",
            "job_id": "job-1",
            "destination_run_id": "destination-run",
            "source_run_id": None,
            "source_origin": "https://old.example",
            "destination_origin": "https://www.example",
            "configuration_json": stable_json(MigrationQaConfiguration(enabled=True).snapshot()),
            "state": "completed_with_warnings",
            "readiness": "ready",
            "updated_at": NOW,
        }
        self.context: tuple[str, str, bool, int, int] | None = (
            "job-1",
            "https://www.example",
            True,
            1,
            0,
        )
        self.inventory = {
            "page_count": 1,
            "page_versions": [PAGE_EVIDENCE_VERSION],
            "expired": False,
            "link_count": 0,
            "sitemap_count": 0,
            "image_count": 0,
            "structured_data_count": 0,
        }
        self.resources: dict[str, tuple[dict[str, Any], ...]] = {
            "sources": (
                {
                    "id": "source-1",
                    "project_id": "project-1",
                    "sequence": 0,
                    "raw_url": "https://old.example/a",
                    "normalized_url": "https://old.example/a",
                    "state": "valid",
                },
            ),
            "redirect-map": (),
            "mappings": (),
            "redirects": (),
            "comparisons": (),
            "findings": (),
            "recommendations": (),
            "sitewide": (),
        }

    def get(self, project_id: str) -> dict[str, Any] | None:
        return self.project if project_id == "project-1" else None

    def run_context(self, _run_id: str) -> tuple[str, str, bool, int, int] | None:
        return self.context

    def evidence_inventory(self, _run_id: str) -> dict[str, Any]:
        return self.inventory

    def list_resource(self, _project_id: str, name: str) -> tuple[dict[str, Any], ...]:
        return self.resources[name]

    def set_readiness(self, _project_id: str, readiness: str) -> dict[str, Any]:
        self.project["readiness"] = readiness
        return {**self.project, "state": "ready" if readiness.startswith("ready") else "draft"}

    def upsert_export(self, values: dict[str, Any]) -> dict[str, Any]:
        return values


class CapturingArtifacts:
    class Configuration:
        enabled = True

    configuration = Configuration()

    def __init__(self) -> None:
        self.content = b""

    def store_bytes(self, **values: Any) -> Any:
        self.content = cast("bytes", values["content"])
        return type("Artifact", (), {"artifact_id": hashlib.sha256(self.content).hexdigest()})()


def service(
    repository: ContractRepository,
    configuration: MigrationQaConfiguration | None = None,
    artifacts: CapturingArtifacts | None = None,
) -> MigrationQaService:
    return MigrationQaService(
        configuration or MigrationQaConfiguration(enabled=True),
        cast("Any", repository),
        cast("Any", artifacts),
    )


@pytest.mark.parametrize(
    ("expected", "mutate"),
    [
        ("ready", lambda repo: None),
        ("missing_evidence", lambda repo: setattr(repo, "context", None)),
        (
            "missing_evidence",
            lambda repo: setattr(repo, "context", ("job", "url", False, 1, 0)),
        ),
        (
            "missing_evidence",
            lambda repo: setattr(repo, "context", ("job", "url", True, 0, 0)),
        ),
        (
            "expired",
            lambda repo: repo.inventory.update({"expired": True}),
        ),
        (
            "incompatible",
            lambda repo: repo.inventory.update({"page_versions": ["unsupported"]}),
        ),
        (
            "ready_with_warnings",
            lambda repo: repo.resources.update(
                {"redirect-map": ({"id": "r", "state": "conflict", "sequence": 0},)}
            ),
        ),
    ],
)
def test_readiness_production_states(expected: str, mutate: Any) -> None:
    repository = ContractRepository()
    mutate(repository)
    assert service(repository).readiness("project-1")["readiness"] == expected


def test_invalid_configuration_and_enabled_optional_evidence_paths() -> None:
    repository = ContractRepository()
    repository.project["configuration_json"] = '{"maximum_page_size":0}'
    assert service(repository).readiness("project-1")["readiness"] == "invalid_configuration"
    repository = ContractRepository()
    repository.project["configuration_json"] = stable_json(
        MigrationQaConfiguration(
            enabled=True,
            compare_internal_links=True,
            compare_sitemaps=True,
            compare_images=True,
            compare_structured_data=True,
        ).snapshot()
    )
    result = service(repository).readiness("project-1")
    assert result["readiness"] == "ready_with_warnings"
    assert set(result["reasons"]) >= {
        "internal_link_evidence_missing",
        "sitemap_evidence_missing",
        "image_evidence_missing",
        "structured_data_evidence_missing",
    }


@pytest.mark.parametrize(
    ("export_format", "resource", "expected_header"),
    [
        (MigrationQaExportFormat.MAPPINGS_CSV, "mappings", "id,project_id,source_row_id"),
        (MigrationQaExportFormat.REDIRECTS_CSV, "redirects", "id,project_id,mapping_id"),
        (MigrationQaExportFormat.COMPARISONS_CSV, "comparisons", "id,project_id,mapping_id"),
        (MigrationQaExportFormat.FINDINGS_CSV, "findings", "stable_id,project_id,sequence"),
        (
            MigrationQaExportFormat.RECOMMENDATIONS_CSV,
            "recommendations",
            "stable_id,project_id,sequence",
        ),
        (MigrationQaExportFormat.SITEWIDE_CSV, "sitewide", "id,project_id,category"),
    ],
)
def test_empty_csv_exports_have_fixed_ordered_header(
    export_format: MigrationQaExportFormat, resource: str, expected_header: str
) -> None:
    repository = ContractRepository()
    repository.resources[resource] = ()
    content, media_type, _filename, rows, truncated = service(repository)._render_export(
        "project-1", export_format
    )
    assert media_type == "text/csv"
    assert content.startswith(expected_header)
    assert rows == 0
    assert not truncated


def test_csv_formula_protection_cell_bounds_numeric_integrity_and_row_truncation() -> None:
    repository = ContractRepository()
    repository.resources["findings"] = tuple(
        {
            "stable_id": f"finding-{index}",
            "project_id": "project-1",
            "sequence": index,
            "code": "destination_404",
            "category": "destination",
            "severity": "error",
            "confidence": "high",
            "requires_human_review": False,
            "mapping_id": "mapping-1",
            "source_url": "=FORMULA",
            "destination_url": "+FORMULA",
            "source_evidence_ids_json": "[]",
            "destination_evidence_ids_json": "[]",
            "reason": "@" + "x" * 50,
            "bounded_evidence_json": "{}",
            "occurrence_count": 301,
            "affected_page_count": 1,
        }
        for index in range(2)
    )
    content, _media, _filename, rows, truncated = service(
        repository,
        MigrationQaConfiguration(enabled=True, maximum_export_rows=1, maximum_field_characters=10),
    )._render_export("project-1", MigrationQaExportFormat.FINDINGS_CSV)
    parsed = next(csv.DictReader(io.StringIO(content)))
    assert parsed["source_url"] == "'=FORMULA"
    assert parsed["destination_url"] == "'+FORMULA"
    assert parsed["reason"].startswith("'@")
    assert len(parsed["reason"]) == 11
    assert parsed["occurrence_count"] == "301"
    assert parsed["export_truncated"] == "True"
    assert rows == 1
    assert truncated


def test_json_and_markdown_exports_have_complete_versioned_contracts() -> None:
    repository = ContractRepository()
    json_content, media, _filename, _rows, _truncated = service(repository)._render_export(
        "project-1", MigrationQaExportFormat.JSON
    )
    payload = json.loads(json_content)
    assert media == "application/json"
    assert payload["schema_name"] == MIGRATION_QA_EXPORT_SCHEMA
    assert payload["schema_version"] == "1.0"
    assert {
        "project",
        "policy",
        "evidence_versions",
        "scope",
        "readiness",
        "summary",
        "source_rows",
        "redirect_map_rows",
        "mappings",
        "redirect_observations",
        "page_comparisons",
        "findings",
        "recommendations",
        "warnings",
        "limitations",
        "truncation",
    } <= payload.keys()
    markdown, media, _filename, rows, _truncated = service(repository)._render_export(
        "project-1", MigrationQaExportFormat.MARKDOWN
    )
    assert media == "text/markdown"
    assert markdown.count("\n## ") == 18
    assert rows == 18


def test_export_registration_uses_artifact_sha256_identity() -> None:
    repository = ContractRepository()
    repository.project["state"] = "completed"
    artifacts = CapturingArtifacts()
    created = service(repository, artifacts=artifacts).create_export(
        "project-1", MigrationQaExportFormat.JSON
    )
    assert created["artifact_id"] == hashlib.sha256(artifacts.content).hexdigest()
