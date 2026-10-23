"""Pure MaStR Energy Mapper `map_mastr_assets` (DATA-18, GOV-02/03).

Deterministically aggregates the lean asset dictionaries from the SQLite reader (`read_energy`)
into a `CanonicalRecord` with `EnergyAssetPayload`
(kind=energy_asset). The function is pure: no HTTP, no logging, no
``datetime.now()``. The ``retrieved_at`` timestamp is injected on a keyword-only basis
to ensure that tests remain deterministic.

CRITICAL (license classification GOV-02): MaStR energy assets are Tier A
(open license), ``source=SourceId.MASTR``, ``license_id=DL_DE_BY_2_0``,
``license_tier=A``. The
attribution MANDATORY requires the Federal Network Agency/Market Master Data Register, including the
DL-DE/BY-2.0 license URL (GOV-03).

``observed_at`` remains ``None`` (no measurement timestamp at the city level); ``geo``
remains ``None`` (the individual coordinates are listed in the ``assets`` dictionaries).
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    EnergyAssetPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

# DL-DE/BY 2.0 (Datenlizenz Deutschland Namensnennung 2.0, govdata.de).
_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"


def map_mastr_assets(
    slug: str,
    rows: list[dict],
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps the slim MaStR facility dictionaries to a ``CanonicalRecord``.

    ``rows`` are the slim facility dictionaries returned by the SQLite reader (one
    dict each containing ``unit_type``/``zip_code``/``lat``/``lon``/``power_kw``). The
    ``retrieved_at`` timestamp is injected (no ``datetime.now()`` in the
    mapper) to ensure the result remains deterministic. The join keys
    ``ags``/``wikidata_qid`` are passed through from the register (ARCH-02,
    default ``None``). ``geo`` remains ``None`` (city level); ``observed_at``
    remains ``None``.

    ``by_type`` counts the plants by type (pv/wind/storage/biogas). Empty
    ``rows`` are NOT an error (batch with no matches -> count 0).
"""
    by_type: dict[str, int] = {}
    # H7: leistung_kw je Anlage zur Stadt-Gesamtleistung (+ je Typ) aggregieren -
    # die wichtigste MaStR-Kennzahl. Nur echte Zahlen zählen; trägt keine Anlage
    # eine Leistung, bleibt total_power_kw None (ehrliche Null statt 0.0).
    power_by_type: dict[str, float] = {}
    total_power_kw = 0.0
    has_power = False
    for row in rows:
        typ = row.get("einheit_typ")
        if typ:
            by_type[typ] = by_type.get(typ, 0) + 1
        leistung = row.get("leistung_kw")
        if isinstance(leistung, (int, float)) and not isinstance(leistung, bool):
            has_power = True
            total_power_kw += leistung
            if typ:
                power_by_type[typ] = power_by_type.get(typ, 0.0) + leistung

    total_power = round(total_power_kw, 1) if has_power else None
    power_by_type = {t: round(p, 1) for t, p in power_by_type.items()}

    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.MASTR,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Bundesnetzagentur - Marktstammdatenregister",
            license_url=_DL_DE_BY_URL,
        ),
        payload=EnergyAssetPayload(
            count=len(rows),
            by_type=by_type,
            total_power_kw=total_power,
            power_by_type=power_by_type,
            assets=list(rows),
        ),
    )
