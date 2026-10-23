"""OpenAPI YAML serving route /openapi.yaml (API-09, design-first).

FastAPI serves the generated schema internally only as JSON under /openapi.json.
The stable, design-first maintained spec resides as ``docs/openapi.yaml`` in the repo
(REST rule 11) and is served here unchanged as ``application/yaml``.

Security (T-04-10): ``_SPEC`` is a hardcoded constant without
user input components (no path parameter -> no path traversal). ``include_in_schema
=False`` keeps the route out of the generated schema (no recursion in
/openapi.json or the drift detector).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter()

# Hardcoded path to design-first spec (no user input, T-04-10). The spec
# is static; it is read once upon import (no blocking
# file I/O per request, ruff ASYNC240) and delivered unchanged.
_SPEC_PATH = Path("docs/openapi.yaml")
_SPEC_TEXT = _SPEC_PATH.read_text(encoding="utf-8")


@router.get("/openapi.yaml", include_in_schema=False)
async def openapi_yaml() -> Response:
    """Delivers the design-first OpenAPI spec as YAML (API-09)."""
    return Response(_SPEC_TEXT, media_type="application/yaml")
