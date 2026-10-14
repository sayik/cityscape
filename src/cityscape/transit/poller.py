"""Background poller for GTFS-RT (Phase 19, Plan 04, RESEARCH Pattern 1).

The poller parses the GTFS-RT feed (~68 MB) ONCE per cadence and stores the compact,
indexed updates into Redis (``transit/store.store_updates_indexed``). The
request path subsequently reads ONLY from Redis (no 68 MB parse per request, no
CPU spike/OOM on the 4 GB box, T-19-REQPARSE). The poller runs as a long-lived
asyncio task in the lifespan (``main.py`` ``_schedule``/``bg_tasks``), NEVER in the
request path.

Robustness: an iteration that fails with an exception (upstream down,
parse error) must NOT crash the task - it is logged (``log.warning``),
and the next iteration runs after ``interval_s`` seconds. ``CancelledError``
(shutdown in lifespan-finally) is passed through (clean exit).
"""

from __future__ import annotations

import asyncio

import structlog

from cityscape.adapters.gtfs_rt import fetch_gtfs_rt_feed, parse_trip_updates
from cityscape.transit.resolver import build_trip_route_index
from cityscape.transit.store import store_rt_source, store_updates_indexed

log = structlog.get_logger()


def _gtfs_static_path_for(settings, used_source: str | None) -> str | None:
    """Selects the static GTFS path matching the RT provenance (Audit Fix K7).

    Analogous to ``api/v1/live.live_transit_trip``: if the DELFI feed currently
    delivers (``mobilithek_delfi``), the DELFI IDs are resolved against
    ``delfi_gtfs_path`` (fallback ``gtfs_rt_static_path``); for the gtfs.de backup, vice versa.
    This aligns the ID namespace (trip_id) and static data. ``None`` -> no
    static data configured (route_id remains honestly unresolved, no crash).
    """
    if used_source == "mobilithek_delfi":
        return getattr(settings, "delfi_gtfs_path", None) or getattr(
            settings, "gtfs_rt_static_path", None
        )
    return getattr(settings, "gtfs_rt_static_path", None) or getattr(
        settings, "delfi_gtfs_path", None
    )


def _load_trip_route_index(cache: dict, path: str | None) -> dict | None:
    """Builds/caches the ``{trip_id: route_id}`` map per static path (Audit Fix K7).

    ``trips.txt`` is small; the index is built ONCE per path and reused in
    ``cache`` (held per poller run), rather than streaming it afresh from disk
    every tick (45s). A read/parse error OR a missing
    path -> ``None`` (honestly, no crash; route_id remains unresolved).
    """
    if not path:
        return None
    if path in cache:
        return cache[path]
    try:
        index = build_trip_route_index(path)
    except (OSError, KeyError, ValueError) as exc:
        log.warning("gtfs_rt_static_index_failed", error=str(exc), path=path)
        index = None
    cache[path] = index
    return index


async def _fetch_with_fallback(
    app, *, source: str, abo_id: str | None
) -> tuple[bytes | None, str | None]:
    """Fetches the RT feed and falls back from ``mobilithek_delfi`` to ``gtfs_de``.

    Primary source ``mobilithek_delfi`` (DELFI via Mobilithek mTLS): if it
    returns no bytes (no_data/disabled) OR fails (upstream error), the
    keyless gtfs.de backup feed is pulled ("switch and gtfs as backup"). Returns
    ``(body, used_source)`` so the read path can choose the correct attribution
    (DELFI e.V. vs gtfs.de). Other sources (gtfs_de) have no fallback.
    """
    http = app.state.http
    mtls = getattr(app.state, "mobilithek_http", None)
    if source == "mobilithek_delfi":
        try:
            feed = await fetch_gtfs_rt_feed(
                http, mtls, source="mobilithek_delfi", abo_id=abo_id
            )
        except Exception as exc:  # noqa: BLE001 - DELFI error -> backup, no crash
            log.warning("gtfs_rt_delfi_failed_fallback_gtfs_de", error=str(exc))
            feed = None
        if feed is not None:
            return feed, "mobilithek_delfi"
        # Backup: keyless gtfs.de feed (raise_for_status caught by outer loop).
        feed = await fetch_gtfs_rt_feed(http, None, source="gtfs_de", abo_id=None)
        return feed, "gtfs_de"

    feed = await fetch_gtfs_rt_feed(http, mtls, source=source, abo_id=abo_id)
    return feed, source


