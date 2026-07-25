"""Loopback-only capability server for the shared Build Dispatch Board."""

from __future__ import annotations

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
from typing import Any, Mapping, cast
from urllib.parse import urlsplit

from hacksome.stages.build.approval.contracts import ApprovalError
from hacksome.stages.build.approval.service import ApprovalService
from hacksome.core.state import StateError, advisory_lease, normalize_json


CAPABILITY_COOKIE = "hacksome_build_cap"
MAX_BODY_BYTES = 256 * 1024
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,256}$")
_CARD_DETAIL = re.compile(r"^/api/cards/(?P<ordinal>0|[1-9][0-9]{0,5})$")
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


class ApprovalServerError(RuntimeError):
    """The local Approval server could not start or serve safely."""


class ApprovalHTTPError(ApprovalServerError):
    """Transport validation failure safe to return to the browser."""

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
class ApprovalServerConfig:
    approval_root: Path
    host: str = "127.0.0.1"
    port: int = 0
    reconcile_interval_seconds: float = 2.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "approval_root",
            Path(self.approval_root).expanduser().resolve(),
        )
        if not _is_loopback(self.host):
            raise ValueError("Build Approval server is loopback-only")
        if not isinstance(self.port, int) or not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if self.reconcile_interval_seconds <= 0:
            raise ValueError("reconcile interval must be positive")


