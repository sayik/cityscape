"""Pure Wikidata Master Data Mapper (CORE-02).

Deterministically translates raw Wikidata master data (a dict) into a
``CanonicalRecord`` with ``CityBaseDataPayload``. The function is pure: no
HTTP, no logging, no ``datetime.now()``. The ``retrieved_at`` timestamp
is injected using keyword-only assignment so that tests remain deterministic. This mapper
serves as the template for every subsequent source mapper starting in Phase 4.
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    CityBaseDataPayload,
    GeoPoint,
    LicenseId,
    LicenseTier,
    SourceId,
)

_CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"


def map_wikidata_city(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps raw Wikidata master data to a ``CanonicalRecord``.

    Master data is static, so ``observed_at`` is ``None``. The
    ``retrieved_at`` timestamp is injected (no ``datetime.now()`` in the
    mapper) so that the result remains deterministic and fully testable. The
    Join keys ``ags`` and ``wikidata_qid`` are passed through from the register
    (default ``None``, so that the mapper remains pure and testable without the register) and
    are thus incorporated into ``record_id``/``content_hash`` (ARCH-02). Master data has
    no measuring station, so there is no ``station_id``.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=GeoPoint(lat=raw["lat"], lon=raw["lon"]),
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.WIKIDATA,
        license_id=LicenseId.CC0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(text="Wikidata", license_url=_CC0_URL),
        payload=CityBaseDataPayload(
            population=raw.get("population"),
            area_km2=raw.get("area"),
        ),
    )
