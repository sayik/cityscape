"""Pooled httpx AsyncClient (RES-01) + descriptive User-Agent (RES-05).

Analogous to the ``infra/redis.py`` create/close pair: exactly ONE ``httpx.AsyncClient``
serves all upstreams. The client is created during lifespan startup
(``create_http_client``) and closed during shutdown via ``close_http_client``.
Pool limits and a conservative default timeout protect against hanging
upstreams; per-source timeout is overridable per request
(``per_source_timeout``) without multiplying the pool. The User-Agent carries
"cityscape" plus repo URL on EVERY request (fair use, T-03-04).
"""

from __future__ import annotations

import httpx

from cityscape import __version__

#: Descriptive User-Agent on EVERY upstream request (RES-05, T-03-04). The version
#: originates from the single source ``cityscape.__version__`` (no hard-coded
#: version string that drifts with releases).
USER_AGENT = (
    f"cityscapeAPI/{__version__} "
    "(+https://github.com/street1983nk/cityscape-api; open data proxy)"
)

#: Process-wide pool singleton. ``create_http_client`` returns the same
#: instance for the same process (shared connection pool, RES-01).
_client: httpx.AsyncClient | None = None


def create_http_client(settings) -> httpx.AsyncClient:
    """Returns the process-wide, pooled AsyncClient (RES-01/05).

    On first call, the client is built and cached; subsequent calls return
    the same instance (one shared pool, no client per request). If the
    cached client was closed in the meantime (lifespan shutdown), a fresh
    one is built. Synchronous (no await during creation).
    """
    global _client
    if _client is None or _client.is_closed:
        user_agent = getattr(settings, "http_user_agent", None) or USER_AGENT
        _client = httpx.AsyncClient(
            headers={"User-Agent": user_agent},  # RES-05: UA on EVERY request
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
                keepalive_expiry=30.0,
            ),
            # Conservative default; overridable per-source per request (T-03-03).
            timeout=httpx.Timeout(connect=2.0, read=5.0, write=5.0, pool=1.0),
            # NO automatic redirects (Audit MEDIUM-1, 2026-06-10): the
            # SSRF invariant of the adapters (hardcoded hosts/allowlists) protects
            # only the FIRST request; a 30x from a (compromised) upstream
            # would otherwise be followed blindly, even to internal targets (metadata IP,
            # redis). A legitimate redirect now manifests as an error and
            # gets noticed during beta smoke/monitoring; the affected adapter
            # then updates specifically to the final URL (like divi_live to www).
            follow_redirects=False,
        )
    return _client


def per_source_timeout(settings, *, source: str) -> httpx.Timeout:
    """Returns the per-source timeout overriding the client default per request.

    The pool remains ONE singleton; only the timeout varies per source (a
    slow source like Wikidata-SPARQL may read longer than a fast
    REST source, pitfall 5).
    Source-specific values come from ``SourceConfig`` starting Phase 4; until then
    the conservative default applies.
    """
    return httpx.Timeout(connect=2.0, read=5.0, write=5.0, pool=1.0)


async def close_http_client(client: httpx.AsyncClient | None) -> None:
    """Closes the pooled client and pool cleanly (no-op on None)."""
    global _client
    if client is not None:
        await client.aclose()
    _client = None
