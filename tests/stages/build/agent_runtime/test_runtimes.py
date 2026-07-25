"""Runtime abstraction (07-07 codex-runtime): base contract semantics, the
runtime_for factory, and the merged ClaudeCodeRuntime adapter. Absorbs the old
test_provider.py (ClaudeCodeProvider.build_exec) and the argv tests that lived
in orchestration/tests/test_{agent,ceo}_loop.py (build_claude_argv) — the two
legacy builders are now one adapter, so their assertions converge here.
"""

import uuid

import pytest

from hacksome.stages.build.agent_runtime.credentials import ApiKeyCreds, SubscriptionCreds
from hacksome.stages.build.agent_runtime.runtimes import (
    ClaudeCodeRuntime,
    CodexRuntime,
    OpenCodeRuntime,
    runtime_for,
)
from hacksome.stages.build.agent_runtime.runtimes.base import UNSET, RunRequest, RunResult, UnsetType
from hacksome.stages.build.agent_runtime.runtimes.claude_code import DEFAULT_EFFORT, DEFAULT_MODEL
from hacksome.stages.build.agent_runtime.spec import AgentSpec


# --- base.py: UNSET vs None vs str -------------------------------------------

def test_unset_is_a_falsy_singleton_distinct_from_none():
    assert UnsetType() is UNSET            # singleton → `is UNSET` always works
    assert UNSET is not None
    assert repr(UNSET) == "UNSET"
    # falsy: a missed `is UNSET` check degrades to "omit the flag", never to
    # leaking the sentinel repr onto a CLI argv
    assert not UNSET


def test_run_request_defaults():
    req = RunRequest(prompt="hi")
    assert req.model is UNSET and req.effort is UNSET
    assert req.charter is None and req.mcp_config is None
    assert req.resume_token is None and req.session_hint is None
    assert req.bypass_permissions is True
    assert req.workdir is None


def test_run_result_optional_fields_default():
    res = RunResult(ok=True, text="t", error=None)
    assert res.session_token is None and res.cost_usd is None
    assert res.usage is None and res.raw_tail == ""


# --- runtime_for factory ------------------------------------------------------

def test_runtime_for_claude_returns_fresh_instances():
    spec = AgentSpec(name="x", provider="claude-code")
    rt = runtime_for(spec)
    assert isinstance(rt, ClaudeCodeRuntime)
    # fresh instance per call — the adapter is stateful per run (session token)
    assert runtime_for(spec) is not rt


def test_runtime_for_codex_stub_and_unknown():
    # codex is a REAL adapter since stage 2 (semantics in test_codex_runtime.py)
    assert isinstance(runtime_for(AgentSpec(name="x", provider="codex")), CodexRuntime)
    # stubs fail AT THE FACTORY (not at first method call) so caller degrade
    # paths can catch them — same message the old seam raised at build time
    with pytest.raises(NotImplementedError, match="provider 'opencode' not implemented"):
        runtime_for(AgentSpec(name="x", provider="opencode"))
    with pytest.raises(ValueError, match="unknown provider: 'bogus'"):
        runtime_for(AgentSpec(name="x", provider="bogus"))


def test_opencode_stub_raises():
    with pytest.raises(NotImplementedError, match="provider 'opencode' not implemented; seam only"):
        OpenCodeRuntime().build_argv(RunRequest(prompt="task"))


# --- ClaudeCodeRuntime argv (merged builder; golden lock in
# test_claude_runtime_golden.py, targeted semantics here) -----------------------

def _argv(**kw):
    return ClaudeCodeRuntime().build_argv(RunRequest(**kw))


def test_argv_full():
    argv = _argv(prompt="do the thing", charter="BE NICE",
                 mcp_config="/opt/foundagent/mcp.json")
    assert argv[:3] == ["claude", "-p", "do the thing"]
    assert argv[argv.index("--mcp-config") + 1] == "/opt/foundagent/mcp.json"
    assert argv[argv.index("--append-system-prompt") + 1] == "BE NICE"
    assert "--verbose" in argv and "stream-json" in argv
    assert "--dangerously-skip-permissions" in argv


def test_argv_new_session_uses_session_id_flag():
    argv = _argv(prompt="hi", session_hint="S1")
    assert argv[:3] == ["claude", "-p", "hi"]
    assert "--session-id" in argv and "S1" in argv
    assert "--resume" not in argv
    assert "--dangerously-skip-permissions" in argv


def test_argv_resume_uses_resume_flag():
    argv = _argv(prompt="hi", resume_token="S1")
    assert "--resume" in argv and "S1" in argv
    assert "--session-id" not in argv


