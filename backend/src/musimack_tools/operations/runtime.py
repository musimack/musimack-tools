"""Supervisor-neutral web and worker composition for production operations."""

# ruff: noqa: TRY003

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from starlette.middleware.trustedhost import TrustedHostMiddleware

from musimack_tools.application.service import SeoToolkitApplicationService
from musimack_tools.artifacts.repository import SQLAlchemyArtifactRepository
from musimack_tools.artifacts.service import ArtifactService
from musimack_tools.authentication.service import AuthenticationService
from musimack_tools.core.config import Settings
from musimack_tools.crawl.dns import SystemAsyncResolver
from musimack_tools.crawl.fetcher import SafeSingleUrlFetcher
from musimack_tools.crawl.html import HtmlMetadataParser
from musimack_tools.crawl.limits import CrawlHardLimits
from musimack_tools.crawl.orchestrator import SingleSiteCrawlOrchestrator
from musimack_tools.crawl.robots import RobotsTxtService
from musimack_tools.crawl.safety import DestinationSafetyValidator
from musimack_tools.deployment.application import create_production_app
from musimack_tools.deployment.artifacts import ArtifactStorageSettings
from musimack_tools.deployment.durable import DurableExecutionSettings
from musimack_tools.deployment.history import HistorySettings, prepare_history
from musimack_tools.deployment.persistence import PersistenceSettings
from musimack_tools.deployment.persistence_runtime import PreparedPersistence
from musimack_tools.deployment.settings import ProductionSettings, authentication_configuration
from musimack_tools.deployment.worker import prepare_durable_execution
from musimack_tools.domain.application import (
    ApplicationReadinessReport,
    ReadinessCheck,
    ReadinessCheckCode,
    ReadinessState,
)
from musimack_tools.domain.site_audit_orchestration import SiteAuditStage
from musimack_tools.domain.sitemap_audit import DiscoveryOptions
from musimack_tools.durable.service import DurableJobService
from musimack_tools.image_audit.service import ImageAuditService
from musimack_tools.internal_link.service import InternalLinkAuditService
from musimack_tools.link_audit.service import LinkAuditService
from musimack_tools.metadata_audit.service import MetadataAuditService
from musimack_tools.migration_qa.service import MigrationQaService
from musimack_tools.operations.configuration import (
    ApplicationRole,
    OperationsSettings,
    require_production_configuration,
)
from musimack_tools.operations.preflight import run_preflight
from musimack_tools.persistence.engine import PersistenceRuntime, create_persistence_runtime
from musimack_tools.persistence.image_audit_repository import SQLAlchemyImageAuditRepository
from musimack_tools.persistence.internal_link_repository import SQLAlchemyInternalLinkRepository
from musimack_tools.persistence.link_audit_repository import SQLAlchemyLinkAuditRepository
from musimack_tools.persistence.metadata_audit_repository import SQLAlchemyMetadataAuditRepository
from musimack_tools.persistence.migration_qa_repository import SQLAlchemyMigrationQaRepository
from musimack_tools.persistence.page_evidence_repository import SQLAlchemyPageEvidenceRepository
from musimack_tools.persistence.repositories import SQLAlchemyPersistenceRepository
from musimack_tools.persistence.site_audit_orchestration_repository import (
    SQLAlchemySiteAuditOrchestrationRepository,
)
from musimack_tools.persistence.site_audit_repository import SQLAlchemySiteAuditRepository
from musimack_tools.persistence.site_audit_settings_repository import (
    SQLAlchemySiteAuditSettingsRepository,
)
from musimack_tools.persistence.sitemap_audit_repository import SQLAlchemySitemapAuditRepository
from musimack_tools.persistence.structured_data_repository import (
    SQLAlchemyStructuredDataAuditRepository,
)
from musimack_tools.recommendation.sitemap import SitemapRecommendationEngine
from musimack_tools.run.service import CrawlRunService
from musimack_tools.site_audit.orchestration import (
    ApplicationSiteAuditCrawlGateway,
    SiteAuditOrchestrationService,
)
from musimack_tools.site_audit.specialists import (
    SpecialistAuthority,
    SQLAlchemySiteAuditSpecialistGateway,
)
from musimack_tools.site_audit_settings.service import (
    SiteAuditSettingsConfiguration,
    SiteAuditSettingsService,
)
from musimack_tools.sitemap_audit.service import SitemapAuditService
from musimack_tools.structured_data_audit.service import StructuredDataAuditService

