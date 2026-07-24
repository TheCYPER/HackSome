"""Active Team template MCP assets and credential-safety contracts."""

import json
from pathlib import Path

import pytest

from agent.spec import AgentSpec


ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "agents"
ROLE_SPECS = {
    "lead": AGENTS / "lead.yaml",
    "team-worker": AGENTS / "ephemeral" / "team-worker.yaml",
    "team-verifier": AGENTS / "ephemeral" / "team-verifier.yaml",
}
FULL_SERVER_SET = {"cua-local", "dataforseo", "gsc", "ga4", "playwright", "stripe"}
CREDENTIAL_MARKERS = ("USERNAME", "PASSWORD", "CREDENTIALS", "TOKEN", "KEY", "SECRET")


def _mcp_path(role: str) -> Path:
    spec = AgentSpec.load(str(ROLE_SPECS[role]))
    return Path(spec.resolve(spec.mcp_config))


def _servers(role: str) -> dict:
    return json.loads(_mcp_path(role).read_text(encoding="utf-8"))["mcpServers"]


@pytest.mark.parametrize("role", ROLE_SPECS)
def test_every_active_template_resolves_an_existing_mcp_asset(role):
    path = _mcp_path(role)
    assert path.is_file()
    assert isinstance(_servers(role), dict)


@pytest.mark.parametrize("role", ["lead", "team-worker"])
def test_decision_and_execution_templates_keep_the_full_tool_field(role):
    assert set(_servers(role)) == FULL_SERVER_SET


def test_verifier_mcp_is_deliberately_narrow_and_independent():
    assert set(_servers("team-verifier")) == {"cua-local", "playwright"}
    assert _mcp_path("team-verifier").name == "verifier-v7.json"
    assert not (AGENTS / "mcp" / "verifier.json").exists()


@pytest.mark.parametrize("role", ROLE_SPECS)
def test_cua_local_matches_the_agent_image_baseline(role):
    cua = _servers(role)["cua-local"]
    assert cua == {
        "command": "python3",
        "args": ["/opt/foundagent/cua_mcp.py"],
        "env": {"CUA_HOST_SERVER": "1"},
    }


@pytest.mark.parametrize("role", ROLE_SPECS)
def test_playwright_uses_the_account_browser_wrapper(role):
    playwright = _servers(role)["playwright"]
    assert playwright["command"] == "/opt/foundagent-orch/agent/browser_mcp.sh"
    assert "args" not in playwright
    wrapper = ROOT / "agent" / "browser_mcp.sh"
    assert wrapper.is_file()


@pytest.mark.parametrize("role", ROLE_SPECS)
def test_mcp_credentials_are_variable_expansions_not_literals(role):
    for server_name, server in _servers(role).items():
        for key, value in server.get("env", {}).items():
            if any(marker in key.upper() for marker in CREDENTIAL_MARKERS):
                assert value.startswith("${"), (
                    f"{role}/{server_name} {key} must be an environment expansion"
                )
