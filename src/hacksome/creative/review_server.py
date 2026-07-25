"""Local, capability-gated HTTP relay for the Creative C6 review round.

The HTTP layer deliberately knows nothing about JSONL or ``RunHub`` internals.
Its backend owns review-domain validation and the short-lived ``run.lock``
leases.  This module owns only transport security, process-local capability and
reviewer sessions, role projection, fixed UI resources, and the long-lived
``review-server.lock`` lease.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import secrets
import socket
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, cast
from urllib.parse import urlsplit

from hacksome.state import StateError, advisory_lease, normalize_json


ReviewRole = Literal["reviewer", "curator"]

CAPABILITY_COOKIE = "hacksome_cap"
REVIEWER_SESSION_COOKIE = "hacksome_reviewer_session"
MAX_BODY_BYTES = 256 * 1024
MAX_APPROVED_FRAGMENTS_PER_TASK = 12
MAX_FEEDBACK_CONTEXT_BYTES = 24 * 1024

_REVIEWER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,256}$")
_TEXT_LIMITS = {
    "reviewer_name": 80,
    "curator_name": 80,
    "one_sentence_retell": 400,
    "share_target": 200,
    "comment": 4000,
    "reason": 1000,
    "overall_comment": 4000,
    "coverage_override_reason": 4000,
    "curator_instruction": 4000,
}
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "connect-src 'self'; img-src 'none'; object-src 'none'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
_REVIEWER_TOP_LEVEL_FIELDS = frozenset(
    {
        "concepts",
        "coverage_summary",
        "empty",
        "next_command",
        "pairs",
        "round",
        "run_id",
        "schema_version",
        "status",
    }
)
_REVIEWER_ROUND_FIELDS = frozenset(
    {
        "batch_id",
        "batch_sha256",
        "concepts",
        "id",
        "pairs",
        "resolution_id",
        "resolution_sha256",
        "round_id",
        "round_sha256",
        "sha256",
        "status",
    }
)
_REVIEWER_CONCEPT_FIELDS = frozenset(
    {
        "action",
        "assumptions_confusion_and_risks",
        "audience_action",
        "concept_ref",
        "concept_sha256",
        "core_mechanism",
        "first_impression",
        "first_thirty_seconds",
        "hook",
        "id",
        "mechanism",
        "minimum_demo",
        "minimum_hackathon_demo",
        "novelty",
        "novelty_and_references",
        "one_sentence_hook",
        "primary_territory_ref",
        "ref",
        "reveal",
        "risks",
        "setup_reveal_aftertaste",
        "sha256",
        "share_trigger_and_artifact",
        "software_core_and_runtime",
        "territory",
        "title",
    }
)
_REVIEWER_PAIR_FIELDS = frozenset(
    {
        "left_ref",
        "left_sha256",
        "pair_id",
        "right_ref",
        "right_sha256",
    }
)
_REVIEWER_COVERAGE_FIELDS = frozenset(
    {
        "concept_count",
        "covered_concept_count",
        "reviewer_count",
        "shortlist_count",
    }
)
_TEAM_RECEIPT_FIELDS = frozenset(
    {
        "concept_reviews",
        "independence",
        "one_sentence_retell",
        "overall_comment",
        "pairwise",
        "recommendation",
        "reviewer_name",
        "schema_version",
        "share_impulse",
        "share_target",
        "demo_confidence",
        "submitted_at",
    }
)
_TEAM_CONCEPT_REVIEW_FIELDS = frozenset(
    {
        "comment",
        "concept_ref",
        "demo_confidence",
        "one_sentence_retell",
        "reactions",
        "recommendation",
        "share_impulse",
        "share_target",
    }
)
_TEAM_PAIR_FIELDS = frozenset(
    {
        "left_ref",
        "pair_id",
        "preference",
        "reason",
        "right_ref",
    }
)


class ReviewBackend(Protocol):
    """Narrow boundary implemented by the C6 review-domain adapter.

    Implementations must take their own short-lived shared/exclusive run lease.
    The server must not wrap these calls in another ``run.lock`` lease because
    ``RunHub`` writers already acquire it and nested POSIX leases may deadlock.
    """

    def has_submitted(self, reviewer_id: str) -> bool:
        """Return whether this reviewer has any receipt in the current round."""

    def snapshot(
        self,
        *,
        role: ReviewRole,
        reviewer_id: str | None,
        include_team_wall: bool,
    ) -> Mapping[str, Any]:
        """Return the trusted domain projection for one authenticated viewer."""

    def submit_review(
        self,
        payload: Mapping[str, Any],
        *,
        expected_reviewer_id: str,
    ) -> Mapping[str, Any]:
        """Validate and append one immutable review receipt."""

    def submit_resolution(
        self,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Validate and append the resolution that closes the current round."""


