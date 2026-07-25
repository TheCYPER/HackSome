"""Codex runtime adapter (07-07 codex-runtime stage 2, AC2).

argv golden, JSONL parsing against REAL fixtures (tests/fixtures/codex/*.jsonl,
captured live from codex-cli 0.142.5 under ChatGPT-subscription auth on
2026-07-07 — not hand-written), config.toml rendering (env expansion + special
chars, proven valid by tomllib round-trip), auth-seed idempotence, skills via
the neutral loadout core, and the credential/home seams."""

import json
import os
import stat
import tomllib

import pytest

from hacksome.stages.build.agent_runtime.credentials import CodexApiKeyCreds, CodexSubscriptionCreds
from hacksome.stages.build.agent_runtime.runtimes import CodexRuntime
from hacksome.stages.build.agent_runtime.runtimes.base import UNSET, RunRequest
from hacksome.stages.build.agent_runtime.runtimes.codex import DEFAULT_EFFORT, DEFAULT_MODEL
from hacksome.stages.build.agent_runtime.spec import AgentSpec

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fixtures", "codex")


def _fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()


def _argv(**kw):
    return CodexRuntime().build_argv(RunRequest(**kw))


# --- argv golden ----------------------------------------------------------------

def test_argv_first_wake_full():
    """The design §4 first-wake shape, element for element."""
    assert DEFAULT_MODEL == "gpt-5.5"       # user decision, verified live
    assert DEFAULT_EFFORT == "xhigh"
    argv = _argv(prompt="do the thing", charter="BE NICE")
    assert argv == [
        "codex", "exec", "do the thing", "--json", "--skip-git-repo-check",
        "-c", 'developer_instructions="BE NICE"',
        "-m", "gpt-5.5",
        "-c", 'model_reasoning_effort="xhigh"',
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-bypass-hook-trust",
    ]


def test_argv_resume_prepends_the_thread_token():
    argv = _argv(prompt="hi", resume_token="T-1")
    assert argv[:5] == ["codex", "exec", "resume", "T-1", "hi"]
    assert "--json" in argv and "--skip-git-repo-check" in argv
    assert "--dangerously-bypass-approvals-and-sandbox" in argv


def test_argv_session_hint_is_ignored():
    """codex cannot pre-set a thread id (upstream open issue) — a hint must
    change NOTHING; the authoritative token only comes back via
    thread.started."""
    assert _argv(prompt="hi", session_hint="HINT-1") == _argv(prompt="hi")
    assert "HINT-1" not in _argv(prompt="hi", session_hint="HINT-1")


def test_argv_resume_wins_over_session_hint():
    argv = _argv(prompt="hi", resume_token="T-1", session_hint="HINT-1")
    assert argv[2:4] == ["resume", "T-1"]
    assert "HINT-1" not in argv


def test_argv_no_charter_omits_developer_instructions():
    argv = _argv(prompt="hi")
    assert not any(a.startswith("developer_instructions=") for a in argv)


def test_argv_mcp_config_never_becomes_a_flag():
    """codex has no per-invocation MCP flag — the config rides CODEX_HOME
    (materialize_home), so the request field must leave the argv untouched."""
    argv = _argv(prompt="hi", mcp_config="/some/mcp.json")
    assert argv == _argv(prompt="hi")
    assert "/some/mcp.json" not in argv


def test_argv_no_bypass_when_permission_mode_not_bypass():
    argv = _argv(prompt="hi", bypass_permissions=False)
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv
    assert "--json" in argv
    # the hook-trust flag is NOT gated on the permission mode (07-09
    # codex-hooks): silent hook skipping is orthogonal to sandboxing
    assert "--dangerously-bypass-hook-trust" in argv


def test_argv_hook_trust_flag_is_unconditional():
    """07-09 codex-hooks (design §4): without the flag codex silently skips
    hooks in headless --json — every invocation shape must carry it."""
    for argv in (_argv(prompt="hi"),
                 _argv(prompt="hi", resume_token="T-1"),
                 _argv(prompt="hi", bypass_permissions=False)):
        assert "--dangerously-bypass-hook-trust" in argv


def _effort_of(argv):
    vals = [a for a in argv if a.startswith("model_reasoning_effort=")]
    assert len(vals) <= 1
    return vals[0].split("=", 1)[1] if vals else None


