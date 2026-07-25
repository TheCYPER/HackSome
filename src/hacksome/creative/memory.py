"""Validated, bounded Idea Memory discovery and frozen snapshot contracts.

This module deliberately owns only local data contracts. It does not orchestrate
Agent tasks and it does not produce the C7 memory record.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol

from hacksome.state import (
    atomic_write_bytes,
    canonical_json_bytes,
    read_json_object,
    sha256_file,
    sha256_json,
)


MEMORY_SCHEMA_VERSION = 2
SUPPORTED_MEMORY_SCHEMA_VERSIONS = frozenset({1, MEMORY_SCHEMA_VERSION})
SNAPSHOT_SCHEMA_VERSION = 1
SUPPORTED_SOURCE_CONTRACT_VERSION = "2"
SUPPORTED_SOURCE_CONTRACT_VERSIONS = frozenset(
    {"1", SUPPORTED_SOURCE_CONTRACT_VERSION}
)
SUPPORTED_REPORT_POLICY_VERSION = "2"
SUPPORTED_REPORT_POLICY_BY_CONTRACT = {
    "1": "1",
    SUPPORTED_SOURCE_CONTRACT_VERSION: SUPPORTED_REPORT_POLICY_VERSION,
}
MEMORY_RECORD_ARTIFACT_TYPE = "creative_memory_record"
MEMORY_SNAPSHOT_RELATIVE_PATH = (
    "state/creative-memory/idea-memory-snapshot.json"
)

MAX_MEMORY_TEXT_BYTES = 8 * 1024
MAX_REASON_EVIDENCE = 12
MAX_DISCOVERY_DIAGNOSTICS = 256

MemoryMode = Literal["auto", "off"]
MemoryClassification = Literal[
    "positive", "caution", "portfolio_only", "subjective", "transformed"
]
MemoryStageStatus = Literal[
    "disabled", "empty", "completed", "optional_failed"
]
MemoryTaskStatus = Literal[
    "succeeded", "failed", "invalidated", "not_started"
]

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ABSOLUTE_LOCAL_PATH = re.compile(
    r"(?:^|[\s(])/(?:Users|home|private|tmp|var)/|(?:^|[\s(])[A-Za-z]:\\"
)
_PRIVATE_FIELD_NAMES = frozenset(
    {
        "reviewer_id",
        "reviewer_name",
        "curator_name",
        "raw_feedback",
        "human_comment",
        "overall_comment",
        "curator_instruction",
        "prompt",
        "prompt_text",
        "task_log",
        "session_id",
    }
)
_ZERO_REASON_CODES = frozenset(
    {
        "no_concepts_generated",
        "all_candidates_failed_hook",
        "all_candidates_failed_concept_screen",
        "shortlist_empty",
        "all_human_rejected",
    }
)
_CLASSIFICATIONS = frozenset(
    {"positive", "caution", "portfolio_only", "subjective", "transformed"}
)
_PORTFOLIO_REASON_CODES = frozenset(
    {"portfolio_capacity", "territory_round_robin_capacity"}
)
_CURATOR_CAUTION_REASON_CODES = frozenset(
    {"curators_both_exclude", "insufficient_include_support"}
)
_SUBJECTIVE_OUTCOMES = frozenset({"human_reject", "human_taste_veto"})
_TRANSFORMED_OUTCOMES = frozenset(
    {
        "superseded_by_hook_repair",
        "superseded_by_evidence_revision",
        "revised_into",
        "merged_into",
    }
)
_CAUTION_OUTCOMES = frozenset({"c4_eliminated", "not_shortlisted", "eliminated"})


class MemoryValidationError(ValueError):
    """A memory record, snapshot, cue, or summary violates its contract."""


class MemorySettings(Protocol):
    idea_memory_mode: MemoryMode
    max_memory_runs: int
    max_memory_entries: int
    max_memory_snapshot_bytes: int
    max_memory_selected_cues: int
    max_memory_challengers: int


SourceValidator = Callable[[Path], Sequence[str]]


def _strict_object(
    value: Any,
    *,
    expected: frozenset[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MemoryValidationError(f"{label} must be an object")
    result = dict(value)
    missing = sorted(expected - result.keys())
    unknown = sorted(result.keys() - expected)
    if missing:
        raise MemoryValidationError(f"{label} is missing fields: {missing}")
    if unknown:
        raise MemoryValidationError(f"{label} has unknown fields: {unknown}")
    return result


def _text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise MemoryValidationError(f"{label} must be a string")
    if not allow_empty and not value.strip():
        raise MemoryValidationError(f"{label} must not be empty")
    if len(value.encode("utf-8")) > MAX_MEMORY_TEXT_BYTES:
        raise MemoryValidationError(f"{label} exceeds the memory text budget")
    if _ABSOLUTE_LOCAL_PATH.search(value):
        raise MemoryValidationError(f"{label} contains an absolute local path")
    return value


def _identifier(value: Any, label: str) -> str:
    text = _text(value, label)
    if not _SAFE_ID.fullmatch(text):
        raise MemoryValidationError(f"{label} is not a safe identifier")
    return text


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise MemoryValidationError(f"{label} must be a lowercase SHA-256")
    return value


def _string_tuple(
    value: Any,
    label: str,
    *,
    allow_empty: bool = True,
    identifiers: bool = True,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise MemoryValidationError(f"{label} must be an array")
    values = tuple(
        _identifier(item, f"{label} item")
        if identifiers
        else _text(item, f"{label} item")
        for item in value
    )
    if not allow_empty and not values:
        raise MemoryValidationError(f"{label} must not be empty")
    if len(values) != len(set(values)):
        raise MemoryValidationError(f"{label} contains duplicates")
    return values


def reject_private_memory_fields(value: Any) -> None:
    """Reject known identity/raw-feedback fields anywhere in a memory payload."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise MemoryValidationError("memory object keys must be strings")
            if key in _PRIVATE_FIELD_NAMES:
                raise MemoryValidationError(
                    f"private field is forbidden in Idea Memory: {key}"
                )
            reject_private_memory_fields(child)
    elif isinstance(value, list):
        for child in value:
            reject_private_memory_fields(child)


@dataclass(frozen=True, slots=True)
class MemoryChallengeContext:
    summary: str
    intended_reactions: str

    @classmethod
    def from_mapping(cls, value: Any) -> MemoryChallengeContext:
        raw = _strict_object(
            value,
            expected=frozenset({"summary", "intended_reactions"}),
            label="memory challenge_context",
        )
        return cls(
            summary=_text(raw["summary"], "challenge summary"),
            intended_reactions=_text(
                raw["intended_reactions"], "challenge intended reactions"
            ),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "summary": self.summary,
            "intended_reactions": self.intended_reactions,
        }


