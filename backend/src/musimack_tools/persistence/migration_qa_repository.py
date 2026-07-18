"""Short-transaction persistence for website migration QA projects."""

# ruff: noqa: ANN401

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update

from musimack_tools.domain.migration_qa import MigrationQaConfiguration, stable_json
from musimack_tools.persistence.link_audit_repository import SQLAlchemyLinkAuditRepository
from musimack_tools.persistence.migration_qa_models import (
    MigrationEventModel,
    MigrationExportModel,
    MigrationFindingModel,
    MigrationPageComparisonModel,
    MigrationQaProjectModel,
    MigrationRecommendationModel,
    MigrationRedirectMapRowModel,
    MigrationRedirectObservationModel,
    MigrationSitewideSummaryModel,
    MigrationSourceRowModel,
    MigrationUrlMappingModel,
)

RESOURCE_MODELS: dict[str, Any] = {
    "sources": MigrationSourceRowModel,
    "redirect-map": MigrationRedirectMapRowModel,
    "mappings": MigrationUrlMappingModel,
    "redirects": MigrationRedirectObservationModel,
    "comparisons": MigrationPageComparisonModel,
    "findings": MigrationFindingModel,
    "recommendations": MigrationRecommendationModel,
    "sitewide": MigrationSitewideSummaryModel,
}


def is_expired_evidence_timestamp(expires_at: datetime, now: datetime) -> bool:
    """Compare SQLite-naive and timezone-aware evidence timestamps as UTC."""
    normalized_expiry = (
        expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at.astimezone(UTC)
    )
    normalized_now = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    return normalized_expiry <= normalized_now


