from hacksome.stages.build import AGENTS_ROOT
from hacksome.stages.build.agent_runtime.resident_loadout import materialize_for
from hacksome.stages.build.agent_runtime.runtimes import runtime_for
from hacksome.stages.build.agent_runtime.spec import AgentSpec


ACTIVE_SPECS = {
    AGENTS_ROOT / "lead.yaml",
    AGENTS_ROOT / "ephemeral" / "team-worker.yaml",
    AGENTS_ROOT / "ephemeral" / "team-verifier.yaml",
}
ACTIVE_CHARTERS = {
    AGENTS_ROOT / "assets" / "lead-charter.md",
    AGENTS_ROOT / "assets" / "team-worker-charter.md",
    AGENTS_ROOT / "assets" / "team-verifier-charter.md",
}
SHARED_TOOL_PROMPT = AGENTS_ROOT / "assets" / "shared-tool-use.md"
LEAD_SKILL_ROOT = AGENTS_ROOT / "assets" / "skills" / "maintain-lead-brief"
LEAD_SKILL_FILES = {
    LEAD_SKILL_ROOT / "SKILL.md",
    LEAD_SKILL_ROOT / "agents" / "openai.yaml",
}


def test_only_lead_declares_and_materializes_reflection_skill(tmp_path, monkeypatch):
    expected = {
        "lead": ["maintain-lead-brief"],
        "team-worker": [],
        "team-verifier": [],
    }
    for path in ACTIVE_SPECS:
        spec = AgentSpec.load(str(path))
        expected_names = expected[spec.name]
        assert [candidate.rsplit("/", 1)[-1] for candidate in spec.skills] == (
            expected_names
        )
        info = runtime_for(spec).materialize_home(
            spec,
            str(tmp_path / f"{spec.name}-home"),
            skills_root=str(tmp_path / f"{spec.name}-skills"),
        )
        assert info.skills == expected_names

    lead_spec = AGENTS_ROOT / "lead.yaml"
    user_home = tmp_path / "user-home"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("AGENT_SPEC", str(lead_spec))
    info = materialize_for("lead", str(AGENTS_ROOT), str(tmp_path / "home"))
    assert info is not None
    assert info.skills == ["maintain-lead-brief"]
    skill_root = user_home / ".agents" / "skills" / "maintain-lead-brief"
    assert (skill_root / "SKILL.md").is_file()
    assert (skill_root / "agents" / "openai.yaml").is_file()


def test_production_inventory_contains_only_active_role_specs_and_lead_skill():
    production_specs = set(AGENTS_ROOT.rglob("*.yaml"))

    assert production_specs == ACTIVE_SPECS | {
        LEAD_SKILL_ROOT / "agents" / "openai.yaml"
    }
    assert set((AGENTS_ROOT / "assets").rglob("*charter.md")) == ACTIVE_CHARTERS
    assert SHARED_TOOL_PROMPT.is_file()
    assert {path for path in LEAD_SKILL_ROOT.rglob("*") if path.is_file()} == (
        LEAD_SKILL_FILES
    )
