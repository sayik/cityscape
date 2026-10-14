"""httpx wrapper around the local cityscape live FastAPI (DX-05).

The MCP tools fetch their data through this wrapper, never directly from upstreams.
The ``get_resource`` function constructs the URL exclusively from the configured
base URL plus a fixed ``/cities/{slug}/{resource}`` schema and returns the
parsed JSON unchanged (no mapping/licensing logic, D-07/D-08).

Security:

- T-12-MCP-SSRF: The base URL originates exclusively from the env variable
  ``CITYSCAPE_MCP_API_BASE`` (default ``http://localhost:8000/api/v1``). Its host
  is checked against an allowlist; a non-allowlisted host is rejected with
  ``ValueError`` before any request is dispatched. An arbitrary URL from
  tool arguments is impossible.
- T-12-MCP-INJECT: ``resource`` is validated against the ``ALLOWED_RESOURCES``
  constant and ``slug`` is URL-quoted as a pure path component before the URL
  is built. An unknown ``resource`` or a slug containing path/host characters
  raises a ``ValueError`` before any request is dispatched.
"""

from __future__ import annotations

import asyncio
import os
import re
import weakref
from urllib.parse import quote, urlsplit

import httpx

from cityscape.config import get_settings

# Default base URL of local live API (loopback). Overridable via env,
# but only to an allowlisted host (see ALLOWED_HOSTS).
_DEFAULT_BASE_URL = "http://localhost:8000/api/v1"

# T-12-MCP-SSRF: Host allowlist. The list is deliberately kept narrow; a
# non-allowlisted host is rejected before a request is sent.
# - localhost/127.0.0.1/::1: local subprocess (stdio) against a local API.
# - api: internal compose service name. In remote operation (Phase 2), the
#   MCP container calls the API across the compose network (http://api:8000/api/v1), NOT
#   the public URL (otherwise all users share one IP -> rate limit).
ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
        "api",
    }
)

# Header with which the MCP server marks its internal API calls. The API
# MetricsMiddleware detects it, makes MCP actions visible in dashboard +
# triggers an ntfy push (Owner request: track MCP actions). Best-effort
# identifier, not an auth mechanism.
_MCP_SOURCE_HEADER = "X-cityscape-Mcp"

