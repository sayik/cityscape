"""Reiner Federal Hospital Atlas Mapper `map_hospital_atlas` (hospital locations).

Deterministically converts the flat `raw-dict` from `fetch_hospital_atlas` into
a `CanonicalRecord` with `HospitalAtlasPayload`. Pure: no HTTP, no
logging, no ``datetime.now()`` (``retrieved_at`` injected).

FAIL-CLOSED (License): The Federal Hospital Atlas has NO explicit open license
-> license_id UNKNOWN, Tier C (live-only, no archive), honestly tagged until
confirmation by BMG/IQTIG. CRITICAL (Pitfall 4): Filtered by proximity,
``distance_km`` per location; ``geo`` remains ``None``.
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    HospitalAtlasPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

_PROFILE_URL = "https://bundes-klinik-atlas.de/"


def map_hospital_atlas(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps raw Federal Clinic Atlas locations to a ``CanonicalRecord``.

    ``observed_at`` remains ``None`` (master data, no measurement time). License
    UNKNOWN/Tier C (fail-closed). Join keys from the register. ``geo=None``
    (Pitfall 4: near the location, not exact city).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.KLINIK_ATLAS,
        license_id=LicenseId.UNKNOWN,
        license_tier=LicenseTier.C,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Bundes-Klinik-Atlas (BMG/IQTIG)",
            license_url=_PROFILE_URL,
        ),
        payload=HospitalAtlasPayload(
            count=raw.get("count", 0),
            total_beds=raw.get("total_beds"),
            truncated=raw.get("truncated", False),
            hospitals=raw.get("hospitals", []),
        ),
    )
