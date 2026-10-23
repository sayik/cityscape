"""Pure census grid mapper map_population_density (DATA-OSM-Tier-2).

Calculates the inhabited area (cells * 0.01 km²) and the population density
(inhabitants per km² over the inhabited area) from the aggregated raw-dict
(sum of inhabitants + number of inhabited
100m cells). Pure, deterministic (no now()).
License: DL-DE/BY 2.0 (Tier A), Source: 2022 Census (Statistical Offices).
"""

from __future__ import annotations

from datetime import datetime

from cityscape.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    PopulationDensityPayload,
    SourceId,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"
_CELL_AREA_KM2 = 0.01  # 100m x 100m = 0.01 km2


def map_population_density(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Maps the aggregated Census Grid raw dictionary to a ``CanonicalRecord``.

    ``populated_area_km2`` = populated cells * 0.01; ``density_per_km2`` = population
    / populated area (None if there are no populated cells). Values are static
    (census reference date), therefore ``observed_at=None``; ``retrieved_at`` is injected.
"""
    cells = raw.get("populated_cells", 0) or 0
    population = raw.get("population")
    area = round(cells * _CELL_AREA_KM2, 4) if cells else None
    density = (
        round(population / area, 1)
        if population is not None and area and area > 0
        else None
    )

    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.ZENSUS_GRID,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="© Federal and State Statistical Offices, 2022 Census",
            license_url=_DL_DE_BY_URL,
        ),
        payload=PopulationDensityPayload(
            population=population,
            populated_cells=cells,
            populated_area_km2=area,
            density_per_km2=density,
        ),
    )
