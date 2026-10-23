"""Reiner Accident Atlas Mapper `map_accidents` (traffic accidents, DL-DE/BY 2.0, Tier A).

Deterministically maps the annual aggregate from the SQLite reader (``archive.unfallatlas_db.
read_accidents``) to a ``CanonicalRecord`` with
``AccidentPayload``. Pure: no HTTP, no ``datetime.now()`` (injected).

License: DL-DE/BY 2.0; attribution must be verbatim: “Federal and
State Statistical Offices, Accident Atlas” (must appear verbatim in DATA-LICENSES.md + SOURCE_LICENSE
). ``observed_at``/``geo`` remain ``None`` (annual aggregate per district).
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    AccidentPayload,
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    SourceId,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"


def map_accidents(
    slug: str,
    row: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps an annual accident aggregate to a ``CanonicalRecord``.

    ``row`` is the dict returned by the SQLite reader (total/fatal/serious/light/
    with_*/reference_year/district_key). The ``retrieved_at`` timestamp is
    injected (no ``datetime.now()`` in the mapper). GOV-02/03: ``source=
    UNFALLATLAS``, ``license_id=DL_DE_BY_2_0``, Tier A.
    """
    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.UNFALLATLAS,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Statistische Ämter des Bundes und der Länder, Unfallatlas",
            license_url=_DL_DE_BY_URL,
        ),
        payload=AccidentPayload(
            reference_year=row.get("reference_year"),
            total=row.get("total"),
            fatal=row.get("fatal"),
            serious=row.get("serious"),
            light=row.get("light"),
            with_bicycle=row.get("with_bicycle"),
            with_pedestrian=row.get("with_pedestrian"),
            with_car=row.get("with_car"),
            with_motorcycle=row.get("with_motorcycle"),
            district_key=row.get("district_key"),
        ),
    )
