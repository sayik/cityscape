"""eRound geo map: refill_point_id -> city slug + coordinates (DATA-42, Stage 1).

The dynamic eRound occupancy feed carries ONLY ``refill_point_id`` + ``status``
(no geo). City assignment is provided by the static full inventory
(``aegiEnergyInfrastructureTablePublication``, ~94 MB JSON, coordinates per
STATION under ``locationReference.locAreaLocation.coordinatesForDisplay``,
live verified 2026-07-03: 4921 sites / 7401 stations / 14937 charging points).

Two roles:
- ``build_geo_map(doc)``: pure transformation of the parsed stat document into
  the map ``{slug: {refill_point_id: [lat, lon]}}`` (nearest registry city within
  population-scaled radius, formula pattern BORIS/denkmal). Pure and without
  IO, so that the private ingest (``ingest.eround_geo``) and seed generator
  compute the exact same assignment.
- ``load_city_points(path)``: cached file loader for the request path.
  Source of truth is the file in the persistent data volume (written by daily
  ingest); if missing, the loader falls back to the committed seed
  (``data/seeds/eround_geo_map.json``). DELIBERATELY a file instead of Redis:
  the Redis store is not persistent (allkeys-lru, no RDB/AOF) and could
  silently evict the map; the file survives restarts.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import structlog

from cityscape.infra.seeds import seeds_dir

log = structlog.get_logger()

# Fallback seed in the repo (initial full inventory from 2026-07-03, CC0). Ingest
# writes the fresher copy into the data volume (settings.eround_geo_map_path).
_SEED_NAME = "eround_geo_map.json"

# Loader cache per (resolved path): (mtime, cities-dict). The map changes
# at most once daily (ingest); an mtime check per request is sufficient.
_CACHE: dict[str, tuple[float, dict]] = {}


def _city_radius_deg(population: int | None) -> float:
    """City radius (degrees) from population (formula pattern BORIS/denkmal).

    Larger cities = larger city area -> larger radius, clamped to
    [0.06, 0.30] degrees. Deliberately coarse (city core radius, not official
    boundary clipping): a charging point just outside the municipal border of a
    major city functionally belongs to the city charging network.
    """
    pop = population or 0
    return min(0.30, max(0.06, 0.05 + pop / 16_000_000))


def _coerce_list(value) -> list:
    """Normalizes DATEX II field to a list (dict OR list OR None)."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def nearest_city_slug(lat: float, lon: float, cities) -> str | None:
    """Nearest city whose radius contains the point (normalized degree distance).

    ``cities`` is a sequence of ``(slug, lat, lon, radius_deg)``. The
    longitude difference is compressed with ``cos(lat)`` so ground distance
    is approximately isotropic (pattern ``denkmal._bbox_param``). No match ->
    ``None`` (point lies outside all registry cities, e.g. rural).
    """
    best: str | None = None
    best_d: float | None = None
    for slug, clat, clon, radius in cities:
        dlat = lat - clat
        dlon = (lon - clon) * math.cos(math.radians(clat))
        d = math.hypot(dlat, dlon)
        if d <= radius and (best_d is None or d < best_d):
            best, best_d = slug, d
    return best


def _registry_cities() -> list[tuple[str, float, float, float]]:
    """All 84 registry cities as (slug, lat, lon, radius_deg) tuples."""
    from cityscape.registry import CITY_REGISTRY

    return [
        (c.slug, c.geo.lat, c.geo.lon, _city_radius_deg(c.population))
        for c in CITY_REGISTRY
    ]


def build_geo_map(doc: dict) -> dict:
    """Builds the geo map from parsed static full inventory (pure, no IO).

    Navigates ``payload[].aegiEnergyInfrastructureTablePublication`` ->
    ``energyInfrastructureTable[]`` -> ``energyInfrastructureSite[]`` ->
    ``energyInfrastructureStation[]`` (coordinates) -> ``refillPoint[].
    aegiElectricChargingPoint.idG``. Stations without coordinates or outside
    all city radii are honestly omitted (the dynamic status of these
    points cannot be assigned to any city). Returns:
    ``{"publication_time": ..., "cities": {slug: {rp_id: [lat, lon]}}}``.
    """
    container = doc.get("messageContainer")
    if not isinstance(container, dict):
        container = doc if isinstance(doc, dict) else {}

    cities = _registry_cities()
    by_city: dict[str, dict[str, list[float]]] = {}
    publication_time: str | None = None

    for payload in _coerce_list(container.get("payload")):
        if not isinstance(payload, dict):
            continue
        pub = payload.get("aegiEnergyInfrastructureTablePublication")
        if not isinstance(pub, dict):
            continue
        if publication_time is None and pub.get("publicationTime"):
            publication_time = str(pub["publicationTime"])
        for table in _coerce_list(pub.get("energyInfrastructureTable")):
            if not isinstance(table, dict):
                continue
            for site in _coerce_list(table.get("energyInfrastructureSite")):
                if not isinstance(site, dict):
                    continue
                for station in _coerce_list(site.get("energyInfrastructureStation")):
                    if not isinstance(station, dict):
                        continue
                    loc = (
                        (station.get("locationReference") or {})
                        .get("locAreaLocation", {})
                        .get("coordinatesForDisplay", {})
                    )
                    lat, lon = loc.get("latitude"), loc.get("longitude")
                    if lat is None or lon is None:
                        continue
                    slug = nearest_city_slug(float(lat), float(lon), cities)
                    if slug is None:
                        continue
                    for rp in _coerce_list(station.get("refillPoint")):
                        cp = (
                            rp.get("aegiElectricChargingPoint")
                            if isinstance(rp, dict)
                            else None
                        )
                        if isinstance(cp, dict) and cp.get("idG"):
                            by_city.setdefault(slug, {})[str(cp["idG"])] = [
                                round(float(lat), 6),
                                round(float(lon), 6),
                            ]

    return {
        "publication_time": publication_time,
        "cities": {slug: by_city[slug] for slug in sorted(by_city)},
    }


def load_city_points(path: str) -> dict[str, dict[str, list[float]]]:
    """Loads the geo map for the request path (volume file, otherwise seed).

    mtime-cached per path (the map changes at most daily). An
    unreadable/corrupt file -> empty map + warning (the route then
    honestly returns ``no_data``, no 500). Return value is ONLY the ``cities`` dict.
    """
    candidate = Path(path)
    if not candidate.is_file():
        candidate = seeds_dir() / _SEED_NAME
    resolved = str(candidate)

    try:
        mtime = os.path.getmtime(resolved)
    except OSError:
        return {}

    cached = _CACHE.get(resolved)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    try:
        with open(resolved, encoding="utf-8") as fh:
            data = json.load(fh)
        cities = data.get("cities")
        if not isinstance(cities, dict):
            cities = {}
    except (OSError, ValueError) as exc:
        log.warning("eround_geo_map_unreadable", error=type(exc).__name__)
        cities = {}

    _CACHE[resolved] = (mtime, cities)
    return cities
