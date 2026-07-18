"""Deterministic website migration QA over retained, bounded crawl evidence."""

# ruff: noqa: ANN401, C901, PLR0912, PLR0913, PLR0915, PLR2004

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.domain.artifacts import ArtifactType
from musimack_tools.domain.migration_qa import (
    MIGRATION_QA_API_VERSION,
    MIGRATION_QA_EVIDENCE_VERSION,
    MIGRATION_QA_EXPORT_SCHEMA,
    MIGRATION_QA_POLICY_VERSION,
    MigrationQaConfiguration,
    MigrationQaExportFormat,
    MigrationQaReadiness,
    MigrationType,
    classify_migration_finding,
    decode_cursor,
    encode_cursor,
    stable_identity,
    stable_json,
)
from musimack_tools.domain.page_evidence import PAGE_EVIDENCE_VERSION
from musimack_tools.domain.urls import UrlNormalizationError
from musimack_tools.migration_qa.analysis import analyze_migration

if TYPE_CHECKING:
    from musimack_tools.artifacts.service import ArtifactService
    from musimack_tools.persistence.migration_qa_repository import SQLAlchemyMigrationQaRepository


_ACTION_BY_CODE = {
    "redirect_missing": "add_redirect",
    "redirect_wrong_destination": "correct_redirect_destination",
    "redirect_temporary": "replace_temporary_redirect",
    "redirect_chain": "remove_redirect_chain",
    "redirect_loop": "break_redirect_loop",
    "mapping_unmapped": "map_unmapped_source",
    "mapping_ambiguous": "resolve_ambiguous_mapping",
    "destination_error": "fix_destination_status",
    "destination_noindex": "remove_destination_noindex",
    "metadata_title_missing": "restore_title",
    "metadata_title_changed": "restore_title",
    "metadata_description_missing": "restore_description",
    "metadata_description_changed": "restore_description",
    "canonical_changed": "align_canonical",
    "internal_link_to_old_url": "update_internal_links_to_final_urls",
    "sitemap_missing_destination": "restore_sitemap_entry",
    "image_missing": "restore_image",
    "structured_missing": "restore_structured_data",
    "readiness_missing_evidence": "collect_missing_evidence",
}

_CSV_SCHEMAS: dict[str, tuple[str, ...]] = {
    "mappings": (
        "id",
        "project_id",
        "source_row_id",
        "source_url",
        "destination_url",
        "mapping_method",
        "cardinality",
        "confidence",
        "state",
        "bounded_evidence_json",
        "export_truncated",
    ),
    "redirects": (
        "id",
        "project_id",
        "mapping_id",
        "planned_destination_url",
        "observed_final_url",
        "observed_status",
        "hop_count",
        "chain_identity",
        "loop_identity",
        "truncated",
        "evidence_source",
        "state",
        "chain_json",
        "evidence_json",
        "export_truncated",
    ),
    "comparisons": (
        "id",
        "project_id",
        "mapping_id",
        "source_url",
        "destination_url",
        "status_state",
        "metadata_state",
        "content_state",
        "canonical_state",
        "indexability_state",
        "similarity_score",
        "comparison_basis_json",
        "evidence_json",
        "export_truncated",
    ),
    "findings": (
        "stable_id",
        "project_id",
        "sequence",
        "code",
        "category",
        "severity",
        "confidence",
        "requires_human_review",
        "mapping_id",
        "source_url",
        "destination_url",
        "source_evidence_ids_json",
        "destination_evidence_ids_json",
        "reason",
        "bounded_evidence_json",
        "occurrence_count",
        "affected_page_count",
        "export_truncated",
    ),
    "recommendations": (
        "stable_id",
        "project_id",
        "sequence",
        "action",
        "severity",
        "confidence",
        "requires_human_review",
        "scope",
        "source_url",
        "destination_url",
        "supporting_finding_ids_json",
        "supporting_evidence_json",
        "occurrence_count",
        "affected_page_count",
        "reason",
        "export_truncated",
    ),
    "sitewide": (
        "id",
        "project_id",
        "category",
        "metric_name",
        "numerator",
        "denominator",
        "ratio",
        "state",
        "evidence_json",
        "export_truncated",
    ),
}


