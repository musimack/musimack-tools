"""Explicit local-only authenticated browser-QA composition for Phase 21."""

# ruff: noqa: T201, TRY003 - explicit QA CLI reports safe values and fails with operator guidance.

from __future__ import annotations

import argparse
import os
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from musimack_tools.application.service import SeoToolkitApplicationService
from musimack_tools.artifacts.repository import SQLAlchemyArtifactRepository
from musimack_tools.artifacts.service import ArtifactService
from musimack_tools.authentication.service import AuthenticationService
from musimack_tools.deployment.application import create_production_app
from musimack_tools.deployment.persistence_runtime import PreparedPersistence
from musimack_tools.deployment.settings import ProductionSettings, authentication_configuration
from musimack_tools.domain.artifacts import (
    ArtifactStorageConfiguration,
    ArtifactStorageRootConfiguration,
)
from musimack_tools.domain.crawl import (
    CrawlConfigurationSnapshot,
    CrawlCounters,
    CrawlRequest,
    CrawlResult,
    CrawlState,
)
from musimack_tools.domain.fetching import FetchOutcome, FetchRequest, FetchResult, ResponseHeaders
from musimack_tools.domain.history import HistoryConfiguration
from musimack_tools.domain.job import JobState
from musimack_tools.domain.metadata_audit import MetadataAuditConfiguration
from musimack_tools.domain.page_evidence import PageEvidenceConfiguration
from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.domain.run import RunStage, RunStageRecord, RunStageState
from musimack_tools.domain.sitemap_audit import SitemapAuditConfiguration
from musimack_tools.history.service import HistoryService
from musimack_tools.jobs.registry import InMemoryJobRegistry
from musimack_tools.jobs.service import InternalJobService
from musimack_tools.metadata_audit.service import MetadataAuditService
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.history_repository import SQLAlchemyHistoryRepository
from musimack_tools.persistence.metadata_audit_repository import SQLAlchemyMetadataAuditRepository
from musimack_tools.persistence.repositories import SQLAlchemyPersistenceRepository
from musimack_tools.persistence.sitemap_audit_repository import SQLAlchemySitemapAuditRepository
from musimack_tools.recommendation.sitemap import SitemapRecommendationEngine
from musimack_tools.run.service import CrawlRunService
from musimack_tools.sitemap_audit.service import SitemapAuditService
from page_evidence_helpers import PageRecordOptions, crawl_result, page_record
from persistence_helpers import sample_request, sample_result, sample_snapshot

if TYPE_CHECKING:
    from fastapi import FastAPI

    from musimack_tools.crawl.cancellation import CancellationToken
    from musimack_tools.crawl.orchestrator import ProgressObserver
    from musimack_tools.domain.urls import CrawlScopePolicy
    from musimack_tools.run.progress import RunProgressSink

_QA_ENABLED = "MUSIMACK_QA_BROWSER_ENABLED"
_DATABASE = "MUSIMACK_PERSISTENCE_DATABASE_PATH"
_ARTIFACT_ROOT = "MUSIMACK_QA_ARTIFACT_ROOT"
_ADMIN_EMAIL = "MUSIMACK_QA_ADMIN_EMAIL"
_ADMIN_NAME = "MUSIMACK_QA_ADMIN_NAME"
_ADMIN_PASSWORD = "MUSIMACK_QA_ADMIN_PASSWORD"  # noqa: S105 - environment variable name.
_SITEMAP = "https://example.com/sitemap.xml"
_ROBOTS = "https://example.com/robots.txt"
_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