class SQLAlchemyMigrationQaRepository:
    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self._evidence = SQLAlchemyLinkAuditRepository(runtime)

    def run_context(self, run_id: str) -> tuple[str, str, bool, int, int] | None:
        return self._evidence.run_context(run_id)

    def pages(self, run_id: str) -> tuple[dict[str, Any], ...]:
        return self._evidence.pages(run_id)

    def links(self, run_id: str) -> tuple[dict[str, Any], ...]:
        return self._evidence.source_links(run_id)

    def evidence_inventory(self, run_id: str) -> dict[str, Any]:
        from musimack_tools.persistence.image_audit_models import (  # noqa: PLC0415
            CrawlImageEvidenceModel,
        )
        from musimack_tools.persistence.link_audit_models import (  # noqa: PLC0415
            CrawlLinkEvidenceModel,
        )
        from musimack_tools.persistence.models import CrawlPageEvidenceModel  # noqa: PLC0415
        from musimack_tools.persistence.sitemap_audit_models import (  # noqa: PLC0415
            SitemapAuditEntryModel,
            SitemapAuditModel,
        )
        from musimack_tools.persistence.structured_data_models import (  # noqa: PLC0415
            CrawlStructuredDataEvidenceModel,
        )

        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            pages = tuple(
                session.scalars(
                    select(CrawlPageEvidenceModel).where(CrawlPageEvidenceModel.run_id == run_id)
                )
            )
            sitemap_id = session.scalar(
                select(SitemapAuditModel.audit_id)
                .where(
                    SitemapAuditModel.run_id == run_id,
                    SitemapAuditModel.state.in_(
                        ("completed", "completed_with_warnings", "partially_completed")
                    ),
                )
                .order_by(SitemapAuditModel.completed_at.desc())
                .limit(1)
            )

            def count(model: Any, condition: Any) -> int:
                return int(
                    session.scalar(select(func.count()).select_from(model).where(condition)) or 0
                )

            return {
                "page_count": len(pages),
                "page_versions": sorted({row.evidence_version for row in pages}),
                "expired": bool(pages)
                and all(is_expired_evidence_timestamp(row.expires_at, now) for row in pages),
                "link_count": count(
                    CrawlLinkEvidenceModel, CrawlLinkEvidenceModel.run_id == run_id
                ),
                "sitemap_count": count(
                    SitemapAuditEntryModel,
                    SitemapAuditEntryModel.audit_id == sitemap_id,
                )
                if sitemap_id
                else 0,
                "image_count": count(
                    CrawlImageEvidenceModel, CrawlImageEvidenceModel.run_id == run_id
                ),
                "structured_data_count": count(
                    CrawlStructuredDataEvidenceModel,
                    CrawlStructuredDataEvidenceModel.run_id == run_id,
                ),
            }

    def sitemap_urls(self, run_id: str) -> tuple[dict[str, Any], ...]:
        from musimack_tools.persistence.sitemap_audit_models import (  # noqa: PLC0415
            SitemapAuditEntryModel,
            SitemapAuditModel,
        )

        with self._runtime.transaction() as session:
            audit_id = session.scalar(
                select(SitemapAuditModel.audit_id)
                .where(
                    SitemapAuditModel.run_id == run_id,
                    SitemapAuditModel.state.in_(
                        ("completed", "completed_with_warnings", "partially_completed")
                    ),
                )
                .order_by(SitemapAuditModel.completed_at.desc())
                .limit(1)
            )
            if audit_id is None:
                return ()
            rows = session.scalars(
                select(SitemapAuditEntryModel)
                .where(
                    SitemapAuditEntryModel.audit_id == audit_id,
                    SitemapAuditEntryModel.is_child_reference.is_(False),
                )
                .order_by(SitemapAuditEntryModel.entry_sequence)
            )
            return tuple(_dict(row) for row in rows)

    def images(self, run_id: str) -> tuple[dict[str, Any], ...]:
        from musimack_tools.persistence.image_audit_models import (  # noqa: PLC0415
            CrawlImageEvidenceModel,
            ImageAuditModel,
            ImageAuditResourceModel,
        )

        with self._runtime.transaction() as session:
            audit_id = session.scalar(
                select(ImageAuditModel.audit_id)
                .where(
                    ImageAuditModel.run_id == run_id,
                    ImageAuditModel.state.in_(("completed", "completed_with_warnings")),
                )
                .order_by(ImageAuditModel.completed_at.desc())
                .limit(1)
            )
            resources = (
                {
                    row.image_identity: _dict(row)
                    for row in session.scalars(
                        select(ImageAuditResourceModel).where(
                            ImageAuditResourceModel.audit_id == audit_id
                        )
                    )
                }
                if audit_id
                else {}
            )
            rows = session.scalars(
                select(CrawlImageEvidenceModel)
                .where(CrawlImageEvidenceModel.run_id == run_id)
                .order_by(CrawlImageEvidenceModel.occurrence_sequence)
            )
            return tuple(
                {**_dict(row), "resource": resources.get(row.image_identity)} for row in rows
            )

    def structured_data(self, run_id: str) -> tuple[dict[str, Any], ...]:
        from musimack_tools.persistence.structured_data_models import (  # noqa: PLC0415
            CrawlStructuredDataEvidenceModel,
        )

        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(CrawlStructuredDataEvidenceModel)
                .where(CrawlStructuredDataEvidenceModel.run_id == run_id)
                .order_by(CrawlStructuredDataEvidenceModel.occurrence_sequence)
            )
            return tuple(_dict(row) for row in rows)

    def create(
        self, values: dict[str, Any], configuration: MigrationQaConfiguration
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        values = {
            **values,
            "configuration_json": stable_json(configuration.snapshot()),
            "state": "draft",
            "readiness": "missing_evidence",
            "total_sources": 0,
            "total_mappings": 0,
            "total_findings": 0,
            "warning_count": 0,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "retention_until": now + timedelta(days=configuration.retention_days),
            "failure_code": None,
        }
        with self._runtime.transaction() as session:
            existing = session.get(MigrationQaProjectModel, values["project_id"])
            if existing is not None:
                return _dict(existing)
            row = MigrationQaProjectModel(**values)
            session.add(row)
            session.flush()
            session.add(
                MigrationEventModel(
                    project_id=row.project_id,
                    state="draft",
                    affected_count=0,
                    detail=None,
                    created_at=now,
                )
            )
            session.flush()
            return _dict(row)

    def get(self, project_id: str) -> dict[str, Any] | None:
        with self._runtime.transaction() as session:
            row = session.get(MigrationQaProjectModel, project_id)
            return _dict(row) if row else None

    def list_projects(self) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            return tuple(
                _dict(row)
                for row in session.scalars(
                    select(MigrationQaProjectModel).order_by(
                        MigrationQaProjectModel.created_at.desc(),
                        MigrationQaProjectModel.project_id.desc(),
                    )
                )
            )

    def replace_input(self, project_id: str, name: str, rows: list[dict[str, Any]]) -> None:
        model = RESOURCE_MODELS[name]
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            session.execute(delete(model).where(model.project_id == project_id))
            session.add_all(model(**row) for row in rows)
            project = session.get(MigrationQaProjectModel, project_id)
            if project is None:
                raise ValueError("migration_qa_project_not_found")
            if name == "sources":
                project.total_sources = len(rows)
            project.updated_at = now
            project.state = "draft"
            project.readiness = "missing_evidence"
            session.add(
                MigrationEventModel(
                    project_id=project_id,
                    state=f"{name}_ingested",
                    affected_count=len(rows),
                    detail=None,
                    created_at=now,
                )
            )

    def set_readiness(self, project_id: str, readiness: str) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            row = session.get(MigrationQaProjectModel, project_id)
            if row is None:
                raise ValueError("migration_qa_project_not_found")
            row.readiness = readiness
            row.state = "ready" if readiness in {"ready", "ready_with_warnings"} else "draft"
            row.updated_at = now
            session.flush()
            return _dict(row)

    def claim_execution(self, project_id: str) -> bool:
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            result = session.execute(
                update(MigrationQaProjectModel)
                .where(
                    MigrationQaProjectModel.project_id == project_id,
                    MigrationQaProjectModel.state == "ready",
                )
                .values(state="running", updated_at=now)
            )
            if result.rowcount != 1:
                return False
            session.add(
                MigrationEventModel(
                    project_id=project_id,
                    state="running",
                    affected_count=0,
                    detail=None,
                    created_at=now,
                )
            )
            return True

    def replace_analysis(
        self, project_id: str, resources: dict[str, list[dict[str, Any]]], warnings: int
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        analysis_names = (
            "mappings",
            "redirects",
            "comparisons",
            "findings",
            "recommendations",
            "sitewide",
        )
        with self._runtime.transaction() as session:
            project = session.get(MigrationQaProjectModel, project_id)
            if project is None:
                raise ValueError("migration_qa_project_not_found")
            if project.state != "running":
                raise ValueError("migration_qa_already_terminal")
            for name in analysis_names:
                model = RESOURCE_MODELS[name]
                session.execute(delete(model).where(model.project_id == project_id))
                session.add_all(model(**value) for value in resources.get(name, []))
                session.flush()
            project.total_mappings = len(resources.get("mappings", []))
            project.total_findings = len(resources.get("findings", []))
            project.warning_count = warnings
            project.state = "completed_with_warnings" if warnings else "completed"
            project.updated_at = now
            project.completed_at = now
            project.failure_code = None
            session.add(
                MigrationEventModel(
                    project_id=project_id,
                    state=project.state,
                    affected_count=sum(len(value) for value in resources.values()),
                    detail=None,
                    created_at=now,
                )
            )
            session.flush()
            return _dict(project)

    def terminalize(self, project_id: str, state: str, failure_code: str | None) -> bool:
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            project = session.get(MigrationQaProjectModel, project_id)
            if project is None or project.state in {
                "completed",
                "completed_with_warnings",
                "failed",
                "cancelled",
            }:
                return False
            project.state = state
            project.failure_code = failure_code
            project.updated_at = now
            project.completed_at = now
            session.add(
                MigrationEventModel(
                    project_id=project_id,
                    state=state,
                    affected_count=0,
                    detail=failure_code,
                    created_at=now,
                )
            )
            return True

    def reconcile_interrupted(self) -> int:
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            rows = tuple(
                session.scalars(
                    select(MigrationQaProjectModel).where(
                        MigrationQaProjectModel.state == "running"
                    )
                )
            )
            for project in rows:
                project.state = "failed"
                project.failure_code = "migration_qa_interrupted"
                project.updated_at = now
                project.completed_at = now
            return len(rows)

    def list_resource(self, project_id: str, name: str) -> tuple[dict[str, Any], ...]:
        model = RESOURCE_MODELS[name]
        ordering = (
            model.sequence
            if hasattr(model, "sequence")
            else model.stable_id
            if hasattr(model, "stable_id")
            else model.id
        )
        with self._runtime.transaction() as session:
            return tuple(
                _dict(row)
                for row in session.scalars(
                    select(model).where(model.project_id == project_id).order_by(ordering)
                )
            )

    def upsert_export(self, values: dict[str, Any]) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = session.scalar(
                select(MigrationExportModel).where(
                    MigrationExportModel.project_id == values["project_id"],
                    MigrationExportModel.export_format == values["export_format"],
                )
            )
            if row is None:
                row = MigrationExportModel(**values)
                session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            session.flush()
            return _dict(row)

    def list_exports(self, project_id: str) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            return tuple(
                _dict(row)
                for row in session.scalars(
                    select(MigrationExportModel)
                    .where(MigrationExportModel.project_id == project_id)
                    .order_by(MigrationExportModel.export_format)
                )
            )

    def cleanup(self, now: datetime | None = None) -> int:
        with self._runtime.transaction() as session:
            result = session.execute(
                delete(MigrationQaProjectModel).where(
                    MigrationQaProjectModel.retention_until < (now or datetime.now(UTC)),
                    MigrationQaProjectModel.state.in_(
                        ("completed", "completed_with_warnings", "failed", "cancelled")
                    ),
                )
            )
            return int(result.rowcount or 0)


def _dict(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}
