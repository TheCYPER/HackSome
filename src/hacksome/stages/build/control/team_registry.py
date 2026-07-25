"""Durable Team identity registry and registry-before-side-effect bootstrap."""

from __future__ import annotations

import hashlib
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from hacksome.stages.build.control.handoff import BuildAuthorizationEnvelopeV1
from hacksome.stages.build.control.runtime_store import (
    StoreError,
    atomic_write_json,
    file_lock,
    read_json,
)
from hacksome.stages.build.control.team_store import TeamLayout


SLOT_STATES = frozenset(
    {"bootstrapping", "starting", "active", "pausing", "resuming"}
)
OBSERVED_STATES = frozenset(
    {*SLOT_STATES, "queued", "paused", "error"}
)
DESIRED_STATES = frozenset({"active", "paused"})
_TEAM_ID = re.compile(r"^team-[0-9a-f]{24}$")
_OPERATION_ID = re.compile(r"^[a-z][a-z0-9-]{7,127}$")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RegistryConflictError(StoreError):
    """A stable Build identity or operation was rebound."""


class TeamRegistry:
    """One global registry with monotonic FIFO enqueue sequence."""

    def __init__(self, build_root: str | Path) -> None:
        self.build_root = Path(build_root).expanduser().resolve()
        self.registry_root = self.build_root / "registry"
        self.teams_dir = self.registry_root / "teams"
        self.operations_dir = self.registry_root / "operations"
        self.operation_locks_dir = self.registry_root / "operation-locks"
        self.sequence_path = self.registry_root / "sequence.json"
        self.lock_path = self.registry_root / "lock"
        self.control_roots = self.build_root / "teams"

    def _ensure_layout(self) -> None:
        self.teams_dir.mkdir(parents=True, exist_ok=True)
        self.operations_dir.mkdir(parents=True, exist_ok=True)
        self.operation_locks_dir.mkdir(parents=True, exist_ok=True)
        self.control_roots.mkdir(parents=True, exist_ok=True)

    def _next_sequence_locked(self) -> int:
        value = read_json(self.sequence_path)
        if value is None:
            value = {"next_enqueue_seq": 1}
        if not isinstance(value, dict):
            raise StoreError("Team registry sequence is invalid")
        sequence = value.get("next_enqueue_seq")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise StoreError("Team registry sequence is invalid")
        atomic_write_json(
            self.sequence_path,
            {"next_enqueue_seq": sequence + 1},
        )
        return sequence

    def _row_path(self, team_id: str) -> Path:
        if not isinstance(team_id, str) or not _TEAM_ID.fullmatch(team_id):
            raise StoreError(f"invalid Team ID: {team_id!r}")
        return self.teams_dir / f"{team_id}.json"

    def _validate_row(self, row: Any) -> dict[str, Any]:
        if not isinstance(row, dict):
            raise StoreError("Team registry row must be an object")
        required = {
            "schema_version",
            "team_id",
            "identity_sha256",
            "source_run_id",
            "idea_card_id",
            "idea_card_sha256",
            "handoff_sha256",
            "envelope_sha256",
            "authorization_id",
            "route_id",
            "route_contract_version",
            "catalog_sha256",
            "handoff",
            "authorization_receipt_state",
            "enqueue_seq",
            "control_root",
            "desired_state",
            "observed_state",
            "operation_id",
            "attempts",
            "last_error",
            "created_at",
            "updated_at",
        }
        if set(row) != required or row.get("schema_version") != 1:
            raise StoreError("Team registry row has invalid fields")
        team_id = row.get("team_id")
        if not isinstance(team_id, str) or not _TEAM_ID.fullmatch(team_id):
            raise StoreError("Team registry row has invalid team_id")
        envelope = BuildAuthorizationEnvelopeV1.from_mapping(
            {
                "schema_version": 1,
                "authorization_id": row.get("authorization_id"),
                "source": {
                    "route_id": row.get("route_id"),
                    "route_contract_version": row.get(
                        "route_contract_version"
                    ),
                    "catalog_sha256": row.get("catalog_sha256"),
                },
                "handoff": row.get("handoff"),
            }
        )
        if (
            row.get("identity_sha256") != envelope.handoff.identity_sha256
            or row.get("team_id") != envelope.handoff.team_id
            or row.get("source_run_id") != envelope.handoff.source_run_id
            or row.get("idea_card_id") != envelope.handoff.idea_card_id
            or row.get("idea_card_sha256")
            != envelope.handoff.idea_card_sha256
            or row.get("handoff_sha256") != envelope.handoff.handoff_sha256
            or row.get("envelope_sha256") != envelope.envelope_sha256
        ):
            raise StoreError("Team registry identity closure is invalid")
        expected_control = f"teams/{team_id}"
        if row.get("control_root") != expected_control:
            raise StoreError("Team registry control_root is invalid")
        if row.get("desired_state") not in DESIRED_STATES:
            raise StoreError("Team registry desired_state is invalid")
        if row.get("observed_state") not in OBSERVED_STATES:
            raise StoreError("Team registry observed_state is invalid")
        if row.get("authorization_receipt_state") not in {
            None,
            "queued",
            "bootstrapping",
            "starting",
            "active",
            "error",
        }:
            raise StoreError(
                "Team registry authorization_receipt_state is invalid"
            )
        enqueue_seq = row.get("enqueue_seq")
        attempts = row.get("attempts")
        if (
            isinstance(enqueue_seq, bool)
            or not isinstance(enqueue_seq, int)
            or enqueue_seq < 1
            or isinstance(attempts, bool)
            or not isinstance(attempts, int)
            or attempts < 0
        ):
            raise StoreError("Team registry counters are invalid")
        operation_id = row.get("operation_id")
        if operation_id is not None and (
            not isinstance(operation_id, str)
            or not _OPERATION_ID.fullmatch(operation_id)
        ):
            raise StoreError("Team registry operation_id is invalid")
        return row

    def _rows_locked(self) -> list[dict[str, Any]]:
        if not self.teams_dir.is_dir():
            return []
        return [
            self._validate_row(read_json(path))
            for path in sorted(self.teams_dir.glob("team-*.json"))
        ]

    def authorize(
        self,
        envelope: BuildAuthorizationEnvelopeV1,
    ) -> dict[str, Any]:
        """Persist one Team intent before creating any Team state."""

        self._ensure_layout()
        with file_lock(self.lock_path):
            rows = self._rows_locked()
            for row in rows:
                if row["authorization_id"] == envelope.authorization_id:
                    if row["envelope_sha256"] != envelope.envelope_sha256:
                        raise RegistryConflictError(
                            "authorization_id was replayed with different content"
                        )
                    return dict(row)
                same_source_card = (
                    row["source_run_id"] == envelope.handoff.source_run_id
                    and row["idea_card_id"] == envelope.handoff.idea_card_id
                )
                if (
                    same_source_card
                    and row["idea_card_sha256"]
                    != envelope.handoff.idea_card_sha256
                ):
                    raise RegistryConflictError(
                        "source run/Card identity already has a different hash"
                    )
                if (
                    row["team_id"] == envelope.handoff.team_id
                    and row["identity_sha256"]
                    != envelope.handoff.identity_sha256
                ):
                    raise RegistryConflictError(
                        "truncated Team ID collision detected"
                    )
            sequence = self._next_sequence_locked()
            created_at = _now()
            row = {
                "schema_version": 1,
                "team_id": envelope.handoff.team_id,
                "identity_sha256": envelope.handoff.identity_sha256,
                "source_run_id": envelope.handoff.source_run_id,
                "idea_card_id": envelope.handoff.idea_card_id,
                "idea_card_sha256": envelope.handoff.idea_card_sha256,
                "handoff_sha256": envelope.handoff.handoff_sha256,
                "envelope_sha256": envelope.envelope_sha256,
                "authorization_id": envelope.authorization_id,
                "route_id": envelope.route_id,
                "route_contract_version": envelope.route_contract_version,
                "catalog_sha256": envelope.catalog_sha256,
                "handoff": envelope.handoff.to_mapping(),
                "authorization_receipt_state": None,
                "enqueue_seq": sequence,
                "control_root": f"teams/{envelope.handoff.team_id}",
                "desired_state": "active",
                "observed_state": "queued",
                "operation_id": None,
                "attempts": 0,
                "last_error": None,
                "created_at": created_at,
                "updated_at": created_at,
            }
            self._validate_row(row)
            path = self._row_path(envelope.handoff.team_id)
            if path.exists():
                raise RegistryConflictError(
                    f"Team registry row already exists: {row['team_id']}"
                )
            atomic_write_json(path, row)
            return row

    def get(self, team_id: str) -> dict[str, Any]:
        path = self._row_path(team_id)
        row = read_json(path)
        if row is None:
            raise StoreError(f"unknown Team: {team_id}")
        return dict(self._validate_row(row))

    def record_authorization_receipt_state(
        self,
        team_id: str,
        observed_state: str,
    ) -> str:
        """Freeze the ingestion receipt state for exact replay.

        Team lifecycle may later become paused or resuming, but a replay of the
        original authorize operation must still return a value allowed by the
        strict authorize-receipt contract.
        """

        if observed_state not in {
            "queued",
            "bootstrapping",
            "starting",
            "active",
            "error",
        }:
            raise StoreError(
                f"invalid authorization receipt state: {observed_state}"
            )
        self._ensure_layout()
        with file_lock(self.lock_path):
            row = self.get(team_id)
            existing = row["authorization_receipt_state"]
            if isinstance(existing, str):
                return existing
            row["authorization_receipt_state"] = observed_state
            self._replace_locked(row)
            return observed_state

    def list(self) -> list[dict[str, Any]]:
        if not self.registry_root.exists():
            return []
        with file_lock(self.lock_path):
            return [
                dict(row)
                for row in sorted(
                    self._rows_locked(),
                    key=lambda value: (
                        value["enqueue_seq"],
                        value["team_id"],
                    ),
                )
            ]

    def _replace_locked(self, row: dict[str, Any]) -> dict[str, Any]:
        row["updated_at"] = _now()
        self._validate_row(row)
        atomic_write_json(self._row_path(row["team_id"]), row)
        return dict(row)

    def reserve_next(self, *, max_active_teams: int) -> dict[str, Any] | None:
        self._ensure_layout()
        with file_lock(self.lock_path):
            rows = self._rows_locked()
            occupied = sum(row["observed_state"] in SLOT_STATES for row in rows)
            if occupied >= max_active_teams:
                return None
            candidates = sorted(
                (
                    row
                    for row in rows
                    if row["desired_state"] == "active"
                    and row["observed_state"] == "queued"
                ),
                key=lambda row: (row["enqueue_seq"], row["team_id"]),
            )
            if not candidates:
                return None
            row = dict(candidates[0])
            attempt = row["attempts"] + 1
            row["attempts"] = attempt
            row["operation_id"] = f"start-{row['team_id'][5:]}-{attempt:04d}"
            row["observed_state"] = "bootstrapping"
            row["last_error"] = None
            return self._replace_locked(row)

    def transition(
        self,
        team_id: str,
        *,
        operation_id: str | None,
        observed_state: str,
        desired_state: str | None = None,
        last_error: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if observed_state not in OBSERVED_STATES:
            raise StoreError(f"invalid observed_state: {observed_state}")
        self._ensure_layout()
        with file_lock(self.lock_path):
            row = self.get(team_id)
            if row["operation_id"] != operation_id:
                raise RegistryConflictError(
                    f"stale Team operation for {team_id}"
                )
            row["observed_state"] = observed_state
            if desired_state is not None:
                if desired_state not in DESIRED_STATES:
                    raise StoreError(f"invalid desired_state: {desired_state}")
                row["desired_state"] = desired_state
            row["last_error"] = last_error
            if observed_state in {"active", "paused", "queued", "error"}:
                row["operation_id"] = None
            return self._replace_locked(row)

    def bootstrap(self, team_id: str) -> tuple[TeamLayout, bool]:
        """Create or exact-byte adopt the two reference initializers."""

        row = self.get(team_id)
        handoff = BuildAuthorizationEnvelopeV1.from_mapping(
            {
                "schema_version": 1,
                "authorization_id": row["authorization_id"],
                "source": {
                    "route_id": row["route_id"],
                    "route_contract_version": row["route_contract_version"],
                    "catalog_sha256": row["catalog_sha256"],
                },
                "handoff": row["handoff"],
            }
        ).handoff
        control_root = PurePosixPath(row["control_root"])
        if (
            control_root.is_absolute()
            or ".." in control_root.parts
            or control_root.as_posix() != f"teams/{team_id}"
        ):
            raise StoreError("Team control root escapes the Build root")
        root = self.build_root.joinpath(*control_root.parts)
        references = root / "project" / "reference"
        if references.exists():
            challenge = references / "challenge.md"
            card = references / "initial-idea-card.md"
            if (
                not challenge.is_file()
                or not card.is_file()
                or challenge.read_text(encoding="utf-8")
                != handoff.challenge_markdown
                or card.read_text(encoding="utf-8")
                != handoff.initial_idea_card_markdown
            ):
                raise RegistryConflictError(
                    "existing Team references conflict with the handoff"
                )
            return TeamLayout(root), True
        layout = TeamLayout.bootstrap(
            root,
            challenge_markdown=handoff.challenge_markdown,
            initial_idea_card_markdown=handoff.initial_idea_card_markdown,
        )
        return layout, False

    def begin_pause(self, team_id: str) -> dict[str, Any]:
        self._ensure_layout()
        with file_lock(self.lock_path):
            row = self.get(team_id)
            if row["observed_state"] == "paused":
                return row
            if (
                row["desired_state"] == "paused"
                and row["observed_state"] == "pausing"
            ):
                return row
            if row["observed_state"] == "queued":
                row["desired_state"] = "paused"
                row["observed_state"] = "paused"
                row["operation_id"] = None
                return self._replace_locked(row)
            attempt = row["attempts"] + 1
            row["attempts"] = attempt
            row["desired_state"] = "paused"
            row["observed_state"] = "pausing"
            row["operation_id"] = f"pause-{row['team_id'][5:]}-{attempt:04d}"
            return self._replace_locked(row)

    def enqueue_resume(self, team_id: str) -> dict[str, Any]:
        self._ensure_layout()
        with file_lock(self.lock_path):
            row = self.get(team_id)
            if row["observed_state"] == "pausing":
                raise RegistryConflictError(
                    "Team cannot resume until pause is fully confirmed"
                )
            if (
                row["desired_state"] == "active"
                and row["observed_state"] != "paused"
            ):
                return row
            row["desired_state"] = "active"
            row["observed_state"] = "queued"
            row["operation_id"] = None
            row["enqueue_seq"] = self._next_sequence_locked()
            row["last_error"] = None
            return self._replace_locked(row)

    def retry_errors(self) -> int:
        self._ensure_layout()
        changed = 0
        with file_lock(self.lock_path):
            for row in self._rows_locked():
                if (
                    row["desired_state"] == "active"
                    and row["observed_state"] == "error"
                ):
                    candidate = dict(row)
                    candidate["observed_state"] = "queued"
                    candidate["operation_id"] = None
                    candidate["last_error"] = None
                    self._replace_locked(candidate)
                    changed += 1
        return changed

    def begin_request(
        self,
        *,
        request_id: str,
        action: str,
        team_id: str,
    ) -> bool:
        if action not in {"pause", "resume"}:
            raise StoreError(f"unsupported control action: {action}")
        if (
            not isinstance(request_id, str)
            or not request_id
            or len(request_id) > 128
            or "\x00" in request_id
        ):
            raise StoreError("operator request_id is invalid")
        self._row_path(team_id)
        self._ensure_layout()
        request_sha = hashlib.sha256(
            f"{action}\0{team_id}\0{request_id}".encode()
        ).hexdigest()
        path = self.operations_dir / f"{request_sha}.json"
        with file_lock(self.lock_path):
            for existing_path in self.operations_dir.glob("*.json"):
                existing = read_json(existing_path)
                if (
                    isinstance(existing, dict)
                    and existing.get("request_id") == request_id
                ):
                    if (
                        existing.get("request_sha256") != request_sha
                        or existing.get("action") != action
                        or existing.get("team_id") != team_id
                    ):
                        raise RegistryConflictError(
                            "operator request_id was reused with different content"
                        )
                    return False
            atomic_write_json(
                path,
                {
                    "schema_version": 1,
                    "request_id": request_id,
                    "request_sha256": request_sha,
                    "action": action,
                    "team_id": team_id,
                    "created_at": _now(),
                },
            )
        return True

    @contextmanager
    def operation_lease(
        self,
        team_id: str,
        operation_id: str,
    ) -> Iterator[None]:
        """Serialize one external lifecycle side effect across reconcilers."""

        self._row_path(team_id)
        if (
            not isinstance(operation_id, str)
            or not _OPERATION_ID.fullmatch(operation_id)
        ):
            raise StoreError("Team operation_id is invalid")
        self._ensure_layout()
        lease = (
            self.operation_locks_dir
            / f"{team_id}-{operation_id}.lock"
        )
        with file_lock(lease):
            yield


__all__ = [
    "DESIRED_STATES",
    "OBSERVED_STATES",
    "RegistryConflictError",
    "SLOT_STATES",
    "TeamRegistry",
]
