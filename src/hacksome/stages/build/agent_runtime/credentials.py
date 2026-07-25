"""Credential seam (AG3) — decoupled from provider.

The yaml vocabulary (`credentials: subscription | api-key`) is runtime-RELATIVE:
each runtime adapter maps it to its own credential classes via
credential_kinds() (07-07 codex-runtime, design §5):

    claude-code × subscription → CLAUDE_CODE_OAUTH_TOKEN
    claude-code × api-key      → ANTHROPIC_API_KEY
    codex       × subscription → (no env var) CODEX_HOME/auth.json, pre-seeded
    codex       × api-key      → CODEX_API_KEY

CRITICAL — credential mutual-exclusion (spike-verified, design §3.3):
    ANTHROPIC_API_KEY has HIGHER priority than CLAUDE_CODE_OAUTH_TOKEN inside the
    container. If both are present the API key wins and the subscription token is
    *silently ignored* (claude --help: "Anthropic auth is strictly
    ANTHROPIC_API_KEY or apiKeyHelper"). Therefore each CredentialSource.env()
    returns ONLY its own variable, and `injection_env()` additionally CLEARS every
    other credential var so subscription mode can never be silently overridden.
    The clear-set spans BOTH runtimes (cross-runtime bleed guard): a lingering
    CODEX_API_KEY / OPENAI_API_KEY must never leak into a claude run and vice
    versa. OPENAI_API_KEY is never injected by any source (codex's exec-
    recommended var is CODEX_API_KEY) but the OpenAI SDK also honors it, so it
    is always cleared.
"""

import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# Every credential env var the seam knows about — across ALL runtimes.
# `injection_env()` clears any of these NOT set by the active CredentialSource
# → enforces mutual exclusion (and cross-runtime non-bleed).
ALL_CREDENTIAL_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY",
                       "CODEX_API_KEY", "OPENAI_API_KEY")


@runtime_checkable
class CredentialSource(Protocol):
    """Supplies the (exclusive) credential env for a provider invocation."""

    kind: str

    def env(self) -> dict[str, str]:
        """Return ONLY this source's own credential var (mutually exclusive)."""
        ...


@dataclass
class SubscriptionCreds:
    """Claude subscription OAuth token (default, cheapest). Source: vm/.env.local
    → CLAUDE_CODE_OAUTH_TOKEN. Injects ONLY the OAuth token."""

    kind: str = "subscription"
    token: str | None = None

    def env(self) -> dict[str, str]:
        token = self.token if self.token is not None else os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
        return {"CLAUDE_CODE_OAUTH_TOKEN": token}


@dataclass
class ApiKeyCreds:
    """Anthropic API key (per-usage billing). Source: env ANTHROPIC_API_KEY.
    Injects ONLY the API key."""

    kind: str = "api-key"
    key: str | None = None

    def env(self) -> dict[str, str]:
        key = self.key if self.key is not None else os.environ.get("ANTHROPIC_API_KEY", "")
        return {"ANTHROPIC_API_KEY": key}


@dataclass
class CodexSubscriptionCreds:
    """ChatGPT-subscription auth for codex (the main codex form, design §5).

    There is NO env var to inject: auth rides CODEX_HOME/auth.json, which the
    codex adapter's materialize_home seeds per role from the account package
    (accounts/<id>/codex-auth.json, produced once by `codex login
    --device-auth`) and which codex then refreshes in place. env() returning {}
    still matters: injection_env() clears ALL credential vars around it, so a
    lingering CODEX_API_KEY / OPENAI_API_KEY cannot silently outrank the
    subscription auth."""

    kind: str = "subscription"

    def env(self) -> dict[str, str]:
        return {}


@dataclass
class CodexApiKeyCreds:
    """OpenAI API key for codex exec (per-usage billing). Source: env
    CODEX_API_KEY — the exec/CI-recommended var. Injects ONLY that key
    (OPENAI_API_KEY stays in the clear-set, never injected)."""

    kind: str = "api-key"
    key: str | None = None

    def env(self) -> dict[str, str]:
        key = self.key if self.key is not None else os.environ.get("CODEX_API_KEY", "")
        return {"CODEX_API_KEY": key}


def injection_env(creds: CredentialSource) -> dict[str, str]:
    """Final, mutually-exclusive credential env to inject into the container.

    = creds.env() PLUS an explicit empty value for every OTHER credential var, so
    the unused credential can never linger and silently win (spike-verified
    api-key > subscription priority; the four-var set also guards cross-runtime
    bleed).
    """
    env = dict(creds.env())
    for var in ALL_CREDENTIAL_VARS:
        env.setdefault(var, "")
    return env
