"""Multi-city compare (API-05): fan out ONE resource across multiple cities.

D-06: one endpoint delivers one resource across multiple cities in ONE response;
per city a ``source_status`` (ok/disabled/no_data/error/not_found). A missing
or dead city source produces NO overall 5xx (per-city graceful degradation):
fan-out runs via ``asyncio.gather`` against the resilient facade
(``request.app.state.resilient_client.fetch``), which never blocks and raises no
unmapped upstream errors.

Security: ``resource`` is validated against ``RESOURCE_MAP`` (unknown -> 400
ValidationFailedError BEFORE raw user string reaches cache key/fetch,
T-11-FILTER-INJ). The ``cities`` list is capped at ``_MAX_CITIES``
(T-11-CMP-DOS); slugs are validated by ``get_city`` (build_cache_key only from
validated registry slug). The route is rate-limited (@limiter.limit).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from asgi_correlation_id import correlation_id
from fastapi import APIRouter, Depends, Request, Response

from cityscape.adapters.dwd import fetch_weather
from cityscape.adapters.uba import fetch_air_uba
from cityscape.api.errors import NotFoundError, ValidationFailedError
from cityscape.api.v1.pagination import PageParams, page_params, paginate
from cityscape.api.v1.ratelimit import ANON_LIMIT, limiter
from cityscape.config import Settings
from cityscape.infra.cache import build_cache_key
from cityscape.normalization.mappers.dwd import map_weather
from cityscape.normalization.mappers.uba import map_air_uba
from cityscape.registry import get_city

router = APIRouter()

# Resource -> (source, fetch_fn, mapper, toggle). Additively extensible (analogous
# to CONNECTOR_MAP in cities.py). The keys define allowed resource
# values (allowlist, T-11-FILTER-INJ); a value outside -> 400. Exactly the
# existing adapters/mappers registered here are reused (no new
# sources): "weather" -> DWD (keyless), "air" -> UBA (Tier A air path).
RESOURCE_MAP: dict[str, tuple] = {
    "weather": ("dwd", fetch_weather, map_weather, "enable_dwd"),
    "air": ("uba", fetch_air_uba, map_air_uba, "enable_uba"),
}


def _delegated_resources() -> dict:
    """Resource -> existing city route handler (compare expansion 2026-07-04).

    Second branch alongside RESOURCE_MAP: instead of an adapter fetch, the
    EXISTING route handler is invoked per city (identical behavior
    incl. toggles, fallbacks, no_data/not_ingested and attribution; no
    logic duplicates). Only cheap candidates are listed: store reads
    (indicators), cached sources (GENESIS regio, DWD warnings: ONE
    nationwide fetch for all cities), and Redis join
    (charging-status). INTENTIONALLY EXCLUDED: fuel-prices (Tankerkoenig ToS
    demands on-demand without cache, a 28-city fan-out per request would be
    a ToS/limit risk).

    Lazy function instead of module constant: cities.py imports heavy
    adapter dependencies on load; local import avoids import cycles via
    api.v1.__init__ and keeps module load time of compare.py small.
    """
    from cityscape.api.v1 import cities as city_routes

    return {
        "indicators": city_routes.city_indicators,
        "demographics": city_routes.city_demographics,
        "unemployment": city_routes.city_unemployment,
        "tourism": city_routes.city_tourism,
        "charging-status": city_routes.city_charging_status,
        "weather-warnings": city_routes.city_weather_warnings,
    }


# Upper limit for number of compared cities (T-11-CMP-DOS): bounds fan-out
# independent of registry size, preventing a long cities string from
# triggering arbitrarily many parallel upstream calls.
_MAX_CITIES = 28

# Allowlist of sortable fields for compare list (T-11-FILTER-INJ).
_COMPARE_SORT_WHITELIST = {"city", "source_status"}


async def _one(slug: str, request: Request, resource: str) -> dict:
    """Fetches a resource for ONE city; degrades per-city gracefully (D-06).

    NEVER raises into the fan-out: unknown slug -> ``not_found``, toggle off
    -> ``disabled``, dead upstream without cache (raw is None) -> ``error``, empty
    response -> ``no_data``, else mapper -> ``ok``. Each branch carries its
    own ``source_status``; no branch results in an overall 5xx.
    """
    source, fetch_fn_adapter, mapper, toggle = RESOURCE_MAP[resource]

    # Unknown slug -> per-city not_found as partial result (D-06: no 404 for
    # entire compare response, one bad city does not spoil the batch).
    try:
        entry = get_city(slug)
    except NotFoundError:
        return {"city": slug, "data": None, "source_status": "not_found"}

    # Freshly read source toggle (Settings() instead of app.state.settings so that
    # per-test env override takes effect). DATA-06: disabled -> disabled.
    if not getattr(Settings(), toggle):
        return {"city": entry.slug, "data": None, "source_status": "disabled"}

    client = request.app.state.resilient_client
    key = build_cache_key(source, city_slug=entry.slug)

    async def fetch_fn():
        return await fetch_fn_adapter(
            request.app.state.http,
            slug=entry.slug,
            lat=entry.geo.lat,
            lon=entry.geo.lon,
        )

    # D-06: fan-out NEVER raises. Facade already catches httpx errors/breaker open
    # (-> (None, STALE-ON-ERROR)); any error penetrating beyond that
    # (e.g. adapter/mapper defect of an individual city) is additionally degraded
    # here to per-city "error" so a broken city does not spoil the entire compare
    # response with 5xx.
    try:
        raw, status = await client.fetch(source, key, fetch_fn)
    except Exception:  # noqa: BLE001 - silently degrade per city (D-06)
        return {"city": entry.slug, "data": None, "source_status": "error"}

    # Dead upstream without cache -> per-city error (NO raise, D-06).
    if raw is None:
        return {"city": entry.slug, "data": None, "source_status": "error"}

    # Source reachable, but no payload -> honest no_data.
    if not raw:
        return {"city": entry.slug, "data": None, "source_status": "no_data"}

    try:
        record = mapper(
            raw, retrieved_at=datetime.now(UTC), ags=entry.ags, wikidata_qid=entry.qid
        )
    except Exception:  # noqa: BLE001 - defective record for a city -> error (D-06)
        return {"city": entry.slug, "data": None, "source_status": "error"}

    return {
        "city": entry.slug,
        "data": record.model_dump(mode="json"),
        "source_status": "ok",
        "cache_status": status,
    }


async def _one_delegated(slug: str, request: Request, resource: str) -> dict:
    """Fetches a delegated resource for ONE city via route handler.

    Same D-06 contract as ``_one``: unknown slug -> ``not_found``,
    ANY handler error (incl. UpstreamError 503 of single endpoint) is
    degraded to per-city ``error``, never to an overall 5xx.
    ``source_status`` of handler envelope (ok/disabled/no_data/
    not_ingested/...) is passed through unchanged, ``cache_status``/
    ``fallback`` as well.

    Special case charging-status: single point list (up to 500 per city)
    is omitted in compare (``points_omitted`` marker instead of list),
    otherwise a 28-city response would grow to megabytes; for comparison
    the aggregates matter (total/reported/status_counts).
    """
    try:
        entry = get_city(slug)
    except NotFoundError:
        return {"city": slug, "data": None, "source_status": "not_found"}

    handler = _delegated_resources()[resource]
    try:
        envelope = await handler(entry.slug, request)
    except Exception:  # noqa: BLE001 - silently degrade per city (D-06)
        return {"city": entry.slug, "data": None, "source_status": "error"}

    data = envelope.get("data")
    meta = envelope.get("meta") or {}

    if resource == "charging-status" and isinstance(data, dict):
        payload = data.get("payload")
        if isinstance(payload, dict) and "points" in payload:
            payload = {k: v for k, v in payload.items() if k != "points"}
            payload["points_omitted"] = True
            data = {**data, "payload": payload}

    row = {
        "city": entry.slug,
        "data": data,
        "source_status": meta.get("source_status", "ok"),
    }
    if meta.get("cache_status") is not None:
        row["cache_status"] = meta["cache_status"]
    if meta.get("fallback"):
        row["fallback"] = meta["fallback"]
    return row


@router.get("/compare")
@limiter.limit(ANON_LIMIT)
async def compare(
    request: Request,
    response: Response,
    cities: str,
    resource: str,
    page: PageParams = Depends(page_params),  # noqa: B008 - FastAPI dependency idiom
) -> dict:
    """Fans out ``resource`` across multiple ``cities`` (API-05, D-06).

    ``cities`` is a comma-separated slug list; ``resource`` must be in
    ``RESOURCE_MAP`` (otherwise 400). Fan-out runs via ``asyncio.gather``
    across resilient facade; per city a ``source_status``, a
    missing/dead source produces NO overall 5xx. Result is paginatable
    (API-04, allowlist {city, source_status}).
    """
    # resource against allowlist (T-11-FILTER-INJ): unknown -> 400 BEFORE
    # raw value reaches cache key/fetch. Allowed are adapter
    # resources (RESOURCE_MAP) plus delegated route resources.
    delegated = _delegated_resources()
    if resource not in RESOURCE_MAP and resource not in delegated:
        raise ValidationFailedError(
            f"Unbekannte resource '{resource}'.",
            hint=f"Erlaubt: {', '.join(sorted([*RESOURCE_MAP, *delegated]))}.",
        )

    slugs = [s.strip() for s in cities.split(",") if s.strip()]
    if not slugs:
        raise ValidationFailedError(
            "Parameter 'cities' darf nicht leer sein.",
            hint="Beispiel: cities=berlin,koeln,hamburg.",
        )
    # Bound fan-out size (T-11-CMP-DOS).
    slugs = slugs[:_MAX_CITIES]

    if resource in delegated:
        results = await asyncio.gather(
            *[_one_delegated(s, request, resource) for s in slugs]
        )
    else:
        results = await asyncio.gather(*[_one(s, request, resource) for s in slugs])

    # Optional allowlist-protected sorting + pagination of compare list
    # (API-04): unknown sort -> 400, offset overflow -> empty 200 page.
    results = list(results)
    if page.sort:
        results.sort(
            key=lambda row: (row.get(page.sort) is None, row.get(page.sort)),
            reverse=(page.order == "desc"),
        )
    page_items = paginate(results, page, sort_whitelist=_COMPARE_SORT_WHITELIST)

    return {
        "data": page_items,
        "meta": {
            "resource": resource,
            "correlation_id": correlation_id.get(),
            "total": len(results),
        },
    }
