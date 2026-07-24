import threading

from agent.runtimes.base import RunResult
from orchestration.control_client import BoundActor
from orchestration.department_provisioner import DepartmentProvisionerService
from orchestration.departments import DepartmentCatalog
from orchestration.runtime_store import CompanyLayout, atomic_write_json
from orchestration.scheduler import WorkerLaunch
from orchestration.verifier_runtime import VerifierCommandService, verifier_prompt
from orchestration.worker_manager import WorkerCommandService


class FakeHub:
    def __init__(self):
        self.calls = []

    def call(self, method, payload=None, *, request_id=None):
        self.calls.append((method, payload, request_id))
        if method == "worker_started":
            return {
                "id": payload["goal_id"],
                "status": "running",
                "worker_state": "running",
                "deadline_at": 123,
            }
        if method == "worker_resumed":
            return {
                "id": payload["goal_id"],
                "status": "running",
                "worker_state": "running",
            }
        if method == "worker_turn_finished":
            return {"status": "verifying", "worker_state": "awaiting_verdict"}
        return {"ok": True, **(payload or {})}


class FakeDepartmentBackend:
    def __init__(self):
        self.definitions = []

    def ensure(self, definition):
        self.definitions.append(definition)
        return definition.container_name


class FlakyDepartmentBackend(FakeDepartmentBackend):
    def __init__(self):
        super().__init__()
        self.failures = 1

    def ensure(self, definition):
        self.definitions.append(definition)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("docker temporarily unavailable")
        return definition.container_name


class FakeWorkerManager:
    def __init__(self):
        self.created = []
        self.runs = []
        self.stops = []
        self.workers = {}

    def create_worker(self, launch):
        self.created.append(launch)
        self.workers[launch.worker_id] = {
            "id": launch.worker_id,
            "goal_id": launch.goal_id,
            "owner_department": launch.owner_department,
            "state": "ready",
        }
        return {"id": launch.worker_id}

    def get(self, worker_id):
        return dict(self.workers[worker_id])

    def run_worker(self, worker_id, prompt, *, resume):
        self.runs.append((worker_id, prompt, resume))
        return RunResult(
            ok=True,
            text="submitted",
            error=None,
            session_token="session-1",
            raw_output="full output",
            stderr="",
        )

    def stop_worker(self, worker_id):
        self.stops.append(worker_id)
        return True

    def container_logs(self, worker_id):
        return f"container output for {worker_id}"


class FakeVerifierBackend:
    def __init__(self, review_path):
        self.review_path = review_path
        self.created = []
        self.stopped = []
        self.prompts = []

    def create(self, definition):
        self.created.append(definition)

    def run(self, definition, prompt):
        self.prompts.append(prompt)
        review = {
            "id": definition.review_id,
            "status": "passed",
            "verdict": "PASS",
            "instance_id": definition.instance_id,
            "instance_state": "stopping",
        }
        atomic_write_json(self.review_path, review)
        return RunResult(
            ok=True,
            text="PASS recorded",
            error=None,
            session_token=None,
            raw_output="complete verifier stream",
            stderr="",
        )

    def stop(self, definition):
        self.stopped.append(definition)

    def logs(self, definition):
        return f"container output for {definition.instance_id}"


class BlockingVerifierBackend:
    def __init__(self):
        self.created = []
        self.turn_started = threading.Event()
        self.release_turn = threading.Event()
        self.stopped = []

    def create(self, definition):
        self.created.append(definition)

    def run(self, definition, prompt):
        self.turn_started.set()
        assert self.release_turn.wait(2)
        return RunResult(
            ok=False,
            text="",
            error="verifier container stopped",
            session_token=None,
        )

    def stop(self, definition):
        self.stopped.append(definition)
        self.release_turn.set()

    def logs(self, definition):
        return f"container output for {definition.instance_id}"


