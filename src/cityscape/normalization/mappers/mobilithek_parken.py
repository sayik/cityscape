"""Pure Parking/Count Data Mobilithek Mapper (LIVE-09/10, Tier A, Phase 20).

Translates the raw adapter dictionaries from ``adapters/mobilithek_datex2.py``
deterministically into a ``CanonicalRecord``:
- ``map_dortmund_parking``: Dortmund dynamic parking guidance system
  (ParkingStatusPublication, ``facilities``) -> ``ParkingPayload``,
  SourceId.DORTMUND_PARKING (LIVE-09, closes the DATA-09 parking occupancy gap).
- ``map_kiel_counts``: Kiel motorized and bicycle traffic counting stations (MeasuredDataPublication,
  ``measurements``) -> ``CountStationPayload`` (``counts``),
  SourceId.KIEL_ZAEHLSTELLEN (LIVE-10).

Template is ``mappers/mobilithek_koeln.py`` (exact, Plan 04): pure (no HTTP,
no XML parsing, no system clock), ``retrieved_at`` injected as a keyword only
(deterministic). Both sources are licensed under the Germany
Attribution 2.0: ``license_id=DL_DE_BY_2_0``, ``license_tier=A`` (verified,
T-20-TIER: NO blanket Tier A across all sources, only these DL-DE/BY feeds).
Attribution: “City of Dortmund” or “State Capital of Kiel.”

Pure live data -> ``geo=None`` (the dynamic feed contains only ID references);
``observed_at`` from the DATEX-II ``publicationTime`` (``as_of``) if available,
otherwise ``None`` (honestly, no system clock).
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    CountStationPayload,
    LicenseId,
    LicenseTier,
    ParkingPayload,
    SourceId,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"
_FRANKFURT_ATTRIBUTION = "Stadt Frankfurt am Main"
_WUPPERTAL_ATTRIBUTION = "Stadt Wuppertal"
# Since June 13, 2026, Dortmund parking data has been sourced directly from the city’s keyless Opendatasoft
# feed (adapters/dortmund_parking, instead of Mobilithek). This dataset
# is licensed under the Germany Zero 2.0 Data License (verified in the dataset metadata) ->
# even more open than DL-DE/BY, and still Tier A. Kiel remains under DL-DE/BY (Mobilithek).
_DL_DE_ZERO_URL = "https://www.govdata.de/dl-de/zero-2-0"
_DORTMUND_ATTRIBUTION = "Stadt Dortmund"
_KIEL_ATTRIBUTION = "Landeshauptstadt Kiel"
# Magdeburg Parking (Mobilithek, ifak e.V.): The data source is the City of Magdeburg.
# Its Open Data Terms of Use (magdeburg.de/.../Offene-Verwaltungsdaten)
# specify, in the absence of other designation, the Germany Attribution 2.0 Data License
# (DL-DE/BY 2.0) -> Tier A. The vague “free use/Open Data” in the
# Mobilithek offering is merely ifak’s generic label; the
# data owner is the determining factor. Required source citation verbatim (note of change in case of
# modification; here modified=False, like the sister parking mapper). Research conducted on 2026-06-30.
_MAGDEBURG_ATTRIBUTION = "Datenquelle: Landeshauptstadt Magdeburg, www.magdeburg.de"


def _parse_as_of(raw: dict) -> datetime | None:
    """Liest ``as_of`` (DATEX-II publicationTime) als aware ``datetime`` oder None.

    Rein (keine Systemuhr). Ein nicht-parsebarer/fehlender Wert -> ``None``
    (ehrlich, kein Fehler).
    """
    text = raw.get("as_of")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def map_dortmund_parking(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps the Dortmund parking occupancy data (parking) to a ``CanonicalRecord``.

    The ``facilities`` (for each parking garage: facility_id + free/capacity/occupancy,
    LIVE-09) are moved to the ``ParkingPayload``. ``observed_at`` from the most recent
    ``timestamp`` (``as_of``), if available. ``retrieved_at`` is injected
    (no system clock in the mapper). Tier A, DL-DE Zero 2.0 (direct, keyless
    Opendatasoft feed from the City of Dortmund), attribution “City of Dortmund”.
    Closes the DATA-09 real-time parking occupancy gap.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.DORTMUND_PARKING,
        license_id=LicenseId.DL_DE_ZERO_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_DORTMUND_ATTRIBUTION,
            license_url=_DL_DE_ZERO_URL,
        ),
        payload=ParkingPayload(
            facilities=raw.get("facilities", []),
        ),
    )


def map_frankfurt_parking(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps the Frankfurt parking data (parking) to a ``CanonicalRecord``.

    The ``facilities`` (for each parking space: facility_id + free/occupancy/
    occupancy_graded/observed_at from the dynamic feed, enriched with
    name/lat/lon/capacity from the static counterpart, DATEX II V3 joined via the
    ``mobilithek_datex3`` adapter) are transferred to the ``ParkingPayload``.
    ``observed_at`` from the DATEX-II ``publicationTime`` (``as_of``) of the
    dynamic feed, if available. ``retrieved_at`` is injected (no
    system clock in the mapper). Tier A, DL-DE/BY 2.0 (verified by opendata.hessen.de
    on 2026-06-22, license_id dl-by-de/2.0), Attribution “City of Frankfurt am Main”.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.FRANKFURT_PARKING,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_FRANKFURT_ATTRIBUTION,
            license_url=_DL_DE_BY_URL,
        ),
        payload=ParkingPayload(
            facilities=raw.get("facilities", []),
        ),
    )


def map_wuppertal_parking(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps the Wuppertal parking data (parking) to a ``CanonicalRecord``.

    The ``facilities`` (for each parking space: facility_id + free/capacity/occupied/
    occupancy/status/trend/observed_at from the dynamic feed, enriched with
    name/lat/lon from the static counterpart, DATEX II V2 ParkingFacility profile
    joined in the ``mobilithek_datex2`` adapter) are transferred to the ``ParkingPayload``.
    ``observed_at`` from the DATEX-II ``publicationTime`` (``as_of``) of the
    dynamic feed, if available. ``retrieved_at`` is injected (no system clock
    in the mapper). Tier A, DL-DE/Zero 2.0 (mobilitaetsdaten.nrw / Mobilithek subscription
    license dl-zero-de/2.0 verified 2026-06-22), attribution “City of Wuppertal.”
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.WUPPERTAL_PARKING,
        license_id=LicenseId.DL_DE_ZERO_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_WUPPERTAL_ATTRIBUTION,
            license_url=_DL_DE_ZERO_URL,
        ),
        payload=ParkingPayload(
            facilities=raw.get("facilities", []),
        ),
    )


def map_magdeburg_parking(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps the Magdeburg parking data (parking) to a ``CanonicalRecord``.

    The ``facilities`` (for each parking space: facility_id + free/capacity/occupied/
    occupancy/status/trend/observed_at from the dynamic feed, enriched with
    name/lat/lon from the static counterpart, DATEX II V2 ParkingFacility profile
    joined in the ``mobilithek_datex2`` adapter) are transferred to the ``ParkingPayload``.
    ``observed_at`` from the DATEX-II ``publicationTime`` (``as_of``) of the
    dynamic feed, if available. ``retrieved_at`` is injected (no system clock
    in the mapper).

    License: The data source is the City of Magdeburg; in the absence of other designation, its Open Data
    terms of use specify the Germany Data License
    Attribution 2.0 -> ``license_id=DL_DE_BY_2_0``,
    ``license_tier=A`` (Research 2026-06-30: magdeburg.de Open Administrative Data,
    required source citation “Data source: State Capital Magdeburg,
    www.magdeburg.de”). The vague “free use/Open Data” description in the Mobilithek offering
    was merely ifak’s generic label, not the owner’s authoritative license.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.MAGDEBURG_PARKING,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_MAGDEBURG_ATTRIBUTION,
            license_url=_DL_DE_BY_URL,
        ),
        payload=ParkingPayload(
            facilities=raw.get("facilities", []),
        ),
    )


def map_kiel_counts(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps the Kiel measurement data (measured) to a ``CanonicalRecord``.

    The ``measurements`` (for each counting station: station_id + flow/speed, LIVE-10) are
    interpreted as ``counts`` in the ``CountStationPayload``. ``observed_at``
    from the DATEX-II ``publicationTime`` (``as_of``), if available.
    ``retrieved_at`` is injected (no system clock in the mapper). Tier A, DL-DE/BY 2.0,
    Attribution “Landeshauptstadt Kiel”.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.KIEL_ZAEHLSTELLEN,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_KIEL_ATTRIBUTION,
            license_url=_DL_DE_BY_URL,
        ),
        payload=CountStationPayload(
            counts=raw.get("measurements", []),
        ),
    )
