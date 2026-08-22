"""App-Factory + Middleware-Wiring + Lifespan (Pattern 1, FND-03/04/05).

``create_app()`` verdrahtet Config, Logging, Correlation-ID-Middleware,
CORS-Whitelist (nie '*'), zentrales Error-Mapping und den versionierten
/api/v1-Router. Der Lifespan oeffnet/schliesst den Redis-Pool (lazy).
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import structlog
from asgi_correlation_id import CorrelationIdMiddleware, correlation_id
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import _find_route_handler
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from cityscape import __version__
from cityscape.api.responses import OrjsonResponse

from .api.errors import register_exception_handlers
from .api.v1 import api_v1
from .api.v1.abuse_guard import AbuseGuardMiddleware
from .api.v1.gpt_guard import GPTActionLimitMiddleware
from .api.v1.ratelimit import limiter, real_client_ip
from .charging.poller import maybe_start_eround_poller
from .config import get_settings
from .infra.etag import cache_control_for, compute_etag
from .infra.gpt_actions import is_gpt_action
from .infra.http import close_http_client, create_http_client
from .infra.metrics import incr_daily, incr_request, push_log, record_consumer
from .infra.mobilithek import close_mobilithek_client, create_mobilithek_client
from .infra.redis import close_redis_pool, create_redis_pool
from .logging import configure_logging
from .resilience.breaker_redis import RedisBreakerRegistry
from .resilience.client import ResilientSourceClient
from .transit.poller import maybe_start_gtfs_rt_poller

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Opens the Redis pool and the pooled HTTP client at startup, and closes them at shutdown."""
    settings = get_settings()
    app.state.settings = settings
    app.state.redis = create_redis_pool(
        settings.redis_url, max_connections=settings.redis_max_connections
    )
    # A process-wide, pooled httpx-AsyncClient for all upstreams (RES-01/05).
    app.state.http = create_http_client(settings)
    # Dedicated mTLS client ONLY for Mobilithek (LIVE-04, T-20-MTLS): the
    # The client certificate must never be sent to external hosts, hence a SEPARATE client,
    # NOT app.state.http. Graceful degradation: no pull without certificate + password
    # (None); the live routes then return source_status="disabled".
    if settings.mobilithek_cert_path and settings.mobilithek_cert_password:
        # Fail-open instead of crash (RES core principle): a missing or defective cert
        # (e.g., forgetting to mount a volume) must NEVER prevent the app from starting.
        # Live routes are then degraded to source_status="disabled".
        try:
            app.state.mobilithek_http = create_mobilithek_client(settings)
        except (OSError, ValueError) as exc:
            log.warning(
                "mobilithek_client_init_failed",
                error=str(exc),
                cert_path=str(settings.mobilithek_cert_path),
            )
            app.state.mobilithek_http = None
    else:
        app.state.mobilithek_http = None
    # Process-wide task set for SWR background refresh (Pitfall 3, Plan 03/04).
    app.state.bg_tasks = set()
    # Process-wide, Redis-persistent breaker registry: Breaker state MUST
    # persist across requests (a source triggered in Request A remains open for
    # Request B, RES-04) AND survive deployments/worker boundaries (C-2026). The
    # RedisBreakerRegistry mirrors the state via write-through to Redis and uses
    # wall-clock time (cross-process valid `opened_at`). If Redis fails,
    # it silently degrades to pure in-memory behavior (BreakerRegistry base).
    app.state.breakers = RedisBreakerRegistry(redis=app.state.redis)

    def _schedule(coro):
        """Treats an SWR Refresh coroutine as a long-running task (Pitfall 3).

        Holds a reference in ``app.state.bg_tasks`` to prevent premature
        garbage collection and removes it again upon completion.
        """
        task = asyncio.ensure_future(coro)
        app.state.bg_tasks.add(task)
        task.add_done_callback(app.state.bg_tasks.discard)

    # A single interface for all source adapters starting with Phase 4 (Integration RES-01..05).
    app.state.resilient_client = ResilientSourceClient(
        http=app.state.http,
        redis=app.state.redis,
        breakers=app.state.breakers,
        schedule=_schedule,
    )
    # GTFS-RT Background Poller (Phase 19): Parses the feed ONCE per schedule cycle into
    # Redis (NEVER in the request path, T-19-REQPARSE). Runs only when enable_gtfs_rt is True
    # and the source can be resolved (gtfs_de always; mobilithek_delfi only with a certificate
    # and subscription ID); uses the existing _schedule/bg_tasks pattern (GC protection). By
    # default (enable_gtfs_rt False), NO task is created (no break in behavior).
    maybe_start_gtfs_rt_poller(app, settings, _schedule)
    # eRound Allocation Poller (DATA-42): Accumulates the drain queue deltas of the
    # dynamic eRound subscription in Redis (based on the GTFS-RT Poller pattern). Only when
    # enable_eround_charging + Cert + Subscription ID are active; otherwise, NO task (no break in behavior).
    maybe_start_eround_poller(app, settings, _schedule)
    try:
        yield
    finally:
        # First cancel long-running background tasks (GTFS-RT poller, SWR refresh),
        # so that no task continues to access http/redis after the pool closes. The
        # poller catches the CancelledError and terminates cleanly (Phase 19).
        for task in list(app.state.bg_tasks):
            task.cancel()
        # Order: Close the HTTP pools first, then Redis.
        await close_http_client(app.state.http)
        if app.state.mobilithek_http is not None:
            await close_mobilithek_client(app.state.mobilithek_http)
        await close_redis_pool(app.state.redis)


