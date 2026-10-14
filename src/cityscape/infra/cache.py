"""Hand-rolled cache-aside helper with stale-while-revalidate + single-flight.

Covers RES-02 (cache-aside + per-source TTL: repeated calls hit the
Redis cache instead of upstream again) and RES-03 (stale-while-revalidate +
single-flight against cache stampede: N parallel requests on a cold key
produce exactly ONE upstream call).

Redis only knows ONE TTL per key. Therefore we encode the fresh and the
stale windows IN the value (``fresh_until`` / ``stale_until`` as Unix timestamps).
GET -> Fresh: serve immediately (HIT). Stale: serve immediately AND schedule
exactly one background refresh (STALE), protected by a short
``SET NX EX`` single-flight lock so only one worker refetches. Missing/expired:
fetch synchronously and store (MISS).

decode_responses resolution (orchestrator decision 5): This cache layer
works bytes-safe and is independent of the ``decode_responses`` mode of the
passed client. On read, a str result (decode_responses=True) is encoded to
bytes before ``orjson.loads``; on write, ``orjson.dumps`` bytes are always
sent to Redis. Thus the helper works both with the existing
``decode_responses=True`` pool (app.state.redis) and with a
``decode_responses=False`` cache client, without introducing a second connection
pool (leaner, MVP-suitable).

Graceful degradation (pitfall 2): Every Redis access is wrapped in try/except
(pattern from health.py). If Redis fails, the path degrades to a direct
fetch (cache miss) instead of crashing.

Cache poisoning protection (T-03-06): ``build_cache_key`` builds versioned keys
only from validated slugs/params via a stable sha256 param hash, never from raw
user strings.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import orjson
import structlog

log = structlog.get_logger()

# Minimum stale window (seconds), so that even with ttl=0 (immediately stale)
# a stale-while-revalidate path exists instead of counting directly as a cache miss.
_DEFAULT_STALE_PAD = 60.0

# Lock lifetime (seconds) for the single-flight lock. If a holder fails,
# the Redis TTL releases the lock automatically (no deadlock).
_LOCK_TTL = 10

# Wait time parameters for losers of the single-flight lock on a cold key.
_WAIT_POLL = 0.02
_WAIT_MAX = 5.0


@dataclass(frozen=True)
class EntryMeta:
    """Metadata of a cache entry (fresh/stale window as Unix time)."""

    fresh_until: float
    stale_until: float


def _to_bytes(raw: bytes | str) -> bytes:
    """Normalizes a Redis read result to bytes (decode_responses-agnostic)."""
    if isinstance(raw, str):
        return raw.encode()
    return raw


# Marker for base64-encoded bytes payloads (orjson cannot directly serialize
# bytes; but HTTP responses provide raw bytes via resp.content).
_BYTES_TAG = "__b64__"


def _encode_payload(payload):
    """Makes arbitrary payloads orjson-serializable (bytes -> base64 container)."""
    if isinstance(payload, bytes):
        return {_BYTES_TAG: base64.b64encode(payload).decode("ascii")}
    return payload


def _decode_payload(payload):
    """Reverses ``_encode_payload`` (base64 container -> bytes)."""
    if isinstance(payload, dict) and _BYTES_TAG in payload and len(payload) == 1:
        return base64.b64decode(payload[_BYTES_TAG])
    return payload


def build_cache_key(source: str, *, city_slug: str, params: dict | None = None) -> str:
    """Builds a versioned, collision-resistant cache key.

    Schema: ``source:{source}:v1:{city_slug}:{param_hash}``. The param hash is
    a stable sha256 over sorted items (orjson-serialized), so that ordering
    variants result in the same key. Only build from validated slugs/params
    (T-03-06: no raw user string -> no cache poisoning). Versioned
    (``:v1:``) so that a Phase 4 schema change does not need to flush unrelated keys.
    """
    items = sorted((params or {}).items())
    digest = hashlib.sha256(orjson.dumps(items)).hexdigest()[:16]
    return f"source:{source}:v1:{city_slug}:{digest}"


async def read_entry_meta(redis, key: str) -> EntryMeta | None:
    """Reads the fresh/stale metadata of a cache entry (or None on miss)."""
    try:
        raw = await redis.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    v = orjson.loads(_to_bytes(raw))
    return EntryMeta(fresh_until=v["fresh_until"], stale_until=v["stale_until"])


async def _store(redis, key: str, payload, ttl_fresh: float, ttl_stale: float) -> None:
    """Writes payload + fresh/stale windows; Redis key TTL = stale end."""
    now = time.time()
    value = {
        "payload": _encode_payload(payload),
        "fresh_until": now + ttl_fresh,
        "stale_until": now + ttl_stale,
    }
    # ex must be >= 1; for tiny ttl_stale we round up to 1s.
    ex = max(1, int(round(ttl_stale)))
    await redis.set(key, orjson.dumps(value), ex=ex)


async def _refresh_and_store(
    redis,
    key: str,
    ttl_fresh: float,
    ttl_stale: float,
    fetch: Callable[[], Awaitable],
) -> None:
    """Single-flight refresh coroutine: refetches and stores (lock expires via ex)."""
    payload = await fetch()
    try:
        await _store(redis, key, payload, ttl_fresh, ttl_stale)
    except Exception as exc:
        # Degraded ignore of Redis write errors during background refresh.
        log.debug("cache_refresh_store_failed", key=key, error=str(exc))


def _default_schedule(coro: Awaitable) -> None:
    """Schedules a refresh coroutine as a detached task (reference prevents GC)."""
    task = asyncio.ensure_future(coro)
    _default_schedule._tasks.add(task)  # type: ignore[attr-defined]
    task.add_done_callback(_default_schedule._tasks.discard)  # type: ignore[attr-defined]


_default_schedule._tasks = set()  # type: ignore[attr-defined]


async def cache_get_or_set(
    redis,
    key: str,
    *,
    ttl: float,
    fetch: Callable[[], Awaitable],
    ttl_stale: float | None = None,
    schedule: Callable[[Awaitable], None] | None = None,
):
    """Cache-aside + stale-while-revalidate + single-flight around ``fetch``.

    Args:
        redis: redis.asyncio-compatible client (decode_responses agnostic).
        key: pre-built cache key (see ``build_cache_key``).
        ttl: Fresh window in seconds. Within this: HIT.
        fetch: parameterless async function returning the fresh payload.
        ttl_stale: Stale window in seconds (default: ttl + minimum pad).
        schedule: schedules the background refresh coroutine (default: asyncio task).

    Returns:
        ``(payload, status)`` with status in {"HIT", "STALE", "MISS"}.

    Paths:
        - Fresh (now < fresh_until): serve immediately -> HIT.
        - Stale (fresh_until <= now < stale_until): serve stale immediately +
          schedule exactly one refresh (SET NX EX single-flight lock) -> STALE.
        - Miss/expired: synchronously fetch + store -> MISS. For N parallel
          cold requests, exactly one wins the lock and fetches; the rest
          wait briefly for the fresh entry (exactly 1 upstream call).
        - Redis down: try/except -> direct fetch, no crash (MISS).
    """
    if ttl_stale is None:
        ttl_stale = ttl + _DEFAULT_STALE_PAD
    if schedule is None:
        schedule = _default_schedule

    # 1. Read cache (graceful degradation: Redis error -> cache miss path).
    raw = None
    redis_ok = True
    try:
        raw = await redis.get(key)
    except Exception:
        redis_ok = False

    now = time.time()
    if raw is not None:
        v = orjson.loads(_to_bytes(raw))
        if now < v["fresh_until"]:
            return _decode_payload(v["payload"]), "HIT"
        if now < v["stale_until"]:
            # Single-flight: only ONE worker acquires the lock and refetches.
            try:
                got_lock = await redis.set(f"lock:{key}", b"1", nx=True, ex=_LOCK_TTL)
            except Exception:
                got_lock = False
            if got_lock:
                schedule(_refresh_and_store(redis, key, ttl, ttl_stale, fetch))
            return _decode_payload(v["payload"]), "STALE"

    # 2. Miss/expired. Single-flight also for the cold path, so that N parallel
    #    requests produce exactly one upstream call.
    if redis_ok:
        try:
            got_lock = await redis.set(f"lock:{key}", b"1", nx=True, ex=_LOCK_TTL)
        except Exception:
            got_lock = False

        if not got_lock:
            # Losers: wait briefly for the winner's fresh entry.
            waited = 0.0
            while waited < _WAIT_MAX:
                await asyncio.sleep(_WAIT_POLL)
                waited += _WAIT_POLL
                try:
                    raw = await redis.get(key)
                except Exception:
                    raw = None
                    break
                if raw is not None:
                    v = orjson.loads(_to_bytes(raw))
                    now = time.time()
                    status = "HIT" if now < v["fresh_until"] else "STALE"
                    return _decode_payload(v["payload"]), status
            # Timeout/Redis error while waiting -> fetch ourselves (no hang).

    # 3. Synchronously fetch + store (lock holder or degraded path).
    payload = await fetch()
    try:
        await _store(redis, key, payload, ttl, ttl_stale)
    except Exception as exc:
        # Ignore Redis write errors (graceful degradation, pitfall 2).
        log.debug("cache_store_failed", key=key, error=str(exc))
    return payload, "MISS"
