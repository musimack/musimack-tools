"""Transactional repository for CSA-04 parent orchestration state."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from musimack_tools.domain.site_audit_orchestration import (
    MAXIMUM_STAGE_RETRIES,
    SITE_AUDIT_ORCHESTRATION_VERSION,
    STAGE_DEPENDENCIES,
    ArtifactPurpose,
    OrchestrationState,
    SiteAuditOrchestrationError,
    SiteAuditStage,
    StageState,
    enabled_stage_graph,
)
from musimack_tools.domain.site_audit_persistence import normalized_url_identity
from musimack_tools.persistence.site_audit_models import (
    SiteAuditArtifactAssociationModel,
    SiteAuditModel,
    SiteAuditOrchestrationModel,
    SiteAuditOrchestrationStageModel,
    SiteAuditSpecialistAssociationModel,
    SiteAuditSummaryModel,
    SiteAuditURLModel,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from musimack_tools.persistence.base import Base
    from musimack_tools.persistence.engine import PersistenceRuntime


class SQLAlchemySiteAuditOrchestrationRepository:
    def __init__(self, runtime: PersistenceRuntime) -> None:
        self._runtime = runtime

    def initialize(self, audit_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        configuration = snapshot["configuration"]
        graph = enabled_stage_graph(configuration.get("enabled_modules", []))
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            audit = self._audit(session, audit_id)
            existing = session.get(SiteAuditOrchestrationModel, audit_id)
            if existing is not None:
                if existing.snapshot_sha256 != snapshot["sha256"]:
                    raise SiteAuditOrchestrationError(
                        "site_audit_submission_conflict",
                        "This Site Audit already has a different active execution.",
                    )
                return self._record(existing)
            row = SiteAuditOrchestrationModel(
                audit_id=audit_id,
                snapshot_id=str(snapshot["snapshot_id"]),
                snapshot_sha256=str(snapshot["sha256"]),
                state=OrchestrationState.QUEUED.value,
                current_stage=SiteAuditStage.CRAWL.value,
                cancellation_requested=False,
                retry_count=0,
                recovery_count=0,
                projection_version=SITE_AUDIT_ORCHESTRATION_VERSION,
                submitted_at=now,
                updated_at=now,
                revision=1,
            )
            session.add(row)
            session.flush()
            for order, (stage, required) in enumerate(graph):
                session.add(
                    SiteAuditOrchestrationStageModel(
                        audit_id=audit_id,
                        stage=stage.value,
                        stable_order=order,
                        required=required,
                        dependencies_json=json.dumps(
                            [item.value for item in STAGE_DEPENDENCIES[stage]],
                            separators=(",", ":"),
                        ),
                        state=StageState.PENDING.value,
                        attempt_count=0,
                        checkpoint=0,
                        source_count=0,
                        projected_count=0,
                        updated_at=now,
                    )
                )
            audit.parent_job_id = None
            audit.parent_run_id = None
            session.flush()
            return self._record(row)

    def orchestration(self, audit_id: str) -> dict[str, Any] | None:
        with self._runtime.transaction() as session:
            row = session.get(SiteAuditOrchestrationModel, audit_id)
            return self._record(row) if row else None

    def stages(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(SiteAuditOrchestrationStageModel)
                .where(SiteAuditOrchestrationStageModel.audit_id == audit_id)
                .order_by(SiteAuditOrchestrationStageModel.stable_order)
            )
            return tuple(self._stage_record(row) for row in rows)

    def attach_crawl(self, audit_id: str, job_id: str, run_id: str) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = self._orchestration(session, audit_id)
            if row.crawl_job_id is not None and (row.crawl_job_id, row.crawl_run_id) != (
                job_id,
                run_id,
            ):
                raise SiteAuditOrchestrationError(
                    "site_audit_submission_conflict", "The Site Audit crawl is already associated."
                )
            row.crawl_job_id = job_id
            row.crawl_run_id = run_id
            row.updated_at = datetime.now(UTC)
            row.revision += 1
            audit = self._audit(session, audit_id)
            audit.parent_job_id = job_id
            audit.parent_run_id = run_id
            session.flush()
            return self._record(row)

    def set_state(
        self,
        audit_id: str,
        state: OrchestrationState,
        *,
        current_stage: SiteAuditStage | None = None,
        failure_code: str | None = None,
        failure_explanation: str | None = None,
    ) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = self._orchestration(session, audit_id)
            now = datetime.now(UTC)
            row.state = state.value
            row.current_stage = current_stage.value if current_stage else None
            row.failure_code = failure_code
            row.failure_explanation = failure_explanation
            row.updated_at = now
            row.revision += 1
            if state is OrchestrationState.RUNNING and row.started_at is None:
                row.started_at = now
            if state in {
                OrchestrationState.CANCELLED,
                OrchestrationState.COMPLETED,
                OrchestrationState.COMPLETED_WITH_WARNINGS,
                OrchestrationState.PARTIALLY_COMPLETED,
                OrchestrationState.FAILED,
            }:
                row.completed_at = now
            session.flush()
            return self._record(row)

    def update_stage(  # noqa: PLR0913
        self,
        audit_id: str,
        stage: SiteAuditStage,
        state: StageState,
        *,
        checkpoint: int | None = None,
        source_count: int | None = None,
        projected_count: int | None = None,
        failure_code: str | None = None,
        failure_explanation: str | None = None,
        lease_owner: str | None = None,
        lease_seconds: int = 60,
    ) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = self._stage(session, audit_id, stage)
            now = datetime.now(UTC)
            if state is StageState.RUNNING and row.state != StageState.RUNNING.value:
                row.attempt_count += 1
                row.started_at = now
            row.state = state.value
            row.updated_at = now
            row.failure_code = failure_code
            row.failure_explanation = failure_explanation
            if checkpoint is not None:
                row.checkpoint = max(row.checkpoint, checkpoint)
            if source_count is not None:
                row.source_count = source_count
            if projected_count is not None:
                row.projected_count = projected_count
            if state.terminal:
                row.completed_at = now
                row.lease_owner = None
                row.lease_expires_at = None
            else:
                row.lease_owner = lease_owner
                row.lease_expires_at = now + timedelta(seconds=lease_seconds)
            session.flush()
            return self._stage_record(row)

    def request_cancellation(self, audit_id: str) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = self._orchestration(session, audit_id)
            if row.state in {
                OrchestrationState.CANCELLED.value,
                OrchestrationState.COMPLETED.value,
                OrchestrationState.COMPLETED_WITH_WARNINGS.value,
                OrchestrationState.PARTIALLY_COMPLETED.value,
                OrchestrationState.FAILED.value,
            }:
                return self._record(row)
            row.cancellation_requested = True
            row.state = OrchestrationState.CANCEL_REQUESTED.value
            row.updated_at = datetime.now(UTC)
            row.revision += 1
            session.flush()
            return self._record(row)

    def retry(self, audit_id: str) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = self._orchestration(session, audit_id)
            if row.state not in {
                OrchestrationState.FAILED.value,
                OrchestrationState.RECOVERY_REQUIRED.value,
            }:
                raise SiteAuditOrchestrationError(
                    "site_audit_retry_not_allowed", "This Site Audit cannot be retried."
                )
            if row.retry_count >= MAXIMUM_STAGE_RETRIES:
                raise SiteAuditOrchestrationError(
                    "site_audit_retry_limit_reached", "The Site Audit retry limit was reached."
                )
            for stage in session.scalars(
                select(SiteAuditOrchestrationStageModel).where(
                    SiteAuditOrchestrationStageModel.audit_id == audit_id,
                    SiteAuditOrchestrationStageModel.state.in_(
                        [StageState.FAILED.value, StageState.BLOCKED.value]
                    ),
                )
            ):
                stage.state = StageState.PENDING.value
                stage.failure_code = None
                stage.failure_explanation = None
                stage.completed_at = None
                stage.updated_at = datetime.now(UTC)
            row.retry_count += 1
            row.state = OrchestrationState.QUEUED.value
            row.failure_code = None
            row.failure_explanation = None
            row.completed_at = None
            row.updated_at = datetime.now(UTC)
            row.revision += 1
            session.flush()
            return self._record(row)

    def recover_expired(self, *, limit: int = 100) -> tuple[str, ...]:
        now = datetime.now(UTC)
        recovered: list[str] = []
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(SiteAuditOrchestrationStageModel)
                .where(
                    SiteAuditOrchestrationStageModel.state == StageState.RUNNING.value,
                    SiteAuditOrchestrationStageModel.lease_expires_at < now,
                )
                .order_by(SiteAuditOrchestrationStageModel.lease_expires_at)
                .limit(max(1, min(limit, 500)))
            )
            for stage in rows:
                stage.state = StageState.PENDING.value
                stage.lease_owner = None
                stage.lease_expires_at = None
                stage.failure_code = "site_audit_stage_lease_expired"
                stage.failure_explanation = "The interrupted stage is ready for reconciliation."
                stage.updated_at = now
                parent = self._orchestration(session, stage.audit_id)
                parent.state = OrchestrationState.RECOVERY_REQUIRED.value
                parent.recovery_count += 1
                parent.updated_at = now
                parent.revision += 1
                recovered.append(stage.audit_id)
            session.flush()
        return tuple(dict.fromkeys(recovered))

    def reconcilable(self, *, limit: int = 25) -> tuple[str, ...]:
        """Return a stable bounded parent scan, including incomplete terminal projections."""
        bounded = max(1, min(limit, 100))
        active_states = {
            OrchestrationState.QUEUED.value,
            OrchestrationState.RUNNING.value,
            OrchestrationState.CANCEL_REQUESTED.value,
            OrchestrationState.RECOVERY_REQUIRED.value,
        }
        repair_states = {
            OrchestrationState.COMPLETED.value,
            OrchestrationState.COMPLETED_WITH_WARNINGS.value,
            OrchestrationState.PARTIALLY_COMPLETED.value,
        }
        result: list[str] = []
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(SiteAuditOrchestrationModel)
                .where(SiteAuditOrchestrationModel.crawl_job_id.is_not(None))
                .order_by(
                    SiteAuditOrchestrationModel.updated_at,
                    SiteAuditOrchestrationModel.audit_id,
                )
                .limit(500)
            )
            for row in rows:
                if row.state in active_states and row.recovery_count < MAXIMUM_STAGE_RETRIES:
                    result.append(row.audit_id)
                elif row.state in repair_states:
                    summary = session.get(SiteAuditSummaryModel, row.audit_id)
                    artifacts = tuple(
                        session.scalars(
                            select(SiteAuditArtifactAssociationModel).where(
                                SiteAuditArtifactAssociationModel.audit_id == row.audit_id
                            )
                        )
                    )
                    if summary is None or len(artifacts) < len(ArtifactPurpose):
                        result.append(row.audit_id)
                if len(result) >= bounded:
                    break
        return tuple(result)

    def record_reconciliation_failure(self, audit_id: str) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = self._orchestration(session, audit_id)
            row.state = OrchestrationState.RECOVERY_REQUIRED.value
            row.failure_code = "site_audit_reconciliation_failed"
            row.failure_explanation = "Automatic reconciliation requires bounded recovery."
            row.recovery_count += 1
            row.updated_at = datetime.now(UTC)
            row.revision += 1
            session.flush()
            return self._record(row)

    def upsert_specialist(self, audit_id: str, record: dict[str, Any]) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            self._orchestration(session, audit_id)
            row = session.scalar(
                select(SiteAuditSpecialistAssociationModel).where(
                    SiteAuditSpecialistAssociationModel.audit_id == audit_id,
                    SiteAuditSpecialistAssociationModel.module == str(record["module"]),
                )
            )
            now = datetime.now(UTC)
            values = {
                "specialist_audit_id": record.get("specialist_audit_id"),
                "source_run_id": record.get("source_run_id"),
                "execution_source": str(record.get("execution_source", "base_evidence")),
                "eligibility_state": str(record.get("eligibility_state", "eligible")),
                "eligibility_reason": str(record.get("eligibility_reason", "same_crawl_run")),
                "freshness_state": str(record.get("freshness_state", "current")),
                "partial": bool(record.get("partial", False)),
                "evidence_count": int(record.get("evidence_count", 0)),
                "updated_at": now,
            }
            if row is None:
                row = SiteAuditSpecialistAssociationModel(
                    audit_id=audit_id,
                    module=str(record["module"]),
                    associated_at=now,
                    **values,
                )
                session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            session.flush()
            return self._record(row)

    def specialists(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(SiteAuditSpecialistAssociationModel)
                .where(SiteAuditSpecialistAssociationModel.audit_id == audit_id)
                .order_by(SiteAuditSpecialistAssociationModel.module)
            )
            return tuple(self._record(row) for row in rows)

    def find_url(self, audit_id: str, normalized_url: str) -> dict[str, Any] | None:
        identity = normalized_url_identity(normalized_url)
        with self._runtime.transaction() as session:
            row = session.scalar(
                select(SiteAuditURLModel).where(
                    SiteAuditURLModel.audit_id == audit_id,
                    SiteAuditURLModel.normalized_url_identity == identity,
                )
            )
            return self._record(row) if row else None

    def update_url(self, audit_id: str, url_id: str, values: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "enqueued_state",
            "discovery_decision",
            "metadata_scoring_decision",
            "sitemap_policy_decision",
            "recommended_sitemap_state",
            "existing_sitemap_state",
            "indexability_state",
            "canonical_state",
            "robots_state",
            "partial",
            "failure_code",
            "highest_severity",
            "issue_count",
        }
        with self._runtime.transaction() as session:
            row = session.get(SiteAuditURLModel, url_id)
            if row is None or row.audit_id != audit_id:
                raise SiteAuditOrchestrationError(
                    "site_audit_url_not_found", "The Site Audit URL was not found."
                )
            for key, value in values.items():
                if key in allowed:
                    setattr(row, key, value)
            row.updated_at = datetime.now(UTC)
            session.flush()
            return self._record(row)

    @staticmethod
    def _audit(session: Session, audit_id: str) -> SiteAuditModel:
        row = session.get(SiteAuditModel, audit_id)
        if row is None:
            raise SiteAuditOrchestrationError(
                "site_audit_not_found", "The Site Audit was not found."
            )
        return row

    @staticmethod
    def _orchestration(session: Session, audit_id: str) -> SiteAuditOrchestrationModel:
        row = session.get(SiteAuditOrchestrationModel, audit_id)
        if row is None:
            raise SiteAuditOrchestrationError(
                "site_audit_orchestration_not_found", "The Site Audit execution was not found."
            )
        return row

    @staticmethod
    def _stage(
        session: Session, audit_id: str, stage: SiteAuditStage
    ) -> SiteAuditOrchestrationStageModel:
        row = session.scalar(
            select(SiteAuditOrchestrationStageModel).where(
                SiteAuditOrchestrationStageModel.audit_id == audit_id,
                SiteAuditOrchestrationStageModel.stage == stage.value,
            )
        )
        if row is None:
            raise SiteAuditOrchestrationError(
                "site_audit_stage_not_found", "The Site Audit stage was not found."
            )
        return row

    @staticmethod
    def _record(row: Base) -> dict[str, Any]:
        return {
            column.name: (
                (
                    value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
                ).isoformat()
                if isinstance(value := getattr(row, column.name), datetime)
                else value
            )
            for column in row.__table__.columns
        }

    @classmethod
    def _stage_record(cls, row: SiteAuditOrchestrationStageModel) -> dict[str, Any]:
        result = cls._record(row)
        result["dependencies"] = tuple(json.loads(row.dependencies_json))
        result.pop("dependencies_json")
        return result
