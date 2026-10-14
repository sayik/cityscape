"""FastMCP server instance of the cityscape MCP server (DX-05).

The server registers a few named tools (entry/meta/parameterized)
plus a generic ``get_city_resource`` for all remaining data types
(consolidation 2026-07-02, see comment on registration block). The actual
tool logic resides as standalone async functions in ``cityscape.mcp.tools``
(Blocker-4 calling convention): ``@mcp.tool()`` is only thinly layered over
these functions here, so that they remain directly testable as coroutines and
the decorator still registers the FunctionTool for the FastMCP API.

There is NO mapping/licensing logic in the server: each tool calls the
live FastAPI via ``cityscape.mcp.client.get_resource`` and returns its
normalized JSON 1:1 (D-07/D-08). Two transports:
- stdio (default): local subprocess for Claude Desktop/Code.
- streamable-http: public remote endpoint (e.g. mcp.cityscape.dev),
  behind Caddy/Cloudflare, keyless like the API. Activated via
  CITYSCAPE_MCP_TRANSPORT=streamable-http; CITYSCAPE_MCP_API_BASE then points to the
  public API (https://cityscape.dev/api/v1).
"""

from __future__ import annotations

import functools
import os

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from cityscape.mcp import tools
from cityscape.mcp.client import ALLOWED_RESOURCES, UpstreamError
from cityscape.registry.catalog import CITY_DATA_CATALOG

# Server Instructions: delivered to the client/agent during initialize and
# are the largest discovery leverage. They tell the agent WHERE to start
# (get_city_overview) and how everything connects, so it can access all data
# quickly and without guessing (Owner request 2026-06-24). The tool count is
# filled in live BELOW after all _register() calls have run (see
# ``mcp._mcp_server.instructions = ...`` after the last _register() line):
# a hardcoded count here would immediately become outdated with every new tool
# (exactly the issue triggered by an outdated memory entry "44 Tools", Owner discovery
# 2026-07-01) and is visible to EVERY client on EVERY connect, not just to
# Claude Code with its own memory.
_INSTRUCTIONS = (
    "cityscape is a keyless, read-only open-data API for 84 German cities with "
    "~60 data types, exposed as {tool_count} MCP tools (count is live from this "
    "server, not a cached or remembered number). To answer ANY city question, "
    "START with get_city_overview(slug): it returns the city's base data, a "
    "catalog of ALL available data types (each with its coverage status and the "
    "exact tool to call next) and a small live snapshot (weather, air, train "
    "departures). Most data types are fetched with ONE generic tool: "
    "get_city_resource(slug, resource=<type>), where <type> is the catalog key "
    "(e.g. 'parking', 'charging', 'demographics', 'solar'); its resource enum "
    "lists every valid key. Find valid city slugs with list_cities (or the "
    "cityscape://cities resource); browse every data type with the "
    "cityscape://catalog resource; see sources and licenses with sources. "
    "Compare one metric across many cities in one call with compare. Every tool "
    "returns a canonical {data, meta} envelope; meta.source_status tells you whether "
    "a source delivered data (ok / no_data / not_covered / disabled / error), so a "
    "missing source degrades gracefully instead of failing. Coverage keeps growing: "
    "more data types and cities are added regularly."
)

mcp = FastMCP("cityscape", instructions=_INSTRUCTIONS)

# Records the names of all tools registered via _register(), so that the
# instructions below can carry the REAL, up-to-date count instead of a
# manually maintained one that becomes outdated.
_registered_tool_names: list[str] = []


# Behavioral hints (MCP Tool Annotations): Every cityscape tool is a
# read-only GET wrapper on the live API: it writes no state, is safely
# repeatable (idempotent), and non-destructive. Clients can thus allow calls
# without prompting; directory scanners (Glama/Smithery) evaluate the
# transparency positively. ``open_world`` honestly distinguishes: data tools
# pull live data from external authority APIs (open, mutable domain = True),
# whereas the meta tools list_cities/sources provide CITYSCAPE's own
# closed coverage list (closed domain = False).
def _annotations(*, open_world: bool) -> ToolAnnotations:
    return ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=open_world,
    )


# Human-readable display titles per tool. The Anthropic Connectors Directory
# requires a title for every tool; clients/directories also display
# this title in the tool picker. The function name (snake_case) is the
# stable technical identifier, while the title is for display. If an entry is missing,
# _title_for() falls back to an automatic title-case derivation so that
# new tools are never left without a title (see test_mcp_tool_titles).
_TOOL_TITLES: dict[str, str] = {
    "get_city": "City Base Data",
    "get_city_overview": "City Overview",
    "get_city_resource": "City Data by Type",
    "air_quality": "Air Quality",
    "weather": "Weather",
    "pois": "Points of Interest",
    "station_board_departures": "Station Board: Departures",
    "station_board_arrivals": "Station Board: Arrivals",
    "transit_departures": "Transit Departures",
    "list_cities": "List Cities",
    "sources": "Data Sources",
    "compare": "Compare Cities",
}


