"""City registry library: major cities + lookup with 404 path (CORE-03/CORE-04).

Re-exports ``CityRegistryEntry`` model and ``CITY_REGISTRY``
constant, and provides ``get_city`` lookup. An unknown slug raises
``NotFoundError`` (from existing Phase 1 error infrastructure), mapped by
the central handler to the uniform 404 envelope with hint. The
layer coupling registry -> api/errors is a deliberate, documented
MVP decision (02-RESEARCH Pattern 4 variant a / Open Question 2).
"""

from __future__ import annotations

from cityscape.api.errors import NotFoundError
from cityscape.registry.catalog import CITY_DATA_CATALOG
from cityscape.registry.cities import _BY_SLUG, CITY_REGISTRY
from cityscape.registry.models import CityRegistryEntry

__all__ = [
    "CITY_REGISTRY",
    "CityRegistryEntry",
    "get_city",
    "list_cities",
]

# Known per-city sub-resources (data type keys from catalog + meta-
# discovery resource "overview"). Used for DX hint: if someone calls
# /cities/<datatype> instead of /cities/<city>/<datatype>, the "slug" is
# actually a data type, not a city -> targeted correction hint.
_CITY_SUBRESOURCES: frozenset[str] = frozenset(
    {dt.key for dt in CITY_DATA_CATALOG} | {"overview"}
)


def _unknown_city_hint(slug: str) -> str:
    """Builds the 404 hint for an unknown city slug.

    If the slug is actually a data type (e.g. ``overview``, ``crime-stats``),
    the caller likely forgot the city slug
    (``/cities/overview`` instead of ``/cities/<city>/overview``); then additionally
    reference the per-city path. Otherwise generic city list hint.
    """
    base = "Nutze GET /api/v1/cities fuer alle unterstuetzten Staedte."
    key = slug.lower()
    if key in _CITY_SUBRESOURCES:
        return (
            f"'{slug}' ist eine Datenart, keine Stadt. Du hast vermutlich den "
            f"Stadt-Slug vergessen, z.B. GET /api/v1/cities/berlin/{key}. " + base
        )
    return base


def get_city(slug: str) -> CityRegistryEntry:
    """Returns the city entry for slug (case-insensitive) or raises 404."""
    entry = _BY_SLUG.get(slug.lower())
    if entry is None:
        raise NotFoundError(
            f"Unbekannte Stadt '{slug}'.",
            hint=_unknown_city_hint(slug),
        )
    return entry


def list_cities() -> tuple[CityRegistryEntry, ...]:
    """Returns all registered cities (28 core + >100k population expansion)."""
    return CITY_REGISTRY
