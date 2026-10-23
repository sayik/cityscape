"""Pure INKAR mapper ``map_indicators`` (BBSR indicators, DL-DE/BY 2.0, Tier A).

Deterministically maps the indicator rows from the SQLite reader
(``archive.inkar_db.read_indicators``) to a
``CanonicalRecord`` with ``IndicatorsPayload``. Pure: no HTTP, no logging,
no ``datetime.now()`` (``retrieved_at`` is injected).

Source: Federal Institute for Research on Building, Urban Affairs, and Spatial Development (BBSR) /
INKAR (Indicators and Maps for Spatial and Urban Development). License: DL-DE/BY
2.0, attribution must be verbatim: “Federal Institute for Research on Building, Urban Affairs, and Spatial Development
(BBSR), INKAR” (must appear verbatim in DATA-LICENSES.md + SOURCE_LICENSE). The
values are unmodified source metrics (``modified=False``); ``geo`` remains
``None`` (county/city level), ``observed_at`` remains ``None`` (the year is specified
for each indicator in the payload).
"""

from __future__ import annotations

import re
from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    IndicatorsPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"

# INKAR führt die Einheit nur im name-String als Klammerzusatz "(in %)" / "(in EUR)"
# (Audit 2026-06-29). Wir extrahieren sie zusätzlich in ein strukturiertes unit-Feld.
_UNIT_RE = re.compile(r"\(in\s+([^)]+)\)", re.IGNORECASE)


def _extract_unit(name: object) -> str | None:
    """Liest die Einheit aus dem INKAR-Indikatornamen ("(in %)" -> "%"); sonst None."""
    if not isinstance(name, str):
        return None
    match = _UNIT_RE.search(name)
    return match.group(1).strip() if match else None


def map_indicators(
    slug: str,
    rows: list[dict],
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps a city's INKAR indicator rows to a ``CanonicalRecord``.

    ``rows`` is the list of slim dictionaries returned by the SQLite reader
    (``group``/``name``/``value``/``year``/``category``). The ``retrieved_at``
    timestamp is injected (no ``datetime.now()`` in the mapper) so that the
    result remains deterministic. The join keys ``ags``/``wikidata_qid`` are
    passed through from the register (default ``None``).
    """
    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.INKAR,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Bundesinstitut für Bau-, Stadt- und Raumforschung (BBSR), INKAR",
            license_url=_DL_DE_BY_URL,
            modified=False,
        ),
        payload=IndicatorsPayload(
            indicator_count=len(rows),
            # Einheit zusätzlich strukturiert je Indikator (aus dem name-String).
            indicators=[
                {**row, "unit": _extract_unit(row.get("name"))} for row in rows
            ],
        ),
    )
