"""Exact-origin internal CORS policy without wildcard reflection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import PlainTextResponse

if TYPE_CHECKING:
    from fastapi import FastAPI, Request, Response
    from starlette.types import ASGIApp

    from musimack_tools.domain.security import CorsConfiguration

_ALLOWED_METHODS = ("GET", "POST", "OPTIONS")


class InternalCorsMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_origins: tuple[str, ...],
        request_id_header: str,
        maximum_age_seconds: int,
    ) -> None:
        super().__init__(app)
        self._allowed_origins = frozenset(allowed_origins)
        self._allowed_headers = ("Authorization", "Content-Type", request_id_header)
        self._allowed_header_names = frozenset(name.lower() for name in self._allowed_headers)
        self._maximum_age_seconds = maximum_age_seconds

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        origins = request.headers.getlist("origin")
        preflight = request.method == "OPTIONS" and bool(
            request.headers.get("access-control-request-method")
        )
        if len(origins) != 1 or origins[0] not in self._allowed_origins:
            if preflight:
                return PlainTextResponse("Disallowed CORS request.", status_code=400)
            return await call_next(request)
        origin = origins[0]
        if preflight:
            return self._preflight_response(request, origin)
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Expose-Headers"] = self._allowed_headers[-1]
        response.headers.add_vary_header("Origin")
        return response

    def _preflight_response(self, request: Request, origin: str) -> Response:
        method = request.headers.get("access-control-request-method", "")
        requested = request.headers.get("access-control-request-headers", "")
        requested_headers = tuple(
            item.strip().lower() for item in requested.split(",") if item.strip()
        )
        if method not in _ALLOWED_METHODS or any(
            item not in self._allowed_header_names for item in requested_headers
        ):
            return PlainTextResponse("Disallowed CORS request.", status_code=400)
        return PlainTextResponse(
            "OK",
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": ", ".join(_ALLOWED_METHODS),
                "Access-Control-Allow-Headers": ", ".join(self._allowed_headers),
                "Access-Control-Expose-Headers": self._allowed_headers[-1],
                "Access-Control-Max-Age": str(self._maximum_age_seconds),
                "Vary": "Origin",
            },
        )


def add_internal_cors(
    application: FastAPI,
    configuration: CorsConfiguration,
    *,
    request_id_header: str,
) -> None:
    if not configuration.enabled:
        return
    application.add_middleware(
        InternalCorsMiddleware,
        allowed_origins=configuration.allowed_origins,
        request_id_header=request_id_header,
        maximum_age_seconds=configuration.maximum_age_seconds,
    )
