import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from hacksome.stages.build.control.handoff import BuildAuthorizationEnvelopeV1
from hacksome.stages.build.control.runtime_store import StoreError
from hacksome.stages.build.control.team_operator import TeamOperator
from hacksome.stages.build.control.team_pool import (
    ComposeTeamLifecycle,
    FakeTeamLifecycle,
)
from hacksome.stages.build.control.team_registry import RegistryConflictError
from tests.stages.build.control.test_handoff import envelope


def test_compose_lifecycle_propagates_reflection_rollout_flag(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("LEAD_REFLECTION_MEMORY_ENABLED", "1")
    lifecycle = ComposeTeamLifecycle(
        build_ops_root=tmp_path / "ops",
        repository_root=tmp_path / "repo",
    )

    environment = lifecycle._environment(
        {
            "team_id": "demo-team",
            "_absolute_control_root": str(tmp_path / "state" / "demo-team"),
        }
    )

    assert environment["LEAD_REFLECTION_MEMORY_ENABLED"] == "1"


def test_ten_teams_two_slots_fifo_pause_and_receipt_replay(tmp_path):
    lifecycle = FakeTeamLifecycle()
    operator = TeamOperator(
        build_root=tmp_path / "build",
        lifecycle=lifecycle,
        max_active_teams=2,
    )
    values = [
        envelope(
            run_id="run-many",
            card_id=f"card-{index}",
            markdown=f"# Card {index}\n\nExact {index}.\n",
        )
        for index in range(10)
    ]
    receipts = [operator.authorize(value) for value in values]
    status = operator.list()
    assert [team["observed_state"] for team in status["teams"]].count("active") == 2
    assert [team["observed_state"] for team in status["teams"]].count("queued") == 8
    assert [
        team["queue_position"]
        for team in status["teams"]
        if team["observed_state"] == "queued"
    ] == list(range(1, 9))
    assert len(lifecycle.start_calls) == 2
    assert not (
        operator.registry.build_root
        / operator.registry.get(receipts[2]["team_id"])["control_root"]
    ).exists()

    operator.pause(receipts[0]["team_id"], request_id="pause-first")
    after = operator.list()
    assert (
        next(
            team for team in after["teams"] if team["team_id"] == receipts[0]["team_id"]
        )["observed_state"]
        == "paused"
    )
    assert (
        next(
            team for team in after["teams"] if team["team_id"] == receipts[2]["team_id"]
        )["observed_state"]
        == "active"
    )

    replay = operator.authorize(values[0])
    assert replay == receipts[0]
    assert replay["observed_state"] in {
        "queued",
        "bootstrapping",
        "starting",
        "active",
        "error",
    }


def test_start_failure_retains_row_and_error(tmp_path):
    lifecycle = FakeTeamLifecycle()
    operator = TeamOperator(
        build_root=tmp_path / "build",
        lifecycle=lifecycle,
        max_active_teams=2,
    )
    value = envelope()
    decoded = BuildAuthorizationEnvelopeV1.from_mapping(value)
    lifecycle.fail_start.add(decoded.handoff.team_id)
    receipt = operator.authorize(value)
    assert receipt["observed_state"] == "error"
    row = operator.registry.get(receipt["team_id"])
    assert row["authorization_id"] == decoded.authorization_id
    assert row["last_error"]["code"] == "start_failed"


def test_start_response_loss_is_adopted_without_duplicate_start(tmp_path):
    class ResponseLossLifecycle(FakeTeamLifecycle):
        def start(self, row):
            super().start(row)
            raise StoreError("simulated response loss after start")

    lifecycle = ResponseLossLifecycle()
    operator = TeamOperator(
        build_root=tmp_path / "build",
        lifecycle=lifecycle,
        max_active_teams=1,
    )
    receipt = operator.authorize(envelope())
    assert receipt["observed_state"] == "active"
    assert lifecycle.start_calls == [receipt["team_id"]]


def test_partial_pause_and_crash_resume_through_reconcile(tmp_path):
    lifecycle = FakeTeamLifecycle()
    operator = TeamOperator(
        build_root=tmp_path / "build",
        lifecycle=lifecycle,
        max_active_teams=1,
    )
    first = operator.authorize(envelope(card_id="first"))
    second = operator.authorize(envelope(card_id="second"))
    lifecycle.partial_stop.add(first["team_id"])

    paused = operator.pause(first["team_id"], request_id="pause-partial")
    assert paused["team"]["observed_state"] == "pausing"
    assert operator.inspect(second["team_id"])["team"]["observed_state"] == "queued"
    with pytest.raises(RegistryConflictError, match="fully confirmed"):
        operator.resume(first["team_id"], request_id="resume-too-early")

    lifecycle.partial_stop.clear()
    restarted = TeamOperator(
        build_root=tmp_path / "build",
        lifecycle=lifecycle,
        max_active_teams=1,
    )
    restarted.reconcile()
    assert restarted.inspect(first["team_id"])["team"]["observed_state"] == "paused"
    assert restarted.inspect(second["team_id"])["team"]["observed_state"] == "active"
    assert lifecycle.stop_calls == [first["team_id"], first["team_id"]]


def test_concurrent_reconcile_and_pause_execute_each_side_effect_once(tmp_path):
    class SlowLifecycle(FakeTeamLifecycle):
        def start(self, row):
            time.sleep(0.04)
            super().start(row)

        def stop(self, row):
            time.sleep(0.04)
            return super().stop(row)

    lifecycle = SlowLifecycle()
    operator = TeamOperator(
        build_root=tmp_path / "build",
        lifecycle=lifecycle,
        max_active_teams=1,
    )
    decoded = BuildAuthorizationEnvelopeV1.from_mapping(envelope())
    operator.registry.authorize(decoded)
    reserved = operator.registry.reserve_next(max_active_teams=1)
    assert reserved is not None

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: operator.pool.reconcile(), range(2)))
    assert lifecycle.start_calls == [decoded.handoff.team_id]

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(
            executor.map(
                lambda index: operator.pool.pause(
                    decoded.handoff.team_id,
                    request_id=f"pause-concurrent-{index}",
                ),
                range(2),
            )
        )
    assert lifecycle.stop_calls == [decoded.handoff.team_id]
