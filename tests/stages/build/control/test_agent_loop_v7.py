import inspect
import subprocess

import pytest

import hacksome.stages.build.control.agent_loop as agent_loop
import hacksome.stages.build.control.lead_loop as lead_loop
from hacksome.stages.build import AGENTS_ROOT
from hacksome.stages.build.control.agent_loop import WakeOutcome, build_v7_wake_prompt
from hacksome.stages.build.control.run_logs import RunLogRecorder


class StopLoop(BaseException):
    pass


class ReliableInbox:
    def __init__(self, events):
        self.events = list(events)
        self.cursor = 0
        self.acks = []
        self.waits = 0

    def peek_one(self, key):
        if self.cursor >= len(self.events):
            return None
        return self.events[self.cursor]

    def ack_one(self, key):
        event = self.events[self.cursor]
        self.acks.append(event["id"])
        self.cursor += 1

    def wait(self, key, timeout):
        self.waits += 1
        return self.peek_one(key) is not None


def _event(number):
    return {
        "id": f"message-{number}",
        "time": "2026-07-14T00:00:00Z",
        "to": "researcher",
        "text": f"message {number}",
        "body": {"v": 1, "type": "department_message", "data": {"body": str(number)}},
    }


def test_v7_prompt_has_fixed_layers_and_exactly_one_message():
    prompt = build_v7_wake_prompt(
        _event(1),
        actor_id="researcher",
        wake_id="wake-1",
        trigger="event",
        objective="Own evidence quality",
        notes="Follow up source A",
        capabilities=("create_goal", "send_department_message", "write_notes"),
        now="2026-07-14T00:00:00Z",
    )

    headings = [
        "WAKE CONTEXT",
        "COMPANY ENTRY",
        "CURRENT OBJECTIVE",
        "OBJECTIVE REVIEWS IN FLIGHT",
        "NOTES",
        "CAPABILITIES",
        "TRIGGER",
        "COMPLETION CONTRACT",
    ]
    positions = [prompt.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "message 1" in prompt
    assert "message 2" not in prompt
    assert "native folder /company" in prompt
    assert "shallow listing" in prompt
    assert "/company/MAP.md" not in prompt
    assert "/shared/ledger" not in prompt


def test_v7_prompt_surfaces_pending_objective_without_exposing_review_store():
    prompt = build_v7_wake_prompt(
        None,
        actor_id="ceo",
        wake_id="wake-pending",
        trigger="heartbeat",
        objective=None,
        notes=None,
        capabilities=("propose_company_objective",),
        now="2026-07-14T00:00:00Z",
        objective_reviews_in_flight=[
            {
                "proposal_id": "objective-1",
                "review_id": "review-1",
                "actor_id": "ceo",
                "objective_kind": "company",
                "revision": 1,
                "text": "Serve one concrete buyer.",
                "status": "reviewing",
            }
        ],
        strategic=True,
    )

    assert "Serve one concrete buyer." in prompt
    assert "do not duplicate it" in prompt
    assert "/reviews" not in prompt


def test_reliable_loop_retries_same_message_and_only_acks_success(
    tmp_path, monkeypatch
):
    inbox = ReliableInbox([_event(1), _event(2)])
    prompts = []
    outcomes = [
        WakeOutcome(None, False, "runtime failed"),
        WakeOutcome("session-1", True),
        WakeOutcome("session-2", True),
    ]

    def fake_wake(session_id, prompt, **kwargs):
        prompts.append(prompt)
        return outcomes.pop(0)

    completed = []

    def on_completed(event):
        completed.append(event)
        if len(completed) == 2:
            raise StopLoop

    monkeypatch.setattr(agent_loop, "wake", fake_wake)
    monkeypatch.setattr(agent_loop.time, "sleep", lambda _: None)

    with pytest.raises(StopLoop):
        agent_loop.agent_loop(
            key="researcher",
            session_file=tmp_path / "session",
            heartbeat=900,
            inbox=inbox,
            retry_backoff=0,
            wake_completed=on_completed,
            context_loader=lambda: {
                "objective": "Own evidence quality",
                "objective_reviews_in_flight": [],
                "notes": None,
                "capabilities": ["create_goal"],
            },
        )

    assert inbox.acks == ["message-1", "message-2"]
    assert "message 1" in prompts[0] and "message 1" in prompts[1]
    assert "message 2" not in prompts[0]
    assert "message 2" in prompts[2]


def test_reliable_loop_drains_three_messages_before_waiting_for_heartbeat(
    tmp_path, monkeypatch
):
    inbox = ReliableInbox([_event(1), _event(2), _event(3)])
    completed = []

    monkeypatch.setattr(
        agent_loop,
        "wake",
        lambda *args, **kwargs: WakeOutcome(None, True),
    )

    def on_completed(event):
        completed.append(event["message_id"])
        if len(completed) == 3:
            raise StopLoop

    with pytest.raises(StopLoop):
        agent_loop.agent_loop(
            key="researcher",
            session_file=tmp_path / "session",
            heartbeat=900,
            inbox=inbox,
            wake_completed=on_completed,
            context_loader=lambda: {
                "objective": "Own evidence quality",
                "objective_reviews_in_flight": [],
                "notes": None,
                "capabilities": ["create_goal"],
            },
        )

    assert completed == ["message-1", "message-2", "message-3"]
    assert inbox.waits == 0


def test_remote_completion_owns_ack_and_hub_context_is_injected(tmp_path, monkeypatch):
    inbox = ReliableInbox([_event(1)])
    prompts = []
    completed = []

    def fake_wake(session_id, prompt, **kwargs):
        prompts.append(prompt)
        return WakeOutcome(None, True)

    def complete(details):
        completed.append(details)
        # The real Hub atomically advances its own Inbox here.
        inbox.cursor += 1
        raise StopLoop

    monkeypatch.setattr(agent_loop, "wake", fake_wake)

    with pytest.raises(StopLoop):
        agent_loop.agent_loop(
            key="researcher",
            session_file=tmp_path / "session",
            heartbeat=900,
            inbox=inbox,
            wake_completed=complete,
            completion_owns_ack=True,
            context_loader=lambda: {
                "objective": "Own current evidence",
                "objective_reviews_in_flight": [],
                "notes": "Check source B",
                "capabilities": ["create_goal"],
            },
        )

    assert inbox.acks == []
    assert completed[0]["message_id"] == "message-1"
    assert "Own current evidence" in prompts[0]
    assert "Check source B" in prompts[0]
    assert "create_goal" in prompts[0]


def test_wake_gate_suppresses_model_until_it_allows_wake(tmp_path, monkeypatch):
    inbox = ReliableInbox([])
    gate_results = iter((False, True))
    wake_calls = []

    def fake_wake(*args, **kwargs):
        wake_calls.append(kwargs["trigger"])
        raise StopLoop

    monkeypatch.setattr(agent_loop, "wake", fake_wake)
    monkeypatch.setattr(agent_loop.time, "sleep", lambda _: None)

    with pytest.raises(StopLoop):
        agent_loop.agent_loop(
            key="lead",
            session_file=tmp_path / "session",
            heartbeat=60,
            inbox=inbox,
            context_loader=lambda: {},
            prompt_builder=lambda *_: "lead prompt",
            wake_gate=lambda _event, _context: next(gate_results),
        )

    assert inbox.waits == 2
    assert wake_calls == ["heartbeat"]


def test_custom_prompt_builder_receives_loaded_wake_context(tmp_path, monkeypatch):
    context = {
        "actor_id": "lead",
        "capabilities": ["read_lead_brief"],
        "lead_brief": {"enabled": True, "revision": 0},
    }
    captured = []

    def prompt_builder(event, wake_id, trigger, now, loaded_context):
        captured.append((event, wake_id, trigger, now, loaded_context))
        return "LEAD WAKE"

    def fake_wake(*_args, **_kwargs):
        raise StopLoop

    monkeypatch.setattr(agent_loop, "wake", fake_wake)

    with pytest.raises(StopLoop):
        agent_loop.agent_loop(
            key="lead",
            session_file=tmp_path / "session",
            heartbeat=60,
            inbox=ReliableInbox([]),
            context_loader=lambda: context,
            prompt_builder=prompt_builder,
        )

    assert captured[0][0] is None
    assert captured[0][2] == "heartbeat"
    assert captured[0][4] is context


def test_refresh_wakes_never_read_resume_or_overwrite_existing_session_file(
    tmp_path, monkeypatch
):
    session_file = tmp_path / "session"
    session_file.write_text("historical-lead-token", encoding="utf-8")
    resume_tokens = []
    completions = []

    def fail_load(_path):
        raise AssertionError("refresh mode must not read the session file")

    def fail_save(_path, _token):
        raise AssertionError("refresh mode must not overwrite the session file")

    def fake_wake(session_id, _prompt, **_kwargs):
        resume_tokens.append(session_id)
        return WakeOutcome(f"new-token-{len(resume_tokens)}", True)

    def on_completed(_details):
        completions.append(True)
        if len(completions) == 2:
            raise StopLoop

    monkeypatch.setattr(agent_loop, "load_session", fail_load)
    monkeypatch.setattr(agent_loop, "save_session", fail_save)
    monkeypatch.setattr(agent_loop, "wake", fake_wake)

    with pytest.raises(StopLoop):
        agent_loop.agent_loop(
            key="lead",
            session_file=session_file,
            session_mode="refresh",
            heartbeat=60,
            inbox=ReliableInbox([_event(1), _event(2)]),
            context_loader=lambda: {},
            prompt_builder=lambda *_args: "LEAD WAKE",
            wake_completed=on_completed,
        )

    assert resume_tokens == [None, None]
    assert session_file.read_text(encoding="utf-8") == "historical-lead-token"


@pytest.mark.parametrize("override_text", (None, "OPERATOR OVERRIDE"))
def test_resident_loop_uses_agent_spec_prompt_unless_operator_overrides(
    tmp_path, monkeypatch, override_text
):
    captured = []
    spec_path = AGENTS_ROOT / "lead.yaml"
    monkeypatch.setenv("AGENT_SPEC", str(spec_path))
    *_, assembled_prompt = agent_loop._role_config("lead")
    override_path = None
    if override_text is not None:
        override = tmp_path / "override.md"
        override.write_text(override_text)
        override_path = str(override)

    def fake_wake(_session_id, _prompt, **kwargs):
        captured.append(kwargs["charter"])
        raise StopLoop

    monkeypatch.setattr(agent_loop, "wake", fake_wake)

    with pytest.raises(StopLoop):
        agent_loop.agent_loop(
            key="lead",
            session_file=tmp_path / "session",
            heartbeat=60,
            charter_path=override_path,
            system_prompt=assembled_prompt,
            inbox=ReliableInbox([]),
            context_loader=lambda: {},
            prompt_builder=lambda *_args: "LEAD WAKE",
        )

    expected = override_text or assembled_prompt
    assert captured == [expected]
    if override_text is None:
        assert captured[0].startswith("# Shared Tool-Use Environment")
        assert "# Hackathon Lead" in captured[0]


@pytest.mark.parametrize("override_state", ("missing", "empty"))
def test_resident_loop_invalid_operator_override_falls_back_to_agent_spec_prompt(
    tmp_path, monkeypatch, override_state
):
    captured = []
    spec_path = AGENTS_ROOT / "lead.yaml"
    monkeypatch.setenv("AGENT_SPEC", str(spec_path))
    *_, assembled_prompt = agent_loop._role_config("lead")
    override_path = tmp_path / "override.md"
    if override_state == "empty":
        override_path.write_text("")

    def fake_wake(_session_id, _prompt, **kwargs):
        captured.append(kwargs["charter"])
        raise StopLoop

    monkeypatch.setattr(agent_loop, "wake", fake_wake)

    with pytest.raises(StopLoop):
        agent_loop.agent_loop(
            key="lead",
            session_file=tmp_path / "session",
            heartbeat=60,
            charter_path=str(override_path),
            system_prompt=assembled_prompt,
            inbox=ReliableInbox([]),
            context_loader=lambda: {},
            prompt_builder=lambda *_args: "LEAD WAKE",
        )

    assert captured == [assembled_prompt]
    assert captured[0].startswith("# Shared Tool-Use Environment")
    assert "# Hackathon Lead" in captured[0]


def test_role_config_returns_fully_assembled_lead_prompt(monkeypatch):
    spec_path = AGENTS_ROOT / "lead.yaml"
    monkeypatch.setenv("AGENT_SPEC", str(spec_path))

    *_, session_mode, _idle, _strategic, prompt = agent_loop._role_config("lead")

    assert session_mode == "refresh"
    assert prompt.startswith("# Shared Tool-Use Environment")
    assert "# Hackathon Lead" in prompt
    assert prompt.index("# Shared Tool-Use Environment") < prompt.index(
        "# Hackathon Lead"
    )


def test_lead_main_passes_agent_spec_prompt_to_resident_loop(monkeypatch):
    spec_path = AGENTS_ROOT / "lead.yaml"
    captured = {}
    client = object()
    inbox = object()
    monkeypatch.setenv("AGENT_SPEC", str(spec_path))
    monkeypatch.delenv("AGENT_CHARTER", raising=False)
    monkeypatch.setattr(lead_loop, "HubClient", lambda: client)
    monkeypatch.setattr(
        lead_loop,
        "RemoteInbox",
        lambda actual_client: inbox if actual_client is client else None,
    )
    monkeypatch.setattr(
        lead_loop,
        "agent_loop",
        lambda **kwargs: captured.update(kwargs),
    )

    lead_loop.main()

    assert captured["charter_path"] is None
    assert captured["system_prompt"].startswith("# Shared Tool-Use Environment")
    assert "# Hackathon Lead" in captured["system_prompt"]
    assert captured["inbox"] is inbox


def test_resident_loop_has_no_v6_prompt_or_direct_state_fallbacks():
    assert not hasattr(agent_loop, "build_wake_prompt")
    assert not hasattr(agent_loop, "_read_objective")
    parameters = inspect.signature(agent_loop.agent_loop).parameters
    assert not {
        "objective_path",
        "notes_path",
        "prompt_mode",
        "reliable_inbox",
        "capabilities",
    }.intersection(parameters)
    assert parameters["inbox"].default is inspect.Parameter.empty
    assert parameters["context_loader"].default is inspect.Parameter.empty


def test_structured_wake_outcome_exposes_runtime_failure(monkeypatch):
    monkeypatch.setattr(
        agent_loop.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            stdout='{"type":"result","is_error":true,"result":"bad","api_error_status":500}',
            stderr="full stderr",
        ),
    )

    outcome = agent_loop.wake(
        "session-1",
        "prompt",
        key="researcher",
        return_outcome=True,
    )

    assert isinstance(outcome, WakeOutcome)
    assert outcome.ok is False
    assert outcome.session_id == "session-1"


