"""IP allowlist for rate limit bypass (security/operational hardening 2026-07-02).

Background: Remote MCP traffic from the Anthropic Connectors Directory arrives
server-side via FEW Anthropic egress IPs. A per-IP / subnet limit would
throttle this legitimate aggregate, even though many different end users are
behind it. This module provides the shared CIDR check for ALL limiters
(MCP middleware, AbuseGuard subnet limit, slowapi IP limit).

Properties:

- ONLY limit bypass, NO authentication/authorization: an allowlisted IP
  receives no additional privileges whatsoever; it simply is not throttled.
- ENV-configurable without code deployment: ``CITYSCAPE_RATELIMIT_ALLOWLIST`` as
  a comma-separated CIDR list (mixed v4/v6; bare IPs count as /32 or
  /128). Empty (default) = feature off = prior behavior.
- FAIL-SAFE: empty or unparseable configuration allowlists NOBODY.
  Invalid entries are discarded (warning logged), valid remainder continues
  to apply; an unparseable client IP is never allowlisted.
- Intentionally stdlib-only (``ipaddress``): the MCP service imports this module
  without pulling the FastAPI/Settings path (same principle as the
  independent ``client_ip`` copy in ``mcp/ratelimit.py``).

The client IP originates from CF-Connecting-IP/XFF[0] for all callers and is
trustworthy only under the CF-only firewall (see ratelimit.real_client_ip);
the allowlist inherits this trust prerequisite.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Sequence
from functools import lru_cache

logger = logging.getLogger(__name__)

# Shared env name: identical to the pydantic Settings field
# ``ratelimit_allowlist`` (prefix CITYSCAPE_) so that ONE variable configures
# API and MCP containers alike.
ENV_VAR = "CITYSCAPE_RATELIMIT_ALLOWLIST"

_Network = ipaddress.IPv4Network | ipaddress.IPv6Network


@lru_cache(maxsize=16)
def parse_allowlist(raw: str | None) -> tuple[_Network, ...]:
    """Parses the comma-separated CIDR list into networks (fail-safe).

    Invalid entries are discarded and logged ONCE per configuration value
    (lru_cache deduplicates repetitions); valid entries of the same list
    remain effective. ``None``/empty/whitespace-only yields ``()`` = nobody
    allowlisted. ``strict=False`` allows host bits (e.g. "10.1.2.3/24").
    """
    if not raw or not raw.strip():
        return ()
    networks: list[_Network] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            logger.warning(
                "Rate-Limit-Allowlist: ungueltiger CIDR-Eintrag %r verworfen.", part
            )
    return tuple(networks)


def ip_allowlisted(ip: str, networks: Sequence[_Network]) -> bool:
    """True if ``ip`` lies within one of the allowlist networks (otherwise/on garbage False).

    IPv4-mapped IPv6 addresses (``::ffff:203.0.113.5``) also match pure
    v4 CIDRs, so that a v6 listener uses the same allowlist.
    """
    if not networks:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    mapped = getattr(addr, "ipv4_mapped", None)
    return any(
        addr in net or (mapped is not None and mapped in net) for net in networks
    )
