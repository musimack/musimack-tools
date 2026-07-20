"""FastAPI application composition root."""

from fastapi import FastAPI

from musimack_tools.api.health import create_health_router
from musimack_tools.core.config import Settings, get_settings
from musimack_tools.core.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a testable API application without starting background work."""
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)
    application = FastAPI(
        title=resolved_settings.application_name,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    application.include_router(
        create_health_router(resolved_settings.application_name),
        prefix="/api",
    )
    return application


app = create_app()
