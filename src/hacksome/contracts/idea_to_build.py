"""Strict JSON contract for the manual Ideation-to-Build handoff."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping


_FIELDS = frozenset(
    {
        "source_run_id",
        "idea_card_id",
        "idea_card_sha256",
        "challenge_markdown",
        "initial_idea_card_markdown",
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class IdeaToBuildHandoffError(ValueError):
    """An Ideation handoff is malformed or no longer matches its Idea Card."""


@dataclass(frozen=True, slots=True)
class IdeaToBuildHandoff:
    source_run_id: str
    idea_card_id: str
    idea_card_sha256: str
    challenge_markdown: str
    initial_idea_card_markdown: str

    def __post_init__(self) -> None:
        for name in ("source_run_id", "idea_card_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise IdeaToBuildHandoffError(f"{name} must be non-empty")
        if not isinstance(self.idea_card_sha256, str) or not _SHA256.fullmatch(
            self.idea_card_sha256
        ):
            raise IdeaToBuildHandoffError("idea_card_sha256 must be lowercase SHA-256")
        for name in ("challenge_markdown", "initial_idea_card_markdown"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise IdeaToBuildHandoffError(f"{name} must be non-empty Markdown")
        actual = sha256(self.initial_idea_card_markdown.encode("utf-8")).hexdigest()
        if actual != self.idea_card_sha256:
            raise IdeaToBuildHandoffError("Idea Card hash does not match handoff bytes")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> IdeaToBuildHandoff:
        if not isinstance(value, Mapping):
            raise IdeaToBuildHandoffError("handoff must be a JSON object")
        keys = frozenset(value)
        missing = _FIELDS - keys
        extra = keys - _FIELDS
        if missing:
            raise IdeaToBuildHandoffError(
                f"handoff is missing fields: {sorted(missing)}"
            )
        if extra:
            raise IdeaToBuildHandoffError(
                f"handoff has unknown fields: {sorted(extra)}"
            )
        return cls(**{name: value[name] for name in _FIELDS})

    @classmethod
    def from_json_file(cls, path: str | Path) -> IdeaToBuildHandoff:
        source = Path(path)
        if source.is_symlink() or not source.is_file():
            raise IdeaToBuildHandoffError(f"handoff file is missing: {source}")
        try:
            value = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise IdeaToBuildHandoffError(f"handoff JSON is invalid: {exc}") from exc
        return cls.from_mapping(value)

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @property
    def identity(self) -> str:
        """Stable cross-run identity used by a Build-side adapter."""

        return ":".join(
            (self.source_run_id, self.idea_card_id, self.idea_card_sha256)
        )
