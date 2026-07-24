import json

import pytest

import orchestration.email_send as email_send
from orchestration.company_hub import CompanyHub
from orchestration.method_adapter import ActorContext


CEO = ActorContext("ceo", "ceo")
WORKER_MANAGER = ActorContext("manager", "worker-manager")
VERIFIER_MANAGER = ActorContext("manager", "verifier-manager")
PROVISIONER = ActorContext("manager", "department-provisioner")
PERIPHERAL = ActorContext("manager", "peripheral")


@pytest.fixture(autouse=True)
def _company_hub_uses_fixture_catalog(department_specs, monkeypatch):
    company_hub_class = CompanyHub

    def create_hub(*args, **kwargs):
        kwargs.setdefault("department_specs_path", department_specs)
        return company_hub_class(*args, **kwargs)

    monkeypatch.setattr(
        "orchestration.tests.test_company_hub_v7.CompanyHub",
        create_hub,
    )


def _request(method, payload=None, request_id=None):
    return {
        "version": 1,
        "request_id": request_id or f"req-{method}",
        "method": method,
        "payload": payload or {},
    }


def _call(hub, actor, method, payload=None, request_id=None):
    response = hub.call(actor, _request(method, payload, request_id))
    assert response["ok"], response
    return response["result"]


def _verdict(hub, review_id, verdict="PASS", reason="meets the objective"):
    review = hub.reviews.get(review_id)
    actor = ActorContext(
        "verifier",
        review["instance_id"],
        review_id=review_id,
    )
    return _call(
        hub,
        actor,
        "submit_verdict",
        {"verdict": verdict, "reason": reason},
        request_id=f"verdict-{review_id}",
    )


def _activate_company_objective(hub):
    proposal = _call(
        hub,
        CEO,
        "propose_company_objective",
        {"objective": "Build a useful profitable software company."},
        "company-objective-1",
    )
    _verdict(hub, proposal["review_id"])
    return proposal


def _confirm_stopping_verifiers(hub):
    for review in hub.reviews.list_reviews():
        if review.get("instance_state") != "stopping":
            continue
        _call(
            hub,
            VERIFIER_MANAGER,
            "verifier_instance_stopped",
            {
                "review_id": review["id"],
                "instance_id": review["instance_id"],
            },
            request_id=f"confirm-stopped-{review['instance_id']}",
        )


def _create_department(hub, option_id):
    request = _call(
        hub,
        CEO,
        "create_department",
        {
            "option_id": option_id,
            "initial_objective": f"Own proactive {option_id} outcomes.",
        },
        f"create-{option_id}",
    )
    _verdict(hub, request["objective_review_id"])
    department = _call(
        hub,
        PROVISIONER,
        "department_started",
        {"creation_id": request["id"], "service_name": f"department-{option_id}"},
        f"started-{option_id}",
    )
    return ActorContext("department", option_id, department_id=option_id), department


def _append_mail(hub, number, received_at, *, text=None, address="maya@foundagent.net"):
    hub.mail_store.append(
        {
            "id": f"mail-{number}",
            "received_at": float(received_at),
            "address": address,
            "from": "no-reply@example.test",
            "subject": f"Message {number}",
            "text": text or f"verification-{number}",
            "links": [f"https://example.test/{number}"],
            "message_id": f"<message-{number}@example.test>",
            "source_key": f"inbox/{number}.eml",
        }
    )


def test_cold_start_has_zero_departments_and_exactly_one_ceo_idle(tmp_path):
    hub = CompanyHub(tmp_path / "new-company")

    first = hub.tick()
    second = hub.tick()

    assert first["workers"] == 0
    assert second["verifiers"]["active_instances"] == 0
    assert hub.departments.list_departments() == []
    unread = hub.inbox.peek("ceo")
    assert len(unread) == 1
    assert unread[0]["body"]["type"] == "company_idle"

    _call(
        hub,
        CEO,
        "wake_completed",
        {
            "message_id": unread[0]["id"],
            "wake_id": "wake-cold-1",
            "finished_at": "2026-07-14T00:00:00Z",
        },
        "complete-cold-1",
    )

    renewed = hub.inbox.peek("ceo")
    assert len(renewed) == 1
    assert renewed[0]["id"] != unread[0]["id"]