class BuildApprovalServer(ThreadingHTTPServer):
    """Fixed-route HTTP relay around one ``ApprovalService``."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        service: ApprovalService,
        config: ApprovalServerConfig,
        *,
        join_token: str | None = None,
    ) -> None:
        self.service = service
        self.config = config
        token = join_token or secrets.token_urlsafe(32)
        if not _TOKEN.fullmatch(token):
            raise ValueError("join token must be URL-safe")
        self.join_token: str | None = token
        self.capability = secrets.token_urlsafe(32)
        self._memory_lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._lease: Any = None
        self._serve_thread: threading.Thread | None = None
        self._reconcile_thread: threading.Thread | None = None
        self._reconcile_requested = threading.Event()
        self._serving = threading.Event()
        self._stopping = threading.Event()
        self._assets = _load_assets()
        if ":" in config.host:
            self.address_family = socket.AF_INET6
        super().__init__((config.host, config.port), _ApprovalHandler)
        self.bound_port = int(self.server_address[1])
        host = f"[{config.host}]" if ":" in config.host else config.host
        self.authority = f"{host}:{self.bound_port}"
        self.origin = f"http://{self.authority}"
        self.approval_url = f"{self.origin}/join/{token}"

    def exchange_join_token(self, candidate: str) -> bool:
        with self._memory_lock:
            current = self.join_token
            if current is None or not secrets.compare_digest(current, candidate):
                return False
            self.join_token = None
            return True

    def valid_capability(self, candidate: str | None) -> bool:
        return candidate is not None and secrets.compare_digest(
            candidate, self.capability
        )

    def start(self) -> "BuildApprovalServer":
        with self._lifecycle_lock:
            if self._serve_thread is not None and self._serve_thread.is_alive():
                raise ApprovalServerError("Approval server is already running")
            self._acquire_lease()
            self._serve_thread = threading.Thread(
                target=self._serve_with_lease,
                name="hacksome-build-approval",
                daemon=True,
            )
            self._serve_thread.start()
        if not self._serving.wait(timeout=2):
            self._release_lease()
            raise ApprovalServerError("Approval server did not start")
        return self

    def serve_forever(self, poll_interval: float = 0.1) -> None:
        self._acquire_lease()
        self._serve_with_lease(poll_interval)

    def _serve_with_lease(self, poll_interval: float = 0.1) -> None:
        self._serving.set()
        self._reconcile_requested.set()
        self._reconcile_thread = threading.Thread(
            target=self._reconcile_loop,
            name="hacksome-build-reconcile",
            daemon=True,
        )
        self._reconcile_thread.start()
        try:
            super().serve_forever(poll_interval=poll_interval)
        finally:
            self._serving.clear()
            self._release_lease()

    def _reconcile_loop(self) -> None:
        while not self._stopping.is_set():
            self._reconcile_requested.wait(
                self.config.reconcile_interval_seconds
            )
            self._reconcile_requested.clear()
            if self._stopping.is_set():
                break
            try:
                self.service.reconcile()
            except Exception:
                # Durable outbox remains available to the next bounded pass.
                continue

    def request_reconcile(self) -> None:
        """Wake the single background reconciler without delaying HTTP."""

        self._reconcile_requested.set()

    def stop(self) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        self._reconcile_requested.set()
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
            reconcile = self._reconcile_thread
            if (
                reconcile is not None
                and reconcile.is_alive()
                and reconcile is not threading.current_thread()
            ):
                reconcile.join(timeout=2)
        finally:
            self._release_lease()

    def _acquire_lease(self) -> None:
        with self._lifecycle_lock:
            if self._lease is not None:
                return
            lease = advisory_lease(
                self.config.approval_root / "server.lock",
                exclusive=True,
                create=True,
                blocking=False,
            )
            try:
                lease.__enter__()
            except StateError:
                super().server_close()
                raise
            self._lease = lease

    def _release_lease(self) -> None:
        with self._lifecycle_lock:
            lease = self._lease
            if lease is None:
                return
            self._lease = None
            lease.__exit__(None, None, None)

    def __enter__(self) -> "BuildApprovalServer":
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.stop()


class _ApprovalHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HackSomeDispatch"
    sys_version = ""

    @property
    def approval_server(self) -> BuildApprovalServer:
        return cast(BuildApprovalServer, self.server)

    def version_string(self) -> str:
        return self.server_version

    def log_message(self, format: str, *args: Any) -> None:
        """Capability-bearing paths never reach process logs."""

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

    def _dispatch(self, method: str) -> None:
        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment:
            self._error(HTTPStatus.NOT_FOUND, "not_found", "route not found")
            return
        path = parsed.path
        allowed = _allowed_method(path)
        if allowed is None:
            self._error(HTTPStatus.NOT_FOUND, "not_found", "route not found")
            return
        if method != allowed:
            self._error(
                HTTPStatus.METHOD_NOT_ALLOWED,
                "method_not_allowed",
                f"{method} is not allowed for this route",
                extra_headers={"Allow": allowed},
            )
            return
        if not self._valid_host():
            self._error(
                HTTPStatus.BAD_REQUEST,
                "invalid_host",
                "invalid Host header",
            )
            return
        if path.startswith("/join/"):
            self._join(path.removeprefix("/join/"))
            return
        if not self._valid_origin(required=method == "POST"):
            self._error(
                HTTPStatus.FORBIDDEN,
                "invalid_origin",
                "Origin does not match this Approval server",
            )
            return
        if not self._authenticated():
            self._error(
                HTTPStatus.UNAUTHORIZED,
                "authentication_required",
                "open the Build Approval join link first",
            )
            return
        if method == "GET":
            self._get(path)
        else:
            self._post(path)

    def _join(self, token: str) -> None:
        if not self.approval_server.exchange_join_token(token):
            self._error(
                HTTPStatus.NOT_FOUND,
                "not_found",
                "join link is invalid or already used",
            )
            return
        self.send_response(HTTPStatus.SEE_OTHER)
        self._security_headers()
        self.send_header("Location", "/")
        self.send_header(
            "Set-Cookie",
            _cookie_header(
                CAPABILITY_COOKIE,
                self.approval_server.capability,
            ),
        )
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _get(self, path: str) -> None:
        if path == "/":
            self._bytes(
                HTTPStatus.OK,
                self.approval_server._assets["index.html"],
                "text/html; charset=utf-8",
            )
            return
        if path == "/assets/styles.css":
            self._bytes(
                HTTPStatus.OK,
                self.approval_server._assets["styles.css"],
                "text/css; charset=utf-8",
            )
            return
        if path == "/assets/app.js":
            self._bytes(
                HTTPStatus.OK,
                self.approval_server._assets["app.js"],
                "text/javascript; charset=utf-8",
            )
            return
        try:
            if path == "/api/snapshot":
                value = self.approval_server.service.snapshot()
            else:
                match = _CARD_DETAIL.fullmatch(path)
                if match is None:
                    raise KeyError(path)
                value = self.approval_server.service.card_detail(
                    int(match.group("ordinal"))
                )
        except KeyError:
            self._error(HTTPStatus.NOT_FOUND, "not_found", "route not found")
            return
        except ApprovalError as exc:
            self._error(exc.http_status, exc.code, str(exc))
            return
        except Exception:
            self._error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "snapshot_failed",
                "Build Approval state could not be loaded",
            )
            return
        self._json(HTTPStatus.OK, value)

    def _post(self, path: str) -> None:
        try:
            payload = self._json_body()
            if path == "/api/authorize":
                value = self.approval_server.service.authorize(payload)
                self.approval_server.request_reconcile()
                status = HTTPStatus.ACCEPTED
            elif path == "/api/close":
                value = self.approval_server.service.close(payload)
                status = HTTPStatus.OK
            elif path == "/api/reconcile":
                if payload:
                    raise ApprovalError(
                        "reconcile request must be an empty object"
                    )
                value = self.approval_server.service.reconcile()
                status = HTTPStatus.ACCEPTED
            else:
                self._error(
                    HTTPStatus.NOT_FOUND, "not_found", "route not found"
                )
                return
        except ApprovalHTTPError as exc:
            self._error(exc.status, exc.code, exc.message)
            return
        except ApprovalError as exc:
            self._error(exc.http_status, exc.code, str(exc))
            return
        except Exception:
            self._error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "mutation_failed",
                "the durable Build Approval mutation could not be completed",
            )
            return
        self._json(status, value)

    def _valid_host(self) -> bool:
        hosts = self.headers.get_all("Host", failobj=[])
        return len(hosts) == 1 and hosts[0].strip().lower() == (
            self.approval_server.authority.lower()
        )

    def _valid_origin(self, *, required: bool) -> bool:
        origins = self.headers.get_all("Origin", failobj=[])
        if not origins:
            return not required
        return len(origins) == 1 and secrets.compare_digest(
            origins[0].strip(),
            self.approval_server.origin,
        )

    def _authenticated(self) -> bool:
        cookie = _parse_cookie_headers(
            self.headers.get_all("Cookie", failobj=[])
        )
        morsel = cookie.get(CAPABILITY_COOKIE)
        return self.approval_server.valid_capability(
            morsel.value if morsel is not None else None
        )

    def _json_body(self) -> dict[str, Any]:
        types = self.headers.get_all("Content-Type", failobj=[])
        if len(types) != 1:
            raise ApprovalHTTPError(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "invalid_content_type",
                "Content-Type must be application/json",
            )
        media_type, separator, parameters = types[0].partition(";")
        if media_type.strip().lower() != "application/json":
            raise ApprovalHTTPError(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "invalid_content_type",
                "Content-Type must be application/json",
            )
        if separator and parameters.strip().lower() not in {
            "charset=utf-8",
            'charset="utf-8"',
        }:
            raise ApprovalHTTPError(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "invalid_charset",
                "JSON requests must use UTF-8",
            )
        lengths = self.headers.get_all("Content-Length", failobj=[])
        if len(lengths) != 1:
            raise ApprovalHTTPError(
                HTTPStatus.LENGTH_REQUIRED,
                "content_length_required",
                "Content-Length is required",
            )
        try:
            length = int(lengths[0])
        except ValueError as exc:
            raise ApprovalHTTPError(
                HTTPStatus.BAD_REQUEST,
                "invalid_content_length",
                "Content-Length must be an integer",
            ) from exc
        if length < 0:
            raise ApprovalHTTPError(
                HTTPStatus.BAD_REQUEST,
                "invalid_content_length",
                "Content-Length must not be negative",
            )
        if length > MAX_BODY_BYTES:
            raise ApprovalHTTPError(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "body_too_large",
                "request body exceeds the safety limit",
            )
        content = self.rfile.read(length)
        try:
            value = json.loads(content.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ApprovalHTTPError(
                HTTPStatus.BAD_REQUEST,
                "invalid_json",
                "request body is not valid UTF-8 JSON",
            ) from exc
        if not isinstance(value, dict):
            raise ApprovalHTTPError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "invalid_json_shape",
                "request JSON must be an object",
            )
        try:
            normalized = normalize_json(value, label="Approval HTTP request")
        except (StateError, ValueError) as exc:
            raise ApprovalHTTPError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "non_strict_json",
                "request JSON contains unsupported non-strict values",
            ) from exc
        if not isinstance(normalized, dict):
            raise ApprovalHTTPError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "invalid_json_shape",
                "request JSON must be an object",
            )
        return normalized

    def _json(
        self,
        status: int | HTTPStatus,
        value: Mapping[str, Any],
    ) -> None:
        try:
            body = json.dumps(
                normalize_json(dict(value), label="Approval HTTP response"),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except Exception:
            self._error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "invalid_backend_response",
                "Approval backend returned an invalid response",
            )
            return
        self._bytes(
            status,
            body,
            "application/json; charset=utf-8",
        )

    def _error(
        self,
        status: int | HTTPStatus,
        code: str,
        message: str,
        *,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.close_connection = True
        self._bytes(
            status,
            json.dumps(
                {"code": code, "message": message},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
            "application/json; charset=utf-8",
            extra_headers=extra_headers,
        )

    def _bytes(
        self,
        status: int | HTTPStatus,
        content: bytes,
        content_type: str,
        *,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.send_response(int(status))
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)
            self.wfile.flush()

    def _security_headers(self) -> None:
        for key, value in _SECURITY_HEADERS.items():
            self.send_header(key, value)
        self.send_header("Content-Security-Policy", _CSP)


def _allowed_method(path: str) -> str | None:
    if path.startswith("/join/") and len(path) > len("/join/"):
        return "GET"
    if _CARD_DETAIL.fullmatch(path):
        return "GET"
    return {
        "/": "GET",
        "/assets/styles.css": "GET",
        "/assets/app.js": "GET",
        "/api/snapshot": "GET",
        "/api/authorize": "POST",
        "/api/close": "POST",
        "/api/reconcile": "POST",
    }.get(path)


def _load_assets() -> dict[str, bytes]:
    package_root = resources.files("hacksome.stages.build").joinpath(
        "approval_ui"
    )
    assets: dict[str, bytes] = {}
    for name in ("index.html", "styles.css", "app.js"):
        try:
            assets[name] = package_root.joinpath(name).read_bytes()
        except (FileNotFoundError, TypeError) as exc:
            raise ApprovalServerError(
                f"packaged Build Approval UI asset is missing: {name}"
            ) from exc
    return assets


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _cookie_header(name: str, value: str) -> str:
    cookie = SimpleCookie()
    cookie[name] = value
    cookie[name]["path"] = "/"
    cookie[name]["httponly"] = True
    cookie[name]["samesite"] = "Strict"
    return cookie.output(header="").strip()


def _parse_cookie_headers(values: list[str]) -> SimpleCookie:
    cookie = SimpleCookie()
    try:
        cookie.load("; ".join(values))
    except Exception:
        return SimpleCookie()
    return cookie


__all__ = [
    "ApprovalHTTPError",
    "ApprovalServerConfig",
    "ApprovalServerError",
    "BuildApprovalServer",
    "CAPABILITY_COOKIE",
]