@dataclass(frozen=True, slots=True)
class MemoryReasonEvidence:
    reason_code: str
    evidence_excerpt: str
    source_review_ref: str
    source_review_sha256: str

    @classmethod
    def from_mapping(cls, value: Any) -> MemoryReasonEvidence:
        raw = _strict_object(
            value,
            expected=frozenset(
                {
                    "reason_code",
                    "evidence_excerpt",
                    "source_review_ref",
                    "source_review_sha256",
                }
            ),
            label="memory reason evidence",
        )
        return cls(
            reason_code=_identifier(raw["reason_code"], "reason evidence code"),
            evidence_excerpt=_text(
                raw["evidence_excerpt"], "reason evidence excerpt"
            ),
            source_review_ref=_identifier(
                raw["source_review_ref"], "reason evidence review ref"
            ),
            source_review_sha256=_sha256(
                raw["source_review_sha256"], "reason evidence review hash"
            ),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "reason_code": self.reason_code,
            "evidence_excerpt": self.evidence_excerpt,
            "source_review_ref": self.source_review_ref,
            "source_review_sha256": self.source_review_sha256,
        }


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    memory_entry_id: str
    capsule_sha256: str
    source_kind: Literal["concept_revision", "final_idea"]
    source_candidate_ref: str
    source_candidate_sha256: str
    source_concept_refs: tuple[str, ...]
    primary_territory_ref: str
    one_sentence_hook: str
    audience_action: str
    core_mechanism: str
    reveal_pattern: str
    intended_reaction: str
    terminal_outcome: str
    reason_codes: tuple[str, ...]
    reason_evidence: tuple[MemoryReasonEvidence, ...]
    evidence_refs: tuple[str, ...]
    classification: MemoryClassification
    software_core_and_runtime: str | None = None
    share_trigger_and_artifact: str | None = None
    minimum_hackathon_demo: str | None = None

    @classmethod
    def from_mapping(
        cls,
        value: Any,
        *,
        memory_schema_version: int = 1,
    ) -> MemoryEntry:
        expected_fields = {
                "memory_entry_id",
                "capsule_sha256",
                "source_kind",
                "source_candidate_ref",
                "source_candidate_sha256",
                "source_concept_refs",
                "primary_territory_ref",
                "one_sentence_hook",
                "audience_action",
                "core_mechanism",
                "reveal_pattern",
                "intended_reaction",
                "terminal_outcome",
                "reason_codes",
                "reason_evidence",
                "evidence_refs",
                "classification",
        }
        if memory_schema_version == 2:
            expected_fields.update(
                {
                    "software_core_and_runtime",
                    "share_trigger_and_artifact",
                    "minimum_hackathon_demo",
                }
            )
        elif memory_schema_version != 1:
            raise MemoryValidationError("unsupported memory entry schema version")
        expected = frozenset(
            expected_fields
        )
        raw = _strict_object(value, expected=expected, label="memory entry")
        source_kind = raw["source_kind"]
        if source_kind not in {"concept_revision", "final_idea"}:
            raise MemoryValidationError("memory entry source_kind is invalid")
        classification = raw["classification"]
        if classification not in _CLASSIFICATIONS:
            raise MemoryValidationError("memory entry classification is invalid")
        raw_reason_evidence = raw["reason_evidence"]
        if not isinstance(raw_reason_evidence, list):
            raise MemoryValidationError("memory reason_evidence must be an array")
        if len(raw_reason_evidence) > MAX_REASON_EVIDENCE:
            raise MemoryValidationError("memory reason_evidence exceeds its limit")
        entry = cls(
            memory_entry_id=_identifier(
                raw["memory_entry_id"], "memory entry id"
            ),
            capsule_sha256=_sha256(
                raw["capsule_sha256"], "memory entry capsule hash"
            ),
            source_kind=source_kind,
            source_candidate_ref=_identifier(
                raw["source_candidate_ref"], "memory source candidate ref"
            ),
            source_candidate_sha256=_sha256(
                raw["source_candidate_sha256"], "memory source candidate hash"
            ),
            source_concept_refs=_string_tuple(
                raw["source_concept_refs"], "memory source concept refs"
            ),
            primary_territory_ref=_identifier(
                raw["primary_territory_ref"], "memory primary territory ref"
            ),
            one_sentence_hook=_text(
                raw["one_sentence_hook"], "memory one-sentence hook"
            ),
            audience_action=_text(
                raw["audience_action"], "memory audience action"
            ),
            core_mechanism=_text(
                raw["core_mechanism"], "memory core mechanism"
            ),
            reveal_pattern=_text(
                raw["reveal_pattern"], "memory reveal pattern"
            ),
            intended_reaction=_text(
                raw["intended_reaction"], "memory intended reaction"
            ),
            terminal_outcome=_identifier(
                raw["terminal_outcome"], "memory terminal outcome"
            ),
            reason_codes=_string_tuple(
                raw["reason_codes"], "memory reason codes"
            ),
            reason_evidence=tuple(
                MemoryReasonEvidence.from_mapping(item)
                for item in raw_reason_evidence
            ),
            evidence_refs=_string_tuple(
                raw["evidence_refs"], "memory evidence refs"
            ),
            classification=classification,
            software_core_and_runtime=(
                _text(
                    raw["software_core_and_runtime"],
                    "memory software core and runtime",
                )
                if memory_schema_version == 2
                else None
            ),
            share_trigger_and_artifact=(
                _text(
                    raw["share_trigger_and_artifact"],
                    "memory share trigger and artifact",
                )
                if memory_schema_version == 2
                else None
            ),
            minimum_hackathon_demo=(
                _text(
                    raw["minimum_hackathon_demo"],
                    "memory minimum hackathon demo",
                )
                if memory_schema_version == 2
                else None
            ),
        )
        if any(
            evidence.reason_code not in entry.reason_codes
            for evidence in entry.reason_evidence
        ):
            raise MemoryValidationError(
                "memory reason evidence must bind to an entry reason code"
            )
        expected_classification = expected_memory_classification(
            source_kind=entry.source_kind,
            terminal_outcome=entry.terminal_outcome,
            reason_codes=entry.reason_codes,
        )
        if entry.classification != expected_classification:
            raise MemoryValidationError(
                "memory classification does not match outcome/reason semantics"
            )
        if sha256_json(entry.canonical_capsule_payload()) != entry.capsule_sha256:
            raise MemoryValidationError("memory entry capsule hash mismatch")
        return entry

    def canonical_capsule_payload(self) -> dict[str, Any]:
        payload = self.to_dict()
        del payload["capsule_sha256"]
        return payload

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "memory_entry_id": self.memory_entry_id,
            "capsule_sha256": self.capsule_sha256,
            "source_kind": self.source_kind,
            "source_candidate_ref": self.source_candidate_ref,
            "source_candidate_sha256": self.source_candidate_sha256,
            "source_concept_refs": list(self.source_concept_refs),
            "primary_territory_ref": self.primary_territory_ref,
            "one_sentence_hook": self.one_sentence_hook,
            "audience_action": self.audience_action,
            "core_mechanism": self.core_mechanism,
            "reveal_pattern": self.reveal_pattern,
            "intended_reaction": self.intended_reaction,
            "terminal_outcome": self.terminal_outcome,
            "reason_codes": list(self.reason_codes),
            "reason_evidence": [
                evidence.to_dict() for evidence in self.reason_evidence
            ],
            "evidence_refs": list(self.evidence_refs),
            "classification": self.classification,
        }
        if self.software_core_and_runtime is not None:
            result["software_core_and_runtime"] = self.software_core_and_runtime
        if self.share_trigger_and_artifact is not None:
            result["share_trigger_and_artifact"] = self.share_trigger_and_artifact
        if self.minimum_hackathon_demo is not None:
            result["minimum_hackathon_demo"] = self.minimum_hackathon_demo
        return result


