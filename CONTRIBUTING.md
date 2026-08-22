# Contribution Guide

Thank you for wanting to contribute to the cityscape API. This guide describes the setup, the mandatory quality gates, and the rules for handling secrets.

## Setup

The project uses [uv](https://docs.astral.sh/uv/) for dependency and environment management (Python 3.13).

```bash
# Install dependencies and set up a virtual environment
uv sync
```

## Mandatory Gate Commands

Before you open a pull request, all three gates must pass locally. These are the exact same commands that run in CI:

Translated with DeepL.com (free version)

```bash
# Linting (ruff: E, F, I, UP, B, ASYNC, S)
uv run ruff check .

# Format-check (ruff format im Check-Modus)
uv run ruff format --check .

# Tests (pytest, async-Modus aktiv)
uv run pytest -q
```

A PR is only merged if ruff (check + format) and pytest run successfully. This is the mandatory final gate for the project: linting and tests must pass before anything is considered “done.”

## Secret Rule: Never commit secrets

- Real API keys, tokens, or credentials **never** belong in the repository.
- Configuration is handled exclusively via environment variables prefixed with `CITYSCAPE_`.
- Only `.env.example` (with empty placeholders) is versioned. Your local `.env` file with real values is excluded via `.gitignore` and should remain that way.
- In CI, a **gitleaks** scan runs across the entire Git history with every push and pull request. If it finds a secret, the pipeline fails (`--exit-code 1`). Any secrets found are redacted in the CI log (`--redact`).

If you accidentally commit a secret: Rotate the affected key immediately (gitleaks also detects it in the history) and remove it from the history before you push.

## Code Style

- German-language docstrings and comments, correct umlauts (ä/ö/ü/ß), no ASCII substitutions.
- Follow the patterns established in the project (App Factory, centralized error mapping, structured JSON logging, versioned routing under `/api/v1`).


## Add a Data Source

A new upstream source is defined declaratively in **one** place:
`src/cityscape/registry/source_specs.py`. A `SourceSpec` entry there automatically populates
the derived structures (source list for the `/sources` route,
license + attribution, cache TTL, breaker cooldown), so you no longer have to maintain four scattered
locations.

Steps for a new source `my_source`:

1. **Registry entry** in `registry/source_specs.py`:
   `SourceSpec(name=“my_source”, license_id="...", attribution="...", ttl=(fresh_s, stale_s), cooldown=...)`.
   Omit `ttl`/`cooldown` if the defaults are appropriate (60 s fresh / 120 s stale, 30 s breaker probe).
2. **Toggle** in `config.py` (`SourceToggleSettings`): `enable_my_source: bool = ...`.
   The name MUST be exactly `enable_<name>` (dynamic resolution via `getattr`).
3. **SourceId** in `normalization/enums.py`: an enum value with the same name
   (documented exceptions/aliases are listed in `tests/unit/test_source_specs_registry.py`).
4. **License line** in `DATA-LICENSES.md`: verbatim attribution (fail-closed
   against `tests/unit/test_source_license_map.py`).
5. **Adapter** (`adapters/<name>.py`, `fetch_*`) + **Mapper**
   (`normalization/mappers/<name>.py`, `map_*` → canonical envelope).
6. **Route** (`api/v1/cities.py` or `live.py`) + corresponding entry in `docs/openapi.yaml`.


`tests/unit/test_source_specs_registry.py` enforces consistency (missing
toggle, missing SourceId, invalid license/TTL/cooldown) and fails if
a step was omitted.