class BlockingCreateVerifierBackend:
    def __init__(self):
        self.create_started = threading.Event()
        self.release_create = threading.Event()
        self.created = []
        self.stopped = []
        self.runs = []

    def create(self, definition):
        self.created.append(definition)
        self.create_started.set()
        assert self.release_create.wait(2)

    def run(self, definition, prompt):
        self.runs.append((definition, prompt))
        raise AssertionError("a cancelled review must not run")

    def stop(self, definition):
        self.stopped.append(definition)

    def logs(self, definition):
        return f"container output for {definition.instance_id}"


def test_department_provisioner_accepts_only_fixed_creation_command(tmp_path):
    layout = CompanyLayout.initialize(tmp_path / "new-company")
    catalog = DepartmentCatalog.load("agents/departments")
    creation_id = "department-request"
    atomic_write_json(
        layout.departments / "requests" / f"{creation_id}.json",
        {"id": creation_id, "option_id": "builder", "status": "provisioning"},
    )
    command = {
        "command_id": "provision:builder",
        "action": "provision_department",
        "creation_id": creation_id,
        "template_id": "builder",
    }
    atomic_write_json(layout.departments / "commands" / "builder.json", command)
    backend = FakeDepartmentBackend()
    hub = FakeHub()
    service = DepartmentProvisionerService(
        layout,
        company_id="new-company",
        catalog=catalog,
        backend=backend,
        hub=hub,
    )

    assert service.process_once() == 1
    assert service.process_once() == 0
    assert backend.definitions[0].template.id == "builder"
    assert backend.definitions[0].home == layout.sessions / "builder"
    assert hub.calls[0][0] == "department_started"
    assert not hasattr(service, "retire")


def test_department_provision_failure_retries_same_command_and_container(tmp_path):
    layout = CompanyLayout.initialize(tmp_path / "new-company")
    catalog = DepartmentCatalog.load("agents/departments")
    creation_id = "department-request"
    atomic_write_json(
        layout.departments / "requests" / f"{creation_id}.json",
        {"id": creation_id, "option_id": "researcher", "status": "provisioning"},
    )
    command = {
        "command_id": "provision:researcher",
        "action": "provision_department",
        "creation_id": creation_id,
        "template_id": "researcher",
    }
    atomic_write_json(layout.departments / "commands" / "researcher.json", command)
    backend = FlakyDepartmentBackend()
    hub = FakeHub()
    service = DepartmentProvisionerService(
        layout,
        company_id="new-company",
        catalog=catalog,
        backend=backend,
        hub=hub,
    )

    assert service.process_once() == 0
    assert not service._receipt(command["command_id"]).exists()
    assert service.process_once() == 1
    assert service.process_once() == 0
    assert [call[0] for call in hub.calls] == [
        "department_provision_failed",
        "department_started",
    ]
    assert len(backend.definitions) == 2
    assert backend.definitions[0].container_name == backend.definitions[1].container_name


def test_worker_command_runs_one_goal_and_reports_complete_turn(tmp_path):
    layout = CompanyLayout.initialize(tmp_path / "new-company")
    manager = FakeWorkerManager()
    hub = FakeHub()
    service = WorkerCommandService(layout, manager=manager, hub=hub, max_workers=5)
    command = {
        "version": 1,
        "command_id": "start:goal-1:1",
        "action": "start_worker",
        "goal_id": "goal-1",
        "worker_id": "worker-1",
        "owner_department": "builder",
        "intent": "ship the artifact",
    }

    result = service._process(command)

    assert result["ok"] is True
    assert len(manager.created) == 1
    assert manager.runs[0][0] == "worker-1"
    assert "ship the artifact" in manager.runs[0][1]
    assert [call[0] for call in hub.calls] == ["worker_started", "worker_turn_finished"]
    run_dir = layout.telemetry / "runs" / result["run_id"]
    assert (run_dir / "runtime.jsonl").read_text() == "full output"
    assert (run_dir / "container.log").read_text() == "container output for worker-1"
    assert "goal_id=goal-1" in (run_dir / "harness.log").read_text()


