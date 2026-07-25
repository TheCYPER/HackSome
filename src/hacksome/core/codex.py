"""Async subprocess runner for the local Codex CLI.

This module intentionally implements one concrete runtime. It is not a model
provider abstraction: its command line, JSONL event parsing, session resume,
and doctor probes all follow the Codex CLI contract.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import (  # type: ignore[import-untyped]
    SchemaError,
    ValidationError,
)

from hacksome.core.config import CodexConfig
from hacksome.core.models import (
    CodexDoctorResult,
    CodexError,
    CodexFailureKind,
    CodexLogs,
    CodexResult,
    CodexRunStatus,
    CodexTask,
)


_FAILURE_EVENT_TYPES = {"error", "turn.failed"}
_CODEX_UNSUPPORTED_SCHEMA_KEYWORDS = frozenset({"uniqueItems"})
_SCHEMA_MAP_CHILDREN = frozenset(
    {"$defs", "definitions", "dependentSchemas", "patternProperties", "properties"}
)
_SCHEMA_LIST_CHILDREN = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
_SCHEMA_SINGLE_CHILDREN = frozenset(
    {
        "additionalProperties",
        "contains",
        "else",
        "if",
        "items",
        "not",
        "propertyNames",
        "then",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
)
_REQUIRED_DISABLED_FEATURES = frozenset(CodexConfig().disabled_features)
_REQUIRED_CONFIG_OVERRIDES = frozenset(CodexConfig().config_overrides)


@dataclass(slots=True)
class _AttemptCapture:
    session_id: str | None = None
    usage: dict[str, int | float] = field(default_factory=dict)
    reported_error: str | None = None
    turn_completed: bool = False
    stderr_tail: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _AttemptResult:
    status: CodexRunStatus
    session_id: str | None
    structured_output: dict[str, Any]
    usage: dict[str, int | float]
    error: CodexError | None
    returncode: int | None
    last_message: Path


class CodexRunner:
    """Run Codex tasks with bounded concurrency and durable diagnostics."""

    def __init__(self, config: CodexConfig | None = None) -> None:
        self.config = config or CodexConfig()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrency)

    async def run(self, task: CodexTask) -> CodexResult:
        """Execute one logical task, resuming its explicit session on retry."""

        cwd, schema, schema_validator, log_root = self._validate_and_resolve(task)
        log_root.mkdir(parents=True, exist_ok=True)
        stdout_log = log_root / "stdout.jsonl"
        stderr_log = log_root / "stderr.jsonl"
        # A caller can always inspect both paths, including when process spawn
        # fails before either stream reader is created.
        stdout_log.touch(exist_ok=True)
        stderr_log.touch(exist_ok=True)

        started_at = _utc_now()
        started_monotonic = time.monotonic()
        total_usage: dict[str, int | float] = {}
        current_session_id = task.session_id if task.resume else None
        should_resume = task.resume
        final_attempt: _AttemptResult | None = None
        attempts = 0

        for attempt_number in range(1, self.config.infrastructure_retries + 2):
            attempts = attempt_number
            last_message = log_root / f"last-message.attempt-{attempt_number:03d}.json"
            self._append_jsonl(
                stderr_log,
                {
                    "type": "runner.attempt.started",
                    "attempt": attempt_number,
                    "resume": should_resume,
                    "session_id": current_session_id,
                    "timestamp": _utc_now(),
                },
            )

            async with self._semaphore:
                final_attempt = await self._run_once(
                    task=task,
                    cwd=cwd,
                    schema=schema,
                    schema_validator=schema_validator,
                    stdout_log=stdout_log,
                    stderr_log=stderr_log,
                    last_message=last_message,
                    attempt_number=attempt_number,
                    resume=should_resume,
                    session_id=current_session_id,
                )

            _merge_usage(total_usage, final_attempt.usage)
            if final_attempt.session_id:
                current_session_id = final_attempt.session_id

            self._append_jsonl(
                stderr_log,
                {
                    "type": "runner.attempt.finished",
                    "attempt": attempt_number,
                    "status": final_attempt.status.value,
                    "returncode": final_attempt.returncode,
                    "session_id": current_session_id,
                    "timestamp": _utc_now(),
                },
            )

            if final_attempt.status is CodexRunStatus.SUCCEEDED:
                break
            if final_attempt.error is None or not final_attempt.error.retryable:
                break
            if attempt_number > self.config.infrastructure_retries:
                break

            # Never use `--last`: after a session id has been observed, retries
            # are tied to that exact thread. A pre-thread spawn failure retries
            # as a fresh task because there is nothing valid to resume.
            should_resume = current_session_id is not None

        assert final_attempt is not None
        finished_at = _utc_now()
        logs = CodexLogs(
            stdout=stdout_log,
            stderr=stderr_log,
            last_message=final_attempt.last_message,
        )
        return CodexResult(
            task_id=task.task_id,
            status=final_attempt.status,
            session_id=current_session_id,
            structured_output=final_attempt.structured_output,
            usage=total_usage,
            logs=logs,
            error=final_attempt.error,
            returncode=final_attempt.returncode,
            attempts=attempts,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=time.monotonic() - started_monotonic,
        )

    async def doctor(self) -> CodexDoctorResult:
        """Probe executable, CLI capabilities, version, and login state."""

        executable = shutil.which(self.config.executable)
        if executable is None:
            return CodexDoctorResult(
                executable=self.config.executable,
                available=False,
                error=f"Codex executable not found: {self.config.executable}",
            )

        version_probe = await self._probe([executable, "--version"])
        if version_probe[0] != 0:
            return CodexDoctorResult(
                executable=executable,
                available=True,
                error=_probe_error("version probe failed", version_probe),
            )
        version = (version_probe[1] or version_probe[2]).strip() or None

        root_help = await self._probe([executable, "--help"])
        exec_help = await self._probe([executable, "exec", "--help"])
        root_text = f"{root_help[1]}\n{root_help[2]}"
        exec_text = f"{exec_help[1]}\n{exec_help[2]}"
        capabilities = {
            "json_events": "--json" in exec_text,
            "output_schema": "--output-schema" in exec_text,
            "last_message": "--output-last-message" in exec_text,
            "explicit_resume": "resume" in exec_text,
            "web_search": "--search" in root_text,
            "workspace_sandbox": "--sandbox" in root_text,
            "isolated_cwd": "--cd" in root_text,
        }

        login_probe = await self._probe([executable, "login", "status"])
        authenticated = login_probe[0] == 0
        errors: list[str] = []
        if root_help[0] != 0 or exec_help[0] != 0:
            errors.append("Codex help/capability probe failed")
        missing = [name for name, present in capabilities.items() if not present]
        if missing:
            errors.append(f"Codex is missing required capabilities: {', '.join(missing)}")
        if not authenticated:
            errors.append(_probe_error("Codex login check failed", login_probe))
        isolation_error = _runtime_isolation_error(self.config)
        if isolation_error:
            errors.append(isolation_error)
        ambient_error = _ambient_global_instruction_error()
        if ambient_error:
            errors.append(ambient_error)

        return CodexDoctorResult(
            executable=executable,
            available=True,
            version=version,
            authenticated=authenticated,
            capabilities=capabilities,
            error="; ".join(errors) or None,
        )

    def _validate_and_resolve(
        self, task: CodexTask
    ) -> tuple[Path, Path, Draft202012Validator, Path]:
        isolation_error = _runtime_isolation_error(self.config)
        if isolation_error:
            raise ValueError(isolation_error)
        ambient_error = _ambient_global_instruction_error()
        if ambient_error:
            raise ValueError(ambient_error)

        cwd = task.cwd.expanduser().resolve()
        if not cwd.is_dir():
            raise ValueError(f"Task cwd is not an existing directory: {cwd}")

        schema = task.output_schema.expanduser().resolve()
        if not schema.is_file():
            raise ValueError(f"Output schema is not an existing file: {schema}")
        try:
            schema_value = json.loads(schema.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Output schema is not valid UTF-8 JSON: {schema}") from exc
        unsupported = _find_unsupported_schema_keywords(schema_value)
        if unsupported:
            details = ", ".join(sorted(unsupported))
            raise ValueError(
                "Output schema uses keyword(s) unsupported by Codex structured "
                f"output: {details}"
            )
        try:
            Draft202012Validator.check_schema(schema_value)
        except SchemaError as exc:
            raise ValueError(f"Output schema is not valid JSON Schema: {exc.message}") from exc
        schema_validator = Draft202012Validator(schema_value)

        if task.log_dir is None:
            log_root = cwd / ".hacksome" / "logs" / task.task_id
        else:
            log_root = task.log_dir.expanduser().resolve()
        return cwd, schema, schema_validator, log_root

    async def _run_once(
        self,
        *,
        task: CodexTask,
        cwd: Path,
        schema: Path,
        schema_validator: Draft202012Validator,
        stdout_log: Path,
        stderr_log: Path,
        last_message: Path,
        attempt_number: int,
        resume: bool,
        session_id: str | None,
    ) -> _AttemptResult:
        capture = _AttemptCapture(session_id=session_id)
        command = self._build_command(
            task=task,
            cwd=cwd,
            schema=schema,
            last_message=last_message,
            resume=resume,
            session_id=session_id,
        )
        timeout = task.timeout_seconds or self.config.default_timeout_seconds

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
                start_new_session=(os.name == "posix"),
                limit=self.config.subprocess_stream_limit_bytes,
            )
        except FileNotFoundError:
            error = CodexError(
                kind=CodexFailureKind.EXECUTABLE_NOT_FOUND,
                message=f"Codex executable not found: {self.config.executable}",
                retryable=False,
            )
            self._log_spawn_failure(stderr_log, attempt_number, error)
            return _failed_attempt(error, last_message)
        except OSError as exc:
            error = CodexError(
                kind=CodexFailureKind.SPAWN_FAILED,
                message=f"Could not start Codex: {exc}",
                retryable=True,
            )
            self._log_spawn_failure(stderr_log, attempt_number, error)
            return _failed_attempt(error, last_message)

        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_reader = asyncio.create_task(
            self._drain_stdout(
                process.stdout, stdout_log, capture, attempt_number
            )
        )
        stderr_reader = asyncio.create_task(
            self._drain_stderr(
                process.stderr, stderr_log, capture, attempt_number
            )
        )

        timed_out = False
        try:
            async with asyncio.timeout(timeout):
                try:
                    process.stdin.write(task.prompt.encode("utf-8"))
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    # The real exit code and stderr carry the useful failure.
                    pass
                finally:
                    process.stdin.close()
                await process.wait()
        except TimeoutError:
            timed_out = True
            await self._terminate_process_group(process)
        except asyncio.CancelledError:
            await self._terminate_process_group(process)
            await asyncio.gather(stdout_reader, stderr_reader, return_exceptions=True)
            raise
        finally:
            if not process.stdin.is_closing():
                process.stdin.close()

        await asyncio.gather(stdout_reader, stderr_reader)
        returncode = process.returncode

        if timed_out:
            error = CodexError(
                kind=CodexFailureKind.TIMED_OUT,
                message=f"Codex task timed out after {timeout:g} seconds",
                retryable=True,
                returncode=returncode,
            )
            return _AttemptResult(
                status=CodexRunStatus.TIMED_OUT,
                session_id=capture.session_id,
                structured_output={},
                usage=capture.usage,
                error=error,
                returncode=returncode,
                last_message=last_message,
            )

        if returncode != 0:
            detail = capture.reported_error or _stderr_summary(capture.stderr_tail)
            suffix = f": {detail}" if detail else ""
            error = CodexError(
                kind=CodexFailureKind.NON_ZERO_EXIT,
                message=f"Codex exited with status {returncode}{suffix}",
                retryable=(
                    not _looks_like_auth_failure(detail)
                    and not _looks_like_non_retryable_request_failure(detail)
                ),
                returncode=returncode,
            )
            return _AttemptResult(
                status=CodexRunStatus.FAILED,
                session_id=capture.session_id,
                structured_output={},
                usage=capture.usage,
                error=error,
                returncode=returncode,
                last_message=last_message,
            )

        if capture.reported_error:
            error = CodexError(
                kind=CodexFailureKind.CODEX_REPORTED_FAILURE,
                message=capture.reported_error,
                retryable=True,
                returncode=returncode,
            )
            return _AttemptResult(
                status=CodexRunStatus.FAILED,
                session_id=capture.session_id,
                structured_output={},
                usage=capture.usage,
                error=error,
                returncode=returncode,
                last_message=last_message,
            )

        if not capture.session_id:
            error = CodexError(
                kind=CodexFailureKind.PROTOCOL_ERROR,
                message="Codex completed without emitting a thread/session id",
                retryable=True,
                returncode=returncode,
            )
            return _failed_attempt(
                error,
                last_message,
                usage=capture.usage,
                returncode=returncode,
            )

        structured_output, output_error = _read_last_message(last_message)
        if output_error:
            error = CodexError(
                kind=CodexFailureKind.INVALID_OUTPUT,
                message=output_error,
                retryable=True,
                returncode=returncode,
            )
            return _AttemptResult(
                status=CodexRunStatus.FAILED,
                session_id=capture.session_id,
                structured_output={},
                usage=capture.usage,
                error=error,
                returncode=returncode,
                last_message=last_message,
            )

        try:
            schema_validator.validate(structured_output)
        except ValidationError as exc:
            location = ".".join(str(part) for part in exc.absolute_path)
            prefix = f" at {location}" if location else ""
            error = CodexError(
                kind=CodexFailureKind.INVALID_OUTPUT,
                message=f"Codex last message failed output schema{prefix}: {exc.message}",
                retryable=True,
                returncode=returncode,
            )
            return _AttemptResult(
                status=CodexRunStatus.FAILED,
                session_id=capture.session_id,
                structured_output={},
                usage=capture.usage,
                error=error,
                returncode=returncode,
                last_message=last_message,
            )

        return _AttemptResult(
            status=CodexRunStatus.SUCCEEDED,
            session_id=capture.session_id,
            structured_output=structured_output,
            usage=capture.usage,
            error=None,
            returncode=returncode,
            last_message=last_message,
        )

    def _build_command(
        self,
        *,
        task: CodexTask,
        cwd: Path,
        schema: Path,
        last_message: Path,
        resume: bool,
        session_id: str | None,
    ) -> list[str]:
        command = [
            self.config.executable,
            "--ask-for-approval",
            self.config.approval_policy,
            "--sandbox",
            self.config.sandbox,
            "--cd",
            str(cwd),
        ]
        if self.config.model:
            command.extend(["--model", self.config.model])
        command.extend(
            [
                "--config",
                f'model_reasoning_effort="{self.config.reasoning_effort}"',
            ]
        )
        for feature in self.config.disabled_features:
            command.extend(["--disable", feature])
        for override in self.config.config_overrides:
            command.extend(["--config", override])
        # Stage policy must win over both Codex defaults and any ambient/user
        # configuration. In particular, non-research stages are explicitly
        # offline instead of merely omitting the `--search` convenience flag.
        web_search_mode = "live" if task.web_search else "disabled"
        command.extend(["--config", f'web_search="{web_search_mode}"'])

        command.append("exec")
        if resume:
            if not session_id:
                raise ValueError("An explicit session_id is required to resume Codex")
            command.append("resume")

        command.extend(
            [
                "--json",
                "--output-schema",
                str(schema),
                "--output-last-message",
                str(last_message),
            ]
        )
        if self.config.ignore_user_config:
            command.append("--ignore-user-config")
        if self.config.ignore_rules:
            command.append("--ignore-rules")
        if self.config.skip_git_repo_check:
            command.append("--skip-git-repo-check")
        if self.config.strict_config:
            command.append("--strict-config")

        if resume:
            assert session_id is not None
            command.append(session_id)
        command.append("-")
        return command

    async def _drain_stdout(
        self,
        stream: asyncio.StreamReader,
        path: Path,
        capture: _AttemptCapture,
        attempt_number: int,
    ) -> None:
        with path.open("a", encoding="utf-8") as log:
            async for raw_line in stream:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = {
                        "type": "runner.stdout.unparsed",
                        "line": line,
                    }
                if not isinstance(event, dict):
                    event = {
                        "type": "runner.stdout.unparsed",
                        "value": event,
                    }
                self._capture_event(event, capture)
                _write_jsonl_record(
                    log,
                    {
                        "attempt": attempt_number,
                        "timestamp": _utc_now(),
                        "event": event,
                    },
                )

    async def _drain_stderr(
        self,
        stream: asyncio.StreamReader,
        path: Path,
        capture: _AttemptCapture,
        attempt_number: int,
    ) -> None:
        with path.open("a", encoding="utf-8") as log:
            async for raw_line in stream:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    continue
                capture.stderr_tail.append(line)
                if len(capture.stderr_tail) > 20:
                    del capture.stderr_tail[0]
                _write_jsonl_record(
                    log,
                    {
                        "type": "runner.stderr",
                        "attempt": attempt_number,
                        "timestamp": _utc_now(),
                        "line": line,
                    },
                )

    @staticmethod
    def _capture_event(event: dict[str, Any], capture: _AttemptCapture) -> None:
        session_id = _event_session_id(event)
        if session_id:
            capture.session_id = session_id

        usage = event.get("usage")
        if isinstance(usage, dict):
            _merge_usage(capture.usage, usage)

        event_type = event.get("type")
        if event_type == "turn.completed":
            # Codex can emit transient `error` events while reconnecting a
            # sampling request. A later terminal completion is authoritative.
            capture.turn_completed = True
            capture.reported_error = None
        elif event_type in _FAILURE_EVENT_TYPES:
            capture.turn_completed = False
            capture.reported_error = _event_error(event)

    async def _terminate_process_group(
        self, process: asyncio.subprocess.Process
    ) -> None:
        if process.returncode is not None:
            return

        self._send_process_signal(process, signal.SIGTERM)
        try:
            await asyncio.wait_for(
                process.wait(), timeout=self.config.termination_grace_seconds
            )
            return
        except TimeoutError:
            pass

        self._send_process_signal(process, signal.SIGKILL)
        await process.wait()

    @staticmethod
    def _send_process_signal(
        process: asyncio.subprocess.Process, sig: signal.Signals
    ) -> None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, sig)
            elif sig == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        except ProcessLookupError:
            pass

    async def _probe(self, command: list[str]) -> tuple[int | None, str, str]:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=self.config.subprocess_stream_limit_bytes,
            )
        except OSError as exc:
            return None, "", str(exc)
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.config.doctor_timeout_seconds
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            return None, "", "probe timed out"
        return (
            process.returncode,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    @staticmethod
    def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as log:
            _write_jsonl_record(log, record)

    @staticmethod
    def _log_spawn_failure(
        stderr_log: Path, attempt_number: int, error: CodexError
    ) -> None:
        CodexRunner._append_jsonl(
            stderr_log,
            {
                "type": "runner.spawn.failed",
                "attempt": attempt_number,
                "timestamp": _utc_now(),
                "kind": error.kind.value,
                "message": error.message,
            },
        )


def _failed_attempt(
    error: CodexError,
    last_message: Path,
    *,
    usage: dict[str, int | float] | None = None,
    returncode: int | None = None,
) -> _AttemptResult:
    return _AttemptResult(
        status=CodexRunStatus.FAILED,
        session_id=None,
        structured_output={},
        usage=usage or {},
        error=error,
        returncode=returncode,
        last_message=last_message,
    )


def _read_last_message(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, f"Codex did not write the last-message file: {path}"
    except OSError as exc:
        return {}, f"Could not read Codex last-message file {path}: {exc}"

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"Codex last message is not valid JSON: {exc}"
    if not isinstance(parsed, dict):
        return {}, "Codex last message must be a JSON object"
    return parsed, None


def _ambient_global_instruction_error() -> str | None:
    """Reject global Codex instructions that would leak into stage sessions."""

    configured_home = os.environ.get("CODEX_HOME", "").strip()
    codex_home = (
        Path(configured_home).expanduser()
        if configured_home
        else Path.home() / ".codex"
    )
    for name in ("AGENTS.override.md", "AGENTS.md"):
        candidate = codex_home / name
        try:
            if candidate.is_file() and candidate.read_text(encoding="utf-8").strip():
                return (
                    "Codex stage isolation requires no global instructions; "
                    f"{candidate} is non-empty"
                )
        except (OSError, UnicodeError) as exc:
            return f"Could not verify global Codex instructions at {candidate}: {exc}"
    return None


def _runtime_isolation_error(config: CodexConfig) -> str | None:
    missing_features = sorted(
        _REQUIRED_DISABLED_FEATURES.difference(config.disabled_features)
    )
    missing_overrides = sorted(
        _REQUIRED_CONFIG_OVERRIDES.difference(config.config_overrides)
    )
    disabled_controls = [
        name
        for name, enabled in (
            ("ignore_user_config", config.ignore_user_config),
            ("ignore_rules", config.ignore_rules),
            ("strict_config", config.strict_config),
        )
        if not enabled
    ]
    details: list[str] = []
    if missing_features:
        details.append("missing --disable " + ", ".join(missing_features))
    if missing_overrides:
        details.append("missing --config " + ", ".join(missing_overrides))
    if disabled_controls:
        details.append("disabled controls " + ", ".join(disabled_controls))
    if not details:
        return None
    return "Codex stage isolation configuration is incomplete: " + "; ".join(details)


def _event_session_id(event: dict[str, Any]) -> str | None:
    for key in ("thread_id", "session_id", "threadId", "sessionId"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    thread = event.get("thread")
    if isinstance(thread, dict):
        value = thread.get("id")
        if isinstance(value, str) and value:
            return value
    return None


def _event_error(event: dict[str, Any]) -> str:
    error = event.get("error")
    if isinstance(error, str) and error:
        return error
    if isinstance(error, dict):
        for key in ("message", "detail", "code"):
            value = error.get(key)
            if isinstance(value, str) and value:
                return value
    for key in ("message", "detail"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return f"Codex reported {event.get('type', 'an error')}"


def _merge_usage(
    destination: dict[str, int | float], source: dict[str, Any]
) -> None:
    for key, value in source.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        destination[key] = destination.get(key, 0) + value


def _stderr_summary(lines: list[str], limit: int = 2_000) -> str:
    return "\n".join(lines)[-limit:].strip()


def _looks_like_auth_failure(message: str | None) -> bool:
    if not message:
        return False
    normalized = message.casefold()
    markers = (
        "not logged in",
        "authentication",
        "unauthorized",
        "invalid api key",
        "login required",
    )
    return any(marker in normalized for marker in markers)


def _looks_like_non_retryable_request_failure(message: str | None) -> bool:
    """Return true when retrying the identical Codex request cannot help."""

    if not message:
        return False
    normalized = message.casefold()
    markers = (
        "invalid_request_error",
        "invalid_json_schema",
        "unsupported_parameter",
        "context_length_exceeded",
    )
    return any(marker in normalized for marker in markers)


def _find_unsupported_schema_keywords(value: Any, path: str = "$") -> set[str]:
    """Locate output-schema vocabulary known to be rejected by Codex."""

    found: set[str] = set()
    if not isinstance(value, dict):
        return found
    for key in value:
        if key in _CODEX_UNSUPPORTED_SCHEMA_KEYWORDS:
            found.add(f"{path}.{key}")
    for key in _SCHEMA_SINGLE_CHILDREN:
        child = value.get(key)
        if isinstance(child, dict):
            found.update(_find_unsupported_schema_keywords(child, f"{path}.{key}"))
    for key in _SCHEMA_LIST_CHILDREN:
        children = value.get(key)
        if isinstance(children, list):
            for index, child in enumerate(children):
                found.update(
                    _find_unsupported_schema_keywords(
                        child,
                        f"{path}.{key}[{index}]",
                    )
                )
    for key in _SCHEMA_MAP_CHILDREN:
        children = value.get(key)
        if isinstance(children, dict):
            for name, child in children.items():
                found.update(
                    _find_unsupported_schema_keywords(
                        child,
                        f"{path}.{key}.{name}",
                    )
                )
    return found


def _write_jsonl_record(log: TextIO, record: dict[str, Any]) -> None:
    log.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    log.write("\n")
    log.flush()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _probe_error(
    prefix: str, probe: tuple[int | None, str, str]
) -> str:
    returncode, stdout, stderr = probe
    detail = (stderr or stdout).strip()
    suffix = f": {detail}" if detail else ""
    return f"{prefix} (status {returncode}){suffix}"
