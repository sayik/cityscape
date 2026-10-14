"""Mobilithek mTLS pull client (LIVE-04, Phase 20).

The only genuinely new infra module of this phase: a dedicated
``httpx.AsyncClient`` that sends a client certificate ONLY to ``mobilithek.info``
(T-20-MTLS). httpx/ssl cannot directly read ``.p12``, therefore
``cryptography`` (pyca) converts the p12 to PEM on startup and constructs
an ``ssl.SSLContext`` from it.

Security invariants:
- **PEM never permanently on disk** (T-20-PEM, Security V12): the decrypted
  key material is written to a short-lived tmpfs file (``/dev/shm`` if
  available) with 0600 permissions, read by ``ssl.load_cert_chain``, and
  IMMEDIATELY deleted in ``finally`` via ``os.unlink``.
- **gzip MANDATORY** (Pitfall 1): the broker responds without
  ``Accept-Encoding: gzip`` with an empty HTTP 400 (verified 2026-06-12).
- **SSRF invariant** (T-20-SSRF): host hardcoded to ``mobilithek.info:8443``,
  ``follow_redirects=False``, ``aboId`` ONLY from the settings allowlist.
- **422 = no_data** (T-20-422): an active subscription without data package returns HTTP
  422; this is treated as ``no_data`` (no ``raise``, no breaker trip,
  no retry storm). Only 5xx/network errors pass through.
- **Password as SecretStr** (T-20-SECLOG): never logged, never in cache key, never
  in the pull URL.
"""

from __future__ import annotations

import os
import ssl
import tempfile

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

from cityscape.infra.http import USER_AGENT

#: MANDATORY header value (Pitfall 1): without ``Accept-Encoding: gzip`` the
#: broker responds with an empty HTTP 400. Exported as constant (test contract).
GZIP_HEADER = "gzip"

#: Mobilithek broker host HARDCODED (T-20-SSRF): never from config/user input.
_MOBILITHEK_BASE = "https://mobilithek.info:8443/mobilithek/api/v1.0"

#: tmpfs directory for the short-lived PEM (T-20-PEM): ``/dev/shm`` keeps the
#: decrypted key material in RAM, never on persistent disk.
_TMPFS_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None  # noqa: S108


def build_pull_url(abo_id: str, *, style: str = "path") -> str:
    """Builds the Mobilithek pull URL for a subscription (hardcoded host, SSRF).

    ``abo_id`` MUST originate from the settings allowlist (``*_abo_id``), NEVER from
    user input (T-20-SSRF). The cert password NEVER appears in the URL
    (T-20-SECLOG). The host remains hardcoded in EVERY variant
    (``_MOBILITHEK_BASE``), the SSRF invariant applies unchanged.

    Three verified access point patterns (Mobilithek portal/Service Desk):
    - ``style="path"`` (default, the V2 city subscriptions): with
      ``/subscription/{aboId}/clientPullService?subscriptionID={aboId}``.
    - ``style="query"`` (the eRound AFIR subscription, LIVE-11): WITHOUT the
      ``/{aboId}/clientPullService`` path segment, only
      ``/subscription?subscriptionID={aboId}``.
    - ``style="container"`` (legacy data model, technical interface description
      ch. 7.3.2.2.1; confirmed by Mobilithek Service Desk on 2026-06-15 for the
      DELFI GTFS-RT subscription): ``/container/subscription?subscriptionID=
      {aboId}``. The more modern ``path`` access (ch. 6.2.1) returns a 4xx error
      for this legacy subscription.
    """
    if style == "container":
        return f"{_MOBILITHEK_BASE}/container/subscription?subscriptionID={abo_id}"
    if style == "query":
        return f"{_MOBILITHEK_BASE}/subscription?subscriptionID={abo_id}"
    return (
        f"{_MOBILITHEK_BASE}/subscription/{abo_id}/clientPullService"
        f"?subscriptionID={abo_id}"
    )


def build_mtls_context(p12_path: str, password: str) -> ssl.SSLContext:
    """Builds an ``ssl.SSLContext`` from a ``.p12`` file (mTLS, T-20-PEM).

    Reads the p12 bytes, decrypts key + cert (+ chain) via
    ``cryptography`` (pyca), serializes them as PEM into a short-lived
    tmpfs file (0600 permissions), loads this into the context and DELETES it immediately
    in ``finally`` (decrypted key material never permanently on disk,
    Security V12 / Pitfall 2). ``password`` is the decrypted SecretStr
    value; it is never logged.
    """
    with open(p12_path, "rb") as fh:
        p12_bytes = fh.read()

    key, cert, chain = pkcs12.load_key_and_certificates(p12_bytes, password.encode())
    if key is None or cert is None:
        raise ValueError("p12 enthaelt keinen Private-Key oder kein Zertifikat")

    pem = cert.public_bytes(serialization.Encoding.PEM)
    pem += key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    for ca in chain or []:
        pem += ca.public_bytes(serialization.Encoding.PEM)

    ctx = ssl.create_default_context()
    # Create file with restrictive permissions (0600) on tmpfs (RAM); delete=False
    # so we can pass the path to load_cert_chain, then unlink in finally.
    tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115
        mode="wb", delete=False, dir=_TMPFS_DIR, suffix=".pem"
    )
    try:
        os.chmod(tmp.name, 0o600)
        tmp.write(pem)
        tmp.flush()
        tmp.close()
        ctx.load_cert_chain(certfile=tmp.name)
    finally:
        # Delete decrypted PEM IMMEDIATELY (T-20-PEM / Security V12).
        os.unlink(tmp.name)
    return ctx


def create_mobilithek_client(settings) -> httpx.AsyncClient:
    """Builds the dedicated mTLS client ONLY for Mobilithek (T-20-MTLS).

    Analogous to ``infra/http.create_http_client``, BUT with ``verify=SSLContext``
    (client cert) and MANDATORY header ``Accept-Encoding: gzip``. A DEDICATED
    client, NOT the shared ``app.state.http`` (the cert must never be sent to third-party
    hosts). ``follow_redirects=False`` maintains the SSRF invariant.
    """
    ctx = build_mtls_context(
        settings.mobilithek_cert_path,
        settings.mobilithek_cert_password.get_secret_value(),
    )
    return httpx.AsyncClient(
        verify=ctx,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": GZIP_HEADER,  # MANDATORY (Pitfall 1)
        },
        # Conservative default; Mobilithek can be minute-fresh, but must not
        # hang indefinitely.
        timeout=httpx.Timeout(connect=2.0, read=10.0, write=5.0, pool=1.0),
        follow_redirects=False,  # SSRF invariant (T-20-SSRF)
    )


async def close_mobilithek_client(client: httpx.AsyncClient | None) -> None:
    """Closes the Mobilithek client and its pool cleanly (no-op on None)."""
    if client is not None:
        await client.aclose()


async def pull_subscription(client: httpx.AsyncClient, url: str) -> dict:
    """Pulls a Mobilithek subscription: 422 = no_data, otherwise raise_for_status (T-20-422).

    ``url`` MUST be built via ``build_pull_url`` from an allowlist ``abo_id``
    (hardcoded host, SSRF). HTTP 422 (active subscription, no data package) returns
    ``{"status": "no_data", "body": None}`` WITHOUT ``raise`` (no breaker trip,
    no retry storm). 200 returns ``{"status": "ok", "body": <bytes>}``; 5xx/
    other errors pass through via ``raise_for_status``.
    """
    resp = await client.get(url)
    if resp.status_code == 422:
        return {"status": "no_data", "body": None}
    resp.raise_for_status()
    return {"status": "ok", "body": resp.content}
