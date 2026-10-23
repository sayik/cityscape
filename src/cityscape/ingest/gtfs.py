"""GTFS entry streamer (utf-8, constant memory, DATA-05).

``stream_entry(zip_path, entry_name)`` opens EXCLUSIVELY the named
entry of the GTFS ZIP by name (no ``extractall``, no ``raw.read()``) and yields
lines line-by-line as a ``dict`` (iterator). ``stream_stops`` is the
specialized convenience for ``stops.txt`` and internally calls
``stream_entry(zip_path, "stops.txt")``. This keeps memory footprint
constant, even when the real uncompressed DELFI ZIP contains 431 MB stops.txt and 2.8 GB
stop_times.txt.

Memory/security contract (T-06-03/T-06-05/T-19-MEM/T-19-ZIP):
- NEVER ``ZipFile.extractall`` (Zip slip protection) and NEVER ``raw.read()`` (OOM protection).
- ``stream_entry`` must also only open by name and stream line-by-line.
  ``stop_times.txt`` (multiple GB) is streamed and filtered exclusively,
  NEVER loaded completely (see ``transit/resolver.py``).
- Decoding with ``encoding="utf-8", errors="replace"``: the GTFS specification
  mandates UTF-8 and the DELFI feed provides it as such (audit rerun
  2026-06-29 verified live: ``stops.txt`` carries bytes ``c3 b6`` for "ö",
  Content-Type ``charset=utf-8``). Earlier cp1252 assumption caused
  double-mojibake ("Köln Hbf" -> "KÃ¶ln Hbf") on every stop with umlauts/ß.
  ``errors="replace"`` remains as protection against isolated invalid bytes.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterator
from pathlib import Path


def stream_entry(zip_path: str | Path, entry_name: str) -> Iterator[dict[str, str]]:
    """Streams lines of any GTFS entry from the ZIP (utf-8).

    Opens exclusively the entry ``entry_name`` by name (``z.open``) and
    yields each CSV line as a ``dict`` (column name -> value). Yield-based:
    the entire file is never read into memory.

    Security/memory contract (T-06-03/T-19-MEM/T-19-ZIP): NEVER ``extractall``
    (Zip slip), NEVER ``raw.read()`` (OOM). Applies also to ``stop_times.txt`` (multiple
    GB): stream line-by-line only and filter in caller, NEVER load
    completely.
    """
    with zipfile.ZipFile(zip_path) as z:
        with z.open(entry_name) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
            yield from csv.DictReader(text)


def stream_stops(zip_path: str | Path) -> Iterator[dict[str, str]]:
    """Streams lines of ``stops.txt`` from the GTFS ZIP (utf-8).

    Specialization of :func:`stream_entry` for ``stops.txt`` (no
    behavioral break from previous implementation).
    """
    yield from stream_entry(zip_path, "stops.txt")
