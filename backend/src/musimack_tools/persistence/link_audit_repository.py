"""Short-transaction persistence and bounded queries for link audits."""

# ruff: noqa: ANN401, FBT001

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update

from musimack_tools.domain.link_audit import (
    LINK_ANALYSIS_POLICY_VERSION,
    LINK_AUDIT_EXPORT_VERSION,
    LINK_AUDIT_VERSION,
    LINK_EVIDENCE_VERSION,
    REDIRECT_ANALYSIS_POLICY_VERSION,
    LinkAuditConfiguration,
    LinkAuditLifecycle,
    stable_identity,
    stable_json,
)
from musimack_tools.domain.page_evidence import PAGE_EVIDENCE_VERSION
from musimack_tools.domain.urls import ScopeMode
from musimack_tools.persistence.link_audit_models import (
    CrawlLinkEvidenceModel,
    LinkAuditChainModel,
    LinkAuditEventModel,
    LinkAuditExportModel,
    LinkAuditFindingModel,
    LinkAuditModel,
    LinkAuditRecommendationModel,
    LinkAuditTargetModel,
)
from musimack_tools.persistence.models import (
    ConfigurationSnapshotModel,
    CrawlPageEvidenceModel,
    CrawlPageRedirectHopModel,
    JobModel,
    RunModel,
)