def test_wake_completion_recovers_cursor_advance_before_ack_receipt(tmp_path):
    hub = CompanyHub(tmp_path / "new-company")
    hub.tick()
    message = hub.inbox.peek_one("ceo")

    # Simulate a process death in the narrow interval after cursor commit but
    # before CompanyHub persisted its own acknowledgement receipt.
    hub.inbox.ack_one("ceo")
    receipt = hub._ack_receipt_path("ceo", message["id"])
    assert not receipt.exists()

    result = _call(
        hub,
        CEO,
        "wake_completed",
        {
            "message_id": message["id"],
            "wake_id": "wake-recovered-ack",
            "finished_at": "2026-07-14T00:00:00Z",
        },
        "complete-recovered-ack",
    )

    assert result == {"recorded": True, "acked": False}
    recovered = json.loads(receipt.read_text())
    assert recovered["recovered_after_cursor_advance"] is True
    unread = hub.inbox.peek("ceo")
    assert len(unread) == 1
    assert unread[0]["id"] != message["id"]


def test_department_options_are_public_only_and_creation_waits_for_objective_pass(tmp_path):
    hub = CompanyHub(tmp_path / "new-company")
    options = _call(hub, CEO, "list_department_options", request_id="options")

    assert [row["id"] for row in options] == [
        "strategist",
        "researcher",
        "builder",
        "growth",
    ]
    assert all(set(row) == {"id", "name", "description"} for row in options)

    rejected = hub.call(
        CEO,
        _request(
            "create_department",
            {"option_id": "researcher", "initial_objective": "Find evidence."},
            "too-early",
        ),
    )
    assert rejected["ok"] is False
    assert "Company Objective" in rejected["error"]["message"]

    _activate_company_objective(hub)
    request = _call(
        hub,
        CEO,
        "create_department",
        {"option_id": "researcher", "initial_objective": "Find evidence."},
        "create-researcher",
    )
    assert hub.departments.list_departments() == []
    _verdict(hub, request["objective_review_id"], "FAIL", "too vague")
    assert hub.departments.list_departments() == []
    assert not list((hub.layout.departments / "commands").glob("*.json"))


def test_department_message_has_only_logical_fields_and_never_copies_ceo(tmp_path):
    hub = CompanyHub(tmp_path / "new-company")
    _activate_company_objective(hub)
    researcher, _ = _create_department(hub, "researcher")
    _, _ = _create_department(hub, "builder")
    ceo_before = [event["id"] for event in hub.inbox.peek("ceo")]

    receipt = _call(
        hub,
        researcher,
        "send_department_message",
        {"to": "builder", "subject": "Need a prototype", "body": "Build the tested path."},
        "message-one",
    )

    assert set(receipt) == {"message_id", "time", "from", "to", "subject", "body"}
    assert receipt["from"] == "researcher"
    event = hub.inbox.peek("builder")[-1]
    assert event["body"] == {
        "v": 1,
        "type": "department_message",
        "from": "researcher",
        "data": {"subject": "Need a prototype", "body": "Build the tested path."},
    }
    assert [event["id"] for event in hub.inbox.peek("ceo")] == ceo_before

    forbidden = hub.call(
        researcher,
        _request(
            "send_department_message",
            {
                "to": "builder",
                "subject": "x",
                "body": "y",
                "kind": "request",
                "reply_to_message_id": "old",
            },
            "message-forbidden",
        ),
    )
    assert forbidden["ok"] is False
    assert "unknown payload fields" in forbidden["error"]["message"]


