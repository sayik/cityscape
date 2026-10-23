"""Custom per-source circuit breaker (RES-04, CLOSED/OPEN/HALF_OPEN).

Why custom (orchestrator decision 1, RESEARCH Pattern 3 Option B):
``pybreaker`` is not asyncio-native and ``purgatory`` would be an additional
runtime dependency. The state logic of a circuit breaker is small (~60 LOC)
and purely synchronous (counting/timing logic, no I/O), so we introduce no new
dependency. The state lives in-process per uvicorn worker (MVP: single
worker acceptable, T-03-13 accept; upgrade path Redis-backed for multi-worker).

The breaker isolates per source (``BreakerRegistry`` holds a separate
``CircuitBreaker`` per ``source_name``): a dead source only trips its own
breaker and leaves other sources unaffected (RES-04, T-03-10). When OPEN,
the breaker fails fast (no hammering on an unhealthy source, T-03-11),
until after ``cooldown`` a single HALF_OPEN probe call is allowed:
success -> CLOSED (failure_count 0), failure -> OPEN again.

Pure state logic, unit-testable without network (same separation as
registry/models.py). ``BreakerOpen`` is a lightweight signal exception mapped
to ``UpstreamError`` (503) in client.py, carrying NO HTTP status of its own.
"""

from __future__ import annotations

import enum
import time
from collections.abc import Callable


class BreakerOpen(Exception):
    """Signal: the breaker for this source is open (fail-fast, no upstream call).

    Lightweight and HTTP-agnostic; client.py maps it to
    ``UpstreamError`` (503) so the central handler builds the envelope.
    """


class BreakerState(enum.StrEnum):
    """The three breaker states (directly usable in logs/headers as a string)."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """In-process circuit breaker for a SINGLE source (CLOSED/OPEN/HALF_OPEN).

    Args:
        failure_threshold: Number of consecutive failures until OPEN.
        cooldown: Seconds that OPEN is held before a HALF_OPEN probe
            is allowed.
        now: Injectable clock (``Callable[[], float]``, default ``time.monotonic``)
            -> deterministic tests without ``sleep``.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown: float = 30.0,
        *,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self._now = now
        self.failure_count = 0
        self.state: BreakerState = BreakerState.CLOSED
        self.opened_at: float | None = None

    def is_open(self) -> bool:
        """True as long as the breaker is effectively open (before cooldown expires).

        After cooldown expires, the breaker is ready for a HALF_OPEN probe
        and is no longer considered (blockingly) open.
        """
        if self.state is not BreakerState.OPEN:
            return False
        return not self._cooldown_elapsed()

    def _cooldown_elapsed(self) -> bool:
        """True if at least ``cooldown`` has elapsed since opening."""
        if self.opened_at is None:
            return True
        return (self._now() - self.opened_at) >= self.cooldown

    def allow_request(self) -> bool:
        """May a call proceed? CLOSED yes; OPEN only after cooldown (HALF_OPEN probe).

        When cooldown expires, the breaker transitions to HALF_OPEN and allows
        EXACTLY this probe call through. Before expiry, remains OPEN -> fail-fast.
        """
        if self.state is BreakerState.CLOSED:
            return True
        if self.state is BreakerState.HALF_OPEN:
            return True
        # OPEN: allow a single probe call only after cooldown.
        if self._cooldown_elapsed():
            self.state = BreakerState.HALF_OPEN
            return True
        return False

    def record_success(self) -> None:
        """Successful call -> close breaker, reset failure counter."""
        self.failure_count = 0
        self.state = BreakerState.CLOSED
        self.opened_at = None

    def record_failure(self) -> None:
        """Failed call -> increment counter; on threshold (or HALF_OPEN) OPEN."""
        # An error during the HALF_OPEN probe re-opens immediately.
        if self.state is BreakerState.HALF_OPEN:
            self._open()
            return
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self._open()

    def _open(self) -> None:
        """Sets the breaker to OPEN and records the opening time."""
        self.state = BreakerState.OPEN
        self.opened_at = self._now()


class BreakerRegistry:
    """Process-wide registry {source_name -> CircuitBreaker} (per-source isolation).

    Each source receives its own ``CircuitBreaker`` with identical
    configuration. An open breaker for one source leaves other sources
    unaffected (RES-04, T-03-10). State lives across requests as long as
    the registry is held on ``app.state``.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown: float = 30.0,
        *,
        now: Callable[[], float] = time.monotonic,
        cooldowns: dict[str, float] | None = None,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self._now = now
        # Per-source cooldown override (2026-06-14): fragile/slowly recovering
        # sources (e.g. intermittently degraded government APIs) receive a long
        # cooldown so that the OPEN breaker rarely probes the sick upstream (little
        # error noise), yet still closes ITSELF once the upstream is back.
        # This allows such sources to heal automatically without needing to
        # disable them manually via enable_* toggles. If an entry is missing,
        # the global default cooldown applies.
        self._cooldowns = cooldowns or {}
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(self, source: str) -> CircuitBreaker:
        """Returns the breaker for the source (creates it on first access).

        The cooldown is overridable per source (``cooldowns`` map); without
        an entry, the global default applies.
        """
        breaker = self._breakers.get(source)
        if breaker is None:
            breaker = CircuitBreaker(
                failure_threshold=self.failure_threshold,
                cooldown=self._cooldowns.get(source, self.cooldown),
                now=self._now,
            )
            self._breakers[source] = breaker
        return breaker
