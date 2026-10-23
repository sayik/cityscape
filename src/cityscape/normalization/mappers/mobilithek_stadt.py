"""Pure City Mobilithek Mappers (LIVE-08/12, Tier A DL-DE/BY, Phase 20).

Translates the raw adapter dictionaries from ``adapters/mobilithek_datex2.py``
(SituationPublication, ``events`) deterministically into a ``CanonicalRecord``:
- ``map_berlin_traffic_messages``: Berlin traffic reports (SenMVKU,
  SituationPublication) -> ``RoadEventPayload`` (``city_source=“berlin_senmvku”``),
  SourceId.BERLIN_VERKEHRSMELDUNGEN (LIVE-08).
- ``map_hannover_road_events``: Hanover traffic reports (City of Hanover, Department of
  Civil Engineering, SituationPublication) -> ``RoadEventPayload`` (``city_source=“hannover”``),
  SourceId.HANNOVER_VERKEHRSMELDUNGEN, Attribution “State Capital Hanover”.
- ``map_koeln_lez``: Cologne Low-Emission Zone (MoCKiii, SituationPublication) ->
  ``RoadEventPayload`` (``city_source=“koeln”``), SourceId.KOELN_LEZ_LIVE (LIVE-12).

Template is ``mappers/mobilithek_koeln.py`` (exact, Plan 04): direct (no HTTP,
no XML parsing, no system clock), ``retrieved_at`` injected as a keyword only
(deterministic). Both sources are licensed under the Germany
Attribution 2.0: ``license_id=DL_DE_BY_2_0``, ``license_tier=A`` (verified,
T-20-TIER: NO blanket Tier A across all sources, only these DL-DE/BY feeds).
Verbatim attribution in accordance with DATA-LICENSES.md (Berlin = SenMVKU, Cologne = City
of Cologne).

Pure live data -> ``geo=None`` (geo per event in the payload); ``observed_at`` from
the DATEX-II ``publicationTime`` (``as_of`) if available, otherwise ``None``
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    RoadEventPayload,
    SourceId,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"
_BERLIN_ATTRIBUTION = (
    "Senatsverwaltung für Mobilität, Verkehr, Klimaschutz und Umwelt (SenMVKU)"
)
_KOELN_ATTRIBUTION = "Stadt Köln"
_HANNOVER_ATTRIBUTION = "Landeshauptstadt Hannover"


def _parse_as_of(raw: dict) -> datetime | None:
    """Reads ``as_of`` (DATEX-II publicationTime) as an aware ``datetime`` or None.

    Pure (no system clock). An unparseable/missing value -> ``None``
    (honestly, not an error).
    """
    text = raw.get("as_of")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def map_berlin_traffic_messages(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps Berlin traffic reports (situation) to a ``CanonicalRecord``.

    The ``events`` (SenMVKU SituationPublication, LIVE-08) are mapped to the
    ``RoadEventPayload`` (``city_source=“berlin_senmvku”``). ``observed_at`` from
    the DATEX-II ``publicationTime`` (``as_of``), if available. ``retrieved_at``
    is injected (no system clock in the mapper). Tier A, DL-DE/BY 2.0, verbatim
    SenMVKU attribution (DATA-LICENSES.md).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.BERLIN_VERKEHRSMELDUNGEN,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_BERLIN_ATTRIBUTION,
            license_url=_DL_DE_BY_URL,
        ),
        payload=RoadEventPayload(
            city_source="berlin_senmvku",
            events=raw.get("events", []),
        ),
    )


def map_hannover_road_events(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps Hanover traffic reports (situation) to a ``CanonicalRecord``.

    The ``events`` (State Capital of Hanover, Civil Engineering Department:
    construction sites/traffic-related events/traffic disruptions,
    SituationPublication, BBox-filtered to Hannover) are transferred to the
    ``RoadEventPayload`` (``city_source=“hannover”``). ``observed_at`` from the
    DATEX-II ``publicationTime`` (``as_of``), if available. ``retrieved_at``
    is injected (no system clock in the mapper). The Mobilithek service is “free
    use/Open Data” = DL-DE/BY 2.0 (Tier A, similar to Bremen), attribution
    exactly as stated: “State Capital of Hanover” (DATA-LICENSES.md).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.HANNOVER_VERKEHRSMELDUNGEN,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_HANNOVER_ATTRIBUTION,
            license_url=_DL_DE_BY_URL,
        ),
        payload=RoadEventPayload(
            city_source="hannover",
            events=raw.get("events", []),
        ),
    )


def map_koeln_lez(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps the Cologne LowEmissionZone (situation) to a ``CanonicalRecord``.

    The ``events`` (MoCKiii SituationPublication, LIVE-12) are moved into the
    ``RoadEventPayload`` (``city_source=“koeln”``). ``observed_at`` from the
    DATEX-II ``publicationTime`` (``as_of``), if available. ``retrieved_at``
    is injected (no system clock in the mapper). Tier A, DL-DE/BY 2.0, Attribution
    “City of Cologne” (DATA-LICENSES.md).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.KOELN_LEZ_LIVE,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_KOELN_ATTRIBUTION,
            license_url=_DL_DE_BY_URL,
        ),
        payload=RoadEventPayload(
            city_source="koeln",
            events=raw.get("events", []),
        ),
    )
