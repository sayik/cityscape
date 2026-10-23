"""Pure data and enum contracts of the resilience layer (NO I/O).

``SourceConfig`` is a frozen value object (Pitfall 2: ``frozen=True``) with
per-source parameters (fresh/stale TTL, timeout), held per source starting Phase 4.
``CacheStatus`` names the four possible cache results
(HIT/MISS/STALE/STALE-ON-ERROR) as ``StrEnum``, so that the status is directly
usable as a header/log string. Both types are contracts for Plan 03/04.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict, Field


class SourceConfig(BaseModel):
    """Frozen per-source configuration (name, fresh/stale TTL, timeout).

    All time fields must be positive (``gt=0``); ``ttl_fresh``/``ttl_stale``
    in seconds, ``timeout`` in seconds per request. Frozen against accidental
    mutation at runtime.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    ttl_fresh: int = Field(gt=0)
    ttl_stale: int = Field(gt=0)
    timeout: float = Field(gt=0)


class CacheStatus(enum.StrEnum):
    """Result of a cache access (directly suitable for logs/headers as a string)."""

    HIT = "HIT"
    MISS = "MISS"
    STALE = "STALE"
    STALE_ON_ERROR = "STALE-ON-ERROR"