def expected_memory_classification(
    *,
    source_kind: str,
    terminal_outcome: str,
    reason_codes: Sequence[str],
) -> MemoryClassification:
    """Return the controller-owned classification for one validated source."""

    reasons = frozenset(reason_codes)
    if source_kind == "final_idea":
        return "positive"
    if source_kind != "concept_revision":
        raise MemoryValidationError("unsupported memory source kind")
    if terminal_outcome in _SUBJECTIVE_OUTCOMES:
        return "subjective"
    if terminal_outcome in _TRANSFORMED_OUTCOMES:
        return "transformed"
    if reasons & _PORTFOLIO_REASON_CODES:
        return "portfolio_only"
    if (
        reasons & _CURATOR_CAUTION_REASON_CODES
        or terminal_outcome in _CAUTION_OUTCOMES
    ):
        return "caution"
    raise MemoryValidationError(
        "concept memory outcome/reasons have no supported classification"
    )


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    memory_schema_version: int
    source_run_id: str
    source_route_id: str
    source_contract_version: str
    source_report_artifact_id: str
    source_report_sha256: str
    created_at: str
    producer_kind: Literal["live", "fixture"]
    zero_reason_code: str | None
    challenge_context: MemoryChallengeContext
    entries: tuple[MemoryEntry, ...]

    @classmethod
    def from_mapping(cls, value: Any) -> MemoryRecord:
        reject_private_memory_fields(value)
        raw = _strict_object(
            value,
            expected=frozenset(
                {
                    "memory_schema_version",
                    "source_run_id",
                    "source_route",
                    "source_report_artifact_id",
                    "source_report_sha256",
                    "created_at",
                    "producer_kind",
                    "zero_reason_code",
                    "challenge_context",
                    "entries",
                }
            ),
            label="creative memory record",
        )
        if raw["memory_schema_version"] not in SUPPORTED_MEMORY_SCHEMA_VERSIONS:
            raise MemoryValidationError("unsupported memory schema version")
        route = _strict_object(
            raw["source_route"],
            expected=frozenset({"id", "contract_version"}),
            label="memory source route",
        )
        if route["id"] != "creative":
            raise MemoryValidationError("memory source route must be creative")
        if route["contract_version"] not in SUPPORTED_SOURCE_CONTRACT_VERSIONS:
            raise MemoryValidationError("unsupported memory source contract version")
        expected_schema_version = (
            1 if route["contract_version"] == "1" else MEMORY_SCHEMA_VERSION
        )
        if raw["memory_schema_version"] != expected_schema_version:
            raise MemoryValidationError(
                "memory schema version does not match source contract version"
            )
        producer_kind = raw["producer_kind"]
        if producer_kind not in {"live", "fixture"}:
            raise MemoryValidationError("memory producer_kind is invalid")
        zero_reason = raw["zero_reason_code"]
        if zero_reason is not None and zero_reason not in _ZERO_REASON_CODES:
            raise MemoryValidationError("memory zero_reason_code is invalid")
        if (
            route["contract_version"] == "1"
            and zero_reason == "all_candidates_failed_concept_screen"
        ):
            raise MemoryValidationError(
                "Creative v1 memory cannot use the v2 Concept Screen zero reason"
            )
        if (
            route["contract_version"] == "2"
            and zero_reason == "all_candidates_failed_hook"
        ):
            raise MemoryValidationError(
                "Creative v2 memory cannot use the legacy Hook zero reason"
            )
        raw_entries = raw["entries"]
        if not isinstance(raw_entries, list):
            raise MemoryValidationError("memory entries must be an array")
        entries = tuple(
            MemoryEntry.from_mapping(
                item,
                memory_schema_version=raw["memory_schema_version"],
            )
            for item in raw_entries
        )
        entry_ids = tuple(entry.memory_entry_id for entry in entries)
        if len(entry_ids) != len(set(entry_ids)):
            raise MemoryValidationError("memory entry IDs must be unique")
        final_entries = tuple(
            entry for entry in entries if entry.source_kind == "final_idea"
        )
        if zero_reason is None and not final_entries:
            raise MemoryValidationError(
                "non-zero memory record requires a final_idea entry"
            )
        if zero_reason is not None and final_entries:
            raise MemoryValidationError(
                "zero-Idea memory record cannot contain final_idea entries"
            )
        created_at = _text(raw["created_at"], "memory created_at")
        _parse_timestamp(created_at, "memory created_at")
        return cls(
            memory_schema_version=raw["memory_schema_version"],
            source_run_id=_identifier(raw["source_run_id"], "memory source run id"),
            source_route_id="creative",
            source_contract_version=route["contract_version"],
            source_report_artifact_id=_identifier(
                raw["source_report_artifact_id"], "memory source report artifact id"
            ),
            source_report_sha256=_sha256(
                raw["source_report_sha256"], "memory source report hash"
            ),
            created_at=created_at,
            producer_kind=producer_kind,
            zero_reason_code=zero_reason,
            challenge_context=MemoryChallengeContext.from_mapping(
                raw["challenge_context"]
            ),
            entries=entries,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_schema_version": self.memory_schema_version,
            "source_run_id": self.source_run_id,
            "source_route": {
                "id": self.source_route_id,
                "contract_version": self.source_contract_version,
            },
            "source_report_artifact_id": self.source_report_artifact_id,
            "source_report_sha256": self.source_report_sha256,
            "created_at": self.created_at,
            "producer_kind": self.producer_kind,
            "zero_reason_code": self.zero_reason_code,
            "challenge_context": self.challenge_context.to_dict(),
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True, slots=True)
class MemoryCapsuleRef:
    """Complete cross-run identity for one copied memory capsule."""

    source_run_id: str
    source_route_id: str
    source_contract_version: str
    source_artifact_id: str
    source_artifact_sha256: str
    source_memory_record_artifact_id: str
    source_memory_record_sha256: str
    capsule_sha256: str

    @classmethod
    def from_mapping(cls, value: Any) -> MemoryCapsuleRef:
        raw = _strict_object(
            value,
            expected=frozenset(
                {
                    "source_run_id",
                    "source_route_id",
                    "source_contract_version",
                    "source_artifact_id",
                    "source_artifact_sha256",
                    "source_memory_record_artifact_id",
                    "source_memory_record_sha256",
                    "capsule_sha256",
                }
            ),
            label="memory capsule ref",
        )
        if raw["source_route_id"] != "creative":
            raise MemoryValidationError("memory capsule route must be creative")
        if raw["source_contract_version"] not in SUPPORTED_SOURCE_CONTRACT_VERSIONS:
            raise MemoryValidationError(
                "memory capsule contract version is unsupported"
            )
        return cls(
            source_run_id=_identifier(
                raw["source_run_id"], "capsule source run id"
            ),
            source_route_id="creative",
            source_contract_version=raw["source_contract_version"],
            source_artifact_id=_identifier(
                raw["source_artifact_id"], "capsule source artifact id"
            ),
            source_artifact_sha256=_sha256(
                raw["source_artifact_sha256"], "capsule source artifact hash"
            ),
            source_memory_record_artifact_id=_identifier(
                raw["source_memory_record_artifact_id"],
                "capsule memory record artifact id",
            ),
            source_memory_record_sha256=_sha256(
                raw["source_memory_record_sha256"],
                "capsule memory record hash",
            ),
            capsule_sha256=_sha256(
                raw["capsule_sha256"], "copied capsule hash"
            ),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "source_run_id": self.source_run_id,
            "source_route_id": self.source_route_id,
            "source_contract_version": self.source_contract_version,
            "source_artifact_id": self.source_artifact_id,
            "source_artifact_sha256": self.source_artifact_sha256,
            "source_memory_record_artifact_id": (
                self.source_memory_record_artifact_id
            ),
            "source_memory_record_sha256": self.source_memory_record_sha256,
            "capsule_sha256": self.capsule_sha256,
        }

    @property
    def stable_key(self) -> tuple[str, ...]:
        return (
            self.source_run_id,
            self.source_route_id,
            self.source_contract_version,
            self.source_artifact_id,
            self.source_artifact_sha256,
            self.source_memory_record_artifact_id,
            self.source_memory_record_sha256,
            self.capsule_sha256,
        )


@dataclass(frozen=True, slots=True)
class MemoryCapsule:
    memory_ref: MemoryCapsuleRef
    challenge_context: MemoryChallengeContext
    entry: MemoryEntry

    @classmethod
    def from_source(
        cls,
        *,
        record: MemoryRecord,
        record_artifact_id: str,
        record_sha256: str,
        entry: MemoryEntry,
    ) -> MemoryCapsule:
        payload = {
            "challenge_context": record.challenge_context.to_dict(),
            "entry": entry.to_dict(),
        }
        memory_ref = MemoryCapsuleRef(
            source_run_id=record.source_run_id,
            source_route_id=record.source_route_id,
            source_contract_version=record.source_contract_version,
            source_artifact_id=entry.source_candidate_ref,
            source_artifact_sha256=entry.source_candidate_sha256,
            source_memory_record_artifact_id=record_artifact_id,
            source_memory_record_sha256=record_sha256,
            capsule_sha256=sha256_json(payload),
        )
        return cls(
            memory_ref=memory_ref,
            challenge_context=record.challenge_context,
            entry=entry,
        )

    @classmethod
    def from_mapping(cls, value: Any) -> MemoryCapsule:
        raw = _strict_object(
            value,
            expected=frozenset({"memory_ref", "challenge_context", "entry"}),
            label="memory capsule",
        )
        memory_ref = MemoryCapsuleRef.from_mapping(raw["memory_ref"])
        capsule = cls(
            memory_ref=memory_ref,
            challenge_context=MemoryChallengeContext.from_mapping(
                raw["challenge_context"]
            ),
            entry=MemoryEntry.from_mapping(
                raw["entry"],
                memory_schema_version=(
                    1 if memory_ref.source_contract_version == "1" else 2
                ),
            ),
        )
        if (
            capsule.memory_ref.source_artifact_id
            != capsule.entry.source_candidate_ref
            or capsule.memory_ref.source_artifact_sha256
            != capsule.entry.source_candidate_sha256
        ):
            raise MemoryValidationError(
                "memory capsule ref does not bind its source entry"
            )
        if (
            sha256_json(capsule.canonical_payload())
            != capsule.memory_ref.capsule_sha256
        ):
            raise MemoryValidationError("copied memory capsule hash mismatch")
        return capsule

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "challenge_context": self.challenge_context.to_dict(),
            "entry": self.entry.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_ref": self.memory_ref.to_dict(),
            **self.canonical_payload(),
        }


