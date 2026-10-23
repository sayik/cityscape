"""Per-station live boards ``/stations/{eva}/departures`` + ``/arrivals`` (DATA-36).

Unlike city-wide ``/cities/{slug}/station-departures`` (curated
metropolis main stations), these endpoints provide the live board of ANY arbitrary DB
station via its EVA number (from catalog ``/cities/{slug}/stations``),
including local transit (all train types ICE/IC/RE/RB/S) and disruptions/notices.
Source: DB Timetables (DB API Marketplace, CC BY 4.0 = Tier A), same adapter
as city-wide boards, just with exactly one EVA.

Security:
- T-05-08/T-12 (SSRF/Injection): ``eva`` is strictly validated as a 6-8 digit number
  BEFORE it enters the upstream URL (pure numeric path component;
  a non-numeric or too long value -> 422).
- T-08-CRED: Client-Id/Api-Key go ONLY into request headers (adapter), never into
  cache key/response/log.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from asgi_correlation_id import correlation_id
from fastapi import APIRouter, Request

from cityscape.adapters.db_timetables import (
    fetch_station_arrivals,
    fetch_station_departures,
)
from cityscape.api.errors import UnprocessableError, UpstreamError
from cityscape.config import Settings
from cityscape.infra.cache import build_cache_key
from cityscape.normalization.mappers.db_timetables import (
    map_station_arrivals,
    map_station_departures,
)

router = APIRouter()

# An EVA number (European Vehicle/Station number) is a pure number
# (German stations 7 digits, defensively 6-8). Strict validation = SSRF protection.
_EVA_RE = re.compile(r"^\d{6,8}$")


def _validate_eva(eva: str) -> str:
    """Validates EVA as 6-8 digit number (SSRF, T-12); 422 on violation."""
    if not _EVA_RE.match(eva):
        raise UnprocessableError(
            f"Ungueltige EVA-Nummer {eva!r}: erwartet eine 6-8-stellige Zahl.",
            hint="EVA-Nummern stehen im Katalog GET /api/v1/cities/{slug}/stations.",
        )
    return eva


async def _board(
    request: Request,
    *,
    eva: str,
    cache_prefix: str,
    fetch_fn_factory,
    mapper,
    empty_key: str,
) -> dict:
    """Common core for departure/arrival board of a single EVA.

    Three ``source_status``: ``disabled`` (toggle off/no keys), ``no_data``
    (station reachable, no trains in time window), ``ok`` (mapped payload).
    """
    eva = _validate_eva(eva)
    cid = correlation_id.get()
    settings = Settings()
    cid_secret = settings.db_client_id
    key = settings.db_api_key
    if (
        not settings.enable_db_timetables
        or cid_secret is None
        or key is None
        or not cid_secret.get_secret_value()
        or not key.get_secret_value()
    ):
        return {
            "data": None,
            "meta": {"correlation_id": cid, "source_status": "disabled"},
        }

    client = request.app.state.resilient_client
    cache_key = build_cache_key(cache_prefix, city_slug=f"eva-{eva}")
    client_id = cid_secret.get_secret_value()
    api_key = key.get_secret_value()

    async def fetch_fn():
        return await fetch_fn_factory(
            request.app.state.http,
            slug=eva,
            evas=(eva,),
            client_id=client_id,
            api_key=api_key,
            now=datetime.now(UTC),
        )

    raw, status = await client.fetch("db_timetables", cache_key, fetch_fn)
    if raw is None:
        raise UpstreamError(
            "Quelle 'db_timetables' voruebergehend nicht erreichbar, kein Cache.",
            hint="Erneut versuchen oder GET /api/v1/health fuer Quellen-Status.",
        )

    if not raw.get(empty_key):
        return {
            "data": None,
            "meta": {
                "correlation_id": cid,
                "source_status": "no_data",
                "cache_status": status,
            },
        }

    record = mapper(raw, retrieved_at=datetime.now(UTC))
    return {
        "data": record.model_dump(mode="json"),
        "meta": {
            "correlation_id": cid,
            "source_status": "ok",
            "cache_status": status,
        },
    }


@router.get("/{eva}/departures")
async def station_departures_by_eva(eva: str, request: Request) -> dict:
    """Live departures for any DB station (EVA) incl. local transit + disruptions.

    Next train departures at station with EVA number ``eva`` (all train types
    ICE/IC/RE/RB/S, real-time delays, disruptions/notices). EVA from catalog
    ``GET /api/v1/cities/{slug}/stations``. Source DB Timetables (CC BY 4.0).
    """
    return await _board(
        request,
        eva=eva,
        cache_prefix="db_timetables",
        fetch_fn_factory=fetch_station_departures,
        mapper=map_station_departures,
        empty_key="departures",
    )


@router.get("/{eva}/arrivals")
async def station_arrivals_by_eva(eva: str, request: Request) -> dict:
    """Live arrivals for any DB station (EVA) incl. local transit + disruptions.

    Mirror endpoint to ``station_departures_by_eva`` (``origin`` instead of ``destination``).
    Source DB Timetables (CC BY 4.0).
    """
    return await _board(
        request,
        eva=eva,
        cache_prefix="db_timetables_arr",
        fetch_fn_factory=fetch_station_arrivals,
        mapper=map_station_arrivals,
        empty_key="arrivals",
    )
