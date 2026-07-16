"""Structured internal API errors and bounded exception normalization."""

from __future__ import annotations

import logging
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

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

_LOGGER = logging.getLogger(__name__)
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
        del request
        return error_response(error)

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
        return error_response(
            InternalApiError(
                400,
                ApiErrorCode.REQUEST_VALIDATION_FAILED,
                "The request schema is invalid.",
                tuple(_domain_detail(item) for item in details),
            )
        )

    @application.exception_handler(Exception)
    async def internal_unexpected_error_handler(
        request: Request,
        error: Exception,
    ) -> JSONResponse:
        if not request.url.path.startswith(configuration.route_prefix):
            raise error
        _LOGGER.exception(
            "internal_api_unexpected_error path=%s method=%s",
            request.url.path,
            request.method,
        )
        return error_response(
            InternalApiError(
                500,
                ApiErrorCode.INTERNAL_API_ERROR,
                "The internal API could not complete the request.",
            )
        )


def error_response(error: InternalApiError) -> JSONResponse:
    envelope = ApiErrorEnvelope(
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
        )
    )
    return JSONResponse(status_code=error.status_code, content=envelope.model_dump(mode="json"))


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