@pytest.mark.parametrize("neutral,codex", [
    ("max", '"xhigh"'),          # the one translated word (codex tops at xhigh)
    ("low", '"low"'),
    ("medium", '"medium"'),
    ("high", '"high"'),
    ("xhigh", '"xhigh"'),
])
def test_argv_effort_translation(neutral, codex):
    assert _effort_of(_argv(prompt="hi", effort=neutral)) == codex


def test_argv_model_effort_unset_none_str_matrix():
    """UNSET → adapter defaults; None → flag omitted (account/CLI default);
    str → pass-through. Same three-way semantics as the claude adapter."""
    unset = _argv(prompt="hi", model=UNSET, effort=UNSET)
    assert unset[unset.index("-m") + 1] == DEFAULT_MODEL
    assert _effort_of(unset) == f'"{DEFAULT_EFFORT}"'

    omitted = _argv(prompt="hi", model=None, effort=None)
    assert "-m" not in omitted
    assert _effort_of(omitted) is None

    pinned = _argv(prompt="hi", model="gpt-5.5-codex", effort="medium")
    assert pinned[pinned.index("-m") + 1] == "gpt-5.5-codex"
    assert _effort_of(pinned) == '"medium"'


def test_argv_charter_is_always_a_valid_toml_value():
    """-c values are TOML-parsed by codex; the adapter must emit a valid TOML
    basic string for ANY charter (newlines, quotes, backslashes, CJK)."""
    charter = 'line1 "quoted"\nline2 \\backslash\t中文 charter'
    argv = _argv(prompt="hi", charter=charter)
    elem = argv[argv.index("-c") + 1]
    assert elem.startswith("developer_instructions=")
    assert tomllib.loads(elem) == {"developer_instructions": charter}


# --- parse_output: real fixtures ---------------------------------------------------

FIRST_THREAD = "019f3abf-4579-74e3-9779-6a9c0ccaf324"


def test_parse_first_wake_fixture():
    raw = _fixture("exec_first_wake.jsonl")
    # the fixture really does carry a NON-FATAL error item (skills budget
    # notice) — the regression value of this test depends on it
    assert '"type":"error"' in raw
    res = CodexRuntime().parse_output(raw, 0)
    assert res.ok is True and res.error is None
    assert res.text == "FIXTURE_OK"
    assert res.session_token == FIRST_THREAD
    assert res.cost_usd is None               # codex has no dollar field
    # usage passes through natively, incl. reasoning_output_tokens
    assert res.usage == {"input_tokens": 17070, "cached_input_tokens": 4992,
                         "output_tokens": 169, "reasoning_output_tokens": 160}
    assert '"turn.completed"' in res.raw_tail


def test_parse_resume_fixture_reemits_the_same_thread_id():
    """`exec resume` re-emits thread.started with the SAME id (verified live)
    → one uniform token source for both branches."""
    res = CodexRuntime().parse_output(_fixture("exec_resume.jsonl"), 0)
    assert res.ok is True
    assert res.session_token == FIRST_THREAD   # same thread as the first wake
    assert res.text == "fixture-bot"
    assert res.usage["reasoning_output_tokens"] == 193


def test_parse_bad_model_fixture_fails_with_the_api_message():
    res = CodexRuntime().parse_output(_fixture("exec_bad_model.jsonl"), 1)
    assert res.ok is False
    assert ("The 'nonexistent-model-xyz' model is not supported when using "
            "Codex with a ChatGPT account") in res.error
    # the process got past thread.started → the (failed) thread exists on disk
    # and stays resumable, so the token IS returned
    assert res.session_token == "019f3abf-e32e-7cf1-8e60-8fcabf23094b"
    assert res.text == "" and res.usage is None
    assert '"turn.failed"' in res.raw_tail


def test_parse_falls_back_to_the_top_level_error_event():
    """Derived from the real capture: without the final turn.failed line the
    top-level {"type":"error"} event must still carry the failure."""
    lines = [
        line
        for line in _fixture("exec_bad_model.jsonl").splitlines()
        if '"turn.failed"' not in line
    ]
    res = CodexRuntime().parse_output("\n".join(lines), 1)
    assert res.ok is False
    assert "not supported when using Codex with a ChatGPT account" in res.error


def test_parse_error_items_alone_never_fail_a_turn():
    """item.type=="error" can be a mere warning — only turn.failed / top-level
    error / a missing turn.completed may flip ok (fixture-verified rule)."""
    lines = [
        line
        for line in _fixture("exec_first_wake.jsonl").splitlines()
        if '"agent_message"' not in line
    ]
    res = CodexRuntime().parse_output("\n".join(lines), 0)
    assert res.ok is True and res.error is None   # error item still present
    assert res.text == ""                          # no agent_message survived


