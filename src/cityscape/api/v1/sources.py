"""Source status route /sources (API-03).

Lists each known upstream source's ``enabled`` state (from the
``enable_*`` settings) and its circuit breaker state (CLOSED/OPEN/HALF_OPEN from
the process-wide ``app.state.breakers`` registry). This allows clients and agents
to see at a glance which source is active and whether its breaker has tripped
(graceful degradation transparency).

The breaker is created lazily via the existing ``BreakerRegistry``; a breaker
never called before reports its default state CLOSED. NO custom
HTTPException/try-except with detail leak: the central handler remains responsible.
"""

from __future__ import annotations

from asgi_correlation_id import correlation_id
from fastapi import APIRouter, Depends, Request, Response

from cityscape.api.v1.pagination import PageParams, page_params, paginate
from cityscape.api.v1.ratelimit import ANON_LIMIT, limiter
from cityscape.registry.source_specs import KNOWN_SOURCES as _KNOWN_SOURCES
from cityscape.registry.source_specs import SOURCE_LICENSE

router = APIRouter()

# Allowlist of sortable/filterable fields for /sources (T-11-FILTER-INJ): only
# these field names are allowed as sort, unknown field -> 400 BEFORE raw
# user string is interpreted (never interpolated into a query/cache key).
_SOURCES_SORT_WHITELIST = {"source", "enabled", "license"}

# _KNOWN_SOURCES (order = public /sources order) and
# SOURCE_LICENSE (license + verbatim attribution, VERBATIM from
# DATA-LICENSES.md, fail-closed via tests/unit/test_source_license_map.py)
# now originate from declarative source registry (registry/source_specs.py),
# so that a new source needs only ONE entry there instead of many scattered
# places. Both names are imported above (backwards compatibility).


@router.get("/sources")
@limiter.limit(ANON_LIMIT)
async def sources(
    request: Request,
    response: Response,
    page: PageParams = Depends(page_params),  # noqa: B008 - FastAPI dependency idiom
) -> dict:
    """Lists per source enabled (from settings) + breaker state (API-03).

    Rate-limited (API-06): @limiter.limit below @router.get, ``request`` is
    mandatory param (Pitfall 4). ``response`` is mandatory so slowapi can inject
    standard RateLimit headers into the success response; on limit breach
    the 429 envelope handler takes over.

    Keyless/open: no API key required, IP limit (ANON_LIMIT) applies to everyone.

    Paginated (API-04, REST Best Practice #3/#8): ``Depends(page_params)`` reads
    page/limit/offset/sort/order; ``paginate`` slices the page allowlist-
    protected (unknown sort -> 400, T-11-FILTER-INJ) and returns an empty list
    with 200 on offset overflow (never 500). ``limit > MAX_LIMIT`` is rejected as
    422 via ``Query(le=MAX_LIMIT)``.
    """
    settings = request.app.state.settings
    breakers = request.app.state.breakers

    data = [
        {
            "source": name,
            "enabled": bool(getattr(settings, f"enable_{name}", False)),
            "breaker_state": breakers.get(name).state.value,
            "license": SOURCE_LICENSE.get(name, {}).get("license_id"),
            "attribution": SOURCE_LICENSE.get(name, {}).get("attribution"),
        }
        for name in _KNOWN_SOURCES
    ]

    # Allowlist-protected sorting BEFORE slicing (sort only from allowlist,
    # otherwise 400 in paginate). order controls direction, both are validated.
    if page.sort:
        data.sort(
            key=lambda row: (row.get(page.sort) is None, row.get(page.sort)),
            reverse=(page.order == "desc"),
        )

    page_items = paginate(data, page, sort_whitelist=_SOURCES_SORT_WHITELIST)
    return {
        "data": page_items,
        "meta": {
            "correlation_id": correlation_id.get(),
            "page": page.page,
            "limit": page.limit,
            "offset": page.offset,
            "total": len(data),
        },
    }