# T-12-MCP-INJECT: allowed resource names, exactly the city sub-resources from
# docs/openapi.yaml (GET /api/v1/cities/{slug}/<resource>). Raw tool input is
# validated against this constant before reaching the URL.
ALLOWED_RESOURCES: frozenset[str] = frozenset(
    {
        "base",
        # Single-call overview: base + catalog of all data types + live highlights.
        "overview",
        "air",
        "air-uba",
        "weather",
        "pois",
        "traffic",
        "transit",
        # DATA-40: unified parking garage endpoint per city (ParkenDD ~22 cities +
        # Munich fallback). Replaces the old, Frankfurt-specific /live/{slug}/parking
        # route; uncovered slugs -> 200 not_covered (not 404).
        "parking",
        "charging",
        # DATA-42: eRound live charging occupancy per city (join geo-map + delta state).
        "charging-status",
        "water-level",
        "flood",
        "pollen-uv",
        # DWD forest fire / grassland fire index per city (keyless, GeoNutzV, Tier A).
        "fire-danger",
        # EEA bathing water quality in radius (keyless, CC-BY 4.0, Tier A).
        "bathing-water",
        # Federal Hospital Atlas hospital locations (keyless; fail-closed Tier C,
        # disabled by default until BMG/IQTIG license confirmation).
        "hospitals-atlas",
        # DB FaSta elevator / escalator status (key-gated DB Marketplace, CC-BY,
        # Tier A; disabled without key).
        "station-facilities",
        "demographics",
        "energy",
        "geo",
        "election",
        "holidays",
        "health",
        "icu-live",
        "road-events",
        "events",
        "webcams",
        # SMARD/DWD (added earlier, matched in MCP allowlist).
        "power-load",
        "power-price",
        "weather-warnings",
        # Quick-260705-ufv: BBK NINA civil protection warnings per city (keyless,
        # ARS-based, Tier A, full coverage). Via get_city_resource.
        "civil-protection-warnings",
        # DATA-27/28/29: KBA + GENESIS trio + accident atlas (Tier A, district annual values).
        "vehicle-registrations",
        "unemployment",
        "tourism",
        "construction",
        "accidents",
        # PKS-01: BKA police crime statistics (Tier A, district annual values).
        "crime-stats",
        # DATA-30: Tankerkönig fuel prices (Tier A, aggregated per city).
        "fuel-prices",
        # DATA-33: GBFS bike/scooter sharing (Tier A, aggregated per city).
        "sharing",
        # DATA-38: PVGIS solar irradiance + normalized PV yield per city (Tier A).
        "solar",
        # DATA-39: Rooftop solar cadastre per city (NRW pilot, Tier A, partial coverage).
        "solar-roofs",
        # DATA-32: INKAR/BBSR socio-economic indicators per district (Tier A).
        "indicators",
        # DATA-35: BORIS official standard land values per city, aggregated (Tier A).
        "land-values",
        # DATA-37: Regionalstatistik.de property tax rates (municipality) +
        # business registrations/deregistrations (district), Tier A.
        "tax-rates",
        "business-registrations",
        # DATA-37: Regionalstatistik.de corporate insolvencies per district (52411-02
        # enterprises + 52411-03 other debtors), Tier A.
        "insolvencies",
        # DATA-34: DB Timetables station departures + arrivals for metropolitan central stations (Tier A).
        "station-departures",
        "station-arrivals",
        # DATA-36: StaDa station catalog per city (all stations with EVA, Tier A).
        "stations",
        # DATA-OSM (Tier 1): 10 dedicated OSM Overpass data types (ODbL, Tier B).
        "playgrounds",
        "drinking-water",
        "public-toilets",
        "markets",
        "parcel-lockers",
        "post-offices",
        "post-boxes",
        "public-wifi",
        "recycling-centres",
        "government-offices",
        "education",
        # DATA-OSM-Tier-2: Monument lists per federal state (state WFS, coverage-gated).
        "heritage",
        # DATA-OSM-Tier-2: Tree cadastre per city (municipal WFS, coverage-gated).
        "tree-cadastre",
        # DATA-OSM-Tier-2: Population density (Zensus 2022 100m grid, all cities).
        "population-density",
        # TENDER-05/06: Public procurement per city (oeffentlichevergabe.de,
        # OCDS, CC0/Tier A). Read-only from deduplicated store (Plan 21-04/05).
        "public-tenders",
        # DATA-40: Municipal bike counting stations per city (continuous counters, Tier A,
        # partial coverage). NOT the sharing tool (GBFS rental vehicles).
        "bike-counts",
        # DATA-41: District heating / heating network coverage per city (municipal heating planning,
        # federated per city WFS, Tier A, partial coverage berlin/hamburg).
        "district-heating",
        # Quick-260705-jgt: Municipal office wait times per city (live, keyless, Tier A,
        # partial coverage only Cologne). Via get_city_resource(slug, "office-wait-times").
        "office-wait-times",
    }
)

# T-12-MCP-INJECT: allowed per-station board paths under GET /api/v1/stations/{eva}/...
# The EVA is additionally validated as pure numeric (_validate_eva) before reaching
# the URL; only these board names are permitted as the second segment.
ALLOWED_STATION_BOARDS: frozenset[str] = frozenset({"departures", "arrivals"})

# T-12-MCP-INJECT: allowed live resource paths under GET /api/v1/live/{slug}/...
# Multi-segment paths are permitted here because they are checked against THIS allowlist
# (no raw tool input in path except the quoted slug).
ALLOWED_LIVE_RESOURCES: frozenset[str] = frozenset(
    {
        "transit/departures",
        # Frankfurt am Main live parking occupancy (Mobilithek DATEX II V3). Route is
        # fixed to city (/live/frankfurt-am-main/parking); any other slug -> 404.
        "parking",
    }
)

# T-12-MCP-INJECT: allowed slug-less top-level endpoints (GET /api/v1/<name>),
# optionally with query parameters. "compare" fans out a resource across multiple
# cities (cities/resource as query, no raw input in path).
ALLOWED_COLLECTIONS: frozenset[str] = frozenset(
    {
        "cities",
        "sources",
        "compare",
    }
)

