"""Short-transaction repository for restart-safe page crawl evidence."""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import and_, delete, func, or_, select

from musimack_tools.domain.page_evidence import (
    PAGE_EVIDENCE_ORDERING,
    PAGE_EVIDENCE_PERSISTENCE_VERSION,
    PAGE_EVIDENCE_RETENTION_VERSION,
    PAGE_EVIDENCE_VERSION,
    ContentTypeCategory,
    IndexabilityEvidenceState,
    MetadataPresence,
    PageEvidenceCleanupResult,
    PageEvidenceConfiguration,
    PageEvidenceDiagnostics,
    PageEvidenceFilters,
    PageEvidenceListItem,
    PageEvidencePage,
    PageEvidenceReasonCode,
    PageEvidenceReconciliationReport,
    PageEvidenceRetentionState,
    PageEvidenceState,
    PageEvidenceSummary,
    decode_cursor,
    encode_cursor,
    project_crawl_result,
)
from musimack_tools.persistence.image_audit_models import CrawlImageEvidenceModel
from musimack_tools.persistence.link_audit_models import CrawlLinkEvidenceModel
from musimack_tools.persistence.models import (
    CrawlPageEvidenceEventModel,
    CrawlPageEvidenceModel,
    CrawlPageEvidenceSummaryModel,
    CrawlPageParseWarningModel,
    CrawlPageRedirectHopModel,
    RunModel,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from sqlalchemy.sql.elements import ColumnElement

    from musimack_tools.domain.crawl import CrawlResult
    from musimack_tools.persistence.engine import PersistenceRuntime

_MAX_RECONCILIATION_ROWS = 10_000
_MAX_URL_FILTER_LENGTH = 256
_LOGGER = logging.getLogger(__name__)


def persist_projected_evidence(  # noqa: C901
    session: Session,
    job_id: str,
    run_id: str,
    crawl: CrawlResult,
    configuration: PageEvidenceConfiguration,
) -> PageEvidenceSummary:
    """Persist one accepted crawl result inside the caller's terminal transaction."""
    _LOGGER.info("page_evidence_persistence_started job_id=%s run_id=%s", job_id, run_id)
    projection = project_crawl_result(job_id, run_id, crawl, configuration)
    existing = session.get(CrawlPageEvidenceSummaryModel, run_id)
    if existing is not None:
        identifiers = tuple(
            session.scalars(
                select(CrawlPageEvidenceModel.evidence_id)
                .where(CrawlPageEvidenceModel.run_id == run_id)
                .order_by(CrawlPageEvidenceModel.discovery_sequence)
            )
        )
        expected = tuple(page.evidence_id for page in projection.pages)
        if identifiers != expected:
            raise ValueError(PageEvidenceReasonCode.CONFLICT)
        link_identifiers = tuple(
            session.scalars(
                select(CrawlLinkEvidenceModel.link_id)
                .where(CrawlLinkEvidenceModel.run_id == run_id)
                .order_by(CrawlLinkEvidenceModel.discovery_sequence)
            )
        )
        expected_links = tuple(link.link_id for link in projection.links)
        if link_identifiers != expected_links:
            raise ValueError(PageEvidenceReasonCode.CONFLICT)
        image_identifiers = tuple(
            session.scalars(
                select(CrawlImageEvidenceModel.image_id)
                .where(CrawlImageEvidenceModel.run_id == run_id)
                .order_by(CrawlImageEvidenceModel.occurrence_sequence)
            )
        )
        expected_images = tuple(image.image_id for image in projection.images)
        if image_identifiers != expected_images:
            raise ValueError(PageEvidenceReasonCode.CONFLICT)
        _LOGGER.info(
            "page_evidence_persistence_idempotent job_id=%s run_id=%s page_count=%d",
            job_id,
            run_id,
            len(expected),
        )
        return _summary(existing)

    expires_at = (
        projection.pages[0].created_at + timedelta(days=configuration.retention_days)
        if projection.pages
        else datetime.now(UTC) + timedelta(days=configuration.retention_days)
    )
    for start in range(0, len(projection.pages), configuration.batch_size):
        for page in projection.pages[start : start + configuration.batch_size]:
            values = {
                column.name: getattr(page, column.name)
                for column in CrawlPageEvidenceModel.__table__.columns
                if hasattr(page, column.name)
            }
            values.update(
                content_type_category=page.content_type_category.value,
                title_presence=page.title_presence.value,
                description_presence=page.description_presence.value,
                canonical_presence=page.canonical_presence.value,
                evidence_state=page.evidence_state.value,
                retention_state=PageEvidenceRetentionState.RETAINED.value,
                retention_hold=False,
                persisted_at=page.created_at,
                expires_at=expires_at,
                persistence_version=PAGE_EVIDENCE_PERSISTENCE_VERSION,
            )
            session.add(CrawlPageEvidenceModel(**values))
            for redirect in page.redirects:
                session.add(
                    CrawlPageRedirectHopModel(evidence_id=page.evidence_id, **asdict(redirect))
                )
            for warning in page.warnings:
                values = asdict(warning)
                values["stable_code"] = values.pop("code")
                session.add(
                    CrawlPageParseWarningModel(
                        evidence_id=page.evidence_id,
                        created_at=page.created_at,
                        warning_version=PAGE_EVIDENCE_VERSION,
                        **values,
                    )
                )
        session.flush()
        _LOGGER.info(
            "page_evidence_batch_persisted job_id=%s run_id=%s batch_count=%d",
            job_id,
            run_id,
            min(configuration.batch_size, len(projection.pages) - start),
        )

    for start in range(0, len(projection.links), configuration.batch_size):
        for link in projection.links[start : start + configuration.batch_size]:
            session.add(CrawlLinkEvidenceModel(**asdict(link)))
        session.flush()
        _LOGGER.info(
            "link_evidence_batch_persisted job_id=%s run_id=%s batch_count=%d",
            job_id,
            run_id,
            min(configuration.batch_size, len(projection.links) - start),
        )

    for start in range(0, len(projection.images), configuration.batch_size):
        for image in projection.images[start : start + configuration.batch_size]:
            session.add(CrawlImageEvidenceModel(**asdict(image)))
        session.flush()
        _LOGGER.info(
            "image_evidence_batch_persisted job_id=%s run_id=%s batch_count=%d",
            job_id,
            run_id,
            min(configuration.batch_size, len(projection.images) - start),
        )

    pages = projection.pages
    status_counts = Counter(
        str(page.status_class) if page.status_class is not None else "missing" for page in pages
    )
    content_counts = Counter(page.content_type_category.value for page in pages)
    robots_counts = Counter(
        "allowed"
        if page.robots_allowed
        else "denied"
        if page.robots_allowed is False
        else "unavailable"
        for page in pages
    )
    indexability_counts = Counter(page.indexability_state.value for page in pages)
    summary_model = CrawlPageEvidenceSummaryModel(
        run_id=run_id,
        job_id=job_id,
        total_records=len(pages),
        completed_records=sum(page.evidence_state is PageEvidenceState.COMPLETE for page in pages),
        partial_records=sum(
            page.evidence_state
            in {PageEvidenceState.PARTIAL, PageEvidenceState.CANCELLED, PageEvidenceState.TRUNCATED}
            for page in pages
        ),
        failed_records=sum(page.evidence_state is PageEvidenceState.FETCH_FAILED for page in pages),
        html_records=sum(page.content_type_category is ContentTypeCategory.HTML for page in pages),
        non_html_records=sum(
            page.content_type_category
            not in {ContentTypeCategory.HTML, ContentTypeCategory.MISSING}
            for page in pages
        ),
        redirect_records=sum(page.redirect_count > 0 for page in pages),
        parse_warning_count=sum(page.parse_warning_count for page in pages),
        truncated_records=sum(page.value_truncated for page in pages),
        title_evidence_count=sum(
            page.title_presence in {MetadataPresence.SINGLE, MetadataPresence.MULTIPLE}
            for page in pages
        ),
        description_evidence_count=sum(
            page.description_presence in {MetadataPresence.SINGLE, MetadataPresence.MULTIPLE}
            for page in pages
        ),
        canonical_evidence_count=sum(
            page.canonical_presence in {MetadataPresence.SINGLE, MetadataPresence.MULTIPLE}
            for page in pages
        ),
        status_class_counts_json=json.dumps(status_counts, sort_keys=True, separators=(",", ":")),
        content_type_counts_json=json.dumps(content_counts, sort_keys=True, separators=(",", ":")),
        robots_permission_counts_json=json.dumps(
            robots_counts, sort_keys=True, separators=(",", ":")
        ),
        indexability_counts_json=json.dumps(
            indexability_counts, sort_keys=True, separators=(",", ":")
        ),
        source_page_count=projection.source_page_count,
        projection_truncated=projection.truncated,
        persisted_at=pages[0].created_at if pages else datetime.now(UTC),
        retention_state=PageEvidenceRetentionState.RETAINED.value,
        evidence_version=PAGE_EVIDENCE_VERSION,
        persistence_version=PAGE_EVIDENCE_PERSISTENCE_VERSION,
        ordering_version=PAGE_EVIDENCE_ORDERING,
    )
    session.add(summary_model)
    session.add(
        CrawlPageEvidenceEventModel(
            run_id=run_id,
            job_id=job_id,
            event_type="persisted",
            safe_reason_code=(
                PageEvidenceReasonCode.TRUNCATED.value if projection.truncated else None
            ),
            affected_count=len(pages),
            occurred_at=summary_model.persisted_at,
            event_version=PAGE_EVIDENCE_RETENTION_VERSION,
        )
    )
    session.flush()
    _LOGGER.info(
        "page_evidence_persistence_completed job_id=%s run_id=%s page_count=%d truncated=%s",
        job_id,
        run_id,
        len(pages),
        projection.truncated,
    )
    return _summary(summary_model)


class SQLAlchemyPageEvidenceRepository:
    """Dedicated bounded query, retention, and reconciliation authority."""

    def __init__(self, runtime: PersistenceRuntime) -> None:
        self._runtime = runtime
        self._configuration = runtime.configuration.page_evidence

    def persist_run_page_evidence(
        self, job_id: str, run_id: str, crawl: CrawlResult
    ) -> PageEvidenceSummary:
        if not self._configuration.enabled:
            raise ValueError(PageEvidenceReasonCode.DISABLED)
        with self._runtime.transaction() as session:
            return persist_projected_evidence(session, job_id, run_id, crawl, self._configuration)

    def get_summary(self, run_id: str) -> PageEvidenceSummary | None:
        with self._runtime.transaction() as session:
            value = session.get(CrawlPageEvidenceSummaryModel, run_id)
            return _summary(value) if value is not None else None

    def get_page(self, evidence_id: str) -> PageEvidenceListItem | None:
        with self._runtime.transaction() as session:
            value = session.get(CrawlPageEvidenceModel, evidence_id)
            return _item(value) if value is not None else None

    def list_pages(
        self,
        filters: PageEvidenceFilters,
        *,
        page_size: int | None = None,
        cursor: str | None = None,
    ) -> PageEvidencePage:
        size = page_size or self._configuration.default_page_size
        if not 1 <= size <= self._configuration.maximum_page_size:
            raise ValueError(PageEvidenceReasonCode.INVALID_PAGE_SIZE)
        fingerprint = filters.fingerprint()
        statement = select(CrawlPageEvidenceModel)
        criteria = _criteria(filters)
        if criteria:
            statement = statement.where(*criteria)
        if cursor:
            sequence, identity = decode_cursor(cursor, fingerprint)
            statement = statement.where(
                or_(
                    CrawlPageEvidenceModel.discovery_sequence > sequence,
                    and_(
                        CrawlPageEvidenceModel.discovery_sequence == sequence,
                        CrawlPageEvidenceModel.requested_url_identity > identity,
                    ),
                )
            )
        statement = statement.order_by(
            CrawlPageEvidenceModel.discovery_sequence,
            CrawlPageEvidenceModel.requested_url_identity,
        ).limit(size + 1)
        with self._runtime.transaction() as session:
            rows = tuple(session.scalars(statement))
        _LOGGER.info(
            "page_evidence_query_completed page_size=%d result_count=%d",
            size,
            min(len(rows), size),
        )
        selected = rows[:size]
        next_cursor = None
        if len(rows) > size and selected:
            last = selected[-1]
            next_cursor = encode_cursor(
                last.discovery_sequence, last.requested_url_identity, fingerprint
            )
        return PageEvidencePage(tuple(_item(row) for row in selected), next_cursor, size)

    def cleanup_expired(
        self, *, now: datetime | None = None, dry_run: bool = True
    ) -> PageEvidenceCleanupResult:
        current = now or datetime.now(UTC)
        terminal_states: tuple[str, ...] = (
            "completed",
            "completed_with_warnings",
            "partially_completed",
            "cancelled",
        )
        if not self._configuration.preserve_terminal_failures:
            terminal_states = (*terminal_states, "failed")
        with self._runtime.transaction() as session:
            ids = tuple(
                session.scalars(
                    select(CrawlPageEvidenceModel.evidence_id)
                    .join(RunModel, RunModel.run_id == CrawlPageEvidenceModel.run_id)
                    .where(
                        CrawlPageEvidenceModel.expires_at <= current,
                        CrawlPageEvidenceModel.retention_hold.is_(False),
                        RunModel.lifecycle.in_(terminal_states),
                    )
                    .order_by(CrawlPageEvidenceModel.expires_at, CrawlPageEvidenceModel.evidence_id)
                    .limit(self._configuration.cleanup_batch_size)
                )
            )
            if not dry_run and ids:
                run_ids = tuple(
                    session.scalars(
                        select(CrawlPageEvidenceModel.run_id)
                        .where(CrawlPageEvidenceModel.evidence_id.in_(ids))
                        .distinct()
                    )
                )
                session.execute(
                    delete(CrawlPageEvidenceModel).where(
                        CrawlPageEvidenceModel.evidence_id.in_(ids)
                    )
                )
                for run_id in run_ids:
                    summary = session.get(CrawlPageEvidenceSummaryModel, run_id)
                    if summary is not None:
                        summary.retention_state = PageEvidenceRetentionState.METADATA_ONLY.value
            _LOGGER.info(
                "page_evidence_cleanup_completed planned=%d deleted=%d dry_run=%s",
                len(ids),
                0 if dry_run else len(ids),
                dry_run,
            )
            return PageEvidenceCleanupResult(len(ids), 0 if dry_run else len(ids), dry_run)

    def set_retention_hold(self, run_id: str, *, held: bool) -> int:
        """Apply or release a durable hold without deleting evidence."""
        with self._runtime.transaction() as session:
            rows = tuple(
                session.scalars(
                    select(CrawlPageEvidenceModel).where(CrawlPageEvidenceModel.run_id == run_id)
                )
            )
            for row in rows:
                row.retention_hold = held
            _LOGGER.info(
                "page_evidence_retention_changed run_id=%s held=%s affected_count=%d",
                run_id,
                held,
                len(rows),
            )
            return len(rows)

    def diagnostics(self, *, now: datetime | None = None) -> PageEvidenceDiagnostics:
        """Return aggregate evidence readiness without exposing page content."""
        current = now or datetime.now(UTC)
        with self._runtime.transaction() as session:
            summaries = tuple(session.scalars(select(CrawlPageEvidenceSummaryModel)))
            retained = int(
                session.scalar(
                    select(func.count())
                    .select_from(CrawlPageEvidenceModel)
                    .where(
                        CrawlPageEvidenceModel.retention_state
                        == PageEvidenceRetentionState.RETAINED.value,
                        CrawlPageEvidenceModel.expires_at > current,
                    )
                )
                or 0
            )
            expired = int(
                session.scalar(
                    select(func.count())
                    .select_from(CrawlPageEvidenceModel)
                    .where(CrawlPageEvidenceModel.expires_at <= current)
                )
                or 0
            )
        return PageEvidenceDiagnostics(
            enabled=self._configuration.enabled,
            persistence_ready=True,
            runs_with_evidence=len(summaries),
            page_records=sum(item.total_records for item in summaries),
            partial_records=sum(item.partial_records for item in summaries),
            failed_records=sum(item.failed_records for item in summaries),
            html_records=sum(item.html_records for item in summaries),
            non_html_records=sum(item.non_html_records for item in summaries),
            truncated_records=sum(item.truncated_records for item in summaries),
            parse_warning_count=sum(item.parse_warning_count for item in summaries),
            retained_records=retained,
            expired_records=expired,
            cleanup_pending_records=0,
        )

    def reconcile(self, *, maximum_rows: int = 1_000) -> PageEvidenceReconciliationReport:
        if not 1 <= maximum_rows <= _MAX_RECONCILIATION_ROWS:
            raise ValueError(PageEvidenceReasonCode.RECONCILIATION_FAILED)
        reasons: list[str] = []
        inspected = 0
        with self._runtime.transaction() as session:
            summaries = tuple(
                session.scalars(
                    select(CrawlPageEvidenceSummaryModel)
                    .order_by(CrawlPageEvidenceSummaryModel.run_id)
                    .limit(maximum_rows + 1)
                )
            )
            for summary in summaries[:maximum_rows]:
                inspected += 1
                page_count = int(
                    session.scalar(
                        select(func.count())
                        .select_from(CrawlPageEvidenceModel)
                        .where(CrawlPageEvidenceModel.run_id == summary.run_id)
                    )
                    or 0
                )
                warning_count = int(
                    session.scalar(
                        select(func.count())
                        .select_from(CrawlPageParseWarningModel)
                        .join(CrawlPageEvidenceModel)
                        .where(CrawlPageEvidenceModel.run_id == summary.run_id)
                    )
                    or 0
                )
                if page_count != summary.total_records:
                    reasons.append("page_evidence_summary_count_mismatch")
                if warning_count > summary.parse_warning_count:
                    reasons.append("page_evidence_warning_count_mismatch")
                if summary.evidence_version != PAGE_EVIDENCE_VERSION:
                    reasons.append("page_evidence_version_mismatch")
        unique = tuple(dict.fromkeys(reasons))
        _LOGGER.info(
            "page_evidence_reconciliation_completed inspected=%d mismatch_count=%d truncated=%s",
            inspected,
            len(reasons),
            len(summaries) > maximum_rows,
        )
        return PageEvidenceReconciliationReport(
            inspected, len(reasons), unique, len(summaries) > maximum_rows
        )


def _criteria(filters: PageEvidenceFilters) -> list[ColumnElement[bool]]:
    criteria: list[ColumnElement[bool]] = []
    pairs = (
        (CrawlPageEvidenceModel.run_id, filters.run_id),
        (CrawlPageEvidenceModel.job_id, filters.job_id),
        (CrawlPageEvidenceModel.http_status, filters.http_status),
        (CrawlPageEvidenceModel.status_class, filters.status_class),
        (CrawlPageEvidenceModel.parsed_as_html, filters.parsed_as_html),
        (CrawlPageEvidenceModel.robots_allowed, filters.robots_allowed),
        (CrawlPageEvidenceModel.crawl_depth, filters.crawl_depth),
        (CrawlPageEvidenceModel.fetch_failed, filters.fetch_failed),
    )
    criteria.extend(column == value for column, value in pairs if value is not None)
    if filters.url_text:
        if len(filters.url_text) > _MAX_URL_FILTER_LENGTH:
            raise ValueError(PageEvidenceReasonCode.INVALID_FILTER)
        criteria.append(
            CrawlPageEvidenceModel.requested_url.contains(filters.url_text, autoescape=True)
        )
    if filters.content_type_category is not None:
        criteria.append(
            CrawlPageEvidenceModel.content_type_category == filters.content_type_category.value
        )
    if filters.evidence_state is not None:
        criteria.append(CrawlPageEvidenceModel.evidence_state == filters.evidence_state.value)
    if filters.indexability_state is not None:
        criteria.append(
            CrawlPageEvidenceModel.indexability_state == filters.indexability_state.value
        )
    if filters.redirected is not None:
        criteria.append(
            CrawlPageEvidenceModel.redirect_count > 0
            if filters.redirected
            else CrawlPageEvidenceModel.redirect_count == 0
        )
    if filters.has_parse_warnings is not None:
        criteria.append(
            CrawlPageEvidenceModel.parse_warning_count > 0
            if filters.has_parse_warnings
            else CrawlPageEvidenceModel.parse_warning_count == 0
        )
    for presence, column in (
        (filters.has_title, CrawlPageEvidenceModel.title_presence),
        (filters.has_description, CrawlPageEvidenceModel.description_presence),
        (filters.has_canonical, CrawlPageEvidenceModel.canonical_presence),
    ):
        if presence is not None:
            criteria.append(
                column.in_(("single", "multiple"))
                if presence
                else column.in_(("missing", "empty", "unavailable"))
            )
    return criteria


def _item(row: CrawlPageEvidenceModel) -> PageEvidenceListItem:
    return PageEvidenceListItem(
        evidence_id=row.evidence_id,
        job_id=row.job_id,
        run_id=row.run_id,
        requested_url=row.requested_url,
        final_url=row.final_url,
        discovery_sequence=row.discovery_sequence,
        crawl_depth=row.crawl_depth,
        fetch_outcome=row.fetch_outcome,
        http_status=row.http_status,
        redirect_count=row.redirect_count,
        content_type=row.content_type,
        content_type_category=ContentTypeCategory(row.content_type_category),
        parsed_as_html=row.parsed_as_html,
        title_presence=MetadataPresence(row.title_presence),
        title_value=row.title_value,
        description_presence=MetadataPresence(row.description_presence),
        canonical_presence=MetadataPresence(row.canonical_presence),
        canonical_url=row.canonical_url,
        robots_allowed=row.robots_allowed,
        robots_reason_code=row.robots_reason_code,
        indexability_evidence_json=row.indexability_evidence_json,
        indexability_state=IndexabilityEvidenceState(row.indexability_state),
        parse_warning_count=row.parse_warning_count,
        evidence_state=PageEvidenceState(row.evidence_state),
        value_truncated=row.value_truncated,
        persisted_at=row.persisted_at,
        evidence_version=row.evidence_version,
    )


def _summary(row: CrawlPageEvidenceSummaryModel) -> PageEvidenceSummary:
    return PageEvidenceSummary(
        run_id=row.run_id,
        job_id=row.job_id,
        total_records=row.total_records,
        completed_records=row.completed_records,
        partial_records=row.partial_records,
        failed_records=row.failed_records,
        html_records=row.html_records,
        non_html_records=row.non_html_records,
        redirect_records=row.redirect_records,
        parse_warning_count=row.parse_warning_count,
        truncated_records=row.truncated_records,
        title_evidence_count=row.title_evidence_count,
        description_evidence_count=row.description_evidence_count,
        canonical_evidence_count=row.canonical_evidence_count,
        status_class_counts_json=row.status_class_counts_json,
        content_type_counts_json=row.content_type_counts_json,
        robots_permission_counts_json=row.robots_permission_counts_json,
        indexability_counts_json=row.indexability_counts_json,
        source_page_count=row.source_page_count,
        projection_truncated=row.projection_truncated,
        persisted_at=row.persisted_at,
        retention_state=PageEvidenceRetentionState(row.retention_state),
    )
