"""Canonical enums from the normalization library (CORE-01).

Defines the fixed value ranges for license tier, license ID, and source as
``StrEnum``. ``StrEnum`` serializes losslessly to JSON strings and serves as a
mandatory anchor for tier-separated data storage (GOV Foundation): no
data record may enter the system without a correct tier tag.
"""

from __future__ import annotations

from enum import StrEnum


class LicenseTier(StrEnum):
    """License Tier for data storage organized by tier (GOV-Fundament).

    Identifies (GOV-02/04) the license for each data record to ensure proper attribution
    and reuse without modifying the schema. Required field in the envelope to ensure
    that no data record slips through without a tier.
    """

    A = "A"  # permissiv (CC0, CC-BY, DL-DE/BY, DL-DE/Zero, GeoNutzV)
    B = "B"  # copyleft (ODbL, CC-BY-SA): getrennt kennzeichnen
    C = "C"  # live-only (z.B. ParkenDD, DIVI): nur Live-Anzeige


class LicenseId(StrEnum):
    """Specific license for each data set (attribution and species assignment)."""

    CC0 = "cc0"
    CC_BY_4_0 = "cc_by_4_0"
    DL_DE_BY_2_0 = "dl_de_by_2_0"
    DL_DE_ZERO_2_0 = "dl_de_zero_2_0"
    GEONUTZV = "geonutzv"
    ODBL = "odbl"
    CC_BY_SA_4_0 = "cc_by_sa_4_0"
    # EU Reuse Policy (Commission Decision 2011/833/EU, effectively
    # CC BY 4.0): EU JRC data such as PVGIS may be used freely (including for commercial purposes) provided that
    # the source is cited (“PVGIS © European Communities”). Permissive = Tier A.
    EC_REUSE = "ec_reuse"
    # Honest tag for sources with heterogeneous/unknown licenses per dataset
    # (e.g., ParkenDD, whose license varies by city): prevents an
    # incorrect blanket CC-BY tag in the envelope (GOV-01/03 compliance).
    UNKNOWN = "unknown"
    # Section 5(2) UrhG: official work, in the public domain. Redistribution is
    # permitted as long as the content remains UNCHANGED and the source is cited
    # (prohibition on modification). Effectively permissive (including commercial use) -> Tier A. Used
    # for the official BBK-NINA civil protection warning texts.
    AMTLICHES_WERK = "amtliches_werk"


