"""Pure SMARD mapper `map_smard` (Electricity Market Data, CC BY 4.0, Tier A).

Translates the flat SMARD-raw-dict (from ``adapters.smard.fetch_smard``)
deterministically into a ``CanonicalRecord`` with ``PowerPayload``. Pure: no
HTTP, no logging, no ``datetime.now()`` (``retrieved_at`` is injected).

SMARD data is adopted unchanged (no processing), therefore
``modified=False``. License: CC BY 4.0, attribution must read exactly "Bundesnetzagentur |
SMARD.de" (must appear verbatim in DATA-LICENSES.md + SOURCE_LICENSE).
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    GeoPoint,
    LicenseId,
    LicenseTier,
    PowerPayload,
    SourceId,
)

_CC_BY_4_0_URL = "https://creativecommons.org/licenses/by/4.0/"


def map_smard(
    slug: str,
    raw: dict,
    *,
    measure: str,
    unit: str,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> CanonicalRecord:
    """Maps an SMARD daily value to a ``CanonicalRecord``.

    ``measure`` is “load” (electricity consumption/grid load, per control zone) or ‘price’
    (day-ahead wholesale price, nationwide). ``unit`` is, for example, “MWh” or “EUR/MWh”.
    ``lat``/``lon`` are taken from the register (the identifier is regional but is
    assigned to the city).
    """
    geo = GeoPoint(lat=lat, lon=lon) if lat is not None and lon is not None else None
    return CanonicalRecord(
        city_slug=slug,
        geo=geo,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.SMARD,
        license_id=LicenseId.CC_BY_4_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Bundesnetzagentur | SMARD.de",
            license_url=_CC_BY_4_0_URL,
            modified=False,
        ),
        payload=PowerPayload(
            measure=measure,
            value=raw.get("value"),
            unit=unit,
            region=raw.get("region"),
            series_date=raw.get("series_date"),
        ),
    )
