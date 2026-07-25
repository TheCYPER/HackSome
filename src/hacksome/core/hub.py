"""Central persistence owner for one Idea workflow run.

The Hub owns route-neutral state only.  Route-specific inspection and semantic
validation live in :mod:`hacksome.routes`; the methods kept here are backwards
compatible forwarding points for the Useful workflow.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from hacksome.core.config import (
    CodexConfig,
    PersistedConfigError,
    codex_config_sha256,
    decode_codex_config,
    serialize_codex_config,
)
from hacksome.core.models import CodexResult
from hacksome.core.state import (
    StateConflictError,
    StateError,
    advisory_lease,
    append_jsonl,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    normalize_json,
    read_json_object,
    read_jsonl,
    sha256_bytes,
    sha256_file,
    sha256_json,
    sha256_text,
)


LEGACY_RUN_SCHEMA_VERSION = 1
RUN_SCHEMA_VERSION = 2
SUPPORTED_RUN_SCHEMA_VERSIONS = frozenset(
    {LEGACY_RUN_SCHEMA_VERSION, RUN_SCHEMA_VERSION}
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ALLOWED_STATUSES = frozenset(
    {"created", "running", "waiting", "completed", "failed"}
)
_ROUTE_VERSION_KEYS = (
    "contract_version",
    "prompt_policy_version",
    "stage_policy_version",
    "report_policy_version",
)
_LEDGERS: dict[str, tuple[str, str]] = {
    "events": ("events.jsonl", "event_id"),
    "decisions": ("decisions.jsonl", "decision_id"),
    "human_reviews": ("human-reviews.jsonl", "review_id"),
    "human_resolutions": ("human-resolutions.jsonl", "resolution_id"),
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class TaskPaths:
    root: Path
    workspace: Path
    raw: Path
    prompt: Path
    request: Path
    result: Path
    output: Path


class RunHub:
    """Persist prompts, Sessions, artifacts, decisions, and run state."""

    def __init__(self, run_dir: str | Path) -> None:
        self.run_dir = Path(run_dir).expanduser().resolve()
        self.state_path = self.run_dir / "run.json"
        self.events_path = self.run_dir / "events.jsonl"
        self.decisions_path = self.run_dir / "decisions.jsonl"
        self.lock_path = self.run_dir / "run.lock"
        self.review_server_lock_path = self.run_dir / "review-server.lock"
        self._lock = threading.RLock()
        if not self.state_path.is_file():
            raise StateError(f"run does not exist: {self.run_dir}")

    @classmethod
    def create(
        cls,
        challenge: str,
        runs_dir: str | Path,
        *,
        settings: Mapping[str, Any],
        codex_config: CodexConfig,
        run_id: str | None = None,
        route: str | Mapping[str, Any] | None = None,
        inputs: Mapping[str, Any] | None = None,
        resource_manifest: Mapping[str, Any] | None = None,
    ) -> "RunHub":
        """Create a v2 run; omitted ``route`` remains Useful-compatible."""

        if not isinstance(challenge, str) or not challenge.strip():
            raise ValueError("challenge must not be empty")
        normalized_id = run_id or cls._generated_run_id(challenge)
        if not _SAFE_ID.fullmatch(normalized_id):
            raise ValueError(
                "run_id must contain only letters, numbers, '.', '_' or '-'"
            )
        root = Path(runs_dir).expanduser().resolve() / normalized_id
        if root.exists():
            raise StateError(f"run directory already exists: {root}")

        route_data = cls._normalize_route(route)
        settings_data = normalize_json(dict(settings), label="workflow settings")
        if not isinstance(settings_data, dict):
            raise StateError("workflow settings must be an object")
        codex_data = serialize_codex_config(codex_config)

        (root / "input").mkdir(parents=True)
        (root / "tasks").mkdir()
        (root / "artifacts").mkdir()
        challenge_path = root / "input" / "challenge.md"
        atomic_write_text(challenge_path, challenge)
        atomic_write_text(root / "run.lock", "")
        atomic_write_text(root / "events.jsonl", "")
        atomic_write_text(root / "decisions.jsonl", "")

        now = utc_now()
        challenge_sha256 = sha256_text(challenge)
        input_data: dict[str, Any] = {
            "challenge": {
                "path": "input/challenge.md",
                "sha256": challenge_sha256,
            }
        }
        if inputs is not None:
            extra_inputs = normalize_json(dict(inputs), label="run inputs")
            if not isinstance(extra_inputs, dict):
                raise StateError("run inputs must be an object")
            supplied_challenge = extra_inputs.pop("challenge", None)
            if supplied_challenge is not None and supplied_challenge != input_data[
                "challenge"
            ]:
                raise StateError("challenge input metadata is controller-owned")
            input_data.update(extra_inputs)

        created_event = {
            "event_id": "run:created",
            "kind": "run.created",
            "data": {
                "challenge_sha256": challenge_sha256,
                "route_id": route_data["id"],
            },
            "created_at": now,
        }
        state = {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": normalized_id,
            "route": route_data,
            "status": "created",
            "current_stage": None,
            "created_at": now,
            "updated_at": now,
            "inputs": input_data,
            "settings": settings_data,
            "codex_config": codex_data,
            "config_hashes": {
                "codex_config_sha256": codex_config_sha256(codex_config),
                "workflow_settings_sha256": sha256_json(settings_data),
            },
            "resource_manifest": (
                normalize_json(
                    dict(resource_manifest), label="resource manifest reference"
                )
                if resource_manifest is not None
                else None
            ),
            "tasks": {},
            "artifacts": {},
            "idea_card_ids": [],
            "result_artifact_ids": [],
            "wait": None,
            "terminal_error": None,
            "secondary_errors": [],
            "transition_seq": 0,
            "pending_records": [
                {
                    "ledger": "events",
                    "record": created_event,
                }
            ],
        }
        atomic_write_json(root / "run.json", state)
        hub = cls(root)
        hub.reconcile_pending()
        return hub

    @staticmethod
    def _normalize_route(
        route: str | Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if route is None:
            route_data: dict[str, Any] = {"id": "useful"}
        elif isinstance(route, str):
            route_data = {"id": route}
        else:
            route_data = dict(route)
        route_id = route_data.get("id")
        if not isinstance(route_id, str) or not _SAFE_ID.fullmatch(route_id):
            raise ValueError("route id must be a safe non-empty identifier")
        for key in _ROUTE_VERSION_KEYS:
            route_data.setdefault(key, "1")
            value = route_data[key]
            if not isinstance(value, str) or not value:
                raise ValueError(f"route {key} must be a non-empty string")
        normalized = normalize_json(route_data, label="route metadata")
        if not isinstance(normalized, dict):
            raise StateError("route metadata must be an object")
        return normalized

    @staticmethod
    def _generated_run_id(challenge: str) -> str:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        return f"idea-{stamp}-{sha256_text(challenge)[:8]}"

    @property
    def run_id(self) -> str:
        value = self.load_state().get("run_id")
        if not isinstance(value, str):
            raise StateError("run.json has no valid run_id")
        return value

    @property
    def schema_version(self) -> int:
        return self._read_raw_state()["schema_version"]

    @property
    def route_id(self) -> str:
        route = _object(self.load_state().get("route"), "route")
        return _string(route.get("id"), "route id")

    def load_raw_state(self) -> dict[str, Any]:
        """Read the exact persisted state without projection or mutation."""

        return self._read_raw_state()

    def load_state(self) -> dict[str, Any]:
        """Read one consistent snapshot, projecting schema v1 in memory only."""

        initial = self._read_raw_state()
        if initial["schema_version"] == RUN_SCHEMA_VERSION and self.lock_path.is_file():
            with advisory_lease(self.lock_path, exclusive=False, create=False):
                initial = self._read_raw_state()
        return self._project_state(initial)

    def _read_raw_state(self) -> dict[str, Any]:
        state = read_json_object(self.state_path)
        version = state.get("schema_version")
        if version not in SUPPORTED_RUN_SCHEMA_VERSIONS:
            raise StateError(f"unsupported run schema version: {version!r}")
        return state

    @staticmethod
    def _project_state(raw: Mapping[str, Any]) -> dict[str, Any]:
        state = normalize_json(dict(raw), label="run state")
        if not isinstance(state, dict):
            raise StateError("run state must be an object")
        if state.get("schema_version") != LEGACY_RUN_SCHEMA_VERSION:
            return state
        legacy_input = state.get("input")
        state.setdefault(
            "route",
            {
                "id": "useful",
                "contract_version": "1",
                "prompt_policy_version": "1",
                "stage_policy_version": "1",
                "report_policy_version": "1",
            },
        )
        state.setdefault(
            "inputs",
            {"challenge": legacy_input} if isinstance(legacy_input, dict) else {},
        )
        state.setdefault("result_artifact_ids", [])
        state.setdefault("wait", None)
        state.setdefault("terminal_error", None)
        state.setdefault("secondary_errors", [])
        state.setdefault("transition_seq", 0)
        state.setdefault("pending_records", [])
        return state

    def load_codex_config(self) -> CodexConfig:
        state = self.load_state()
        value = _object(state.get("codex_config"), "Codex configuration")
        if state["schema_version"] == LEGACY_RUN_SCHEMA_VERSION:
            # Historical v1 values were written with dataclasses.asdict().
            expected = sha256_json(value)
        else:
            hashes = _object(state.get("config_hashes"), "config hashes")
            expected = _string(
                hashes.get("codex_config_sha256"), "Codex configuration hash"
            )
        try:
            return decode_codex_config(value, expected_sha256=expected)
        except PersistedConfigError as exc:
            raise StateError(f"invalid persisted Codex configuration: {exc}") from exc

    def challenge(self) -> str:
        state = self.load_state()
        inputs = _object(state.get("inputs"), "run inputs")
        input_data = _object(inputs.get("challenge"), "challenge input")
        path = self._resolve_relative(
            _string(input_data.get("path"), "challenge input path")
        )
        text = path.read_text(encoding="utf-8")
        if sha256_text(text) != input_data.get("sha256"):
            raise StateError("challenge input hash does not match run.json")
        return text

    def set_run_status(
        self,
        status: str,
        *,
        stage: str | None = None,
        reason: str | None = None,
        error: BaseException | Mapping[str, Any] | None = None,
        task_id: str | None = None,
    ) -> None:
        """Persist one uniquely sequenced status transition and its event."""

        if status not in _ALLOWED_STATUSES:
            raise ValueError(f"unsupported run status: {status}")
        if stage is not None and (not isinstance(stage, str) or not stage):
            raise ValueError("stage must be omitted or non-empty")
        with self._exclusive_lease():
            state = self._prepare_writer_state()
            from_status = state.get("status")
            if not isinstance(from_status, str):
                raise StateError("run status must be a string")
            sequence = state.get("transition_seq")
            if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
                raise StateError("transition_seq must be a non-negative integer")
            sequence += 1
            event_id = f"run:transition:{sequence:08d}"
            at = utc_now()
            state["status"] = status
            state["current_stage"] = stage
            state["transition_seq"] = sequence
            if status == "failed":
                error_record = self._error_record(
                    error,
                    stage=stage,
                    task_id=task_id,
                    event_id=event_id,
                    at=at,
                )
                if state.get("terminal_error") is None:
                    state["terminal_error"] = error_record
                else:
                    secondary = state.get("secondary_errors")
                    if not isinstance(secondary, list):
                        raise StateError("secondary_errors must be a list")
                    secondary.append(error_record)
            event = {
                "event_id": event_id,
                "kind": "run.status",
                "data": {
                    "from_status": from_status,
                    "to_status": status,
                    "status": status,
                    "stage": stage,
                    "reason": reason,
                },
                "created_at": at,
            }
            self._commit_locked(state, [self._pending("events", event)])

    @staticmethod
    def _error_record(
        error: BaseException | Mapping[str, Any] | None,
        *,
        stage: str | None,
        task_id: str | None,
        event_id: str,
        at: str,
    ) -> dict[str, Any]:
        if error is None:
            kind = "RunFailed"
            message = f"run failed during {stage or 'unknown stage'}"
            extra: dict[str, Any] = {}
        elif isinstance(error, BaseException):
            kind = type(error).__name__
            message = str(error)
            extra = {}
        else:
            extra = dict(error)
            kind = extra.pop("kind", None)
            message = extra.pop("message", None)
            if not isinstance(kind, str) or not kind:
                raise ValueError("terminal error kind must be non-empty")
            if not isinstance(message, str) or not message:
                raise ValueError("terminal error message must be non-empty")
        record = {
            "kind": kind,
            "message": message,
            "stage": stage,
            "task_id": task_id,
            "event_id": event_id,
            "at": at,
            **extra,
        }
        normalized = normalize_json(record, label="terminal error")
        if not isinstance(normalized, dict):
            raise StateError("terminal error must be an object")
        return normalized

    def add_secondary_error(
        self,
        error: BaseException | Mapping[str, Any],
        *,
        stage: str | None = None,
        task_id: str | None = None,
    ) -> None:
        with self._exclusive_lease():
            state = self._prepare_writer_state()
            secondary = state.get("secondary_errors")
            if not isinstance(secondary, list):
                raise StateError("secondary_errors must be a list")
            at = utc_now()
            secondary.append(
                self._error_record(
                    error,
                    stage=stage,
                    task_id=task_id,
                    event_id=f"secondary-error:{len(secondary) + 1:08d}",
                    at=at,
                )
            )
            state["updated_at"] = at
            atomic_write_json(self.state_path, state)

    def register_input(self, name: str, record: Mapping[str, Any]) -> None:
        if not _SAFE_ID.fullmatch(name):
            raise ValueError(f"unsafe input name: {name!r}")
        normalized = normalize_json(dict(record), label=f"input {name}")
        if not isinstance(normalized, dict):
            raise StateError("input record must be an object")

        def update(state: dict[str, Any]) -> None:
            inputs = _object(state.get("inputs"), "run inputs")
            existing = inputs.get(name)
            if existing is not None and existing != normalized:
                raise StateConflictError(f"input {name!r} is already registered")
            inputs[name] = normalized

        self._mutate(update)

    def set_resource_manifest(self, record: Mapping[str, Any]) -> None:
        normalized = normalize_json(dict(record), label="resource manifest reference")

        def update(state: dict[str, Any]) -> None:
            existing = state.get("resource_manifest")
            if existing is not None and existing != normalized:
                raise StateConflictError("resource manifest is already frozen")
            state["resource_manifest"] = normalized

        self._mutate(update)

    def set_wait(self, wait: Mapping[str, Any] | None) -> None:
        normalized = (
            normalize_json(dict(wait), label="wait state") if wait is not None else None
        )

        def update(state: dict[str, Any]) -> None:
            state["wait"] = normalized

        self._mutate(update)

    def set_wait_and_append_ledger_record(
        self,
        wait: Mapping[str, Any],
        *,
        ledger: str,
        record: Mapping[str, Any],
    ) -> bool:
        """Atomically persist wait state with one durable ledger record.

        The run snapshot is written with the exact ledger row in its outbox
        before the JSONL append is attempted.  A crash during that append leaves
        the wait transition and pending row together for ``reconcile``.
        """

        if ledger not in _LEDGERS:
            raise ValueError(f"unsupported outbox ledger: {ledger}")
        normalized_wait = normalize_json(dict(wait), label="wait state")
        if not isinstance(normalized_wait, dict):
            raise StateError("wait state must be an object")
        _, id_field = _LEDGERS[ledger]
        normalized_record = normalize_json(
            dict(record), label=f"{ledger} record"
        )
        if not isinstance(normalized_record, dict):
            raise StateError(f"{ledger} record must be an object")
        record_id = normalized_record.get(id_field)
        if not isinstance(record_id, str) or not record_id:
            raise StateError(
                f"{ledger} record requires non-empty {id_field!r}"
            )

        with self._exclusive_lease():
            state = self._prepare_writer_state()
            existing = self._find_ledger_record(
                ledger, record_id, state
            )
            created = existing is None
            pending_records: list[Mapping[str, Any]] = []
            if existing is not None:
                comparable = (
                    existing
                    if "created_at" in normalized_record
                    else {
                        key: value
                        for key, value in existing.items()
                        if key != "created_at"
                    }
                )
                if comparable != normalized_record:
                    raise StateConflictError(
                        f"{id_field} {record_id!r} already has "
                        "different content"
                    )
            else:
                normalized_record.setdefault("created_at", utc_now())
                pending_records.append(
                    self._pending(ledger, normalized_record)
                )
            state["wait"] = normalized_wait
            self._commit_locked(state, pending_records)
        return created

    def set_result_artifacts(self, artifact_ids: Sequence[str]) -> None:
        values = list(artifact_ids)
        if any(not isinstance(value, str) or not _SAFE_ID.fullmatch(value) for value in values):
            raise ValueError("result artifact IDs must be safe identifiers")

        def update(state: dict[str, Any]) -> None:
            artifacts = _object(state.get("artifacts"), "artifacts")
            missing = [value for value in values if value not in artifacts]
            if missing:
                raise StateError(f"result artifacts are not registered: {missing}")
            state["result_artifact_ids"] = values

        self._mutate(update)

    def bind_finalization_manifest(
        self,
        reference: Mapping[str, Any],
    ) -> bool:
        """Bind one immutable finalization manifest to the run.

        The manifest file is written and hashed by the route coordinator before
        this call.  Binding it in ``run.json`` makes an otherwise orphaned state
        file discoverable without allowing a later caller to substitute a
        different plan.
        """

        normalized = normalize_json(
            dict(reference),
            label="finalization manifest reference",
        )
        expected_keys = {
            "id",
            "manifest_path",
            "manifest_sha256",
            "phase",
        }
        if not isinstance(normalized, dict) or set(normalized) != expected_keys:
            raise StateError(
                "finalization manifest reference has invalid fields"
            )
        finalization_id = normalized.get("id")
        manifest_path = normalized.get("manifest_path")
        manifest_sha256 = normalized.get("manifest_sha256")
        if (
            not isinstance(finalization_id, str)
            or not _SAFE_ID.fullmatch(finalization_id)
        ):
            raise StateError("finalization manifest id is invalid")
        if not isinstance(manifest_path, str):
            raise StateError("finalization manifest path is invalid")
        if (
            not isinstance(manifest_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256)
        ):
            raise StateError("finalization manifest hash is invalid")
        if normalized.get("phase") != "publishing":
            raise StateError(
                "a new finalization manifest must start in publishing"
            )
        manifest_file = self._resolve_relative(manifest_path)
        if not manifest_file.is_file():
            raise StateError("finalization manifest file is missing")
        if sha256_file(manifest_file) != manifest_sha256:
            raise StateConflictError("finalization manifest hash mismatch")

        created = False

        def update(state: dict[str, Any]) -> None:
            nonlocal created
            existing = state.get("finalization")
            if existing is None:
                state["finalization"] = normalized
                created = True
                return
            if not isinstance(existing, dict):
                raise StateError("run finalization reference must be an object")
            comparable = dict(existing)
            phase = comparable.pop("phase", None)
            expected = dict(normalized)
            expected.pop("phase")
            if comparable != expected or phase not in {
                "publishing",
                "completed",
            }:
                raise StateConflictError(
                    "run is already bound to a different finalization manifest"
                )

        self._mutate(update)
        return created

    def load_consistent_snapshot(self) -> dict[str, Any]:
        """Read run state and every allowlisted ledger under one shared lease."""

        with advisory_lease(self.lock_path, exclusive=False, create=False):
            state = self._project_state(self._read_raw_state())
            ledgers = {
                ledger: read_jsonl(self.run_dir / filename)
                for ledger, (filename, _id_field) in _LEDGERS.items()
            }
        return {"state": state, "ledgers": ledgers}

    def task_paths(self, task_id: str) -> TaskPaths:
        if not _SAFE_ID.fullmatch(task_id):
            raise ValueError(f"unsafe task id: {task_id!r}")
        root = self.run_dir / "tasks" / task_id
        return TaskPaths(
            root=root,
            workspace=root / "workspace",
            raw=root / "raw",
            prompt=root / "prompt.md",
            request=root / "request.json",
            result=root / "result.json",
            output=root / "output.json",
        )

    def begin_task(
        self,
        *,
        task_id: str,
        stage: str,
        prompt: str,
        prompt_metadata: Mapping[str, Any],
        output_schema: Path,
        web_search: bool,
        parent_refs: Sequence[str],
        failure_policy: str = "fatal",
    ) -> TaskPaths:
        if failure_policy not in {"fatal", "optional_branch"}:
            raise ValueError(f"unsupported failure policy: {failure_policy}")
        paths = self.task_paths(task_id)
        if paths.root.exists():
            raise StateError(f"task already exists: {task_id}")
        paths.workspace.mkdir(parents=True)
        paths.raw.mkdir()
        atomic_write_text(paths.raw / "stdout.jsonl", "")
        atomic_write_text(paths.raw / "stderr.jsonl", "")
        atomic_write_text(paths.prompt, prompt)
        request = {
            "task_id": task_id,
            "stage": stage,
            "status": "running",
            "created_at": utc_now(),
            "web_search": web_search,
            "failure_policy": failure_policy,
            "parent_refs": list(parent_refs),
            "prompt": {
                **dict(prompt_metadata),
                "path": self._relative(paths.prompt),
                "sha256": sha256_text(prompt),
            },
            "output_schema": {
                "name": output_schema.name,
                "sha256": sha256_file(output_schema),
            },
        }
        atomic_write_json(paths.request, request)
        request_sha256 = sha256_file(paths.request)

        def update(state: dict[str, Any]) -> None:
            tasks = _object(state.get("tasks"), "tasks")
            if task_id in tasks:
                raise StateError(f"task already registered: {task_id}")
            tasks[task_id] = {
                "task_id": task_id,
                "stage": stage,
                "status": "running",
                "request_path": self._relative(paths.request),
                "request_sha256": request_sha256,
                "prompt_path": self._relative(paths.prompt),
                "prompt_sha256": sha256_text(prompt),
                "parent_refs": list(parent_refs),
                "web_search": web_search,
                "failure_policy": failure_policy,
            }
            state["current_stage"] = stage

        self._mutate(
            update,
            event=self._new_event(
                "task.started",
                event_id=f"task:{task_id}:started",
                data={"task_id": task_id, "stage": stage},
            ),
        )
        return paths

    def finish_task(self, result: CodexResult) -> None:
        paths = self.task_paths(result.task_id)
        if not paths.request.is_file():
            raise StateError(f"task was not started: {result.task_id}")
        atomic_write_json(paths.output, result.structured_output)
        error: dict[str, Any] | None = None
        if result.error is not None:
            error = {
                "kind": result.error.kind.value,
                "message": result.error.message,
                "retryable": result.error.retryable,
                "returncode": result.error.returncode,
            }
        payload = {
            "task_id": result.task_id,
            "status": result.status.value,
            "session_id": result.session_id,
            "attempts": result.attempts,
            "usage": result.usage,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "duration_seconds": result.duration_seconds,
            "returncode": result.returncode,
            "error": error,
            "output_path": self._relative(paths.output),
            "raw_logs": {
                "stdout": self._relative(result.logs.stdout),
                "stderr": self._relative(result.logs.stderr),
                "last_message": self._relative(result.logs.last_message),
            },
        }
        atomic_write_json(paths.result, payload)
        output_sha256 = sha256_file(paths.output)
        result_sha256 = sha256_file(paths.result)

        def update(state: dict[str, Any]) -> None:
            tasks = _object(state.get("tasks"), "tasks")
            task = _object(tasks.get(result.task_id), f"task {result.task_id}")
            task.update(
                {
                    "status": result.status.value,
                    "result_path": self._relative(paths.result),
                    "result_sha256": result_sha256,
                    "output_path": self._relative(paths.output),
                    "output_sha256": output_sha256,
                    "session_id": result.session_id,
                }
            )

        self._mutate(
            update,
            event=self._new_event(
                "task.finished",
                event_id=f"task:{result.task_id}:finished",
                data={
                    "task_id": result.task_id,
                    "status": result.status.value,
                    "session_id": result.session_id,
                },
            ),
        )

    def fail_task(self, task_id: str, error: BaseException) -> None:
        """Persist a runner/preflight exception that occurred after begin_task."""

        paths = self.task_paths(task_id)
        payload = {
            "task_id": task_id,
            "status": "failed",
            "session_id": None,
            "attempts": 0,
            "usage": {},
            "started_at": None,
            "finished_at": utc_now(),
            "duration_seconds": None,
            "returncode": None,
            "error": {"kind": type(error).__name__, "message": str(error)},
            "output_path": None,
            "raw_logs": {
                "stdout": self._relative(paths.raw / "stdout.jsonl"),
                "stderr": self._relative(paths.raw / "stderr.jsonl"),
                "last_message": None,
            },
        }
        atomic_write_json(paths.result, payload)
        result_sha256 = sha256_file(paths.result)

        def update(state: dict[str, Any]) -> None:
            tasks = _object(state.get("tasks"), "tasks")
            task = _object(tasks.get(task_id), f"task {task_id}")
            task.update(
                {
                    "status": "failed",
                    "result_path": self._relative(paths.result),
                    "result_sha256": result_sha256,
                    "session_id": None,
                }
            )

        self._mutate(
            update,
            event=self._new_event(
                "task.finished",
                event_id=f"task:{task_id}:finished",
                data={"task_id": task_id, "status": "failed", "session_id": None},
            ),
        )

    def invalidate_task(self, task_id: str, error: BaseException) -> None:
        """Mark a Codex-successful task failed when publication validation fails."""

        paths = self.task_paths(task_id)
        payload = read_json_object(paths.result)
        payload["status"] = "failed"
        payload["validation_error"] = {
            "kind": type(error).__name__,
            "message": str(error),
        }
        atomic_write_json(paths.result, payload)
        result_sha256 = sha256_file(paths.result)

        def update(state: dict[str, Any]) -> None:
            tasks = _object(state.get("tasks"), "tasks")
            task = _object(tasks.get(task_id), f"task {task_id}")
            task["status"] = "failed"
            task["result_sha256"] = result_sha256

        self._mutate(
            update,
            event=self._new_event(
                "task.invalidated",
                event_id=f"task:{task_id}:invalidated",
                data={
                    "task_id": task_id,
                    "kind": type(error).__name__,
                    "message": str(error),
                },
            ),
        )

    def publish_artifact(
        self,
        *,
        artifact_id: str,
        artifact_type: str,
        relative_path: str,
        content: str,
        task_id: str | None,
        source_refs: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        """Publish or idempotently adopt one immutable artifact."""

        if not _SAFE_ID.fullmatch(artifact_id):
            raise ValueError(f"unsafe artifact id: {artifact_id!r}")
        if not isinstance(artifact_type, str) or not artifact_type:
            raise ValueError("artifact_type must be non-empty")
        if not isinstance(content, str):
            raise TypeError("artifact content must be text")
        destination = self._resolve_relative(relative_path)
        if destination.is_symlink():
            raise StateError(f"refusing symlink artifact path: {relative_path}")
        content_sha256 = sha256_text(content)
        stable_record = normalize_json(
            {
                "artifact_id": artifact_id,
                "artifact_type": artifact_type,
                "path": relative_path,
                "sha256": content_sha256,
                "task_id": task_id,
                "source_refs": list(source_refs),
                "metadata": dict(metadata or {}),
            },
            label=f"artifact {artifact_id}",
        )
        if not isinstance(stable_record, dict):
            raise StateError("artifact record must be an object")

        with self._exclusive_lease():
            state = self._prepare_writer_state()
            artifacts = _object(state.get("artifacts"), "artifacts")
            existing = artifacts.get(artifact_id)
            if existing is not None:
                existing_record = _object(existing, f"artifact {artifact_id}")
                without_time = {
                    key: value
                    for key, value in existing_record.items()
                    if key != "created_at"
                }
                if without_time != stable_record:
                    raise StateConflictError(
                        f"artifact {artifact_id!r} already has different metadata"
                    )
                if not destination.is_file():
                    raise StateError(
                        f"artifact {artifact_id!r} is registered but its file is missing"
                    )
                if sha256_file(destination) != content_sha256:
                    raise StateConflictError(
                        f"artifact {artifact_id!r} file hash conflicts with its record"
                    )
                return artifact_id

            for other_id, raw in artifacts.items():
                if isinstance(raw, dict) and raw.get("path") == relative_path:
                    raise StateConflictError(
                        f"artifact path {relative_path!r} is already registered "
                        f"to {other_id!r}"
                    )

            if destination.exists():
                if not destination.is_file():
                    raise StateConflictError(
                        f"artifact path is not a regular file: {relative_path}"
                    )
                if sha256_file(destination) != content_sha256:
                    raise StateConflictError(
                        f"unregistered artifact path has different content: "
                        f"{relative_path}"
                    )
            else:
                atomic_write_text(destination, content)

            record = {**stable_record, "created_at": utc_now()}
            artifacts[artifact_id] = record
            event = self._new_event(
                "artifact.published",
                event_id=f"artifact:{artifact_id}:published",
                data={"artifact_id": artifact_id, "artifact_type": artifact_type},
            )
            self._commit_locked(state, [self._pending("events", event)])
        return artifact_id

    def publish_planned_artifact(
        self,
        *,
        artifact_record: Mapping[str, Any],
        publish_event: Mapping[str, Any],
        content: bytes,
    ) -> str:
        """Publish exact manifest-planned bytes, record, and event.

        Unlike ``publish_artifact()``, this method never chooses a timestamp or
        regenerates event content.  A replay therefore reproduces the manifest
        byte-for-byte and fails closed on any conflicting record.
        """

        if not isinstance(content, bytes):
            raise TypeError("planned artifact content must be bytes")
        record = normalize_json(
            dict(artifact_record),
            label="planned artifact record",
        )
        event = normalize_json(
            dict(publish_event),
            label="planned artifact event",
        )
        record_keys = {
            "artifact_id",
            "artifact_type",
            "path",
            "sha256",
            "task_id",
            "source_refs",
            "metadata",
            "created_at",
        }
        event_keys = {"event_id", "kind", "data", "created_at"}
        if not isinstance(record, dict) or set(record) != record_keys:
            raise StateError("planned artifact record has invalid fields")
        if not isinstance(event, dict) or set(event) != event_keys:
            raise StateError("planned artifact event has invalid fields")

        artifact_id = record.get("artifact_id")
        artifact_type = record.get("artifact_type")
        relative_path = record.get("path")
        digest = record.get("sha256")
        created_at = record.get("created_at")
        if (
            not isinstance(artifact_id, str)
            or not _SAFE_ID.fullmatch(artifact_id)
        ):
            raise StateError("planned artifact id is invalid")
        if not isinstance(artifact_type, str) or not artifact_type:
            raise StateError("planned artifact type is invalid")
        if not isinstance(relative_path, str):
            raise StateError("planned artifact path is invalid")
        if digest != sha256_bytes(content):
            raise StateConflictError("planned artifact content hash mismatch")
        if not isinstance(created_at, str) or not created_at:
            raise StateError("planned artifact created_at is invalid")
        task_id = record.get("task_id")
        if task_id is not None and (
            not isinstance(task_id, str) or not _SAFE_ID.fullmatch(task_id)
        ):
            raise StateError("planned artifact task_id is invalid")
        source_refs = record.get("source_refs")
        metadata = record.get("metadata")
        if (
            not isinstance(source_refs, list)
            or any(
                not isinstance(reference, str) or not reference
                for reference in source_refs
            )
            or not isinstance(metadata, dict)
        ):
            raise StateError(
                "planned artifact source_refs/metadata are invalid"
            )

        event_id = event.get("event_id")
        if (
            event_id != f"artifact:{artifact_id}:published"
            or event.get("kind") != "artifact.published"
            or event.get("created_at") != created_at
            or event.get("data")
            != {
                "artifact_id": artifact_id,
                "artifact_type": artifact_type,
            }
        ):
            raise StateError(
                "planned artifact publish event does not match its record"
            )

        destination = self._resolve_relative(relative_path)
        if destination.is_symlink():
            raise StateError(
                f"refusing symlink artifact path: {relative_path}"
            )
        with self._exclusive_lease():
            state = self._prepare_writer_state()
            artifacts = _object(state.get("artifacts"), "artifacts")
            existing_record = artifacts.get(artifact_id)
            existing_event = self._find_ledger_record(
                "events",
                str(event_id),
                state,
            )
            if existing_record is not None:
                if existing_record != record:
                    raise StateConflictError(
                        f"artifact {artifact_id!r} already has different metadata"
                    )
                if not destination.is_file():
                    raise StateError(
                        f"artifact {artifact_id!r} is registered but its file is missing"
                    )
                if sha256_file(destination) != digest:
                    raise StateConflictError(
                        f"artifact {artifact_id!r} file hash conflicts with its record"
                    )
                if existing_event is not None:
                    if existing_event != event:
                        raise StateConflictError(
                            f"artifact {artifact_id!r} has a conflicting publish event"
                        )
                    return artifact_id
                self._commit_locked(
                    state,
                    [self._pending("events", event)],
                )
                return artifact_id

            if existing_event is not None:
                raise StateConflictError(
                    f"artifact {artifact_id!r} event exists without its record"
                )
            for other_id, raw in artifacts.items():
                if isinstance(raw, dict) and raw.get("path") == relative_path:
                    raise StateConflictError(
                        f"artifact path {relative_path!r} is already registered "
                        f"to {other_id!r}"
                    )
            if destination.exists():
                if not destination.is_file():
                    raise StateConflictError(
                        f"artifact path is not a regular file: {relative_path}"
                    )
                if sha256_file(destination) != digest:
                    raise StateConflictError(
                        "unregistered planned artifact path has different content: "
                        f"{relative_path}"
                    )
            else:
                atomic_write_bytes(destination, content)
            artifacts[artifact_id] = record
            self._commit_locked(
                state,
                [self._pending("events", event)],
            )
        return artifact_id

    def commit_planned_completion(
        self,
        *,
        result_artifact_ids: Sequence[str],
        transition_event: Mapping[str, Any],
        finalization_id: str,
        manifest_sha256: str,
    ) -> bool:
        """Expose final results only after the exact completion event exists.

        The event is appended before the final atomic ``run.json`` replacement.
        If the process stops between those writes, replay observes the exact
        event and safely completes the state transition without creating a new
        timestamp or transition sequence.
        """

        results = list(result_artifact_ids)
        if (
            len(results) != len(set(results))
            or any(
                not isinstance(value, str) or not _SAFE_ID.fullmatch(value)
                for value in results
            )
        ):
            raise ValueError(
                "result artifact IDs must be unique safe identifiers"
            )
        event = normalize_json(
            dict(transition_event),
            label="planned completion event",
        )
        if not isinstance(event, dict) or set(event) != {
            "event_id",
            "kind",
            "data",
            "created_at",
        }:
            raise StateError("planned completion event has invalid fields")
        event_id = event.get("event_id")
        match = (
            re.fullmatch(r"run:transition:([0-9]{8})", event_id)
            if isinstance(event_id, str)
            else None
        )
        data = event.get("data")
        if (
            match is None
            or event.get("kind") != "run.status"
            or not isinstance(event.get("created_at"), str)
            or not isinstance(data, dict)
            or data.get("to_status") != "completed"
            or data.get("status") != "completed"
        ):
            raise StateError("planned completion event is invalid")
        planned_sequence = int(match.group(1))
        if (
            not isinstance(finalization_id, str)
            or not _SAFE_ID.fullmatch(finalization_id)
            or not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256)
        ):
            raise StateError("planned finalization identity is invalid")

        with self._exclusive_lease():
            state = self._prepare_writer_state()
            finalization = state.get("finalization")
            if (
                not isinstance(finalization, dict)
                or finalization.get("id") != finalization_id
                or finalization.get("manifest_sha256") != manifest_sha256
                or finalization.get("phase")
                not in {"publishing", "completed"}
            ):
                raise StateConflictError(
                    "planned completion does not match the bound manifest"
                )
            artifacts = _object(state.get("artifacts"), "artifacts")
            missing = [value for value in results if value not in artifacts]
            if missing:
                raise StateError(
                    f"result artifacts are not registered: {missing}"
                )
            current_sequence = state.get("transition_seq")
            if (
                isinstance(current_sequence, bool)
                or not isinstance(current_sequence, int)
                or current_sequence < 0
            ):
                raise StateError(
                    "transition_seq must be a non-negative integer"
                )

            existing_event = self._find_ledger_record(
                "events",
                str(event_id),
                state,
            )
            if existing_event is not None and existing_event != event:
                raise StateConflictError(
                    "planned completion event conflicts with its ledger record"
                )
            if state.get("status") == "completed":
                if (
                    current_sequence != planned_sequence
                    or state.get("result_artifact_ids") != results
                    or finalization.get("phase") != "completed"
                    or existing_event is None
                ):
                    raise StateConflictError(
                        "completed run does not match its finalization manifest"
                    )
                return False
            if (
                state.get("status") != "running"
                or current_sequence + 1 != planned_sequence
                or data.get("from_status") != "running"
            ):
                raise StateConflictError(
                    "run cannot apply the planned completion transition"
                )
            if state.get("terminal_error") is not None:
                raise StateConflictError(
                    "failed run cannot publish planned final results"
                )

            if existing_event is None:
                append_jsonl(
                    self.events_path,
                    event,
                    id_field="event_id",
                )
            state["status"] = "completed"
            state["current_stage"] = data.get("stage")
            state["transition_seq"] = planned_sequence
            state["result_artifact_ids"] = results
            finalization["phase"] = "completed"
            state["updated_at"] = event["created_at"]
            atomic_write_json(self.state_path, state)
        return True

    def read_artifact(self, artifact_id: str) -> str:
        state = self.load_state()
        artifacts = _object(state.get("artifacts"), "artifacts")
        record = _object(artifacts.get(artifact_id), f"artifact {artifact_id}")
        path = self._resolve_relative(_string(record.get("path"), "artifact path"))
        content = path.read_text(encoding="utf-8")
        if sha256_text(content) != record.get("sha256"):
            raise StateError(f"artifact hash mismatch: {artifact_id}")
        return content

    def append_decision(
        self,
        record: Mapping[str, Any] | None = None,
        **fields_data: Any,
    ) -> bool:
        """Append a route-owned decision record through the durable outbox."""

        if record is not None and fields_data:
            raise TypeError("pass a decision mapping or keyword fields, not both")
        value = dict(record) if record is not None else dict(fields_data)
        return self.append_ledger_record("decisions", value)

    def record_decision(
        self,
        *,
        decision_id: str,
        gate: str,
        candidate_ref: str,
        decision: str,
        review_ref: str,
        task_id: str,
    ) -> None:
        """Useful-compatible decision wrapper preserving the v1 row shape."""

        if decision not in {"pass", "reject"}:
            raise ValueError(f"unsupported decision: {decision}")
        self.append_decision(
            {
                "decision_id": decision_id,
                "gate": gate,
                "candidate_ref": candidate_ref,
                "decision": decision,
                "review_ref": review_ref,
                "task_id": task_id,
            }
        )

    def append_ledger_record(
        self,
        ledger: str,
        record: Mapping[str, Any],
    ) -> bool:
        """Append one record to an allowlisted ledger, idempotently by ID."""

        if ledger not in _LEDGERS:
            raise ValueError(f"unsupported outbox ledger: {ledger}")
        _, id_field = _LEDGERS[ledger]
        normalized = normalize_json(dict(record), label=f"{ledger} record")
        if not isinstance(normalized, dict):
            raise StateError(f"{ledger} record must be an object")
        record_id = normalized.get(id_field)
        if not isinstance(record_id, str) or not record_id:
            raise StateError(f"{ledger} record requires non-empty {id_field!r}")

        with self._exclusive_lease():
            state = self._prepare_writer_state()
            existing = self._find_ledger_record(ledger, record_id, state)
            if existing is not None:
                if "created_at" not in normalized:
                    comparable = {
                        key: value
                        for key, value in existing.items()
                        if key != "created_at"
                    }
                else:
                    comparable = existing
                if comparable != normalized:
                    raise StateConflictError(
                        f"{id_field} {record_id!r} already has different content"
                    )
                return False
            normalized.setdefault("created_at", utc_now())
            self._commit_locked(state, [self._pending(ledger, normalized)])
        return True

    def set_idea_cards(self, artifact_ids: Sequence[str]) -> None:
        def update(state: dict[str, Any]) -> None:
            state["idea_card_ids"] = list(artifact_ids)

        self._mutate(update)

    def reconcile_pending(self) -> int:
        """Flush the bounded v2 outbox without changing business state."""

        raw = self._read_raw_state()
        if raw["schema_version"] == LEGACY_RUN_SCHEMA_VERSION:
            return 0
        with self._exclusive_lease():
            state = self._read_raw_state()
            return self._reconcile_locked(state)

    def core_inspect(self) -> dict[str, Any]:
        """Return the route-neutral fields used by all projections."""

        state = self.load_state()
        tasks = _object(state.get("tasks"), "tasks")
        counts: dict[str, int] = {}
        for raw in tasks.values():
            task = _object(raw, "task")
            status = _string(task.get("status"), "task status")
            counts[status] = counts.get(status, 0) + 1
        decisions = read_jsonl(self.decisions_path)
        pending = state.get("pending_records", [])
        return {
            "run_id": state.get("run_id"),
            "route_id": _object(state.get("route"), "route").get("id"),
            "status": state.get("status"),
            "current_stage": state.get("current_stage"),
            "task_counts": counts,
            "decision_count": len(decisions),
            "result_artifact_count": len(state.get("result_artifact_ids", [])),
            "needs_reconcile": isinstance(pending, list) and bool(pending),
            "run_dir": str(self.run_dir),
        }

    def inspect(self) -> dict[str, Any]:
        """Compatibility forwarding point for route-aware inspection."""

        from hacksome.core.routes import inspect_run

        return inspect_run(self.run_dir)

    def validate(self) -> list[str]:
        """Compatibility forwarding point for route-aware validation."""

        from hacksome.core.routes import validate_run

        return validate_run(self.run_dir)

    def core_validate(self) -> list[str]:
        """Validate route-neutral input, task, artifact, event, and outbox state."""

        errors: list[str] = []
        try:
            state = self.load_state()
        except (OSError, StateError) as exc:
            return [str(exc)]
        version = state["schema_version"]
        if version == RUN_SCHEMA_VERSION and not self.lock_path.is_file():
            errors.append("v2 run is missing run.lock")

        inputs = state.get("inputs")
        if not isinstance(inputs, dict):
            errors.append("run.json inputs must be an object")
            inputs = {}
        challenge_record = inputs.get("challenge")
        if not isinstance(challenge_record, dict):
            errors.append("run inputs has no challenge record")
        for input_name, raw in inputs.items():
            if not isinstance(raw, dict):
                errors.append(f"input {input_name} must be an object")
                continue
            self._validate_file_record(
                errors,
                raw,
                label=f"input {input_name}",
                path_key="path",
                hash_key="sha256",
            )
        try:
            challenge = self.challenge()
            if not challenge.strip():
                errors.append("challenge is empty")
        except (OSError, StateError, UnicodeError) as exc:
            errors.append(str(exc))

        if version == RUN_SCHEMA_VERSION:
            manifest = state.get("resource_manifest")
            if not isinstance(manifest, dict):
                errors.append("v2 run has no resource_manifest")
            else:
                self._validate_file_record(
                    errors,
                    manifest,
                    label="resource manifest",
                    path_key="path",
                    hash_key="sha256",
                )
            hashes = state.get("config_hashes")
            if not isinstance(hashes, dict):
                errors.append("run.json config_hashes must be an object")
            else:
                for value_key, hash_key in (
                    ("codex_config", "codex_config_sha256"),
                    ("settings", "workflow_settings_sha256"),
                ):
                    expected = hashes.get(hash_key)
                    if not isinstance(expected, str):
                        errors.append(f"config_hashes is missing {hash_key}")
                    elif sha256_json(state.get(value_key)) != expected:
                        errors.append(f"{value_key} hash mismatch")
            if state.get("status") == "failed" and not isinstance(
                state.get("terminal_error"), dict
            ):
                errors.append("failed v2 run has no terminal_error")
            if not isinstance(state.get("secondary_errors"), list):
                errors.append("secondary_errors must be a list")
            if not isinstance(state.get("result_artifact_ids"), list):
                errors.append("result_artifact_ids must be a list")
            wait = state.get("wait")
            if wait is not None and not isinstance(wait, dict):
                errors.append("wait must be null or an object")

        tasks = state.get("tasks")
        if not isinstance(tasks, dict):
            errors.append("run.json tasks must be an object")
            tasks = {}
        for task_id, raw in tasks.items():
            if not isinstance(raw, dict):
                errors.append(f"task {task_id} must be an object")
                continue
            for key in ("request_path", "prompt_path"):
                value = raw.get(key)
                try:
                    present = (
                        isinstance(value, str)
                        and self._resolve_relative(value).is_file()
                    )
                except StateError:
                    present = False
                if not present:
                    errors.append(f"task {task_id} is missing {key}")
            for path_key, hash_key in (
                ("request_path", "request_sha256"),
                ("prompt_path", "prompt_sha256"),
            ):
                self._validate_file_record(
                    errors,
                    raw,
                    label=f"task {task_id}",
                    path_key=path_key,
                    hash_key=hash_key,
                    missing_is_error=False,
                )
            failure_policy = raw.get("failure_policy", "fatal")
            if failure_policy not in {"fatal", "optional_branch"}:
                errors.append(f"task {task_id} has invalid failure_policy")
            status = raw.get("status")
            if status == "succeeded":
                for key in ("result_path", "output_path"):
                    value = raw.get(key)
                    try:
                        present = (
                            isinstance(value, str)
                            and self._resolve_relative(value).is_file()
                        )
                    except StateError:
                        present = False
                    if not present:
                        errors.append(f"task {task_id} is missing {key}")
                for path_key, hash_key in (
                    ("result_path", "result_sha256"),
                    ("output_path", "output_sha256"),
                ):
                    self._validate_file_record(
                        errors,
                        raw,
                        label=f"task {task_id}",
                        path_key=path_key,
                        hash_key=hash_key,
                        missing_is_error=False,
                    )
                if not isinstance(raw.get("session_id"), str) or not raw.get(
                    "session_id"
                ):
                    errors.append(f"task {task_id} has no Session ID")
            try:
                paths = self.task_paths(str(task_id))
            except ValueError:
                errors.append(f"task {task_id} has an unsafe ID")
                continue
            for log_name in ("stdout.jsonl", "stderr.jsonl"):
                if not (paths.raw / log_name).is_file():
                    errors.append(f"task {task_id} is missing raw/{log_name}")

        artifacts = state.get("artifacts")
        if not isinstance(artifacts, dict):
            errors.append("run.json artifacts must be an object")
            artifacts = {}
        registered_paths: dict[str, str] = {}
        for artifact_id, raw in artifacts.items():
            if not isinstance(raw, dict):
                errors.append(f"artifact {artifact_id} must be an object")
                continue
            artifact_path = raw.get("path")
            if not isinstance(artifact_path, str):
                errors.append(f"artifact {artifact_id} has no path")
                continue
            other = registered_paths.setdefault(artifact_path, str(artifact_id))
            if other != str(artifact_id):
                errors.append(
                    f"artifact path {artifact_path} is registered more than once"
                )
            self._validate_file_record(
                errors,
                raw,
                label=f"artifact {artifact_id}",
                path_key="path",
                hash_key="sha256",
            )

        artifact_root = self.run_dir / "artifacts"
        if artifact_root.is_dir():
            registered = set(registered_paths)
            for path in sorted(artifact_root.rglob("*")):
                if path.is_symlink():
                    errors.append(
                        f"artifact tree contains symlink: {self._relative_lexical(path)}"
                    )
                elif path.is_file():
                    relative = self._relative_lexical(path)
                    if relative not in registered:
                        errors.append(f"unregistered artifact file: {relative}")

        try:
            events = read_jsonl(self.events_path)
        except (OSError, StateError) as exc:
            errors.append(str(exc))
            events = []
        event_by_id = {
            row.get("event_id"): row
            for row in events
            if isinstance(row.get("event_id"), str)
        }
        pending = state.get("pending_records", [])
        if version == RUN_SCHEMA_VERSION:
            if not isinstance(pending, list):
                errors.append("pending_records must be a list")
                pending = []
            elif pending:
                errors.append(
                    "run has pending records; run `hacksome reconcile RUN_DIR`"
                )
            for index, raw in enumerate(pending):
                try:
                    self._validate_pending(raw)
                except StateError as exc:
                    errors.append(f"pending_records[{index}]: {exc}")
                if (
                    isinstance(raw, dict)
                    and raw.get("ledger") == "events"
                    and isinstance(raw.get("record"), dict)
                ):
                    event = raw["record"]
                    event_id = event.get("event_id")
                    if isinstance(event_id, str):
                        event_by_id.setdefault(event_id, event)

            sequence = state.get("transition_seq")
            if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
                errors.append("transition_seq must be a non-negative integer")
            else:
                actual: list[int] = []
                for event_id in event_by_id:
                    if isinstance(event_id, str) and event_id.startswith(
                        "run:transition:"
                    ):
                        suffix = event_id.removeprefix("run:transition:")
                        if not suffix.isdigit():
                            errors.append(f"invalid transition event ID: {event_id}")
                        else:
                            actual.append(int(suffix))
                if sorted(actual) != list(range(1, sequence + 1)):
                    errors.append("transition event sequence does not match run.json")

            for artifact_id in artifacts:
                event_id = f"artifact:{artifact_id}:published"
                if event_id not in event_by_id:
                    errors.append(f"artifact {artifact_id} has no publish event")

        result_ids = state.get("result_artifact_ids", [])
        if isinstance(result_ids, list):
            for artifact_id in result_ids:
                if artifact_id not in artifacts:
                    errors.append(f"result artifact is not registered: {artifact_id}")
        return errors

    def _validate_file_record(
        self,
        errors: list[str],
        record: Mapping[str, Any],
        *,
        label: str,
        path_key: str,
        hash_key: str,
        missing_is_error: bool = True,
    ) -> None:
        relative = record.get(path_key)
        expected = record.get(hash_key)
        if not isinstance(relative, str):
            if missing_is_error:
                errors.append(f"{label} has no {path_key}")
            return
        try:
            path = self._resolve_relative(relative)
        except StateError as exc:
            errors.append(f"{label}: {exc}")
            return
        if not path.is_file():
            if missing_is_error:
                errors.append(f"{label} is missing: {relative}")
            return
        if not isinstance(expected, str):
            errors.append(f"{label} has no {hash_key}")
        elif sha256_file(path) != expected:
            if path_key == "path":
                errors.append(f"{label} hash mismatch")
            else:
                errors.append(f"{label} {path_key} hash mismatch")

    def _mutate(
        self,
        callback: Callable[[dict[str, Any]], None],
        *,
        event: Mapping[str, Any] | None = None,
    ) -> None:
        with self._exclusive_lease():
            state = self._prepare_writer_state()
            callback(state)
            state["updated_at"] = utc_now()
            pending = [self._pending("events", event)] if event is not None else []
            self._commit_locked(state, pending)

    def _event(self, kind: str, *, event_id: str, data: Mapping[str, Any]) -> None:
        self.append_ledger_record(
            "events",
            self._new_event(kind, event_id=event_id, data=data),
        )

    @staticmethod
    def _new_event(
        kind: str,
        *,
        event_id: str,
        data: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "event_id": event_id,
            "kind": kind,
            "data": dict(data),
            "created_at": utc_now(),
        }

    @staticmethod
    def _pending(ledger: str, record: Mapping[str, Any]) -> dict[str, Any]:
        return {"ledger": ledger, "record": dict(record)}

    def _exclusive_lease(self) -> Any:
        # The in-process RLock keeps nested Python writers ordered; the POSIX
        # lease coordinates independent CLI/review-server processes.
        class _Lease:
            def __init__(self, hub: RunHub) -> None:
                self.hub = hub
                self.file_lease: Any = None

            def __enter__(self) -> None:
                self.hub._lock.acquire()
                try:
                    raw = self.hub._read_raw_state()
                    if raw["schema_version"] == LEGACY_RUN_SCHEMA_VERSION:
                        raise StateError("schema v1 runs are strictly read-only")
                    self.file_lease = advisory_lease(
                        self.hub.lock_path, exclusive=True, create=True
                    )
                    self.file_lease.__enter__()
                except BaseException:
                    self.hub._lock.release()
                    raise

            def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
                try:
                    if self.file_lease is not None:
                        self.file_lease.__exit__(exc_type, exc, traceback)
                finally:
                    self.hub._lock.release()

        return _Lease(self)

    def _prepare_writer_state(self) -> dict[str, Any]:
        state = self._read_raw_state()
        if state["schema_version"] != RUN_SCHEMA_VERSION:
            raise StateError("schema v1 runs are strictly read-only")
        self._reconcile_locked(state)
        return self._read_raw_state()

    def _commit_locked(
        self,
        state: dict[str, Any],
        pending_records: Sequence[Mapping[str, Any]],
    ) -> None:
        pending = state.get("pending_records")
        if not isinstance(pending, list):
            raise StateError("pending_records must be a list")
        for raw in pending_records:
            normalized = self._validate_pending(raw)
            if normalized not in pending:
                pending.append(normalized)
        state["updated_at"] = utc_now()
        atomic_write_json(self.state_path, state)
        self._reconcile_locked(state)

    def _reconcile_locked(self, state: dict[str, Any]) -> int:
        pending = state.get("pending_records")
        if not isinstance(pending, list):
            raise StateError("pending_records must be a list")
        if not pending:
            return 0
        normalized = [self._validate_pending(raw) for raw in pending]
        for item in normalized:
            ledger = _string(item.get("ledger"), "pending ledger")
            filename, id_field = _LEDGERS[ledger]
            record = _object(item.get("record"), "pending record")
            append_jsonl(self.run_dir / filename, record, id_field=id_field)
        state["pending_records"] = []
        atomic_write_json(self.state_path, state)
        return len(normalized)

    @staticmethod
    def _validate_pending(raw: Any) -> dict[str, Any]:
        normalized = normalize_json(raw, label="pending record")
        if not isinstance(normalized, dict) or set(normalized) != {
            "ledger",
            "record",
        }:
            raise StateError("pending record must contain only ledger and record")
        ledger = normalized.get("ledger")
        if not isinstance(ledger, str) or ledger not in _LEDGERS:
            raise StateError(f"unsupported pending ledger: {ledger!r}")
        record = normalized.get("record")
        if not isinstance(record, dict):
            raise StateError("pending record payload must be an object")
        id_field = _LEDGERS[ledger][1]
        record_id = record.get(id_field)
        if not isinstance(record_id, str) or not record_id:
            raise StateError(f"pending {ledger} record requires {id_field}")
        return normalized

    def _find_ledger_record(
        self,
        ledger: str,
        record_id: str,
        state: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        filename, id_field = _LEDGERS[ledger]
        for record in read_jsonl(self.run_dir / filename):
            if record.get(id_field) == record_id:
                return record
        pending = state.get("pending_records", [])
        if isinstance(pending, list):
            for raw in pending:
                item = self._validate_pending(raw)
                if item["ledger"] == ledger:
                    record = _object(item["record"], "pending record")
                    if record.get(id_field) == record_id:
                        return record
        return None

    def _resolve_relative(self, relative: str) -> Path:
        pure = PurePosixPath(relative)
        if pure.is_absolute() or not pure.parts or ".." in pure.parts:
            raise StateError(f"unsafe run-relative path: {relative!r}")
        resolved = self.run_dir.joinpath(*pure.parts).resolve(strict=False)
        if resolved != self.run_dir and self.run_dir not in resolved.parents:
            raise StateError(f"path escapes run directory: {relative!r}")
        return resolved

    def _relative(self, path: Path) -> str:
        resolved = path.expanduser().resolve(strict=False)
        try:
            return resolved.relative_to(self.run_dir).as_posix()
        except ValueError as exc:
            raise StateError(f"path is outside run directory: {resolved}") from exc

    def _relative_lexical(self, path: Path) -> str:
        try:
            return path.relative_to(self.run_dir).as_posix()
        except ValueError as exc:
            raise StateError(f"path is outside run directory: {path}") from exc


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StateError(f"{label} must be an object")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise StateError(f"{label} must be a non-empty string")
    return value
