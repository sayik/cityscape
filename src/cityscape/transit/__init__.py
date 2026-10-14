"""Transit resolution and position estimation against static DELFI GTFS.

Pure, testable building blocks of Phase 19 (no network, no system clock, no Redis):
- ``resolver``: on-demand resolution index trip_id/route_id/stop against
  static GTFS (streamed with constant memory).
- ``interpolation``: linear position estimation with injected time.

Caching (Redis) and polling are handled in the caller (Plan 19-04), not in
these pure functions.
"""
