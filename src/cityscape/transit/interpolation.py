"""Pure linear position estimation between two GTFS stops.

Estimates the position of a trip linearly between the last passed stop and
the next stop (RESEARCH Pattern 4) using the scheduled timetable (sorted stops
with geo + scheduled_epoch) and current delay. The linear interpolation
on lat/lon is an approximation (does not follow the actual route shape) and is
therefore flagged with ``estimated=True``.

Pattern "pure function with injected time" (analogous to
``mappers/mobilithek_koeln.py``: ``retrieved_at`` keyword-only, no system clock in
core): ``now_epoch`` and ``service_day_epoch`` are injected. This makes the
function deterministically testable and free of non-reproducible state
(T-19-CLOCK). NO system clock in core (no calls to wall-clock functions
from ``datetime`` or ``time``).
"""

from __future__ import annotations


def estimate_position(
    stops: list[dict], *, delay_s: int, now_epoch: int
) -> dict | None:
    """Interpolates the position of a trip linearly between two stops.

    ``stops`` are stops sorted by scheduled time with keys ``scheduled_epoch``
    (int), ``lat`` (float), ``lon`` (float), and ``stop_id`` (str). ``delay_s``
    shifts the effective scheduled time: ``adjusted = now_epoch - delay_s`` (a
    current delay means the trip corresponds to an earlier scheduled time).

    Finds ``prev`` (last stop with ``scheduled_epoch <= adjusted``) and ``nxt``
    (first stop thereafter). If either is ``None`` -> returns ``None``
    (honestly before departure or after arrival, no fantasy position). If
    ``span <= 0`` -> ``frac = 0.0`` (no ``ZeroDivisionError``).

    Returns ``{"lat", "lon", "estimated": True, "between": [prev_id, nxt_id]}``.
    """
    adjusted = now_epoch - delay_s  # Scheduled time the trip currently corresponds to
    prev: dict | None = None
    nxt: dict | None = None
    for s in stops:
        if s["scheduled_epoch"] <= adjusted:
            prev = s
        else:
            nxt = s
            break
    if prev is None or nxt is None:
        return None  # before departure / after arrival -> honestly None
    span = nxt["scheduled_epoch"] - prev["scheduled_epoch"]
    frac = 0.0 if span <= 0 else (adjusted - prev["scheduled_epoch"]) / span
    return {
        "lat": prev["lat"] + (nxt["lat"] - prev["lat"]) * frac,
        "lon": prev["lon"] + (nxt["lon"] - prev["lon"]) * frac,
        "estimated": True,  # Flag estimate (linear approximation)
        "between": [prev["stop_id"], nxt["stop_id"]],
    }


def gtfs_time_to_epoch(hms: str, *, service_day_epoch: int) -> int:
    """Converts a GTFS time ``"HH:MM:SS"`` against a service day into epoch.

    GTFS times are relative to the service day and can be >24:00:00 (e.g.
    ``25:30:00`` = 01:30 of the following day). ``service_day_epoch`` (midnight of
    the service day as Unix epoch) is injected (no system clock in core):
    ``service_day_epoch + HH*3600 + MM*60 + SS``.
    """
    h, m, s = (int(part) for part in hms.split(":"))
    return service_day_epoch + h * 3600 + m * 60 + s
