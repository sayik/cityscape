"""FastAPI dependencies.

Provides resources stored in ``app.state`` via lifespan: the
Redis client and the process-wide, pooled httpx AsyncClient (RES-01).
Expands later (cache helper, rate limit context, ResilientSourceClient).
"""

from __future__ import annotations

from fastapi import Request


def get_redis(request: Request):
    """Returns the Redis client set during lifespan from app state."""
    return request.app.state.redis


def get_http_client(request: Request):
    """Returns the pooled httpx AsyncClient set during lifespan (RES-01)."""
    return request.app.state.http


def get_resilient_client(request: Request):
    """Returns the process-wide ResilientSourceClient (facade RES-01..05).

    The client is stored once during lifespan at ``app.state.resilient_client``
    and shares a process-wide ``BreakerRegistry``
    (``app.state.breakers``). Thus, the breaker state lives across requests:
    a breaker opened in request A remains open in request B (RES-04). The
    facade is the ONE entry point for all source adapters from Phase 4 onward.
    """
    return request.app.state.resilient_client
