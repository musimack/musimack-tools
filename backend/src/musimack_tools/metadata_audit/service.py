"""Explicit bounded metadata-audit execution, queries, and exports."""

# ruff: noqa: ANN401, C901, FBT001, PLR2004, TRY300, TRY400

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from musimack_tools.domain.artifacts import ArtifactType
from musimack_tools.domain.metadata_audit import (
    METADATA_AUDIT_EXPORT_VERSION,
    METADATA_AUDIT_VERSION,
    DuplicateGroup,
    DuplicateType,
    ExportFormat,
    MetadataAudit,
    MetadataAuditConfiguration,
    audit_identity,
    duplicate_group_identity,
    duplicate_normalize,
    evaluate_page,
)

if TYPE_CHECKING:
    from musimack_tools.artifacts.service import ArtifactService
    from musimack_tools.persistence.metadata_audit_repository import (
        SQLAlchemyMetadataAuditRepository,
    )

_LOGGER = logging.getLogger("musimack_tools.metadata_audit")


class MetadataAuditService:
    def __init__(
        self,
        configuration: MetadataAuditConfiguration,
        repository: SQLAlchemyMetadataAuditRepository,
        artifacts: ArtifactService | None = None,
    ) -> None:
        self.configuration = configuration
        self._repository = repository
        self._artifacts = artifacts

    def create_and_run_audit(self, run_id: str) -> MetadataAudit:
        if not self.configuration.enabled:
            raise ValueError("metadata_audit_disabled")
        context = self._repository.run_context(run_id)
        if context is None:
            raise ValueError("metadata_audit_run_not_found")
        job_id, seed, terminal, page_count = context
        if not terminal:
            raise ValueError("metadata_audit_run_not_terminal")
        if page_count == 0:
            raise ValueError("metadata_audit_page_evidence_unavailable")
        if page_count > self.configuration.maximum_pages:
            raise ValueError("metadata_audit_page_evidence_unavailable")
        audit_id = audit_identity(run_id, self.configuration)
        existing = self._repository.get(audit_id)
        if existing is not None and existing.state.value not in {"planned", "running"}:
            return existing
        self._repository.create(audit_id, job_id, run_id, seed, self.configuration)
        self._repository.mark_running(audit_id)
        canonical_targets = self._repository.canonical_targets(run_id)
        _LOGGER.info(
            "metadata_audit_started audit_id=%s run_id=%s job_id=%s", audit_id, run_id, job_id
        )
        try:
            offset = 0
            partial = False
            while offset < page_count:
                pages = self._repository.evidence_batch(
                    run_id, offset, self.configuration.batch_size
                )
                if not pages:
                    break
                for page in pages:
                    issues = evaluate_page(audit_id, page, self.configuration, canonical_targets)
                    self._repository.persist_page(audit_id, page, issues)
                    partial = (
                        partial
                        or page.value_truncated
                        or page.evidence_state.value
                        in {"partial", "cancelled", "truncated", "unavailable"}
                    )
                offset += len(pages)
                _LOGGER.info(
                    "metadata_audit_page_batch audit_id=%s page_count=%d", audit_id, len(pages)
                )
            self._group_duplicates(audit_id)
            summary = self._summary(audit_id)
            completed = self._repository.finish(audit_id, summary, partial)
            _LOGGER.info(
                "metadata_audit_completed audit_id=%s pages=%d issues=%d",
                audit_id,
                completed.page_count,
                completed.issue_count,
            )
            return completed
        except Exception:  # noqa: BLE001 - failure is persisted and safely mapped by API.
            self._repository.fail(audit_id, "metadata_audit_persistence_failed")
            _LOGGER.error(
                "metadata_audit_failed audit_id=%s reason_code=metadata_audit_persistence_failed",
                audit_id,
            )
            raise ValueError("metadata_audit_persistence_failed") from None

    def get_audit(self, audit_id: str) -> MetadataAudit:
        value = self._repository.get(audit_id)
        if value is None:
            raise ValueError("metadata_audit_not_found")
        return value

    def list_audits(
        self, *, offset: int = 0, page_size: int | None = None
    ) -> tuple[MetadataAudit, ...]:
        size = self._size(page_size)
        return self._repository.list_audits(offset, size)

    def get_summary(self, audit_id: str) -> dict[str, Any]:
        self.get_audit(audit_id)
        value = self._repository.summary(audit_id)
        if value is None:
            raise ValueError("metadata_audit_partial")
        return value

    def list_pages(
        self,
        audit_id: str,
        *,
        offset: int = 0,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> tuple[Any, ...]:
        self.get_audit(audit_id)
        return self._repository.list_pages(audit_id, offset, self._size(page_size), filters or {})

    def get_page(self, audit_id: str, page_id: str) -> dict[str, Any]:
        page = self._repository.get_page(audit_id, page_id)
        if page is None:
            raise ValueError("metadata_audit_page_not_found")
        issues = self._repository.list_issues(
            audit_id, 0, self.configuration.maximum_issues_per_page, {"page_id": page_id}
        )
        return {"page": asdict(page), "issues": issues, "versions": self.versions()}

    def list_issues(
        self,
        audit_id: str,
        *,
        offset: int = 0,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        self.get_audit(audit_id)
        return self._repository.list_issues(audit_id, offset, self._size(page_size), filters or {})

    def list_duplicate_groups(
        self,
        audit_id: str,
        *,
        offset: int = 0,
        page_size: int | None = None,
        duplicate_type: str | None = None,
    ) -> tuple[DuplicateGroup, ...]:
        self.get_audit(audit_id)
        if duplicate_type is not None:
            DuplicateType(duplicate_type)
        return self._repository.duplicate_groups(
            audit_id, offset, self._size(page_size), duplicate_type
        )

    def get_duplicate_group(
        self, audit_id: str, group_id: str, *, offset: int = 0, page_size: int | None = None
    ) -> dict[str, Any]:
        groups = [
            group
            for group in self._repository.duplicate_groups(
                audit_id, 0, self.configuration.maximum_page_size
            )
            if group.group_id == group_id
        ]
        if not groups:
            raise ValueError("metadata_audit_duplicate_group_not_found")
        members = self._repository.duplicate_members(
            audit_id, group_id, offset, self._size(page_size)
        )
        return {"group": asdict(groups[0]), "members": [asdict(item) for item in members]}

    def create_export(self, audit_id: str, export_format: ExportFormat) -> dict[str, Any]:
        audit = self.get_audit(audit_id)
        if self._artifacts is None or not self._artifacts.configuration.enabled:
            raise ValueError("metadata_audit_export_failed")
        enabled = {
            ExportFormat.CSV: self.configuration.csv_enabled,
            ExportFormat.JSON: self.configuration.json_enabled,
            ExportFormat.MARKDOWN: self.configuration.markdown_enabled,
        }[export_format]
        if not enabled:
            raise ValueError("metadata_audit_export_unsupported")
        existing = self._repository.export_record(audit_id, export_format.value)
        if existing is not None and existing.artifact_id:
            return {
                "export_id": existing.export_id,
                "artifact_id": existing.artifact_id,
                "format": existing.export_format,
                "row_count": existing.row_count,
                "truncated": existing.truncated,
                "state": existing.state,
            }
        issues = self._repository.list_issues(
            audit_id, 0, self.configuration.maximum_export_rows + 1, {}
        )
        truncated = len(issues) > self.configuration.maximum_export_rows
        issues = issues[: self.configuration.maximum_export_rows]
        content = self._export_bytes(audit, export_format, issues, truncated)
        kind = {
            ExportFormat.CSV: ArtifactType.CSV_EXPORT,
            ExportFormat.JSON: ArtifactType.RUN_SUMMARY_JSON,
            ExportFormat.MARKDOWN: ArtifactType.RUN_SUMMARY_MARKDOWN,
        }[export_format]
        extension = export_format.value if export_format is not ExportFormat.MARKDOWN else "md"
        filename = f"metadata-audit-{audit_id}.{extension}"
        artifact = self._artifacts.store_bytes(
            job_id=audit.job_id,
            run_id=audit.run_id,
            artifact_type=kind,
            filename=filename,
            content=content,
        )
        _LOGGER.info(
            "metadata_audit_export_created audit_id=%s format=%s rows=%d",
            audit_id,
            export_format.value,
            len(issues),
        )
        return self._repository.register_export(
            audit_id, export_format.value, artifact.artifact_id, len(issues), truncated
        )

    def get_diagnostics(self) -> dict[str, Any]:
        values = self._repository.diagnostics()
        values.update(self.versions())
        values["enabled"] = self.configuration.enabled
        values["export_ready"] = (
            self._artifacts is not None and self._artifacts.configuration.enabled
        )
        return values

    def versions(self) -> dict[str, str]:
        return {
            "audit": self.configuration.audit_version,
            "taxonomy": self.configuration.taxonomy_version,
            "severity": self.configuration.severity_version,
            "persistence": self.configuration.persistence_version,
            "api": self.configuration.api_version,
            "export": self.configuration.export_version,
            "duplicate": self.configuration.duplicate_version,
            "pagination": self.configuration.pagination_version,
        }

    def _size(self, value: int | None) -> int:
        size = value or self.configuration.default_page_size
        if not 1 <= size <= self.configuration.maximum_page_size:
            raise ValueError("metadata_audit_invalid_page_size")
        return size

    def _group_duplicates(self, audit_id: str) -> None:
        for kind, issue_code in (
            (DuplicateType.TITLE, "title_duplicate"),
            (DuplicateType.META_DESCRIPTION, "meta_description_duplicate"),
        ):
            buckets: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
            for page_id, identity, value in self._repository.duplicate_candidates(audit_id, kind):
                normalized = duplicate_normalize(value)
                if normalized:
                    buckets[normalized].append((page_id, identity, value))
            for normalized, members in buckets.items():
                if len(members) < 2:
                    continue
                group_id = duplicate_group_identity(audit_id, kind, normalized)
                group = DuplicateGroup(
                    group_id,
                    audit_id,
                    kind,
                    hashlib.sha256(normalized.encode()).hexdigest(),
                    members[0][2],
                    len(members),
                    tuple(item[0] for item in members[: self.configuration.duplicate_sample_size]),
                    datetime.now(UTC),
                )
                self._repository.persist_duplicate_group(
                    group, tuple((item[0], item[1]) for item in members), issue_code
                )

    def _summary(self, audit_id: str) -> dict[str, Any]:
        pages = self._repository.list_pages(audit_id, 0, self.configuration.maximum_pages, {})
        issues = self._repository.list_issues(
            audit_id,
            0,
            min(
                self.configuration.maximum_pages * self.configuration.maximum_issues_per_page,
                1_000_000,
            ),
            {},
        )
        severity = Counter(item["severity"] for item in issues)
        category = Counter(item["category"] for item in issues)
        codes = Counter(item["code"] for item in issues)
        status = Counter(
            str(item.http_status) if item.http_status is not None else "missing" for item in pages
        )
        content = Counter(item.content_type_category for item in pages)
        indexability = Counter(item.indexability_state for item in pages)
        groups = self._repository.duplicate_groups(
            audit_id, 0, self.configuration.maximum_page_size
        )
        return {
            "total_pages": len(pages),
            "audited_html_pages": content["html"],
            "non_html_pages": len(pages) - content["html"],
            "pages_with_issues": sum(item.issue_count > 0 for item in pages),
            "pages_without_issues": sum(item.issue_count == 0 for item in pages),
            "total_issues": len(issues),
            "severity_counts": dict(sorted(severity.items())),
            "category_counts": dict(sorted(category.items())),
            "issue_code_counts": dict(sorted(codes.items())),
            "duplicate_title_group_count": sum(
                item.duplicate_type is DuplicateType.TITLE for item in groups
            ),
            "duplicate_description_group_count": sum(
                item.duplicate_type is DuplicateType.META_DESCRIPTION for item in groups
            ),
            "status_distribution": dict(sorted(status.items())),
            "content_type_distribution": dict(sorted(content.items())),
            "indexability_distribution": dict(sorted(indexability.items())),
            "partial_page_count": sum(item.partial for item in pages),
            "failed_page_count": sum(item.fetch_outcome == "failure" for item in pages),
            "export_available": True,
            "audit_state": "completed",
            "versions": self.versions(),
        }

    def _export_bytes(
        self,
        audit: MetadataAudit,
        export_format: ExportFormat,
        issues: tuple[dict[str, Any], ...],
        truncated: bool,
    ) -> bytes:
        if export_format is ExportFormat.CSV:
            stream = io.StringIO(newline="")
            fields = (
                "audit_id",
                "run_id",
                "url",
                "category",
                "code",
                "severity",
                "summary",
                "determinacy",
                "status",
                "content_type",
                "duplicate_group_id",
            )
            writer = csv.DictWriter(
                stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n"
            )
            writer.writeheader()
            for issue in issues:
                row = {**issue, "audit_id": audit.audit_id, "run_id": audit.run_id}
                writer.writerow({key: _csv_safe(row.get(key)) for key in fields})
            return stream.getvalue().encode("utf-8")
        if export_format is ExportFormat.JSON:
            payload = {
                "audit": asdict(audit),
                "summary": self.get_summary(audit.audit_id),
                "issues": issues,
                "truncated": truncated,
                "versions": {**self.versions(), "export": METADATA_AUDIT_EXPORT_VERSION},
            }
            return (
                json.dumps(
                    payload, sort_keys=True, default=str, ensure_ascii=False, separators=(",", ":")
                )
                + "\n"
            ).encode()
        summary = self.get_summary(audit.audit_id)
        lines = [
            "# Metadata audit",
            "",
            f"Audit: `{audit.audit_id}`",
            "",
            "## Severity summary",
            "",
        ]
        lines.extend(f"- {key}: {value}" for key, value in summary["severity_counts"].items())
        lines.extend(["", "## Critical and high findings", ""])
        lines.extend(
            f"- **{item['severity']}** `{item['code']}` — {item['summary']}"
            for item in issues
            if item["severity"] in {"critical", "high"}
        )
        lines.extend(
            [
                "",
                "## Limitations",
                "",
                "This report uses durable crawl evidence only; no page was re-fetched or reparsed.",
                f"Export truncated: {str(truncated).lower()}.",
                "",
                f"Audit version: `{METADATA_AUDIT_VERSION}`.",
            ]
        )
        return ("\n".join(lines) + "\n").encode()


def _csv_safe(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text
