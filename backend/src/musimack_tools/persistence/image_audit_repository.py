"""Short-transaction persistence for restart-safe image audits."""

# ruff: noqa: ANN401, FBT001, PLR0913

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update

from musimack_tools.domain.image_audit import (
    IMAGE_AUDIT_VERSION,
    IMAGE_EVIDENCE_VERSION,
    IMAGE_POLICY_VERSION,
    ImageAuditConfiguration,
    ImageAuditLifecycle,
    stable_json,
)
from musimack_tools.persistence.image_audit_models import (
    CrawlImageEvidenceModel,
    ImageAuditEventModel,
    ImageAuditExportModel,
    ImageAuditModel,
    ImageAuditResourceModel,
    ImageDuplicateGroupModel,
    ImageFindingModel,
    ImageOccurrenceAnalysisModel,
    ImagePageSummaryModel,
    ImageRecommendationModel,
)
from musimack_tools.persistence.link_audit_repository import SQLAlchemyLinkAuditRepository

_RUNNING = {
    ImageAuditLifecycle.CLAIMING.value,
    ImageAuditLifecycle.BUILDING_INVENTORY.value,
    ImageAuditLifecycle.RESOLVING_RESOURCES.value,
    ImageAuditLifecycle.CLASSIFYING_ALT_TEXT.value,
    ImageAuditLifecycle.ANALYZING_REUSE.value,
    ImageAuditLifecycle.BUILDING_RECOMMENDATIONS.value,
}


