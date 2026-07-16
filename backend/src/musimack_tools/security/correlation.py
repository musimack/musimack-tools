"""Request-local correlation identifiers and response propagation."""

from __future__ import annotations

import contextvars
import re
import secrets
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

if TYPE_CHECKING:
    from fastapi import Request, Response
    from starlette.types import ASGIApp

_SAFE_CORRELATION = re.compile(r"^[A-Za-z0-9._-]+$")
_current_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "musimack_request_id", default=None
)


def current_request_id() -> str | None:
    return _current_request_id.get()


def valid_correlation_id(value: str | None, *, maximum_length: int = 64) -> bool:
    return bool(value and len(value) <= maximum_length and _SAFE_CORRELATION.fullmatch(value))


def generate_correlation_id() -> str:
    return f"req-{secrets.token_hex(16)}"


class CorrelationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, header_name: str, maximum_length: int = 64) -> None:
        super().__init__(app)
        self._header_name = header_name
        self._maximum_length = maximum_length

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied_values = request.headers.getlist(self._header_name)
        supplied = supplied_values[0] if len(supplied_values) == 1 else None
        if supplied is not None and valid_correlation_id(
            supplied, maximum_length=self._maximum_length
        ):
            request_id = supplied
        else:
            request_id = generate_correlation_id()
        token = _current_request_id.set(request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
            response.headers[self._header_name] = request_id
            return response
        finally:
            _current_request_id.reset(token)
