"""AgentSpec loading + credential factory (AG1/AG2/AG3, AC1/AC2/AC3).

The provider factory moved to agent.runtimes.runtime_for (07-07 codex-runtime)
and is tested in test_runtimes.py; the spec keeps the declaration semantics —
including the load-bearing absent-vs-null distinction for model/effort."""

import os

import pytest

from agent.spec import AgentSpec, credential_for
from agent.credentials import (
    ApiKeyCreds,
    CodexApiKeyCreds,
    CodexSubscriptionCreds,
    SubscriptionCreds,
)
from agent.runtimes.base import UNSET

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AGENTS = os.path.join(REPO, "agents")
ROLE_SPECS = {
    "lead": os.path.join(AGENTS, "lead.yaml"),
    "team-worker": os.path.join(AGENTS, "ephemeral", "team-worker.yaml"),
    "team-verifier": os.path.join(AGENTS, "ephemeral", "team-verifier.yaml"),
}


def _write_fixture_yaml(root):
    """Self-contained spec fixture (yaml + charter + one skill) under root/agents.

    Loading semantics used the (since deleted) operator.yaml/hello-foundagent
    as fixtures and broke when the backlog reset removed them; a spec-loading
    test must not depend on which production yamls currently exist.
    """
    agents = root / "agents"
    skill = agents / "assets" / "skills" / "demo-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo-skill\n---\nSay hello.\n")
    (agents / "assets" / "charter.md").write_text("[charter-ack] demo charter\n")
    (agents / "demo.yaml").write_text(
        "name: demo\n"
        "provider: claude-code\n"
        "credentials: subscription\n"
        "system_prompt: assets/charter.md\n"
        "skills:\n  - assets/skills/demo-skill\n"
        "mcp_config: /opt/foundagent/mcp.json\n"
        "permission_mode: bypass\n")
    return str(agents / "demo.yaml")


def test_load_full_spec(tmp_path):
    spec = AgentSpec.load(_write_fixture_yaml(tmp_path))
    assert spec.name == "demo"
    assert spec.provider == "claude-code"
    assert spec.credentials == "subscription"
    assert spec.system_prompt == "assets/charter.md"
    assert spec.skills == ["assets/skills/demo-skill"]
    assert spec.mcp_config == "/opt/foundagent/mcp.json"
    assert spec.bypass_permissions is True


def test_load_team_worker():
    spec = AgentSpec.load(ROLE_SPECS["team-worker"])
    assert spec.name == "team-worker"
    assert spec.provider == "codex"
    assert spec.model == "gpt-5.6-sol"
    assert spec.effort == "xhigh"
    assert spec.credentials == "subscription"
    assert spec.skills == []
    assert spec.system_prompt == "../assets/team-worker-charter.md"
    assert spec.hooks is None


def test_resident_roles_use_codex_sol_xhigh():
    """Every active Team role stays on the same declared model baseline."""
    for role, path in ROLE_SPECS.items():
        spec = AgentSpec.load(path)
        assert spec.provider == "codex", role
        assert spec.model == "gpt-5.6-sol", role
        assert spec.effort == "xhigh", role


def test_ac1_add_agent_without_code_change(tmp_path):
    """AC1: two distinct agents loaded from two yaml files, ZERO .py change.

    The api-key half is a self-contained fixture since 07-07 longrun-hardening
    (researcher.yaml carried the demo value before, but a production yaml must
    not stay broken just to prop up this test)."""
    op = AgentSpec.load(_write_fixture_yaml(tmp_path))  # subscription
    keyed = tmp_path / "agents" / "keyed.yaml"
    keyed.write_text("name: keyed\ncredentials: api-key\n")
    ke = AgentSpec.load(str(keyed))
    # different declarations → different specs (credential source diverges)
    assert op.credentials != ke.credentials
    assert isinstance(credential_for(op), SubscriptionCreds)
    assert isinstance(credential_for(ke), ApiKeyCreds)


def test_defaults_minimal_spec():
    spec = AgentSpec(name="x")
    assert spec.provider == "claude-code"
    assert spec.credentials == "subscription"
    assert spec.mcp_config == "/opt/foundagent/mcp.json"
    assert spec.permission_mode == "bypass"
    assert spec.skills == []
    assert spec.session == "fresh"       # issue #207: resume is the opt-in exception
    assert spec.idle == "stop"           # 07-08: proactive is the opt-in exception
    assert spec.strategic is False        # 07-11: event reasoning is opt-in


