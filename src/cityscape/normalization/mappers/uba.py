"""Pure UBA Air Mapper map_air_uba (DATA-10, GOV-01/03, Tier A).

Deterministically translates the flat UBA-raw-dict into a ``CanonicalRecord``
using the REUSED ``AirQualityPayload`` (kind=air_quality, no new
AirPayload). The function is pure: no HTTP, no logging, no
``datetime.now()``. The ``retrieved_at`` timestamp is injected using keyword-only,
so that tests remain deterministic.

CRITICAL (License Classification GOV-02): UBA is Tier A (open license),
``license_id=DL_DE_BY_2_0``, ``license_tier=A``. The UBA record is delivered via the
route ``/air-uba`` (Tier A dataset).

CRITICAL (GOV-03): UBA data under the Germany Attribution 2.0 data license is
NOT processed (unlike DWD weather data); therefore, the attribution does NOT
include ``modified`` (default ``False``) and requires verbatim attribution of
“Umweltbundesamt”.
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    AirQualityPayload,
    Attribution,
    CanonicalRecord,
    GeoPoint,
    LicenseId,
    LicenseTier,
    SourceId,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"


def map_air_uba(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps raw UBA air data to a ``CanonicalRecord`` (Tier A).

    ``observed_at`` comes from the UBA measurement time (``raw[“observed_at”]``); the
    ``retrieved_at`` timestamp is injected (no ``datetime.now()`` in the
    mapper) so that the result remains deterministic. The join keys
    ``ags``/``wikidata_qid`` are passed through from the register (default
    ``None``). The payload uses the existing ``AirQualityPayload``; the
    UBA station ID serves as the business key for the ``record_id``
    (ARCH-02). The attribution does NOT include a ``modified`` field (DL-DE/BY, GOV-03).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=GeoPoint(lat=raw["lat"], lon=raw["lon"]),
        observed_at=raw.get("observed_at"),
        retrieved_at=retrieved_at,
        source=SourceId.UBA,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            # H15: verbatim wie source_specs + DATA-LICENSES.md ("(UBA)" war im
            # Mapper abgeschnitten -> Attribution-Drift gegen Doku/Registry).
            text="Umweltbundesamt (UBA)",
            license_url=_DL_DE_BY_URL,
        ),
        payload=AirQualityPayload(
            station_id=raw.get("station_id"),
            pm10=raw.get("pm10"),
            pm25=raw.get("pm25"),
            no2=raw.get("no2"),
            o3=raw.get("o3"),
            so2=raw.get("so2"),
        ),
    )
