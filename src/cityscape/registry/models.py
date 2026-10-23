"""City registry model with cross-walk IDs (CORE-03).

Defines ``CityRegistryEntry`` as a frozen value object (Pitfall 2:
``frozen=True`` against tampering, T-02-06). Mandatory cross-walk IDs are
Wikidata QID and OSM relation; DWD station and GTFS stop are optional
fields (slots present, empty/None), populated in Phase 5/6. ``slug`` is
ASCII (muenchen), ``name_de`` contains correct umlauts (München).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from cityscape.normalization import GeoPoint


class CityRegistryEntry(BaseModel):
    """A validated city entry with stable cross-walk identifiers.

    QID and OSM relation are SPARQL-verified and mandatory.
    DWD/GTFS fields exist as slots (CORE-03 requires columns),
    but remain empty/None in Phase 2.

    ``ags`` is the official 8-digit municipality key (Gemeindeschlüssel) and serves as
    dim_city join anchor against census/elections/MaStR (ARCH-02). ``state`` is the
    existing state abbreviation and likewise serves as join anchor
    (no new field needed).
    """

    model_config = ConfigDict(frozen=True)

    slug: str
    name_de: str
    state: str
    ags: str = Field(pattern=r"^\d{8}$")
    is_state_capital: bool
    qid: str = Field(pattern=r"^Q\d+$")
    osm_relation: int = Field(gt=0)
    geo: GeoPoint
    population: int | None = None
    dwd_station_ids: tuple[str, ...] = ()
    gtfs_stop_ref: str | None = None
    # Coverage level (expansion 2026-06): "full" = manually verified core city with
    # all sources incl. hand-curated maps (LHP gauge, DWD pollen region,
    # DIVI county, city road event connector); "auto" = >100k population city
    # served ONLY by AGS/geo-automatic Tier A sources; hand-curated
    # sources return honest no_data. Default "full" (core registry).
    coverage: str = Field(default="full", pattern=r"^(full|auto)$")