def test_run_archive_preserves_complete_output_without_tail_truncation(tmp_path):
    recorder = RunLogRecorder(tmp_path / "telemetry" / "runs")
    raw = "\n".join(f'{{"event": {number}}}' for number in range(2000))

    run_dir = recorder.record(
        run_id="wake-1",
        metadata={"agent_id": "ceo", "ok": True},
        raw_output=raw,
        stderr="all stderr",
        model_output="final answer",
        harness_log="harness",
        container_log="container",
    )

    assert (run_dir / "runtime.jsonl").read_text() == raw
    assert (run_dir / "stderr.log").read_text() == "all stderr"
    assert (run_dir / "container.log").read_text() == "container"


def test_resident_archive_records_harness_correlation(tmp_path, monkeypatch):
    root = tmp_path / "telemetry" / "runs"
    root.mkdir(parents=True)
    monkeypatch.setenv("RUN_LOGS_DIR", str(root))

    agent_loop._archive_wake(
        run_id="wake-correlated",
        key="ceo",
        trigger="event",
        started_at="2026-07-14T00:00:00Z",
        session_id="session-1",
        ok=True,
        error=None,
        raw_output="{}\n",
        stderr="",
        model_output="done",
    )

    harness = (root / "wake-correlated" / "harness.log").read_text()
    assert "run_id=wake-correlated" in harness
    assert "agent_id=ceo" in harness
    assert "session_token=session-1" in harness