if TYPE_CHECKING:
    from fastapi import FastAPI

    from musimack_tools.crawl.cancellation import CancellationToken
    from musimack_tools.domain.persistence import PersistenceConfiguration
    from musimack_tools.domain.run import CrawlRunResult
    from musimack_tools.jobs.coordinator import JobRunExecutor, JobRunServiceFactory
    from musimack_tools.jobs.service import InternalJobService
    from musimack_tools.persistence.durable_repository import (
        SQLAlchemyDurableExecutionRepository,
    )
    from musimack_tools.run.progress import RunProgressSink

_LOGGER = logging.getLogger("musimack_tools.operations")
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
ReadinessProvider = Callable[[], tuple[ReadinessCheck, ...]]


class ProductionApplicationService(SeoToolkitApplicationService):
    """Add deployment dependencies to the existing private readiness projection."""

    def __init__(self, jobs: InternalJobService, provider: ReadinessProvider) -> None:
        super().__init__(jobs)
        self._operations_readiness = provider

    async def get_readiness(self) -> ApplicationReadinessReport:
        base = await super().get_readiness()
        checks = (*base.checks, *self._operations_readiness())
        state = (
            ReadinessState.NOT_READY
            if any(check.state is ReadinessState.NOT_READY for check in checks)
            else ReadinessState.DEGRADED
            if any(check.state is ReadinessState.DEGRADED for check in checks)
            else ReadinessState.READY
        )
        return ApplicationReadinessReport(
            state,
            checks,
            base.active_jobs,
            base.queued_jobs,
            base.retained_terminal_jobs,
            base.application_service_version,
        )


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    application: Settings
    production: ProductionSettings
    persistence: PersistenceSettings
    durable: DurableExecutionSettings
    artifacts: ArtifactStorageSettings
    history: HistorySettings
    operations: OperationsSettings


@dataclass(slots=True)
class WebRuntime:
    app: FastAPI
    persistence: PersistenceRuntime
    jobs: DurableJobService


def load_runtime_settings() -> RuntimeSettings:
    """Load each existing settings boundary exactly once for an operator command."""
    return RuntimeSettings(
        Settings(),
        ProductionSettings(),
        PersistenceSettings(),
        DurableExecutionSettings(),
        ArtifactStorageSettings(),
        HistorySettings(),
        OperationsSettings(),
    )


def create_web_app() -> FastAPI:
    """Uvicorn factory for the explicitly composed private web process."""
    settings = load_runtime_settings()
    runtime = compose_web_runtime(settings)
    return runtime.app


