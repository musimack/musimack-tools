"""Application service for durable page-level crawl evidence."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from musimack_tools.domain.page_evidence import (
    PageEvidenceCleanupResult,
    PageEvidenceDiagnostics,
    PageEvidenceFilters,
    PageEvidenceListItem,
    PageEvidencePage,
    PageEvidenceReconciliationReport,
    PageEvidenceSummary,
)

if TYPE_CHECKING:
    from datetime import datetime

    from musimack_tools.domain.crawl import CrawlResult
    from musimack_tools.persistence.page_evidence_repository import (
        SQLAlchemyPageEvidenceRepository,
    )


class PageEvidenceService:
    """Typed boundary for persistence, queries, retention, and diagnostics."""

    def __init__(self, repository: SQLAlchemyPageEvidenceRepository) -> None:
        self._repository = repository

    def persist_crawl_result(
        self, job_id: str, run_id: str, crawl: CrawlResult
    ) -> PageEvidenceSummary:
        return self._repository.persist_run_page_evidence(job_id, run_id, crawl)

    def get_run_evidence_summary(self, run_id: str) -> PageEvidenceSummary | None:
        return self._repository.get_summary(run_id)

    def list_run_pages(
        self,
        run_id: str,
        *,
        page_size: int | None = None,
        cursor: str | None = None,
        filters: PageEvidenceFilters | None = None,
    ) -> PageEvidencePage:
        selected = filters or PageEvidenceFilters()
        if selected.run_id not in {None, run_id}:
            raise ValueError("page_evidence_invalid_filter")
        selected = replace(selected, run_id=run_id)
        return self._repository.list_pages(selected, page_size=page_size, cursor=cursor)

    def get_run_page(self, evidence_id: str) -> PageEvidenceListItem | None:
        return self._repository.get_page(evidence_id)

    def cleanup_expired_evidence(
        self, *, now: datetime | None = None, dry_run: bool = True
    ) -> PageEvidenceCleanupResult:
        return self._repository.cleanup_expired(now=now, dry_run=dry_run)

    def reconcile_evidence_counts(
        self, *, maximum_rows: int = 1_000
    ) -> PageEvidenceReconciliationReport:
        return self._repository.reconcile(maximum_rows=maximum_rows)

    def get_diagnostics(self) -> PageEvidenceDiagnostics:
        return self._repository.diagnostics()
