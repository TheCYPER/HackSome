"""Canonical bounded reflection checkpoint for one Build Team Lead.

The Markdown body is untrusted, derived orientation data.  This module owns
its validation, persisted representation, runtime projection, freshness, and
metadata-only audit events so no caller needs to parse the format itself.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped]

from hacksome.stages.build.control.runtime_store import (
    StoreError,
    append_jsonl,
    atomic_write_json,
    atomic_write_text,
    file_lock,
    read_json,
    read_jsonl,
)

LEAD_BRIEF_SCHEMA_VERSION = 1
LEAD_BRIEF_MAX_BYTES = 8 * 1024
LEAD_BRIEF_PROJECTION_MAX_BYTES = 12 * 1024
LEAD_BRIEF_MAX_EVIDENCE_REFS = 8
LEAD_BRIEF_MAX_EVIDENCE_REF_BYTES = 256
LEAD_BRIEF_REQUIRED_SECTIONS = (
    "Product Model",
    "Verified State",
    "Decisions",
    "Invariants and Risks",
    "Open Hypotheses",
    "Next Checks",
    "Lessons",
)
LEAD_BRIEF_NO_OP_REASONS = frozenset({"no_material_change"})

_WAKE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SECTION_HEADING = re.compile(r"^## ([^\r\n]+)[ \t]*$", re.MULTILINE)
_FRONTMATTER_FIELDS = frozenset(
    {
        "schema_version",
        "revision",
        "updated_at",
        "source_wake_id",
        "observed_goal_seq",
        "current_goal_seq",
        "goal_state_sha256",
        "content_sha256",
        "content_bytes",
        "evidence_refs",
    }
)
_FRESHNESS_MARKER = "\n## Freshness\n\n"

logger = logging.getLogger(__name__)


class LeadBriefError(ValueError):
    """Deterministic validation, conflict, or persistence failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def parse_lead_reflection_memory_enabled(value: str | None) -> bool:
    """Parse the rollout flag without accepting truthy spelling variants."""

    if value in (None, "", "0"):
        return False
    if value == "1":
        return True
    raise LeadBriefError(
        "invalid_feature_flag",
        "LEAD_REFLECTION_MEMORY_ENABLED must be 0 or 1",
    )


