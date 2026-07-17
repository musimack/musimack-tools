"""Short-transaction persistence for internal-link graph audits."""

# ruff: noqa: ANN401, FBT001, PLR0913

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select, update

from musimack_tools.domain.internal_link import (
    INTERNAL_LINK_AUDIT_VERSION,
    INTERNAL_LINK_EXPORT_VERSION,
    INTERNAL_LINK_GRAPH_VERSION,
    INTERNAL_LINK_POLICY_VERSION,
    InternalLinkConfiguration,
    InternalLinkLifecycle,
    stable_json,
)
from musimack_tools.domain.link_audit import LINK_EVIDENCE_VERSION
from musimack_tools.domain.page_evidence import PAGE_EVIDENCE_VERSION
from musimack_tools.persistence.internal_link_models import (
    InternalLinkAnchorModel,
    InternalLinkAuditModel,
    InternalLinkEdgeModel,
    InternalLinkEventModel,
    InternalLinkExportModel,
    InternalLinkFindingModel,
    InternalLinkOpportunityModel,
    InternalLinkPageMetricModel,
    InternalLinkReachabilityModel,
)
from musimack_tools.persistence.link_audit_repository import SQLAlchemyLinkAuditRepository
from musimack_tools.persistence.sitemap_audit_models import (
    SitemapAuditComparisonModel,
    SitemapAuditModel,
)

_RUNNING = {
    InternalLinkLifecycle.CLAIMING.value,
    InternalLinkLifecycle.BUILDING_GRAPH.value,
    InternalLinkLifecycle.COMPUTING_METRICS.value,
    InternalLinkLifecycle.ANALYZING_REACHABILITY.value,
    InternalLinkLifecycle.ANALYZING_ANCHORS.value,
    InternalLinkLifecycle.BUILDING_OPPORTUNITIES.value,
}


