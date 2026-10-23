"""Pure Regional Statistics Mapper (DATA-37, DL-DE/BY 2.0, Tier A).

Deterministically maps the reader rows from ``archive.regionalstatistik_db`` to
a ``CanonicalRecord``: ``map_tax_rates`` (property tax rates, table
71231) and ``map_business_registrations`` (business registrations/deregistrations, table
52311). Pure: no HTTP, no logging, no ``datetime.now()`` (``retrieved_at``
is injected).

The source is the GENESIS web service of the Federal and State Statistical Offices
(regionalstatistik.de). License: DL-DE/BY 2.0, attribution must be verbatim
“Federal and State Statistical Offices” (must appear verbatim in DATA-LICENSES.md
+ SOURCE_LICENSE; T-11-SRC-DRIFT). The values are unmodified
source metrics (`modified=False`); `geo` remains `None` (municipality/
county level), `observed_at` remains `None` (reference date/year is included in the payload).
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    BusinessRegistrationsPayload,
    CanonicalRecord,
    InsolvenciesPayload,
    LicenseId,
    LicenseTier,
    SourceId,
    TaxRatesPayload,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"
_ATTRIBUTION = "Statistische Ämter des Bundes und der Länder"


def _record(slug: str, payload, *, retrieved_at, ags, wikidata_qid) -> CanonicalRecord:
    """Baut den gemeinsamen CanonicalRecord-Envelope beider Regionalstatistik-Mapper."""
    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.REGIONALSTATISTIK,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_ATTRIBUTION,
            license_url=_DL_DE_BY_URL,
            modified=False,
        ),
        payload=payload,
    )


def map_tax_rates(
    slug: str,
    row: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps a city's tax rate row to a ``CanonicalRecord`` (71231).

    ``row`` is the dict returned by the reader (``business_tax``/``property_tax_a``/
    ``property_tax_b``/``property_tax_c``/``reference_date``). ``retrieved_at`` is
    injected (no ``datetime.now()`` in the mapper). The join keys ``ags``/
    ``wikidata_qid`` are passed through from the register.
    """
    payload = TaxRatesPayload(
        gewerbesteuer_hebesatz=row.get("gewerbesteuer"),
        grundsteuer_a=row.get("grundsteuer_a"),
        grundsteuer_b=row.get("grundsteuer_b"),
        grundsteuer_c=row.get("grundsteuer_c"),
        stichtag=row.get("stichtag"),
    )
    return _record(
        slug, payload, retrieved_at=retrieved_at, ags=ags, wikidata_qid=wikidata_qid
    )


def map_business_registrations(
    slug: str,
    row: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps a city's business listings row to a ``CanonicalRecord``.

    ``row`` is the dict provided by the reader (``anmeldungen``/``abmeldungen``/
    ``saldo``/``jahr``, Table 52311). ``retrieved_at`` is injected. The
    join keys ``ags``/``wikidata_qid`` are passed through from the register.
    """
    payload = BusinessRegistrationsPayload(
        anmeldungen=row.get("anmeldungen"),
        abmeldungen=row.get("abmeldungen"),
        saldo=row.get("saldo"),
        jahr=row.get("jahr"),
    )
    return _record(
        slug, payload, retrieved_at=retrieved_at, ags=ags, wikidata_qid=wikidata_qid
    )


def map_insolvencies(
    slug: str,
    row: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps a city's insolvency row to a ``CanonicalRecord``.

    ``row`` is the dict returned by the reader (``corporate_insolvencies``/
    ``other_debtor_insolvencies``/``year``, tables 52411-02 ISV006 + 52411-03
    ISV007). ``retrieved_at`` is injected (no ``datetime.now()`` in the mapper).
    The join keys ``ags``/``wikidata_qid`` are passed through from the register.
    """
    payload = InsolvenciesPayload(
        unternehmensinsolvenzen=row.get("unternehmensinsolvenzen"),
        uebrige_schuldner_insolvenzen=row.get("uebrige_schuldner_insolvenzen"),
        jahr=row.get("jahr"),
    )
    return _record(
        slug, payload, retrieved_at=retrieved_at, ags=ags, wikidata_qid=wikidata_qid
    )