class ReviewServerError(RuntimeError):
    """Base class for review-server failures."""


class ReviewHTTPError(ReviewServerError):
    """A safe domain/adapter error that can be returned to the browser."""

    def __init__(
        self,
        status: int | HTTPStatus,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.status = int(status)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ReviewServerConfig:
    """Network and persistence boundary for one local review process."""

    run_dir: Path
    host: str = "127.0.0.1"
    public_host: str | None = None
    port: int = 0

    def __post_init__(self) -> None:
        run_dir = Path(self.run_dir).expanduser().resolve()
        object.__setattr__(self, "run_dir", run_dir)
        if not self.host or any(character.isspace() for character in self.host):
            raise ValueError("host must be a non-empty hostname or IP address")
        if not isinstance(self.port, int) or not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if not _is_loopback(self.host) and self.public_host is None:
            raise ValueError(
                "public_host is required when binding a non-loopback address"
            )
        effective_public_host = self.public_host or self.host
        _validate_public_host(effective_public_host)
        object.__setattr__(self, "public_host", effective_public_host)


@dataclass(frozen=True, slots=True)
class ReviewerSession:
    capability: str
    reviewer_id: str


class CreativeReviewServer(ThreadingHTTPServer):
    """Threaded fixed-route HTTP server for one C6 review round."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        backend: ReviewBackend,
        config: ReviewServerConfig,
        *,
        review_token: str | None = None,
        curator_token: str | None = None,
    ) -> None:
        self.backend = backend
        self.config = config
        self.review_token = review_token or secrets.token_urlsafe(32)
        self.curator_token = curator_token or secrets.token_urlsafe(32)
        if not _TOKEN.fullmatch(self.review_token) or not _TOKEN.fullmatch(
            self.curator_token
        ):
            raise ValueError("review and curator tokens must be URL-safe")
        if secrets.compare_digest(self.review_token, self.curator_token):
            raise ValueError("review and curator tokens must be different")

        self._capabilities: dict[str, ReviewRole] = {
            secrets.token_urlsafe(32): "reviewer",
            secrets.token_urlsafe(32): "curator",
        }
        self._join_tokens: dict[str, str] = {
            self.review_token: self._capability_for_role("reviewer"),
            self.curator_token: self._capability_for_role("curator"),
        }
        self._reviewer_sessions: dict[str, ReviewerSession] = {}
        self._memory_lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._review_lease: Any = None
        self._serve_thread: threading.Thread | None = None
        self._serving = threading.Event()
        self._stopping = threading.Event()

        self._assets = _load_review_assets()
        if ":" in config.host:
            self.address_family = socket.AF_INET6
        super().__init__((config.host, config.port), _ReviewRequestHandler)

        self.bound_port = int(self.server_address[1])
        self.authority = _format_authority(
            cast(str, self.config.public_host),
            self.bound_port,
        )
        self.origin = f"http://{self.authority}"
        self.review_url = f"{self.origin}/join/{self.review_token}"
        self.curator_url = f"{self.origin}/join/{self.curator_token}"

    def _capability_for_role(self, role: ReviewRole) -> str:
        for capability, candidate_role in self._capabilities.items():
            if candidate_role == role:
                return capability
        raise AssertionError(f"missing process capability for role {role}")

    def start(self) -> "CreativeReviewServer":
        """Start in a background thread while holding ``review-server.lock``."""

        with self._lifecycle_lock:
            if self._serve_thread is not None and self._serve_thread.is_alive():
                raise ReviewServerError("review server is already running")
            self._acquire_review_lease()
            self._serve_thread = threading.Thread(
                target=self._serve_with_held_lease,
                name="hacksome-review-server",
                daemon=True,
            )
            self._serve_thread.start()
        if not self._serving.wait(timeout=2):
            self._release_review_lease()
            raise ReviewServerError("review server did not start")
        return self

    def serve_forever(self, poll_interval: float = 0.1) -> None:
        """Serve in the current thread while holding the lifecycle lease."""

        self._acquire_review_lease()
        self._serve_with_held_lease(poll_interval)

    def _serve_with_held_lease(self, poll_interval: float = 0.1) -> None:
        self._serving.set()
        try:
            super().serve_forever(poll_interval=poll_interval)
        finally:
            self._serving.clear()
            self._release_review_lease()

    def stop(self) -> None:
        """Stop idempotently, release the socket and lifecycle lease."""

        if self._stopping.is_set():
            return
        self._stopping.set()
        try:
            if self._serving.is_set():
                super().shutdown()
            super().server_close()
            thread = self._serve_thread
            if (
                thread is not None
                and thread.is_alive()
                and thread is not threading.current_thread()
            ):
                thread.join(timeout=2)
        finally:
            self._release_review_lease()

    def schedule_stop(self) -> None:
        """Let the HTTP response flush before closing a resolved round."""

        timer = threading.Timer(0.05, self.stop)
        timer.daemon = True
        timer.start()

    def _acquire_review_lease(self) -> None:
        with self._lifecycle_lock:
            if self._review_lease is not None:
                return
            lease = advisory_lease(
                self.config.run_dir / "review-server.lock",
                exclusive=True,
                create=True,
                blocking=False,
            )
            try:
                lease.__enter__()
            except StateError:
                super().server_close()
                raise
            self._review_lease = lease

    def _release_review_lease(self) -> None:
        with self._lifecycle_lock:
            lease = self._review_lease
            if lease is None:
                return
            self._review_lease = None
            lease.__exit__(None, None, None)

    def __enter__(self) -> "CreativeReviewServer":
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.stop()

    def lookup_capability(self, candidate: str | None) -> tuple[str, ReviewRole] | None:
        if candidate is None:
            return None
        with self._memory_lock:
            for capability, role in self._capabilities.items():
                if secrets.compare_digest(candidate, capability):
                    return capability, role
        return None

    def exchange_join_token(self, candidate: str) -> tuple[str, ReviewRole] | None:
        with self._memory_lock:
            for join_token, capability in self._join_tokens.items():
                if secrets.compare_digest(candidate, join_token):
                    role = self._capabilities[capability]
                    return capability, role
        return None

    def create_reviewer_session(
        self,
        *,
        capability: str,
        reviewer_id: str,
    ) -> str:
        session_token = secrets.token_urlsafe(32)
        with self._memory_lock:
            self._reviewer_sessions[session_token] = ReviewerSession(
                capability=capability,
                reviewer_id=reviewer_id,
            )
        return session_token

    def lookup_reviewer_session(
        self,
        *,
        capability: str,
        candidate: str | None,
    ) -> ReviewerSession | None:
        if candidate is None:
            return None
        with self._memory_lock:
            for token, session in self._reviewer_sessions.items():
                if secrets.compare_digest(candidate, token):
                    if secrets.compare_digest(session.capability, capability):
                        return session
                    return None
        return None


class _ReviewRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HackSomeRelay"
    sys_version = ""

    @property
    def review_server(self) -> CreativeReviewServer:
        return cast(CreativeReviewServer, self.server)

    def version_string(self) -> str:
        return self.server_version

    def log_message(self, format: str, *args: Any) -> None:
        """Silence access logs so capability tokens never reach stderr."""

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_HEAD(self) -> None:
        self._dispatch("HEAD")

    def do_OPTIONS(self) -> None:
        self._dispatch("OPTIONS")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def do_TRACE(self) -> None:
        self._dispatch("TRACE")

    def do_CONNECT(self) -> None:
        self._dispatch("CONNECT")

    def _dispatch(self, method: str) -> None:
        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment:
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "route not found")
            return
        path = parsed.path
        allowed_method = _allowed_method(path)
        if allowed_method is None:
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "route not found")
            return
        if method != allowed_method:
            self._send_error(
                HTTPStatus.METHOD_NOT_ALLOWED,
                "method_not_allowed",
                f"{method} is not allowed for this route",
                extra_headers={"Allow": allowed_method},
            )
            return
        if not self._valid_host():
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_host", "invalid Host header")
            return
        if path.startswith("/join/"):
            self._handle_join(path.removeprefix("/join/"))
            return
        if not self._valid_origin(required=method == "POST"):
            self._send_error(
                HTTPStatus.FORBIDDEN,
                "invalid_origin",
                "Origin does not match this review server",
            )
            return
        authenticated = self._authenticated()
        if authenticated is None:
            self._send_error(
                HTTPStatus.UNAUTHORIZED,
                "authentication_required",
                "open a review or curator join link first",
            )
            return
        capability, role = authenticated
        if method == "GET":
            self._handle_get(path, capability=capability, role=role)
            return
        self._handle_post(path, capability=capability, role=role)

    def _handle_join(self, token: str) -> None:
        exchanged = self.review_server.exchange_join_token(token)
        if exchanged is None:
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "join link is invalid")
            return
        capability, _role = exchanged
        self.send_response(HTTPStatus.SEE_OTHER)
        self._send_security_headers()
        self.send_header("Location", "/")
        self.send_header(
            "Set-Cookie",
            _cookie_header(CAPABILITY_COOKIE, capability),
        )
        self.send_header(
            "Set-Cookie",
            _cookie_header(REVIEWER_SESSION_COOKIE, "", max_age=0),
        )
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_get(
        self,
        path: str,
        *,
        capability: str,
        role: ReviewRole,
    ) -> None:
        if path == "/":
            self._send_bytes(
                HTTPStatus.OK,
                self.review_server._assets["index.html"],
                "text/html; charset=utf-8",
            )
            return
        if path == "/assets/styles.css":
            self._send_bytes(
                HTTPStatus.OK,
                self.review_server._assets["styles.css"],
                "text/css; charset=utf-8",
            )
            return
        if path == "/assets/app.js":
            self._send_bytes(
                HTTPStatus.OK,
                self.review_server._assets["app.js"],
                "text/javascript; charset=utf-8",
            )
            return
        if path == "/api/snapshot":
            session = self._session_for_capability(capability)
            if role == "reviewer" and session is None:
                self._send_error(
                    HTTPStatus.UNAUTHORIZED,
                    "reviewer_session_required",
                    "register the local reviewer session first",
                )
                return
            reviewer_id = session.reviewer_id if session is not None else None
            try:
                has_submitted = bool(
                    reviewer_id
                    and self.review_server.backend.has_submitted(reviewer_id)
                )
                raw = self.review_server.backend.snapshot(
                    role=role,
                    reviewer_id=reviewer_id,
                    include_team_wall=role == "curator" or has_submitted,
                )
                projected = _project_snapshot(
                    raw,
                    role=role,
                    reviewer_id=reviewer_id,
                    has_submitted=has_submitted,
                )
            except ReviewHTTPError as exc:
                self._send_error(exc.status, exc.code, exc.message)
                return
            except Exception as exc:
                domain_error = _domain_http_error(exc)
                if domain_error is not None:
                    self._send_error(
                        domain_error.status,
                        domain_error.code,
                        domain_error.message,
                    )
                    return
                self._send_error(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "snapshot_failed",
                    "the review snapshot could not be loaded",
                )
                return
            self._send_json(HTTPStatus.OK, projected)
            return
        self._send_error(HTTPStatus.NOT_FOUND, "not_found", "route not found")

    def _handle_post(
        self,
        path: str,
        *,
        capability: str,
        role: ReviewRole,
    ) -> None:
        try:
            payload = self._read_json_body()
        except ReviewHTTPError as exc:
            self._send_error(exc.status, exc.code, exc.message)
            return

        if path == "/api/reviewer-sessions":
            reviewer_id = payload.get("reviewer_id")
            if set(payload) != {"reviewer_id"} or not isinstance(reviewer_id, str):
                self._send_error(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    "invalid_reviewer_session",
                    "payload must contain only reviewer_id",
                )
                return
            if not _REVIEWER_ID.fullmatch(reviewer_id):
                self._send_error(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    "invalid_reviewer_id",
                    "reviewer_id must be 8-128 safe characters",
                )
                return
            session_token = self.review_server.create_reviewer_session(
                capability=capability,
                reviewer_id=reviewer_id,
            )
            self._send_json(
                HTTPStatus.CREATED,
                {"reviewer_id": reviewer_id, "status": "registered"},
                extra_headers={
                    "Set-Cookie": _cookie_header(
                        REVIEWER_SESSION_COOKIE,
                        session_token,
                    )
                },
            )
            return

        if path == "/api/reviews":
            session = self._session_for_capability(capability)
            if session is None:
                self._send_error(
                    HTTPStatus.UNAUTHORIZED,
                    "reviewer_session_required",
                    "register the local reviewer session first",
                )
                return
            payload_reviewer_id = payload.get("reviewer_id")
            if payload_reviewer_id != session.reviewer_id:
                self._send_error(
                    HTTPStatus.FORBIDDEN,
                    "reviewer_session_mismatch",
                    "payload reviewer_id does not match this browser session",
                )
                return
            try:
                _validate_review_payload_limits(payload)
                result = self.review_server.backend.submit_review(
                    payload,
                    expected_reviewer_id=session.reviewer_id,
                )
            except ReviewHTTPError as exc:
                self._send_error(exc.status, exc.code, exc.message)
                return
            except Exception as exc:
                domain_error = _domain_http_error(exc)
                if domain_error is not None:
                    self._send_error(
                        domain_error.status,
                        domain_error.code,
                        domain_error.message,
                    )
                    return
                self._send_error(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "review_submit_failed",
                    "the review receipt could not be saved",
                )
                return
            self._send_json(HTTPStatus.OK, result)
            return

        if path == "/api/resolve":
            if role != "curator":
                self._send_error(
                    HTTPStatus.FORBIDDEN,
                    "curator_required",
                    "this action requires the curator capability",
                )
                return
            try:
                _validate_resolution_payload_limits(payload)
                result = self.review_server.backend.submit_resolution(payload)
            except ReviewHTTPError as exc:
                self._send_error(exc.status, exc.code, exc.message)
                return
            except Exception as exc:
                domain_error = _domain_http_error(exc)
                if domain_error is not None:
                    self._send_error(
                        domain_error.status,
                        domain_error.code,
                        domain_error.message,
                    )
                    return
                self._send_error(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "resolution_submit_failed",
                    "the round resolution could not be saved",
                )
                return
            self._send_json(HTTPStatus.OK, result)
            self.review_server.schedule_stop()
            return

        self._send_error(HTTPStatus.NOT_FOUND, "not_found", "route not found")

    def _valid_host(self) -> bool:
        hosts = self.headers.get_all("Host", failobj=[])
        return len(hosts) == 1 and hosts[0].strip().lower() == (
            self.review_server.authority.lower()
        )

    def _valid_origin(self, *, required: bool) -> bool:
        origins = self.headers.get_all("Origin", failobj=[])
        if not origins:
            return not required
        return len(origins) == 1 and secrets.compare_digest(
            origins[0].strip(),
            self.review_server.origin,
        )

    def _authenticated(self) -> tuple[str, ReviewRole] | None:
        cookie = _parse_cookie_headers(self.headers.get_all("Cookie", failobj=[]))
        morsel = cookie.get(CAPABILITY_COOKIE)
        candidate = morsel.value if morsel is not None else None
        return self.review_server.lookup_capability(candidate)

    def _session_for_capability(self, capability: str) -> ReviewerSession | None:
        cookie = _parse_cookie_headers(self.headers.get_all("Cookie", failobj=[]))
        morsel = cookie.get(REVIEWER_SESSION_COOKIE)
        candidate = morsel.value if morsel is not None else None
        return self.review_server.lookup_reviewer_session(
            capability=capability,
            candidate=candidate,
        )

    def _read_json_body(self) -> dict[str, Any]:
        content_types = self.headers.get_all("Content-Type", failobj=[])
        if len(content_types) != 1:
            raise ReviewHTTPError(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "invalid_content_type",
                "Content-Type must be application/json",
            )
        media_type, separator, parameters = content_types[0].partition(";")
        if media_type.strip().lower() != "application/json":
            raise ReviewHTTPError(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "invalid_content_type",
                "Content-Type must be application/json",
            )
        if separator and parameters.strip().lower() not in {"charset=utf-8", "charset=\"utf-8\""}:
            raise ReviewHTTPError(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "invalid_charset",
                "JSON requests must use UTF-8",
            )
        lengths = self.headers.get_all("Content-Length", failobj=[])
        if len(lengths) != 1:
            raise ReviewHTTPError(
                HTTPStatus.LENGTH_REQUIRED,
                "content_length_required",
                "Content-Length is required",
            )
        try:
            length = int(lengths[0])
        except ValueError as exc:
            raise ReviewHTTPError(
                HTTPStatus.BAD_REQUEST,
                "invalid_content_length",
                "Content-Length must be an integer",
            ) from exc
        if length < 0:
            raise ReviewHTTPError(
                HTTPStatus.BAD_REQUEST,
                "invalid_content_length",
                "Content-Length must not be negative",
            )
        if length > MAX_BODY_BYTES:
            raise ReviewHTTPError(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "body_too_large",
                f"request body exceeds {MAX_BODY_BYTES} bytes",
            )
        content = self.rfile.read(length)
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReviewHTTPError(
                HTTPStatus.BAD_REQUEST,
                "invalid_utf8",
                "request body is not valid UTF-8",
            ) from exc
        try:
            value = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise ReviewHTTPError(
                HTTPStatus.BAD_REQUEST,
                "invalid_json",
                f"request body contains invalid JSON at line {exc.lineno}",
            ) from exc
        if not isinstance(value, dict):
            raise ReviewHTTPError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "invalid_json_shape",
                "request JSON must be an object",
            )
        normalized = normalize_json(value, label="review HTTP payload")
        if not isinstance(normalized, dict):
            raise ReviewHTTPError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "invalid_json_shape",
                "request JSON must be an object",
            )
        return normalized

    def _send_json(
        self,
        status: int | HTTPStatus,
        value: Mapping[str, Any],
        *,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        try:
            body = json.dumps(
                normalize_json(dict(value), label="review HTTP response"),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except Exception:
            body = json.dumps(
                {
                    "code": "invalid_backend_response",
                    "message": "the review backend returned an invalid response",
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            self._send_bytes(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                body,
                "application/json; charset=utf-8",
            )
            return
        self._send_bytes(
            status,
            body,
            "application/json; charset=utf-8",
            extra_headers=extra_headers,
        )

    def _send_error(
        self,
        status: int | HTTPStatus,
        code: str,
        message: str,
        *,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.close_connection = True
        body = json.dumps(
            {"code": code, "message": message},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self._send_bytes(
            status,
            body,
            "application/json; charset=utf-8",
            extra_headers=extra_headers,
        )

    def _send_bytes(
        self,
        status: int | HTTPStatus,
        content: bytes,
        content_type: str,
        *,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.send_response(int(status))
        self._send_security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)
            self.wfile.flush()

    def _send_security_headers(self) -> None:
        for key, value in _SECURITY_HEADERS.items():
            self.send_header(key, value)
        self.send_header("Content-Security-Policy", _CSP)


def _load_review_assets() -> dict[str, bytes]:
    package_root = resources.files("hacksome").joinpath("review_ui")
    assets: dict[str, bytes] = {}
    for name in ("index.html", "styles.css", "app.js"):
        try:
            assets[name] = package_root.joinpath(name).read_bytes()
        except (FileNotFoundError, TypeError) as exc:
            raise ReviewServerError(f"packaged review UI asset is missing: {name}") from exc
    return assets


def _domain_http_error(error: Exception) -> ReviewHTTPError | None:
    """Map only the public review-domain error taxonomy without importing it."""

    class_names = {candidate.__name__ for candidate in type(error).__mro__}
    if class_names & {
        "ReviewConflictError",
        "ReviewStaleError",
        "ReviewClosedError",
    }:
        return ReviewHTTPError(
            HTTPStatus.CONFLICT,
            "review_conflict",
            str(error),
        )
    if "ReviewValidationError" in class_names:
        return ReviewHTTPError(
            HTTPStatus.BAD_REQUEST,
            "review_validation_error",
            str(error),
        )
    return None


def _allowed_method(path: str) -> str | None:
    if path.startswith("/join/") and len(path) > len("/join/"):
        return "GET"
    return {
        "/": "GET",
        "/assets/styles.css": "GET",
        "/assets/app.js": "GET",
        "/api/reviewer-sessions": "POST",
        "/api/snapshot": "GET",
        "/api/reviews": "POST",
        "/api/resolve": "POST",
    }.get(path)


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _validate_public_host(host: str) -> None:
    if not host or any(character.isspace() for character in host):
        raise ValueError("public_host must be a non-empty hostname or IP address")
    if any(marker in host for marker in ("/", "?", "#", "@", "://")):
        raise ValueError("public_host must not include scheme, path, query or userinfo")
    if host.startswith("[") or host.endswith("]"):
        raise ValueError("public_host IPv6 literals must be provided without brackets")
    if ":" in host:
        try:
            ipaddress.IPv6Address(host)
        except ValueError as exc:
            raise ValueError(
                "public_host must not include a port; use the port option"
            ) from exc


def _format_authority(host: str, port: int) -> str:
    formatted_host = f"[{host}]" if ":" in host else host
    return f"{formatted_host}:{port}"


def _cookie_header(name: str, value: str, *, max_age: int | None = None) -> str:
    cookie = SimpleCookie()
    cookie[name] = value
    cookie[name]["path"] = "/"
    cookie[name]["httponly"] = True
    cookie[name]["samesite"] = "Strict"
    if max_age is not None:
        cookie[name]["max-age"] = str(max_age)
    return cookie.output(header="").strip()


def _parse_cookie_headers(values: list[str]) -> SimpleCookie:
    cookie = SimpleCookie()
    try:
        cookie.load("; ".join(values))
    except Exception:
        return SimpleCookie()
    return cookie


def _project_snapshot(
    raw: Mapping[str, Any],
    *,
    role: ReviewRole,
    reviewer_id: str | None,
    has_submitted: bool,
) -> dict[str, Any]:
    normalized = normalize_json(dict(raw), label="review snapshot")
    if not isinstance(normalized, dict):
        raise ReviewHTTPError(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            "invalid_snapshot",
            "review backend snapshot must be an object",
        )
    raw_viewer = normalized.get("viewer")
    latest_review_id = (
        raw_viewer.get("latest_review_id")
        if isinstance(raw_viewer, dict)
        else None
    )
    if role == "curator":
        projected = normalized
    else:
        projected = _reviewer_snapshot_projection(
            normalized,
            include_team_wall=has_submitted,
        )
    projected["viewer"] = {
        "role": role,
        "reviewer_id": reviewer_id,
        "has_submitted": has_submitted,
        "latest_review_id": (
            latest_review_id if isinstance(latest_review_id, str) else None
        ),
    }
    if reviewer_id is not None:
        _annotate_pair_display_order(projected, reviewer_id)
    return projected


def _reviewer_snapshot_projection(
    snapshot: Mapping[str, Any],
    *,
    include_team_wall: bool,
) -> dict[str, Any]:
    """Build a fail-closed reviewer view from explicit safe fields."""

    projected = _allowed_fields(snapshot, _REVIEWER_TOP_LEVEL_FIELDS)
    for structured in ("round", "concepts", "pairs", "coverage_summary"):
        projected.pop(structured, None)
    round_value = snapshot.get("round")
    if isinstance(round_value, dict):
        projected["round"] = _round_projection(round_value)
    concepts = snapshot.get("concepts")
    if isinstance(concepts, list):
        projected["concepts"] = [
            _allowed_fields(item, _REVIEWER_CONCEPT_FIELDS)
            for item in concepts
            if isinstance(item, dict)
        ]
    pairs = snapshot.get("pairs")
    if isinstance(pairs, list):
        projected["pairs"] = [
            _allowed_fields(item, _REVIEWER_PAIR_FIELDS)
            for item in pairs
            if isinstance(item, dict)
        ]
    coverage = snapshot.get("coverage_summary")
    if isinstance(coverage, dict):
        projected["coverage_summary"] = _allowed_fields(
            coverage,
            _REVIEWER_COVERAGE_FIELDS,
        )
    if include_team_wall:
        wall = snapshot.get("team_wall")
        if isinstance(wall, list):
            projected["team_wall"] = [
                _team_receipt_projection(item)
                for item in wall
                if isinstance(item, dict)
            ]
    return projected


def _round_projection(round_value: Mapping[str, Any]) -> dict[str, Any]:
    projected = _allowed_fields(round_value, _REVIEWER_ROUND_FIELDS)
    projected.pop("concepts", None)
    projected.pop("pairs", None)
    concepts = round_value.get("concepts")
    if isinstance(concepts, list):
        projected["concepts"] = [
            _allowed_fields(item, _REVIEWER_CONCEPT_FIELDS)
            for item in concepts
            if isinstance(item, dict)
        ]
    pairs = round_value.get("pairs")
    if isinstance(pairs, list):
        projected["pairs"] = [
            _allowed_fields(item, _REVIEWER_PAIR_FIELDS)
            for item in pairs
            if isinstance(item, dict)
        ]
    return projected


def _team_receipt_projection(receipt: Mapping[str, Any]) -> dict[str, Any]:
    projected = _allowed_fields(receipt, _TEAM_RECEIPT_FIELDS)
    projected.pop("concept_reviews", None)
    projected.pop("pairwise", None)
    concept_reviews = receipt.get("concept_reviews")
    if isinstance(concept_reviews, list):
        projected["concept_reviews"] = [
            _allowed_fields(item, _TEAM_CONCEPT_REVIEW_FIELDS)
            for item in concept_reviews
            if isinstance(item, dict)
        ]
    pairwise = receipt.get("pairwise")
    if isinstance(pairwise, list):
        projected["pairwise"] = [
            _allowed_fields(item, _TEAM_PAIR_FIELDS)
            for item in pairwise
            if isinstance(item, dict)
        ]
    return projected


def _allowed_fields(
    value: Mapping[str, Any],
    allowed: frozenset[str],
) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key in allowed}


def _annotate_pair_display_order(
    snapshot: dict[str, Any],
    reviewer_id: str,
) -> None:
    pairs = snapshot.get("pairs")
    if not isinstance(pairs, list):
        round_value = snapshot.get("round")
        if isinstance(round_value, dict):
            pairs = round_value.get("pairs")
    if not isinstance(pairs, list):
        return
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        pair_id = pair.get("pair_id")
        if not isinstance(pair_id, str):
            continue
        digest = hashlib.sha256(f"{reviewer_id}:{pair_id}".encode()).digest()
        pair["display_swapped"] = digest[-1] % 2 == 1


def _validate_text(
    value: Any,
    *,
    field: str,
    maximum: int,
    path: str,
) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise ReviewHTTPError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "invalid_text_field",
            f"{path}.{field} must be a string",
        )
    if len(value) > maximum:
        raise ReviewHTTPError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "text_field_too_long",
            f"{path}.{field} exceeds {maximum} characters",
        )


def _validate_review_payload_limits(payload: Mapping[str, Any]) -> None:
    schema_version = payload.get("schema_version", 1)
    if type(schema_version) is not int or schema_version not in {1, 2}:
        raise ReviewHTTPError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "unsupported_review_schema",
            "review.schema_version must be 1 or 2",
        )
    _validate_text(
        payload.get("reviewer_name"),
        field="reviewer_name",
        maximum=_TEXT_LIMITS["reviewer_name"],
        path="review",
    )
    _validate_text(
        payload.get("overall_comment"),
        field="overall_comment",
        maximum=_TEXT_LIMITS["overall_comment"],
        path="review",
    )
    concept_reviews = payload.get("concept_reviews", [])
    if not isinstance(concept_reviews, list):
        raise ReviewHTTPError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "invalid_concept_reviews",
            "review.concept_reviews must be an array",
        )
    for index, item in enumerate(concept_reviews):
        if not isinstance(item, dict):
            raise ReviewHTTPError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "invalid_concept_review",
                f"review.concept_reviews[{index}] must be an object",
            )
        path = f"review.concept_reviews[{index}]"
        for field in ("one_sentence_retell", "share_target", "comment"):
            _validate_text(
                item.get(field),
                field=field,
                maximum=_TEXT_LIMITS[field],
                path=path,
            )
        if schema_version >= 2:
            share_impulse = item.get("share_impulse")
            demo_confidence = item.get("demo_confidence")
            if share_impulse not in {"immediate", "maybe", "no"}:
                raise ReviewHTTPError(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    "invalid_share_impulse",
                    f"{path}.share_impulse must be immediate, maybe, or no",
                )
            if demo_confidence not in {"yes", "maybe", "no"}:
                raise ReviewHTTPError(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    "invalid_demo_confidence",
                    f"{path}.demo_confidence must be yes, maybe, or no",
                )
            share_target = item.get("share_target")
            if share_impulse == "immediate" and (
                not isinstance(share_target, str) or not share_target.strip()
            ):
                raise ReviewHTTPError(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    "share_target_required",
                    (
                        f"{path}.share_target is required when "
                        "share_impulse is immediate"
                    ),
                )
    pairwise = payload.get("pairwise", [])
    if not isinstance(pairwise, list):
        raise ReviewHTTPError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "invalid_pairwise",
            "review.pairwise must be an array",
        )
    for index, item in enumerate(pairwise):
        if not isinstance(item, dict):
            raise ReviewHTTPError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "invalid_pairwise_entry",
                f"review.pairwise[{index}] must be an object",
            )
        _validate_text(
            item.get("reason"),
            field="reason",
            maximum=_TEXT_LIMITS["reason"],
            path=f"review.pairwise[{index}]",
        )


def _validate_resolution_payload_limits(payload: Mapping[str, Any]) -> None:
    for field in (
        "curator_name",
        "coverage_override_reason",
    ):
        _validate_text(
            payload.get(field),
            field=field,
            maximum=_TEXT_LIMITS[field],
            path="resolution",
        )
    actions_value = payload.get("actions", [])
    if isinstance(actions_value, dict):
        actions = list(actions_value.values())
    elif isinstance(actions_value, list):
        actions = actions_value
    else:
        raise ReviewHTTPError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "invalid_resolution_actions",
            "resolution.actions must be an array or object",
        )
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ReviewHTTPError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "invalid_resolution_action",
                f"resolution.actions[{index}] must be an object",
            )
        for field in ("curator_instruction", "reason"):
            _validate_text(
                action.get(field),
                field=field,
                maximum=_TEXT_LIMITS["curator_instruction"],
                path=f"resolution.actions[{index}]",
            )
        instruction = action.get("curator_instruction")
        instruction_bytes = len(
            instruction.encode("utf-8") if isinstance(instruction, str) else b""
        )
        approved = action.get(
            "approved_feedback",
            action.get("approved_fragments", action.get("approved_fragment_refs", [])),
        )
        if not isinstance(approved, list):
            raise ReviewHTTPError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "invalid_approved_feedback",
                f"resolution.actions[{index}] approved feedback must be an array",
            )
        if len(approved) > MAX_APPROVED_FRAGMENTS_PER_TASK:
            raise ReviewHTTPError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "too_many_approved_fragments",
                (
                    f"resolution.actions[{index}] exceeds "
                    f"{MAX_APPROVED_FRAGMENTS_PER_TASK} approved fragments"
                ),
            )
        represented_bytes = len(
            json.dumps(
                approved,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if represented_bytes + instruction_bytes > MAX_FEEDBACK_CONTEXT_BYTES:
            raise ReviewHTTPError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "feedback_context_too_large",
                (
                    f"resolution.actions[{index}] exceeds the "
                    f"{MAX_FEEDBACK_CONTEXT_BYTES}-byte feedback context budget"
                ),
            )
