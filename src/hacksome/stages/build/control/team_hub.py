"""Deterministic control plane for one autonomous Hackathon Team."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from hacksome.stages.build.control.inbox import FileInbox, make_ime
from hacksome.stages.build.control.lead_brief import (
    LeadBriefCheckpointRequest,
    LeadBriefError,
    LeadBriefStore,
    canonical_goal_state,
    parse_lead_reflection_memory_enabled,
    redact_checkpoint_audit_request,
    redact_lead_brief_audit_result,
)
from hacksome.stages.build.control.method_adapter import (
    ActorContext,
    ActorKind,
    AuditRequest,
    AuditResult,
    MethodAdapter,
    MethodError,
)
from hacksome.stages.build.control.runtime_store import (
    atomic_write_json,
    file_lock,
    read_json,
)
from hacksome.stages.build.control.team_http import TeamHTTPServer
from hacksome.stages.build.control.team_scheduler import (
    NON_TERMINAL,
    TeamGoalScheduler,
    WorkerLaunch,
)
from hacksome.stages.build.control.team_store import TeamLayout
from hacksome.stages.build.control.verifier_manager import ReviewLaunch, VerifierManager

LEAD_KEY = "lead"
LEAD_CAPABILITIES = ("create_goal", "list_my_goals", "cancel_goal")
LEAD_BRIEF_CAPABILITIES = ("read_lead_brief", "checkpoint_lead_brief")
MESSAGE_TYPES = frozenset({"team_started", "goal_batch_drained"})
MESSAGE_MAX_BYTES = 64 * 1024
logger = logging.getLogger(__name__)


class TeamHubError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts)
    return f"{prefix}-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _payload_fields(
    payload: dict,
    *,
    required: set[str] | frozenset[str] = frozenset(),
    optional: set[str] | frozenset[str] = frozenset(),
) -> None:
    keys = set(payload)
    missing = set(required) - keys
    extra = keys - set(required) - set(optional)
    if missing:
        raise TeamHubError(f"missing payload fields: {sorted(missing)}")
    if extra:
        raise TeamHubError(f"unknown payload fields: {sorted(extra)}")


class TeamHub:
    """One resident Lead plus sequential Worker and Verifier lifecycles."""

    def __init__(
        self,
        root: str | os.PathLike,
        *,
        team_id: str = "hackathon-team",
        lead_reflection_memory_enabled: bool | None = None,
    ):
        self.layout = TeamLayout.initialize(root)
        self.team_id = team_id
        if lead_reflection_memory_enabled is None:
            lead_reflection_memory_enabled = parse_lead_reflection_memory_enabled(
                os.environ.get("LEAD_REFLECTION_MEMORY_ENABLED")
            )
        if not isinstance(lead_reflection_memory_enabled, bool):
            raise TeamHubError("lead_reflection_memory_enabled must be a boolean")
        self.lead_reflection_memory_enabled = lead_reflection_memory_enabled
        self.inbox = FileInbox(self.layout.inbox, poll_tick=0.05)
        self.scheduler = TeamGoalScheduler(self.layout.ledger)
        self.reviews = VerifierManager(self.layout.reviews, max_instances=1)
        self.lead_briefs = LeadBriefStore(self.layout.memory, team_id=team_id)
        self.adapter = MethodAdapter(self.layout)
        self._hub_lock = self.layout.control / ".hub.lock"
        self._register_methods()
        self._ensure_started()

    def _register(
        self,
        method: str,
        actors: set[ActorKind],
        handler: Callable[[ActorContext, dict, str], object],
        *,
        audit_request: AuditRequest | None = None,
        audit_result: AuditResult | None = None,
    ) -> None:
        def guarded(actor: ActorContext, payload: dict, request_id: str):
            try:
                with file_lock(self._hub_lock):
                    return handler(actor, payload, request_id)
            except MethodError:
                raise
            except LeadBriefError as exc:
                raise MethodError(exc.code, str(exc)) from exc
            except (ValueError, RuntimeError) as exc:
                raise MethodError("invalid_state", str(exc)) from exc

        self.adapter.register(
            method,
            actors=actors,
            handler=guarded,
            audit_request=audit_request,
            audit_result=audit_result,
        )

    def _register_methods(self) -> None:
        self._register(
            "wake_context",
            {"lead"},
            self._wake_context,
            audit_result=redact_lead_brief_audit_result,
        )
        self._register("peek_message", {"lead"}, self._peek_message)
        self._register("ack_message", {"lead"}, self._ack_message)
        self._register("wake_completed", {"lead"}, self._wake_completed)
        self._register("create_goal", {"lead"}, self._create_goal)
        self._register("list_my_goals", {"lead"}, self._list_my_goals)
        self._register("cancel_goal", {"lead"}, self._cancel_goal)
        self._register(
            "read_lead_brief",
            {"lead"},
            self._read_lead_brief,
            audit_result=redact_lead_brief_audit_result,
        )
        self._register(
            "checkpoint_lead_brief",
            {"lead"},
            self._checkpoint_lead_brief,
            audit_request=redact_checkpoint_audit_request,
        )
        self._register("submit_result", {"worker"}, self._submit_result)
        self._register("submit_verdict", {"verifier"}, self._submit_verdict)
        self._register("worker_started", {"manager"}, self._worker_started)
        self._register("worker_start_failed", {"manager"}, self._worker_start_failed)
        self._register("worker_resumed", {"manager"}, self._worker_resumed)
        self._register("worker_turn_finished", {"manager"}, self._worker_turn_finished)
        self._register("worker_stopped", {"manager"}, self._worker_stopped)
        self._register(
            "verifier_instance_stopped",
            {"manager"},
            self._verifier_instance_stopped,
        )
        self._register(
            "verifier_instance_failed",
            {"manager"},
            self._verifier_instance_failed,
        )

    def call(self, actor: ActorContext, request: object) -> dict:
        return self.adapter.call(actor, request)

    @staticmethod
    def _require_lead(actor: ActorContext) -> None:
        if actor.kind != "lead" or actor.actor_id != LEAD_KEY:
            raise TeamHubError("Lead actor must be bound as lead")

    @staticmethod
    def _require_manager(actor: ActorContext, manager_id: str) -> None:
        if actor.kind != "manager" or actor.actor_id != manager_id:
            raise TeamHubError(f"method requires {manager_id}")

    # -- resident Lead -------------------------------------------------

    def _wake_context(
        self, actor: ActorContext, payload: dict, request_id: str
    ) -> dict:
        _payload_fields(payload)
        self._require_lead(actor)
        result: dict[str, object] = {
            "actor_id": LEAD_KEY,
            "capabilities": list(
                LEAD_CAPABILITIES
                + (
                    LEAD_BRIEF_CAPABILITIES
                    if self.lead_reflection_memory_enabled
                    else ()
                )
            ),
        }
        if self.lead_reflection_memory_enabled:
            current_goal_seq, goal_state_sha256 = self._lead_goal_state()
            result["lead_brief"] = self.lead_briefs.read(
                current_goal_seq=current_goal_seq,
                goal_state_sha256=goal_state_sha256,
                enabled=True,
            )
        return result

    def _read_lead_brief(
        self,
        actor: ActorContext,
        payload: dict,
        request_id: str,
    ) -> dict:
        _payload_fields(payload)
        self._require_lead(actor)
        if not self.lead_reflection_memory_enabled:
            return self.lead_briefs.disabled_projection()
        current_goal_seq, goal_state_sha256 = self._lead_goal_state()
        return self.lead_briefs.read(
            current_goal_seq=current_goal_seq,
            goal_state_sha256=goal_state_sha256,
            enabled=True,
        )

    def _checkpoint_lead_brief(
        self,
        actor: ActorContext,
        payload: dict,
        request_id: str,
    ) -> dict:
        self._require_lead(actor)
        if not self.lead_reflection_memory_enabled:
            raise LeadBriefError(
                "feature_disabled",
                "Lead reflection memory is disabled",
            )
        checkpoint = LeadBriefCheckpointRequest.from_payload(payload)
        current_goal_seq, goal_state_sha256 = self._lead_goal_state()
        return self.lead_briefs.checkpoint(
            checkpoint,
            current_goal_seq=current_goal_seq,
            goal_state_sha256=goal_state_sha256,
        )

    def _peek_message(
        self, actor: ActorContext, payload: dict, request_id: str
    ) -> dict:
        _payload_fields(payload)
        self._require_lead(actor)
        return {"message": self.inbox.peek_one(LEAD_KEY)}

    def _ack_receipt_path(self, message_id: str) -> Path:
        digest = hashlib.sha256(message_id.encode("utf-8")).hexdigest()
        return self.layout.control / "acks" / f"{digest}.json"

    def _ack_bound_message(self, message_id: str) -> bool:
        if not isinstance(message_id, str) or not message_id:
            raise TeamHubError("message_id must be non-empty")
        receipt = self._ack_receipt_path(message_id)
        if receipt.is_file():
            return False
        head = self.inbox.peek_one(LEAD_KEY)
        if not head or head.get("id") != message_id:
            if self.inbox.was_consumed(LEAD_KEY, message_id):
                atomic_write_json(
                    receipt,
                    {
                        "actor_id": LEAD_KEY,
                        "message_id": message_id,
                        "acked_at": _utc_now(),
                        "recovered_after_cursor_advance": True,
                    },
                )
                return False
            raise TeamHubError("message is not the current FIFO head")
        self.inbox.ack_one(LEAD_KEY)
        atomic_write_json(
            receipt,
            {
                "actor_id": LEAD_KEY,
                "message_id": message_id,
                "acked_at": _utc_now(),
            },
        )
        return True

    def _ack_message(self, actor: ActorContext, payload: dict, request_id: str) -> dict:
        _payload_fields(payload, required={"message_id"})
        self._require_lead(actor)
        return {
            "acked": self._ack_bound_message(payload["message_id"]),
            "message_id": payload["message_id"],
        }

    def _wake_completed(
        self, actor: ActorContext, payload: dict, request_id: str
    ) -> dict:
        _payload_fields(
            payload,
            required={"wake_id", "finished_at"},
            optional={"message_id"},
        )
        self._require_lead(actor)
        message_id = payload.get("message_id")
        acked = self._ack_bound_message(message_id) if message_id is not None else False
        memory_completion: dict | None = None
        if self.lead_reflection_memory_enabled:
            current_goal_seq, goal_state_sha256 = self._lead_goal_state()
            try:
                memory_completion = self.lead_briefs.record_wake_completion(
                    payload["wake_id"],
                    current_goal_seq=current_goal_seq,
                    goal_state_sha256=goal_state_sha256,
                )
            except LeadBriefError as exc:
                logger.warning(
                    "Lead brief wake completion failed team=%s wake=%s code=%s",
                    self.team_id,
                    payload["wake_id"],
                    exc.code,
                )
                memory_completion = {
                    "action": "error",
                    "error_code": exc.code,
                }
        completion = {
            "agent_id": LEAD_KEY,
            "message_id": message_id,
            "wake_id": payload["wake_id"],
            "finished_at": payload["finished_at"],
        }
        if memory_completion is not None:
            completion["lead_brief"] = memory_completion
        atomic_write_json(
            self.layout.control / "wake-completions" / f"{payload['wake_id']}.json",
            completion,
        )
        result: dict[str, object] = {"recorded": True, "acked": acked}
        if memory_completion is not None:
            result["lead_brief"] = memory_completion
        return result

    # -- Goal methods --------------------------------------------------

    def _create_goal(self, actor: ActorContext, payload: dict, request_id: str) -> dict:
        _payload_fields(payload, required={"intent"}, optional={"acceptance"})
        self._require_lead(actor)
        goal_id = self.scheduler.create_goal(
            intent=payload["intent"],
            acceptance=payload.get("acceptance"),
            request_id=request_id,
        )
        self._schedule_workers()
        return self._goal_projection(self.scheduler.get(goal_id))

    def _list_my_goals(
        self, actor: ActorContext, payload: dict, request_id: str
    ) -> dict:
        _payload_fields(payload)
        self._require_lead(actor)
        return {
            "goals": [self._goal_projection(row) for row in self.scheduler.list_goals()]
        }

    def _cancel_goal(self, actor: ActorContext, payload: dict, request_id: str) -> dict:
        _payload_fields(payload, required={"goal_id", "reason"})
        self._require_lead(actor)
        goal = self.scheduler.get(payload["goal_id"])
        review_id = goal.get("active_review_id")
        changed = self.scheduler.cancel(
            goal["id"], cancelled_by=LEAD_KEY, reason=payload["reason"]
        )
        goal = self.scheduler.get(goal["id"])
        if changed and review_id:
            self.reviews.cancel(review_id, reason="Goal cancelled")
        if goal.get("worker_id") and goal.get("worker_state") == "stopping":
            self._write_worker_stop(goal)
        self._emit_stopping_verifiers()
        self._schedule_workers()
        self._maybe_signal_batch_drained()
        return {"changed": changed, "goal": self._goal_projection(goal)}

    def _submit_result(
        self, actor: ActorContext, payload: dict, request_id: str
    ) -> dict:
        _payload_fields(payload)
        if not actor.goal_id:
            raise TeamHubError("Worker context has no Goal")
        goal = self.scheduler.get(actor.goal_id)
        if goal.get("worker_id") != actor.actor_id:
            raise TeamHubError("Worker does not own this Goal")
        changed = self.scheduler.submit_result(
            actor.goal_id,
            worker_id=actor.actor_id,
            session_token=goal.get("session_token"),
            operation_id=request_id,
        )
        goal = self.scheduler.get(actor.goal_id)
        if not changed and goal["status"] != "reported":
            return {
                "goal_id": goal["id"],
                "review_id": goal.get("active_review_id") or goal.get("last_review_id"),
                "status": goal["status"],
            }
        review_id = self.reviews.enqueue(
            kind="goal_result",
            subject_id=goal["id"],
            requested_by=actor.actor_id,
            payload={
                "goal_id": goal["id"],
                "intent": goal["intent"],
                "acceptance": goal.get("acceptance"),
            },
            request_id=f"goal-result:{request_id}",
        )
        self.scheduler.begin_verification(goal["id"], review_id=review_id)
        self._schedule_verifiers()
        return {"goal_id": goal["id"], "review_id": review_id, "status": "verifying"}

    # -- Worker manager callbacks -------------------------------------

    def _worker_started(
        self, actor: ActorContext, payload: dict, request_id: str
    ) -> dict:
        self._require_manager(actor, "worker-manager")
        _payload_fields(
            payload, required={"goal_id", "worker_id"}, optional={"started_at"}
        )
        self.scheduler.worker_started(
            payload["goal_id"], worker_id=payload["worker_id"]
        )
        return self._goal_projection(self.scheduler.get(payload["goal_id"]))

    def _worker_start_failed(
        self, actor: ActorContext, payload: dict, request_id: str
    ) -> dict:
        self._require_manager(actor, "worker-manager")
        _payload_fields(payload, required={"goal_id", "worker_id", "reason"})
        self.scheduler.worker_start_failed(
            payload["goal_id"],
            worker_id=payload["worker_id"],
            reason=payload["reason"],
            operation_id=request_id,
        )
        self._schedule_workers()
        return self._goal_projection(self.scheduler.get(payload["goal_id"]))

    def _worker_resumed(
        self, actor: ActorContext, payload: dict, request_id: str
    ) -> dict:
        self._require_manager(actor, "worker-manager")
        _payload_fields(
            payload, required={"goal_id", "worker_id"}, optional={"session_token"}
        )
        self.scheduler.worker_resumed(
            payload["goal_id"],
            worker_id=payload["worker_id"],
            session_token=payload.get("session_token"),
        )
        return self._goal_projection(self.scheduler.get(payload["goal_id"]))

    def _worker_turn_finished(
        self, actor: ActorContext, payload: dict, request_id: str
    ) -> dict:
        self._require_manager(actor, "worker-manager")
        _payload_fields(
            payload,
            required={"goal_id", "worker_id", "ok"},
            optional={"session_token", "error"},
        )
        if payload.get("session_token"):
            self.scheduler.record_session_token(
                payload["goal_id"],
                worker_id=payload["worker_id"],
                session_token=payload["session_token"],
            )
        goal = self.scheduler.get(payload["goal_id"])
        if goal["status"] == "running" and goal.get("worker_state") == "running":
            reason = (
                payload.get("error")
                if not payload["ok"]
                else "Worker turn ended without submit_result"
            ) or "Worker runtime failed"
            changed = self.scheduler.worker_turn_failed(
                payload["goal_id"],
                worker_id=payload["worker_id"],
                reason=reason,
                operation_id=request_id,
            )
            goal = self.scheduler.get(payload["goal_id"])
            if changed:
                self._write_worker_resume(goal)
        return self._goal_projection(goal)

    def _worker_stopped(
        self, actor: ActorContext, payload: dict, request_id: str
    ) -> dict:
        self._require_manager(actor, "worker-manager")
        _payload_fields(payload, required={"goal_id", "worker_id"})
        self.scheduler.worker_stopped(
            payload["goal_id"], worker_id=payload["worker_id"]
        )
        self._schedule_workers()
        self._maybe_signal_batch_drained()
        return self._goal_projection(self.scheduler.get(payload["goal_id"]))

    # -- Verifier ------------------------------------------------------

    def _submit_verdict(
        self, actor: ActorContext, payload: dict, request_id: str
    ) -> dict:
        _payload_fields(payload, required={"verdict", "reason"}, optional={"review_id"})
        if not actor.review_id:
            raise TeamHubError("Verifier context has no review")
        if payload.get("review_id") not in (None, actor.review_id):
            raise TeamHubError("Verifier can submit only its bound review")
        review = self.reviews.get(actor.review_id)
        if review.get("instance_id") != actor.actor_id:
            raise TeamHubError("Verifier instance does not own this review")
        accepted = self.reviews.submit_verdict(
            actor.review_id,
            instance_id=actor.actor_id,
            verdict=payload["verdict"],
            reason=payload["reason"],
        )
        if accepted:
            self._route_review(self.reviews.get(actor.review_id))
            self.reviews.mark_routed(actor.review_id)
        self._emit_stopping_verifiers()
        self._schedule_verifiers()
        return {
            "accepted": accepted,
            "review": self._review_projection(self.reviews.get(actor.review_id)),
        }

    def _route_review(self, review: dict) -> None:
        if review["kind"] != "goal_result":
            raise TeamHubError("Team verifier only accepts Goal results")
        if review["verdict"] == "PASS":
            changed = self.scheduler.verification_passed(
                review["subject_id"], review_id=review["id"]
            )
            if changed:
                self._write_worker_stop(self.scheduler.get(review["subject_id"]))
            return
        changed = self.scheduler.verification_failed(
            review["subject_id"],
            review_id=review["id"],
            feedback=review["reason"],
        )
        if changed:
            self._write_worker_resume(self.scheduler.get(review["subject_id"]))

    def _verifier_instance_stopped(
        self, actor: ActorContext, payload: dict, request_id: str
    ) -> dict:
        self._require_manager(actor, "verifier-manager")
        _payload_fields(payload, required={"review_id", "instance_id"})
        changed = self.reviews.confirm_instance_stopped(
            payload["review_id"], instance_id=payload["instance_id"]
        )
        self._schedule_verifiers()
        return {"changed": changed}

    def _verifier_instance_failed(
        self, actor: ActorContext, payload: dict, request_id: str
    ) -> dict:
        self._require_manager(actor, "verifier-manager")
        _payload_fields(payload, required={"review_id", "instance_id", "reason"})
        changed = self.reviews.instance_failed(
            payload["review_id"],
            instance_id=payload["instance_id"],
            reason=payload["reason"],
        )
        self._schedule_verifiers()
        return {"changed": changed}

    # -- durable commands ---------------------------------------------

    def _write_worker_start(self, launch: WorkerLaunch) -> None:
        atomic_write_json(
            self.layout.workers / "commands" / f"{launch.command_id}.json",
            {
                "version": 1,
                "command_id": launch.command_id,
                "action": "start_worker",
                "goal_id": launch.goal_id,
                "worker_id": launch.worker_id,
                "owner_department": LEAD_KEY,
                "intent": launch.intent,
            },
        )

    def _write_worker_resume(self, goal: dict) -> None:
        command_id = f"resume:{goal['id']}:{goal['attempts']}"
        atomic_write_json(
            self.layout.workers / "commands" / f"{command_id}.json",
            {
                "version": 1,
                "command_id": command_id,
                "action": "resume_worker",
                "goal_id": goal["id"],
                "worker_id": goal["worker_id"],
                "feedback": goal["latest_feedback"],
                "session_token": goal.get("session_token"),
            },
        )

    def _write_worker_stop(self, goal: dict) -> None:
        command_id = f"stop:{goal['id']}"
        atomic_write_json(
            self.layout.workers / "commands" / f"{command_id}.json",
            {
                "version": 1,
                "command_id": command_id,
                "action": "stop_worker",
                "goal_id": goal["id"],
                "worker_id": goal["worker_id"],
            },
        )

    def _write_verifier_start(self, launch: ReviewLaunch) -> None:
        atomic_write_json(
            self.layout.reviews / "commands" / f"start:{launch.instance_id}.json",
            {
                "version": 1,
                "command_id": f"start:{launch.instance_id}",
                "action": "start_verifier",
                "review_id": launch.review_id,
                "review_seq": launch.review_seq,
                "instance_id": launch.instance_id,
                "kind": launch.kind,
                "subject_id": launch.subject_id,
                "payload": launch.payload,
            },
        )

    def _write_verifier_stop(self, review: dict) -> None:
        instance_id = review.get("instance_id")
        if not instance_id:
            return
        atomic_write_json(
            self.layout.reviews / "commands" / f"stop:{instance_id}.json",
            {
                "version": 1,
                "command_id": f"stop:{instance_id}",
                "action": "stop_verifier",
                "review_id": review["id"],
                "instance_id": instance_id,
            },
        )

    def _schedule_workers(self) -> None:
        for launch in self.scheduler.starting_launches():
            self._write_worker_start(launch)
        scheduled_launch = self.scheduler.schedule_one()
        if scheduled_launch is not None:
            self._write_worker_start(scheduled_launch)

    def _schedule_verifiers(self) -> None:
        for launch in self.reviews.running_launches():
            self._write_verifier_start(launch)
        for launch in self.reviews.schedule():
            self._write_verifier_start(launch)

    def _emit_stopping_verifiers(self) -> None:
        for review in self.reviews.stopping_instances():
            self._write_verifier_stop(review)

    # -- Lead triggers -------------------------------------------------

    def _message(
        self, message_type: str, text: str, data: dict, *, message_id: str
    ) -> None:
        if message_type not in MESSAGE_TYPES:
            raise TeamHubError(f"unknown Lead trigger: {message_type}")
        event = make_ime(
            LEAD_KEY,
            text,
            {"v": 1, "type": message_type, "from": "system", "data": data},
            id=message_id,
        )
        if len(str(event).encode("utf-8")) > MESSAGE_MAX_BYTES:
            raise TeamHubError("Lead trigger is too large")
        self.inbox.append(LEAD_KEY, event)

    def _ensure_started(self) -> None:
        self._message(
            "team_started",
            "Team runtime started; inspect the real project and make substantive progress.",
            {},
            message_id=_stable_id("msg", "team-started", self.team_id),
        )

    def _maybe_signal_batch_drained(self) -> None:
        goals = self.scheduler.list_goals()
        if not goals or any(goal["status"] in NON_TERMINAL for goal in goals):
            return
        if any(goal.get("worker_state") == "stopping" for goal in goals):
            return
        sequence = max(int(goal["enqueue_seq"]) for goal in goals)
        marker = self.layout.control / "last-drained-batch.json"
        previous = read_json(marker, default={})
        if (
            isinstance(previous, dict)
            and int(previous.get("enqueue_seq", 0)) >= sequence
        ):
            return
        self._message(
            "goal_batch_drained",
            "The current Goal batch is drained; inspect reality and decide the next progress.",
            {"last_enqueue_seq": sequence},
            message_id=_stable_id("msg", "goal-batch-drained", self.team_id, sequence),
        )
        atomic_write_json(marker, {"enqueue_seq": sequence, "signalled_at": _utc_now()})

    def tick(self) -> dict:
        with file_lock(self._hub_lock):
            for review in self.reviews.terminal_unrouted():
                self._route_review(review)
                self.reviews.mark_routed(review["id"])
            for goal in self.scheduler.list_goals():
                if goal.get("worker_state") == "stopping" and goal.get("worker_id"):
                    self._write_worker_stop(goal)
            self._emit_stopping_verifiers()
            self._schedule_workers()
            self._schedule_verifiers()
            self._maybe_signal_batch_drained()
            return {
                "workers": self.scheduler.inspect()["active_workers"],
                "verifiers": self.reviews.inspect_pool(),
            }

    def _lead_goal_state(self) -> tuple[int, str]:
        return canonical_goal_state(
            [self._goal_projection(goal) for goal in self.scheduler.list_goals()]
        )

    @staticmethod
    def _goal_projection(goal: dict) -> dict:
        return {
            key: goal.get(key)
            for key in (
                "id",
                "intent",
                "status",
                "enqueue_seq",
                "worker_id",
                "worker_state",
                "attempts",
                "latest_feedback",
                "created_at",
                "updated_at",
            )
        }

    @staticmethod
    def _review_projection(review: dict) -> dict:
        return {
            key: review.get(key)
            for key in (
                "id",
                "review_seq",
                "kind",
                "subject_id",
                "status",
                "verdict",
                "reason",
            )
        }


def _state_root() -> Path:
    explicit = os.environ.get("TEAM_STATE_ROOT")
    if explicit:
        return Path(explicit)
    repo = Path(__file__).resolve().parents[1]
    return repo / "state" / os.environ.get("TEAM", "hackathon-team")


def main() -> None:
    team_id = os.environ.get("TEAM", "hackathon-team")
    hub = TeamHub(_state_root(), team_id=team_id)
    hub.tick()
    interval = float(os.environ.get("HUB_TICK_SECS", "0.5"))

    def watchdog() -> None:
        while True:
            try:
                hub.tick()
            except Exception as exc:  # noqa: BLE001
                print(f"[team-hub] tick failed: {exc!r}", flush=True)
            time.sleep(max(0.05, interval))

    threading.Thread(target=watchdog, name="team-hub-watchdog", daemon=True).start()
    port = int(os.environ.get("HUB_PORT", "8910"))
    server = TeamHTTPServer(("0.0.0.0", port), hub)
    print(f"[team-hub] ready root={hub.layout.root} port={port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
