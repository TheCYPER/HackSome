"""Typed contracts used by the Codex runtime and its callers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class CodexRunStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class CodexFailureKind(str, Enum):
    EXECUTABLE_NOT_FOUND = "executable_not_found"
    SPAWN_FAILED = "spawn_failed"
    TIMED_OUT = "timed_out"
    NON_ZERO_EXIT = "non_zero_exit"
    CODEX_REPORTED_FAILURE = "codex_reported_failure"
    PROTOCOL_ERROR = "protocol_error"
    INVALID_OUTPUT = "invalid_output"


@dataclass(frozen=True, slots=True)
class CodexTask:
    """One logical workflow task executed in an isolated local directory."""

    task_id: str
    prompt: str
    cwd: Path
    output_schema: Path
    web_search: bool = False
    timeout_seconds: float | None = None
    session_id: str | None = None
    resume: bool = False
    log_dir: Path | None = None

    def __post_init__(self) -> None:
        if not _TASK_ID.fullmatch(self.task_id):
            raise ValueError(
                "task_id must contain only letters, numbers, '.', '_' or '-' "
                "and be at most 128 characters"
            )
        if not self.prompt:
            raise ValueError("prompt must not be empty")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.resume and not self.session_id:
            raise ValueError("resume=True requires an explicit session_id")
        if self.session_id is not None and not self.session_id.strip():
            raise ValueError("session_id must not be blank")


@dataclass(frozen=True, slots=True)
class CodexLogs:
    stdout: Path
    stderr: Path
    last_message: Path


@dataclass(frozen=True, slots=True)
class CodexError:
    kind: CodexFailureKind
    message: str
    retryable: bool
    returncode: int | None = None


@dataclass(frozen=True, slots=True)
class CodexResult:
    task_id: str
    status: CodexRunStatus
    session_id: str | None
    structured_output: dict[str, Any]
    usage: dict[str, int | float]
    logs: CodexLogs
    error: CodexError | None
    returncode: int | None
    attempts: int
    started_at: str
    finished_at: str
    duration_seconds: float

    @property
    def success(self) -> bool:
        return self.status is CodexRunStatus.SUCCEEDED

    @property
    def stdout_log(self) -> Path:
        return self.logs.stdout

    @property
    def stderr_log(self) -> Path:
        return self.logs.stderr

    @property
    def last_message_path(self) -> Path:
        return self.logs.last_message


@dataclass(frozen=True, slots=True)
class CodexDoctorResult:
    executable: str
    available: bool
    version: str | None = None
    authenticated: bool | None = None
    capabilities: dict[str, bool] = field(default_factory=dict)
    error: str | None = None

    @property
    def healthy(self) -> bool:
        return (
            self.available
            and self.authenticated is True
            and bool(self.capabilities)
            and all(self.capabilities.values())
            and self.error is None
        )
