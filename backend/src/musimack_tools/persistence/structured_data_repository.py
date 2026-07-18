"""Short-transaction persistence for structured-data audits."""

# ruff: noqa: ANN401

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update

from musimack_tools.domain.structured_data_audit import (
    StructuredDataAuditConfiguration,
    stable_json,
)
from musimack_tools.persistence.link_audit_repository import SQLAlchemyLinkAuditRepository
from musimack_tools.persistence.structured_data_models import (
    CrawlStructuredDataEvidenceModel,
    StructuredDataAuditModel,
    StructuredDataBlockModel,
    StructuredDataDuplicateGroupModel,
    StructuredDataEntityModel,
    StructuredDataEventModel,
    StructuredDataExportModel,
    StructuredDataFindingModel,
    StructuredDataPageSummaryModel,
    StructuredDataProfileModel,
    StructuredDataPropertyModel,
    StructuredDataRecommendationModel,
    StructuredDataReferenceModel,
)

RESOURCE_MODELS: dict[str, Any] = {
    "blocks": StructuredDataBlockModel,
    "entities": StructuredDataEntityModel,
    "properties": StructuredDataPropertyModel,
    "references": StructuredDataReferenceModel,
    "duplicate-groups": StructuredDataDuplicateGroupModel,
    "pages": StructuredDataPageSummaryModel,
    "parse-findings": StructuredDataFindingModel,
    "consistency-findings": StructuredDataFindingModel,
    "profiles": StructuredDataProfileModel,
    "recommendations": StructuredDataRecommendationModel,
}


