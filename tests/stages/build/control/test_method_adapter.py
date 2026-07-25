from hacksome.stages.build.control.method_adapter import ActorContext, MethodAdapter
from hacksome.stages.build.control.runtime_store import CompanyLayout
from hacksome.stages.build.control.runtime_store import read_jsonl


def _request(request_id="r1", method="mutate", payload=None):
    return {
        "version": 1,
        "request_id": request_id,
        "method": method,
        "payload": payload or {},
    }


def test_adapter_binds_actor_and_rejects_self_reported_from(tmp_path):
    layout = CompanyLayout.initialize(tmp_path / "company")
    adapter = MethodAdapter(layout)
    calls = []
    adapter.register(
        "mutate",
        actors={"department"},
        handler=lambda actor, payload, request_id: calls.append(actor.actor_id) or {"ok": 1},
    )

    actor = ActorContext("department", "researcher", department_id="researcher")
    response = adapter.call(actor, _request(payload={"from": "builder"}))

    assert response["ok"] is False
    assert response["error"]["code"] == "actor_is_bound"
    assert calls == []


def test_adapter_enforces_role_permissions(tmp_path):
    layout = CompanyLayout.initialize(tmp_path / "company")
    adapter = MethodAdapter(layout)
    adapter.register("mutate", actors={"department"}, handler=lambda *_: {})

    response = adapter.call(ActorContext("worker", "worker-a", goal_id="goal-a"), _request())

    assert response["ok"] is False
    assert response["error"]["code"] == "forbidden"


def test_duplicate_request_returns_persisted_result_without_second_mutation(tmp_path):
    layout = CompanyLayout.initialize(tmp_path / "company")
    adapter = MethodAdapter(layout)
    calls = []

    def mutate(actor, payload, request_id):
        calls.append((actor.actor_id, payload["value"], request_id))
        return {"sequence": len(calls)}

    adapter.register("mutate", actors={"ceo"}, handler=mutate)
    actor = ActorContext("ceo", "ceo")

    first = adapter.call(actor, _request(payload={"value": 7}))
    second = adapter.call(actor, _request(payload={"value": 7}))

    assert first == second
    assert first["result"] == {"sequence": 1}
    assert calls == [("ceo", 7, "r1")]


def test_same_request_id_with_different_meaning_is_rejected(tmp_path):
    layout = CompanyLayout.initialize(tmp_path / "company")
    adapter = MethodAdapter(layout)
    calls = []
    adapter.register(
        "mutate",
        actors={"ceo"},
        handler=lambda actor, payload, request_id: calls.append(payload) or {"ok": True},
    )
    adapter.register("read", actors={"ceo"}, handler=lambda *_: {"value": 1})
    actor = ActorContext("ceo", "ceo")

    assert adapter.call(actor, _request(payload={"value": 7}))["ok"] is True
    changed_payload = adapter.call(actor, _request(payload={"value": 8}))
    changed_method = adapter.call(actor, _request(method="read"))

    assert changed_payload["error"]["code"] == "idempotency_conflict"
    assert changed_method["error"]["code"] == "idempotency_conflict"
    assert calls == [{"value": 7}]


def test_request_envelope_is_strict_and_versioned(tmp_path):
    adapter = MethodAdapter(CompanyLayout.initialize(tmp_path / "company"))
    adapter.register("mutate", actors={"ceo"}, handler=lambda *_: {})
    actor = ActorContext("ceo", "ceo")

    bad_version = adapter.call(actor, {**_request(), "version": 2})
    extra_actor = adapter.call(actor, {**_request("r2"), "actor": "builder"})

    assert bad_version["error"]["code"] == "unsupported_version"
    assert extra_actor["error"]["code"] == "invalid_request"


def test_every_method_result_and_error_is_audited_operator_side(tmp_path):
    layout = CompanyLayout.initialize(tmp_path / "company")
    adapter = MethodAdapter(layout)
    adapter.register("read", actors={"ceo"}, handler=lambda *_: {"value": 1})
    actor = ActorContext("ceo", "ceo")

    adapter.call(actor, _request("audit-ok", "read"))
    adapter.call(actor, _request("audit-error", "missing"))

    rows = read_jsonl(layout.telemetry / "index" / "methods.jsonl")
    assert [row["response"]["ok"] for row in rows] == [True, False]
    assert all(row["actor"]["actor_id"] == "ceo" for row in rows)


def test_sensitive_live_read_is_not_cached_and_audit_is_redacted(tmp_path):
    layout = CompanyLayout.initialize(tmp_path / "company")
    adapter = MethodAdapter(layout)
    calls = []

    def peek(_actor, _payload, _request_id):
        calls.append(len(calls) + 1)
        return {"messages": [{"subject": f"secret-{calls[-1]}"}]}

    adapter.register(
        "peek_mail",
        actors={"worker"},
        handler=peek,
        cache_response=False,
        audit_result=lambda result: {
            "redacted": True,
            "count": len(result["messages"]),
        },
    )
    actor = ActorContext("worker", "worker-a", goal_id="goal-a")

    first = adapter.call(actor, _request("peek-1", "peek_mail"))
    second = adapter.call(actor, _request("peek-1", "peek_mail"))

    assert first["result"]["messages"][0]["subject"] == "secret-1"
    assert second["result"]["messages"][0]["subject"] == "secret-2"
    assert calls == [1, 2]
    assert not (
        layout.control / "requests" / "worker-a" / "peek-1.json"
    ).exists()
    rows = read_jsonl(layout.telemetry / "index" / "methods.jsonl")
    assert [row["response"]["result"] for row in rows] == [
        {"redacted": True, "count": 1},
        {"redacted": True, "count": 1},
    ]
    assert "secret" not in (
        layout.telemetry / "index" / "methods.jsonl"
    ).read_text(encoding="utf-8")


def test_sensitive_audit_redactor_failure_still_fails_closed(tmp_path):
    layout = CompanyLayout.initialize(tmp_path / "company")
    adapter = MethodAdapter(layout)
    adapter.register(
        "peek_mail",
        actors={"department"},
        handler=lambda *_: {"messages": [{"text": "verification code 123456"}]},
        cache_response=False,
        audit_result=lambda _result: 1 / 0,
    )

    response = adapter.call(
        ActorContext("department", "growth", department_id="growth"),
        _request("peek-redactor-error", "peek_mail"),
    )

    assert response["ok"] is True
    rows = read_jsonl(layout.telemetry / "index" / "methods.jsonl")
    assert rows[-1]["response"]["result"] == {"redacted": True}
    assert "123456" not in (
        layout.telemetry / "index" / "methods.jsonl"
    ).read_text(encoding="utf-8")
