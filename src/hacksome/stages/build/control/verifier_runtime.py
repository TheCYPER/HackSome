"""Ephemeral V7 verifier containers and their maximum-three command service."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from typing import Callable

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
from hacksome.stages.build.control.runtime_store import CompanyLayout, atomic_write_json, read_json
from hacksome.stages.build.control.team_store import TeamLayout


class VerifierRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class VerifierDefinition:
    company_id: str
    review_id: str
    instance_id: str
    container_name: str
    home: Path
    workspace: Path
    company_dir: Path


class VerifierBackend(Protocol):
    def create(self, definition: VerifierDefinition) -> None: ...

    def run(self, definition: VerifierDefinition, prompt: str) -> RunResult: ...

    def stop(self, definition: VerifierDefinition) -> None: ...

    def logs(self, definition: VerifierDefinition) -> str: ...


class DockerVerifierBackend:
    def __init__(
        self,
        *,
        repo: str | Path,
        company_id: str,
        account_id: str | None = None,
        image: str | None = None,
        network: str | None = None,
        task_timeout: int = 3600,
        ready_timeout: float = 80.0,
        spec_path: str | Path | None = None,
        shared_mount_target: str = "/company",
        team_mode: bool = False,
    ):
        self.repo = Path(repo).resolve()
        self.company_id = company_id
        self.account_id = account_id or company_id
        self.image = image or os.environ.get("CUA_AGENT_IMAGE", "foundagent/cua-agent:latest")
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
                / "team-verifier.yaml"
            )
        )

    @staticmethod
    def _run(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(args, capture_output=True, text=True)

    def create(self, definition: VerifierDefinition) -> None:
        definition.home.mkdir(parents=True, exist_ok=True)
        definition.workspace.mkdir(parents=True, exist_ok=True)
        account_dir = self.repo / "ops" / "build" / "accounts" / self.account_id
        materialize_ephemeral_home(
            self.spec,
            definition.home,
            account_dir=account_dir,
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
            "foundagent.kind=verifier",
            "--label",
            f"foundagent.review={definition.review_id}",
            "--label",
            f"foundagent.verifier={definition.instance_id}",
            "-v",
            f"{definition.home}:{AGENT_HOME_MOUNT}",
            "-v",
            f"{definition.home / 'skills'}:/home/kasm-user/.agents/skills:ro",
            "-v",
            f"{definition.company_dir}:{self.shared_mount_target}:ro",
            "-v",
            f"{definition.workspace}:/home/kasm-user/workspace",
            "-v",
            f"{self.repo / 'src' / 'hacksome'}:/opt/hacksome/hacksome:ro",
            "-e",
            "PYTHONPATH=/opt/hacksome",
            "-e",
            f"AGENT_KEY={definition.instance_id}",
            "-e",
            "AGENT_KIND=verifier",
            "-e",
            f"REVIEW_ID={definition.review_id}",
            "-e",
            "HUB_URL=http://hub:8910",
        ]
        args += account_package_docker_args(account_dir)
        args += [self.image, "--wait"]
        result = self._run(args)
        if result.returncode != 0:
            raise VerifierRuntimeError(f"docker run failed: {result.stderr.strip()}")
        if not wait_for_computer_server(
            self._run,
            definition.container_name,
            timeout_secs=self.ready_timeout,
        ):
            self._run(["docker", "rm", "-f", definition.container_name])
            raise VerifierRuntimeError("computer-server not ready before timeout")

    def run(self, definition: VerifierDefinition, prompt: str) -> RunResult:
        return run_task(
            self.spec,
            prompt,
            container=definition.container_name,
            timeout=self.task_timeout,
            extra_env={
                "AGENT_KEY": definition.instance_id,
                "AGENT_KIND": "verifier",
                "REVIEW_ID": definition.review_id,
                "HUB_URL": "http://hub:8910",
            },
        )

    def stop(self, definition: VerifierDefinition) -> None:
        self._run(["docker", "stop", "-t", "10", definition.container_name])
        result = self._run(["docker", "rm", "-f", definition.container_name])
        if result.returncode != 0 and "No such container" not in result.stderr:
            raise VerifierRuntimeError(f"docker rm failed: {result.stderr.strip()}")
        shutil.rmtree(definition.home, ignore_errors=True)

    def logs(self, definition: VerifierDefinition) -> str:
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


def verifier_prompt(command: dict) -> str:
    payload = command["payload"]
    common = (
        "VERIFIER REVIEW\n"
        f"review_id: {command['review_id']}\n"
        f"review_kind: {command['kind']}\n"
        f"subject_id: {command['subject_id']}\n\n"
        "Judge this one review independently. You may read /company, which is read-only. "
        "Do not execute the work, create Goals, change Objectives, send messages, or review "
        "anything else. You have no Notes, Inbox, heartbeat, or cross-review session. "
        "Before finishing, call submit_verdict exactly once with PASS or FAIL "
        "and a concrete reason.\n\n"
    )
    if command["kind"] == "company_objective":
        return (
            common
            + f"Proposed Company Objective:\n{payload.get('text', '')}\n\n"
            + f"Current Company Objective:\n{payload.get('current') or '(none)'}\n\n"
            + "Company Objective rubric (every item is load-bearing):\n"
            + "1. It names one concrete buyer/user and a real trigger, not a broad market label.\n"
            + "2. It explains the status quo, including manual work, competitors, free alternatives, or doing nothing.\n"
            + "3. Traceable costly behavior supports demand; trends, interest, risk lists, internal demos, and ease of building cannot carry PASS.\n"
            + "4. It identifies a specific unresolved gap and a credible reason to choose this offer after trust, payment, switching, and learning friction.\n"
            + "5. The company has a usable path to its first real users and a smallest real delivery appropriate to the business form.\n"
            + "6. An observable result can strengthen, weaken, or overturn the thesis, and facts, assumptions, and unknowns are not blurred.\n"
            + "7. It is one durable direction sized for this company, not a Goal list or unrelated portfolio. A revision must have an evidence-backed reason to replace the active Objective.\n"
            + "Fail closed when a load-bearing source is absent, inaccessible, contradictory, or does not support the claim. Never lower the bar because the bet is cheap or fast.\n"
        )
    if command["kind"] == "department_objective":
        return (
            common
            + f"Proposed Department Objective:\n{payload.get('text', '')}\n\n"
            + f"Current Department Objective:\n{payload.get('current') or '(none)'}\n\n"
            + "Department Objective rubric:\n"
            + "1. It defines one durable ownership outcome aligned with the Company Objective and this Department's recurring function.\n"
            + "2. It is sized for the Department and makes observable progress possible within weeks.\n"
            + "3. It is not a one-off Goal, a Goal list, an execution recipe, or permission to wait.\n"
            + "4. A revision has an evidence-backed reason to replace the current Objective.\n"
            + "Do not force the Company Objective's external market-demand rubric onto an internal Department Objective, and do not reject merely because you would choose a different valid operating direction.\n"
        )
    return (
        common
        + f"Goal intent:\n{payload.get('intent', '')}\n\n"
        + f"Additional acceptance information:\n{payload.get('acceptance') or '(none)'}\n\n"
        + "Goal result rubric:\n"
        + "- The Worker has only declared completion; it provided no summary or evidence index. Independently determine how to verify the Goal.\n"
        + "- Inspect the real result wherever the Goal implies it should exist: read-only /company, the public web, or authenticated external accounts available to this runtime.\n"
        + "- A /company artifact is optional. Never fail merely because the Worker created no Company State file or supplied no path.\n"
        + "- PASS only when independently observed evidence satisfies the Goal intent and all supplied acceptance information.\n"
        + "- FAIL closed when evidence is missing, inaccessible, contradictory, or incomplete. Give concrete repair feedback for the same Worker.\n"
        + "- Inspect only: never execute, repair, publish, or otherwise modify the work or any external system.\n"
        + "- Judge completion, not prose style, preferred implementation, or whether you could improve the work yourself.\n"
        + "- In the verdict reason, state what you actually inspected and why it supports PASS or FAIL.\n"
    )


def team_verifier_prompt(command: dict) -> str:
    if command.get("kind") != "goal_result":
        raise VerifierRuntimeError("Team Verifier accepts only goal_result reviews")
    payload = command["payload"]
    return (
        "HACKATHON VERIFIER REVIEW\n"
        f"review_id: {command['review_id']}\n"
        f"goal_id: {payload.get('goal_id', command['subject_id'])}\n\n"
        f"Goal intent:\n{payload.get('intent', '')}\n\n"
        "Private acceptance context (the Worker did not see this):\n"
        f"{payload.get('acceptance') or '(none)'}\n\n"
        "Independently inspect the actual result wherever the Goal says it should "
        "exist. Canonical /project is mounted read-only. You may run tests, inspect "
        "files, use the browser, and inspect authenticated external systems, but you "
        "must not create, edit, repair, publish, delete, or otherwise mutate the "
        "project or any external result.\n\n"
        "PASS only when observed evidence satisfies the Goal intent and all supplied "
        "acceptance context. FAIL when evidence is missing, inaccessible, contradictory, "
        "or incomplete, and give concrete observed feedback for the same Worker.\n\n"
        "Submit exactly one verdict by running:\n"
        "python3 -m hacksome.stages.build.control.control_client submit_verdict \\\n"
        "  --json '{\"verdict\":\"PASS\",\"reason\":\"specific observed evidence\"}' \\\n"
        f"  --request-id 'verdict-{command['review_id']}'\n\n"
        "Use exactly PASS or FAIL. Natural-language claims do not change review state."
    )


class VerifierCommandService:
    def __init__(
        self,
        layout: CompanyLayout | TeamLayout,
        *,
        company_id: str,
        backend: VerifierBackend,
        hub: HubClient,
        max_instances: int = 3,
        prompt_builder: Callable[[dict], str] = verifier_prompt,
    ):
        self.layout = layout
        self.company_id = company_id
        self.backend = backend
        self.hub = hub
        self.prompt_builder = prompt_builder
        self.executor = ThreadPoolExecutor(
            max_workers=max_instances, thread_name_prefix="verifier"
        )
        self.stop_executor = ThreadPoolExecutor(
            max_workers=max_instances, thread_name_prefix="verifier-stop"
        )
        self._guard = threading.Lock()
        self._inflight: set[str] = set()
        self._instance_locks: dict[str, threading.Lock] = {}
        self._creating: dict[str, threading.Event] = {}
        self._stop_requested: set[str] = set()
        self.recorder = RunLogRecorder(layout.telemetry / "runs")
        (layout.reviews / "receipts").mkdir(parents=True, exist_ok=True)

    def _receipt(self, command_id: str) -> Path:
        digest = hashlib.sha256(command_id.encode("utf-8")).hexdigest()
        return self.layout.reviews / "receipts" / f"{digest}.json"

    def _instance_lock(self, instance_id: str) -> threading.Lock:
        with self._guard:
            return self._instance_locks.setdefault(instance_id, threading.Lock())

    def _definition(self, command: dict) -> VerifierDefinition:
        instance_id = command["instance_id"]
        root = self.layout.reviews / "homes" / instance_id
        shared_dir = (
            self.layout.project
            if hasattr(self.layout, "project")
            else self.layout.company
        )
        return VerifierDefinition(
            company_id=self.company_id,
            review_id=command["review_id"],
            instance_id=instance_id,
            container_name=f"{self.company_id}-{instance_id}",
            home=root,
            workspace=root / "workspace",
            company_dir=shared_dir,
        )

    def scan_once(self) -> int:
        submitted = 0
        for path in sorted((self.layout.reviews / "commands").glob("*.json")):
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
                if command.get("action") == "stop_verifier"
                else self.executor
            )
            executor.submit(self._process_guarded, command)
            submitted += 1
        return submitted

    def _process_guarded(self, command: dict) -> None:
        command_id = command["command_id"]
        try:
            if command.get("action") == "stop_verifier":
                # Cancellation/deadline control cannot queue behind the review
                # process it needs to terminate.
                result = self._process(command)
            else:
                with self._instance_lock(command["instance_id"]):
                    result = self._process(command)
            atomic_write_json(
                self._receipt(command_id),
                {"command_id": command_id, "processed_at": time.time(), "result": result},
            )
        except Exception as exc:  # noqa: BLE001 — unreceipted command is retried
            print(f"[verifier-manager] command {command_id} failed: {exc!r}", flush=True)
        finally:
            with self._guard:
                self._inflight.discard(command_id)

    def _process(self, command: dict) -> dict:
        if command.get("action") == "start_verifier":
            return self._start(command)
        if command.get("action") == "stop_verifier":
            return self._stop(command)
        raise VerifierRuntimeError(f"unknown verifier action: {command.get('action')!r}")

    def _start(self, command: dict) -> dict:
        definition = self._definition(command)
        review = read_json(self.layout.reviews / f"{command['review_id']}.json")
        if (
            not isinstance(review, dict)
            or review.get("status") != "running"
            or review.get("instance_id") != command["instance_id"]
        ):
            return {"stale": True}
        create_done = threading.Event()
        with self._guard:
            if command["instance_id"] in self._stop_requested:
                return {"stale": True}
            self._creating[command["instance_id"]] = create_done
        try:
            try:
                self.backend.create(definition)
            finally:
                with self._guard:
                    self._creating.pop(command["instance_id"], None)
                create_done.set()

            # Cancellation/deadline may arrive while the container is coming
            # up.  Never run an invalidated review, and destroy the late
            # container before releasing its verifier-pool seat.
            review = read_json(self.layout.reviews / f"{command['review_id']}.json")
            if (
                not isinstance(review, dict)
                or review.get("status") != "running"
                or review.get("instance_id") != command["instance_id"]
                or review.get("instance_state") != "running"
            ):
                self.backend.stop(definition)
                self.hub.call(
                    "verifier_instance_stopped",
                    {
                        "review_id": command["review_id"],
                        "instance_id": command["instance_id"],
                    },
                    request_id=f"verifier-stopped:{command['instance_id']}",
                )
                return {"stale": True, "late_container_stopped": True}
            started_at = time.time()
            result = self.backend.run(definition, self.prompt_builder(command))
        except Exception as exc:  # noqa: BLE001 — requeue with a fresh instance
            result = RunResult(ok=False, text="", error=str(exc), session_token=None)
            started_at = time.time()
        run_id = f"verifier-review-{command['review_id']}-{command['instance_id']}"
        try:
            container_log = self.backend.logs(definition)
        except Exception as exc:  # noqa: BLE001 — observability is best-effort
            container_log = f"[container-log unavailable] {exc!r}\n"
        self.recorder.record(
            run_id=run_id,
            metadata={
                "kind": "verifier_review",
                "review_id": command["review_id"],
                "instance_id": command["instance_id"],
                "review_kind": command["kind"],
                "started_at": started_at,
                "finished_at": time.time(),
                "ok": result.ok,
                "error": result.error,
                "usage": result.usage,
            },
            raw_output=result.raw_output,
            stderr=result.stderr,
            model_output=result.text or result.error or "",
            harness_log=(
                f"review_id={command['review_id']}\n"
                f"instance_id={command['instance_id']}\n"
                f"review_kind={command['kind']}\n"
                f"ok={result.ok}\n"
            ),
            container_log=container_log,
        )
        review = read_json(self.layout.reviews / f"{command['review_id']}.json")
        self.backend.stop(definition)
        if isinstance(review, dict) and review.get("status") in ("passed", "failed", "cancelled"):
            self.hub.call(
                "verifier_instance_stopped",
                {"review_id": command["review_id"], "instance_id": command["instance_id"]},
                request_id=f"verifier-stopped:{command['instance_id']}",
            )
            return {"run_id": run_id, "verdict_recorded": review.get("verdict")}
        reason = result.error or "Verifier turn ended without submit_verdict"
        self.hub.call(
            "verifier_instance_failed",
            {
                "review_id": command["review_id"],
                "instance_id": command["instance_id"],
                "reason": reason,
            },
            request_id=f"verifier-failed:{command['instance_id']}",
        )
        return {"run_id": run_id, "requeued": True, "reason": reason}

    def _stop(self, command: dict) -> dict:
        with self._guard:
            self._stop_requested.add(command["instance_id"])
            create_done = self._creating.get(command["instance_id"])
        if create_done is not None:
            # Do not tell Hub the slot is free while a concurrent create can
            # still materialize the old instance after that acknowledgement.
            create_done.wait()
        self.backend.stop(self._definition(command))
        result = self.hub.call(
            "verifier_instance_stopped",
            {"review_id": command["review_id"], "instance_id": command["instance_id"]},
            request_id=f"verifier-stopped:{command['instance_id']}",
        )
        return result


def main() -> None:
    repo = Path(os.environ.get("FOUNDAGENT_HOST_REPO") or Path.cwd()).resolve()
    team_id = os.environ.get("TEAM", "hackathon-team")
    layout = TeamLayout.initialize(
        os.environ.get("TEAM_STATE_ROOT")
        or repo / "ops" / "build" / "state" / team_id
    )
    maximum = 1
    backend = DockerVerifierBackend(
        repo=repo,
        company_id=team_id,
        account_id=os.environ.get("ACCOUNT") or team_id,
        network=os.environ.get("TEAM_NETWORK") or f"{team_id}_default",
        task_timeout=int(os.environ.get("VERIFIER_TURN_TIMEOUT_SECS", "3600")),
        ready_timeout=float(os.environ.get("AGENT_READY_TIMEOUT_SECS", "80")),
        spec_path=repository_agents_root(repo) / "ephemeral" / "team-verifier.yaml",
        shared_mount_target="/project",
        team_mode=True,
    )
    hub = HubClient(
        actor=BoundActor("manager", "verifier-manager"),
        timeout=float(os.environ.get("HUB_CLIENT_TIMEOUT_SECS", "30")),
    )
    service = VerifierCommandService(
        layout,
        company_id=team_id,
        backend=backend,
        hub=hub,
        max_instances=maximum,
        prompt_builder=team_verifier_prompt,
    )
    poll = float(os.environ.get("VERIFIER_MANAGER_POLL_SECS", "0.25"))
    print(f"[verifier-manager] ready team={team_id} max={maximum}", flush=True)
    while True:
        service.scan_once()
        time.sleep(max(0.05, poll))


if __name__ == "__main__":
    main()