class SourceId(StrEnum):
    """Known upstream sources that are mapped to the canonical schema."""

    WIKIDATA = "wikidata"
    DWD = "dwd"
    OSM = "osm"
    AUTOBAHN = "autobahn"
    BNETZA = "bnetza"
    UBA = "uba"
    DELFI = "delfi"
    HVV = "hvv"
    # Phase 7: Tier-A Sources (E-Mobility and Expanded Environmental Data).
    # Note: The source/toggle name is “lhp,” but the license/record tag is
    # HOCHWASSER (State Flood Portals, www.hochwasserzentralen.de).
    PEGELONLINE = "pegelonline"
    HOCHWASSER = "hochwasser"
    DWD_POLLEN = "dwd_pollen"
    # DWD Forest Fire/Grassland Fire Index (keylos, GeoNutzV, Tier A, near-station).
    DWD_FIRE = "dwd_fire"
    # EEA Bathing Water Quality (keylos, CC-BY 4.0, Tier A, local/surrounding area).
    EEA_BATHING = "eea_bathing"
    # Federal Hospital Atlas (keylos, license UNKNOWN -> Tier C fail-closed, local).
    KLINIK_ATLAS = "klinik_atlas"
    # DB FaSta Elevator/Escalator Status (key-gated DB Marketplace, CC-BY, Tier A).
    DB_FASTA = "db_fasta"
    # Phase 8: Statistics, Energy, and Geo sources. GENESIS and
    # ZENSUS are account-gated (POST-API); MASTR/BKG/BUNDESWAHL/FEIERTAGE are
    # keyless bulk/seed sources; DIVI is the clinic-specific live-only source
    # (Tier C, database protection). All values are ASCII (StrEnum).
    GENESIS = "genesis"
    ZENSUS = "zensus"
    MASTR = "mastr"
    SMARD = "smard"
    DWD_WARNINGS = "dwd_warnings"
    BKG = "bkg"
    BUNDESWAHL = "bundeswahl"
    DIVI = "divi"
    FEIERTAGE = "feiertage"
    # Phase 9: Keyless city traffic sources (construction sites/road closures) by city.
    # All values in ASCII (StrEnum), no umlauts (slugs: muenchen/koeln). Toggle name
    # == SourceId value == _KNOWN_SOURCES entry. Webcams continue to use
    # SourceId.AUTOBAHN as a live image feature; therefore, there is NO separate
    # Webcam SourceId here. No new LicenseId value
    # (all Phase 9 sources are DL-DE/BY 2.0 = DL_DE_BY_2_0, already available).
    BERLIN_VIZ = "berlin_viz"
    HAMBURG_BAUSTELLEN = "hamburg_baustellen"
    KOELN_VERKEHR = "koeln_verkehr"
    MUENCHEN_BAUSTELLEN = "muenchen_baustellen"
    DORTMUND_BAUSTELLEN = "dortmund_baustellen"
    # SPERRINFOSYS Saxony (LISt GmbH): A Saxony-wide source for Dresden +
    # Leipzig (VKZ filter in the adapter), DL-DE/BY 2.0.
    SPERRINFOSYS = "sperrinfosys"
    MOBIDATA_BW = "mobidata_bw"
    # Phase 10: City Events. DESTINATION_ONE is the account-
    # gated eT4.META source (license key, mixed licenses per record, GOV-04),
    # KOELN_EVENTS is the keyless Köln-Direkt feed (fixed DL-DE/Zero, D-06). All values
    # are ASCII (StrEnum), no umlauts (slug: koeln). Toggle name == SourceId value ==
    # _KNOWN_SOURCES entry. No new LicenseId value required (CC0/CC_BY_4_0/
    # CC_BY_SA_4_0/DL_DE_ZERO_2_0/UNKNOWN already exist).
    DESTINATION_ONE = "destination_one"
    KOELN_EVENTS = "koeln_events"
    # Phase 20: Live sources via the Mobilithek mTLS pull (separate /live-
    # category). All values in ASCII lowercase, no umlauts (slugs: koeln/berlin/
    # dortmund/kiel/eround). Toggle name == SourceId value == _KNOWN_SOURCES-
    # entry: getattr(settings, f“enable_{name}”). No new LicenseId value
    # (DL_DE_BY_2_0/CC0/UNKNOWN exist; eRound only after license verification).
    KOELN_TRAFFIC_FLOW = "koeln_traffic_flow"
    KOELN_BAUSTELLEN_LIVE = "koeln_baustellen_live"
    KOELN_EREIGNISSE_LIVE = "koeln_ereignisse_live"
    KOELN_LEZ_LIVE = "koeln_lez_live"
    BERLIN_VERKEHRSMELDUNGEN = "berlin_verkehrsmeldungen"
    DORTMUND_PARKING = "dortmund_parking"
    KIEL_ZAEHLSTELLEN = "kiel_zaehlstellen"
    EROUND_CHARGING = "eround_charging"
    # Frankfurt am Main parking data (Mobilithek DATEX II V3 Parking, statically +
    # dynamically joined, DL-DE/BY 2.0 = Tier A). ONLY DATEX II V3 XML source
    # (eRound is V3 JSON, Cologne is V2 XML): custom V3 XML parser
    # (adapters/mobilithek_datex3). Toggle name == SourceId value ==
    # _KNOWN_SOURCES entry: getattr(settings, f“enable_{name}”).
    FRANKFURT_PARKING = "frankfurt_parking"
    # Wuppertal parking data (Mobilithek DATEX II V2 ParkingFacility profile, statically
    # and dynamically joined, DL-DE/Zero 2.0 = Tier A). Custom V2 profile
    # (parkingFacilityStatus/-Reference), separate from the Cologne parkingStatus path.
    # Toggle name == SourceId value == _KNOWN_SOURCES entry.
    WUPPERTAL_PARKING = "wuppertal_parking"
    # Magdeburg parking data (Mobilithek DATEX II V2 ParkingFacility profile, statically
    # and dynamically joined; shares the Wuppertal V2 parser). Provider: ifak e.V.,
    # Data source: State Capital of Magdeburg -> its open data terms of use
    # specify the Germany Attribution 2.0 data license in the absence of other designation
    # (license_id=dl_de_by_2_0, Tier A; researched 2026-06-30, magdeburg.de
    # Open Administrative Data). Toggle name == SourceId value.
    MAGDEBURG_PARKING = "magdeburg_parking"
    # Phase 19: GTFS Real-Time Trip Updates, Tier B CC-BY-SA, gtfs.de/Mobilithek-
    # DELFI; no new LicenseId value (CC_BY_SA_4_0 already exists), no
    # umlaut (StrEnum, ASCII lowercase). Toggle name == SourceId value ==
    # _KNOWN_SOURCES entry: getattr(settings, f“enable_{name}”).
    GTFS_RT = "gtfs_rt"
    # DATA-24: HVV Geofox GTI Live Departures (Hamburg), Tier C live-only
    # (Geofox license not public). Own SourceId separate from HVV (= static
    # GTFS stops). Toggle name == SourceId value == _KNOWN_SOURCES entry.
    HVV_GEOFOX = "hvv_geofox"
    # DATA-25: VGN/VAG Nuremberg live departures (Puls API start.vag.de), Tier A
    # (CC-BY 4.0, open, opendata.vag.de) -> easily usable, unlike HVV.
    # Keylos, NO Mobilithek. Toggle name == SourceId value == _KNOWN_SOURCES.
    VGN = "vgn"
    # DATA-26: Hamburg Traffic Conditions (real-time traffic flow by road segment,
    # OAF/GeoJSON api.hamburg.de), Tier A (DL-DE/BY 2.0, open, keyless). Unlike
    # HVV_GEOFOX (Tier C, not open), it is easily usable. NO Mobilithek.
    # Toggle name == SourceId value == _KNOWN_SOURCES entry.
    HAMBURG_TRAFFIC_CONDITIONS = "hamburg_verkehrslage"
    # DATA-27: KBA passenger car fleet + share of electric vehicles by registration district (keylose
    # bulk source, DL-DE/BY 2.0, Tier A). Read-only store access in the request path
    # (like MASTR), no resilient_client. Toggle name == SourceId value ==
    # _KNOWN_SOURCES entry: getattr(settings, f“enable_{name}”).
    KBA = "kba"
    # DATA-29: Accident Atlas (road traffic accidents by district, keyless bulk CSV,
    # DL-DE/BY 2.0, Tier A). Read-only store access (like KBA/MASTR), no
    # resilient_client. Toggle name == SourceId value == _KNOWN_SOURCES entry.
    ACCIDENT_ATLAS = "unfallatlas"
    # DATA-30: Tankerkönig Fuel Prices (MTS-K), aggregated by city. Keyed live
    # source (resilient_client), CC-BY 4.0 = Tier A (open, usable). Toggle-
    # Name == SourceId value == _KNOWN_SOURCES entry: getattr(settings,
    # f“enable_{name}”); the key is a separate SecretStr field.
    TANKERKOENIG = "tankerkoenig"
    # DATA-31: Bremen Construction Zones/Work Sites (Bremen Traffic Management Center,
    # Mobilithek DATEX II V2 SituationPublication, DL-DE/BY 2.0, Tier A). Live-
    # Source same as koeln_baustellen_live. Toggle name == SourceId value ==
    # _KNOWN_SOURCES entry.
    BREMEN_BAUSTELLEN = "bremen_baustellen"
    # Hanover Traffic Reports (State Capital of Hanover, Civil Engineering Department,
    # Mobilithek DATEX II V2 SituationPublication: Construction Sites/Events/
    # Traffic Disruptions, Mobilithek offering “free use/Open Data” = DL-DE/BY
    # 2.0 = Tier A, similar to Bremen/Berlin). Live source like bremen_baustellen.
    # Toggle name == SourceId value == _KNOWN_SOURCES entry.
    HANNOVER_VERKEHRSMELDUNGEN = "hannover_verkehrsmeldungen"
    # DATA-33: GBFS bike/scooter sharing by city (live, aggregated). Primary
    # Nextbike (CC0 = Tier A); for each system, the license from GBFS
    # ``system_information.license_id`` is checked using a fail-closed approach against a Tier A allowlist
    # (GOV-02/04). Keyless, resilient_client. Toggle name == SourceId
    # value == _KNOWN_SOURCES entry: getattr(settings, f“enable_{name}”).
    GBFS = "gbfs"
    # DATA-32: INKAR/BBSR socioeconomic indicators by district (keyless bulk
    # source, DL-DE/BY 2.0, Tier A). Read-only store access in the request path (as with
    # KBA/UNFALLATLAS), no resilient_client. Toggle name == SourceId value ==
    # _KNOWN_SOURCES entry: getattr(settings, f“enable_{name}”).
    INKAR = "inkar"
    # PKS-01: BKA Police Crime Statistics by District (key-less bulk XLSX,
    # DL-DE/BY 2.0, Tier A). Read-only store read in the request path (as in KBA/
    # UNFALLATLAS), no resilient_client. Toggle Name == SourceId Value ==
    # _KNOWN_SOURCES entry: getattr(settings, f“enable_{name}”).
    BKA_PKS = "bka_pks"
    # DATA-34: DB Timetables (live departure board for major city central stations, including long-distance trains +
    # real-time delays). Keyed live source (resilient_client, header auth),
    # CC-BY 4.0 = Tier A. Toggle name == SourceId value == _KNOWN_SOURCES entry;
    # the keys are separate SecretStr fields (db_client_id/db_api_key).
    DB_TIMETABLES = "db_timetables"
    # DATA-35: BORIS official standard land values by city (bulk, keyless). BORIS is
    # federated by federal state (one separate WFS per state, no nationwide
    # single endpoint) -> the BORIS_WFS registry (api.v1.cities) maps federal states
    # -> WFS configuration. Berlin license = DL-DE/Zero 2.0 (DL_DE_ZERO_2_0 already
    # exists). Read-only store access in the request path (like INKAR/KBA), no
    # resilient_client. Toggle name == SourceId value == _KNOWN_SOURCES entry:
    # getattr(settings, f“enable_{name}”).
    BORIS = "boris"
    # DATA-36: StaDa Station Data (station catalog per city: all stations in a
    # city with EVA, Geo, Category). Keyed live source via the same DB API
    # Marketplace as DB_TIMETABLES (same db_client_id/db_api_key), CC BY 4.0 =
    # Tier A. Toggle name == SourceId value == _KNOWN_SOURCES entry.
    STADA = "stada"
    # DATA-37: Regionalstatistik.de (GENESIS web service of the statistical offices):
    # Real estate tax rates (71231, down to the MUNICIPALITY level) + business registrations/deregistrations
    # (52311, at the district level). Bulk ingest → SQLite (no live call in the request path,
    # like INKAR/BORIS), but the GENESIS API has required
    # registration since 05/2025 (header auth username/password, ONLY during ingest, regio_user/
    # regio_pass). License DL-DE/BY 2.0 = Tier A (DL_DE_BY_2_0 already exists).
    # Toggle name == SourceId value == _KNOWN_SOURCES entry.
    REGIONALSTATISTIK = "regionalstatistik"
    # DATA-38 (Level 1): PVGIS solar irradiance + normalized PV yield per city
    # (EU JRC, keyless live calculation API re.jrc.ec.europa.eu PVcalc). PVGIS calculates
    # each EU coordinate -> all registered cities without a city allowlist. EU Reuse
    # Policy (EC_REUSE) = Tier A. Toggle name == SourceId value == _KNOWN_SOURCES-
    # entry: getattr(settings, f“enable_{name}”).
    SOLAR = "solar"
    # DATA-39 (Level 2): Roof solar cadastre by city (installed + installable
    # PV potential per municipality). Federated by federal state like BORIS; NRW pilot from the
    # official municipal aggregate (NRW Solar Cadastre, MaStR/LANUK/Geobasis NRW,
    # DL-DE/Zero 2.0 = Tier A). Seed-based (no live third-party API). Toggle name ==
    # SourceId value == _KNOWN_SOURCES entry: getattr(settings, f“enable_{name}”).
    SOLAR_CADASTRE = "solar_cadastre"
    # DATA-40: Munich Open Data, static/semi-static city sources via CKAN
    # (opendata.muenchen.de, DL-DE/BY 2.0 = Tier A). PARKING GARAGES = Parking garage
    # location catalog (NO real-time occupancy data); BIKE COUNTERS = Bicycle duration counting stations
    # (bike counts per counting station, updated monthly). Toggle name ==
    # SourceId value == _KNOWN_SOURCES entry: getattr(settings, f“enable_{name}”).
    MUENCHEN_PARKHAEUSER = "muenchen_parkhaeuser"
    MUENCHEN_RADZAEHL = "muenchen_radzaehl"
    # DATA-40: bike counts by city (municipal bike counting stations—open data, Tier A,
    # license verified by source). Toggle name == SourceId value == _KNOWN_SOURCES.
    LEIPZIG_RADZAEHL = "leipzig_radzaehl"
    HAMBURG_RADZAEHL = "hamburg_radzaehl"
    BERLIN_RADZAEHL = "berlin_radzaehl"
    STUTTGART_RADZAEHL = "stuttgart_radzaehl"
    KOELN_RADZAEHL = "koeln_radzaehl"
    ESSEN_RADZAEHL = "essen_radzaehl"
    DUESSELDORF_RADZAEHL = "duesseldorf_radzaehl"
    # DATA-40: ParkenDD Aggregator (api.parkendd.de, keylos) = preferred live
    # parking garage occupancy data for many cities (ONE adapter, deduplication principle). License
    # varies by city -> UNKNOWN/Tier C (Tier C pattern), attribution “ParkenDD”.
    # Toggle name == SourceId value == _KNOWN_SOURCES entry.
    PARKENDD = "parkendd"
    # DATA-OSM Tier 2: Lists of historic monuments by federal state (state matter, federated like
    # BORIS). On-demand WFS (GeoJSON), representative point per object. Berlin
    # verified (DL-DE/Zero 2.0 = Tier A); Bavaria CC-BY-ND = NOT usable
    # (fail-closed). Toggle name == SourceId value == _KNOWN_SOURCES entry.
    DENKMAL = "denkmal"
    # DATA-OSM Tier 2: Tree registry per city (municipal open data, on-demand WFS,
    # points). Berlin verified (DL-DE/Zero 2.0 = Tier A, ~900k street trees,
    # capped sample). Toggle Name == SourceId Value == _KNOWN_SOURCES entry.
    TREE_CADASTRE = "tree_cadastre"
    # DATA-OSM Tier 2: 2022 Census 100m grid (key-less ArcGIS Feature Server, NOT
    # the account-gated GENESIS-CENSUS-POST-API). Population density per city calculated exactly via
    # AGS aggregation. DL-DE/BY 2.0 = Tier A. Toggle == SourceId == _KNOWN_SOURCES.
    ZENSUS_GRID = "zensus_grid"
    # Phase 21: Public Procurement by City (Public Procurement Data Service
    # oeffentlichevergabe.de, OCDS 1.1 notices, CC0 = Tier A).
    # Bulk download (OCDS ZIP), city mapping via the Geo-Crosswalk seed
    # (NUTS-3/postal code). Toggle Name == SourceId Value == _KNOWN_SOURCES Entry:
    # getattr(settings, f“enable_{name}”). ASCII value (StrEnum), no umlauts.
    OEFFENTLICHEVERGABE = "oeffentlichevergabe"
    # DATA-41: District heating/heating network coverage by city from municipal
    # heating planning. Federated via city-specific WFS (such as BORIS/solar-roofs, license-verified
    # per source): Berlin = Energy Networks WFS (district heating network area incl.
    # 250 m buffer, DL-DE/Zero 2.0); Hamburg = WFS “Areas with Heating Networks” from
    # municipal heat planning (DL-DE/BY 2.0). Both Tier A. Batch ingest -> archive
    # (no WFS call in the request path, like bnetza); Route reads it in read-only mode. License/
    # attribution are specified per city in the record (Mapper retrieves them from the WFS registry).
    # Toggle name == SourceId value == _KNOWN_SOURCES entry.
    DISTRICT_HEATING = "district_heating"
    # Quick-260705-jgt: Cologne government office wait times (office-wait-times). Keyless
    # direct HTTP request to waiting-od.php (like KOELN_EVENTS), DL-DE/Zero 2.0 = Tier A.
    # Live data only (no archive). Value in ASCII lowercase (StrEnum), no umlauts.
    # Toggle name == SourceId value == _KNOWN_SOURCES entry: getattr(settings,
    # f“enable_{name}”).
    KOELN_WARTEZEITEN = "koeln_wartezeiten"
    # Quick-260705-ufv: BBK NINA Civil Protection Alerts (civil-protection-
    # warnings). Keyless GET request to warnung.bund.de/api31/dashboard/{ARS}.json,
    # ARS derived from the AGS registry. Live alerts only (no archive),
    # official warning text verbatim (LicenseId.AMTLICHES_WERK, Tier A). Value in ASCII
    # lowercase (StrEnum), no umlauts. Toggle name == SourceId value ==
    # _KNOWN_SOURCES entry: getattr(settings, f“enable_{name}”).
    BBK_NINA = "bbk_nina"
