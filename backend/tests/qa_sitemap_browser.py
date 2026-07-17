"""Explicit local-only authenticated browser-QA composition for Phases 21 and 22."""

# ruff: noqa: PLR0913, T201, TRY003 - explicit QA CLI reports safe values and fails with operator guidance.

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from musimack_tools.application.service import SeoToolkitApplicationService
from musimack_tools.artifacts.repository import SQLAlchemyArtifactRepository
from musimack_tools.artifacts.service import ArtifactService
from musimack_tools.authentication.service import AuthenticationService
from musimack_tools.crawl.html import HtmlMetadataParser
from musimack_tools.crawl.normalization import normalize_url
from musimack_tools.crawl.scope import create_scope_policy
from musimack_tools.deployment.application import create_production_app
from musimack_tools.deployment.persistence_runtime import PreparedPersistence
from musimack_tools.deployment.settings import ProductionSettings, authentication_configuration
from musimack_tools.domain.artifacts import (
    ArtifactStorageConfiguration,
    ArtifactStorageRootConfiguration,
)
from musimack_tools.domain.authentication import UserRole, UserState
from musimack_tools.domain.crawl import (
    CrawlConfigurationSnapshot,
    CrawlCounters,
    CrawlRequest,
    CrawlResult,
    CrawlState,
    UrlCrawlRecord,
)
from musimack_tools.domain.fetching import (
    FetchOutcome,
    FetchRequest,
    FetchResult,
    RedirectHop,
    ResponseHeaders,
)
from musimack_tools.domain.history import HistoryConfiguration
from musimack_tools.domain.internal_link import InternalLinkConfiguration
from musimack_tools.domain.job import JobState
from musimack_tools.domain.link_audit import LinkAuditConfiguration
from musimack_tools.domain.metadata_audit import MetadataAuditConfiguration
from musimack_tools.domain.page_evidence import PageEvidenceConfiguration
from musimack_tools.domain.persistence import PersistenceConfiguration
from musimack_tools.domain.run import RunStage, RunStageRecord, RunStageState
from musimack_tools.domain.sitemap_audit import DiscoveryOptions, SitemapAuditConfiguration
from musimack_tools.history.service import HistoryService
from musimack_tools.internal_link.service import InternalLinkAuditService
from musimack_tools.jobs.registry import InMemoryJobRegistry
from musimack_tools.jobs.service import InternalJobService
from musimack_tools.link_audit.service import LinkAuditService
from musimack_tools.metadata_audit.service import MetadataAuditService
from musimack_tools.persistence.engine import create_persistence_runtime
from musimack_tools.persistence.history_repository import SQLAlchemyHistoryRepository
from musimack_tools.persistence.internal_link_repository import SQLAlchemyInternalLinkRepository
from musimack_tools.persistence.link_audit_repository import SQLAlchemyLinkAuditRepository
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