def test_goal_result_uses_ephemeral_verifier_and_routes_only_to_owner(tmp_path):
    hub = CompanyHub(tmp_path / "new-company", goal_timeout_secs=100)
    _activate_company_objective(hub)
    researcher, _ = _create_department(hub, "researcher")
    goal = _call(
        hub,
        researcher,
        "create_goal",
        {"intent": "Produce a sourced market brief.", "acceptance": "At least two sources."},
        "goal-one",
    )
    raw_goal = hub.scheduler.get(goal["id"])
    assert raw_goal["status"] == "claimed"
    worker_command = json.loads(
        next((hub.layout.workers / "commands").glob("start:*.json")).read_text()
    )
    assert "acceptance" not in worker_command

    _call(
        hub,
        WORKER_MANAGER,
        "worker_started",
        {"goal_id": goal["id"], "worker_id": raw_goal["worker_id"]},
        "worker-started-one",
    )
    worker = ActorContext("worker", raw_goal["worker_id"], goal_id=goal["id"])
    rejected = hub.call(
        worker,
        _request(
            "submit_result",
            {"summary": "legacy", "company_refs": ["/company/research/brief.md"]},
            "worker-result-legacy-payload",
        ),
    )
    assert rejected["ok"] is False
    assert "unknown payload fields" in rejected["error"]["message"]
    assert hub.scheduler.get(goal["id"])["status"] == "running"

    result = _call(
        hub,
        worker,
        "submit_result",
        {},
        "worker-result-one",
    )
    review = hub.reviews.get(result["review_id"])
    assert review["kind"] == "goal_result"
    assert review["payload"] == {
        "goal_id": goal["id"],
        "owner_department": "researcher",
        "intent": "Produce a sourced market brief.",
        "acceptance": "At least two sources.",
        "deadline_at": hub.scheduler.get(goal["id"])["deadline_at"],
    }
    assert review["instance_id"].startswith("verifier-")

    ceo_before = [event["id"] for event in hub.inbox.peek("ceo")]
    _verdict(hub, result["review_id"], "PASS", "evidence is sufficient")

    assert hub.scheduler.get(goal["id"])["status"] == "done"
    assert hub.reviews.get(result["review_id"])["instance_state"] == "stopping"
    assert any(
        event["body"]["type"] == "goal_done" for event in hub.inbox.peek("researcher")
    )
    assert [event["id"] for event in hub.inbox.peek("ceo")] == ceo_before


def test_verdict_after_absolute_deadline_is_terminal_noop(tmp_path, monkeypatch):
    clock = {"now": 10.0}
    monkeypatch.setattr("orchestration.scheduler._now", lambda: clock["now"])
    hub = CompanyHub(tmp_path / "new-company", goal_timeout_secs=100)
    _activate_company_objective(hub)
    researcher, _ = _create_department(hub, "researcher")
    goal = _call(
        hub,
        researcher,
        "create_goal",
        {"intent": "Produce a durable evidence brief."},
        "deadline-goal",
    )
    raw_goal = hub.scheduler.get(goal["id"])
    _call(
        hub,
        WORKER_MANAGER,
        "worker_started",
        {"goal_id": goal["id"], "worker_id": raw_goal["worker_id"]},
        "deadline-worker-started",
    )
    result = _call(
        hub,
        ActorContext("worker", raw_goal["worker_id"], goal_id=goal["id"]),
        "submit_result",
        {},
        "deadline-worker-result",
    )

    clock["now"] = 111.0
    late = _verdict(hub, result["review_id"], "PASS", "arrived too late")

    assert late["accepted"] is False
    assert hub.scheduler.get(goal["id"])["status"] == "failed_time"
    assert hub.reviews.get(result["review_id"])["status"] == "cancelled"
    assert any(
        event["body"]["type"] == "goal_failed_time"
        for event in hub.inbox.peek("researcher")
    )


