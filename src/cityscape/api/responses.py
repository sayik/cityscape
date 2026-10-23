"""Custom orjson response class as replacement for FastAPI's ORJSONResponse.

FastAPI deprecated ``fastapi.responses.ORJSONResponse`` (serialization
there now runs via Pydantic as soon as a response_model is set). However,
the error handlers and the ``default_response_class`` still require a
concrete response class with an orjson bytes body (the ETag middleware contract
in main.py depends on deterministic response bytes). This class is the
documented Starlette pattern: a ``JSONResponse`` subclass with ``render`` via
``orjson.dumps`` - identical behavior to the old ORJSONResponse, without deprecation.
"""

from __future__ import annotations

from typing import Any

import orjson
from starlette.responses import JSONResponse


class OrjsonResponse(JSONResponse):
    """JSON response that serializes the body with orjson (bytes)."""

    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content)
