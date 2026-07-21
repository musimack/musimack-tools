"""Immutable contracts for one internal crawl-to-publication run."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from musimack_tools.domain.sitemap import RecommendationPolicy
from musimack_tools.sitemap.limits import SitemapXmlConfiguration

if TYPE_CHECKING:
    from musimack_tools.domain.crawl import CrawlRequest, CrawlResult
    from musimack_tools.domain.run_summary import (
        RunSummaryArtifact,
        RunSummaryConfiguration,
        RunSummaryWriteResult,
    )
    from musimack_tools.domain.sitemap import SitemapRecommendationProjection
    from musimack_tools.domain.sitemap_publication import (
        SitemapPublicationConfiguration,
        SitemapPublicationPlan,
        SitemapPublicationResult,
    )
    from musimack_tools.domain.sitemap_xml import SitemapXmlBundle

CRAWL_RUN_ORCHESTRATION_VERSION = "crawl-run-orchestration-v1"
DEFAULT_ROBOTS_PRODUCT = "MusimackSEOToolkit"
MAXIMUM_EXECUTION_IDENTITY_LENGTH = 256


class RunStage(StrEnum):
    CRAWL = "crawl"
    RECOMMEND = "recommend"
    GENERATE_XML = "generate_xml"
    PLAN_PUBLICATION = "plan_publication"
    PUBLISH = "publish"
    WRITE_SUMMARY = "write_summary"


class RunLifecycle(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    PARTIALLY_COMPLETED = "partially_completed"


class RunStageState(StrEnum):
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    FAILED = "failed"


class RunFailureCode(StrEnum):
    INVALID_RUN_REQUEST = "invalid_run_request"
    STAGE_DEPENDENCY_INVALID = "stage_dependency_invalid"
    CRAWL_FAILED = "crawl_failed"
    CRAWL_CANCELLED = "crawl_cancelled"
    RECOMMENDATION_FAILED = "recommendation_failed"
    XML_GENERATION_FAILED = "xml_generation_failed"
    PUBLICATION_PLANNING_FAILED = "publication_planning_failed"
    PUBLICATION_BLOCKED = "publication_blocked"
    PUBLICATION_PARTIALLY_FAILED = "publication_partially_failed"
    SUMMARY_SERIALIZATION_FAILED = "summary_serialization_failed"
    SUMMARY_WRITING_FAILED = "summary_writing_failed"
    PROGRESS_SINK_FAILED = "progress_sink_failed"
    CANCELLATION_OBSERVED = "cancellation_observed"
    UNEXPECTED_STAGE_FAILURE = "unexpected_internal_stage_failure"


@dataclass(frozen=True, slots=True)
class RunStageRecord:
    stage: RunStage
    state: RunStageState
    explanation: str | None = None


@dataclass(frozen=True, slots=True)
class RunWarning:
    code: str
    stage: RunStage
    message: str
    url: str | None = None


@dataclass(frozen=True, slots=True)
class RunFailure:
    code: RunFailureCode
    stage: RunStage | None
    explanation: str
    internal_exception_type: str | None = None


@dataclass(frozen=True, slots=True)
class RunConfigurationSnapshot:
    normalized_seed_url: str
    crawl_limits: tuple[tuple[str, int | float | bool], ...]
    scope_mode: str
    approved_hosts: tuple[str, ...]
    robots_product_token: str
    recommendation_rule_set_version: str
    xml_format_version: str
    publication_version: str
    manifest_version: str
    requested_stages: tuple[str, ...]
    publication_mode: str | None
    existing_file_policy: str | None
    create_output_directory: bool | None
    orchestration_version: str = CRAWL_RUN_ORCHESTRATION_VERSION


_PREREQUISITES: dict[RunStage, frozenset[RunStage]] = {
    RunStage.RECOMMEND: frozenset({RunStage.CRAWL}),
    RunStage.GENERATE_XML: frozenset({RunStage.CRAWL, RunStage.RECOMMEND}),
    RunStage.PLAN_PUBLICATION: frozenset(
        {RunStage.CRAWL, RunStage.RECOMMEND, RunStage.GENERATE_XML}
    ),
    RunStage.PUBLISH: frozenset({RunStage.CRAWL, RunStage.RECOMMEND, RunStage.GENERATE_XML}),
}

_STAGE_TRANSITIONS: dict[RunStageState, frozenset[RunStageState]] = {
    RunStageState.NOT_REQUESTED: frozenset(),
    RunStageState.PENDING: frozenset(
        {
            RunStageState.RUNNING,
            RunStageState.BLOCKED,
            RunStageState.CANCELLED,
        }
    ),
    RunStageState.RUNNING: frozenset(
        {
            RunStageState.COMPLETED,
            RunStageState.COMPLETED_WITH_WARNINGS,
            RunStageState.CANCELLED,
            RunStageState.FAILED,
        }
    ),
    RunStageState.COMPLETED: frozenset(),
    RunStageState.COMPLETED_WITH_WARNINGS: frozenset(),
    RunStageState.BLOCKED: frozenset(),
    RunStageState.CANCELLED: frozenset(),
    RunStageState.FAILED: frozenset(),
}


def validate_stage_transition(current: RunStageState, following: RunStageState) -> None:
    """Reject nondeterministic or regressive stage transitions."""
    if following not in _STAGE_TRANSITIONS[current]:
        message = f"invalid run stage transition: {current.value} -> {following.value}"
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class CrawlRunRequest:
    crawl_request: CrawlRequest
    requested_stages: tuple[RunStage, ...] = (RunStage.CRAWL,)
    recommendation_policy: RecommendationPolicy = field(default_factory=RecommendationPolicy)
    xml_configuration: SitemapXmlConfiguration = field(default_factory=SitemapXmlConfiguration)
    publication_configuration: SitemapPublicationConfiguration | None = None
    summary_configuration: RunSummaryConfiguration | None = None
    caller_label: str | None = None
    execution_identity: str | None = None
    robots_product_token: str = DEFAULT_ROBOTS_PRODUCT
    orchestration_version: str = CRAWL_RUN_ORCHESTRATION_VERSION

    def __post_init__(self) -> None:  # noqa: C901 - ordered request invariants remain explicit.
        if self.orchestration_version != CRAWL_RUN_ORCHESTRATION_VERSION:
            message = "unsupported run orchestration version"
            raise ValueError(message)
        if not self.requested_stages or len(set(self.requested_stages)) != len(
            self.requested_stages
        ):
            message = "requested stages must be non-empty and unique"
            raise ValueError(message)
        if RunStage.CRAWL not in self.requested_stages:
            message = "every v1 run must request the crawl stage"
            raise ValueError(message)
        canonical_order = tuple(stage for stage in RunStage if stage in self.requested_stages)
        if self.requested_stages != canonical_order:
            message = "requested stages must follow canonical execution order"
            raise ValueError(message)
        requested = set(self.requested_stages)
        for stage, required in _PREREQUISITES.items():
            if stage in requested and not required.issubset(requested):
                message = f"{stage.value} requires: {', '.join(sorted(x.value for x in required))}"
                raise ValueError(message)
        if RunStage.PUBLISH in requested and RunStage.PLAN_PUBLICATION in requested:
            message = "request either plan_publication or publish, not both"
            raise ValueError(message)
        if (
            RunStage.PUBLISH in requested or RunStage.PLAN_PUBLICATION in requested
        ) and self.publication_configuration is None:
            message = "publication stages require publication configuration"
            raise ValueError(message)
        if self.caller_label is not None and not self.caller_label.strip():
            message = "caller label cannot be blank"
            raise ValueError(message)
        if self.execution_identity is not None and (
            not self.execution_identity.strip()
            or len(self.execution_identity) > MAXIMUM_EXECUTION_IDENTITY_LENGTH
        ):
            message = (
                "execution identity must be non-blank and at most "
                f"{MAXIMUM_EXECUTION_IDENTITY_LENGTH} characters"
            )
            raise ValueError(message)
        if not self.robots_product_token.strip():
            message = "robots product token cannot be blank"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class CrawlRunResult:
    run_id: str
    run_digest: str
    caller_label: str | None
    lifecycle: RunLifecycle
    stages: tuple[RunStageRecord, ...]
    configuration: RunConfigurationSnapshot
    crawl_result: CrawlResult | None = None
    recommendation_projection: SitemapRecommendationProjection | None = None
    xml_bundle: SitemapXmlBundle | None = None
    publication_plan: SitemapPublicationPlan | None = None
    publication_result: SitemapPublicationResult | None = None
    summaries: tuple[RunSummaryArtifact, ...] = ()
    summary_write_result: RunSummaryWriteResult | None = None
    warnings: tuple[RunWarning, ...] = ()
    failures: tuple[RunFailure, ...] = ()
    duration_seconds: float = 0.0
    orchestration_version: str = CRAWL_RUN_ORCHESTRATION_VERSION