def _title_for(name: str) -> str:
    """Display title of a tool; fallback = title-case from function name."""
    return _TOOL_TITLES.get(name) or name.replace("_", " ").title()


# Graceful degradation wrapper: a transient upstream/source failure (5xx)
# must NOT abort a tool call hard with an error. Such cases are converted into
# an honest ``source_status="error"`` envelope (exactly the envelope promise
# that the other tools fulfill with 200), so that a reviewer/client never sees
# a raw error if, for example, Overpass is temporarily unavailable.
# 4xx (unknown slug, missing required parameter) is re-raised: the
# text carries message + hint so that the model can correct itself.
def _graceful(fn):
    """Wraps a tool coroutine; 5xx UpstreamError -> graceful envelope."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except UpstreamError as exc:
            code = exc.status_code
            if code is not None and 500 <= code < 600:
                return {
                    "data": None,
                    "meta": {
                        "source_status": "error",
                        "note": str(exc),
                    },
                }
            raise

    return wrapper


# Thin registration of standalone tool functions (Blocker 4): the
# decorator is programmatically applied over each function. The function itself
# remains callable as a coroutine in cityscape.mcp.tools unchanged; FastMCP
# generates the schema from type annotations and docstrings (functools.wraps
# in the wrapper preserves signature, annotations, and docstring; the schema remains identical).
def _register(fn, *, open_world: bool = True) -> None:
    """Registers a tool with title + read-only annotations (see above)."""
    mcp.tool(
        title=_title_for(fn.__name__),
        annotations=_annotations(open_world=open_world),
    )(_graceful(fn))
    _registered_tool_names.append(fn.__name__)


# TOOL CONSOLIDATION 2026-07-02: previously 1 tool per data type (71 tools, ~30k
# tokens tool list, Cursor 80-tool limit in sight). Now: a few
# named tools (entry/meta/parameterized/popular) + ONE generic
# get_city_resource for the entire long tail. Data type discovery
# is handled by get_city_overview + cityscape://catalog (each data type's
# resource key) + the resource enum in the generic tool's inputSchema.
_register(tools.get_city)
# Owner 2026-06-24: single-call overview (base + catalog of all data types +
# live highlights). Discovery entry point so agents see the full breadth per city
# (not just weather). Pulls live highlights -> open_world=True.
_register(tools.get_city_overview)
# Generic long-tail access: EVERY catalog data type via resource key
# (enum from client.ALLOWED_RESOURCES without pois). Live sources behind it ->
# open_world=True.
_register(tools.get_city_resource)
# The two most popular data types retain dedicated tools (discoverability in
# the tool picker); everything else runs via get_city_resource.
_register(tools.air_quality)
_register(tools.weather)
# Parameterized capabilities (actual custom logic, not a pure slug wrapper):
_register(tools.pois)
# DATA-36: Per-station live boards (any EVA, all categories including regional transit).
_register(tools.station_board_departures)
_register(tools.station_board_arrivals)
# DATA-26: Real-time departures per stop (stop_id from resource='transit').
_register(tools.transit_departures)
# Meta tools: describe own coverage -> closed domain
# (open_world=False).
_register(tools.list_cities, open_world=False)
_register(tools.sources, open_world=False)
# API-05/D-06: Multi-city compare of a resource (weather/air) in a single response.
_register(tools.compare)

# Update live tool count in instructions: FastMCP's ``instructions`` is
# a property without a setter (only set via constructor), hence written via the
# underlying ``_mcp_server``. ``str.replace`` instead of
# ``str.format`` because the instructions themselves contain literal ``{data, meta}`` braces
# as an envelope example, which ``.format()`` would misinterpret as placeholders.
mcp._mcp_server.instructions = _INSTRUCTIONS.replace(
    "{tool_count}", str(len(_registered_tool_names))
)


# Schema diet (Token footprint 2026-07-02): The tool list cost ~30k tokens,
# of which ~55% was a 71x BYTE-IDENTICAL repeated outputSchema (ToolEnvelope) including
# German ToolMeta docstring and 9 Pydantic auto-``title`` fields per tool.
# This pass removes in-place AFTER registration:
# - all auto-``title`` from input AND outputSchema (the property key already says
#   everything; the DISPLAY title of the tool is a separate MCPTool field and remains,
#   Anthropic directory requirement unaffected),
# - ``description`` ONLY in outputSchema (class docstrings of ToolEnvelope/
#   ToolMeta; parameter descriptions in inputSchema are valuable for
#   tool selection and REMAIN, test_every_tool_has_output_schema_and_param_
#   descriptions ensures this).
# Measured: ~-27% of total tool list tokens. Runtime validation
# (fn_metadata.output_model) does not depend on the schema dict and remains unaffected.
def _slim_schema(node: object, *, strip_descriptions: bool = False) -> None:
    """Recursively removes auto-``title`` (and optionally ``description``) in-place.

    Recursion ONLY in schema positions (properties VALUES, items, $defs, anyOf,
    ...): a data field itself named "title" is preserved as a property key;
    only the schema keyword is removed.
    """
    if not isinstance(node, dict):
        return
    node.pop("title", None)
    if strip_descriptions:
        node.pop("description", None)
    for key in ("properties", "$defs", "definitions", "patternProperties"):
        sub = node.get(key)
        if isinstance(sub, dict):
            for child in sub.values():
                _slim_schema(child, strip_descriptions=strip_descriptions)
    for key in (
        "items",
        "prefixItems",
        "additionalProperties",
        "anyOf",
        "oneOf",
        "allOf",
        "not",
    ):
        sub = node.get(key)
        if isinstance(sub, dict):
            _slim_schema(sub, strip_descriptions=strip_descriptions)
        elif isinstance(sub, list):
            for child in sub:
                _slim_schema(child, strip_descriptions=strip_descriptions)


def _slim_all_tool_schemas() -> None:
    """Applies the schema diet to all registered tools (once, in-place).

    ``tool.parameters`` (inputSchema) and ``fn_metadata.output_schema`` are
    plain dicts that FastMCP's list_tools returns by reference; the slimming
    here thus applies to every client and every listing.
    """
    for tool in mcp._tool_manager._tools.values():
        _slim_schema(tool.parameters)
        if tool.fn_metadata.output_schema is not None:
            _slim_schema(tool.fn_metadata.output_schema, strip_descriptions=True)


_slim_all_tool_schemas()


def _stamp_datatype_count() -> None:
    """Replaces the ``~60`` placeholder in docstrings with the actual number.

    The tool descriptions are static docstrings (tools.py) and would
    drift with each new data type (2026-07-03: actually 65 data types, text
    said "~60"). The number comes from the single source of truth
    (``ALLOWED_RESOURCES`` minus ``overview``, which is the meta-resource
    itself) and is stamped once into descriptions at import time;
    new data types no longer require manual text edits.
    """
    count = len(ALLOWED_RESOURCES) - 1
    for tool in mcp._tool_manager._tools.values():
        if tool.description and "~60" in tool.description:
            tool.description = tool.description.replace("~60", str(count))


_stamp_datatype_count()


# MCP Resources: expose the coverage catalog as browsable resources, so clients
# can discover what cityscape offers (cities + sources) without a tool call.
@mcp.resource("cityscape://cities")
async def cities_resource() -> dict:
    """All covered German cities with slug, federal state, population and coverage."""
    return await tools.list_cities()


@mcp.resource("cityscape://sources")
async def sources_resource() -> dict:
    """All cityscape data sources with license, attribution and availability."""
    return await tools.sources()


@mcp.resource("cityscape://catalog")
async def catalog_resource() -> dict:
    """The catalog of all per-city data types: label, matching tool and REST path.

    Lets an agent browse the full breadth of cityscape (every data type and the tool
    that fetches it) without a tool call. For a live, per-city view with coverage
    status and highlights, call get_city_overview(slug).
    """
    return {
        "data_types": [
            {
                "type": dt.key,
                "label": dt.label_en,
                "tool": dt.tool,
                "path": f"/api/v1/cities/{{slug}}/{dt.key}",
            }
            for dt in CITY_DATA_CATALOG
        ],
        "note": (
            "cityscape keeps adding more data types and cities. Start with "
            "get_city_overview(slug) for a live, per-city view. Where 'tool' is "
            "get_city_resource, pass the 'type' value as its resource argument."
        ),
    }


# MCP Prompts: a few ready-made prompts that showcase common multi-tool flows.
@mcp.prompt()
def city_overview(slug: str) -> str:
    """Get a complete picture of a German city and what cityscape offers for it."""
    return (
        f"Give me an overview of the German city '{slug}'. Call get_city_overview "
        "first to see its base data, every available data type (with the tool to "
        "fetch each) and a live snapshot, then pull the most relevant data types in "
        "full and summarize the situation."
    )


@mcp.prompt()
def city_briefing(slug: str) -> str:
    """A concise live briefing (weather, air, transit) for a German city."""
    return (
        f"Give me a concise current briefing for the German city '{slug}'. "
        "Use the cityscape tools to fetch weather, air quality and live "
        "public-transport departures, then summarize the situation in a few "
        "bullet points. If a source has no data, say so briefly."
    )


@mcp.prompt()
def compare_air_quality(cities: str) -> str:
    """Compare current air quality across several German cities."""
    return (
        f"Compare the current air quality across these German cities: {cities}. "
        "Use the cityscape 'compare' tool with resource='air', then rank the "
        "cities from cleanest to most polluted and note any missing data."
    )


@mcp.prompt()
def commute_check(slug: str) -> str:
    """Check the live commute/transit situation for a German city."""
    return (
        f"Check the live commute situation in the German city '{slug}': pull "
        "real-time public-transport departures (transit_departures) and any "
        "motorway roadworks/traffic (get_city_resource with resource='traffic'), "
        "then tell me whether there are notable delays right now."
    )


def _mcp_uvicorn_kwargs(settings) -> dict:  # noqa: ANN001 - Settings-Duck-Typing
    """Builds the uvicorn.run kwargs dict for the three MCP backpressure caps.

    Pure value mapping without side effects (no uvicorn import needed), so that
    kwargs construction remains unit-testable without blocking ``uvicorn.run``.
    ``limit_concurrency`` is the actual overload cap: beyond this, uvicorn
    returns 503 instead of flooding the event loop indefinitely;
    ``timeout_keep_alive``/``backlog`` match uvicorn's own defaults
    (just explicitly set and therefore configurable).
    """
    return {
        "limit_concurrency": settings.mcp_limit_concurrency,
        "timeout_keep_alive": settings.mcp_timeout_keep_alive,
        "backlog": settings.mcp_backlog,
    }


def run() -> None:
    """Starts the server in the transport selected via environment variable.

    stdio (default): no open port, local subprocess. streamable-http:
    binds an HTTP port (CITYSCAPE_MCP_HOST/-PORT) for the public
    remote endpoint. Host default 127.0.0.1; the container service sets
    CITYSCAPE_MCP_HOST=0.0.0.0 so Caddy reaches it over the compose network.
    """
    transport = os.environ.get("CITYSCAPE_MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        from mcp.server.transport_security import TransportSecuritySettings

        mcp.settings.host = os.environ.get("CITYSCAPE_MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("CITYSCAPE_MCP_PORT", "8081"))
        # The MCP transport includes DNS rebinding protection, which by default
        # only allows localhost hosts/origins (intended for locally bound servers).
        # Behind Caddy/Cloudflare, host/origin vary; for a public, keyless
        # read-only API, the protection is unnecessary and would block all
        # calls (HTTP 421). Default is therefore off; re-enabled via
        # CITYSCAPE_MCP_DNS_REBINDING_PROTECTION=1 with explicit allowlists
        # (CITYSCAPE_MCP_ALLOWED_HOSTS/-ORIGINS, comma-separated).
        if os.environ.get("CITYSCAPE_MCP_DNS_REBINDING_PROTECTION") == "1":
            hosts = [
                h.strip()
                for h in os.environ.get("CITYSCAPE_MCP_ALLOWED_HOSTS", "").split(",")
                if h.strip()
            ]
            origins = [
                o.strip()
                for o in os.environ.get("CITYSCAPE_MCP_ALLOWED_ORIGINS", "").split(",")
                if o.strip()
            ]
            mcp.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=hosts,
                allowed_origins=origins,
            )
        else:
            mcp.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=False,
            )
        # Custom uvicorn launch instead of mcp.run(transport=...), so that we can
        # wrap the streamable-http app with the IP rate-limit middleware
        # (security hardening 2026-06-21): the public MCP endpoint otherwise had
        # NO throttling. mcp.run() would internally build the same
        # streamable_http_app() and start it via uvicorn; we just insert the
        # middleware in between. The app's own lifespan (session manager) is
        # preserved since uvicorn runs it from the ASGI app.
        import uvicorn

        from cityscape.config import get_settings
        from cityscape.mcp.ratelimit import MCPRateLimitMiddleware

        app = mcp.streamable_http_app()
        app.add_middleware(MCPRateLimitMiddleware)
        # Backpressure caps (quick-260704-ust) via the pure, unit-tested
        # _mcp_uvicorn_kwargs function: limit_concurrency throttles the previously
        # backpressure-free public endpoint (uvicorn returns 503 under overload
        # instead of flooding the event loop). host/port/log_level remain unchanged from
        # mcp.settings.
        uvicorn.run(
            app,
            host=mcp.settings.host,
            port=mcp.settings.port,
            log_level=mcp.settings.log_level.lower(),
            **_mcp_uvicorn_kwargs(get_settings()),
        )
    else:
        mcp.run()


if __name__ == "__main__":
    run()