@dataclass(frozen=True, slots=True)
class MemorySourceRecord:
    source_run_id: str
    source_route_id: str
    source_contract_version: str
    source_memory_record_artifact_id: str
    source_memory_record_sha256: str

    @classmethod
    def from_mapping(cls, value: Any) -> MemorySourceRecord:
        raw = _strict_object(
            value,
            expected=frozenset(
                {
                    "source_run_id",
                    "source_route_id",
                    "source_contract_version",
                    "source_memory_record_artifact_id",
                    "source_memory_record_sha256",
                }
            ),
            label="memory source record",
        )
        if raw["source_route_id"] != "creative":
            raise MemoryValidationError("memory source record route is invalid")
        if raw["source_contract_version"] not in SUPPORTED_SOURCE_CONTRACT_VERSIONS:
            raise MemoryValidationError(
                "memory source record contract version is unsupported"
            )
        return cls(
            source_run_id=_identifier(
                raw["source_run_id"], "memory source record run id"
            ),
            source_route_id="creative",
            source_contract_version=raw["source_contract_version"],
            source_memory_record_artifact_id=_identifier(
                raw["source_memory_record_artifact_id"],
                "memory source record artifact id",
            ),
            source_memory_record_sha256=_sha256(
                raw["source_memory_record_sha256"],
                "memory source record hash",
            ),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "source_run_id": self.source_run_id,
            "source_route_id": self.source_route_id,
            "source_contract_version": self.source_contract_version,
            "source_memory_record_artifact_id": (
                self.source_memory_record_artifact_id
            ),
            "source_memory_record_sha256": self.source_memory_record_sha256,
        }