class DeterministicQaSitemapFetcher:
    """Return a fixed in-memory fixture and never open a network connection."""

    async def fetch(self, request: FetchRequest, scope: CrawlScopePolicy) -> FetchResult:
        del scope
        url = request.url.normalized
        if url == _ROBOTS:
            status, content_type, body = 200, "text/plain", f"Sitemap: {_SITEMAP}\n".encode()
        elif url == _SITEMAP:
            status, content_type, body = (
                200,
                "application/xml",
                (
                    f'<urlset xmlns="{_NS}">'
                    "<url><loc>https://example.com/</loc></url>"
                    "<url><loc>https://example.com/about</loc></url>"
                    "<url><loc>https://example.com/retired</loc></url>"
                    "<url><loc>https://example.com/sitemap-only</loc></url>"
                    "</urlset>"
                ).encode(),
            )
        else:
            status, content_type, body = 404, "text/plain", b"fixture not found"
        return FetchResult(
            requested_url=url,
            final_url=url,
            outcome=FetchOutcome.SUCCESS,
            status_code=status,
            headers=ResponseHeaders(content_type=content_type),
            content_type=content_type,
            declared_content_length=len(body),
            actual_bytes_read=len(body),
            body_truncated=False,
            redirect_chain=(),
            request_duration_seconds=0.0,
            dns_evidence=(),
            failure_code=None,
            failure_explanation=None,
            body=body,
        )


class _AcceptedQaCrawler:
    async def crawl(
        self,
        request: CrawlRequest,
        *,
        observer: ProgressObserver | None = None,
    ) -> CrawlResult:
        del observer
        return CrawlResult(
            seed_url=request.seed_url.normalized,
            scope_policy=request.scope_policy,
            started_at_seconds=0.0,
            ended_at_seconds=1.0,
            duration_seconds=1.0,
            state=CrawlState.COMPLETED,
            url_records=(),
            discoveries=(),
            counters=CrawlCounters(unique_urls_discovered=1, urls_queued=1, urls_fetched=1),
            limit_events=(),
            errors=(),
            cancellation=None,
            total_accepted_bytes=0,
            maximum_observed_queue_size=1,
            maximum_active_worker_count=1,
            configuration=CrawlConfigurationSnapshot(
                request.maximum_unique_urls,
                request.maximum_depth,
                request.maximum_duration_seconds,
                request.maximum_total_fetched_bytes,
                request.maximum_concurrent_fetches,
                request.maximum_queued_urls,
                request.minimum_per_origin_delay_seconds,
                request.query_urls_allowed,
                request.exclusion_rules,
            ),
        )


def _accepted_run_factory(
    cancellation: CancellationToken,
    progress_sink: RunProgressSink,
) -> CrawlRunService:
    return CrawlRunService(
        _AcceptedQaCrawler(), cancellation=cancellation, progress_sink=progress_sink
    )


def create_qa_app() -> FastAPI:
    """Compose the private application only after explicit QA opt-in."""
    if os.environ.get(_QA_ENABLED, "").casefold() not in {"1", "true"}:
        raise RuntimeError(f"set {_QA_ENABLED}=true to enable the browser-QA fixture")
    configuration = _persistence_configuration()
    runtime = create_persistence_runtime(configuration)
    persistence = SQLAlchemyPersistenceRepository(runtime)
    prepared = PreparedPersistence(persistence, persistence.diagnostics(), None)
    registry = InMemoryJobRegistry(
        _accepted_run_factory,
        persistence=persistence,
        recovered_attempts=persistence.highest_attempts(),
        persisted_terminal_jobs=persistence.retained_terminal_jobs(),
    )
    jobs = InternalJobService(registry)
    application_service = SeoToolkitApplicationService(jobs)

    artifact_root = _required_path(_ARTIFACT_ROOT)
    artifacts = ArtifactService(
        ArtifactStorageConfiguration(
            enabled=True,
            roots=(ArtifactStorageRootConfiguration("qa", artifact_root),),
            default_root_id="qa",
            allow_csv=True,
        ),
        SQLAlchemyArtifactRepository(runtime),
    )
    history = HistoryService(
        HistoryConfiguration(enabled=True), SQLAlchemyHistoryRepository(runtime)
    )
    settings = ProductionSettings()
    authentication = AuthenticationService(
        runtime.session_factory, authentication_configuration(settings)
    )
    metadata = MetadataAuditService(
        configuration.metadata_audit,
        SQLAlchemyMetadataAuditRepository(runtime),
        artifacts,
    )
    sitemaps = SitemapAuditService(
        configuration.sitemap_audit,
        SQLAlchemySitemapAuditRepository(runtime),
        DeterministicQaSitemapFetcher(),
        artifacts,
    )
    app = create_production_app(
        application_service,
        settings,
        persistence=prepared,
        artifacts=artifacts,
        history=history,
        authentication=authentication,
        metadata_audits=metadata,
        sitemap_audits=sitemaps,
    )

    async def shutdown() -> None:
        await jobs.shutdown()
        runtime.dispose()

    app.router.add_event_handler("shutdown", shutdown)
    return app


