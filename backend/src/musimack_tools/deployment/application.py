"""Explicit, fail-closed production application composition."""

from __future__ import annotations

from ipaddress import IPv4Network, IPv6Network, ip_network
from typing import TYPE_CHECKING

from fastapi import FastAPI
from pydantic import ValidationError

from musimack_tools.api.health import create_health_router
from musimack_tools.api.internal import mount_internal_api
from musimack_tools.core.config import Settings, get_settings
from musimack_tools.core.logging import configure_logging
from musimack_tools.deployment.settings import ProductionSettings
from musimack_tools.domain.api import InternalApiConfiguration
from musimack_tools.domain.deployment import (
    ProductionApplicationConfiguration,
    ProductionConfigurationError,
    StartupValidationIssue,
    StartupValidationOutcome,
    StartupValidationReport,
)
from musimack_tools.domain.persistence import PersistenceReadinessState
from musimack_tools.domain.security import (
    AccessLogConfiguration,
    CorrelationConfiguration,
    CorsConfiguration,
    CredentialSourceConfiguration,
    InternalAuthenticationConfiguration,
    SecurityHeaderConfiguration,
    TrustedNetworkConfiguration,
    TrustedProxyConfiguration,
)
from musimack_tools.security.authentication import BearerAccessVerifier
from musimack_tools.security.correlation import CorrelationMiddleware
from musimack_tools.security.cors import add_internal_cors
from musimack_tools.security.headers import SecurityHeadersMiddleware
from musimack_tools.security.logging import AccessLoggingMiddleware
from musimack_tools.security.validation import security_readiness, validate_production_startup

if TYPE_CHECKING:
    from musimack_tools.api.dependencies import InternalApiApplication
    from musimack_tools.artifacts.service import ArtifactService
    from musimack_tools.deployment.persistence_runtime import PreparedPersistence
    from musimack_tools.deployment.worker import PreparedDurableExecution

Network = IPv4Network | IPv6Network


