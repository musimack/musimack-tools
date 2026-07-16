"""Restart, query, retention, reconciliation, and terminal-observer tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from musimack_tools.application.page_evidence import PageEvidenceService
from musimack_tools.domain.job import JobState
from musimack_tools.domain.page_evidence import (
    ContentTypeCategory,
    IndexabilityEvidenceState,
    PageEvidenceConfiguration,
    PageEvidenceFilters,
    PageEvidenceReasonCode,
)
from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.migrations import upgrade_to_head
from musimack_tools.persistence.page_evidence_repository import SQLAlchemyPageEvidenceRepository
from musimack_tools.persistence.repositories import SQLAlchemyPersistenceRepository
from page_evidence_helpers import PageRecordOptions, crawl_result, page_record
from persistence_helpers import (
    BACKEND_ROOT,
    sample_request,
    sample_result,
    sample_snapshot,
)

if TYPE_CHECKING:
    from pathlib import Path

    from musimack_tools.domain.job import JobSnapshot
    from musimack_tools.domain.run import CrawlRunRequest
    from musimack_tools.persistence.engine import PersistenceRuntime


def _configuration(path: Path) -> PersistenceConfiguration:
    return PersistenceConfiguration(
        enabled=True,
        database_path=path,
        page_evidence=PageEvidenceConfiguration(
            enabled=True, default_page_size=1, maximum_page_size=10
        ),
    )


def _runtime(
    tmp_path: Path,
) -> tuple[PersistenceRuntime, PersistenceConfiguration, CrawlRunRequest, JobSnapshot]:
    path = tmp_path / "page-evidence.db"
    upgrade_to_head(f"sqlite+pysqlite:///{path.as_posix()}", backend_root=BACKEND_ROOT)
    configuration = _configuration(path)
    runtime = create_persistence_runtime(configuration)
    request = sample_request()
    snapshot = sample_snapshot(request)
    assert SQLAlchemyPersistenceRepository(runtime).record_submission(snapshot, request).succeeded
    return runtime, configuration, request, snapshot


def test_persistence_is_idempotent_and_restart_safe(tmp_path: Path) -> None:
    runtime, configuration, _request, snapshot = _runtime(tmp_path)
    crawl = crawl_result(
        (
            page_record(),
            page_record("https://example.com/about", PageRecordOptions(discovery_order=1)),
        )
    )
    repository = SQLAlchemyPageEvidenceRepository(runtime)
    summary = repository.persist_run_page_evidence(snapshot.job_id, snapshot.run_id, crawl)
    repeated = repository.persist_run_page_evidence(snapshot.job_id, snapshot.run_id, crawl)
    assert summary.total_records == repeated.total_records == 2
    assert summary.run_id == repeated.run_id
    runtime.dispose()
    restarted = create_persistence_runtime(configuration)
    try:
        pages = SQLAlchemyPageEvidenceRepository(restarted).list_pages(
            PageEvidenceFilters(run_id=snapshot.run_id), page_size=10
        )
        assert [item.requested_url for item in pages.items] == [
            "https://example.com/",
            "https://example.com/about",
        ]
    finally:
        restarted.dispose()


def test_terminal_observer_persists_before_payload_eviction(tmp_path: Path) -> None:
    runtime, _configuration_value, request, snapshot = _runtime(tmp_path)
    try:
        result = replace(sample_result(request), crawl_result=crawl_result((page_record(),)))
        terminal = replace(
            snapshot,
            state=JobState.COMPLETED,
            run_lifecycle=result.lifecycle,
            final_result_available=True,
            terminal=True,
        )
        outcome = SQLAlchemyPersistenceRepository(runtime).record_terminal(
            terminal, result, (), None
        )
        assert outcome.succeeded
        stored = SQLAlchemyPageEvidenceRepository(runtime).list_pages(
            PageEvidenceFilters(run_id=snapshot.run_id)
        )
        assert len(stored.items) == 1
    finally:
        runtime.dispose()


def test_filters_and_cursor_pagination_are_stable(tmp_path: Path) -> None:
    runtime, _configuration_value, _request, snapshot = _runtime(tmp_path)
    try:
        crawl = crawl_result(
            (
                page_record(options=PageRecordOptions(discovery_order=0)),
                page_record(
                    "https://example.com/report.pdf",
                    PageRecordOptions(body=None, content_type="application/pdf", discovery_order=1),
                ),
            )
        )
        repository = SQLAlchemyPageEvidenceRepository(runtime)
        repository.persist_run_page_evidence(snapshot.job_id, snapshot.run_id, crawl)
        first = repository.list_pages(PageEvidenceFilters(run_id=snapshot.run_id), page_size=1)
        second = repository.list_pages(
            PageEvidenceFilters(run_id=snapshot.run_id), page_size=1, cursor=first.next_cursor
        )
        assert len(first.items) == len(second.items) == 1
        pdf = repository.list_pages(
            PageEvidenceFilters(
                run_id=snapshot.run_id, content_type_category=ContentTypeCategory.PDF
            ),
            page_size=10,
        )
        assert len(pdf.items) == 1 and pdf.items[0].requested_url.endswith("report.pdf")
        unavailable = repository.list_pages(
            PageEvidenceFilters(
                run_id=snapshot.run_id,
                indexability_state=IndexabilityEvidenceState.UNAVAILABLE,
            ),
            page_size=10,
        )
        assert [item.requested_url for item in unavailable.items] == [
            "https://example.com/report.pdf"
        ]
    finally:
        runtime.dispose()


def test_invalid_page_size_is_rejected(tmp_path: Path) -> None:
    runtime, _configuration_value, _request, _snapshot = _runtime(tmp_path)
    try:
        repository = SQLAlchemyPageEvidenceRepository(runtime)
        try:
            repository.list_pages(PageEvidenceFilters(), page_size=11)
        except ValueError as error:
            assert str(PageEvidenceReasonCode.INVALID_PAGE_SIZE) in str(error)
        else:
            pytest.fail("invalid page size was accepted")
    finally:
        runtime.dispose()


def test_cleanup_is_dry_run_bounded_and_preserves_summary(tmp_path: Path) -> None:
    runtime, _configuration_value, request, snapshot = _runtime(tmp_path)
    try:
        repository = SQLAlchemyPageEvidenceRepository(runtime)
        repository.persist_run_page_evidence(
            snapshot.job_id, snapshot.run_id, crawl_result((page_record(),))
        )
        future = datetime.now(UTC) + timedelta(days=181)
        assert repository.cleanup_expired(now=future).planned == 0
        result = sample_result(request)
        terminal = replace(
            snapshot,
            state=JobState.COMPLETED,
            run_lifecycle=result.lifecycle,
            final_result_available=True,
            terminal=True,
        )
        assert (
            SQLAlchemyPersistenceRepository(runtime)
            .record_terminal(terminal, result, (), None)
            .succeeded
        )
        planned = repository.cleanup_expired(now=future)
        assert planned.planned == 1 and planned.deleted == 0
        executed = repository.cleanup_expired(now=future, dry_run=False)
        assert executed.deleted == 1
        assert repository.get_summary(snapshot.run_id) is not None
    finally:
        runtime.dispose()


def test_reconciliation_is_read_only_and_idempotent(tmp_path: Path) -> None:
    runtime, _configuration_value, _request, snapshot = _runtime(tmp_path)
    try:
        repository = SQLAlchemyPageEvidenceRepository(runtime)
        repository.persist_run_page_evidence(
            snapshot.job_id, snapshot.run_id, crawl_result((page_record(),))
        )
        assert repository.reconcile() == repository.reconcile()
        assert repository.reconcile().mismatched == 0
    finally:
        runtime.dispose()


def test_retention_hold_blocks_cleanup_and_release_restores_it(tmp_path: Path) -> None:
    runtime, _configuration_value, request, snapshot = _runtime(tmp_path)
    try:
        repository = SQLAlchemyPageEvidenceRepository(runtime)
        repository.persist_run_page_evidence(
            snapshot.job_id, snapshot.run_id, crawl_result((page_record(),))
        )
        result = sample_result(request)
        terminal = replace(
            snapshot,
            state=JobState.COMPLETED,
            run_lifecycle=result.lifecycle,
            final_result_available=True,
            terminal=True,
        )
        assert (
            SQLAlchemyPersistenceRepository(runtime)
            .record_terminal(terminal, result, (), None)
            .succeeded
        )
        future = datetime.now(UTC) + timedelta(days=181)
        assert repository.set_retention_hold(snapshot.run_id, held=True) == 1
        assert repository.cleanup_expired(now=future).planned == 0
        assert repository.set_retention_hold(snapshot.run_id, held=False) == 1
        assert repository.cleanup_expired(now=future).planned == 1
    finally:
        runtime.dispose()


def test_service_and_diagnostics_expose_only_aggregates(tmp_path: Path) -> None:
    runtime, _configuration_value, _request, snapshot = _runtime(tmp_path)
    try:
        service = PageEvidenceService(SQLAlchemyPageEvidenceRepository(runtime))
        service.persist_crawl_result(
            snapshot.job_id, snapshot.run_id, crawl_result((page_record(),))
        )
        assert service.get_run_evidence_summary(snapshot.run_id) is not None
        assert len(service.list_run_pages(snapshot.run_id).items) == 1
        diagnostics = service.get_diagnostics()
        assert diagnostics.enabled and diagnostics.page_records == 1
        assert not hasattr(diagnostics, "url") and not hasattr(diagnostics, "title")
    finally:
        runtime.dispose()