def compose_web_runtime(settings: RuntimeSettings) -> WebRuntime:
    """Compose the web role without starting an in-process durable worker."""
    require_production_configuration(
        settings.application,
        settings.production,
        settings.persistence,
        settings.durable,
        settings.artifacts,
        settings.operations,
        repository_root=REPOSITORY_ROOT,
        role=ApplicationRole.WEB,
    )
    report = run_preflight(
        settings.application,
        settings.production,
        settings.persistence,
        settings.durable,
        settings.artifacts,
        settings.operations,
        repository_root=REPOSITORY_ROOT,
        backend_root=BACKEND_ROOT,
        role=ApplicationRole.WEB,
    )
    if not report.ready:
        raise RuntimeError("Production web startup preflight failed.")
    configuration = settings.persistence.to_configuration()
    runtime = create_persistence_runtime(configuration, repository_root=REPOSITORY_ROOT)
    evidence = SQLAlchemyPersistenceRepository(runtime)
    prepared = PreparedPersistence(evidence, evidence.diagnostics(), None)
    web_durable_settings = settings.durable.model_copy(
        update={"worker_enabled": False, "worker_id": None}
    )
    durable = prepare_durable_execution(web_durable_settings, prepared, runtime=runtime)
    if durable.repository is None:
        runtime.dispose()
        raise RuntimeError("Durable web composition is unavailable.")
    jobs = DurableJobService(durable.repository)
    artifact_service = ArtifactService(
        settings.artifacts.to_configuration(), SQLAlchemyArtifactRepository(runtime)
    )
    service = ProductionApplicationService(
        cast("InternalJobService", jobs),
        _readiness_provider(
            evidence,
            durable.repository,
            settings.durable.worker_id,
            artifact_service,
        ),
    )
    history = prepare_history(settings.history, runtime)
    authentication = AuthenticationService(
        runtime.session_factory, authentication_configuration(settings.production)
    )
    crawler_fetcher = _fetcher(settings.application)
    metadata_audits = _metadata_service(configuration, runtime, artifact_service)
    sitemap_audits = _sitemap_service(configuration, runtime, crawler_fetcher, artifact_service)
    link_audits = _link_service(configuration, runtime, artifact_service)
    internal_link_audits = _internal_link_service(configuration, runtime, artifact_service)
    image_audits = _image_service(configuration, runtime, artifact_service)
    structured_data_audits = _structured_service(configuration, runtime, artifact_service)
    site_audit_orchestration = SiteAuditOrchestrationService(
        SQLAlchemySiteAuditRepository(runtime),
        SQLAlchemySiteAuditOrchestrationRepository(runtime),
        SQLAlchemyPageEvidenceRepository(runtime),
        ApplicationSiteAuditCrawlGateway(service),
        artifact_service,
        _specialist_gateway(
            runtime,
            metadata_audits=metadata_audits,
            sitemap_audits=sitemap_audits,
            link_audits=link_audits,
            internal_link_audits=internal_link_audits,
            image_audits=image_audits,
            structured_data_audits=structured_data_audits,
            launch_enabled=False,
        ),
    )
    app = create_production_app(
        service,
        settings.production,
        settings.application,
        persistence=prepared,
        durable=durable,
        artifacts=artifact_service,
        history=history,
        authentication=authentication,
        metadata_audits=metadata_audits,
        sitemap_audits=sitemap_audits,
        link_audits=link_audits,
        internal_link_audits=internal_link_audits,
        image_audits=image_audits,
        structured_data_audits=structured_data_audits,
        migration_qa=_migration_qa_service(configuration, runtime, artifact_service),
        site_audit_settings=_site_audit_settings_service(runtime),
        site_audit_orchestration=site_audit_orchestration,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(settings.operations.trusted_hosts),
    )

    async def shutdown_web_runtime() -> None:
        await jobs.shutdown()
        runtime.dispose()
        _LOGGER.info("production_runtime_stopped", extra={"application_role": "web"})

    app.router.add_event_handler("shutdown", shutdown_web_runtime)
    app.state.operations_preflight = report
    app.state.application_role = ApplicationRole.WEB.value
    _LOGGER.info(
        "production_runtime_ready",
        extra={
            "application_role": "web",
            "environment": settings.application.environment.value,
            "migration_current": prepared.diagnostics.schema_current,
        },
    )
    return WebRuntime(app, runtime, jobs)