def test_parse_empty_stdout_is_the_crash_edge():
    """Death before thread.started → session_token=None: the caller must not
    overwrite its session file, next wake opens a fresh session (design §4)."""
    res = CodexRuntime().parse_output("", 1)
    assert res.ok is False
    assert res.session_token is None
    assert "no turn.completed" in res.error and "rc=1" in res.error


def test_parse_ignores_garbage_lines():
    raw = "not json\n\n" + _fixture("exec_first_wake.jsonl") + "[1,2]\n"
    res = CodexRuntime().parse_output(raw, 0)
    assert res.ok is True and res.text == "FIXTURE_OK"


# --- materialize_home ---------------------------------------------------------------

@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated materialization world: fake $HOME (skills land under
    ~/.agents/skills) + a default auth seed that does NOT exist."""
    monkeypatch.setenv("HOME", str(tmp_path / "userhome"))
    monkeypatch.setenv("CODEX_AUTH_SEED", str(tmp_path / "no-seed.json"))
    return tmp_path


def _spec(tmp_path, *, mcp: dict | None = None, skills: dict | None = None,
          hooks: dict | str | None = None):
    """AgentSpec whose mcp json / skill dirs / hooks snippet live under
    tmp_path. `hooks` (07-09 codex-hooks): a dict is written as the snippet
    json; a raw str is written VERBATIM (the corrupt-snippet case)."""
    base = tmp_path / "agents"
    base.mkdir(exist_ok=True)
    mcp_path = None
    if mcp is not None:
        mcp_path = base / "mcp.json"
        mcp_path.write_text(json.dumps(mcp))
    hooks_rel = None
    if hooks is not None:
        (base / "hooks.snippet.json").write_text(
            json.dumps(hooks) if isinstance(hooks, dict) else hooks)
        hooks_rel = "hooks.snippet.json"
    skill_rel = []
    for name, text in (skills or {}).items():
        d = base / "skills" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(text)
        skill_rel.append(f"skills/{name}")
    return AgentSpec(name="t", mcp_config=str(mcp_path) if mcp_path else None,
                     skills=skill_rel, hooks=hooks_rel, base_dir=str(base))


def _config(home_root) -> dict:
    with open(os.path.join(home_root, "codex", "config.toml"), "rb") as f:
        return tomllib.load(f)


def test_config_toml_renders_servers_with_env_expansion(home, monkeypatch):
    monkeypatch.setenv("CODEX_T_USER", "alice")
    monkeypatch.delenv("CODEX_T_MISSING", raising=False)
    weird = 'quote " backslash \\ tab\t中文'
    spec = _spec(home, mcp={"mcpServers": {
        "s-one": {
            "command": "run-${CODEX_T_USER}",
            "args": ["--flag", "${CODEX_T_MISSING:-fallback}",
                     "${CODEX_T_USER:-bob}"],
            "env": {"USER_KEY": "${CODEX_T_USER}",
                    "MISSING": "${CODEX_T_MISSING}",
                    "WEIRD": weird},
        },
        "plain": {"command": "noop"},
    }})
    root = str(home / "sessions" / "t")
    info = CodexRuntime().materialize_home(spec, root)

    assert info.home == os.path.join(root, "codex")
    doc = _config(root)     # tomllib round-trip proves the render is valid TOML
    assert doc["mcp_servers"]["s-one"] == {
        "command": "run-alice",                       # ${VAR} from os.environ
        "args": ["--flag", "fallback", "alice"],      # :-default; env beats default
        "env": {"USER_KEY": "alice",
                "MISSING": "",                        # unset, no default → "" + WARN
                "WEIRD": weird},                      # special chars survive
    }
    assert doc["mcp_servers"]["plain"] == {"command": "noop"}
    assert any("CODEX_T_MISSING" in w for w in info.warnings)
    mode = stat.S_IMODE(os.stat(
        os.path.join(root, "codex", "config.toml")).st_mode)
    assert mode == 0o600                              # expanded creds live here


def test_config_toml_off_means_off_and_wipes_previous_servers(home):
    root = str(home / "sessions" / "t")
    CodexRuntime().materialize_home(
        _spec(home, mcp={"mcpServers": {"s": {"command": "x"}}}), root)
    assert "mcp_servers" in _config(root)
    # mcp_config=None → the file is REWRITTEN with no tables, so a previous
    # materialization's servers cannot linger
    CodexRuntime().materialize_home(_spec(home, mcp=None), root)
    assert "mcp_servers" not in _config(root)


def test_config_toml_corrupt_mcp_json_degrades_to_no_servers(home):
    spec = _spec(home, mcp={})
    (home / "agents" / "mcp.json").write_text("{not json")
    root = str(home / "sessions" / "t")
    info = CodexRuntime().materialize_home(spec, root)
    assert "mcp_servers" not in _config(root)
    assert any("unusable" in w for w in info.warnings)   # WARN, never a brick


def test_auth_seed_copied_once_and_never_reclobbered(home, monkeypatch):
    seed = home / "codex-auth.json"
    seed.write_text('{"tokens": "SEED"}')
    monkeypatch.setenv("CODEX_AUTH_SEED", str(seed))
    root = str(home / "sessions" / "t")
    target = os.path.join(root, "codex", "auth.json")

    CodexRuntime().materialize_home(_spec(home, mcp=None), root)
    assert open(target).read() == '{"tokens": "SEED"}'
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600

    # codex refreshes tokens by rewriting the per-role copy — a re-run must
    # NOT clobber the (always newer) existing file with the stale seed
    with open(target, "w") as f:
        f.write('{"tokens": "REFRESHED"}')
    info = CodexRuntime().materialize_home(_spec(home, mcp=None), root)
    assert open(target).read() == '{"tokens": "REFRESHED"}'
    assert not any("auth seed" in w for w in info.warnings)


def test_missing_auth_seed_warns_but_never_bricks(home):
    info = CodexRuntime().materialize_home(
        _spec(home, mcp=None), str(home / "sessions" / "t"))
    assert any("auth seed" in w for w in info.warnings)


def test_skills_land_in_the_user_level_agents_dir_and_reconcile(home):
    """Skills go to ~/.agents/skills (home_root-independent — where codex
    discovers user skills), via the neutral core: the manifest (kept in
    CODEX_HOME) removes only what the loadout itself put there."""
    root = str(home / "sessions" / "t")
    skills_root = home / "userhome" / ".agents" / "skills"

    info = CodexRuntime().materialize_home(
        _spec(home, mcp=None, skills={"demo-skill": "say hi\n"}), root)
    assert info.skills == ["demo-skill"]
    assert (skills_root / "demo-skill" / "SKILL.md").read_text() == "say hi\n"

    # an agent-installed skill is NOT in the manifest → never touched
    (skills_root / "self-made").mkdir()
    (skills_root / "self-made" / "SKILL.md").write_text("mine\n")

    info = CodexRuntime().materialize_home(_spec(home, mcp=None), root)
    assert info.skills == []
    assert not (skills_root / "demo-skill").exists()   # reconciled away
    assert (skills_root / "self-made" / "SKILL.md").exists()


# --- hooks reconcile (07-09 codex-hooks) ----------------------------------------------

# The real record-hook snippet's shape (event → matcher group → handlers) —
# codex hooks.json is isomorphic to claude's settings.json `hooks` key.
SNIPPET = {"hooks": {"Stop": [{"hooks": [
    {"type": "command", "command": "python3 /opt/hook.py", "timeout": 30}]}]}}


def _hooks_json(home_root) -> dict:
    with open(os.path.join(home_root, "codex", "hooks.json")) as f:
        return json.load(f)


def _manifest(home_root) -> dict:
    with open(os.path.join(home_root, "codex", ".loadout-manifest.json")) as f:
        return json.load(f)


def test_hooks_snippet_lands_in_hooks_json_and_manifest(home):
    """Declared hooks are merged into CODEX_HOME/hooks.json AND recorded in
    the manifest's hooks slot (the undo bookkeeping reconcile needs)."""
    root = str(home / "sessions" / "t")
    CodexRuntime().materialize_home(_spec(home, hooks=SNIPPET), root)
    assert _hooks_json(root)["hooks"] == SNIPPET["hooks"]
    assert _manifest(root)["hooks"] == SNIPPET["hooks"]


