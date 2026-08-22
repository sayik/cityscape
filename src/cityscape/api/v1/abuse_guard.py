"""Abuse-Guard against DISTRIBUTED bots (scraping hardening).

The slowapi IP limit (``ratelimit.py``, 120/min + 3000/h per IP) throttles a
SINGLE IP. A botnet or cloud range with many IPs bypasses it. This
middleware supplements two inexpensive, early layers of protection BEFORE the fine-grained IP limit:

1. **Aggregated subnet limit** per /24 (IPv4) or /64 (IPv6): throttles when an
   atypically high volume of traffic comes from a SINGLE subnet. Intentionally set high (default 1200/min =
   ~10x the IP burst) so that legitimate NAT/campus users behind a shared
   IP are not affected. Storage in Redis (shared via replicas; fallback
   to in-memory if Redis is unreachable) as with the MCP limiter.
2. **Optional Cloudflare Bot Score Block**: Rejects requests with a ``cf-bot-score``
   below a threshold (``bot_score_min``, 0 = off) with a 403 response. The header
   is only available with Cloudflare Bot Management/Enterprise; it is missing in Free/Pro,
   in which case the check is a no-op hook that automatically takes effect as soon as scores
   are available.

The actual client IP comes from ``real_client_ip`` (CF connecting IP -> XFF[0] ->
peer), identical to the slowapi limiter (trusted behind the CF-only firewall).
"""

from __future__ import annotations

import ipaddress
import logging

from limits import parse
from limits.storage import MemoryStorage, storage_from_string
from limits.strategies import MovingWindowRateLimiter
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from cityscape.api.v1.ratelimit import real_client_ip
from cityscape.config import Settings
from cityscape.infra.allowlist import ip_allowlisted, parse_allowlist

logger = logging.getLogger(__name__)


def subnet_of(ip_str: str, v4_prefix: int, v6_prefix: int) -> str:
    """IP subnet key (/v4_prefix or /v6_prefix); the IP address itself if an error occurs."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return ip_str
    prefix = v4_prefix if isinstance(ip, ipaddress.IPv4Address) else v6_prefix
    return str(ipaddress.ip_network(f"{ip_str}/{prefix}", strict=False))


def _make_storage(settings: Settings):
    """Redis storage (shared via replicas); fallback to in-memory storage—see mcp/ratelimit."""
    uri = settings.limit_storage_uri or settings.redis_url
    try:
        # Kurze Connect-/Read-Timeouts: sonst kann check() bei nicht erreichbarem
        # Redis (lokaler Start ohne Redis, DNS-Hijack des Compose-Servicenamens)
        # bis zum OS-Default blockieren -> App-Start hängt, statt auf den
        # In-Memory-Fallback zu fallen. memory:// ignoriert die kwargs (kein Netz).
        storage = storage_from_string(
            uri, socket_connect_timeout=0.5, socket_timeout=0.5
        )
        if storage.check():
            return storage
        logger.warning(
            "AbuseGuard: Redis (%s) unreachable, in-memory fallback "
            "(per process, not shared across replicas).",
            uri,
        )
    except Exception as exc:  # noqa: BLE001 - jeder Storage-Init-Fehler -> Fallback
        logger.warning("AbuseGuard: Redis Storage Init Failed (%s): %s", uri, exc)
    return MemoryStorage()


class AbuseGuardMiddleware(BaseHTTPMiddleware):
    """Subnet rate limit + optional CF bot score block (runs before the IP limit)."""

    def __init__(self, app) -> None:  # noqa: ANN001 - Starlette-App
        super().__init__(app)
        s = Settings()
        self._bot_score_min = s.bot_score_min
        self._v4 = s.subnet_ipv4_prefix
        self._v6 = s.subnet_ipv6_prefix
        self._item = parse(s.limit_subnet) if s.limit_subnet else None
        self._limiter = (
            MovingWindowRateLimiter(_make_storage(s)) if self._item else None
        )
        self._retry_after = str(self._item.get_expiry()) if self._item else "60"
        # Allowlist Bypass (Connectors Directory Hardening 2026-07-02): CIDRs from
        # CITYSCAPE_RATELIMIT_ALLOWLIST bypass the subnet limit AND the bot score
        # block. Rationale for Bot Score: Allowlisted ranges are explicitly
        # permitted AUTOMATED infrastructure (Anthropic Egress); a
        # low Bot Score would be expected there, and a 403 would block
        # directory traffic just as the limit would. Fail-safe empty = no one.
        self._allowlist = parse_allowlist(s.ratelimit_allowlist)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        from cityscape.api.errors import _envelope

        # 0. Whitelisted infrastructure IPs (e.g., Anthropic Egress) bypass
        #    the AbuseGuard entirely (ONLY this guard; Auth remains unaffected).
        if ip_allowlisted(real_client_ip(request), self._allowlist):
            return await call_next(request)

        # 1. Optional bot score block (no-op without the cf-bot-score header).
        if self._bot_score_min > 0:
            raw = request.headers.get("cf-bot-score")
            if raw:
                try:
                    score: int | None = int(raw)
                except ValueError:
                    score = None
                if score is not None and score < self._bot_score_min:
                    return _envelope(
                        403,
                        "bot_blocked",
                        "Request blocked by bot protection.",
                        hint="Automated access detected (low bot score).",
                    )

        # 2. Aggregiertes Subnetz-Limit gegen verteilte Bots.
        if self._limiter is not None:
            net = subnet_of(real_client_ip(request), self._v4, self._v6)
            if not self._limiter.hit(self._item, "subnet", net):
                response = _envelope(
                    429,
                    "rate_limited",
                    "Subnet rate limit exceeded.",
                    hint=(
                        "Zu viele Anfragen aus diesem Netzbereich. Bitte den "
                        "Retry-After-Header beachten."
                    ),
                )
                response.headers["Retry-After"] = self._retry_after
                return response

        return await call_next(request)
