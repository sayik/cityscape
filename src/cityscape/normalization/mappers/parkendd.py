"""Reiner ParkenDD-Mapper map_parkendd (DATA-40, Live Parking, Tier A per city).

Deterministically translates the raw adapter dictionary (``slug``/``facilities``/``as_of``)
into a ``CanonicalRecord`` with ``ParkingPayload``. Pure: no HTTP, no
system clock (``retrieved_at`` injected as a keyword only).

LICENSE (B-1, GOV-01): ParkenDD aggregates heterogeneously licensed city sources without
a uniform license. The license is therefore verified PER CITY at the actual source
(``_PARKENDD_LICENSE``) and carried with the correct tier (CC0/DL-DE-Zero/DL-DE-BY/
CC-BY, per city; all Tier A). ONLY cities with an open standard license
are delivered (owner decision 2026-06-23: no Tier B/C/NC delivery); the
remaining cities are removed from ``PARKENDD_CITIES`` (not_covered). Pure live data.
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    ParkingPayload,
    SourceId,
)

_PARKENDD_URL = "https://github.com/ParkenDD"

# Kanonische Lizenz-Deed-URL je LicenseId (Attribution.license_url). Für nicht
# gelistete (UNKNOWN) Lizenzen bleibt die ParkenDD-Projektseite die Quellangabe.
_LICENSE_DEED: dict[LicenseId, str] = {
    LicenseId.DL_DE_BY_2_0: "https://www.govdata.de/dl-de/by-2-0",
    LicenseId.DL_DE_ZERO_2_0: "https://www.govdata.de/dl-de/zero-2-0",
    LicenseId.CC0: "https://creativecommons.org/publicdomain/zero/1.0/",
    LicenseId.CC_BY_4_0: "https://creativecommons.org/licenses/by/4.0/",
}

# Per-Stadt-Lizenz der Parkdaten-URSPRUNGSQUELLE (NICHT ParkenDD selbst): ParkenDD
# aggregiert heterogen lizenzierte Stadt-Quellen, daher wird die Lizenz je Stadt an
# der echten Quelle verifiziert und hier getragen (Owner-Entscheidung 2026-06-23:
# "Ursprung je Stadt verifizieren"). Eintrag: slug -> (LicenseId, LicenseTier,
# attribution_text). Lizenz-Recherche je Ursprung 2026-06-23: genau diese 13
# ParkenDD-Städte führen am Ursprung eine OFFENE Standardlizenz und werden
# ausgeliefert (deckungsgleich mit ``adapters.parkendd.PARKENDD_CITIES``); die
# übrigen 9 wurden entfernt (bonn CC BY-NC, hanau/ingolstadt/nuernberg proprietär,
# luebeck/magdeburg/mannheim/regensburg/wiesbaden ohne auffindbare Lizenz). Der
# ``_DEFAULT_LICENSE`` (UNKNOWN/C) ist nur noch ein Fail-safe (keine ausgelieferte
# Stadt fällt darauf).
_PARKENDD_LICENSE: dict[str, tuple[LicenseId, LicenseTier, str]] = {
    "aachen": (LicenseId.CC0, LicenseTier.A, "APAG - Aachener Parkhaus GmbH"),
    "dortmund": (LicenseId.DL_DE_ZERO_2_0, LicenseTier.A, "Stadt Dortmund"),
    "dresden": (LicenseId.DL_DE_BY_2_0, LicenseTier.A, "Landeshauptstadt Dresden"),
    "freiburg-im-breisgau": (LicenseId.DL_DE_BY_2_0, LicenseTier.A, "Stadt Freiburg"),
    "hamburg": (
        LicenseId.DL_DE_BY_2_0,
        LicenseTier.A,
        "Freie und Hansestadt Hamburg, Behörde für Verkehr und Mobilitätswende",
    ),
    "heidelberg": (
        LicenseId.CC_BY_4_0,
        LicenseTier.A,
        "Stadt Heidelberg, Amt für Mobilität",
    ),
    # Namensnennung wortgenau "Stadtwerke Heilbronn" (NICHT "Stadt Heilbronn").
    "heilbronn": (LicenseId.DL_DE_BY_2_0, LicenseTier.A, "Stadtwerke Heilbronn"),
    "kaiserslautern": (LicenseId.CC0, LicenseTier.A, "Stadtverwaltung Kaiserslautern"),
    "karlsruhe": (LicenseId.CC_BY_4_0, LicenseTier.A, "Stadt Karlsruhe"),
    "koeln": (LicenseId.DL_DE_ZERO_2_0, LicenseTier.A, "Stadt Köln"),
    "muenster": (LicenseId.DL_DE_BY_2_0, LicenseTier.A, "Stadt Münster"),
    "oldenburg": (LicenseId.DL_DE_BY_2_0, LicenseTier.A, "Stadt Oldenburg (Oldb)"),
    "ulm": (LicenseId.CC0, LicenseTier.A, "Stadt Ulm"),
}

# Fail-safe für einen nicht gelisteten Slug (sollte nie ausgeliefert werden, da
# PARKENDD_CITIES == Schlüssel dieser Map): ehrlich UNKNOWN/Tier C.
_DEFAULT_LICENSE: tuple[LicenseId, LicenseTier, str] = (
    LicenseId.UNKNOWN,
    LicenseTier.C,
    "ParkenDD",
)


def _parse_as_of(value: object) -> datetime | None:
    """Parst den ParkenDD-``last_updated``-String defensiv zu datetime (sonst None)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def map_parkendd(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps raw ParkenDD parking data to a ``CanonicalRecord`` (Tier C).

    The ``facilities`` (parking garages with free/total/status) are transferred unchanged
    to the ``ParkingPayload``. ``observed_at`` comes from the ParkenDD dataset
    (``as_of``), ``geo=None`` (coordinates for each facility in the payload). ``license_id``/
    ``license_tier``/attribution come from ``_PARKENDD_LICENSE`` PER CITY (
    verified at source); unlisted cities are honestly classified as UNKNOWN/Tier C.
    """
    slug = raw["slug"]
    license_id, license_tier, attribution_text = _PARKENDD_LICENSE.get(
        slug, _DEFAULT_LICENSE
    )
    license_url = _LICENSE_DEED.get(license_id, _PARKENDD_URL)
    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=_parse_as_of(raw.get("as_of")),
        retrieved_at=retrieved_at,
        source=SourceId.PARKENDD,
        license_id=license_id,
        license_tier=license_tier,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=attribution_text,
            license_url=license_url,
        ),
        payload=ParkingPayload(
            facilities=raw.get("facilities", []),
        ),
    )
