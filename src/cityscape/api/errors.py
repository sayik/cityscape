"""Central error mapping with uniform envelope (FND-04, REST rule 7).

An ``AppError`` hierarchy carries status_code + machine-readable code. A
single ``register_exception_handlers(app)`` maps AppError,
RequestValidationError, and the catch-all exception to an ``ErrorEnvelope``.
The catch-all NEVER leaks stacktraces/secrets to the client (Pitfall 2 / T-01-01).
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from asgi_correlation_id import correlation_id
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from cityscape.api.responses import OrjsonResponse

log = structlog.get_logger()


class ErrorDetail(BaseModel):
    """Machine- and human-readable error detail."""

    code: str
    message: str
    hint: str | None = None


class ErrorEnvelope(BaseModel):
    """Uniform error response: error detail + meta (correlation_id, ts)."""

    error: ErrorDetail
    meta: dict


class AppError(Exception):
    """Base of all application-specific errors."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        self.message = message
        self.hint = hint
        super().__init__(message)


class NotFoundError(AppError):
    status_code, code = 404, "not_found"


class UnauthorizedError(AppError):
    status_code, code = 401, "unauthorized"


class ForbiddenError(AppError):
    status_code, code = 403, "forbidden"


class RateLimitError(AppError):
    status_code, code = 429, "rate_limited"


class UpstreamError(AppError):
    status_code, code = 503, "upstream_unavailable"


class ValidationFailedError(AppError):
    status_code, code = 400, "invalid_request"


class UnprocessableError(AppError):
    """Syntactically valid but semantically impermissible input (HTTP 422).

    Used for the ``?type=`` allowlist violation of the POI route: an
    unknown POI type is rejected BEFORE raw user input reaches
    Overpass QL (T-05-09 injection protection).
    """

    status_code, code = 422, "unprocessable"


def _envelope(
    status: int,
    code: str,
    message: str,
    hint: str | None = None,
) -> OrjsonResponse:
    """Builds a uniform ErrorEnvelope response."""
    body = ErrorEnvelope(
        error=ErrorDetail(code=code, message=message, hint=hint),
        meta={
            "correlation_id": correlation_id.get(),
            "generated_at": datetime.now(UTC).isoformat(),
        },
    )
    return OrjsonResponse(status_code=status, content=body.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    """Registers the central exception handlers on the app."""

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> OrjsonResponse:
        return _envelope(exc.status_code, exc.code, exc.message, exc.hint)

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(request: Request, exc: RateLimitExceeded) -> OrjsonResponse:
        # 429 via central envelope (no slowapi default JSON, no
        # stacktrace/detail leak, T-11-RL-LEAK). Code "rate_limited" == RateLimitError.
        response = _envelope(
            429,
            "rate_limited",
            "Rate limit exceeded.",
            hint=(
                "Bitte etwas warten und später erneut versuchen "
                "(RateLimit-Header beachten)."
            ),
        )
        # Set standard RateLimit headers (D-02) on the 429 response. slowapi
        # injects them via the limiter's normalized _header_mapping
        # (RateLimit-Limit/Remaining/Reset + Retry-After).
        limiter = getattr(request.app.state, "limiter", None)
        view_limit = getattr(request.state, "view_rate_limit", None)
        if limiter is not None and view_limit is not None:
            limiter._inject_headers(response, view_limit)
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> OrjsonResponse:
        # Only field path + error type to the client (Audit MEDIUM-2, 2026-06-10):
        # str(exc.errors()) would reflect Pydantic internals AND raw input (input=...)
        # (Information Disclosure). Full details only server-side.
        log.info("request_validation_failed", errors=exc.errors()[:5])
        fields = "; ".join(
            ".".join(str(part) for part in e.get("loc", ())) + f": {e.get('type', '')}"
            for e in exc.errors()[:3]
        )
        return _envelope(
            400,
            "invalid_request",
            "Request validation failed",
            hint=fields or None,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> OrjsonResponse:
        # FastAPI/Starlette raises StarletteHTTPException for routing cases that
        # do NOT go through our AppError hierarchy: unknown path (404) and
        # wrong method (405). Without this handler, Starlette returns the
        # default ``{"detail": "..."}`` instead of the project-wide error envelope
        # (Live report M4). Domain errors (unknown city, POI type, validation,
        # 503) are AppError/RequestValidationError and are handled by the more specific
        # handler above, NOT here.
        code_map = {
            404: ("not_found", "Die angeforderte Ressource wurde nicht gefunden."),
            405: (
                "method_not_allowed",
                "Die HTTP-Methode ist für diese Ressource nicht erlaubt.",
            ),
        }
        code, message = code_map.get(
            exc.status_code,
            ("http_error", "Die Anfrage konnte nicht bearbeitet werden."),
        )
        hint = None
        if exc.status_code == 404:
            hint = "Pfad prüfen oder GET /api/v1/openapi.yaml für die Routenliste."
        elif exc.status_code == 405:
            # Pass through allowed methods from Allow header if set.
            allowed = exc.headers.get("Allow") if exc.headers else None
            hint = f"Erlaubte Methoden: {allowed}." if allowed else None
        return _envelope(exc.status_code, code, message, hint)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> OrjsonResponse:
        # Log stacktrace only server-side, NEVER str(exc) to client.
        log.error("unhandled_exception", exc_info=exc)
        return _envelope(500, "internal_error", "An unexpected error occurred")
