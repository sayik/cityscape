"""Reiner Mapper map_public_tender (DATA-21, public procurement).

Deterministically maps an OCDS Notice dictionary parsed by the adapter (``adapters.oeffentlichevergabe.parse_ocds_release``)
to a ``CanonicalRecord`` with
``PublicTenderPayload`` (``kind=“public_tender”``). The source is the
Public Procurement data service (oeffentlichevergabe.de, Procurement Office of the BMI), CC0 =
Tier A.

City mapping does NOT take place here, but rather in
``cityscape.tenders.matching``; the mapper takes the already resolved
``slug`` and the ``match`` list (``buyer_city`` | ``place_of_performance``) as
arguments and writes them to the payload. ``buyer_city`` contains the
(slugified) city reference, while ``nuts`` contains the contracting authority’s NUTS 3 code.

Pure: no I/O, no logging, no wall clock. The ``retrieved_at`` timestamp
is injected; ``observed_at`` is derived from the ``publication_date`` of the
notice (if parseable, otherwise None). Geo data is not available
(``geo=None``).
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    PublicTenderPayload,
    SourceId,
)

# CC Zero 1.0 (Public Domain). Verbatim deckungsgleich mit
# SOURCE_LICENSE["oeffentlichevergabe"] / DATA-LICENSES.md (Lizenz-Drift-Gate).
_CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
_ATTRIBUTION = (
    "Datenservice Oeffentlicher Einkauf (oeffentlichevergabe.de) "
    "/ Beschaffungsamt des BMI"
)

# Stabile Notice-URL auf der Plattform (aus der fachlichen notice_id abgeleitet).
_NOTICE_URL_PREFIX = "https://oeffentlichevergabe.de/notices/"


def _parse_observed_at(value: str | None) -> datetime | None:
    """Parses an ISO-8601 publication date conservatively (unparseable -> None).

    Pure and without wall clock: only ``datetime.fromisoformat`` (which understands the OCDS ISO
    string, including the time zone). A missing or invalid value results in None.
    The ``CanonicalRecord`` validator handles the canonical UTC normalization.
    Validator.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None


def _source_url(notice: dict) -> str | None:
    """Derives a stable notice URL from the notice_id (or None)."""
    notice_id = notice.get("notice_id")
    if isinstance(notice_id, str) and notice_id.strip():
        return f"{_NOTICE_URL_PREFIX}{notice_id.strip()}"
    return None


def map_public_tender(
    notice: dict,
    *,
    slug: str,
    match: list[str],
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps an OCDS notice dictionary to a Tier-A ``CanonicalRecord``.

    ``slug`` is the already resolved registry city slug (city mapping in
    ``tenders.matching``), and ``match`` is the source list (``buyer_city`` |
    ``place_of_performance``). Both are written to the ``PublicTenderPayload``
    . ``buyer_city`` contains the slug reference, and ``nuts`` contains the NUTS-3 code
    of the contracting authority (``buyer_region`` from the parsed Notice-dict).

    Input: no I/O. ``observed_at`` from ``publication_date`` (if parseable);
    ``retrieved_at`` injected; ``geo=None``. Source CC0 = Tier A.
    """
    payload = PublicTenderPayload(
        notice_id=notice.get("notice_id"),
        notice_version=notice.get("notice_version"),
        notice_type=notice.get("notice_type"),
        status=notice.get("status"),
        title=notice.get("title"),
        buyer_name=notice.get("buyer_name"),
        buyer_city=slug,
        buyer_postal_code=notice.get("buyer_postal_code"),
        nuts=notice.get("buyer_region"),
        cpv=notice.get("cpv"),
        value=notice.get("value"),
        currency=notice.get("currency"),
        publication_date=notice.get("publication_date"),
        deadline=notice.get("deadline"),
        award_date=notice.get("award_date"),
        match=list(match),
        source_url=_source_url(notice),
    )

    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=_parse_observed_at(notice.get("publication_date")),
        retrieved_at=retrieved_at,
        source=SourceId.OEFFENTLICHEVERGABE,
        license_id=LicenseId.CC0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(text=_ATTRIBUTION, license_url=_CC0_URL),
        payload=payload,
    )
