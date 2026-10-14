"""Graceful Redis metric helpers for the admin dashboard (OPS-02).

Pure Redis helpers without route/middleware dependencies: counters for cache
status (HIT/MISS/STALE/STALE-ON-ERROR), request counters (total + per status code
+ per endpoint), and a capped ring buffer of the latest request logs. The
display layer (Plan 13-03) reads these values and computes the hit rate.

Graceful degradation (pattern from cache.py, pitfall 2): EVERY Redis access is
wrapped in try/except. If Redis fails, a metric is lost, but the request path
never crashes (incr/push degrade silently, read_* return empty/zero defaults).

decode_responses-agnostic: Read results are normalized to bytes via the local
``_to_bytes`` helper (identical to cache.py) before ``orjson.loads``, so that
the helpers work both with the prod pool (decode_responses=True) and with the
fake_redis test client (decode_responses=False).
"""

from __future__ import annotations

import orjson
import structlog

from cityscape.config import get_settings

log = structlog.get_logger()

# Redis key constants (centralized so that read and write sides use the same
# names). _LOG_KEY is the list of the request log ring buffer; the cache counter
# prefix is combined with the normalized status bucket; the request
# keys are a counter (count) plus two hashes (status code/endpoint).
_LOG_KEY = "metrics:logs"
_CACHE_PREFIX = "metrics:cache:"
_REQ_COUNT_KEY = "metrics:req:count"
_REQ_STATUS_KEY = "metrics:req:status"
_REQ_ENDPOINT_KEY = "metrics:req:endpoint"

# Active consumer tracking (OPS): per UTC hour a hash ident->request count
# plus a meta hash ident->"user-agent\tlast-path". ident = real client IP
# (or "mcp" for internal MCP server calls). Self-expiring (TTL) to prevent
# unbounded growth. Filtering internal monitoring IPs is done by the evaluation
# layer (the box digest knows its own IP), not the hot request path.
_CONSUMER_PREFIX = "metrics:consumers:"
_CONSUMER_TTL = 10800  # 3 h: safely covers hourly evaluation + delay.

# Daily request counter per channel (api|mcp): a single counter key per UTC day
# (metrics:daily:<channel>:<YYYY-MM-DD>) for the daily 00:05 digest. Intentionally
# NOT per-IP like the consumer buckets: exactly 2 keys/day, hence no Redis OOM
# in case of an IP flood. Self-expiring (TTL covers previous day + delay until digest).
_DAILY_PREFIX = "metrics:daily:"
_DAILY_TTL = 172800  # 48 h: previous day remains readable well after the 00:05 digest.

# The four cache status buckets (source: CacheStatus StrEnum). Bucket name is the
# lower-case status with "-" -> "_" (STALE-ON-ERROR -> stale_on_error).
_CACHE_BUCKETS = ("hit", "miss", "stale", "stale_on_error")


def _to_bytes(raw: bytes | str) -> bytes:
    """Normalizes a Redis read result to bytes (decode_responses-agnostic)."""
    if isinstance(raw, str):
        return raw.encode()
    return raw


def _bucket(status: str) -> str:
    """Maps a cache status to the Redis counter bucket (HIT -> hit)."""
    return status.lower().replace("-", "_")


async def incr_cache_status(redis, status: str) -> None:
    """Increments the cache status counter (HIT/MISS/STALE/STALE-ON-ERROR).

    Graceful: a Redis error loses the metric, but never crashes the request.
    """
    try:
        await redis.incr(f"{_CACHE_PREFIX}{_bucket(status)}")
    except Exception as exc:
        log.debug("metrics_incr_cache_failed", status=status, error=str(exc))


