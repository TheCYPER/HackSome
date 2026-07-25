"""Shared persistence primitives for the V7 orchestration control plane.

The orchestration state is deliberately split from Company State.  LLM
runtimes may receive a mount for ``company/``; every other directory below the
company root is operator/control-plane state and must be reached only through
deterministic methods.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


INTERNAL_DOMAINS = (
    "agents",
    "notes",
    "departments",
    "ledger",
    "inbox",
    "workers",
    "reviews",
    "control",
    "sessions",
    "telemetry",
    "mailboxes",
)

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,62}$")


class StoreError(ValueError):
    """Invalid state identifier or malformed persisted data."""


def require_identifier(value: str, *, label: str = "identifier") -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise StoreError(f"invalid {label}: {value!r}")
    return value


def atomic_write_json(path: Path, value: object) -> None:
    """Atomically replace one JSON document in its destination directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)


def atomic_write_text(path: Path, value: str) -> None:
    """Atomically replace one UTF-8 text projection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)


def read_json(path: Path, *, default=None):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StoreError(f"invalid JSON store {path}: {exc}") from exc


def append_jsonl(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        with contextlib.suppress(OSError):
            os.fchmod(stream.fileno(), 0o666)
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StoreError(f"invalid JSONL {path}:{line_number}: {exc}") from exc
        if not isinstance(row, dict):
            raise StoreError(f"invalid JSONL object {path}:{line_number}")
        rows.append(row)
    return rows


@contextlib.contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Cross-process advisory lock with mixed-container uid compatibility."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o666)
    try:
        with contextlib.suppress(PermissionError):
            os.fchmod(fd, 0o666)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@dataclass(frozen=True)
class CompanyLayout:
    """Filesystem contract for one brand-new V7 company."""

    root: Path

    @classmethod
    def initialize(cls, root: str | os.PathLike) -> "CompanyLayout":
        layout = cls(Path(root).resolve())
        layout.root.mkdir(parents=True, exist_ok=True)
        layout.company.mkdir(parents=True, exist_ok=True)
        for domain in INTERNAL_DOMAINS:
            (layout.root / domain).mkdir(parents=True, exist_ok=True)
        for path in (
            layout.departments / "requests",
            layout.departments / "commands",
            layout.workers / "commands",
            layout.reviews / "commands",
            layout.reviews / "homes",
            layout.control / "requests",
            layout.telemetry / "index",
            layout.telemetry / "runs",
            layout.telemetry / "services",
        ):
            path.mkdir(parents=True, exist_ok=True)
        return layout

    @property
    def company(self) -> Path:
        return self.root / "company"

    @property
    def agents(self) -> Path:
        return self.root / "agents"

    @property
    def notes(self) -> Path:
        return self.root / "notes"

    @property
    def departments(self) -> Path:
        return self.root / "departments"

    @property
    def ledger(self) -> Path:
        return self.root / "ledger"

    @property
    def inbox(self) -> Path:
        return self.root / "inbox"

    @property
    def workers(self) -> Path:
        return self.root / "workers"

    @property
    def reviews(self) -> Path:
        return self.root / "reviews"

    @property
    def control(self) -> Path:
        return self.root / "control"

    @property
    def sessions(self) -> Path:
        return self.root / "sessions"

    @property
    def telemetry(self) -> Path:
        return self.root / "telemetry"

    @property
    def mailboxes(self) -> Path:
        """Company-private email journal and send ledger (control plane only)."""
        return self.root / "mailboxes"

    def agent_state_mount(self, *, read_only: bool = False) -> dict[str, str]:
        """Return the sole raw company-state mount allowed in an LLM runtime."""
        return {
            "source": str(self.company),
            "target": "/company",
            "mode": "ro" if read_only else "rw",
        }

    def objective_path(self, actor_id: str) -> Path:
        return self.agents / require_identifier(actor_id, label="actor id") / "objective.md"

    def notes_path(self, actor_id: str) -> Path:
        return self.notes / require_identifier(actor_id, label="actor id") / "notes.md"
