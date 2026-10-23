"""City mapping for contract awarding in the Normalization Library (TENDER-03).

Plan-21-02 artifact: a pure, deterministic city-mapping function in
the normalization library. The actual matching logic serves as the ONE
source of truth in :mod:`cityscape.tenders.matching` (REST rule 6, no
duplicates); this module provides the
signature ``match_tender_cities(buyer_address, place_addresses)`` and
loads the Geo Crosswalk seed (``tender_geo_crosswalk.json``) lazily and
cached via ``seeds_dir()`` (analogous to a pure mapper seed load).

Purity: no I/O except for the one-time, cached seed load; no
``httpx``/``now()``/logging. The NUTS-3/zip code crosswalk maps and the
register name fallback are the sole resolution basis (fail-closed:
ambiguous/unknown address -> no match, T-21-MISMATCH).
"""

from __future__ import annotations

import json
from functools import lru_cache

from cityscape.infra.seeds import seeds_dir
from cityscape.tenders.matching import match_tender_cities as _match

__all__ = ["load_tender_crosswalk", "match_tender_cities"]

# Seed-Dateiname der NUTS-3-/PLZ-Crosswalk-Maps (Plan 21-01).
_CROSSWALK_SEED = "tender_geo_crosswalk.json"


@lru_cache(maxsize=1)
def load_tender_crosswalk() -> dict:
    """Loads the NUTS-3/PLZ crosswalk maps lazily and cached via ``seeds_dir()``.

    One-time seed load (module cache, similar to ``ingest.delfi._ags8_to_slug``):
    ``data/seeds/tender_geo_crosswalk.json`` = ``{“nuts3”: {...}, “plz_prefix”:
    {...}, “_meta”: {...}}``. Read-only load, no additional side effects.
"""
    path = seeds_dir() / _CROSSWALK_SEED
    return json.loads(path.read_text(encoding="utf-8"))


def match_tender_cities(
    buyer_address: dict | None,
    place_addresses: list[dict],
) -> dict[str, list[str]]:
    """Maps buyer addresses and places of performance to ``slug -> sorted matches``.

    Pure function in the normalization library. Resolves the buyer address
    (-> ``buyer_city``) and each place of performance address
    (-> ``place_of_performance``) separately against the crosswalk maps + the
    register name fallback; both matches are possible. For each slug, the
    matches are deduplicated and sorted. Fail-closed: addresses that cannot be resolved
    contribute nothing (no false positives).

    Delegates to the single source of truth
    (:func:`cityscape.tenders.matching.match_tender_cities`) using the
    lazy-loaded crosswalk seed.
"""
    return _match(buyer_address, place_addresses, load_tender_crosswalk())