def test_hooks_materialize_twice_is_idempotent(home):
    root = str(home / "sessions" / "t")
    spec = _spec(home, hooks=SNIPPET)
    CodexRuntime().materialize_home(spec, root)
    info = CodexRuntime().materialize_home(spec, root)   # must not duplicate
    assert _hooks_json(root)["hooks"] == SNIPPET["hooks"]
    assert len(_hooks_json(root)["hooks"]["Stop"]) == 1
    # a clean re-run never hook-warns (the fixture's missing auth seed does)
    assert not any("hooks.json not reconciled" in w for w in info.warnings)


def test_no_hooks_declared_creates_no_hooks_json(home):
    """A hookless role (the verifier) must not grow a hooks.json — its lack
    of record enforcement is a design decision, not an accident."""
    root = str(home / "sessions" / "t")
    CodexRuntime().materialize_home(_spec(home), root)
    assert not os.path.exists(os.path.join(root, "codex", "hooks.json"))
    assert _manifest(root)["hooks"] == {}


def test_hooks_undeclared_removes_only_loadout_entries(home):
    """hooks on → off: exactly the snippet-derived entries go; the agent's own
    top-level keys AND its own entries under the SAME event stay (same
    contract as the claude settings.json reconcile)."""
    root = str(home / "sessions" / "t")
    CodexRuntime().materialize_home(_spec(home, hooks=SNIPPET), root)
    doc = _hooks_json(root)
    agent_entry = {"hooks": [{"type": "command", "command": "agent's own"}]}
    doc["hooks"]["Stop"].append(agent_entry)
    doc["agentKey"] = "agent's own"
    with open(os.path.join(root, "codex", "hooks.json"), "w") as f:
        json.dump(doc, f)

    CodexRuntime().materialize_home(_spec(home), root)   # hooks undeclared
    doc = _hooks_json(root)
    assert doc["agentKey"] == "agent's own"
    assert doc["hooks"]["Stop"] == [agent_entry]
    assert _manifest(root)["hooks"] == {}


