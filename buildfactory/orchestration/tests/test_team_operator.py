import json

import pytest

from orchestration.runtime_store import StoreError
from orchestration.team_operator import TeamOperator, main
from orchestration.team_pool import FakeTeamLifecycle

from orchestration.tests.test_handoff import envelope


def test_operator_inspect_pause_resume_and_request_idempotency(tmp_path):
    lifecycle = FakeTeamLifecycle()
    operator = TeamOperator(
        build_root=tmp_path / "build",
        lifecycle=lifecycle,
        max_active_teams=1,
    )
    first = operator.authorize(envelope(card_id="first"))
    second = operator.authorize(envelope(card_id="second"))
    assert [team["observed_state"] for team in operator.list()["teams"]] == [
        "active",
        "queued",
    ]

    paused = operator.pause(first["team_id"], request_id="pause-request-1")
    assert paused["team"]["observed_state"] == "paused"
    assert operator.inspect(second["team_id"])["team"]["observed_state"] == "active"
    replay = operator.pause(first["team_id"], request_id="pause-request-1")
    assert replay["team"]["observed_state"] == "paused"

    resumed = operator.resume(first["team_id"], request_id="resume-request-1")
    assert resumed["team"]["observed_state"] == "queued"
    with pytest.raises(StoreError, match="different content"):
        operator.resume(second["team_id"], request_id="resume-request-1")


def test_operator_cli_emits_bounded_strict_json_errors(tmp_path, capsys):
    code = main(
        [
            "inspect",
            "not-a-team",
            "--build-root",
            str(tmp_path / "build"),
            "--fake-lifecycle",
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    payload = json.loads(captured.err)
    assert set(payload) == {"code", "message"}
    assert payload["code"] == "StoreError"
    assert "invalid Team ID" in payload["message"]
