"""Structured output types for the cityscape MCP tools (DX-05).

Each tool continues to pass through the raw API envelope as a ``dict`` 1:1 at
runtime (Blocker 4 call contract, no mapping logic here). The tool functions
are annotated with ``-> ToolEnvelope`` so that FastMCP generates an
``outputSchema`` from them: directory scanners (Smithery/Glama) rate tools
with an output schema significantly higher, and MCP clients additionally receive
structured content (``structuredContent``) instead of plain text only.

IMPORTANT (robustness over strictness): ``data`` is ``Any`` (the payload varies
per resource across ~47 payload types) and ``meta`` allows extra fields
(``extra="allow"``) so that FastMCP's return-value validation (``model_validate`` in
func_metadata.convert_result) NEVER fails on a real response. ``source_status``
is deliberately ``str`` rather than ``Literal``: the API currently knows ok/disabled/
no_data/not_covered/error/not_found/not_ingested, and a new value must not break a
live tool call with a validation error (graceful degradation, never 5xx).
"""

from __future__ import annotations

from typing import Any, TypedDict


class ToolMeta(TypedDict, total=False):
    """Envelope metadata: source, status, cache, license, and attribution.

    Extra fields (e.g. ``covered_cities``, ``radius_m`` on partial coverage)
    are preserved thanks to ``extra="allow"``.
    """

    __pydantic_config__ = {"extra": "allow"}  # type: ignore[misc]

    source: str
    source_status: str
    cache_status: str
    correlation_id: str
    license: str
    attribution: str


class ToolEnvelope(TypedDict):
    """Canonical cityscape response envelope: normalized ``data`` + ``meta``.

    ``data`` is ``null`` if the source returned no data (see
    ``meta.source_status``); otherwise an object or a list per resource.
    """

    data: Any
    meta: ToolMeta
