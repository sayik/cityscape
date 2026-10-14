"""ETag/Cache-Control contracts (API-08): compute_etag + CACHE_TTL map.

``compute_etag`` builds a stable ETag from the serialized response body
(sha256 idiom analogous to infra/cache.py:build_cache_key, here over body bytes). The
ETag is calculated server-side; If-None-Match is only compared, never used as
a cache key (cache poisoning protection). The TTL map yields the Cache-Control
window (seconds) per resource; ``default`` applies otherwise.

The ETag/304 middleware itself (only cache GET/200, never error envelopes) is
wired up in Wave 3; here the importable helper contracts are defined.
"""

from __future__ import annotations

import hashlib

# Cache-Control TTL per resource (seconds). default applies if no
# specific resource matches. Additively extensible without logic changes.
CACHE_TTL = {
    "dwd": 1800,
    "uba": 600,
    "wikidata": 86400,
    "default": 300,
}

# Resources that must NEVER be cached by CDN/browser -> "no-store".
# Real-time endpoints under /api/v1/live/* (resource segment "live":
# HVV departures, GTFS-RT transit, Dortmund parking, Koeln/Berlin live, etc.)
# provide data changing by the minute. Without no-store, Cloudflare caches the
# response up to its browser cache TTL (observed: 4 h override despite
# origin max-age=300) and serves live data heavily stale; a transient
# no_data state would remain frozen for hours. no-store keeps /live/
# cache-free (origin load remains low because the resilient Redis cache sits
# in front). Clients control their polling frequency via meta.refresh_seconds.
NO_STORE_RESOURCES = frozenset({"live", "track"})


def compute_etag(body: bytes) -> str:
    """ETag from serialized body: quoted sha256[:32] hex.

    Deterministic over the raw response bytes (ORJSONResponse produces
    bytes). Same body -> same ETag -> If-None-Match match -> 304.
    """
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def cache_control_for(resource: str | None = None) -> str:
    """Cache-Control value per resource from the CACHE_TTL map.

    Selects the matching max-age TTL ("public, max-age=<ttl>"); falls back to
    ``default`` (300 s) if no specific resource matches. The value is additively
    extensible without changing middleware logic.

    Resources in ``NO_STORE_RESOURCES`` (real-time endpoints /api/v1/live/*)
    return ``no-store`` instead so Cloudflare/browser do not cache them (otherwise
    live data becomes stale up to the CDN browser TTL).
    """
    if resource in NO_STORE_RESOURCES:
        return "no-store"
    ttl = CACHE_TTL.get(resource or "default", CACHE_TTL["default"])
    # stale-while-revalidate + stale-if-error (security hardening 2026-06-21):
    # After max-age expires, a shared cache (Cloudflare) serves the response
    # IMMEDIATELY and revalidates asynchronously in the background -> no thundering
    # herd on origin for popular endpoints (smoothing DoS/scraping load).
    # stale-if-error keeps the API responsive during origin overload/outage
    # (the CDN serves the last good response instead of an error). Window =
    # ttl. Only applies to a shared cache; browsers generally ignore swr.
    return f"public, max-age={ttl}, stale-while-revalidate={ttl}, stale-if-error={ttl}"
