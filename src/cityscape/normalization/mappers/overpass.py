"""Pure Overpass POI Mapper (DATA-04, Tier B copyleft).

Translates raw Overpass elements (a dict with ``poi_type`` and ``elements``)
deterministically into a ``CanonicalRecord`` with ``PoiPayload``. The function is
pure: no HTTP, no logging, no ``datetime.now()``. The ``retrieved_at``
timestamp is injected as a keyword-only parameter so that tests remain deterministic.

OSM is licensed under the ODbL (Tier B copyleft): ``license_id=ODBL``,
``license_tier=B`` (indicates the copyleft license for proper attribution
and reuse) and the verbatim attribution
“© OpenStreetMap contributors”. POIs are
static, so ``observed_at=None``; ``geo`` is ``None`` (the individual POIs
carry their coordinates in the payload; no single city geo is required).
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    PoiPayload,
    SourceId,
)

_ODBL_URL = "https://opendatacommons.org/licenses/odbl/1-0/"


def _truncation(count: int, total_available: int | None) -> tuple[int | None, bool]:
    """Derive ``(total_available, truncated)`` for the payload (Audit K9).

    ``count`` is the number of items delivered (sample). ``total_available``
    is the actual total inventory according to the source (Overpass ``out count;``), or
    ``None``. ``truncated`` is True if the actual inventory is larger than the
    sample. If the total inventory is missing, ``total_available`` remains ``None``
    and ``truncated`` remains ``False`` (to be honest: no truncation is claimed without evidence).
    """
    if total_available is None:
        return None, False
    return total_available, total_available > count


def map_overpass_pois(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps raw Overpass POIs to a ``CanonicalRecord`` (Tier B).

    Each item is reduced to a slim dict (``name``/``lat``/``lon``)
    . ``count`` is always ``len(items)``. POIs are static, so
    ``observed_at`` is ``None``; the ``retrieved_at`` timestamp is injected
    (no ``datetime.now()`` in the mapper) to ensure the result remains deterministic
    . The join keys ``ags``/``wikidata_qid`` are passed through from the register
    (default ``None``); POIs do not have a point-stable measuring station,
    so there is NO ``station_id`` (``poi_type`` is the business key).
    """
    items = [
        {
            "name": element.get("tags", {}).get("name"),
            # node: lat/lon direkt; way/relation (out center): aus center.
            "lat": element.get("lat") or (element.get("center") or {}).get("lat"),
            "lon": element.get("lon") or (element.get("center") or {}).get("lon"),
        }
        for element in raw["elements"]
    ]
    total_available, truncated = _truncation(len(items), raw.get("total_available"))
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.OSM,
        license_id=LicenseId.ODBL,
        license_tier=LicenseTier.B,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="© OpenStreetMap contributors",
            license_url=_ODBL_URL,
        ),
        payload=PoiPayload(
            poi_type=raw["poi_type"],
            count=len(items),
            total_available=total_available,
            truncated=truncated,
            items=items,
        ),
    )


def map_osm_feature(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps a generic OSM feature data type to a ``CanonicalRecord``.

    Like ``map_overpass_pois``, but with additional OSM tag fields configured per feature
    (``raw[“extra_tags”]``, e.g., ``collection_times`` for a mailbox
    or ``opening_hours`` for a market). An extra tag is set only if the
    element carries it (no ``null`` noise). Clean, deterministic (no
    ``datetime.now()``), ODbL/Tier B like the POI mapper.
    """
    extra_tags = raw.get("extra_tags", [])
    items = []
    for element in raw["elements"]:
        tags = element.get("tags", {})
        item = {
            "name": tags.get("name"),
            # node: lat/lon direkt; way/relation (out center): aus center.
            "lat": element.get("lat") or (element.get("center") or {}).get("lat"),
            "lon": element.get("lon") or (element.get("center") or {}).get("lon"),
        }
        for tag in extra_tags:
            value = tags.get(tag)
            if value is not None:
                item[tag] = value
        items.append(item)
    total_available, truncated = _truncation(len(items), raw.get("total_available"))
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.OSM,
        license_id=LicenseId.ODBL,
        license_tier=LicenseTier.B,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="© OpenStreetMap contributors",
            license_url=_ODBL_URL,
        ),
        payload=PoiPayload(
            poi_type=raw["poi_type"],
            count=len(items),
            total_available=total_available,
            truncated=truncated,
            items=items,
        ),
    )