# Fixed, moderate connection/write timeouts for loopback calls (oriented
# towards infra/http.py). connect/write are deliberately short; read + pool are
# settings-driven (see _loopback_timeout).
_LOOPBACK_CONNECT_TIMEOUT = 2.0
_LOOPBACK_WRITE_TIMEOUT = 5.0


def _loopback_limits(settings) -> httpx.Limits:  # noqa: ANN001 - Settings-Duck-Typing
    """Builds the httpx.Limits of the loopback client from settings.

    Pure value mapping (quick-260704-ust). max_connections/max_keepalive
    match httpx defaults by default (no behavioral change), but are
    now explicit and configurable via env.
    """
    return httpx.Limits(
        max_connections=settings.mcp_loopback_max_connections,
        max_keepalive_connections=settings.mcp_loopback_max_keepalive,
    )


def _loopback_timeout(settings) -> httpx.Timeout:  # noqa: ANN001 - Settings-Duck-Typing
    """Builds the httpx.Timeout of the loopback client from settings.

    The SHORT ``pool`` value (default 1.0s) is the actual defense: a
    burst no longer stalls for seconds on the connection pool (previously
    the flat 30s timeout also applied to pool acquire). ``read`` remains deliberately
    generous because upstreams behind the live API can be slow;
    connect/write are fixed moderate values.
    """
    return httpx.Timeout(
        connect=_LOOPBACK_CONNECT_TIMEOUT,
        read=settings.mcp_loopback_read_timeout,
        write=_LOOPBACK_WRITE_TIMEOUT,
        pool=settings.mcp_loopback_pool_timeout,
    )


class UpstreamError(RuntimeError):
    """Readable error from the live API response envelope.

    Raised on 4xx/5xx status instead of surfacing a raw
    ``httpx.HTTPStatusError`` traceback to the agent. FastMCP converts
    a raised exception into a tool error whose text the model
    sees; with this class, the text carries the structured API message including
    ``hint``, allowing the model to self-correct (e.g. call ``list_cities``
    on an unknown slug).

    ``status_code`` carries the HTTP status of the error response so that the
    registration layer (server.py) can gracefully convert 5xx (transient upstream/source
    outages) into a ``source_status="error"`` envelope, while re-raising 4xx
    (e.g. unknown slug, missing required parameter) so the model corrects itself.
    """

    def __init__(self, *args: object, status_code: int | None = None) -> None:
        super().__init__(*args)
        self.status_code = status_code


def _build_upstream_error(response: httpx.Response) -> UpstreamError:
    """Forms a readable ``UpstreamError`` from an error response.

    Prefers the canonical API error envelope ``{"error": {"message",
    "hint", "code"}}``; falls back to the (truncated) raw text or HTTP reason
    phrase if the response is not the expected JSON.
    """
    detail = ""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        err = body["error"]
        detail = " ".join(
            str(part) for part in (err.get("message"), err.get("hint")) if part
        )
    if not detail:
        detail = response.text[:200].strip() or response.reason_phrase
    return UpstreamError(
        f"cityscape-API {response.status_code}: {detail}",
        status_code=response.status_code,
    )


def _base_url() -> str:
    """Reads base URL from env and checks host against allowlist.

    Returns the validated base URL without trailing slash.
    Raises ``ValueError`` if scheme is not http/https or host
    is not in ``ALLOWED_HOSTS`` (T-12-MCP-SSRF).
    """
    # Base URL from CITYSCAPE_MCP_API_BASE, otherwise default. This way
    # the externally documented variable works without breaking the existing
    # env contract.
    raw = os.environ.get("CITYSCAPE_MCP_API_BASE", _DEFAULT_BASE_URL)
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        raise ValueError(
            f"Ungueltiges Schema fuer CITYSCAPE_MCP_API_BASE: "
            f"{parts.scheme!r}. Erlaubt sind nur http/https."
        )
    if parts.hostname not in ALLOWED_HOSTS:
        raise ValueError(
            f"Host {parts.hostname!r} ist nicht allowlistet (T-12-MCP-SSRF). "
            f"Erlaubt: {', '.join(sorted(ALLOWED_HOSTS))}."
        )
    return raw.rstrip("/")