def test_tick_replays_missing_fail_side_effects_after_crash(tmp_path):
    hub = CompanyHub(tmp_path / "new-company", goal_timeout_secs=1000)
    _activate_company_objective(hub)
    researcher, _ = _create_department(hub, "researcher")
    goal = _call(
        hub,
        researcher,
        "create_goal",
        {"intent": "Produce a durable evidence brief."},
        "crash-recovery-goal",
    )
    raw_goal = hub.scheduler.get(goal["id"])
    _call(
        hub,
        WORKER_MANAGER,
        "worker_started",
        {"goal_id": goal["id"], "worker_id": raw_goal["worker_id"]},
        "crash-recovery-started",
    )
    result = _call(
        hub,
        ActorContext("worker", raw_goal["worker_id"], goal_id=goal["id"]),
        "submit_result",
        {},
        "crash-recovery-result",
    )
    review = hub.reviews.get(result["review_id"])

    # Simulate a process death after the verdict and Goal transition were
    # durable, but before the Department message/resume command and routed bit.
    hub.reviews.submit_verdict(
        review["id"],
        instance_id=review["instance_id"],
        verdict="FAIL",
        reason="add the missing source",
    )
    hub.scheduler.verification_failed(
        goal["id"], review_id=review["id"], feedback="add the missing source"
    )
    assert not list((hub.layout.workers / "commands").glob("resume:*.json"))

    hub.tick()
    hub.tick()

    resume_commands = list((hub.layout.workers / "commands").glob("resume:*.json"))
    messages = [
        event
        for event in hub.inbox.peek("researcher")
        if event["body"]["type"] == "goal_verifier_failed"
    ]
    assert len(resume_commands) == 1
    assert len(messages) == 1
    assert hub.reviews.get(review["id"])["routed"] is True


def test_fast_verifier_fail_before_turn_exit_preserves_feedback_and_one_resume(tmp_path):
    hub = CompanyHub(tmp_path / "new-company", goal_timeout_secs=1000)
    _activate_company_objective(hub)
    _confirm_stopping_verifiers(hub)
    researcher, _ = _create_department(hub, "researcher")
    _confirm_stopping_verifiers(hub)
    goal = _call(
        hub,
        researcher,
        "create_goal",
        {"intent": "Produce a sourced brief."},
        "fast-verifier-goal",
    )
    raw = hub.scheduler.get(goal["id"])
    _call(
        hub,
        WORKER_MANAGER,
        "worker_started",
        {"goal_id": raw["id"], "worker_id": raw["worker_id"]},
        "fast-verifier-started",
    )
    result = _call(
        hub,
        ActorContext("worker", raw["worker_id"], goal_id=raw["id"]),
        "submit_result",
        {},
        "fast-verifier-result",
    )

    _verdict(hub, result["review_id"], "FAIL", "add the missing primary source")
    before = hub.scheduler.get(raw["id"])
    assert before["worker_state"] == "resuming"
    assert before["attempts"] == 1

    _call(
        hub,
        WORKER_MANAGER,
        "worker_turn_finished",
        {
            "goal_id": raw["id"],
            "worker_id": raw["worker_id"],
            "ok": True,
            "session_token": "session-after-submit",
        },
        "fast-verifier-turn-finished",
    )

    after = hub.scheduler.get(raw["id"])
    resumes = list((hub.layout.workers / "commands").glob("resume:*.json"))
    assert after["latest_feedback"] == "add the missing primary source"
    assert after["attempts"] == 1
    assert after["session_token"] == "session-after-submit"
    assert len(resumes) == 1


def test_inspect_is_read_only_and_does_not_expose_messages_or_raw_acceptance(tmp_path):
    hub = CompanyHub(tmp_path / "new-company")
    _activate_company_objective(hub)
    researcher, _ = _create_department(hub, "researcher")
    goal = _call(
        hub,
        researcher,
        "create_goal",
        {"intent": "Check one claim", "acceptance": "secret verifier rubric"},
        "inspect-goal",
    )
    before = hub.inbox.peek("ceo")

    overview = _call(hub, CEO, "inspect", request_id="inspect-overview")
    detail = _call(
        hub, CEO, "inspect", {"goal_id": goal["id"]}, "inspect-detail"
    )

    assert "messages" not in json.dumps(overview).lower()
    assert "secret verifier rubric" not in json.dumps(detail)
    assert hub.inbox.peek("ceo") == before
    assert overview["workers"]["max"] == 5


