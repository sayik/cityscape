"""Structured JSON logging with correlation ID (FND-03).

``add_correlation`` extracts the correlation ID set per request
(asgi-correlation-id ContextVar) as the ``request_id`` field into every log line.
The processor must run FIRST, ``JSONRenderer`` last.
"""

from __future__ import annotations

import logging
from typing import Any

import structlog
from asgi_correlation_id import correlation_id


def add_correlation(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Binds the current correlation ID as ``request_id`` to the event."""
    if request_id := correlation_id.get():
        event_dict["request_id"] = request_id
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Configures structlog for JSON logs on stdout (collectible by Docker)."""
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            add_correlation,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        # Caching disabled: allows deterministic reconfiguration in tests
        # (capture pipeline) and costs virtually nothing with stdlib LoggerFactory.
        cache_logger_on_first_use=False,
    )
