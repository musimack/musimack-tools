"""Restart-safe persistence and bounded queries for sitemap audits."""

# ruff: noqa: ANN401, FBT001, PLR0913 - SQLAlchemy runtime and records are explicit.

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update

from musimack_tools.domain.page_evidence import (
    ContentTypeCategory,
    IndexabilityEvidenceState,
    PageEvidenceState,
)
from musimack_tools.domain.sitemap_audit import (
    SITEMAP_AUDIT_VERSION,
    SITEMAP_COMPARISON_POLICY_VERSION,
    AuditLifecycle,
    ComparisonInput,
    ComparisonRecord,
    DiscoveryOptions,
    ParsedSitemap,
    SitemapAuditConfiguration,
    SitemapCandidate,
    SitemapFinding,
    comparison_identity,
    document_identity,
    entry_identity,
    finding_identity,
)
from musimack_tools.domain.urls import ScopeMode
from musimack_tools.persistence.models import (
    ConfigurationSnapshotModel,
    CrawlPageEvidenceModel,
    JobModel,
    RunModel,
)
from musimack_tools.persistence.sitemap_audit_models import (
    SitemapAuditComparisonModel,
    SitemapAuditDocumentModel,
    SitemapAuditEntryModel,
    SitemapAuditEventModel,
    SitemapAuditExportModel,
    SitemapAuditFindingModel,
    SitemapAuditModel,
)