def test_external_event_is_normalized_by_hub_before_delivery(tmp_path):
    hub = CompanyHub(tmp_path / "new-company")
    result = _call(
        hub,
        PERIPHERAL,
        "deliver_external_event",
        {
            "to": "ceo",
            "text": "New external signal",
            "body": "untrusted content",
            "message_id": "<mail@example.com>",
            "time": "2026-07-14T00:00:00Z",
        },
        "external-one",
    )

    event = next(row for row in hub.inbox.peek("ceo") if row["id"] == result["message_id"])
    assert event["body"]["type"] == "external_event"
    assert event["body"]["from"] == "external"
    assert event["body"]["data"]["source_message_id"] == "<mail@example.com>"


def test_seven_goals_fill_five_workers_fifo_and_wait_for_stop_ack(tmp_path):
    hub = CompanyHub(tmp_path / "new-company", max_workers=5)
    _activate_company_objective(hub)
    _confirm_stopping_verifiers(hub)
    builder, _ = _create_department(hub, "builder")
    _confirm_stopping_verifiers(hub)

    goals = [
        _call(
            hub,
            builder,
            "create_goal",
            {"intent": f"Deliver independent artifact {number}."},
            f"seven-goals-{number}",
        )
        for number in range(1, 8)
    ]
    assert [hub.scheduler.get(row["id"])["enqueue_seq"] for row in goals] == list(
        range(1, 8)
    )

    for index, projection in enumerate(goals[:5], 1):
        raw = hub.scheduler.get(projection["id"])
        assert raw["status"] == "claimed"
        _call(
            hub,
            WORKER_MANAGER,
            "worker_started",
            {"goal_id": raw["id"], "worker_id": raw["worker_id"]},
            f"seven-worker-started-{index}",
        )

    assert [hub.scheduler.get(row["id"])["status"] for row in goals] == [
        "running",
        "running",
        "running",
        "running",
        "running",
        "open",
        "open",
    ]
    assert hub.scheduler.inspect()["active_workers"] == 5

    first = hub.scheduler.get(goals[0]["id"])
    result = _call(
        hub,
        ActorContext("worker", first["worker_id"], goal_id=first["id"]),
        "submit_result",
        {},
        "seven-goals-result-one",
    )
    _verdict(hub, result["review_id"], "PASS", "artifact exists")

    # PASS makes the first Goal terminal, but its lifecycle still owns one of
    # five slots until Worker Manager confirms the container was destroyed.
    assert hub.scheduler.get(goals[0]["id"])["worker_state"] == "stopping"
    assert hub.scheduler.get(goals[5]["id"])["status"] == "open"
    _call(
        hub,
        WORKER_MANAGER,
        "worker_stopped",
        {"goal_id": first["id"], "worker_id": first["worker_id"]},
        "seven-worker-stopped-one",
    )

    assert hub.scheduler.get(goals[5]["id"])["status"] == "claimed"
    assert hub.scheduler.get(goals[6]["id"])["status"] == "open"
    assert hub.scheduler.get(goals[5]["id"])["worker_id"] == "worker-6"


def test_ceo_claims_and_lists_only_its_company_mailboxes(tmp_path):
    global_root = tmp_path / "global-mail"
    acme = CompanyHub(
        tmp_path / "acme-state", company_id="acme", mail_global_root=global_root
    )
    bravo = CompanyHub(
        tmp_path / "bravo-state", company_id="bravo", mail_global_root=global_root
    )

    claimed = _call(
        acme,
        CEO,
        "claim_company_mailbox",
        {"name": "maya", "label": "外部账户"},
        "claim-maya",
    )
    repeated = _call(
        acme,
        CEO,
        "claim_company_mailbox",
        {"name": "maya", "label": "忽略的新标签"},
        "claim-maya-again",
    )
    conflict = bravo.call(
        CEO,
        _request(
            "claim_company_mailbox",
            {"name": "maya"},
            "bravo-claim-maya",
        ),
    )

    assert claimed["address"] == "maya@foundagent.net"
    assert claimed["created"] is True
    assert repeated["created"] is False
    assert repeated["label"] == "外部账户"
    assert conflict["ok"] is False
    assert _call(acme, CEO, "list_company_mailboxes", request_id="list-acme") == {
        "mailboxes": [
            {
                "name": "maya",
                "address": "maya@foundagent.net",
                "label": "外部账户",
                "claimed_at": claimed["claimed_at"],
            }
        ],
        "used": 1,
        "limit": 5,
    }
    assert _call(bravo, CEO, "list_company_mailboxes", request_id="list-bravo") == {
        "mailboxes": [],
        "used": 0,
        "limit": 5,
    }
    injected_company = acme.call(
        CEO,
        _request(
            "claim_company_mailbox",
            {"name": "other", "company": "bravo"},
            "claim-injected-company",
        ),
    )
    assert injected_company["ok"] is False
    assert "unknown payload fields" in injected_company["error"]["message"]


