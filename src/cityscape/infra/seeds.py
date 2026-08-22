"""Shared, env-overrideable resolution of the seed directory (CR-01).
A single source of truth for the path to committed seeds (REST rule 6,
no duplicates). Previously, ``collector/plan.py``, ``mappers/holidays.py``,
``registry/cities.py``, and ``export/enrich.py`` each resolved the path individually using
``Path(__file__).resolve().parents[...] / “data” / “seeds”`` and ignored
``CITYSCAPE_SEEDS_DIR`` in the process (Live Report 2026-06-12, M1): In the production container,
the named volume ``cityscape_data`` shadows the path ``/app/data``, which is why
the Dockerfile places the seeds in ``/app/seeds`` and sets ``CITYSCAPE_SEEDS_DIR``
to that location. If the environment override was ignored, seeds were missing (holidays no_data,
56 missing cities from registry_extended.json).
CRITICAL: Resolve lazily at runtime (read ``os.environ`` on every call),
NEVER hardcode into a constant at module import time. Otherwise, tests can no
longer set the environment override (Settings singleton caching).

Translated with DeepL.com (free version)
"""

from __future__ import annotations

import os
from pathlib import Path

# Repo layout fallback: this file is located in src/cityscape/infra/seeds.py,
# so the repo root is parents[3]; data/seeds/ is directly below it.
_REPO_SEED_DIR = Path(__file__).resolve().parents[3] / "data" / "seeds"


def seeds_dir() -> Path:
    """Resolves the seed directory lazily (environment override takes precedence; otherwise, the repo layout is used).

    ``CITYSCAPE_SEEDS_DIR`` (production container: ``/app/seeds``) takes precedence; if
    no override is set, the repo layout applies (local, tests). Is read fresh from ``os.environ``
    on every call so that overrides set per test take effect.
    """
    override = os.environ.get("CITYSCAPE_SEEDS_DIR")
    if override:
        return Path(override)
    return _REPO_SEED_DIR
