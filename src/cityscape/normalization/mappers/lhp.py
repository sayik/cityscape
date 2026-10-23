"""Pure LHP flood mapper `map_flood` (DATA-12, GOV-01/03, Pitfall 6).

Deterministically translates the flat LHP-raw-dict into a ``CanonicalRecord``
with ``FloodWarningPayload`` (kind=flood_warning). The function is pure: no
HTTP, no logging, no ``datetime.now()``. The ``retrieved_at`` timestamp
is injected as a keyword-only value so that tests remain deterministic.

CRITICAL (Tier Separation GOV-02): LHP is Tier A,
``source=HOCHWASSER`` (toggle/source name is “lhp,” but the license/record tag is
HOCHWASSER), ``license_id=CC_BY_4_0``, ``license_tier=A``.

CRITICAL (GOV-03, Pitfall 6): The CC BY 4.0 license for the state flood portals
requires the source AND a status timestamp. The attribution therefore
MUST include the text ``“Data source: www.hochwasserzentralen.de, Status: <stand>”``;
the Mapper/Route test asserts the ``“Status:”`` string.
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    FloodWarningPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

_CC_BY_URL = "https://creativecommons.org/licenses/by/4.0/"


def map_flood(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps raw LHP flood data to a ``CanonicalRecord``.

    The ``retrieved_at`` timestamp is injected (no ``datetime.now()`` in the
    mapper) so that the result remains deterministic. The join keys
    ``ags``/``wikidata_qid`` are passed through from the register (default
    ``None``). ``geo`` remains ``None`` (city level, no gauge geo);
    ``observed_at`` remains ``None`` (event layer without measurement timestamp; the status
    is included in the payload/attribution).

    CRITICAL (Pitfall 6, GOV-03): The attribution MUST include the text
    ``“Data source: www.hochwasserzentralen.de, Status: {stand}”`` (CC-BY 4.0); the
    ``“Status:”`` part is verified by the mapper and route tests.

    Empty ``warnings`` are NOT an error (no active warning -> empty event).
    """
    stand = raw.get("stand")
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.HOCHWASSER,
        license_id=LicenseId.CC_BY_4_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=f"Datenquelle: www.hochwasserzentralen.de, Stand: {stand}",
            license_url=_CC_BY_URL,
        ),
        payload=FloodWarningPayload(
            warnings=raw.get("warnings", []),
            stand=stand,
        ),
    )
