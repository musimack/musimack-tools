"""Bounded history service with deterministic versioned cursor pagination."""

# ruff: noqa: TRY300, TRY301 - cursor parsing keeps safe typed failures adjacent.

from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from musimack_tools.domain.history import (
    HISTORY_JOB_ORDERING,
    HISTORY_PAGINATION_VERSION,
    HISTORY_RUN_ORDERING,
    HistoricalArtifact,
    HistoricalAttempt,
    HistoricalJob,
    HistoricalMessage,
    HistoricalRun,
    HistoricalStage,
    HistoryConfiguration,
    HistoryDiagnostics,
    HistoryError,
    HistoryFailureCode,
    HistoryPage,
    HistoryPageRequest,
    JobHistoryFilter,
    RelatedHistory,
    RunHistoryFilter,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from musimack_tools.persistence.history_repository import SQLAlchemyHistoryRepository

_LOGGER = logging.getLogger("musimack_tools.history")
_CURSOR_FORMAT = "history-cursor-v1"


class HistoryService:
    """Application service whose correctness depends only on durable repository state."""

    def __init__(
        self,
        configuration: HistoryConfiguration,
        repository: SQLAlchemyHistoryRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.configuration = configuration
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))
        self._last_successful_query_at: datetime | None = None
        self._last_failure_reason: str | None = None

    def list_jobs(
        self, filters: JobHistoryFilter, request: HistoryPageRequest
    ) -> HistoryPage[HistoricalJob]:
        page_size = self._page_size(request.page_size)
        after = self._decode_cursor(
            request.cursor, "jobs", filters.canonical(), HISTORY_JOB_ORDERING
        )
        try:
            rows = self._repository.list_jobs(filters, page_size + 1, after)
            page = self._page(rows, page_size, "jobs", filters.canonical(), HISTORY_JOB_ORDERING)
            self._success("history_job_list", page.returned_count, page_size)
            return page
        except HistoryError as error:
            self._failure(error.code)
            raise

    def get_job(self, job_id: str) -> HistoricalJob:
        self._require_enabled()
        item = self._repository.get_job(job_id)
        if item is None:
            self._failure(HistoryFailureCode.JOB_NOT_FOUND)
            raise HistoryError(
                HistoryFailureCode.JOB_NOT_FOUND, "The historical job was not found."
            )
        self._success("history_job_detail", 1, None)
        return item

    def list_runs(
        self, filters: RunHistoryFilter, request: HistoryPageRequest
    ) -> HistoryPage[HistoricalRun]:
        page_size = self._page_size(request.page_size)
        after = self._decode_cursor(
            request.cursor, "runs", filters.canonical(), HISTORY_RUN_ORDERING
        )
        try:
            rows = self._repository.list_runs(filters, page_size + 1, after)
            page = self._page(rows, page_size, "runs", filters.canonical(), HISTORY_RUN_ORDERING)
            self._success("history_run_list", page.returned_count, page_size)
            return page
        except HistoryError as error:
            self._failure(error.code)
            raise

    def get_run(self, run_id: str) -> HistoricalRun:
        self._require_enabled()
        item = self._repository.get_run(run_id)
        if item is None:
            self._failure(HistoryFailureCode.RUN_NOT_FOUND)
            raise HistoryError(
                HistoryFailureCode.RUN_NOT_FOUND, "The historical run was not found."
            )
        self._success("history_run_detail", 1, None)
        return item

    def attempts(self, job_id: str) -> RelatedHistory[HistoricalAttempt]:
        self.get_job(job_id)
        maximum = self.configuration.maximum_attempts_per_job
        items = self._repository.attempts(job_id, maximum + 1)
        return _related(items, maximum)

    def stages(self, run_id: str) -> RelatedHistory[HistoricalStage]:
        self.get_run(run_id)
        maximum = self.configuration.maximum_stages_per_run
        return _related(self._repository.stages(run_id, maximum + 1), maximum)

    def warnings(self, run_id: str) -> RelatedHistory[HistoricalMessage]:
        self.get_run(run_id)
        maximum = self.configuration.maximum_warnings_per_run
        return _related(self._repository.warnings(run_id, maximum + 1), maximum)

    def failures(self, run_id: str) -> RelatedHistory[HistoricalMessage]:
        self.get_run(run_id)
        maximum = self.configuration.maximum_failures_per_run
        return _related(self._repository.failures(run_id, maximum + 1), maximum)

    def artifacts(self, run_id: str) -> RelatedHistory[HistoricalArtifact]:
        self.get_run(run_id)
        maximum = self.configuration.maximum_artifacts_per_run
        return _related(self._repository.artifacts(run_id, maximum + 1), maximum)

    def diagnostics(self) -> HistoryDiagnostics:
        return self._repository.diagnostics(
            enabled=self.configuration.enabled,
            default_page_size=self.configuration.default_page_size,
            maximum_page_size=self.configuration.maximum_page_size,
            last_successful_query_at=self._last_successful_query_at,
            last_failure_reason=self._last_failure_reason,
        )

    def _page_size(self, requested: int) -> int:
        self._require_enabled()
        if requested < 1 or requested > self.configuration.maximum_page_size:
            self._failure(HistoryFailureCode.INVALID_PAGE_SIZE)
            raise HistoryError(
                HistoryFailureCode.INVALID_PAGE_SIZE,
                "The history page size is outside configured bounds.",
            )
        return requested

    def _require_enabled(self) -> None:
        if not self.configuration.enabled:
            raise HistoryError(HistoryFailureCode.DISABLED, "Durable history is disabled.")

    def _page[T](
        self,
        rows: tuple[tuple[T, int, str], ...],
        page_size: int,
        kind: str,
        filters: tuple[tuple[str, str], ...],
        ordering: str,
    ) -> HistoryPage[T]:
        has_more = len(rows) > page_size
        visible = rows[:page_size]
        next_cursor = None
        if has_more and visible:
            _, sequence, identifier = visible[-1]
            next_cursor = self._encode_cursor(kind, filters, ordering, sequence, identifier)
        items = tuple(row[0] for row in visible)
        return HistoryPage(
            items=items,
            page_size=page_size,
            returned_count=len(items),
            has_more=has_more,
            next_cursor=next_cursor,
            applied_filters=filters,
            ordering=ordering,
        )

    def _encode_cursor(
        self,
        kind: str,
        filters: tuple[tuple[str, str], ...],
        ordering: str,
        sequence: int,
        identifier: str,
    ) -> str:
        value = {
            "format": _CURSOR_FORMAT,
            "version": HISTORY_PAGINATION_VERSION,
            "kind": kind,
            "filter": _fingerprint(filters),
            "ordering": ordering,
            "sequence": sequence,
            "identifier": identifier,
        }
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    def _decode_cursor(
        self,
        cursor: str | None,
        kind: str,
        filters: tuple[tuple[str, str], ...],
        ordering: str,
    ) -> tuple[int, str] | None:
        if cursor is None:
            return None
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            value = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")), parse_int=int)
            if not isinstance(value, dict) or value.get("format") != _CURSOR_FORMAT:
                raise ValueError
            if value.get("version") != HISTORY_PAGINATION_VERSION:
                raise HistoryError(
                    HistoryFailureCode.CURSOR_VERSION_UNSUPPORTED,
                    "The history cursor version is unsupported.",
                )
            if value.get("kind") != kind or value.get("filter") != _fingerprint(filters):
                raise HistoryError(
                    HistoryFailureCode.CURSOR_FILTER_MISMATCH,
                    "The history cursor does not match the requested filters.",
                )
            if value.get("ordering") != ordering:
                raise HistoryError(
                    HistoryFailureCode.CURSOR_ORDER_MISMATCH,
                    "The history cursor does not match the requested ordering.",
                )
            sequence = value.get("sequence")
            identifier = value.get("identifier")
            if not isinstance(sequence, int) or sequence < 0 or not isinstance(identifier, str):
                raise ValueError
            return sequence, identifier
        except HistoryError:
            raise
        except ValueError, TypeError, UnicodeError, json.JSONDecodeError:
            self._failure(HistoryFailureCode.INVALID_CURSOR)
            raise HistoryError(
                HistoryFailureCode.INVALID_CURSOR, "The history cursor is invalid."
            ) from None

    def _success(self, event: str, returned: int, page_size: int | None) -> None:
        self._last_successful_query_at = self._clock()
        self._last_failure_reason = None
        _LOGGER.info(event, extra={"returned_count": returned, "page_size": page_size})

    def _failure(self, code: HistoryFailureCode) -> None:
        self._last_failure_reason = code.value
        _LOGGER.warning("history_query_rejected", extra={"reason_code": code.value})


def _fingerprint(filters: tuple[tuple[str, str], ...]) -> str:
    raw = json.dumps(filters, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def _related[T](items: tuple[T, ...], maximum: int) -> RelatedHistory[T]:
    visible = items[:maximum]
    return RelatedHistory(visible, len(visible), len(items) > maximum, maximum)
