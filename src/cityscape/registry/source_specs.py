"""Declarative source registry: ONE place per upstream source.

Single source of truth for pure data-oriented source attributes that
were previously spread across four structures:
  * KNOWN_SOURCES        (previously api/v1/sources.py:_KNOWN_SOURCES)
  * SOURCE_LICENSE       (previously api/v1/sources.py:SOURCE_LICENSE)
  * SOURCE_TTL           (previously resilience/client.py:_SOURCE_TTL)
  * FRAGILE_SOURCE_COOLDOWN (previously resilience/breaker_redis.py)

Adding a new source = ONE SourceSpec entry here (plus continuing:
the enable_<name> toggle in config.py, the SourceId value in enums.py, the
adapter/mapper code, and the verbatim line in DATA-LICENSES.md).
License wordings remain verified fail-closed against DATA-LICENSES.md
(tests/unit/test_source_license_map.py); the order here IS the
public order of the /sources route.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpec:
    """An upstream source, declaratively.

    Args:
        name: Source key; MUST match enable_<name> toggle
            (config.py) and SourceId value (enums.py) exactly.
        license_id: License identifier (see LicenseId/DATA-LICENSES.md).
        attribution: Verbatim attribution VERBATIM from DATA-LICENSES.md.
        ttl: (fresh_s, stale_s) cache window; None = default (60s/120s).
        cooldown: HALF_OPEN probe interval (s) for fragile upstreams;
            None = 30s default of breaker.
    """

    name: str
    license_id: str
    attribution: str
    ttl: tuple[float, float] | None = None
    cooldown: float | None = None


SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec(name="wikidata", license_id="cc0", attribution="Wikidata"),
    SourceSpec(
        name="dwd",
        license_id="geonutzv",
        attribution="Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt",
        ttl=(600.0, 7200.0),
    ),
    SourceSpec(
        name="overpass",
        license_id="odbl",
        attribution="© OpenStreetMap contributors",
        ttl=(86400.0, 604800.0),
    ),
    SourceSpec(
        name="autobahn",
        license_id="dl_de_by_2_0",
        attribution="Bundesanstalt für Straßenwesen (BASt) / Autobahn GmbH",
    ),
    SourceSpec(
        name="hvv",
        license_id="dl_de_by_2_0",
        attribution="Hamburger Verkehrsverbund GmbH (HVV)",
    ),
    SourceSpec(
        name="delfi",
        license_id="cc_by_4_0",
        attribution="Datenquelle: DELFI e.V. / Mobilitätsdaten Deutschland, CC-BY 4.0",
    ),
    SourceSpec(
        name="bnetza", license_id="cc_by_4_0", attribution="Bundesnetzagentur.de"
    ),
    SourceSpec(
        name="uba",
        license_id="dl_de_by_2_0",
        attribution="Umweltbundesamt (UBA)",
        cooldown=900.0,
    ),
    SourceSpec(
        name="pegelonline",
        license_id="dl_de_zero_2_0",
        attribution=(
            "PEGELONLINE, Wasserstraßen- und Schifffahrtsverwaltung des Bundes (WSV)"
        ),
        ttl=(300.0, 7200.0),
        cooldown=600.0,
    ),
    SourceSpec(
        name="lhp",
        license_id="cc_by_4_0",
        attribution="Datenquelle: www.hochwasserzentralen.de, Stand: <Zeitstempel>",
    ),
    SourceSpec(
        name="dwd_pollen",
        license_id="geonutzv",
        attribution="Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt",
    ),
    SourceSpec(
        name="dwd_fire",
        license_id="geonutzv",
        attribution="Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt",
        # ArcGIS re-host can be intermittently sluggish/down -> generous
        # cache window (daily data) + custom HALF_OPEN cooldown.
        ttl=(3600.0, 86400.0),
        cooldown=900.0,
    ),
    SourceSpec(
        name="eea_bathing",
        license_id="cc_by_4_0",
        attribution=(
            "European Environment Agency (EEA), Bathing Water Directive 2006/7/EC"
        ),
        # Annual seasonal assessment (quasi-static) -> long cache window.
        ttl=(86400.0, 2592000.0),
        cooldown=900.0,
    ),
    SourceSpec(
        name="klinik_atlas",
        # FAIL-CLOSED: Bundes-Klinik-Atlas does not declare an explicit open license
        # -> UNKNOWN/Tier C, source disabled by default (see config) until BMG/IQTIG
        # confirms the license.
        license_id="unknown",
        attribution="Bundes-Klinik-Atlas (BMG/IQTIG)",
        ttl=(86400.0, 604800.0),
    ),
    SourceSpec(
        name="db_fasta",
        license_id="cc_by_4_0",
        attribution="Deutsche Bahn / DB InfraGO AG",
        # Real-time status -> short cache window.
        ttl=(300.0, 3600.0),
        cooldown=600.0,
    ),
    SourceSpec(
        name="genesis",
        license_id="dl_de_by_2_0",
        # H15 (Owner 2026-06-29): standardized with regionalstatistik source
        # (same host www.regionalstatistik.de -> "Statistische Ämter des
        # Bundes und der Länder"). zensus remains separate (own ZENSUS source).
        attribution="Statistische Ämter des Bundes und der Länder",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="zensus",
        license_id="dl_de_by_2_0",
        attribution="Statistisches Bundesamt (Destatis) / Regionalstatistik",
    ),
    SourceSpec(
        name="mastr",
        license_id="dl_de_by_2_0",
        attribution="Bundesnetzagentur - Marktstammdatenregister",
    ),
    SourceSpec(
        name="smard", license_id="cc_by_4_0", attribution="Bundesnetzagentur | SMARD.de"
    ),
    SourceSpec(
        name="dwd_warnings",
        license_id="geonutzv",
        attribution="Datenbasis: Deutscher Wetterdienst",
    ),
    SourceSpec(
        name="kba", license_id="dl_de_by_2_0", attribution="Kraftfahrt-Bundesamt (KBA)"
    ),
    SourceSpec(
        name="unfallatlas",
        license_id="dl_de_by_2_0",
        attribution="Statistische Ämter des Bundes und der Länder, Unfallatlas",
    ),
    SourceSpec(
        name="bka_pks",
        license_id="dl_de_by_2_0",
        attribution="Polizeiliche Kriminalstatistik (PKS) - Bundeskriminalamt",
    ),
    SourceSpec(
        name="inkar",
        license_id="dl_de_by_2_0",
        attribution="Bundesinstitut für Bau-, Stadt- und Raumforschung (BBSR), INKAR",
    ),
    SourceSpec(
        name="tankerkoenig",
        license_id="cc_by_4_0",
        attribution="Tankerkoenig (creativecommons.tankerkoenig.de), MTS-K",
    ),
    SourceSpec(name="gbfs", license_id="cc0", attribution="nextbike GmbH / GBFS (CC0)"),
    SourceSpec(
        name="db_timetables", license_id="cc_by_4_0", attribution="Deutsche Bahn AG"
    ),
    SourceSpec(
        name="boris",
        license_id="dl_de_zero_2_0",
        attribution="Geoportal Berlin / Bodenrichtwerte",
    ),
    SourceSpec(
        name="stada",
        license_id="cc_by_4_0",
        attribution="Deutsche Bahn AG",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="regionalstatistik",
        license_id="dl_de_by_2_0",
        attribution="Statistische Ämter des Bundes und der Länder",
    ),
    SourceSpec(
        name="bkg",
        license_id="dl_de_by_2_0",
        attribution="(c) GeoBasis-DE / BKG (Jahr)",
    ),
    SourceSpec(
        name="bundeswahl",
        license_id="dl_de_by_2_0",
        attribution="Die Bundeswahlleiterin",
    ),
    SourceSpec(
        name="divi",
        license_id="cc_by_4_0",
        attribution="Robert Koch-Institut (RKI), DIVI-Intensivregister, Stand: <datum>",
    ),
    SourceSpec(
        name="feiertage",
        license_id="gemeinfrei",
        attribution="Feiertage und Schulferien je Bundesland, gemeinfrei",
    ),
    SourceSpec(
        name="berlin_viz",
        license_id="dl_de_by_2_0",
        attribution="Verkehrsinformationszentrale Berlin (VIZ)",
    ),
    SourceSpec(
        name="hamburg_baustellen",
        license_id="dl_de_by_2_0",
        attribution="Freie und Hansestadt Hamburg",
        cooldown=1800.0,
    ),
    SourceSpec(
        name="koeln_verkehr", license_id="dl_de_zero_2_0", attribution="Stadt Köln"
    ),
    SourceSpec(
        name="muenchen_baustellen",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt München",
    ),
    SourceSpec(
        name="dortmund_baustellen",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Dortmund",
    ),
    SourceSpec(
        name="sperrinfosys",
        license_id="dl_de_by_2_0",
        attribution="Freistaat Sachsen / LISt GmbH (SPERRINFOSYS)",
    ),
    SourceSpec(
        name="mobidata_bw",
        license_id="dl_de_by_2_0",
        attribution="Verkehrsministerium Baden-Württemberg / MobiData BW",
    ),
    SourceSpec(
        name="autobahn_webcam",
        license_id="dl_de_by_2_0",
        attribution="Bundesanstalt für Straßenwesen (BASt) / Autobahn GmbH",
    ),
    SourceSpec(
        name="destination_one", license_id="mixed", attribution="destination.one"
    ),
    SourceSpec(
        name="koeln_events", license_id="dl_de_zero_2_0", attribution="Stadt Köln"
    ),
    SourceSpec(
        name="koeln_traffic_flow", license_id="dl_de_zero_2_0", attribution="Stadt Köln"
    ),
    SourceSpec(
        name="koeln_baustellen_live",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Köln",
    ),
    SourceSpec(
        name="koeln_ereignisse_live",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Köln",
    ),
    SourceSpec(
        name="koeln_lez_live", license_id="dl_de_zero_2_0", attribution="Stadt Köln"
    ),
    SourceSpec(
        name="berlin_verkehrsmeldungen",
        license_id="dl_de_by_2_0",
        attribution=(
            "Senatsverwaltung für Mobilität, Verkehr, Klimaschutz und Umwelt (SenMVKU)"
        ),
    ),
    SourceSpec(
        name="dortmund_parking",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Dortmund",
    ),
    SourceSpec(
        name="kiel_zaehlstellen",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt Kiel",
    ),
    SourceSpec(
        name="eround_charging",
        license_id="cc0",
        attribution="Hamburger Energienetze GmbH / eRound",
    ),
    SourceSpec(
        name="frankfurt_parking",
        license_id="dl_de_by_2_0",
        attribution="Stadt Frankfurt am Main",
    ),
    SourceSpec(
        name="wuppertal_parking",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Wuppertal",
    ),
    # Magdeburg parking (Mobilithek, ifak e.V.): data source Stadt Magdeburg ->
    # their open data terms of use establish Datenlizenz Deutschland
    # Namensnennung 2.0 in absence of other marking (research 2026-06-30,
    # magdeburg.de open government data), Tier A. Attribution = required
    # source indication verbatim.
    SourceSpec(
        name="magdeburg_parking",
        license_id="dl_de_by_2_0",
        attribution="Datenquelle: Landeshauptstadt Magdeburg, www.magdeburg.de",
    ),
    SourceSpec(
        name="bremen_baustellen",
        license_id="dl_de_by_2_0",
        attribution="Freie Hansestadt Bremen",
    ),
    SourceSpec(
        name="hannover_verkehrsmeldungen",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt Hannover",
    ),
    SourceSpec(name="gtfs_rt", license_id="cc_by_sa_4_0", attribution="gtfs.de"),
    SourceSpec(
        name="hvv_geofox",
        license_id="unknown",
        attribution="Hamburger Verkehrsverbund GmbH (HVV) / Geofox",
    ),
    SourceSpec(
        name="vgn",
        license_id="cc_by_4_0",
        attribution="Verkehrs-Aktiengesellschaft Nürnberg (VAG) / VGN",
    ),
    SourceSpec(
        name="hamburg_verkehrslage",
        license_id="dl_de_by_2_0",
        attribution="Freie und Hansestadt Hamburg",
        cooldown=1800.0,
    ),
    SourceSpec(
        name="solar",
        license_id="ec_reuse",
        attribution="PVGIS © European Communities, 2001-2026",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="solar_cadastre",
        license_id="dl_de_zero_2_0",
        attribution="Land NRW / GeoBasis NRW / LANUK (MaStR), Solarkataster NRW",
    ),
    SourceSpec(
        name="muenchen_parkhaeuser",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt München",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="muenchen_radzaehl",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt München",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="leipzig_radzaehl",
        license_id="dl_de_by_2_0",
        attribution="Stadt Leipzig",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="hamburg_radzaehl",
        license_id="dl_de_by_2_0",
        attribution=(
            "Freie und Hansestadt Hamburg, Behörde für Verkehr und Mobilitätswende"
        ),
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="berlin_radzaehl",
        license_id="dl_de_zero_2_0",
        attribution=(
            "Senatsverwaltung für Mobilität, Verkehr, Klimaschutz und Umwelt Berlin"
        ),
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="stuttgart_radzaehl",
        license_id="cc_by_4_0",
        attribution="Landeshauptstadt Stuttgart",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="koeln_radzaehl",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Köln",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="essen_radzaehl",
        license_id="dl_de_by_2_0",
        attribution="Stadt Essen",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="duesseldorf_radzaehl",
        license_id="dl_de_by_2_0",
        attribution="Landeshauptstadt Düsseldorf",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="parkendd",
        license_id="unknown",
        attribution="ParkenDD",
        ttl=(300.0, 3600.0),
    ),
    SourceSpec(
        name="denkmal",
        license_id="dl_de_zero_2_0",
        attribution="Geoportal Berlin / Landesdenkmalamt Berlin, Denkmaldatenbank",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="baumkataster",
        license_id="dl_de_zero_2_0",
        attribution="Geoportal Berlin / Straßen- und Anlagenbaumbestand",
        ttl=(86400.0, 2592000.0),
    ),
    SourceSpec(
        name="zensus_grid",
        license_id="dl_de_by_2_0",
        attribution="© Statistische Ämter des Bundes und der Länder, Zensus 2022",
        ttl=(604800.0, 2592000.0),
    ),
    SourceSpec(
        name="oeffentlichevergabe",
        license_id="cc0",
        attribution=(
            "Datenservice Oeffentlicher Einkauf (oeffentlichevergabe.de) / "
            "Beschaffungsamt des BMI"
        ),
        ttl=(86400.0, 2592000.0),
    ),
    # DATA-41: District heating network supply per city (federated per city WFS,
    # license-verified per origin). Berlin representative (DL-DE/Zero 2.0); Hamburg
    # DL-DE/BY 2.0 is carried by record per city from WFS registry. Batch ingest, no
    # live call in request path (long TTL).
    SourceSpec(
        name="district_heating",
        license_id="dl_de_zero_2_0",
        attribution="Geoportal Berlin / Energienetze",
        ttl=(86400.0, 2592000.0),
    ),
    # Quick-260705-jgt: Cologne office wait times (office-wait-times). Keyless
    # direct HTTP against waiting-od.php, DL-DE/Zero 2.0 = Tier A, pure live data.
    # Attribution "Stadt Koeln" VERBATIM identical to DATA-LICENSES.md entry.
    SourceSpec(
        name="koeln_wartezeiten",
        license_id="dl_de_zero_2_0",
        attribution="Stadt Koeln",
    ),
    # Quick-260705-ufv: BBK NINA civil protection warnings (civil-protection-
    # warnings). Keyless GET against warnung.bund.de/api31/dashboard/{ARS}.json,
    # official warning text verbatim (Sec. 5 para. 2 UrhG, official work = Tier A). Pure
    # live warnings (no archive), short cache window (60s/300s). Attribution
    # VERBATIM identical to mappers/bbk_nina.py + DATA-LICENSES.md (T-11-SRC-DRIFT).
    SourceSpec(
        name="bbk_nina",
        license_id="amtliches_werk",
        attribution="Bundesamt für Bevölkerungsschutz und Katastrophenhilfe (BBK)",
        ttl=(60.0, 300.0),
    ),
)

# --- Derived views (backwards compatible to old structures) ---
KNOWN_SOURCES: tuple[str, ...] = tuple(s.name for s in SOURCE_SPECS)

SOURCE_LICENSE: dict[str, dict[str, str]] = {
    s.name: {"license_id": s.license_id, "attribution": s.attribution}
    for s in SOURCE_SPECS
}

SOURCE_TTL: dict[str, tuple[float, float]] = {
    s.name: s.ttl for s in SOURCE_SPECS if s.ttl is not None
}

FRAGILE_SOURCE_COOLDOWN: dict[str, float] = {
    s.name: s.cooldown for s in SOURCE_SPECS if s.cooldown is not None
}
