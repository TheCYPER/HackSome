"""Harness-side client for the Build Team Hub logical method boundary."""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from hacksome.stages.build.control.lead_brief import LEAD_BRIEF_MAX_BYTES


class ControlClientError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BoundActor:
    kind: str
    actor_id: str
    department_id: str | None = None
    goal_id: str | None = None
    review_id: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "BoundActor":
        env = os.environ if env is None else env
        actor_id = env.get("AGENT_KEY") or env.get("ACTOR_ID") or ""
        kind = env.get("AGENT_KIND") or (
            "lead"
            if actor_id == "lead"
            else ("ceo" if actor_id == "ceo" else "department")
        )
        return cls(
            kind=kind,
            actor_id=actor_id,
            department_id=(
                env.get("DEPARTMENT_ID") or (actor_id if kind == "department" else None)
            ),
            goal_id=env.get("GOAL_ID"),
            review_id=env.get("REVIEW_ID"),
        )

    def headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Foundagent-Actor-Kind": self.kind,
            "X-Foundagent-Actor-Id": self.actor_id,
        }
        if self.department_id:
            headers["X-Foundagent-Department"] = self.department_id
        if self.goal_id:
            headers["X-Foundagent-Goal"] = self.goal_id
        if self.review_id:
            headers["X-Foundagent-Review"] = self.review_id
        return headers


class HubClient:
    def __init__(
        self,
        url: str | None = None,
        *,
        actor: BoundActor | None = None,
        timeout: float = 30.0,
    ):
        self.url = (url or os.environ.get("HUB_URL") or "http://hub:8910").rstrip("/")
        self.actor = actor or BoundActor.from_env()
        self.timeout = timeout

    def call(
        self,
        method: str,
        payload: dict | None = None,
        *,
        request_id: str | None = None,
    ):
        request_id = request_id or f"client-{uuid.uuid4().hex}"
        envelope = {
            "version": 1,
            "request_id": request_id,
            "method": method,
            "payload": payload or {},
        }
        request = Request(
            f"{self.url}/v1/method",
            data=json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
            headers=self.actor.headers(),
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read())
        except HTTPError as exc:
            raise ControlClientError("http_error", f"Hub HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ControlClientError("transport_error", str(exc)) from exc
        if not isinstance(body, dict) or not body.get("ok"):
            error = body.get("error", {}) if isinstance(body, dict) else {}
            raise ControlClientError(
                str(error.get("code", "invalid_response")),
                str(error.get("message", "Hub method failed")),
            )
        return body.get("result")

    def archive_run(self, archive: dict) -> dict:
        request = Request(
            f"{self.url}/v1/run-archive",
            data=json.dumps(archive, ensure_ascii=False).encode("utf-8"),
            headers=self.actor.headers(),
            method="POST",
        )
        try:
            with urlopen(request, timeout=max(self.timeout, 120.0)) as response:
                body = json.loads(response.read())
        except (
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise ControlClientError("archive_transport_error", str(exc)) from exc
        if not isinstance(body, dict) or not body.get("ok"):
            error = body.get("error", {}) if isinstance(body, dict) else {}
            raise ControlClientError(
                str(error.get("code", "archive_failed")),
                str(error.get("message", "run archive failed")),
            )
        return body


@dataclass
class RemoteInbox:
    """Inbox facade that never exposes the backing Inbox directory."""

    client: HubClient
    poll_tick: float = 0.2
    _current: dict[str, str] = field(default_factory=dict)

    def peek_one(self, key: str) -> dict | None:
        self._require_key(key)
        result = self.client.call("peek_message")
        message = result.get("message") if isinstance(result, dict) else None
        if isinstance(message, dict) and isinstance(message.get("id"), str):
            self._current[key] = message["id"]
            return message
        self._current.pop(key, None)
        return None

    def wait(self, key: str, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            if self.peek_one(key) is not None:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(self.poll_tick, remaining))

    def ack_one(self, key: str) -> None:
        """Idempotent fallback after ``wake_completed`` atomically acked it."""
        self._require_key(key)
        message_id = self._current.get(key)
        if message_id:
            self.client.call("ack_message", {"message_id": message_id})
            self._current.pop(key, None)

    def _require_key(self, key: str) -> None:
        if key != self.client.actor.actor_id:
            raise ControlClientError(
                "actor_is_bound", "Inbox key is not the bound actor"
            )


def load_wake_context(client: HubClient | None = None) -> dict:
    return (client or HubClient()).call("wake_context")


def notify_wake_completed(details: dict, client: HubClient | None = None) -> dict:
    payload = {
        "message_id": details.get("message_id"),
        "wake_id": details["wake_id"],
        "finished_at": details["finished_at"],
    }
    if payload["message_id"] is None:
        payload.pop("message_id")
    return (client or HubClient()).call(
        "wake_completed",
        payload,
        request_id=f"wake-completed:{details['wake_id']}",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Call one Build Team Hub method")
    parser.add_argument("method")
    parser.add_argument("--json", default="{}", dest="payload_json")
    parser.add_argument("--request-id")
    parser.add_argument(
        "--markdown-file",
        type=Path,
        help=(
            "Read bounded UTF-8 Markdown for checkpoint_lead_brief replace; "
            "never embeds the body in shell argv"
        ),
    )
    return parser


def _read_markdown_file(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            raw = stream.read(LEAD_BRIEF_MAX_BYTES + 1)
    except OSError as exc:
        raise ValueError(f"could not read --markdown-file: {exc}") from exc
    if len(raw) > LEAD_BRIEF_MAX_BYTES:
        raise ValueError(f"--markdown-file exceeds {LEAD_BRIEF_MAX_BYTES} UTF-8 bytes")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("--markdown-file is not valid UTF-8") from exc


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        payload = json.loads(args.payload_json)
        if not isinstance(payload, dict):
            raise ValueError("--json must decode to an object")
        if args.markdown_file is not None:
            if args.method != "checkpoint_lead_brief":
                raise ValueError(
                    "--markdown-file is only valid for checkpoint_lead_brief"
                )
            if payload.get("action") != "replace":
                raise ValueError("--markdown-file requires checkpoint action 'replace'")
            if "markdown" in payload:
                raise ValueError(
                    "checkpoint Markdown must be supplied only by --markdown-file"
                )
            payload["markdown"] = _read_markdown_file(args.markdown_file)
        result = HubClient().call(args.method, payload, request_id=args.request_id)
    except (ValueError, ControlClientError) as exc:
        raise SystemExit(f"control method failed: {exc}") from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
