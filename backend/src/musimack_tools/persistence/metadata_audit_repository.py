"""Restart-safe metadata-audit persistence and bounded query repository."""

# ruff: noqa: ANN401, FBT001 - injected runtime and SQLAlchemy model guards are explicit.

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import and_, case, func, select

from musimack_tools.domain.metadata_audit import (
    METADATA_AUDIT_PERSISTENCE_VERSION,
    METADATA_AUDIT_VERSION,
    METADATA_DUPLICATE_NORMALIZATION_VERSION,
    METADATA_ISSUE_TAXONOMY_VERSION,
    METADATA_SEVERITY_VERSION,
    AuditIssue,
    AuditPage,
    AuditState,
    DuplicateGroup,
    DuplicateType,
    MetadataAudit,
    MetadataAuditConfiguration,
    Severity,
    audit_page_identity,
    severity_max,
)
from musimack_tools.domain.page_evidence import (
    ContentTypeCategory,
    IndexabilityEvidenceState,
    MetadataPresence,
    PageEvidenceRecord,
    PageEvidenceState,
)
from musimack_tools.persistence.models import (
    CrawlPageEvidenceModel,
    CrawlPageEvidenceSummaryModel,
    CrawlPageRedirectHopModel,
    JobModel,
    MetadataAuditEventModel,
    MetadataAuditExportModel,
    MetadataAuditIssueModel,
    MetadataAuditModel,
    MetadataAuditPageModel,
    MetadataAuditSummaryModel,
    MetadataDuplicateGroupMemberModel,
    MetadataDuplicateGroupModel,
    RunModel,
)


