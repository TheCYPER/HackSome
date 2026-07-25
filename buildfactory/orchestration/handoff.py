"""Strict pure-JSON ingestion contract for approved Idea Cards.

This module intentionally does not import ``hacksome``.  Both processes agree
on serialized bytes and hashes, not private Python types.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from orchestration.runtime_store import StoreError


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_AUTHORIZATION_ID = re.compile(r"^auth-[0-9a-f]{32}$")
_ROUTE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SUPPORTED_ROUTE_CONTRACT_VERSIONS = {
    "useful": frozenset({"1"}),
    "creative": frozenset({"1", "2"}),
}
_HANDOFF_FIELDS = frozenset(
    {
        "source_run_id",
        "idea_card_id",
        "idea_card_sha256",
        "challenge_markdown",
        "initial_idea_card_markdown",
    }
)
_MAX_MARKDOWN_BYTES = 8 * 1024 * 1024


class HandoffError(StoreError):
    """The Build authorization envelope is malformed or conflicts."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HandoffError(f"value is not strict JSON: {exc}") from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _exact(
    value: Any,
    *,
    fields: frozenset[str],
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HandoffError(f"{label} must be an object")
    actual = set(value)
    if actual != fields:
        missing = sorted(fields - actual)
        unknown = sorted(actual - fields)
        details = []
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown fields: {', '.join(unknown)}")
        raise HandoffError(f"{label} has " + "; ".join(details))
    return value


def _text(
    value: Any,
    *,
    label: str,
    max_chars: int = 256,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or len(value) > max_chars
    ):
        raise HandoffError(f"{label} must be bounded non-empty text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise HandoffError(f"{label} is not UTF-8 text") from exc
    return value


def _markdown(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise HandoffError(f"{label} must be non-empty UTF-8 text")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise HandoffError(f"{label} is not UTF-8 text") from exc
    if len(encoded) > _MAX_MARKDOWN_BYTES:
        raise HandoffError(f"{label} exceeds {_MAX_MARKDOWN_BYTES} bytes")
    return value


def _digest(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise HandoffError(f"{label} must be a lowercase SHA-256")
    return value


@dataclass(frozen=True)
class BuildHandoffV1:
    source_run_id: str
    idea_card_id: str
    idea_card_sha256: str
    challenge_markdown: str
    initial_idea_card_markdown: str

    @classmethod
    def from_mapping(cls, value: Any) -> "BuildHandoffV1":
        raw = _exact(value, fields=_HANDOFF_FIELDS, label="Build handoff")
        handoff = cls(
            source_run_id=_text(
                raw["source_run_id"], label="handoff source_run_id"
            ),
            idea_card_id=_text(
                raw["idea_card_id"], label="handoff idea_card_id"
            ),
            idea_card_sha256=_digest(
                raw["idea_card_sha256"], label="handoff idea_card_sha256"
            ),
            challenge_markdown=_markdown(
                raw["challenge_markdown"], label="handoff challenge_markdown"
            ),
            initial_idea_card_markdown=_markdown(
                raw["initial_idea_card_markdown"],
                label="handoff initial_idea_card_markdown",
            ),
        )
        if (
            _sha256_bytes(handoff.initial_idea_card_markdown.encode("utf-8"))
            != handoff.idea_card_sha256
        ):
            raise HandoffError(
                "idea_card_sha256 does not match exact Idea Card bytes"
            )
        return handoff

    def to_mapping(self) -> dict[str, Any]:
        return {
            "source_run_id": self.source_run_id,
            "idea_card_id": self.idea_card_id,
            "idea_card_sha256": self.idea_card_sha256,
            "challenge_markdown": self.challenge_markdown,
            "initial_idea_card_markdown": self.initial_idea_card_markdown,
        }

    @property
    def identity_sha256(self) -> str:
        return _sha256_json(
            {
                "source_run_id": self.source_run_id,
                "idea_card_id": self.idea_card_id,
                "idea_card_sha256": self.idea_card_sha256,
            }
        )

    @property
    def handoff_sha256(self) -> str:
        return _sha256_json(self.to_mapping())

    @property
    def team_id(self) -> str:
        return f"team-{self.identity_sha256[:24]}"

    @property
    def authorization_id(self) -> str:
        return f"auth-{self.identity_sha256[:32]}"


@dataclass(frozen=True)
class BuildAuthorizationEnvelopeV1:
    schema_version: int
    authorization_id: str
    route_id: str
    route_contract_version: str
    catalog_sha256: str
    handoff: BuildHandoffV1

    @classmethod
    def from_mapping(cls, value: Any) -> "BuildAuthorizationEnvelopeV1":
        raw = _exact(
            value,
            fields=frozenset(
                {"schema_version", "authorization_id", "source", "handoff"}
            ),
            label="Build authorization envelope",
        )
        if raw["schema_version"] != 1:
            raise HandoffError("unsupported Build authorization schema version")
        authorization_id = raw["authorization_id"]
        if (
            not isinstance(authorization_id, str)
            or not _AUTHORIZATION_ID.fullmatch(authorization_id)
        ):
            raise HandoffError("authorization_id is invalid")
        source = _exact(
            raw["source"],
            fields=frozenset(
                {"route_id", "route_contract_version", "catalog_sha256"}
            ),
            label="Build authorization source",
        )
        route_id = source["route_id"]
        if (
            not isinstance(route_id, str)
            or not _ROUTE_ID.fullmatch(route_id)
            or route_id not in {"useful", "creative"}
        ):
            raise HandoffError("source route_id is unsupported")
        route_version = _text(
            source["route_contract_version"],
            label="source route_contract_version",
            max_chars=64,
        )
        if route_version not in _SUPPORTED_ROUTE_CONTRACT_VERSIONS[route_id]:
            raise HandoffError("source route contract version is unsupported")
        handoff = BuildHandoffV1.from_mapping(raw["handoff"])
        if authorization_id != handoff.authorization_id:
            raise HandoffError(
                "authorization_id does not match the handoff identity"
            )
        return cls(
            schema_version=1,
            authorization_id=authorization_id,
            route_id=route_id,
            route_contract_version=route_version,
            catalog_sha256=_digest(
                source["catalog_sha256"], label="source catalog_sha256"
            ),
            handoff=handoff,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authorization_id": self.authorization_id,
            "source": {
                "route_id": self.route_id,
                "route_contract_version": self.route_contract_version,
                "catalog_sha256": self.catalog_sha256,
            },
            "handoff": self.handoff.to_mapping(),
        }

    @property
    def envelope_sha256(self) -> str:
        return _sha256_json(self.to_mapping())


__all__ = [
    "BuildAuthorizationEnvelopeV1",
    "BuildHandoffV1",
    "HandoffError",
]
