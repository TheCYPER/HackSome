"""Strict shared JSON contracts for the post-Idea-Card boundary.

Route adapters are the only readers of route-owned run state.  Approval, HTTP,
CLI, and Build delivery code consume these detached value objects instead of
reinterpreting Useful or Creative fields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping

from hacksome.contracts.idea_to_build import (
    IDEA_TO_BUILD_FIELDS,
    IdeaToBuildHandoff,
    IdeaToBuildHandoffError,
)
from hacksome.stages.ideation.useful.artifacts import ArtifactError, title_of
from hacksome.core.state import normalize_json, sha256_json, sha256_text


CATALOG_SCHEMA_VERSION = 1
HANDOFF_FIELDS = IDEA_TO_BUILD_FIELDS
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROUTE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MAX_ID_CHARS = 256
_MAX_TITLE_CHARS = 1000
_MAX_MARKDOWN_BYTES = 8 * 1024 * 1024


class PostCardContractError(ValueError):
    """A shared catalog or handoff payload violates its exact contract."""


def _exact_object(
    value: Any,
    *,
    fields: frozenset[str],
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PostCardContractError(f"{label} must be an object")
    actual = set(value)
    if actual != fields:
        missing = sorted(fields - actual)
        unknown = sorted(actual - fields)
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown fields: {', '.join(unknown)}")
        raise PostCardContractError(f"{label} has " + "; ".join(details))
    return value


def _string(
    value: Any,
    *,
    label: str,
    allow_empty: bool = False,
    max_chars: int = _MAX_ID_CHARS,
) -> str:
    if not isinstance(value, str):
        raise PostCardContractError(f"{label} must be a string")
    if "\x00" in value:
        raise PostCardContractError(f"{label} contains a NUL byte")
    if not allow_empty and not value.strip():
        raise PostCardContractError(f"{label} must not be empty")
    if len(value) > max_chars:
        raise PostCardContractError(f"{label} is too long")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PostCardContractError(f"{label} is not UTF-8 text") from exc
    return value


def _markdown(value: Any, *, label: str) -> str:
    text = _string(
        value,
        label=label,
        max_chars=_MAX_MARKDOWN_BYTES,
    )
    if len(text.encode("utf-8")) > _MAX_MARKDOWN_BYTES:
        raise PostCardContractError(f"{label} exceeds {_MAX_MARKDOWN_BYTES} bytes")
    return text


def _sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise PostCardContractError(f"{label} must be a lowercase SHA-256")
    return value


def _relative_path(value: Any, *, label: str) -> str:
    text = _string(value, label=label, max_chars=1024)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise PostCardContractError(f"{label} must be a normalized relative path")
    if path.as_posix() != text:
        raise PostCardContractError(f"{label} must use normalized POSIX separators")
    return text


@dataclass(frozen=True, slots=True)
class BuildHandoffV1(IdeaToBuildHandoff):
    """Post-card name for the canonical Ideation-to-Build handoff."""

    @classmethod
    def from_mapping(cls, value: Any) -> "BuildHandoffV1":
        try:
            handoff = IdeaToBuildHandoff.from_mapping(value)
        except IdeaToBuildHandoffError as exc:
            raise PostCardContractError(str(exc)) from exc
        return cls(**handoff.to_mapping())


@dataclass(frozen=True, slots=True)
class ArtifactRefV1:
    artifact_id: str
    artifact_type: str
    relative_path: str

    def __post_init__(self) -> None:
        _string(self.artifact_id, label="artifact_id")
        _string(self.artifact_type, label="artifact_type")
        _relative_path(self.relative_path, label="artifact relative_path")

    @classmethod
    def from_mapping(cls, value: Any) -> "ArtifactRefV1":
        raw = _exact_object(
            value,
            fields=frozenset({"artifact_id", "artifact_type", "relative_path"}),
            label="artifact ref",
        )
        return cls(
            artifact_id=_string(raw["artifact_id"], label="artifact_id"),
            artifact_type=_string(raw["artifact_type"], label="artifact_type"),
            relative_path=_relative_path(
                raw["relative_path"], label="artifact relative_path"
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "relative_path": self.relative_path,
        }


@dataclass(frozen=True, slots=True)
class CatalogSourceV1:
    route_id: str
    route_contract_version: str
    run_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.route_id, str) or not _ROUTE_ID.fullmatch(
            self.route_id
        ):
            raise PostCardContractError("catalog route_id is invalid")
        _string(
            self.route_contract_version,
            label="catalog route_contract_version",
            max_chars=64,
        )
        _string(self.run_id, label="catalog run_id")

    @classmethod
    def from_mapping(cls, value: Any) -> "CatalogSourceV1":
        raw = _exact_object(
            value,
            fields=frozenset(
                {"route_id", "route_contract_version", "run_id"}
            ),
            label="catalog source",
        )
        return cls(
            route_id=_string(raw["route_id"], label="catalog route_id"),
            route_contract_version=_string(
                raw["route_contract_version"],
                label="catalog route_contract_version",
            ),
            run_id=_string(raw["run_id"], label="catalog run_id"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "route_contract_version": self.route_contract_version,
            "run_id": self.run_id,
        }


@dataclass(frozen=True, slots=True)
class PostCardCandidateV1:
    ordinal: int
    card_id: str
    title: str
    card_sha256: str
    card_markdown: str
    source_artifact_ref: ArtifactRefV1
    route_handoff_ref: str | None
    handoff: BuildHandoffV1

    def __post_init__(self) -> None:
        if (
            isinstance(self.ordinal, bool)
            or not isinstance(self.ordinal, int)
            or self.ordinal < 0
        ):
            raise PostCardContractError("candidate ordinal must be non-negative")
        _string(self.card_id, label="candidate card_id")
        _string(
            self.title,
            label="candidate title",
            max_chars=_MAX_TITLE_CHARS,
        )
        _sha256(self.card_sha256, label="candidate card_sha256")
        card = _markdown(self.card_markdown, label="candidate card_markdown")
        if sha256_text(card) != self.card_sha256:
            raise PostCardContractError(
                "candidate card_sha256 does not match exact Card bytes"
            )
        try:
            extracted_title = title_of(card)
        except ArtifactError as exc:
            raise PostCardContractError(str(exc)) from exc
        if extracted_title != self.title:
            raise PostCardContractError(
                "candidate title does not match the Card H1"
            )
        if self.source_artifact_ref.artifact_id != self.card_id:
            raise PostCardContractError(
                "candidate artifact ref does not match card_id"
            )
        if self.route_handoff_ref is not None:
            _string(self.route_handoff_ref, label="candidate route_handoff_ref")
        if (
            self.handoff.source_run_id == ""
            or self.handoff.idea_card_id != self.card_id
            or self.handoff.idea_card_sha256 != self.card_sha256
            or self.handoff.initial_idea_card_markdown != self.card_markdown
        ):
            raise PostCardContractError(
                "candidate handoff is not bound to its exact Card"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PostCardCandidateV1":
        raw = _exact_object(
            value,
            fields=frozenset(
                {
                    "ordinal",
                    "card_id",
                    "title",
                    "card_sha256",
                    "card_markdown",
                    "source_artifact_ref",
                    "route_handoff_ref",
                    "handoff",
                }
            ),
            label="catalog candidate",
        )
        route_handoff_ref = raw["route_handoff_ref"]
        if route_handoff_ref is not None:
            route_handoff_ref = _string(
                route_handoff_ref,
                label="candidate route_handoff_ref",
            )
        return cls(
            ordinal=raw["ordinal"],
            card_id=_string(raw["card_id"], label="candidate card_id"),
            title=_string(
                raw["title"],
                label="candidate title",
                max_chars=_MAX_TITLE_CHARS,
            ),
            card_sha256=_sha256(
                raw["card_sha256"], label="candidate card_sha256"
            ),
            card_markdown=_markdown(
                raw["card_markdown"], label="candidate card_markdown"
            ),
            source_artifact_ref=ArtifactRefV1.from_mapping(
                raw["source_artifact_ref"]
            ),
            route_handoff_ref=route_handoff_ref,
            handoff=BuildHandoffV1.from_mapping(raw["handoff"]),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "card_id": self.card_id,
            "title": self.title,
            "card_sha256": self.card_sha256,
            "card_markdown": self.card_markdown,
            "source_artifact_ref": self.source_artifact_ref.to_mapping(),
            "route_handoff_ref": self.route_handoff_ref,
            "handoff": self.handoff.to_mapping(),
        }


@dataclass(frozen=True, slots=True)
class PostCardCatalogV1:
    schema_version: int
    source: CatalogSourceV1
    cards: tuple[PostCardCandidateV1, ...]
    catalog_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != CATALOG_SCHEMA_VERSION:
            raise PostCardContractError(
                f"unsupported catalog schema version: {self.schema_version!r}"
            )
        if tuple(card.ordinal for card in self.cards) != tuple(
            range(len(self.cards))
        ):
            raise PostCardContractError(
                "catalog candidate ordinals must be contiguous and ordered"
            )
        ids = [card.card_id for card in self.cards]
        if len(ids) != len(set(ids)):
            raise PostCardContractError("catalog contains duplicate Card IDs")
        if any(card.handoff.source_run_id != self.source.run_id for card in self.cards):
            raise PostCardContractError(
                "catalog handoff source_run_id does not match catalog source"
            )
        _sha256(self.catalog_sha256, label="catalog_sha256")
        if self.catalog_sha256 != self.computed_sha256():
            raise PostCardContractError("catalog_sha256 does not match catalog bytes")

    @classmethod
    def build(
        cls,
        *,
        source: CatalogSourceV1,
        cards: tuple[PostCardCandidateV1, ...],
    ) -> "PostCardCatalogV1":
        payload = {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "source": source.to_mapping(),
            "cards": [card.to_mapping() for card in cards],
        }
        return cls(
            schema_version=CATALOG_SCHEMA_VERSION,
            source=source,
            cards=cards,
            catalog_sha256=sha256_json(payload),
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "PostCardCatalogV1":
        raw = _exact_object(
            value,
            fields=frozenset(
                {"schema_version", "source", "cards", "catalog_sha256"}
            ),
            label="post-card catalog",
        )
        cards_value = raw["cards"]
        if not isinstance(cards_value, list):
            raise PostCardContractError("catalog cards must be an array")
        catalog = cls(
            schema_version=raw["schema_version"],
            source=CatalogSourceV1.from_mapping(raw["source"]),
            cards=tuple(
                PostCardCandidateV1.from_mapping(card) for card in cards_value
            ),
            catalog_sha256=_sha256(
                raw["catalog_sha256"], label="catalog_sha256"
            ),
        )
        normalized = normalize_json(
            catalog.to_mapping(), label="post-card catalog"
        )
        if normalized != dict(raw):
            raise PostCardContractError("post-card catalog is not canonical JSON")
        return catalog

    def payload_without_hash(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source.to_mapping(),
            "cards": [card.to_mapping() for card in self.cards],
        }

    def computed_sha256(self) -> str:
        return sha256_json(self.payload_without_hash())

    def to_mapping(self) -> dict[str, Any]:
        return {
            **self.payload_without_hash(),
            "catalog_sha256": self.catalog_sha256,
        }

    def card_by_id(self, card_id: str) -> PostCardCandidateV1:
        for card in self.cards:
            if card.card_id == card_id:
                return card
        raise PostCardContractError(f"unknown Idea Card: {card_id!r}")


def build_identity_sha256(handoff: BuildHandoffV1) -> str:
    """Stable Build identity shared across the serialized process boundary."""

    return sha256_json(
        {
            "source_run_id": handoff.source_run_id,
            "idea_card_id": handoff.idea_card_id,
            "idea_card_sha256": handoff.idea_card_sha256,
        }
    )


def stable_team_id(handoff: BuildHandoffV1) -> str:
    return f"team-{build_identity_sha256(handoff)[:24]}"


def stable_authorization_id(handoff: BuildHandoffV1) -> str:
    return f"auth-{build_identity_sha256(handoff)[:32]}"


__all__ = [
    "ArtifactRefV1",
    "BuildHandoffV1",
    "CATALOG_SCHEMA_VERSION",
    "CatalogSourceV1",
    "HANDOFF_FIELDS",
    "PostCardCandidateV1",
    "PostCardCatalogV1",
    "PostCardContractError",
    "build_identity_sha256",
    "stable_authorization_id",
    "stable_team_id",
]