def test_hooks_undeclared_drops_emptied_event_key(home):
    root = str(home / "sessions" / "t")
    CodexRuntime().materialize_home(_spec(home, hooks=SNIPPET), root)
    CodexRuntime().materialize_home(_spec(home), root)
    assert "Stop" not in _hooks_json(root)["hooks"]


def test_corrupt_snippet_warns_and_other_carriers_survive(home):
    """never-brick: a broken snippet degrades to WARN + no hooks while the
    config render and the skills copy proceed untouched."""
    root = str(home / "sessions" / "t")
    spec = _spec(home, mcp={"mcpServers": {"s": {"command": "x"}}},
                 skills={"demo-skill": "say hi\n"}, hooks="{not json")
    info = CodexRuntime().materialize_home(spec, root)
    assert any("hooks.json not reconciled" in w for w in info.warnings)
    assert not os.path.exists(os.path.join(root, "codex", "hooks.json"))
    assert "mcp_servers" in _config(root)                # config still rendered
    assert info.skills == ["demo-skill"]                 # skills still copied


def test_corrupt_snippet_preserves_previous_manifest_record(home):
    """A failed reconcile must keep the PREVIOUS hooks record in the manifest
    (writing {} would orphan the earlier merge — a later healthy run could
    never undo it)."""
    root = str(home / "sessions" / "t")
    CodexRuntime().materialize_home(_spec(home, hooks=SNIPPET), root)
    CodexRuntime().materialize_home(_spec(home, hooks="{not json"), root)
    assert _manifest(root)["hooks"] == SNIPPET["hooks"]  # record survives
    # the later healthy run (hooks off) can therefore still undo the merge
    CodexRuntime().materialize_home(_spec(home), root)
    assert "Stop" not in _hooks_json(root)["hooks"]
    assert _manifest(root)["hooks"] == {}


def test_snippet_change_swaps_entries(home):
    """Snippet content changed between runs (e.g. a new timeout value): last
    run's entries are removed by value from the manifest record, the new ones
    merged — no leftovers, no duplicates."""
    root = str(home / "sessions" / "t")
    CodexRuntime().materialize_home(_spec(home, hooks=SNIPPET), root)
    v2 = {"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "python3 /opt/hook.py", "timeout": 60}]}]}}
    CodexRuntime().materialize_home(_spec(home, hooks=v2), root)
    assert _hooks_json(root)["hooks"] == v2["hooks"]
    assert _manifest(root)["hooks"] == v2["hooks"]


# --- home_env / credential_kinds -----------------------------------------------------

def test_home_env_nests_codex_home_under_the_role_mount():
    assert CodexRuntime().home_env("/sessions/ceo") == {
        "CODEX_HOME": "/sessions/ceo/codex"}


def test_credential_kinds_map_matches_the_yaml_vocabulary():
    assert CodexRuntime().credential_kinds() == {
        "subscription": CodexSubscriptionCreds, "api-key": CodexApiKeyCreds}