class MigrationQaService:
    def __init__(
        self,
        configuration: MigrationQaConfiguration,
        repository: SQLAlchemyMigrationQaRepository,
        artifacts: ArtifactService | None = None,
    ) -> None:
        self.configuration = configuration
        self._repository = repository
        self._artifacts = artifacts

    def diagnostics(self) -> dict[str, Any]:
        return {
            "enabled": self.configuration.enabled,
            "persistence_ready": True,
            "migration_ready": True,
            "policy_version": MIGRATION_QA_POLICY_VERSION,
            "evidence_version": MIGRATION_QA_EVIDENCE_VERSION,
            "reconciled_projects": self._repository.reconcile_interrupted(),
        }

    def evidence_status(self, run_id: str) -> dict[str, Any]:
        context = self._repository.run_context(run_id)
        if context is None:
            raise ValueError("migration_qa_run_not_found")
        return {
            "run_id": run_id,
            "terminal": context[2],
            "page_count": context[3],
            "link_count": context[4],
            "readiness": "ready" if context[2] and context[3] else "missing_evidence",
        }

    def create_project(
        self,
        *,
        name: str,
        destination_run_id: str,
        destination_origin: str,
        mode: str,
        migration_type: MigrationType,
        source_run_id: str | None = None,
        source_origin: str | None = None,
        policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        destination = self._repository.run_context(destination_run_id)
        if destination is None:
            raise ValueError("migration_qa_run_not_found")
        normalized_destination = normalize_url(destination_origin).origin
        normalized_source = normalize_url(source_origin).origin if source_origin else None
        if source_run_id and self._repository.run_context(source_run_id) is None:
            raise ValueError("migration_qa_run_not_found")
        allowed_policy = {
            "preserve_query_parameters",
            "compare_fragments",
            "compare_internal_links",
            "compare_sitemaps",
            "compare_images",
            "compare_structured_data",
        }
        if set(policy or {}) - allowed_policy:
            raise ValueError("migration_qa_invalid_configuration")
        project_configuration = MigrationQaConfiguration(
            **{**self.configuration.snapshot(), **(policy or {})}
        )
        project_id = stable_identity(
            destination_run_id,
            source_run_id or "",
            normalized_destination,
            normalized_source or "",
            mode,
            migration_type.value,
            stable_json(project_configuration.snapshot()),
        )
        return self._repository.create(
            {
                "project_id": project_id,
                "job_id": destination[0],
                "destination_run_id": destination_run_id,
                "source_run_id": source_run_id,
                "name": name.strip(),
                "mode": mode,
                "migration_type": migration_type.value,
                "source_origin": normalized_source,
                "destination_origin": normalized_destination,
            },
            project_configuration,
        )

    def get(self, project_id: str) -> dict[str, Any]:
        return self._required(project_id)

    def list_projects(self, cursor: str | None, page_size: int | None) -> dict[str, Any]:
        return self._page("projects", self._repository.list_projects(), cursor, page_size, {})

    def ingest_source_inventory(self, project_id: str, content: str) -> dict[str, Any]:
        project = self._required(project_id)
        records = _parse_delimited(content, self.configuration.maximum_input_bytes)
        if len(records) > self.configuration.maximum_inventory_rows:
            raise ValueError("migration_qa_inventory_too_large")
        rows: list[dict[str, Any]] = []
        seen: dict[str, tuple[str | None, int]] = {}
        for sequence, record in enumerate(records):
            raw = _field(record, "source_url", "url", "source")
            proposed = _field(record, "destination_url", "proposed_destination_url", required=False)
            state, normalized, diagnostics = "valid", None, []
            if any(
                len(value) > self.configuration.maximum_field_characters
                for value in record.values()
            ):
                state = "invalid"
                diagnostics.append("inventory_field_too_long")
            try:
                value = _normalize_input(raw, project.get("source_origin"))
                normalized = value.normalized
                if project.get("source_origin") and value.origin != project["source_origin"]:
                    state = "out_of_scope"
                    diagnostics.append("inventory_out_of_scope")
                proposed_normalized = _normalized_or_none(
                    proposed, project.get("destination_origin")
                )
                if normalized in seen:
                    previous_destination, previous_index = seen[normalized]
                    if proposed_normalized != previous_destination and (
                        proposed_normalized or previous_destination
                    ):
                        if state == "valid":
                            state = "conflict"
                        diagnostics.append("inventory_conflicting_destination")
                        previous = rows[previous_index]
                        previous_diagnostics = _json_array(previous["diagnostics_json"])
                        if previous["state"] == "valid":
                            previous["state"] = "conflict"
                        if "inventory_conflicting_destination" not in previous_diagnostics:
                            previous_diagnostics.append("inventory_conflicting_destination")
                            previous["diagnostics_json"] = stable_json(previous_diagnostics)
                    elif state == "valid":
                        state = "duplicate"
                    diagnostics.append("inventory_duplicate_source")
                else:
                    seen[normalized] = (proposed_normalized, sequence)
            except UrlNormalizationError as error:
                if state == "valid":
                    state = "invalid"
                code = (
                    "inventory_unsupported_scheme"
                    if error.code.value == "unsupported_scheme"
                    else "inventory_invalid_url"
                )
                diagnostics.append(f"{code}:{error.code.value}")
                proposed_normalized = _normalized_or_none(
                    proposed, project.get("destination_origin")
                )
            rows.append(
                {
                    "id": stable_identity(project_id, "source", str(sequence)),
                    "project_id": project_id,
                    "sequence": sequence,
                    "raw_url": raw,
                    "normalized_url": normalized,
                    "comparison_url": normalized,
                    "proposed_destination_url": proposed_normalized,
                    "source_kind": record.get("source_kind", "inventory") or "inventory",
                    "state": state,
                    "diagnostics_json": stable_json(diagnostics),
                    "created_at": datetime.now(UTC),
                }
            )
        self._repository.replace_input(project_id, "sources", rows)
        return {
            "accepted_rows": len(rows),
            "invalid_rows": sum(row["state"] == "invalid" for row in rows),
        }

    def ingest_redirect_map(self, project_id: str, content: str) -> dict[str, Any]:
        project = self._required(project_id)
        records = _parse_delimited(content, self.configuration.maximum_input_bytes)
        if len(records) > self.configuration.maximum_redirect_rows:
            raise ValueError("migration_qa_redirect_map_too_large")
        rows: list[dict[str, Any]] = []
        seen: dict[str, tuple[str, int]] = {}
        destinations: dict[str, list[int]] = {}
        for sequence, record in enumerate(records):
            raw_source = _field(record, "source_url", "source")
            raw_destination = _field(record, "destination_url", "destination", "target")
            source = _normalized_or_none(raw_source, project.get("source_origin"))
            destination = _normalized_or_none(raw_destination, project.get("destination_origin"))
            diagnostics: list[str] = []
            state = "valid"
            if any(
                len(value) > self.configuration.maximum_field_characters
                for value in record.values()
            ):
                state = "invalid"
                diagnostics.append("redirect_map_invalid_url")
            if not source or not destination:
                state = "invalid"
                diagnostics.append("redirect_map_invalid_url")
            elif source in seen:
                code = (
                    "redirect_map_duplicate_source"
                    if seen[source][0] == destination
                    else "redirect_map_conflicting_destination"
                )
                if state == "valid":
                    state = "duplicate" if code.endswith("duplicate_source") else "conflict"
                diagnostics.append(code)
            if source and destination:
                seen.setdefault(source, (destination, sequence))
                if destination in destinations and source not in {
                    rows[index]["normalized_source_url"] for index in destinations[destination]
                }:
                    diagnostics.append("redirect_destination_collision")
                    for index in destinations[destination]:
                        previous = rows[index]
                        previous_diagnostics = _json_array(previous["diagnostics_json"])
                        if "redirect_destination_collision" not in previous_diagnostics:
                            previous_diagnostics.append("redirect_destination_collision")
                            previous["diagnostics_json"] = stable_json(previous_diagnostics)
                destinations.setdefault(destination, []).append(sequence)
            expected_raw = record.get("status", record.get("expected_status", ""))
            expected = int(expected_raw) if str(expected_raw).isdigit() else None
            if expected is not None and expected not in {301, 302, 307, 308}:
                state = "invalid"
                diagnostics.append("redirect_map_unsupported_status")
            elif expected is None:
                diagnostics.append("redirect_map_status_missing")
            rows.append(
                {
                    "id": stable_identity(project_id, "redirect", str(sequence)),
                    "project_id": project_id,
                    "sequence": sequence,
                    "raw_source_url": raw_source,
                    "raw_destination_url": raw_destination,
                    "normalized_source_url": source,
                    "normalized_destination_url": destination,
                    "expected_status": expected,
                    "state": state,
                    "diagnostics_json": stable_json(diagnostics),
                    "created_at": datetime.now(UTC),
                }
            )
        _annotate_planned_graph(rows)
        self._repository.replace_input(project_id, "redirect-map", rows)
        return {
            "accepted_rows": len(rows),
            "invalid_rows": sum(row["state"] == "invalid" for row in rows),
        }

    def preview_input(self, project_id: str, kind: str, content: str) -> dict[str, Any]:
        project = self._required(project_id)
        records = _parse_delimited(content, self.configuration.maximum_input_bytes)
        maximum = (
            self.configuration.maximum_inventory_rows
            if kind == "source_inventory"
            else self.configuration.maximum_redirect_rows
        )
        if len(records) > maximum:
            raise ValueError("migration_qa_input_too_large")
        rows: list[dict[str, Any]] = []
        for sequence, record in enumerate(records[:25]):
            errors: list[str] = []
            source = _field(record, "source_url", "url", "source", required=False)
            destination = _field(
                record,
                "destination_url",
                "proposed_destination_url",
                "destination",
                "target",
                required=False,
            )
            source_origin = project.get("source_origin")
            destination_origin = project.get("destination_origin")
            if not source or _normalized_or_none(source, source_origin) is None:
                errors.append("invalid_source_url")
            if kind == "redirect_map" and (
                not destination or _normalized_or_none(destination, destination_origin) is None
            ):
                errors.append("invalid_destination_url")
            if any(
                len(value) > self.configuration.maximum_field_characters
                for value in record.values()
            ):
                errors.append("field_too_long")
            rows.append(
                {
                    "sequence": sequence,
                    "source_url": source,
                    "destination_url": destination or None,
                    "status": record.get("status") or record.get("expected_status") or None,
                    "errors": errors,
                }
            )
        return {
            "kind": kind,
            "row_count": len(records),
            "preview_count": len(rows),
            "truncated": len(records) > len(rows),
            "rows": rows,
            "valid": all(not row["errors"] for row in rows),
        }

    def readiness(self, project_id: str) -> dict[str, Any]:
        project = self._required(project_id)
        destination = self._repository.run_context(project["destination_run_id"])
        sources = self._repository.list_resource(project_id, "sources")
        reasons: list[str] = []
        status = MigrationQaReadiness.READY
        inventory = self._evidence_inventory(project["destination_run_id"])
        configuration_invalid = False
        try:
            project_configuration = self._project_configuration(project)
        except TypeError, ValueError, json.JSONDecodeError:
            configuration_invalid = True
            project_configuration = self.configuration
            status = MigrationQaReadiness.INVALID_CONFIGURATION
            reasons.append("configuration_snapshot_invalid")
        if destination is None:
            status = MigrationQaReadiness.MISSING_EVIDENCE
            reasons.append("destination_run_missing")
        elif not destination[2]:
            status = MigrationQaReadiness.MISSING_EVIDENCE
            reasons.append("destination_run_nonterminal")
        elif not destination[3]:
            status = MigrationQaReadiness.MISSING_EVIDENCE
            reasons.append("destination_page_evidence_missing")
        elif inventory.get("expired"):
            status = MigrationQaReadiness.EXPIRED
            reasons.append("destination_page_evidence_expired")
        elif set(inventory.get("page_versions", ())) - {PAGE_EVIDENCE_VERSION}:
            status = MigrationQaReadiness.INCOMPATIBLE
            reasons.append("destination_page_evidence_version_unsupported")
        if not sources:
            status = MigrationQaReadiness.MISSING_EVIDENCE
            reasons.append("source_inventory_missing")
        elif any(row["state"] in {"invalid", "conflict"} for row in sources):
            if status is MigrationQaReadiness.READY:
                status = MigrationQaReadiness.READY_WITH_WARNINGS
            reasons.append("source_inventory_contains_invalid_rows")
        redirect_rows = self._repository.list_resource(project_id, "redirect-map")
        if any(row["state"] in {"invalid", "conflict"} for row in redirect_rows):
            if status is MigrationQaReadiness.READY:
                status = MigrationQaReadiness.READY_WITH_WARNINGS
            reasons.append("redirect_map_contains_invalid_or_conflicting_rows")
        source_run_id = project.get("source_run_id")
        if source_run_id:
            source_context = self._repository.run_context(source_run_id)
            if source_context is None or not source_context[2] or not source_context[3]:
                if status is MigrationQaReadiness.READY:
                    status = MigrationQaReadiness.READY_WITH_WARNINGS
                reasons.append("source_comparison_evidence_missing")
        for enabled, count_key, reason in (
            (
                project_configuration.compare_internal_links,
                "link_count",
                "internal_link_evidence_missing",
            ),
            (project_configuration.compare_sitemaps, "sitemap_count", "sitemap_evidence_missing"),
            (project_configuration.compare_images, "image_count", "image_evidence_missing"),
            (
                project_configuration.compare_structured_data,
                "structured_data_count",
                "structured_data_evidence_missing",
            ),
        ):
            if enabled and not inventory.get(count_key):
                if status is MigrationQaReadiness.READY:
                    status = MigrationQaReadiness.READY_WITH_WARNINGS
                reasons.append(reason)
        if configuration_invalid:
            status = MigrationQaReadiness.INVALID_CONFIGURATION
        updated = self._repository.set_readiness(project_id, status.value)
        return {
            "project_id": project_id,
            "readiness": status.value,
            "reasons": reasons,
            "state": updated["state"],
            "evidence": inventory,
        }

    def _evidence_inventory(self, run_id: str) -> dict[str, Any]:
        factory = getattr(self._repository, "evidence_inventory", None)
        if factory is None:
            context = self._repository.run_context(run_id)
            return {
                "page_count": context[3] if context else 0,
                "page_versions": [PAGE_EVIDENCE_VERSION] if context and context[3] else [],
                "expired": False,
                "link_count": context[4] if context else 0,
                "sitemap_count": 0,
                "image_count": 0,
                "structured_data_count": 0,
            }
        return dict(factory(run_id))

    async def execute_project(self, project_id: str) -> dict[str, Any]:
        readiness = self.readiness(project_id)
        if readiness["readiness"] not in {"ready", "ready_with_warnings"}:
            raise ValueError("migration_qa_missing_evidence")
        if readiness["readiness"] == "ready_with_warnings":
            self._repository.set_readiness(project_id, "ready")
        if not self._repository.claim_execution(project_id):
            raise ValueError("migration_qa_already_terminal")
        try:
            resources = self._analyze(project_id)
            warnings = len(resources["findings"])
            return self._repository.replace_analysis(project_id, resources, warnings)
        except Exception:
            self._repository.terminalize(project_id, "failed", "migration_qa_analysis_failed")
            raise

    def cancel(self, project_id: str) -> dict[str, Any]:
        self._required(project_id)
        if not self._repository.terminalize(project_id, "cancelled", None):
            raise ValueError("migration_qa_already_terminal")
        return self._required(project_id)

    def summary(self, project_id: str) -> dict[str, Any]:
        project = self._required(project_id)
        return {
            "project": project,
            "counts": {
                name: len(self._repository.list_resource(project_id, name))
                for name in (
                    "sources",
                    "redirect-map",
                    "mappings",
                    "redirects",
                    "comparisons",
                    "findings",
                    "recommendations",
                    "sitewide",
                )
            },
            "policy_version": MIGRATION_QA_POLICY_VERSION,
        }

    def list_resource(
        self,
        project_id: str,
        name: str,
        cursor: str | None,
        page_size: int | None,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        self._required(project_id)
        if name not in {
            "sources",
            "redirect-map",
            "mappings",
            "redirects",
            "comparisons",
            "findings",
            "recommendations",
            "sitewide",
        }:
            raise ValueError("migration_qa_invalid_resource")
        rows = self._repository.list_resource(project_id, name)
        for key, value in filters.items():
            if key == "search":
                rows = tuple(row for row in rows if str(value).lower() in stable_json(row).lower())
            elif key == "source_search":
                rows = tuple(
                    row
                    for row in rows
                    if str(value).lower()
                    in str(row.get("source_url") or row.get("raw_source_url") or "").lower()
                )
            elif key == "destination_search":
                rows = tuple(
                    row
                    for row in rows
                    if str(value).lower()
                    in str(
                        row.get("destination_url") or row.get("normalized_destination_url") or ""
                    ).lower()
                )
            else:
                rows = tuple(row for row in rows if str(row.get(key, "")) == str(value))
        return self._page(name, rows, cursor, page_size, filters)

    def create_export(
        self, project_id: str, export_format: MigrationQaExportFormat
    ) -> dict[str, Any]:
        project = self._required(project_id)
        if project["state"] not in {"completed", "completed_with_warnings"}:
            raise ValueError("migration_qa_export_conflict")
        if self._artifacts is None or not self._artifacts.configuration.enabled:
            raise ValueError("migration_qa_export_failed")
        content, media_type, filename, row_count, truncated = self._render_export(
            project_id, export_format
        )
        artifact_type = (
            ArtifactType.CSV_EXPORT
            if export_format.value.endswith("_csv")
            else ArtifactType.RUN_SUMMARY_MARKDOWN
            if export_format is MigrationQaExportFormat.MARKDOWN
            else ArtifactType.RUN_SUMMARY_JSON
        )
        artifact = self._artifacts.store_bytes(
            job_id=str(project["job_id"]),
            run_id=str(project["destination_run_id"]),
            artifact_type=artifact_type,
            filename=filename,
            content=content.encode(),
        )
        return self._repository.upsert_export(
            {
                "id": stable_identity(project_id, export_format.value),
                "project_id": project_id,
                "export_format": export_format.value,
                "media_type": media_type,
                "filename": filename,
                "artifact_id": artifact.artifact_id,
                "row_count": row_count,
                "truncated": truncated,
                "state": "completed",
                "created_at": datetime.now(UTC),
            }
        )

    def list_exports(self, project_id: str) -> tuple[dict[str, Any], ...]:
        self._required(project_id)
        return self._repository.list_exports(project_id)

    def cleanup(self) -> int:
        return self._repository.cleanup()

    def _analyze(self, project_id: str) -> dict[str, list[dict[str, Any]]]:
        project = self._required(project_id)
        configuration = self._project_configuration(project)
        source_run_id = project.get("source_run_id")
        return analyze_migration(
            project,
            configuration,
            self._repository.list_resource(project_id, "sources"),
            self._repository.list_resource(project_id, "redirect-map"),
            self._repository.pages(project["destination_run_id"]),
            self._repository.pages(source_run_id) if source_run_id else (),
            self._optional_evidence("links", project["destination_run_id"]),
            self._optional_evidence("links", source_run_id) if source_run_id else (),
            self._optional_evidence("sitemap_urls", project["destination_run_id"]),
            self._optional_evidence("images", project["destination_run_id"]),
            self._optional_evidence("images", source_run_id) if source_run_id else (),
            self._optional_evidence("structured_data", project["destination_run_id"]),
            self._optional_evidence("structured_data", source_run_id) if source_run_id else (),
        )

    def _optional_evidence(self, method: str, run_id: str) -> tuple[dict[str, Any], ...]:
        factory = getattr(self._repository, method, None)
        if factory is None:
            return ()
        return tuple(factory(run_id))

    @staticmethod
    def _project_configuration(project: dict[str, Any]) -> MigrationQaConfiguration:
        try:
            return MigrationQaConfiguration(**json.loads(project["configuration_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("migration_qa_invalid_configuration") from error

    def _analyze_legacy(self, project_id: str) -> dict[str, list[dict[str, Any]]]:
        project = self._required(project_id)
        sources = self._repository.list_resource(project_id, "sources")
        redirect_rows = self._repository.list_resource(project_id, "redirect-map")
        redirect_map = {
            row["normalized_source_url"]: row for row in redirect_rows if row["state"] == "valid"
        }
        destination_pages = self._repository.pages(project["destination_run_id"])
        destination_by_url = {
            url: page
            for page in destination_pages
            for url in (page.get("requested_url"), page.get("final_url"))
            if url
        }
        source_pages = (
            self._repository.pages(project["source_run_id"]) if project.get("source_run_id") else ()
        )
        source_by_url = {
            url: page
            for page in source_pages
            for url in (page.get("requested_url"), page.get("final_url"))
            if url
        }
        resources: dict[str, list[dict[str, Any]]] = {
            name: []
            for name in (
                "mappings",
                "redirects",
                "comparisons",
                "findings",
                "recommendations",
                "sitewide",
            )
        }
        now = datetime.now(UTC)

        def finding(
            code: str, mapping_id: str | None, page_url: str | None, evidence: dict[str, Any]
        ) -> None:
            classified = classify_migration_finding(code, evidence)
            resources["findings"].append(
                {
                    "id": stable_identity(
                        project_id, "finding", str(len(resources["findings"])), code
                    ),
                    "project_id": project_id,
                    "mapping_id": mapping_id,
                    "page_url": page_url,
                    "code": code,
                    "category": classified["category"],
                    "severity": classified["severity"],
                    "confidence": classified["confidence"],
                    "requires_human_review": classified["requires_human_review"],
                    "explanation": code.replace("_", " ").capitalize(),
                    "evidence_json": stable_json(evidence),
                    "created_at": now,
                }
            )

        for source in sources:
            source_url = source.get("normalized_url")
            explicit = redirect_map.get(source_url)
            destination_url = (explicit or {}).get("normalized_destination_url") or source.get(
                "proposed_destination_url"
            )
            basis = (
                "redirect_map"
                if explicit
                else "inventory"
                if destination_url
                else "origin_substitution"
            )
            if not destination_url and source_url and project.get("source_origin"):
                destination_url = project["destination_origin"] + source_url.removeprefix(
                    project["source_origin"]
                )
            mapping_id = stable_identity(project_id, "mapping", source["id"])
            state = "mapped" if destination_url else "unmapped"
            resources["mappings"].append(
                {
                    "id": mapping_id,
                    "project_id": project_id,
                    "source_row_id": source["id"],
                    "source_url": source_url or source["raw_url"],
                    "destination_url": destination_url,
                    "mapping_basis": basis,
                    "confidence": "high"
                    if explicit
                    else "medium"
                    if destination_url
                    else "indeterminate",
                    "state": state,
                    "evidence_json": stable_json(
                        {"raw_source": source["raw_url"], "planned": bool(explicit)}
                    ),
                    "created_at": now,
                }
            )
            if not destination_url:
                finding("mapping_unmapped", mapping_id, source_url, {"source_row_id": source["id"]})
                continue
            page = destination_by_url.get(destination_url)
            source_page = source_by_url.get(source_url)
            redirect_state = "observed" if page else "missing"
            resources["redirects"].append(
                {
                    "id": stable_identity(mapping_id, "redirect"),
                    "project_id": project_id,
                    "mapping_id": mapping_id,
                    "planned_destination_url": destination_url,
                    "observed_final_url": page.get("final_url") if page else None,
                    "observed_status": page.get("http_status") if page else None,
                    "chain_json": stable_json(page.get("redirects", ()) if page else ()),
                    "state": redirect_state,
                    "evidence_json": stable_json(
                        {"planned": bool(explicit), "retained_observation": bool(page)}
                    ),
                    "created_at": now,
                }
            )
            if not page:
                finding(
                    "destination_missing",
                    mapping_id,
                    destination_url,
                    {"destination_url": destination_url},
                )
            elif page.get("http_status") and int(page["http_status"]) >= 400:
                finding(
                    "destination_error",
                    mapping_id,
                    destination_url,
                    {"http_status": page["http_status"]},
                )
            elif page.get("indexability_state") == "non_indexable":
                finding(
                    "destination_noindex",
                    mapping_id,
                    destination_url,
                    {"indexability_state": page["indexability_state"]},
                )
            if explicit and page and page.get("final_url") and page["final_url"] != destination_url:
                finding(
                    "redirect_wrong_destination",
                    mapping_id,
                    source_url,
                    {"planned": destination_url, "observed": page["final_url"]},
                )
            if page and page.get("redirect_loop"):
                finding(
                    "redirect_loop",
                    mapping_id,
                    source_url,
                    {"redirect_count": page.get("redirect_count")},
                )
            if page and int(page.get("redirect_count") or 0) > 1:
                finding(
                    "redirect_chain",
                    mapping_id,
                    source_url,
                    {"redirect_count": page["redirect_count"]},
                )
            metadata_state = "indeterminate"
            if source_page and page:
                metadata_state = "same"
                if source_page.get("title_normalized_hash") != page.get("title_normalized_hash"):
                    metadata_state = "changed"
                    finding(
                        "metadata_title_changed",
                        mapping_id,
                        destination_url,
                        {
                            "source_hash": source_page.get("title_normalized_hash"),
                            "destination_hash": page.get("title_normalized_hash"),
                        },
                    )
                if source_page.get("description_normalized_hash") != page.get(
                    "description_normalized_hash"
                ):
                    metadata_state = "changed"
                    finding(
                        "metadata_description_changed",
                        mapping_id,
                        destination_url,
                        {
                            "source_hash": source_page.get("description_normalized_hash"),
                            "destination_hash": page.get("description_normalized_hash"),
                        },
                    )
                if source_page.get("canonical_url") != page.get("canonical_url"):
                    finding(
                        "canonical_changed",
                        mapping_id,
                        destination_url,
                        {
                            "source": source_page.get("canonical_url"),
                            "destination": page.get("canonical_url"),
                        },
                    )
                if source_page.get("indexability_state") != page.get("indexability_state"):
                    finding(
                        "indexability_changed",
                        mapping_id,
                        destination_url,
                        {
                            "source": source_page.get("indexability_state"),
                            "destination": page.get("indexability_state"),
                        },
                    )
            resources["comparisons"].append(
                {
                    "id": stable_identity(mapping_id, "comparison"),
                    "project_id": project_id,
                    "mapping_id": mapping_id,
                    "source_url": source_url or source["raw_url"],
                    "destination_url": destination_url,
                    "status_state": "present" if page else "missing",
                    "metadata_state": metadata_state,
                    "content_state": "indeterminate",
                    "canonical_state": "compared" if source_page and page else "indeterminate",
                    "indexability_state": "compared" if source_page and page else "indeterminate",
                    "evidence_json": stable_json(
                        {"source_evidence": bool(source_page), "destination_evidence": bool(page)}
                    ),
                    "created_at": now,
                }
            )

        by_action: dict[str, list[dict[str, Any]]] = {}
        for item in resources["findings"]:
            action = _ACTION_BY_CODE.get(item["code"], "resolve_sitewide_regressions")
            by_action.setdefault(action, []).append(item)
        for action, items in sorted(by_action.items()):
            resources["recommendations"].append(
                {
                    "id": stable_identity(project_id, "recommendation", action),
                    "project_id": project_id,
                    "action": action,
                    "priority": "high"
                    if any(item["severity"] == "error" for item in items)
                    else "medium",
                    "confidence": min(
                        (item["confidence"] for item in items), default="indeterminate"
                    ),
                    "requires_human_review": any(item["requires_human_review"] for item in items),
                    "occurrence_count": len(items),
                    "affected_page_count": len(
                        {item["page_url"] for item in items if item["page_url"]}
                    ),
                    "supporting_finding_ids_json": stable_json([item["id"] for item in items]),
                    "explanation": action.replace("_", " ").capitalize(),
                    "created_at": now,
                }
            )
        total = len(sources)
        mapped = sum(item["state"] == "mapped" for item in resources["mappings"])
        resources["sitewide"].append(
            {
                "id": stable_identity(project_id, "sitewide", "mapping_coverage"),
                "project_id": project_id,
                "category": "mapping",
                "metric_name": "mapping_coverage",
                "numerator": mapped,
                "denominator": total,
                "ratio": f"{mapped / total:.6f}" if total else "0.000000",
                "state": "complete" if total else "indeterminate",
                "evidence_json": stable_json({"bounded": True}),
                "created_at": now,
            }
        )
        if total >= self.configuration.minimum_sitewide_pages and mapped < total:
            finding("sitewide_mapping_coverage_low", None, None, {"mapped": mapped, "total": total})
        return resources

    def _render_export(
        self, project_id: str, export_format: MigrationQaExportFormat
    ) -> tuple[str, str, str, int, bool]:
        if export_format is MigrationQaExportFormat.JSON:
            export_resources: dict[str, tuple[dict[str, Any], ...]] = {
                name: self._repository.list_resource(project_id, name)
                for name in (
                    "sources",
                    "redirect-map",
                    "mappings",
                    "redirects",
                    "comparisons",
                    "findings",
                    "recommendations",
                    "sitewide",
                )
            }
            project = self._required(project_id)
            readiness = {
                "project_id": project_id,
                "readiness": project["readiness"],
                "state": project["state"],
                "evidence": self._evidence_inventory(project["destination_run_id"]),
                "reasons": [],
            }
            payload: dict[str, Any] = {
                "schema_name": MIGRATION_QA_EXPORT_SCHEMA,
                "schema_version": MIGRATION_QA_API_VERSION,
                "project": self._required(project_id),
                "policy": json.loads(project["configuration_json"]),
                "evidence_versions": {
                    "migration_qa": MIGRATION_QA_EVIDENCE_VERSION,
                    "page": PAGE_EVIDENCE_VERSION,
                },
                "scope": {
                    "source_origin": project.get("source_origin"),
                    "destination_origin": project["destination_origin"],
                },
                "readiness": readiness,
                "summary": self.summary(project_id),
                "source_rows": export_resources["sources"],
                "redirect_map_rows": export_resources["redirect-map"],
                "mappings": export_resources["mappings"],
                "redirect_observations": export_resources["redirects"],
                "page_comparisons": export_resources["comparisons"],
                "findings": export_resources["findings"],
                "recommendations": export_resources["recommendations"],
                "warnings": tuple(
                    item for item in export_resources["findings"] if item["severity"] != "info"
                ),
                "limitations": tuple(readiness["reasons"]),
                "truncation": {
                    "maximum_export_rows": self.configuration.maximum_export_rows,
                    "maximum_cell_characters": self.configuration.maximum_field_characters,
                    "truncated": False,
                },
            }
            return (
                stable_json(payload),
                "application/json",
                f"migration-qa-{project_id[:12]}.json",
                sum(len(value) for value in export_resources.values()),
                False,
            )
        if export_format is MigrationQaExportFormat.MARKDOWN:
            summary = self.summary(project_id)
            headings = (
                "Overview",
                "Readiness",
                "Source inventory",
                "Redirect map",
                "URL mappings",
                "Redirect observations",
                "Destination status",
                "Metadata continuity",
                "Content continuity",
                "Canonical continuity",
                "Indexability continuity",
                "Internal links",
                "Sitemaps",
                "Images",
                "Structured data",
                "Sitewide findings",
                "Recommendations",
                "Evidence limitations",
            )
            content = "# Website Migration QA\n\n" + "\n\n".join(
                f"## {heading}\n\n{stable_json(summary['counts'])}" for heading in headings
            )
            return (
                content,
                "text/markdown",
                f"migration-qa-{project_id[:12]}.md",
                len(headings),
                False,
            )
        resource = {
            "findings_csv": "findings",
            "redirects_csv": "redirects",
            "mappings_csv": "mappings",
            "comparisons_csv": "comparisons",
            "recommendations_csv": "recommendations",
            "sitewide_csv": "sitewide",
        }[export_format.value]
        rows = list(self._repository.list_resource(project_id, resource))
        truncated = len(rows) > self.configuration.maximum_export_rows
        rows = rows[: self.configuration.maximum_export_rows]
        output = io.StringIO(newline="")
        fields = _CSV_SCHEMAS[resource]
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            projected: dict[str, Any] = {}
            cell_truncated = False
            for key in fields:
                if key == "export_truncated":
                    continue
                value, was_truncated = _csv_value(
                    row.get(key), self.configuration.maximum_field_characters
                )
                projected[key] = value
                cell_truncated = cell_truncated or was_truncated
            projected["export_truncated"] = truncated or cell_truncated
            writer.writerow(projected)
        return (
            output.getvalue(),
            "text/csv",
            f"migration-qa-{resource}-{project_id[:12]}.csv",
            len(rows),
            truncated,
        )

    def _required(self, project_id: str) -> dict[str, Any]:
        value = self._repository.get(project_id)
        if value is None:
            raise ValueError("migration_qa_project_not_found")
        return value

    def _page(
        self,
        kind: str,
        rows: tuple[dict[str, Any], ...],
        cursor: str | None,
        page_size: int | None,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        size = page_size or self.configuration.default_page_size
        if not 1 <= size <= self.configuration.maximum_page_size:
            raise ValueError("migration_qa_invalid_page_size")
        fingerprint = stable_identity(stable_json(filters))[:24]
        offset = decode_cursor(cursor, kind, fingerprint) if cursor else 0
        selected = rows[offset : offset + size]
        next_offset = offset + len(selected)
        return {
            "items": selected,
            "page_size": size,
            "next_cursor": encode_cursor(kind, fingerprint, next_offset)
            if next_offset < len(rows)
            else None,
            "total": len(rows),
        }


def _parse_delimited(content: str, maximum_bytes: int) -> list[dict[str, str]]:
    if len(content.encode()) > maximum_bytes:
        raise ValueError("migration_qa_input_too_large")
    nonblank = [line.strip() for line in content.splitlines() if line.strip()]
    if not nonblank:
        raise ValueError("migration_qa_invalid_input")
    first = nonblank[0]
    known_headers = {
        "source_url",
        "url",
        "source",
        "destination_url",
        "destination",
        "target",
    }
    first_fields = {item.strip().lower() for item in first.replace("\t", ",").split(",")}
    if not (first_fields & known_headers) and "," not in first and "\t" not in first:
        return [{"source_url": line} for line in nonblank]
    sample = content[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(content), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("migration_qa_invalid_input")
    return [
        {str(key).strip().lower(): str(value or "").strip() for key, value in row.items()}
        for row in reader
    ]


def _field(record: dict[str, str], *names: str, required: bool = True) -> str:
    for name in names:
        value = record.get(name, "")
        if value:
            return value
    if required:
        raise ValueError("migration_qa_missing_required_column")
    return ""


def _normalize_input(value: str, origin: str | None = None) -> Any:
    base = normalize_url(origin) if origin else None
    return normalize_url(value, base=base)


def _normalized_or_none(value: str, origin: str | None = None) -> str | None:
    if not value:
        return None
    try:
        return str(_normalize_input(value, origin).normalized)
    except UrlNormalizationError:
        return None


def _json_array(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
        return [str(item) for item in parsed] if isinstance(parsed, list) else []
    except TypeError, ValueError, json.JSONDecodeError:
        return []


def _annotate_planned_graph(rows: list[dict[str, Any]]) -> None:
    graph = {
        str(row["normalized_source_url"]): str(row["normalized_destination_url"])
        for row in rows
        if row["state"] not in {"invalid", "conflict", "duplicate"}
        and row.get("normalized_source_url")
        and row.get("normalized_destination_url")
    }
    for row in rows:
        source = row.get("normalized_source_url")
        if not source or source not in graph:
            continue
        visited: list[str] = []
        current = str(source)
        while current in graph and current not in visited:
            visited.append(current)
            current = graph[current]
        diagnostics = _json_array(row["diagnostics_json"])
        if current in visited:
            diagnostics.append("redirect_map_loop")
        elif len(visited) > 1:
            diagnostics.append("redirect_map_chain")
        row["diagnostics_json"] = stable_json(sorted(set(diagnostics)))


def _csv_value(value: Any, maximum_characters: int) -> tuple[Any, bool]:
    if isinstance(value, (dict, list, tuple)):
        value = stable_json(value)
    if isinstance(value, datetime):
        value = value.isoformat()
    if not isinstance(value, str):
        return value, False
    truncated = len(value) > maximum_characters
    bounded = value[:maximum_characters]
    if bounded.startswith(("=", "+", "-", "@")):
        bounded = "'" + bounded
    return bounded, truncated
