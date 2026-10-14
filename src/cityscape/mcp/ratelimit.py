"""Rate limiting for the public MCP endpoint (security hardening 2026-06-21).

The remote MCP server (``mcp.cityscape.dev/mcp``, streamable-http) ran until now
WITHOUT its own throttling: Caddy proxies 1:1 and the slowapi limiters of the
FastAPI app only apply to the API path, not to the MCP service. A client
could therefore hammer the MCP endpoint unchecked (each tool call also triggers
an API call, multiplying the upstream load).

This middleware throttles per real client IP using a moving window
(``limits`` library, already available via slowapi). The storage is in REDIS
(``CITYSCAPE_REDIS_URL``) so that the budget is SHARED across multiple MCP replicas
(horizontal scaling): if N replicas were running, each with its own in-memory window,
the effective limit would be multiplied by N. If Redis is unreachable (e.g. local
stdio operation without Redis), the middleware falls back to a process-local
in-memory storage so the server still starts (protective limit, not
hard state). The real client IP comes, as in the API, first from
``CF-Connecting-IP`` (authoritatively set by Cloudflare), then from
``X-Forwarded-For[0]``, otherwise from the peer.
"""

from __future__ import annotations

import logging
import os

from limits import parse
from limits.storage import MemoryStorage, storage_from_string
from limits.strategies import MovingWindowRateLimiter
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# stdlib-only module, intentionally does NOT pull the FastAPI/Settings path (see
# rationale above for client_ip; same decoupling for the allowlist check).
from cityscape.infra.allowlist import ENV_VAR, ip_allowlisted, parse_allowlist

logger = logging.getLogger(__name__)

# Default budget per IP for the MCP endpoint. Overridable via CITYSCAPE_MCP_RATE_LIMIT
# (limits format "<number>/<unit>"). Owner history 2026-06-24:
# first 60 -> 240/min (discovery flows get_city_overview -> multiple targeted
# tool calls), then 240 -> 480/min (more headroom for AI agent sessions). Target size
# by year-end clearly < 1000 users, server box with ample reserve -> uncritical. The
# overview snapshot bundles its highlights server-side into ONE API call (no
# multiplying of upstream load) and is parallelized + time-capped. Deliberately
# remains a protective limit against hammering.
_DEFAULT_LIMIT = "480/minute"


def _make_storage():
    """Redis storage for shared budgets across replicas; fallback in-memory.

    storage_from_string connects lazily; ``check()`` pings Redis and returns
    False if the server is unreachable (does not raise). Only then does the
    process-local fallback engage, so that an inadvertently missing Redis does
    not prevent the local/stdio MCP server from starting.
    """
    url = os.environ.get("CITYSCAPE_REDIS_URL", "redis://redis:6379/0")
    try:
        # Short connect/read timeouts: without them, check() can block up to the
        # OS default if the host cannot be resolved/reached (local stdio operation
        # without Redis, or ISP DNS hijack of the compose service name "redis")
        # -> the MCP server start hangs. This way, check() quickly yields False
        # and we take the in-memory fallback. memory:// ignores kwargs (no network),
        # hence harmless.
        storage = storage_from_string(
            url, socket_connect_timeout=0.5, socket_timeout=0.5
        )
        if storage.check():
            return storage
        logger.warning(
            "MCP rate-limit: Redis (%s) nicht erreichbar, In-Memory-Fallback "
            "(pro-Prozess, nicht replica-geteilt).",
            url,
        )
    except Exception as exc:  # noqa: BLE001 - any storage init error -> fallback
        logger.warning(
            "MCP rate-limit: Redis-Storage-Init fehlgeschlagen (%s), "
            "In-Memory-Fallback: %s",
            url,
            exc,
        )
    return MemoryStorage()


def client_ip(request: Request) -> str:
    """Real client IP: CF-Connecting-IP -> X-Forwarded-For[0] -> Peer.

    Identical source to ``cityscape.api.v1.ratelimit.real_client_ip``; kept
    independent here so that the MCP server does not have to import the
    FastAPI/slowapi path. Trustworthy only under the CF-only firewall (otherwise
    an attacker could spoof CF-Connecting-IP, see DEPLOYMENT.md section 2).
    """
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


class MCPRateLimitMiddleware:
    """ASGI middleware: throttles HTTP requests per client IP (moving window).

    Pure ASGI (not BaseHTTPMiddleware), so that the SSE/streaming path of the
    MCP transport passes through untouched: for allowed requests, ``app`` is
    called directly with the original ``receive``/``send``, so the stream is never
    buffered. Only the rejection case (429) generates a dedicated response.
    """

    def __init__(self, app: ASGIApp, limit: str | None = None) -> None:
        self.app = app
        self._limiter = MovingWindowRateLimiter(_make_storage())
        self._item = parse(
            limit or os.environ.get("CITYSCAPE_MCP_RATE_LIMIT", _DEFAULT_LIMIT)
        )
        # Window in seconds for the Retry-After header.
        self._retry_after = str(self._item.get_expiry())
        # Allowlist bypass (connectors directory hardening 2026-07-02): CIDRs from
        # the env bypass the per-IP limit completely (Anthropic egress bundles
        # many end users behind few IPs). Parsed once at startup, like the
        # limit itself; fail-safe empty = nobody (infra/allowlist.py).
        self._allowlist = parse_allowlist(os.environ.get(ENV_VAR))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Pass through lifespan/WebSocket untouched.
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        ip = client_ip(request)
        # Allowlisted infrastructure IPs (e.g. Anthropic egress) are not
        # counted and never throttled; all others run into the limit unchanged.
        if ip_allowlisted(ip, self._allowlist):
            await self.app(scope, receive, send)
            return
        # hit() counts the request and returns False once the budget is
        # exhausted. Namespace "mcp" neatly separates the buckets.
        if not self._limiter.hit(self._item, "mcp", ip):
            response = JSONResponse(
                {
                    "error": "rate_limited",
                    "message": "MCP rate limit exceeded.",
                    "hint": "Bitte den Retry-After-Header beachten.",
                },
                status_code=429,
                headers={"Retry-After": self._retry_after},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
