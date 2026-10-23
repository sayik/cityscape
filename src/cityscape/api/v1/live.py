"""Separate live category /api/v1/live (LIVE-01/02/03, Phase 20).

Owner decision (LOCKED): all live/quasi-live endpoints receive a dedicated
namespace ``/api/v1/live/...`` with dedicated OpenAPI tag "Live" and an additively
extended envelope contract: the meta block additionally carries ``as_of``
(data timestamp, DATEX-II publicationTime) and ``refresh_seconds`` (source cadence),
without breaking the existing envelope.

Re-exporting existing endpoints (LIVE-03, REST rule 6 = single source of truth):
existing live/quasi-live handlers from ``cities.py`` (air, air-uba, water-level,
traffic, webcams, flood) are re-exported here as THIN alias wrappers under ``/live``.
NO handler body is duplicated: the wrappers invoke exactly the respective
``cities.py`` handler. Legacy paths in ``cities.py`` remain functional
(no breaking change, envelope contract stable) and additionally carry a
``Deprecation`` header and ``deprecated=True`` in OpenAPI.

Prefix ``/live`` and tag "Live" are set during ``include_router`` in
``__init__.py`` (analogous to cities.py), NOT here in the router.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from asgi_correlation_id import correlation_id
from fastapi import APIRouter, Request, Response

from cityscape.adapters.dortmund_parking import fetch_dortmund_parking
from cityscape.adapters.hamburg_verkehrslage import fetch_hamburg_verkehrslage
from cityscape.adapters.hvv_geofox import fetch_hvv_departures
from cityscape.adapters.mobilithek_datex2 import (
    fetch_datex2,
    fetch_magdeburg_parking,
    fetch_wuppertal_parking,
)
from cityscape.adapters.mobilithek_datex3 import fetch_frankfurt_parking
from cityscape.adapters.vgn import fetch_vgn_departures
from cityscape.api.errors import UpstreamError, ValidationFailedError
from cityscape.api.v1 import cities
from cityscape.charging.store import read_latest_delta
from cityscape.config import Settings
from cityscape.infra.cache import build_cache_key
from cityscape.normalization.enums import SourceId
from cityscape.normalization.mappers.gtfs_rt import (
    attribution_for_source,
    map_transit_departures,
    map_transit_route_status,
    map_transit_trip,
)
from cityscape.normalization.mappers.hamburg_verkehrslage import (
    map_hamburg_verkehrslage,
)
from cityscape.normalization.mappers.hvv_geofox import map_hvv_departures
from cityscape.normalization.mappers.mobilithek_afir import map_eround_charging
from cityscape.normalization.mappers.mobilithek_bremen import map_bremen_road_events
from cityscape.normalization.mappers.mobilithek_koeln import (
    map_koeln_road_events,
    map_koeln_traffic_flow,
)
from cityscape.normalization.mappers.mobilithek_parken import (
    map_dortmund_parking,
    map_frankfurt_parking,
    map_kiel_counts,
    map_magdeburg_parking,
    map_wuppertal_parking,
)
from cityscape.normalization.mappers.mobilithek_stadt import (
    map_berlin_traffic_messages,
    map_hannover_road_events,
    map_koeln_lez,
)
from cityscape.normalization.mappers.vgn import map_vgn_departures
from cityscape.registry import get_city
from cityscape.transit.interpolation import estimate_position
from cityscape.transit.resolver import stops_with_geo_for_trip
from cityscape.transit.store import (
    get_trip_update,
    read_rt_source,
    trips_for_route,
    trips_for_stop,
)

router = APIRouter()


def _live_meta(
    *,
    source_status: str,
    cache_status: str | None = None,
    as_of: str | None = None,
    refresh_seconds: int | None = None,
) -> dict:
    """Builds the live envelope meta block (RESEARCH Pattern 5).

    Mirrors existing meta block of each ``cities.py`` handler
    (``correlation_id`` + ``source_status`` [+ ``cache_status``]) and extends it
    ADDITIVELY with the two live indicators ``as_of`` (data timestamp) and
    ``refresh_seconds`` (source cadence). Both live keys are ALWAYS present
    (even on ``disabled``/``no_data``) to ensure live category contract stability;
    an unknown data timestamp is ``None`` (honest), not omitted.
    """
    meta: dict = {
        "correlation_id": correlation_id.get(),
        "source_status": source_status,
    }
    if cache_status is not None:
        meta["cache_status"] = cache_status
    # Live extension: ALWAYS report as_of/refresh_seconds (contract stability).
    meta["as_of"] = as_of
    meta["refresh_seconds"] = refresh_seconds
    return meta


# Cadence of Mobilithek live sources (CONTEXT: live_5min, minute-fresh).
_LIVE_REFRESH_SECONDS = 300

# Default subscription IDs of verified Cologne sources (CONTEXT 2026-06-12, HTTP 200).
# Used only if settings allowlist (``*_abo_id``) has no value
# (owner sets values in production from portal; SSRF allowlist preserved:
# value NEVER originates from user input, only from settings OR these constants).
_KOELN_TRAFFIC_FLOW_ABO_ID = "1000923418744061952"
_KOELN_BAUSTELLEN_ABO_ID = "1000922381824032768"


async def _live_mobilithek(
    *,
    city: str,
    request: Request,
    source: str,
    abo_id: str | None,
    publication: str,
    mapper,
    map_kwargs: dict | None = None,
) -> dict:
    """Common Cologne live route against Mobilithek mTLS pull (LIVE-06/07).

    Follows 1:1 the ``cities.py`` handler skeleton (graceful degradation), BUT for
    pure live data:
    - Register lookup first (T-20-PATH): unknown slug -> 404 (central handler).
    - Toggle check: ``enable_{source}`` False OR ``app.state.mobilithek_http`` None
      (no cert) OR ``abo_id`` missing -> 200 ``source_status="disabled"`` (never 5xx).
    - Resilient fetch via facade (``resilient_client.fetch``) with
      ``fetch_datex2`` as ``fetch_fn`` against the mTLS client.
    - Dead upstream without cache (``raw is None``) -> 503 with self-correcting hint.
    - Empty feed (422/no data) -> 200 ``source_status="no_data"`` WITHOUT mapper.
    - Else mapper + live envelope (``as_of`` from DATEX-II publicationTime,
      ``refresh_seconds`` = cadence).

    CRITICAL (T-20-ARCHIVE): live routes write NO archive - pure
    live data resides only in Redis cache (CONTEXT "Live DO NOT archive"). This
    is the intentional difference from ``cities.py`` handlers (code review gate).
    """
    entry = get_city(city)

    settings = Settings()
    mobilithek_http = getattr(request.app.state, "mobilithek_http", None)
    # disabled: toggle off OR no cert (mTLS client None) OR no subscription ID.
    if (
        not getattr(settings, f"enable_{source}", False)
        or mobilithek_http is None
        or not abo_id
    ):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="disabled",
                refresh_seconds=_LIVE_REFRESH_SECONDS,
            ),
        }

    client = request.app.state.resilient_client
    key = build_cache_key(source, city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_datex2(
            mobilithek_http,
            abo_id=abo_id,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
            publication=publication,
        )

    raw, status = await client.fetch(source, key, fetch_fn)

    # raw is None (dead upstream without cache) MUST be checked before mapper,
    # otherwise 500. 503 with self-correcting hint (DX-06).
    if raw is None:
        raise UpstreamError(
            f"Live-Quelle '{source}' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health für Quellen-Status.",
        )

    # Empty feed (422/no data) -> honest no_data (200) WITHOUT mapper.
    # Payload key per publication (additively extended with parking).
    if publication == "situation":
        payload_key = "events"
    elif publication == "parking":
        payload_key = "facilities"
    else:  # "measured"
        payload_key = "measurements"
    if not raw.get(payload_key):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="no_data",
                cache_status=status,
                as_of=raw.get("as_of"),
                refresh_seconds=_LIVE_REFRESH_SECONDS,
            ),
        }

    record = mapper(
        raw,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
        **(map_kwargs or {}),
    )
    # NO archive write for pure live data (T-20-ARCHIVE)! Only Redis cache
    # (via facade). This is the deliberate difference from cities.py.
    observed = (
        record.observed_at.isoformat() if record.observed_at else raw.get("as_of")
    )
    return {
        "data": record.model_dump(mode="json"),
        "meta": _live_meta(
            source_status="ok",
            cache_status=status,
            as_of=observed,
            refresh_seconds=_LIVE_REFRESH_SECONDS,
        ),
    }


@router.get("/{city}/traffic-flow")
async def live_traffic_flow(city: str, request: Request) -> dict:
    """Live traffic flow per city (Cologne MeasuredDataPublication, LIVE-06).

    Vertical live endpoint in dedicated category. Cologne is verified
    source (MeasuredDataPublication, minute-fresh); other cities carry no
    subscription entry -> ``disabled``. Graceful degradation + live envelope (``as_of`` +
    ``refresh_seconds``) via common ``_live_mobilithek`` helper. NO
    archive (pure live data, T-20-ARCHIVE).
    """
    settings = Settings()
    abo_id = settings.koeln_traffic_flow_abo_id or _KOELN_TRAFFIC_FLOW_ABO_ID
    return await _live_mobilithek(
        city=city,
        request=request,
        source=SourceId.KOELN_TRAFFIC_FLOW.value,
        abo_id=abo_id,
        publication="measured",
        mapper=map_koeln_traffic_flow,
    )


@router.get("/{city}/baustellen")
async def live_baustellen(city: str, request: Request) -> dict:
    """Live construction sites per city (SituationPublication, LIVE-07 / DATA-31).

    City-aware: Cologne (verified subscription) and Bremen (VMZ Bremen, DATA-31)
    are wired; each city carries its own subscription ID + SourceId + mapper
    (carrier-accurate attribution). An unwired city -> 200
    ``source_status="disabled"`` (no subscription). SituationPublication ->
    RoadEventPayload. NO archive (pure live data, T-20-ARCHIVE).
    """
    settings = Settings()
    if city == "bremen":
        # DATA-31: Bremen road events (VMZ Bremen). Own mapper (attribution
        # "Freie Hansestadt Bremen"), own subscription ID + SourceId/toggle.
        return await _live_mobilithek(
            city=city,
            request=request,
            source=SourceId.BREMEN_BAUSTELLEN.value,
            abo_id=settings.bremen_baustellen_abo_id,
            publication="situation",
            mapper=map_bremen_road_events,
        )
    abo_id = settings.koeln_baustellen_live_abo_id or _KOELN_BAUSTELLEN_ABO_ID
    return await _live_mobilithek(
        city=city,
        request=request,
        source=SourceId.KOELN_BAUSTELLEN_LIVE.value,
        abo_id=abo_id,
        publication="situation",
        mapper=map_koeln_road_events,
        map_kwargs={"source": SourceId.KOELN_BAUSTELLEN_LIVE},
    )


@router.get("/{city}/ereignisse")
async def live_ereignisse(city: str, request: Request) -> dict:
    """Live traffic events per city (Cologne SituationPublication, LIVE-07).

    Cologne traffic information/events. Subscription ID is added by owner
    from portal (settings allowlist ``koeln_ereignisse_live_abo_id``);
    until then the route honestly returns ``disabled`` (no default subscription,
    CONTEXT "still testing"). SituationPublication -> RoadEventPayload. NO archive
    (pure live data, T-20-ARCHIVE).
    """
    settings = Settings()
    return await _live_mobilithek(
        city=city,
        request=request,
        source=SourceId.KOELN_EREIGNISSE_LIVE.value,
        abo_id=settings.koeln_ereignisse_live_abo_id,
        publication="situation",
        mapper=map_koeln_road_events,
        map_kwargs={"source": SourceId.KOELN_EREIGNISSE_LIVE},
    )


@router.get("/berlin/verkehrsmeldungen")
async def live_berlin_verkehrsmeldungen(request: Request) -> dict:
    """Live traffic messages Berlin (SenMVKU SituationPublication, LIVE-08).

    Pure V2 SituationPublication source via same Plan 04 parser
    (``fetch_datex2`` publication="situation") + common
    ``_live_mobilithek`` helper; only the mapper (``map_berlin_traffic_messages``)
    is Berlin-specific. City slug fixed to ``berlin`` (source covers only Berlin).
    Subscription ID from settings allowlist (SSRF, T-20-SSRF). NO archive (pure
    live data, T-20-ARCHIVE).
    """
    settings = Settings()
    return await _live_mobilithek(
        city="berlin",
        request=request,
        source=SourceId.BERLIN_VERKEHRSMELDUNGEN.value,
        abo_id=settings.berlin_verkehrsmeldungen_abo_id,
        publication="situation",
        mapper=map_berlin_traffic_messages,
    )


@router.get("/hannover/verkehrsmeldungen")
async def live_hannover_verkehrsmeldungen(request: Request) -> dict:
    """Live traffic messages Hannover (LH Hannover SituationPublication, DATEX II V2).

    Pure V2 SituationPublication source (construction sites, traffic-relevant
    events, disruptions in strategic traffic network of city
    Hannover) via same Plan 04 parser (``fetch_datex2`` publication=
    "situation") + common ``_live_mobilithek`` helper; only mapper
    (``map_hannover_road_events``) is Hannover-specific. City slug fixed to
    ``hannover`` (source covers Hannover region, BBox filtered). Subscription ID from
    settings allowlist (SSRF, T-20-SSRF). License DL-DE/BY 2.0 (Tier A,
    Mobilithek offer "free use/open data", analogous to Bremen), attribution
    "Landeshauptstadt Hannover". NO archive (pure live data, T-20-ARCHIVE).
    """
    settings = Settings()
    return await _live_mobilithek(
        city="hannover",
        request=request,
        source=SourceId.HANNOVER_VERKEHRSMELDUNGEN.value,
        abo_id=settings.hannover_verkehrsmeldungen_abo_id,
        publication="situation",
        mapper=map_hannover_road_events,
    )


@router.get("/koeln/umweltzone")
async def live_koeln_umweltzone(request: Request) -> dict:
    """Live low emission zone Cologne (MoCKiii SituationPublication, LIVE-12).

    Completes Cologne source group. Pure V2 SituationPublication via
    Plan 04 parser + ``_live_mobilithek``; only mapper (``map_koeln_lez``) is
    LEZ-specific. City slug fixed to ``koeln``. Subscription ID from settings allowlist
    (SSRF, T-20-SSRF). NO archive (pure live data, T-20-ARCHIVE).
    """
    settings = Settings()
    return await _live_mobilithek(
        city="koeln",
        request=request,
        source=SourceId.KOELN_LEZ_LIVE.value,
        abo_id=settings.koeln_lez_live_abo_id,
        publication="situation",
        mapper=map_koeln_lez,
    )


@router.get("/dortmund/parking", deprecated=True)
async def live_dortmund_parking(request: Request, response: Response) -> dict:
    """Live parking occupancy Dortmund (DATA-09, Tier A, DIRECT keyless). DEPRECATED.

    DEPRECATED (DATA-40, dedup): superseded by unified parking endpoint
    ``GET /api/v1/cities/dortmund/parking`` (ONE endpoint for all parking cities with
    source fallback). This path remains backwards-compatible (unchanged
    envelope), but carries ``Deprecation``/``Link`` headers to successor.

    Direct, keyless access to open parking guidance system of City of Dortmund via
    Opendatasoft Explore API (``adapters/dortmund_parking``) instead of
    Mobilithek mTLS: NO cert, NO subscription needed (owner strategy 2026-06-13,
    direct provider API like HVV Geofox). Toggle ``enable_dortmund_parking`` off
    -> 200 ``source_status="disabled"`` (never 5xx). Resilient fetch via
    facade; empty feed -> ``no_data``; dead upstream without cache -> 503 with
    self-correcting hint. License DL-DE Zero 2.0 (Tier A). Closes the
    DATA-09 real-time parking occupancy gap. NO archive (pure live data,
    T-20-ARCHIVE) - only Redis cache via facade.
    """
    cities._mark_deprecated(response, "/api/v1/cities/dortmund/parking")
    entry = get_city("dortmund")
    settings = Settings()
    if not settings.enable_dortmund_parking:
        return {
            "data": None,
            "meta": _live_meta(
                source_status="disabled",
                refresh_seconds=_LIVE_REFRESH_SECONDS,
            ),
        }

    client = request.app.state.resilient_client
    key = build_cache_key("dortmund_parking", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_dortmund_parking(request.app.state.http)

    raw, status = await client.fetch("dortmund_parking", key, fetch_fn)

    if raw is None:
        raise UpstreamError(
            "Live-Quelle 'dortmund_parking' voruebergehend nicht erreichbar, "
            "kein gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health für Quellen-Status.",
        )

    if not raw.get("facilities"):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="no_data",
                cache_status=status,
                as_of=raw.get("as_of"),
                refresh_seconds=_LIVE_REFRESH_SECONDS,
            ),
        }

    record = map_dortmund_parking(
        raw,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    observed = (
        record.observed_at.isoformat() if record.observed_at else raw.get("as_of")
    )
    return {
        "data": record.model_dump(mode="json"),
        "meta": _live_meta(
            source_status="ok",
            cache_status=status,
            as_of=observed,
            refresh_seconds=_LIVE_REFRESH_SECONDS,
        ),
    }


@router.get("/kiel/zaehlstellen")
async def live_kiel_zaehlstellen(request: Request) -> dict:
    """Live count data Kiel (motor vehicle/bike counting stations, MeasuredDataPublication, LIVE-10).

    Kiel permanent counting stations via MeasuredData branch from Plan 04
    (``fetch_datex2`` publication="measured") + common
    ``_live_mobilithek`` helper; mapper (``map_kiel_counts``) interprets
    ``measurements`` as ``counts``. City slug fixed to ``kiel``. Subscription ID from
    settings allowlist (SSRF, T-20-SSRF). NO archive (pure live data,
    T-20-ARCHIVE).
    """
    settings = Settings()
    return await _live_mobilithek(
        city="kiel",
        request=request,
        source=SourceId.KIEL_ZAEHLSTELLEN.value,
        abo_id=settings.kiel_zaehlstellen_abo_id,
        publication="measured",
        mapper=map_kiel_counts,
    )


@router.get("/eround/charging")
async def live_eround_charging(request: Request) -> dict:
    """Live charging station occupancy eRound (AFIR DATEX-II V3, LIVE-11/DATA-42).

    Reads EXCLUSIVELY from Redis (GTFS-RT pattern, T-19-REQPARSE analogous):
    background poller (``charging/poller``) is the ONLY upstream
    puller and stores the latest delta pull result per tick as a snapshot
    (``charging/store.store_latest_delta``). Data updates are thus STRICTLY
    decoupled from request workers: no upstream call, no Redis write in
    request path (structurally eliminating last-write-wins race between route
    and poller - there is only one writer serialized via Redis lock).
    The eRound feed is a drain queue; a request pull would drain deltas away from poller.

    City slug fixed to ``koeln`` as anchor (eRound delivers nationwide
    locations; slug serves only for registry lookup). License CC0 -> Tier A
    (checkpoint cc0-tier-a). Toggle off / no cert / no subscription ID ->
    ``disabled`` (without cert the poller never runs either). Missing/empty/
    expired snapshot (TTL 900 s = 3 poll ticks) -> honest ``no_data``.
    NO archive (pure live data, T-20-ARCHIVE). Per-city aggregation:
    ``/cities/{slug}/charging-status``.
    """
    settings = Settings()
    city = "koeln"
    abo_id = settings.eround_charging_abo_id
    source = SourceId.EROUND_CHARGING.value

    entry = get_city(city)
    mobilithek_http = getattr(request.app.state, "mobilithek_http", None)
    # disabled: toggle off OR no cert (then poller doesn't run either)
    # OR no subscription ID. More honest than endless no_data.
    if (
        not getattr(settings, f"enable_{source}", False)
        or mobilithek_http is None
        or not abo_id
    ):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="disabled",
                refresh_seconds=_LIVE_REFRESH_SECONDS,
            ),
        }

    latest = await read_latest_delta(request.app.state.redis)

    # No snapshot (poller not yet run/TTL expired) OR empty
    # feed (422/no deltas in tick) -> honest no_data (200) WITHOUT mapper.
    if latest is None or not latest.get("points"):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="no_data",
                as_of=(latest or {}).get("as_of"),
                refresh_seconds=_LIVE_REFRESH_SECONDS,
            ),
        }

    record = map_eround_charging(
        {
            "slug": entry.slug,
            "points": latest["points"],
            "as_of": latest.get("as_of"),
        },
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    # NO archive write for pure live data (T-20-ARCHIVE)! Even with Tier A:
    # pure live occupancy is not archived (RESEARCH "Live DO NOT archive").
    observed = (
        record.observed_at.isoformat() if record.observed_at else latest.get("as_of")
    )
    return {
        "data": record.model_dump(mode="json"),
        "meta": _live_meta(
            source_status="ok",
            as_of=observed,
            refresh_seconds=_LIVE_REFRESH_SECONDS,
        ),
    }


@router.get("/frankfurt-am-main/parking")
async def live_frankfurt_parking(request: Request) -> dict:
    """Live parking occupancy Frankfurt am Main (DATEX-II V3, static+dynamic).

    Dedicated route (analogous to ``live_eround_charging``), because Frankfurt delivers
    DATEX-II **V3** as XML (dedicated parser ``fetch_frankfurt_parking`` separate from
    V2 path) AND joins two subscriptions: dynamic carries occupancy,
    static carries base data (name/geo/capacity). City slug fixed to
    ``frankfurt-am-main`` (source covers only Frankfurt). Both subscription IDs from
    settings allowlist (SSRF, T-20-SSRF). Container pull (pull test 2026-06-22:
    portal soap/datexv3 endpoint returns 405 on GET).

    Graceful degradation: toggle off OR no cert (mTLS client None) OR no
    dynamic subscription ID -> 200 ``source_status="disabled"`` (never 5xx). Empty feed
    (422/no occupancy) -> 200 ``no_data``. Dead upstream without cache -> 503 with
    self-correcting hint. License DL-DE/BY 2.0 (Tier A), attribution "Stadt
    Frankfurt am Main". NO archive (pure live data, T-20-ARCHIVE) - only
    Redis cache via facade.
    """
    settings = Settings()
    city = "frankfurt-am-main"
    abo_id = settings.frankfurt_parking_abo_id
    source = SourceId.FRANKFURT_PARKING.value

    entry = get_city(city)
    mobilithek_http = getattr(request.app.state, "mobilithek_http", None)
    # disabled: toggle off OR no cert (mTLS client None) OR no subscription ID.
    if (
        not getattr(settings, f"enable_{source}", False)
        or mobilithek_http is None
        or not abo_id
    ):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="disabled",
                refresh_seconds=_LIVE_REFRESH_SECONDS,
            ),
        }

    client = request.app.state.resilient_client
    key = build_cache_key(source, city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_frankfurt_parking(
            mobilithek_http,
            abo_id=abo_id,
            static_abo_id=settings.frankfurt_parking_static_abo_id,
            slug=entry.slug,
        )

    raw, status = await client.fetch(source, key, fetch_fn)

    # raw is None (dead upstream without cache) MUST be checked before mapper.
    if raw is None:
        raise UpstreamError(
            f"Live-Quelle '{source}' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health für Quellen-Status.",
        )

    # Empty feed (422/no data) -> honest no_data (200) WITHOUT mapper.
    if not raw.get("facilities"):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="no_data",
                cache_status=status,
                as_of=raw.get("as_of"),
                refresh_seconds=_LIVE_REFRESH_SECONDS,
            ),
        }

    record = map_frankfurt_parking(
        raw,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    # NO archive write for pure live data (T-20-ARCHIVE)! Only Redis cache.
    observed = (
        record.observed_at.isoformat() if record.observed_at else raw.get("as_of")
    )
    return {
        "data": record.model_dump(mode="json"),
        "meta": _live_meta(
            source_status="ok",
            cache_status=status,
            as_of=observed,
            refresh_seconds=_LIVE_REFRESH_SECONDS,
        ),
    }


@router.get("/wuppertal/parking")
async def live_wuppertal_parking(request: Request) -> dict:
    """Live parking occupancy Wuppertal (DATEX-II V2 ParkingFacility, static+dynamic).

    Dedicated route (analogous to Frankfurt), because Wuppertal joins two subscriptions
    (dynamic occupancy + static base data) via DATEX-II V2 ParkingFacility profile
    (dedicated parser ``fetch_wuppertal_parking``, separate from Cologne parkingStatus
    path). City slug fixed to ``wuppertal``. Both subscription IDs from settings allowlist
    (SSRF, T-20-SSRF). Pull style "path" (pull test 2026-06-22).

    Graceful degradation: toggle off OR no cert OR no dynamic subscription ID
    -> 200 ``source_status="disabled"``. Empty feed -> 200 ``no_data``. Dead
    upstream without cache -> 503. License DL-DE/Zero 2.0 (Tier A), attribution "Stadt
    Wuppertal". NO archive (pure live data, T-20-ARCHIVE).
    """
    settings = Settings()
    city = "wuppertal"
    abo_id = settings.wuppertal_parking_abo_id
    source = SourceId.WUPPERTAL_PARKING.value

    entry = get_city(city)
    mobilithek_http = getattr(request.app.state, "mobilithek_http", None)
    if (
        not getattr(settings, f"enable_{source}", False)
        or mobilithek_http is None
        or not abo_id
    ):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="disabled",
                refresh_seconds=_LIVE_REFRESH_SECONDS,
            ),
        }

    client = request.app.state.resilient_client
    key = build_cache_key(source, city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_wuppertal_parking(
            mobilithek_http,
            abo_id=abo_id,
            static_abo_id=settings.wuppertal_parking_static_abo_id,
            slug=entry.slug,
        )

    raw, status = await client.fetch(source, key, fetch_fn)

    if raw is None:
        raise UpstreamError(
            f"Live-Quelle '{source}' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health für Quellen-Status.",
        )

    if not raw.get("facilities"):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="no_data",
                cache_status=status,
                as_of=raw.get("as_of"),
                refresh_seconds=_LIVE_REFRESH_SECONDS,
            ),
        }

    record = map_wuppertal_parking(
        raw,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    observed = (
        record.observed_at.isoformat() if record.observed_at else raw.get("as_of")
    )
    return {
        "data": record.model_dump(mode="json"),
        "meta": _live_meta(
            source_status="ok",
            cache_status=status,
            as_of=observed,
            refresh_seconds=_LIVE_REFRESH_SECONDS,
        ),
    }


@router.get("/magdeburg/parking")
async def live_magdeburg_parking(request: Request) -> dict:
    """Live parking occupancy Magdeburg (DATEX-II V2 ParkingFacility, static+dynamic).

    Dedicated route (analogous to Wuppertal), because Magdeburg joins two subscriptions
    (dynamic occupancy + static base data) via DATEX-II V2 ParkingFacility profile
    (provider ifak e.V.; shares ``fetch_magdeburg_parking``/Wuppertal V2 parser,
    but ``parkingFacilityOccupancy`` for Magdeburg is already a percentage). City slug
    fixed to ``magdeburg``. Both subscription IDs from settings allowlist (SSRF, T-20-SSRF).
    Pull style "path".

    Graceful degradation: toggle off OR no cert OR no dynamic subscription ID
    -> 200 ``source_status="disabled"``. Empty feed -> 200 ``no_data``. Dead
    upstream without cache -> 503. License Datenlizenz Deutschland Namensnennung 2.0
    (license_id dl_de_by_2_0, Tier A; data source Stadt Magdeburg, research
    2026-06-30), attribution "Datenquelle: Landeshauptstadt Magdeburg,
    www.magdeburg.de". NO archive (pure live data, T-20-ARCHIVE).
    """
    settings = Settings()
    city = "magdeburg"
    abo_id = settings.magdeburg_parking_abo_id
    source = SourceId.MAGDEBURG_PARKING.value

    entry = get_city(city)
    mobilithek_http = getattr(request.app.state, "mobilithek_http", None)
    if (
        not getattr(settings, f"enable_{source}", False)
        or mobilithek_http is None
        or not abo_id
    ):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="disabled",
                refresh_seconds=_LIVE_REFRESH_SECONDS,
            ),
        }

    client = request.app.state.resilient_client
    key = build_cache_key(source, city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_magdeburg_parking(
            mobilithek_http,
            abo_id=abo_id,
            static_abo_id=settings.magdeburg_parking_static_abo_id,
            slug=entry.slug,
        )

    raw, status = await client.fetch(source, key, fetch_fn)

    if raw is None:
        raise UpstreamError(
            f"Live-Quelle '{source}' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health für Quellen-Status.",
        )

    if not raw.get("facilities"):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="no_data",
                cache_status=status,
                as_of=raw.get("as_of"),
                refresh_seconds=_LIVE_REFRESH_SECONDS,
            ),
        }

    record = map_magdeburg_parking(
        raw,
        retrieved_at=datetime.now(UTC),
        ags=entry.ags,
        wikidata_qid=entry.qid,
    )
    observed = (
        record.observed_at.isoformat() if record.observed_at else raw.get("as_of")
    )
    return {
        "data": record.model_dump(mode="json"),
        "meta": _live_meta(
            source_status="ok",
            cache_status=status,
            as_of=observed,
            refresh_seconds=_LIVE_REFRESH_SECONDS,
        ),
    }


# Cadence of HVV Geofox live departures (minute-fresh).
_HVV_REFRESH_SECONDS = 60


@router.get("/hamburg/departures")
async def live_hamburg_departures(
    request: Request, station: str = "Hamburg Hauptbahnhof"
) -> dict:
    """Live public transit departures Hamburg per station (HVV Geofox GTI, DATA-24, Tier C).

    Real-time departure board incl. delays and line disruption notices from
    HVV Geofox GTI API. City fixed to ``hamburg`` (Geofox covers only HVV area).
    Query parameter ``station`` is a station name (default Hauptbahnhof),
    resolved by adapter via ``checkName`` to Geofox station ID.

    Graceful degradation: toggle off OR missing credentials (user/key) -> 200
    ``source_status="disabled"`` (never 5xx). Unknown station / no departures
    -> 200 ``source_status="no_data"``. Dead upstream without cache -> 503 with
    self-correcting hint. NO archive (Tier C live-only, T-20-ARCHIVE):
    credentials NEVER reach cache key (only station name) / response.
    """
    entry = get_city("hamburg")
    settings = Settings()
    key = settings.hvv_api_key
    # disabled: toggle off OR missing credential pair (analogous to city_demographics).
    if not settings.enable_hvv_geofox or not settings.hvv_user or key is None:
        return {
            "data": None,
            "meta": _live_meta(
                source_status="disabled",
                refresh_seconds=_HVV_REFRESH_SECONDS,
            ),
        }

    name = (station or "").strip()[:100]
    if not name:
        raise ValidationFailedError(
            "Parameter 'station' erforderlich.",
            hint="Einen HVV-Stationsnamen angeben, z. B. station=Hauptbahnhof.",
        )

    client = request.app.state.resilient_client
    # Cache key carries ONLY station name (T-08-CRED): never credentials.
    cache_key = build_cache_key(
        "hvv_geofox", city_slug=entry.slug, params={"station": name}
    )
    hvv_user = settings.hvv_user
    hvv_secret = key.get_secret_value()

    async def fetch_fn():
        return await fetch_hvv_departures(
            request.app.state.http,
            slug=entry.slug,
            station=name,
            user=hvv_user,
            key=hvv_secret,
            now=datetime.now(UTC),
        )

    raw, status = await client.fetch("hvv_geofox", cache_key, fetch_fn)

    # Dead upstream without cache -> 503 with self-correcting hint (DX-06).
    if raw is None:
        raise UpstreamError(
            "Live-Quelle 'hvv_geofox' voruebergehend nicht erreichbar, kein "
            "gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health für Quellen-Status.",
        )

    # Unknown station or no departures -> honest no_data (200) WITHOUT mapper.
    if not raw.get("departures"):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="no_data",
                cache_status=status,
                refresh_seconds=_HVV_REFRESH_SECONDS,
            ),
        }

    record = map_hvv_departures(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    # NO archive write (Tier C live-only, T-20-ARCHIVE)! Only Redis cache.
    return {
        "data": record.model_dump(mode="json"),
        "meta": _live_meta(
            source_status="ok",
            cache_status=status,
            as_of=record.observed_at.isoformat() if record.observed_at else None,
            refresh_seconds=_HVV_REFRESH_SECONDS,
        ),
    }


# --- Transit Live Routes (GTFS-RT, Phase 19, Tier B) -------------------------
#
# Request path reads ONLY from Redis (transit.store): background poller
# (transit/poller.py) parsed and indexed the 68 MB feed ONCE per cadence.
# NO 68 MB parse per request (T-19-REQPARSE). Cadence 45s (poller),
# NOT _LIVE_REFRESH_SECONDS=300 of DATEX sources.

# Poller cadence (CONTEXT: 30-60s; feed ~68 MB). Live routes report this as
# refresh_seconds so clients can align their polling cadence accordingly.
_TRANSIT_REFRESH_SECONDS = 45

# stop_id/route_id allowlist (T-19-CACHEPOISON): DELFI IDs follow pattern
# de:<AGS digits>:<rest>; gtfs.de Free feed uses purely NUMERIC stop_ids
# (verified live 2026-06-12: 150k+ index keys like transit_rt:idx:stop:27796).
# Both formats are permitted; ONLY validated values reach Redis keys
# (no raw user strings).
_STOP_ID_RE = re.compile(r"^(de:\d+:[\w:.\-]+|\d+)$")
_ID_RE = re.compile(r"^[\w:.\-]+$")


def _transit_disabled(settings) -> bool:
    """True if GTFS-RT toggle is off (-> source_status='disabled')."""
    return not getattr(settings, "enable_gtfs_rt", False)


def _service_day_epoch(now_epoch: int) -> int:
    """Midnight (UTC) of operating day of ``now_epoch`` as Unix epoch.

    Pure arithmetic (no system clock call): ``now_epoch`` is injected by
    handler. Serves as reference for GTFS scheduled times ("HH:MM:SS", >24h possible).
    """
    return now_epoch - (now_epoch % 86_400)


def _stop_time_update_for(update: dict, stop_id: str) -> dict | None:
    """Finds the stop_time_update of an update that serves ``stop_id``.

    Audit fix M-1: allows live departure to carry stop-accurate departure time and
    sequence. No match -> ``None`` (honest, not an error).
    """
    for stu in update.get("stop_time_updates", []) or []:
        if stu.get("stop_id") == stop_id:
            return stu
    return None


def _departure_delay(stu: dict | None, update: dict) -> int | None:
    """Returns delay (seconds) of a departure, honestly from stops.

    Audit fix K6: prefers stop-accurate value from stop_time_update
    (``departure_delay``, else ``arrival_delay``); if missing, effective trip delay
    ``delay_s`` derived during parsing; only lastly the trip level ``delay``
    (practically never set in real feeds).
    """
    if stu is not None:
        dep = stu.get("departure_delay")
        if dep is not None:
            return dep
        arr = stu.get("arrival_delay")
        if arr is not None:
            return arr
    eff = update.get("delay_s")
    if eff is not None:
        return eff
    return update.get("delay")


@router.get("/{city}/transit/departures")
async def live_transit_departures(
    city: str, request: Request, stop_id: str | None = None
) -> dict:
    """Live departures per stop with delay (GTFS-RT, TRANSIT-RT-03, Tier B).

    Reads ONLY from Redis (poller has parsed): ``trips_for_stop`` + per trip
    ``get_trip_update``. Empty list -> ``no_data``. ``stop_id`` must match
    DELFI pattern ``de:<digits>:...`` (allowlist, T-19-CACHEPOISON),
    otherwise 400. NO archive (Tier B, T-19-ARCHIVE), NO request parse.
    """
    entry = get_city(city)
    settings = Settings()
    if _transit_disabled(settings):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="disabled",
                refresh_seconds=_TRANSIT_REFRESH_SECONDS,
            ),
        }
    if not stop_id or not _STOP_ID_RE.match(stop_id):
        raise ValidationFailedError(
            "Ungueltige oder fehlende stop_id.",
            hint=(
                "Erwartet wird eine Halt-ID im DELFI-Muster 'de:<AGS>:<id>' "
                "oder eine numerische gtfs.de-Halt-ID."
            ),
        )

    redis = request.app.state.redis
    trip_ids = await trips_for_stop(redis, stop_id)
    departures: list[dict] = []
    for tid in trip_ids:
        update = await get_trip_update(redis, tid)
        if update is None:
            continue
        # Audit fix M-1: find stop_time_update matching THIS stop in order to
        # serve departure with departure_time/stop_sequence (and stop-accurate delay)
        # instead of just trip_id/route_id/delay_s.
        stu = _stop_time_update_for(update, stop_id)
        departures.append(
            {
                "trip_id": tid,
                "route_id": update.get("route_id"),
                # Audit fix K6: prefer stop-accurate delay from stop_time_update
                # (departure, else arrival), otherwise effective trip delay delay_s;
                # tu.delay only as last fallback.
                "delay_s": _departure_delay(stu, update),
                "departure_time": stu.get("departure_time") if stu else None,
                "stop_sequence": stu.get("stop_sequence") if stu else None,
            }
        )

    if not departures:
        return {
            "data": None,
            "meta": _live_meta(
                source_status="no_data",
                refresh_seconds=_TRANSIT_REFRESH_SECONDS,
            ),
        }

    record = map_transit_departures(
        {"stop_id": stop_id, "departures": departures},
        retrieved_at=datetime.now(UTC),
        city_slug=entry.slug,
        ags=entry.ags,
        wikidata_qid=entry.qid,
        source_attribution=attribution_for_source(await read_rt_source(redis)),
    )
    # NO archive write for pure live data (T-19-ARCHIVE, Tier B)! Only Redis.
    return {
        "data": record.model_dump(mode="json"),
        "meta": _live_meta(
            source_status="ok",
            as_of=record.observed_at.isoformat() if record.observed_at else None,
            refresh_seconds=_TRANSIT_REFRESH_SECONDS,
        ),
    }


@router.get("/{city}/transit/trips/{trip_id}")
async def live_transit_trip(city: str, trip_id: str, request: Request) -> dict:
    """Live trip detail incl. estimated position (GTFS-RT, TRANSIT-RT-04, Tier B).

    Reads update from Redis (``get_trip_update``); if missing -> ``no_data``.
    Static resolution (``stops_with_geo_for_trip`` against ``delfi_gtfs_path``) +
    ``estimate_position`` yield estimated position. now_epoch is MANDATORY
    the request time (``datetime.now(UTC).timestamp()`` determined and injected in
    handler, NOT the potentially stale update.timestamp). If static data is not
    resolvable -> ``unresolved=True`` (no 500, RESEARCH Pitfall 4). NO archive.
    """
    entry = get_city(city)
    settings = Settings()
    if _transit_disabled(settings):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="disabled",
                refresh_seconds=_TRANSIT_REFRESH_SECONDS,
            ),
        }
    if not _ID_RE.match(trip_id):
        raise ValidationFailedError(
            "Ungueltige trip_id.",
            hint="Die trip_id darf nur Wort-/Trennzeichen enthalten.",
        )

    redis = request.app.state.redis
    update = await get_trip_update(redis, trip_id)
    if update is None:
        return {
            "data": None,
            "meta": _live_meta(
                source_status="no_data",
                refresh_seconds=_TRANSIT_REFRESH_SECONDS,
            ),
        }

    # now_epoch MANDATORY the request time (plan requirement), determined in handler
    # and injected into pure core (estimate_position has no system clock).
    now_epoch = int(datetime.now(UTC).timestamp())
    estimated_position: dict | None = None
    unresolved = True
    # RT resolution against static data matching PROVENANCE (polish
    # 2026-06-15): if currently served by DELFI feed (mobilithek_delfi), DELFI
    # IDs are resolved against DELFI static (delfi_gtfs_path); on gtfs.de
    # backup against gtfs.de static (gtfs_rt_static_path). This ensures ID namespace
    # and static data always match (otherwise honestly unresolved instead of wrong position).
    used_source = await read_rt_source(redis)
    if used_source == "mobilithek_delfi":
        gtfs_path = getattr(settings, "delfi_gtfs_path", None) or getattr(
            settings, "gtfs_rt_static_path", None
        )
    else:
        gtfs_path = getattr(settings, "gtfs_rt_static_path", None) or getattr(
            settings, "delfi_gtfs_path", None
        )
    if gtfs_path:
        try:
            stops = stops_with_geo_for_trip(
                gtfs_path, trip_id, service_day_epoch=_service_day_epoch(now_epoch)
            )
            if stops:
                unresolved = False
                estimated_position = estimate_position(
                    stops,
                    # Audit fix K6: effective delay delay_s (from
                    # stop_time_update) instead of practically never set
                    # trip-level tu.delay; fallback to 0.
                    delay_s=update.get("delay_s")
                    if update.get("delay_s") is not None
                    else (update.get("delay") or 0),
                    now_epoch=now_epoch,
                )
        except (OSError, KeyError, ValueError):
            # Static data unreadable/incomplete -> honestly unresolved (no 500).
            unresolved = True

    record = map_transit_trip(
        {
            "trip_id": trip_id,
            "route_id": update.get("route_id"),
            # Audit fix K6: provide effective delay delay_s to mapper
            # (map_transit_trip reads "delay" -> Payload.delay_s), fallback tu.delay.
            "delay": update.get("delay_s")
            if update.get("delay_s") is not None
            else update.get("delay"),
            "timestamp": update.get("timestamp"),
            "stop_time_updates": update.get("stop_time_updates", []),
            "estimated_position": estimated_position,
            "unresolved": unresolved,
        },
        retrieved_at=datetime.now(UTC),
        city_slug=entry.slug,
        ags=entry.ags,
        wikidata_qid=entry.qid,
        source_attribution=attribution_for_source(used_source),
    )
    # NO archive write for pure live data (T-19-ARCHIVE, Tier B)! Only Redis.
    return {
        "data": record.model_dump(mode="json"),
        "meta": _live_meta(
            source_status="ok",
            as_of=record.observed_at.isoformat() if record.observed_at else None,
            refresh_seconds=_TRANSIT_REFRESH_SECONDS,
        ),
    }


@router.get("/{city}/transit/routes/{route_id}/status")
async def live_transit_route_status(city: str, route_id: str, request: Request) -> dict:
    """Live delay status of a transit line (GTFS-RT, TRANSIT-RT-05, Tier B).

    Aggregates active trips of a line from Redis (``trips_for_route`` +
    ``get_trip_update``): ``active_trips`` count, ``avg_delay_s``/``max_delay_s``
    across delays. Empty -> ``no_data``. NO request parse, NO archive.
    """
    entry = get_city(city)
    settings = Settings()
    if _transit_disabled(settings):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="disabled",
                refresh_seconds=_TRANSIT_REFRESH_SECONDS,
            ),
        }
    if not _ID_RE.match(route_id):
        raise ValidationFailedError(
            "Ungueltige route_id.",
            hint="Die route_id darf nur Wort-/Trennzeichen enthalten.",
        )

    redis = request.app.state.redis
    trip_ids = await trips_for_route(redis, route_id)
    delays: list[int] = []
    trips: list[dict] = []
    for tid in trip_ids:
        update = await get_trip_update(redis, tid)
        if update is None:
            continue
        # Audit fix K6: effective delay delay_s (from stop_time_update)
        # instead of practically never set trip level tu.delay; otherwise
        # avg/max_delay_s of each line was ALWAYS null.
        delay = update.get("delay_s")
        if delay is None:
            delay = update.get("delay")
        if delay is not None:
            delays.append(delay)
        trips.append({"trip_id": tid, "delay_s": delay})

    if not trips:
        return {
            "data": None,
            "meta": _live_meta(
                source_status="no_data",
                refresh_seconds=_TRANSIT_REFRESH_SECONDS,
            ),
        }

    avg_delay = round(sum(delays) / len(delays), 1) if delays else None
    max_delay = max(delays) if delays else None
    record = map_transit_route_status(
        {
            "route_id": route_id,
            "active_trips": len(trips),
            "avg_delay_s": avg_delay,
            "max_delay_s": max_delay,
            "trips": trips,
        },
        retrieved_at=datetime.now(UTC),
        city_slug=entry.slug,
        ags=entry.ags,
        wikidata_qid=entry.qid,
        source_attribution=attribution_for_source(await read_rt_source(redis)),
    )
    # NO archive write for pure live data (T-19-ARCHIVE, Tier B)! Only Redis.
    return {
        "data": record.model_dump(mode="json"),
        "meta": _live_meta(
            source_status="ok",
            as_of=record.observed_at.isoformat() if record.observed_at else None,
            refresh_seconds=_TRANSIT_REFRESH_SECONDS,
        ),
    }


# --- Re-exporting existing endpoints under /live (LIVE-03, REST rule 6) ------
#
# THIN alias wrappers: each invokes EXACTLY the existing cities.py handler
# (single source of truth, NO duplicated body, RESEARCH anti-pattern). The
# envelope contract is thus identical to legacy path by construction. Alias
# wrappers pass a DISPOSABLE response (``Response()``) to cities handler so that
# Deprecation header set by handler does NOT end up on /live response:
# the /live path is the successor, not the deprecated legacy path. Alias
# routes inherit prefix /live + tag "Live" from include_router.


@router.get("/{slug}/air")
async def live_air(slug: str, request: Request) -> dict:
    """Live alias for UBA air endpoint (LIVE-03)."""
    return await cities.city_air(slug, request, Response())


@router.get("/{slug}/air-uba")
async def live_air_uba(slug: str, request: Request) -> dict:
    """Live alias for UBA air endpoint (LIVE-03)."""
    return await cities.city_air_uba(slug, request, Response())


@router.get("/{slug}/water-level")
async def live_water_level(slug: str, request: Request) -> dict:
    """Live alias for PEGELONLINE water level endpoint (LIVE-03)."""
    return await cities.city_water_level(slug, request, Response())


@router.get("/{slug}/traffic")
async def live_traffic(slug: str, request: Request) -> dict:
    """Live alias for Autobahn traffic endpoint (LIVE-03)."""
    return await cities.city_traffic(slug, request, Response())


@router.get("/{slug}/webcams")
async def live_webcams(slug: str, request: Request) -> dict:
    """Live alias for Autobahn webcam endpoint (LIVE-03)."""
    return await cities.city_webcams(slug, request, Response())


@router.get("/{slug}/flood")
async def live_flood(slug: str, request: Request) -> dict:
    """Live alias for LHP flood endpoint (LIVE-03)."""
    return await cities.city_flood(slug, request, Response())


# Cadence of VGN live departures (minute-fresh).
_VGN_REFRESH_SECONDS = 60


@router.get("/nuernberg/departures")
async def live_nuernberg_departures(request: Request, stop_id: str = "510") -> dict:
    """Live public transit departures Nuremberg per stop (VGN/VAG Puls API, DATA-25, Tier A).

    Real-time departure board incl. delay from open, keyless VAG Puls API
    (CC-BY 4.0, Tier A). City fixed to ``nuernberg`` (VGN area). Query parameter
    ``stop_id`` is numeric VGN stop ID (VGNKennung; default 510 = Nuremberg
    Hbf), retrievable via ``/dm/api/haltestellen.json/vgn``.

    Graceful degradation: toggle off -> 200 ``source_status="disabled"`` (never 5xx).
    Invalid stop_id -> 400. No departures -> 200 ``source_status="no_data"``.
    Dead upstream without cache -> 503 with self-correcting hint. NO archive
    (pure live data, T-20-ARCHIVE) - only Redis cache via facade.
    """
    entry = get_city("nuernberg")
    settings = Settings()
    if not settings.enable_vgn:
        return {
            "data": None,
            "meta": _live_meta(
                source_status="disabled",
                refresh_seconds=_VGN_REFRESH_SECONDS,
            ),
        }

    sid = (stop_id or "").strip()
    if not sid.isdigit():
        raise ValidationFailedError(
            "Ungueltige oder fehlende stop_id.",
            hint=(
                "Erwartet wird die numerische VGN-Halt-ID (VGNKennung), z. B. "
                "stop_id=510 (Nürnberg Hbf)."
            ),
        )

    client = request.app.state.resilient_client
    cache_key = build_cache_key("vgn", city_slug=entry.slug, params={"stop_id": sid})

    async def fetch_fn():
        return await fetch_vgn_departures(request.app.state.http, stop_id=sid)

    raw, status = await client.fetch("vgn", cache_key, fetch_fn)

    if raw is None:
        raise UpstreamError(
            "Live-Quelle 'vgn' voruebergehend nicht erreichbar, kein gecachter "
            "Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health für Quellen-Status.",
        )

    if not raw.get("departures"):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="no_data",
                cache_status=status,
                as_of=raw.get("as_of"),
                refresh_seconds=_VGN_REFRESH_SECONDS,
            ),
        }

    record = map_vgn_departures(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    observed = (
        record.observed_at.isoformat() if record.observed_at else raw.get("as_of")
    )
    return {
        "data": record.model_dump(mode="json"),
        "meta": _live_meta(
            source_status="ok",
            cache_status=status,
            as_of=observed,
            refresh_seconds=_VGN_REFRESH_SECONDS,
        ),
    }


# Cadence of Hamburg traffic flow (5-minute snapshot of OAF source).
_VERKEHRSLAGE_REFRESH_SECONDS = 300


@router.get("/hamburg/verkehrslage")
async def live_hamburg_verkehrslage(request: Request) -> dict:
    """Live traffic flow Hamburg (DATA-26, Tier A, DIRECT keyless).

    Direct, keyless access to real-time traffic flow of Free and Hanseatic City of
    Hamburg via OGC API Features (``adapters/hamburg_verkehrslage``) instead of
    Mobilithek mTLS: NO cert, NO subscription (owner strategy, direct provider API).
    Response carries network summary (``summary.total`` +
    ``by_state`` counts per state class) and prioritized, capped list
    of non-flowing road segments (``measurements``). City fixed to
    ``hamburg`` (source covers only municipal area).

    Graceful degradation: toggle ``enable_hamburg_verkehrslage`` off -> 200
    ``source_status="disabled"`` (never 5xx). Resilient fetch via facade;
    empty feed (``summary.total`` == 0) -> ``no_data``; dead upstream without cache
    -> 503 with self-correcting hint. License DL-DE/BY 2.0 (Tier A). NO
    archive (pure live data, T-26-ARCHIVE) - only Redis cache via facade.
    """
    entry = get_city("hamburg")
    settings = Settings()
    if not settings.enable_hamburg_verkehrslage:
        return {
            "data": None,
            "meta": _live_meta(
                source_status="disabled",
                refresh_seconds=_VERKEHRSLAGE_REFRESH_SECONDS,
            ),
        }

    client = request.app.state.resilient_client
    key = build_cache_key("hamburg_verkehrslage", city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_hamburg_verkehrslage(request.app.state.http)

    raw, status = await client.fetch("hamburg_verkehrslage", key, fetch_fn)

    if raw is None:
        raise UpstreamError(
            "Live-Quelle 'hamburg_verkehrslage' voruebergehend nicht erreichbar, "
            "kein gecachter Wert vorhanden.",
            hint="Erneut versuchen oder GET /api/v1/health für Quellen-Status.",
        )

    # Empty feed -> honest no_data. A fully flowing condition (segments empty,
    # but summary populated) is NOT no_data, but a valid "ok".
    summary = raw.get("summary") or {}
    if not summary.get("total"):
        return {
            "data": None,
            "meta": _live_meta(
                source_status="no_data",
                cache_status=status,
                as_of=raw.get("as_of"),
                refresh_seconds=_VERKEHRSLAGE_REFRESH_SECONDS,
            ),
        }

    record = map_hamburg_verkehrslage(
        raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
    )
    observed = (
        record.observed_at.isoformat() if record.observed_at else raw.get("as_of")
    )
    return {
        "data": record.model_dump(mode="json"),
        "meta": _live_meta(
            source_status="ok",
            cache_status=status,
            as_of=observed,
            refresh_seconds=_VERKEHRSLAGE_REFRESH_SECONDS,
        ),
    }
