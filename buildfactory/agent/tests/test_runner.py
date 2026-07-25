"""stream-json parsing (AG5 / AC5), pinned to spike S1 real fields.

parse_stream_json moved from runner.py into the claude adapter (07-07
codex-runtime) — same contract, tested here against the same fixtures."""

import subprocess

from agent.runner import run_task
from agent.runtimes.claude_code import parse_stream_json
from agent.spec import AgentSpec

# Spike S1: real NDJSON event sequence (system/init → assistant → rate_limit → result).
S1_SUCCESS = "\n".join([
    '{"type":"system","subtype":"init","apiKeySource":"none","model":"claude-sonnet-4-6"}',
    '{"type":"assistant","message":{"content":[{"type":"text","text":"Hi!"}]}}',
    '{"type":"rate_limit_event"}',
    '{"type":"result","subtype":"success","is_error":false,'
    '"result":"Hi! How can I help you today?","total_cost_usd":0.0417612,'
    '"num_turns":1,"stop_reason":"end_turn","duration_ms":6935,"api_error_status":null}',
])

# Spike trap: 401 still reports subtype=="success" — ONLY is_error reflects failure.
S1_401_TRAP = (
    '{"type":"system","subtype":"init"}\n'
    '{"type":"result","subtype":"success","is_error":true,'
    '"result":"Invalid API key · Fix external API key",'
    '"total_cost_usd":0,"api_error_status":401}'
)

# is_error true but api_error_status null → error falls back to result text.
ERROR_NO_STATUS = '{"type":"result","subtype":"success","is_error":true,"result":"boom","api_error_status":null}'


def test_parse_success():
    res = parse_stream_json(S1_SUCCESS)
    assert res.ok is True
    assert res.text == "Hi! How can I help you today?"
    assert res.cost_usd == 0.0417612
    assert res.error is None
    assert '"type":"result"' in res.raw_tail


def test_parse_401_trap_uses_is_error_not_subtype():
    """Pins the trap: subtype=='success' but is_error true → ok must be False."""
    res = parse_stream_json(S1_401_TRAP)
    assert res.ok is False
    assert res.error == "401"
    assert res.text == "Invalid API key · Fix external API key"


def test_parse_error_without_api_status_falls_back_to_text():
    res = parse_stream_json(ERROR_NO_STATUS)
    assert res.ok is False
    assert res.error == "boom"


def test_parse_no_result_event():
    res = parse_stream_json('{"type":"system","subtype":"init"}\n{"type":"assistant"}')
    assert res.ok is False
    assert "no result event" in res.error


def test_parse_takes_last_result_event():
    stdout = (
        '{"type":"result","subtype":"success","is_error":true,"result":"first","api_error_status":500}\n'
        '{"type":"result","subtype":"success","is_error":false,"result":"second","total_cost_usd":0.01,"api_error_status":null}'
    )
    res = parse_stream_json(stdout)
    assert res.ok is True
    assert res.text == "second"


def test_run_task_creates_fresh_session_and_injects_goal_context(monkeypatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            cmd, 0,
            stdout='{"type":"result","is_error":false,"result":"ok","total_cost_usd":0}',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    spec = AgentSpec(name="t", credentials="subscription",
                     mcp_config="/opt/foundagent/mcp.json", permission_mode="bypass")
    res = run_task(
        spec, "task", container="c1", extra_env={"GOAL_ID": "goal-1"}
    )
    assert res.ok is True
    cmd = captured["cmd"]
    assert "--session-id" in cmd[-1]
    assert "GOAL_ID=goal-1" in cmd


def test_run_task_wires_resume_token_instead_of_new_session_hint(monkeypatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            cmd, 0,
            stdout='{"type":"result","is_error":false,"result":"ok","total_cost_usd":0}',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    spec = AgentSpec(name="t", credentials="subscription", mcp_config=None)

    run_task(
        spec,
        "continue the same Goal",
        container="worker-1",
        resume_token="existing-session",
    )

    argv = captured["cmd"][-1]
    assert "--resume existing-session" in argv
    assert "--session-id" not in argv


def test_run_task_injects_runtime_home_env(monkeypatch):
    """The docker exec must point the CLI at the materialized loadout: codex
    gets CODEX_HOME=<mount>/codex (it would otherwise read ~/.codex and miss
    the rendered config.toml/auth.json entirely); claude gets its (default,
    but explicit) CLAUDE_CONFIG_DIR=<mount>."""
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    codex_spec = AgentSpec(name="t", provider="codex", credentials="api-key",
                           mcp_config="/opt/foundagent/mcp.json")
    run_task(codex_spec, "task", container="c1")
    assert "CODEX_HOME=/home/kasm-user/.claude/codex" in captured["cmd"]

    claude_spec = AgentSpec(name="t", credentials="subscription",
                            mcp_config="/opt/foundagent/mcp.json")
    run_task(claude_spec, "task", container="c1")
    assert "CLAUDE_CONFIG_DIR=/home/kasm-user/.claude" in captured["cmd"]


def test_run_task_extra_env_cannot_override_credentials(monkeypatch):
    """extra_env must not be able to smuggle a credential var (mutual exclusion)."""
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            cmd, 0,
            stdout='{"type":"result","is_error":false,"result":"ok","total_cost_usd":0}',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    spec = AgentSpec(name="t", credentials="subscription",
                     mcp_config="/opt/foundagent/mcp.json", permission_mode="bypass")
    run_task(spec, "task", container="c1",
             extra_env={"ANTHROPIC_API_KEY": "leak", "GOAL_ID": "goal-1"})
    cmd = captured["cmd"]
    assert "ANTHROPIC_API_KEY=leak" not in cmd
    assert "GOAL_ID=goal-1" in cmd


def test_timeout_preserves_partial_codex_session_for_safe_resume(monkeypatch):
    partial = (
        b'{"type":"thread.started","thread_id":"thread-timeout"}\n'
        b'{"type":"turn.started"}\n'
    )

    def fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(
            cmd,
            kw["timeout"],
            output=partial,
            stderr=b"still running",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    spec = AgentSpec(
        name="t",
        provider="codex",
        credentials="subscription",
        mcp_config=None,
    )

    result = run_task(spec, "long turn", container="worker-1", timeout=1)

    assert result.ok is False
    assert result.error == "timeout"
    assert result.timed_out is True
    assert result.session_token == "thread-timeout"
    assert "thread.started" in result.raw_output
    assert result.stderr == "still running"
