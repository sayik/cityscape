"""Reiner PEGELONLINE Water Level Mapper map_water_level (DATA-11, GOV-01/03, Tier A).

Deterministically translates the flat PEGELONLINE-raw-dict into a
``CanonicalRecord`` with ``WaterLevelPayload`` (kind=water_level). The function is
pure: no HTTP, no logging, no ``datetime.now()``. The ``retrieved_at``
timestamp is injected on a keyword-only basis so that tests remain deterministic.

CRITICAL (License Classification GOV-02): PEGELONLINE is Tier A (open license),
``license_id=DL_DE_ZERO_2_0``, ``license_tier=A``. The record is delivered via the route
``/water-level``, BUT only if a station was found
(Binnenstadt returns no_data).

CRITICAL (GOV-03): The Germany Zero 2.0 data license does NOT require
attribution; however, attribution is still provided (“PEGELONLINE / WSV”)
and does NOT include a ``modified`` attribute (data is not processed).
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    SourceId,
    WaterLevelPayload,
)

# Datenlizenz Deutschland Zero 2.0 (keine Namensnennungspflicht).
_DL_DE_ZERO_URL = "https://www.govdata.de/dl-de/zero-2-0"


def map_water_level(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps raw PEGELONLINE water level data to a ``CanonicalRecord``.

    ``observed_at`` comes from the measurement timestamp (``raw[“observed_at”]``); the
    ``retrieved_at`` timestamp is injected (no ``datetime.now()`` in the
    mapper) so that the result remains deterministic. The join keys
    ``ags``/``wikidata_qid`` are passed through from the register (default
    ``None``). ``geo`` remains ``None`` (city level, no station geo). The
    attribution contains NO ``modified`` (DL-DE/Zero, GOV-03).

    This function is called ONLY if a station was found; the
    no_data path (``raw[“station”] is None``) is already handled in the route.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=raw.get("observed_at"),
        retrieved_at=retrieved_at,
        source=SourceId.PEGELONLINE,
        license_id=LicenseId.DL_DE_ZERO_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            # H15: verbatim wie source_specs + DATA-LICENSES.md (Kurzform
            # "PEGELONLINE / WSV" war ein Attribution-Drift gegen Doku/Registry).
            text=(
                "PEGELONLINE, Wasserstraßen- und Schifffahrtsverwaltung "
                "des Bundes (WSV)"
            ),
            license_url=_DL_DE_ZERO_URL,
        ),
        payload=WaterLevelPayload(
            station=raw.get("station"),
            water=raw.get("water"),
            value=raw.get("value"),
            unit=raw.get("unit"),
        ),
    )
