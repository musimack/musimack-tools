"""Dependency composition for the private internal API adapter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol

from fastapi import Request

from musimack_tools.api.access import DenyAllAccessVerifier
from musimack_tools.domain.api import (
    AccessDenialReason,
    AccessOutcome,
    ApiErrorCode,
    InternalApiConfiguration,
    InternalApiError,
    InternalCallerContext,
)

if TYPE_CHECKING:
    from musimack_tools.domain.application import (
        ApplicationCancellationResult,
        ApplicationJobStatus,
        ApplicationPreflightResult,
        ApplicationProgressResult,
        ApplicationReadinessReport,
        ApplicationRegistryStatus,
        ApplicationResultProjection,
        ApplicationSubmissionResult,
        ApplicationValidationReport,
        RawApplicationCrawlRequest,
    )
    from musimack_tools.domain.capabilities import ApplicationCapabilityReport

AccessDependency = Callable[[Request], Awaitable[InternalCallerContext | None]]


class InternalApiApplication(Protocol):
    def validate_request(self, raw: RawApplicationCrawlRequest) -> ApplicationValidationReport: ...

    async def preflight(self, raw: RawApplicationCrawlRequest) -> ApplicationPreflightResult: ...

    async def submit(self, raw: RawApplicationCrawlRequest) -> ApplicationSubmissionResult: ...

    async def get_job_status(self, job_id: str) -> ApplicationJobStatus: ...

    async def get_job_progress(self, job_id: str) -> ApplicationProgressResult: ...

    async def get_job_result(self, job_id: str) -> ApplicationResultProjection: ...

    async def cancel_job(self, job_id: str) -> ApplicationCancellationResult: ...

    async def get_registry_status(self) -> ApplicationRegistryStatus: ...

    async def get_readiness(self) -> ApplicationReadinessReport: ...

    def get_capabilities(self) -> ApplicationCapabilityReport: ...


def create_access_dependency(configuration: InternalApiConfiguration) -> AccessDependency:
    """Create a fail-closed dependency bound to one immutable configuration."""
    verifier = configuration.access_verifier or DenyAllAccessVerifier()

    async def require_internal_access(request: Request) -> InternalCallerContext | None:
        try:
            decision = await verifier.verify(request)
        except Exception:  # noqa: BLE001 - verifier failures must fail closed.
            raise InternalApiError(
                403,
                ApiErrorCode.ACCESS_VERIFIER_UNAVAILABLE,
                "Internal access verification is unavailable.",
            ) from None
        if decision.outcome is AccessOutcome.UNAVAILABLE:
            raise InternalApiError(
                403,
                ApiErrorCode.ACCESS_VERIFIER_UNAVAILABLE,
                "Internal access verification is unavailable.",
            )
        if decision.outcome is not AccessOutcome.ALLOWED:
            code = (
                ApiErrorCode.ACCESS_VERIFIER_UNAVAILABLE
                if decision.reason is AccessDenialReason.ACCESS_VERIFIER_UNAVAILABLE
                else ApiErrorCode.ACCESS_DENIED
            )
            raise InternalApiError(403, code, "Internal API access is denied.")
        return decision.caller

    return require_internal_access


def enforce_declared_body_limit(configuration: InternalApiConfiguration) -> AccessDependency:
    """Reject an explicitly oversized Content-Length without consuming the body."""

    async def enforce(request: Request) -> InternalCallerContext | None:
        raw_length = request.headers.get("content-length")
        if raw_length is None:
            return None
        try:
            length = int(raw_length)
        except ValueError:
            raise InternalApiError(
                400,
                ApiErrorCode.REQUEST_VALIDATION_FAILED,
                "The request metadata is invalid.",
            ) from None
        if length < 0:
            raise InternalApiError(
                400,
                ApiErrorCode.REQUEST_VALIDATION_FAILED,
                "The request metadata is invalid.",
            )
        if length > configuration.maximum_request_body_bytes:
            raise InternalApiError(
                413,
                ApiErrorCode.REQUEST_BODY_TOO_LARGE,
                "The request body exceeds the internal API limit.",
            )
        return None

    return enforce
