"""Explicit, fail-closed production application composition."""

from __future__ import annotations

from ipaddress import IPv4Network, IPv6Network, ip_network
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, Response
from pydantic import ValidationError

from musimack_tools.api.health import create_health_router
from musimack_tools.api.internal import mount_internal_api
from musimack_tools.core.config import Settings, get_settings
from musimack_tools.core.logging import configure_logging
from musimack_tools.deployment.settings import ProductionSettings, authentication_configuration
from musimack_tools.domain.api import InternalApiConfiguration
from musimack_tools.domain.authentication import AuthenticationMode, UserRole
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
from musimack_tools.security.session_authentication import SessionAccessVerifier
from musimack_tools.security.validation import security_readiness, validate_production_startup

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from musimack_tools.api.access import InternalAccessVerifier
    from musimack_tools.api.dependencies import InternalApiApplication
    from musimack_tools.artifacts.service import ArtifactService
    from musimack_tools.authentication.service import AuthenticationService
    from musimack_tools.deployment.persistence_runtime import PreparedPersistence
    from musimack_tools.deployment.worker import PreparedDurableExecution
    from musimack_tools.history.service import HistoryService
    from musimack_tools.link_audit.service import LinkAuditService
    from musimack_tools.metadata_audit.service import MetadataAuditService
    from musimack_tools.sitemap_audit.service import SitemapAuditService

Network = IPv4Network | IPv6Network


