"""Pure StaDa mapper ``map_station_catalog`` (DATA-36, CC BY 4.0, Tier A).

Converts the StaDa raw dict filtered by city (``{slug, stations}``, built
in the route from ``adapters.stada.fetch_all_stations`` + ags filters)
deterministically into a ``CanonicalRecord`` with ``StationCatalogPayload``. Pure:
no HTTP, no logging, no ``datetime.now()`` (``retrieved_at`` injected).

The catalog is passed through unchanged (no merge), hence ``modified=False``.
License: CC BY 4.0, attribution must read exactly “Deutsche Bahn AG” (must appear verbatim in
DATA-LICENSES.md + SOURCE_LICENSE, T-11-SRC-DRIFT).
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    GeoPoint,
    LicenseId,
    LicenseTier,
    SourceId,
    StationCatalogPayload,
)

_CC_BY_4_0_URL = "https://creativecommons.org/licenses/by/4.0/"


def map_station_catalog(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> CanonicalRecord:
    """Maps a city's train station catalog to a ``CanonicalRecord``.

    ``modified=False`` (master data unchanged). ``observed_at=None`` (no
    observation time). ``lat``/``lon`` (city coordinates from the registry) are,
    if available, set as ``geo``.
    """
    stations = raw.get("stations", [])
    geo = GeoPoint(lat=lat, lon=lon) if lat is not None and lon is not None else None
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=geo,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.STADA,
        license_id=LicenseId.CC_BY_4_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Deutsche Bahn AG", license_url=_CC_BY_4_0_URL, modified=False
        ),
        payload=StationCatalogPayload(
            station_count=len(stations),
            stations=stations,
        ),
    )
