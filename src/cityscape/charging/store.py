"""Redis store for accumulated eRound occupancy deltas (DATA-42, Stage 2).

The dynamic eRound feed is a DRAIN QUEUE (live verified 2026-07-03:
pull1=14, pull2=4 points, 0 overlap): each pull yields only changes
since the last pull, NEVER the full state. The full state only arises through
ACCUMULATION of deltas in Redis.

Key layout (versioned, ``transit/store.py`` pattern):
- ``eround_charging:v1:{refill_point_id}`` -> orjson ``{status, observed_at}``
  (SET with ``ex=ttl``).

Each key carries TTL as an honest staleness window: if the poller fails,
outdated statuses expire automatically (no perpetually frozen "available").
NO archive write (pure live data, T-20-ARCHIVE).
"""

from __future__ import annotations

import orjson

_KEY_PREFIX = "eround_charging:v1:"

#: Snapshot of the latest delta pull result (for the /live read path).
#: The request path NEVER pulls by itself (strict decoupling of data updates from
#: request worker): the poller is the ONLY upstream puller and deposits
#: the last pull result here; the /live route only reads this key.
_LATEST_KEY = "eround_charging:latest"

#: Freshness window of the snapshot: 3 poll ticks (300 s) grace period, then honest
#: no_data instead of a frozen outdated state (poller dead = visible).
LATEST_TTL_S = 900

#: Staleness window: a charging point status without a fresh delta is valid for at
#: most 24 h (the feed only delivers changes; an unchanged point therefore remains
#: valid longer than the poll cadence, but not forever).
STATUS_TTL_S = 24 * 60 * 60

#: MGET chunk size for the read path (Hamburg has ~2700 points; a single
#: giant MGET is avoided).
_MGET_CHUNK = 1000


def _key(refill_point_id: str) -> str:
    return f"{_KEY_PREFIX}{refill_point_id}"


async def store_point_statuses(redis, points, *, ttl: int = STATUS_TTL_S) -> int:
    """Accumulates occupancy deltas in Redis (SET with TTL per point).

    ``points`` are adapter dicts from ``adapters/mobilithek_afir.py``
    (``refill_point_id`` + ``status`` [+ ``observed_at``]). Entries without ID
    or status are honestly omitted. Returns: count of written points.
    Idempotent (rewriting the same delta state is harmless).
    """
    pipe = redis.pipeline()
    written = 0
    for point in points or []:
        if not isinstance(point, dict):
            continue
        rp_id = point.get("refill_point_id")
        status = point.get("status")
        if not rp_id or not status:
            continue
        value = orjson.dumps(
            {"status": str(status), "observed_at": point.get("observed_at")}
        )
        pipe.set(_key(str(rp_id)), value, ex=ttl)
        written += 1
    if written:
        await pipe.execute()
    return written


async def store_latest_delta(redis, raw: dict, *, ttl: int = LATEST_TTL_S) -> None:
    """Stores the latest delta pull result as snapshot (poller only).

    ``raw`` is the adapter dict from ``fetch_afir`` (``points`` + ``as_of``).
    Even an EMPTY result is written: it keeps the snapshot fresh and
    lets the read path honestly report ``no_data`` (feed delivered nothing),
    instead of freezing an old state.
    """
    value = orjson.dumps({"points": raw.get("points") or [], "as_of": raw.get("as_of")})
    await redis.set(_LATEST_KEY, value, ex=ttl)


async def read_latest_delta(redis) -> dict | None:
    """Reads the latest delta snapshot (or ``None`` on miss/corrupt)."""
    raw = await redis.get(_LATEST_KEY)
    if raw is None:
        return None
    try:
        value = orjson.loads(raw)
    except orjson.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


async def get_point_statuses(redis, rp_ids) -> dict[str, dict]:
    """Reads accumulated statuses for a set of IDs (chunked MGET).

    Returns: ``{refill_point_id: {status, observed_at}}`` ONLY for points with
    fresh (unexpired) status; unknown/expired IDs are honestly omitted.
    A corrupt single value is skipped (no 500).
    """
    ids = [str(i) for i in rp_ids]
    result: dict[str, dict] = {}
    for start in range(0, len(ids), _MGET_CHUNK):
        chunk = ids[start : start + _MGET_CHUNK]
        raw_values = await redis.mget([_key(i) for i in chunk])
        for rp_id, raw in zip(chunk, raw_values, strict=True):
            if raw is None:
                continue
            try:
                value = orjson.loads(raw)
            except orjson.JSONDecodeError:
                continue
            if isinstance(value, dict) and value.get("status"):
                result[rp_id] = value
    return result
