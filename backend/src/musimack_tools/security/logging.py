"""Audit-safe, query-free access events for the explicit internal application."""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from musimack_tools.domain.api import INTERNAL_API_VERSION
from musimack_tools.domain.security import SECURITY_VERSION

if TYPE_CHECKING:
    from fastapi import Request, Response
    from starlette.types import ASGIApp

_LOGGER = logging.getLogger("musimack_tools.security.access")
_JOB_ID = re.compile(r"^job-[0-9a-f]{12}-[0-9]{4}$")
_SAFE_LOG_VALUE = re.compile(r"[^A-Za-z0-9._:/-]")
_CLIENT_ERROR_STATUS = 400
_UNAUTHORIZED_STATUS = 401
_FORBIDDEN_STATUS = 403


def sanitize_log_value(value: object | None) -> str:
    if value is None:
        return "-"
    return _SAFE_LOG_VALUE.sub("_", str(value))[:200]


def log_unhandled_access_event(request: Request, *, exception_type: str) -> None:
    """Emit safe evidence for errors handled outside the user middleware stack."""
    route = request.scope.get("route")
    route_template = getattr(route, "path", request.url.path)
    _LOGGER.error(
        "event=internal_api_request_failed correlation_id=%s method=%s route=%s status=500 "
        "auth_outcome=%s caller_id=%s client_address=%s exception_type=%s api_version=%s "
        "security_version=%s",
        sanitize_log_value(getattr(request.state, "request_id", None)),
        sanitize_log_value(request.method),
        sanitize_log_value(route_template),
        sanitize_log_value(getattr(request.state, "authentication_outcome", None)),
        sanitize_log_value(getattr(request.state, "caller_id", None)),
        sanitize_log_value(getattr(request.state, "client_address", None)),
        sanitize_log_value(exception_type),
        INTERNAL_API_VERSION,
        SECURITY_VERSION,
    )


class AccessLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, logger: logging.Logger = _LOGGER) -> None:
        super().__init__(app)
        self._logger = logger

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        route_template = getattr(route, "path", request.url.path)
        job_id_value = request.path_params.get("job_id")
        job_id = job_id_value if job_id_value and _JOB_ID.fullmatch(job_id_value) else None
        outcome = getattr(request.state, "authentication_outcome", "not_evaluated")
        if response.status_code < _CLIENT_ERROR_STATUS:
            event = "internal_api_request_completed"
        elif response.status_code == _UNAUTHORIZED_STATUS:
            event = "internal_api_authentication_failed"
        elif response.status_code == _FORBIDDEN_STATUS:
            event = "internal_api_access_denied"
        else:
            event = "internal_api_request_failed"
        self._logger.info(
            "event=%s correlation_id=%s method=%s route=%s status=%d duration_ms=%.3f "
            "auth_outcome=%s caller_id=%s client_address=%s job_id=%s api_version=%s "
            "security_version=%s",
            event,
            sanitize_log_value(getattr(request.state, "request_id", None)),
            sanitize_log_value(request.method),
            sanitize_log_value(route_template),
            response.status_code,
            (time.perf_counter() - started) * 1_000,
            sanitize_log_value(outcome),
            sanitize_log_value(getattr(request.state, "caller_id", None)),
            sanitize_log_value(getattr(request.state, "client_address", None)),
            sanitize_log_value(job_id),
            INTERNAL_API_VERSION,
            SECURITY_VERSION,
        )
        return response
