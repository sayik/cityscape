"""Rate limit for ChatGPT GPT Action traffic (pattern: mcp/ratelimit.py).

Why a SEPARATE limit: ALL users of the cityscape GPT arrive server-side
via FEW OpenAI egress IPs (openai.com/chatgpt-actions.json). To prevent a
single power user from exhausting the shared IP budget of all ChatGPT users,
the OpenAI ranges are on CITYSCAPE_RATELIMIT_ALLOWLIST
(bypassing slowapi IP limit + AbuseGuard, same pattern as
Anthropic egress for the MCP server). This module acts as the BACKSTOP to that: a
moving-window limit per GPT USER (ephemeral OpenAI user identifier, fallback
conversation/GPT/IP) with the same default as the MCP endpoint (480/min,
CITYSCAPE_LIMIT_GPT). Storage in Redis (shared across workers), fallback
in-memory as in the MCP limiter.

Spoofing: The OpenAI headers can be spoofed, but a spoofer without
an allowlisted IP remains subject to the regular IP limit; this limit
is only applied IN ADDITION (no bypass vector, see infra/gpt_actions.py).
"""

from __future__ import annotations

import logging

from limits import parse
from limits.storage import MemoryStorage, storage_from_string
from limits.strategies import MovingWindowRateLimiter
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from cityscape.api.v1.ratelimit import real_client_ip
from cityscape.config import Settings
from cityscape.infra.gpt_actions import gpt_rate_ident, is_gpt_action

logger = logging.getLogger(__name__)


def _make_storage(settings: Settings):
    """Redis storage (shared across workers); fallback in-memory, see mcp/ratelimit."""
    uri = settings.limit_storage_uri or settings.redis_url
    try:
        # Short timeouts: check() must not block up to OS default when Redis
        # is unreachable (local start without Redis), otherwise app startup
        # hangs instead of falling back to in-memory. memory:// ignores kwargs.
        storage = storage_from_string(
            uri, socket_connect_timeout=0.5, socket_timeout=0.5
        )
        if storage.check():
            return storage
        logger.warning(
            "GPT-Guard: Redis (%s) nicht erreichbar, In-Memory-Fallback "
            "(pro-Prozess, nicht worker-geteilt).",
            uri,
        )
    except Exception as exc:  # noqa: BLE001 - any storage init error -> fallback
        logger.warning(
            "GPT-Guard: Redis-Storage-Init fehlgeschlagen (%s): %s", uri, exc
        )
    return MemoryStorage()


class GPTActionLimitMiddleware(BaseHTTPMiddleware):
    """Moving-window limit per GPT user; fires ONLY on GPT action requests."""

    def __init__(self, app, limit: str | None = None) -> None:  # noqa: ANN001 - Starlette app
        super().__init__(app)
        s = Settings()
        effective = limit if limit is not None else s.limit_gpt
        self._item = parse(effective) if effective else None
        self._limiter = (
            MovingWindowRateLimiter(_make_storage(s)) if self._item else None
        )
        self._retry_after = str(self._item.get_expiry()) if self._item else "60"

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Throttle only real data routes; health/docs/admin remain untouched.
        if (
            self._limiter is None
            or not request.url.path.startswith("/api/v1/")
            or not is_gpt_action(request.headers)
        ):
            return await call_next(request)

        ident = gpt_rate_ident(request.headers, real_client_ip(request))
        if not self._limiter.hit(self._item, "gpt", ident):
            # Local import as in AbuseGuard (avoids cycles during module loading).
            from cityscape.api.errors import _envelope

            response = _envelope(
                429,
                "rate_limited",
                "GPT action rate limit exceeded.",
                hint=(
                    "Zu viele Anfragen aus dieser ChatGPT-Sitzung. Bitte den "
                    "Retry-After-Header beachten."
                ),
            )
            response.headers["Retry-After"] = self._retry_after
            return response

        return await call_next(request)