def create_production_app(  # noqa: C901, PLR0912, PLR0913, PLR0915
    service: InternalApiApplication,
    settings: ProductionSettings | None = None,
    application_settings: Settings | None = None,
    persistence: PreparedPersistence | None = None,
    durable: PreparedDurableExecution | None = None,
    artifacts: ArtifactService | None = None,
) -> FastAPI:
    """Create an authenticated internal app, rejecting invalid startup configuration."""
    try:
        resolved = settings or ProductionSettings()
    except ValidationError as error:
        del error
        raise _configuration_error("security_settings_invalid") from None
    report = validate_production_startup(resolved, service)
    if report.outcome is StartupValidationOutcome.INVALID:
        raise ProductionConfigurationError(report)
    if persistence is not None and persistence.diagnostics.state not in {
        PersistenceReadinessState.READY,
        PersistenceReadinessState.DISABLED,
    }:
        raise _configuration_error("persistence_not_ready")
    if durable is not None and durable.configuration.enabled:
        if (
            persistence is None
            or persistence.diagnostics.state is not PersistenceReadinessState.READY
        ):
            raise _configuration_error("durable_persistence_required")
        if not persistence.diagnostics.schema_current:
            raise _configuration_error("durable_migration_required")

    core_settings = application_settings or get_settings()
    configure_logging(core_settings)
    configuration = production_configuration(resolved)
    bearer_token = resolved.bearer_token
    if bearer_token is None:
        raise _configuration_error("security_credential_missing")
    verifier = BearerAccessVerifier(
        enabled=configuration.authentication.enabled,
        expected_credential=bearer_token.get_secret_value(),
        credential_id=configuration.authentication.credential_source.credential_id,
        trusted_networks=configuration.trusted_networks,
        trusted_proxies=configuration.trusted_proxies,
    )
    application = FastAPI(
        title=core_settings.application_name,
        openapi_url="/openapi.json" if configuration.include_openapi else None,
        docs_url="/docs" if configuration.include_openapi else None,
        redoc_url=None,
    )
    application.include_router(create_health_router(core_settings.application_name), prefix="/api")
    mounted = mount_internal_api(
        application,
        service,
        InternalApiConfiguration(
            mount_internal_routes=True,
            include_internal_routes_in_schema=configuration.include_openapi,
            include_internal_endpoints_in_docs=configuration.include_openapi,
            access_verifier=verifier,
        ),
    )
    if not mounted:
        raise _configuration_error("internal_router_not_mounted")
    if artifacts is not None and artifacts.configuration.enabled:
        from musimack_tools.api.artifacts import create_artifact_router  # noqa: PLC0415

        readiness = artifacts.readiness()
        if not readiness or any(not item.ready for item in readiness):
            raise _configuration_error("artifact_storage_not_ready")
        if artifacts.configuration.reconcile_on_startup:
            application.state.artifact_reconciliation = artifacts.reconcile()
        application.include_router(
            create_artifact_router(
                artifacts,
                InternalApiConfiguration(
                    mount_internal_routes=True,
                    include_internal_routes_in_schema=configuration.include_openapi,
                    include_internal_endpoints_in_docs=configuration.include_openapi,
                    access_verifier=verifier,
                ),
            )
        )
        application.state.artifact_readiness = readiness

    add_internal_cors(
        application,
        configuration.cors,
        request_id_header=configuration.correlation.header_name,
    )
    if configuration.security_headers.enabled:
        application.add_middleware(SecurityHeadersMiddleware)
    if configuration.access_logging.enabled:
        application.add_middleware(AccessLoggingMiddleware)
    application.add_middleware(
        CorrelationMiddleware,
        header_name=configuration.correlation.header_name,
        maximum_length=configuration.correlation.maximum_length,
    )
    application.state.production_configuration = configuration
    application.state.startup_validation = report
    application.state.security_readiness = security_readiness(resolved)
    if persistence is not None:
        application.state.persistence_readiness = persistence.diagnostics
    if durable is not None:
        application.state.durable_readiness = durable.diagnostics
        if durable.worker is not None:
            worker = durable.worker
            repository = durable.repository
            worker_id = durable.configuration.worker_id

            async def start_durable_worker() -> None:
                await worker.start()
                if repository is not None and worker_id is not None:
                    application.state.durable_readiness = repository.diagnostics(
                        worker_id.value, recovery_complete=True
                    )

            async def stop_durable_worker() -> None:
                await worker.shutdown()
                if repository is not None and worker_id is not None:
                    application.state.durable_readiness = repository.diagnostics(
                        worker_id.value, recovery_complete=True
                    )

            application.router.add_event_handler("startup", start_durable_worker)
            application.router.add_event_handler("shutdown", stop_durable_worker)
    return application


def production_configuration(settings: ProductionSettings) -> ProductionApplicationConfiguration:
    trusted_networks = TrustedNetworkConfiguration(_parse_networks(settings.trusted_networks))
    trusted_proxies = TrustedProxyConfiguration(
        _parse_networks(settings.trusted_proxies),
        settings.maximum_forwarded_hops,
        settings.maximum_forwarded_header_length,
    )
    return ProductionApplicationConfiguration(
        authentication=InternalAuthenticationConfiguration(
            enabled=settings.enabled,
            credential_source=CredentialSourceConfiguration(
                credential_id=settings.token_id,
                credential_configured=settings.bearer_token is not None,
            ),
        ),
        include_openapi=settings.include_openapi,
        trusted_networks=trusted_networks,
        trusted_proxies=trusted_proxies,
        cors=CorsConfiguration(
            settings.cors_enabled,
            settings.allowed_origins,
            settings.maximum_cors_age_seconds,
        ),
        correlation=CorrelationConfiguration(settings.request_id_header),
        security_headers=SecurityHeaderConfiguration(settings.security_headers),
        access_logging=AccessLogConfiguration(settings.access_logging),
    )


def _parse_networks(values: tuple[str, ...]) -> tuple[Network, ...]:
    return tuple(ip_network(value, strict=False) for value in values)


def _configuration_error(code: str) -> ProductionConfigurationError:
    return ProductionConfigurationError(
        StartupValidationReport(
            StartupValidationOutcome.INVALID,
            (
                StartupValidationIssue(
                    code,
                    "Production security configuration is invalid.",
                    blocking=True,
                ),
            ),
        )
    )
