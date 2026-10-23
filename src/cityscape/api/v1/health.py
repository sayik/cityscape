"""Walking skeleton demo routes (FND-03/04/05).

Demonstrates each cross-cutting concern end-to-end:
- /health  -> Redis ping + status (FND-05)
- /ping    -> Correlation ID in meta + JSON log with request_id (FND-03/05)
- /echo    -> Type-validated query (triggers 400 envelope on error, FND-04)
- /_boom   -> Forced UpstreamError (demonstrates 503 envelope, FND-04)
"""

from __future__ import annotations

import structlog
from asgi_correlation_id import correlation_id
from fastapi import APIRouter, Request

from cityscape import __version__

from ..errors import UpstreamError

router = APIRouter()
log = structlog.get_logger()


@router.get("/health")
async def health(request: Request) -> dict:
    """Liveness/readiness incl. Redis ping (ping only here, not in lifespan)."""
    redis = request.app.state.redis
    try:
        await redis.ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return {"status": "ok", "version": __version__, "redis": redis_ok}


@router.get("/ping")
async def ping() -> dict:
    """Generates a JSON log line with request_id and returns the ID in meta."""
    log.info("ping_received")
    return {"data": {"pong": True}, "meta": {"correlation_id": correlation_id.get()}}


@router.get("/echo")
async def echo(n: int) -> dict:
    """Echo of an int query; non-int triggers RequestValidationError -> 400."""
    return {"data": {"n": n}, "meta": {"correlation_id": correlation_id.get()}}


@router.get("/_boom")
async def boom() -> dict:
    """Walking skeleton: demonstrates uniform error envelope (503)."""
    raise UpstreamError(
        "Simulated upstream failure",
        hint="This route exists only to test error mapping.",
    )
