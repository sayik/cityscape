"""Entrypoint für ``python -m cityscape`` (lokaler uvicorn-Start)."""

from __future__ import annotations

import uvicorn


def main() -> None:
    """Startet die App mit uvicorn (lokal/Dev)."""
    uvicorn.run("cityscape.main:app", host="0.0.0.0", port=8000)  # noqa: S104


if __name__ == "__main__":
    main()