class SQLAlchemyStructuredDataAuditRepository:
    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self._evidence = SQLAlchemyLinkAuditRepository(runtime)

    def run_context(self, run_id: str) -> tuple[str, str, bool, int, int] | None:
        context = self._evidence.run_context(run_id)
        if context is None:
            return None
        with self._runtime.transaction() as session:
            count = int(
                session.scalar(
                    select(func.count())
                    .select_from(CrawlStructuredDataEvidenceModel)
                    .where(CrawlStructuredDataEvidenceModel.run_id == run_id)
                )
                or 0
            )
        return context[0], context[1], context[2], context[3], count

    def pages(self, run_id: str) -> tuple[dict[str, Any], ...]:
        return self._evidence.pages(run_id)

    def evidence(self, run_id: str) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(CrawlStructuredDataEvidenceModel)
                .where(CrawlStructuredDataEvidenceModel.run_id == run_id)
                .order_by(CrawlStructuredDataEvidenceModel.occurrence_sequence)
            )
            return tuple(_dict(row) for row in rows)

    def evidence_versions(self, run_id: str) -> tuple[str, ...]:
        with self._runtime.transaction() as session:
            return tuple(
                sorted(
                    session.scalars(
                        select(CrawlStructuredDataEvidenceModel.evidence_version)
                        .where(CrawlStructuredDataEvidenceModel.run_id == run_id)
                        .distinct()
                    )
                )
            )

    def create(
        self,
        audit_id: str,
        job_id: str,
        run_id: str,
        configuration: StructuredDataAuditConfiguration,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            existing = session.get(StructuredDataAuditModel, audit_id)
            if existing is not None:
                return _dict(existing)
            row = StructuredDataAuditModel(
                audit_id=audit_id,
                job_id=job_id,
                run_id=run_id,
                configuration_json=stable_json(configuration.snapshot()),
                state="accepted",
                total_pages=0,
                total_blocks=0,
                total_entities=0,
                total_findings=0,
                warning_count=0,
                created_at=now,
                updated_at=now,
                completed_at=None,
                retention_until=now + timedelta(days=configuration.retention_days),
                failure_code=None,
            )
            session.add(row)
            session.add(
                StructuredDataEventModel(
                    audit_id=audit_id,
                    state="accepted",
                    affected_count=0,
                    detail=None,
                    created_at=now,
                )
            )
            session.flush()
            return _dict(row)

    def claim_execution(self, audit_id: str) -> bool:
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            result = session.execute(
                update(StructuredDataAuditModel)
                .where(
                    StructuredDataAuditModel.audit_id == audit_id,
                    StructuredDataAuditModel.state == "accepted",
                )
                .values(state="claiming", updated_at=now, failure_code=None)
            )
            if result.rowcount != 1:
                return False
            session.add(
                StructuredDataEventModel(
                    audit_id=audit_id,
                    state="claiming",
                    affected_count=0,
                    detail=None,
                    created_at=now,
                )
            )
            return True

    def terminalize(self, audit_id: str, state: str, failure_code: str) -> bool:
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            row = session.get(StructuredDataAuditModel, audit_id)
            if row is None or row.state not in {
                "claiming",
                "building_inventory",
                "analyzing_entities",
                "evaluating_profiles",
                "analyzing_consistency",
                "building_recommendations",
            }:
                return False
            row.state = state
            row.failure_code = failure_code
            row.updated_at = now
            row.completed_at = now
            session.add(
                StructuredDataEventModel(
                    audit_id=audit_id,
                    state=state,
                    affected_count=0,
                    detail=failure_code,
                    created_at=now,
                )
            )
            return True

    def reconcile_interrupted(self) -> int:
        now = datetime.now(UTC)
        running = {
            "claiming",
            "building_inventory",
            "analyzing_entities",
            "evaluating_profiles",
            "analyzing_consistency",
            "building_recommendations",
        }
        with self._runtime.transaction() as session:
            rows = tuple(
                session.scalars(
                    select(StructuredDataAuditModel).where(
                        StructuredDataAuditModel.state.in_(running)
                    )
                )
            )
            for row in rows:
                row.state = "failed"
                row.failure_code = "structured_data_audit_interrupted"
                row.updated_at = now
                row.completed_at = now
                session.add(
                    StructuredDataEventModel(
                        audit_id=row.audit_id,
                        state="failed",
                        affected_count=0,
                        detail=row.failure_code,
                        created_at=now,
                    )
                )
            return len(rows)

    def replace_analysis(
        self,
        audit_id: str,
        resources: dict[str, list[dict[str, Any]]],
        counts: dict[str, int],
        *,
        warnings: int,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            row = session.get(StructuredDataAuditModel, audit_id)
            if row is None:
                raise ValueError("structured_data_audit_not_found")
            if row.state != "claiming":
                raise ValueError("structured_data_audit_already_terminal")
            for model in set(RESOURCE_MODELS.values()):
                session.execute(delete(model).where(model.audit_id == audit_id))
            for name, values in resources.items():
                model = RESOURCE_MODELS[name]
                for value in values:
                    session.add(model(**value))
            for state in (
                "building_inventory",
                "analyzing_entities",
                "evaluating_profiles",
                "analyzing_consistency",
                "building_recommendations",
            ):
                session.add(
                    StructuredDataEventModel(
                        audit_id=audit_id,
                        state=state,
                        affected_count=0,
                        detail=None,
                        created_at=now,
                    )
                )
            row.state = "completed_with_warnings" if warnings else "completed"
            row.total_pages = counts["pages"]
            row.total_blocks = counts["blocks"]
            row.total_entities = counts["entities"]
            row.total_findings = counts["findings"]
            row.warning_count = warnings
            row.updated_at = now
            row.completed_at = now
            row.failure_code = None
            session.add(
                StructuredDataEventModel(
                    audit_id=audit_id,
                    state=row.state,
                    affected_count=sum(counts.values()),
                    detail=None,
                    created_at=now,
                )
            )
            session.flush()
            return _dict(row)

    def get(self, audit_id: str) -> dict[str, Any] | None:
        with self._runtime.transaction() as session:
            row = session.get(StructuredDataAuditModel, audit_id)
            return _dict(row) if row is not None else None

    def list_audits(self) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            return tuple(
                _dict(row)
                for row in session.scalars(
                    select(StructuredDataAuditModel).order_by(
                        StructuredDataAuditModel.created_at.desc(),
                        StructuredDataAuditModel.audit_id.desc(),
                    )
                )
            )

    def list_resource(self, audit_id: str, name: str) -> tuple[dict[str, Any], ...]:
        model = RESOURCE_MODELS[name]
        with self._runtime.transaction() as session:
            statement = select(model).where(model.audit_id == audit_id)
            if name == "parse-findings":
                statement = statement.where(model.category == "parse")
            elif name == "consistency-findings":
                statement = statement.where(model.category != "parse")
            return tuple(_dict(row) for row in session.scalars(statement.order_by(model.id)))

    def upsert_export(self, values: dict[str, Any]) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = session.scalar(
                select(StructuredDataExportModel).where(
                    StructuredDataExportModel.audit_id == values["audit_id"],
                    StructuredDataExportModel.export_format == values["export_format"],
                )
            )
            if row is None:
                row = StructuredDataExportModel(**values)
                session.add(row)
            else:
                row.media_type = values["media_type"]
                row.filename = values["filename"]
                row.artifact_id = values["artifact_id"]
                row.row_count = values["row_count"]
                row.truncated = values["truncated"]
                row.state = values["state"]
                row.created_at = values["created_at"]
            session.flush()
            return _dict(row)

    def list_exports(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            return tuple(
                _dict(row)
                for row in session.scalars(
                    select(StructuredDataExportModel)
                    .where(StructuredDataExportModel.audit_id == audit_id)
                    .order_by(StructuredDataExportModel.export_format)
                )
            )

    def cleanup(self, *, now: datetime | None = None) -> int:
        with self._runtime.transaction() as session:
            result = session.execute(
                delete(StructuredDataAuditModel).where(
                    StructuredDataAuditModel.retention_until < (now or datetime.now(UTC)),
                    StructuredDataAuditModel.state.in_(
                        ("completed", "completed_with_warnings", "failed", "cancelled")
                    ),
                )
            )
            return int(result.rowcount or 0)


def _dict(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}
