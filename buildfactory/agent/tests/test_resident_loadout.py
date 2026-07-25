"""V7 fixed-template loadout materialization contracts."""

from pathlib import Path

import pytest

from agent import resident_loadout


ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "agents"


@pytest.fixture(autouse=True)
def _isolated_runtime_home(tmp_path, monkeypatch):
    home = tmp_path / "user-home"
    home.mkdir()
    auth = tmp_path / "codex-auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CODEX_AUTH_SEED", str(auth))
    monkeypatch.setenv("DATAFORSEO_USERNAME", "test-user")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "test-password")
    monkeypatch.delenv("AGENT_SPEC", raising=False)


def _materialize(tmp_path, monkeypatch, key: str, relative_spec: str):
    monkeypatch.setenv("AGENT_SPEC", str(AGENTS / relative_spec))
    return resident_loadout.materialize_for(
        key,
        agents_dir=str(AGENTS),
        claude_home=str(tmp_path / f"{key}-home"),
    )


@pytest.mark.parametrize(
    ("key", "relative_spec"),
    [
        ("lead", "lead.yaml"),
        ("team-worker", "ephemeral/team-worker.yaml"),
        ("team-verifier", "ephemeral/team-verifier.yaml"),
    ],
)
def test_active_team_templates_materialize_zero_skills(
    tmp_path, monkeypatch, key, relative_spec
):
    info = _materialize(tmp_path, monkeypatch, key, relative_spec)
    assert info.skills == []


def test_unknown_key_is_charter_only(tmp_path):
    assert resident_loadout.materialize_for(
        "nope", agents_dir=str(AGENTS), claude_home=str(tmp_path / "home")
    ) is None


def test_main_never_bricks_on_bad_template(tmp_path, monkeypatch, capsys):
    bad_dir = tmp_path / "agents"
    bad_dir.mkdir()
    (bad_dir / "ghost.yaml").write_text(
        "name: ghost\nskills:\n  - assets/skills/does-not-exist\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_KEY", "ghost")
    monkeypatch.setenv("AGENTS_DIR", str(bad_dir))
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / "claude"))
    assert resident_loadout.main() == 0
    assert "ERROR materializing" in capsys.readouterr().out


def test_main_without_agent_key_is_noop(monkeypatch):
    monkeypatch.delenv("AGENT_KEY", raising=False)
    assert resident_loadout.main() == 0


def test_deprecated_loadout_overlay_cannot_mutate_fixed_template(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AGENT_LOADOUT", str(tmp_path / "arbitrary.yaml"))
    info = _materialize(tmp_path, monkeypatch, "lead", "lead.yaml")
    assert info.skills == []
