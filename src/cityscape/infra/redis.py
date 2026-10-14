"""Redis connection lifecycle (Pitfall 6).

The pool is created lazily (no connect at boot), so that ``docker compose
up`` does not fail due to a startup race. A ping is performed only in
the /health handler, not during lifespan startup. Uses ``redis.asyncio``
(not the deprecated ``aioredis``).
"""

from __future__ import annotations

import redis.asyncio as aioredis


def create_redis_pool(
    url: str, *, max_connections: int | None = None
) -> aioredis.Redis:
    """Creates a lazy Redis client with connection pool (no boot connect).

    ``max_connections`` caps (quick-260704-ust) the previously unbounded
    socket growth of the pool; ``from_url`` passes the kwarg through to the
    ConnectionPool. Decision: standard ConnectionPool with a generous
    cap instead of BlockingConnectionPool. The cap is intended to LIMIT, not throttle (normal
    operation uses a handful of connections, hitting the cap is already an
    anomaly): a hard ConnectionError from the standard pool falls cleanly into the
    existing graceful degradation / 503 handling along with the already short
    Redis socket timeouts. A BlockingConnectionPool would instead build up queues
    of acquire-waiters, pushing backpressure into the event loop, precisely the
    failure mode we avoid elsewhere. If hard errors occur later under normal
    bursts, update with BlockingConnectionPool + short timeout.
    """
    kwargs: dict = {"encoding": "utf-8", "decode_responses": True}
    if max_connections is not None:
        kwargs["max_connections"] = max_connections
    return aioredis.from_url(url, **kwargs)


async def close_redis_pool(client: aioredis.Redis | None) -> None:
    """Closes the Redis client and its pool cleanly."""
    if client is not None:
        await client.aclose()
