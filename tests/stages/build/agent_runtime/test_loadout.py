"""Skill/Hook/Prompt materialization (AG4 / D6, AC4 static).

Since 07-07 codex-runtime the entry point is the claude adapter's
materialize_home (neutral skills/manifest core in loadout.py + the claude
settings.json hooks merge in the adapter); the contract below is unchanged."""

import json
import os

from hacksome.stages.build.agent_runtime.runtimes.claude_code import ClaudeCodeRuntime
from hacksome.stages.build.agent_runtime.spec import AgentSpec


def materialize(spec, home):
    return ClaudeCodeRuntime().materialize_home(spec, home)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AGENTS = os.path.join(REPO, "agents")


def _demo(root, skills=("demo-skill",), hooks=True):
    """Build a self-contained fixture spec under root/agents and load it.

    These tests used the (since deleted) operator.yaml + hello-foundagent as
    fixtures and broke when the backlog reset removed them. Materialization
    semantics must not depend on which production yamls happen to exist, so
    the fixture is written into tmp_path instead. Re-callable with different
    skills/hooks to model an overlay flipping capabilities between restarts.
    """
    agents = root / "agents"
    for name in skills:
        skill = agents / "assets" / "skills" / name
        skill.mkdir(parents=True, exist_ok=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\n---\nSay hello.\n")
    (agents / "assets").mkdir(parents=True, exist_ok=True)
    (agents / "assets" / "charter.md").write_text("[charter-ack] demo charter\n")
    (agents / "assets" / "hooks.snippet.json").write_text(json.dumps(
        {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": []}]}}))
    yaml = "name: demo\nsystem_prompt: assets/charter.md\n"
    if skills:
        yaml += "skills:\n" + "".join(f"  - assets/skills/{n}\n" for n in skills)
    if hooks:
        yaml += "hooks: assets/hooks.snippet.json\n"
    (agents / "demo.yaml").write_text(yaml)
    return AgentSpec.load(str(agents / "demo.yaml"))


def _settings(home):
    with open(os.path.join(home, "settings.json")) as f:
        return json.load(f)


def test_materialize_skill_and_settings(tmp_path):
    home = str(tmp_path / "claude")
    info = materialize(_demo(tmp_path), home)

    # skill copied to <claude_home>/skills/<name>/SKILL.md (spike S2 landing path)
    skill_md = os.path.join(home, "skills", "demo-skill", "SKILL.md")
    assert os.path.exists(skill_md)
    assert info.skills == ["demo-skill"]

    # hooks merged into settings.json
    assert info.hooks_merged is True
    with open(info.settings_path) as f:
        settings = json.load(f)
    assert "PreToolUse" in settings["hooks"]
    assert len(settings["hooks"]["PreToolUse"]) == 1

    # system prompt read for --append-system-prompt
    assert info.system_prompt and "[charter-ack]" in info.system_prompt


def test_merge_preserves_existing_keys_and_entries(tmp_path):
    home = str(tmp_path / "claude")
    os.makedirs(home)
    # pre-existing settings with an unrelated key + an existing hook entry
    pre = {
        "foo": "bar",
        "hooks": {"PreToolUse": [{"matcher": "Existing", "hooks": []}]},
    }
    with open(os.path.join(home, "settings.json"), "w") as f:
        json.dump(pre, f)

    materialize(_demo(tmp_path), home)

    with open(os.path.join(home, "settings.json")) as f:
        settings = json.load(f)
    # existing top-level key untouched (no whole-file overwrite)
    assert settings["foo"] == "bar"
    # existing entry preserved + new one appended
    matchers = [e.get("matcher") for e in settings["hooks"]["PreToolUse"]]
    assert "Existing" in matchers
    assert "*" in matchers
    assert len(settings["hooks"]["PreToolUse"]) == 2


def test_materialize_is_idempotent(tmp_path):
    home = str(tmp_path / "claude")
    spec = _demo(tmp_path)
    materialize(spec, home)
    info = materialize(spec, home)  # second run must not duplicate the hook
    settings = _settings(home)
    assert len(settings["hooks"]["PreToolUse"]) == 1
    assert os.path.exists(os.path.join(home, "skills", "demo-skill", "SKILL.md"))
    # manifest is stable across identical runs, and a clean re-run never warns
    assert info.warnings == []
    with open(os.path.join(home, ".loadout-manifest.json")) as f:
        manifest = json.load(f)
    assert manifest == {
        "skills": ["demo-skill"],
        "hooks": {"PreToolUse": [{"matcher": "*", "hooks": []}]},
    }


# --- reconcile (07-03 company-loadout-overlay, manifest bookkeeping) ----------


def test_reconcile_removes_skill_turned_off(tmp_path):
    # on → off → re-materialize: the dir the LOADOUT copied last run must go.
    home = str(tmp_path / "claude")
    materialize(_demo(tmp_path, skills=("demo-skill", "extra-skill")), home)
    assert os.path.exists(os.path.join(home, "skills", "extra-skill", "SKILL.md"))

    info = materialize(_demo(tmp_path, skills=("demo-skill",)), home)
    assert not os.path.exists(os.path.join(home, "skills", "extra-skill"))
    assert os.path.exists(os.path.join(home, "skills", "demo-skill", "SKILL.md"))
    assert info.skills == ["demo-skill"]


def test_reconcile_never_touches_manual_skill_dirs(tmp_path):
    # A dir the agent installed itself is not in the manifest → never deleted,
    # even when the loadout's own skill set shrinks to nothing.
    home = tmp_path / "claude"
    materialize(_demo(tmp_path), str(home))
    manual = home / "skills" / "hand-installed"
    manual.mkdir()
    (manual / "SKILL.md").write_text("agent's own\n")

    materialize(_demo(tmp_path, skills=()), str(home))
    assert not (home / "skills" / "demo-skill").exists()
    assert (manual / "SKILL.md").exists()


def test_hooks_off_removes_only_snippet_entries(tmp_path):
    # hooks on → off: exactly the snippet-derived entries go; the agent's own
    # top-level keys AND its own entries under the SAME event stay.
    home = str(tmp_path / "claude")
    materialize(_demo(tmp_path), home)
    settings = _settings(home)
    settings["agentKey"] = "agent's own"
    settings["hooks"]["PreToolUse"].append({"matcher": "AgentAdded", "hooks": []})
    with open(os.path.join(home, "settings.json"), "w") as f:
        json.dump(settings, f)

    info = materialize(_demo(tmp_path, hooks=False), home)
    assert info.hooks_merged is False
    settings = _settings(home)
    assert settings["agentKey"] == "agent's own"
    assert settings["hooks"]["PreToolUse"] == [{"matcher": "AgentAdded", "hooks": []}]


def test_hooks_off_drops_emptied_event_key(tmp_path):
    # When the snippet entry was the ONLY one under its event, the event key
    # itself is dropped rather than left as an empty list.
    home = str(tmp_path / "claude")
    materialize(_demo(tmp_path), home)
    materialize(_demo(tmp_path, hooks=False), home)
    assert "PreToolUse" not in _settings(home)["hooks"]


def test_snippet_change_swaps_entries(tmp_path):
    # Snippet content changed between runs: last run's entries are removed
    # (by value, from the manifest) and the new ones merged — no leftovers.
    home = str(tmp_path / "claude")
    spec = _demo(tmp_path)
    materialize(spec, home)
    (tmp_path / "agents" / "assets" / "hooks.snippet.json").write_text(json.dumps(
        {"hooks": {"PreToolUse": [{"matcher": "V2", "hooks": []}]}}))

    materialize(spec, home)
    assert _settings(home)["hooks"]["PreToolUse"] == [{"matcher": "V2", "hooks": []}]


def test_missing_manifest_is_add_only(tmp_path):
    # First run / pre-feature home: no manifest → nothing is ever deleted,
    # whatever already sits in skills/ or settings.json.
    home = tmp_path / "claude"
    stray = home / "skills" / "pre-existing"
    stray.mkdir(parents=True)
    (stray / "SKILL.md").write_text("was here first\n")

    info = materialize(_demo(tmp_path), str(home))
    assert info.warnings == []
    assert (stray / "SKILL.md").exists()
    assert (home / "skills" / "demo-skill" / "SKILL.md").exists()


def test_corrupt_manifest_is_add_only_with_warning(tmp_path):
    home = tmp_path / "claude"
    home.mkdir()
    (home / ".loadout-manifest.json").write_text("{not json")
    stray = home / "skills" / "pre-existing"
    stray.mkdir(parents=True)

    info = materialize(_demo(tmp_path), str(home))
    assert any("manifest" in w for w in info.warnings)
    assert stray.exists()  # corrupt bookkeeping must never turn into deletions
    assert (home / "skills" / "demo-skill" / "SKILL.md").exists()
    # the manifest is rewritten clean, so the next run reconciles normally
    with open(home / ".loadout-manifest.json") as f:
        assert json.load(f)["skills"] == ["demo-skill"]


def test_reconcile_ignores_path_escapes_in_manifest(tmp_path):
    # A tampered manifest must never become a delete-outside-skills primitive:
    # "." / ".." resolve to skills/ and claude_home themselves, "a/../b" has a
    # separator — all skipped, only bare dir names are deletion candidates.
    home = tmp_path / "claude"
    manual = home / "skills" / "hand-installed"
    manual.mkdir(parents=True)
    (home / "precious.txt").write_text("agent state\n")
    (home / ".loadout-manifest.json").write_text(json.dumps(
        {"skills": ["..", ".", "skills/../precious.txt"], "hooks": {}}))

    materialize(_demo(tmp_path), str(home))
    assert (home / "precious.txt").exists()
    assert manual.exists()
    assert (home / "skills" / "demo-skill" / "SKILL.md").exists()


def test_manifest_garbage_hook_shape_degrades_to_add_only(tmp_path):
    # {"hooks": {"PreToolUse": 5}} is valid JSON but not our shape: the event
    # is dropped at read time (add-only for it), materialize must not crash.
    home = str(tmp_path / "claude")
    materialize(_demo(tmp_path), home)          # settings.json now has hooks
    with open(os.path.join(home, ".loadout-manifest.json"), "w") as f:
        json.dump({"skills": ["demo-skill"], "hooks": {"PreToolUse": 5}}, f)

    info = materialize(_demo(tmp_path, hooks=False), home)
    assert info.hooks_merged is False
    # lost bookkeeping = the old entry is orphaned in settings.json (add-only,
    # same stance as a fully corrupt manifest: leftovers over deletions)
    assert _settings(home)["hooks"]["PreToolUse"] == [{"matcher": "*", "hooks": []}]
