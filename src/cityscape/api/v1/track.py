"""Tracking beacon: cache-free endpoint that triggers the first-contact push.

Data endpoints (/api/v1/cities/...) are Cloudflare edge-cached
(``respect_origin`` + ``max-age``); a cached hit (cf-cache-status HIT)
does NOT reach the origin, therefore the ``note_first_seen`` middleware does
not fire for a cached data fetch -> a new dev pulling only cached endpoints
would remain unrecorded.

This beacon is intentionally ``no-store`` (Cloudflare never caches it): each call
reaches the origin, the telemetry middleware sees the client and sends on the
FIRST time per IP exactly one ntfy first-contact push (idempotent via the
Redis seen set). The docs page calls it additionally (fire-and-forget) during "Try it".
Intentionally responds empty (204), thus carrying no load/data.

Security: read-only, no query/body input, fixed host; runs behind the same
rate limits/AbuseGuard as the rest (no new attack vector).
"""

from __future__ import annotations

from fastapi import APIRouter, Response

router = APIRouter()


@router.get("/track", include_in_schema=False)
async def track() -> Response:
    """Cache-free first-contact beacon (204). note_first_seen fires in middleware.

    ``Cache-Control: no-store`` prevents Cloudflare/browsers from caching
    the beacon, ensuring every call reaches the origin and the first-contact push
    (once per IP) is reliably triggered. ``include_in_schema=False``: internal
    telemetry path, not part of public data contract.
    """
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
