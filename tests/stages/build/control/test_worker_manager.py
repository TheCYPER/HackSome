import threading

from hacksome.stages.build.agent_runtime.runtimes.base import RunResult
from hacksome.stages.build.control.worker_manager import (
    WorkerLaunch,
    WorkerManager,
    WorkerManagerError,
    initial_worker_prompt,
    resume_worker_prompt,
)


class FakeBackend:
    def __init__(self):
        self.created = []
        self.runs = []
        self.stopped = []
        self.observed = {}
        self.results = []

    def create(self, definition):
        self.created.append(definition)
        self.observed[definition.worker_id] = "running"

    def run(self, definition, prompt, *, resume_token):
        self.runs.append((definition, prompt, resume_token))
        if self.results:
            return self.results.pop(0)
        return RunResult(ok=True, text="ok", error=None, session_token="session-1")

    def stop(self, definition):
        self.stopped.append(definition)
        self.observed.pop(definition.worker_id, None)

    def logs(self, definition):
        return f"complete logs for {definition.worker_id}"

    def inspect(self, company_id):
        return dict(self.observed)


class BlockingBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.turn_started = threading.Event()
        self.release_turn = threading.Event()

    def run(self, definition, prompt, *, resume_token):
        self.runs.append((definition, prompt, resume_token))
        self.turn_started.set()
        assert self.release_turn.wait(2)
        return RunResult(ok=False, text="", error="container stopped", session_token=None)

    def stop(self, definition):
        super().stop(definition)
        self.release_turn.set()


class BlockingCreateBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.create_started = threading.Event()
        self.release_create = threading.Event()

    def create(self, definition):
        self.created.append(definition)
        self.create_started.set()
        assert self.release_create.wait(2)
        self.observed[definition.worker_id] = "running"

    def stop(self, definition):
        super().stop(definition)
        self.release_create.set()


def _launch(number=1):
    return WorkerLaunch(
        goal_id=f"goal-{number}",
        worker_id=f"worker-{number}",
        intent=f"deliver {number}",
        acceptance="hidden verifier criteria",
        owner_department="researcher",
        command_id=f"start-{number}",
    )


def _manager(tmp_path, backend, max_workers=5):
    company = tmp_path / "company"
    company.mkdir()
    return WorkerManager(
        tmp_path / "workers",
        company_id="new-company",
        company_dir=company,
        backend=backend,
        max_workers=max_workers,
    )


def test_create_is_idempotent_and_one_worker_is_bound_to_one_goal(tmp_path):
    backend = FakeBackend()
    manager = _manager(tmp_path, backend)
    launch = _launch()

    first = manager.create_worker(launch)
    second = manager.create_worker(launch)

    assert first["goal_id"] == second["goal_id"] == launch.goal_id
    assert len(backend.created) == 1
    assert backend.created[0].company_dir.name == "company"


def test_resume_uses_same_worker_workspace_and_session_token(tmp_path):
    backend = FakeBackend()
    manager = _manager(tmp_path, backend)
    launch = _launch()
    manager.create_worker(launch)

    manager.run_worker(launch.worker_id, "first", resume=False)
    backend.results.append(
        RunResult(ok=True, text="fixed", error=None, session_token="session-1")
    )
    manager.run_worker(launch.worker_id, "feedback", resume=True)

    first_definition, _, first_token = backend.runs[0]
    second_definition, _, second_token = backend.runs[1]
    assert first_token is None
    assert second_token == "session-1"
    assert first_definition == second_definition
    assert manager.get(launch.worker_id)["turns"] == 2


def test_missing_first_token_is_recorded_without_replacing_worker(tmp_path):
    backend = FakeBackend()
    backend.results.append(RunResult(ok=False, text="", error="crash", session_token=None))
    manager = _manager(tmp_path, backend)
    launch = _launch()
    manager.create_worker(launch)

    manager.run_worker(launch.worker_id, "first", resume=False)
    manager.run_worker(launch.worker_id, "retry", resume=True)

    assert backend.runs[1][2] is None
    assert manager.get(launch.worker_id)["continuity_unavailable"] is True
    assert len(backend.created) == 1


def test_timeout_retires_container_and_recreates_before_same_session_resume(tmp_path):
    backend = FakeBackend()
    backend.results.append(
        RunResult(
            ok=False,
            text="",
            error="timeout",
            timed_out=True,
            session_token="session-timeout",
        )
    )
    manager = _manager(tmp_path, backend)
    launch = _launch()
    manager.create_worker(launch)

    result = manager.run_worker(launch.worker_id, "first", resume=False)

    assert result.timed_out is True
    assert len(backend.stopped) == 1
    timed_out = manager.get(launch.worker_id)
    assert timed_out["state"] == "missing"
    assert timed_out["session_token"] == "session-timeout"
    assert timed_out["last_result"]["timed_out"] is True

    manager.create_worker(launch)
    backend.results.append(
        RunResult(
            ok=True,
            text="fixed",
            error=None,
            session_token="session-timeout",
        )
    )
    manager.run_worker(launch.worker_id, "feedback", resume=True)

    assert len(backend.created) == 2
    assert backend.runs[-1][2] == "session-timeout"


