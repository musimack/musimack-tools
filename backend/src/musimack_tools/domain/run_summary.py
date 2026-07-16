"""Immutable run-summary serialization and local-writing contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from musimack_tools.domain.sitemap_publication import ExistingFilePolicy

if TYPE_CHECKING:
    from pathlib import Path

CRAWL_RUN_SUMMARY_SCHEMA_VERSION = "crawl-run-summary-v1"
RUN_SUMMARY_JSON_NAME = "run-summary.json"
RUN_SUMMARY_MARKDOWN_NAME = "run-summary.md"


class RunSummaryFormat(StrEnum):
    JSON = "json"
    MARKDOWN = "markdown"


class RunSummaryWriteState(StrEnum):
    NOT_REQUESTED = "not_requested"
    DRY_RUN = "dry_run"
    WRITTEN = "written"
    BLOCKED = "blocked"
    PARTIALLY_FAILED = "partially_failed"


@dataclass(frozen=True, slots=True)
class RunSummaryConfiguration:
    output_root: Path
    existing_file_policy: ExistingFilePolicy = ExistingFilePolicy.FAIL_IF_EXISTS
    create_output_directory: bool = False
    dry_run: bool = False


@dataclass(frozen=True, slots=True)
class RunSummaryArtifact:
    logical_name: str
    format: RunSummaryFormat
    content: bytes
    byte_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class RunSummaryWriteFailure:
    code: str
    explanation: str
    logical_name: str | None = None


@dataclass(frozen=True, slots=True)
class RunSummaryWrittenFile:
    logical_name: str
    byte_count: int
    sha256: str
    replaced_existing: bool


@dataclass(frozen=True, slots=True)
class RunSummaryWriteResult:
    state: RunSummaryWriteState
    written_files: tuple[RunSummaryWrittenFile, ...]
    failures: tuple[RunSummaryWriteFailure, ...]
