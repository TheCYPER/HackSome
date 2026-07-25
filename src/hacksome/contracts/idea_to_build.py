"""Strict JSON contract for the manual Ideation-to-Build handoff."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping


IDEA_TO_BUILD_FIELDS = frozenset(
    {
        "source_run_id",
        "idea_card_id",
        "idea_card_sha256",
        "challenge_markdown",
        "initial_idea_card_markdown",
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_ID_CHARS = 256
_MAX_MARKDOWN_BYTES = 8 * 1024 * 1024


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
            if (
                not isinstance(value, str)
                or not value.strip()
                or "\x00" in value
                or len(value) > _MAX_ID_CHARS
            ):
                raise IdeaToBuildHandoffError(f"{name} must be non-empty")
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise IdeaToBuildHandoffError(
                    f"{name} must be UTF-8 text"
                ) from exc
        if not isinstance(self.idea_card_sha256, str) or not _SHA256.fullmatch(
            self.idea_card_sha256
        ):
            raise IdeaToBuildHandoffError("idea_card_sha256 must be lowercase SHA-256")
        for name in ("challenge_markdown", "initial_idea_card_markdown"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value.strip()
                or "\x00" in value
            ):
                raise IdeaToBuildHandoffError(f"{name} must be non-empty Markdown")
            try:
                encoded = value.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise IdeaToBuildHandoffError(
                    f"{name} must be UTF-8 Markdown"
                ) from exc
            if len(encoded) > _MAX_MARKDOWN_BYTES:
                raise IdeaToBuildHandoffError(f"{name} is too large")
        actual = sha256(self.initial_idea_card_markdown.encode("utf-8")).hexdigest()
        if actual != self.idea_card_sha256:
            raise IdeaToBuildHandoffError("Idea Card hash does not match handoff bytes")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> IdeaToBuildHandoff:
        if not isinstance(value, Mapping):
            raise IdeaToBuildHandoffError("handoff must be a JSON object")
        keys = frozenset(value)
        missing = IDEA_TO_BUILD_FIELDS - keys
        extra = keys - IDEA_TO_BUILD_FIELDS
        if missing:
            raise IdeaToBuildHandoffError(
                f"handoff is missing fields: {sorted(missing)}"
            )
        if extra:
            raise IdeaToBuildHandoffError(
                f"handoff has unknown fields: {sorted(extra)}"
            )
        return cls(**{name: value[name] for name in IDEA_TO_BUILD_FIELDS})

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

    def to_mapping(self) -> dict[str, str]:
        """Return the canonical JSON object used at the process boundary."""

        return self.to_dict()

    @property
    def identity(self) -> str:
        """Stable cross-run identity used by a Build-side adapter."""

        return ":".join(
            (self.source_run_id, self.idea_card_id, self.idea_card_sha256)
        )


__all__ = [
    "IDEA_TO_BUILD_FIELDS",
    "IdeaToBuildHandoff",
    "IdeaToBuildHandoffError",
]