def _qa_html(title: str) -> str:
    return f"<title>{title}</title><meta name='description' content='{title} QA evidence'>"


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
    links = LinkAuditService(
        configuration.link_audit,
        SQLAlchemyLinkAuditRepository(runtime),
        artifacts,
    )
    internal_links = InternalLinkAuditService(
        configuration.internal_link,
        SQLAlchemyInternalLinkRepository(runtime),
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
        link_audits=links,
        internal_link_audits=internal_links,
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
        operator = service.create_user(
            "qa-operator@localhost.test",
            "QA Operator",
            UserRole.OPERATOR,
            _required(_ADMIN_PASSWORD),
            UserState.ACTIVE,
        )
        viewer = service.create_user(
            "qa-viewer@localhost.test",
            "QA Viewer",
            UserRole.VIEWER,
            _required(_ADMIN_PASSWORD),
            UserState.ACTIVE,
        )
        print(f"Bootstrapped QA operator: {operator.email}")
        print(f"Bootstrapped QA viewer: {viewer.email}")
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
        scope = create_scope_policy(normalize_url("https://example.com/"))
        home = _scoped_page(
            "https://example.com/",
            PageRecordOptions(
                body=(
                    "<title>QA home</title><meta name='description' content='QA home'>"
                    "<a href='/working'>Working</a><a href='/missing'>404</a>"
                    "<a href='/gone'>410</a><a href='/server-error'>500</a>"
                    "<a href='/unverified'>Unverified</a><a href='/manual.pdf'>PDF</a>"
                    "<a href='https://outside.example/path'>External</a>"
                    "<a href='https://example.com:8443/private'>Out of scope</a>"
                    "<a href='mailto:qa@example.com'>Mail</a><a href='tel:+15551234567'>Phone</a>"
                    "<a href='#details'>Fragment</a><a href='/permanent'>Permanent</a>"
                    "<a href='/temporary'>Temporary</a><a href='/chain'>Chain</a>"
                    "<a href='/mixed'>Mixed</a><a href='/broken-redirect'>Broken redirect</a>"
                    "<a href='/external-redirect'>External redirect</a><a href='/loop'>Loop</a>"
                    "<a href='/sitewide-missing'>Sitewide missing</a>"
                    "<a href='/deep-one'>Deep path</a>"
                    "<a href='/redirect-only-source'>Redirect-only</a>"
                    "<a href='/nofollow-only' rel='nofollow'>Nofollow-only</a>"
                    "<a href='/authority-target'>Authority</a><a href='/hub'>Hub</a>"
                    "<a href='/anchor-target'>click here</a>"
                    "<a href='/anchor-target'>click here</a>"
                    "<a href='/anchor-target'>click here</a>"
                    "<a href='/anchor-target'>click here</a>"
                    "<a href='/anchor-target'>click here</a>"
                    "<a href='/anchor-target'>click here</a>"
                    "<a href='/anchor-target'>click here</a>"
                    "<a href='/anchor-target'>click here</a><a href='/anchor-target'></a>"
                    "<a href='/anchor-target'>https://example.com/anchor-target</a>"
                    "<a href='/shared-anchor-one'>read more</a>"
                    "<a href='/shared-anchor-two'>read more</a>"
                    "<a href='/concentrated-target'>Product guide</a>"
                    "<a href='/concentrated-target'>Product guide</a>"
                    "<a href='/concentrated-target'>Product guide</a>"
                    "<a href='/concentrated-target'>Product guide</a>"
                    "<a href='/concentrated-target'>Product guide</a>"
                    "<a href='/concentrated-target'>Product guide</a>"
                    "<a href='/concentrated-target'>Product guide</a>"
                    "<a href='/concentrated-target'>Product guide</a>"
                    "<a href='/concentrated-target'>Product guide</a>"
                    "<a href='/concentrated-target'>Overview</a>"
                    "<a href='/high-outlinks'>High outlinks</a>"
                ),
                x_robots=(),
            ),
            scope,
        )
        repeated = _scoped_page(
            "https://example.com/source-two",
            PageRecordOptions(
                body=(
                    "<title>Second source</title><a href='/sitewide-missing'>Repeated sitewide</a>"
                    "<a href='/authority-target'>Authority target</a>"
                    "<a href='/anchor-target'>click here</a>"
                ),
                discovery_order=1,
                x_robots=(),
            ),
            scope,
        )
        crawl = crawl_result(
            (
                home,
                repeated,
                _scoped_page(
                    "https://example.com/working",
                    PageRecordOptions(discovery_order=2, x_robots=()),
                    scope,
                ),
                _scoped_page(
                    "https://example.com/missing",
                    PageRecordOptions(status=404, discovery_order=3, x_robots=()),
                    scope,
                ),
                _scoped_page(
                    "https://example.com/gone",
                    PageRecordOptions(status=410, discovery_order=4, x_robots=()),
                    scope,
                ),
                _scoped_page(
                    "https://example.com/server-error",
                    PageRecordOptions(status=500, discovery_order=5, x_robots=()),
                    scope,
                ),
                _scoped_page(
                    "https://example.com/manual.pdf",
                    PageRecordOptions(
                        body=None,
                        content_type="application/pdf",
                        discovery_order=6,
                        x_robots=(),
                    ),
                    scope,
                ),
                _scoped_page(
                    "https://example.com/sitewide-missing",
                    PageRecordOptions(status=404, discovery_order=7, x_robots=()),
                    scope,
                ),
                _redirect_page(
                    "https://example.com/permanent",
                    "https://example.com/working",
                    (301,),
                    8,
                    scope,
                ),
                _redirect_page(
                    "https://example.com/temporary",
                    "https://example.com/working",
                    (302,),
                    9,
                    scope,
                ),
                _redirect_page(
                    "https://example.com/chain",
                    "https://example.com/working",
                    (301, 301),
                    10,
                    scope,
                ),
                _redirect_page(
                    "https://example.com/mixed",
                    "https://example.com/working",
                    (301, 302),
                    11,
                    scope,
                ),
                _redirect_page(
                    "https://example.com/broken-redirect",
                    "https://example.com/missing",
                    (301,),
                    12,
                    scope,
                    final_status=404,
                ),
                _redirect_page(
                    "https://example.com/external-redirect",
                    "https://outside.example/final",
                    (302,),
                    13,
                    scope,
                ),
                _redirect_page(
                    "https://example.com/loop",
                    "https://example.com/loop",
                    (301,),
                    14,
                    scope,
                ),
                _scoped_page(
                    "https://example.com/deep-one",
                    PageRecordOptions(
                        body="<title>Deep one</title><a href='/deep-two'>Next</a>",
                        discovery_order=15,
                        x_robots=(),
                    ),
                    scope,
                ),
                _scoped_page(
                    "https://example.com/deep-two",
                    PageRecordOptions(
                        body="<title>Deep two</title><a href='/deep-three'>Next</a>",
                        discovery_order=16,
                        x_robots=(),
                    ),
                    scope,
                ),
                _scoped_page(
                    "https://example.com/deep-three",
                    PageRecordOptions(body=_qa_html("Deep three"), discovery_order=17, x_robots=()),
                    scope,
                ),
                _scoped_page(
                    "https://example.com/true-orphan",
                    PageRecordOptions(
                        body=_qa_html("True orphan"), discovery_order=18, x_robots=()
                    ),
                    scope,
                ),
                _scoped_page(
                    "https://example.com/sitemap-only",
                    PageRecordOptions(
                        body=_qa_html("Sitemap only"), discovery_order=19, x_robots=()
                    ),
                    scope,
                ),
                _redirect_page(
                    "https://example.com/redirect-only-source",
                    "https://example.com/redirect-only-target",
                    (301,),
                    20,
                    scope,
                ),
                _scoped_page(
                    "https://example.com/redirect-only-target",
                    PageRecordOptions(
                        body=_qa_html("Redirect only"), discovery_order=21, x_robots=()
                    ),
                    scope,
                ),
                _scoped_page(
                    "https://example.com/nofollow-only",
                    PageRecordOptions(
                        body=_qa_html("Nofollow only"), discovery_order=22, x_robots=()
                    ),
                    scope,
                ),
                _scoped_page(
                    "https://example.com/authority-target",
                    PageRecordOptions(
                        body=_qa_html("Authority target"), discovery_order=23, x_robots=()
                    ),
                    scope,
                ),
                _scoped_page(
                    "https://example.com/hub",
                    PageRecordOptions(
                        body=(
                            "<title>Hub</title><a href='/authority-target'>Authority</a>"
                            "<a href='/anchor-target'>click here</a>"
                        ),
                        discovery_order=24,
                        x_robots=(),
                    ),
                    scope,
                ),
                _scoped_page(
                    "https://example.com/anchor-target",
                    PageRecordOptions(
                        body=_qa_html("Anchor target"), discovery_order=25, x_robots=()
                    ),
                    scope,
                ),
                _scoped_page(
                    "https://example.com/shared-anchor-one",
                    PageRecordOptions(
                        body=_qa_html("Shared anchor one"), discovery_order=26, x_robots=()
                    ),
                    scope,
                ),
                _scoped_page(
                    "https://example.com/shared-anchor-two",
                    PageRecordOptions(
                        body=_qa_html("Shared anchor two"), discovery_order=27, x_robots=()
                    ),
                    scope,
                ),
                _scoped_page(
                    "https://example.com/high-outlinks",
                    PageRecordOptions(
                        body="<title>High outlinks</title>"
                        + "".join(f"<a href='/out-{index}'>Out</a>" for index in range(6)),
                        discovery_order=28,
                        x_robots=(),
                    ),
                    scope,
                ),
                *(
                    _scoped_page(
                        f"https://example.com/out-{index}",
                        PageRecordOptions(
                            body=_qa_html(f"Outbound target {index}"),
                            discovery_order=29 + index,
                            x_robots=(),
                        ),
                        scope,
                    )
                    for index in range(6)
                ),
                _scoped_page(
                    "https://example.com/concentrated-target",
                    PageRecordOptions(
                        body=_qa_html("Concentrated target"),
                        discovery_order=35,
                        x_robots=(),
                    ),
                    scope,
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
        sitemap_service = SitemapAuditService(
            SitemapAuditConfiguration(enabled=True),
            SQLAlchemySitemapAuditRepository(runtime),
            DeterministicQaSitemapFetcher(),
        )
        asyncio.run(
            sitemap_service.create_and_run(
                snapshot.run_id,
                DiscoveryOptions(
                    explicit_url=_SITEMAP,
                    discover_robots=False,
                    discover_common_locations=False,
                ),
            )
        )
        print(f"Seeded QA crawl run: {snapshot.run_id}")
        print("Seeded Phase 22 link fixture and 22-case Phase 23 internal-link fixture")
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
        link_audit=LinkAuditConfiguration(
            enabled=True,
            default_page_size=5,
            minimum_sitewide_source_pages=2,
            minimum_sitewide_crawl_pages=2,
            sitewide_ratio=0.1,
        ),
        internal_link=InternalLinkConfiguration(
            enabled=True,
            default_page_size=5,
            minimum_hub_destinations=2,
            minimum_authority_referrers=2,
            minimum_sitewide_pages=2,
            maximum_graph_depth=2,
            maximum_outlinks=5,
        ),
    )


def _scoped_page(
    url: str,
    options: PageRecordOptions,
    scope: CrawlScopePolicy,
) -> UrlCrawlRecord:
    record = page_record(url, options)
    fetch = record.fetch_result
    if fetch is None or fetch.body is None:
        return record
    return replace(record, parse_result=HtmlMetadataParser().parse(fetch, scope=scope))


def _redirect_page(
    source: str,
    final: str,
    statuses: tuple[int, ...],
    discovery_order: int,
    scope: CrawlScopePolicy,
    *,
    final_status: int = 200,
) -> UrlCrawlRecord:
    record = page_record(
        source,
        PageRecordOptions(final_url=final, status=final_status, discovery_order=discovery_order),
    )
    fetch = record.fetch_result
    if fetch is None:
        raise RuntimeError("QA redirect fixture has no fetch evidence")
    nodes = [source]
    nodes.extend(
        f"https://example.com/redirect-hop-{discovery_order}-{index}"
        for index in range(1, len(statuses))
    )
    nodes.append(final)
    hops = tuple(
        RedirectHop(
            source_url=nodes[index],
            status_code=status,
            raw_location=nodes[index + 1],
            destination_url=nodes[index + 1],
            allowed=True,
            failure_code=None,
            explanation="deterministic QA redirect",
        )
        for index, status in enumerate(statuses)
    )
    fetch = replace(fetch, redirect_chain=hops, final_url=final, status_code=final_status)
    parse = HtmlMetadataParser().parse(fetch, scope=scope) if fetch.body is not None else None
    return replace(record, fetch_result=fetch, parse_result=parse, final_fetched_url=final)


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