async def run_worker(settings: RuntimeSettings | None = None) -> None:
    """Run the durable worker role until a process termination signal is received."""
    resolved = settings or load_runtime_settings()
    require_production_configuration(
        resolved.application,
        resolved.production,
        resolved.persistence,
        resolved.durable,
        resolved.artifacts,
        resolved.operations,
        repository_root=REPOSITORY_ROOT,
        role=ApplicationRole.WORKER,
    )
    report = run_preflight(
        resolved.application,
        resolved.production,
        resolved.persistence,
        resolved.durable,
        resolved.artifacts,
        resolved.operations,
        repository_root=REPOSITORY_ROOT,
        backend_root=BACKEND_ROOT,
        role=ApplicationRole.WORKER,
    )
    if not report.ready:
        raise RuntimeError("Production worker startup preflight failed.")
    runtime = create_persistence_runtime(
        resolved.persistence.to_configuration(), repository_root=REPOSITORY_ROOT
    )
    evidence = SQLAlchemyPersistenceRepository(runtime)
    prepared = PreparedPersistence(evidence, evidence.diagnostics(), None)
    artifact_service = ArtifactService(
        resolved.artifacts.to_configuration(), SQLAlchemyArtifactRepository(runtime)
    )

    def retain_generated_xml(job_id: str, result: CrawlRunResult) -> None:
        batch = artifact_service.retain_generated_xml(job_id, result)
        bundle = result.xml_bundle
        expected = (
            0 if bundle is None else len(bundle.documents) + int(bundle.index_document is not None)
        )
        if batch.failure_codes or len(batch.registered) != expected:
            raise RuntimeError("Generated XML artifact retention failed.")

    site_audit_orchestration: SiteAuditOrchestrationService | None = None

    async def reconcile_site_audits() -> int:
        return (
            0
            if site_audit_orchestration is None
            else await site_audit_orchestration.reconcile_pending(maximum_parents=25)
        )

    durable = prepare_durable_execution(
        resolved.durable,
        prepared,
        runtime=runtime,
        run_service_factory=production_run_service_factory(resolved.application),
        result_observer=retain_generated_xml,
        reconciliation_observer=reconcile_site_audits,
    )
    if durable.worker is None:
        runtime.dispose()
        raise RuntimeError("Durable worker composition is unavailable.")
    if durable.repository is None:
        runtime.dispose()
        raise RuntimeError("Durable worker repository is unavailable.")
    jobs = DurableJobService(durable.repository, worker=durable.worker)
    application_service = ProductionApplicationService(cast("InternalJobService", jobs), lambda: ())
    crawler_fetcher = _fetcher(resolved.application)
    configuration = resolved.persistence.to_configuration()
    metadata_audits = _metadata_service(configuration, runtime, artifact_service)
    sitemap_audits = _sitemap_service(configuration, runtime, crawler_fetcher, artifact_service)
    link_audits = _link_service(configuration, runtime, artifact_service)
    internal_link_audits = _internal_link_service(configuration, runtime, artifact_service)
    image_audits = _image_service(configuration, runtime, artifact_service)
    structured_data_audits = _structured_service(configuration, runtime, artifact_service)
    site_audit_orchestration = SiteAuditOrchestrationService(
        SQLAlchemySiteAuditRepository(runtime),
        SQLAlchemySiteAuditOrchestrationRepository(runtime),
        SQLAlchemyPageEvidenceRepository(runtime),
        ApplicationSiteAuditCrawlGateway(application_service),
        artifact_service,
        _specialist_gateway(
            runtime,
            metadata_audits=metadata_audits,
            sitemap_audits=sitemap_audits,
            link_audits=link_audits,
            internal_link_audits=internal_link_audits,
            image_audits=image_audits,
            structured_data_audits=structured_data_audits,
            launch_enabled=True,
        ),
    )
    stop = asyncio.Event()
    _install_stop_signals(stop)
    try:
        startup = await durable.worker.start()
        _LOGGER.info(
            "production_runtime_ready",
            extra={
                "application_role": "worker",
                "environment": resolved.application.environment.value,
                "worker_id": startup.worker_id,
            },
        )
        await stop.wait()
        shutdown = await asyncio.wait_for(
            durable.worker.shutdown(),
            timeout=resolved.operations.shutdown_timeout_seconds,
        )
        _LOGGER.info(
            "production_runtime_stopped",
            extra={
                "application_role": "worker",
                "worker_state": shutdown.final_state.value,
                "orphan_tasks": shutdown.orphan_tasks,
            },
        )
    finally:
        runtime.dispose()


def production_run_service_factory(
    application: Settings,
) -> JobRunServiceFactory:
    """Build the accepted live crawler factory once for one worker process."""
    fetcher = _fetcher(application)
    parser = HtmlMetadataParser()
    robots = RobotsTxtService.from_settings(fetcher, application)
    limits = CrawlHardLimits.from_settings(application)
    recommendation = SitemapRecommendationEngine()

    def factory(
        cancellation: CancellationToken,
        progress_sink: RunProgressSink,
    ) -> JobRunExecutor:
        crawler = SingleSiteCrawlOrchestrator(
            fetcher,
            parser,
            limits,
            robots,
            cancellation=cancellation,
        )
        return CrawlRunService(
            crawler,
            recommendation=recommendation,
            progress_sink=progress_sink,
            cancellation=cancellation,
        )

    return factory


def _fetcher(settings: Settings) -> SafeSingleUrlFetcher:
    return SafeSingleUrlFetcher(
        settings,
        DestinationSafetyValidator(settings, SystemAsyncResolver()),
    )


