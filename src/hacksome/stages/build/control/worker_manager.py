"""Lifecycle manager for one-Goal ephemeral Worker containers."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from hacksome.stages.build.agent_runtime import AgentSpec, RunResult, run_task
from hacksome.stages.build.agent_runtime.runner import AGENT_HOME_MOUNT
from hacksome.stages.build.paths import repository_agents_root
from hacksome.stages.build.control.control_client import BoundActor, HubClient
from hacksome.stages.build.control.run_logs import RunLogRecorder
from hacksome.stages.build.control.runtime_materialization import (
    account_package_docker_args,
    materialize_ephemeral_home,
    prepare_container_tree,
    wait_for_computer_server,
)
from hacksome.stages.build.control.runtime_store import CompanyLayout, atomic_write_json, file_lock, read_json
from hacksome.stages.build.control.team_store import TeamLayout


ACTIVE_STATES = ("creating", "ready", "running", "stopping")
TERMINAL = ("done", "cancelled")


class WorkerManagerError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerLaunch:
    """One Team-owned Worker command with durable lifecycle identity."""

    goal_id: str
    worker_id: str
    intent: str
    acceptance: str | None
    owner_department: str
    command_id: str


@dataclass(frozen=True)
class WorkerDefinition:
    company_id: str
    worker_id: str
    goal_id: str
    owner_department: str
    container_name: str
    home: Path
    workspace: Path
    company_dir: Path


class WorkerBackend(Protocol):
    def create(self, definition: WorkerDefinition) -> None: ...

    def run(
        self,
        definition: WorkerDefinition,
        prompt: str,
        *,
        resume_token: str | None,
    ) -> RunResult: ...

    def stop(self, definition: WorkerDefinition) -> None: ...

    def logs(self, definition: WorkerDefinition) -> str: ...

    def inspect(self, company_id: str) -> dict[str, str]: ...


class DockerWorkerBackend:
    """DooD backend using the existing Agent runtime/loadout seam."""

    def __init__(
        self,
        *,
        repo: str | Path,
        company_id: str,
        image: str | None = None,
        account_id: str | None = None,
        network: str | None = None,
        task_timeout: int = 21600,
        ready_timeout: float = 80.0,
        spec_path: str | Path | None = None,
        shared_mount_target: str = "/company",
        team_mode: bool = False,
    ):
        self.repo = Path(repo).resolve()
        self.company_id = company_id
        self.image = image or os.environ.get("CUA_AGENT_IMAGE", "foundagent/cua-agent:latest")
        self.account_id = account_id or company_id
        self.network = network or f"{company_id}_default"
        self.task_timeout = task_timeout
        self.ready_timeout = ready_timeout
        self.shared_mount_target = shared_mount_target
        self.team_mode = team_mode
        self.spec = AgentSpec.load(
            str(
                spec_path
                or repository_agents_root(self.repo)
                / "ephemeral"
                / "team-worker.yaml"
            )
        )

    @staticmethod
    def _run(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(args, capture_output=True, text=True)

    def create(self, definition: WorkerDefinition) -> None:
        definition.home.mkdir(parents=True, exist_ok=True)
        definition.workspace.mkdir(parents=True, exist_ok=True)
        materialize_ephemeral_home(
            self.spec,
            definition.home,
            account_dir=self.repo / "ops" / "build" / "accounts" / self.account_id,
            include_account_secrets=True,
        )
        prepare_container_tree(definition.workspace)
        self._run(["docker", "rm", "-f", definition.container_name])
        args = [
            "docker",
            "run",
            "-d",
            "--name",
            definition.container_name,
            "--network",
            self.network,
            "--label",
            (
                f"hacksome.team={definition.company_id}"
                if self.team_mode
                else f"foundagent.company={definition.company_id}"
            ),
            "--label",
            "foundagent.kind=worker",
            "--label",
            f"foundagent.goal={definition.goal_id}",
            "--label",
            f"foundagent.worker={definition.worker_id}",
            "-v",
            f"{definition.home}:{AGENT_HOME_MOUNT}",
            "-v",
            f"{definition.home / 'skills'}:/home/kasm-user/.agents/skills:ro",
            "-v",
            f"{definition.company_dir}:{self.shared_mount_target}",
            "-v",
            f"{definition.workspace}:/home/kasm-user/workspace",
            "-v",
            f"{self.repo / 'src' / 'hacksome'}:/opt/hacksome/hacksome:ro",
            "-e",
            "PYTHONPATH=/opt/hacksome",
            "-e",
            f"AGENT_KEY={definition.worker_id}",
            "-e",
            "AGENT_KIND=worker",
            "-e",
            f"GOAL_ID={definition.goal_id}",
            "-e",
            "HUB_URL=http://hub:8910",
        ]
        account_dir = self.repo / "ops" / "build" / "accounts" / self.account_id
        args += account_package_docker_args(account_dir)
        args += [self.image, "--wait"]
        result = self._run(args)
        if result.returncode != 0:
            raise WorkerManagerError(f"docker run failed: {result.stderr.strip()}")
        if not wait_for_computer_server(
            self._run,
            definition.container_name,
            timeout_secs=self.ready_timeout,
        ):
            self._run(["docker", "rm", "-f", definition.container_name])
            raise WorkerManagerError("computer-server not ready before timeout")

    def run(
        self,
        definition: WorkerDefinition,
        prompt: str,
        *,
        resume_token: str | None,
    ) -> RunResult:
        return run_task(
            self.spec,
            prompt,
            container=definition.container_name,
            timeout=self.task_timeout,
            resume_token=resume_token,
            extra_env={
                "AGENT_KEY": definition.worker_id,
                "AGENT_KIND": "worker",
                "GOAL_ID": definition.goal_id,
                "HUB_URL": "http://hub:8910",
            },
        )

    def stop(self, definition: WorkerDefinition) -> None:
        self._run(["docker", "stop", "-t", "15", definition.container_name])
        result = self._run(["docker", "rm", "-f", definition.container_name])
        if result.returncode != 0 and "No such container" not in result.stderr:
            raise WorkerManagerError(f"docker rm failed: {result.stderr.strip()}")

    def logs(self, definition: WorkerDefinition) -> str:
        result = self._run(
            ["docker", "logs", "--timestamps", definition.container_name]
        )
        if result.returncode != 0:
            return f"[container-log unavailable] {result.stderr.strip()}\n"
        return (
            "[stdout]\n"
            + (result.stdout or "")
            + "\n[stderr]\n"
            + (result.stderr or "")
        )

    def inspect(self, company_id: str) -> dict[str, str]:
        result = self._run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                (
                    f"label=hacksome.team={company_id}"
                    if self.team_mode
                    else f"label=foundagent.company={company_id}"
                ),
                "--filter",
                "label=foundagent.kind=worker",
                "--format",
                "{{.Label \"foundagent.worker\"}}\t{{.State}}",
            ]
        )
        if result.returncode != 0:
            raise WorkerManagerError(f"docker inspect failed: {result.stderr.strip()}")
        rows: dict[str, str] = {}
        for line in result.stdout.splitlines():
            worker_id, _, state = line.partition("\t")
            if worker_id:
                rows[worker_id] = state or "unknown"
        return rows


class WorkerManager:
    def __init__(
        self,
        root: str | Path,
        *,
        company_id: str,
        company_dir: str | Path,
        backend: WorkerBackend,
        max_workers: int = 5,
    ):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.company_id = company_id
        self.company_dir = Path(company_dir).resolve()
        self.backend = backend
        self.max_workers = max_workers
        self._lock_path = self.root / ".workers.lock"
        # ``backend.create`` deliberately runs outside the file lock because a
        # real CUA container can take tens of seconds to become ready.  Keep a
        # process-local lease so the periodic reconciler cannot mistake that
        # expected creation window for a crashed/missing Worker.  After a
        # manager restart the set is empty, so genuinely stale ``creating``
        # rows are still reconciled.
        self._lifecycle_guard = threading.Lock()
        self._creating: set[str] = set()
        self._running: set[str] = set()

    def _path(self, worker_id: str) -> Path:
        return self.root / f"{worker_id}.json"

    def _load(self, worker_id: str) -> dict:
        row = read_json(self._path(worker_id))
        if not isinstance(row, dict):
            raise WorkerManagerError(f"no such worker: {worker_id}")
        return row

    def _save(self, row: dict) -> None:
        row["updated_at"] = time.time()
        atomic_write_json(self._path(row["id"]), row)

    def list_workers(self) -> list[dict]:
        rows = []
        for path in self.root.glob("worker-*.json"):
            row = read_json(path)
            if isinstance(row, dict):
                rows.append(row)
        return sorted(rows, key=lambda row: row["created_at"])

    def get(self, worker_id: str) -> dict:
        return self._load(worker_id)

    def _definition(self, row: dict) -> WorkerDefinition:
        return WorkerDefinition(
            company_id=self.company_id,
            worker_id=row["id"],
            goal_id=row["goal_id"],
            owner_department=row["owner_department"],
            container_name=row["container_name"],
            home=self.root / row["id"] / "home",
            workspace=self.root / row["id"] / "workspace",
            company_dir=self.company_dir,
        )

    def create_worker(self, launch: WorkerLaunch) -> dict:
        with self._lifecycle_guard:
            with file_lock(self._lock_path):
                if self._path(launch.worker_id).is_file():
                    row = self._load(launch.worker_id)
                    if row["goal_id"] != launch.goal_id:
                        raise WorkerManagerError("worker id is already bound to another Goal")
                    if row["state"] not in ("creating", "create_failed", "missing"):
                        return row
                    retry_existing = True
                else:
                    retry_existing = False
                if retry_existing:
                    row["state"] = "creating"
                    self._save(row)
                else:
                    active = sum(
                        1 for row in self.list_workers() if row["state"] in ACTIVE_STATES
                    )
                    if active >= self.max_workers:
                        raise WorkerManagerError("worker concurrency limit reached")
                    now = time.time()
                    row = {
                        "id": launch.worker_id,
                        "goal_id": launch.goal_id,
                        "owner_department": launch.owner_department,
                        "container_name": f"{self.company_id}-{launch.worker_id}",
                        "state": "creating",
                        "session_token": None,
                        "turns": 0,
                        "continuity_unavailable": False,
                        "last_result": None,
                        "created_at": now,
                        "updated_at": now,
                    }
                    self._save(row)
                self._creating.add(launch.worker_id)
        definition = self._definition(row)
        try:
            self.backend.create(definition)
        except Exception as exc:
            with file_lock(self._lock_path):
                row = self._load(launch.worker_id)
                # A stop can legitimately remove the container while its
                # readiness probe is still running.  Preserve that terminal
                # lifecycle instead of resurrecting it as create_failed.
                if row["state"] in ("stopping", "stopped"):
                    return row
                row["state"] = "create_failed"
                row["last_error"] = str(exc)
                self._save(row)
            raise
        else:
            cleanup_late_container = False
            with file_lock(self._lock_path):
                row = self._load(launch.worker_id)
                if row["state"] in ("stopping", "stopped"):
                    cleanup_late_container = True
                else:
                    row["state"] = "ready"
                    row.pop("last_error", None)
                    self._save(row)
            if cleanup_late_container:
                # The stop may have arrived before ``docker run``.  Run it a
                # second time after create returns so no late container leaks.
                self.backend.stop(definition)
            return row
        finally:
            with self._lifecycle_guard:
                self._creating.discard(launch.worker_id)

    def run_worker(self, worker_id: str, prompt: str, *, resume: bool) -> RunResult:
        with self._lifecycle_guard:
            if worker_id in self._running:
                raise WorkerManagerError("worker already has an active turn")
            self._running.add(worker_id)
        try:
            return self._run_worker_claimed(worker_id, prompt, resume=resume)
        finally:
            with self._lifecycle_guard:
                self._running.discard(worker_id)

    def _run_worker_claimed(
        self, worker_id: str, prompt: str, *, resume: bool
    ) -> RunResult:
        with file_lock(self._lock_path):
            row = self._load(worker_id)
            if row["state"] not in ("ready", "running"):
                raise WorkerManagerError(f"worker cannot run from state {row['state']!r}")
            token = row.get("session_token") if resume else None
            if resume and token is None:
                row["continuity_unavailable"] = True
            row["state"] = "running"
            self._save(row)
        definition = self._definition(row)
        result = self.backend.run(definition, prompt, resume_token=token)
        timeout_cleanup_error = None
        if result.timed_out:
            # Killing the host-side `docker exec` client does not kill Codex,
            # test servers, or browser jobs inside the dedicated Worker
            # container. Retire the entire container before Hub can enqueue a
            # same-Goal resume. Home, workspace, and session files are host
            # mounts, so recreation preserves continuity without permitting
            # two turns to write `/project` concurrently.
            try:
                self.backend.stop(definition)
            except Exception as exc:  # noqa: BLE001 - persist cleanup failure for safe retry
                timeout_cleanup_error = str(exc)
        with file_lock(self._lock_path):
            row = self._load(worker_id)
            row["turns"] += 1
            if result.session_token:
                row["session_token"] = result.session_token
            row["last_result"] = {
                "ok": result.ok,
                "text": result.text,
                "error": result.error,
                "timed_out": result.timed_out,
                "session_token": result.session_token,
                "cost_usd": result.cost_usd,
                "usage": result.usage,
                "raw_tail": result.raw_tail,
            }
            # A deadline/cancel stop may race a long-running docker exec. The
            # late turn result is still auditable, but it must never resurrect
            # a lifecycle that the control path already stopped.
            if row["state"] not in ("stopping", "stopped"):
                if result.timed_out:
                    row["state"] = "missing" if timeout_cleanup_error is None else "create_failed"
                    row["last_error"] = (
                        "turn timed out; execution container retired"
                        if timeout_cleanup_error is None
                        else f"turn timed out; container cleanup failed: {timeout_cleanup_error}"
                    )
                else:
                    row["state"] = "ready"
            self._save(row)
        return result

    def stop_worker(self, worker_id: str) -> bool:
        with file_lock(self._lock_path):
            row = self._load(worker_id)
            if row["state"] == "stopped":
                return False
            row["state"] = "stopping"
            self._save(row)
        self.backend.stop(self._definition(row))
        with file_lock(self._lock_path):
            row = self._load(worker_id)
            row["state"] = "stopped"
            row["stopped_at"] = time.time()
            self._save(row)
        return True

    def container_logs(self, worker_id: str) -> str:
        row = self._load(worker_id)
        try:
            return self.backend.logs(self._definition(row))
        except Exception as exc:  # noqa: BLE001 — observability is best-effort
            return f"[container-log unavailable] {exc!r}\n"

    def reconcile(self) -> list[dict]:
        observed = self.backend.inspect(self.company_id)
        changes: list[dict] = []
        orphaned: list[tuple[str, WorkerDefinition]] = []
        with self._lifecycle_guard:
            creating = set(self._creating)
            running = set(self._running)
            with file_lock(self._lock_path):
                for row in self.list_workers():
                    if row["id"] in creating:
                        continue
                    actual = observed.get(row["id"])
                    if (
                        row["state"] == "running"
                        and row["id"] not in running
                        and actual is not None
                    ):
                        # A fresh manager cannot attach to the stdout/result of
                        # an exec owned by the previous manager. Retire the
                        # dedicated container before replaying its unreceipted
                        # command; otherwise both turns can mutate /project.
                        row["state"] = "stopping"
                        row["last_error"] = (
                            "orphaned active turn detected during reconcile"
                        )
                        self._save(row)
                        orphaned.append((row["id"], self._definition(row)))
                        continue
                    if row["state"] in ACTIVE_STATES and actual is None:
                        row["state"] = "missing"
                        row["last_error"] = "container missing during reconcile"
                        self._save(row)
                        changes.append({"worker_id": row["id"], "state": "missing"})
        for worker_id, definition in orphaned:
            cleanup_error = None
            try:
                self.backend.stop(definition)
            except Exception as exc:  # noqa: BLE001 - recovery must stay fail closed
                cleanup_error = str(exc)
            with file_lock(self._lock_path):
                row = self._load(worker_id)
                if row["state"] == "stopping":
                    row["state"] = (
                        "missing" if cleanup_error is None else "create_failed"
                    )
                    row["last_error"] = (
                        "orphaned active turn container retired"
                        if cleanup_error is None
                        else f"orphaned turn cleanup failed: {cleanup_error}"
                    )
                    self._save(row)
            changes.append({"worker_id": worker_id, "state": row["state"]})
        return changes


def initial_worker_prompt(launch: WorkerLaunch, *, deadline_at: float) -> str:
    """The Worker sees the Goal, not verifier-only acceptance criteria."""
    return (
        "WORKER TURN\n"
        f"goal_id: {launch.goal_id}\n"
        f"owner_department: {launch.owner_department}\n"
        f"deadline_at: {deadline_at}\n"
        "Complete this one Goal and no other work:\n"
        f"{launch.intent}\n\n"
        "Carry out the real work wherever this Goal requires. Maintain /company only when "
        "the work naturally changes durable shared Company State; a Company State file is "
        "not required for completion. When you believe the Goal is complete, call "
        "submit_result with no result content so the independent verifier can inspect it."
    )


def resume_worker_prompt(*, goal_id: str, feedback: str, remaining_seconds: float) -> str:
    return (
        "WORKER REWORK TURN\n"
        f"goal_id: {goal_id}\n"
        f"remaining_seconds: {max(0.0, remaining_seconds):.3f}\n"
        "The independent verifier rejected the previous result:\n"
        f"{feedback}\n\n"
        "Continue the same Goal in this same session and correct the real work wherever it "
        "lives. Maintain /company only if durable shared Company State actually changes. "
        "Do not switch to another Goal. Call submit_result with no result content when ready "
        "for another independent review."
    )


def team_initial_worker_prompt(launch: WorkerLaunch) -> str:
    """Self-contained Team Worker prompt; private acceptance is never present."""
    return (
        "HACKATHON WORKER TURN\n"
        f"goal_id: {launch.goal_id}\n\n"
        "Complete this one Goal and no other Goal:\n"
        f"{launch.intent}\n\n"
        "You have full tools and read/write access beneath /project. Inspect the real "
        "state first and perform the substantive work wherever the Goal requires. "
        "There is no deadline, fixed phase, standing Objective, or additional human "
        "approval. The files under /project/reference are initializer material, not "
        "immutable requirements.\n\n"
        "When the real work is ready for independent review, run exactly:\n"
        "python3 -m hacksome.stages.build.control.control_client submit_result \\\n"
        f"  --request-id 'result-{launch.goal_id}-<meaningful-revision>'\n\n"
        "submit_result accepts an empty business payload. Do not add a summary, path, "
        "URL, evidence list, or acceptance claim. Natural-language claims do not "
        "advance the Goal; only the command does."
    )


def team_resume_worker_prompt(*, goal_id: str, feedback: str) -> str:
    return (
        "HACKATHON WORKER REWORK TURN\n"
        f"goal_id: {goal_id}\n\n"
        "A fresh independent Verifier rejected the previous result after observing:\n"
        f"{feedback}\n\n"
        "Continue the same Goal in this same Worker, workspace, home, and session. "
        "Inspect the current real state, correct the substantive work, and do not switch "
        "to another Goal. When it is ready for another independent review, run exactly:\n"
        "python3 -m hacksome.stages.build.control.control_client submit_result \\\n"
        f"  --request-id 'result-{goal_id}-<meaningful-revision>'\n\n"
        "Use a new stable revision suffix only after a meaningful change."
    )


class WorkerCommandService:
    """Concurrent command consumer joining Hub commands to WorkerManager."""

    def __init__(
        self,
        layout: CompanyLayout | TeamLayout,
        *,
        manager: WorkerManager,
        hub: HubClient,
        max_workers: int = 5,
        team_mode: bool = False,
    ):
        self.layout = layout
        self.manager = manager
        self.hub = hub
        self.team_mode = team_mode
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="worker")
        self.stop_executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="worker-stop"
        )
        self._guard = threading.Lock()
        self._inflight: set[str] = set()
        self._worker_locks: dict[str, threading.Lock] = {}
        self.recorder = RunLogRecorder(layout.telemetry / "runs")
        (layout.workers / "receipts").mkdir(parents=True, exist_ok=True)

    def _receipt(self, command_id: str) -> Path:
        import hashlib

        digest = hashlib.sha256(command_id.encode("utf-8")).hexdigest()
        return self.layout.workers / "receipts" / f"{digest}.json"

    def _worker_lock(self, worker_id: str) -> threading.Lock:
        with self._guard:
            return self._worker_locks.setdefault(worker_id, threading.Lock())

    def scan_once(self) -> int:
        submitted = 0
        for path in sorted((self.layout.workers / "commands").glob("*.json")):
            command = read_json(path)
            if not isinstance(command, dict) or not isinstance(command.get("command_id"), str):
                continue
            command_id = command["command_id"]
            if self._receipt(command_id).is_file():
                continue
            with self._guard:
                if command_id in self._inflight:
                    continue
                self._inflight.add(command_id)
            executor = (
                self.stop_executor
                if command.get("action") == "stop_worker"
                else self.executor
            )
            executor.submit(self._process_guarded, command)
            submitted += 1
        return submitted

    def _process_guarded(self, command: dict) -> None:
        command_id = command["command_id"]
        try:
            worker_id = command.get("worker_id")
            if not isinstance(worker_id, str):
                raise WorkerManagerError("worker command has no worker_id")
            if command.get("action") == "stop_worker":
                # Stop is an out-of-band control path. It must not wait behind
                # the model turn it exists to terminate.
                result = self._process(command)
            else:
                with self._worker_lock(worker_id):
                    result = self._process(command)
            atomic_write_json(
                self._receipt(command_id),
                {"command_id": command_id, "processed_at": time.time(), "result": result},
            )
        except Exception as exc:  # noqa: BLE001 — unreceipted command is retried
            print(f"[worker-manager] command {command_id} failed: {exc!r}", flush=True)
        finally:
            with self._guard:
                self._inflight.discard(command_id)

    def _process(self, command: dict) -> dict:
        action = command.get("action")
        if action == "start_worker":
            return self._start(command)
        if action == "resume_worker":
            return self._resume(command)
        if action == "stop_worker":
            return self._stop(command)
        raise WorkerManagerError(f"unknown worker command action: {action!r}")

    def _start(self, command: dict) -> dict:
        launch = WorkerLaunch(
            goal_id=command["goal_id"],
            worker_id=command["worker_id"],
            intent=command["intent"],
            acceptance=None,
            owner_department=command["owner_department"],
            command_id=command["command_id"],
        )
        persisted_goal = read_json(self.layout.ledger / f"{launch.goal_id}.json")
        if isinstance(persisted_goal, dict) and persisted_goal.get("status") in TERMINAL:
            return {"stale": True, "goal_status": persisted_goal["status"]}
        try:
            self.manager.create_worker(launch)
        except Exception as exc:
            self.hub.call(
                "worker_start_failed",
                {
                    "goal_id": launch.goal_id,
                    "worker_id": launch.worker_id,
                    "reason": str(exc),
                },
                request_id=f"manager-start-failed:{command['command_id']}",
            )
            return {"reported_start_failure": str(exc)}
        try:
            goal = self.hub.call(
                "worker_started",
                {"goal_id": launch.goal_id, "worker_id": launch.worker_id},
                request_id=f"manager-started:{command['command_id']}",
            )
        except Exception:
            persisted_goal = read_json(self.layout.ledger / f"{launch.goal_id}.json")
            if not isinstance(persisted_goal, dict) or persisted_goal.get("status") not in TERMINAL:
                raise
            self.manager.stop_worker(launch.worker_id)
            self.hub.call(
                "worker_stopped",
                {"goal_id": launch.goal_id, "worker_id": launch.worker_id},
                request_id=f"manager-stopped-terminal-race:{command['command_id']}",
            )
            return {"terminal_race": persisted_goal["status"]}
        # A replay after the Worker already submitted is not another model turn.
        if goal["status"] != "running" or goal["worker_state"] != "running":
            return {"already_advanced": goal["status"]}
        prompt = (
            team_initial_worker_prompt(launch)
            if self.team_mode
            else initial_worker_prompt(launch, deadline_at=goal["deadline_at"])
        )
        return self._run_turn(launch.worker_id, launch.goal_id, prompt, resume=False)

    def _resume(self, command: dict) -> dict:
        persisted_goal = read_json(self.layout.ledger / f"{command['goal_id']}.json")
        if isinstance(persisted_goal, dict) and persisted_goal.get("status") in TERMINAL:
            return {"stale": True, "goal_status": persisted_goal["status"]}
        if not isinstance(persisted_goal, dict):
            raise WorkerManagerError("resume command has no persisted Goal")
        worker = self.manager.get(command["worker_id"])
        if worker.get("state") in ("missing", "create_failed"):
            # Reconcile a lost container without inventing a replacement
            # Worker: the id, home, workspace, Goal, and session files remain
            # bound to the original lifecycle.
            owner_department = worker.get("owner_department")
            if not isinstance(owner_department, str) or not owner_department:
                owner_department = persisted_goal.get("owner_department")
            if not isinstance(owner_department, str) or not owner_department:
                if self.team_mode:
                    owner_department = "lead"
                else:
                    raise WorkerManagerError(
                        "resume command has no bound owner department"
                    )
            self.manager.create_worker(
                WorkerLaunch(
                    goal_id=command["goal_id"],
                    worker_id=command["worker_id"],
                    intent=persisted_goal["intent"],
                    acceptance=None,
                    owner_department=owner_department,
                    command_id=command["command_id"],
                )
            )
        goal = self.hub.call(
            "worker_resumed",
            {
                "goal_id": command["goal_id"],
                "worker_id": command["worker_id"],
                "session_token": command.get("session_token"),
            },
            request_id=f"manager-resumed:{command['command_id']}",
        )
        if goal["status"] != "running" or goal["worker_state"] != "running":
            return {"already_advanced": goal["status"]}
        prompt = (
            team_resume_worker_prompt(
                goal_id=command["goal_id"],
                feedback=command["feedback"],
            )
            if self.team_mode
            else resume_worker_prompt(
                goal_id=command["goal_id"],
                feedback=command["feedback"],
                remaining_seconds=float(command.get("remaining_seconds") or 0),
            )
        )
        return self._run_turn(
            command["worker_id"], command["goal_id"], prompt, resume=True
        )

    def _run_turn(self, worker_id: str, goal_id: str, prompt: str, *, resume: bool) -> dict:
        started_at = time.time()
        try:
            result = self.manager.run_worker(worker_id, prompt, resume=resume)
        except Exception as exc:  # noqa: BLE001 — same Worker retry is Hub policy
            result = RunResult(ok=False, text="", error=str(exc), session_token=None)
        run_id = f"worker-turn-{goal_id}-{int(started_at * 1_000_000)}"
        container_log = self.manager.container_logs(worker_id)
        self.recorder.record(
            run_id=run_id,
            metadata={
                "kind": "worker_turn",
                "goal_id": goal_id,
                "worker_id": worker_id,
                "resume": resume,
                "started_at": started_at,
                "finished_at": time.time(),
                "ok": result.ok,
                "error": result.error,
                "timed_out": result.timed_out,
                "session_token": result.session_token,
                "usage": result.usage,
            },
            raw_output=result.raw_output,
            stderr=result.stderr,
            model_output=result.text or result.error or "",
            harness_log=(
                f"worker_id={worker_id}\n"
                f"goal_id={goal_id}\n"
                f"resume={resume}\n"
                f"ok={result.ok}\n"
            ),
            container_log=container_log,
        )
        goal = self.hub.call(
            "worker_turn_finished",
            {
                "goal_id": goal_id,
                "worker_id": worker_id,
                "ok": result.ok,
                "session_token": result.session_token,
                "error": result.error,
            },
            request_id=f"manager-turn-finished:{run_id}",
        )
        return {"run_id": run_id, "goal_status": goal["status"], "ok": result.ok}

    def _stop(self, command: dict) -> dict:
        try:
            self.manager.stop_worker(command["worker_id"])
        except WorkerManagerError as exc:
            if "no such worker" not in str(exc):
                raise
        goal = self.hub.call(
            "worker_stopped",
            {"goal_id": command["goal_id"], "worker_id": command["worker_id"]},
            request_id=f"manager-stopped:{command['command_id']}",
        )
        return {"goal_status": goal["status"], "worker_state": goal["worker_state"]}


def main() -> None:
    repo = Path(os.environ.get("FOUNDAGENT_HOST_REPO") or Path.cwd()).resolve()
    team_id = os.environ.get("TEAM", "hackathon-team")
    layout = TeamLayout.initialize(
        os.environ.get("TEAM_STATE_ROOT")
        or repo / "ops" / "build" / "state" / team_id
    )
    maximum = 1
    backend = DockerWorkerBackend(
        repo=repo,
        company_id=team_id,
        account_id=os.environ.get("ACCOUNT") or team_id,
        network=os.environ.get("TEAM_NETWORK") or f"{team_id}_default",
        task_timeout=int(os.environ.get("WORKER_TURN_TIMEOUT_SECS", "21600")),
        ready_timeout=float(os.environ.get("AGENT_READY_TIMEOUT_SECS", "80")),
        spec_path=repository_agents_root(repo) / "ephemeral" / "team-worker.yaml",
        shared_mount_target="/project",
        team_mode=True,
    )
    manager = WorkerManager(
        layout.workers,
        company_id=team_id,
        company_dir=layout.project,
        backend=backend,
        max_workers=maximum,
    )
    hub = HubClient(
        actor=BoundActor("manager", "worker-manager"),
        timeout=float(os.environ.get("HUB_CLIENT_TIMEOUT_SECS", "30")),
    )
    service = WorkerCommandService(
        layout,
        manager=manager,
        hub=hub,
        max_workers=maximum,
        team_mode=True,
    )
    poll = float(os.environ.get("WORKER_MANAGER_POLL_SECS", "0.25"))
    print(f"[worker-manager] ready team={team_id} root={layout.root}", flush=True)
    next_reconcile = 0.0
    while True:
        now = time.monotonic()
        if now >= next_reconcile:
            try:
                changes = manager.reconcile()
                for change in changes:
                    print(f"[worker-manager] reconciled {change}", flush=True)
            except Exception as exc:  # noqa: BLE001 — command replay still provides recovery
                print(f"[worker-manager] reconcile failed: {exc!r}", flush=True)
            next_reconcile = now + float(
                os.environ.get("WORKER_RECONCILE_SECS", "5")
            )
        service.scan_once()
        time.sleep(max(0.05, poll))


if __name__ == "__main__":
    main()