async def incr_request(redis, *, endpoint: str, status_code: int) -> None:
    """Counts a request: total counter + status code hash + endpoint hash.

    Graceful: any Redis error degrades silently (metric loss, no crash).
    """
    try:
        await redis.incr(_REQ_COUNT_KEY)
        await redis.hincrby(_REQ_STATUS_KEY, str(status_code), 1)
        await redis.hincrby(_REQ_ENDPOINT_KEY, endpoint, 1)
    except Exception as exc:
        log.debug("metrics_incr_request_failed", endpoint=endpoint, error=str(exc))


async def push_log(redis, entry: dict, max: int | None = None) -> None:
    """Pushes a log entry into the capped ring buffer (newest first).

    ``max`` is intentionally a None sentinel and is NOT bound as default directly
    from ``get_settings()``: otherwise the settings value would be frozen at import
    time and test determinism (monkeypatched admin_log_max) breaks.
    Fall back to the settings value only within the function. LPUSH places
    the newest entry at the head, LTRIM caps to the latest ``max`` entries.
    Graceful: a Redis error loses the log entry, but never crashes.
    """
    if max is None:
        max = get_settings().admin_log_max
    try:
        pipe = redis.pipeline()
        pipe.lpush(_LOG_KEY, orjson.dumps(entry).decode())
        pipe.ltrim(_LOG_KEY, 0, max - 1)
        await pipe.execute()
    except Exception as exc:
        log.debug("metrics_push_log_failed", error=str(exc))


async def read_logs(redis, n: int) -> list[dict]:
    """Reads the latest ``n`` log entries (newest first).

    Graceful: on a Redis error -> empty list instead of crash.
    """
    try:
        raw = await redis.lrange(_LOG_KEY, 0, n - 1)
    except Exception:
        return []
    return [orjson.loads(_to_bytes(item)) for item in raw]


async def read_cache_counts(redis) -> dict[str, int]:
    """Reads the four cache status counters (missing/errors -> 0).

    Graceful: on a Redis error -> all buckets 0.
    """
    try:
        raw = [await redis.get(f"{_CACHE_PREFIX}{b}") for b in _CACHE_BUCKETS]
    except Exception:
        return dict.fromkeys(_CACHE_BUCKETS, 0)
    return {
        b: int(v) if v is not None else 0
        for b, v in zip(_CACHE_BUCKETS, raw, strict=False)
    }


def consumer_hour(now) -> str:
    """UTC hour bucket key (e.g. ``2026-06-14T17``)."""
    return now.strftime("%Y-%m-%dT%H")


async def record_consumer(
    redis, *, ident: str, user_agent: str, path: str, status_code: int, now
) -> None:
    """Counts an active consumer into the hour bucket (count + latest meta).

    ``ident`` = real client IP or ``"mcp"`` (internal MCP server call). The
    meta hash stores User-Agent + last path + last HTTP status (last-write-
    wins, tab-separated) for app identification and to show in the digest whether
    a (scanner) path returned 200 or 404. Both keys expire automatically after
    ``_CONSUMER_TTL``. Graceful: any Redis error degrades silently and NEVER
    crashes the request.
    """
    try:
        hour = consumer_hour(now)
        ckey = f"{_CONSUMER_PREFIX}{hour}"
        mkey = f"{_CONSUMER_PREFIX}meta:{hour}"
        meta = f"{(user_agent or '')[:200]}\t{path}\t{status_code}"
        pipe = redis.pipeline()
        pipe.hincrby(ckey, ident, 1)
        pipe.hset(mkey, ident, meta)
        pipe.expire(ckey, _CONSUMER_TTL)
        pipe.expire(mkey, _CONSUMER_TTL)
        await pipe.execute()
    except Exception as exc:
        log.debug("record_consumer_failed", error=str(exc))


