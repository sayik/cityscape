"""Public per-city coverage map of partially covered endpoints.

Honesty over empty promises (owner decision 2026-06-13): some
endpoints only cover curated cities. Previously they returned an empty
``source_status="ok"`` for an uncovered city (looked like "no
incident"), which concealed the lack of coverage. Instead, the routes
now return ``source_status="not_covered"`` (200, ``data: null``) and
list the covered cities in the meta block (``covered_cities``). ``not_covered``
is clearly distinguishable from ``no_data`` (city covered, currently no
data) and from 404 (city unknown).

This module is the SINGLE source of truth for coverage and is DERIVED from
curated adapter city maps (no duplicating slug lists):
- ``flood``    -> ``adapters.lhp._CITY_PEGEL`` (curated gauge per city)
- ``webcams``  -> ``adapters.autobahn._CITY_ROADS`` (curated highways)
- ``traffic``  -> ``adapters.autobahn._CITY_ROADS`` (same map as webcams)
- ``road-events`` -> ``api.v1.cities.CONNECTOR_MAP`` (curated city connectors)

Since ``CONNECTOR_MAP`` lives in ``cities.py`` (with fetch_fn/mapper tuples) and
``cities.py`` imports this module, the road-events list is mirrored here
instead of imported (circular import avoidance). A module assertion in ``cities.py``
verifies equality of both lists and catches drift hard on import.

NOT partially covered (intentionally NOT in this map):
- ``water-level``: geo-proximity without curated city map; already returns
  honest ``no_data`` when no nearby station exists (dynamic, nationwide on
  federal waterways).
- ``live/transit/*``: nationwide GTFS-RT feed without structural city boundary;
  ``no_data`` on empty Redis remains the honest verdict.
All other city/live endpoints are fully covered nationwide (84/84).
"""

from __future__ import annotations

from cityscape.adapters.autobahn import _CITY_ROADS
from cityscape.adapters.baumkataster import BAUM_WFS
from cityscape.adapters.boris import BORIS_SHAPEFILE, BORIS_WFS
from cityscape.adapters.denkmal import DENKMAL_WFS
from cityscape.adapters.lhp import _CITY_PEGEL
from cityscape.adapters.parkendd import PARKENDD_CITIES
from cityscape.registry.cities import CITY_REGISTRY

# road-events: mirrored from ``api.v1.cities.CONNECTOR_MAP`` (see module docstring).
# The assertion in cities.py keeps this list synchronized with CONNECTOR_MAP.
_ROAD_EVENTS_CITIES: frozenset[str] = frozenset(
    {
        "berlin",
        "koeln",
        "hamburg",
        "muenchen",
        "stuttgart",
        "bremen",
        "dortmund",
        "dresden",
        "leipzig",
    }
)

# sharing (DATA-33): mirrored from ``api.v1.cities.GBFS_SYSTEMS`` (curated
# Nextbike GBFS systems per city). As with road-events, the source map lives in
# cities.py (which imports this module), so the slug set is mirrored here
# and kept drift-synchronized via module assertion in cities.py.
_SHARING_CITIES: frozenset[str] = frozenset(
    {
        "berlin",
        "muenchen",
        "koeln",
        "frankfurt-am-main",
        "duesseldorf",
        "dresden",
        "leipzig",
        "hannover",
        "nuernberg",
        "bremen",
        "braunschweig",
        "freiburg-im-breisgau",
        "karlsruhe",
        "aachen",
        "kassel",
        "wiesbaden",
        "oldenburg",
        "potsdam",
        "bielefeld",
        "moenchengladbach",
        "mannheim",
        "heidelberg",
        "ludwigshafen-am-rhein",
        "hanau",
        "leverkusen",
    }
)

# station-departures/-arrivals (DATA-34/36): NO longer partially covered. The main
# station EVAs per city are derived from StaDa catalog
# (api.v1.cities._resolve_city_station_evas) -> full coverage across all 84
# cities. Therefore no PARTIAL_COVERAGE entry (no not_covered) anymore.

# land-values (DATA-35): BORIS is federated per federal state -> covered are
# exactly those registry cities whose state (``state``) has either an open
# WFS (``BORIS_WFS``) OR an open shapefile download (``BORIS_SHAPEFILE``,
# NW/ST). DERIVED directly from both maps + registry (no duplication): a
# new state expands coverage automatically.
_BORIS_STATES = set(BORIS_WFS) | set(BORIS_SHAPEFILE)
_LAND_VALUES_CITIES: frozenset[str] = frozenset(
    c.slug for c in CITY_REGISTRY if c.state in _BORIS_STATES
)

# solar-roofs (DATA-39): rooftop solar cadastre is federated per federal state (like
# BORIS). NRW pilot from official municipality aggregate (seed) -> covered are
# registry cities in NRW. Another state expands coverage as soon as its seed
# is available (then add state code here).
_SOLAR_CADASTRE_STATES = {"NW", "BY", "BE", "HH", "BB"}
_SOLAR_ROOFS_CITIES: frozenset[str] = frozenset(
    c.slug for c in CITY_REGISTRY if c.state in _SOLAR_CADASTRE_STATES
)