class SQLAlchemyMetadataAuditRepository:
    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def run_context(self, run_id: str) -> tuple[str, str, bool, int] | None:
        with self._runtime.transaction() as session:
            row = session.execute(
                select(RunModel, JobModel, CrawlPageEvidenceSummaryModel)
                .join(JobModel, JobModel.run_id == RunModel.run_id)
                .outerjoin(
                    CrawlPageEvidenceSummaryModel,
                    CrawlPageEvidenceSummaryModel.run_id == RunModel.run_id,
                )
                .where(RunModel.run_id == run_id)
                .order_by(JobModel.attempt_number.desc())
                .limit(1)
            ).first()
            if row is None:
                return None
            run, job, summary = row
            terminal = run.lifecycle in {
                "completed",
                "completed_with_warnings",
                "partially_completed",
                "failed",
                "cancelled",
            }
            return (
                job.job_id,
                run.normalized_seed_url,
                terminal,
                summary.total_records if summary else 0,
            )

    def create(
        self,
        audit_id: str,
        job_id: str,
        run_id: str,
        seed: str,
        configuration: MetadataAuditConfiguration,
    ) -> MetadataAudit:
        canonical = configuration.canonical_json()
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            existing = session.get(MetadataAuditModel, audit_id)
            if existing is not None:
                if existing.configuration_hash != digest:
                    raise ValueError("metadata_audit_conflict")
                return _audit(existing)
            row = MetadataAuditModel(
                audit_id=audit_id,
                job_id=job_id,
                run_id=run_id,
                seed_url=seed,
                state=AuditState.PLANNED.value,
                configuration_json=canonical,
                configuration_hash=digest,
                audit_version=METADATA_AUDIT_VERSION,
                taxonomy_version=METADATA_ISSUE_TAXONOMY_VERSION,
                severity_version=METADATA_SEVERITY_VERSION,
                duplicate_version=METADATA_DUPLICATE_NORMALIZATION_VERSION,
                created_at=now,
                started_at=None,
                completed_at=None,
                page_count=0,
                issue_count=0,
                partial=False,
                failure_code=None,
                export_available=False,
            )
            session.add(row)
            session.flush()
            session.add(_event(audit_id, "created", 0, now))
            return _audit(row)

    def mark_running(self, audit_id: str) -> None:
        with self._runtime.transaction() as session:
            row = _required(session.get(MetadataAuditModel, audit_id))
            if row.state not in {AuditState.PLANNED.value, AuditState.RUNNING.value}:
                raise ValueError("metadata_audit_invalid_transition")
            row.state = AuditState.RUNNING.value
            row.started_at = row.started_at or datetime.now(UTC)
            session.add(_event(audit_id, "started", 0, row.started_at))

    def evidence_batch(
        self, run_id: str, offset: int, limit: int
    ) -> tuple[PageEvidenceRecord, ...]:
        with self._runtime.transaction() as session:
            rows = tuple(
                session.scalars(
                    select(CrawlPageEvidenceModel)
                    .where(CrawlPageEvidenceModel.run_id == run_id)
                    .order_by(
                        CrawlPageEvidenceModel.discovery_sequence,
                        CrawlPageEvidenceModel.requested_url_identity,
                    )
                    .offset(offset)
                    .limit(limit)
                )
            )
            result = []
            for row in rows:
                hops = tuple(
                    session.scalars(
                        select(CrawlPageRedirectHopModel)
                        .where(CrawlPageRedirectHopModel.evidence_id == row.evidence_id)
                        .order_by(CrawlPageRedirectHopModel.sequence)
                    )
                )
                result.append(_evidence(row, hops))
            return tuple(result)

    def canonical_targets(self, run_id: str) -> dict[str, tuple[int | None, int]]:
        with self._runtime.transaction() as session:
            rows = session.execute(
                select(
                    CrawlPageEvidenceModel.requested_url_identity,
                    CrawlPageEvidenceModel.http_status,
                    CrawlPageEvidenceModel.redirect_count,
                ).where(CrawlPageEvidenceModel.run_id == run_id)
            ).all()
            return {identity: (status, redirects) for identity, status, redirects in rows}

    def persist_page(
        self, audit_id: str, evidence: PageEvidenceRecord, issues: tuple[AuditIssue, ...]
    ) -> AuditPage:
        now = datetime.now(UTC)
        page_id = audit_page_identity(audit_id, evidence.evidence_id)
        highest = severity_max(issues)
        partial = (
            evidence.evidence_state
            in {
                PageEvidenceState.PARTIAL,
                PageEvidenceState.CANCELLED,
                PageEvidenceState.TRUNCATED,
                PageEvidenceState.UNAVAILABLE,
            }
            or evidence.value_truncated
        )
        with self._runtime.transaction() as session:
            row = session.get(MetadataAuditPageModel, page_id)
            if row is None:
                row = MetadataAuditPageModel(
                    audit_page_id=page_id,
                    audit_id=audit_id,
                    evidence_id=evidence.evidence_id,
                    url=evidence.requested_url,
                    url_identity=evidence.requested_url_identity,
                    final_url=evidence.final_url,
                    fetch_outcome=evidence.fetch_outcome,
                    http_status=evidence.http_status,
                    content_type=evidence.content_type,
                    content_type_category=evidence.content_type_category.value,
                    title_value=evidence.title_value,
                    title_presence=evidence.title_presence.value,
                    title_count=evidence.title_count,
                    title_length=evidence.title_length,
                    description_value=evidence.description_value,
                    description_presence=evidence.description_presence.value,
                    description_count=evidence.description_count,
                    description_length=evidence.description_length,
                    canonical_value=evidence.canonical_url,
                    canonical_state=evidence.canonical_presence.value,
                    robots_allowed=evidence.robots_allowed,
                    indexability_state=evidence.indexability_state.value,
                    recommendation_state=None,
                    issue_count=len(issues),
                    highest_severity=highest.value if highest else None,
                    partial=partial,
                    audit_page_version=METADATA_AUDIT_VERSION,
                )
                session.add(row)
                session.flush()
                for issue in issues:
                    session.add(
                        MetadataAuditIssueModel(
                            issue_id=issue.issue_id,
                            audit_id=audit_id,
                            audit_page_id=page_id,
                            code=issue.code,
                            category=issue.category.value,
                            severity=issue.severity.value,
                            safe_summary=issue.summary,
                            safe_detail=issue.detail,
                            determinacy=issue.determinacy.value,
                            evidence_json=issue.evidence_json,
                            duplicate_group_id=issue.duplicate_group_id,
                            created_at=now,
                            taxonomy_version=METADATA_ISSUE_TAXONOMY_VERSION,
                            severity_version=METADATA_SEVERITY_VERSION,
                        )
                    )
            return _page(row)

    def duplicate_candidates(
        self, audit_id: str, kind: DuplicateType
    ) -> tuple[tuple[str, str, str], ...]:
        value = (
            MetadataAuditPageModel.title_value
            if kind is DuplicateType.TITLE
            else MetadataAuditPageModel.description_value
        )
        presence = (
            MetadataAuditPageModel.title_presence
            if kind is DuplicateType.TITLE
            else MetadataAuditPageModel.description_presence
        )
        with self._runtime.transaction() as session:
            return tuple(
                session.execute(
                    select(
                        MetadataAuditPageModel.audit_page_id,
                        MetadataAuditPageModel.url_identity,
                        value,
                    )
                    .where(
                        MetadataAuditPageModel.audit_id == audit_id,
                        value.is_not(None),
                        presence.in_(("single", "multiple")),
                    )
                    .order_by(MetadataAuditPageModel.url_identity)
                ).all()
            )

    def persist_duplicate_group(
        self, group: DuplicateGroup, member_ids: tuple[tuple[str, str], ...], issue_code: str
    ) -> None:
        with self._runtime.transaction() as session:
            if session.get(MetadataDuplicateGroupModel, group.group_id) is not None:
                return
            session.add(
                MetadataDuplicateGroupModel(
                    group_id=group.group_id,
                    audit_id=group.audit_id,
                    duplicate_type=group.duplicate_type.value,
                    normalized_value_hash=group.normalized_value_hash,
                    sample_value=group.sample_value,
                    member_count=group.member_count,
                    sample_members_json=json.dumps(group.sample_members),
                    created_at=group.created_at,
                    version=METADATA_DUPLICATE_NORMALIZATION_VERSION,
                )
            )
            session.flush()
            for page_id, identity in member_ids:
                session.add(
                    MetadataDuplicateGroupMemberModel(
                        group_id=group.group_id, audit_page_id=page_id, url_identity=identity
                    )
                )
                page = _required(session.get(MetadataAuditPageModel, page_id))
                issue_id = (
                    "issue-"
                    + hashlib.sha256(
                        f"{group.audit_id}\0{page_id}\0{issue_code}".encode()
                    ).hexdigest()[:32]
                )
                session.add(
                    MetadataAuditIssueModel(
                        issue_id=issue_id,
                        audit_id=group.audit_id,
                        audit_page_id=page_id,
                        code=issue_code,
                        category=(
                            "title"
                            if group.duplicate_type is DuplicateType.TITLE
                            else "meta_description"
                        ),
                        severity="medium",
                        safe_summary=issue_code.replace("_", " ").capitalize(),
                        safe_detail="Deterministic duplicate metadata group membership.",
                        determinacy="determinate",
                        evidence_json="{}",
                        duplicate_group_id=group.group_id,
                        created_at=group.created_at,
                        taxonomy_version=METADATA_ISSUE_TAXONOMY_VERSION,
                        severity_version=METADATA_SEVERITY_VERSION,
                    )
                )
                page.issue_count += 1
                if page.highest_severity is None or page.highest_severity in {"low", "information"}:
                    page.highest_severity = "medium"

    def finish(self, audit_id: str, summary: dict[str, Any], partial: bool) -> MetadataAudit:
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            row = _required(session.get(MetadataAuditModel, audit_id))
            if row.state in {
                AuditState.COMPLETED.value,
                AuditState.COMPLETED_WITH_WARNINGS.value,
                AuditState.PARTIALLY_COMPLETED.value,
            }:
                return _audit(row)
            row.page_count = int(summary["total_pages"])
            row.issue_count = int(summary["total_issues"])
            row.partial = partial
            row.state = (
                AuditState.PARTIALLY_COMPLETED.value
                if partial
                else (
                    AuditState.COMPLETED_WITH_WARNINGS.value
                    if row.issue_count
                    else AuditState.COMPLETED.value
                )
            )
            row.completed_at = now
            row.export_available = True
            session.add(
                MetadataAuditSummaryModel(
                    audit_id=audit_id,
                    summary_json=json.dumps(summary, sort_keys=True, separators=(",", ":")),
                    created_at=now,
                    version=METADATA_AUDIT_VERSION,
                )
            )
            session.add(_event(audit_id, "completed", row.page_count, now))
            session.flush()
            return _audit(row)

    def fail(self, audit_id: str, code: str) -> None:
        with self._runtime.transaction() as session:
            row = _required(session.get(MetadataAuditModel, audit_id))
            row.state, row.failure_code, row.completed_at = (
                AuditState.FAILED.value,
                code,
                datetime.now(UTC),
            )
            session.add(_event(audit_id, "failed", row.page_count, row.completed_at, code))

    def get(self, audit_id: str) -> MetadataAudit | None:
        with self._runtime.transaction() as session:
            row = session.get(MetadataAuditModel, audit_id)
            return _audit(row) if row else None

    def list_audits(self, offset: int, limit: int) -> tuple[MetadataAudit, ...]:
        with self._runtime.transaction() as session:
            return tuple(
                _audit(row)
                for row in session.scalars(
                    select(MetadataAuditModel)
                    .order_by(
                        MetadataAuditModel.created_at.desc(), MetadataAuditModel.audit_id.desc()
                    )
                    .offset(offset)
                    .limit(limit)
                )
            )

    def summary(self, audit_id: str) -> dict[str, Any] | None:
        with self._runtime.transaction() as session:
            row = session.get(MetadataAuditSummaryModel, audit_id)
            return json.loads(row.summary_json) if row else None

    def list_pages(
        self, audit_id: str, offset: int, limit: int, filters: dict[str, Any]
    ) -> tuple[AuditPage, ...]:
        statement = select(MetadataAuditPageModel).where(
            MetadataAuditPageModel.audit_id == audit_id
        )
        criteria = _page_criteria(filters)
        if criteria:
            statement = statement.where(*criteria)
        rank = case(
            (MetadataAuditPageModel.highest_severity == "critical", 5),
            (MetadataAuditPageModel.highest_severity == "high", 4),
            (MetadataAuditPageModel.highest_severity == "medium", 3),
            (MetadataAuditPageModel.highest_severity == "low", 2),
            else_=1,
        )
        with self._runtime.transaction() as session:
            return tuple(
                _page(row)
                for row in session.scalars(
                    statement.order_by(rank.desc(), MetadataAuditPageModel.url_identity)
                    .offset(offset)
                    .limit(limit)
                )
            )

    def get_page(self, audit_id: str, page_id: str) -> AuditPage | None:
        with self._runtime.transaction() as session:
            row = session.scalar(
                select(MetadataAuditPageModel).where(
                    MetadataAuditPageModel.audit_id == audit_id,
                    MetadataAuditPageModel.audit_page_id == page_id,
                )
            )
            return _page(row) if row else None

    def list_issues(
        self, audit_id: str, offset: int, limit: int, filters: dict[str, Any]
    ) -> tuple[dict[str, Any], ...]:
        statement = select(
            MetadataAuditIssueModel,
            MetadataAuditPageModel.url,
            MetadataAuditPageModel.http_status,
            MetadataAuditPageModel.content_type_category,
        ).join(MetadataAuditPageModel)
        statement = statement.where(MetadataAuditIssueModel.audit_id == audit_id)
        criteria = _issue_criteria(filters)
        if criteria:
            statement = statement.where(*criteria)
        rank = case(
            (MetadataAuditIssueModel.severity == "critical", 5),
            (MetadataAuditIssueModel.severity == "high", 4),
            (MetadataAuditIssueModel.severity == "medium", 3),
            (MetadataAuditIssueModel.severity == "low", 2),
            else_=1,
        )
        with self._runtime.transaction() as session:
            rows = session.execute(
                statement.order_by(
                    rank.desc(),
                    MetadataAuditIssueModel.category,
                    MetadataAuditIssueModel.code,
                    MetadataAuditPageModel.url_identity,
                )
                .offset(offset)
                .limit(limit)
            ).all()
            return tuple(
                {
                    "issue_id": issue.issue_id,
                    "audit_page_id": issue.audit_page_id,
                    "code": issue.code,
                    "category": issue.category,
                    "severity": issue.severity,
                    "summary": issue.safe_summary,
                    "detail": issue.safe_detail,
                    "determinacy": issue.determinacy,
                    "evidence": json.loads(issue.evidence_json),
                    "duplicate_group_id": issue.duplicate_group_id,
                    "url": url,
                    "status": status,
                    "content_type": content,
                }
                for issue, url, status, content in rows
            )

    def duplicate_groups(
        self, audit_id: str, offset: int, limit: int, duplicate_type: str | None = None
    ) -> tuple[DuplicateGroup, ...]:
        statement = select(MetadataDuplicateGroupModel).where(
            MetadataDuplicateGroupModel.audit_id == audit_id
        )
        if duplicate_type:
            statement = statement.where(
                MetadataDuplicateGroupModel.duplicate_type == duplicate_type
            )
        with self._runtime.transaction() as session:
            return tuple(
                _group(row)
                for row in session.scalars(
                    statement.order_by(
                        MetadataDuplicateGroupModel.member_count.desc(),
                        MetadataDuplicateGroupModel.group_id,
                    )
                    .offset(offset)
                    .limit(limit)
                )
            )

    def duplicate_members(
        self, audit_id: str, group_id: str, offset: int, limit: int
    ) -> tuple[AuditPage, ...]:
        with self._runtime.transaction() as session:
            return tuple(
                _page(row)
                for row in session.scalars(
                    select(MetadataAuditPageModel)
                    .join(MetadataDuplicateGroupMemberModel)
                    .join(MetadataDuplicateGroupModel)
                    .where(
                        MetadataDuplicateGroupModel.audit_id == audit_id,
                        MetadataDuplicateGroupMemberModel.group_id == group_id,
                    )
                    .order_by(
                        MetadataDuplicateGroupMemberModel.url_identity,
                        MetadataDuplicateGroupMemberModel.audit_page_id,
                    )
                    .offset(offset)
                    .limit(limit)
                )
            )

    def export_record(self, audit_id: str, export_format: str) -> MetadataAuditExportModel | None:
        with self._runtime.transaction() as session:
            return cast(
                "MetadataAuditExportModel | None",
                session.scalar(
                    select(MetadataAuditExportModel).where(
                        MetadataAuditExportModel.audit_id == audit_id,
                        MetadataAuditExportModel.export_format == export_format,
                    )
                ),
            )

    def register_export(
        self, audit_id: str, export_format: str, artifact_id: str, row_count: int, truncated: bool
    ) -> dict[str, Any]:
        export_id = (
            "export-" + hashlib.sha256(f"{audit_id}\0{export_format}".encode()).hexdigest()[:40]
        )
        with self._runtime.transaction() as session:
            row = session.get(MetadataAuditExportModel, export_id)
            if row is None:
                row = MetadataAuditExportModel(
                    export_id=export_id,
                    audit_id=audit_id,
                    export_format=export_format,
                    artifact_id=artifact_id,
                    row_count=row_count,
                    truncated=truncated,
                    state="available",
                    failure_code=None,
                    created_at=datetime.now(UTC),
                )
                session.add(row)
            return {
                "export_id": export_id,
                "artifact_id": row.artifact_id,
                "format": row.export_format,
                "row_count": row.row_count,
                "truncated": row.truncated,
                "state": row.state,
            }

    def diagnostics(self) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            counts = dict(
                session.execute(
                    select(MetadataAuditModel.state, func.count()).group_by(
                        MetadataAuditModel.state
                    )
                ).all()
            )
            return {
                "enabled": True,
                "total_audits": sum(counts.values()),
                "state_counts": counts,
                "page_count": session.scalar(
                    select(func.count()).select_from(MetadataAuditPageModel)
                )
                or 0,
                "issue_count": session.scalar(
                    select(func.count()).select_from(MetadataAuditIssueModel)
                )
                or 0,
                "duplicate_group_count": session.scalar(
                    select(func.count()).select_from(MetadataDuplicateGroupModel)
                )
                or 0,
                "persistence_ready": True,
                "migration_ready": True,
                "page_evidence_ready": True,
            }