def _nonnegative_int(
    value: object,
    *,
    label: str,
    code: str = "invalid_payload",
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LeadBriefError(code, f"{label} must be a non-negative integer")
    return value


def _positive_int(value: object, *, label: str) -> int:
    result = _nonnegative_int(value, label=label, code="store_corrupt")
    if result == 0:
        raise LeadBriefError("store_corrupt", f"{label} must be positive")
    return result


def _validated_wake_id(value: object) -> str:
    if not isinstance(value, str) or not _WAKE_ID.fullmatch(value):
        raise LeadBriefError("invalid_payload", f"invalid wake_id: {value!r}")
    return value


def _validated_sha256(
    value: object, *, label: str, code: str = "invalid_payload"
) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise LeadBriefError(code, f"{label} must be a lowercase SHA-256 digest")
    return value


def _normalize_markdown(value: object) -> str:
    if not isinstance(value, str):
        raise LeadBriefError("invalid_markdown", "markdown must be text")
    if "\x00" in value:
        raise LeadBriefError("invalid_markdown", "markdown contains a NUL byte")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise LeadBriefError(
            "invalid_markdown", "markdown is not valid UTF-8 text"
        ) from exc

    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"
    encoded = normalized.encode("utf-8")
    if len(encoded) > LEAD_BRIEF_MAX_BYTES:
        raise LeadBriefError(
            "brief_too_large",
            f"markdown exceeds {LEAD_BRIEF_MAX_BYTES} UTF-8 bytes",
        )
    headings = _SECTION_HEADING.findall(normalized)
    if tuple(headings) != LEAD_BRIEF_REQUIRED_SECTIONS:
        raise LeadBriefError(
            "invalid_sections",
            "markdown must contain exactly the seven required level-two sections in order",
        )
    if not normalized.startswith(f"## {LEAD_BRIEF_REQUIRED_SECTIONS[0]}\n"):
        raise LeadBriefError(
            "invalid_sections", "markdown must start with Product Model"
        )
    for index, section in enumerate(LEAD_BRIEF_REQUIRED_SECTIONS):
        heading = f"## {section}\n"
        start = normalized.index(heading) + len(heading)
        if index + 1 < len(LEAD_BRIEF_REQUIRED_SECTIONS):
            end = normalized.index(
                f"## {LEAD_BRIEF_REQUIRED_SECTIONS[index + 1]}\n",
                start,
            )
        else:
            end = len(normalized)
        if not normalized[start:end].strip():
            raise LeadBriefError(
                "invalid_sections",
                f"section {section!r} must not be empty",
            )
    return normalized


def _normalize_evidence_refs(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise LeadBriefError("invalid_evidence", "evidence_refs must be an array")
    if not value or len(value) > LEAD_BRIEF_MAX_EVIDENCE_REFS:
        raise LeadBriefError(
            "invalid_evidence",
            f"evidence_refs must contain 1-{LEAD_BRIEF_MAX_EVIDENCE_REFS} entries",
        )
    refs: list[str] = []
    for item in value:
        if (
            not isinstance(item, str)
            or not item
            or item != item.strip()
            or "\x00" in item
            or "\n" in item
            or "\r" in item
        ):
            raise LeadBriefError(
                "invalid_evidence",
                "each evidence reference must be one trimmed line of text",
            )
        try:
            encoded = item.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise LeadBriefError(
                "invalid_evidence",
                "evidence reference is not valid UTF-8 text",
            ) from exc
        if len(encoded) > LEAD_BRIEF_MAX_EVIDENCE_REF_BYTES:
            raise LeadBriefError(
                "invalid_evidence",
                f"evidence reference exceeds {LEAD_BRIEF_MAX_EVIDENCE_REF_BYTES} UTF-8 bytes",
            )
        refs.append(item)
    return tuple(refs)


@dataclass(frozen=True)
class LeadBriefCheckpointRequest:
    action: Literal["replace", "no_op"]
    wake_id: str
    base_revision: int
    observed_goal_seq: int
    markdown: str | None = None
    evidence_refs: tuple[str, ...] = ()
    reason: str | None = None

    @classmethod
    def from_payload(cls, payload: object) -> LeadBriefCheckpointRequest:
        if not isinstance(payload, dict):
            raise LeadBriefError(
                "invalid_payload", "checkpoint payload must be an object"
            )
        action = payload.get("action")
        common = {"action", "wake_id", "base_revision", "observed_goal_seq"}
        if action == "replace":
            expected = common | {"markdown", "evidence_refs"}
        elif action == "no_op":
            expected = common | {"reason"}
        else:
            raise LeadBriefError(
                "invalid_payload",
                "action must be 'replace' or 'no_op'",
            )
        missing = expected - set(payload)
        extra = set(payload) - expected
        if missing:
            raise LeadBriefError(
                "invalid_payload",
                f"missing checkpoint fields: {sorted(missing)}",
            )
        if extra:
            raise LeadBriefError(
                "invalid_payload",
                f"unknown checkpoint fields: {sorted(extra)}",
            )

        wake_id = _validated_wake_id(payload["wake_id"])
        base_revision = _nonnegative_int(
            payload["base_revision"], label="base_revision"
        )
        observed_goal_seq = _nonnegative_int(
            payload["observed_goal_seq"],
            label="observed_goal_seq",
        )
        if action == "replace":
            return cls(
                action="replace",
                wake_id=wake_id,
                base_revision=base_revision,
                observed_goal_seq=observed_goal_seq,
                markdown=_normalize_markdown(payload["markdown"]),
                evidence_refs=_normalize_evidence_refs(payload["evidence_refs"]),
            )
        reason = payload["reason"]
        if reason not in LEAD_BRIEF_NO_OP_REASONS:
            raise LeadBriefError(
                "invalid_payload",
                f"reason must be one of {sorted(LEAD_BRIEF_NO_OP_REASONS)}",
            )
        return cls(
            action="no_op",
            wake_id=wake_id,
            base_revision=base_revision,
            observed_goal_seq=observed_goal_seq,
            reason=reason,
        )


def canonical_goal_state(goals: Sequence[Mapping[str, object]]) -> tuple[int, str]:
    """Return the latest Goal sequence and a stable hash of canonical projections."""

    rows = [dict(goal) for goal in goals]
    try:
        rows.sort(
            key=lambda row: (
                _nonnegative_int(row.get("enqueue_seq"), label="enqueue_seq"),
                str(row.get("id", "")),
            )
        )
        current_goal_seq = max(
            (
                _nonnegative_int(row.get("enqueue_seq"), label="enqueue_seq")
                for row in rows
            ),
            default=0,
        )
        serialized = json.dumps(
            rows,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        if isinstance(exc, LeadBriefError):
            raise
        raise LeadBriefError(
            "invalid_goal_state",
            "canonical Goal projections are not serializable",
        ) from exc
    return current_goal_seq, hashlib.sha256(serialized).hexdigest()


def _safe_text_metadata(value: object) -> dict[str, object]:
    if not isinstance(value, str):
        return {"redacted": True, "content_bytes": None, "content_sha256": None}
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return {"redacted": True, "content_bytes": None, "content_sha256": None}
    return {
        "redacted": True,
        "content_bytes": len(encoded),
        "content_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def redact_checkpoint_audit_request(value: object) -> object:
    """Remove submitted Markdown from parsed or malformed method audit rows."""

    if not isinstance(value, dict):
        return {"redacted": True}
    redacted = dict(value)
    payload = redacted.get("payload")
    if isinstance(payload, dict):
        payload = dict(payload)
        if "markdown" in payload:
            payload["markdown"] = _safe_text_metadata(payload["markdown"])
        redacted["payload"] = payload
    return redacted


def _redacted_projection(value: object) -> object:
    if not isinstance(value, dict):
        return {"redacted": True}
    redacted = dict(value)
    if "markdown" in redacted:
        redacted["markdown"] = _safe_text_metadata(redacted["markdown"])
    return redacted


def redact_lead_brief_audit_result(value: object) -> object:
    """Remove injected/read Markdown while preserving useful audit metadata."""

    if not isinstance(value, dict):
        return {"redacted": True}
    redacted = dict(value)
    if "lead_brief" in redacted:
        redacted["lead_brief"] = _redacted_projection(redacted["lead_brief"])
        return redacted
    return _redacted_projection(redacted)


@dataclass(frozen=True)
class _StoredBrief:
    revision: int
    updated_at: str
    source_wake_id: str
    observed_goal_seq: int
    current_goal_seq: int
    goal_state_sha256: str
    content_sha256: str
    content_bytes: int
    evidence_refs: tuple[str, ...]
    markdown: str


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _render_document(
    stored: _StoredBrief,
    *,
    current_goal_seq: int,
    stale: bool,
) -> str:
    evidence = "\n".join(f"  - {ref}" for ref in stored.evidence_refs)
    frontmatter = "\n".join(
        (
            "---",
            f"schema_version: {LEAD_BRIEF_SCHEMA_VERSION}",
            f"revision: {stored.revision}",
            f"updated_at: {json.dumps(stored.updated_at, ensure_ascii=False)}",
            f"source_wake_id: {json.dumps(stored.source_wake_id, ensure_ascii=False)}",
            f"observed_goal_seq: {stored.observed_goal_seq}",
            f"current_goal_seq: {current_goal_seq}",
            f"goal_state_sha256: {json.dumps(stored.goal_state_sha256)}",
            f"content_sha256: {json.dumps(stored.content_sha256)}",
            f"content_bytes: {stored.content_bytes}",
            "evidence_refs: "
            + json.dumps(list(stored.evidence_refs), ensure_ascii=False),
            "---",
            "",
        )
    )
    freshness = (
        "## Freshness\n\n"
        f"- status: {'stale' if stale else 'current'}\n"
        f"- observed_goal_seq: {stored.observed_goal_seq}\n"
        f"- current_goal_seq: {current_goal_seq}\n"
        f"- goal_state_sha256: {stored.goal_state_sha256}\n"
        f"- updated_at: {stored.updated_at}\n"
        "- evidence:\n"
        f"{evidence}\n"
    )
    rendered = frontmatter + stored.markdown + "\n" + freshness
    if len(rendered.encode("utf-8")) > LEAD_BRIEF_PROJECTION_MAX_BYTES:
        raise LeadBriefError(
            "store_corrupt",
            "rendered Lead brief exceeds its projection bound",
        )
    return rendered


class LeadBriefStore:
    """Atomic current snapshot plus metadata-only events for one Team."""

    def __init__(self, root: str | Path, *, team_id: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        if (
            not isinstance(team_id, str)
            or not team_id
            or "\x00" in team_id
            or "\n" in team_id
            or "\r" in team_id
        ):
            raise LeadBriefError("invalid_team", "team_id must be one line of text")
        self.team_id = team_id
        self.snapshot_path = self.root / "lead-brief.md"
        self.events_path = self.root / "events.jsonl"
        self.checkpoints_root = self.root / "checkpoints"
        self.lock_path = self.root / ".lead-brief.lock"

    @staticmethod
    def disabled_projection() -> dict[str, object]:
        return {"enabled": False}

    @staticmethod
    def _empty_projection(
        *,
        current_goal_seq: int,
        goal_state_sha256: str,
    ) -> dict[str, object]:
        return {
            "enabled": True,
            "schema_version": LEAD_BRIEF_SCHEMA_VERSION,
            "revision": 0,
            "markdown": None,
            "content_bytes": 0,
            "content_sha256": None,
            "observed_goal_seq": 0,
            "current_goal_seq": current_goal_seq,
            "goal_state_sha256": goal_state_sha256,
            "stale": False,
            "updated_at": None,
            "source_wake_id": None,
        }

    def _load_current(self) -> _StoredBrief | None:
        if not self.snapshot_path.is_file():
            return None
        try:
            text = self.snapshot_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise LeadBriefError(
                "store_corrupt",
                "Lead brief snapshot is unreadable",
            ) from exc
        if not text.startswith("---\n"):
            raise LeadBriefError("store_corrupt", "Lead brief frontmatter is missing")
        boundary = text.find("\n---\n", 4)
        if boundary < 0:
            raise LeadBriefError(
                "store_corrupt", "Lead brief frontmatter is incomplete"
            )
        try:
            metadata = yaml.safe_load(text[4:boundary])
        except yaml.YAMLError as exc:
            raise LeadBriefError(
                "store_corrupt", "Lead brief frontmatter is invalid"
            ) from exc
        if not isinstance(metadata, dict) or set(metadata) != _FRONTMATTER_FIELDS:
            raise LeadBriefError(
                "store_corrupt",
                "Lead brief frontmatter fields do not match schema version 1",
            )
        body = text[boundary + len("\n---\n") :]
        if _FRESHNESS_MARKER not in body:
            raise LeadBriefError(
                "store_corrupt", "Lead brief freshness section is missing"
            )
        submitted, _freshness = body.rsplit(_FRESHNESS_MARKER, 1)
        try:
            markdown = _normalize_markdown(submitted)
        except LeadBriefError as exc:
            raise LeadBriefError("store_corrupt", str(exc)) from exc
        content = markdown.encode("utf-8")

        if metadata.get("schema_version") != LEAD_BRIEF_SCHEMA_VERSION:
            raise LeadBriefError(
                "store_corrupt", "unsupported Lead brief schema version"
            )
        revision = _positive_int(metadata.get("revision"), label="revision")
        updated_at = metadata.get("updated_at")
        if not isinstance(updated_at, str):
            raise LeadBriefError("store_corrupt", "updated_at must be text")
        try:
            parsed_time = datetime.fromisoformat(updated_at)
        except ValueError as exc:
            raise LeadBriefError("store_corrupt", "updated_at is invalid") from exc
        if parsed_time.tzinfo is None:
            raise LeadBriefError("store_corrupt", "updated_at must include a timezone")
        try:
            source_wake_id = _validated_wake_id(metadata.get("source_wake_id"))
        except LeadBriefError as exc:
            raise LeadBriefError("store_corrupt", str(exc)) from exc
        observed_goal_seq = _nonnegative_int(
            metadata.get("observed_goal_seq"),
            label="observed_goal_seq",
            code="store_corrupt",
        )
        current_goal_seq = _nonnegative_int(
            metadata.get("current_goal_seq"),
            label="current_goal_seq",
            code="store_corrupt",
        )
        try:
            goal_state_sha256 = _validated_sha256(
                metadata.get("goal_state_sha256"),
                label="goal_state_sha256",
                code="store_corrupt",
            )
            content_sha256 = _validated_sha256(
                metadata.get("content_sha256"),
                label="content_sha256",
                code="store_corrupt",
            )
        except LeadBriefError as exc:
            raise LeadBriefError("store_corrupt", str(exc)) from exc
        content_bytes = _nonnegative_int(
            metadata.get("content_bytes"),
            label="content_bytes",
            code="store_corrupt",
        )
        try:
            evidence_refs = _normalize_evidence_refs(metadata.get("evidence_refs"))
        except LeadBriefError as exc:
            raise LeadBriefError("store_corrupt", str(exc)) from exc
        if current_goal_seq != observed_goal_seq:
            raise LeadBriefError(
                "store_corrupt",
                "stored Goal sequence was stale at replace time",
            )
        if content_bytes != len(content):
            raise LeadBriefError("store_corrupt", "content byte count does not match")
        if content_sha256 != hashlib.sha256(content).hexdigest():
            raise LeadBriefError("store_corrupt", "content digest does not match")
        stored = _StoredBrief(
            revision=revision,
            updated_at=updated_at,
            source_wake_id=source_wake_id,
            observed_goal_seq=observed_goal_seq,
            current_goal_seq=current_goal_seq,
            goal_state_sha256=goal_state_sha256,
            content_sha256=content_sha256,
            content_bytes=content_bytes,
            evidence_refs=evidence_refs,
            markdown=markdown,
        )
        if text != _render_document(
            stored,
            current_goal_seq=stored.current_goal_seq,
            stale=False,
        ):
            raise LeadBriefError(
                "store_corrupt", "Lead brief is not canonically encoded"
            )
        return stored

    def _event(
        self,
        *,
        action: str,
        wake_id: str | None,
        revision: int,
        content_bytes: int,
        content_sha256: str | None,
        observed_goal_seq: int,
        current_goal_seq: int,
        goal_state_sha256: str,
        stale: bool,
        error_code: str | None = None,
        reason: str | None = None,
    ) -> dict[str, object]:
        return {
            "time": _utc_now(),
            "team_id": self.team_id,
            "wake_id": wake_id,
            "action": action,
            "revision": revision,
            "content_bytes": content_bytes,
            "content_sha256": content_sha256,
            "observed_goal_seq": observed_goal_seq,
            "current_goal_seq": current_goal_seq,
            "goal_state_sha256": goal_state_sha256,
            "stale": stale,
            "error_code": error_code,
            "reason": reason,
        }

    def _append_event_best_effort(self, event: dict[str, object]) -> None:
        try:
            append_jsonl(self.events_path, event)
        except Exception as exc:  # noqa: BLE001 - telemetry never changes checkpoint truth
            logger.warning(
                "Lead brief event write failed for team=%s action=%s error=%s",
                self.team_id,
                event.get("action"),
                type(exc).__name__,
            )

    def _checkpoint_receipt_path(self, wake_id: str) -> Path:
        digest = hashlib.sha256(wake_id.encode("utf-8")).hexdigest()
        return self.checkpoints_root / f"{digest}.json"

    def _read_checkpoint_receipt(self, wake_id: str) -> dict[str, object] | None:
        try:
            receipt = read_json(self._checkpoint_receipt_path(wake_id))
        except StoreError as exc:
            raise LeadBriefError(
                "store_corrupt",
                "Lead brief checkpoint receipt is invalid",
            ) from exc
        if receipt is None:
            return None
        if (
            not isinstance(receipt, dict)
            or set(receipt) != {"schema_version", "wake_id", "action", "revision"}
            or receipt.get("schema_version") != LEAD_BRIEF_SCHEMA_VERSION
            or receipt.get("wake_id") != wake_id
            or receipt.get("action") not in {"replace", "no_op", "missing"}
        ):
            raise LeadBriefError(
                "store_corrupt",
                "Lead brief checkpoint receipt does not match schema version 1",
            )
        _nonnegative_int(
            receipt.get("revision"),
            label="revision",
            code="store_corrupt",
        )
        return receipt

    def _write_checkpoint_receipt(
        self,
        *,
        wake_id: str,
        action: Literal["replace", "no_op", "missing"],
        revision: int,
        required: bool,
    ) -> bool:
        receipt = {
            "schema_version": LEAD_BRIEF_SCHEMA_VERSION,
            "wake_id": wake_id,
            "action": action,
            "revision": revision,
        }
        try:
            atomic_write_json(self._checkpoint_receipt_path(wake_id), receipt)
        except OSError as exc:
            if required:
                raise LeadBriefError(
                    "write_failed",
                    "could not persist the Lead brief checkpoint receipt",
                ) from exc
            logger.warning(
                "Lead brief receipt write failed for team=%s wake=%s action=%s",
                self.team_id,
                wake_id,
                action,
            )
            return False
        return True

    def _ensure_snapshot_receipt(self, stored: _StoredBrief | None) -> None:
        """Backfill the current replace receipt before its snapshot is superseded."""

        if (
            stored is not None
            and self._read_checkpoint_receipt(stored.source_wake_id) is None
        ):
            self._write_checkpoint_receipt(
                wake_id=stored.source_wake_id,
                action="replace",
                revision=stored.revision,
                required=True,
            )

    def _projection(
        self,
        stored: _StoredBrief,
        *,
        current_goal_seq: int,
        goal_state_sha256: str,
    ) -> dict[str, object]:
        stale = (
            stored.current_goal_seq != current_goal_seq
            or stored.goal_state_sha256 != goal_state_sha256
        )
        return {
            "enabled": True,
            "schema_version": LEAD_BRIEF_SCHEMA_VERSION,
            "revision": stored.revision,
            "markdown": _render_document(
                stored,
                current_goal_seq=current_goal_seq,
                stale=stale,
            ),
            "content_bytes": stored.content_bytes,
            "content_sha256": stored.content_sha256,
            "observed_goal_seq": stored.observed_goal_seq,
            "current_goal_seq": current_goal_seq,
            "goal_state_sha256": stored.goal_state_sha256,
            "stale": stale,
            "updated_at": stored.updated_at,
            "source_wake_id": stored.source_wake_id,
        }

    def read(
        self,
        *,
        current_goal_seq: int,
        goal_state_sha256: str,
        enabled: bool,
    ) -> dict[str, object]:
        if not enabled:
            return self.disabled_projection()
        current_goal_seq = _nonnegative_int(
            current_goal_seq,
            label="current_goal_seq",
        )
        goal_state_sha256 = _validated_sha256(
            goal_state_sha256,
            label="goal_state_sha256",
        )
        with file_lock(self.lock_path):
            stored = self._load_current()
            projection = (
                self._empty_projection(
                    current_goal_seq=current_goal_seq,
                    goal_state_sha256=goal_state_sha256,
                )
                if stored is None
                else self._projection(
                    stored,
                    current_goal_seq=current_goal_seq,
                    goal_state_sha256=goal_state_sha256,
                )
            )
            if stored is None:
                revision = 0
                content_bytes = 0
                content_sha256 = None
                observed_goal_seq = 0
            else:
                revision = stored.revision
                content_bytes = stored.content_bytes
                content_sha256 = stored.content_sha256
                observed_goal_seq = stored.observed_goal_seq
            self._append_event_best_effort(
                self._event(
                    action="stale" if projection["stale"] else "read",
                    wake_id=None,
                    revision=revision,
                    content_bytes=content_bytes,
                    content_sha256=content_sha256,
                    observed_goal_seq=observed_goal_seq,
                    current_goal_seq=current_goal_seq,
                    goal_state_sha256=goal_state_sha256,
                    stale=bool(projection["stale"]),
                )
            )
            return projection

    def checkpoint(
        self,
        request: LeadBriefCheckpointRequest,
        *,
        current_goal_seq: int,
        goal_state_sha256: str,
    ) -> dict[str, object]:
        current_goal_seq = _nonnegative_int(
            current_goal_seq,
            label="current_goal_seq",
        )
        goal_state_sha256 = _validated_sha256(
            goal_state_sha256,
            label="goal_state_sha256",
        )
        try:
            return self._checkpoint(
                request,
                current_goal_seq=current_goal_seq,
                goal_state_sha256=goal_state_sha256,
            )
        except LeadBriefError as exc:
            content_bytes = (
                len(request.markdown.encode("utf-8"))
                if isinstance(request.markdown, str)
                else 0
            )
            content_sha256 = (
                hashlib.sha256(request.markdown.encode("utf-8")).hexdigest()
                if isinstance(request.markdown, str)
                else None
            )
            if exc.code != "store_corrupt":
                with file_lock(self.lock_path):
                    self._append_event_best_effort(
                        self._event(
                            action="error",
                            wake_id=request.wake_id,
                            revision=request.base_revision,
                            content_bytes=content_bytes,
                            content_sha256=content_sha256,
                            observed_goal_seq=request.observed_goal_seq,
                            current_goal_seq=current_goal_seq,
                            goal_state_sha256=goal_state_sha256,
                            stale=request.observed_goal_seq != current_goal_seq,
                            error_code=exc.code,
                            reason=request.reason,
                        )
                    )
            else:
                logger.warning(
                    "Lead brief store is corrupt for team=%s; error event skipped",
                    self.team_id,
                )
            raise

    def _checkpoint(
        self,
        request: LeadBriefCheckpointRequest,
        *,
        current_goal_seq: int,
        goal_state_sha256: str,
    ) -> dict[str, object]:
        with file_lock(self.lock_path):
            stored = self._load_current()
            current_revision = stored.revision if stored is not None else 0
            self._ensure_snapshot_receipt(stored)
            if self._read_checkpoint_receipt(request.wake_id) is not None:
                raise LeadBriefError(
                    "wake_already_checkpointed",
                    "this wake already has a Lead brief checkpoint",
                )
            try:
                events = read_jsonl(self.events_path)
            except StoreError as exc:
                raise LeadBriefError(
                    "store_corrupt",
                    "Lead brief event journal is invalid",
                ) from exc
            if (stored is not None and stored.source_wake_id == request.wake_id) or any(
                event.get("wake_id") == request.wake_id
                and event.get("action") in {"replace", "no_op", "missing"}
                for event in events
            ):
                raise LeadBriefError(
                    "wake_already_checkpointed",
                    "this wake already has a Lead brief checkpoint",
                )
            if request.base_revision != current_revision:
                raise LeadBriefError(
                    "revision_conflict",
                    f"base_revision {request.base_revision} does not match {current_revision}",
                )
            if request.observed_goal_seq != current_goal_seq:
                raise LeadBriefError(
                    "stale_goal_state",
                    "observed_goal_seq is stale; reread and inspect live state",
                )

            if request.action == "replace":
                assert request.markdown is not None
                content = request.markdown.encode("utf-8")
                replacement = _StoredBrief(
                    revision=current_revision + 1,
                    updated_at=_utc_now(),
                    source_wake_id=request.wake_id,
                    observed_goal_seq=request.observed_goal_seq,
                    current_goal_seq=current_goal_seq,
                    goal_state_sha256=goal_state_sha256,
                    content_sha256=hashlib.sha256(content).hexdigest(),
                    content_bytes=len(content),
                    evidence_refs=request.evidence_refs,
                    markdown=request.markdown,
                )
                try:
                    atomic_write_text(
                        self.snapshot_path,
                        _render_document(
                            replacement,
                            current_goal_seq=current_goal_seq,
                            stale=False,
                        ),
                    )
                except OSError as exc:
                    raise LeadBriefError(
                        "write_failed",
                        "could not atomically replace the Lead brief",
                    ) from exc
                stored = replacement
                stale = False
            else:
                stale = stored is not None and (
                    stored.current_goal_seq != current_goal_seq
                    or stored.goal_state_sha256 != goal_state_sha256
                )

            revision = stored.revision if stored is not None else 0
            content_bytes = stored.content_bytes if stored is not None else 0
            content_sha256 = stored.content_sha256 if stored is not None else None
            self._write_checkpoint_receipt(
                wake_id=request.wake_id,
                action=request.action,
                revision=revision,
                required=request.action == "no_op",
            )
            self._append_event_best_effort(
                self._event(
                    action=request.action,
                    wake_id=request.wake_id,
                    revision=revision,
                    content_bytes=content_bytes,
                    content_sha256=content_sha256,
                    observed_goal_seq=request.observed_goal_seq,
                    current_goal_seq=current_goal_seq,
                    goal_state_sha256=goal_state_sha256,
                    stale=stale,
                    reason=request.reason,
                )
            )
            return {
                "action": request.action,
                "revision": revision,
                "content_bytes": content_bytes,
                "content_sha256": content_sha256,
                "stale": stale,
                "observed_goal_seq": request.observed_goal_seq,
                "current_goal_seq": current_goal_seq,
                "goal_state_sha256": goal_state_sha256,
            }

    def record_wake_completion(
        self,
        wake_id: str,
        *,
        current_goal_seq: int,
        goal_state_sha256: str,
    ) -> dict[str, object]:
        wake_id = _validated_wake_id(wake_id)
        current_goal_seq = _nonnegative_int(
            current_goal_seq,
            label="current_goal_seq",
        )
        goal_state_sha256 = _validated_sha256(
            goal_state_sha256,
            label="goal_state_sha256",
        )
        with file_lock(self.lock_path):
            stored = self._load_current()
            self._ensure_snapshot_receipt(stored)
            receipt = self._read_checkpoint_receipt(wake_id)
            if receipt is not None:
                return {
                    "action": receipt["action"],
                    "revision": receipt["revision"],
                }
            try:
                events = read_jsonl(self.events_path)
            except StoreError as exc:
                raise LeadBriefError(
                    "store_corrupt",
                    "Lead brief event journal is invalid",
                ) from exc
            for event in reversed(events):
                if event.get("wake_id") == wake_id and event.get("action") in {
                    "replace",
                    "no_op",
                    "missing",
                }:
                    revision = _nonnegative_int(
                        event.get("revision"),
                        label="revision",
                        code="store_corrupt",
                    )
                    self._write_checkpoint_receipt(
                        wake_id=wake_id,
                        action=event["action"],
                        revision=revision,
                        required=True,
                    )
                    return {
                        "action": event["action"],
                        "revision": revision,
                    }
            if stored is not None and stored.source_wake_id == wake_id:
                return {"action": "replace", "revision": stored.revision}

            revision = stored.revision if stored is not None else 0
            content_bytes = stored.content_bytes if stored is not None else 0
            content_sha256 = stored.content_sha256 if stored is not None else None
            observed_goal_seq = stored.observed_goal_seq if stored is not None else 0
            stale = stored is not None and (
                stored.current_goal_seq != current_goal_seq
                or stored.goal_state_sha256 != goal_state_sha256
            )
            self._write_checkpoint_receipt(
                wake_id=wake_id,
                action="missing",
                revision=revision,
                required=True,
            )
            self._append_event_best_effort(
                self._event(
                    action="missing",
                    wake_id=wake_id,
                    revision=revision,
                    content_bytes=content_bytes,
                    content_sha256=content_sha256,
                    observed_goal_seq=observed_goal_seq,
                    current_goal_seq=current_goal_seq,
                    goal_state_sha256=goal_state_sha256,
                    stale=stale,
                    error_code="checkpoint_missing",
                )
            )
            return {"action": "missing", "revision": revision}


__all__ = [
    "LEAD_BRIEF_MAX_BYTES",
    "LEAD_BRIEF_MAX_EVIDENCE_REFS",
    "LEAD_BRIEF_MAX_EVIDENCE_REF_BYTES",
    "LEAD_BRIEF_NO_OP_REASONS",
    "LEAD_BRIEF_PROJECTION_MAX_BYTES",
    "LEAD_BRIEF_REQUIRED_SECTIONS",
    "LEAD_BRIEF_SCHEMA_VERSION",
    "LeadBriefCheckpointRequest",
    "LeadBriefError",
    "LeadBriefStore",
    "canonical_goal_state",
    "parse_lead_reflection_memory_enabled",
    "redact_checkpoint_audit_request",
    "redact_lead_brief_audit_result",
]