def _etag_payload(body: bytes, request_id: str | None) -> bytes:
    """Overrides the per-request `correlation_id` for the ETag calculation.

    The ETag is intended to represent the stable resource content, not the
    correlation_id that is generated anew for each request. If the current ID is
    included in the body, only that specific occurrence is replaced with a fixed placeholder
    (for hashing purposes only); the delivered body remains unchanged. If there is no
    known ID (no match), the body is hashed as-is.
    """
    if not request_id:
        return body
    needle = request_id.encode()
    if needle not in body:
        return body
    return body.replace(needle, b"__etag_stable_correlation_id__")


class ETagMiddleware(BaseHTTPMiddleware):
    """ETag/Cache-Control + conditional GET (API-08, Pattern 4).

    Processes ONLY successful GET reads (status 200): reads the final
    response body (OrjsonResponse returns bytes), calculates a
    stable ETag from it, and sets Cache-Control for each resource. If the
    ``If-None-Match`` request header matches the calculated ETag, a
    304 response without a body is returned (ETag and Cache-Control are preserved). Error
    envelopes, 503 responses, non-GET requests, and streaming requests are NEVER handled (anti-pattern,
    T-11-ETAG-LEAK). ``If-None-Match`` is only compared; it is never used as a cache
    key (T-11-ETAG-POISON).

    Order (Pitfall 5): This middleware must see the final body, so
    it must be close to the response (added first = executed last); CORS
    is excluded.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)

        # Cache only successful GET reads; leave everything else unchanged.
        if request.method != "GET" or response.status_code != 200:
            return response

        # Merge the final body from the streaming iterator (BaseHTTPMiddleware
        # returns a StreamingResponse) without losing it for the client.
        body = b"".join([chunk async for chunk in response.body_iterator])

        # ETag based on the STABLE resource content: the correlation_id (meta.correlation_id) generated anew for each request
        # is request noise and must not cause the
        # ETag to vary; otherwise, If-None-Match will never match -> no 304.
        # We therefore hash a variant with the correlation_id neutralized; the
        # DELIVERED body retains the real ID unchanged.
        etag = compute_etag(_etag_payload(body, correlation_id.get()))
        response.headers["ETag"] = etag
        # Derive the resource from the path segment to /api/v1/<resource>; falls
        # back on to the default in cache_control_for if unknown.
        parts = [p for p in request.url.path.split("/") if p]
        resource = parts[2] if len(parts) > 2 else None
        response.headers["Cache-Control"] = cache_control_for(resource)

        # Conditional GET: If-None-Match == ETag -> 304 with no body. Headers
        # (ETag/Cache-Control + existing headers, e.g., Correlation-ID) are preserved.
        if request.headers.get("if-none-match") == etag:
            not_modified = Response(status_code=304, headers=dict(response.headers))
            del not_modified.headers["content-length"]
            return not_modified

        return Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )


class MetricsMiddleware(BaseHTTPMiddleware):
    """Log capture for the admin dashboard (OPS-01/OPS-02).

    Measures the processing time for each request (``time.perf_counter`` BEFORE/AFTER
    ``call_next``) and, upon completion, writes a COMPACT log entry (time,
    method, path, status, duration, request_id) to the capped Redis circular buffer
    plus a request counter (total + status + endpoint). ONLY
    request metadata ends up in the buffer; NEVER headers/body/cookies (T-13-02-06).

    Order (Pitfall 1/5): MetricsMiddleware needs the final status AND the
    correlation_id. ``CorrelationIdMiddleware`` must therefore run BEFORE MetricsMiddleware
    (= added later, since Starlette executes last-added-first) so that
    ``correlation_id.get()`` is already set in the dispatch.

    Every Redis access is wrapped in a try/except block: a loss of metrics NEVER crashes the
    request path (graceful degradation, pattern from metrics.py).
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        dauer_ms = round((time.perf_counter() - start) * 1000, 1)

        # Normalize the endpoint path for the counter hash to the route template
        # (no unrestricted cardinality due to slugs): prefers the matched
        # route template (scope[“route”].path), otherwise the raw URL path.
        route = request.scope.get("route")
        endpoint = getattr(route, "path", None) or request.url.path

        # Mark MCP actions: The remote MCP server marks its internal
        # calls with X-cityscape-Mcp (value = resource). This makes MCP actions visible in the
        # dashboard (separate field + separate counter “mcp:<endpoint>”) and
        # prevents them from being mixed with normal API traffic (owner’s request: track MCP).
        mcp_resource = request.headers.get("x-cityscape-mcp")
        # Mark GPT actions (OpenAI header/ChatGPT-UA, infra/gpt_actions):
        # Create a separate “gpt” channel, similar to “mcp,” so that ChatGPT traffic is visible in the dashboard/
        # digest and is not mixed with API traffic.
        via_gpt = not mcp_resource and is_gpt_action(request.headers)

        try:
            redis = request.app.state.redis
            entry = {
                "zeit": datetime.now(UTC).isoformat(),
                "methode": request.method,
                "pfad": request.url.path,
                "status": response.status_code,
                "dauer_ms": dauer_ms,
                "request_id": correlation_id.get(),
            }
            if mcp_resource:
                entry["via_mcp"] = True
                entry["mcp_ressource"] = mcp_resource
            if via_gpt:
                entry["via_gpt"] = True
            if mcp_resource:
                counter_endpoint = f"mcp:{endpoint}"
            elif via_gpt:
                counter_endpoint = f"gpt:{endpoint}"
            else:
                counter_endpoint = endpoint
            await push_log(redis, entry)
            await incr_request(
                redis,
                endpoint=counter_endpoint,
                status_code=response.status_code,
            )
            # Active Consumer Tracking (only actual data requests at /api/v1/, excluding
            # Health/OpenAPI): hourly count + latest metadata per client IP or
            # “mcp” for internal MCP calls. Feeds into the hourly ntfy digest.
            p = request.url.path
            if p.startswith("/api/v1/") and not p.startswith(
                ("/api/v1/health", "/api/v1/openapi")
            ):
                now = datetime.now(UTC)
                if mcp_resource:
                    ident = "mcp"
                elif via_gpt:
                    # Aggregated as “mcp” (deliberately NOT the ephemeral user ID:
                    # limited cardinality of the hourly buckets); the pseudonymous
                    # user identifier is included in the per-call push (note_gpt_action).
                    ident = "gpt"
                else:
                    ident = real_client_ip(request)
                await record_consumer(
                    redis,
                    ident=ident,
                    user_agent=request.headers.get("user-agent", ""),
                    path=request.url.path,
                    status_code=response.status_code,
                    now=now,
                )
                # Daily counter per channel (api|mcp|gpt) for the daily 00:05-
                # digest. Same scope as consumer tracking (only actual
                # data requests at /api/v1/, excluding Health/OpenAPI).
                if mcp_resource:
                    channel = "mcp"
                elif via_gpt:
                    channel = "gpt"
                else:
                    channel = "api"
                await incr_daily(redis, channel=channel, now=now)
        except Exception as exc:  # noqa: BLE001 - A metrics failure never crashes the request
            # Graceful degradation: a metrics/Redis error must never crash the request path;
            # log it only for debugging (avoids S110 bare pass).
            log.debug("metrics_middleware_failed", error=str(exc))

        # First-contact notification: Notifies via ntfy when a new developer (based on
        # client IP) uses the API for the first time. Self-contained and best-effort,
        # never crashes the request. Hooked after `call_next` (path is then known).
        try:
            pass  # First-contact telemetry is private (removed from the public build)
        except Exception as exc:  # noqa: BLE001 - The initial contact push never causes the request to crash
            log.debug("first_seen_middleware_failed", error=str(exc))

        # Track MCP actions via ntfy (only triggers when the MCP header is set).
        # Custom encapsulation, best-effort, never crashes the request.
        try:
            pass  # MCP telemetry is private (removed from the public build)
        except Exception as exc:  # noqa: BLE001 - MCP-Push never crashes the request
            log.debug("mcp_action_middleware_failed", error=str(exc))

        # Track GPT activity via ntfy (triggers only when ChatGPT
        # traffic is detected). Custom wrapper, best-effort, never crashes the request.
        try:
            await note_gpt_action(
                request,
                settings=request.app.state.settings,
                status_code=response.status_code,
            )
        except Exception as exc:  # noqa: BLE001 - GPT-Push never crashes the request
            log.debug("gpt_action_middleware_failed", error=str(exc))

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Applies the `limiter-default_limits` to EVERY route (Live Report M2).

    Background: The `slowapi-``@limiter.limit`` decorator is only applied to a few routes
    (/sources, /compare, /admin/login). The remaining City/Meta GET requests had NO
    decorator, so neither the IP limit (60/min) nor RateLimit
    headers were applied there. This middleware calls the limiter with ``in_middleware=True``
    : SlowAPI then applies the ``default_limits`` (ANON_LIMIT) to all routes NOT marked by
    decorator, and skips those that are already decorated (to avoid
    double-counting).

    Why NOT use the included ``SlowAPIMiddleware``: its synchronous
    429 path falls back to SlowAPI’s own default handler as soon as the
    registered ``RateLimitExceeded`` handler is asynchronous (our Envelope handler
    is asynchronous) and crashes there (``exc.detail``). This middleware returns the 429
    directly via the central ErrorEnvelope instead (same form as
    the asynchronous handler) and injects the RateLimit headers in both cases.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        limiter_obj = request.app.state.limiter
        if not getattr(limiter_obj, "enabled", True):
            return await call_next(request)

        handler = _find_route_handler(request.app.routes, request.scope)

        # Do NOT check routes WITH their own @limiter.limit decorator here: their
        # auto_check decorator handles this itself (sources/compare with ANON_LIMIT,
        # admin/login with ADMIN_LOGIN_LIMIT). Otherwise, slowapi-0.1.9 in the
        # middleware path would apply the default ADDITIONALLY (empty route_limits ->
        # combined_defaults=True), which would skew the limits (double counting).
        marked = getattr(limiter_obj, "_Limiter__marked_for_limiting", {})
        if handler is not None:
            handler_name = f"{handler.__module__}.{handler.__name__}"
            if handler_name in marked:
                return await call_next(request)
        try:
            # in_middleware=True: applies default_limits to undecorated routes,
            # skips those marked with @limiter.limit (whose decorator checks them itself).
            limiter_obj._check_request_limit(request, handler, in_middleware=True)
        except RateLimitExceeded:
            # Central 429 envelope (identical to the async handler in errors.py),
            # plus RateLimit header. Local import prevents loops during module loading.
            from .api.errors import _envelope

            response = _envelope(
                429,
                "rate_limited",
                "Rate limit exceeded.",
                hint=(
                    "Bitte etwas warten und spaeter erneut versuchen "
                    "(RateLimit-Header beachten)."
                ),
            )
            view_limit = getattr(request.state, "view_rate_limit", None)
            if view_limit is not None:
                limiter_obj._inject_headers(response, view_limit)
            return response

        response = await call_next(request)
        # If successful, inject the RateLimit headers into the response (D-02).
        view_limit = getattr(request.state, "view_rate_limit", None)
        if view_limit is not None:
            response = limiter_obj._inject_headers(response, view_limit)
        return response


def create_app() -> FastAPI:
    """Baut und verdrahtet die FastAPI-App (testbare Factory)."""
    settings = get_settings()
    configure_logging(settings.log_level)

    # Fail-fast for admin subconfiguration (Audit LOW-3, 2026-06-10): if ONLY
    # the password is set (without a session secret), a successful login
    # would crash with a 500 error when writing to `request.session` (session
    # middleware not mounted). Not a bypass, but a hidden defect; therefore,
    # abort immediately at startup instead of waiting until the first login.
    if bool(settings.admin_password) != bool(settings.admin_session_secret):
        raise RuntimeError(
            "Admin subconfiguration: CITYSCAPE_ADMIN_PASSWORD and "
            "CITYSCAPE_ADMIN_SESSION_SECRET must BOTH be set or BOTH "
            "leer sein (fail-closed)."
        )

    app = FastAPI(
        title="cityscape API",
        version=__version__,
        default_response_class=OrjsonResponse,
        lifespan=lifespan,
    )

    # Order (Pitfall 1/5): Last added = executed FIRST in the request.
    # Execution order of a request (outer -> inner):
    #   CORS -> Session -> CorrelationId -> Metrics -> ETag -> RateLimit -> Route.
    # Reasoning behind the relative order of Metrics/CorrelationId/ETag/RateLimit:
    #   - RateLimit is at the very innermost layer (added last): it reliably matches the final route handler
    #     and injects the RateLimit headers into the route response;
    #     ETag (further out) copies them via `dict(response.headers)` (including to
    #     the 304 response), while CORS remains on the outside.
    #   - ETag must see the FINAL body -> close to the route.
    #   - Metrics needs the final status AND the correlation_id; CorrelationId
    #     must therefore run BEFORE Metrics (= CorrelationId added later than Metrics).
    #   - SessionMiddleware far out (executed early) so that request.session
    #     is available before the inline auth guard for the /admin routes.
    #   - CORS remains at the very end (added last).
    #
    # RateLimitMiddleware (Live Report M2): Applies the limiter's default_limits
    # (ANON_LIMIT, default 60/min per IP) to EVERY route, including the
    # city/meta GETs that do not have their own @limiter.limit decorator. Without this middleware
    # only the per-route decorator limit (admin-login) was enforced; the GET reads remained
    # unthrottled and without a RateLimit header.
    # GPT-Action limit added BEFORE RateLimitMiddleware -> runs immediately AFTER
    # (innermost protection layer). Backstop per ChatGPT user for OpenAI egress IPs
    # OpenAI egress IPs exempted from the IP limit; triggers ONLY when
    # GPT action traffic is detected (details: api/v1/gpt_guard.py).
    app.add_middleware(GPTActionLimitMiddleware)
    app.add_middleware(RateLimitMiddleware)
    # AbuseGuard added AFTER RateLimitMiddleware -> runs just BEFORE it (Starlette:
    # last added = outermost layer = executed first). Coarse, low-cost
    # pre-filter against distributed bots (subnet limit + optional CF bot score block)
    # before the more granular per-IP limit. Scraping hardening; details: abuse_guard.py.
    app.add_middleware(AbuseGuardMiddleware)
    app.add_middleware(ETagMiddleware)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    # SessionMiddleware only if a session secret is configured (fail-closed,
    # T-13-02-02): without a secret, there is no admin login. HttpOnly is the Starlette
    # default; SameSite=Strict + Secure(Prod) + max_age 8h protect the cookie.
    if settings.admin_session_secret:
        app.add_middleware(
            SessionMiddleware,
            secret_key=settings.admin_session_secret.get_secret_value(),
            session_cookie="cs_admin",
            same_site="strict",
            https_only=settings.admin_cookie_https_only,
            max_age=60 * 60 * 8,
        )
    # Keyless, public read API: “*” is the default (see config.py). “*”
    # and allow_credentials=True are mutually exclusive according to the CORS spec -> Credentials
    # are only allowed if explicitly whitelisted. Admin is same-origin and therefore CORS-neutral.
    cors_wildcard = "*" in settings.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=not cors_wildcard,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    # StaticFiles mount for admin.css (B1): check_dir=False prevents a
    # RuntimeError if the directory is still empty or does not exist when the app starts.
    # Absolute path relative to the package via Path(__file__).parent.
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "static", check_dir=False),
        name="static",
    )

    # Rate Limiter (API-06): slowapi reads app.state.limiter for each request and
    # injects the (normalized) RateLimit headers into successful responses from
    # routes annotated with @limiter.limit. The 429 handler is wired into
    # register_exception_handlers (Envelope instead of the slowapi default).
    app.state.limiter = limiter

    register_exception_handlers(app)
    app.include_router(api_v1)
    # Admin Router (OPS-01): The prefix /admin is set in the router, NOT /api/v1.
    return app


app = create_app()