def _validate_slug(slug: str) -> str:
    """Validates and quotes slug as pure path component (T-12-MCP-INJECT).

    A slug must not contain path separators or host components (``/``, ``@``, ``:``,
    whitespace); such inputs could redirect the URL. Returns the
    URL-quoted slug or raises ``ValueError``.
    """
    if not slug or not isinstance(slug, str):
        raise ValueError("Slug muss ein nicht-leerer String sein.")
    # Pure path component: no slash/at/colon/whitespace. These characters
    # could redirect host/userinfo/path (e.g. "hamburg@evil.example/internal").
    forbidden = set("/@:\\ \t\n\r?#")
    if any(ch in forbidden for ch in slug):
        raise ValueError(
            f"Ungueltiger Slug {slug!r}: enthaelt unzulaessige Zeichen "
            "(Pfad-/Host-Trenner)."
        )
    return quote(slug, safe="")


async def get_resource(
    slug: str,
    resource: str,
    params: dict[str, str] | None = None,
) -> dict:
    """Calls a city resource of the local live API and returns the JSON.

    Constructs the URL exclusively from the allowlisted base URL plus the fixed
    ``/cities/{slug}/{resource}`` schema. ``resource`` is validated against
    ``ALLOWED_RESOURCES``, ``slug`` is quoted as a pure path component,
    and base URL host is validated against ``ALLOWED_HOSTS`` before any request
    is sent. The result (canonical ``{data, meta}`` envelope of the API) is
    returned unchanged without any mapping/licensing logic.

    Args:
        slug: City slug (pure path component, e.g. ``"hamburg"``).
        resource: Resource name from ``ALLOWED_RESOURCES`` (e.g. ``"base"``).
        params: Optional query parameters (e.g. ``{"type": "hospital"}``).

    Raises:
        ValueError: For non-allowlisted host (T-12-MCP-SSRF) or unknown
            ``resource``/invalid ``slug`` (T-12-MCP-INJECT), in each case BEFORE a
            request is sent.
    """
    if resource not in ALLOWED_RESOURCES:
        raise ValueError(
            f"Unbekannte Ressource {resource!r} (T-12-MCP-INJECT). "
            f"Erlaubt: {', '.join(sorted(ALLOWED_RESOURCES))}."
        )
    safe_slug = _validate_slug(slug)
    # MCP identifier: resource name (already validated against ALLOWED_RESOURCES).
    return await _request(f"/cities/{safe_slug}/{resource}", params, tag=resource)


async def get_live(
    slug: str,
    live_resource: str,
    params: dict[str, str] | None = None,
) -> dict:
    """Calls a live resource ``/live/{slug}/{live_resource}``; returns JSON.

    ``live_resource`` is checked against ``ALLOWED_LIVE_RESOURCES``, ``slug`` quoted as
    pure path component, and base host validated against ``ALLOWED_HOSTS``
    BEFORE a request is sent (T-12-MCP-SSRF/-INJECT). Envelope 1:1.

    Args:
        slug: City slug (pure path component, e.g. ``"berlin"``).
        live_resource: Path from ``ALLOWED_LIVE_RESOURCES`` (e.g.
            ``"transit/departures"``).
        params: Optional query parameters (e.g. ``{"stop_id": "..."}``).
    """
    if live_resource not in ALLOWED_LIVE_RESOURCES:
        raise ValueError(
            f"Unbekannte Live-Ressource {live_resource!r} (T-12-MCP-INJECT). "
            f"Erlaubt: {', '.join(sorted(ALLOWED_LIVE_RESOURCES))}."
        )
    safe_slug = _validate_slug(slug)
    return await _request(
        f"/live/{safe_slug}/{live_resource}", params, tag=f"live:{live_resource}"
    )


