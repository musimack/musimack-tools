"""Immutable progress evidence for internal crawl runs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from musimack_tools.domain.crawl import ProgressSnapshot
    from musimack_tools.domain.run import RunLifecycle, RunStage, RunStageState


class RunEventCode(StrEnum):
    RUN_ACCEPTED = "run_accepted"
    RUN_STARTED = "run_started"
    STAGE_STARTED = "stage_started"
    CRAWL_PROGRESS = "crawl_progress"
    STAGE_COMPLETED = "stage_completed"
    STAGE_BLOCKED = "stage_blocked"
    STAGE_CANCELLED = "stage_cancelled"
    STAGE_FAILED = "stage_failed"
    CANCELLATION_OBSERVED = "cancellation_observed"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"


@dataclass(frozen=True, slots=True)
class RunProgressSnapshot:
    lifecycle: RunLifecycle
    active_stage: RunStage | None
    stage_state: RunStageState | None
    crawl_progress: ProgressSnapshot | None = None
    urls_discovered: int = 0
    urls_queued: int = 0
    urls_fetched: int = 0
    urls_parsed: int = 0
    bytes_fetched: int = 0
    queue_size: int = 0
    active_count: int = 0
    current_depth: int | None = None
    recommendation_counts: tuple[int, int, int, int] | None = None
    xml_document_count: int | None = None
    xml_entry_count: int | None = None
    publication_file_count: int | None = None
    warning_count: int = 0
    failure_count: int = 0
    cancellation_requested: bool = False
    recent_crawl_error_code: str | None = None
    elapsed_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class RunProgressEvent:
    sequence: int
    code: RunEventCode
    snapshot: RunProgressSnapshot
    explanation: str
