"""CUA_PROXY expansion snippet (07-03-proxy-slot).

Locks the proxy-slot contract of agent/proxy_env.sh: a single CUA_PROXY key in
accounts/<id>/secrets.env expands to both-case proxy env pairs for whichever
shell sources the snippet (the startup hook does so in the computer-server
subshell ONLY — LLM insulation is structural, the claude subtree never sees
these vars); unset means NOT ONE proxy variable appears (host egress, zero
impact); the NO_PROXY default keeps localhost + Anthropic domains off the
proxy as defense in depth for curl-based tooling, and an explicit NO_PROXY
overrides it wholesale.
"""

import os
import subprocess

from hacksome.stages.build import ASSETS_ROOT


SNIPPET = str(ASSETS_ROOT / "scripts" / "proxy_env.sh")

PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
              "NO_PROXY", "no_proxy")
DEFAULT_NO_PROXY = ("localhost,127.0.0.1,.anthropic.com,anthropic.com,"
                    ".claude.ai,claude.ai")


def _env_after_source(extra_env):
    """Source the snippet in a clean shell and return the resulting env dict."""
    env = {"PATH": os.environ["PATH"]}
    env.update(extra_env)
    out = subprocess.run(
        ["bash", "-c", f". {SNIPPET} && env"],
        env=env, capture_output=True, text=True, check=True,
    ).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def test_unset_cua_proxy_exports_nothing():
    env = _env_after_source({})
    assert not [v for v in PROXY_VARS if v in env]


def test_cua_proxy_expands_to_all_six_vars_with_default_no_proxy():
    url = "http://user:pass@203.0.113.7:8080"
    env = _env_after_source({"CUA_PROXY": url})
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        assert env[var] == url
    # Exact-match the default NO_PROXY: localhost + Anthropic domains stay off
    # the proxy for curl-based tooling in the sourcing subtree. Defense in
    # depth only — the hard "LLM never rides the proxy" guarantee is the
    # hook's scoping (the claude subtree never sources this snippet), because
    # the claude CLI ignores host-based NO_PROXY entries (design.md matrix).
    assert env["NO_PROXY"] == DEFAULT_NO_PROXY
    assert env["no_proxy"] == DEFAULT_NO_PROXY


def test_explicit_no_proxy_overrides_default_wholesale():
    env = _env_after_source({"CUA_PROXY": "http://203.0.113.7:8080",
                             "NO_PROXY": "localhost"})
    assert env["NO_PROXY"] == "localhost"
    assert env["no_proxy"] == "localhost"


def test_snippet_is_posix_sh_compatible():
    # The kasm hook runs under bash, but the snippet claims plain sh semantics;
    # keep it sourceable by dash-like shells so the contract stays portable.
    subprocess.run(["sh", "-c", f"CUA_PROXY=x . {SNIPPET}"], check=True)