def test_session_field_loads_and_defaults_fresh(tmp_path):
    """`session:` defaults fresh; only the long-running Lead opts into resume."""
    spec = AgentSpec.load(_write_fixture_yaml(tmp_path))    # no session key
    assert spec.session == "fresh"
    assert AgentSpec.load(ROLE_SPECS["lead"]).session == "resume"
    assert AgentSpec.load(ROLE_SPECS["team-worker"]).session == "fresh"
    assert AgentSpec.load(ROLE_SPECS["team-verifier"]).session == "fresh"


def test_idle_field_loads_and_defaults_stop(tmp_path):
    """`idle:` defaults stop; the resident Lead is the only proactive role."""
    spec = AgentSpec.load(_write_fixture_yaml(tmp_path))    # no idle key
    assert spec.idle == "stop"
    assert AgentSpec.load(ROLE_SPECS["lead"]).idle == "proactive"
    assert AgentSpec.load(ROLE_SPECS["team-worker"]).idle == "stop"
    assert AgentSpec.load(ROLE_SPECS["team-verifier"]).idle == "stop"


def test_strategic_field_loads_and_defaults_false(tmp_path):
    """The Team runtime leaves the retired Company strategic prefix disabled."""
    spec = AgentSpec.load(_write_fixture_yaml(tmp_path))
    assert spec.strategic is False
    for role in ROLE_SPECS:
        assert AgentSpec.load(ROLE_SPECS[role]).strategic is False


def test_credential_for():
    assert isinstance(credential_for(AgentSpec(name="x", credentials="subscription")), SubscriptionCreds)
    assert isinstance(credential_for(AgentSpec(name="x", credentials="api-key")), ApiKeyCreds)


def test_credential_for_is_provider_aware():
    """07-07 codex-runtime (design §5): the SAME yaml vocabulary resolves via
    the chosen runtime's credential_kinds() — switching provider re-maps
    subscription/api-key without touching the credentials key."""
    assert isinstance(
        credential_for(AgentSpec(name="x", provider="codex",
                                 credentials="subscription")),
        CodexSubscriptionCreds)
    assert isinstance(
        credential_for(AgentSpec(name="x", provider="codex",
                                 credentials="api-key")),
        CodexApiKeyCreds)


def test_unknown_credentials_raise():
    # unknown provider is runtime_for's job now — see test_runtimes.py
    with pytest.raises(ValueError):
        credential_for(AgentSpec(name="x", credentials="bogus"))
    with pytest.raises(ValueError):
        credential_for(AgentSpec(name="x", provider="codex", credentials="bogus"))


def test_read_system_prompt_and_skill_paths(tmp_path):
    spec = AgentSpec.load(_write_fixture_yaml(tmp_path))
    sp = spec.read_system_prompt()
    assert sp and "[charter-ack]" in sp
    paths = spec.skill_paths()
    assert len(paths) == 1
    assert os.path.isabs(paths[0])
    assert os.path.basename(paths[0]) == "demo-skill"
    assert os.path.exists(os.path.join(paths[0], "SKILL.md"))


def test_model_effort_unset_override_and_null(tmp_path):
    """model/effort three-way semantics (07-07 codex-runtime): key ABSENT from
    the yaml → UNSET (the runtime adapter applies its own fleet default —
    claude: opus + xhigh, locked in test_runtimes.py); set in yaml → override;
    explicit null → None (flag omitted → account/CLI default). load() must
    keep absent and null distinguishable."""
    spec = AgentSpec.load(_write_fixture_yaml(tmp_path))   # no model/effort keys
    assert spec.model is UNSET
    assert spec.effort is UNSET

    pinned = tmp_path / "agents" / "pinned.yaml"
    pinned.write_text("name: pinned\nmodel: claude-sonnet-4-6\neffort: low\n")
    spec2 = AgentSpec.load(str(pinned))
    assert (spec2.model, spec2.effort) == ("claude-sonnet-4-6", "low")

    optout = tmp_path / "agents" / "optout.yaml"
    optout.write_text("name: optout\nmodel: null\neffort: null\n")
    spec3 = AgentSpec.load(str(optout))
    assert spec3.model is None and spec3.effort is None
    assert spec3.model is not UNSET     # null ≠ absent — the whole point
