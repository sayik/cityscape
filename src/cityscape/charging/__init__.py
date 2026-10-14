"""Live EV charging station occupancy by city (eRound AFIR, DATA-42).

Three modules modeled after ``transit/`` (Poller writes to Redis, the
request path reads ONLY from Redis, T-19-REQPARSE similarly):

- ``geomap``: pure geo-map logic (full stat inventory -> refill_point_id ->
  city slug + coordinates) plus the cached file loader for the request path.
- ``store``: Redis store for the accumulated occupancy deltas (TTL = staleness).
- ``poller``: long-running asyncio task that pulls the dynamic eRound subscription at each interval
  and accumulates the deltas (the feed is a drain queue: each pull
  delivers only the changes since the last pull, NEVER the full state).

"""