def bootstrap() -> None:
    """Create the one explicitly supplied local administrator."""
    runtime = create_persistence_runtime(_persistence_configuration())
    try:
        settings = ProductionSettings()
        service = AuthenticationService(
            runtime.session_factory, authentication_configuration(settings)
        )
        user = service.bootstrap_administrator(
            _required(_ADMIN_EMAIL),
            _required(_ADMIN_NAME),
            _required(_ADMIN_PASSWORD),
        )
        print(f"Bootstrapped QA administrator: {user.email}")
    finally:
        runtime.dispose()


def seed() -> None:
    """Persist one completed run, page evidence, and recommendation projection."""
    runtime = create_persistence_runtime(_persistence_configuration())
    try:
        request = replace(sample_request(), requested_stages=(RunStage.CRAWL, RunStage.RECOMMEND))
        snapshot = sample_snapshot(request)
        repository = SQLAlchemyPersistenceRepository(runtime)
        submission = repository.record_submission(snapshot, request)
        if not submission.succeeded:
            raise RuntimeError("QA run submission seed failed")
        crawl = crawl_result(
            (
                page_record(
                    options=PageRecordOptions(
                        body=(
                            "<title>QA home</title><meta name='description' content='QA home'>"
                            "<link rel='canonical' href='/'>"
                        ),
                        x_robots=(),
                    )
                ),
                page_record(
                    "https://example.com/about",
                    PageRecordOptions(
                        body=(
                            "<title>About QA</title><meta name='description' content='About'>"
                            "<link rel='canonical' href='/about'>"
                        ),
                        discovery_order=1,
                        x_robots=(),
                    ),
                ),
                page_record(
                    "https://example.com/retired",
                    PageRecordOptions(discovery_order=2, x_robots=("noindex",)),
                ),
            )
        )
        result = replace(
            sample_result(request),
            stages=(
                RunStageRecord(RunStage.CRAWL, RunStageState.COMPLETED),
                RunStageRecord(RunStage.RECOMMEND, RunStageState.COMPLETED),
            ),
            crawl_result=crawl,
            recommendation_projection=SitemapRecommendationEngine().project(crawl),
        )
        terminal = replace(
            snapshot,
            state=JobState.COMPLETED,
            run_lifecycle=result.lifecycle,
            final_result_available=True,
            terminal=True,
        )
        persisted = repository.record_terminal(terminal, result, (), None)
        if not persisted.succeeded:
            raise RuntimeError("QA terminal run seed failed")
        print(f"Seeded QA crawl run: {snapshot.run_id}")
        print(f"Deterministic sitemap fixture: {_SITEMAP}")
    finally:
        runtime.dispose()


def _persistence_configuration() -> PersistenceConfiguration:
    return PersistenceConfiguration(
        enabled=True,
        database_path=_required_path(_DATABASE),
        page_evidence=PageEvidenceConfiguration(enabled=True),
        metadata_audit=MetadataAuditConfiguration(enabled=True),
        sitemap_audit=SitemapAuditConfiguration(enabled=True),
    )


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable is missing: {name}")
    return value


def _required_path(name: str) -> Path:
    return Path(_required(name)).resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bootstrap", "seed"))
    command = parser.parse_args().command
    bootstrap() if command == "bootstrap" else seed()


if __name__ == "__main__":
    main()
