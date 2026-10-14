"""Static GTFS refresh batch (TRANSIT-RT-08, RESEARCH Pattern 8).

Downloads the current static DELFI/gtfs.de GTFS and replaces
``data/delfi/*.zip`` idempotently (OVERWRITE like ``ingest/delfi.py``: GTFS is a
full snapshot, not an event stream). Background: the gtfs.de Basic static feed is
valid for only 7 days (RESEARCH Open Question 3); without regular refresh, the
``trip_id`` values between the RT feed and outdated static data drift apart
(RESEARCH Pitfall 4) and resolution fails.

Cadence recommendation: WEEKLY (tied to the 7-day Basic validity), not
monthly. The batch runs exclusively manually or via timer
(``python -m cityscape.transit.refresh <target.zip>``), NEVER in the request path or
lifespan. OS registration of the timer (OPS-05 pattern, systemd) takes place
outside this phase.

Security:

- T-19-DLSSRF: the download URL (``GTFS_DE_STATIC_URL``) is HARDCODED (gtfs.de
  static host), NEVER assembled from config/user-input/function argument;
  ``follow_redirects=False`` is pool default (``infra/http.py``).
- T-19-DLZIP: the refresh unzips nothing, only download + atomic rename. The ZIP
  is only streamed in the resolver (``transit/resolver.py``, stop_times never
  completely in memory).
- Size-Cap (Memory-DoS): an absurdly large body is rejected before being written
  to disk (analogous to ``adapters/gtfs_rt._MAX_FEED_BYTES``).
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from cityscape.config import Settings
from cityscape.infra.http import close_http_client, create_http_client

# gtfs.de static download HARDCODED (T-19-DLSSRF, like the RT feed host in
# adapters/gtfs_rt._GTFS_DE_FEED_URL): the host is NEVER assembled from config/user-input/
# argument.
# [OWNER-VERIFY] The real gtfs.de static download path is not verified verbatim
# in RESEARCH (only the RT feed realtime-free.pb). This URL is the
# known gtfs.de static bundle path and should be confirmed with the owner /
# gtfs.de download portal BEFORE the real timer run; if the path is wrong,
# the download fails hard (raise_for_status) instead of silently setting a wrong ZIP.
GTFS_DE_STATIC_URL = "https://download.gtfs.de/germany/free/latest.zip"

# Size-Cap (Memory-DoS): the static full ZIP is several hundred MB; 1 GiB leaves
# buffer for growth, but rejects an absurdly large/tampered body.
_MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024  # 1 GiB


def _write_atomic(body: bytes, dest_path: str) -> None:
    """Writes ``body`` atomically to ``dest_path`` (temp file + ``os.replace``).

    Pure synchronous disk I/O step (called in async path via ``asyncio.to_thread``
    so that the event loop does not block, ruff ASYNC240). Temp file
    IN the destination directory so the rename is atomic on the same filesystem
    (cross-device rename would not be atomic). OVERWRITE: idempotent.
    """
    dest = Path(dest_path).resolve()
    dest_dir = dest.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(dest_dir), suffix=".zip.tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(body)
        os.replace(tmp_path, dest)  # atomic OVERWRITE
    except BaseException:
        # on any error remove the temp remnant (no garbage in destination directory)
        tmp_path.unlink(missing_ok=True)
        raise


async def refresh_static_gtfs(http, *, url: str, dest_path: str) -> None:
    """Downloads the static GTFS ZIP and replaces ``dest_path`` atomically (idempotent).

    First writes to a temp file IN the destination directory and then renames it
    atomically to ``dest_path`` via ``os.replace`` (no partial write risk, no
    reader ever sees half a ZIP). OVERWRITE: a second run overwrites the
    existing ZIP (GTFS is a full snapshot, idempotent like ``ingest/delfi``).
    The refresh unzips nothing (T-19-DLZIP). The ``url`` MUST be the hardcoded
    ``GTFS_DE_STATIC_URL`` (T-19-DLSSRF); the parameter exists only for
    testing, the caller passes through the module constant.
    """
    resp = await http.get(url)
    resp.raise_for_status()
    body = resp.content
    if len(body) > _MAX_DOWNLOAD_BYTES:
        raise ValueError(
            f"Statik-GTFS-Body ueberschreitet _MAX_DOWNLOAD_BYTES "
            f"({_MAX_DOWNLOAD_BYTES})"
        )

    # Offload disk I/O to a thread (event loop remains unblocked, ruff ASYNC240).
    await asyncio.to_thread(_write_atomic, body, dest_path)


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint: ``python -m cityscape.transit.refresh <target.zip>``.

    Target path from ``argv[1]`` OR ``Settings().gtfs_rt_static_path``; if
    neither is set -> notice to stderr + ``sys.exit(2)`` (analogous to
    ``ingest/delfi.main``). The DELFI ZIP (``delfi_gtfs_path``, Tier A) is
    intentionally NOT a fallback: this refresh fetches the gtfs.de static data (Tier B,
    numeric feed IDs) and must not overwrite the Tier A license space.
    Otherwise downloads via dedicated short-lived, pooled httpx client (closed
    in ``finally``) and outputs success to stdout. NEVER runs in request path.
    """
    import asyncio

    argv = sys.argv if argv is None else argv
    settings = Settings()
    dest_path = argv[1] if len(argv) > 1 else settings.gtfs_rt_static_path
    if not dest_path:
        print(
            "Kein GTFS-ZIP-Zielpfad. Nutzung: python -m cityscape.transit.refresh "
            "<ziel.zip> oder CITYSCAPE_GTFS_RT_STATIC_PATH setzen.",
            file=sys.stderr,
        )
        sys.exit(2)

    async def _run() -> None:
        http = create_http_client(settings)
        try:
            await refresh_static_gtfs(http, url=GTFS_DE_STATIC_URL, dest_path=dest_path)
        finally:
            await close_http_client(http)

    asyncio.run(_run())
    print(f"Statik-GTFS aktualisiert: {dest_path}")


if __name__ == "__main__":
    main(sys.argv)
