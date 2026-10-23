"""Pure PVGIS Solar Mapper map_solar (DATA-38, GOV-03).

Deterministically translates the flat PVGIS-raw-dict into a ``CanonicalRecord``
with ``SolarPayload``. The function is pure: no HTTP, no logging, no
``datetime.now()`` (the ``retrieved_at`` timestamp is injected as a keyword-only parameter,
so that tests remain deterministic).

``observed_at`` is intentionally set to ``None``: PVGIS provides a climatological
multi-year average, not a specific measurement time; the reference period is specified as
``period_start``/``period_end`` in the payload (record_id thus falls back to
``retrieved_at``, ARCH-02).

CRITICAL (GOV-03): PVGIS data is processed (cityscape normalized to 1 kWp at
optimal angle and reshapes the schema), so the attribution includes
``modified=True`` and the exact PVGIS note. The license and tier are
hard-coded: EU Reuse Policy (EC_REUSE, effectively CC BY 4.0, freely usable with
attribution) = Tier A.
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    GeoPoint,
    LicenseId,
    LicenseTier,
    SolarPayload,
    SourceId,
)

_PVGIS_URL = (
    "https://joint-research-centre.ec.europa.eu/"
    "photovoltaic-geographical-information-system-pvgis_en"
)


def map_solar(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps raw PVGIS solar metrics to a ``CanonicalRecord``.

    ``retrieved_at`` is injected (no ``datetime.now()`` in the mapper) so that the
    result remains deterministic and fully testable. The join keys ``ags``/
    ``wikidata_qid`` are passed through from the register (default ``None``).
"""
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=GeoPoint(lat=raw["lat"], lon=raw["lon"]),
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.SOLAR,
        license_id=LicenseId.EC_REUSE,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="PVGIS © European Communities, 2001-2026",
            license_url=_PVGIS_URL,
            modified=True,
        ),
        payload=SolarPayload(
            annual_irradiation_kwh_m2=raw.get("annual_irradiation_kwh_m2"),
            annual_yield_kwh_kwp=raw.get("annual_yield_kwh_kwp"),
            optimal_slope_deg=raw.get("optimal_slope_deg"),
            optimal_azimuth_deg=raw.get("optimal_azimuth_deg"),
            peakpower_kwp=raw.get("peakpower_kwp"),
            system_loss_pct=raw.get("system_loss_pct"),
            total_performance_delta_pct=raw.get("total_performance_delta_pct"),
            radiation_db=raw.get("radiation_db"),
            period_start=raw.get("period_start"),
            period_end=raw.get("period_end"),
            monthly=raw.get("monthly") or [],
        ),
    )
