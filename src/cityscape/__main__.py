"""Entry point for ``python -m cityscape`` (local uvicorn startup)."""

from __future__ import annotations

import uvicorn


def main() -> None:
    """Starts the app with uvicorn (local/dev)."""
    uvicorn.run("cityscape.main:app", host="0.0.0.0", port=8000)  # noqa: S104


if __name__ == "__main__":
    main()
