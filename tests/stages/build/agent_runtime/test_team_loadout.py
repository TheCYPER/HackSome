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


def test_all_team_roles_declare_and_materialize_zero_skills(tmp_path, monkeypatch):
    for path in ACTIVE_SPECS:
        spec = AgentSpec.load(str(path))
        assert spec.skills == []
        assert spec.skill_paths() == []
        info = runtime_for(spec).materialize_home(
            spec, str(tmp_path / f"{spec.name}-home")
        )
        assert info.skills == []

    lead_spec = AGENTS_ROOT / "lead.yaml"
    monkeypatch.setenv("AGENT_SPEC", str(lead_spec))
    info = materialize_for("lead", str(AGENTS_ROOT), str(tmp_path / "home"))
    assert info is not None
    assert info.skills == []
    skills_root = tmp_path / "home" / "skills"
    assert not skills_root.exists() or list(skills_root.iterdir()) == []


def test_production_inventory_contains_only_active_zero_skill_specs():
    production_specs = set(AGENTS_ROOT.rglob("*.yaml"))

    assert production_specs == ACTIVE_SPECS
    assert set((AGENTS_ROOT / "assets").rglob("*charter.md")) == ACTIVE_CHARTERS
    assert SHARED_TOOL_PROMPT.is_file()
    assert not (AGENTS_ROOT / "assets" / "skills").exists()
