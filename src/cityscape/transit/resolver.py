"""On-demand resolution index trip_id/route_id/stop against static GTFS.

Resolves live RT references (trip_id, route_id, stops) against static DELFI GTFS.
Built on memory-constant zip entry streaming from
:func:`cityscape.ingest.gtfs.stream_entry` (RESEARCH Pattern 3, T-06-03/T-19-MEM):

- ``trips.txt`` is small -> complete ``{trip_id: route_id}`` map in memory.
- ``stop_times.txt`` is several GB unpacked -> NEVER load completely. We stream
  line by line and accept ONLY rows for the requested ``trip_id``
  (Memory Pitfall 2 from RESEARCH; neither full read nor full unpack of the ZIP).

Index strategy (RESEARCH Open Question 2, Claude's Discretion):
- (a) MVP, implemented here: stream and filter per requested ``trip_id``. Pure
  function without cache/Redis; caching per trip_id (long TTL since static data
  only changes upon monthly refresh) occurs in caller (Plan 19-04).
- (b) Documented follow-up option: pre-built index only for the 28 register cities during
  static refresh (stream stop_times ONCE, store a compact index per city for each
  trip_id of the register cities via ``ingest.delfi.city_for_stop`` ->
  request lookup O(1) without GB scan). Added as needed in a refresh job.

NO network, no Redis access in these pure functions.
"""

from __future__ import annotations

from pathlib import Path

from cityscape.ingest.delfi import city_for_stop
from cityscape.ingest.gtfs import stream_entry
from cityscape.transit.interpolation import gtfs_time_to_epoch


def build_trip_route_index(zip_path: str | Path) -> dict[str, str]:
    """Builds a ``{trip_id: route_id}`` map from ``trips.txt``.

    ``trips.txt`` is small enough for a complete in-memory map. Streams
    the entry line by line (no full read, no full unpack) and is
    idempotent: a second run yields the same result (overwrite snapshot,
    no drift).
    """
    return {
        row["trip_id"]: row["route_id"] for row in stream_entry(zip_path, "trips.txt")
    }


def stop_times_for_trip(zip_path: str | Path, trip_id: str) -> list[dict]:
    """Returns stops of ONE ``trip_id`` sorted by ``stop_sequence``.

    Streams ``stop_times.txt`` (several GB) line by line and accepts ONLY
    rows of the requested ``trip_id``. COMMENT requirement (T-06-03/T-19-MEM):
    ``stop_times.txt`` is NEVER loaded completely, only streamed and filtered.

    Unknown ``trip_id`` -> empty list.
    """
    out: list[dict] = []
    # NEVER load stop_times.txt (several GB) completely: only stream and filter.
    for row in stream_entry(zip_path, "stop_times.txt"):
        if row.get("trip_id") != trip_id:
            continue
        out.append(
            {
                "stop_id": row["stop_id"],
                "stop_sequence": int(row["stop_sequence"]),
                "arrival_time": row.get("arrival_time"),
                "departure_time": row.get("departure_time"),
            }
        )
    return sorted(out, key=lambda r: r["stop_sequence"])


def _stops_geo_index(zip_path: str | Path) -> dict[str, dict[str, float]]:
    """Builds a ``{stop_id: {lat, lon}}`` map from ``stops.txt``.

    ``stops.txt`` is small enough for a complete in-memory map (unlike
    ``stop_times.txt``). Streams line by line (no full read). Rows without
    parseable coordinates are skipped (honestly, no error).
    """
    out: dict[str, dict[str, float]] = {}
    for row in stream_entry(zip_path, "stops.txt"):
        sid = row.get("stop_id")
        if not sid:
            continue
        try:
            out[sid] = {"lat": float(row["stop_lat"]), "lon": float(row["stop_lon"])}
        except (KeyError, ValueError, TypeError):
            continue
    return out


def stops_with_geo_for_trip(
    zip_path: str | Path, trip_id: str, *, service_day_epoch: int
) -> list[dict]:
    """Returns trip stops enriched with geo + ``scheduled_epoch``.

    Combines :func:`stop_times_for_trip` (sorted stops with scheduled times) with the
    ``stops.txt`` geo map and converts the GTFS scheduled time (``arrival_time``, otherwise
    ``departure_time``, "HH:MM:SS", >24h possible) against the injected
    ``service_day_epoch`` into a ``scheduled_epoch`` (pure function, no
    system clock). Stops without geo OR without parseable scheduled time are skipped
    so that :func:`cityscape.transit.interpolation.estimate_position` only
    sees complete stops. Unknown ``trip_id`` -> empty list.
    """
    stops = stop_times_for_trip(zip_path, trip_id)
    if not stops:
        return []
    geo = _stops_geo_index(zip_path)
    enriched: list[dict] = []
    for s in stops:
        sid = s["stop_id"]
        coords = geo.get(sid)
        hms = s.get("arrival_time") or s.get("departure_time")
        if coords is None or not hms:
            continue
        try:
            scheduled = gtfs_time_to_epoch(hms, service_day_epoch=service_day_epoch)
        except (ValueError, AttributeError):
            continue
        enriched.append(
            {
                "stop_id": sid,
                "stop_sequence": s["stop_sequence"],
                "scheduled_epoch": scheduled,
                "lat": coords["lat"],
                "lon": coords["lon"],
            }
        )
    return enriched


def slug_for_trip(zip_path: str | Path, trip_id: str) -> str | None:
    """Maps a ``trip_id`` to a register city via its first stop.

    Helper function for the optional pre-built index per city (RESEARCH Pattern 3b):
    uses :func:`cityscape.ingest.delfi.city_for_stop` on the trip's first stop_id
    (NO new geo code). Returns register slug or ``None`` (trip
    outside the 28 register cities or unknown trip_id).
    """
    stops = stop_times_for_trip(zip_path, trip_id)
    if not stops:
        return None
    return city_for_stop(stops[0]["stop_id"])