@dataclass(frozen=True, slots=True)
class MemoryDiagnostic:
    code: str
    source_name: str | None
    detail: str

    @classmethod
    def from_mapping(cls, value: Any) -> MemoryDiagnostic:
        raw = _strict_object(
            value,
            expected=frozenset({"code", "source_name", "detail"}),
            label="memory diagnostic",
        )
        source_name = raw["source_name"]
        if source_name is not None:
            source_name = _text(source_name, "memory diagnostic source name")
        return cls(
            code=_identifier(raw["code"], "memory diagnostic code"),
            source_name=source_name,
            detail=_text(raw["detail"], "memory diagnostic detail"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "source_name": self.source_name,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class IdeaMemorySnapshot:
    schema_version: int
    mode: MemoryMode
    created_from: Literal["runs_dir", "disabled"]
    source_records: tuple[MemorySourceRecord, ...]
    entries: tuple[MemoryCapsule, ...]
    diagnostics: tuple[MemoryDiagnostic, ...]
    truncated: bool
    empty_reason: Literal["disabled", "no_eligible_history"] | None

    def __post_init__(self) -> None:
        if self.schema_version != SNAPSHOT_SCHEMA_VERSION:
            raise MemoryValidationError("unsupported memory snapshot schema")
        if self.mode not in {"auto", "off"}:
            raise MemoryValidationError("memory snapshot mode is invalid")
        if self.mode == "off":
            if self.created_from != "disabled":
                raise MemoryValidationError(
                    "off memory snapshot must be created_from=disabled"
                )
            if self.source_records or self.entries:
                raise MemoryValidationError("off memory snapshot must be empty")
            if self.empty_reason != "disabled":
                raise MemoryValidationError(
                    "off memory snapshot requires empty_reason=disabled"
                )
        else:
            if self.created_from != "runs_dir":
                raise MemoryValidationError(
                    "auto memory snapshot must be created_from=runs_dir"
                )
            expected_reason = None if self.entries else "no_eligible_history"
            if self.empty_reason != expected_reason:
                raise MemoryValidationError(
                    "auto memory snapshot has inconsistent empty_reason"
                )
        source_keys = tuple(
            (
                source.source_run_id,
                source.source_memory_record_artifact_id,
            )
            for source in self.source_records
        )
        if len(source_keys) != len(set(source_keys)):
            raise MemoryValidationError(
                "memory snapshot source records must be unique"
            )
        source_refs = {
            (
                source.source_run_id,
                source.source_memory_record_artifact_id,
                source.source_memory_record_sha256,
            )
            for source in self.source_records
        }
        capsule_keys = tuple(capsule.memory_ref.stable_key for capsule in self.entries)
        if len(capsule_keys) != len(set(capsule_keys)):
            raise MemoryValidationError(
                "memory snapshot capsule refs must be unique"
            )
        for capsule in self.entries:
            ref = capsule.memory_ref
            if (
                ref.source_run_id,
                ref.source_memory_record_artifact_id,
                ref.source_memory_record_sha256,
            ) not in source_refs:
                raise MemoryValidationError(
                    "memory capsule has no matching source record"
                )
            if sha256_json(capsule.canonical_payload()) != ref.capsule_sha256:
                raise MemoryValidationError("memory snapshot capsule hash mismatch")

    @classmethod
    def from_mapping(cls, value: Any) -> IdeaMemorySnapshot:
        reject_private_memory_fields(value)
        raw = _strict_object(
            value,
            expected=frozenset(
                {
                    "schema_version",
                    "mode",
                    "created_from",
                    "source_records",
                    "entries",
                    "diagnostics",
                    "truncated",
                    "empty_reason",
                }
            ),
            label="idea memory snapshot",
        )
        if not isinstance(raw["source_records"], list):
            raise MemoryValidationError(
                "memory snapshot source_records must be an array"
            )
        if not isinstance(raw["entries"], list):
            raise MemoryValidationError(
                "memory snapshot entries must be an array"
            )
        if not isinstance(raw["diagnostics"], list):
            raise MemoryValidationError(
                "memory snapshot diagnostics must be an array"
            )
        if not isinstance(raw["truncated"], bool):
            raise MemoryValidationError(
                "memory snapshot truncated must be boolean"
            )
        return cls(
            schema_version=raw["schema_version"],
            mode=raw["mode"],
            created_from=raw["created_from"],
            source_records=tuple(
                MemorySourceRecord.from_mapping(item)
                for item in raw["source_records"]
            ),
            entries=tuple(
                MemoryCapsule.from_mapping(item) for item in raw["entries"]
            ),
            diagnostics=tuple(
                MemoryDiagnostic.from_mapping(item)
                for item in raw["diagnostics"]
            ),
            truncated=raw["truncated"],
            empty_reason=raw["empty_reason"],
        )

    @property
    def has_eligible_entries(self) -> bool:
        return bool(self.entries)

    @property
    def eligible_entry_count(self) -> int:
        return len(self.entries)

    def capsule_prompt_projection(self) -> dict[str, Any]:
        """Return only the untrusted capsule data allowed into Recall."""

        return {
            "schema_version": self.schema_version,
            "entries": [capsule.to_dict() for capsule in self.entries],
        }

    def capsule_prompt_text(self) -> str:
        return json.dumps(
            self.capsule_prompt_projection(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "created_from": self.created_from,
            "source_records": [
                source.to_dict() for source in self.source_records
            ],
            "entries": [capsule.to_dict() for capsule in self.entries],
            "diagnostics": [
                diagnostic.to_dict() for diagnostic in self.diagnostics
            ],
            "truncated": self.truncated,
            "empty_reason": self.empty_reason,
        }

    def to_json_bytes(self) -> bytes:
        return (
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class _EligibleSource:
    path: Path
    created_at: datetime
    run_id: str
    record_artifact_id: str
    record_sha256: str
    record: MemoryRecord

    @property
    def source_record(self) -> MemorySourceRecord:
        return MemorySourceRecord(
            source_run_id=self.run_id,
            source_route_id="creative",
            source_contract_version=self.record.source_contract_version,
            source_memory_record_artifact_id=self.record_artifact_id,
            source_memory_record_sha256=self.record_sha256,
        )


def build_memory_snapshot(
    runs_dir: str | Path,
    settings: MemorySettings | Mapping[str, Any],
    *,
    source_validator: SourceValidator | None = None,
    exclude_run_id: str | None = None,
) -> IdeaMemorySnapshot:
    """Discover eligible direct-child runs and freeze bounded capsule copies."""

    mode = _memory_setting(settings, "idea_memory_mode")
    if mode not in {"auto", "off"}:
        raise MemoryValidationError("idea_memory_mode must be auto or off")
    max_runs = _positive_setting(settings, "max_memory_runs")
    max_entries = _positive_setting(settings, "max_memory_entries")
    max_snapshot_bytes = _positive_setting(
        settings, "max_memory_snapshot_bytes"
    )
    if mode == "off":
        return IdeaMemorySnapshot(
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            mode="off",
            created_from="disabled",
            source_records=(),
            entries=(),
            diagnostics=(),
            truncated=False,
            empty_reason="disabled",
        )

    root = Path(runs_dir).expanduser()
    if source_validator is None:
        source_validator = _default_source_validator
    diagnostics: list[MemoryDiagnostic] = []
    if not root.exists():
        return _empty_auto_snapshot(diagnostics)
    if not root.is_dir():
        raise MemoryValidationError("runs_dir must be a directory")

    eligible: list[_EligibleSource] = []
    try:
        children = sorted(root.iterdir(), key=lambda child: child.name)
    except OSError as exc:
        raise MemoryValidationError("cannot enumerate runs_dir") from exc
    for child in children:
        if len(diagnostics) >= MAX_DISCOVERY_DIAGNOSTICS:
            break
        if child.is_symlink():
            diagnostics.append(
                _diagnostic(
                    "source_symlink_rejected",
                    child.name,
                    "direct-child symlinks are never followed",
                )
            )
            continue
        if not child.is_dir():
            diagnostics.append(
                _diagnostic(
                    "source_not_directory",
                    child.name,
                    "direct child is not a run directory",
                )
            )
            continue
        try:
            source = _load_eligible_source(
                child,
                source_validator=source_validator,
                exclude_run_id=exclude_run_id,
            )
        except _SourceRejected as exc:
            diagnostics.append(_diagnostic(exc.code, child.name, exc.detail))
            continue
        eligible.append(source)
    if len(diagnostics) >= MAX_DISCOVERY_DIAGNOSTICS and len(children) > len(
        eligible
    ) + len(diagnostics):
        diagnostics[-1] = _diagnostic(
            "diagnostic_limit_reached",
            None,
            "additional discovery diagnostics were omitted",
        )

    eligible.sort(
        key=lambda source: (
            -source.created_at.timestamp(),
            source.run_id,
        )
    )
    selected_sources = eligible[:max_runs]
    if len(eligible) > max_runs:
        diagnostics.append(
            _diagnostic(
                "memory_run_limit_reached",
                None,
                f"{len(eligible) - max_runs} eligible source run(s) omitted",
            )
        )
    flattened = [
        (source, entry)
        for source in selected_sources
        for entry in sorted(
            source.record.entries, key=lambda item: item.memory_entry_id
        )
    ]
    limited_entries = flattened[:max_entries]
    truncated = len(eligible) > max_runs or len(flattened) > max_entries
    if len(flattened) > max_entries:
        diagnostics.append(
            _diagnostic(
                "memory_entry_limit_reached",
                None,
                f"{len(flattened) - max_entries} eligible memory entry(s) omitted",
            )
        )

    capsules = [
        MemoryCapsule.from_source(
            record=source.record,
            record_artifact_id=source.record_artifact_id,
            record_sha256=source.record_sha256,
            entry=entry,
        )
        for source, entry in limited_entries
    ]
    source_records = tuple(source.source_record for source in selected_sources)
    snapshot = _auto_snapshot(
        source_records=source_records,
        entries=tuple(capsules),
        diagnostics=tuple(diagnostics),
        truncated=truncated,
    )
    if len(snapshot.to_json_bytes()) > max_snapshot_bytes:
        truncated = True
        byte_diagnostic = _diagnostic(
            "memory_byte_limit_reached",
            None,
            "one or more eligible entries were omitted by the snapshot byte limit",
        )
        if not any(item.code == byte_diagnostic.code for item in diagnostics):
            diagnostics.append(byte_diagnostic)
        while capsules:
            capsules.pop()
            referenced_sources = {
                (
                    capsule.memory_ref.source_run_id,
                    capsule.memory_ref.source_memory_record_artifact_id,
                )
                for capsule in capsules
            }
            bounded_sources = tuple(
                source
                for source in source_records
                if (
                    source.source_run_id,
                    source.source_memory_record_artifact_id,
                )
                in referenced_sources
            )
            snapshot = _auto_snapshot(
                source_records=bounded_sources,
                entries=tuple(capsules),
                diagnostics=tuple(diagnostics),
                truncated=True,
            )
            if len(snapshot.to_json_bytes()) <= max_snapshot_bytes:
                break
        else:
            snapshot = _auto_snapshot(
                source_records=(),
                entries=(),
                diagnostics=tuple(diagnostics),
                truncated=True,
            )
        if len(snapshot.to_json_bytes()) > max_snapshot_bytes:
            raise MemoryValidationError(
                "max_memory_snapshot_bytes is too small for discovery diagnostics"
            )
    return snapshot


def persist_memory_snapshot(
    snapshot: IdeaMemorySnapshot,
    run_dir: str | Path,
) -> dict[str, Any]:
    """Persist exact snapshot bytes and return RunHub input metadata."""

    # Re-parse the public projection so callers cannot persist a forged object
    # created through unsafe dataclass construction.
    validated = IdeaMemorySnapshot.from_mapping(snapshot.to_dict())
    root = Path(run_dir).expanduser().resolve()
    if not root.is_dir():
        raise MemoryValidationError(f"run directory does not exist: {root}")
    destination = root / MEMORY_SNAPSHOT_RELATIVE_PATH
    _reject_symlink_chain(root, destination)
    payload = validated.to_json_bytes()
    atomic_write_bytes(destination, payload)
    return {
        "path": MEMORY_SNAPSHOT_RELATIVE_PATH,
        "sha256": sha256_file(destination),
        "mode": validated.mode,
        "source": validated.created_from,
        "eligible_entry_count": validated.eligible_entry_count,
        "diagnostic_count": len(validated.diagnostics),
    }


def load_memory_snapshot(
    path: str | Path,
    *,
    expected_sha256: str,
) -> IdeaMemorySnapshot:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise MemoryValidationError("memory snapshot file is missing or a symlink")
    if sha256_file(source) != _sha256(expected_sha256, "snapshot hash"):
        raise MemoryValidationError("memory snapshot hash mismatch")
    try:
        raw = read_json_object(source)
    except Exception as exc:
        raise MemoryValidationError(f"memory snapshot JSON is invalid: {exc}") from exc
    return IdeaMemorySnapshot.from_mapping(raw)


def _empty_auto_snapshot(
    diagnostics: Sequence[MemoryDiagnostic],
) -> IdeaMemorySnapshot:
    return _auto_snapshot(
        source_records=(),
        entries=(),
        diagnostics=tuple(diagnostics),
        truncated=False,
    )


def _auto_snapshot(
    *,
    source_records: tuple[MemorySourceRecord, ...],
    entries: tuple[MemoryCapsule, ...],
    diagnostics: tuple[MemoryDiagnostic, ...],
    truncated: bool,
) -> IdeaMemorySnapshot:
    return IdeaMemorySnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        mode="auto",
        created_from="runs_dir",
        source_records=source_records,
        entries=entries,
        diagnostics=diagnostics,
        truncated=truncated,
        empty_reason=None if entries else "no_eligible_history",
    )


class _SourceRejected(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _load_eligible_source(
    run_dir: Path,
    *,
    source_validator: SourceValidator,
    exclude_run_id: str | None,
) -> _EligibleSource:
    state_path = run_dir / "run.json"
    if state_path.is_symlink() or not state_path.is_file():
        raise _SourceRejected("missing_run_state", "run.json is missing")
    try:
        state = read_json_object(state_path)
    except Exception as exc:
        raise _SourceRejected(
            "invalid_run_state", f"run.json cannot be decoded ({type(exc).__name__})"
        ) from exc
    if state.get("schema_version") != 2:
        raise _SourceRejected(
            "unsupported_run_schema", "only v2 Creative runs are eligible"
        )
    route = state.get("route")
    if not isinstance(route, Mapping):
        raise _SourceRejected("unsupported_route", "run has no route metadata")
    if route.get("id") != "creative":
        raise _SourceRejected("unsupported_route", "run is not Creative")
    contract_version = route.get("contract_version")
    if contract_version not in SUPPORTED_SOURCE_CONTRACT_VERSIONS:
        raise _SourceRejected(
            "unsupported_contract_version",
            "Creative contract version is unsupported",
        )
    if (
        route.get("report_policy_version")
        != SUPPORTED_REPORT_POLICY_BY_CONTRACT.get(str(contract_version))
    ):
        raise _SourceRejected(
            "unsupported_report_policy",
            "Creative report policy version is unsupported",
        )
    if state.get("status") != "completed":
        raise _SourceRejected(
            "source_not_completed", "only completed Creative runs are eligible"
        )
    run_id = state.get("run_id")
    try:
        validated_run_id = _identifier(run_id, "source run id")
    except MemoryValidationError as exc:
        raise _SourceRejected("invalid_source_run_id", str(exc)) from exc
    if exclude_run_id is not None and validated_run_id == exclude_run_id:
        raise _SourceRejected("current_run_excluded", "current run cannot source itself")
    created_at_raw = state.get("created_at")
    try:
        created_at = _parse_timestamp(created_at_raw, "source run created_at")
    except MemoryValidationError as exc:
        raise _SourceRejected("invalid_source_created_at", str(exc)) from exc
    try:
        validation_errors = tuple(source_validator(run_dir))
    except Exception as exc:
        raise _SourceRejected(
            "source_validation_failed",
            f"offline validation could not run ({type(exc).__name__})",
        ) from exc
    if validation_errors:
        raise _SourceRejected(
            "source_validation_failed",
            f"offline validation reported {len(validation_errors)} error(s)",
        )
    artifacts = state.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise _SourceRejected(
            "missing_memory_record", "run artifacts are not an object"
        )
    candidates = [
        (artifact_id, record)
        for artifact_id, record in artifacts.items()
        if isinstance(artifact_id, str)
        and isinstance(record, Mapping)
        and record.get("artifact_type") == MEMORY_RECORD_ARTIFACT_TYPE
    ]
    if len(candidates) != 1:
        raise _SourceRejected(
            "missing_memory_record",
            "completed Creative run must register exactly one memory record",
        )
    record_artifact_id, artifact_record = candidates[0]
    result_ids = state.get("result_artifact_ids")
    if not isinstance(result_ids, list) or record_artifact_id not in result_ids:
        raise _SourceRejected(
            "memory_record_not_final",
            "memory record is not a completed result artifact",
        )
    try:
        record_path, record_sha256 = _validated_artifact_file(
            run_dir,
            record_artifact_id,
            artifact_record,
        )
    except MemoryValidationError as exc:
        raise _SourceRejected("memory_record_hash_mismatch", str(exc)) from exc
    try:
        raw_record = read_json_object(record_path)
        memory_record = MemoryRecord.from_mapping(raw_record)
        _validate_memory_record_bindings(
            memory_record,
            state=state,
            run_dir=run_dir,
        )
    except Exception as exc:
        raise _SourceRejected(
            "invalid_memory_record",
            f"memory record failed semantic validation ({type(exc).__name__})",
        ) from exc
    if memory_record.producer_kind == "fixture":
        raise _SourceRejected(
            "fixture_source_rejected", "fixture memory is never auto-discovered"
        )
    if memory_record.source_run_id != validated_run_id:
        raise _SourceRejected(
            "invalid_memory_record", "memory record source_run_id mismatch"
        )
    return _EligibleSource(
        path=run_dir,
        created_at=created_at,
        run_id=validated_run_id,
        record_artifact_id=record_artifact_id,
        record_sha256=record_sha256,
        record=memory_record,
    )


def _validate_memory_record_bindings(
    record: MemoryRecord,
    *,
    state: Mapping[str, Any],
    run_dir: Path,
) -> None:
    artifacts = state.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise MemoryValidationError("source artifacts must be an object")
    _validate_artifact_binding(
        artifacts,
        run_dir,
        record.source_report_artifact_id,
        record.source_report_sha256,
        label="source report",
    )
    for entry in record.entries:
        _validate_artifact_binding(
            artifacts,
            run_dir,
            entry.source_candidate_ref,
            entry.source_candidate_sha256,
            label="source candidate",
        )
        for concept_ref in entry.source_concept_refs:
            _validate_artifact_binding(
                artifacts,
                run_dir,
                concept_ref,
                None,
                label="source concept",
            )
        for evidence_ref in entry.evidence_refs:
            _validate_artifact_binding(
                artifacts,
                run_dir,
                evidence_ref,
                None,
                label="source evidence",
            )
        for evidence in entry.reason_evidence:
            _validate_artifact_binding(
                artifacts,
                run_dir,
                evidence.source_review_ref,
                evidence.source_review_sha256,
                label="source machine review",
            )


def _validate_artifact_binding(
    artifacts: Mapping[str, Any],
    run_dir: Path,
    artifact_id: str,
    expected_sha256: str | None,
    *,
    label: str,
) -> None:
    raw = artifacts.get(artifact_id)
    if not isinstance(raw, Mapping):
        raise MemoryValidationError(f"{label} is not registered: {artifact_id}")
    _, actual_sha256 = _validated_artifact_file(run_dir, artifact_id, raw)
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise MemoryValidationError(f"{label} hash binding mismatch")


def _validated_artifact_file(
    run_dir: Path,
    artifact_id: str,
    record: Mapping[str, Any],
) -> tuple[Path, str]:
    if record.get("artifact_id") not in {None, artifact_id}:
        raise MemoryValidationError("artifact record identity mismatch")
    raw_path = record.get("path")
    expected_sha256 = record.get("sha256")
    if not isinstance(raw_path, str) or not raw_path:
        raise MemoryValidationError("artifact record has no safe path")
    expected_hash = _sha256(expected_sha256, "artifact record hash")
    relative = PurePosixPath(raw_path)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.as_posix() != raw_path
    ):
        raise MemoryValidationError("artifact path escapes source run")
    candidate = run_dir.joinpath(*relative.parts)
    _reject_symlink_chain(run_dir, candidate)
    run_root = run_dir.resolve()
    if not candidate.resolve(strict=False).is_relative_to(run_root):
        raise MemoryValidationError("artifact path escapes source run")
    if not candidate.is_file():
        raise MemoryValidationError("artifact file is missing")
    if sha256_file(candidate) != expected_hash:
        raise MemoryValidationError("artifact file hash mismatch")
    return candidate, expected_hash


def _reject_symlink_chain(root: Path, candidate: Path) -> None:
    root_resolved = root.resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise MemoryValidationError("path escapes its run directory") from exc
    cursor = root
    if root.is_symlink():
        raise MemoryValidationError("run directory must not be a symlink")
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise MemoryValidationError("path contains a symlink")
    if not candidate.resolve(strict=False).is_relative_to(root_resolved):
        raise MemoryValidationError("path escapes its run directory")


def _default_source_validator(run_dir: Path) -> Sequence[str]:
    # Lazy import avoids making the route registry import Creative memory while
    # CreativeRunContract itself is being registered.
    from hacksome.routes import validate_run

    return validate_run(run_dir)


def _memory_setting(
    settings: MemorySettings | Mapping[str, Any],
    name: str,
) -> Any:
    if isinstance(settings, Mapping):
        if name not in settings:
            raise MemoryValidationError(f"memory setting is missing: {name}")
        return settings[name]
    if not hasattr(settings, name):
        raise MemoryValidationError(f"memory setting is missing: {name}")
    return getattr(settings, name)


def _positive_setting(
    settings: MemorySettings | Mapping[str, Any],
    name: str,
) -> int:
    value = _memory_setting(settings, name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MemoryValidationError(f"{name} must be a positive integer")
    return value


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise MemoryValidationError(f"{label} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MemoryValidationError(f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise MemoryValidationError(f"{label} must include a timezone")
    return parsed


def _diagnostic(
    code: str,
    source_name: str | None,
    detail: str,
) -> MemoryDiagnostic:
    return MemoryDiagnostic(
        code=_identifier(code, "memory diagnostic code"),
        source_name=(
            _text(source_name, "memory diagnostic source name")
            if source_name is not None
            else None
        ),
        detail=_text(detail, "memory diagnostic detail"),
    )


def extract_exact_markdown_section(
    markdown: str,
    heading: str,
    *,
    max_bytes: int = MAX_MEMORY_TEXT_BYTES,
) -> str:
    """Copy one exact H2 body without model summarization or fuzzy matching."""

    if not isinstance(markdown, str) or not markdown:
        raise MemoryValidationError("Markdown must not be empty")
    if not isinstance(heading, str) or not heading.strip():
        raise MemoryValidationError("section heading must not be empty")
    escaped = re.escape(heading)
    matches = list(
        re.finditer(
            rf"(?m)^##[ \t]+{escaped}[ \t]*\r?\n",
            markdown,
        )
    )
    if len(matches) != 1:
        raise MemoryValidationError(
            f"Markdown must contain H2 {heading!r} exactly once"
        )
    start = matches[0].end()
    next_heading = re.search(r"(?m)^#{1,2}[ \t]+", markdown[start:])
    end = start + next_heading.start() if next_heading else len(markdown)
    body = markdown[start:end].strip()
    if not body:
        raise MemoryValidationError(f"Markdown H2 {heading!r} is empty")
    if len(body.encode("utf-8")) > max_bytes:
        raise MemoryValidationError(
            f"Markdown H2 {heading!r} exceeds its extraction budget"
        )
    _text(body, f"Markdown H2 {heading}")
    return body


@dataclass(frozen=True, slots=True)
class MemoryTaskSlot:
    status: MemoryTaskStatus
    task_ref: str | None
    diagnostic_ref: str | None

    @classmethod
    def from_mapping(cls, value: Any) -> MemoryTaskSlot:
        raw = _strict_object(
            value,
            expected=frozenset({"status", "task_ref", "diagnostic_ref"}),
            label="memory recall slot",
        )
        slot = cls(
            status=raw["status"],
            task_ref=_optional_identifier(raw["task_ref"], "memory task ref"),
            diagnostic_ref=_optional_identifier(
                raw["diagnostic_ref"], "memory diagnostic ref"
            ),
        )
        slot.validate()
        return slot

    def validate(self) -> None:
        if self.status not in {
            "succeeded",
            "failed",
            "invalidated",
            "not_started",
        }:
            raise MemoryValidationError("memory task status is invalid")
        if self.status == "not_started":
            if self.task_ref is not None or self.diagnostic_ref is not None:
                raise MemoryValidationError(
                    "not-started memory task cannot have refs"
                )
        elif self.status == "succeeded":
            if self.task_ref is None or self.diagnostic_ref is not None:
                raise MemoryValidationError(
                    "succeeded memory task requires task_ref only"
                )
        elif self.task_ref is None or self.diagnostic_ref is None:
            raise MemoryValidationError(
                "failed/invalidated memory task requires task and diagnostic refs"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "task_ref": self.task_ref,
            "diagnostic_ref": self.diagnostic_ref,
        }


@dataclass(frozen=True, slots=True)
class MemoryRemixSlot:
    slot: int
    status: MemoryTaskStatus
    task_ref: str | None
    challenger_ref: str | None
    diagnostic_ref: str | None

    @classmethod
    def from_mapping(cls, value: Any) -> MemoryRemixSlot:
        raw = _strict_object(
            value,
            expected=frozenset(
                {
                    "slot",
                    "status",
                    "task_ref",
                    "challenger_ref",
                    "diagnostic_ref",
                }
            ),
            label="memory remix slot",
        )
        slot_number = raw["slot"]
        if isinstance(slot_number, bool) or not isinstance(slot_number, int):
            raise MemoryValidationError("memory remix slot must be an integer")
        slot = cls(
            slot=slot_number,
            status=raw["status"],
            task_ref=_optional_identifier(raw["task_ref"], "remix task ref"),
            challenger_ref=_optional_identifier(
                raw["challenger_ref"], "remix challenger ref"
            ),
            diagnostic_ref=_optional_identifier(
                raw["diagnostic_ref"], "remix diagnostic ref"
            ),
        )
        slot.validate()
        return slot

    def validate(self) -> None:
        if self.slot < 1 or self.slot > 2:
            raise MemoryValidationError("memory remix slot must be 1 or 2")
        if self.status not in {
            "succeeded",
            "failed",
            "invalidated",
            "not_started",
        }:
            raise MemoryValidationError("memory remix status is invalid")
        if self.status == "not_started":
            if any(
                value is not None
                for value in (
                    self.task_ref,
                    self.challenger_ref,
                    self.diagnostic_ref,
                )
            ):
                raise MemoryValidationError(
                    "not-started remix slot cannot have refs"
                )
        elif self.status == "succeeded":
            if (
                self.task_ref is None
                or self.diagnostic_ref is not None
            ):
                raise MemoryValidationError(
                    "succeeded remix requires a task ref and no diagnostic"
                )
        elif (
            self.task_ref is None
            or self.diagnostic_ref is None
            or self.challenger_ref is not None
        ):
            raise MemoryValidationError(
                "failed/invalidated remix requires task/diagnostic refs"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "status": self.status,
            "task_ref": self.task_ref,
            "challenger_ref": self.challenger_ref,
            "diagnostic_ref": self.diagnostic_ref,
        }


@dataclass(frozen=True, slots=True)
class MemoryStageSummary:
    status: MemoryStageStatus
    recall: MemoryTaskSlot
    selected_cue_ids: tuple[str, ...]
    remix_slots: tuple[MemoryRemixSlot, ...]

    def __post_init__(self) -> None:
        if self.status not in {
            "disabled",
            "empty",
            "completed",
            "optional_failed",
        }:
            raise MemoryValidationError("memory stage summary status is invalid")
        self.recall.validate()
        if len(self.selected_cue_ids) != len(set(self.selected_cue_ids)):
            raise MemoryValidationError("selected memory cue IDs must be unique")
        if len(self.selected_cue_ids) > 8:
            raise MemoryValidationError("selected memory cues exceed hard limit 8")
        slot_numbers = tuple(slot.slot for slot in self.remix_slots)
        if slot_numbers != tuple(range(1, len(self.remix_slots) + 1)):
            raise MemoryValidationError(
                "memory remix slots must be stable and contiguous"
            )
        if len(self.remix_slots) > 2:
            raise MemoryValidationError("memory remix slots exceed hard limit 2")
        for slot in self.remix_slots:
            slot.validate()
        failures = self.recall.status in {"failed", "invalidated"} or any(
            slot.status in {"failed", "invalidated"} for slot in self.remix_slots
        )
        if self.status in {"disabled", "empty"}:
            if (
                self.recall.status != "not_started"
                or self.selected_cue_ids
                or any(slot.status != "not_started" for slot in self.remix_slots)
            ):
                raise MemoryValidationError(
                    "disabled/empty memory summary cannot start Agent tasks"
                )
        elif self.status == "completed":
            if self.recall.status != "succeeded" or failures:
                raise MemoryValidationError(
                    "completed memory summary requires successful Recall"
                )
        elif not failures:
            raise MemoryValidationError(
                "optional_failed memory summary requires a failed branch"
            )
        if self.recall.status in {"failed", "invalidated"} and any(
            slot.status != "not_started" for slot in self.remix_slots
        ):
            raise MemoryValidationError(
                "Remix cannot start after Recall failure"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> MemoryStageSummary:
        raw = _strict_object(
            value,
            expected=frozenset(
                {"status", "recall", "selected_cue_ids", "remix_slots"}
            ),
            label="memory stage summary",
        )
        if not isinstance(raw["remix_slots"], list):
            raise MemoryValidationError("memory remix_slots must be an array")
        return cls(
            status=raw["status"],
            recall=MemoryTaskSlot.from_mapping(raw["recall"]),
            selected_cue_ids=_string_tuple(
                raw["selected_cue_ids"], "selected memory cue IDs"
            ),
            remix_slots=tuple(
                MemoryRemixSlot.from_mapping(item)
                for item in raw["remix_slots"]
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "recall": self.recall.to_dict(),
            "selected_cue_ids": list(self.selected_cue_ids),
            "remix_slots": [slot.to_dict() for slot in self.remix_slots],
        }


def _optional_identifier(value: Any, label: str) -> str | None:
    return None if value is None else _identifier(value, label)


@dataclass(frozen=True, slots=True)
class MemoryCue:
    cue_id: str
    source_memory_refs: tuple[MemoryCapsuleRef, ...]
    role: Literal["inspire", "avoid"]
    transferable_pattern: str
    why_relevant: str
    current_atom_refs: tuple[str, ...]
    related_concept_refs: tuple[str, ...]
    elements_that_must_not_be_copied: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cue_id": self.cue_id,
            "source_memory_refs": [
                reference.to_dict() for reference in self.source_memory_refs
            ],
            "role": self.role,
            "transferable_pattern": self.transferable_pattern,
            "why_relevant": self.why_relevant,
            "current_atom_refs": list(self.current_atom_refs),
            "related_concept_refs": list(self.related_concept_refs),
            "elements_that_must_not_be_copied": list(
                self.elements_that_must_not_be_copied
            ),
        }


def validate_memory_inspiration_packet(
    value: Any,
    *,
    snapshot: IdeaMemorySnapshot,
    current_atom_refs: Sequence[str],
    related_concept_refs: Sequence[str] = (),
    max_cues: int = 8,
) -> tuple[MemoryCue, ...]:
    """Validate Recall output against exact snapshot and current-run refs."""

    if isinstance(max_cues, bool) or not 0 <= max_cues <= 8:
        raise MemoryValidationError("max_cues must be between 0 and 8")
    raw = _strict_object(
        value,
        expected=frozenset({"cues", "no_relevant_memory_reason"}),
        label="memory inspiration packet",
    )
    raw_cues = raw["cues"]
    if not isinstance(raw_cues, list):
        raise MemoryValidationError("memory cues must be an array")
    if len(raw_cues) > max_cues:
        raise MemoryValidationError("memory cue count exceeds its limit")
    allowed_refs = {
        capsule.memory_ref.stable_key: capsule.memory_ref
        for capsule in snapshot.entries
    }
    allowed_atoms = frozenset(current_atom_refs)
    allowed_concepts = frozenset(related_concept_refs)
    cues: list[MemoryCue] = []
    for raw_cue in raw_cues:
        cue_raw = _strict_object(
            raw_cue,
            expected=frozenset(
                {
                    "cue_id",
                    "source_memory_refs",
                    "role",
                    "transferable_pattern",
                    "why_relevant",
                    "current_atom_refs",
                    "related_concept_refs",
                    "elements_that_must_not_be_copied",
                }
            ),
            label="memory cue",
        )
        raw_refs = cue_raw["source_memory_refs"]
        if not isinstance(raw_refs, list) or not raw_refs:
            raise MemoryValidationError(
                "memory cue requires source_memory_refs"
            )
        refs = tuple(MemoryCapsuleRef.from_mapping(item) for item in raw_refs)
        if any(reference.stable_key not in allowed_refs for reference in refs):
            raise MemoryValidationError(
                "memory cue references a capsule outside the frozen snapshot"
            )
        role = cue_raw["role"]
        if role not in {"inspire", "avoid"}:
            raise MemoryValidationError("memory cue role is invalid")
        atom_refs = _string_tuple(
            cue_raw["current_atom_refs"],
            "memory cue current atom refs",
            allow_empty=False,
        )
        if any(reference not in allowed_atoms for reference in atom_refs):
            raise MemoryValidationError("memory cue references an unknown current Atom")
        concept_refs = _string_tuple(
            cue_raw["related_concept_refs"],
            "memory cue related concept refs",
        )
        if any(reference not in allowed_concepts for reference in concept_refs):
            raise MemoryValidationError(
                "memory cue references an unknown current Concept"
            )
        cues.append(
            MemoryCue(
                cue_id=_identifier(cue_raw["cue_id"], "memory cue id"),
                source_memory_refs=refs,
                role=role,
                transferable_pattern=_text(
                    cue_raw["transferable_pattern"],
                    "memory transferable pattern",
                ),
                why_relevant=_text(
                    cue_raw["why_relevant"], "memory relevance"
                ),
                current_atom_refs=atom_refs,
                related_concept_refs=concept_refs,
                elements_that_must_not_be_copied=_string_tuple(
                    cue_raw["elements_that_must_not_be_copied"],
                    "memory elements not to copy",
                    identifiers=False,
                ),
            )
        )
    cue_ids = tuple(cue.cue_id for cue in cues)
    if len(cue_ids) != len(set(cue_ids)):
        raise MemoryValidationError("memory cue IDs must be unique")
    deduplicated = deduplicate_memory_cues(cues)
    if len(deduplicated) != len(cues):
        raise MemoryValidationError("memory cues contain duplicate patterns")
    no_relevant_reason = raw["no_relevant_memory_reason"]
    if cues:
        if no_relevant_reason is not None:
            raise MemoryValidationError(
                "non-empty memory packet cannot have no-memory reason"
            )
    else:
        _text(no_relevant_reason, "no relevant memory reason")
    return tuple(cues)


def deduplicate_memory_cues(cues: Sequence[MemoryCue]) -> tuple[MemoryCue, ...]:
    """Stable first-wins deduplication for controller-owned cue collections."""

    seen: set[tuple[str, tuple[tuple[str, ...], ...]]] = set()
    result: list[MemoryCue] = []
    for cue in cues:
        key = (
            normalize_memory_text(cue.transferable_pattern),
            tuple(sorted(reference.stable_key for reference in cue.source_memory_refs)),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(cue)
    return tuple(result)


def normalize_memory_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"\w+", normalized, flags=re.UNICODE))


def copy_risk_reasons(
    *,
    candidate_hook: str,
    candidate_mechanism: str,
    candidate_reveal: str,
    source_capsules: Sequence[MemoryCapsule],
) -> tuple[str, ...]:
    """Return deterministic copy-risk codes for a Remix candidate."""

    hook = normalize_memory_text(candidate_hook)
    mechanism = normalize_memory_text(candidate_mechanism)
    reveal = normalize_memory_text(candidate_reveal)
    reasons: list[str] = []
    for capsule in source_capsules:
        entry = capsule.entry
        if hook and hook == normalize_memory_text(entry.one_sentence_hook):
            reasons.append("normalized_hook_match")
        if (
            mechanism
            and reveal
            and mechanism == normalize_memory_text(entry.core_mechanism)
            and reveal == normalize_memory_text(entry.reveal_pattern)
        ):
            reasons.append("mechanism_reveal_copy")
    return tuple(dict.fromkeys(reasons))


def validate_remix_provenance(
    *,
    current_atom_refs: Sequence[str],
    memory_source_refs: Sequence[MemoryCapsuleRef],
    cue_refs: Sequence[str],
    primary_territory_ref: str,
    atom_territories: Mapping[str, str],
    snapshot: IdeaMemorySnapshot,
    cues: Sequence[MemoryCue],
) -> None:
    """Validate current-Atom × frozen-memory provenance for one challenger."""

    if not current_atom_refs:
        raise MemoryValidationError("memory challenger requires a current Atom")
    if not memory_source_refs:
        raise MemoryValidationError("memory challenger requires a memory source")
    if not cue_refs:
        raise MemoryValidationError("memory challenger requires a memory cue")
    if len(current_atom_refs) != len(set(current_atom_refs)):
        raise MemoryValidationError("challenger current Atom refs contain duplicates")
    if any(reference not in atom_territories for reference in current_atom_refs):
        raise MemoryValidationError("challenger references an unknown current Atom")
    allowed_territories = {
        atom_territories[reference] for reference in current_atom_refs
    }
    if primary_territory_ref not in allowed_territories:
        raise MemoryValidationError(
            "challenger primary territory is not owned by a current Atom"
        )
    snapshot_refs = {
        capsule.memory_ref.stable_key for capsule in snapshot.entries
    }
    if any(reference.stable_key not in snapshot_refs for reference in memory_source_refs):
        raise MemoryValidationError(
            "challenger references memory outside the frozen snapshot"
        )
    cue_by_id = {cue.cue_id: cue for cue in cues}
    if any(cue_ref not in cue_by_id for cue_ref in cue_refs):
        raise MemoryValidationError("challenger references an unknown memory cue")
    cue_memory_refs = {
        reference.stable_key
        for cue_ref in cue_refs
        for reference in cue_by_id[cue_ref].source_memory_refs
    }
    if any(
        reference.stable_key not in cue_memory_refs
        for reference in memory_source_refs
    ):
        raise MemoryValidationError(
            "challenger memory refs are not supported by its selected cues"
        )


def validate_challenger_count(
    challenger_refs: Sequence[str],
    *,
    max_challengers: int = 2,
) -> tuple[str, ...]:
    if (
        isinstance(max_challengers, bool)
        or max_challengers < 0
        or max_challengers > 2
    ):
        raise MemoryValidationError("max_challengers must be between 0 and 2")
    refs = tuple(
        _identifier(reference, "memory challenger ref")
        for reference in challenger_refs
    )
    if len(refs) > max_challengers:
        raise MemoryValidationError("memory challenger count exceeds its limit")
    if len(refs) != len(set(refs)):
        raise MemoryValidationError("memory challenger refs must be unique")
    return refs


def canonical_capsule_bytes(capsule: MemoryCapsule) -> bytes:
    """Expose the exact canonical bytes used for copied-capsule hashing."""

    return canonical_json_bytes(capsule.canonical_payload())
