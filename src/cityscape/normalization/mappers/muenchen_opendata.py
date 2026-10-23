"""Pure Munich mapper map_muenchen_road_events (DATA-15, Tier A DL-DE/BY).

Deterministically translates the raw adapter dictionary (``slug``/``events``) into a
``CanonicalRecord`` with ``RoadEventPayload``. The function is pure: no HTTP,
no log calls, no system clock. The ``retrieved_at`` timestamp is
injected as a keyword-only field so that tests remain deterministic.

The roadwork data from the City of Munich (CKAN package
``baustellen_4_weeks_opendata`` on opendata.muenchen.de, GeoJSON via WFS on
geoportal.muenchen.de, [VERIFIED 2026-06-10]) are available under the
Germany Attribution 2.0 data license:
``license_id=DL_DE_BY_2_0``, ``license_tier=A`` (indicates the permissive
license for proper attribution and reuse, T-9-03) and the verbatim
attribution “City of Munich.” The individual events contain their time and
geometry in the payload, hence ``observed_at=None`` and ``geo=None``.
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    ParkingPayload,
    RoadEventPayload,
    SourceId,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"


def map_muenchen_road_events(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps raw Munich road events to a ``CanonicalRecord`` (Tier A).

    The ``events`` (construction sites/road closures, DATA-15) are passed unchanged into the
    ``RoadEventPayload`` (``city_source=“muenchen_baustellen”``). The
    ``retrieved_at`` timestamp is injected (no system clock in the mapper) so that
    the result remains deterministic. The join keys ``ags``/``wikidata_qid``
    are passed through from the register (default ``None``). Traffic events
    carry their own time and geometry per event, hence the deliberate use of ``observed_at=None`` and
    ``geo=None`` (no strict geometry validation, Pitfall 6).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.MUENCHEN_BAUSTELLEN,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Landeshauptstadt München",
            license_url=_DL_DE_BY_URL,
        ),
        payload=RoadEventPayload(
            city_source="muenchen_baustellen",
            events=raw.get("events", []),
        ),
    )


def map_muenchen_parking(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps the Munich parking garage location catalog to a ``CanonicalRecord``.

    The ``facilities`` (parking garage locations, DATA-40) are transferred unchanged to the
    ``ParkingPayload``. STATIC location catalog of the City of Munich
    (CKAN package ``parkhaeuser-munchen`` on opendata.muenchen.de, [VERIFIED
    2026-06-23]), NO live data. Data License Germany Attribution 2.0
    (``license_id=DL_DE_BY_2_0``, ``license_tier=A``), verbatim attribution
    “City of Munich”. Each location entry contains its own coordinates,
    hence ``observed_at=None`` and ``geo=None``. ``retrieved_at`` is injected
    (no system clock in the mapper) to ensure the result remains deterministic.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.MUENCHEN_PARKHAEUSER,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Landeshauptstadt München",
            license_url=_DL_DE_BY_URL,
        ),
        payload=ParkingPayload(
            facilities=raw.get("facilities", []),
        ),
    )
