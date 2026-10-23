"""Pure eRound-AFIR Mapper (LIVE-11, CC0/Tier A, Phase 20).

Translates the raw adapter dictionary from ``adapters/mobilithek_afir.py``
(``points``, eRound AFIR Recharging, EnergyInfrastructureStatusPublication V3)
deterministically into a ``CanonicalRecord`` with ``ChargingStatusPayload`` and
SourceId.EROUND_CHARGING (LIVE-11, closes the DATA-09 charging allocation gap).

License (owner verification 2026-06-12, Checkpoint decision ``cc0-tier-a``): the
eRound offering (mobilithek.info/offers/961629419076456448, “Terms of Use” tab
) specifies **Creative Commons CC Zero**
(http://dcat-ap.de/def/licenses/cc-zero) as its default license -> ``license_id=CC0``,
``license_tier=A``. CC0 does not require attribution; however, project convention
consistently includes it (“Hamburger Energienetze GmbH / eRound”).

The template is ``mappers/mobilithek_parken.py`` (exactly): raw (no HTTP, no
parsing, no system clock), ``retrieved_at`` injected as a keyword-only field
(deterministically). Pure live data -> ``geo=None`` (the dynamic feed contains
only charging point IDs/statuses); ``observed_at`` from the DATEX-II ``publicationTime``
(``as_of``) if available, otherwise ``None`` (honestly, no system clock).
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    ChargingStatusCityPayload,
    ChargingStatusPayload,
    GeoPoint,
    LicenseId,
    LicenseTier,
    SourceId,
)

_CC0_URL = "http://dcat-ap.de/def/licenses/cc-zero"
_EROUND_ATTRIBUTION = "Hamburger Energienetze GmbH / eRound"


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


def map_eround_charging(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps the eRound charging station occupancy (points) to a ``CanonicalRecord``.

    The ``points`` (for each charging point: refill_point_id + status/observed_at, LIVE-11)
    are transferred to the ``ChargingStatusPayload``. ``observed_at`` from the DATEX-II
    ``publicationTime`` (``as_of``), if available. ``retrieved_at`` is injected
    (no system clock in the mapper). Tier A, CC0 (owner verification, checkpoint
    cc0-tier-a), attribution “Hamburger Energienetze GmbH / eRound”. Closes
    the DATA-09 real-time charging station occupancy gap.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.EROUND_CHARGING,
        license_id=LicenseId.CC0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_EROUND_ATTRIBUTION,
            license_url=_CC0_URL,
        ),
        payload=ChargingStatusPayload(
            points=raw.get("points", []),
        ),
    )


def _parse_observed_max(points: list[dict]) -> datetime | None:
    """The most recent ``observed_at`` of the reported points (or None, as is).

    ISO strings are lexically compared correctly only if they have a consistent format;
    therefore, they are parsed properly (using `fromisoformat`), and the maximum of the parseable values
    is taken. No parseable value -> ``None`` (honestly).
    """
    best: datetime | None = None
    for point in points:
        text = point.get("observed_at")
        if not text:
            continue
        try:
            value = datetime.fromisoformat(str(text))
        except (ValueError, TypeError):
            continue
        if best is None or value > best:
            best = value
    return best


def map_city_charging_status(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
    geo: GeoPoint | None = None,
) -> CanonicalRecord:
    """Maps the aggregated city charging occupancy (DATA-42) to a single record.

    ``raw`` is the join of Geo-Map and Redis-State (built from the route):
    ``slug``, ``total_points``, ``reported_points``, ``status_counts``,
    ``points`` (capped) + ``truncated``. ``observed_at`` is the most recent
    ``observed_at`` of the reported points (genuine feed freshness, not
    the system clock). License/attribution identical to ``map_eround_charging``
    (CC0/Tier A, eRound). ``geo`` is the city center from the register.
    """
    points = raw.get("points", [])
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=geo,
        observed_at=_parse_observed_max(points),
        retrieved_at=retrieved_at,
        source=SourceId.EROUND_CHARGING,
        license_id=LicenseId.CC0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_EROUND_ATTRIBUTION,
            license_url=_CC0_URL,
        ),
        payload=ChargingStatusCityPayload(
            total_points=raw.get("total_points", 0),
            reported_points=raw.get("reported_points", 0),
            status_counts=raw.get("status_counts", {}),
            points=points,
            truncated=raw.get("truncated", False),
        ),
    )