def _required(value: Any) -> Any:
    if value is None:
        raise ValueError("metadata_audit_not_found")
    return value


def _event(
    audit_id: str, event_type: str, count: int, when: datetime, reason: str | None = None
) -> MetadataAuditEventModel:
    return MetadataAuditEventModel(
        audit_id=audit_id,
        event_type=event_type,
        safe_reason_code=reason,
        affected_count=count,
        occurred_at=when,
        version=METADATA_AUDIT_PERSISTENCE_VERSION,
    )


def _audit(row: MetadataAuditModel) -> MetadataAudit:
    return MetadataAudit(
        row.audit_id,
        row.job_id,
        row.run_id,
        row.seed_url,
        AuditState(row.state),
        row.created_at,
        row.started_at,
        row.completed_at,
        row.page_count,
        row.issue_count,
        row.partial,
        row.failure_code,
        row.export_available,
        row.configuration_json,
    )


def _page(row: MetadataAuditPageModel) -> AuditPage:
    return AuditPage(
        row.audit_page_id,
        row.audit_id,
        row.evidence_id,
        row.url,
        row.final_url,
        row.fetch_outcome,
        row.http_status,
        row.content_type,
        row.content_type_category,
        row.title_value,
        row.title_presence,
        row.description_value,
        row.description_presence,
        row.canonical_value,
        row.canonical_state,
        row.robots_allowed,
        row.indexability_state,
        row.recommendation_state,
        row.issue_count,
        Severity(row.highest_severity) if row.highest_severity else None,
        row.partial,
    )


