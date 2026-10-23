"""Mapper: VGN/VAG-Nuremberg Live Departures -> CanonicalRecord (DATA-25, Tier A).

Maps the raw dictionary of ``adapters.vgn.fetch_vgn_departures`` (stop + lean
departure dictionaries, including real-time forecasts) to the canonical envelope. Reuse
of ``TransitDeparturePayload`` (Phase 19, like HVV-Geofox), since the
format is identical: ``stop_id`` + ``departures``.

CRITICAL (GOV-02/03): Unlike HVV-Geofox, the VAG/VGN real-time API is
OPEN under Creative Commons Attribution 4.0 (opendata.vag.de) -> ``license_id =
CC_BY_4_0``, ``license_tier = A`` (cleanly usable, NOT Tier C). Pure live
display, NO archive. ``retrieved_at`` is injected (no system clock in the mapper);
``observed_at`` is derived from ``as_of`` (Metadata.Timestamp from the departure monitor).
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    SourceId,
)
from cityscape.normalization.payloads import TransitDeparturePayload

_VGN_ATTRIBUTION = "Verkehrs-Aktiengesellschaft Nürnberg (VAG) / VGN"
_CC_BY_URL = "https://creativecommons.org/licenses/by/4.0/"


def _parse_as_of(raw: dict) -> datetime | None:
    """``as_of`` (Metadata.Timestamp, ISO) as an aware datetime or None (raw)."""
    text = raw.get("as_of")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def map_vgn_departures(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
    city_slug: str = "nuernberg",
) -> CanonicalRecord:
    """Maps VGN Live departures to a ``CanonicalRecord`` (Tier A, CC-BY).

    The normalized ``departures`` (for each departure: line/direction/in_minutes/
    delay_s/alerts/product) are transferred to the ``TransitDeparturePayload``. Tier A
    (CC-BY 4.0, open), NO archive (live data only).
    """
    return CanonicalRecord(
        city_slug=city_slug,
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.VGN,
        license_id=LicenseId.CC_BY_4_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(text=_VGN_ATTRIBUTION, license_url=_CC_BY_URL),
        payload=TransitDeparturePayload(
            stop_id=raw.get("stop_id"),
            departures=raw.get("departures", []),
        ),
    )