async def gtfs_rt_poller(
    app,
    *,
    interval_s: int = 45,
    source: str,
    abo_id: str | None,
    settings=None,
) -> None:
    """Infinite loop: fetches + parses the feed each cadence and writes to Redis.

    Each iteration: ``fetch_gtfs_rt_feed`` -> on ``None`` (no_data/disabled),
    the store is skipped; on ``bytes`` -> ``parse_trip_updates`` ->
    ``store_updates_indexed``. An exception in an iteration does NOT crash the task
    (``log.warning``, continues after ``asyncio.sleep(interval_s)``).
    ``CancelledError`` (shutdown) is passed through.

    Audit Fix K7: from ``settings``, the static GTFS path is determined per
    provenance and a ``{trip_id: route_id}`` index is constructed from it (cached
    per path), so that ``store_updates_indexed`` can resolve empty route_ids.
    """
    # Audit Fix K7: index cache per static path (survives ticks; trips.txt
    # changes only during the weekly static refresh).
    index_cache: dict = {}
    while True:
        try:
            # Multi-worker guard: with uvicorn --workers this poller runs in
            # EVERY worker. A per-tick Redis lock (SET NX EX) ensures that
            # only ONE worker actually polls per interval (no redundant
            # upstream fetch). TTL < interval -> expires before the next tick;
            # if the holder fails, another worker takes over next tick
            # (self-healing, no permanent leader). Redis error -> poll
            # anyway (graceful degradation, never crash).
            should_poll = True
            try:
                should_poll = bool(
                    await app.state.redis.set(
                        "lock:gtfs_rt_poll",
                        b"1",
                        nx=True,
                        ex=max(1, interval_s - 5),
                    )
                )
            except Exception:
                should_poll = True
            if should_poll:
                feed, used_source = await _fetch_with_fallback(
                    app, source=source, abo_id=abo_id
                )
                if feed is not None:
                    updates = parse_trip_updates(feed)
                    # Audit Fix K7: resolve route_id from the static GTFS
                    # matching the provenance (index cached per path).
                    trip_route_index = None
                    if settings is not None:
                        static_path = _gtfs_static_path_for(settings, used_source)
                        trip_route_index = _load_trip_route_index(
                            index_cache, static_path
                        )
                    await store_updates_indexed(
                        app.state.redis,
                        updates,
                        ttl=90,
                        trip_route_index=trip_route_index,
                    )
                    # Provenance of the snapshot for read-path attribution.
                    await store_rt_source(
                        app.state.redis, used_source or source, ttl=90
                    )
        except asyncio.CancelledError:
            # Shutdown (lifespan-finally cancels bg_tasks): exit cleanly.
            raise
        except Exception as exc:  # noqa: BLE001 - an iteration must never crash
            log.warning("gtfs_rt_poll_failed", error=str(exc), source=source)
        await asyncio.sleep(interval_s)


def maybe_start_gtfs_rt_poller(app, settings, schedule) -> None:
    """Starts the poller task ONLY when the toggle is active + source resolvable.

    Resolvability (RESEARCH Pattern 7):
    - ``enable_gtfs_rt`` must be True,
    - Source ``gtfs_de``: always resolvable (keyless),
    - Source ``mobilithek_delfi``: only with mTLS client (``app.state.mobilithek_http``)
      AND ``transit_rt_delfi_abo_id`` (settings allowlist, SSRF) - otherwise no task
      (graceful degradation = disabled).

    When the toggle is disabled (default), NO task is created (bg_tasks
    unchanged), existing app startup remains unaffected.
    """
    if not getattr(settings, "enable_gtfs_rt", False):
        return

    source = getattr(settings, "transit_rt_source", "gtfs_de")
    abo_id = getattr(settings, "transit_rt_delfi_abo_id", None)

    if source == "mobilithek_delfi":
        mobilithek_http = getattr(app.state, "mobilithek_http", None)
        if mobilithek_http is None or not abo_id:
            # Source not resolvable: without cert/subscription no pull -> no task.
            return

    schedule(
        gtfs_rt_poller(
            app, interval_s=45, source=source, abo_id=abo_id, settings=settings
        )
    )
