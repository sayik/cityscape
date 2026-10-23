"""Versioned API router /api/v1 (FND-05, REST rule 1)."""

from __future__ import annotations

from fastapi import APIRouter

from . import cities, compare, dcat, health, live, openapi, sources, stations, track

api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(health.router, tags=["meta"])
# Cache-free first-contact beacon (/api/v1/track): triggers note_first_seen, even
# when data endpoints are edge-cached (HIT does not reach origin).
api_v1.include_router(track.router, tags=["meta"])
api_v1.include_router(cities.router, tags=["cities"])
api_v1.include_router(sources.router, tags=["meta"])
api_v1.include_router(openapi.router, tags=["meta"])
# EU leverage: DCAT-AP catalog (JSON-LD) for data.europa.eu/GovData harvesting.
api_v1.include_router(dcat.router, tags=["meta"])
api_v1.include_router(compare.router, tags=["compare"])
# Phase 20: separate live category (LIVE-01/02/03). Own namespace /live +
# own OpenAPI tag "Live" (own docs section). Prefix + tag are set here
# (analogous to cities.py), so final path is under /api/v1/live/...
api_v1.include_router(live.router, prefix="/live", tags=["Live"])
# DATA-36: Per-station live boards (any EVA, all train types). Own namespace
# /stations + own OpenAPI tag "stations". Final path /api/v1/stations/...
api_v1.include_router(stations.router, prefix="/stations", tags=["stations"])