class SQLAlchemyLinkAuditRepository:
    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def run_context(self, run_id: str) -> tuple[str, str, bool, int, int] | None:
        with self._runtime.transaction() as session:
            row = session.execute(
                select(RunModel, JobModel)
                .join(JobModel, JobModel.run_id == RunModel.run_id)
                .where(RunModel.run_id == run_id)
                .order_by(JobModel.attempt_number.desc())
                .limit(1)
            ).first()
            if row is None:
                return None
            run, job = row
            pages = int(
                session.scalar(
                    select(func.count())
                    .select_from(CrawlPageEvidenceModel)
                    .where(CrawlPageEvidenceModel.run_id == run_id)
                )
                or 0
            )
            links = int(
                session.scalar(
                    select(func.count())
                    .select_from(CrawlLinkEvidenceModel)
                    .where(CrawlLinkEvidenceModel.run_id == run_id)
                )
                or 0
            )
            terminal = run.lifecycle in {
                "completed",
                "completed_with_warnings",
                "partially_completed",
                "failed",
                "cancelled",
            }
            return job.job_id, run.normalized_seed_url, terminal, pages, links

    def run_scope_snapshot(self, run_id: str) -> tuple[ScopeMode, tuple[str, ...]] | None:
        with self._runtime.transaction() as session:
            canonical = session.scalar(
                select(ConfigurationSnapshotModel.canonical_json)
                .join(
                    RunModel,
                    RunModel.configuration_snapshot_id == ConfigurationSnapshotModel.snapshot_id,
                )
                .where(RunModel.run_id == run_id)
            )
            if canonical is None:
                return None
            try:
                payload = json.loads(canonical)
                return ScopeMode(payload["scope_mode"]), tuple(
                    str(item) for item in payload["approved_hosts"]
                )
            except KeyError, TypeError, ValueError, json.JSONDecodeError:
                return None

    def create(
        self,
        audit_id: str,
        job_id: str,
        run_id: str,
        seed_url: str,
        configuration: LinkAuditConfiguration,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            existing = session.get(LinkAuditModel, audit_id)
            if existing is not None:
                return _dict(existing)
            row = LinkAuditModel(
                audit_id=audit_id,
                job_id=job_id,
                run_id=run_id,
                seed_url=seed_url,
                configuration_json=stable_json(configuration.snapshot()),
                state=LinkAuditLifecycle.ACCEPTED.value,
                failure_code=None,
                warning_count=0,
                link_occurrence_count=0,
                source_target_pair_count=0,
                target_count=0,
                working_target_count=0,
                broken_target_count=0,
                redirect_target_count=0,
                unverified_target_count=0,
                redirect_chain_count=0,
                redirect_loop_count=0,
                recommendation_count=0,
                created_at=now,
                started_at=None,
                completed_at=None,
                retention_until=now + timedelta(days=configuration.retention_days),
                audit_version=LINK_AUDIT_VERSION,
                link_evidence_version=LINK_EVIDENCE_VERSION,
                page_evidence_version="seo-toolkit-page-crawl-evidence-v1",
                link_policy_version=LINK_ANALYSIS_POLICY_VERSION,
                redirect_policy_version=REDIRECT_ANALYSIS_POLICY_VERSION,
            )
            session.add(row)
            session.flush()
            session.add(_event(audit_id, 0, "created", None))
            return _dict(row)

    def claim_execution(self, audit_id: str) -> bool:
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            result = session.execute(
                update(LinkAuditModel)
                .where(
                    LinkAuditModel.audit_id == audit_id,
                    LinkAuditModel.state == LinkAuditLifecycle.ACCEPTED.value,
                )
                .values(state=LinkAuditLifecycle.CLAIMING.value, started_at=now, failure_code=None)
            )
            if result.rowcount != 1:
                return False
            session.add(_event(audit_id, 1, LinkAuditLifecycle.CLAIMING.value, None))
            return True

    def transition(
        self, audit_id: str, state: LinkAuditLifecycle, failure_code: str | None = None
    ) -> None:
        terminal = {
            LinkAuditLifecycle.COMPLETED,
            LinkAuditLifecycle.COMPLETED_WITH_WARNINGS,
            LinkAuditLifecycle.FAILED,
            LinkAuditLifecycle.CANCELLED,
        }
        with self._runtime.transaction() as session:
            row = _required(session.get(LinkAuditModel, audit_id))
            row.state = state.value
            row.failure_code = failure_code
            if row.started_at is None and state is not LinkAuditLifecycle.ACCEPTED:
                row.started_at = datetime.now(UTC)
            if state in terminal:
                row.completed_at = datetime.now(UTC)
            sequence = int(
                session.scalar(
                    select(func.count())
                    .select_from(LinkAuditEventModel)
                    .where(LinkAuditEventModel.audit_id == audit_id)
                )
                or 0
            )
            session.add(_event(audit_id, sequence, state.value, failure_code))

    def fail_if_running(self, audit_id: str, failure_code: str) -> bool:
        with self._runtime.transaction() as session:
            row = session.get(LinkAuditModel, audit_id)
            if row is None or row.state not in _RUNNING:
                return False
            row.state = LinkAuditLifecycle.FAILED.value
            row.failure_code = failure_code
            row.completed_at = datetime.now(UTC)
            sequence = int(
                session.scalar(
                    select(func.count())
                    .select_from(LinkAuditEventModel)
                    .where(LinkAuditEventModel.audit_id == audit_id)
                )
                or 0
            )
            session.add(_event(audit_id, sequence, "failed", failure_code))
            return True

    def reconcile_interrupted(self) -> int:
        with self._runtime.transaction() as session:
            rows = tuple(
                session.scalars(select(LinkAuditModel).where(LinkAuditModel.state.in_(_RUNNING)))
            )
            now = datetime.now(UTC)
            for row in rows:
                row.state = LinkAuditLifecycle.FAILED.value
                row.failure_code = "link_audit_interrupted"
                row.completed_at = now
                sequence = int(
                    session.scalar(
                        select(func.count())
                        .select_from(LinkAuditEventModel)
                        .where(LinkAuditEventModel.audit_id == row.audit_id)
                    )
                    or 0
                )
                session.add(_event(row.audit_id, sequence, "failed", "link_audit_interrupted"))
            return len(rows)

    def source_links(self, run_id: str) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            rows = tuple(
                session.scalars(
                    select(CrawlLinkEvidenceModel)
                    .where(CrawlLinkEvidenceModel.run_id == run_id)
                    .order_by(
                        CrawlLinkEvidenceModel.discovery_sequence,
                        CrawlLinkEvidenceModel.link_id,
                    )
                )
            )
            if any(row.evidence_version != LINK_EVIDENCE_VERSION for row in rows):
                raise ValueError("link_audit_version_unsupported")
            return tuple(_dict(row) for row in rows)

    def pages(self, run_id: str) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            result: list[dict[str, Any]] = []
            rows = tuple(
                session.scalars(
                    select(CrawlPageEvidenceModel)
                    .where(CrawlPageEvidenceModel.run_id == run_id)
                    .order_by(CrawlPageEvidenceModel.discovery_sequence)
                )
            )
            if any(row.evidence_version != PAGE_EVIDENCE_VERSION for row in rows):
                raise ValueError("link_audit_version_unsupported")
            for row in rows:
                value = _dict(row)
                value["redirects"] = tuple(
                    _dict(item)
                    for item in session.scalars(
                        select(CrawlPageRedirectHopModel)
                        .where(CrawlPageRedirectHopModel.evidence_id == row.evidence_id)
                        .order_by(CrawlPageRedirectHopModel.sequence)
                    )
                )
                result.append(value)
            return tuple(result)

    def persist_target(self, audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = LinkAuditTargetModel(audit_id=audit_id, **values)
            session.add(row)
            session.flush()
            return _dict(row)

    def persist_chain(self, audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = LinkAuditChainModel(audit_id=audit_id, **values)
            session.add(row)
            session.flush()
            return _dict(row)

    def persist_finding(self, audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = LinkAuditFindingModel(audit_id=audit_id, **values)
            session.add(row)
            session.flush()
            return _dict(row)

    def persist_recommendation(self, audit_id: str, values: dict[str, Any]) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = LinkAuditRecommendationModel(audit_id=audit_id, **values)
            session.add(row)
            session.flush()
            return _dict(row)

    def finalize(self, audit_id: str, *, warning_count: int = 0) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = _required(session.get(LinkAuditModel, audit_id))
            targets = tuple(
                session.scalars(
                    select(LinkAuditTargetModel).where(LinkAuditTargetModel.audit_id == audit_id)
                )
            )
            row.warning_count = warning_count
            row.link_occurrence_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(CrawlLinkEvidenceModel)
                    .where(CrawlLinkEvidenceModel.run_id == row.run_id)
                )
                or 0
            )
            row.source_target_pair_count = len(
                {
                    (item.source_evidence_id, item.target_url_identity or item.link_id)
                    for item in session.scalars(
                        select(CrawlLinkEvidenceModel).where(
                            CrawlLinkEvidenceModel.run_id == row.run_id
                        )
                    )
                }
            )
            row.target_count = len(targets)
            row.working_target_count = sum(
                item.broken_state == "working_internal_link" for item in targets
            )
            row.broken_target_count = sum(
                item.broken_state == "broken_internal_link" for item in targets
            )
            row.redirect_target_count = sum(
                item.redirect_state != "no_redirect" for item in targets
            )
            row.unverified_target_count = sum(
                item.broken_state == "unverified_internal_link" for item in targets
            )
            row.redirect_chain_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(LinkAuditChainModel)
                    .where(LinkAuditChainModel.audit_id == audit_id)
                )
                or 0
            )
            row.redirect_loop_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(LinkAuditChainModel)
                    .where(
                        LinkAuditChainModel.audit_id == audit_id, LinkAuditChainModel.loop.is_(True)
                    )
                )
                or 0
            )
            row.recommendation_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(LinkAuditRecommendationModel)
                    .where(LinkAuditRecommendationModel.audit_id == audit_id)
                )
                or 0
            )
            row.state = (
                LinkAuditLifecycle.COMPLETED_WITH_WARNINGS.value
                if warning_count
                else LinkAuditLifecycle.COMPLETED.value
            )
            row.completed_at = datetime.now(UTC)
            sequence = int(
                session.scalar(
                    select(func.count())
                    .select_from(LinkAuditEventModel)
                    .where(LinkAuditEventModel.audit_id == audit_id)
                )
                or 0
            )
            session.add(_event(audit_id, sequence, row.state, None, {"targets": len(targets)}))
            session.flush()
            return _dict(row)

    def get(self, audit_id: str) -> dict[str, Any] | None:
        with self._runtime.transaction() as session:
            row = session.get(LinkAuditModel, audit_id)
            return _dict(row) if row is not None else None

    def list_audits(self, offset: int, limit: int) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(LinkAuditModel)
                .order_by(LinkAuditModel.created_at.desc(), LinkAuditModel.audit_id.desc())
                .offset(offset)
                .limit(limit)
            )
            return tuple(_dict(row) for row in rows)

    def list_targets(
        self, audit_id: str, offset: int, limit: int, filters: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], ...]:
        statement = select(LinkAuditTargetModel).where(LinkAuditTargetModel.audit_id == audit_id)
        selected = filters or {}
        columns = {
            "broken_state": LinkAuditTargetModel.broken_state,
            "redirect_state": LinkAuditTargetModel.redirect_state,
            "severity": LinkAuditTargetModel.severity,
            "action": LinkAuditTargetModel.action,
            "reason": LinkAuditTargetModel.primary_reason,
            "http_status": LinkAuditTargetModel.http_status,
            "content_type": LinkAuditTargetModel.content_type,
            "in_scope": LinkAuditTargetModel.in_scope,
            "sitewide": LinkAuditTargetModel.sitewide_candidate,
        }
        for key, column in columns.items():
            if key in selected:
                statement = statement.where(column == selected[key])
        if "minimum_sources" in selected:
            statement = statement.where(
                LinkAuditTargetModel.unique_source_page_count >= int(selected["minimum_sources"])
            )
        if "status_class" in selected:
            lower = int(selected["status_class"]) * 100
            statement = statement.where(
                LinkAuditTargetModel.http_status >= lower,
                LinkAuditTargetModel.http_status < lower + 100,
            )
        if "url" in selected:
            statement = statement.where(
                LinkAuditTargetModel.target_url.contains(str(selected["url"]), autoescape=True)
            )
        return self._rows(statement.order_by(LinkAuditTargetModel.target_sequence), offset, limit)

    def list_occurrences(
        self, audit_id: str, offset: int, limit: int, filters: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            audit = _required(session.get(LinkAuditModel, audit_id))
            statement = (
                select(CrawlLinkEvidenceModel, CrawlPageEvidenceModel)
                .join(
                    CrawlPageEvidenceModel,
                    CrawlPageEvidenceModel.evidence_id == CrawlLinkEvidenceModel.source_evidence_id,
                )
                .where(CrawlLinkEvidenceModel.run_id == audit.run_id)
            )
            selected = filters or {}
            if "source" in selected:
                statement = statement.where(
                    CrawlLinkEvidenceModel.source_requested_url.contains(
                        str(selected["source"]), autoescape=True
                    )
                )
            if "target" in selected:
                statement = statement.where(
                    CrawlLinkEvidenceModel.resolved_url.contains(
                        str(selected["target"]), autoescape=True
                    )
                )
            if "anchor" in selected:
                statement = statement.where(
                    CrawlLinkEvidenceModel.anchor_text.contains(
                        str(selected["anchor"]), autoescape=True
                    )
                )
            if "source_page" in selected:
                statement = statement.where(
                    CrawlLinkEvidenceModel.source_evidence_id == selected["source_page"]
                )
            if "target_state" in selected:
                statement = statement.join(
                    LinkAuditTargetModel,
                    (LinkAuditTargetModel.audit_id == audit_id)
                    & (
                        LinkAuditTargetModel.target_url_identity
                        == CrawlLinkEvidenceModel.target_url_identity
                    ),
                ).where(LinkAuditTargetModel.broken_state == selected["target_state"])
            if "internal" in selected:
                statement = statement.where(
                    CrawlLinkEvidenceModel.internal == bool(selected["internal"])
                )
            if "nofollow" in selected:
                statement = statement.where(
                    CrawlLinkEvidenceModel.nofollow == bool(selected["nofollow"])
                )
            rows = session.execute(
                statement.order_by(CrawlLinkEvidenceModel.discovery_sequence)
                .offset(offset)
                .limit(limit)
            )
            values: list[dict[str, Any]] = []
            for link, source in rows:
                value = _dict(link)
                value.update(
                    source_status=source.http_status,
                    source_indexability=source.indexability_state,
                )
                values.append(value)
            return tuple(values)

    def list_chains(
        self, audit_id: str, offset: int, limit: int, filters: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], ...]:
        statement = (
            select(LinkAuditChainModel, LinkAuditTargetModel)
            .join(
                LinkAuditTargetModel,
                LinkAuditTargetModel.target_id == LinkAuditChainModel.target_id,
            )
            .where(LinkAuditChainModel.audit_id == audit_id)
        )
        selected = filters or {}
        if "loop" in selected:
            statement = statement.where(LinkAuditChainModel.loop == bool(selected["loop"]))
        if "severity" in selected:
            statement = statement.where(LinkAuditChainModel.severity == selected["severity"])
        if "minimum_hops" in selected:
            statement = statement.where(
                LinkAuditChainModel.hop_count >= int(selected["minimum_hops"])
            )
        if "final_status" in selected:
            statement = statement.where(
                LinkAuditTargetModel.http_status == selected["final_status"]
            )
        if "entry" in selected:
            statement = statement.where(
                LinkAuditChainModel.entry_url.contains(str(selected["entry"]), autoescape=True)
            )
        if "destination" in selected:
            statement = statement.where(
                LinkAuditChainModel.final_url.contains(
                    str(selected["destination"]), autoescape=True
                )
            )
        with self._runtime.transaction() as session:
            rows = session.execute(
                statement.order_by(LinkAuditChainModel.chain_sequence).offset(offset).limit(limit)
            )
            values: list[dict[str, Any]] = []
            for chain, target in rows:
                value = _dict(chain)
                value["final_status"] = target.http_status
                values.append(value)
            return tuple(values)

    def list_findings(
        self, audit_id: str, offset: int, limit: int, filters: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], ...]:
        statement = select(LinkAuditFindingModel).where(LinkAuditFindingModel.audit_id == audit_id)
        selected = filters or {}
        if "severity" in selected:
            statement = statement.where(LinkAuditFindingModel.severity == selected["severity"])
        if "code" in selected:
            statement = statement.where(LinkAuditFindingModel.stable_code == selected["code"])
        return self._rows(statement.order_by(LinkAuditFindingModel.finding_sequence), offset, limit)

    def list_recommendations(
        self, audit_id: str, offset: int, limit: int, filters: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], ...]:
        statement = select(LinkAuditRecommendationModel).where(
            LinkAuditRecommendationModel.audit_id == audit_id
        )
        selected = filters or {}
        for key, column in {
            "action": LinkAuditRecommendationModel.action,
            "confidence": LinkAuditRecommendationModel.confidence,
            "severity": LinkAuditRecommendationModel.severity,
            "human_review": LinkAuditRecommendationModel.human_review_required,
        }.items():
            if key in selected:
                statement = statement.where(column == selected[key])
        if "source" in selected:
            statement = statement.where(
                LinkAuditRecommendationModel.source_url.contains(
                    str(selected["source"]), autoescape=True
                )
            )
        if "destination" in selected:
            statement = statement.where(
                LinkAuditRecommendationModel.suggested_destination.contains(
                    str(selected["destination"]), autoescape=True
                )
            )
        return self._rows(
            statement.order_by(LinkAuditRecommendationModel.recommendation_sequence), offset, limit
        )

    def upsert_export(
        self, audit_id: str, export_format: str, artifact_id: str, row_count: int, truncated: bool
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        export_id = stable_identity(audit_id, export_format)
        with self._runtime.transaction() as session:
            row = session.get(LinkAuditExportModel, export_id)
            if row is None:
                row = LinkAuditExportModel(
                    export_id=export_id,
                    audit_id=audit_id,
                    export_format=export_format,
                    artifact_id=artifact_id,
                    state="available",
                    row_count=row_count,
                    truncated=truncated,
                    created_at=now,
                    completed_at=now,
                    export_version=LINK_AUDIT_EXPORT_VERSION,
                )
                session.add(row)
            else:
                row.artifact_id = artifact_id
                row.state = "available"
                row.row_count = row_count
                row.truncated = truncated
                row.completed_at = now
            session.flush()
            return _dict(row)

    def list_exports(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(LinkAuditExportModel)
                .where(LinkAuditExportModel.audit_id == audit_id)
                .order_by(LinkAuditExportModel.created_at, LinkAuditExportModel.export_id)
            )
            return tuple(_dict(row) for row in rows)

    def cleanup(self, *, now: datetime | None = None) -> int:
        current = now or datetime.now(UTC)
        with self._runtime.transaction() as session:
            result = session.execute(
                delete(LinkAuditModel).where(LinkAuditModel.retention_until <= current)
            )
            return int(result.rowcount or 0)

    def diagnostics(self) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            return {
                "persistence_ready": True,
                "migration_ready": True,
                "audit_count": int(
                    session.scalar(select(func.count()).select_from(LinkAuditModel)) or 0
                ),
                "interrupted_count": int(
                    session.scalar(
                        select(func.count())
                        .select_from(LinkAuditModel)
                        .where(LinkAuditModel.state.in_(_RUNNING))
                    )
                    or 0
                ),
            }

    def _rows(self, statement: Any, offset: int, limit: int) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            rows = session.scalars(statement.offset(offset).limit(limit))
            return tuple(_dict(row) for row in rows)


_RUNNING = {
    LinkAuditLifecycle.CLAIMING.value,
    LinkAuditLifecycle.BUILDING_GRAPH.value,
    LinkAuditLifecycle.CLASSIFYING_LINKS.value,
    LinkAuditLifecycle.EXPANDING_REDIRECTS.value,
    LinkAuditLifecycle.DETECTING_LOOPS.value,
    LinkAuditLifecycle.BUILDING_RECOMMENDATIONS.value,
}


def _event(
    audit_id: str,
    sequence: int,
    event_type: str,
    safe_code: str | None,
    counts: dict[str, int] | None = None,
) -> LinkAuditEventModel:
    return LinkAuditEventModel(
        audit_id=audit_id,
        sequence=sequence,
        event_type=event_type,
        safe_code=safe_code,
        counts_json=stable_json(counts or {}),
        created_at=datetime.now(UTC),
    )


def _dict(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _required(value: Any) -> Any:
    if value is None:
        raise ValueError("link_audit_not_found")
    return value
