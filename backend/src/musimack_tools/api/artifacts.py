"""Authenticated internal artifact metadata and bounded download routes."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic requires the runtime type.
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import Field

from musimack_tools.api.dependencies import create_access_dependency
from musimack_tools.api.schemas import ApiErrorEnvelope, ApiSchema
from musimack_tools.domain.api import ApiErrorCode, InternalApiConfiguration, InternalApiError
from musimack_tools.domain.artifacts import (
    ARTIFACT_RECONCILIATION_VERSION,
    ARTIFACT_RETRIEVAL_VERSION,
    ARTIFACT_STORAGE_VERSION,
    ArtifactError,
    ArtifactFailureCode,
    ArtifactRecord,
)
from musimack_tools.security.correlation import current_request_id

_INVALID_ARTIFACT_SERVICE = "artifact routes require an ArtifactService"


class ArtifactMetadataSchema(ApiSchema):
    artifact_id: str
    job_id: str
    run_id: str
    artifact_type: str
    lifecycle_state: str
    integrity_state: str
    filename: str
    content_type: str
    byte_count: int
    created_at: datetime
    available_at: datetime | None
    last_verified_at: datetime | None
    expires_at: datetime | None
    retention_state: str
    download_available: bool
    reason_code: str | None
    storage_version: str = ARTIFACT_STORAGE_VERSION
    retrieval_version: str = ARTIFACT_RETRIEVAL_VERSION
    reconciliation_version: str = ARTIFACT_RECONCILIATION_VERSION


class ArtifactListDataSchema(ApiSchema):
    offset: int
    limit: int
    items: tuple[ArtifactMetadataSchema, ...]


class ArtifactDetailResponse(ApiSchema):
    api_version: str
    request_id: str | None = Field(default_factory=current_request_id)
    data: ArtifactMetadataSchema


class ArtifactListResponse(ApiSchema):
    api_version: str
    request_id: str | None = Field(default_factory=current_request_id)
    data: ArtifactListDataSchema


def create_artifact_router(
    service: object,
    configuration: InternalApiConfiguration,
) -> APIRouter:
    """Build three private routes using the accepted access verifier."""
    from musimack_tools.artifacts.service import ArtifactService  # noqa: PLC0415

    if not isinstance(service, ArtifactService):
        raise TypeError(_INVALID_ARTIFACT_SERVICE)
    access = create_access_dependency(configuration)
    include = (
        configuration.include_internal_routes_in_schema
        and configuration.include_internal_endpoints_in_docs
    )
    router = APIRouter(
        prefix=f"{configuration.route_prefix}/artifacts",
        dependencies=[Depends(access)],
        include_in_schema=include,
    )
    errors: dict[int | str, dict[str, Any]] = {
        401: {"model": ApiErrorEnvelope},
        403: {"model": ApiErrorEnvelope},
        404: {"model": ApiErrorEnvelope},
        409: {"model": ApiErrorEnvelope},
        503: {"model": ApiErrorEnvelope},
    }

    @router.get("", response_model=ArtifactListResponse, responses=errors)
    async def list_artifacts(
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> ArtifactListResponse:
        items = service.list(offset=offset, limit=limit)
        return ArtifactListResponse(
            api_version=configuration.api_version,
            data=ArtifactListDataSchema(
                offset=offset, limit=limit, items=tuple(_schema(item) for item in items)
            ),
        )

    @router.get("/{artifact_id}", response_model=ArtifactDetailResponse, responses=errors)
    async def artifact_detail(artifact_id: str) -> ArtifactDetailResponse:
        try:
            record = service.get(artifact_id)
        except ArtifactError as error:
            raise _api_error(error) from None
        return ArtifactDetailResponse(
            api_version=configuration.api_version,
            data=_schema(record),
        )

    @router.get("/{artifact_id}/download", responses=errors, response_model=None)
    async def download_artifact(artifact_id: str) -> StreamingResponse:
        try:
            descriptor = service.prepare_download(artifact_id)
        except ArtifactError as error:
            raise _api_error(error) from None
        return StreamingResponse(
            descriptor.iterator_factory(),
            media_type=descriptor.content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{descriptor.filename}"',
                "Content-Length": str(descriptor.byte_count),
                "Accept-Ranges": "none",
            },
        )

    return router


def _schema(record: ArtifactRecord) -> ArtifactMetadataSchema:
    return ArtifactMetadataSchema(
        artifact_id=record.artifact_id,
        job_id=record.job_id,
        run_id=record.run_id,
        artifact_type=record.artifact_type.value,
        lifecycle_state=record.lifecycle_state.value,
        integrity_state=record.integrity_state.value,
        filename=record.filename,
        content_type=record.content_type,
        byte_count=record.expected_byte_count,
        created_at=record.created_at,
        available_at=record.available_at,
        last_verified_at=record.last_verified_at,
        expires_at=record.expires_at,
        retention_state=record.retention_state.value,
        download_available=(
            record.lifecycle_state.value in {"available", "retained"}
            and record.integrity_state.value == "verified"
        ),
        reason_code=record.reason_code,
    )


def _api_error(error: ArtifactError) -> InternalApiError:
    if error.code is ArtifactFailureCode.NOT_FOUND:
        return InternalApiError(404, ApiErrorCode.ARTIFACT_NOT_FOUND, "Artifact was not found.")
    if error.code in {
        ArtifactFailureCode.NOT_AVAILABLE,
        ArtifactFailureCode.MISSING,
        ArtifactFailureCode.CORRUPT,
        ArtifactFailureCode.EXPIRED,
        ArtifactFailureCode.DELETED,
    }:
        return InternalApiError(
            409, ApiErrorCode.ARTIFACT_NOT_AVAILABLE, "Artifact is not available."
        )
    return InternalApiError(
        503, ApiErrorCode.ARTIFACT_RETRIEVAL_FAILED, "Artifact retrieval could not complete."
    )