class SQLAlchemySitemapAuditRepository:
    """Own normalized audit writes, transitions, filters, and cleanup."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def run_context(self, run_id: str) -> tuple[str, str, bool, int] | None:
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
            count = session.scalar(
                select(func.count())
                .select_from(CrawlPageEvidenceModel)
                .where(CrawlPageEvidenceModel.run_id == run_id)
            )
            terminal = run.lifecycle in {
                "completed",
                "completed_with_warnings",
                "partially_completed",
                "failed",
                "cancelled",
            }
            return job.job_id, run.normalized_seed_url, terminal, int(count or 0)

    def run_scope_snapshot(self, run_id: str) -> tuple[ScopeMode, tuple[str, ...]] | None:
        """Return the accepted host-scope snapshot retained with the crawl run."""
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
                mode = ScopeMode(payload["scope_mode"])
                hosts = tuple(str(item) for item in payload["approved_hosts"])
            except KeyError, TypeError, ValueError, json.JSONDecodeError:
                return None
            return mode, hosts

    def create(
        self,
        audit_id: str,
        job_id: str,
        run_id: str,
        seed: str,
        options: DiscoveryOptions,
        configuration: SitemapAuditConfiguration,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            existing = session.get(SitemapAuditModel, audit_id)
            if existing is not None:
                return _dict(existing)
            row = SitemapAuditModel(
                audit_id=audit_id,
                job_id=job_id,
                run_id=run_id,
                seed_url=seed,
                explicit_sitemap_url=options.explicit_url,
                discovery_settings_json=_json(asdict(options)),
                configuration_json=_json(configuration.snapshot()),
                state=AuditLifecycle.ACCEPTED.value,
                failure_code=None,
                warning_count=0,
                document_count=0,
                unique_url_count=0,
                comparison_count=0,
                add_count=0,
                remove_count=0,
                review_count=0,
                unchanged_count=0,
                created_at=now,
                started_at=None,
                completed_at=None,
                retention_until=now + timedelta(days=configuration.retention_days),
                audit_version=SITEMAP_AUDIT_VERSION,
                parser_version=configuration.parser_version,
                comparison_version=SITEMAP_COMPARISON_POLICY_VERSION,
                normalization_version="seo-toolkit-url-normalization-v1",
                page_evidence_version="seo-toolkit-page-evidence-v1",
                recommendation_version="seo-toolkit-sitemap-recommendation-v1",
            )
            session.add(row)
            session.flush()
            session.add(_event(audit_id, 0, "created", None))
            return _dict(row)

    def transition(
        self, audit_id: str, state: AuditLifecycle, failure_code: str | None = None
    ) -> None:
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            row = _required(session.get(SitemapAuditModel, audit_id))
            row.state = state.value
            row.failure_code = failure_code
            if row.started_at is None and state is not AuditLifecycle.ACCEPTED:
                row.started_at = now
            if state in {
                AuditLifecycle.COMPLETED,
                AuditLifecycle.COMPLETED_WITH_WARNINGS,
                AuditLifecycle.PARTIALLY_COMPLETED,
                AuditLifecycle.FAILED,
                AuditLifecycle.CANCELLED,
            }:
                row.completed_at = now
            sequence = int(
                session.scalar(
                    select(func.count())
                    .select_from(SitemapAuditEventModel)
                    .where(SitemapAuditEventModel.audit_id == audit_id)
                )
                or 0
            )
            session.add(_event(audit_id, sequence, state.value, failure_code))

    def persist_operational_accounting(self, audit_id: str, accounting: dict[str, Any]) -> None:
        """Retain one bounded idempotent execution projection in existing JSON storage."""

        with self._runtime.transaction() as session:
            row = _required(session.get(SitemapAuditModel, audit_id))
            configuration = json.loads(row.configuration_json)
            configuration["operational_accounting"] = accounting
            row.configuration_json = _json(configuration)

    def claim_execution(self, audit_id: str) -> bool:
        """Atomically admit exactly one executor for an accepted audit."""
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            result = session.execute(
                update(SitemapAuditModel)
                .where(
                    SitemapAuditModel.audit_id == audit_id,
                    SitemapAuditModel.state == AuditLifecycle.ACCEPTED.value,
                )
                .values(
                    state=AuditLifecycle.DISCOVERING.value,
                    started_at=now,
                    failure_code=None,
                )
            )
            if result.rowcount != 1:
                return False
            session.add(_event(audit_id, 1, AuditLifecycle.DISCOVERING.value, None))
            return True

    def fail_if_running(self, audit_id: str, failure_code: str) -> bool:
        """Make an interrupted executor terminal without overwriting a terminal result."""
        running = {
            AuditLifecycle.DISCOVERING.value,
            AuditLifecycle.FETCHING.value,
            AuditLifecycle.PARSING.value,
            AuditLifecycle.COMPARING.value,
        }
        with self._runtime.transaction() as session:
            row = session.get(SitemapAuditModel, audit_id)
            if row is None or row.state not in running:
                return False
            row.state = AuditLifecycle.FAILED.value
            row.failure_code = failure_code
            row.completed_at = datetime.now(UTC)
            sequence = int(
                session.scalar(
                    select(func.count())
                    .select_from(SitemapAuditEventModel)
                    .where(SitemapAuditEventModel.audit_id == audit_id)
                )
                or 0
            )
            session.add(_event(audit_id, sequence, AuditLifecycle.FAILED.value, failure_code))
            return True

    def reconcile_interrupted(self) -> int:
        """Fail nonterminal audits left behind by a stopped application process."""
        running = {
            AuditLifecycle.DISCOVERING.value,
            AuditLifecycle.FETCHING.value,
            AuditLifecycle.PARSING.value,
            AuditLifecycle.COMPARING.value,
        }
        with self._runtime.transaction() as session:
            identifiers = tuple(
                session.scalars(
                    select(SitemapAuditModel.audit_id)
                    .where(SitemapAuditModel.state.in_(running))
                    .order_by(SitemapAuditModel.audit_id)
                )
            )
        for audit_id in identifiers:
            self.fail_if_running(audit_id, "sitemap_audit_execution_interrupted")
        return len(identifiers)

    def persist_document(
        self,
        audit_id: str,
        candidate: SitemapCandidate,
        *,
        parent_document_id: str | None,
        depth: int,
        final_url: str | None,
        fetch_state: str,
        http_status: int | None,
        content_type: str | None,
        payload: bytes,
        redirects: tuple[Any, ...],
        parsed: ParsedSitemap,
    ) -> str:
        identity = final_url or candidate.normalized_url
        doc_id = document_identity(audit_id, identity)
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            row = session.get(SitemapAuditDocumentModel, doc_id)
            if row is None:
                row = SitemapAuditDocumentModel(
                    document_id=doc_id,
                    audit_id=audit_id,
                    parent_document_id=parent_document_id,
                    discovery_source=candidate.discovery_source.value,
                    requested_url=candidate.normalized_url,
                    final_url=final_url,
                    normalized_identity=identity,
                    provenance_json=_json([item.value for item in candidate.provenance]),
                    depth=depth,
                    discovery_sequence=candidate.discovery_sequence,
                    fetch_state=fetch_state,
                    http_status=http_status,
                    content_type=content_type,
                    payload_size=len(payload),
                    payload_sha256=hashlib.sha256(payload).hexdigest() if payload else None,
                    redirect_json=_json([asdict(item) for item in redirects]),
                    root_type=parsed.root_type.value,
                    entry_count=len(parsed.entries),
                    child_count=len(parsed.children),
                    parse_state=parsed.parse_state.value,
                    validation_count=len(parsed.findings),
                    created_at=now,
                    completed_at=now,
                )
                session.add(row)
            all_entries = parsed.entries + parsed.children
            entry_ids: dict[int, str] = {}
            for entry in all_entries:
                item_id = entry_identity(doc_id, entry.entry_sequence, entry.raw_location)
                entry_ids[entry.entry_sequence] = item_id
                if session.get(SitemapAuditEntryModel, item_id) is None:
                    session.add(
                        SitemapAuditEntryModel(
                            entry_id=item_id,
                            audit_id=audit_id,
                            document_id=doc_id,
                            raw_location=entry.raw_location,
                            normalized_identity=entry.normalized_url,
                            entry_sequence=entry.entry_sequence,
                            in_scope=entry.in_scope,
                            validation_state="valid" if entry.valid else "invalid",
                            duplicate=entry.duplicate,
                            duplicate_identity=entry.normalized_url if entry.duplicate else None,
                            is_child_reference=entry in parsed.children,
                        )
                    )
            for finding in parsed.findings:
                self._add_finding(session, audit_id, doc_id, entry_ids, finding)
            return doc_id

    def persist_finding(
        self, audit_id: str, finding: SitemapFinding, document_id: str | None = None
    ) -> None:
        with self._runtime.transaction() as session:
            self._add_finding(session, audit_id, document_id, {}, finding)

    def _add_finding(
        self,
        session: Any,
        audit_id: str,
        document_id: str | None,
        entry_ids: dict[int, str],
        finding: SitemapFinding,
    ) -> None:
        sequence = int(
            session.scalar(
                select(func.count())
                .select_from(SitemapAuditFindingModel)
                .where(SitemapAuditFindingModel.audit_id == audit_id)
            )
            or 0
        )
        normalized = SitemapFinding(
            finding.code,
            finding.severity,
            finding.message,
            sequence,
            finding.raw_url,
            finding.normalized_url,
            finding.entry_sequence,
            finding.context,
        )
        item_id = finding_identity(audit_id, document_id, normalized)
        if session.get(SitemapAuditFindingModel, item_id) is None:
            session.add(
                SitemapAuditFindingModel(
                    finding_id=item_id,
                    audit_id=audit_id,
                    document_id=document_id,
                    entry_id=entry_ids.get(finding.entry_sequence or -1),
                    code=finding.code.value,
                    severity=finding.severity.value,
                    safe_message=finding.message[:512],
                    raw_url=finding.raw_url,
                    normalized_identity=finding.normalized_url,
                    context_json=_json(dict(finding.context)),
                    finding_sequence=sequence,
                    created_at=datetime.now(UTC),
                )
            )

    def evidence(self, run_id: str) -> tuple[ComparisonInput, ...]:
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(CrawlPageEvidenceModel)
                .where(CrawlPageEvidenceModel.run_id == run_id)
                .order_by(CrawlPageEvidenceModel.discovery_sequence)
            )
            return tuple(
                ComparisonInput(
                    row.evidence_id,
                    row.requested_url,
                    row.requested_url_identity,
                    row.final_url,
                    row.final_url_identity,
                    row.fetch_failed,
                    row.http_status,
                    row.redirect_count,
                    row.content_type,
                    ContentTypeCategory(row.content_type_category),
                    row.parsed_as_html,
                    row.canonical_url,
                    row.canonical_url_identity,
                    row.indexability_evidence_json,
                    IndexabilityEvidenceState(row.indexability_state),
                    PageEvidenceState(row.evidence_state),
                )
                for row in rows
            )

    def sitemap_entries(self, audit_id: str) -> dict[str, tuple[str, str]]:
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(SitemapAuditEntryModel)
                .where(
                    SitemapAuditEntryModel.audit_id == audit_id,
                    SitemapAuditEntryModel.validation_state == "valid",
                    SitemapAuditEntryModel.duplicate.is_(False),
                    SitemapAuditEntryModel.is_child_reference.is_(False),
                    SitemapAuditEntryModel.normalized_identity.is_not(None),
                )
                .order_by(SitemapAuditEntryModel.entry_sequence)
            )
            return {
                hashlib.sha256(row.normalized_identity.encode()).hexdigest(): (
                    row.entry_id,
                    row.raw_location or row.normalized_identity,
                )
                for row in rows
                if row.normalized_identity is not None
            }

    def persist_comparisons(self, audit_id: str, records: tuple[ComparisonRecord, ...]) -> None:
        with self._runtime.transaction() as session:
            for record in records:
                item_id = comparison_identity(audit_id, record.url_identity)
                if session.get(SitemapAuditComparisonModel, item_id) is None:
                    session.add(
                        SitemapAuditComparisonModel(
                            comparison_id=item_id,
                            audit_id=audit_id,
                            normalized_identity=record.url_identity,
                            url=record.url,
                            in_sitemap=record.in_sitemap,
                            representative_entry_id=record.representative_entry_id,
                            evidence_id=record.evidence_id,
                            recommendation_state=(
                                record.recommendation_state.value
                                if record.recommendation_state
                                else None
                            ),
                            comparison_state=record.comparison_state.value,
                            action=record.action.value,
                            reason_code=record.reason.value,
                            http_status=record.http_status,
                            redirect_target=record.redirect_target,
                            canonical_target=record.canonical_target,
                            indexability_state=record.indexability_state,
                            content_type=record.content_type,
                            crawl_evidence_state=record.crawl_evidence_state,
                            record_sequence=record.sequence,
                            comparison_version=SITEMAP_COMPARISON_POLICY_VERSION,
                        )
                    )

    def finish(self, audit_id: str, *, partial: bool = False) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            row = _required(session.get(SitemapAuditModel, audit_id))
            row.document_count = _count(session, SitemapAuditDocumentModel, audit_id)
            row.unique_url_count = int(
                session.scalar(
                    select(
                        func.count(func.distinct(SitemapAuditEntryModel.normalized_identity))
                    ).where(
                        SitemapAuditEntryModel.audit_id == audit_id,
                        SitemapAuditEntryModel.is_child_reference.is_(False),
                    )
                )
                or 0
            )
            row.warning_count = _count(session, SitemapAuditFindingModel, audit_id)
            actions = Counter(
                session.scalars(
                    select(SitemapAuditComparisonModel.action).where(
                        SitemapAuditComparisonModel.audit_id == audit_id
                    )
                )
            )
            row.comparison_count = sum(actions.values())
            row.add_count = actions["add"]
            row.remove_count = actions["remove"]
            row.review_count = actions["review"]
            row.unchanged_count = actions["unchanged"]
            row.state = (
                AuditLifecycle.PARTIALLY_COMPLETED.value
                if partial
                else AuditLifecycle.COMPLETED_WITH_WARNINGS.value
                if row.warning_count
                else AuditLifecycle.COMPLETED.value
            )
            row.completed_at = datetime.now(UTC)
            sequence = int(
                session.scalar(
                    select(func.count())
                    .select_from(SitemapAuditEventModel)
                    .where(SitemapAuditEventModel.audit_id == audit_id)
                )
                or 0
            )
            session.add(_event(audit_id, sequence, row.state, None))
            return _dict(row)

    def get(self, audit_id: str) -> dict[str, Any] | None:
        with self._runtime.transaction() as session:
            row = session.get(SitemapAuditModel, audit_id)
            return _dict(row) if row else None

    def list_audits(self, offset: int, limit: int) -> tuple[dict[str, Any], ...]:
        return self._list(SitemapAuditModel, offset, limit, SitemapAuditModel.created_at.desc())

    def list_documents(
        self,
        audit_id: str,
        offset: int,
        limit: int,
        filters: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            statement = select(SitemapAuditDocumentModel).where(
                SitemapAuditDocumentModel.audit_id == audit_id
            )
            values = filters or {}
            for key, column in {
                "parse_state": SitemapAuditDocumentModel.parse_state,
                "depth": SitemapAuditDocumentModel.depth,
                "discovery_source": SitemapAuditDocumentModel.discovery_source,
            }.items():
                if values.get(key) is not None:
                    statement = statement.where(column == values[key])
            if values.get("root") is not None:
                statement = statement.where(
                    SitemapAuditDocumentModel.parent_document_id.is_(None)
                    if values["root"]
                    else SitemapAuditDocumentModel.parent_document_id.is_not(None)
                )
            if values.get("url"):
                statement = statement.where(
                    SitemapAuditDocumentModel.requested_url.contains(values["url"], autoescape=True)
                )
            rows = session.scalars(
                statement.order_by(SitemapAuditDocumentModel.discovery_sequence)
                .offset(offset)
                .limit(limit)
            )
            return tuple(_dict(row) for row in rows)

    def list_entries(self, audit_id: str, offset: int, limit: int) -> tuple[dict[str, Any], ...]:
        return self._list_for(
            SitemapAuditEntryModel,
            audit_id,
            offset,
            limit,
            SitemapAuditEntryModel.entry_sequence,
        )

    def list_findings(
        self,
        audit_id: str,
        offset: int,
        limit: int,
        filters: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            statement = select(SitemapAuditFindingModel).where(
                SitemapAuditFindingModel.audit_id == audit_id
            )
            values = filters or {}
            for key, column in {
                "severity": SitemapAuditFindingModel.severity,
                "code": SitemapAuditFindingModel.code,
                "document_id": SitemapAuditFindingModel.document_id,
            }.items():
                if values.get(key):
                    statement = statement.where(column == values[key])
            if values.get("url"):
                statement = statement.where(
                    SitemapAuditFindingModel.raw_url.contains(values["url"], autoescape=True)
                )
            rows = session.scalars(
                statement.order_by(SitemapAuditFindingModel.finding_sequence)
                .offset(offset)
                .limit(limit)
            )
            return tuple(_dict(row) for row in rows)

    def list_comparisons(
        self,
        audit_id: str,
        offset: int,
        limit: int,
        filters: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            statement = select(SitemapAuditComparisonModel).where(
                SitemapAuditComparisonModel.audit_id == audit_id
            )
            values = filters or {}
            for key, column in {
                "action": SitemapAuditComparisonModel.action,
                "state": SitemapAuditComparisonModel.comparison_state,
                "reason": SitemapAuditComparisonModel.reason_code,
                "recommendation": SitemapAuditComparisonModel.recommendation_state,
                "http_status": SitemapAuditComparisonModel.http_status,
                "indexability": SitemapAuditComparisonModel.indexability_state,
            }.items():
                if values.get(key) is not None:
                    statement = statement.where(column == values[key])
            if values.get("status_class") is not None:
                lower = int(values["status_class"]) * 100
                statement = statement.where(
                    SitemapAuditComparisonModel.http_status >= lower,
                    SitemapAuditComparisonModel.http_status < lower + 100,
                )
            if values.get("content_type"):
                statement = statement.where(
                    SitemapAuditComparisonModel.content_type.contains(
                        values["content_type"], autoescape=True
                    )
                )
            if values.get("document_id"):
                statement = statement.join(
                    SitemapAuditEntryModel,
                    SitemapAuditEntryModel.entry_id
                    == SitemapAuditComparisonModel.representative_entry_id,
                ).where(SitemapAuditEntryModel.document_id == values["document_id"])
            if values.get("url"):
                statement = statement.where(
                    SitemapAuditComparisonModel.url.contains(values["url"], autoescape=True)
                )
            rows = session.scalars(
                statement.order_by(
                    SitemapAuditComparisonModel.action,
                    SitemapAuditComparisonModel.record_sequence,
                )
                .offset(offset)
                .limit(limit)
            )
            return tuple(_dict(row) for row in rows)

    def upsert_export(
        self,
        audit_id: str,
        export_format: str,
        artifact_id: str | None,
        row_count: int,
        truncated: bool,
    ) -> dict[str, Any]:
        export_id = (
            "sitemap-export-"
            + hashlib.sha256(f"{audit_id}\0{export_format}".encode()).hexdigest()[:32]
        )
        now = datetime.now(UTC)
        with self._runtime.transaction() as session:
            row = session.get(SitemapAuditExportModel, export_id)
            if row is None:
                row = SitemapAuditExportModel(
                    export_id=export_id,
                    audit_id=audit_id,
                    export_format=export_format,
                    artifact_id=artifact_id,
                    state="available" if artifact_id else "failed",
                    row_count=row_count,
                    truncated=truncated,
                    created_at=now,
                    completed_at=now,
                    export_version="seo-toolkit-sitemap-audit-export-v1",
                )
                session.add(row)
            return _dict(row)

    def list_exports(self, audit_id: str) -> tuple[dict[str, Any], ...]:
        return self._list_for(
            SitemapAuditExportModel,
            audit_id,
            0,
            10,
            SitemapAuditExportModel.created_at,
        )

    def diagnostics(self) -> dict[str, Any]:
        with self._runtime.transaction() as session:
            counts = dict(
                session.execute(
                    select(SitemapAuditModel.state, func.count()).group_by(SitemapAuditModel.state)
                ).all()
            )
            return {
                "enabled": True,
                "total_audits": sum(counts.values()),
                "state_counts": counts,
                "document_count": _count_all(session, SitemapAuditDocumentModel),
                "entry_count": _count_all(session, SitemapAuditEntryModel),
                "finding_count": _count_all(session, SitemapAuditFindingModel),
                "comparison_count": _count_all(session, SitemapAuditComparisonModel),
                "persistence_ready": True,
                "migration_ready": True,
                "page_evidence_ready": True,
            }

    def cleanup_expired(self, now: datetime, limit: int = 100) -> int:
        with self._runtime.transaction() as session:
            ids = tuple(
                session.scalars(
                    select(SitemapAuditModel.audit_id)
                    .where(SitemapAuditModel.retention_until <= now)
                    .order_by(SitemapAuditModel.retention_until)
                    .limit(limit)
                )
            )
            if ids:
                session.execute(
                    delete(SitemapAuditModel).where(SitemapAuditModel.audit_id.in_(ids))
                )
            return len(ids)

    def _list(
        self, model: Any, offset: int, limit: int, ordering: Any
    ) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            rows = session.scalars(select(model).order_by(ordering).offset(offset).limit(limit))
            return tuple(_dict(row) for row in rows)

    def _list_for(
        self, model: Any, audit_id: str, offset: int, limit: int, ordering: Any
    ) -> tuple[dict[str, Any], ...]:
        with self._runtime.transaction() as session:
            rows = session.scalars(
                select(model)
                .where(model.audit_id == audit_id)
                .order_by(ordering)
                .offset(offset)
                .limit(limit)
            )
            return tuple(_dict(row) for row in rows)


def _dict(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _required(value: Any) -> Any:
    if value is None:
        raise ValueError("sitemap_audit_not_found")
    return value


def _count(session: Any, model: Any, audit_id: str) -> int:
    return int(
        session.scalar(select(func.count()).select_from(model).where(model.audit_id == audit_id))
        or 0
    )


def _count_all(session: Any, model: Any) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _event(
    audit_id: str, sequence: int, event_type: str, safe_code: str | None
) -> SitemapAuditEventModel:
    return SitemapAuditEventModel(
        audit_id=audit_id,
        sequence=sequence,
        event_type=event_type,
        safe_code=safe_code,
        counts_json="{}",
        created_at=datetime.now(UTC),
    )
