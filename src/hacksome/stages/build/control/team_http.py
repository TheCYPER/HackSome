"""HTTP transport for the Team Hub without importing Company product modules."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from hacksome.stages.build.control.method_adapter import ActorContext
from hacksome.stages.build.control.run_logs import RunLogRecorder


class TeamHTTPError(ValueError):
    pass


class TeamHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], hub):
        self.hub = hub
        super().__init__(address, TeamHTTPRequestHandler)


class TeamHTTPRequestHandler(BaseHTTPRequestHandler):
    server: TeamHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _json(self, status: int, value: dict) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"ok": True})
            return
        self._json(404, {"ok": False, "error": {"code": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/v1/run-archive":
            self._archive_run()
            return
        if self.path != "/v1/method":
            self._json(404, {"ok": False, "error": {"code": "not_found"}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1024 * 1024:
                raise TeamHTTPError("invalid request size")
            raw = json.loads(self.rfile.read(length))
            actor = ActorContext(
                kind=self.headers.get("X-Foundagent-Actor-Kind", ""),  # type: ignore[arg-type]
                actor_id=self.headers.get("X-Foundagent-Actor-Id", ""),
                goal_id=self.headers.get("X-Foundagent-Goal") or None,
                review_id=self.headers.get("X-Foundagent-Review") or None,
            )
            self._json(200, self.server.hub.call(actor, raw))
        except Exception as exc:  # noqa: BLE001
            self._json(
                400,
                {
                    "version": 1,
                    "request_id": None,
                    "ok": False,
                    "error": {"code": "invalid_transport", "message": str(exc)},
                },
            )

    def _archive_run(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            maximum = int(
                os.environ.get("RUN_ARCHIVE_MAX_BYTES", str(256 * 1024 * 1024))
            )
            if length <= 0 or length > maximum:
                raise TeamHTTPError("invalid run archive size")
            raw = json.loads(self.rfile.read(length))
            if not isinstance(raw, dict):
                raise TeamHTTPError("run archive must be an object")
            allowed = {
                "run_id",
                "metadata",
                "raw_output",
                "stderr",
                "model_output",
                "harness_log",
                "container_log",
            }
            required = {"run_id", "metadata", "raw_output", "stderr", "model_output"}
            if set(raw) - allowed or not required <= set(raw):
                raise TeamHTTPError("invalid run archive fields")
            actor = ActorContext(
                kind=self.headers.get("X-Foundagent-Actor-Kind", ""),  # type: ignore[arg-type]
                actor_id=self.headers.get("X-Foundagent-Actor-Id", ""),
            )
            if actor.kind != "lead" or actor.actor_id != "lead":
                raise TeamHTTPError("only the resident Lead may archive resident wakes")
            if (
                not isinstance(raw["metadata"], dict)
                or raw["metadata"].get("agent_id") != actor.actor_id
            ):
                raise TeamHTTPError("run archive actor does not match metadata")
            run_dir = RunLogRecorder(
                self.server.hub.layout.telemetry / "runs"
            ).record(
                run_id=raw["run_id"],
                metadata=raw["metadata"],
                raw_output=raw["raw_output"],
                stderr=raw["stderr"],
                model_output=raw["model_output"],
                harness_log=raw.get("harness_log", ""),
                container_log=raw.get("container_log", ""),
            )
            self._json(
                200,
                {"ok": True, "run_id": raw["run_id"], "stored": run_dir.name},
            )
        except Exception as exc:  # noqa: BLE001
            self._json(
                400,
                {
                    "ok": False,
                    "error": {"code": "archive_failed", "message": str(exc)},
                },
            )
