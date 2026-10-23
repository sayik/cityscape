"""Mapper ``map_muenchen_radzaehl`` (DATA-40, Munich daily bicycle count data, Tier A).

Deterministically translates the raw adapter dictionary (``slug``/``stations``/``as_of``)
into a ``CanonicalRecord`` with ``CountStationPayload`` (canonical counting station
envelope, reused for all bike-counts sources). Pure: no HTTP, no
system clock (``retrieved_at`` injected as a keyword only).

LICENSE (GOV-01): City of Munich, Open Data Portal, Data License
Germany Attribution 2.0 (``DL_DE_BY_2_0`` -> Tier A), [VERIFIED 2026-06-23
via package_show license_id ``dl-by-de/2.0``]. Attribution with name credit."""

from __future__ import annotations

from datetime import UTC, datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    CountStationPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

# Attribution wortgenau wie in sources.SOURCE_LICENSE["muenchen_radzaehl"]
# (T-11-SRC-DRIFT): die DL-DE/BY-Namensnennung ist "Landeshauptstadt München".
_LICENSE_URL = "https://www.govdata.de/dl-de/by-2-0"
_ATTRIBUTION = "Landeshauptstadt München"


def _parse_datum(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.strptime(value, "%Y.%m.%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def _period(value: object) -> str | None:
    parsed = _parse_datum(value)
    return parsed.date().isoformat() if parsed else None


def _directions(station: dict) -> dict | None:
    out: dict[str, int | None] = {}
    for label_key, value_key in (
        ("direction_1", "direction_1_value"),
        ("direction_2", "direction_2_value"),
    ):
        label = station.get(label_key)
        if label:
            out[str(label)] = station.get(value_key)
    return out or None


def map_muenchen_radzaehl(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps raw Munich daily bike count values to a ``CanonicalRecord``.

    For each station, a simple count dictionary (``station``/``lat``/``lon``/``value`` =
    daily total/``granularity`` “day”/``period`` ISO day/``directions``) in the
    ``CountStationPayload``. ``observed_at`` is the most recent count day (``as_of``);
    ``geo=None`` (coordinates for each station in the payload). Tier A (DL-DE/BY 2.0).
    """
    counts: list[dict] = []
    for station in raw.get("stations", []):
        if not isinstance(station, dict):
            continue
        counts.append(
            {
                "station": station.get("zaehlstelle"),
                "station_id": station.get("zaehlstelle"),
                "name_long": station.get("name_long"),
                "lat": station.get("lat"),
                "lon": station.get("lon"),
                "value": station.get("value"),
                "vehicle_type": "bicycle",
                "granularity": "day",
                "period": _period(station.get("datum")),
                "directions": _directions(station),
            }
        )

    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_datum(raw.get("as_of")),
        retrieved_at=retrieved_at,
        source=SourceId.MUENCHEN_RADZAEHL,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_ATTRIBUTION,
            license_url=_LICENSE_URL,
        ),
        payload=CountStationPayload(counts=counts),
    )
