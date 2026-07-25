"""Persistent FIFO manager for one-review ephemeral verifier instances."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from hacksome.stages.build.control.runtime_store import atomic_write_json, file_lock, read_json


ReviewKind = Literal["company_objective", "department_objective", "goal_result"]
Verdict = Literal["PASS", "FAIL"]

QUEUED = "queued"
RUNNING = "running"
PASSED = "passed"
FAILED = "failed"
CANCELLED = "cancelled"
TERMINAL_REVIEW_STATES = (PASSED, FAILED, CANCELLED)
ACTIVE_INSTANCE_STATES = ("running", "stopping")


class ReviewError(ValueError):
    pass


def _now() -> float:
    return time.time()


@dataclass(frozen=True)
class ReviewLaunch:
    review_id: str
    review_seq: int
    instance_id: str
    kind: ReviewKind
    subject_id: str
    payload: dict


class VerifierManager:
    """The source of truth for the global, maximum-three review pool.

    ``schedule`` reserves slots and produces launch commands.  A verdict moves
    the instance to ``stopping`` but does not release its slot; only
    ``confirm_instance_stopped`` does that.  Every retry gets a different
    instance id and no verifier session is ever reused.
    """

    def __init__(self, root: str | Path, *, max_instances: int = 3):
        if max_instances <= 0:
            raise ValueError("max_instances must be positive")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_instances = max_instances
        self._lock_path = self.root / ".reviews.lock"
        self._sequence_path = self.root / "sequence.json"

    def _path(self, review_id: str) -> Path:
        return self.root / f"{review_id}.json"

    def _load(self, review_id: str) -> dict:
        review = read_json(self._path(review_id))
        if not isinstance(review, dict):
            raise ReviewError(f"no such review: {review_id}")
        return review

    def _save(self, review: dict) -> None:
        review["updated_at"] = _now()
        atomic_write_json(self._path(review["id"]), review)

    def _next_sequence(self) -> int:
        row = read_json(self._sequence_path, default={})
        current = int(row.get("last", 0)) if isinstance(row, dict) else 0
        value = current + 1
        atomic_write_json(self._sequence_path, {"last": value})
        return value

    @staticmethod
    def _stable_id(request_id: str) -> str:
        digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:16]
        return f"review-{digest}"

    def list_reviews(self) -> list[dict]:
        reviews = []
        for path in self.root.glob("review-*.json"):
            row = read_json(path)
            if isinstance(row, dict):
                reviews.append(row)
        return sorted(reviews, key=lambda row: row["review_seq"])

    def get(self, review_id: str) -> dict:
        return self._load(review_id)

    def enqueue(
        self,
        *,
        kind: ReviewKind,
        subject_id: str,
        requested_by: str,
        payload: dict,
        request_id: str,
    ) -> str:
        if kind not in ("company_objective", "department_objective", "goal_result"):
            raise ReviewError(f"unknown review kind: {kind!r}")
        review_id = self._stable_id(request_id)
        with file_lock(self._lock_path):
            if self._path(review_id).is_file():
                return review_id
            now = _now()
            review = {
                "id": review_id,
                "review_seq": self._next_sequence(),
                "kind": kind,
                "subject_id": subject_id,
                "requested_by": requested_by,
                "payload": payload,
                "status": QUEUED,
                "instance_id": None,
                "instance_state": None,
                "instance_attempt": 0,
                "verdict": None,
                "reason": None,
                "routed": False,
                "created_at": now,
                "updated_at": now,
            }
            self._save(review)
        return review_id

    def _active_instance_count(self) -> int:
        return sum(
            1
            for review in self.list_reviews()
            if review.get("instance_state") in ACTIVE_INSTANCE_STATES
        )

    def schedule(self) -> list[ReviewLaunch]:
        launches: list[ReviewLaunch] = []
        with file_lock(self._lock_path):
            available = self.max_instances - self._active_instance_count()
            if available <= 0:
                return []
            queued = [review for review in self.list_reviews() if review["status"] == QUEUED]
            for review in queued[:available]:
                attempt = int(review.get("instance_attempt", 0)) + 1
                instance_id = f"verifier-{review['review_seq']}-{attempt}"
                review["status"] = RUNNING
                review["instance_attempt"] = attempt
                review["instance_id"] = instance_id
                review["instance_state"] = "running"
                self._save(review)
                launches.append(
                    ReviewLaunch(
                        review_id=review["id"],
                        review_seq=review["review_seq"],
                        instance_id=instance_id,
                        kind=review["kind"],
                        subject_id=review["subject_id"],
                        payload=dict(review["payload"]),
                    )
                )
        return launches

    def running_launches(self) -> list[ReviewLaunch]:
        """Reconstruct idempotent start commands for running review instances."""
        launches = []
        for review in self.list_reviews():
            if review["status"] != RUNNING or review.get("instance_state") != "running":
                continue
            launches.append(
                ReviewLaunch(
                    review_id=review["id"],
                    review_seq=review["review_seq"],
                    instance_id=review["instance_id"],
                    kind=review["kind"],
                    subject_id=review["subject_id"],
                    payload=dict(review["payload"]),
                )
            )
        return launches

    def submit_verdict(
        self,
        review_id: str,
        *,
        instance_id: str,
        verdict: Verdict,
        reason: str,
    ) -> bool:
        if verdict not in ("PASS", "FAIL"):
            raise ReviewError("verdict must be PASS or FAIL")
        if not isinstance(reason, str) or not reason.strip():
            raise ReviewError("verdict reason must be non-empty")
        with file_lock(self._lock_path):
            review = self._load(review_id)
            if review["status"] in TERMINAL_REVIEW_STATES:
                return False
            if review["status"] != RUNNING:
                raise ReviewError(f"review {review_id} is not running")
            if review.get("instance_id") != instance_id:
                raise ReviewError("verdict instance does not own this review")
            if review.get("instance_state") != "running":
                return False
            review["status"] = PASSED if verdict == "PASS" else FAILED
            review["verdict"] = verdict
            review["reason"] = reason.strip()
            review["instance_state"] = "stopping"
            self._save(review)
            return True

    def cancel(self, review_id: str, *, reason: str) -> bool:
        with file_lock(self._lock_path):
            review = self._load(review_id)
            if review["status"] in TERMINAL_REVIEW_STATES:
                return False
            review["status"] = CANCELLED
            review["reason"] = reason
            if review.get("instance_state") == "running":
                review["instance_state"] = "stopping"
            else:
                review["instance_id"] = None
                review["instance_state"] = None
            self._save(review)
            return True

    def instance_failed(self, review_id: str, *, instance_id: str, reason: str) -> bool:
        """Requeue one review after its ephemeral instance is confirmed gone."""
        with file_lock(self._lock_path):
            review = self._load(review_id)
            if review["status"] != RUNNING:
                return False
            if review.get("instance_id") != instance_id:
                return False
            review["status"] = QUEUED
            review["instance_id"] = None
            review["instance_state"] = None
            review["last_instance_error"] = reason
            self._save(review)
            return True

    def confirm_instance_stopped(self, review_id: str, *, instance_id: str) -> bool:
        with file_lock(self._lock_path):
            review = self._load(review_id)
            if review.get("instance_id") != instance_id:
                return False
            if review.get("instance_state") != "stopping":
                return False
            review["instance_id"] = None
            review["instance_state"] = None
            self._save(review)
            return True

    def inspect_pool(self) -> dict:
        reviews = self.list_reviews()
        return {
            "max_instances": self.max_instances,
            "active_instances": sum(
                1 for row in reviews if row.get("instance_state") in ACTIVE_INSTANCE_STATES
            ),
            "queued": sum(1 for row in reviews if row["status"] == QUEUED),
            "running": sum(1 for row in reviews if row["status"] == RUNNING),
        }

    def terminal_unrouted(self) -> list[dict]:
        return [
            review
            for review in self.list_reviews()
            if review["status"] in (PASSED, FAILED) and not review.get("routed", False)
        ]

    def mark_routed(self, review_id: str) -> None:
        with file_lock(self._lock_path):
            review = self._load(review_id)
            if review["status"] not in (PASSED, FAILED):
                raise ReviewError("only a verdict-bearing review can be routed")
            review["routed"] = True
            self._save(review)

    def stopping_instances(self) -> list[dict]:
        return [
            review
            for review in self.list_reviews()
            if review.get("instance_state") == "stopping" and review.get("instance_id")
        ]


def main() -> None:
    """Keep the deterministic service alive; Hub drives it through persisted state."""
    import os

    root = os.environ.get("REVIEWS_ROOT", "/shared/reviews")
    manager = VerifierManager(root, max_instances=int(os.environ.get("VERIFIER_MAX", "3")))
    print(f"[verifier-manager] ready root={manager.root} max={manager.max_instances}", flush=True)
    while True:
        time.sleep(30)


if __name__ == "__main__":
    main()