def test_reconcile_retires_orphaned_turn_before_command_replay(tmp_path):
    backend = FakeBackend()
    first_manager = _manager(tmp_path, backend)
    launch = _launch()
    first_manager.create_worker(launch)
    row = first_manager.get(launch.worker_id)
    row["state"] = "running"
    first_manager._save(row)
    restarted_manager = WorkerManager(
        first_manager.root,
        company_id=first_manager.company_id,
        company_dir=first_manager.company_dir,
        backend=backend,
        max_workers=first_manager.max_workers,
    )

    changes = restarted_manager.reconcile()

    assert changes == [{"worker_id": launch.worker_id, "state": "missing"}]
    assert backend.stopped[-1].worker_id == launch.worker_id
    assert restarted_manager.get(launch.worker_id)["state"] == "missing"


def test_manager_enforces_hard_five_limit_independently(tmp_path):
    backend = FakeBackend()
    manager = _manager(tmp_path, backend, max_workers=2)
    manager.create_worker(_launch(1))
    manager.create_worker(_launch(2))

    try:
        manager.create_worker(_launch(3))
    except WorkerManagerError as exc:
        assert "concurrency" in str(exc)
    else:
        raise AssertionError("third Worker unexpectedly started")


def test_stop_is_idempotent_and_reconcile_detects_missing_container(tmp_path):
    backend = FakeBackend()
    manager = _manager(tmp_path, backend)
    manager.create_worker(_launch(1))

    assert manager.stop_worker("worker-1") is True
    assert manager.stop_worker("worker-1") is False
    assert len(backend.stopped) == 1

    manager.create_worker(_launch(2))
    backend.observed.pop("worker-2")
    assert manager.reconcile() == [{"worker_id": "worker-2", "state": "missing"}]

    recreated = manager.create_worker(_launch(2))
    assert recreated["id"] == "worker-2"
    assert len([row for row in backend.created if row.worker_id == "worker-2"]) == 2


def test_reconcile_does_not_mark_an_inflight_creation_missing(tmp_path):
    backend = BlockingCreateBackend()
    manager = _manager(tmp_path, backend)
    launch = _launch()
    create = threading.Thread(target=manager.create_worker, args=(launch,))
    create.start()
    assert backend.create_started.wait(1)

    assert manager.reconcile() == []
    assert manager.get(launch.worker_id)["state"] == "creating"

    backend.release_create.set()
    create.join(timeout=2)
    assert not create.is_alive()
    assert manager.get(launch.worker_id)["state"] == "ready"


def test_stop_during_creation_cannot_resurrect_or_leak_the_worker(tmp_path):
    backend = BlockingCreateBackend()
    manager = _manager(tmp_path, backend)
    launch = _launch()
    create = threading.Thread(target=manager.create_worker, args=(launch,))
    create.start()
    assert backend.create_started.wait(1)

    assert manager.stop_worker(launch.worker_id) is True
    create.join(timeout=2)

    assert not create.is_alive()
    assert manager.get(launch.worker_id)["state"] == "stopped"
    assert launch.worker_id not in backend.observed
    assert len(backend.stopped) == 2


def test_worker_prompts_never_reveal_verifier_acceptance(tmp_path):
    launch = _launch()

    initial = initial_worker_prompt(launch, deadline_at=123.0)
    follow_up = resume_worker_prompt(goal_id=launch.goal_id, feedback="fix source", remaining_seconds=30)

    assert launch.intent in initial
    assert launch.acceptance not in initial
    assert "not required for completion" in initial
    assert "no result content" in initial
    assert "summary" not in initial.lower()
    assert "fix source" in follow_up
    assert launch.goal_id in follow_up
    assert "no result content" in follow_up


def test_out_of_band_stop_cannot_be_overwritten_by_late_turn_result(tmp_path):
    backend = BlockingBackend()
    manager = _manager(tmp_path, backend)
    launch = _launch()
    manager.create_worker(launch)
    turn = threading.Thread(
        target=manager.run_worker,
        args=(launch.worker_id, "long turn"),
        kwargs={"resume": False},
    )
    turn.start()
    assert backend.turn_started.wait(1)

    assert manager.stop_worker(launch.worker_id) is True
    turn.join(timeout=2)

    assert not turn.is_alive()
    assert manager.get(launch.worker_id)["state"] == "stopped"
