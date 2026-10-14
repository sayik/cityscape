"""Central configuration (FND-02).

A single ``Settings`` source reads ``.env`` + environment variables with the
prefix ``CITYSCAPE_``. Per-source ``enable_*`` flags enable graceful
degradation; key fields are ``SecretStr | None`` (default None =
source unusable, no secrets in code).

MAINTAINABILITY (2026-06-21): The fields are grouped into thematic mixin classes
(CoreSettings, RateLimitSettings, AdminSettings, SourceToggleSettings,
CredentialSettings, MobilithekSettings, TransitSettings, BulkPathSettings,
MonitoringSettings). ``Settings`` inherits from all of them; pydantic merges the fields into
A SINGLE flat class. This is intentionally NOT a nested structure
(``settings.admin.password``): the fields remain flat (``settings.enable_vgn``)
because (a) the source toggles are resolved dynamically in multiple places via
``getattr(settings, f"enable_{name}")`` (sources/live/cities/
watchdog/admin) and (b) nested models would alter the env variable names
(``CITYSCAPE_ADMIN__PASSWORD`` instead of ``CITYSCAPE_ADMIN_PASSWORD``), which
would break the production .env. Add new fields to the thematically appropriate mixin class.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class CoreSettings(BaseSettings):
    """Infrastructure and runtime: logging, Redis, CORS, HTTP, data path."""

    log_level: str = "INFO"
    redis_url: str = "redis://redis:6379/0"
    # CORS: the public API is KEYLESS, READ-ONLY, and delivers open data
    # explicitly intended for arbitrary browser/client apps (vibecoders,
    # dashboards, starter templates on Vercel/Netlify/localhost). For such a
    # public data service API, "*" is the standard (cf. Open-Meteo,
    # Nominatim): the old whitelist silently blocked every cross-origin browser client.
    # Deliberate departure from the earlier "never *" rule; that applied to
    # credentialed APIs. Here, allow_credentials in main.py is set to False
    # as soon as "*" is active (CORS spec: "*" + credentials are mutually exclusive).
    # The admin dashboard is same-origin (cookie cs_admin SameSite=strict)
    # and untouched by CORS. Can be restricted to a whitelist via CITYSCAPE_CORS_ORIGINS
    # (in which case credentialed CORS is used again).
    cors_origins: list[str] = ["*"]

    # Optional override of the upstream User-Agent (RES-05). None = the
    # USER_AGENT constant from infra/http.py applies; can be overridden via
    # CITYSCAPE_HTTP_USER_AGENT (e.g. for staging identification).
    http_user_agent: str | None = None

    # Root path of the local data directory. Can be overridden via
    # CITYSCAPE_ARCHIVE_DIR so tests write to tmp_path instead of real data/.
    # (Field/env name unchanged for compatibility reasons.)
    archive_dir: str = "data/archive"

    # --- MCP/Redis Connection Backpressure (quick-260704-ust) ---
    # Three defensive caps against connection pool exhaustion. Purely defensive: in
    # normal operation, NOTHING changes (defaults mirror previous
    # effective values); the caps only kick in under overload. All eight fields
    # can be adjusted via CITYSCAPE_*-env without code deployment. INTENTIONALLY NOT part
    # of this change: switching the MCP server to stateless_http
    # (separate design decision) and auto-scaling.
    #
    # mcp_limit_concurrency is the ONLY real new overload cap: the
    # public MCP uvicorn (stateful, long-lived streamable-http sessions,
    # single worker) previously had ZERO backpressure (uvicorn default = unlimited).
    # Beyond this cap, uvicorn responds with 503 instead of flooding the event loop
    # indefinitely. 256 concurrent sessions are generously budgeted on the 8-vCPU box
    # with a single MCP worker.
    mcp_limit_concurrency: int = 256
    # Matches uvicorn's own default exactly (no behavioral change, just
    # explicitly set and therefore configurable).
    mcp_timeout_keep_alive: int = 5
    # Matches uvicorn's own default exactly (no behavioral change, just
    # explicitly set and therefore configurable).
    mcp_backlog: int = 2048
    # Generously caps previously unlimited socket growth of the Redis pool
    # (normal operation uses only a handful of connections; hitting this
    # cap is already an anomaly). Previously: no max_connections set.
    redis_max_connections: int = 150
    # Match httpx defaults (no behavioral change) for the
    # MCP loopback client; just explicitly set and therefore configurable.
    mcp_loopback_max_connections: int = 100
    mcp_loopback_max_keepalive: int = 20
    # The actual loopback defense: a SHORT pool-acquire cap instead of
    # today's 30s. A burst no longer accumulates for seconds on the
    # connection pool, but quickly falls into 503 handling.
    mcp_loopback_pool_timeout: float = 1.0
    # Keeps today's generous read timeout (upstreams behind the API can be
    # slow); deliberately NOT shortened to avoid cutting off slow sources.
    mcp_loopback_read_timeout: float = 30.0


class RateLimitSettings(BaseSettings):
    """IP rate limiting (API-06). True DoS protection resides with Cloudflare."""

    # limits/slowapi format ("<number>/<unit>"). The API is keyless/open; the
    # IP budget applies to ALL clients (DoS/scraping protection). Tiered
    # (security hardening 2026-06-21): a BURST budget per minute for short
    # data science/dashboard spikes AND a sustainable HOURLY budget against
    # continuous scraping. Both apply simultaneously: ANON_LIMIT combines them
    # semicolon-separated, slowapi/limits ``parse_many`` reads this as MULTIPLE
    # limits. Overridable via CITYSCAPE_LIMIT_ANON (e.g. tests).
    # History: previously flat 300/min (=18,000/h), then 120/min + 3000/h
    # (hardening 2026-06-21). Owner on 2026-06-24 raised to 300/min burst + 6000/h sustained
    # (average 100/min) so AI agents/power-user flows don't hit 429.
    # Non-critical: box with large headroom (~30% load, 6 free cores) +
    # CF edge cache/SWR + breaker; the limit is abuse prevention, not a
    # capacity throttle (target scale by year-end well < 1000 users/day).
    limit_anon: str = "300/minute"
    # Sustainable secondary limit over a longer window (empty = only limit_anon).
    limit_anon_sustained: str = "6000/hour"
    # Strict budget on admin login against password brute force (security audit
    # 2026-06-10, HIGH-1). Dedicated strict @limiter.limit decorator on route.
    limit_admin_login: str = "5/minute"
    # Sync Redis URI for slowapi's own limits storage (Pitfall 1: slowapi does
    # NOT share the async pool app.state.redis, but opens its own sync
    # connection to the SAME Redis server). None = fall back to redis_url
    # in the application (same server, separate connection).
    limit_storage_uri: str | None = None
    # Aggregated subnet limit against DISTRIBUTED bots (scraping hardening): the
    # IP limit above only catches a single IP; a botnet/cloud range with many
    # IPs bypasses it. This secondary limit throttles per /24 (IPv4) or /64 (IPv6).
    # INTENTIONALLY high (default 3000/min = ~10x the IP burst budget) so legitimate
    # NAT/campus users behind a shared IP are NOT affected; it
    # only triggers when untypically many requests come from ONE subnet. Empty
    # ("") = disabled. Overridable via CITYSCAPE_LIMIT_SUBNET.
    # Owner on 2026-06-24 raised from 1200 to 3000/min (proportional to the IP
    # burst raised to 300/min, ~10x ratio maintained -> no gap for
    # bot swarms, NAT protection preserved).
    limit_subnet: str = "3000/minute"
    subnet_ipv4_prefix: int = 24
    subnet_ipv6_prefix: int = 64
    # IP allowlist for RATE LIMIT BYPASS (comma-separated CIDR list, v4/v6
    # mixed, bare IPs = /32 or /128; e.g. "203.0.113.0/24,2001:db8::/32").
    # Purpose: Remote MCP traffic from Anthropic Connectors Directory arrives
    # server-side via FEW Anthropic egress IPs; per-IP/subnet limits
    # would throttle this legitimate aggregate. Allowlisted IPs bypass the
    # slowapi IP limit, AbuseGuard subnet limit, and MCP limit.
    # Limit bypass ONLY, NO auth; the admin login limit (brute force protection)
    # ALWAYS applies, even for allowlisted IPs. FAIL-SAFE: empty (default) or
    # invalid entries = nobody allowlisted (status quo behavior). Configurable
    # via env CITYSCAPE_RATELIMIT_ALLOWLIST without code deployment; the MCP
    # container reads the same env (infra/allowlist.py, stdlib-only).
    ratelimit_allowlist: str = ""
    # Rate limit per ChatGPT GPT user (api/v1/gpt_guard.py): OpenAI Actions
    # traffic arrives via FEW egress IPs (openai.com/chatgpt-actions.json),
    # which are allowlisted for this purpose; this limit is the backstop per
    # ephemeral OpenAI user identifier. Default like MCP endpoint (480/min,
    # Owner history see mcp/ratelimit.py). Empty ("") = disabled. Overridable
    # via CITYSCAPE_LIMIT_GPT.
    limit_gpt: str = "480/minute"
    # Optional Cloudflare bot score threshold (1-99; 0 = disabled). Applies
    # ONLY when Cloudflare sets the ``cf-bot-score`` header (Bot Management /
    # Enterprise). On Free/Pro the header is absent -> the check is a no-op hook
    # that automatically takes effect as soon as scores are available. Requests with
    # score < threshold are rejected with 403 (very likely bots).
    bot_score_min: int = 0


class AdminSettings(BaseSettings):
    """Admin dashboard (OPS-01/02): cookie session, network guard."""

    # admin_password protects /admin via cookie session (fail-closed: None = login
    # impossible, Best Practice 2). Both secret fields are SecretStr so the
    # value is never logged/serialized in plaintext. admin_session_secret signs
    # the session cookie (itsdangerous, >=32 bytes recommended). admin_log_max
    # limits the Redis circular buffer for request logs. admin_cookie_https_only sets
    # the Secure flag of the cookie (default True; settable to False only in tests/locally without TLS).
    admin_password: SecretStr | None = None
    admin_session_secret: SecretStr | None = None
    admin_log_max: int = 200
    admin_cookie_https_only: bool = True
    # Defense-in-depth for /admin (T-18-15): code-level network guard.
    # Operationally /admin is already Tailnet-only (Caddy returns 404 publicly,
    # ``tailscale serve`` runs without funnel, ufw opens 80/443 only for
    # Cloudflare). This guard additionally blocks ANY request with a publicly
    # routable client IP (real_client_ip) with 404 in case the Caddy 404 rule is
    # ever removed. Loopback/private/Tailnet-CGNAT (100.64.0.0/10) are always
    # permitted as non-globally routable; admin_trusted_networks optionally allows
    # additional (including globally routable) CIDRs (empty = non-global rule only).
    admin_trusted_networks: list[str] = []


class SourceToggleSettings(BaseSettings):
    """Per-source ``enable_*`` toggles (graceful degradation).

    IMPORTANT: Each toggle name MUST match exactly the SourceSpec name in the source
    registry (registry/source_specs.py, from which _KNOWN_SOURCES is derived) and
    the SourceId value, as it is resolved dynamically via
    ``getattr(settings, f"enable_{name}")``. Therefore, these fields remain flat
    on the Settings class (no nesting). The drift test
    tests/unit/test_source_specs_registry.py enforces that an enable_<name> toggle exists
    for every registry source. Keyed live sources default to True but remain
    "disabled" without credentials.
    """

    # Phase 4/6: Base sources.
    enable_wikidata: bool = True
    enable_dwd: bool = True
    enable_overpass: bool = True
    # Overpass endpoint operator-configurable (CITYSCAPE_OVERPASS_BASE_URL). The
    # public instance forbids third-party backends in continuous operation (fair use);
    # for production, switch to a self-hosted instance (planet dump) or a commercial
    # service (e.g. Geofabrik). Env = operator input (not user input) ->
    # SSRF invariant is preserved.
    overpass_base_url: str = "https://overpass-api.de/api/interpreter"
    # Audit K9: Element limit for the OSM/Overpass sample (POIs + all feature
    # data types). Previously hard 200 -> silently truncated ~67-87% of all objects (Cologne
    # playgrounds 200 instead of 1540). Default now 2000; the true total count
    # arrives independently via Overpass ``out count;`` as ``total_available`` +
    # ``truncated`` flag. Adjustable via CITYSCAPE_OVERPASS_MAX_ELEMENTS.
    overpass_max_elements: int = 2000
    enable_autobahn: bool = True
    enable_hvv: bool = False
    enable_delfi: bool = False
    # Phase 7: keyless, nationwide Tier-A sources (default True analogously to enable_dwd).
    # enable_lhp = flood data (record tag hochwasser). enable_bnetza controls ONLY the
    # /charging route (snapshot read from offline CSV since the ArcGIS outage, not live).
    enable_bnetza: bool = True
    enable_uba: bool = True
    enable_pegelonline: bool = True
    enable_lhp: bool = True
    enable_dwd_pollen: bool = True
    # DWD forest fire/grassland fire index (keyless, GeoNutzV, Tier A). Data via
    # a public ArcGIS FeatureServer (DWD data re-host). Host operator-
    # configurable (CITYSCAPE_DWD_FIRE_BASE_URL); Env = operator input (not
    # user input) -> SSRF invariant is preserved.
    enable_dwd_fire: bool = True
    dwd_fire_base_url: str = "https://services2.arcgis.com/7wuv6DH7DYhDuwvU/ArcGIS/rest/services/DWD/FeatureServer"
    # EEA bathing water quality (keyless, CC-BY 4.0, Tier A). Annual MapServer of the
    # EEA DiscoMap; the year portion of the URL + eea_bathing_year are updated
    # as soon as the EEA evaluates the new bathing season. Host operator-configurable
    # (CITYSCAPE_EEA_BATHING_BASE_URL) -> SSRF invariant is preserved.
    enable_eea_bathing: bool = True
    eea_bathing_base_url: str = (
        "https://water.discomap.eea.europa.eu/arcgis/rest/services/BathingWater/"
        "BathingWater_Dyna_WM_2025/MapServer/3"
    )
    eea_bathing_year: int = 2025
    # Federal Hospital Atlas (Bundes-Klinik-Atlas, BMG/IQTIG): site-accurate hospital list. FAIL-CLOSED:
    # NO explicit open license declared -> default DISABLED (Tier C/UNKNOWN)
    # until BMG/IQTIG confirms the license. Host operator-configurable.
    enable_klinik_atlas: bool = False
    klinik_atlas_base_url: str = (
        "https://bundes-klinik-atlas.de/fileadmin/json/locations.json"
    )
    # DB FaSta elevator/escalator status (DB API Marketplace, CC-BY 4.0, Tier A).
    # KEY-GATED: requires a free marketplace key (Plan Free4All).
    # KEYED via the SAME DB API Marketplace as db_timetables/stada: uses the
    # shared db_client_id/db_api_key (NO separate key, same application
    # "cityscape"). Without these credentials, the route returns source_status=disabled.
    # Host operator-configurable.
    enable_db_fasta: bool = True
    db_fasta_base_url: str = (
        "https://apis.deutschebahn.com/db-api-marketplace/apis/fasta/v2/facilities"
    )
    # Phase 8: account-gated sources default False (until credentials are set);
    # keyless bulk/seed sources default True (toggle controls only the route, not
    # the offline ingest). enable_genesis = demographics + hospital, enable_zensus
    # = Zensus host, enable_divi = clinic-specific DIVI live source (Tier C, optional).
    enable_genesis: bool = False
    # GENESIS Regionalstatistik trio (unemployment rate/tourism/construction activity per
    # district, DATA-28). Separate toggle with proper header-auth adapter, without touching
    # the demographics path. Requires the same genesis_username/-password.
    enable_genesis_regio: bool = True
    enable_zensus: bool = False
    enable_divi: bool = False
    enable_mastr: bool = True
    # SMARD electricity market data (consumption/grid load + day-ahead price), keyless CC BY 4.0.
    enable_smard: bool = True
    # DWD weather warnings (official warnings, WarnApp JSON), keyless GeoNutzV.
    enable_dwd_warnings: bool = True
    # KBA passenger car inventory + EV share per registration district (bulk, keyless DL-DE/BY).
    enable_kba: bool = True
    # Traffic accident atlas (road accidents per district, bulk CSV, keyless DL-DE/BY).
    enable_unfallatlas: bool = True
    # INKAR/BBSR socio-economic indicators per district (bulk, keyless DL-DE/BY).
    enable_inkar: bool = True
    # BKA-PKS police crime statistics per district (bulk XLSX, keyless DL-DE/BY, Tier A).
    enable_bka_pks: bool = True
    # Tankerkönig fuel prices (MTS-K, CC BY 4.0). KEYED: default True, but without
    # tankerkoenig_key the route returns 200 disabled. Toggle name == SourceId.
    enable_tankerkoenig: bool = True
    # DATA-33: GBFS bike/scooter sharing (live, aggregated, primary Nextbike CC0).
    # Keyless -> default True; per system license fail-closed against Tier-A allowlist.
    enable_gbfs: bool = True
    # DATA-34: DB Timetables (station departures for metropolitan central stations including long-distance).
    # KEYED: without db_client_id/db_api_key the route returns 200 disabled.
    enable_db_timetables: bool = True
    # DATA-35: BORIS official standard land values per city (bulk, keyless, federated
    # WFS per federal state). Read-only store read in request path.
    enable_boris: bool = True
    # DATA-36: StaDa Station Data (station catalog per city). Keyed via the same
    # DB API Marketplace as db_timetables (db_client_id/db_api_key, no separate key).
    enable_stada: bool = True
    # DATA-37: Regionalstatistik.de (property tax assessment rates 71231 + business registrations/
    # -deregistrations 52311). Bulk ingest -> SQLite (read-only in request path); without
    # regio_user/regio_pass returns 200 disabled (data could never be ingested).
    enable_regionalstatistik: bool = True
    # DATA-38 (Stage 1): PVGIS solar (EU JRC PVcalc, keyless live calculation API). PVGIS
    # computes for any EU coordinate -> all registry cities covered. Keyless ->
    # default True. Toggle name == SourceId.SOLAR == _KNOWN_SOURCES entry.
    enable_solar: bool = True
    # DATA-39 (Stage 2): Rooftop solar cadastre per city (seed-based, NRW pilot,
    # DL-DE/Zero 2.0). Partial coverage (NRW), federated per federal state like BORIS.
    enable_solar_cadastre: bool = True
    # DATA-40: Munich Open Data (CKAN, keyless, DL-DE/BY 2.0). parkhaeuser =
    # static parking garage location catalog; radzaehl = continuous bike counting stations
    # (updated monthly). Both keyless -> default True. Partial coverage
    # (only Munich) until further cities are supported.
    enable_muenchen_parkhaeuser: bool = True
    enable_muenchen_radzaehl: bool = True
    # DATA-40 bike-counts: municipal bicycle counting stations per city (keyless, Tier A).
    enable_leipzig_radzaehl: bool = True
    enable_hamburg_radzaehl: bool = True
    enable_berlin_radzaehl: bool = True
    enable_stuttgart_radzaehl: bool = True
    enable_koeln_radzaehl: bool = True
    enable_essen_radzaehl: bool = True
    enable_duesseldorf_radzaehl: bool = True
    # DATA-40: ParkenDD aggregator (keyless) = preferred live parking occupancy for
    # many cities. Default True (keyless). Replaces /live/dortmund/parking (dedup).
    enable_parkendd: bool = True
    # DATA-OSM-Tier-2: Monument lists per federal state (on-demand WFS, keyless). Default
    # True. Coverage-gated (registry.coverage), only verified open states.
    enable_denkmal: bool = True
    # DATA-OSM-Tier-2: Tree cadastre per city (municipal on-demand WFS, keyless).
    # Default True. Coverage-gated, only verified openly licensed cities.
    enable_baumkataster: bool = True
    # DATA-OSM-Tier-2: Zensus 2022 100m grid (keyless ArcGIS FeatureServer) for
    # population density per city. Default True (keyless, DL-DE/BY).
    enable_zensus_grid: bool = True
    # Phase 21: Public procurement per city (oeffentlichevergabe.de OCDS,
    # CC0 = Tier A). Bulk download, keyless. Default True.
    enable_oeffentlichevergabe: bool = True
    # DATA-41: District heating / heating network coverage per city (municipal heating planning,
    # federated per city WFS, keyless). Default True. Coverage-gated
    # (registry.coverage), only verified openly licensed cities (berlin/hamburg).
    enable_district_heating: bool = True
    enable_bkg: bool = True
    enable_bundeswahl: bool = True
    enable_feiertage: bool = True
    # Phase 9: keyless municipal traffic sources (construction sites/road closures) per city +
    # Autobahn webcam sub-service. All keyless, hence default True.
    enable_berlin_viz: bool = True
    enable_hamburg_baustellen: bool = True
    enable_koeln_verkehr: bool = True
    enable_muenchen_baustellen: bool = True
    enable_dortmund_baustellen: bool = True
    # SPERRINFOSYS Saxony: keyless, ONE source for Dresden + Leipzig.
    enable_sperrinfosys: bool = True
    enable_mobidata_bw: bool = True
    enable_autobahn_webcam: bool = True
    # Phase 10: City events. destination.one is KEYLESS (Experience
    # "open-data" freely accessible, support confirmation 2026-06-10) -> default True.
    enable_destination_one: bool = True
    enable_koeln_events: bool = True
    # Phase 19: GTFS-Realtime trip updates (live public transit delays). Default False
    # until actively switched. Resolved via getattr(settings, "enable_gtfs_rt").
    enable_gtfs_rt: bool = False
    # DATA-24/25/26: Live departures / traffic situation. enable_hvv_geofox KEYED (default
    # False, requires hvv_api_key + hvv_user). enable_vgn keyless (open VAG-Puls
    # API, CC-BY 4.0). enable_hamburg_verkehrslage keyless (OAF/GeoJSON, DL-DE/BY 2.0).
    enable_hvv_geofox: bool = False
    enable_vgn: bool = True
    enable_hamburg_verkehrslage: bool = True
    # Phase 20: Mobilithek mTLS live sources (live = cert + subscription required, hence all
    # default False until certificate and subscription ID are set). Exception:
    # dortmund_parking is KEYLESS since 2026-06-13 (direct Opendatasoft feed) ->
    # default True; dortmund_parking_abo_id unused (kept for SSRF consistency).
    enable_koeln_traffic_flow: bool = False
    enable_koeln_baustellen_live: bool = False
    enable_koeln_ereignisse_live: bool = False
    enable_koeln_lez_live: bool = False
    enable_berlin_verkehrsmeldungen: bool = False
    enable_dortmund_parking: bool = True
    enable_kiel_zaehlstellen: bool = False
    enable_eround_charging: bool = False
    # Quick-260705-jgt: Cologne municipal office wait times (office-wait-times). KEYLESS
    # (direct HTTPS feed waiting-od.php, like enable_dortmund_parking) -> default
    # True. Toggle name == SourceId value.
    enable_koeln_wartezeiten: bool = True
    # Quick-260705-ufv: BBK NINA civil protection warnings (civil-protection-
    # warnings). KEYLESS (GET warnung.bund.de/api31/dashboard/{ARS}.json, like
    # enable_dwd_warnings) -> default True. Toggle name == SourceId value.
    enable_bbk_nina: bool = True
    # DATA-31: Bremen construction sites (Mobilithek DATEX II Situation, DL-DE/BY 2.0).
    enable_bremen_baustellen: bool = False
    # Hanover traffic messages (Mobilithek DATEX II V2 Situation, DL-DE/BY 2.0).
    # Live = cert + subscription required -> default False until certificate + subscription ID are set.
    enable_hannover_verkehrsmeldungen: bool = False
    # Frankfurt am Main parking data (Mobilithek DATEX II V3 Parking, static +
    # dynamic joined, DL-DE/BY 2.0). Live = cert + subscription required -> default False
    # until certificate and both subscription IDs are set.
    enable_frankfurt_parking: bool = False
    # Wuppertal parking data (Mobilithek DATEX II V2 ParkingFacility, static +
    # dynamic joined, DL-DE/Zero 2.0). Live = cert + subscription -> default False.
    enable_wuppertal_parking: bool = False
    # Magdeburg parking data (Mobilithek DATEX II V2 ParkingFacility, static +
    # dynamic). Shares Wuppertal V2 parser; occupancy for Magdeburg
    # is already percentage (not fraction 0..1). Default False until subscription IDs + live verification.
    enable_magdeburg_parking: bool = False


class CredentialSettings(BaseSettings):
    """API keys / credentials of external sources. All secrets as SecretStr | None.

    None = source unusable (graceful degradation). Secrets are passed ONLY into
    header/body/query of the respective upstream request, NEVER into cache key/response/
    log. Values come from gitignored .env (env names via prefix).
    """

    # Phase 8 GENESIS/Zensus (account-gated POST API). Field name genesis_username
    # because the Owner specifically set CITYSCAPE_GENESIS_USERNAME (+ _PASSWORD) in .env.
    # Zensus may use a separate account (dedicated fields).
    genesis_username: str | None = None
    genesis_password: SecretStr | None = None
    zensus_user: str | None = None
    zensus_password: SecretStr | None = None
    # HVV Geofox GTI live departures (DATA-24): hvv_api_key = HMAC secret, hvv_user =
    # geofox-auth-user. Both passed only in header/body of signed Geofox request.
    hvv_api_key: SecretStr | None = None
    hvv_user: str | None = None
    # DATA-30: Tankerkönig API key. Only in query parameter ``apikey``. None ->
    # route returns 200 source_status="disabled". Env CITYSCAPE_TANKERKOENIG_KEY.
    tankerkoenig_key: SecretStr | None = None
    # DATA-34: DB Timetables credentials (DB API Marketplace). Only in headers
    # DB-Client-Id/DB-Api-Key. None -> route 200 disabled.
    db_client_id: SecretStr | None = None
    db_api_key: SecretStr | None = None
    # DATA-37: Regionalstatistik.de GENESIS webservice (header auth username/
    # password). Only in ingest request headers. None -> /tax-rates +
    # /business-registrations 200 disabled (bulk could never be ingested).
    regio_user: SecretStr | None = None
    regio_pass: SecretStr | None = None


class MobilithekSettings(BaseSettings):
    """Mobilithek mTLS: certificate + per-source subscription IDs (SSRF allowlist).

    The aboId in the Mobilithek pull URL NEVER comes from user input, only from these
    fields (RESEARCH Pitfall 7). None = source cannot be resolved. Subscription IDs from
    mobilithek.info -> My Subscriptions -> Details page (HTTPS access point).
    """

    # cert_path optional (None = no live source usable); cert_password SecretStr
    # (never logged in plaintext). httpx/ssl cannot read .p12 directly ->
    # cryptography converts to PEM on startup (infra/mobilithek.py).
    mobilithek_cert_path: str | None = None
    mobilithek_cert_password: SecretStr | None = None
    koeln_traffic_flow_abo_id: str | None = None
    koeln_baustellen_live_abo_id: str | None = None
    koeln_ereignisse_live_abo_id: str | None = None
    koeln_lez_live_abo_id: str | None = None
    berlin_verkehrsmeldungen_abo_id: str | None = None
    # dortmund_parking is keyless since 2026-06-13 -> unused, kept for SSRF consistency.
    dortmund_parking_abo_id: str | None = None
    kiel_zaehlstellen_abo_id: str | None = None
    eround_charging_abo_id: str | None = None
    # eRound STAT subscription (DATA-42 Stage 1): static complete location inventory
    # (aegiEnergyInfrastructureTablePublication, ~94 MB JSON) for the daily
    # geo-map (refill_point_id -> city). Pulled ONLY by batch ingest
    # (ingest.eround_geo), NEVER in request path. SSRF allowlist.
    eround_locations_abo_id: str | None = None
    # Target / read path for the eRound geo-map in the persistent data volume. The
    # request path falls back to the committed seed if the file is missing.
    eround_geo_map_path: str = "data/eround/eround_geo_map.json"
    bremen_baustellen_abo_id: str | None = None
    # Hanover traffic messages (DATEX II V2 SituationPublication, path-pull).
    # Subscription ID from portal (details page HTTPS access point); SSRF allowlist
    # (aboId NEVER from user input).
    hannover_verkehrsmeldungen_abo_id: str | None = None
    # Frankfurt parking data: TWO subscriptions (DATEX II V3, container pull). The dynamic
    # subscription carries occupancy (free/utilization), the static one carries master data
    # (name/geo/capacity); the adapter joins both on parkingRecord ID.
    # Both in SSRF allowlist (aboId NEVER from user input).
    frankfurt_parking_abo_id: str | None = None
    frankfurt_parking_static_abo_id: str | None = None
    # Wuppertal parking data: TWO subscriptions (DATEX II V2 ParkingFacility, path pull).
    # dynamic = occupancy, static = master data; joined on parkingFacility ID.
    wuppertal_parking_abo_id: str | None = None
    wuppertal_parking_static_abo_id: str | None = None
    # Magdeburg parking data: TWO subscriptions (DATEX II V2 ParkingFacility, path pull).
    # dynamic = occupancy, static = master data; joined on parkingFacility ID.
    # Both in SSRF allowlist (aboId NEVER from user input).
    magdeburg_parking_abo_id: str | None = None
    magdeburg_parking_static_abo_id: str | None = None


class TransitSettings(BaseSettings):
    """GTFS-Realtime source switching (Phase 19, live transit delays)."""

    # Source switching (RESEARCH Pattern 7): "gtfs_de" (verified primary
    # source, no key) | "mobilithek_delfi" (mTLS pull, returns as of 2026-06-12
    # 422 = no_data). Default gtfs_de until Mobilithek subscription delivers real packets.
    transit_rt_source: str = "gtfs_de"
    # Mobilithek DELFI Realtime subscription ID as SSRF allowlist (aboId NEVER from user input).
    # None = source cannot be resolved. Owner subscription only in gitignored .env
    # (CITYSCAPE_TRANSIT_RT_DELFI_ABO_ID).
    transit_rt_delfi_abo_id: str | None = None


class BulkPathSettings(BaseSettings):
    """Local paths for offline / batch ingest (NOT in request path).

    None = batch cannot run or batch fetches source keylessly directly from
    upstream. Ingests run exclusively as manual batch commands (python -m).
    """

    # GTFS ZIPs for batch ingest (DATA-05). None = batch aborts with exit code 2.
    delfi_gtfs_path: str | None = None
    hvv_gtfs_path: str | None = None
    # Phase 19: SEPARATE static path for GTFS-RT resolution. The gtfs.de free
    # feed references gtfs.de's OWN static schedule (numeric IDs, CC-BY-SA Tier B,
    # renewed weekly via transit.refresh). Must NOT point to the DELFI ZIP
    # (CC-BY 4.0 Tier A), otherwise license scopes mix. None =
    # fallback to delfi_gtfs_path (tests / Mobilithek source with DELFI IDs).
    gtfs_rt_static_path: str | None = None
    # Phase 8: Bulk files for offline ingest (None = batch aborts with exit code 2).
    mastr_zip_path: str | None = None
    bkg_path: str | None = None
    bundeswahl_csv_path: str | None = None
    divi_csv_path: str | None = None
    # KBA bulk (DATA-27): None = batch fetches dataset directly keyless from KBA portal.
    kba_source_path: str | None = None
    # Traffic accident atlas bulk (DATA-29): None = batch fetches latest year from NRW portal.
    unfallatlas_source_path: str | None = None
    # INKAR bulk (DATA-32): None = batch fetches indicators live from www.inkar.de.
    inkar_source_path: str | None = None
    # BKA-PKS bulk (PKS-02): None = batch probes latest year live from www.bka.de.
    bka_pks_source_path: str | None = None
    # BORIS bulk (DATA-35): None = batch fetches standard land values live from state WFS.
    boris_source_path: str | None = None
    # Regionalstatistik bulk (DATA-37): None = batch fetches tables live from
    # GENESIS webservice (regio_user/regio_pass).
    regio_source_path: str | None = None


class MonitoringSettings(BaseSettings):
    """Monitoring / alerting / self-healing (OPS-06/07/08).

    Notifier channels (ntfy + email), dead-man ping, external liveness ping. Token
    and password are SecretStr | None = None (fail-closed: no sending without value).
    """

    # ntfy: push channel. ntfy_topic is effectively a password (only a-z/0-9/_/-).
    ntfy_url: str | None = None
    ntfy_topic: str | None = None
    ntfy_token: SecretStr | None = None
    # SMTP: email backup channel. smtp_ssl=False = STARTTLS port 587 (default),
    # smtp_ssl=True = SMTP_SSL port 465 (decision SMTP transport mode).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_to: str | None = None
    smtp_ssl: bool = False
    # Notification throttle (flood/crash protection): max number of NON-critical
    # pushes (INFO/WARNING) per time window and process. When cap is exceeded,
    # further pushes are suppressed (exactly ONE advisory per window is
    # emitted); CRITICAL is exempt and always passes through. Protects against ntfy/SMTP
    # floods (thread/socket congestion, mail provider block) during first-contact/MCP bursts.
    # 0 or negative = throttle disabled.
    notify_max_per_window: int = 20
    notify_window_seconds: int = 60
    # Dead-man ping (Kuma push or Healthchecks.io) per timer job; overridable via systemd drop-in.
    # None = no ping.
    deadman_url: str | None = None
    # Dead-man ping for the 08:00 digest (CR-05): dedicated Kuma push monitor
    # ("digest", ~26 h heartbeat). None = no ping (graceful).
    digest_deadman_url: str | None = None
    # External box liveness ping (Finding 8): watchdog pings this URL at the end
    # of each successful run. The URL carries a UUID and should be treated like a secret
    # (only via .env/systemd drop-in, never committed).
    healthchecks_url: str | None = None
    # Self-heal reprobe (A, 2026-06-14): opt-in list of hard-disabled sources whose
    # upstream the watchdog periodically probes directly to send exactly one
    # "X is reactivatable" ntfy upon recovery. Format (comma-
    # separated): ``source=https://probe.url,source2=https://probe.url2``. Only for
    # sources that were INTENTIONALLY disabled via enable_* toggle during an outage;
    # sources left enabled heal automatically via persistent breaker.
    # Probe URLs are owner-controlled (no user input -> no SSRF). Empty = disabled.
    selfheal_probes: str = ""
    # Capacity / saturation early warning (OPS-08, 2026-07-04): watchdog warns
    # the owner via WARNING push BEFORE the single API replica saturates, allowing
    # timely manual scaling (Stage 1: alert only, no auto-scaling).
    # Intentionally conservative defaults (early warning, not capacity governor):
    # capacity_load_per_core_warn = 0.75 leaves headroom on 8-vCPU box
    # before 1-min load per core becomes critical. capacity_redis_mem_warn = 0.80
    # warns before Redis memory usage (used_memory/maxmemory) reaches eviction threshold.
    # capacity_hysteresis_ticks = 2 requires two consecutive breaches so a single
    # peak load tick does not trigger a false alarm. All three overridable via CITYSCAPE_CAPACITY_*-env.
    capacity_load_per_core_warn: float = 0.75
    capacity_redis_mem_warn: float = 0.80
    capacity_hysteresis_ticks: int = 2


class Settings(
    CoreSettings,
    RateLimitSettings,
    AdminSettings,
    SourceToggleSettings,
    CredentialSettings,
    MobilithekSettings,
    TransitSettings,
    BulkPathSettings,
    MonitoringSettings,
):
    """Validated application settings from env/.env (prefix CITYSCAPE_).

    Inherits all fields flat from thematic mixin classes above. ``model_config``
    resides ONLY here (applies via inheritance to all inherited fields). Access remains
    flat: ``settings.enable_vgn``, ``getattr(settings, "enable_<name>")``,
    env ``CITYSCAPE_<FIELD>`` - unchanged relative to previous flat class.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CITYSCAPE_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Singleton access to settings (cached for the process)."""
    return Settings()
