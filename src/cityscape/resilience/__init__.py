"""Resilience building blocks: pooled HTTP pool, cache-aside/SWR, circuit breaker.

This package bundles the Phase 3 resilience layer. ``types.py`` provides
pure contracts (``SourceConfig``, ``CacheStatus``) without I/O, consumed by
the cache and facade plans (03-03/03-04).
"""

from __future__ import annotations
