"""Strict-FIFO Goal state machine for one Hackathon Team."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

from hacksome.stages.build.control.runtime_store import (
    atomic_write_json,
    file_lock,
    read_json,
    require_identifier,
)


OPEN = "open"
CLAIMED = "claimed"
RUNNING = "running"
REPORTED = "reported"
VERIFYING = "verifying"
DONE = "done"
CANCELLED = "cancelled"

NON_TERMINAL = (OPEN, CLAIMED, RUNNING, REPORTED, VERIFYING)
TERMINAL = (DONE, CANCELLED)
ACTIVE_WORKER_STATES = ("starting", "running", "awaiting_verdict", "resuming", "stopping")


class GoalError(ValueError):
    pass


def _now() -> float:
    return time.time()


def _goal_id(request_id: str) -> str:
    return "goal-" + hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class WorkerLaunch:
    goal_id: str
    worker_id: str
    intent: str
    command_id: str


class TeamGoalScheduler:
    """Persistent Goal truth with exactly one concurrent Worker lifecycle."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_workers = 1
        self._lock_path = self.root / ".scheduler.lock"
        self._sequence_path = self.root / "sequence.json"

    def _path(self, goal_id: str) -> Path:
        return self.root / f"{goal_id}.json"

    def _load(self, goal_id: str) -> dict:
        goal = read_json(self._path(goal_id))
        if not isinstance(goal, dict):
            raise GoalError(f"no such goal: {goal_id}")
        return goal

    def _save(self, goal: dict) -> None:
        goal["updated_at"] = _now()
        atomic_write_json(self._path(goal["id"]), goal)

    def _next_sequence(self) -> int:
        row = read_json(self._sequence_path, default={})
        current = int(row.get("last", 0)) if isinstance(row, dict) else 0
        value = current + 1
        atomic_write_json(self._sequence_path, {"last": value})
        return value

    def get(self, goal_id: str) -> dict:
        return self._load(goal_id)

    def list_goals(self) -> list[dict]:
        rows = [
            row
            for path in self.root.glob("goal-*.json")
            if isinstance((row := read_json(path)), dict)
        ]
        return sorted(rows, key=lambda row: row["enqueue_seq"])

    def create_goal(
        self,
        *,
        intent: str,
        acceptance: str | None,
        request_id: str,
    ) -> str:
        if not isinstance(intent, str) or not intent.strip():
            raise GoalError("intent must be non-empty")
        if acceptance is not None and (
            not isinstance(acceptance, str) or not acceptance.strip()
        ):
            raise GoalError("acceptance must be non-empty when provided")
        goal_id = _goal_id(request_id)
        with file_lock(self._lock_path):
            if self._path(goal_id).is_file():
                return goal_id
            now = _now()
            self._save(
                {
                    "id": goal_id,
                    "intent": intent.strip(),
                    "acceptance": acceptance.strip() if acceptance else None,
                    "status": OPEN,
                    "enqueue_seq": self._next_sequence(),
                    "worker_id": None,
                    "worker_state": None,
                    "start_command_pending": False,
                    "start_attempts": 0,
                    "last_start_failure_operation": None,
                    "attempts": 0,
                    "latest_feedback": None,
                    "last_result_operation": None,
                    "last_turn_failure_operation": None,
                    "session_token": None,
                    "active_review_id": None,
                    "last_review_id": None,
                    "cancelled_by": None,
                    "cancel_reason": None,
                    "cancelled_at": None,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        return goal_id

    @staticmethod
    def _launch(goal: dict) -> WorkerLaunch:
        return WorkerLaunch(
            goal_id=goal["id"],
            worker_id=goal["worker_id"],
            intent=goal["intent"],
            command_id=f"start:{goal['id']}:{goal['start_attempts']}",
        )

    def _active_worker_count(self) -> int:
        return sum(
            1
            for goal in self.list_goals()
            if goal.get("worker_state") in ACTIVE_WORKER_STATES
        )

    def schedule_one(self) -> WorkerLaunch | None:
        with file_lock(self._lock_path):
            starting = [
                goal
                for goal in self.list_goals()
                if goal["status"] == CLAIMED and goal.get("worker_state") == "starting"
            ]
            if starting:
                head = min(starting, key=lambda row: row["enqueue_seq"])
                if head.get("start_command_pending"):
                    head["start_command_pending"] = False
                    self._save(head)
                    return self._launch(head)
                return None
            if self._active_worker_count() >= 1:
                return None
            opens = [goal for goal in self.list_goals() if goal["status"] == OPEN]
            if not opens:
                return None
            goal = min(opens, key=lambda row: row["enqueue_seq"])
            goal["status"] = CLAIMED
            goal["worker_id"] = f"worker-{goal['enqueue_seq']}"
            goal["worker_state"] = "starting"
            goal["start_attempts"] = 1
            self._save(goal)
            return self._launch(goal)

    def starting_launches(self) -> list[WorkerLaunch]:
        return [
            self._launch(goal)
            for goal in self.list_goals()
            if goal["status"] == CLAIMED and goal.get("worker_state") == "starting"
        ]

    def worker_start_failed(
        self,
        goal_id: str,
        *,
        worker_id: str,
        reason: str,
        operation_id: str | None = None,
    ) -> bool:
        with file_lock(self._lock_path):
            goal = self._load(goal_id)
            if operation_id and goal.get("last_start_failure_operation") == operation_id:
                return False
            self._require(goal, (CLAIMED,), "worker_start_failed")
            self._require_worker(goal, worker_id)
            goal["worker_state"] = "starting"
            goal["start_attempts"] += 1
            goal["start_command_pending"] = True
            goal["latest_feedback"] = str(reason)
            goal["last_start_failure_operation"] = operation_id
            self._save(goal)
            return True

    def worker_started(self, goal_id: str, *, worker_id: str) -> None:
        with file_lock(self._lock_path):
            goal = self._load(goal_id)
            if (
                goal["status"] == RUNNING
                and goal.get("worker_id") == worker_id
                and goal.get("worker_state") == "running"
            ):
                return
            self._require(goal, (CLAIMED,), "worker_started")
            self._require_worker(goal, worker_id)
            goal["status"] = RUNNING
            goal["worker_state"] = "running"
            goal["latest_feedback"] = None
            self._save(goal)

    def record_session_token(
        self, goal_id: str, *, worker_id: str, session_token: str
    ) -> None:
        if not session_token:
            return
        with file_lock(self._lock_path):
            goal = self._load(goal_id)
            self._require_worker(goal, worker_id)
            goal["session_token"] = session_token
            self._save(goal)

    def worker_turn_failed(
        self,
        goal_id: str,
        *,
        worker_id: str,
        reason: str,
        operation_id: str | None = None,
    ) -> bool:
        if not isinstance(reason, str) or not reason.strip():
            raise GoalError("worker turn failure reason must be non-empty")
        with file_lock(self._lock_path):
            goal = self._load(goal_id)
            self._require_worker(goal, worker_id)
            if operation_id and goal.get("last_turn_failure_operation") == operation_id:
                return False
            if goal["status"] != RUNNING:
                return False
            goal["worker_state"] = "resuming"
            goal["attempts"] += 1
            goal["latest_feedback"] = reason.strip()
            goal["last_turn_failure_operation"] = operation_id
            self._save(goal)
            return True

    def submit_result(
        self,
        goal_id: str,
        *,
        worker_id: str,
        session_token: str | None,
        operation_id: str | None = None,
    ) -> bool:
        with file_lock(self._lock_path):
            goal = self._load(goal_id)
            if operation_id and goal.get("last_result_operation") == operation_id:
                return False
            self._require(goal, (RUNNING,), "submit_result")
            self._require_worker(goal, worker_id)
            goal["status"] = REPORTED
            goal["worker_state"] = "awaiting_verdict"
            goal["session_token"] = session_token
            goal["last_result_operation"] = operation_id
            self._save(goal)
            return True

    def begin_verification(self, goal_id: str, *, review_id: str) -> None:
        with file_lock(self._lock_path):
            goal = self._load(goal_id)
            if goal["status"] == VERIFYING and goal.get("active_review_id") == review_id:
                return
            self._require(goal, (REPORTED,), "begin_verification")
            goal["status"] = VERIFYING
            goal["active_review_id"] = review_id
            self._save(goal)

    def verification_passed(self, goal_id: str, *, review_id: str) -> bool:
        with file_lock(self._lock_path):
            goal = self._load(goal_id)
            if goal.get("last_review_id") == review_id and goal["status"] == DONE:
                return False
            self._require_review(goal, review_id)
            self._require(goal, (VERIFYING,), "verification_passed")
            goal["status"] = DONE
            goal["worker_state"] = "stopping"
            goal["active_review_id"] = None
            goal["last_review_id"] = review_id
            self._save(goal)
            return True

    def verification_failed(
        self, goal_id: str, *, review_id: str, feedback: str
    ) -> bool:
        if not isinstance(feedback, str) or not feedback.strip():
            raise GoalError("verification feedback must be non-empty")
        with file_lock(self._lock_path):
            goal = self._load(goal_id)
            if goal.get("last_review_id") == review_id and goal["status"] == RUNNING:
                return False
            self._require_review(goal, review_id)
            self._require(goal, (VERIFYING,), "verification_failed")
            goal["status"] = RUNNING
            goal["worker_state"] = "resuming"
            goal["attempts"] += 1
            goal["latest_feedback"] = feedback.strip()
            goal["active_review_id"] = None
            goal["last_review_id"] = review_id
            self._save(goal)
            return True

    def worker_resumed(
        self, goal_id: str, *, worker_id: str, session_token: str | None
    ) -> None:
        with file_lock(self._lock_path):
            goal = self._load(goal_id)
            if (
                goal["status"] == RUNNING
                and goal.get("worker_id") == worker_id
                and goal.get("worker_state") == "running"
            ):
                return
            self._require(goal, (RUNNING,), "worker_resumed")
            self._require_worker(goal, worker_id)
            if goal.get("worker_state") != "resuming":
                raise GoalError("worker is not awaiting a resume turn")
            goal["worker_state"] = "running"
            if session_token:
                goal["session_token"] = session_token
            self._save(goal)

    def cancel(self, goal_id: str, *, cancelled_by: str, reason: str) -> bool:
        cancelled_by = require_identifier(cancelled_by, label="actor id")
        if not isinstance(reason, str) or not reason.strip():
            raise GoalError("cancel reason must be non-empty")
        with file_lock(self._lock_path):
            goal = self._load(goal_id)
            if goal["status"] in TERMINAL:
                return False
            goal["status"] = CANCELLED
            goal["cancelled_by"] = cancelled_by
            goal["cancel_reason"] = reason.strip()
            goal["cancelled_at"] = _now()
            goal["active_review_id"] = None
            goal["worker_state"] = "stopping" if goal.get("worker_id") else None
            self._save(goal)
            return True

    def worker_stopped(self, goal_id: str, *, worker_id: str) -> None:
        with file_lock(self._lock_path):
            goal = self._load(goal_id)
            if (
                goal["status"] in TERMINAL
                and goal.get("worker_id") == worker_id
                and goal.get("worker_state") == "stopped"
            ):
                return
            self._require(goal, TERMINAL, "worker_stopped")
            self._require_worker(goal, worker_id)
            if goal.get("worker_state") != "stopping":
                raise GoalError("worker is not stopping")
            goal["worker_state"] = "stopped"
            self._save(goal)

    def inspect(self) -> dict:
        goals = self.list_goals()
        counts = {state: 0 for state in (*NON_TERMINAL, *TERMINAL)}
        for goal in goals:
            counts[goal["status"]] += 1
        return {
            "counts": counts,
            "active_workers": self._active_worker_count(),
            "max_workers": 1,
            "goals": goals,
        }

    @staticmethod
    def _require(goal: dict, allowed: tuple[str, ...], action: str) -> None:
        if goal["status"] not in allowed:
            raise GoalError(
                f"illegal {action}: goal {goal['id']} is {goal['status']!r}; expected {allowed}"
            )

    @staticmethod
    def _require_worker(goal: dict, worker_id: str) -> None:
        if goal.get("worker_id") != worker_id:
            raise GoalError("worker does not own this goal")

    @staticmethod
    def _require_review(goal: dict, review_id: str) -> None:
        if goal.get("active_review_id") != review_id:
            raise GoalError("review does not own this Goal transition")
