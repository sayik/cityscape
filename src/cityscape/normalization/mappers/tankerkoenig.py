"""Reiner Tankerkönig mapper ``map_fuel_prices`` (fuel prices, CC BY 4.0, Tier A).

Deterministically translates the aggregated Tankerkönig raw dict (from
``adapters.tankerkoenig.fetch_fuel_prices``) into a
``CanonicalRecord`` with ``FuelPricePayload``. Pure: no HTTP, no logging, no
``datetime.now()`` (``retrieved_at`` is injected).

The city aggregates (avg/min per fuel type) are CALCULATED from the individual prices
(average/minimum), hence ``modified=True``. License: CC BY 4.0, Attribution
word-for-word: “Tankerkoenig (creativecommons.tankerkoenig.de), MTS-K” (must appear verbatim
in DATA-LICENSES.md + SOURCE_LICENSE).
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    FuelPricePayload,
    GeoPoint,
    LicenseId,
    LicenseTier,
    SourceId,
)

_CC_BY_4_0_URL = "https://creativecommons.org/licenses/by/4.0/"


def map_fuel_prices(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> CanonicalRecord:
    """Maps a city's aggregated fuel prices to a ``CanonicalRecord``.

    ``lat``/``lon`` come from the register (the metric aggregates gas stations within
    the vicinity of these coordinates). ``modified=True``, because the city aggregates are calculated from the
    individual prices.
    """
    geo = GeoPoint(lat=lat, lon=lon) if lat is not None and lon is not None else None
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=geo,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.TANKERKOENIG,
        license_id=LicenseId.CC_BY_4_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Tankerkoenig (creativecommons.tankerkoenig.de), MTS-K",
            license_url=_CC_BY_4_0_URL,
            modified=True,
        ),
        payload=FuelPricePayload(
            radius_km=raw.get("radius_km"),
            station_count=raw.get("station_count", 0),
            open_count=raw.get("open_count", 0),
            avg_e5=raw.get("avg_e5"),
            avg_e10=raw.get("avg_e10"),
            avg_diesel=raw.get("avg_diesel"),
            min_e5=raw.get("min_e5"),
            min_e10=raw.get("min_e10"),
            min_diesel=raw.get("min_diesel"),
            stations=raw.get("stations", []),
        ),
    )