class SQLAlchemyImageAuditRepository:
    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self._evidence = SQLAlchemyLinkAuditRepository(runtime)

    def run_context(self, run_id: str) -> tuple[str, str, bool, int, int] | None:
        context = self._evidence.run_context(run_id)
        if context is None:
            return None
        with self._runtime.transaction() as session:
            images = int(
                session.scalar(
                    select(func.count())
                    .select_from(CrawlImageEvidenceModel)
                    .where(CrawlImageEvidenceModel.run_id == run_id)
                )
                or 0
            )
        return context[0], context[1], context[2], context[3], images

    def run_scope_snapshot(self, run_id: str) -> Any:
        return self._evidence.run_scope_snapshot(run_id)

    def pages(self, run_id: str) -> tuple[dict[str, Any], ...]:
        return self._evidence.pages(run_id)

    def images(self, run_id: str) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(CrawlImageEvidenceModel)
                .where(CrawlImageEvidenceModel.run_id == run_id)
                .order_by(
                    CrawlImageEvidenceModel.occurrence_sequence, CrawlImageEvidenceModel.image_id
                )
            )
            return tuple(_dict(row) for row in rows)

    def image_evidence_versions(self, run_id: str) -> tuple[str, ...]:
        with self._runtime.transaction() as session:
            values = session.scalars(
                select(CrawlImageEvidenceModel.evidence_version)
                .where(CrawlImageEvidenceModel.run_id == run_id)
                .distinct()
                .order_by(CrawlImageEvidenceModel.evidence_version)
            )
            return tuple(values)

    def create(
        self,
        audit_id: str,
        job_id: str,
        run_id: str,
        scope_snapshot: dict[str, Any],
        configuration: ImageAuditConfiguration,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            existing = session.get(ImageAuditModel, audit_id)
            if existing is not None:
                return _dict(existing)
            row = ImageAuditModel(
                audit_id=audit_id,
                job_id=job_id,
                run_id=run_id,
                scope_snapshot_json=stable_json(scope_snapshot),
                configuration_json=stable_json(configuration.snapshot()),
                state=ImageAuditLifecycle.ACCEPTED.value,
                failure_code=None,
                warning_count=0,
                image_occurrence_count=0,
                unique_image_count=0,
                valid_image_count=0,
                broken_image_count=0,
                redirecting_image_count=0,
                unverified_image_count=0,
                missing_alt_count=0,
                empty_alt_count=0,
                generic_alt_count=0,
                filename_alt_count=0,
                duplicate_alt_count=0,
                missing_dimensions_count=0,
                loading_review_count=0,
                recommendation_count=0,
                created_at=now,
                started_at=None,
                completed_at=None,
                retention_until=now + timedelta(days=configuration.retention_days),
                audit_version=IMAGE_AUDIT_VERSION,
                evidence_version=IMAGE_EVIDENCE_VERSION,
                policy_version=IMAGE_POLICY_VERSION,
            )
            session.add(row)
            session.flush()
            session.add(_event(audit_id, "created", None, 0))
            return _dict(row)

    def claim_execution(self, audit_id: str) -> bool:
        with self._runtime.transaction() as session:
            result = session.execute(
                update(ImageAuditModel)
                .where(
                    ImageAuditModel.audit_id == audit_id,
                    ImageAuditModel.state == ImageAuditLifecycle.ACCEPTED.value,
                )
                .values(
                    state=ImageAuditLifecycle.CLAIMING.value,
                    started_at=datetime.now(UTC),
                    failure_code=None,
                )
            )
            if result.rowcount != 1:
                return False
            session.add(_event(audit_id, ImageAuditLifecycle.CLAIMING.value, None, 0))
            return True

    def transition(
        self, audit_id: str, state: ImageAuditLifecycle, failure_code: str | None = None
    ) -> None:
        with self._runtime.transaction() as session:
            row = _required(session.get(ImageAuditModel, audit_id))
            row.state = state.value
            row.failure_code = failure_code
            if state in {
                ImageAuditLifecycle.COMPLETED,
                ImageAuditLifecycle.COMPLETED_WITH_WARNINGS,
                ImageAuditLifecycle.FAILED,
                ImageAuditLifecycle.CANCELLED,
            }:
                row.completed_at = datetime.now(UTC)
            session.add(_event(audit_id, state.value, failure_code, 0))

    def fail_if_running(self, audit_id: str, code: str) -> bool:
        with self._runtime.transaction() as session:
            row = session.get(ImageAuditModel, audit_id)
            if row is None or row.state not in _RUNNING:
                return False
            row.state, row.failure_code, row.completed_at = (
                ImageAuditLifecycle.FAILED.value,
                code,
                datetime.now(UTC),
            )
            session.add(_event(audit_id, "failed", code, 0))
            return True

    def reconcile_interrupted(self) -> int:
        with self._runtime.transaction() as session:
            rows = tuple(
                session.scalars(select(ImageAuditModel).where(ImageAuditModel.state.in_(_RUNNING)))
            )
            for row in rows:
                row.state, row.failure_code, row.completed_at = (
                    "failed",
                    "image_audit_interrupted",
                    datetime.now(UTC),
                )
                session.add(_event(row.audit_id, "failed", row.failure_code, 0))
            return len(rows)

    def persist_resource(self, audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        return self._persist(ImageAuditResourceModel, audit_id, values)

    def persist_occurrence(self, audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        return self._persist(ImageOccurrenceAnalysisModel, audit_id, values)

    def persist_group(self, audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        return self._persist(ImageDuplicateGroupModel, audit_id, values)

    def persist_page(self, audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        return self._persist(ImagePageSummaryModel, audit_id, values)

    def persist_finding(self, audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        return self._persist(ImageFindingModel, audit_id, values)

    def persist_recommendation(self, audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        return self._persist(ImageRecommendationModel, audit_id, values)

    def _persist(self, model: Any, audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = model(audit_id=audit_id, **values)
            session.add(row)
            session.flush()
            return _dict(row)

    def finalize(self, audit_id: str, warning_count: int = 0) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = _required(session.get(ImageAuditModel, audit_id))
            resources = tuple(
                session.scalars(
                    select(ImageAuditResourceModel).where(
                        ImageAuditResourceModel.audit_id == audit_id
                    )
                )
            )
            occurrences = tuple(
                session.scalars(
                    select(ImageOccurrenceAnalysisModel).where(
                        ImageOccurrenceAnalysisModel.audit_id == audit_id
                    )
                )
            )
            groups = tuple(
                session.scalars(
                    select(ImageDuplicateGroupModel).where(
                        ImageDuplicateGroupModel.audit_id == audit_id
                    )
                )
            )
            recommendations = int(
                session.scalar(
                    select(func.count())
                    .select_from(ImageRecommendationModel)
                    .where(ImageRecommendationModel.audit_id == audit_id)
                )
                or 0
            )
            row.warning_count = warning_count
            row.image_occurrence_count = len(occurrences)
            row.unique_image_count = len(resources)
            row.valid_image_count = sum(item.resource_state == "valid_image" for item in resources)
            row.broken_image_count = sum(
                item.resource_state == "broken_image" for item in resources
            )
            row.redirecting_image_count = sum(
                item.resource_state == "redirecting_image" for item in resources
            )
            row.unverified_image_count = sum(
                item.resource_state == "unverified_image" for item in resources
            )
            row.missing_alt_count = sum(item.alt_state == "alt_missing" for item in occurrences)
            row.empty_alt_count = sum(
                item.alt_state in {"alt_empty", "alt_whitespace_only", "alt_image_link_empty"}
                for item in occurrences
            )
            row.generic_alt_count = sum(item.alt_state == "alt_generic" for item in occurrences)
            row.filename_alt_count = sum(
                item.alt_state == "alt_filename_like" for item in occurrences
            )
            row.duplicate_alt_count = len(groups)
            row.missing_dimensions_count = sum(
                item.dimension_state != "dimensions_present" for item in occurrences
            )
            row.loading_review_count = sum(
                item.loading_state
                in {"lazy_loading_missing", "invalid_loading_value", "loading_review"}
                for item in occurrences
            )
            row.recommendation_count = recommendations
            row.state = (
                ImageAuditLifecycle.COMPLETED_WITH_WARNINGS
                if warning_count
                else ImageAuditLifecycle.COMPLETED
            ).value
            row.completed_at = datetime.now(UTC)
            session.add(_event(audit_id, row.state, None, len(occurrences)))
            session.flush()
            return _dict(row)

    def get(self, audit_id: str) -> dict[str, Any] | None:
        with self._runtime.transaction() as session:
            row = session.get(ImageAuditModel, audit_id)
            return _dict(row) if row is not None else None

    def list_model(
        self, model: Any, audit_id: str, *, order: Any, filters: tuple[Any, ...] = ()
    ) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            statement = select(model).where(model.audit_id == audit_id, *filters).order_by(*order)
            return tuple(_dict(row) for row in session.scalars(statement))

    def list_audits(self) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            return tuple(
                _dict(row)
                for row in session.scalars(
                    select(ImageAuditModel).order_by(
                        ImageAuditModel.created_at.desc(), ImageAuditModel.audit_id.desc()
                    )
                )
            )

    def upsert_export(
        self,
        audit_id: str,
        export_id: str,
        export_format: str,
        artifact_id: str | None,
        row_count: int,
        truncated: bool,
        state: str,
        failure_code: str | None = None,
    ) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = session.scalar(
                select(ImageAuditExportModel).where(
                    ImageAuditExportModel.audit_id == audit_id,
                    ImageAuditExportModel.export_format == export_format,
                )
            )
            if row is None:
                row = ImageAuditExportModel(
                    export_id=export_id,
                    audit_id=audit_id,
                    export_format=export_format,
                    artifact_id=artifact_id,
                    row_count=row_count,
                    truncated=truncated,
                    state=state,
                    failure_code=failure_code,
                    created_at=datetime.now(UTC),
                )
                session.add(row)
            else:
                row.artifact_id, row.row_count, row.truncated, row.state, row.failure_code = (
                    artifact_id,
                    row_count,
                    truncated,
                    state,
                    failure_code,
                )
            session.flush()
            return _dict(row)

    def list_exports(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        return self.list_model(
            ImageAuditExportModel,
            audit_id,
            order=(ImageAuditExportModel.created_at, ImageAuditExportModel.export_id),
        )

    def cleanup(self, *, now: datetime | None = None) -> int:
        with self._runtime.transaction() as session:
            result = session.execute(
                delete(ImageAuditModel).where(
                    ImageAuditModel.retention_until < (now or datetime.now(UTC)),
                    ImageAuditModel.state.in_(
                        ("completed", "completed_with_warnings", "failed", "cancelled")
                    ),
                )
            )
            return int(result.rowcount or 0)


def _event(
    audit_id: str, event_type: str, reason: str | None, affected: int
) -> ImageAuditEventModel:
    return ImageAuditEventModel(
        audit_id=audit_id,
        event_type=event_type,
        safe_reason_code=reason,
        affected_count=affected,
        occurred_at=datetime.now(UTC),
        version=IMAGE_AUDIT_VERSION,
    )


def _required(value: Any) -> Any:
    if value is None:
        raise ValueError("image_audit_not_found")
    return value


def _dict(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}
