"""Credential seam mutual-exclusion (AG3 / AC3, spike-verified; four-var
clear-set across both runtimes since 07-07 codex-runtime)."""

from hacksome.stages.build.agent_runtime.credentials import (
    ALL_CREDENTIAL_VARS,
    ApiKeyCreds,
    CodexApiKeyCreds,
    CodexSubscriptionCreds,
    SubscriptionCreds,
    injection_env,
)


def _cleared(*own):
    """Expected injection_env clear-set: every known var empty except `own`."""
    return {v: "" for v in ALL_CREDENTIAL_VARS if v not in own}


def test_all_credential_vars_is_the_four_var_cross_runtime_set():
    """OPENAI_API_KEY is NEVER injected by any source but the OpenAI SDK honors
    it, so it must ride the clear-set (cross-runtime bleed guard)."""
    assert ALL_CREDENTIAL_VARS == ("CLAUDE_CODE_OAUTH_TOKEN",
                                   "ANTHROPIC_API_KEY",
                                   "CODEX_API_KEY",
                                   "OPENAI_API_KEY")


def test_subscription_env_only_oauth():
    env = SubscriptionCreds(token="tok").env()
    assert env == {"CLAUDE_CODE_OAUTH_TOKEN": "tok"}
    assert "ANTHROPIC_API_KEY" not in env


def test_apikey_env_only_key():
    env = ApiKeyCreds(key="k").env()
    assert env == {"ANTHROPIC_API_KEY": "k"}
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env


def test_codex_subscription_env_is_empty():
    """Codex subscription auth rides CODEX_HOME/auth.json (seeded by the codex
    adapter's materialize_home) — there is NO env var to inject."""
    assert CodexSubscriptionCreds().env() == {}


def test_codex_apikey_env_only_codex_key():
    env = CodexApiKeyCreds(key="ck").env()
    assert env == {"CODEX_API_KEY": "ck"}
    assert "OPENAI_API_KEY" not in env


def test_injection_env_subscription_clears_every_other_var():
    """Subscription mode must inject an EMPTY value for every other credential
    var so none can silently override the OAuth token (api-key > subscription
    priority, plus cross-runtime bleed)."""
    env = injection_env(SubscriptionCreds(token="t"))
    assert env == {"CLAUDE_CODE_OAUTH_TOKEN": "t",
                   **_cleared("CLAUDE_CODE_OAUTH_TOKEN")}


def test_injection_env_apikey_clears_every_other_var():
    env = injection_env(ApiKeyCreds(key="k"))
    assert env == {"ANTHROPIC_API_KEY": "k", **_cleared("ANTHROPIC_API_KEY")}


def test_injection_env_codex_subscription_clears_all_four():
    """env() is {} → the injection is PURELY the clear-set: a lingering
    CODEX_API_KEY / OPENAI_API_KEY must never outrank the auth.json seed."""
    assert injection_env(CodexSubscriptionCreds()) == _cleared()


def test_injection_env_codex_apikey_clears_the_rest():
    env = injection_env(CodexApiKeyCreds(key="ck"))
    assert env == {"CODEX_API_KEY": "ck", **_cleared("CODEX_API_KEY")}
    assert env["OPENAI_API_KEY"] == ""   # recognized by the SDK, never injected


def test_subscription_reads_env_when_token_none(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "from-env")
    assert SubscriptionCreds().env() == {"CLAUDE_CODE_OAUTH_TOKEN": "from-env"}


def test_apikey_reads_env_when_key_none(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-from-env")
    assert ApiKeyCreds().env() == {"ANTHROPIC_API_KEY": "key-from-env"}


def test_codex_apikey_reads_env_when_key_none(monkeypatch):
    monkeypatch.setenv("CODEX_API_KEY", "codex-from-env")
    assert CodexApiKeyCreds().env() == {"CODEX_API_KEY": "codex-from-env"}
