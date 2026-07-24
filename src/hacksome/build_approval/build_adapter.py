"""Build control protocol plus in-memory and production subprocess adapters."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from hacksome.build_approval.contracts import (
    ApprovalValidationError,
    BuildAdapterError,
    BuildAuthorizationEnvelopeV1,
    BuildReceiptV1,
    BuildStatusSnapshotV1,
    BuildTeamStatusV1,
)
from hacksome.post_card.contracts import stable_team_id
from hacksome.state import canonical_json_bytes


class BuildControlAdapter(Protocol):
    def authorize(
        self,
        envelope: BuildAuthorizationEnvelopeV1,
    ) -> BuildReceiptV1: ...

    def status(self) -> BuildStatusSnapshotV1: ...

    def reconcile(self) -> BuildStatusSnapshotV1: ...


class InMemoryBuildControlAdapter:
    """Deterministic fake lifecycle used by the default offline test suite."""

    def __init__(
        self,
        *,
        max_active_teams: int = 2,
        fail_card_ids: frozenset[str] = frozenset(),
    ) -> None:
        if (
            isinstance(max_active_teams, bool)
            or not isinstance(max_active_teams, int)
            or max_active_teams < 1
            or max_active_teams > 100
        ):
            raise ValueError("max_active_teams must be between 1 and 100")
        self.max_active_teams = max_active_teams
        self.fail_card_ids = fail_card_ids
        self._envelopes: dict[str, BuildAuthorizationEnvelopeV1] = {}
        self._order: list[str] = []

    def authorize(
        self,
        envelope: BuildAuthorizationEnvelopeV1,
    ) -> BuildReceiptV1:
        if envelope.handoff.idea_card_id in self.fail_card_ids:
            raise BuildAdapterError(
                "the fake Build lifecycle rejected this Card",
                code="fake_start_failure",
            )
        existing = self._envelopes.get(envelope.authorization_id)
        if existing is not None and existing.to_mapping() != envelope.to_mapping():
            raise BuildAdapterError(
                "authorization was replayed with different content",
                code="build_idempotency_conflict",
            )
        if existing is None:
            self._envelopes[envelope.authorization_id] = envelope
            self._order.append(envelope.authorization_id)
        index = self._order.index(envelope.authorization_id)
        observed = "active" if index < self.max_active_teams else "queued"
        return BuildReceiptV1(
            schema_version=1,
            authorization_id=envelope.authorization_id,
            team_id=stable_team_id(envelope.handoff),
            identity_sha256=envelope.identity_sha256,
            observed_state=observed,
        )

    def status(self) -> BuildStatusSnapshotV1:
        teams: list[BuildTeamStatusV1] = []
        queue = 0
        for index, authorization_id in enumerate(self._order):
            envelope = self._envelopes[authorization_id]
            observed = "active" if index < self.max_active_teams else "queued"
            queue_position: int | None = None
            if observed == "queued":
                queue += 1
                queue_position = queue
            teams.append(
                BuildTeamStatusV1(
                    team_id=stable_team_id(envelope.handoff),
                    desired_state="active",
                    observed_state=observed,
                    queue_position=queue_position,
                )
            )
        return BuildStatusSnapshotV1(
            schema_version=1,
            max_active_teams=self.max_active_teams,
            teams=tuple(teams),
        )

    def reconcile(self) -> BuildStatusSnapshotV1:
        return self.status()


class SubprocessBuildControlAdapter:
    """Fixed-argv pure-JSON boundary to BuildFactory's operator module."""

    def __init__(
        self,
        *,
        build_root: str | Path,
        build_python: str | Path = sys.executable,
        buildfactory_dir: str | Path | None = None,
        max_active_teams: int = 2,
        timeout_seconds: float = 180.0,
        max_output_bytes: int = 256 * 1024,
        fake_lifecycle: bool = False,
    ) -> None:
        self.build_root = Path(build_root).expanduser().resolve()
        self.build_python = str(Path(build_python).expanduser().resolve())
        self.buildfactory_dir = (
            Path(buildfactory_dir).expanduser().resolve()
            if buildfactory_dir is not None
            else Path(__file__).resolve().parents[3] / "buildfactory"
        )
        if (
            isinstance(max_active_teams, bool)
            or not isinstance(max_active_teams, int)
            or max_active_teams < 1
            or max_active_teams > 100
        ):
            raise ValueError("max_active_teams must be between 1 and 100")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
        ):
            raise ValueError("Build adapter timeout must be positive")
        if (
            isinstance(max_output_bytes, bool)
            or not isinstance(max_output_bytes, int)
            or max_output_bytes < 1
            or max_output_bytes > 16 * 1024 * 1024
        ):
            raise ValueError(
                "Build adapter output limit must be between 1 byte and 16 MiB"
            )
        self.max_active_teams = max_active_teams
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.fake_lifecycle = fake_lifecycle

    def _environment(self) -> dict[str, str]:
        allowed = (
            "PATH",
            "HOME",
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "XDG_RUNTIME_DIR",
        )
        return {
            key: value
            for key in allowed
            if (value := os.environ.get(key)) is not None
        }

    def _call(
        self,
        command: str,
        *,
        stdin_value: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        argv = [
            self.build_python,
            "-m",
            "orchestration.team_operator",
            command,
            "--build-root",
            str(self.build_root),
            "--max-active-teams",
            str(self.max_active_teams),
            "--json",
        ]
        if stdin_value is not None:
            argv.append("--json-stdin")
        if self.fake_lifecycle:
            argv.append("--fake-lifecycle")
        try:
            with (
                tempfile.TemporaryFile() as stdout_file,
                tempfile.TemporaryFile() as stderr_file,
            ):
                result = subprocess.run(
                    argv,
                    input=(
                        canonical_json_bytes(dict(stdin_value)) + b"\n"
                        if stdin_value is not None
                        else None
                    ),
                    stdout=stdout_file,
                    stderr=stderr_file,
                    cwd=self.buildfactory_dir,
                    env=self._environment(),
                    shell=False,
                    timeout=self.timeout_seconds,
                    check=False,
                )
                stdout_size = stdout_file.tell()
                stderr_size = stderr_file.tell()
                if (
                    stdout_size > self.max_output_bytes
                    or stderr_size > self.max_output_bytes
                ):
                    raise BuildAdapterError(
                        "Build operator output exceeded the safety limit",
                        code="build_output_too_large",
                    )
                stdout_file.seek(0)
                stderr_file.seek(0)
                stdout = stdout_file.read(self.max_output_bytes + 1)
                stderr_file.read(self.max_output_bytes + 1)
        except subprocess.TimeoutExpired as exc:
            raise BuildAdapterError(
                "Build operator timed out",
                code="build_timeout",
            ) from exc
        except OSError as exc:
            raise BuildAdapterError(
                "Build operator is unavailable",
                code="build_unavailable",
            ) from exc
        if result.returncode != 0:
            raise BuildAdapterError(
                "Build operator rejected the request",
                code="build_operator_failed",
            )
        try:
            value = json.loads(stdout.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise BuildAdapterError(
                "Build operator returned invalid JSON",
                code="build_invalid_json",
            ) from exc
        if not isinstance(value, dict):
            raise BuildAdapterError(
                "Build operator response must be an object",
                code="build_invalid_json",
            )
        return value

    def authorize(
        self,
        envelope: BuildAuthorizationEnvelopeV1,
    ) -> BuildReceiptV1:
        try:
            return BuildReceiptV1.from_mapping(
                self._call("authorize", stdin_value=envelope.to_mapping()),
                envelope=envelope,
            )
        except ApprovalValidationError as exc:
            raise BuildAdapterError(
                "Build operator returned a mismatched receipt",
                code="build_receipt_mismatch",
            ) from exc

    def status(self) -> BuildStatusSnapshotV1:
        try:
            return BuildStatusSnapshotV1.from_mapping(self._call("list"))
        except ApprovalValidationError as exc:
            raise BuildAdapterError(
                "Build operator returned an invalid status snapshot",
                code="build_status_invalid",
            ) from exc

    def reconcile(self) -> BuildStatusSnapshotV1:
        try:
            return BuildStatusSnapshotV1.from_mapping(
                self._call("reconcile")
            )
        except ApprovalValidationError as exc:
            raise BuildAdapterError(
                "Build operator returned an invalid reconcile snapshot",
                code="build_status_invalid",
            ) from exc


__all__ = [
    "BuildControlAdapter",
    "InMemoryBuildControlAdapter",
    "SubprocessBuildControlAdapter",
]