class SQLAlchemyInternalLinkRepository:
    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self._evidence = SQLAlchemyLinkAuditRepository(runtime)

    def run_context(self, run_id: str) -> tuple[str, str, bool, int, int] | None:
        return self._evidence.run_context(run_id)

    def run_scope_snapshot(self, run_id: str) -> Any:
        return self._evidence.run_scope_snapshot(run_id)

    def source_links(self, run_id: str) -> tuple[dict[str, Any], ...]:
        return self._evidence.source_links(run_id)

    def pages(self, run_id: str) -> tuple[dict[str, Any], ...]:
        pages = [dict(page) for page in self._evidence.pages(run_id)]
        with self._runtime.transaction() as session:
            audit_id = session.scalar(
                select(SitemapAuditModel.audit_id)
                .where(
                    SitemapAuditModel.run_id == run_id,
                    SitemapAuditModel.state.in_(("completed", "completed_with_warnings")),
                )
                .order_by(
                    SitemapAuditModel.completed_at.desc(),
                    SitemapAuditModel.created_at.desc(),
                    SitemapAuditModel.audit_id.desc(),
                )
                .limit(1)
            )
            if audit_id is None:
                return tuple(pages)
            membership = {
                str(row.evidence_id): bool(row.in_sitemap)
                for row in session.scalars(
                    select(SitemapAuditComparisonModel).where(
                        SitemapAuditComparisonModel.audit_id == audit_id,
                        SitemapAuditComparisonModel.evidence_id.is_not(None),
                    )
                )
            }
        for page in pages:
            page["in_sitemap"] = membership.get(str(page.get("evidence_id")), False)
        return tuple(pages)

    def create(
        self,
        audit_id: str,
        job_id: str,
        run_id: str,
        seed_url: str,
        scope_snapshot: dict[str, Any],
        configuration: InternalLinkConfiguration,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            existing = session.get(InternalLinkAuditModel, audit_id)
            if existing is not None:
                return _dict(existing)
            row = InternalLinkAuditModel(
                audit_id=audit_id,
                job_id=job_id,
                run_id=run_id,
                seed_url=seed_url,
                scope_snapshot_json=stable_json(scope_snapshot),
                seed_snapshot_json=stable_json((seed_url,)),
                configuration_json=stable_json(configuration.snapshot()),
                state=InternalLinkLifecycle.ACCEPTED.value,
                failure_code=None,
                warning_count=0,
                node_count=0,
                eligible_page_count=0,
                edge_occurrence_count=0,
                unique_edge_count=0,
                reachable_count=0,
                orphan_candidate_count=0,
                deep_page_count=0,
                hub_candidate_count=0,
                authority_candidate_count=0,
                anchor_finding_count=0,
                opportunity_count=0,
                created_at=now,
                started_at=None,
                completed_at=None,
                retention_until=now + timedelta(days=configuration.retention_days),
                audit_version=INTERNAL_LINK_AUDIT_VERSION,
                graph_version=INTERNAL_LINK_GRAPH_VERSION,
                policy_version=INTERNAL_LINK_POLICY_VERSION,
                page_evidence_version=PAGE_EVIDENCE_VERSION,
                link_evidence_version=LINK_EVIDENCE_VERSION,
            )
            session.add(row)
            session.flush()
            session.add(_event(audit_id, 0, "created", None))
            return _dict(row)

    def claim_execution(self, audit_id: str) -> bool:
        with self._runtime.transaction() as session:
            result = session.execute(
                update(InternalLinkAuditModel)
                .where(
                    InternalLinkAuditModel.audit_id == audit_id,
                    InternalLinkAuditModel.state == InternalLinkLifecycle.ACCEPTED.value,
                )
                .values(
                    state=InternalLinkLifecycle.CLAIMING.value,
                    started_at=datetime.now(UTC),
                    failure_code=None,
                )
            )
            if result.rowcount != 1:
                return False
            session.add(_event(audit_id, 1, InternalLinkLifecycle.CLAIMING.value, None))
            return True

    def transition(
        self, audit_id: str, state: InternalLinkLifecycle, failure_code: str | None = None
    ) -> None:
        terminal = {
            InternalLinkLifecycle.COMPLETED,
            InternalLinkLifecycle.COMPLETED_WITH_WARNINGS,
            InternalLinkLifecycle.FAILED,
            InternalLinkLifecycle.CANCELLED,
        }
        with self._runtime.transaction() as session:
            row = _required(session.get(InternalLinkAuditModel, audit_id))
            row.state = state.value
            row.failure_code = failure_code
            if row.started_at is None:
                row.started_at = datetime.now(UTC)
            if state in terminal:
                row.completed_at = datetime.now(UTC)
            sequence = int(
                session.scalar(
                    select(func.count())
                    .select_from(InternalLinkEventModel)
                    .where(InternalLinkEventModel.audit_id == audit_id)
                )
                or 0
            )
            session.add(_event(audit_id, sequence, state.value, failure_code))

    def fail_if_running(self, audit_id: str, code: str) -> bool:
        with self._runtime.transaction() as session:
            row = session.get(InternalLinkAuditModel, audit_id)
            if row is None or row.state not in _RUNNING:
                return False
            row.state, row.failure_code, row.completed_at = "failed", code, datetime.now(UTC)
            sequence = int(
                session.scalar(
                    select(func.count())
                    .select_from(InternalLinkEventModel)
                    .where(InternalLinkEventModel.audit_id == audit_id)
                )
                or 0
            )
            session.add(_event(audit_id, sequence, "failed", code))
            return True

    def reconcile_interrupted(self) -> int:
        with self._runtime.transaction() as session:
            rows = tuple(
                session.scalars(
                    select(InternalLinkAuditModel).where(InternalLinkAuditModel.state.in_(_RUNNING))
                )
            )
            for row in rows:
                row.state = "failed"
                row.failure_code = "internal_link_audit_interrupted"
                row.completed_at = datetime.now(UTC)
                sequence = int(
                    session.scalar(
                        select(func.count())
                        .select_from(InternalLinkEventModel)
                        .where(InternalLinkEventModel.audit_id == row.audit_id)
                    )
                    or 0
                )
                session.add(_event(row.audit_id, sequence, "failed", row.failure_code))
            return len(rows)

    def persist_page(self, audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        return self._persist(InternalLinkPageMetricModel, audit_id, values)

    def persist_edge(self, audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        return self._persist(InternalLinkEdgeModel, audit_id, values)

    def persist_reachability(self, audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        return self._persist(InternalLinkReachabilityModel, audit_id, values)

    def persist_finding(self, audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        return self._persist(InternalLinkFindingModel, audit_id, values)

    def persist_anchor(self, audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        return self._persist(InternalLinkAnchorModel, audit_id, values)

    def persist_opportunity(self, audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        return self._persist(InternalLinkOpportunityModel, audit_id, values)

    def _persist(self, model: Any, audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = model(audit_id=audit_id, **values)
            session.add(row)
            session.flush()
            return _dict(row)

    def finalize(self, audit_id: str, warning_count: int = 0) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = _required(session.get(InternalLinkAuditModel, audit_id))
            metrics = tuple(
                session.scalars(
                    select(InternalLinkPageMetricModel).where(
                        InternalLinkPageMetricModel.audit_id == audit_id
                    )
                )
            )
            row.warning_count = warning_count
            row.node_count = len(metrics)
            row.eligible_page_count = sum(item.eligibility == "eligible" for item in metrics)
            row.edge_occurrence_count = int(
                session.scalar(
                    select(func.sum(InternalLinkEdgeModel.raw_occurrence_count)).where(
                        InternalLinkEdgeModel.audit_id == audit_id
                    )
                )
                or 0
            )
            row.unique_edge_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(InternalLinkEdgeModel)
                    .where(InternalLinkEdgeModel.audit_id == audit_id)
                )
                or 0
            )
            row.reachable_count = sum(item.reachable for item in metrics)
            row.orphan_candidate_count = sum(
                item.orphan_state in {"true_orphan_candidate", "sitemap_discovered_without_inlinks"}
                for item in metrics
            )
            row.deep_page_count = sum(item.primary_state == "deep_page" for item in metrics)
            row.hub_candidate_count = sum(item.hub_state == "candidate" for item in metrics)
            row.authority_candidate_count = sum(
                item.authority_state == "candidate" for item in metrics
            )
            row.anchor_finding_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(InternalLinkAnchorModel)
                    .where(
                        InternalLinkAnchorModel.audit_id == audit_id,
                        InternalLinkAnchorModel.anchor_state != "healthy",
                    )
                )
                or 0
            )
            row.opportunity_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(InternalLinkOpportunityModel)
                    .where(InternalLinkOpportunityModel.audit_id == audit_id)
                )
                or 0
            )
            row.state = (
                InternalLinkLifecycle.COMPLETED_WITH_WARNINGS
                if warning_count
                else InternalLinkLifecycle.COMPLETED
            ).value
            row.completed_at = datetime.now(UTC)
            sequence = int(
                session.scalar(
                    select(func.count())
                    .select_from(InternalLinkEventModel)
                    .where(InternalLinkEventModel.audit_id == audit_id)
                )
                or 0
            )
            session.add(_event(audit_id, sequence, row.state, None))
            session.flush()
            return _dict(row)

    def get(self, audit_id: str) -> dict[str, Any] | None:
        with self._runtime.transaction() as session:
            row = session.get(InternalLinkAuditModel, audit_id)
            return _dict(row) if row else None

    def list_audits(self, offset: int, limit: int) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(InternalLinkAuditModel)
                .order_by(
                    InternalLinkAuditModel.created_at.desc(), InternalLinkAuditModel.audit_id.desc()
                )
                .offset(offset)
                .limit(limit)
            )
            return tuple(_dict(row) for row in rows)

    def list_pages(
        self, audit_id: str, filters: dict[str, Any], offset: int, limit: int
    ) -> tuple[dict[str, Any], ...]:
        statement = select(InternalLinkPageMetricModel).where(
            InternalLinkPageMetricModel.audit_id == audit_id
        )
        mapping = {
            "eligibility": InternalLinkPageMetricModel.eligibility,
            "state": InternalLinkPageMetricModel.primary_state,
            "orphan": InternalLinkPageMetricModel.orphan_state,
            "hub": InternalLinkPageMetricModel.hub_state,
            "authority": InternalLinkPageMetricModel.authority_state,
            "severity": InternalLinkPageMetricModel.severity,
            "reachable": InternalLinkPageMetricModel.reachable,
        }
        for key, column in mapping.items():
            if filters.get(key) not in {None, ""}:
                selected = filters[key]
                statement = statement.where(
                    column.in_(selected) if isinstance(selected, tuple) else column == selected
                )
        if filters.get("q") or filters.get("url"):
            statement = statement.where(
                InternalLinkPageMetricModel.requested_url.contains(
                    str(filters.get("q") or filters["url"])
                )
            )
        for key, column, operation in (
            ("min_inlinks", InternalLinkPageMetricModel.inbound_occurrences, "min"),
            ("max_inlinks", InternalLinkPageMetricModel.inbound_occurrences, "max"),
            ("min_outlinks", InternalLinkPageMetricModel.outbound_occurrences, "min"),
            ("max_outlinks", InternalLinkPageMetricModel.outbound_occurrences, "max"),
            ("min_depth", InternalLinkPageMetricModel.graph_depth, "min"),
        ):
            if filters.get(key) is not None:
                statement = statement.where(
                    column >= filters[key] if operation == "min" else column <= filters[key]
                )
        return self._rows(
            statement.order_by(
                InternalLinkPageMetricModel.page_sequence, InternalLinkPageMetricModel.metric_id
            ),
            offset,
            limit,
        )

    def list_edges(
        self, audit_id: str, filters: dict[str, Any], offset: int, limit: int
    ) -> tuple[dict[str, Any], ...]:
        statement = select(InternalLinkEdgeModel).where(InternalLinkEdgeModel.audit_id == audit_id)
        if filters.get("source"):
            statement = statement.where(
                InternalLinkEdgeModel.source_url.contains(str(filters["source"]))
            )
        if filters.get("target"):
            statement = statement.where(
                InternalLinkEdgeModel.target_url.contains(str(filters["target"]))
            )
        if filters.get("url"):
            value = str(filters["url"])
            statement = statement.where(
                or_(
                    InternalLinkEdgeModel.source_url.contains(value),
                    InternalLinkEdgeModel.target_url.contains(value),
                )
            )
        for key, column in {
            "nofollow": InternalLinkEdgeModel.nofollow_occurrence_count,
            "sitewide": InternalLinkEdgeModel.sitewide,
            "state": InternalLinkEdgeModel.edge_state,
        }.items():
            filter_value = filters.get(key)
            if filter_value not in {None, ""}:
                statement = statement.where(
                    column > 0 if key == "nofollow" and filter_value else column == filter_value
                )
        if filters.get("redirect_adjusted") is not None:
            statement = statement.where(
                InternalLinkEdgeModel.redirect_adjusted_identity.is_not(None)
                if filters["redirect_adjusted"]
                else InternalLinkEdgeModel.redirect_adjusted_identity.is_(None)
            )
        if filters.get("canonical_adjusted") is not None:
            statement = statement.where(
                InternalLinkEdgeModel.canonical_adjusted_identity.is_not(None)
                if filters["canonical_adjusted"]
                else InternalLinkEdgeModel.canonical_adjusted_identity.is_(None)
            )
        return self._rows(
            statement.order_by(InternalLinkEdgeModel.edge_sequence, InternalLinkEdgeModel.edge_id),
            offset,
            limit,
        )

    def list_reachability(
        self, audit_id: str, offset: int, limit: int
    ) -> tuple[dict[str, Any], ...]:
        return self._model_rows(
            InternalLinkReachabilityModel,
            audit_id,
            InternalLinkReachabilityModel.sequence,
            offset,
            limit,
        )

    def list_findings(self, audit_id: str, offset: int, limit: int) -> tuple[dict[str, Any], ...]:
        return self._model_rows(
            InternalLinkFindingModel,
            audit_id,
            InternalLinkFindingModel.finding_sequence,
            offset,
            limit,
        )

    def list_anchors(
        self, audit_id: str, filters: dict[str, Any], offset: int, limit: int
    ) -> tuple[dict[str, Any], ...]:
        statement = select(InternalLinkAnchorModel).where(
            InternalLinkAnchorModel.audit_id == audit_id
        )
        if filters.get("state"):
            statement = statement.where(InternalLinkAnchorModel.anchor_state == filters["state"])
        if filters.get("severity"):
            statement = statement.where(InternalLinkAnchorModel.severity == filters["severity"])
        if filters.get("target") or filters.get("url"):
            statement = statement.where(
                InternalLinkAnchorModel.target_url.contains(
                    str(filters.get("target") or filters["url"])
                )
            )
        return self._rows(
            statement.order_by(
                InternalLinkAnchorModel.anchor_sequence, InternalLinkAnchorModel.anchor_id
            ),
            offset,
            limit,
        )

    def list_opportunities(
        self, audit_id: str, filters: dict[str, Any], offset: int, limit: int
    ) -> tuple[dict[str, Any], ...]:
        statement = select(InternalLinkOpportunityModel).where(
            InternalLinkOpportunityModel.audit_id == audit_id
        )
        mapping = {
            "type": InternalLinkOpportunityModel.opportunity_type,
            "action": InternalLinkOpportunityModel.action,
            "confidence": InternalLinkOpportunityModel.confidence,
            "severity": InternalLinkOpportunityModel.severity,
            "review": InternalLinkOpportunityModel.human_review_required,
        }
        for key, column in mapping.items():
            if filters.get(key) not in {None, ""}:
                statement = statement.where(column == filters[key])
        if filters.get("source"):
            statement = statement.where(
                InternalLinkOpportunityModel.source_url.contains(str(filters["source"]))
            )
        if filters.get("target"):
            statement = statement.where(
                InternalLinkOpportunityModel.target_url.contains(str(filters["target"]))
            )
        if filters.get("url"):
            value = str(filters["url"])
            statement = statement.where(
                or_(
                    InternalLinkOpportunityModel.source_url.contains(value),
                    InternalLinkOpportunityModel.target_url.contains(value),
                )
            )
        return self._rows(
            statement.order_by(
                InternalLinkOpportunityModel.opportunity_sequence,
                InternalLinkOpportunityModel.opportunity_id,
            ),
            offset,
            limit,
        )

    def upsert_export(
        self,
        audit_id: str,
        export_id: str,
        export_format: str,
        artifact_id: str,
        row_count: int,
        truncated: bool,
    ) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = session.scalar(
                select(InternalLinkExportModel).where(
                    InternalLinkExportModel.audit_id == audit_id,
                    InternalLinkExportModel.export_format == export_format,
                )
            )
            if row is None:
                row = InternalLinkExportModel(
                    export_id=export_id,
                    audit_id=audit_id,
                    export_format=export_format,
                    artifact_id=artifact_id,
                    state="completed",
                    row_count=row_count,
                    truncated=truncated,
                    created_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                    export_version=INTERNAL_LINK_EXPORT_VERSION,
                )
                session.add(row)
            else:
                row.artifact_id, row.row_count, row.truncated, row.state, row.completed_at = (
                    artifact_id,
                    row_count,
                    truncated,
                    "completed",
                    datetime.now(UTC),
                )
            session.flush()
            return _dict(row)

    def list_exports(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        return self._model_rows(
            InternalLinkExportModel, audit_id, InternalLinkExportModel.created_at, 0, 100
        )

    def cleanup(self, now: datetime | None = None) -> int:
        with self._runtime.transaction() as session:
            result = session.execute(
                delete(InternalLinkAuditModel).where(
                    InternalLinkAuditModel.retention_until < (now or datetime.now(UTC))
                )
            )
            return int(result.rowcount or 0)

    def diagnostics(self) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            return {
                "persistence_ready": True,
                "migration_ready": True,
                "audit_count": int(
                    session.scalar(select(func.count()).select_from(InternalLinkAuditModel)) or 0
                ),
                "interrupted_count": int(
                    session.scalar(
                        select(func.count())
                        .select_from(InternalLinkAuditModel)
                        .where(InternalLinkAuditModel.state.in_(_RUNNING))
                    )
                    or 0
                ),
            }

    def _model_rows(
        self, model: Any, audit_id: str, order: Any, offset: int, limit: int
    ) -> tuple[dict[str, Any], ...]:
        return self._rows(
            select(model)
            .where(model.audit_id == audit_id)
            .order_by(order)
            .offset(offset)
            .limit(limit),
            0,
            limit,
            already_paged=True,
        )

    def _rows(
        self, statement: Any, offset: int, limit: int, *, already_paged: bool = False
    ) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            query = statement if already_paged else statement.offset(offset).limit(limit)
            return tuple(_dict(row) for row in session.scalars(query))


def _dict(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _required(value: Any) -> Any:
    if value is None:
        raise ValueError("internal_link_audit_not_found")
    return value


def _event(
    audit_id: str, sequence: int, event_type: str, code: str | None
) -> InternalLinkEventModel:
    return InternalLinkEventModel(
        audit_id=audit_id,
        sequence=sequence,
        event_type=event_type,
        safe_code=code,
        counts_json="{}",
        created_at=datetime.now(UTC),
    )
