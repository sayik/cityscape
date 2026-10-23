"""Pagination contracts (API-04): PageParams + page_params + paginate.

Opt-in list pagination (D-07): page/limit/offset + allowlist for sort/order.
``limit`` is capped at ``MAX_LIMIT`` (200 with capped page instead of 5xx,
Best Practice #8): the central RequestValidationError handler maps to 400, but an
excessive limit should NOT be considered an invalid_request, so in
``page_params`` it is capped via ``min(limit, MAX_LIMIT)`` instead of being
rejected via ``le=``. Allowlist violation on sort/order -> ``ValidationFailedError`` (400)
BEFORE raw user string is interpreted (T-11-FILTER-INJ). Offset overflow ->
Python slice yields ``[]`` (200, never 500, Best Practice #8).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query

from cityscape.api.errors import ValidationFailedError

# Defaults + hard upper limit for page limit (cap via Query(le=MAX_LIMIT)).
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


@dataclass
class PageParams:
    """Validated pagination parameters of a list GET."""

    page: int
    limit: int
    offset: int
    sort: str | None
    order: str


def page_params(
    page: int = Query(1, ge=1),
    limit: int = Query(DEFAULT_LIMIT, ge=1),
    offset: int = Query(0, ge=0),
    sort: str | None = Query(None),
    order: str = Query("asc"),
) -> PageParams:
    """FastAPI dependency: parses + validates page/limit/offset/sort/order.

    ``limit`` is capped via ``min(limit, MAX_LIMIT)`` (capped 200 page
    instead of 5xx/4xx, Best Practice #8), not rejected hard via ``le=``.
    """
    if order not in ("asc", "desc"):
        raise ValidationFailedError(
            "order muss 'asc' oder 'desc' sein.",
            hint="Erlaubt: asc, desc.",
        )
    limit = min(limit, MAX_LIMIT)
    return PageParams(page=page, limit=limit, offset=offset, sort=sort, order=order)


def paginate(items: list, p: PageParams, *, sort_whitelist: set[str]) -> list:
    """Slices a page out of ``items`` (allowlist protected).

    sort not in allowlist -> ValidationFailedError(400). Offset overflow
    yields an empty list via Python slicing (200, never 500).
    """
    if p.sort and p.sort not in sort_whitelist:
        raise ValidationFailedError(
            f"Unbekanntes sort-Feld '{p.sort}'.",
            hint=f"Erlaubt: {', '.join(sorted(sort_whitelist))}.",
        )
    start = p.offset if p.offset else (p.page - 1) * p.limit
    return items[start : start + p.limit]


def _parse_int_param(raw: str | None, *, name: str, minimum: int, default: int) -> int:
    """Parses a raw query string into an int with a minimum value (or default).

    ``None`` (parameter not set) -> ``default``. Non-numeric or below
    ``minimum`` -> ``ValidationFailedError`` (400 invalid_request) BEFORE the value
    enters a slice index (T-chc-03). No raw string reaches slice semantics.
    """
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationFailedError(
            f"Ungueltiger Wert fuer '{name}': '{raw}'.",
            hint=f"'{name}' muss eine ganze Zahl >= {minimum} sein.",
        ) from None
    if value < minimum:
        raise ValidationFailedError(
            f"Ungueltiger Wert fuer '{name}': {value}.",
            hint=f"'{name}' muss eine ganze Zahl >= {minimum} sein.",
        )
    return value


def parse_page_params(request, *, default_limit: int = DEFAULT_LIMIT) -> PageParams:
    """Parses limit/offset (and page) from ``request.query_params`` (without Depends).

    Counterpart to ``page_params`` for routes/helpers where FastAPI
    ``Depends`` is not used (e.g. shared OSM helper and store routes that read
    the query themselves). Mirrors validation of ``page_params``:
    ``limit`` >= 1 (default ``default_limit``, configurable per endpoint),
    ``offset`` >= 0, ``page`` >= 1; non-numeric/too small -> 400 invalid_request;
    ``limit`` is capped via ``min(limit, MAX_LIMIT)`` (capped page instead of
    error, Best Practice #8).

    ``sort``/``order`` are INTENTIONALLY not offered for these data type lists:
    underlying lists carry no guaranteed, stable server-side sort order,
    so promising ``sort`` would be dishonest. They remain fixed at
    ``None`` / ``"asc"``, so ``paginate_envelope`` slices purely via offset/limit.
    """
    qp = request.query_params
    limit = _parse_int_param(
        qp.get("limit"), name="limit", minimum=1, default=default_limit
    )
    offset = _parse_int_param(qp.get("offset"), name="offset", minimum=0, default=0)
    page = _parse_int_param(qp.get("page"), name="page", minimum=1, default=1)
    limit = min(limit, MAX_LIMIT)
    return PageParams(page=page, limit=limit, offset=offset, sort=None, order="asc")


def paginate_envelope(
    data: dict,
    meta: dict,
    p: PageParams,
    *,
    list_key: str,
    delivered_count_field: str | None = None,
) -> None:
    """Caps an envelope list HONESTLY and indicates the slice in meta.

    Slices ``data["payload"][list_key]`` to page ``[offset:offset+limit]``
    (offset overflow -> empty list, NO error, Best Practice #8) and sets
    ``meta["pagination"]`` = total/returned/limit/offset/truncated (no silent
    caps, CLAUDE.md "No silent caps"). Item values are NOT rewritten, only
    list length changes (T-chc: slice/omission only).

    ``delivered_count_field`` (PoiPayload case only): if set,
    ``payload[delivered_count_field]`` is set to delivered page length
    (PoiPayload semantics: ``count`` = delivered items) and, if a
    ``truncated`` field exists, updated to ``(total > returned) or previous value``;
    ``total_available`` remains untouched (true overall total).
    If ``delivered_count_field`` is ``None`` (energy/charging/events), aggregated
    metrics (count/by_type/total_power_kw) remain UNTOUCHED: the payload
    still describes the full snapshot, ``meta.pagination`` the delivered
    page (Condition 2, honest separation of aggregate vs. page).

    Defensive: missing ``payload`` or ``list_key`` or not a ``list`` -> no-op.
    """
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return
    items = payload.get(list_key)
    if not isinstance(items, list):
        return

    total = len(items)
    page = items[p.offset : p.offset + p.limit]
    payload[list_key] = page
    returned = len(page)

    meta["pagination"] = {
        "total": total,
        "returned": returned,
        "limit": p.limit,
        "offset": p.offset,
        "truncated": p.offset + returned < total,
    }

    if delivered_count_field is not None:
        payload[delivered_count_field] = returned
        if "truncated" in payload:
            payload["truncated"] = (total > returned) or bool(payload.get("truncated"))