def test_argv_resume_takes_precedence_over_session_hint():
    argv = _argv(prompt="hi", resume_token="R", session_hint="N")
    assert "--resume" in argv and "R" in argv
    assert "--session-id" not in argv and "N" not in argv


def test_argv_charter_appended_and_omitted():
    argv = _argv(prompt="hi", resume_token="S1", charter="BE THE CEO")
    assert argv[argv.index("--append-system-prompt") + 1] == "BE THE CEO"
    assert "--append-system-prompt" not in _argv(prompt="hi", resume_token="S1")


def test_argv_no_bypass_when_permission_mode_not_bypass():
    argv = _argv(prompt="task", bypass_permissions=False)
    assert "--dangerously-skip-permissions" not in argv
    assert "stream-json" in argv


def test_argv_strict_mcp_config_is_unconditional():
    """--strict-mcp-config rides EVERY run (07-03 mcp-loadout): with a config
    only our file loads; with none (overlay `mcp: off`) claude must not pick up
    ~/.claude.json or a workdir .mcp.json — off means OFF."""
    assert "--strict-mcp-config" in _argv(prompt="hi", resume_token="S1",
                                          mcp_config="/m.json")
    bare = _argv(prompt="hi", resume_token="S1")          # mcp_config=None
    assert "--strict-mcp-config" in bare
    assert "--mcp-config" not in bare


def test_argv_default_model_effort_when_unset():
    """No yaml key → adapter fleet defaults ride every argv (07-03
    model-effort-config; constants moved into the adapter, design §3)."""
    argv = _argv(prompt="task")            # model/effort default to UNSET
    assert DEFAULT_MODEL == "claude-opus-4-8"
    assert DEFAULT_EFFORT == "xhigh"
    assert argv[argv.index("--model") + 1] == "claude-opus-4-8"
    assert argv[argv.index("--effort") + 1] == "xhigh"


def test_argv_model_effort_override_and_null_optout():
    argv = _argv(prompt="task", model="claude-sonnet-4-6", effort="low")
    assert argv[argv.index("--model") + 1] == "claude-sonnet-4-6"
    assert argv[argv.index("--effort") + 1] == "low"
    # explicit `model: null` / `effort: null` in the yaml → flag omitted
    argv2 = _argv(prompt="task", model=None, effort=None)
    assert "--model" not in argv2
    assert "--effort" not in argv2


# --- ClaudeCodeRuntime parse_output: session-token echo ------------------------

RESULT_OK = '{"type":"result","is_error":false,"result":"done","total_cost_usd":0.01}'


def test_parse_output_echoes_the_preset_session_token():
    rt = ClaudeCodeRuntime()
    argv = rt.build_argv(RunRequest(prompt="hi", session_hint="SID-H"))
    assert argv[argv.index("--session-id") + 1] == "SID-H"
    res = rt.parse_output(RESULT_OK, 0)
    assert res.ok is True and res.text == "done"
    assert res.session_token == "SID-H"


def test_parse_output_echoes_resume_token_and_minted_uuid():
    rt = ClaudeCodeRuntime()
    rt.build_argv(RunRequest(prompt="hi", resume_token="SID-R"))
    assert rt.parse_output(RESULT_OK, 0).session_token == "SID-R"
    rt2 = ClaudeCodeRuntime()
    argv = rt2.build_argv(RunRequest(prompt="hi"))
    minted = argv[argv.index("--session-id") + 1]
    assert uuid.UUID(minted).version == 4
    assert rt2.parse_output(RESULT_OK, 0).session_token == minted


def test_parse_output_returns_token_even_on_error_result():
    """The old resident loop persisted the sid regardless of the turn's exit —
    the on-disk session usually exists once the process ran; keep that."""
    rt = ClaudeCodeRuntime()
    rt.build_argv(RunRequest(prompt="hi", session_hint="SID-E"))
    res = rt.parse_output('{"type":"result","is_error":true,"result":"boom"}', 1)
    assert res.ok is False and res.session_token == "SID-E"


# --- home_env / credential_kinds ----------------------------------------------

def test_home_env_points_claude_config_dir_at_home_root():
    # CLAUDE_CODE_DISABLE_AUTO_MEMORY (issue #207): the ephemeral Worker path's
    # injection point for the fleet-wide auto-memory kill (residents get it
    # from the compose x-agent-env anchor).
    assert ClaudeCodeRuntime().home_env("/sessions/ceo") == {
        "CLAUDE_CONFIG_DIR": "/sessions/ceo",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}


def test_credential_kinds_map_matches_the_yaml_vocabulary():
    kinds = ClaudeCodeRuntime().credential_kinds()
    assert kinds == {"subscription": SubscriptionCreds, "api-key": ApiKeyCreds}