# parking (DATA-40): ONE parking endpoint with source fallback (deduplication principle).
# Prefers ParkenDD live occupancy (derived from ``adapters.parkendd.PARKENDD_CITIES``,
# 22 cities), plus Munich via static CKAN location catalog
# (fallback without live occupancy). A new ParkenDD city
# expands coverage automatically. Since 2026-07-02 (gap closing top 12)
# additionally the three Mobilithek mTLS cities whose sources were previously ONLY
# wired as /live routes (``_MOBILITHEK_PARKING`` in api/v1/cities.py,
# must remain synchronized with this set).
_PARKING_CITIES: frozenset[str] = (
    frozenset(PARKENDD_CITIES)
    | {"muenchen"}
    | {"frankfurt-am-main", "wuppertal", "magdeburg"}
)

# bike-counts (DATA-40): municipal bicycle counting stations open data per city (NO
# Eco-Counter: license unclear, owner decision 2026-06-23). Each city its
# own origin-verified license source. Grows additively per integrated
# city (must remain in sync with ``_resolve_bike_counts_connector`` in api/v1/cities.py).
_BIKE_COUNTS_CITIES: frozenset[str] = frozenset(
    {
        "muenchen",
        "leipzig",
        "hamburg",
        "berlin",
        "stuttgart",
        "koeln",
        "essen",
        "duesseldorf",
    }
)

# heritage (DATA-OSM-Tier-2): monument lists are state matter -> federated via WFS
# (like BORIS/solar-roofs). Covered are registry cities whose federal state
# (``state``) has a verified, openly licensed monument WFS
# (``DENKMAL_WFS``). A new state expands coverage automatically.
_HERITAGE_STATES = set(DENKMAL_WFS)
_HERITAGE_CITIES: frozenset[str] = frozenset(
    c.slug for c in CITY_REGISTRY if c.state in _HERITAGE_STATES
)

# tree-cadastre (DATA-OSM-Tier-2): tree cadastres are municipal open data -> configured
# per city (``BAUM_WFS``). Covered are exactly the configured,
# verified openly licensed cities. A new city expands automatically.
_TREE_CADASTRE_CITIES: frozenset[str] = frozenset(BAUM_WFS)

# district-heating (DATA-41): district heating supply from municipal
# heat planning, federated per city WFS. The WFS registry (``DISTRICT_HEATING_WFS``)
# lives in PRIVATE ingest module (``ingest.district_heating``, no public export);
# therefore the slug set is mirrored here (like road-events/sharing) instead of
# imported, so public live proxy code loads without private module. A
# module assertion in ``ingest.district_heating`` keeps both sets drift-synchronized.
_DISTRICT_HEATING_CITIES: frozenset[str] = frozenset({"berlin", "hamburg"})

# office-wait-times (Quick-260705-jgt): administrative office wait times live. Currently ONLY
# Cologne covered (keyless direct feed waiting-od.php); other cities return
# honest not_covered (200, not 404). Grows additively per integrated city.
_OFFICE_WAIT_TIMES_CITIES: frozenset[str] = frozenset({"koeln"})

# Single source of truth: endpoint identifier -> covered city slugs.
# Identifier matches last path segment of route (``/cities/{slug}/<key>``).
PARTIAL_COVERAGE: dict[str, frozenset[str]] = {
    "flood": frozenset(_CITY_PEGEL),
    "webcams": frozenset(_CITY_ROADS),
    "traffic": frozenset(_CITY_ROADS),
    "road-events": _ROAD_EVENTS_CITIES,
    "sharing": _SHARING_CITIES,
    "land-values": _LAND_VALUES_CITIES,
    "solar-roofs": _SOLAR_ROOFS_CITIES,
    "parking": _PARKING_CITIES,
    "bike-counts": _BIKE_COUNTS_CITIES,
    "heritage": _HERITAGE_CITIES,
    "tree-cadastre": _TREE_CADASTRE_CITIES,
    "district-heating": _DISTRICT_HEATING_CITIES,
    "office-wait-times": _OFFICE_WAIT_TIMES_CITIES,
}


def is_covered(endpoint: str, slug: str) -> bool:
    """True if ``slug`` is covered for ``endpoint``.

    An unknown ``endpoint`` (not partially covered -> nationwide covered) is
    always considered covered (fail-open for fully covered endpoints that never
    query this map).
    """
    covered = PARTIAL_COVERAGE.get(endpoint)
    if covered is None:
        return True
    return slug in covered


def covered_cities(endpoint: str) -> list[str]:
    """Sorted list of covered city slugs for ``endpoint``.

    Used for meta.covered_cities reporting in ``not_covered`` responses. Empty for
    an unknown (= nationwide covered) endpoint.
    """
    return sorted(PARTIAL_COVERAGE.get(endpoint, frozenset()))
