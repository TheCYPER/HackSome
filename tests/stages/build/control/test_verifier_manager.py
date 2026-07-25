import pytest

from hacksome.stages.build.control.verifier_manager import (
    FAILED,
    PASSED,
    QUEUED,
    RUNNING,
    ReviewError,
    VerifierManager,
)


def _enqueue(manager, number, kind="goal_result"):
    return manager.enqueue(
        kind=kind,
        subject_id=f"subject-{number}",
        requested_by="researcher",
        payload={"n": number},
        request_id=f"request-{number}",
    )


def test_all_review_kinds_share_one_fifo_and_three_instance_pool(tmp_path):
    manager = VerifierManager(tmp_path / "reviews", max_instances=3)
    ids = [
        _enqueue(manager, 1, "company_objective"),
        _enqueue(manager, 2, "department_objective"),
        _enqueue(manager, 3, "goal_result"),
        _enqueue(manager, 4, "goal_result"),
        _enqueue(manager, 5, "department_objective"),
    ]

    launches = manager.schedule()

    assert [launch.review_id for launch in launches] == ids[:3]
    assert manager.inspect_pool() == {
        "max_instances": 3,
        "active_instances": 3,
        "queued": 2,
        "running": 3,
    }


def test_verdict_does_not_release_slot_until_instance_is_destroyed(tmp_path):
    manager = VerifierManager(tmp_path / "reviews", max_instances=1)
    first = _enqueue(manager, 1)
    second = _enqueue(manager, 2)
    launch = manager.schedule()[0]

    assert manager.submit_verdict(
        first, instance_id=launch.instance_id, verdict="PASS", reason="meets the goal"
    )
    assert manager.get(first)["status"] == PASSED
    assert manager.schedule() == []

    assert manager.confirm_instance_stopped(first, instance_id=launch.instance_id)
    assert manager.schedule()[0].review_id == second


def test_fail_is_terminal_for_this_review_but_next_worker_report_is_new_review(tmp_path):
    manager = VerifierManager(tmp_path / "reviews")
    first = _enqueue(manager, 1)
    launch = manager.schedule()[0]

    assert manager.submit_verdict(
        first, instance_id=launch.instance_id, verdict="FAIL", reason="missing evidence"
    )
    assert manager.get(first)["status"] == FAILED
    assert manager.submit_verdict(
        first, instance_id=launch.instance_id, verdict="PASS", reason="late verdict"
    ) is False

    second = manager.enqueue(
        kind="goal_result",
        subject_id="subject-1",
        requested_by="researcher",
        payload={"attempt": 2},
        request_id="request-1-attempt-2",
    )
    assert second != first


def test_instance_crash_requeues_same_review_with_fresh_instance(tmp_path):
    manager = VerifierManager(tmp_path / "reviews", max_instances=1)
    review_id = _enqueue(manager, 1)
    first = manager.schedule()[0]

    assert manager.instance_failed(review_id, instance_id=first.instance_id, reason="crash")
    assert manager.get(review_id)["status"] == QUEUED
    second = manager.schedule()[0]

    assert second.review_id == review_id
    assert second.instance_id != first.instance_id


def test_wrong_instance_and_invalid_verdict_fail_closed(tmp_path):
    manager = VerifierManager(tmp_path / "reviews")
    review_id = _enqueue(manager, 1)
    launch = manager.schedule()[0]

    with pytest.raises(ReviewError):
        manager.submit_verdict(review_id, instance_id="verifier-other", verdict="PASS", reason="x")
    with pytest.raises(ReviewError):
        manager.submit_verdict(review_id, instance_id=launch.instance_id, verdict="MAYBE", reason="x")

    assert manager.get(review_id)["status"] == RUNNING


def test_enqueue_is_idempotent_by_request_id(tmp_path):
    manager = VerifierManager(tmp_path / "reviews")

    first = _enqueue(manager, 1)
    second = _enqueue(manager, 999)

    assert first != second
    same = manager.enqueue(
        kind="company_objective",
        subject_id="different",
        requested_by="ceo",
        payload={},
        request_id="request-1",
    )
    assert same == first
    assert len(manager.list_reviews()) == 2
