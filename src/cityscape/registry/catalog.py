"""Static catalog of all city data types (discovery layer for /overview).

Owner request (2026-06-24): MCP agents and end users should see at a glance
HOW MANY data types exist per city, not only the most frequently used weather. This
catalog is the ONLY source for data type labels + associated MCP tool names
for the ``GET /cities/{slug}/overview`` endpoint.

Pure static metadata (no upstream calls). Availability per city is
derived cheaply at runtime from ``registry.coverage``. An assertion in test
``tests/integration/test_city_overview.py`` keeps the keys identical with
the MCP allowlist (``mcp.client.ALLOWED_RESOURCES``), so the catalog does not
silently fall behind when adding a new data type.
"""

from __future__ import annotations

from typing import NamedTuple


class DataType(NamedTuple):
    """A city data type for the overview catalog.

    ``key`` is the last path segment (``/cities/{slug}/<key>``) and also the
    coverage key (``registry.coverage.is_covered``). ``tool`` is the name
    of the associated MCP tool, so an agent can jump directly.
    """

    key: str
    tool: str
    label: str
    label_en: str


# Exactly the city sub-resources from ``mcp.client.ALLOWED_RESOURCES`` (test keeps
# sets identical). Labels with real umlauts (German spelling).
CITY_DATA_CATALOG: tuple[DataType, ...] = (
    DataType("base", "get_city", "Basisdaten", "Base data"),
    DataType("weather", "weather", "Wetter", "Weather"),
    DataType(
        "weather-warnings", "weather_warnings", "Wetterwarnungen", "Weather warnings"
    ),
    # Quick-260705-ufv: BBK NINA civil protection warnings per city (keyless,
    # ARS-based, full coverage). No entry in _NAMED_TOOLS -> runs via
    # get_city_resource. Label with correct umlaut, key/tool ASCII.
    DataType(
        "civil-protection-warnings",
        "civil_protection_warnings",
        "Bevölkerungsschutz-Warnungen",
        "Civil protection warnings",
    ),
    DataType("pollen-uv", "pollen_uv", "Pollen & UV-Index", "Pollen & UV index"),
    DataType("fire-danger", "fire_danger", "Waldbrandgefahr", "Wildfire danger"),
    DataType(
        "bathing-water",
        "bathing_water",
        "Badegewässerqualität",
        "Bathing water quality",
    ),
    DataType(
        "hospitals-atlas",
        "hospitals_atlas",
        "Krankenhausatlas",
        "Hospital atlas",
    ),
    DataType(
        "station-facilities",
        "station_facilities",
        "Aufzüge & Rolltreppen (Bahnhof)",
        "Elevators & escalators (station)",
    ),
    DataType("air", "air_quality_live", "Luftqualität (live)", "Air quality (live)"),
    DataType(
        "air-uba", "air_quality", "Luftqualität (amtlich)", "Air quality (official)"
    ),
    DataType("transit", "transit", "ÖPNV-Haltestellen", "Public transit stops"),
    DataType(
        "station-departures",
        "station_departures",
        "Bahn-Abfahrten (Hbf)",
        "Train departures (main station)",
    ),
    DataType(
        "station-arrivals",
        "station_arrivals",
        "Bahn-Ankünfte (Hbf)",
        "Train arrivals (main station)",
    ),
    DataType("stations", "stations", "Bahnhöfe", "Railway stations"),
    DataType("traffic", "traffic", "Autobahn-Verkehr", "Motorway traffic"),
    DataType(
        "road-events",
        "road_events",
        "Innerstädtische Baustellen",
        "Inner-city roadworks",
    ),
    DataType("webcams", "webcams", "Verkehrs-Webcams", "Traffic webcams"),
    DataType("charging", "charging", "Ladesäulen", "EV charging stations"),
    # DATA-42: eRound live charging occupancy per city (AFIR DATEX-II V3, CC0). Join
    # from geo-map (static full database) + accumulated occupancy deltas.
    DataType(
        "charging-status",
        "charging_status",
        "Ladesäulen-Belegung (live)",
        "EV charging occupancy (live)",
    ),
    DataType("parking", "parking", "Parkhäuser", "Car parks"),
    DataType("fuel-prices", "fuel_prices", "Spritpreise", "Fuel prices"),
    DataType("sharing", "sharing", "Bike- & Scooter-Sharing", "Bike & scooter sharing"),
    DataType("pois", "pois", "Points of Interest", "Points of interest"),
    DataType("health", "health", "Krankenhäuser", "Hospitals"),
    DataType("icu-live", "icu_live", "Intensivbetten (live)", "ICU beds (live)"),
    DataType("water-level", "water_level", "Pegelstände", "Water levels"),
    DataType("flood", "flood", "Hochwasserwarnungen", "Flood warnings"),
    DataType("geo", "geo", "Geodaten & Grenzen", "Geodata & boundaries"),
    DataType("demographics", "demographics", "Demografie", "Demographics"),
    DataType(
        "indicators",
        "indicators",
        "Sozioökonomische Indikatoren",
        "Socioeconomic indicators",
    ),
    DataType("unemployment", "unemployment", "Arbeitslosigkeit", "Unemployment"),
    DataType(
        "tourism", "tourism", "Tourismus (Übernachtungen)", "Tourism (overnight stays)"
    ),
    DataType("construction", "construction", "Baugenehmigungen", "Building permits"),
    DataType("accidents", "accidents", "Verkehrsunfälle", "Road accidents"),
    DataType("crime-stats", "crime_stats", "Kriminalität", "Crime statistics"),
    DataType(
        "vehicle-registrations",
        "vehicle_registrations",
        "Kfz-Bestand",
        "Vehicle registrations",
    ),
    DataType("election", "election", "Wahlergebnisse", "Election results"),
    DataType("holidays", "holidays", "Feiertage", "Public holidays"),
    DataType("energy", "energy", "Energieanlagen", "Energy installations"),
    DataType("power-load", "power_load", "Netzlast (Strom)", "Grid load (electricity)"),
    DataType(
        "power-price", "power_price", "Strom-Börsenpreis", "Day-ahead power price"
    ),
    DataType(
        "solar", "solar", "Solar-Einstrahlung & Ertrag", "Solar irradiation & yield"
    ),
    DataType(
        "solar-roofs", "solar_roofs", "Dach-Solarkataster", "Rooftop solar cadastre"
    ),
    DataType("land-values", "land_values", "Bodenrichtwerte", "Land values"),
    DataType(
        "tax-rates", "tax_rates", "Realsteuer-Hebesätze", "Property & trade tax rates"
    ),
    DataType(
        "business-registrations",
        "business_registrations",
        "Gewerbe-An- & Abmeldungen",
        "Business registrations",
    ),
    # DATA-37: Regionalstatistik.de filed insolvencies per county (52411-02
    # enterprises + 52411-03 other debtors), Tier A. key/tool ASCII.
    DataType("insolvencies", "insolvencies", "Insolvenzen", "Insolvencies"),
    DataType("events", "events", "Veranstaltungen", "Public events"),
    # DATA-OSM (Tier 1): dedicated OSM Overpass data types (ODbL, Tier B).
    DataType("playgrounds", "playgrounds", "Spielplätze", "Playgrounds"),
    DataType(
        "drinking-water",
        "drinking_water",
        "Trinkwasserbrunnen",
        "Drinking water fountains",
    ),
    DataType(
        "public-toilets", "public_toilets", "Öffentliche Toiletten", "Public toilets"
    ),
    DataType("markets", "markets", "Wochenmärkte", "Markets"),
    DataType("parcel-lockers", "parcel_lockers", "Paketstationen", "Parcel lockers"),
    DataType("post-offices", "post_offices", "Postfilialen", "Post offices"),
    DataType("post-boxes", "post_boxes", "Briefkästen", "Post boxes"),
    DataType("public-wifi", "public_wifi", "Öffentliches WLAN", "Public Wi-Fi"),
    DataType(
        "recycling-centres",
        "recycling_centres",
        "Recyclinghöfe",
        "Recycling centres",
    ),
    DataType(
        "government-offices",
        "government_offices",
        "Behörden & Ämter",
        "Government offices",
    ),
    DataType("education", "education", "Bildungseinrichtungen", "Education facilities"),
    # DATA-OSM-Tier-2: monument lists per state (state WFS, coverage-gated).
    DataType("heritage", "heritage", "Denkmäler", "Heritage monuments"),
    # DATA-OSM-Tier-2: tree cadastre per city (municipal WFS, coverage-gated).
    DataType("tree-cadastre", "tree_cadastre", "Baumkataster", "Tree cadastre"),
    # DATA-OSM-Tier-2: population density from Census 2022 100m grid (all cities).
    DataType(
        "population-density",
        "population_density",
        "Einwohnerdichte",
        "Population density",
    ),
    # TENDER-01/05: public procurement (oeffentlichevergabe.de, CC0 = Tier A).
    # key/tool ASCII (path segment + MCP tool), label with correct umlaut.
    DataType(
        "public-tenders",
        "public_tenders",
        "Öffentliche Auftragsvergabe",
        "Public procurement",
    ),
    # DATA-40: municipal bicycle counting open data per city (permanent counters, Tier A,
    # partial coverage muenchen/leipzig/hamburg/berlin/stuttgart). key/tool ASCII,
    # label with correct umlaut. NOT the sharing tool (GBFS rental vehicles).
    DataType(
        "bike-counts",
        "bike_counts",
        "Radzählstellen",
        "Bike counters",
    ),
    # DATA-41: district heating networks per city (municipal heat planning,
    # federated per city WFS, Tier A, partial coverage berlin/hamburg). key/tool ASCII,
    # label with correct umlaut.
    DataType(
        "district-heating",
        "district_heating",
        "Fernwärme & Wärmenetze",
        "District heating networks",
    ),
    # Quick-260705-jgt: office wait times per city (live, keyless, Tier A,
    # partial coverage koeln only). key/tool ASCII (path segment), label with correct
    # umlaut. No entry in _NAMED_TOOLS -> runs via get_city_resource.
    DataType(
        "office-wait-times",
        "office_wait_times",
        "Behörden-Wartezeiten (live)",
        "Government office wait times (live)",
    ),
)

# MCP TOOL CONSOLIDATION 2026-07-02: The long-tail runs via ONE generic
# tool ``get_city_resource(slug, resource=<key>)``; only few data types
# retain a named tool. Instead of rewriting all entries above (and
# reminding each future entry), tool mapping is DERIVED here:
# historical ``tool`` values in literals above are thus
# documentation only; this derivation is authoritative. New data types
# point automatically to get_city_resource. The overview/catalog consumer
# passes the ``type`` key as resource argument to get_city_resource
# (note in cityscape://catalog note and server instructions).
_NAMED_TOOLS: dict[str, str] = {
    "base": "get_city",
    "overview": "get_city_overview",
    "weather": "weather",
    "air-uba": "air_quality",
    "pois": "pois",
}

CITY_DATA_CATALOG = tuple(
    dt._replace(tool=_NAMED_TOOLS.get(dt.key, "get_city_resource"))
    for dt in CITY_DATA_CATALOG
)
