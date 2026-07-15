"""Health endpoint for the API process."""

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Stable, intentionally minimal public health response."""

    model_config = ConfigDict(frozen=True)

    application: str
    status: str


def create_health_router(application_name: str) -> APIRouter:
    """Create a health router bound to the configured application name."""
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(application=application_name, status="healthy")

    return router