def create_production_app(  # noqa: C901, PLR0912, PLR0913, PLR0915
    service: InternalApiApplication,
    settings: ProductionSettings | None = None,
    application_settings: Settings | None = None,
    persistence: PreparedPersistence | None = None,
    durable: PreparedDurableExecution | None = None,
    artifacts: ArtifactService | None = None,
    history: HistoryService | None = None,
    authentication: AuthenticationService | None = None,
    metadata_audits: MetadataAuditService | None = None,
    sitemap_audits: SitemapAuditService | None = None,
    link_audits: LinkAuditService | None = None,
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
    auth_configuration = authentication_configuration(resolved)
    bearer_token = resolved.bearer_token
    bearer_verifier = (
        BearerAccessVerifier(
            enabled=configuration.authentication.enabled,
            expected_credential=bearer_token.get_secret_value(),
            credential_id=configuration.authentication.credential_source.credential_id,
            trusted_networks=configuration.trusted_networks,
            trusted_proxies=configuration.trusted_proxies,
            compatibility_role=(
                UserRole.ADMINISTRATOR
                if auth_configuration.shared_bearer_compatibility_admin
                else UserRole.OPERATOR
            ),
        )
        if bearer_token is not None
        else None
    )
    verifier: InternalAccessVerifier
    if auth_configuration.enabled:
        if authentication is None:
            raise _configuration_error("authentication_service_required")
        if auth_configuration.mode is AuthenticationMode.SHARED_BEARER:
            if bearer_verifier is None:
                raise _configuration_error("security_credential_missing")
            verifier = bearer_verifier
        else:
            verifier = SessionAccessVerifier(
                authentication,
                auth_configuration,
                bearer_verifier=bearer_verifier,
                trusted_networks=configuration.trusted_networks,
                trusted_proxies=configuration.trusted_proxies,
            )
    else:
        if bearer_verifier is None:
            raise _configuration_error("security_credential_missing")
        verifier = bearer_verifier
    application = FastAPI(
        title=core_settings.application_name,
        openapi_url="/openapi.json" if configuration.include_openapi else None,
        docs_url="/docs" if configuration.include_openapi else None,
        redoc_url=None,
    )
    if (
        auth_configuration.enabled
        and auth_configuration.mode is not AuthenticationMode.SHARED_BEARER
    ):

        @application.middleware("http")
        async def apply_rotated_session_cookie(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            response = await call_next(request)
            replacement = getattr(request.state, "session_replacement_token", None)
            if isinstance(replacement, str):
                response.set_cookie(
                    auth_configuration.session_cookie_name,
                    replacement,
                    max_age=auth_configuration.session_lifetime_minutes * 60,
                    httponly=True,
                    secure=auth_configuration.require_secure_cookie,
                    samesite="strict",
                    path="/api/internal/v1",
                )
            return response

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
    if auth_configuration.enabled and authentication is not None:
        from musimack_tools.api.authentication import create_authentication_router  # noqa: PLC0415

        application.include_router(
            create_authentication_router(
                authentication,
                InternalApiConfiguration(
                    mount_internal_routes=True,
                    include_internal_routes_in_schema=configuration.include_openapi,
                    include_internal_endpoints_in_docs=configuration.include_openapi,
                    access_verifier=verifier,
                ),
            )
        )
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
    if history is not None and history.configuration.enabled:
        from musimack_tools.api.history import create_history_router  # noqa: PLC0415

        diagnostics = history.diagnostics()
        if not diagnostics.database_ready or not diagnostics.migration_ready:
            raise _configuration_error("history_not_ready")
        application.include_router(
            create_history_router(
                history,
                InternalApiConfiguration(
                    mount_internal_routes=True,
                    include_internal_routes_in_schema=configuration.include_openapi,
                    include_internal_endpoints_in_docs=configuration.include_openapi,
                    access_verifier=verifier,
                ),
            )
        )
        application.state.history_diagnostics = diagnostics
    if metadata_audits is not None and metadata_audits.configuration.enabled:
        from musimack_tools.api.metadata_audit import create_metadata_audit_router  # noqa: PLC0415

        audit_diagnostics = metadata_audits.get_diagnostics()
        if not audit_diagnostics["persistence_ready"] or not audit_diagnostics["migration_ready"]:
            raise _configuration_error("metadata_audit_not_ready")
        application.include_router(
            create_metadata_audit_router(
                metadata_audits,
                InternalApiConfiguration(
                    mount_internal_routes=True,
                    include_internal_routes_in_schema=configuration.include_openapi,
                    include_internal_endpoints_in_docs=configuration.include_openapi,
                    access_verifier=verifier,
                ),
            )
        )
        application.state.metadata_audit_diagnostics = audit_diagnostics
    if sitemap_audits is not None and sitemap_audits.configuration.enabled:
        from musimack_tools.api.sitemap_audit import create_sitemap_audit_router  # noqa: PLC0415

        sitemap_diagnostics = sitemap_audits.diagnostics()
        if (
            not sitemap_diagnostics["persistence_ready"]
            or not sitemap_diagnostics["migration_ready"]
        ):
            raise _configuration_error("sitemap_audit_not_ready")
        application.include_router(
            create_sitemap_audit_router(
                sitemap_audits,
                InternalApiConfiguration(
                    mount_internal_routes=True,
                    include_internal_routes_in_schema=configuration.include_openapi,
                    include_internal_endpoints_in_docs=configuration.include_openapi,
                    access_verifier=verifier,
                ),
            )
        )
        application.state.sitemap_audit_diagnostics = sitemap_diagnostics
    if link_audits is not None and link_audits.configuration.enabled:
        from musimack_tools.api.link_audit import create_link_audit_router  # noqa: PLC0415

        link_diagnostics = link_audits.diagnostics()
        if not link_diagnostics["persistence_ready"] or not link_diagnostics["migration_ready"]:
            raise _configuration_error("link_audit_not_ready")
        application.include_router(
            create_link_audit_router(
                link_audits,
                InternalApiConfiguration(
                    mount_internal_routes=True,
                    include_internal_routes_in_schema=configuration.include_openapi,
                    include_internal_endpoints_in_docs=configuration.include_openapi,
                    access_verifier=verifier,
                ),
            )
        )
        application.state.link_audit_diagnostics = link_diagnostics

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
    if authentication is not None:
        application.state.authentication_diagnostics = authentication.diagnostics()
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
