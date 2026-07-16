"""Run request, lifecycle, identity, progress, and summary contracts."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import create_scope_policy
from musimack_tools.domain.crawl import CrawlRequest
from musimack_tools.domain.run import (
    CRAWL_RUN_ORCHESTRATION_VERSION,
    CrawlRunRequest,
    CrawlRunResult,
    RunConfigurationSnapshot,
    RunLifecycle,
    RunStage,
    RunStageRecord,
    RunStageState,
    validate_stage_transition,
)
from musimack_tools.domain.run_summary import (
    CRAWL_RUN_SUMMARY_SCHEMA_VERSION,
    RunSummaryConfiguration,
)
from musimack_tools.domain.sitemap import RecommendationPolicy
from musimack_tools.domain.sitemap_publication import SitemapPublicationConfiguration
from musimack_tools.run.identity import (
    canonical_identity_bytes,
    configuration_snapshot,
    run_identity,
)
from musimack_tools.run.progress import NoOpRunProgressSink, RecordingRunProgressSink
from musimack_tools.run.summary import serialize_summaries
from musimack_tools.sitemap.limits import SitemapXmlConfiguration

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _request(  # noqa: PLR0913 - explicit knobs exercise identity inputs.
    *,
    seed: str = "https://example.com/",
    stages: tuple[RunStage, ...] = (RunStage.CRAWL,),
    publication_root: Path | None = None,
    summary_root: Path | None = None,
    caller_label: str | None = None,
    maximum_urls: int = 50,
) -> CrawlRunRequest:
    normalized = normalize_url(seed)
    return CrawlRunRequest(
        crawl_request=CrawlRequest(
            normalized,
            create_scope_policy(normalized),
            maximum_unique_urls=maximum_urls,
        ),
        requested_stages=stages,
        publication_configuration=(
            SitemapPublicationConfiguration(publication_root)
            if publication_root is not None
            else None
        ),
        summary_configuration=(
            RunSummaryConfiguration(summary_root) if summary_root is not None else None
        ),
        caller_label=caller_label,
    )


def _result(request: CrawlRunRequest) -> CrawlRunResult:
    display, digest = run_identity(request)
    return CrawlRunResult(
        run_id=display,
        run_digest=digest,
        caller_label=request.caller_label,
        lifecycle=RunLifecycle.COMPLETED,
        stages=tuple(
            RunStageRecord(
                stage,
                RunStageState.COMPLETED
                if stage in request.requested_stages
                else RunStageState.NOT_REQUESTED,
            )
            for stage in RunStage
        ),
        configuration=configuration_snapshot(request),
    )


@pytest.mark.parametrize(
    "stages",
    [
        (RunStage.CRAWL,),
        (RunStage.CRAWL, RunStage.WRITE_SUMMARY),
        (RunStage.CRAWL, RunStage.RECOMMEND),
        (RunStage.CRAWL, RunStage.RECOMMEND, RunStage.GENERATE_XML),
    ],
)
def test_valid_stage_combinations(stages: tuple[RunStage, ...]) -> None:
    assert _request(stages=stages).requested_stages == stages


@pytest.mark.parametrize(
    "stages",
    [
        (),
        (RunStage.CRAWL, RunStage.CRAWL),
        (RunStage.RECOMMEND,),
        (RunStage.WRITE_SUMMARY,),
        (RunStage.RECOMMEND, RunStage.CRAWL),
        (RunStage.CRAWL, RunStage.GENERATE_XML),
        (RunStage.CRAWL, RunStage.RECOMMEND, RunStage.PUBLISH),
    ],
)
def test_invalid_stage_combinations_are_rejected(stages: tuple[RunStage, ...]) -> None:
    with pytest.raises(ValueError):
        _request(stages=stages)


def test_full_request_requires_and_accepts_publication_configuration(tmp_path: Path) -> None:
    stages = (
        RunStage.CRAWL,
        RunStage.RECOMMEND,
        RunStage.GENERATE_XML,
        RunStage.PUBLISH,
        RunStage.WRITE_SUMMARY,
    )
    assert _request(stages=stages, publication_root=tmp_path).requested_stages == stages


def test_request_and_nested_stage_tuple_are_immutable() -> None:
    request = _request()
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.caller_label = "changed"  # type: ignore[misc]


def test_orchestration_version_is_exact_and_rejects_other_versions() -> None:
    assert _request().orchestration_version == CRAWL_RUN_ORCHESTRATION_VERSION
    with pytest.raises(ValueError, match="unsupported"):
        replace(_request(), orchestration_version="future")


@pytest.mark.parametrize(
    ("current", "following"),
    [
        (RunStageState.PENDING, RunStageState.RUNNING),
        (RunStageState.RUNNING, RunStageState.COMPLETED),
        (RunStageState.RUNNING, RunStageState.COMPLETED_WITH_WARNINGS),
        (RunStageState.PENDING, RunStageState.BLOCKED),
    ],
)
def test_valid_stage_transitions(current: RunStageState, following: RunStageState) -> None:
    validate_stage_transition(current, following)


@pytest.mark.parametrize(
    ("current", "following"),
    [
        (RunStageState.NOT_REQUESTED, RunStageState.RUNNING),
        (RunStageState.COMPLETED, RunStageState.RUNNING),
        (RunStageState.FAILED, RunStageState.COMPLETED),
        (RunStageState.PENDING, RunStageState.COMPLETED),
    ],
)
def test_invalid_stage_transitions_are_rejected(
    current: RunStageState,
    following: RunStageState,
) -> None:
    with pytest.raises(ValueError, match="invalid run stage transition"):
        validate_stage_transition(current, following)


def test_same_request_has_same_lowercase_sha256_identity() -> None:
    first = run_identity(_request())
    second = run_identity(_request())
    assert first == second
    assert re.fullmatch(r"run-[0-9a-f]{12}", first[0])
    assert re.fullmatch(r"[0-9a-f]{64}", first[1])
    assert first[1] == hashlib.sha256(canonical_identity_bytes(_request())).hexdigest()


@pytest.mark.parametrize(
    "changed",
    [
        _request(seed="https://example.com/changed"),
        _request(maximum_urls=51),
        _request(stages=(RunStage.CRAWL, RunStage.WRITE_SUMMARY)),
        replace(
            _request(),
            recommendation_policy=RecommendationPolicy(missing_canonical_requires_review=True),
        ),
        replace(
            _request(), xml_configuration=SitemapXmlConfiguration(url_entries_per_document_limit=10)
        ),
    ],
)
def test_meaningful_request_changes_identity(changed: CrawlRunRequest) -> None:
    assert run_identity(changed) != run_identity(_request())


def test_output_roots_and_caller_label_do_not_leak_into_portable_identity(tmp_path: Path) -> None:
    stages = (RunStage.CRAWL, RunStage.RECOMMEND, RunStage.GENERATE_XML, RunStage.PUBLISH)
    first = _request(stages=stages, publication_root=tmp_path / "one", caller_label="one")
    second = _request(stages=stages, publication_root=tmp_path / "two", caller_label="two")
    assert run_identity(first) == run_identity(second)
    assert str(tmp_path).encode() not in canonical_identity_bytes(first)


def test_safe_snapshot_has_no_output_path_or_caller_label(tmp_path: Path) -> None:
    snapshot = configuration_snapshot(
        _request(publication_root=tmp_path, caller_label="private-label")
    )
    encoded = repr(snapshot)
    assert str(tmp_path) not in encoded
    assert "private-label" not in encoded
    assert snapshot.normalized_seed_url == "https://example.com/"


def test_summary_json_is_deterministic_utf8_sorted_and_final_newline() -> None:
    artifacts = serialize_summaries(_result(_request(caller_label="Müsic")))
    json_artifact = artifacts[0]
    assert json_artifact.content.endswith(b"\n")
    payload = json.loads(json_artifact.content)
    assert payload["schema_version"] == CRAWL_RUN_SUMMARY_SCHEMA_VERSION
    assert payload["caller_label"] == "Müsic"
    assert serialize_summaries(_result(_request(caller_label="Müsic"))) == artifacts
    assert json_artifact.sha256 == hashlib.sha256(json_artifact.content).hexdigest()


def test_summary_markdown_has_required_sections_and_no_timestamp() -> None:
    markdown = serialize_summaries(_result(_request()))[1].content.decode()
    for heading in (
        "# Crawl Run Summary",
        "## Stages",
        "## Counts",
        "## Publication",
        "## Warnings",
        "## Failures",
        "## Versions",
        "## Safe Configuration",
    ):
        assert heading in markdown
    assert "timestamp" not in markdown.casefold()
    assert markdown.endswith("\n")


@pytest.mark.anyio
async def test_noop_and_recording_progress_sinks() -> None:
    noop = NoOpRunProgressSink()
    recording = RecordingRunProgressSink()
    assert recording.events == ()
    assert noop is not None


def test_configuration_snapshot_is_frozen() -> None:
    snapshot = configuration_snapshot(_request())
    assert isinstance(snapshot, RunConfigurationSnapshot)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.scope_mode = "changed"  # type: ignore[misc]
