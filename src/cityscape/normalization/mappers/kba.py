"""Pure KBA mapper `map_vehicle_registrations` (passenger car registry, DL-DE/BY 2.0, Tier A).

Deterministically maps the streamlined registration district row from the SQLite reader
(``archive.kba_db.read_vehicle_registrations``) to a
``CanonicalRecord`` with ``VehicleRegistrationPayload``. Clean: no HTTP, no
logging, no ``datetime.now()`` (``retrieved_at`` is injected).

The Federal Motor Transport Authority (KBA) only includes shares (percentages) in the dataset, not
absolute electric vehicle numbers; ``bev_estimated`` is derived here from ``pkw_total`` and
``bev_share`` (clearly marked as derived, ``modified=False``
for the unmodified source shares). License DL-DE/BY 2.0, Attribution
exactly as stated: “Federal Motor Transport Authority (KBA)” (must appear verbatim in DATA-LICENSES.md +
SOURCE_LICENSE).
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    SourceId,
    VehicleRegistrationPayload,
)

# DL-DE/BY 2.0 (Datenlizenz Deutschland Namensnennung 2.0, govdata.de).
_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"


def _bev_estimated(pkw_total: int | None, bev_share: float | None) -> int | None:
    """Derives the absolute BEV figure from the total fleet and the BEV share.

    Note (Audit 2026-06-29): Although the KBA layer contains “Pkw_BEV” absolute fields,
    these are consistently 0 or locked -> the calculation based on total fleet ×
    BEV share (bev_estimated) is the only reliable source; therefore, it is intentionally
    estimated rather than provided.

    Both values are required; otherwise, ``None`` (honest degradation, not 0). Round
    to the nearest whole number.
    """
    if pkw_total is None or bev_share is None:
        return None
    return round(pkw_total * bev_share / 100)


def map_vehicle_registrations(
    slug: str,
    row: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps a KBA registration district row to a ``CanonicalRecord``.

    ``row`` is the slim row returned by the SQLite reader (``pkw_total``/
    ``bev_share``/``electric_share``/``plugin_hybrid_share``/``district``/
    ``district_key``/``reference_period``). The ``retrieved_at`` timestamp is
    injected (no ``datetime.now()`` in the mapper) so that the result
    remains deterministic. The join keys ``ags``/``wikidata_qid`` are passed through from the
    register (default ``None``). ``geo`` remains ``None`` (district
    /city level); ``observed_at`` remains ``None`` (the reporting time is included in the
    payload).
    """
    pkw_total = row.get("pkw_total")
    bev_share = row.get("bev_share")
    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.KBA,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Kraftfahrt-Bundesamt (KBA)",
            license_url=_DL_DE_BY_URL,
            modified=False,
        ),
        payload=VehicleRegistrationPayload(
            pkw_total=pkw_total,
            electric_share=row.get("electric_share"),
            bev_share=bev_share,
            plugin_hybrid_share=row.get("plugin_hybrid_share"),
            bev_estimated=_bev_estimated(pkw_total, bev_share),
            district=row.get("district"),
            district_key=row.get("district_key"),
            reference_period=row.get("reference_period"),
        ),
    )
