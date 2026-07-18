"""Deterministic retained-evidence structured-data analysis."""

# ruff: noqa: ANN401, C901, E501, PLR0911, PLR0912, PLR0913, PLR0915, PLR2004, SIM102, TC001

from __future__ import annotations

import asyncio
import csv
import io
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from musimack_tools.domain.artifacts import ArtifactType
from musimack_tools.domain.page_evidence import STRUCTURED_DATA_EVIDENCE_VERSION
from musimack_tools.domain.structured_data_audit import (
    PROFILE_REQUIRED_PROPERTIES,
    RECOGNIZED_TYPES,
    STRUCTURED_DATA_PROFILE_VERSION,
    StructuredDataAuditConfiguration,
    StructuredDataExportFormat,
    audit_identity,
    decode_cursor,
    encode_cursor,
    stable_identity,
    stable_json,
)
from musimack_tools.persistence.structured_data_repository import (
    SQLAlchemyStructuredDataAuditRepository,
)

if TYPE_CHECKING:
    from musimack_tools.artifacts.service import ArtifactService


_CONFIRMED_FINDINGS = frozenset(
    {
        "json_ld_invalid_json",
        "json_ld_empty_block",
        "json_ld_scalar_root",
        "json_ld_truncated",
        "microdata_property_outside_scope",
        "microdata_invalid_itemid",
        "rdfa_invalid_prefix_mapping",
        "property_missing_value",
        "property_empty_value",
        "property_url_invalid",
        "page_structured_data_on_non_html_content",
        "page_structured_data_on_error_status",
    }
)
_REVIEW_ONLY_FINDINGS = frozenset(
    {
        "json_ld_unrecognized_context",
        "json_ld_unsupported_script_type",
        "rdfa_unsupported_pattern",
        "entity_conflicting_types",
        "entity_inconsistent_across_pages",
        "page_multiple_primary_entities",
        "sitewide_schema_inconsistency",
    }
)
_CSV_SCHEMAS: dict[StructuredDataExportFormat, tuple[str, ...]] = {
    StructuredDataExportFormat.INVENTORY_CSV: (
        "id",
        "audit_id",
        "page_url",
        "format",
        "parse_status",
        "types_json",
        "identifiers_json",
        "fingerprint",
        "evidence_json",
        "created_at",
    ),
    StructuredDataExportFormat.ENTITY_CSV: (
        "id",
        "audit_id",
        "block_id",
        "page_url",
        "entity_identifier",
        "entity_type",
        "properties_json",
        "created_at",
    ),
    StructuredDataExportFormat.PROPERTY_CSV: (
        "id",
        "audit_id",
        "entity_id",
        "page_url",
        "property_name",
        "value_json",
        "value_state",
        "created_at",
    ),
    StructuredDataExportFormat.DUPLICATE_CSV: (
        "id",
        "audit_id",
        "fingerprint",
        "raw_fingerprint",
        "normalized_fingerprint",
        "comparison_basis",
        "member_count",
        "pages_json",
        "classification",
        "created_at",
    ),
    StructuredDataExportFormat.PAGE_CSV: (
        "id",
        "audit_id",
        "page_url",
        "block_count",
        "entity_count",
        "finding_count",
        "formats_json",
        "created_at",
    ),
    StructuredDataExportFormat.RECOMMENDATIONS_CSV: (
        "id",
        "audit_id",
        "action",
        "priority",
        "confidence",
        "requires_human_review",
        "scope",
        "occurrence_count",
        "affected_page_count",
        "supporting_finding_ids_json",
        "supporting_evidence_json",
        "page_url",
        "finding_code",
        "explanation",
        "created_at",
    ),
}
_JSON_EXPORT_SCHEMA_NAME = "musimack-structured-data-audit"
_JSON_EXPORT_SCHEMA_VERSION = "1.0"
_MAX_CSV_CELL_CHARS = 4_096
_MARKDOWN_SECTIONS = (
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
)


def _finding_policy(code: str) -> tuple[str, bool]:
    if code in _CONFIRMED_FINDINGS:
        return "high", False
    if code in _REVIEW_ONLY_FINDINGS:
        return "medium", True
    return "medium", code.startswith(("entity_", "page_", "sitewide_", "rdfa_"))