def test_team_resume_recreates_missing_worker_from_lifecycle_owner(tmp_path):
    layout = CompanyLayout.initialize(tmp_path / "hackathon-team")
    atomic_write_json(
        layout.ledger / "goal-1.json",
        {
            "id": "goal-1",
            "intent": "keep improving the product",
            "status": "awaiting_rework",
        },
    )
    manager = FakeWorkerManager()
    manager.create_worker(
        WorkerLaunch(
            goal_id="goal-1",
            worker_id="worker-1",
            intent="keep improving the product",
            acceptance=None,
            owner_department="lead",
            command_id="start:goal-1:1",
        )
    )
    manager.created.clear()
    manager.workers["worker-1"]["state"] = "missing"
    hub = FakeHub()
    service = WorkerCommandService(
        layout,
        manager=manager,
        hub=hub,
        max_workers=1,
        team_mode=True,
    )

    result = service._process(
        {
            "version": 1,
            "command_id": "resume:goal-1:1",
            "action": "resume_worker",
            "goal_id": "goal-1",
            "worker_id": "worker-1",
            "feedback": "continue from the real state",
            "session_token": "session-1",
        }
    )

    assert result["ok"] is True
    assert manager.created[0].owner_department == "lead"
    assert len(manager.runs) == 1
    assert manager.runs[0][0] == "worker-1"
    assert manager.runs[0][2] is True
    assert "continue from the real state" in manager.runs[0][1]
    assert [call[0] for call in hub.calls] == [
        "worker_resumed",
        "worker_turn_finished",
    ]


def test_verifier_instance_handles_one_review_then_is_stopped(tmp_path):
    layout = CompanyLayout.initialize(tmp_path / "new-company")
    review_id = "review-one"
    review_path = layout.reviews / f"{review_id}.json"
    atomic_write_json(
        review_path,
        {
            "id": review_id,
            "status": "running",
            "instance_id": "verifier-1-1",
            "instance_state": "running",
        },
    )
    backend = FakeVerifierBackend(review_path)
    hub = FakeHub()
    service = VerifierCommandService(
        layout,
        company_id="new-company",
        backend=backend,
        hub=hub,
        max_instances=3,
    )
    command = {
        "version": 1,
        "command_id": "start:verifier-1-1",
        "action": "start_verifier",
        "review_id": review_id,
        "review_seq": 1,
        "instance_id": "verifier-1-1",
        "kind": "goal_result",
        "subject_id": "goal-1",
        "payload": {
            "goal_id": "goal-1",
            "owner_department": "builder",
            "intent": "ship result",
            "acceptance": "must be real",
            "deadline_at": 999.0,
        },
    }

    result = service._process(command)

    assert result["verdict_recorded"] == "PASS"
    assert len(backend.created) == len(backend.stopped) == 1
    assert "must be real" in backend.prompts[0]
    assert "provided no summary or evidence index" in backend.prompts[0]
    assert "authenticated external accounts" in backend.prompts[0]
    assert "A /company artifact is optional" in backend.prompts[0]
    assert "never execute, repair, publish" in backend.prompts[0]
    assert hub.calls[0][0] == "verifier_instance_stopped"
    run_dir = layout.telemetry / "runs" / result["run_id"]
    assert (run_dir / "container.log").read_text() == "container output for verifier-1-1"
    assert "review_id=review-one" in (run_dir / "harness.log").read_text()


