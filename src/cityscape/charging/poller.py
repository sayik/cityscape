"""Background poller for eRound occupancy deltas (DATA-42, Stage 2).

Pattern ``transit/poller.py``: long-running asyncio task in lifespan
(``main.py`` ``_schedule``/``bg_tasks``), NEVER in request path. Each iteration
pulls the dynamic eRound subscription (drain queue: only changes since the
last pull) and accumulates deltas into Redis
(``charging/store.store_point_statuses``). The request path
(``/cities/{slug}/charging-status``) subsequently reads ONLY from Redis.

Robustness: a failing iteration (upstream down, parse error) does NOT crash
the task (``log.warning``), the next one runs after ``interval_s``.
``CancelledError`` (shutdown) is passed through. A per-tick Redis lock
(SET NX EX) prevents redundant pulls across multiple workers/replicas; because the
feed is a drain queue, a duplicate pull would not be an error (both accumulate
their subset to Redis), only unnecessary upstream traffic.
"""

from __future__ import annotations

import asyncio

import structlog

from cityscape.adapters.mobilithek_afir import fetch_afir
from cityscape.charging.store import store_latest_delta, store_point_statuses

log = structlog.get_logger()

#: Poll cadence: 5 minutes (plan specification live_5min; the feed is minute-fresh,
#: the drain queue buffers changes between pulls without loss).
_INTERVAL_S = 300

_LOCK_KEY = "lock:eround_charging_poll"


async def eround_status_poller(app, *, abo_id: str, interval_s: int = _INTERVAL_S):
    """Infinite loop: pull dynamic subscription and accumulate deltas into Redis."""
    while True:
        try:
            # Multi-worker guard (gtfs_rt_poller pattern): only one worker polls
            # per interval; Redis error -> poll anyway (graceful degradation).
            should_poll = True
            try:
                should_poll = bool(
                    await app.state.redis.set(
                        _LOCK_KEY, b"1", nx=True, ex=max(1, interval_s - 5)
                    )
                )
            except Exception:
                should_poll = True
            if should_poll:
                raw = await fetch_afir(
                    app.state.mobilithek_http, abo_id=abo_id, slug="eround"
                )
                points = raw.get("points") or []
                if points:
                    written = await store_point_statuses(app.state.redis, points)
                    log.info("eround_status_accumulated", points=written)
                # ALWAYS write snapshot (even if empty): the /live read path
                # never pulls by itself (strict decoupling from request worker)
                # and needs a fresh state for ok/no_data honesty.
                await store_latest_delta(app.state.redis, raw)
        except asyncio.CancelledError:
            # Shutdown (lifespan-finally cancels bg_tasks): exit cleanly.
            raise
        except Exception as exc:  # noqa: BLE001 - an iteration must never crash
            log.warning("eround_status_poll_failed", error=type(exc).__name__)
        await asyncio.sleep(interval_s)


def maybe_start_eround_poller(app, settings, schedule) -> None:
    """Starts the poller ONLY with active toggle + cert + subscription ID (GTFS-RT pattern).

    Without ``enable_eround_charging`` OR without mTLS client
    (``app.state.mobilithek_http``) OR without ``eround_charging_abo_id``,
    NO task is created (graceful degradation = the route returns ``disabled``/
    ``no_data``, app startup remains unchanged).
    """
    if not getattr(settings, "enable_eround_charging", False):
        return
    abo_id = getattr(settings, "eround_charging_abo_id", None)
    if getattr(app.state, "mobilithek_http", None) is None or not abo_id:
        return

    schedule(eround_status_poller(app, abo_id=abo_id))