class StructuredDataAuditService:
    def __init__(
        self,
        configuration: StructuredDataAuditConfiguration,
        repository: SQLAlchemyStructuredDataAuditRepository,
        artifacts: ArtifactService | None = None,
    ) -> None:
        self.configuration = configuration
        self._repository = repository
        self._artifacts = artifacts
        self._repository.reconcile_interrupted()

    def diagnostics(self) -> dict[str, Any]:
        return {
            "enabled": self.configuration.enabled,
            "persistence_ready": True,
            "migration_ready": True,
            "evidence_version": STRUCTURED_DATA_EVIDENCE_VERSION,
            "profile_version": STRUCTURED_DATA_PROFILE_VERSION,
        }

    def evidence_status(self, run_id: str) -> dict[str, Any]:
        context = self._repository.run_context(run_id)
        if context is None:
            raise ValueError("structured_data_audit_run_not_found")
        job_id, state, terminal, page_count, block_count = context
        versions = self._repository.evidence_versions(run_id)
        pages = self._repository.pages(run_id)
        now = datetime.now(UTC)
        expired = any(_page_evidence_expired(page, now) for page in pages)
        compatible = versions == (STRUCTURED_DATA_EVIDENCE_VERSION,)
        return {
            "run_id": run_id,
            "job_id": job_id,
            "run_state": state,
            "terminal": terminal,
            "page_count": page_count,
            "block_count": block_count,
            "evidence_versions": versions,
            "compatible": compatible,
            "expired": expired,
            "ready": terminal and page_count > 0 and block_count > 0 and compatible and not expired,
        }

    def create_audit(self, run_id: str) -> dict[str, Any]:
        status = self.evidence_status(run_id)
        if not status["terminal"]:
            raise ValueError("structured_data_audit_run_not_terminal")
        if not status["page_count"]:
            raise ValueError("structured_data_audit_page_evidence_unavailable")
        if not status["block_count"]:
            raise ValueError("structured_data_audit_evidence_unavailable")
        if not status["compatible"]:
            raise ValueError("structured_data_audit_evidence_version_unsupported")
        if status["expired"]:
            raise ValueError("structured_data_audit_evidence_expired")
        audit_id = audit_identity(run_id, self.configuration)
        return self._repository.create(audit_id, str(status["job_id"]), run_id, self.configuration)

    async def execute_audit(self, audit_id: str) -> dict[str, Any]:
        audit = self._required(audit_id)
        if audit["state"] in {"completed", "completed_with_warnings", "failed", "cancelled"}:
            raise ValueError("structured_data_audit_already_terminal")
        if not self._repository.claim_execution(audit_id):
            raise ValueError("structured_data_audit_already_executing")
        try:
            evidence = self._repository.evidence(str(audit["run_id"]))
            pages = self._repository.pages(str(audit["run_id"]))
            resources = self._analyze(audit_id, evidence, pages)
            findings = resources["parse-findings"] + resources["consistency-findings"]
            return self._repository.replace_analysis(
                audit_id,
                resources,
                {
                    "pages": len(resources["pages"]),
                    "blocks": len(resources["blocks"]),
                    "entities": len(resources["entities"]),
                    "findings": len(findings),
                },
                warnings=len(findings),
            )
        except asyncio.CancelledError:
            self._repository.terminalize(audit_id, "cancelled", "structured_data_audit_cancelled")
            raise
        except Exception:
            self._repository.terminalize(
                audit_id, "failed", "structured_data_audit_execution_failed"
            )
            raise

    def get(self, audit_id: str) -> dict[str, Any]:
        return self._required(audit_id)

    def summary(self, audit_id: str) -> dict[str, Any]:
        audit = self._required(audit_id)
        return {
            **audit,
            "format_counts": dict(
                Counter(row["format"] for row in self._repository.list_resource(audit_id, "blocks"))
            ),
            "finding_code_counts": dict(
                Counter(
                    row["code"]
                    for name in ("parse-findings", "consistency-findings")
                    for row in self._repository.list_resource(audit_id, name)
                )
            ),
            "non_certifying": True,
            "profile_version": STRUCTURED_DATA_PROFILE_VERSION,
        }

    def list_audits(self, cursor: str | None, page_size: int | None) -> dict[str, Any]:
        return self._page("audits", self._repository.list_audits(), cursor, page_size, {})

    def list_resource(
        self,
        audit_id: str,
        name: str,
        cursor: str | None,
        page_size: int | None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._required(audit_id)
        rows = self._repository.list_resource(audit_id, name)
        filters = filters or {}
        for key, value in filters.items():
            if key == "search":
                needle = str(value).casefold()
                rows = tuple(
                    row
                    for row in rows
                    if any(needle in str(field).casefold() for field in row.values())
                )
                continue
            if key in {
                "page_url",
                "code",
                "severity",
                "confidence",
                "requires_human_review",
                "scope",
                "format",
                "entity_type",
                "property_name",
                "profile_name",
                "observation_state",
                "action",
            }:
                rows = tuple(row for row in rows if str(row.get(key, "")) == str(value))
        return self._page(name, rows, cursor, page_size, filters)

    def create_export(
        self, audit_id: str, export_format: StructuredDataExportFormat
    ) -> dict[str, Any]:
        audit = self._required(audit_id)
        if audit["state"] not in {"completed", "completed_with_warnings"}:
            raise ValueError("structured_data_audit_export_conflict")
        if self._artifacts is None or not self._artifacts.configuration.enabled:
            raise ValueError("structured_data_audit_export_failed")
        content, media_type, filename, row_count, truncated = self._render_export(
            audit_id, export_format
        )
        artifact_type = (
            ArtifactType.CSV_EXPORT
            if export_format.value.endswith("_csv")
            else ArtifactType.RUN_SUMMARY_MARKDOWN
            if export_format is StructuredDataExportFormat.MARKDOWN
            else ArtifactType.RUN_SUMMARY_JSON
        )
        artifact = self._artifacts.store_bytes(
            job_id=str(audit["job_id"]),
            run_id=str(audit["run_id"]),
            artifact_type=artifact_type,
            filename=filename,
            content=content.encode(),
        )
        now = datetime.now(UTC)
        return self._repository.upsert_export(
            {
                "id": stable_identity(audit_id, export_format.value),
                "audit_id": audit_id,
                "export_format": export_format.value,
                "media_type": media_type,
                "filename": filename,
                "artifact_id": artifact.artifact_id,
                "row_count": row_count,
                "truncated": truncated,
                "state": "completed",
                "created_at": now,
            }
        )

    def list_exports(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        self._required(audit_id)
        return self._repository.list_exports(audit_id)

    def cleanup(self) -> int:
        return self._repository.cleanup()

    def _required(self, audit_id: str) -> dict[str, Any]:
        value = self._repository.get(audit_id)
        if value is None:
            raise ValueError("structured_data_audit_not_found")
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
            raise ValueError("structured_data_audit_invalid_page_size")
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
            "ordering": "stable_id_asc-v1",
        }

    def _analyze(
        self, audit_id: str, evidence: tuple[dict[str, Any], ...], pages: tuple[dict[str, Any], ...]
    ) -> dict[str, list[dict[str, Any]]]:
        now = datetime.now(UTC)
        resources: dict[str, list[dict[str, Any]]] = {
            name: []
            for name in (
                "blocks",
                "entities",
                "properties",
                "references",
                "duplicate-groups",
                "pages",
                "parse-findings",
                "consistency-findings",
                "profiles",
                "recommendations",
            )
        }
        page_meta = {str(page.get("requested_url")): page for page in pages}
        page_counts: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"blocks": 0, "entities": 0, "findings": 0, "formats": set()}
        )
        for page in pages:
            page_counts[str(page.get("final_url") or page.get("requested_url"))]
        entity_ids_by_identifier: dict[str, list[tuple[str, str, str, str | None]]] = defaultdict(
            list
        )
        blocks_by_fingerprint: dict[str, list[str]] = defaultdict(list)
        block_fingerprint_meta: dict[str, tuple[str, str | None]] = {}
        all_type_sets: list[set[str]] = []

        def child_id(kind: str, *parts: object) -> str:
            return stable_identity(audit_id, kind, *parts)

        def finding(
            code: str,
            page_url: str | None,
            block_id: str | None,
            entity_id: str | None,
            explanation: str,
            category: str = "parse",
            severity: str = "warning",
        ) -> None:
            confidence, requires_human_review = _finding_policy(code)
            item = {
                "id": child_id(
                    "finding",
                    code,
                    page_url,
                    block_id,
                    entity_id,
                    len(resources["parse-findings"]) + len(resources["consistency-findings"]),
                ),
                "audit_id": audit_id,
                "page_url": page_url,
                "block_id": block_id,
                "entity_id": entity_id,
                "code": code,
                "severity": severity,
                "confidence": confidence,
                "requires_human_review": requires_human_review,
                "category": category,
                "explanation": explanation,
                "evidence_json": stable_json(
                    {
                        "page_urls": [page_url] if page_url else [],
                        "block_ids": [block_id] if block_id else [],
                        "entity_ids": [entity_id] if entity_id else [],
                    }
                ),
                "created_at": now,
            }
            resources["parse-findings" if category == "parse" else "consistency-findings"].append(
                item
            )
            if page_url:
                page_counts[page_url]["findings"] += 1

        for evidence_row in evidence:
            page_url = str(evidence_row["source_final_url"] or evidence_row["source_requested_url"])
            block_id = child_id("block", evidence_row["block_id"])
            types = _json_list(evidence_row["types_json"])
            identifiers = _json_list(evidence_row["identifiers_json"])
            contexts = _json_list(evidence_row["contexts_json"])
            references = _json_list(evidence_row["references_json"])
            diagnostics = _json_list(evidence_row.get("diagnostics_json", "[]"))
            properties = _json_object(evidence_row["properties_json"])
            parsed_root: object | None = None
            if evidence_row["format"] == "json_ld" and evidence_row["parse_status"] == "parsed":
                try:
                    parsed_root = json.loads(
                        str(evidence_row["raw_value"]).lstrip("\ufeff").removeprefix("ï»¿")
                    )
                except json.JSONDecodeError:
                    parsed_root = None
            fingerprint = str(
                evidence_row["normalized_fingerprint"] or evidence_row["raw_fingerprint"]
            )
            blocks_by_fingerprint[fingerprint].append(page_url)
            block_fingerprint_meta.setdefault(
                fingerprint,
                (
                    str(evidence_row["raw_fingerprint"]),
                    str(evidence_row["normalized_fingerprint"])
                    if evidence_row["normalized_fingerprint"]
                    else None,
                ),
            )
            all_type_sets.append(set(types))
            resources["blocks"].append(
                {
                    "id": block_id,
                    "audit_id": audit_id,
                    "page_url": page_url,
                    "format": evidence_row["format"],
                    "parse_status": evidence_row["parse_status"],
                    "types_json": stable_json(types),
                    "identifiers_json": stable_json(identifiers),
                    "fingerprint": fingerprint,
                    "evidence_json": stable_json(
                        {
                            "source_locator": evidence_row["source_locator"],
                            "contexts": contexts,
                            "truncated": evidence_row["value_truncated"],
                            "parse_error": evidence_row["parse_error"],
                        }
                    ),
                    "created_at": now,
                }
            )
            page_counts[page_url]["blocks"] += 1
            page_counts[page_url]["formats"].add(evidence_row["format"])
            if evidence_row["parse_status"] != "parsed":
                finding(
                    "json_ld_invalid_json", page_url, block_id, None, "JSON-LD is not valid JSON."
                )
            if (
                evidence_row["format"] == "json_ld"
                and parsed_root is not None
                and not isinstance(parsed_root, (dict, list))
            ):
                finding(
                    "json_ld_scalar_root",
                    page_url,
                    block_id,
                    None,
                    "JSON-LD has a scalar top-level value instead of an object or array.",
                )
            if not str(evidence_row["raw_value"]).strip():
                finding(
                    "json_ld_empty_block",
                    page_url,
                    block_id,
                    None,
                    "The structured-data block is empty.",
                )
            if evidence_row["value_truncated"]:
                finding(
                    "json_ld_truncated",
                    page_url,
                    block_id,
                    None,
                    "Retained evidence reached its configured bound.",
                )
            if evidence_row["format"] == "json_ld" and not contexts:
                finding(
                    "json_ld_missing_context", page_url, block_id, None, "JSON-LD has no @context."
                )
            if evidence_row["format"] == "json_ld" and any(
                "schema.org" not in context.casefold() for context in contexts
            ):
                finding(
                    "json_ld_unrecognized_context",
                    page_url,
                    block_id,
                    None,
                    "JSON-LD uses a context outside the recognized review vocabulary.",
                    severity="info",
                )
            if evidence_row["format"] == "json_ld" and (
                str(evidence_row.get("script_type") or "").split(";", 1)[0].strip().casefold()
                != "application/ld+json"
            ):
                finding(
                    "json_ld_unsupported_script_type",
                    page_url,
                    block_id,
                    None,
                    "JSON-LD-like evidence uses a non-standard script media type.",
                )
            if (
                evidence_row["format"] == "json_ld"
                and not types
                and evidence_row["parse_status"] == "parsed"
            ):
                finding("json_ld_missing_type", page_url, block_id, None, "JSON-LD has no @type.")
            if evidence_row["format"] == "microdata" and not types:
                finding(
                    "microdata_missing_itemtype",
                    page_url,
                    block_id,
                    None,
                    "Microdata itemscope has no itemtype.",
                )
            if evidence_row["format"] == "microdata" and not properties:
                finding(
                    "microdata_empty_itemscope",
                    page_url,
                    block_id,
                    None,
                    "Microdata itemscope contains no retained properties.",
                )
            if evidence_row["format"] == "microdata" and references:
                if any(item.startswith("microdata_unresolved_itemref:") for item in diagnostics):
                    finding(
                        "microdata_unresolved_itemref",
                        page_url,
                        block_id,
                        None,
                        "A bounded Microdata itemref could not be resolved within retained evidence.",
                    )
            if "microdata_property_outside_scope" in diagnostics:
                finding(
                    "microdata_property_outside_scope",
                    page_url,
                    block_id,
                    None,
                    "Microdata itemprop is not associated with a supported item scope.",
                )
            if "microdata_invalid_itemid" in diagnostics:
                finding(
                    "microdata_invalid_itemid",
                    page_url,
                    block_id,
                    None,
                    "Microdata itemid is unusable under the bounded identifier policy.",
                )
            if evidence_row["format"] == "rdfa" and not contexts:
                finding(
                    "rdfa_missing_vocabulary_context",
                    page_url,
                    block_id,
                    None,
                    "RDFa has no bounded vocabulary context.",
                )
            if evidence_row["format"] == "rdfa" and properties and not identifiers:
                finding(
                    "rdfa_property_without_subject",
                    page_url,
                    block_id,
                    None,
                    "RDFa properties have no explicit retained subject identifier.",
                    severity="info",
                )
            if "rdfa_invalid_prefix_mapping" in diagnostics:
                finding(
                    "rdfa_invalid_prefix_mapping",
                    page_url,
                    block_id,
                    None,
                    "RDFa prefix declaration is malformed under the supported bounded syntax.",
                )
            if "rdfa_unsupported_pattern" in diagnostics:
                finding(
                    "rdfa_unsupported_pattern",
                    page_url,
                    block_id,
                    None,
                    "RDFa evidence requires semantics outside the bounded extractor.",
                    severity="info",
                )
            page = page_meta.get(str(evidence_row["source_requested_url"]), {})
            if page.get("http_status") and int(page["http_status"]) >= 400:
                finding(
                    "page_structured_data_on_error_status",
                    page_url,
                    block_id,
                    None,
                    "Structured data appears on an HTTP error page.",
                    "page",
                )
            content_type = str(page.get("content_type") or "").split(";", 1)[0].casefold()
            if content_type and content_type not in {"text/html", "application/xhtml+xml"}:
                finding(
                    "page_structured_data_on_non_html_content",
                    page_url,
                    block_id,
                    None,
                    "Structured data is associated with retained non-HTML response evidence.",
                    "page",
                )
            if page.get("indexability_state") == "non_indexable":
                finding(
                    "page_structured_data_on_nonindexable_page",
                    page_url,
                    block_id,
                    None,
                    "Structured data appears on a non-indexable page.",
                    "page",
                )

            entity_types: list[str | None] = [*types] if types else [None]
            entity_identifiers: list[str | None] = [*identifiers] if identifiers else [None]
            entity_count = max(len(entity_types), len(entity_identifiers), 1)
            for index in range(entity_count):
                entity_type = entity_types[min(index, len(entity_types) - 1)]
                identifier = entity_identifiers[min(index, len(entity_identifiers) - 1)]
                entity_id = child_id("entity", block_id, index, entity_type, identifier)
                resources["entities"].append(
                    {
                        "id": entity_id,
                        "audit_id": audit_id,
                        "block_id": block_id,
                        "page_url": page_url,
                        "entity_identifier": identifier,
                        "entity_type": entity_type,
                        "properties_json": stable_json(properties),
                        "created_at": now,
                    }
                )
                page_counts[page_url]["entities"] += 1
                if identifier:
                    entity_ids_by_identifier[identifier].append(
                        (entity_id, page_url, stable_json(properties), entity_type)
                    )
                else:
                    finding(
                        "entity_missing_identifier",
                        page_url,
                        block_id,
                        entity_id,
                        "Entity has no stable identifier.",
                        "entity",
                        "info",
                    )
                if entity_type and _malformed_entity_type(entity_type):
                    finding(
                        "json_ld_invalid_type",
                        page_url,
                        block_id,
                        entity_id,
                        "Entity type is outside the recognized review vocabulary.",
                        "entity",
                    )
                for property_name, raw_values in sorted(properties.items()):
                    values = raw_values if isinstance(raw_values, list) else [raw_values]
                    property_id = child_id("property", entity_id, property_name)
                    state = (
                        "empty"
                        if not values or all(not str(value).strip() for value in values)
                        else "present"
                    )
                    resources["properties"].append(
                        {
                            "id": property_id,
                            "audit_id": audit_id,
                            "entity_id": entity_id,
                            "page_url": page_url,
                            "property_name": property_name,
                            "value_json": stable_json(values),
                            "value_state": state,
                            "created_at": now,
                        }
                    )
                    if state == "empty":
                        finding(
                            "property_empty_value",
                            page_url,
                            block_id,
                            entity_id,
                            f"Property {property_name} has an empty value.",
                            "property",
                        )
                    if f"property_missing_value:{property_name}" in diagnostics:
                        finding(
                            "property_missing_value",
                            page_url,
                            block_id,
                            entity_id,
                            f"Property {property_name} is asserted without a usable value.",
                            "property",
                        )
                    if len({stable_json(value) for value in values}) < len(values):
                        finding(
                            "property_duplicate_value",
                            page_url,
                            block_id,
                            entity_id,
                            f"Property {property_name} repeats a value.",
                            "property",
                            "info",
                        )
                    if property_name.casefold() in {"url", "sameas", "image", "logo"}:
                        for value in values:
                            if (
                                isinstance(value, str)
                                and value
                                and urlsplit(value).scheme not in {"http", "https"}
                            ):
                                finding(
                                    "property_url_invalid",
                                    page_url,
                                    block_id,
                                    entity_id,
                                    f"Property {property_name} is not an absolute HTTP(S) URL.",
                                    "property",
                                )
                for reference in references:
                    resources["references"].append(
                        {
                            "id": child_id("reference", entity_id, reference),
                            "audit_id": audit_id,
                            "page_url": page_url,
                            "source_entity_id": entity_id,
                            "target_identifier": reference,
                            "resolved": reference in identifiers,
                            "created_at": now,
                        }
                    )
                    if reference not in identifiers:
                        finding(
                            "property_reference_unresolved",
                            page_url,
                            block_id,
                            entity_id,
                            "An entity reference is unresolved in retained evidence.",
                            "property",
                        )
                self._profiles(
                    resources["profiles"], audit_id, entity_id, entity_type, properties, now
                )

        for fingerprint, member_pages in sorted(blocks_by_fingerprint.items()):
            if len(member_pages) > 1:
                raw_fingerprint, normalized_fingerprint = block_fingerprint_meta[fingerprint]
                resources["duplicate-groups"].append(
                    {
                        "id": child_id("duplicate", fingerprint),
                        "audit_id": audit_id,
                        "fingerprint": fingerprint,
                        "raw_fingerprint": raw_fingerprint,
                        "normalized_fingerprint": normalized_fingerprint,
                        "comparison_basis": "normalized"
                        if normalized_fingerprint
                        else "raw_fallback",
                        "member_count": len(member_pages),
                        "pages_json": stable_json(member_pages),
                        "classification": "cross_page_duplicate"
                        if len(set(member_pages)) > 1
                        else "on_page_duplicate",
                        "created_at": now,
                    }
                )
                code = (
                    "json_ld_duplicate_block"
                    if any(
                        row["format"] == "json_ld" and row["fingerprint"] == fingerprint
                        for row in resources["blocks"]
                    )
                    else "entity_duplicate_on_page"
                )
                finding(
                    code,
                    member_pages[0],
                    None,
                    None,
                    "Equivalent structured-data evidence is repeated.",
                    "duplicate",
                )
        for identifier, members in entity_ids_by_identifier.items():
            by_page = Counter(page for _, page, _, _ in members)
            if any(count > 1 for count in by_page.values()):
                finding(
                    "json_ld_duplicate_entity_id",
                    members[0][1],
                    None,
                    members[0][0],
                    f"Identifier {identifier} repeats on a page.",
                    "entity",
                )
            if (
                len({properties for _, _, properties, _ in members}) > 1
                and len({page for _, page, _, _ in members}) > 1
            ):
                finding(
                    "entity_inconsistent_across_pages",
                    None,
                    None,
                    members[0][0],
                    f"Identifier {identifier} has inconsistent properties across pages.",
                    "consistency",
                )
            type_sets = {entity_type for _, _, _, entity_type in members if entity_type}
            if len(type_sets) > 1 and not _compatible_entity_types(type_sets):
                finding(
                    "entity_conflicting_types",
                    None,
                    None,
                    members[0][0],
                    f"Identifier {identifier} has conflicting retained types: {', '.join(sorted(type_sets))}.",
                    "consistency",
                )
        if (
            len({frozenset(values) for values in all_type_sets}) > 1
            and len(page_counts) >= self.configuration.minimum_sitewide_pages
        ):
            finding(
                "sitewide_schema_inconsistency",
                None,
                None,
                None,
                "Structured-data type sets differ across the crawled site.",
                "consistency",
            )
        for page_url, counts in sorted(page_counts.items()):
            if counts["entities"] > 1:
                finding(
                    "page_multiple_primary_entities",
                    page_url,
                    None,
                    None,
                    "The page exposes multiple candidate primary entities.",
                    "page",
                    "info",
                )
            resources["pages"].append(
                {
                    "id": child_id("page", page_url),
                    "audit_id": audit_id,
                    "page_url": page_url,
                    "block_count": counts["blocks"],
                    "entity_count": counts["entities"],
                    "finding_count": counts["findings"],
                    "formats_json": stable_json(sorted(counts["formats"])),
                    "created_at": now,
                }
            )
        self._recommend(resources, audit_id, now)
        return resources

    def _profiles(
        self,
        target: list[dict[str, Any]],
        audit_id: str,
        entity_id: str,
        entity_type: str | None,
        properties: dict[str, Any],
        now: datetime,
    ) -> None:
        if entity_type is None:
            return
        profile = (
            "LocalBusiness"
            if entity_type
            in {
                "ProfessionalService",
                "MedicalBusiness",
                "Physician",
                "Dentist",
            }
            else entity_type
        )
        required = PROFILE_REQUIRED_PROPERTIES.get(profile)
        if not required:
            return
        for name in required:
            values = properties.get(name)
            state = _profile_state(name, values)
            target.append(
                {
                    "id": stable_identity(audit_id, "profile", entity_id, profile, name),
                    "audit_id": audit_id,
                    "entity_id": entity_id,
                    "profile_name": profile,
                    "profile_version": STRUCTURED_DATA_PROFILE_VERSION,
                    "property_name": name,
                    "observation_state": state,
                    "explanation": (
                        f"{name} is {state} under the bounded {STRUCTURED_DATA_PROFILE_VERSION} "
                        "definition. Review observation only; this profile does not certify "
                        "search-engine eligibility."
                    ),
                    "created_at": now,
                }
            )

    def _recommend(
        self, resources: dict[str, list[dict[str, Any]]], audit_id: str, now: datetime
    ) -> None:
        mapping: dict[str, tuple[str, ...]] = {
            "json_ld_invalid_json": ("fix_invalid_json_ld",),
            "json_ld_scalar_root": ("fix_invalid_json_ld",),
            "json_ld_empty_block": ("remove_empty_structured_data_block",),
            "json_ld_missing_context": ("add_missing_context",),
            "json_ld_unrecognized_context": ("review_external_context",),
            "json_ld_unsupported_script_type": ("review_external_context",),
            "json_ld_missing_type": ("add_missing_type",),
            "json_ld_invalid_type": ("review_unknown_type",),
            "json_ld_duplicate_entity_id": ("resolve_duplicate_entity_id",),
            "json_ld_duplicate_block": ("consolidate_duplicate_entity",),
            "entity_conflicting_types": ("resolve_conflicting_entity_types",),
            "entity_inconsistent_across_pages": ("resolve_inconsistent_entity_values",),
            "property_empty_value": ("fix_empty_property",),
            "property_url_invalid": ("fix_invalid_property_url",),
            "property_reference_unresolved": ("resolve_unresolved_reference",),
            "page_multiple_primary_entities": ("review_multiple_primary_entities",),
            "page_structured_data_on_nonindexable_page": ("review_nonindexable_page_schema",),
            "page_structured_data_on_error_status": ("review_error_page_schema",),
            "sitewide_schema_inconsistency": ("review_sitewide_schema_inconsistency",),
            "json_ld_truncated": ("review_truncated_evidence",),
            "microdata_empty_itemscope": ("remove_empty_structured_data_block",),
        }

        def add(
            action: str,
            explanation: str,
            *,
            page_url: str | None = None,
            findings: tuple[dict[str, Any], ...] = (),
            evidence: dict[str, list[str]] | None = None,
            scope: str = "page",
            confidence: str = "medium",
            priority: str = "medium",
        ) -> None:
            bounded_evidence = {
                key: sorted(dict.fromkeys(values))[:100]
                for key, values in sorted((evidence or {}).items())
            }
            finding_ids = sorted(str(item["id"]) for item in findings)
            pages = sorted(
                {
                    str(value)
                    for value in ([page_url] + [item.get("page_url") for item in findings])
                    if value
                }
            )
            recommendation_id = stable_identity(
                audit_id, "recommendation", action, page_url, finding_ids, bounded_evidence
            )
            if any(item["id"] == recommendation_id for item in resources["recommendations"]):
                return
            resources["recommendations"].append(
                {
                    "id": recommendation_id,
                    "audit_id": audit_id,
                    "action": action,
                    "priority": priority,
                    "confidence": confidence,
                    "requires_human_review": True,
                    "scope": scope,
                    "occurrence_count": max(
                        1,
                        len(findings),
                        max((len(values) for values in bounded_evidence.values()), default=0),
                    ),
                    "affected_page_count": len(pages),
                    "supporting_finding_ids_json": stable_json(finding_ids),
                    "supporting_evidence_json": stable_json(bounded_evidence),
                    "page_url": page_url,
                    "finding_code": str(findings[0]["code"]) if findings else None,
                    "explanation": explanation,
                    "created_at": now,
                }
            )

        findings = resources["parse-findings"] + resources["consistency-findings"]
        for finding_item in findings:
            for action in mapping.get(str(finding_item["code"]), ()):
                add(
                    action,
                    str(finding_item["explanation"]),
                    page_url=finding_item["page_url"],
                    findings=(finding_item,),
                    evidence={
                        "block_ids": [str(finding_item["block_id"])]
                        if finding_item["block_id"]
                        else [],
                        "entity_ids": [str(finding_item["entity_id"])]
                        if finding_item["entity_id"]
                        else [],
                    },
                    scope="site" if finding_item["page_url"] is None else "page",
                    confidence=str(finding_item["confidence"]),
                    priority="high" if finding_item["severity"] == "error" else "medium",
                )
        for profile in resources["profiles"]:
            if profile["observation_state"] in {"missing", "empty", "invalid", "conflicting"}:
                add(
                    "add_missing_required_profile_property",
                    f"Review {profile['profile_name']}.{profile['property_name']} ({profile['observation_state']}).",
                    evidence={"profile_ids": [str(profile["id"])]},
                    scope="entity",
                    confidence="high"
                    if profile["observation_state"] in {"missing", "empty"}
                    else "medium",
                )
            profile_name = str(profile["profile_name"])
            property_name = str(profile["property_name"])
            state = str(profile["observation_state"])
            if (
                profile_name in {"Article", "BlogPosting"}
                and property_name == "publisher"
                and state != "present"
            ):
                add(
                    "review_article_publisher",
                    "Review missing, unusable, or conflicting retained article publisher evidence.",
                    evidence={
                        "profile_ids": [str(profile["id"])],
                        "entity_ids": [str(profile["entity_id"])],
                    },
                    scope="entity",
                )
            if (
                profile_name in {"Product", "Offer"}
                and property_name in {"offers", "price", "priceCurrency"}
                and state != "present"
            ):
                add(
                    "review_product_offer_relationship",
                    "Review the retained Product and Offer relationship without inventing price facts.",
                    evidence={
                        "profile_ids": [str(profile["id"])],
                        "entity_ids": [str(profile["entity_id"])],
                    },
                    scope="entity",
                )
            if profile_name == "BreadcrumbList" and state != "present":
                add(
                    "review_breadcrumb_structure",
                    "Review retained BreadcrumbList structure; this is not an eligibility claim.",
                    evidence={
                        "profile_ids": [str(profile["id"])],
                        "entity_ids": [str(profile["entity_id"])],
                    },
                    scope="entity",
                )

        for page in resources["pages"]:
            formats = _json_list(str(page["formats_json"]))
            if len(formats) > 1:
                add(
                    "review_schema_format_mix",
                    "Multiple structured-data formats coexist on this page; review only if they describe overlapping entities.",
                    page_url=str(page["page_url"]),
                    evidence={"page_ids": [str(page["id"])]},
                    scope="page",
                    confidence="low",
                    priority="low",
                )
        for entity in resources["entities"]:
            entity_type = str(entity.get("entity_type") or "")
            if entity_type == "LocalBusiness":
                add(
                    "review_local_business_subtype",
                    "Review whether the retained generic LocalBusiness type needs a more specific subtype; no replacement is selected.",
                    page_url=str(entity["page_url"]),
                    evidence={"entity_ids": [str(entity["id"])]},
                    scope="entity",
                    confidence="low",
                    priority="low",
                )
            if (
                entity_type
                and entity_type not in RECOGNIZED_TYPES
                and not _malformed_entity_type(entity_type)
            ):
                add(
                    "review_unknown_type",
                    "Review the unfamiliar retained type without treating it as invalid Schema.org.",
                    page_url=str(entity["page_url"]),
                    evidence={"entity_ids": [str(entity["id"])]},
                    scope="entity",
                    confidence="low",
                    priority="low",
                )
            if entity_type == "Organization" and not entity.get("entity_identifier"):
                add(
                    "review_organization_identity",
                    "Review retained Organization identity evidence; no authoritative business fact is selected.",
                    page_url=str(entity["page_url"]),
                    evidence={"entity_ids": [str(entity["id"])]},
                    scope="entity",
                    confidence="medium",
                )
            if entity_type == "Organization":
                identity_findings = tuple(
                    item
                    for item in findings
                    if item["code"] == "entity_inconsistent_across_pages"
                    and item["entity_id"] == entity["id"]
                )
                if identity_findings:
                    add(
                        "review_organization_identity",
                        "Review conflicting retained Organization identity evidence; no authoritative value is selected.",
                        findings=identity_findings,
                        evidence={"entity_ids": [str(entity["id"])]},
                        scope="site",
                        confidence="medium",
                    )

        resources["recommendations"].sort(key=lambda item: str(item["id"]))

    def _render_export(
        self, audit_id: str, export_format: StructuredDataExportFormat
    ) -> tuple[str, str, str, int, bool]:
        mapping = {
            StructuredDataExportFormat.INVENTORY_CSV: "blocks",
            StructuredDataExportFormat.ENTITY_CSV: "entities",
            StructuredDataExportFormat.PROPERTY_CSV: "properties",
            StructuredDataExportFormat.DUPLICATE_CSV: "duplicate-groups",
            StructuredDataExportFormat.PAGE_CSV: "pages",
            StructuredDataExportFormat.RECOMMENDATIONS_CSV: "recommendations",
        }
        if export_format in mapping:
            all_rows = list(self._repository.list_resource(audit_id, mapping[export_format]))
            export_rows = all_rows[: self.configuration.maximum_export_rows]
            content = _csv(export_rows, _CSV_SCHEMAS[export_format])
            return (
                content,
                "text/csv; charset=utf-8",
                f"{audit_id}-{export_format.value}.csv",
                len(export_rows),
                len(export_rows) < len(all_rows),
            )
        resource_names = (
            "blocks",
            "entities",
            "properties",
            "references",
            "duplicate-groups",
            "pages",
            "parse-findings",
            "consistency-findings",
            "profiles",
            "recommendations",
        )
        all_resources = {
            name: self._repository.list_resource(audit_id, name) for name in resource_names
        }
        payload = {
            name: rows[: self.configuration.maximum_export_rows]
            for name, rows in all_resources.items()
        }
        truncated_collections = [
            name
            for name, rows in all_resources.items()
            if len(rows) > self.configuration.maximum_export_rows
        ]
        omitted_counts = {
            name: len(rows) - self.configuration.maximum_export_rows
            for name, rows in all_resources.items()
            if len(rows) > self.configuration.maximum_export_rows
        }
        row_count = sum(len(rows) for rows in payload.values())
        truncated = bool(truncated_collections)
        if export_format is StructuredDataExportFormat.JSON:
            audit = self._required(audit_id)
            summary = self.summary(audit_id)
            document = {
                "schema_name": _JSON_EXPORT_SCHEMA_NAME,
                "schema_version": _JSON_EXPORT_SCHEMA_VERSION,
                "audit": {
                    key: audit.get(key)
                    for key in (
                        "audit_id",
                        "run_id",
                        "state",
                        "created_at",
                        "updated_at",
                        "completed_at",
                        "configuration_json",
                    )
                },
                "evidence_version": STRUCTURED_DATA_EVIDENCE_VERSION,
                "scope": {"source_run_id": audit["run_id"], "network_access": False},
                "summary": summary,
                "blocks": payload["blocks"],
                "entities": payload["entities"],
                "properties": payload["properties"],
                "references": payload["references"],
                "duplicate_groups": payload["duplicate-groups"],
                "page_summaries": payload["pages"],
                "findings": payload["parse-findings"] + payload["consistency-findings"],
                "profiles": payload["profiles"],
                "recommendations": payload["recommendations"],
                "warnings": [
                    {"code": "audit_completed_with_warnings", "count": audit["warning_count"]}
                ]
                if audit["warning_count"]
                else [],
                "truncation": {
                    "truncated": truncated,
                    "collections": truncated_collections,
                    "collection_cap": self.configuration.maximum_export_rows,
                    "omitted_counts": omitted_counts,
                    "field_cap": _MAX_CSV_CELL_CHARS,
                },
            }
            return (
                json.dumps(document, default=str, indent=2, sort_keys=True),
                "application/json",
                f"{audit_id}.json",
                row_count,
                truncated,
            )
        lines = [
            "# Structured-data audit",
            "",
            "Review evidence only; this report does not certify rich-result eligibility.",
            "",
        ]
        counts_by_section = {
            "Executive Summary": len(payload["pages"]),
            "Scope": len(payload["blocks"]),
            "Evidence Readiness": len(payload["blocks"]),
            "Format Distribution": len(payload["blocks"]),
            "Type Distribution": len(payload["entities"]),
            "Parse and Syntax Findings": len(payload["parse-findings"]),
            "Entity Consistency Findings": len(payload["consistency-findings"]),
            "Page-Level Findings": len(payload["pages"]),
            "Sitewide Findings": sum(
                item.get("page_url") is None for item in payload["consistency-findings"]
            ),
            "Duplicate Groups": len(payload["duplicate-groups"]),
            "Profile Observations": len(payload["profiles"]),
            "Recommendations": len(payload["recommendations"]),
            "Limitations": int(truncated),
            "Human-Review Notes": sum(
                bool(item.get("requires_human_review")) for item in payload["recommendations"]
            ),
        }
        for name in _MARKDOWN_SECTIONS:
            lines.extend(
                (
                    f"## {name}",
                    "",
                    f"Records: {counts_by_section[name]}",
                    "",
                )
            )
        return (
            "\n".join(lines),
            "text/markdown; charset=utf-8",
            f"{audit_id}.md",
            row_count,
            truncated,
        )


