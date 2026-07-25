import threading

import pytest

from orchestration.company_hub import CompanyHub, HubHTTPServer
from orchestration.control_client import (
    BoundActor,
    ControlClientError,
    HubClient,
    RemoteInbox,
)


@pytest.fixture
def live_hub(tmp_path, department_specs):
    hub = CompanyHub(
        tmp_path / "new-company",
        department_specs_path=department_specs,
    )
    hub.tick()
    server = HubHTTPServer(("127.0.0.1", 0), hub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield hub, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_client_reads_bound_context_and_remote_inbox_without_state_mount(live_hub):
    hub, url = live_hub
    client = HubClient(url, actor=BoundActor("ceo", "ceo"))

    context = client.call("wake_context")
    remote = RemoteInbox(client, poll_tick=0)
    event = remote.peek_one("ceo")

    assert context["actor_id"] == "ceo"
    assert "inspect" in context["capabilities"]
    assert event["body"]["type"] == "company_idle"
    assert str(hub.layout.inbox) not in str(context)


def test_business_payload_cannot_override_http_bound_actor(live_hub):
    _, url = live_hub
    client = HubClient(url, actor=BoundActor("ceo", "ceo"))

    with pytest.raises(ControlClientError) as exc:
        client.call("write_notes", {"text": "x", "from": "builder"})

    assert exc.value.code == "actor_is_bound"


def test_resident_harness_archives_full_run_through_hub(live_hub):
    hub, url = live_hub
    client = HubClient(url, actor=BoundActor("ceo", "ceo"))
    raw = "\n".join(f'{{"event":{number}}}' for number in range(500))

    result = client.archive_run(
        {
            "run_id": "wake-remote-1",
            "metadata": {"kind": "resident_wake", "agent_id": "ceo", "ok": True},
            "raw_output": raw,
            "stderr": "complete stderr",
            "model_output": "complete answer",
            "harness_log": "harness",
            "container_log": "container",
        }
    )

    run_dir = hub.layout.telemetry / "runs" / result["run_id"]
    assert (run_dir / "runtime.jsonl").read_text() == raw
    assert (run_dir / "stderr.log").read_text() == "complete stderr"
    assert (run_dir / "container.log").read_text() == "container"
