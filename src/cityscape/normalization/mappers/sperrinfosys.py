"""Reiner SPERRINFOSYS Mapper ``map_sperrinfosys_road_events`` (Tier A DL-DE/BY).

Deterministically translates the raw adapter dictionary (``slug``/``events``) into a
``CanonicalRecord`` with ``RoadEventPayload`` (``city_source=“sperrinfosys”``).
Pure: no HTTP, no logging, no system clock (``retrieved_at`` injected).

The Saxony-wide road closures from SPERRINFOSYS (Free State of Saxony / LISt GmbH,
Mobilithek Offer -2102129055146091928, [VERIFIED 2026-07-02]) are subject to
the Germany Data License Attribution 2.0: ``license_id=DL_DE_BY_2_0``,
``license_tier=A``. The three-part attribution is VERBATIM-mandatory
(exactly the same wording in ``registry/source_specs.py`` and ``DATA-LICENSES.md``,
T-11-SRC-DRIFT): Attribution + License Link + Modification Notice.
``modified=True`` is REQUIRED: the coordinates were reprojected from EPSG:25833 to
WGS84 (modification notice per DL-DE/BY 2.0). The individual events
carry time and geometry in the payload, hence ``observed_at=None`` and
``geo=None``.
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


def map_sperrinfosys_road_events(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps raw SPERRINFOSYS road events to a ``CanonicalRecord``.

    The ``events`` (road closures, filtered by VKZ for each city) are passed unchanged into
    the ``RoadEventPayload`` (``city_source=“sperrinfosys”``). The
    ``retrieved_at`` timestamp is injected (no system clock in the mapper);
    ``ags``/``wikidata_qid`` are taken from the registry (default ``None``).
    ``attribution.modified=True`` because the coordinates were reprojected.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.SPERRINFOSYS,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Freistaat Sachsen / LISt GmbH (SPERRINFOSYS)",
            license_url=_DL_DE_BY_URL,
            modified=True,
        ),
        payload=RoadEventPayload(
            city_source="sperrinfosys",
            events=raw.get("events", []),
        ),
    )