def _readiness_provider(
    persistence: SQLAlchemyPersistenceRepository,
    durable: SQLAlchemyDurableExecutionRepository,
    worker_id: str | None,
    artifacts: ArtifactService,
) -> ReadinessProvider:
    def checks() -> tuple[ReadinessCheck, ...]:
        persistence_state = persistence.diagnostics()
        artifact_states = artifacts.readiness()
        durable_state = durable.diagnostics(worker_id, recovery_complete=True)
        worker_ready = bool(
            durable_state.worker_registered
            and durable_state.worker_state is not None
            and durable_state.worker_state.value == "ready"
            and durable_state.heartbeat_healthy
        )
        return (
            ReadinessCheck(
                ReadinessCheckCode.PERSISTENCE_READY,
                (
                    ReadinessState.READY
                    if persistence_state.database_reachable
                    else ReadinessState.NOT_READY
                ),
                (
                    "Durable persistence is reachable."
                    if persistence_state.database_reachable
                    else "Durable persistence is unavailable."
                ),
            ),
            ReadinessCheck(
                ReadinessCheckCode.MIGRATION_CURRENT,
                (
                    ReadinessState.READY
                    if persistence_state.schema_current
                    else ReadinessState.NOT_READY
                ),
                (
                    "The database migration is current."
                    if persistence_state.schema_current
                    else "The database migration is not current."
                ),
            ),
            ReadinessCheck(
                ReadinessCheckCode.ARTIFACT_STORAGE_READY,
                (
                    ReadinessState.READY
                    if artifact_states and all(item.ready for item in artifact_states)
                    else ReadinessState.NOT_READY
                ),
                (
                    "Configured artifact storage is accessible."
                    if artifact_states and all(item.ready for item in artifact_states)
                    else "Configured artifact storage is unavailable."
                ),
            ),
            ReadinessCheck(
                ReadinessCheckCode.WORKER_AVAILABLE,
                ReadinessState.READY if worker_ready else ReadinessState.NOT_READY,
                (
                    "The configured durable worker is available."
                    if worker_ready
                    else "The configured durable worker is unavailable."
                ),
            ),
        )

    return checks


def _metadata_service(
    configuration: PersistenceConfiguration,
    runtime: PersistenceRuntime,
    artifacts: ArtifactService,
) -> MetadataAuditService | None:
    value = configuration.metadata_audit
    return (
        MetadataAuditService(value, SQLAlchemyMetadataAuditRepository(runtime), artifacts)
        if value.enabled
        else None
    )


def _sitemap_service(
    configuration: PersistenceConfiguration,
    runtime: PersistenceRuntime,
    fetcher: SafeSingleUrlFetcher,
    artifacts: ArtifactService,
) -> SitemapAuditService | None:
    value = configuration.sitemap_audit
    return (
        SitemapAuditService(value, SQLAlchemySitemapAuditRepository(runtime), fetcher, artifacts)
        if value.enabled
        else None
    )


def _link_service(
    configuration: PersistenceConfiguration,
    runtime: PersistenceRuntime,
    artifacts: ArtifactService,
) -> LinkAuditService | None:
    value = configuration.link_audit
    return (
        LinkAuditService(value, SQLAlchemyLinkAuditRepository(runtime), artifacts)
        if value.enabled
        else None
    )


def _internal_link_service(
    configuration: PersistenceConfiguration,
    runtime: PersistenceRuntime,
    artifacts: ArtifactService,
) -> InternalLinkAuditService | None:
    value = configuration.internal_link
    return (
        InternalLinkAuditService(value, SQLAlchemyInternalLinkRepository(runtime), artifacts)
        if value.enabled
        else None
    )


def _image_service(
    configuration: PersistenceConfiguration,
    runtime: PersistenceRuntime,
    artifacts: ArtifactService,
) -> ImageAuditService | None:
    value = configuration.image_audit
    return (
        ImageAuditService(value, SQLAlchemyImageAuditRepository(runtime), artifacts)
        if value.enabled
        else None
    )


