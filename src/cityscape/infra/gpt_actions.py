"""Detection of ChatGPT GPT action traffic (OpenAI Custom GPTs).

Background: The cityscape GPT in the GPT Store calls the API via OpenAI egress.
OpenAI sends documented identification headers with each request:

- ``openai-gpt-id``: which GPT triggered the call,
- ``openai-ephemeral-user-id``: pseudonymous identifier, stable per user+GPT,
- ``openai-conversation-id``: the conversation,

plus the User-Agent ``ChatGPT-User`` (Cloudflare-verified bot). These
signals feed three consumers (analogous to the MCP channel):

1. ntfy push per action (ops/firstseen.note_gpt_action),
2. metric channel ``gpt`` (dashboard/digest, main.MetricsMiddleware),
3. dedicated rate limit per GPT user (api/v1/gpt_guard), because ALL
   ChatGPT users arrive server-side via FEW OpenAI egress IPs and a
   per-IP limit would throttle them collectively (same pattern as
   Anthropic egress for the MCP server, see infra/allowlist.py).

SPOOFING CLASSIFICATION: The headers are forgeable client-side. However, a spoofer
gains NOTHING from this: the IP-based limits (slowapi + AbuseGuard)
continue to apply unchanged for non-allowlisted IPs; the GPT limit is merely
ADDITIONAL. Only the channel labeling (metrics/ntfy) would be spoofed;
the ntfy flood throttle (ops/notify) limits the impact.

Stdlib-only (like infra/allowlist.py), so that non-FastAPI paths can also
use the module without Settings/slowapi imports.
"""

from __future__ import annotations

from collections.abc import Mapping

# Documented OpenAI Actions headers (Starlette headers are case-insensitive,
# .get() expects lowercase).
GPT_ID_HEADER = "openai-gpt-id"
GPT_USER_HEADER = "openai-ephemeral-user-id"
GPT_CONVERSATION_HEADER = "openai-conversation-id"

# UA marker for Actions calls ("ChatGPT-User/1.0 (+https://openai.com/bot)").
_UA_MARKER = "chatgpt-user"


def is_gpt_action(headers: Mapping[str, str]) -> bool:
    """True if the request looks like a ChatGPT GPT action call.

    Detected via the OpenAI identification headers OR the ChatGPT User-Agent;
    both signals combined also cover partial setups (e.g. UA without header
    during actions import/schema fetch).
    """
    if (
        headers.get(GPT_ID_HEADER)
        or headers.get(GPT_USER_HEADER)
        or headers.get(GPT_CONVERSATION_HEADER)
    ):
        return True
    return _UA_MARKER in headers.get("user-agent", "").lower()


def gpt_rate_ident(headers: Mapping[str, str], client_ip: str) -> str:
    """Counting key for the GPT rate limit: User > Conversation > GPT > IP.

    The ephemeral user identifier is stable per user+GPT and thus the
    fairest key (each ChatGPT user gets their own budget).
    If missing, we fall back to conversation, then GPT, and finally
    IP (never without a key).
    """
    return (
        headers.get(GPT_USER_HEADER)
        or headers.get(GPT_CONVERSATION_HEADER)
        or headers.get(GPT_ID_HEADER)
        or client_ip
    )