def _json_list(value: str) -> list[str]:
    parsed = json.loads(value)
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _page_evidence_expired(page: dict[str, Any], now: datetime) -> bool:
    if page.get("retention_state") == "expired":
        return True
    expires_at = page.get("expires_at")
    if not isinstance(expires_at, datetime):
        return False
    comparable = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)
    return comparable < now


def _json_object(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    return parsed if isinstance(parsed, dict) else {}


def _compatible_entity_types(types: set[str]) -> bool:
    local_business_family = {
        "LocalBusiness",
        "ProfessionalService",
        "MedicalBusiness",
        "Physician",
        "Dentist",
        "Hotel",
        "LodgingBusiness",
        "Restaurant",
    }
    article_family = {"Article", "BlogPosting", "NewsArticle"}
    webpage_family = {"WebPage", "AboutPage", "ContactPage", "CollectionPage"}
    return any(
        types <= family for family in (local_business_family, article_family, webpage_family)
    )


def _malformed_entity_type(value: str) -> bool:
    if not value or value != value.strip() or any(character.isspace() for character in value):
        return True
    if value.startswith("@"):
        return True
    if "://" in value:
        parsed = urlsplit(value)
        return parsed.scheme not in {"http", "https"} or not parsed.netloc
    return False


def _profile_state(property_name: str, raw_values: Any, *, applicable: bool = True) -> str:
    if not applicable:
        return "not_applicable"
    if raw_values is None:
        return "missing"
    values = raw_values if isinstance(raw_values, list) else [raw_values]
    if not values or all(not str(value).strip() for value in values):
        return "empty"
    normalized = [str(value).strip() for value in values if str(value).strip()]
    if any(value == "[structured]" for value in normalized):
        return "indeterminate"
    singleton_properties = {
        "name",
        "url",
        "logo",
        "telephone",
        "address",
        "headline",
        "publisher",
        "datePublished",
        "startDate",
        "price",
        "priceCurrency",
    }
    if property_name in singleton_properties and len(set(normalized)) > 1:
        return "conflicting"
    if property_name in {"url", "logo"}:
        if any(
            urlsplit(value).scheme not in {"http", "https"} or not urlsplit(value).netloc
            for value in normalized
        ):
            return "invalid"
    if property_name == "price":
        try:
            for value in normalized:
                float(value)
        except ValueError:
            return "invalid"
    if property_name == "priceCurrency" and any(
        len(value) != 3 or not value.isalpha() for value in normalized
    ):
        return "invalid"
    if property_name in {"datePublished", "startDate"} and any(
        len(value) < 10 or value[4:5] != "-" or value[7:8] != "-" for value in normalized
    ):
        return "invalid"
    return "present"


def _csv(rows: list[dict[str, Any]], fieldnames: tuple[str, ...]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows({field: _csv_cell(row.get(field)) for field in fieldnames} for row in rows)
    return output.getvalue()


def _csv_cell(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    if len(text) > _MAX_CSV_CELL_CHARS:
        text = f"{text[: _MAX_CSV_CELL_CHARS - 12]}...[truncated]"
    if text.startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text
