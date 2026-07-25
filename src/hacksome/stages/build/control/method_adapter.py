"""Versioned deterministic method boundary for V7 Agent calls.

The actor is supplied by the harness/tool process and is never accepted from
the business request.  This is an attribution and misuse boundary, not an
adversarial container-authentication system.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Protocol

from hacksome.stages.build.control.runtime_store import (
    append_jsonl,
    atomic_write_json,
    file_lock,
    read_json,
    require_identifier,
)

ActorKind = Literal["lead", "ceo", "department", "worker", "verifier", "manager"]
Handler = Callable[["ActorContext", dict, str], object]
AuditRequest = Callable[[object], object]
AuditResult = Callable[[object], object]

_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class MethodLayout(Protocol):
    """Minimal control-plane paths required by logical method dispatch."""

    @property
    def control(self) -> Path: ...

    @property
    def telemetry(self) -> Path: ...


class MethodError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ActorContext:
    kind: ActorKind
    actor_id: str
    department_id: str | None = None
    goal_id: str | None = None
    review_id: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.actor_id, label="actor id")
        if self.kind not in (
            "lead",
            "ceo",
            "department",
            "worker",
            "verifier",
            "manager",
        ):
            raise MethodError("invalid_actor", f"unknown actor kind: {self.kind!r}")


@dataclass(frozen=True)
class MethodRequest:
    version: int
    request_id: str
    method: str
    payload: dict

    @classmethod
    def parse(cls, raw: object) -> "MethodRequest":
        if not isinstance(raw, dict):
            raise MethodError("invalid_request", "request must be an object")
        allowed = {"version", "request_id", "method", "payload"}
        extra = set(raw) - allowed
        if extra:
            raise MethodError(
                "invalid_request", f"unknown request fields: {sorted(extra)}"
            )
        if raw.get("version") != 1:
            raise MethodError(
                "unsupported_version", "only method protocol version 1 is supported"
            )
        request_id = raw.get("request_id")
        if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
            raise MethodError(
                "invalid_request_id", f"invalid request_id: {request_id!r}"
            )
        method = raw.get("method")
        if not isinstance(method, str) or not method:
            raise MethodError("invalid_method", "method must be a non-empty string")
        payload = raw.get("payload", {})
        if not isinstance(payload, dict):
            raise MethodError("invalid_payload", "payload must be an object")
        if "from" in payload:
            raise MethodError("actor_is_bound", "payload must not declare 'from'")
        return cls(1, request_id, method, payload)


class MethodAdapter:
    """Dispatch logical methods with role permissions and replay-safe results."""

    def __init__(self, layout: MethodLayout):
        self.layout = layout
        self._handlers: dict[str, Handler] = {}
        self._permissions: dict[str, frozenset[ActorKind]] = {}
        self._cache_responses: dict[str, bool] = {}
        self._audit_request: dict[str, AuditRequest | None] = {}
        self._audit_result: dict[str, AuditResult | None] = {}

    def register(
        self,
        method: str,
        *,
        actors: set[ActorKind],
        handler: Handler,
        cache_response: bool = True,
        audit_request: AuditRequest | None = None,
        audit_result: AuditResult | None = None,
    ) -> None:
        if method in self._handlers:
            raise ValueError(f"method already registered: {method}")
        if not actors:
            raise ValueError("a method must allow at least one actor kind")
        self._handlers[method] = handler
        self._permissions[method] = frozenset(actors)
        self._cache_responses[method] = cache_response
        self._audit_request[method] = audit_request
        self._audit_result[method] = audit_result

    def call(self, actor: ActorContext, raw_request: object) -> dict:
        request: MethodRequest | None = None
        try:
            request = MethodRequest.parse(raw_request)
            handler = self._handlers.get(request.method)
            if handler is None:
                raise MethodError("unknown_method", f"unknown method: {request.method}")
            if actor.kind not in self._permissions[request.method]:
                raise MethodError(
                    "forbidden",
                    f"{actor.kind} cannot call {request.method}",
                )
            response_path = (
                self.layout.control
                / "requests"
                / actor.actor_id
                / f"{request.request_id}.json"
            )
            request_identity = {
                "version": request.version,
                "method": request.method,
                "payload": request.payload,
            }
            cache_response = self._cache_responses[request.method]
            lock_path = self.layout.control / ".method-adapter.lock"
            with file_lock(lock_path):
                if cache_response:
                    prior = read_json(response_path)
                    if prior is not None:
                        if (
                            not isinstance(prior, dict)
                            or prior.get("request") != request_identity
                            or not isinstance(prior.get("response"), dict)
                        ):
                            raise MethodError(
                                "idempotency_conflict",
                                "request_id was already used for a different logical request",
                            )
                        response = prior["response"]
                        self._audit(actor, request, response, replayed=True)
                        return response
                result = handler(actor, dict(request.payload), request.request_id)
                response = {
                    "version": 1,
                    "request_id": request.request_id,
                    "ok": True,
                    "result": result,
                }
                if cache_response:
                    atomic_write_json(
                        response_path,
                        {"request": request_identity, "response": response},
                    )
                self._audit(actor, request, response, replayed=False)
                return response
        except MethodError as exc:
            request_id = (
                raw_request.get("request_id") if isinstance(raw_request, dict) else None
            )
            response = {
                "version": 1,
                "request_id": request_id,
                "ok": False,
                "error": {"code": exc.code, "message": str(exc)},
            }
            self._audit(
                actor, request, response, replayed=False, raw_request=raw_request
            )
            return response

    def _audit(
        self,
        actor: ActorContext,
        request: MethodRequest | None,
        response: dict,
        *,
        replayed: bool,
        raw_request: object | None = None,
    ) -> None:
        """Best-effort complete operator audit; never changes method semantics."""
        try:
            request_row: object
            if request is not None:
                request_row = {
                    "version": request.version,
                    "request_id": request.request_id,
                    "method": request.method,
                    "payload": request.payload,
                }
            else:
                request_row = raw_request
            method = (
                request.method
                if request is not None
                else (
                    raw_request.get("method")
                    if isinstance(raw_request, dict)
                    and isinstance(raw_request.get("method"), str)
                    else None
                )
            )
            redact_request = (
                self._audit_request.get(method) if method is not None else None
            )
            if redact_request is not None:
                try:
                    request_row = redact_request(request_row)
                except Exception:  # noqa: BLE001 — fail closed for sensitive data
                    request_row = {
                        "redacted": True,
                        "method": method,
                        "request_id": (
                            request.request_id
                            if request is not None
                            else (
                                raw_request.get("request_id")
                                if isinstance(raw_request, dict)
                                else None
                            )
                        ),
                    }
            audit_response = response
            if request is not None and response.get("ok"):
                redact = self._audit_result.get(request.method)
                if redact is not None:
                    try:
                        audit_response = {
                            **response,
                            "result": redact(response.get("result")),
                        }
                    except Exception:  # noqa: BLE001 — fail closed for sensitive data
                        audit_response = {
                            "version": response.get("version", 1),
                            "request_id": response.get("request_id"),
                            "ok": True,
                            "result": {"redacted": True},
                        }
            append_jsonl(
                self.layout.telemetry / "index" / "methods.jsonl",
                {
                    "time": time.time(),
                    "actor": {
                        "kind": actor.kind,
                        "actor_id": actor.actor_id,
                        "department_id": actor.department_id,
                        "goal_id": actor.goal_id,
                        "review_id": actor.review_id,
                    },
                    "request": request_row,
                    "response": audit_response,
                    "replayed": replayed,
                },
            )
        except Exception:  # noqa: BLE001 — observability never blocks control
            return
