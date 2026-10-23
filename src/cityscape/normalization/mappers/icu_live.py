

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    IcuCapacityPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)


def map_icu_live(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    datum = raw.get("datum")
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.DIVI,
        license_id=LicenseId.UNKNOWN,
        license_tier=LicenseTier.C,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=(
                "DIVI-Intensivregister (klinikscharfe Live-Lage). Datenbank-"
                "Schutzrecht: keine offene Lizenz, ausschliesslich live "
                f"durchgeleitet. Stand: {datum}"
            ),
            license_url=None,
        ),
        payload=IcuCapacityPayload(
            kreis_id=raw.get("kreis_id"),
            kreis_name=raw.get("kreis_name"),
            beds_free=raw.get("beds_free"),
            beds_occupied=raw.get("beds_occupied"),
            hospitals=raw.get("hospitals") or [],
            datum=datum,
        ),
    )
