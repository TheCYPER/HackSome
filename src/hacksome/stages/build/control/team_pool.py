"""Bounded global Team pool with explicit pause/resume and FIFO queueing."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Protocol

from hacksome.stages.build.control.runtime_store import StoreError
from hacksome.stages.build.control.team_registry import TeamRegistry


class TeamLifecycle(Protocol):
    def start(self, row: dict) -> None: ...

    def probe(self, row: dict) -> str: ...

    def stop(self, row: dict) -> bool: ...


class FakeTeamLifecycle:
    """No-Docker lifecycle for deterministic unit and integration tests."""

    def __init__(self) -> None:
        self.running: set[str] = set()
        self.start_calls: list[str] = []
        self.stop_calls: list[str] = []
        self.fail_start: set[str] = set()
        self.partial_stop: set[str] = set()

    def start(self, row: dict) -> None:
        team_id = row["team_id"]
        self.start_calls.append(team_id)
        if team_id in self.fail_start:
            raise StoreError("simulated Team start failure")
        self.running.add(team_id)

    def probe(self, row: dict) -> str:
        return "active" if row["team_id"] in self.running else "stopped"

    def stop(self, row: dict) -> bool:
        team_id = row["team_id"]
        self.stop_calls.append(team_id)
        if team_id in self.partial_stop:
            return False
        self.running.discard(team_id)
        return True


class ComposeTeamLifecycle:
    """Production lifecycle with fixed Compose/Docker argv and trusted paths."""

    _SERVICES = frozenset(
        {"hub", "lead", "worker-manager", "verifier-manager"}
    )

    def __init__(
        self,
        *,
        build_ops_root: str | Path | None = None,
        repository_root: str | Path | None = None,
        timeout_seconds: float = 240.0,
        account: str = "foundagent",
    ) -> None:
        self.root = (
            Path(build_ops_root).expanduser().resolve()
            if build_ops_root is not None
            else Path(__file__).resolve().parents[5] / "ops" / "build"
        )
        self.repository_root = (
            Path(repository_root).expanduser().resolve()
            if repository_root is not None
            else self.root.parents[1]
        )
        self.compose_file = self.root / "docker-compose.yml"
        self.timeout_seconds = timeout_seconds
        self.account = account

    def _environment(self, row: dict) -> dict[str, str]:
        allowed = (
            "PATH",
            "HOME",
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "XDG_RUNTIME_DIR",
        )
        environment = {
            key: value
            for key in allowed
            if (value := os.environ.get(key)) is not None
        }
        environment.update(
            {
                "TEAM": row["team_id"],
                "ACCOUNT": self.account,
                "HACKSOME_ROOT": str(self.repository_root),
                "BUILD_OPS_ROOT": str(self.root),
                "TEAM_STATE_ROOT": str(
                    Path(row["_absolute_control_root"]).resolve()
                ),
            }
        )
        return environment

    def _compose(self, row: dict, *args: str) -> subprocess.CompletedProcess:
        command = [
            "docker",
            "compose",
            "-f",
            str(self.compose_file),
            "--project-name",
            row["team_id"],
            *args,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                cwd=self.root,
                env=self._environment(row),
                shell=False,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StoreError("Docker Compose lifecycle is unavailable") from exc
        if result.returncode != 0:
            raise StoreError("Docker Compose lifecycle command failed")
        return result

    def start(self, row: dict) -> None:
        self._compose(
            row,
            "up",
            "-d",
            "--build",
            "--wait",
            "--wait-timeout",
            "120",
        )

    def probe(self, row: dict) -> str:
        result = self._compose(
            row,
            "ps",
            "--status",
            "running",
            "--services",
        )
        services = {
            line.strip()
            for line in result.stdout.decode("utf-8", errors="replace").splitlines()
            if line.strip()
        }
        if not services:
            return "stopped"
        if services == self._SERVICES:
            return "active"
        return "unknown"

    def stop(self, row: dict) -> bool:
        self._compose(row, "stop", "--timeout", "30")
        try:
            listed = subprocess.run(
                [
                    "docker",
                    "ps",
                    "-q",
                    "--filter",
                    f"label=hacksome.team={row['team_id']}",
                ],
                capture_output=True,
                env=self._environment(row),
                shell=False,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StoreError("Docker lifecycle probe is unavailable") from exc
        if listed.returncode != 0:
            raise StoreError("Docker lifecycle probe failed")
        container_ids = [
            value
            for value in listed.stdout.decode("ascii", errors="ignore").split()
            if value
        ]
        for container_id in container_ids:
            stopped = subprocess.run(
                ["docker", "stop", "--time", "30", container_id],
                capture_output=True,
                env=self._environment(row),
                shell=False,
                timeout=self.timeout_seconds,
                check=False,
            )
            if stopped.returncode != 0:
                return False
        return self.probe(row) == "stopped"


class TeamPool:
    def __init__(
        self,
        registry: TeamRegistry,
        lifecycle: TeamLifecycle,
        *,
        max_active_teams: int = 2,
    ) -> None:
        if (
            isinstance(max_active_teams, bool)
            or not isinstance(max_active_teams, int)
            or max_active_teams < 1
            or max_active_teams > 100
        ):
            raise ValueError("max_active_teams must be between 1 and 100")
        self.registry = registry
        self.lifecycle = lifecycle
        self.max_active_teams = max_active_teams

    def _runtime_row(self, row: dict) -> dict:
        return {
            **row,
            "_absolute_control_root": str(
                self.registry.build_root / row["control_root"]
            ),
        }

    def _continue_start(self, row: dict) -> None:
        team_id = row["team_id"]
        operation_id = row["operation_id"]
        if not isinstance(operation_id, str):
            return
        with self.registry.operation_lease(team_id, operation_id):
            row = self.registry.get(team_id)
            if (
                row["operation_id"] != operation_id
                or row["observed_state"]
                not in {"bootstrapping", "starting", "resuming"}
            ):
                return
            try:
                if row["observed_state"] == "bootstrapping":
                    self.registry.bootstrap(team_id)
                    row = self.registry.transition(
                        team_id,
                        operation_id=operation_id,
                        observed_state="starting",
                    )
                probe = self.lifecycle.probe(self._runtime_row(row))
                if probe != "active":
                    self.lifecycle.start(self._runtime_row(row))
                    probe = self.lifecycle.probe(self._runtime_row(row))
                if probe == "active":
                    self.registry.transition(
                        team_id,
                        operation_id=operation_id,
                        observed_state="active",
                    )
                else:
                    raise StoreError("Team start could not be confirmed")
            except Exception as exc:
                try:
                    probe = self.lifecycle.probe(self._runtime_row(row))
                except Exception:
                    probe = "unknown"
                if probe == "active":
                    self.registry.transition(
                        team_id,
                        operation_id=operation_id,
                        observed_state="active",
                    )
                    return
                if probe == "unknown":
                    # Unknown may still be running and continues occupying a slot.
                    self.registry.transition(
                        team_id,
                        operation_id=operation_id,
                        observed_state="starting",
                        last_error={
                            "code": "start_unknown",
                            "message": (
                                "Team start result is unknown; reconcile again"
                            ),
                        },
                    )
                    return
                self.registry.transition(
                    team_id,
                    operation_id=operation_id,
                    observed_state="error",
                    last_error={
                        "code": "start_failed",
                        "message": str(exc)[:500],
                    },
                )

    def _continue_pause(self, row: dict) -> bool:
        """Finish one durable pause operation after crashes or partial stops."""

        team_id = row["team_id"]
        operation_id = row["operation_id"]
        if not isinstance(operation_id, str):
            return row["observed_state"] == "paused"
        with self.registry.operation_lease(team_id, operation_id):
            row = self.registry.get(team_id)
            if row["observed_state"] == "paused":
                return True
            if (
                row["operation_id"] != operation_id
                or row["observed_state"] != "pausing"
            ):
                return False
            try:
                stopped = self.lifecycle.stop(self._runtime_row(row))
            except Exception as exc:
                self.registry.transition(
                    team_id,
                    operation_id=operation_id,
                    observed_state="pausing",
                    last_error={
                        "code": "stop_failed",
                        "message": str(exc)[:500],
                    },
                )
                return False
            if not stopped:
                self.registry.transition(
                    team_id,
                    operation_id=operation_id,
                    observed_state="pausing",
                    last_error={
                        "code": "stop_incomplete",
                        "message": (
                            "Team stop is incomplete; reconcile again"
                        ),
                    },
                )
                return False
            self.registry.transition(
                team_id,
                operation_id=operation_id,
                observed_state="paused",
                desired_state="paused",
            )
            return True

    def reconcile(self, *, retry_errors: bool = False) -> list[dict]:
        if retry_errors:
            self.registry.retry_errors()
        for row in self.registry.list():
            if row["observed_state"] == "pausing":
                self._continue_pause(row)
        for row in self.registry.list():
            if row["observed_state"] in {
                "bootstrapping",
                "starting",
                "resuming",
            }:
                self._continue_start(row)
        while True:
            reserved = self.registry.reserve_next(
                max_active_teams=self.max_active_teams
            )
            if reserved is None:
                break
            self._continue_start(reserved)
        return self.registry.list()

    def pause(self, team_id: str, *, request_id: str) -> dict:
        self.registry.begin_request(
            request_id=request_id,
            action="pause",
            team_id=team_id,
        )
        row = self.registry.begin_pause(team_id)
        if row["observed_state"] == "paused":
            self.reconcile()
            return row
        if self._continue_pause(row):
            self.reconcile()
        return self.registry.get(team_id)

    def resume(self, team_id: str, *, request_id: str) -> dict:
        self.registry.begin_request(
            request_id=request_id,
            action="resume",
            team_id=team_id,
        )
        self.registry.enqueue_resume(team_id)
        self.reconcile()
        return self.registry.get(team_id)


__all__ = [
    "ComposeTeamLifecycle",
    "FakeTeamLifecycle",
    "TeamLifecycle",
    "TeamPool",
]
