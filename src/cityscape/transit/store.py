"""Redis store for compact, indexed GTFS-RT updates (Phase 19, Plan 04).

Writes ONLY the compact trip update dicts parsed by the adapter to Redis,
NEVER the raw 68 MB feed (anti-pattern, RESEARCH Pitfall 1: a raw feed body
in Redis exhausts the 4 GB box memory and makes every read path expensive). The
background poller (``transit/poller.py``) parses the feed ONCE per cadence and
calls ``store_updates_indexed``; the request path (``api/v1/live.py``) then reads
ONLY via the read helpers (no parse in the request, T-19-REQPARSE).

Key layout (versioned with ``v1`` prefix, analogous to ``infra/cache.build_cache_key``,
T-19-CACHEPOISON: trip_id/stop_id/route_id are validated by the caller, never a
raw user string):
- ``transit_rt:v1:{trip_id}``        -> orjson-serialized update dict (SET ex)
- ``transit_rt:idx:stop:{stop_id}``  -> set of trip_ids serving this stop
- ``transit_rt:idx:route:{route_id}``-> set of trip_ids for this line

All keys carry a TTL: a new poller run overwrites fresh data, and
if the poller fails, outdated updates expire automatically (only most recent
state, CONTEXT LOCKED). NO archive write (Tier B, T-19-ARCHIVE): pure
live data is NEVER written to the Tier A archive.
"""

from __future__ import annotations

import orjson

# Versioned key prefixes (RESEARCH architecture diagram). A schema change
# can move v1 -> v2 without needing to flush unrelated keys.
_TRIP_PREFIX = "transit_rt:v1:"
_STOP_IDX_PREFIX = "transit_rt:idx:stop:"
_ROUTE_IDX_PREFIX = "transit_rt:idx:route:"
# Provenance of the RT state currently in Redis (DATA-34/Mobilithek switch):
# which feed delivered the latest updates ("mobilithek_delfi" primary OR
# "gtfs_de" backup fallback). The read path selects the correct attribution from this.
_SOURCE_KEY = "transit_rt:source"


def _trip_key(trip_id: str) -> str:
    return f"{_TRIP_PREFIX}{trip_id}"


def _stop_idx_key(stop_id: str) -> str:
    return f"{_STOP_IDX_PREFIX}{stop_id}"


def _route_idx_key(route_id: str) -> str:
    return f"{_ROUTE_IDX_PREFIX}{route_id}"


async def store_updates_indexed(
    redis, updates, *, ttl: int = 90, trip_route_index: dict | None = None
) -> None:
    """Writes compact trip updates indexed into Redis (NEVER the raw feed).

    Per update: ``transit_rt:v1:{trip_id}`` as orjson value (SET with ex=ttl) plus
    the secondary indices ``idx:stop:{stop_id}`` (per stop) and
    ``idx:route:{route_id}`` (if route_id present) as set of affected
    trip_ids, also with TTL (via expire). ONLY compact dicts; the raw
    feed body is intentionally never stored here (anti-pattern).

    Audit Fix K7 (2026-06-29): In the real gtfs.de feed, ``trip.route_id``
    is consistently empty, meaning the ``idx:route:`` index was never populated and
    ``live_transit_route_status`` ALWAYS returned ``no_data``. With
    ``trip_route_index`` (``{trip_id: route_id}`` from static GTFS, built by the
    poller via ``resolver.build_trip_route_index``), a missing
    route_id is resolved via ``trip_id`` BEFORE indexing. The
    resolved route_id is also written into the stored update so the
    read path sees it. If the index is empty or the trip_id unknown, it
    honestly remains without index (no_data for this trip), but without crashing.
    """
    for update in updates:
        trip_id = update.get("trip_id")
        if not trip_id:
            continue

        route_id = update.get("route_id")
        # Audit Fix K7: resolve empty route_id from static GTFS.
        if not route_id and trip_route_index:
            resolved = trip_route_index.get(trip_id)
            if resolved:
                route_id = resolved
                update["route_id"] = resolved

        # Compact dict orjson-serialized (NEVER the raw feed body).
        await redis.set(_trip_key(trip_id), orjson.dumps(update), ex=ttl)

        if route_id:
            route_key = _route_idx_key(route_id)
            await redis.sadd(route_key, trip_id)
            await redis.expire(route_key, ttl)

        for stu in update.get("stop_time_updates", []) or []:
            stop_id = stu.get("stop_id")
            if not stop_id:
                continue
            stop_key = _stop_idx_key(stop_id)
            await redis.sadd(stop_key, trip_id)
            await redis.expire(stop_key, ttl)


async def store_rt_source(redis, source: str, *, ttl: int = 90) -> None:
    """Records the source of current RT state (provenance for attribution)."""
    await redis.set(_SOURCE_KEY, source, ex=ttl)


async def read_rt_source(redis) -> str | None:
    """Reads the provenance of current RT state (or ``None`` on miss)."""
    raw = await redis.get(_SOURCE_KEY)
    if raw is None:
        return None
    return raw.decode() if isinstance(raw, bytes) else str(raw)


async def get_trip_update(redis, trip_id: str) -> dict | None:
    """Reads the compact update of a ``trip_id`` (or ``None`` on miss)."""
    raw = await redis.get(_trip_key(trip_id))
    if raw is None:
        return None
    return orjson.loads(raw)


async def trips_for_stop(redis, stop_id: str) -> list[str]:
    """Returns trip_ids serving a stop (or empty list)."""
    members = await redis.smembers(_stop_idx_key(stop_id))
    return list(members)


async def trips_for_route(redis, route_id: str) -> list[str]:
    """Returns trip_ids of a line (or empty list)."""
    members = await redis.smembers(_route_idx_key(route_id))
    return list(members)