def test_mail_method_role_matrix_rejects_every_undeclared_capability(tmp_path):
    hub = CompanyHub(
        tmp_path / "acme-state",
        company_id="acme",
        mail_global_root=tmp_path / "global-mail",
    )
    actors = {
        "ceo": CEO,
        "department": ActorContext("department", "growth", department_id="growth"),
        "worker": ActorContext("worker", "worker-1", goal_id="goal-1"),
        "verifier": ActorContext("verifier", "verifier-1", review_id="review-1"),
    }
    forbidden = {
        "ceo": ("peek_company_email", "send_company_email"),
        "department": ("claim_company_mailbox",),
        "worker": ("claim_company_mailbox",),
        "verifier": (
            "claim_company_mailbox",
            "list_company_mailboxes",
            "peek_company_email",
            "send_company_email",
        ),
    }

    for role, methods in forbidden.items():
        for method in methods:
            response = hub.call(
                actors[role],
                _request(method, request_id=f"forbidden-{role}-{method}"),
            )
            assert response["error"]["code"] == "forbidden"


def test_department_and_bound_worker_peek_company_mail_without_consuming(
    tmp_path, monkeypatch
):
    global_root = tmp_path / "global-mail"
    hub = CompanyHub(
        tmp_path / "acme-state", company_id="acme", mail_global_root=global_root
    )
    _call(
        hub,
        CEO,
        "claim_company_mailbox",
        {"name": "maya"},
        "peek-claim-maya",
    )
    _activate_company_objective(hub)
    growth, _ = _create_department(hub, "growth")
    for number in range(105):
        _append_mail(hub, number, number)

    monkeypatch.setattr("orchestration.scheduler._now", lambda: 50.0)
    goal = _call(
        hub,
        growth,
        "create_goal",
        {"intent": "Complete an account verification."},
        "mail-goal",
    )
    raw_goal = hub.scheduler.get(goal["id"])
    _call(
        hub,
        WORKER_MANAGER,
        "worker_started",
        {"goal_id": goal["id"], "worker_id": raw_goal["worker_id"], "started_at": 50.0},
        "mail-worker-started",
    )
    worker = ActorContext("worker", raw_goal["worker_id"], goal_id=goal["id"])

    department_result = _call(
        hub, growth, "peek_company_email", request_id="department-mail-peek"
    )
    worker_result = _call(
        hub, worker, "peek_company_email", request_id="worker-mail-peek"
    )

    assert department_result["count"] == 100
    assert [row["received_at"] for row in department_result["messages"]] == list(
        map(float, range(5, 105))
    )
    assert worker_result["count"] == 55
    assert worker_result["messages"][0]["received_at"] == 50.0
    assert worker_result["messages"][-1]["received_at"] == 104.0
    assert all("source_key" not in row for row in worker_result["messages"])
    assert hub.mail_store.peek_for_ceo()["id"] == "mail-0"

    restarted_worker = ActorContext(
        "worker", raw_goal["worker_id"], goal_id=goal["id"]
    )
    after_restart = _call(
        hub,
        restarted_worker,
        "peek_company_email",
        request_id="worker-mail-peek-after-restart",
    )
    assert [row["id"] for row in after_restart["messages"]] == [
        row["id"] for row in worker_result["messages"]
    ]

    submitted = _call(
        hub,
        worker,
        "submit_result",
        {},
        "mail-worker-submit",
    )
    _verdict(hub, submitted["review_id"], "FAIL", "finish the verification")
    after_fail = _call(
        hub,
        worker,
        "peek_company_email",
        request_id="worker-mail-peek-after-fail",
    )
    assert [row["id"] for row in after_fail["messages"]] == [
        row["id"] for row in worker_result["messages"]
    ]

    assert _call(
        hub, growth, "list_company_mailboxes", request_id="growth-list-mail"
    )["mailboxes"][0]["address"] == "maya@foundagent.net"
    assert _call(
        hub, worker, "list_company_mailboxes", request_id="worker-list-mail"
    )["used"] == 1

    telemetry = (
        hub.layout.telemetry / "index" / "methods.jsonl"
    ).read_text(encoding="utf-8")
    assert "verification-50" not in telemetry
    assert "https://example.test/50" not in telemetry
    assert '"redacted": true' in telemetry
    assert not (
        hub.layout.control
        / "requests"
        / "growth"
        / "department-mail-peek.json"
    ).exists()
    assert not (
        hub.layout.control
        / "requests"
        / raw_goal["worker_id"]
        / "worker-mail-peek.json"
    ).exists()

    wrong_worker = hub.call(
        ActorContext("worker", "worker-999", goal_id=goal["id"]),
        _request("peek_company_email", request_id="wrong-worker-mail-peek"),
    )
    verifier = hub.call(
        ActorContext("verifier", "verifier-1", review_id="review-1"),
        _request("peek_company_email", request_id="verifier-mail-peek"),
    )
    ceo = hub.call(
        CEO,
        _request("peek_company_email", request_id="ceo-mail-peek"),
    )
    assert wrong_worker["ok"] is False
    assert verifier["error"]["code"] == "forbidden"
    assert ceo["error"]["code"] == "forbidden"