def _structured_service(
    configuration: PersistenceConfiguration,
    runtime: PersistenceRuntime,
    artifacts: ArtifactService,
) -> StructuredDataAuditService | None:
    value = configuration.structured_data_audit
    return (
        StructuredDataAuditService(
            value, SQLAlchemyStructuredDataAuditRepository(runtime), artifacts
        )
        if value.enabled
        else None
    )


def _migration_qa_service(
    configuration: PersistenceConfiguration,
    runtime: PersistenceRuntime,
    artifacts: ArtifactService,
) -> MigrationQaService | None:
    value = configuration.migration_qa
    return (
        MigrationQaService(value, SQLAlchemyMigrationQaRepository(runtime), artifacts)
        if value.enabled
        else None
    )


def _site_audit_settings_service(runtime: PersistenceRuntime) -> SiteAuditSettingsService:
    return SiteAuditSettingsService(
        SiteAuditSettingsConfiguration(enabled=True),
        SQLAlchemySiteAuditSettingsRepository(runtime),
    )


def _specialist_gateway(  # noqa: C901, PLR0913 - accepted authorities are explicit.
    runtime: PersistenceRuntime,
    *,
    metadata_audits: MetadataAuditService | None,
    sitemap_audits: SitemapAuditService | None,
    link_audits: LinkAuditService | None,
    internal_link_audits: InternalLinkAuditService | None,
    image_audits: ImageAuditService | None,
    structured_data_audits: StructuredDataAuditService | None,
    launch_enabled: bool,
) -> SQLAlchemySiteAuditSpecialistGateway:
    authorities: dict[SiteAuditStage, SpecialistAuthority] = {}
    if metadata_audits is not None:
        authorities[SiteAuditStage.METADATA] = SpecialistAuthority(
            SQLAlchemyMetadataAuditRepository(runtime),
            launch=(metadata_audits.create_and_run_audit if launch_enabled else None),
        )
    if sitemap_audits is not None:

        async def launch_sitemap(run_id: str) -> dict[str, object]:
            return await sitemap_audits.create_and_run(run_id, DiscoveryOptions())

        authorities[SiteAuditStage.EXISTING_SITEMAP] = SpecialistAuthority(
            SQLAlchemySitemapAuditRepository(runtime),
            document_method="list_documents",
            entry_method="list_entries",
            launch=launch_sitemap if launch_enabled else None,
        )
    if link_audits is not None:

        async def launch_link(run_id: str) -> dict[str, object]:
            created = link_audits.create_audit(run_id)
            return await link_audits.execute_audit(str(created["audit_id"]))

        authorities[SiteAuditStage.BROKEN_LINKS] = SpecialistAuthority(
            SQLAlchemyLinkAuditRepository(runtime),
            launch=launch_link if launch_enabled else None,
        )
    if internal_link_audits is not None:

        async def launch_internal_link(run_id: str) -> dict[str, object]:
            created = internal_link_audits.create_audit(run_id)
            return await internal_link_audits.execute_audit(str(created["audit_id"]))

        authorities[SiteAuditStage.INTERNAL_LINKS] = SpecialistAuthority(
            SQLAlchemyInternalLinkRepository(runtime),
            launch=launch_internal_link if launch_enabled else None,
        )
    if image_audits is not None:

        async def launch_image(run_id: str) -> dict[str, object]:
            created = image_audits.create_audit(run_id)
            return await image_audits.execute_audit(str(created["audit_id"]))

        authorities[SiteAuditStage.IMAGES] = SpecialistAuthority(
            SQLAlchemyImageAuditRepository(runtime),
            launch=launch_image if launch_enabled else None,
            paginated_list=False,
        )
    if structured_data_audits is not None:

        async def launch_structured(run_id: str) -> dict[str, object]:
            created = structured_data_audits.create_audit(run_id)
            return await structured_data_audits.execute_audit(str(created["audit_id"]))

        authorities[SiteAuditStage.STRUCTURED_DATA] = SpecialistAuthority(
            SQLAlchemyStructuredDataAuditRepository(runtime),
            launch=launch_structured if launch_enabled else None,
            paginated_list=False,
        )
    return SQLAlchemySiteAuditSpecialistGateway(authorities)


def _install_stop_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError, RuntimeError:
            signal.signal(signum, lambda *_args: loop.call_soon_threadsafe(stop.set))