def _group(row: MetadataDuplicateGroupModel) -> DuplicateGroup:
    return DuplicateGroup(
        row.group_id,
        row.audit_id,
        DuplicateType(row.duplicate_type),
        row.normalized_value_hash,
        row.sample_value,
        row.member_count,
        tuple(json.loads(row.sample_members_json)),
        row.created_at,
    )


def _evidence(
    row: CrawlPageEvidenceModel, hops: tuple[CrawlPageRedirectHopModel, ...]
) -> PageEvidenceRecord:
    from musimack_tools.domain.page_evidence import PageRedirectEvidence  # noqa: PLC0415

    redirects = tuple(
        PageRedirectEvidence(
            h.sequence,
            h.source_url,
            h.target_url,
            h.status_code,
            h.cross_host,
            h.terminal,
            h.loop,
            h.failure_code,
        )
        for h in hops
    )
    return PageEvidenceRecord(
        row.evidence_id,
        row.job_id,
        row.run_id,
        row.requested_url,
        row.requested_url_identity,
        row.final_url,
        row.final_url_identity,
        row.discovery_sequence,
        row.crawl_depth,
        row.referrer_url,
        row.frontier_state,
        row.fetch_outcome,
        row.http_status,
        row.status_class,
        row.fetch_failed,
        row.redirect_count,
        row.redirect_truncated,
        row.redirect_loop,
        row.content_type,
        ContentTypeCategory(row.content_type_category),
        row.charset,
        row.parsed_as_html,
        row.parse_outcome,
        MetadataPresence(row.title_presence),
        row.title_value,
        row.title_normalized_hash,
        row.title_count,
        row.title_length,
        row.title_truncated,
        MetadataPresence(row.description_presence),
        row.description_value,
        row.description_normalized_hash,
        row.description_count,
        row.description_length,
        row.description_truncated,
        MetadataPresence(row.canonical_presence),
        row.canonical_url,
        row.canonical_url_identity,
        row.canonical_count,
        row.canonical_conflicting,
        row.canonical_cross_host,
        row.canonical_cross_scheme,
        row.canonical_cross_port,
        row.canonical_truncated,
        row.meta_robots_json,
        row.x_robots_json,
        row.robots_allowed,
        row.robots_reason_code,
        row.robots_evidence_json,
        row.indexability_evidence_json,
        IndexabilityEvidenceState(row.indexability_state),
        row.parse_warning_count,
        row.parse_warnings_truncated,
        PageEvidenceState(row.evidence_state),
        row.failure_code,
        row.value_truncated,
        row.created_at,
        redirects=redirects,
    )