def test_tick_notifies_only_ceo_and_replay_is_deduplicated(tmp_path, monkeypatch):
    hub = CompanyHub(
        tmp_path / "acme-state",
        company_id="acme",
        mail_global_root=tmp_path / "global-mail",
    )
    _activate_company_objective(hub)
    growth, _ = _create_department(hub, "growth")
    _append_mail(hub, "notify", 100, text="one-time code 654321")
    real_ack = hub.mail_store.ack_for_ceo
    failures = 0

    def fail_once(message_id):
        nonlocal failures
        failures += 1
        if failures == 1:
            raise OSError("crash after Inbox append")
        real_ack(message_id)

    monkeypatch.setattr(hub.mail_store, "ack_for_ceo", fail_once)
    with pytest.raises(OSError, match="crash after Inbox"):
        hub.tick()
    result = hub.tick()

    ceo_events = [
        row for row in hub.inbox.peek("ceo") if row["body"]["type"] == "external_event"
    ]
    department_events = [
        row
        for row in hub.inbox.peek(growth.actor_id)
        if row["body"]["type"] == "external_event"
    ]
    assert result["mail_notifications"] == 1
    assert len(ceo_events) == 1
    assert department_events == []
    assert ceo_events[0]["body"]["data"]["mail_id"] == "mail-notify"
    assert "654321" in ceo_events[0]["body"]["data"]["body"]
    assert hub.mail_store.peek_for_ceo() is None
    assert hub.tick()["mail_notifications"] == 0
    assert len(
        [
            row
            for row in hub.inbox.peek("ceo")
            if row["body"]["type"] == "external_event"
        ]
    ) == 1