def test_verifier_stop_bypasses_a_running_review_lock(tmp_path):
    layout = CompanyLayout.initialize(tmp_path / "new-company")
    review_id = "review-blocking"
    instance_id = "verifier-1-1"
    atomic_write_json(
        layout.reviews / f"{review_id}.json",
        {
            "id": review_id,
            "status": "running",
            "instance_id": instance_id,
            "instance_state": "running",
        },
    )
    backend = BlockingVerifierBackend()
    hub = FakeHub()
    service = VerifierCommandService(
        layout,
        company_id="new-company",
        backend=backend,
        hub=hub,
        max_instances=1,
    )
    start = {
        "command_id": "start:blocking",
        "action": "start_verifier",
        "review_id": review_id,
        "review_seq": 1,
        "instance_id": instance_id,
        "kind": "goal_result",
        "subject_id": "goal-1",
        "payload": {
            "goal_id": "goal-1",
            "owner_department": "builder",
            "intent": "x",
            "acceptance": None,
            "deadline_at": 999.0,
        },
    }
    stop = {
        "command_id": "stop:blocking",
        "action": "stop_verifier",
        "review_id": review_id,
        "instance_id": instance_id,
    }
    running = threading.Thread(target=service._process_guarded, args=(start,))
    stopping = threading.Thread(target=service._process_guarded, args=(stop,))

    running.start()
    assert backend.turn_started.wait(1)
    stopping.start()
    stopping.join(timeout=1)
    running.join(timeout=2)

    assert not stopping.is_alive()
    assert not running.is_alive()
    assert backend.stopped


def test_verifier_cancel_during_create_releases_slot_only_after_late_cleanup(tmp_path):
    layout = CompanyLayout.initialize(tmp_path / "new-company")
    review_id = "review-creating"
    instance_id = "verifier-1-1"
    review_path = layout.reviews / f"{review_id}.json"
    atomic_write_json(
        review_path,
        {
            "id": review_id,
            "status": "running",
            "instance_id": instance_id,
            "instance_state": "running",
        },
    )
    backend = BlockingCreateVerifierBackend()
    hub = FakeHub()
    service = VerifierCommandService(
        layout,
        company_id="new-company",
        backend=backend,
        hub=hub,
        max_instances=1,
    )
    start = {
        "command_id": "start:creating",
        "action": "start_verifier",
        "review_id": review_id,
        "review_seq": 1,
        "instance_id": instance_id,
        "kind": "goal_result",
        "subject_id": "goal-1",
        "payload": {
            "goal_id": "goal-1",
            "owner_department": "builder",
            "intent": "x",
            "acceptance": None,
            "deadline_at": 999.0,
        },
    }
    stop = {
        "command_id": "stop:creating",
        "action": "stop_verifier",
        "review_id": review_id,
        "instance_id": instance_id,
    }
    starting = threading.Thread(target=service._process_guarded, args=(start,))
    stopping = threading.Thread(target=service._process_guarded, args=(stop,))
    starting.start()
    assert backend.create_started.wait(1)
    atomic_write_json(
        review_path,
        {
            "id": review_id,
            "status": "cancelled",
            "instance_id": instance_id,
            "instance_state": "stopping",
        },
    )
    stopping.start()

    stopping.join(timeout=0.05)
    assert stopping.is_alive()
    assert hub.calls == []
    backend.release_create.set()
    starting.join(timeout=2)
    stopping.join(timeout=2)

    assert not starting.is_alive()
    assert not stopping.is_alive()
    assert backend.runs == []
    assert len(backend.stopped) == 2
    assert [call[0] for call in hub.calls] == [
        "verifier_instance_stopped",
        "verifier_instance_stopped",
    ]


def test_verifier_prompt_has_no_resident_or_business_methods():
    prompt = verifier_prompt(
        {
            "review_id": "review-1",
            "kind": "company_objective",
            "subject_id": "ceo",
            "payload": {"text": "Build value", "current": None},
        }
    )

    assert "submit_verdict" in prompt
    assert "one review" in prompt
    assert "create Goals" in prompt
    assert "Notes" in prompt


def test_bound_actor_headers_never_derive_from_business_payload():
    headers = BoundActor("department", "researcher", department_id="researcher").headers()

    assert headers["X-Foundagent-Actor-Id"] == "researcher"
    assert "from" not in headers
