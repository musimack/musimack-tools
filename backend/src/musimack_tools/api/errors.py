"""Structured internal API errors and bounded exception normalization."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from musimack_tools.api.schemas import (
    ApiErrorDataSchema,
    ApiErrorDetailSchema,
    ApiErrorEnvelope,
)
from musimack_tools.domain.api import (
    ApiErrorCode,
    ApiErrorDetail,
    InternalApiConfiguration,
    InternalApiError,
)
from musimack_tools.security.headers import SECURITY_HEADERS
from musimack_tools.security.logging import log_unhandled_access_event

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

_INVALID_FIELD_MESSAGE = "The field is invalid."


def install_internal_api_error_handlers(
    application: FastAPI,
    configuration: InternalApiConfiguration,
) -> None:
    """Install bounded handlers only when internal routes are explicitly mounted."""

    @application.exception_handler(InternalApiError)
    async def internal_api_error_handler(
        request: Request,
        error: InternalApiError,
    ) -> JSONResponse:
        return error_response(error, request_id=getattr(request.state, "request_id", None))

    @application.exception_handler(RequestValidationError)
    async def internal_validation_error_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        if not request.url.path.startswith(configuration.route_prefix):
            return await request_validation_exception_handler(request, error)
        details = tuple(
            _validation_detail(item)
            for item in error.errors()[: configuration.maximum_validation_details]
        )
        response = error_response(
            InternalApiError(
                400,
                ApiErrorCode.REQUEST_VALIDATION_FAILED,
                "The request schema is invalid.",
                tuple(_domain_detail(item) for item in details),
            ),
            request_id=getattr(request.state, "request_id", None),
        )
        _apply_outer_production_headers(request, response)
        return response

    @application.exception_handler(Exception)
    async def internal_unexpected_error_handler(
        request: Request,
        error: Exception,
    ) -> JSONResponse:
        if not request.url.path.startswith(configuration.route_prefix):
            raise error
        log_unhandled_access_event(request, exception_type=type(error).__name__)
        response = error_response(
            InternalApiError(
                500,
                ApiErrorCode.INTERNAL_API_ERROR,
                "The internal API could not complete the request.",
            ),
            request_id=getattr(request.state, "request_id", None),
        )
        _apply_outer_production_headers(request, response)
        return response


def error_response(error: InternalApiError, *, request_id: str | None = None) -> JSONResponse:
    envelope = ApiErrorEnvelope(
        request_id=request_id,
        error=ApiErrorDataSchema(
            code=error.code.value,
            message=error.message,
            details=tuple(
                ApiErrorDetailSchema(
                    code=item.code,
                    message=item.message,
                    field=item.field,
                    source_code=item.source_code,
                )
                for item in error.details
            ),
        ),
    )
    return JSONResponse(
        status_code=error.status_code,
        content=envelope.model_dump(mode="json"),
        headers=dict(error.headers),
    )


def _validation_detail(value: dict[str, Any]) -> ApiErrorDetailSchema:
    location = value.get("loc", ())
    field = ".".join(str(item) for item in location if item not in {"body", "path", "query"})
    code = str(value.get("type", "invalid"))
    return ApiErrorDetailSchema(
        code=code,
        message=_INVALID_FIELD_MESSAGE,
        field=field or None,
    )


def _domain_detail(value: ApiErrorDetailSchema) -> ApiErrorDetail:
    return ApiErrorDetail(
        code=value.code,
        message=value.message,
        field=value.field,
        source_code=value.source_code,
    )


def _apply_outer_production_headers(request: Request, response: JSONResponse) -> None:
    """Apply headers when Starlette handles an exception outside user middleware."""
    configuration = getattr(request.app.state, "production_configuration", None)
    if configuration is None:
        return
    if configuration.security_headers.enabled:
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
    request_id = getattr(request.state, "request_id", None)
    if request_id is not None:
        response.headers[configuration.correlation.header_name] = request_id
