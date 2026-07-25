#!/usr/bin/env python3
"""V7 Hub-owned FIFO Inbox using append-only JSONL plus explicit ack cursors.

Only the deterministic control plane opens these files. Resident Agents reach
their bound FIFO head through ``RemoteInbox`` and never receive this directory
as a mount. Reading is non-consuming; successful wake completion advances one
message atomically through the Company Hub.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

# Stable actor key for the resident CEO.
CEO_KEY = "ceo"

# --- IME envelope (the Standard Point; design §2) ----------------------------

def make_ime(to: str | None, text: str, body: object, *, id: str | None = None,
             ts: str | None = None) -> dict:
    """Build a 5-field Inbox Message Envelope — IME (design §2): the ONE shape
    every async inbound thing (external event / goal completion / tool result)
    collapses to, read by the agent like a tool result.

        id    — dedup / read handle (auto: uuid hex)
        time  — when it happened (auto: ISO-8601 UTC)
        to    — addressee = which agent's inbox; None → the CEO
        text  — a VERY short, glanceable line
        body  — the full content; everything else (source, links, "which goal
                this answers", deadlines, structured data) is mentioned INSIDE
                body, never as new envelope fields (design §2.3).

    `to` is also the Hub-owned routing key; routing does not inspect text/body."""
    return {
        "id": id or uuid.uuid4().hex,
        "time": ts or datetime.now(timezone.utc).isoformat(),
        "to": to,
        "text": text,
        "body": body,
    }


@runtime_checkable
class Inbox(Protocol):
    """Reliable Hub-side FIFO contract."""

    def append(self, key: str, event: dict) -> None:
        """Producer side (state machine): enqueue one event under `key`."""
        ...

    def peek_one(self, key: str) -> dict | None: ...

    def ack_one(self, key: str) -> None: ...

    def wait(self, key: str, timeout: float) -> bool: ...


class FileInbox:
    """Minimal file stub: `<root>/<key>.jsonl` (append-only) + `<key>.cursor`.

    One Hub consumer per key; many producers may append under one advisory
    lock. Entirely swappable behind the ``Inbox`` protocol.

    ``root`` is always supplied by the deterministic control-plane layout.
    There is no environment fallback that lets an Agent silently open a second
    Inbox.
    """

    def __init__(self, root: str | os.PathLike, poll_tick: float = 1.0):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.poll_tick = poll_tick

    def _events_path(self, key: str) -> Path:
        return self.root / f"{key}.jsonl"

    def _cursor_path(self, key: str) -> Path:
        return self.root / f"{key}.cursor"

    def _seen_path(self, key: str) -> Path:
        return self.root / f"{key}.seen"

    @contextlib.contextmanager
    def _lock(self):
        # 0o666 + best-effort fchmod: internal producers may run under different
        # container uids, while all mutation remains control-plane-owned.
        fd = os.open(self.root / ".inbox.lock", os.O_CREAT | os.O_RDWR, 0o666)
        try:
            try:
                os.fchmod(fd, 0o666)
            except PermissionError:
                pass
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    # --- producer ------------------------------------------------------------

    def append(self, key: str, event: dict) -> None:
        """Enqueue one event under `key`. If the event carries an `id`, it is
        deduped: a redelivered event (same id) is dropped — sources are
        at-least-once (design R4). Events WITHOUT an `id` are always appended
        (the ledger's pre-IME terminal events have none)."""
        eid = event.get("id")
        line = json.dumps(event, ensure_ascii=False)
        with self._lock():
            if eid is not None:
                seen = self._seen_path(key)
                ids = set(seen.read_text(encoding="utf-8").split()) if seen.is_file() else set()
                if eid in ids:
                    return
                with seen.open("a", encoding="utf-8") as f:
                    self._share(f)
                    f.write(eid + "\n")
            with self._events_path(key).open("a", encoding="utf-8") as f:
                self._share(f)
                f.write(line + "\n")

    @staticmethod
    def _share(f) -> None:
        """Best-effort 0o666 on a producer-written file (.jsonl / .seen) — the
        same mixed-uid stance as `_lock`: one key can have producers in ROOT
        containers (hub, provisioner) and kasm-user agent containers (e.g. the
        verifier's role/objective verdict IMEs land in ceo.jsonl, which the hub
        may have created first). The creator opens it up; a later non-owner's
        fchmod raises — ignore it (the file is already 666 then)."""
        with contextlib.suppress(OSError):
            os.fchmod(f.fileno(), 0o666)

    # --- consumer ------------------------------------------------------------

    def _read_cursor(self, key: str) -> int:
        p = self._cursor_path(key)
        if not p.is_file():
            return 0
        try:
            return int(p.read_text(encoding="utf-8").strip() or 0)
        except ValueError:
            return 0

    def _all_lines(self, key: str) -> list[str]:
        p = self._events_path(key)
        return p.read_text(encoding="utf-8").splitlines() if p.is_file() else []

    def _write_cursor(self, key: str, value: int) -> None:
        path = self._cursor_path(key)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(str(value), encoding="utf-8")
            os.replace(tmp, path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                tmp.unlink()

    # --- Hub consumer: peek + explicit ack (crash-safe at-least-once) ---------

    def peek(self, key: str) -> list[dict]:
        """Return all unread rows without consuming them for Hub reconciliation."""
        cur = self._read_cursor(key)
        lines = self._all_lines(key)
        return [json.loads(line) for line in lines[cur:] if line.strip()]

    def peek_one(self, key: str) -> dict | None:
        """Next unread event WITHOUT advancing the cursor (skips blanks)."""
        cur = self._read_cursor(key)
        lines = self._all_lines(key)
        while cur < len(lines):
            if lines[cur].strip():
                return json.loads(lines[cur])
            cur += 1
        return None

    def ack_one(self, key: str) -> None:
        """Advance the cursor past ONE consumed event (the peeked one), skipping
        leading blanks. Call only AFTER its effects are durably persisted."""
        cur = self._read_cursor(key)
        lines = self._all_lines(key)
        while cur < len(lines):
            blank = not lines[cur].strip()
            cur += 1
            if not blank:
                break
        self._write_cursor(key, cur)

    def was_consumed(self, key: str, message_id: str) -> bool:
        """Return whether ``message_id`` is already before the cursor.

        This is an internal crash-recovery seam for a consumer that advanced
        the cursor but died before writing its own acknowledgement receipt.
        It never mutates Inbox state and does not expose consumed payloads.
        """
        if not isinstance(message_id, str) or not message_id:
            return False
        cursor = self._read_cursor(key)
        for line in self._all_lines(key)[:cursor]:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("id") == message_id:
                return True
        return False

    def wait(self, key: str, timeout: float) -> bool:
        """Block up to `timeout`s until ≥1 unread event is ready, WITHOUT
        consuming it. Returns True if ready, False on timeout. The Hub blocks
        here, then drains via peek_one/ack_one."""
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            if self.peek_one(key) is not None:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(self.poll_tick, remaining))