async def get_collection(
    name: str,
    params: dict[str, str] | None = None,
) -> dict:
    """Calls a slug-less collection endpoint ``/{name}`` and returns the JSON.

    ``name`` is checked against ``ALLOWED_COLLECTIONS`` and base host validated against
    ``ALLOWED_HOSTS`` BEFORE a request is sent (T-12-MCP-SSRF/-INJECT).

    Args:
        name: Collection endpoint from ``ALLOWED_COLLECTIONS`` (``"cities"`` /
            ``"sources"``).
        params: Optional query parameters (e.g. pagination).
    """
    if name not in ALLOWED_COLLECTIONS:
        raise ValueError(
            f"Unbekannter Collection-Endpunkt {name!r} (T-12-MCP-INJECT). "
            f"Erlaubt: {', '.join(sorted(ALLOWED_COLLECTIONS))}."
        )
    return await _request(f"/{name}", params, tag=f"collection:{name}")


_EVA_RE = re.compile(r"^\d{6,8}$")


async def get_station_board(eva: str, board: str) -> dict:
    """Calls a per-station board ``/stations/{eva}/{board}`` and returns the JSON.

    ``eva`` is strictly validated as a 6-8 digit number (T-12-MCP-SSRF/-INJECT),
    ``board`` checked against ``ALLOWED_STATION_BOARDS``, base host against
    ``ALLOWED_HOSTS`` BEFORE a request is sent. Envelope 1:1.

    Args:
        eva: EVA station number (pure numeric, e.g. ``"8011160"``; from the
            catalog ``GET /cities/{slug}/stations``).
        board: ``"departures"`` or ``"arrivals"``.
    """
    if board not in ALLOWED_STATION_BOARDS:
        raise ValueError(
            f"Unbekanntes Board {board!r} (T-12-MCP-INJECT). "
            f"Erlaubt: {', '.join(sorted(ALLOWED_STATION_BOARDS))}."
        )
    if not isinstance(eva, str) or not _EVA_RE.match(eva):
        raise ValueError(
            f"Ungueltige EVA {eva!r} (T-12-MCP-INJECT): erwartet eine 6-8-stellige "
            "Zahl."
        )
    return await _request(f"/stations/{eva}/{board}", None, tag=f"station:{board}")


async def _request(
    path: str,
    params: dict[str, str] | None,
    *,
    tag: str,
) -> dict:
    """Executes the loopback GET against the allowlisted base URL (shared core).

    ``path`` is built exclusively from already validated components
    (quoted slug + allowlisted resource/collection); raw tool input never
    reaches here unvalidated. Base host is checked against allowlist in ``_base_url``.
    The MCP identifier ``tag`` is passed as a header (dashboard/ntfy).
    """
    base = _base_url()
    url = f"{base}{path}"
    headers = {_MCP_SOURCE_HEADER: tag}

    response = await _get_client().get(url, params=params, headers=headers)
    # On 4xx/5xx pass through structured API error envelope as readable
    # UpstreamError instead of presenting a raw traceback to the agent
    # (the model sees message + hint and can self-correct).
    if response.is_error:
        raise _build_upstream_error(response)
    return response.json()


# Reused AsyncClient per event loop (latency hardening 2026-07-02):
# previously EVERY tool call opened a fresh ``httpx.AsyncClient`` and thus
# a new TCP connection to the API; over an agent session with many calls
# this connection overhead accumulates. The cache is keyed per event loop
# because pooled connections are bound to the loop on which they were created:
# in server operation (one loop) this yields exactly ONE pooled client with keep-alive;
# in tests (fresh loop per test), each loop gets its own instead of reusing
# a foreign (broken) one.
# WeakKeyDictionary instead of ``id(loop)`` key: a garbage-collected loop removes its
# entry, and a new loop at the same memory address can never inherit the
# dead client. No explicit close needed: the process holds at most a handful of
# clients whose loopback connections the peer closes when idle.
_clients: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient] = (
    weakref.WeakKeyDictionary()
)


def _get_client() -> httpx.AsyncClient:
    """Pooled AsyncClient of current event loop (lazy, keep-alive)."""
    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None or client.is_closed:
        settings = get_settings()
        client = httpx.AsyncClient(
            limits=_loopback_limits(settings),
            timeout=_loopback_timeout(settings),
        )
        _clients[loop] = client
    return client
