"""Redis-persistent breaker registry (RES-04 Upgrade, 2026-06-14).

The in-process ``BreakerRegistry`` loses its state on every deploy/restart
and does not share it across multiple uvicorn workers: a breaker tripped in
worker A or before a deploy restarts as CLOSED afterwards and hammers the
sick source again until it fails 5x again. This subclass mirrors the breaker
state per source write-through to Redis and hydrates it back before each access,
so that OPEN/HALF_OPEN survives deploys and worker boundaries (the upgrade path
envisioned in the code, breaker.py docstring T-03-13).

Important (clock): the persisted ``opened_at`` is only meaningful across
processes if it is a WALL-CLOCK time. Therefore this registry injects
``time.time`` (instead of the base class default ``time.monotonic``) into each
created ``CircuitBreaker``; the cooldown comparison (now - opened_at >= cooldown)
thus remains correct across processes.

Graceful degradation (core RES principle): any Redis error in hydrate/persist
silently degrades to pure in-memory behavior (only ``type(exc).__name__``
is logged, never ``str(exc)``). The breaker continues to function even without
Redis, just process-locally again.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import orjson
import structlog

from cityscape.registry.source_specs import (
    FRAGILE_SOURCE_COOLDOWN as _REGISTRY_COOLDOWN,
)

from .breaker import BreakerRegistry, BreakerState, CircuitBreaker

log = structlog.get_logger()

# State key per source. Separate namespace, partitioned from cache keys
# (source:{name}:v1:...), ensuring a breaker state never collides with payload data.
_KEY_PREFIX = "breaker:state:"

# TTL of persisted state: after one day without any access, the entry
# expires (a source untouched for 24h starts cleanly CLOSED). An active
# OPEN breaker is rewritten on every record_*, extending the TTL.
_STATE_TTL = 86400

# Per-source cooldown (s) for fragile upstreams from declarative source
# registry (registry/source_specs.py). Sources without an entry retain 30s.
_FRAGILE_SOURCE_COOLDOWN: dict[str, float] = dict(_REGISTRY_COOLDOWN)


class RedisBreakerRegistry(BreakerRegistry):
    """``BreakerRegistry`` with write-through persistence of breaker state in Redis.

    Args:
        redis: redis.asyncio-compatible client (app.state.redis).
        failure_threshold/cooldown: same as base class.
        now: Injectable clock; default ``time.time`` (WALL-CLOCK, valid
            across processes), NOT the monotonic default of the base class.
    """

    def __init__(
        self,
        redis,
        failure_threshold: int = 5,
        cooldown: float = 30.0,
        *,
        now: Callable[[], float] = time.time,
        cooldowns: dict[str, float] | None = None,
    ) -> None:
        super().__init__(
            failure_threshold=failure_threshold,
            cooldown=cooldown,
            now=now,
            cooldowns=cooldowns if cooldowns is not None else _FRAGILE_SOURCE_COOLDOWN,
        )
        self._redis = redis

    @staticmethod
    def _key(source: str) -> str:
        return f"{_KEY_PREFIX}{source}"

    async def hydrate(self, source: str, breaker: CircuitBreaker) -> None:
        """Loads persisted state from Redis into the in-memory breaker.

        Redis is the source of truth (multi-worker convergence). If the
        entry is missing or unreadable, the in-memory breaker remains unchanged
        (fresh worker -> CLOSED). Silently degrades on any Redis error.
        """
        try:
            raw = await self._redis.get(self._key(source))
        except Exception as exc:  # noqa: BLE001 - Redis error -> in-memory fallback
            log.debug("breaker_hydrate_failed", source=source, error=type(exc).__name__)
            return
        if raw is None:
            return
        try:
            if isinstance(raw, str):
                raw = raw.encode()
            data = orjson.loads(raw)
            breaker.state = BreakerState(data["state"])
            breaker.opened_at = data["opened_at"]
            breaker.failure_count = int(data["failure_count"])
        except (ValueError, KeyError, TypeError) as exc:
            # Defective entry: ignore instead of crash (in-memory remains valid).
            log.debug(
                "breaker_hydrate_parse_failed",
                source=source,
                error=type(exc).__name__,
            )

    async def persist(self, source: str, breaker: CircuitBreaker) -> None:
        """Writes current breaker state write-through to Redis (best-effort).

        Called after each record_success/record_failure so that the next
        worker/request sees the state. Silently degrades.
        """
        payload = orjson.dumps(
            {
                "state": breaker.state.value,
                "opened_at": breaker.opened_at,
                "failure_count": breaker.failure_count,
            }
        )
        try:
            await self._redis.set(self._key(source), payload, ex=_STATE_TTL)
        except Exception as exc:  # noqa: BLE001 - Persist loss is not fatal
            log.debug("breaker_persist_failed", source=source, error=type(exc).__name__)