async def read_consumers(redis, hour: str) -> list[dict]:
    """Reads the active consumers of an hour bucket (count + UA + path + status).

    Return value per entry: ``{ident, count, user_agent, last_path, last_status}``,
    descending by count. ``last_status`` is the HTTP status of the last request
    as string (``""`` for legacy entries without status field). Graceful: on a
    Redis error -> empty list.
    """
    try:
        counts = await redis.hgetall(f"{_CONSUMER_PREFIX}{hour}")
        meta = await redis.hgetall(f"{_CONSUMER_PREFIX}meta:{hour}")
    except Exception:
        return []
    meta = {
        _to_bytes(k).decode(): _to_bytes(v).decode() for k, v in (meta or {}).items()
    }
    out = []
    for ident_raw, count_raw in (counts or {}).items():
        ident = _to_bytes(ident_raw).decode()
        # Tab-separated: UA \t path \t status. Legacy entries (without status) -> "".
        parts = meta.get(ident, "").split("\t")
        ua = parts[0] if parts else ""
        last_path = parts[1] if len(parts) > 1 else ""
        last_status = parts[2] if len(parts) > 2 else ""
        out.append(
            {
                "ident": ident,
                "count": int(count_raw),
                "user_agent": ua,
                "last_path": last_path,
                "last_status": last_status,
            }
        )
    out.sort(key=lambda c: c["count"], reverse=True)
    return out


async def incr_daily(redis, *, channel: str, now) -> None:
    """Counts a request into the channel's daily counter (``api``|``mcp``).

    A single counter key per channel and UTC day
    (``metrics:daily:<channel>:<YYYY-MM-DD>``) with automatic expiration (``_DAILY_TTL``).
    Unlike the per-IP consumer buckets, this does NOT grow with the number of
    clients (exactly two keys per day), hence no OOM risk during an IP flood.
    Feeds the daily 00:05 ntfy digest. Graceful: any Redis error
    degrades silently (metric loss), but NEVER crashes the request path.
    """
    try:
        key = f"{_DAILY_PREFIX}{channel}:{now.strftime('%Y-%m-%d')}"
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, _DAILY_TTL)
        await pipe.execute()
    except Exception as exc:
        log.debug("incr_daily_failed", channel=channel, error=str(exc))


async def read_daily(redis, *, day: str) -> dict[str, int]:
    """Reads the daily counters for all channels (``api``|``mcp``|``gpt``) for ``day``.

    ``day`` is a UTC date ``YYYY-MM-DD``. Missing keys -> 0. Graceful: on
    a Redis error -> all 0 (never a crash in the digest).
    """
    out = {"api": 0, "mcp": 0, "gpt": 0}
    try:
        for channel in out:
            raw = await redis.get(f"{_DAILY_PREFIX}{channel}:{day}")
            if raw is not None:
                out[channel] = int(raw)
    except Exception:
        return {"api": 0, "mcp": 0, "gpt": 0}
    return out


def compute_hit_rate(counts: dict[str, int]) -> float:
    """Computes the cache hit rate: hit / (hit + miss + stale + stale_on_error).

    STALE is included in the denominator (the cache served data, refresh ran in
    the background), but is displayed separately in the dashboard. Division by 0
    (no requests yet) -> 0.0, never a ZeroDivisionError.
    """
    total = sum(counts.get(b, 0) for b in _CACHE_BUCKETS)
    if total == 0:
        return 0.0
    return counts.get("hit", 0) / total


async def read_request_counts(redis) -> dict:
    """Reads request statistics: total count + status code hash + endpoint hash.

    Graceful: on a Redis error -> defaults (count 0, empty hashes).
    """
    try:
        count_raw = await redis.get(_REQ_COUNT_KEY)
        status_raw = await redis.hgetall(_REQ_STATUS_KEY)
        endpoint_raw = await redis.hgetall(_REQ_ENDPOINT_KEY)
    except Exception:
        return {"count": 0, "status": {}, "endpoint": {}}
    count = int(count_raw) if count_raw is not None else 0
    status = {_to_bytes(k).decode(): int(v) for k, v in (status_raw or {}).items()}
    endpoint = {_to_bytes(k).decode(): int(v) for k, v in (endpoint_raw or {}).items()}
    return {"count": count, "status": status, "endpoint": endpoint}
