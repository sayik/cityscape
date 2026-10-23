"""Rate limiting contracts (API-06): Limiter + key_func + tier constants.

Wave 1 wires up the real sync Redis URI (Pitfall 1: slowapi does NOT share the
async pool ``app.state.redis``, but opens via ``storage_uri`` its OWN
synchronous redis-py connection to the SAME Redis server). ``build_limiter`` derives
the storage URI from settings (``limit_storage_uri or redis_url``).

Headers are normalized to the IETF standard names ``RateLimit-Limit`` /
``RateLimit-Remaining`` / ``RateLimit-Reset`` (D-02): slowapi
emits the older ``X-RateLimit-*`` names by default; via
``_header_mapping`` we map them to the standard names without the ``X-`` prefix.

``real_client_ip`` is MANDATORY instead of slowapi's ``get_remote_address`` (T-11-RL-
SPOOF): behind Caddy/Cloudflare, ``request.client.host`` only reads the proxy IP.
The real client IP comes first from the Cloudflare header, then from the first
IP in X-Forwarded-For, otherwise direct peer.
"""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.extension import HEADERS

from cityscape.config import Settings
from cityscape.infra.allowlist import ip_allowlisted, parse_allowlist

# IETF standard RateLimit headers (D-02, without X- prefix). slowapi uses
# X-RateLimit-* by default; this mapping normalizes names.
_STANDARD_HEADER_MAPPING = {
    HEADERS.LIMIT: "RateLimit-Limit",
    HEADERS.REMAINING: "RateLimit-Remaining",
    HEADERS.RESET: "RateLimit-Reset",
    HEADERS.RETRY_AFTER: "Retry-After",
}


def ANON_LIMIT() -> str:
    """Combined IP budget: burst (limit_anon) + sustained window.

    Returns both limits separated by semicolons; slowapi/limits ``parse_many``
    interprets this as MULTIPLE concurrently active limits (minute burst caps
    spikes, hour limit throttles sustained scraping). If only limit_anon is set
    (e.g. test override CITYSCAPE_LIMIT_ANON), it applies alone.

    Freshly instantiated instead of get_settings() cache (toggle lookup convention),
    since @limiter.limit reads the limit per request and per-test set CITYSCAPE_
    env vars must take effect.
    """
    s = Settings()
    limits = [s.limit_anon]
    if s.limit_anon_sustained:
        limits.append(s.limit_anon_sustained)
    return ";".join(limits)


def ADMIN_LOGIN_LIMIT() -> str:
    """Strict budget on admin login against brute force (Audit HIGH-1)."""
    return Settings().limit_admin_login


def real_client_ip(request: Request) -> str:
    """Real client IP: CF-Connecting-IP -> X-Forwarded-For[0] -> Peer (MANDATORY).

    Never use slowapi's ``get_remote_address`` (reads only proxy IP, T-11-RL-SPOOF).

    TRUST PREREQUISITE (Audit HIGH-2, 2026-06-10): These headers are only
    trustworthy if origin is EXCLUSIVELY reachable from Cloudflare
    (mandatory firewall step in runbook) and Caddy strips a client-sent
    X-Forwarded-For (Caddyfile.prod). Without both, an attacker could set
    a random IP per request and obtain fresh rate limit buckets.
    """
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def rate_key(request: Request) -> str:
    """Counting key per client: ``ip:<client-ip>`` (keyless, open API)."""
    return f"ip:{real_client_ip(request)}"


def _storage_uri(settings: Settings) -> str:
    """Sync storage URI for slowapi: limit_storage_uri otherwise redis_url (Pitfall 1).

    slowapi uses this to open its OWN synchronous redis-py connection to the SAME
    Redis server (not the async app.state.redis pool). This satisfies "shared across
    workers + survives restart" in practice (RESEARCH Open Q1, variant a).
    """
    return settings.limit_storage_uri or settings.redis_url


def build_limiter(settings: Settings) -> Limiter:
    """Builds the slowapi limiter from settings (test override safe).

    ``headers_enabled=True`` makes slowapi emit RateLimit headers;
    ``_header_mapping`` normalizes them to IETF standard names (D-02).

    ``default_limits=[ANON_LIMIT]`` (Live report M2): IP budget (default
    60/min) applies as DEFAULT to EVERY route that RateLimitMiddleware sees,
    including city/meta GETs without own @limiter.limit decorator. Routes
    WITH their own decorator (/sources, /compare, /admin/login) keep their own
    limit (slowapi does NOT apply default additionally in middleware path for
    decorated routes). Thus all GET routes carry a limit + RateLimit
    headers without needing each route to be decorated.

    The API is keyless/open: all clients share IP budget (ANON_LIMIT),
    there is no key/tier differentiation anymore.

    ALLOWLIST BYPASS (Connectors directory hardening 2026-07-02): wrapper around
    ``_check_request_limit`` is the SINGLE choke point through which slowapi runs
    ALL checks (default_limits via RateLimitMiddleware AND @limiter.limit decorators
    of /sources, /compare, /admin/login). CIDRs from CITYSCAPE_RATELIMIT_ALLOWLIST
    (e.g. Anthropic egress: many end users behind few IPs) are not counted there
    and never throttled.
    EXCEPTION /admin*: admin login limit is brute force protection (auth-related,
    HIGH-1) and ALWAYS applies, even for allowlisted IPs (ONLY limit bypass, NO
    auth impact). Allowlist is read freshly per request from settings like ANON_LIMIT
    (test override convention); parse_allowlist is lru-cached, so per request only
    inexpensive CIDR comparison occurs. Fail-safe: empty/broken configuration
    allowlists no one (infra/allowlist.py).
    """
    lim = Limiter(
        key_func=rate_key,
        default_limits=[ANON_LIMIT],
        headers_enabled=True,
        storage_uri=_storage_uri(settings),
    )
    # Set before first request: extension._init preserves existing entries
    # (header_mapping.get(..., default)), so standard names pass through.
    lim._header_mapping.update(_STANDARD_HEADER_MAPPING)

    orig_check = lim._check_request_limit

    def _check_with_allowlist(
        request: Request, endpoint_func, in_middleware: bool = False
    ) -> None:  # noqa: ANN001 - slowapi internal signature (Callable | None)
        if not request.url.path.startswith("/admin") and ip_allowlisted(
            real_client_ip(request), parse_allowlist(Settings().ratelimit_allowlist)
        ):
            # Bypass: no counting, no 429. Set view_rate_limit explicitly to
            # None, because slowapi decorator reads it unchecked after route
            # (request.state raises AttributeError otherwise);
            # _inject_headers is a no-op with None -> no RateLimit headers.
            request.state.view_rate_limit = None
            return
        orig_check(request, endpoint_func, in_middleware)

    # Deliberate hook into private method (internal style: slowapi 0.1.9 is
    # pinned, see _header_mapping above and _Limiter__marked_for_limiting in
    # main.py); slowapi itself provides no request-based exempt hook
    # (exempt_when/_request_filters are called WITHOUT request).
    lim._check_request_limit = _check_with_allowlist
    return lim


# Module limiter with settings-derived storage URI. create_app() does NOT
# overwrite this instance, but wires it to app.state.limiter; storage URI
# is read at import time from (test) settings.
limiter = build_limiter(Settings())
