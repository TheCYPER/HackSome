from pathlib import Path

from agent.resident_loadout import materialize_for
from agent.runtimes import runtime_for
from agent.spec import AgentSpec


ROOT = Path(__file__).resolve().parents[2]
ACTIVE_SPECS = {
    ROOT / "agents" / "lead.yaml",
    ROOT / "agents" / "ephemeral" / "team-worker.yaml",
    ROOT / "agents" / "ephemeral" / "team-verifier.yaml",
}
ACTIVE_CHARTERS = {
    ROOT / "agents" / "assets" / "lead-charter.md",
    ROOT / "agents" / "assets" / "team-worker-charter.md",
    ROOT / "agents" / "assets" / "team-verifier-charter.md",
}


def test_all_team_roles_declare_and_materialize_zero_skills(tmp_path, monkeypatch):
    for path in ACTIVE_SPECS:
        spec = AgentSpec.load(str(path))
        assert spec.skills == []
        assert spec.skill_paths() == []
        info = runtime_for(spec).materialize_home(
            spec, str(tmp_path / f"{spec.name}-home")
        )
        assert info.skills == []

    lead_spec = ROOT / "agents" / "lead.yaml"
    monkeypatch.setenv("AGENT_SPEC", str(lead_spec))
    info = materialize_for("lead", str(ROOT / "agents"), str(tmp_path / "home"))
    assert info is not None
    assert info.skills == []
    skills_root = tmp_path / "home" / "skills"
    assert not skills_root.exists() or list(skills_root.iterdir()) == []


def test_production_inventory_contains_only_active_zero_skill_specs():
    production_specs = set((ROOT / "agents").rglob("*.yaml"))

    assert production_specs == ACTIVE_SPECS
    assert set((ROOT / "agents" / "assets").rglob("*charter.md")) == ACTIVE_CHARTERS
    assert not (ROOT / "agents" / "assets" / "skills").exists()
    assert not (ROOT / "docker-compose.mail.yml").exists()