def test_department_and_worker_can_send_but_ceo_and_verifier_cannot(
    tmp_path, monkeypatch
):
    global_root = tmp_path / "global-mail"
    hub = CompanyHub(
        tmp_path / "acme-state", company_id="acme", mail_global_root=global_root
    )
    _call(
        hub,
        CEO,
        "claim_company_mailbox",
        {"name": "maya"},
        "send-claim-maya",
    )
    from orchestration.mailbox import claim_company_mailbox

    claim_company_mailbox("bravo", "billing", root=global_root)
    _activate_company_objective(hub)
    growth, _ = _create_department(hub, "growth")
    goal = _call(
        hub,
        growth,
        "create_goal",
        {"intent": "Send the requested account email."},
        "send-goal",
    )
    raw_goal = hub.scheduler.get(goal["id"])
    worker = ActorContext("worker", raw_goal["worker_id"], goal_id=goal["id"])
    provider_calls = []

    def provider(payload, key):
        provider_calls.append((payload, key))
        return True, f"re-{len(provider_calls)}"

    monkeypatch.setattr(email_send, "_post_resend", provider)
    department_send = _call(
        hub,
        growth,
        "send_company_email",
        {
            "mailbox": "maya",
            "to": "buyer@example.com",
            "subject": "Department send",
            "text": "Allowed, though ordinary work should use a Worker.",
        },
        "department-send-email",
    )
    worker_send = _call(
        hub,
        worker,
        "send_company_email",
        {
            "mailbox": "maya",
            "to": "buyer@example.com",
            "subject": "Worker send",
            "text": "Normal execution path.",
        },
        "worker-send-email",
    )
    replay = _call(
        hub,
        worker,
        "send_company_email",
        {
            "mailbox": "maya",
            "to": "buyer@example.com",
            "subject": "Worker send",
            "text": "Normal execution path.",
        },
        "worker-send-email",
    )

    assert department_send["sent"] is True
    assert worker_send == replay
    assert [key for _payload, key in provider_calls] == [
        "department-send-email",
        "worker-send-email",
    ]
    assert hub.call(
        CEO,
        _request(
            "send_company_email",
            {
                "mailbox": "maya",
                "to": "x@example.com",
                "subject": "x",
                "text": "x",
            },
            "ceo-send-email",
        ),
    )["error"]["code"] == "forbidden"
    assert hub.call(
        ActorContext("verifier", "verifier-1", review_id="review-1"),
        _request(
            "send_company_email",
            {
                "mailbox": "maya",
                "to": "x@example.com",
                "subject": "x",
                "text": "x",
            },
            "verifier-send-email",
        ),
    )["error"]["code"] == "forbidden"
    other_company = hub.call(
        growth,
        _request(
            "send_company_email",
            {
                "mailbox": "billing",
                "to": "x@example.com",
                "subject": "x",
                "text": "x",
            },
            "other-company-send-email",
        ),
    )
    assert other_company["ok"] is False
    assert "not owned" in other_company["error"]["message"]


def test_two_company_hubs_never_cross_read_mail(tmp_path):
    global_root = tmp_path / "global-mail"
    acme = CompanyHub(
        tmp_path / "acme-state", company_id="acme", mail_global_root=global_root
    )
    bravo = CompanyHub(
        tmp_path / "bravo-state", company_id="bravo", mail_global_root=global_root
    )
    def worker_for(hub, request_id):
        goal_id = hub.scheduler.create_goal(
            owner_department="growth",
            intent="Inspect current Company mail.",
            acceptance=None,
            request_id=request_id,
        )
        launch = hub.scheduler.schedule_one()
        assert launch is not None
        return ActorContext("worker", launch.worker_id, goal_id=goal_id)

    acme_worker = worker_for(acme, "acme-mail-goal")
    bravo_worker = worker_for(bravo, "bravo-mail-goal")
    _append_mail(
        acme,
        "acme",
        acme.scheduler.get(acme_worker.goal_id)["created_at"],
        address="maya@foundagent.net",
    )
    _append_mail(
        bravo,
        "bravo",
        bravo.scheduler.get(bravo_worker.goal_id)["created_at"],
        address="billing@foundagent.net",
    )
    acme_mail = _call(
        acme,
        acme_worker,
        "peek_company_email",
        request_id="acme-cross-peek",
    )
    bravo_mail = _call(
        bravo,
        bravo_worker,
        "peek_company_email",
        request_id="bravo-cross-peek",
    )

    assert [row["address"] for row in acme_mail["messages"]] == [
        "maya@foundagent.net"
    ]
    assert [row["address"] for row in bravo_mail["messages"]] == [
        "billing@foundagent.net"
    ]
