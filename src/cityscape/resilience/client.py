"""ResilientSourceClient: the central fetch facade (Integration RES-01..05).

This class merges the individual resilience layers into ONE function,
which Phase 4+ trivially consumes per source adapter:

- RES-01/05 (Pool + User-Agent): the pooled ``httpx.AsyncClient`` from
  ``app.state.http`` is passed through; the source adapter receives it as
  its only I/O channel.
- RES-02/03 (Cache-Aside + SWR + Single-Flight): every read goes through
  ``cache_get_or_set`` (exactly one upstream call on HIT/single-flight).
- RES-04 (per-source breaker): the upstream coroutine is protected per source by the
  ``CircuitBreaker`` of the ``BreakerRegistry``. A dead source only trips
  its own breaker and blocks neither other sources nor the
  overall response (T-03-10).

Fallback policy (T-03-10/12): if the upstream fails (breaker OPEN OR
``httpx.HTTPError``), the facade returns an existing (even expired)
cache entry as ``STALE-ON-ERROR``. If no cache exists, it returns
``(None, STALE-ON-ERROR)`` instead of blocking or leaking a stacktrace;
the calling API layer (Phase 4) decides whether this becomes an ``UpstreamError``
(503). ``fetch`` never blocks and does not raise an unmapped upstream error.

``fetch_fn`` is a pure parameterless async function provided by the source adapter
(knows neither cache nor breaker). This keeps the adapter lean and all
resilience logic contained within this facade.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx
import orjson
import structlog

from cityscape.registry.source_specs import SOURCE_TTL as _REGISTRY_TTL

from ..infra.cache import cache_get_or_set
from ..infra.metrics import incr_cache_status
from .breaker import BreakerOpen, BreakerRegistry
from .types import CacheStatus

log = structlog.get_logger()


async def _last_cache(redis, key: str):
    """Reads the (even expired) cache value in a bytes-safe manner; None on miss/error.

    Graceful degradation (T-03-09): any Redis error -> None instead of raise. The
    value container is the same as in ``infra/cache._store`` (payload +
    fresh_until/stale_until); base64-wrapped bytes are decoded back.
    """
    try:
        raw = await redis.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    try:
        if isinstance(raw, str):
            raw = raw.encode()
        value = orjson.loads(raw)
    except Exception:
        return None
    payload = value.get("payload") if isinstance(value, dict) else None
    if isinstance(payload, dict) and "__b64__" in payload and len(payload) == 1:
        import base64

        return base64.b64decode(payload["__b64__"])
    return payload


# Default cache window (fresh_s, stale_s) for sources without an explicit registry
# entry: previous behavior (60s fresh, ~120s stale via pad).
_DEFAULT_TTL: tuple[float, float] = (60.0, 120.0)
# Per-source cache TTL (fresh_s, stale_s) from declarative source registry
# (registry/source_specs.py). Sources without an entry use _DEFAULT_TTL.
_SOURCE_TTL: dict[str, tuple[float, float]] = dict(_REGISTRY_TTL)

# --- Outbound limits per upstream (ToS compliance) ----------------------------
# Upper limit of concurrent upstream calls per source. Shared VM IP -> the
# Wikidata WDQS endpoint allows only ~5 parallel queries/IP. Sources without
# an entry: unlimited (behavior unchanged).
_SOURCE_MAX_CONCURRENCY: dict[str, int] = {"wikidata": 5}
# Minimum interval (seconds) between upstream calls per source (aggregate rate).
# DB Timetables ToS: <=60 calls/minute -> >=1.0s. Sources without entry: no
# limit. All cityscape users share the DB key, therefore limit the aggregate.
_SOURCE_MIN_INTERVAL_S: dict[str, float] = {"db_timetables": 1.0}

_semaphores: dict[str, asyncio.Semaphore] = {}
_rate_locks: dict[str, asyncio.Lock] = {}
_last_call_monotonic: dict[str, float] = {}


def _source_semaphore(source: str) -> asyncio.Semaphore | None:
    """Lazy per-source semaphore (None = unlimited). Single-loop app: process-wide."""
    limit = _SOURCE_MAX_CONCURRENCY.get(source)
    if limit is None:
        return None
    sem = _semaphores.get(source)
    if sem is None:
        sem = asyncio.Semaphore(limit)
        _semaphores[source] = sem
    return sem


async def _pace(source: str) -> None:
    """Enforces minimum interval between calls of a source (no-op without entry)."""
    interval = _SOURCE_MIN_INTERVAL_S.get(source)
    if not interval:
        return
    lock = _rate_locks.get(source)
    if lock is None:
        lock = asyncio.Lock()
        _rate_locks[source] = lock
    async with lock:
        wait = interval - (time.monotonic() - _last_call_monotonic.get(source, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_monotonic[source] = time.monotonic()


async def _run_limited(source: str, fetch_fn: Callable[[], Awaitable]):
    """Executes ``fetch_fn`` under per-source concurrency + minimum interval."""
    sem = _source_semaphore(source)
    if sem is None:
        await _pace(source)
        return await fetch_fn()
    async with sem:
        await _pace(source)
        return await fetch_fn()


class ResilientSourceClient:
    """Facade: Combines pool, cache, SWR, single-flight, and breaker into `fetch()`.

    Args:
        http: process-wide, pooled ``httpx.AsyncClient`` (app.state.http).
        redis: redis.asyncio-compatible client (app.state.redis).
        breakers: process-wide ``BreakerRegistry`` (app.state.breakers). Default:
            a fresh registry (the breaker state then persists only for this
            instance; a shared registry is injected into the app so that the
            breaker state persists across requests).
        schedule: schedules the SWR background refresh coroutine (default: the
            asyncio task holder from ``cache_get_or_set``).
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        redis,
        breakers: BreakerRegistry | None = None,
        schedule: Callable[[Awaitable], None] | None = None,
    ) -> None:
        self._http = http
        self._redis = redis
        self._breakers = breakers if breakers is not None else BreakerRegistry()
        self._schedule = schedule

    async def fetch(
        self,
        source: str,
        key: str,
        fetch_fn: Callable[[], Awaitable],
        *,
        store: bool = True,
    ):
        """Fetch data from source ``source`` under ``key`` (resilient, never blocking).

        Order: Cache (HIT/STALE/MISS) around a breaker-protected upstream
        coroutine. On OPEN breaker or upstream error -> last-cache fallback
        (STALE-ON-ERROR) or ``(None, STALE-ON-ERROR)``.

        Args:
            store: If ``False``, the call runs ON-DEMAND: NO Redis read/write,
                no stale fallback, no SWR background refresh; only the
                breaker protection around the live call remains. For sources whose
                ToS prohibit mirroring/caching (Tankerkoenig/MTS-K): data only
                live on user action, never cached (T-08-CRED consequence).

        Returns:
            ``(payload, status)`` tuple (never None). ``status`` is a
            ``CacheStatus`` string (HIT/MISS/STALE/STALE-ON-ERROR).
        """
        breaker = self._breakers.get(source)
        # Optional Redis persistence of breaker state (RedisBreakerRegistry, C-2026):
        # hydrate PULLS cross-process state before the decision, persist
        # WRITES it after each record_*. Duck typing -> the lightweight in-memory
        # BreakerRegistry (tests/fallback) remains completely untouched (no methods).
        hydrate = getattr(self._breakers, "hydrate", None)
        persist = getattr(self._breakers, "persist", None)
        if hydrate is not None:
            await hydrate(source, breaker)

        async def refresh():
            # Breaker per source, but ONE shared pool (RES-01/04).
            if not breaker.allow_request():
                raise BreakerOpen(source)
            try:
                result = await _run_limited(source, fetch_fn)
            except Exception:
                breaker.record_failure()
                if persist is not None:
                    await persist(source, breaker)
                raise
            breaker.record_success()
            if persist is not None:
                await persist(source, breaker)
            return result

        if not store:
            # ON-DEMAND (no Redis read/write, no stale, no SWR refresh): only
            # the live call behind the breaker. Provider ToS that prohibit
            # mirroring/caching (Tankerkoenig/MTS-K) only allow live retrieval on user action.
            try:
                result = await refresh()
                await incr_cache_status(self._redis, CacheStatus.MISS)
                return result, CacheStatus.MISS
            except (BreakerOpen, httpx.HTTPError) as exc:
                log.info(
                    "resilient_fetch_fallback",
                    source=source,
                    key=key,
                    has_stale=False,
                    error=type(exc).__name__,
                )
                await incr_cache_status(self._redis, CacheStatus.STALE_ON_ERROR)
                return None, CacheStatus.STALE_ON_ERROR

        try:
            ttl_fresh, ttl_stale = _SOURCE_TTL.get(source, _DEFAULT_TTL)
            result = await cache_get_or_set(
                self._redis,
                key,
                ttl=ttl_fresh,
                ttl_stale=ttl_stale,
                fetch=refresh,
                schedule=self._schedule,
            )
            # Cache status counter at the SINGLE chokepoint (OPS-02). result[1] is
            # the raw status str (HIT/MISS/STALE); incr_cache_status is internally
            # wrapped in try/except (13-01) and can never block the fetch path.
            # STILL INSIDE try block so that the except behavior below remains unchanged.
            await incr_cache_status(self._redis, result[1])
            return result
        except (BreakerOpen, httpx.HTTPError) as exc:
            # Upstream dead OR breaker open: last-cache fallback instead of blocking.
            stale = await _last_cache(self._redis, key)
            log.info(
                "resilient_fetch_fallback",
                source=source,
                key=key,
                has_stale=stale is not None,
                error=type(exc).__name__,
            )
            # The fallback path also counts at the chokepoint (STALE-ON-ERROR bucket).
            await incr_cache_status(self._redis, CacheStatus.STALE_ON_ERROR)
            return stale, CacheStatus.STALE_ON_ERROR
