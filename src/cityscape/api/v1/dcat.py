"""DCAT-AP catalog endpoint ``/api/v1/catalog.jsonld`` (EU harvesting).

Provides a machine-readable DCAT-AP catalog (JSON-LD) of the datasets
served by cityscape. Goal: indexable by ``data.europa.eu`` / GovData / other
CKAN harvesters without requiring cityscape itself to be a public body
(the catalog describes the *distributions* = API endpoints +
openly licensed bulk snapshots on Zenodo/Hugging Face).

Deliberately NO new RDF dependency: JSON-LD is part of DCAT-AP and is serialized
here as a pure dict. The curated dataset definitions reside in
``dcat_datasets.json`` (next to this module, read once on import like
``openapi.py`` reads the spec). License URL is derived from ``_LICENSE_URI``
maintained here and attribution is derived from ``sources.SOURCE_LICENSE``
(Single Source of Truth, no duplication of license texts).

The route is ``include_in_schema=False`` (like ``openapi.py``): the catalog is its
own JSON-LD document, not part of the data envelope, and should not end up in
``/openapi.json`` or the drift detector.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import Response

from cityscape.api.v1.sources import SOURCE_LICENSE

router = APIRouter()

BASE = "https://cityscape.dev/api/v1"
HOMEPAGE = "https://cityscape.dev"
PUBLISHER_NAME = "cityscape"

# EU data theme vocabulary (authority table publications.europa.eu).
_THEME = "http://publications.europa.eu/resource/authority/data-theme/{}"
GERMANY = "http://publications.europa.eu/resource/authority/country/DEU"
_FILE_TYPE = "http://publications.europa.eu/resource/authority/file-type/{}"

# Curated dataset definitions (topic granularity) separated so that long
# multilingual texts are not constrained by Python line length limits.
_DATA_PATH = Path(__file__).parent / "dcat_datasets.json"
_DATA = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
_DATASETS: list[dict] = _DATA["datasets"]
_SNAPSHOT_DISTRIBUTIONS: list[dict] = _DATA["snapshot_distributions"]

# license_id (string as in SOURCE_LICENSE) -> (label, URI). Mirrors
# manifest._SPDX_MAP + supplements non-Tier-A cases (odbl/public domain), which
# are reported honestly in the catalog. unknown/mixed -> no license URI.
_LICENSE_URI: dict[str, tuple[str, str]] = {
    "cc0": ("CC0-1.0", "https://creativecommons.org/publicdomain/zero/1.0/"),
    "cc_by_4_0": ("CC-BY-4.0", "https://creativecommons.org/licenses/by/4.0/"),
    "dl_de_by_2_0": ("DL-DE-BY-2.0", "https://www.govdata.de/dl-de/by-2-0"),
    "dl_de_zero_2_0": ("DL-DE-ZERO-2.0", "https://www.govdata.de/dl-de/zero-2-0"),
    "geonutzv": (
        "GeoNutzV",
        "https://www.dwd.de/DE/service/rechtliche_hinweise/rechtliche_hinweise.html",
    ),
    "gemeinfrei": (
        "Public Domain",
        "https://creativecommons.org/publicdomain/zero/1.0/",
    ),
    "odbl": ("ODbL-1.0", "https://opendatacommons.org/licenses/odbl/1-0/"),
}


def _publisher() -> dict:
    return {
        "@type": "foaf:Agent",
        "foaf:name": PUBLISHER_NAME,
        "foaf:homepage": {"@id": HOMEPAGE},
    }


def _lang(de: str, en: str) -> list[dict]:
    """DCAT-AP multilingualism as JSON-LD language-tagged literals."""
    return [{"@value": de, "@language": "de"}, {"@value": en, "@language": "en"}]


def _license_node(license_id: str) -> dict | None:
    entry = _LICENSE_URI.get(license_id)
    if not entry:
        return None
    label, uri = entry
    return {"@id": uri, "@type": "dct:LicenseDocument", "rdfs:label": label}


def _dataset_node(d: dict) -> dict:
    src = SOURCE_LICENSE.get(d["source"], {})
    license_id = src.get("license_id", "")
    attribution = src.get("attribution", "")
    access = f"{BASE}/cities/{{slug}}/{d['endpoint']}"
    license_node = _license_node(license_id)
    distribution = {
        "@type": "dcat:Distribution",
        "dct:title": _lang(
            f"cityscape API: /cities/{{slug}}/{d['endpoint']}",
            f"cityscape API: /cities/{{slug}}/{d['endpoint']}",
        ),
        "dcat:accessURL": {"@id": access},
        "dct:format": {"@id": _FILE_TYPE.format("JSON")},
        "dcat:mediaType": "application/json",
        "dct:conformsTo": {"@id": f"{BASE}/openapi.yaml"},
    }
    if license_node:
        distribution["dct:license"] = license_node
    node = {
        "@type": "dcat:Dataset",
        "@id": f"{HOMEPAGE}/catalog/{d['id']}",
        "dct:identifier": d["id"],
        "dct:title": _lang(d["title_de"], d["title_en"]),
        "dct:description": _lang(d["desc_de"], d["desc_en"]),
        "dcat:theme": [{"@id": _THEME.format(d["theme"])}],
        "dcat:keyword": d["keywords"],
        "dct:spatial": {"@id": GERMANY},
        "dct:publisher": _publisher(),
        "dct:accrualPeriodicity": {
            "@id": "http://publications.europa.eu/resource/authority/frequency/CONT"
        },
        "dcat:distribution": [distribution],
    }
    if license_node:
        node["dct:license"] = license_node
    if attribution:
        node["dct:rights"] = attribution
    return node


def _snapshot_dataset() -> dict:
    dists = []
    for s in _SNAPSHOT_DISTRIBUTIONS:
        label, uri = s["license"]
        dists.append(
            {
                "@type": "dcat:Distribution",
                "dct:title": _lang(s["title"], s["title"]),
                "dcat:accessURL": {"@id": s["accessURL"]},
                "dcat:downloadURL": {"@id": s["accessURL"]},
                "dct:format": {"@id": _FILE_TYPE.format("CSV")},
                "dcat:mediaType": s["mediaType"],
                "dct:license": {
                    "@id": uri,
                    "@type": "dct:LicenseDocument",
                    "rdfs:label": label,
                },
            }
        )
    return {
        "@type": "dcat:Dataset",
        "@id": f"{HOMEPAGE}/catalog/german-cities-snapshot",
        "dct:identifier": "german-cities-snapshot",
        "dct:title": _lang(
            "cityscape Querschnitt deutscher Staedte (Open-Data-Snapshot)",
            "cityscape German Cities Open-Data Snapshot",
        ),
        "dct:description": _lang(
            "Reproduzierbarer, offen lizenzierter Querschnitt offener Daten fuer "
            "deutsche Staedte (Stammdaten, Wetter, Luftqualitaet u.a.), CSV/Parquet.",
            "Reproducible, openly licensed cross-section of open data for German "
            "cities (base data, weather, air quality and more), as CSV/Parquet.",
        ),
        "dcat:theme": [{"@id": _THEME.format("REGI")}],
        "dcat:keyword": ["open data", "Germany", "cities", "Staedte", "snapshot"],
        "dct:spatial": {"@id": GERMANY},
        "dct:publisher": _publisher(),
        "dcat:distribution": dists,
    }


def build_catalog() -> dict:
    """Builds the DCAT-AP catalog as JSON-LD document (pure function, testable)."""
    datasets = [_dataset_node(d) for d in _DATASETS]
    datasets.append(_snapshot_dataset())
    return {
        "@context": {
            "dcat": "http://www.w3.org/ns/dcat#",
            "dct": "http://purl.org/dc/terms/",
            "foaf": "http://xmlns.com/foaf/0.1/",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        },
        "@type": "dcat:Catalog",
        "@id": f"{HOMEPAGE}/catalog",
        "dct:title": _lang(
            "cityscape Open-Data-Katalog deutscher Staedte",
            "cityscape Open Data Catalogue for German cities",
        ),
        "dct:description": _lang(
            "DCAT-AP-Katalog der ueber die cityscape-API bereitgestellten offenen "
            "Datensaetze deutscher Staedte. cityscape buendelt amtliche offene "
            "Quellen (DWD, UBA, BNetzA, BORIS, Destatis u.a.) hinter einer "
            "einheitlichen, keylosen REST-API; je Datensatz sind Quelle, Lizenz "
            "und Pflicht-Attribution ausgewiesen.",
            "DCAT-AP catalogue of the open datasets for German cities provided via "
            "the cityscape API. cityscape bundles official open sources (DWD, UBA, "
            "BNetzA, BORIS, Destatis and others) behind one keyless REST API; each "
            "dataset states its source, license and required attribution.",
        ),
        "dct:publisher": _publisher(),
        "foaf:homepage": {"@id": HOMEPAGE},
        "dct:language": [
            {"@id": "http://publications.europa.eu/resource/authority/language/DEU"},
            {"@id": "http://publications.europa.eu/resource/authority/language/ENG"},
        ],
        "dcat:dataset": datasets,
    }


@router.get("/catalog.jsonld", include_in_schema=False)
async def catalog_jsonld() -> Response:
    """Delivers the DCAT-AP catalog as JSON-LD (EU harvesting, no envelope)."""
    body = json.dumps(build_catalog(), ensure_ascii=False, indent=2)
    return Response(body, media_type="application/ld+json")