def _page_criteria(filters: dict[str, Any]) -> list[Any]:
    criteria: list[Any] = []
    mapping = {
        "highest_severity": MetadataAuditPageModel.highest_severity,
        "status": MetadataAuditPageModel.http_status,
        "content_type": MetadataAuditPageModel.content_type_category,
        "indexability": MetadataAuditPageModel.indexability_state,
        "robots_allowed": MetadataAuditPageModel.robots_allowed,
        "recommendation": MetadataAuditPageModel.recommendation_state,
        "canonical": MetadataAuditPageModel.canonical_state,
        "partial": MetadataAuditPageModel.partial,
    }
    for key, column in mapping.items():
        if filters.get(key) is not None:
            criteria.append(column == filters[key])
    if filters.get("url"):
        criteria.append(MetadataAuditPageModel.url.contains(filters["url"], autoescape=True))
    if filters.get("has_issues") is not None:
        criteria.append(
            MetadataAuditPageModel.issue_count > 0
            if filters["has_issues"]
            else MetadataAuditPageModel.issue_count == 0
        )
    if filters.get("status_class") is not None:
        low = int(filters["status_class"]) * 100
        criteria.append(
            and_(
                MetadataAuditPageModel.http_status >= low,
                MetadataAuditPageModel.http_status < low + 100,
            )
        )
    return criteria


def _issue_criteria(filters: dict[str, Any]) -> list[Any]:
    criteria: list[Any] = []
    mapping = {
        "severity": MetadataAuditIssueModel.severity,
        "category": MetadataAuditIssueModel.category,
        "code": MetadataAuditIssueModel.code,
        "page_id": MetadataAuditIssueModel.audit_page_id,
        "determinacy": MetadataAuditIssueModel.determinacy,
        "duplicate_group_id": MetadataAuditIssueModel.duplicate_group_id,
        "content_type": MetadataAuditPageModel.content_type_category,
    }
    for key, column in mapping.items():
        if filters.get(key) is not None:
            criteria.append(column == filters[key])
    if filters.get("url"):
        criteria.append(MetadataAuditPageModel.url.contains(filters["url"], autoescape=True))
    if filters.get("status_class") is not None:
        low = int(filters["status_class"]) * 100
        criteria.append(
            and_(
                MetadataAuditPageModel.http_status >= low,
                MetadataAuditPageModel.http_status < low + 100,
            )
        )
    return criteria
