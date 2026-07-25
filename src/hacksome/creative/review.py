"""Human-curation domain contracts and append-only review ledgers.

The HTTP server is deliberately a thin adapter.  This module owns all
canonical request hashing, round/revision binding, immutable receipt history,
feedback-fragment provenance, coverage, and resolution validation.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Literal, Mapping, Sequence, cast

from hacksome.creative.contracts import (
    CreativeContractError,
    ZeroReasonCode,
    parse_concept_revision_ref,
)
from hacksome.hub import RunHub, utc_now
from hacksome.state import (
    StateConflictError,
    StateError,
    advisory_lease,
    canonical_json_bytes,
    normalize_json,
    read_jsonl,
    sha256_json,
    sha256_text,
)


MAX_SHORTLIST = 8
MAX_REVIEWER_NAME = 80
MAX_ONE_SENTENCE_RETELL = 400
MAX_SHARE_TARGET = 200
MAX_CONCEPT_COMMENT = 4_000
MAX_PAIR_REASON = 1_000
MAX_OVERALL_COMMENT = 4_000
MAX_CURATOR_INSTRUCTION = 4_000
MAX_RESOLUTION_REASON = 4_000
MAX_APPROVED_FRAGMENTS_PER_ACTION = 12
MAX_APPROVED_FEEDBACK_BYTES = 24 * 1024

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROUND_ID = re.compile(r"^creative-review-round-[0-9]{3}$")
_BATCH_ID = re.compile(r"^creative-review-batch-r[0-9]{3}$")
_PAIR_ID = re.compile(r"^creative-pair-[0-9]{3}$")

ReviewBatchStatus = Literal["ready", "skipped_empty"]
ReviewRoundStatus = Literal["open", "closed"]
Independence = Literal["pre_reveal", "post_reveal"]
ReactionValue = Literal["yes", "maybe", "no"]
ShareImpulse = Literal["immediate", "maybe", "no"]
DemoConfidence = Literal["yes", "maybe", "no"]
Recommendation = Literal["keep", "revise", "reject", "taste_veto", "no_opinion"]
PairPreference = Literal["left", "right", "both", "neither", "cannot_compare"]
ResolutionActionName = Literal["keep", "revise", "reject", "taste_veto", "merge"]

_REACTION_KEYS = ("surprise", "fun", "mystery", "confusion")
_REACTION_VALUES = frozenset({"yes", "maybe", "no"})
_SHARE_IMPULSES = frozenset({"immediate", "maybe", "no"})
_DEMO_CONFIDENCE_VALUES = frozenset({"yes", "maybe", "no"})
_REVIEW_SCHEMA_VERSIONS = frozenset({1, 2})
_RECOMMENDATIONS = frozenset({"keep", "revise", "reject", "taste_veto", "no_opinion"})
_PAIR_PREFERENCES = frozenset({"left", "right", "both", "neither", "cannot_compare"})
_RESOLUTION_ACTIONS = frozenset({"keep", "revise", "reject", "taste_veto", "merge"})
_SKIP_REASONS = frozenset(
    {
        ZeroReasonCode.NO_CONCEPTS_GENERATED.value,
        ZeroReasonCode.ALL_CANDIDATES_FAILED_HOOK.value,
        "all_candidates_failed_concept_screen",
        ZeroReasonCode.SHORTLIST_EMPTY.value,
    }
)


class ReviewError(ValueError):
    """Base class for invalid human-curation data."""


class ReviewValidationError(ReviewError):
    """A request is malformed or violates a domain invariant."""


class ReviewConflictError(ReviewError):
    """A stable ID or append-only history conflicts with persisted data."""


class ReviewStaleError(ReviewConflictError):
    """A request is bound to an outdated round, revision, or content hash."""


class ReviewClosedError(ReviewConflictError):
    """The review round already has an immutable resolution."""


@dataclass(frozen=True, slots=True)
class ConceptBinding:
    """One exact Concept revision admitted to the human shortlist."""

    concept_ref: str
    concept_sha256: str

    def __post_init__(self) -> None:
        try:
            parse_concept_revision_ref(self.concept_ref)
        except CreativeContractError as exc:
            raise ReviewValidationError(str(exc)) from exc
        _require_sha256(self.concept_sha256, "concept_sha256")

    def to_dict(self) -> dict[str, str]:
        return {
            "concept_ref": self.concept_ref,
            "concept_sha256": self.concept_sha256,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ConceptBinding:
        value = _exact_object(
            raw,
            required={"concept_ref", "concept_sha256"},
            label="concept binding",
        )
        return cls(
            concept_ref=_require_string(value["concept_ref"], "concept_ref"),
            concept_sha256=_require_string(value["concept_sha256"], "concept_sha256"),
        )


@dataclass(frozen=True, slots=True)
class ReviewPair:
    """A controller-owned canonical comparison pair."""

    pair_id: str
    left_ref: str
    right_ref: str
    left_sha256: str
    right_sha256: str

    def __post_init__(self) -> None:
        _require_pattern(self.pair_id, _PAIR_ID, "pair_id")
        if self.left_ref == self.right_ref:
            raise ReviewValidationError(
                "a review pair cannot compare a Concept to itself"
            )
        for label, reference in (
            ("left_ref", self.left_ref),
            ("right_ref", self.right_ref),
        ):
            try:
                parse_concept_revision_ref(reference)
            except CreativeContractError as exc:
                raise ReviewValidationError(f"{label}: {exc}") from exc
        _require_sha256(self.left_sha256, "left_sha256")
        _require_sha256(self.right_sha256, "right_sha256")

    def to_dict(self) -> dict[str, str]:
        return {
            "pair_id": self.pair_id,
            "left_ref": self.left_ref,
            "right_ref": self.right_ref,
            "left_sha256": self.left_sha256,
            "right_sha256": self.right_sha256,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ReviewPair:
        value = _exact_object(
            raw,
            required={
                "pair_id",
                "left_ref",
                "right_ref",
                "left_sha256",
                "right_sha256",
            },
            label="review pair",
        )
        return cls(
            pair_id=_require_string(value["pair_id"], "pair_id"),
            left_ref=_require_string(value["left_ref"], "left_ref"),
            right_ref=_require_string(value["right_ref"], "right_ref"),
            left_sha256=_require_string(value["left_sha256"], "left_sha256"),
            right_sha256=_require_string(value["right_sha256"], "right_sha256"),
        )


@dataclass(frozen=True, slots=True)
class DisplayPair:
    """Reviewer-specific presentation order for a canonical pair."""

    pair_id: str
    left_ref: str
    right_ref: str
    left_sha256: str
    right_sha256: str
    swapped: bool


def canonical_adjacent_pairs(
    concepts: Sequence[ConceptBinding],
) -> tuple[ReviewPair, ...]:
    """Return a connected, bounded ring over the canonical shortlist order."""

    ordered = tuple(sorted(concepts, key=lambda item: item.concept_ref))
    if len(ordered) > MAX_SHORTLIST:
        raise ReviewValidationError(
            f"human shortlist cannot contain more than {MAX_SHORTLIST} Concepts"
        )
    if len({item.concept_ref for item in ordered}) != len(ordered):
        raise ReviewValidationError("human shortlist contains duplicate Concept refs")
    if len(ordered) < 2:
        return ()
    indexes = (
        [(0, 1)]
        if len(ordered) == 2
        else [
            *((index, index + 1) for index in range(len(ordered) - 1)),
            (len(ordered) - 1, 0),
        ]
    )
    return tuple(
        ReviewPair(
            pair_id=f"creative-pair-{index:03d}",
            left_ref=ordered[left].concept_ref,
            right_ref=ordered[right].concept_ref,
            left_sha256=ordered[left].concept_sha256,
            right_sha256=ordered[right].concept_sha256,
        )
        for index, (left, right) in enumerate(indexes[:MAX_SHORTLIST], start=1)
    )


def display_pair_for_reviewer(
    pair: ReviewPair,
    reviewer_id: str,
) -> DisplayPair:
    """Deterministically swap only presentation order to reduce side bias."""

    _require_safe_id(reviewer_id, "reviewer_id")
    swapped = int(sha256_text(f"{reviewer_id}:{pair.pair_id}")[-1], 16) % 2 == 1
    if not swapped:
        return DisplayPair(**pair.to_dict(), swapped=False)
    return DisplayPair(
        pair_id=pair.pair_id,
        left_ref=pair.right_ref,
        right_ref=pair.left_ref,
        left_sha256=pair.right_sha256,
        right_sha256=pair.left_sha256,
        swapped=True,
    )


@dataclass(frozen=True, slots=True)
class ReviewBatch:
    """Immutable C6 shortlist binding, including the legal empty outcome."""

    batch_id: str
    run_id: str
    status: ReviewBatchStatus
    concepts: tuple[ConceptBinding, ...]
    skip_reason: str | None = None

    def __post_init__(self) -> None:
        _require_pattern(self.batch_id, _BATCH_ID, "batch_id")
        _require_safe_id(self.run_id, "run_id")
        if self.status not in {"ready", "skipped_empty"}:
            raise ReviewValidationError(
                "review batch status must be ready or skipped_empty"
            )
        if len(self.concepts) > MAX_SHORTLIST:
            raise ReviewValidationError(
                f"human shortlist cannot contain more than {MAX_SHORTLIST} Concepts"
            )
        if (
            tuple(sorted(self.concepts, key=lambda item: item.concept_ref))
            != self.concepts
        ):
            raise ReviewValidationError("review batch Concepts must be sorted by ref")
        if len({item.concept_ref for item in self.concepts}) != len(self.concepts):
            raise ReviewValidationError("review batch contains duplicate Concept refs")
        if self.status == "ready":
            if not self.concepts:
                raise ReviewValidationError(
                    "ready review batch requires at least one Concept"
                )
            if self.skip_reason is not None:
                raise ReviewValidationError(
                    "ready review batch cannot have skip_reason"
                )
        else:
            if self.concepts:
                raise ReviewValidationError(
                    "skipped_empty batch cannot contain Concepts"
                )
            if self.skip_reason not in _SKIP_REASONS:
                raise ReviewValidationError(
                    "skipped_empty batch requires a supported skip_reason"
                )

    @property
    def concept_refs(self) -> tuple[str, ...]:
        return tuple(item.concept_ref for item in self.concepts)

    @property
    def batch_sha256(self) -> str:
        return sha256_json(self._hash_payload())

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "run_id": self.run_id,
            "status": self.status,
            "concepts": [item.to_dict() for item in self.concepts],
            "skip_reason": self.skip_reason,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._hash_payload(), "batch_sha256": self.batch_sha256}

    @classmethod
    def build(
        cls,
        *,
        run_id: str,
        concepts: Sequence[ConceptBinding],
        batch_id: str = "creative-review-batch-r001",
        skip_reason: str | None = None,
    ) -> ReviewBatch:
        ordered = tuple(sorted(concepts, key=lambda item: item.concept_ref))
        return cls(
            batch_id=batch_id,
            run_id=run_id,
            status="ready" if ordered else "skipped_empty",
            concepts=ordered,
            skip_reason=skip_reason,
        )

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ReviewBatch:
        value = _exact_object(
            raw,
            required={
                "batch_id",
                "run_id",
                "status",
                "concepts",
                "skip_reason",
                "batch_sha256",
            },
            label="review batch",
        )
        concepts = _object_list(value["concepts"], "review batch concepts")
        batch = cls(
            batch_id=_require_string(value["batch_id"], "batch_id"),
            run_id=_require_string(value["run_id"], "run_id"),
            status=_require_string(value["status"], "status"),  # type: ignore[arg-type]
            concepts=tuple(ConceptBinding.from_dict(item) for item in concepts),
            skip_reason=_optional_string(value["skip_reason"], "skip_reason"),
        )
        if value["batch_sha256"] != batch.batch_sha256:
            raise ReviewStaleError("review batch hash mismatch")
        return batch


@dataclass(frozen=True, slots=True)
class ReviewRound:
    """One immutable review target set plus mutable open/closed projection."""

    round_id: str
    run_id: str
    batch_id: str
    batch_sha256: str
    concepts: tuple[ConceptBinding, ...]
    pairs: tuple[ReviewPair, ...]
    status: ReviewRoundStatus = "open"
    resolution_id: str | None = None
    resolution_sha256: str | None = None

    def __post_init__(self) -> None:
        _require_pattern(self.round_id, _ROUND_ID, "round_id")
        _require_safe_id(self.run_id, "run_id")
        _require_pattern(self.batch_id, _BATCH_ID, "batch_id")
        _require_sha256(self.batch_sha256, "batch_sha256")
        if not self.concepts or len(self.concepts) > MAX_SHORTLIST:
            raise ReviewValidationError(
                f"review round requires 1 through {MAX_SHORTLIST} Concepts"
            )
        if (
            tuple(sorted(self.concepts, key=lambda item: item.concept_ref))
            != self.concepts
        ):
            raise ReviewValidationError("review round Concepts must be sorted by ref")
        expected_pairs = canonical_adjacent_pairs(self.concepts)
        if self.pairs != expected_pairs:
            raise ReviewValidationError(
                "review round pairs are not the canonical adjacent set"
            )
        if self.status not in {"open", "closed"}:
            raise ReviewValidationError("review round status must be open or closed")
        if self.status == "open":
            if self.resolution_id is not None or self.resolution_sha256 is not None:
                raise ReviewValidationError(
                    "open review round cannot name a resolution"
                )
        else:
            _require_safe_id(self.resolution_id, "resolution_id")
            _require_sha256(self.resolution_sha256, "resolution_sha256")

    @property
    def bindings(self) -> Mapping[str, ConceptBinding]:
        return MappingProxyType({item.concept_ref: item for item in self.concepts})

    @property
    def pair_index(self) -> Mapping[str, ReviewPair]:
        return MappingProxyType({item.pair_id: item for item in self.pairs})

    @property
    def round_sha256(self) -> str:
        return sha256_json(self._binding_payload())

    def _binding_payload(self) -> dict[str, Any]:
        return {
            "round_id": self.round_id,
            "run_id": self.run_id,
            "batch_id": self.batch_id,
            "batch_sha256": self.batch_sha256,
            "concepts": [item.to_dict() for item in self.concepts],
            "pairs": [item.to_dict() for item in self.pairs],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._binding_payload(),
            "round_sha256": self.round_sha256,
            "status": self.status,
            "resolution_id": self.resolution_id,
            "resolution_sha256": self.resolution_sha256,
        }

    @classmethod
    def open(
        cls,
        batch: ReviewBatch,
        *,
        round_id: str = "creative-review-round-001",
    ) -> ReviewRound:
        if batch.status != "ready":
            raise ReviewValidationError(
                "cannot open a round for a skipped review batch"
            )
        return cls(
            round_id=round_id,
            run_id=batch.run_id,
            batch_id=batch.batch_id,
            batch_sha256=batch.batch_sha256,
            concepts=batch.concepts,
            pairs=canonical_adjacent_pairs(batch.concepts),
        )

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ReviewRound:
        value = _exact_object(
            raw,
            required={
                "round_id",
                "run_id",
                "batch_id",
                "batch_sha256",
                "concepts",
                "pairs",
                "round_sha256",
                "status",
                "resolution_id",
                "resolution_sha256",
            },
            label="review round",
        )
        round_value = cls(
            round_id=_require_string(value["round_id"], "round_id"),
            run_id=_require_string(value["run_id"], "run_id"),
            batch_id=_require_string(value["batch_id"], "batch_id"),
            batch_sha256=_require_string(value["batch_sha256"], "batch_sha256"),
            concepts=tuple(
                ConceptBinding.from_dict(item)
                for item in _object_list(value["concepts"], "round concepts")
            ),
            pairs=tuple(
                ReviewPair.from_dict(item)
                for item in _object_list(value["pairs"], "round pairs")
            ),
            status=_require_string(value["status"], "status"),  # type: ignore[arg-type]
            resolution_id=_optional_string(value["resolution_id"], "resolution_id"),
            resolution_sha256=_optional_string(
                value["resolution_sha256"], "resolution_sha256"
            ),
        )
        if value["round_sha256"] != round_value.round_sha256:
            raise ReviewStaleError("review round hash mismatch")
        return round_value

    def closed_by(self, resolution: HumanResolution) -> ReviewRound:
        if resolution.round_id != self.round_id:
            raise ReviewStaleError("resolution belongs to a different review round")
        return replace(
            self,
            status="closed",
            resolution_id=resolution.resolution_id,
            resolution_sha256=resolution.resolution_sha256,
        )


@dataclass(frozen=True, slots=True)
class ConceptReview:
    feedback_ref: str
    feedback_sha256: str
    concept_ref: str
    concept_sha256: str
    one_sentence_retell: str
    share_target: str
    share_impulse: ShareImpulse | None
    demo_confidence: DemoConfidence | None
    reactions: Mapping[str, str]
    recommendation: Recommendation
    comment: str

    def fragment_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "feedback_ref": self.feedback_ref,
            "concept_ref": self.concept_ref,
            "concept_sha256": self.concept_sha256,
            "one_sentence_retell": self.one_sentence_retell,
            "share_target": self.share_target,
            "reactions": dict(self.reactions),
            "recommendation": self.recommendation,
            "comment": self.comment,
        }
        if self.share_impulse is not None:
            payload["share_impulse"] = self.share_impulse
        if self.demo_confidence is not None:
            payload["demo_confidence"] = self.demo_confidence
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.fragment_payload(),
            "feedback_sha256": self.feedback_sha256,
        }


@dataclass(frozen=True, slots=True)
class PairwiseReview:
    feedback_ref: str
    feedback_sha256: str
    pair_id: str
    left_ref: str
    right_ref: str
    left_sha256: str
    right_sha256: str
    preference: PairPreference
    reason: str

    def fragment_payload(self) -> dict[str, Any]:
        return {
            "feedback_ref": self.feedback_ref,
            "pair_id": self.pair_id,
            "left_ref": self.left_ref,
            "right_ref": self.right_ref,
            "left_sha256": self.left_sha256,
            "right_sha256": self.right_sha256,
            "preference": self.preference,
            "reason": self.reason,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.fragment_payload(),
            "feedback_sha256": self.feedback_sha256,
        }


@dataclass(frozen=True, slots=True)
class HumanReview:
    schema_version: int
    review_id: str
    round_id: str
    round_sha256: str
    run_id: str
    reviewer_id: str
    reviewer_name: str
    submitted_at: str
    request_sha256: str
    independence: Independence
    concept_reviews: tuple[ConceptReview, ...]
    pairwise: tuple[PairwiseReview, ...]
    overall_comment: str
    overall_feedback_ref: str
    overall_feedback_sha256: str
    supersedes_review_id: str | None

    def overall_fragment_payload(self) -> dict[str, Any]:
        return {
            "feedback_ref": self.overall_feedback_ref,
            "overall_comment": self.overall_comment,
        }

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "review_id": self.review_id,
            "round_id": self.round_id,
            "round_sha256": self.round_sha256,
            "run_id": self.run_id,
            "reviewer_id": self.reviewer_id,
            "reviewer_name": self.reviewer_name,
            "submitted_at": self.submitted_at,
            "request_sha256": self.request_sha256,
            "independence": self.independence,
            "concept_reviews": [item.to_dict() for item in self.concept_reviews],
            "pairwise": [item.to_dict() for item in self.pairwise],
            "overall_comment": self.overall_comment,
            "overall_feedback_ref": self.overall_feedback_ref,
            "overall_feedback_sha256": self.overall_feedback_sha256,
            "supersedes_review_id": self.supersedes_review_id,
        }
        if self.schema_version >= 2:
            payload["schema_version"] = self.schema_version
        return payload

    def request_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "review_id": self.review_id,
            "round_id": self.round_id,
            "round_sha256": self.round_sha256,
            "run_id": self.run_id,
            "reviewer_id": self.reviewer_id,
            "reviewer_name": self.reviewer_name,
            "concept_reviews": [
                {
                    key: value
                    for key, value in item.fragment_payload().items()
                    if key != "feedback_ref"
                }
                for item in self.concept_reviews
            ],
            "pairwise": [
                {
                    key: value
                    for key, value in item.fragment_payload().items()
                    if key != "feedback_ref"
                }
                for item in self.pairwise
            ],
            "overall_comment": self.overall_comment,
            "supersedes_review_id": self.supersedes_review_id,
        }
        if self.schema_version >= 2:
            payload["schema_version"] = self.schema_version
        return payload


@dataclass(frozen=True, slots=True)
class FeedbackFragment:
    feedback_ref: str
    feedback_sha256: str
    kind: Literal["concept", "pair", "overall"]
    review_id: str
    reviewer_id: str
    related_concept_refs: tuple[str, ...]
    payload: Mapping[str, Any]
    has_guidance: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "feedback_ref": self.feedback_ref,
            "feedback_sha256": self.feedback_sha256,
            "kind": self.kind,
            "review_id": self.review_id,
            "reviewer_id": self.reviewer_id,
            "related_concept_refs": list(self.related_concept_refs),
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class ApprovedFeedback:
    feedback_ref: str
    feedback_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "feedback_ref": self.feedback_ref,
            "feedback_sha256": self.feedback_sha256,
        }


@dataclass(frozen=True, slots=True)
class ResolutionAction:
    concept_ref: str
    action: ResolutionActionName
    approved_feedback: tuple[ApprovedFeedback, ...]
    curator_instruction: str
    curator_instruction_sha256: str | None
    reason: str
    merge_group_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_ref": self.concept_ref,
            "action": self.action,
            "approved_feedback": [item.to_dict() for item in self.approved_feedback],
            "curator_instruction": self.curator_instruction,
            "curator_instruction_sha256": self.curator_instruction_sha256,
            "reason": self.reason,
            "merge_group_id": self.merge_group_id,
        }


@dataclass(frozen=True, slots=True)
class MergeGroup:
    merge_group_id: str
    source_refs: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "merge_group_id": self.merge_group_id,
            "source_refs": list(self.source_refs),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class HumanResolution:
    resolution_id: str
    run_id: str
    curator_name: str
    round_id: str
    round_sha256: str
    actions: tuple[ResolutionAction, ...]
    merge_groups: tuple[MergeGroup, ...]
    uncovered_concept_refs: tuple[str, ...]
    coverage_override_reason: str | None
    latest_receipt_set_sha256: str
    approved_feedback_set_sha256: str
    closed_at: str
    request_sha256: str
    resolution_sha256: str

    def hash_payload(self) -> dict[str, Any]:
        return {
            "resolution_id": self.resolution_id,
            "run_id": self.run_id,
            "curator_name": self.curator_name,
            "round_id": self.round_id,
            "round_sha256": self.round_sha256,
            "actions": [item.to_dict() for item in self.actions],
            "merge_groups": [item.to_dict() for item in self.merge_groups],
            "uncovered_concept_refs": list(self.uncovered_concept_refs),
            "coverage_override_reason": self.coverage_override_reason,
            "latest_receipt_set_sha256": self.latest_receipt_set_sha256,
            "approved_feedback_set_sha256": self.approved_feedback_set_sha256,
            "closed_at": self.closed_at,
            "request_sha256": self.request_sha256,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.hash_payload(), "resolution_sha256": self.resolution_sha256}

    def request_payload(self) -> dict[str, Any]:
        return {
            "resolution_id": self.resolution_id,
            "run_id": self.run_id,
            "curator_name": self.curator_name,
            "round_id": self.round_id,
            "round_sha256": self.round_sha256,
            "actions": [
                {
                    "concept_ref": item.concept_ref,
                    "action": item.action,
                    "approved_feedback": [
                        approved.to_dict() for approved in item.approved_feedback
                    ],
                    "curator_instruction": item.curator_instruction,
                    "reason": item.reason,
                    "merge_group_id": item.merge_group_id,
                }
                for item in self.actions
            ],
            "merge_groups": [item.to_dict() for item in self.merge_groups],
            "coverage_override_reason": self.coverage_override_reason,
        }

    def wait_close_payload(self) -> dict[str, Any]:
        """Return the exact wait projection the workflow should persist."""

        return {
            "status": "closed",
            "round_id": self.round_id,
            "round_sha256": self.round_sha256,
            "resolution_id": self.resolution_id,
            "resolution_sha256": self.resolution_sha256,
            "latest_receipt_set_sha256": self.latest_receipt_set_sha256,
            "approved_feedback_set_sha256": self.approved_feedback_set_sha256,
        }


@dataclass(frozen=True, slots=True)
class ConceptCoverage:
    concept_ref: str
    reviewer_ids: tuple[str, ...]

    @property
    def covered(self) -> bool:
        return bool(self.reviewer_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_ref": self.concept_ref,
            "reviewer_ids": list(self.reviewer_ids),
            "covered": self.covered,
        }


@dataclass(frozen=True, slots=True)
class ReviewSnapshot:
    """Consistent domain snapshot; role-specific redaction remains server-owned."""

    round: ReviewRound
    latest_reviews: tuple[HumanReview, ...]
    coverage: tuple[ConceptCoverage, ...]
    latest_receipt_set_sha256: str
    resolution: HumanResolution | None

    def to_dict(self, *, include_reviews: bool = False) -> dict[str, Any]:
        value: dict[str, Any] = {
            "round": self.round.to_dict(),
            "coverage": [item.to_dict() for item in self.coverage],
            "latest_receipt_set_sha256": self.latest_receipt_set_sha256,
            "resolution": (
                self.resolution.to_dict() if self.resolution is not None else None
            ),
        }
        if include_reviews:
            value["latest_reviews"] = [item.to_dict() for item in self.latest_reviews]
        return value


_STORE_LOCKS: dict[str, threading.RLock] = {}
_STORE_LOCKS_GUARD = threading.Lock()


def _store_lock(path: Path) -> threading.RLock:
    key = str(path.resolve(strict=False))
    with _STORE_LOCKS_GUARD:
        return _STORE_LOCKS.setdefault(key, threading.RLock())


class ReviewStore:
    """Validate and append one review round through RunHub's durable outbox."""

    def __init__(
        self,
        hub: RunHub,
        review_round: ReviewRound,
        *,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        if hub.route_id != "creative":
            raise ReviewValidationError("human review store requires a Creative run")
        if hub.run_id != review_round.run_id:
            raise ReviewStaleError("review round run_id does not match RunHub")
        route = hub.load_state().get("route")
        contract_version = (
            route.get("contract_version") if isinstance(route, dict) else None
        )
        if contract_version == "1":
            self.schema_version = 1
        elif contract_version == "2":
            self.schema_version = 2
        else:
            raise ReviewValidationError(
                "human review store requires a supported Creative contract"
            )
        self.hub = hub
        self.round = review_round
        self._clock = clock
        self._lock = _store_lock(hub.run_dir)
        self.reviews_path = hub.run_dir / "human-reviews.jsonl"
        self.resolutions_path = hub.run_dir / "human-resolutions.jsonl"

    def initialize(self) -> None:
        """Create both empty ledgers once without overwriting existing receipts."""

        with self._lock:
            for path in (self.reviews_path, self.resolutions_path):
                if path.is_symlink():
                    raise StateError(f"refusing symlink review ledger: {path}")
                try:
                    descriptor = os.open(
                        path,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600,
                    )
                except FileExistsError:
                    continue
                else:
                    os.close(descriptor)

    def submit_review(
        self,
        payload: Mapping[str, Any],
        *,
        expected_reviewer_id: str | None = None,
    ) -> HumanReview:
        """Append a first receipt or latest-only superseding edit."""

        request = _review_request(payload)
        if (
            _review_schema_version(request.get("schema_version"))
            != self.schema_version
        ):
            raise ReviewValidationError(
                "review schema_version does not match the run contract"
            )
        request_hash = canonical_request_sha256(request)
        review_id = _require_safe_id(request["review_id"], "review_id")
        with self._lock:
            self.hub.reconcile_pending()
            existing = self._review_by_id(review_id)
            if existing is not None:
                if existing.request_sha256 != request_hash:
                    raise ReviewConflictError(
                        f"review_id {review_id!r} already has a different request"
                    )
                return existing
            self._require_open()
            self._validate_round_request(request)
            reviewer_id = _require_safe_id(request["reviewer_id"], "reviewer_id")
            if expected_reviewer_id is not None:
                _require_safe_id(expected_reviewer_id, "expected_reviewer_id")
                if reviewer_id != expected_reviewer_id:
                    raise ReviewConflictError(
                        "reviewer_id does not match the authenticated reviewer session"
                    )
            latest_by_reviewer = {
                item.reviewer_id: item for item in self._latest_receipts_unlocked()
            }
            prior = latest_by_reviewer.get(reviewer_id)
            supersedes = _optional_safe_id(
                request["supersedes_review_id"], "supersedes_review_id"
            )
            if prior is None:
                if supersedes is not None:
                    raise ReviewConflictError(
                        "a first review cannot supersede another receipt"
                    )
                independence: Independence = "pre_reveal"
            else:
                if supersedes != prior.review_id:
                    raise ReviewConflictError(
                        "supersedes_review_id must name this reviewer's latest receipt"
                    )
                independence = "post_reveal"

            review = self._build_review(
                request,
                request_sha256=request_hash,
                independence=independence,
                submitted_at=_timestamp(self._clock(), "submitted_at"),
            )
            try:
                self.hub.append_ledger_record("human_reviews", review.to_dict())
            except StateConflictError as exc:
                raise ReviewConflictError(str(exc)) from exc
            return review

    def latest_receipts(self) -> tuple[HumanReview, ...]:
        with self._shared_read():
            return self._latest_receipts_unlocked()

    def feedback_fragments(self) -> tuple[FeedbackFragment, ...]:
        with self._shared_read():
            return self._feedback_fragments_unlocked(self._latest_receipts_unlocked())

    def snapshot(self) -> ReviewSnapshot:
        with self._shared_read():
            latest = self._latest_receipts_unlocked()
            resolution = self._single_resolution_unlocked()
            effective_round = (
                self.round.closed_by(resolution)
                if resolution is not None
                else self.round
            )
            coverage = _coverage(self.round, latest)
            return ReviewSnapshot(
                round=effective_round,
                latest_reviews=latest,
                coverage=coverage,
                latest_receipt_set_sha256=latest_receipt_set_sha256(latest),
                resolution=resolution,
            )

    def submit_resolution(
        self,
        payload: Mapping[str, Any],
    ) -> HumanResolution:
        """Validate coverage/feedback/actions and append one immutable close."""

        request = _resolution_request(payload)
        request_hash = canonical_request_sha256(request)
        resolution_id = _require_safe_id(request["resolution_id"], "resolution_id")
        with self._lock:
            self.hub.reconcile_pending()
            existing_by_id = self._resolution_by_id(resolution_id)
            if existing_by_id is not None:
                if existing_by_id.request_sha256 != request_hash:
                    raise ReviewConflictError(
                        f"resolution_id {resolution_id!r} already has a different request"
                    )
                return existing_by_id
            self._require_open()
            self._validate_round_request(request)
            if self._single_resolution_unlocked() is not None:
                raise ReviewClosedError("review round already has a resolution")

            latest = self._latest_receipts_unlocked()
            fragments = {
                item.feedback_ref: item
                for item in self._feedback_fragments_unlocked(latest)
            }
            coverage = _coverage(self.round, latest)
            resolution = self._build_resolution(
                request,
                request_sha256=request_hash,
                latest=latest,
                fragments=fragments,
                coverage=coverage,
                closed_at=_timestamp(self._clock(), "closed_at"),
            )
            try:
                raw_wait = self.hub.load_raw_state().get("wait")
                if raw_wait is not None and not isinstance(raw_wait, dict):
                    raise ReviewValidationError(
                        "persisted wait state must be an object"
                    )
                wait = dict(raw_wait) if isinstance(raw_wait, dict) else {}
                persisted_round_id = wait.get("round_id")
                persisted_round_sha256 = wait.get("round_sha256")
                if persisted_round_id not in {None, self.round.round_id}:
                    raise ReviewStaleError(
                        "persisted wait belongs to another review round"
                    )
                if persisted_round_sha256 not in {
                    None,
                    self.round.round_sha256,
                }:
                    raise ReviewStaleError("persisted wait round hash is stale")
                wait.update(resolution.wait_close_payload())
                self.hub.set_wait_and_append_ledger_record(
                    wait,
                    ledger="human_resolutions",
                    record=resolution.to_dict(),
                )
            except StateConflictError as exc:
                raise ReviewConflictError(str(exc)) from exc
            return resolution

    def _shared_read(self) -> Any:
        return advisory_lease(
            self.hub.lock_path,
            exclusive=False,
            create=False,
        )

    def _require_open(self) -> None:
        if self.round.status != "open":
            raise ReviewClosedError("review round is closed")
        if self._single_resolution_unlocked() is not None:
            raise ReviewClosedError("review round already has a resolution")

    def _validate_round_request(self, request: Mapping[str, Any]) -> None:
        if request["run_id"] != self.round.run_id:
            raise ReviewStaleError("run_id does not match the review round")
        if request["round_id"] != self.round.round_id:
            raise ReviewStaleError("round_id does not match the review round")
        if request["round_sha256"] != self.round.round_sha256:
            raise ReviewStaleError("round_sha256 does not match the review round")

    def _build_review(
        self,
        request: Mapping[str, Any],
        *,
        request_sha256: str,
        independence: Independence,
        submitted_at: str,
    ) -> HumanReview:
        schema_version = _review_schema_version(request.get("schema_version"))
        review_id = _require_safe_id(request["review_id"], "review_id")
        reviewer_name = _free_text(
            request["reviewer_name"],
            "reviewer_name",
            maximum=MAX_REVIEWER_NAME,
            required=True,
            single_line=True,
        )
        concept_rows = _object_list(request["concept_reviews"], "concept_reviews")
        if len(concept_rows) > len(self.round.concepts):
            raise ReviewValidationError("too many concept reviews")
        concept_reviews: list[ConceptReview] = []
        seen_concepts: set[str] = set()
        for row in concept_rows:
            concept_fields = {
                "concept_ref",
                "concept_sha256",
                "one_sentence_retell",
                "share_target",
                "reactions",
                "recommendation",
                "comment",
            }
            if schema_version >= 2:
                concept_fields.update({"share_impulse", "demo_confidence"})
            value = _exact_object(
                row,
                required=concept_fields,
                label="concept review",
            )
            concept_ref = _require_string(value["concept_ref"], "concept_ref")
            if concept_ref in seen_concepts:
                raise ReviewValidationError(f"duplicate concept review: {concept_ref}")
            seen_concepts.add(concept_ref)
            binding = self.round.bindings.get(concept_ref)
            if binding is None:
                raise ReviewStaleError(f"unknown shortlist Concept: {concept_ref}")
            if value["concept_sha256"] != binding.concept_sha256:
                raise ReviewStaleError(f"Concept hash changed for {concept_ref}")
            reactions = _reaction_mapping(value["reactions"])
            recommendation = _enum_string(
                value["recommendation"],
                _RECOMMENDATIONS,
                "recommendation",
            )
            share_target = _free_text(
                value["share_target"],
                "share_target",
                maximum=MAX_SHARE_TARGET,
            )
            share_impulse = (
                cast(
                    ShareImpulse,
                    _enum_string(
                        value["share_impulse"],
                        _SHARE_IMPULSES,
                        "share_impulse",
                    ),
                )
                if schema_version >= 2
                else None
            )
            demo_confidence = (
                cast(
                    DemoConfidence,
                    _enum_string(
                        value["demo_confidence"],
                        _DEMO_CONFIDENCE_VALUES,
                        "demo_confidence",
                    ),
                )
                if schema_version >= 2
                else None
            )
            if share_impulse == "immediate" and not share_target.strip():
                raise ReviewValidationError(
                    "share_target is required when share_impulse is immediate"
                )
            feedback_ref = f"{review_id}:concept:{concept_ref}"
            partial = ConceptReview(
                feedback_ref=feedback_ref,
                feedback_sha256="0" * 64,
                concept_ref=concept_ref,
                concept_sha256=binding.concept_sha256,
                one_sentence_retell=_free_text(
                    value["one_sentence_retell"],
                    "one_sentence_retell",
                    maximum=MAX_ONE_SENTENCE_RETELL,
                ),
                share_target=share_target,
                share_impulse=share_impulse,
                demo_confidence=demo_confidence,
                reactions=MappingProxyType(reactions),
                recommendation=recommendation,  # type: ignore[arg-type]
                comment=_free_text(
                    value["comment"],
                    "comment",
                    maximum=MAX_CONCEPT_COMMENT,
                ),
            )
            concept_reviews.append(
                replace(
                    partial,
                    feedback_sha256=sha256_json(partial.fragment_payload()),
                )
            )

        pair_rows = _object_list(request["pairwise"], "pairwise")
        if len(pair_rows) > len(self.round.pairs):
            raise ReviewValidationError("too many pairwise answers")
        pairwise: list[PairwiseReview] = []
        seen_pairs: set[str] = set()
        for row in pair_rows:
            value = _exact_object(
                row,
                required={
                    "pair_id",
                    "left_ref",
                    "right_ref",
                    "left_sha256",
                    "right_sha256",
                    "preference",
                    "reason",
                },
                label="pairwise review",
            )
            pair_id = _require_string(value["pair_id"], "pair_id")
            if pair_id in seen_pairs:
                raise ReviewValidationError(f"duplicate pair answer: {pair_id}")
            seen_pairs.add(pair_id)
            expected = self.round.pair_index.get(pair_id)
            if expected is None:
                raise ReviewStaleError(f"unknown review pair: {pair_id}")
            submitted_binding = (
                value["left_ref"],
                value["right_ref"],
                value["left_sha256"],
                value["right_sha256"],
            )
            canonical_binding = (
                expected.left_ref,
                expected.right_ref,
                expected.left_sha256,
                expected.right_sha256,
            )
            if submitted_binding != canonical_binding:
                raise ReviewStaleError(
                    f"pair {pair_id} must be submitted in canonical order"
                )
            preference = _enum_string(
                value["preference"],
                _PAIR_PREFERENCES,
                "preference",
            )
            feedback_ref = f"{review_id}:pair:{pair_id}"
            partial_pair = PairwiseReview(
                feedback_ref=feedback_ref,
                feedback_sha256="0" * 64,
                pair_id=pair_id,
                left_ref=expected.left_ref,
                right_ref=expected.right_ref,
                left_sha256=expected.left_sha256,
                right_sha256=expected.right_sha256,
                preference=preference,  # type: ignore[arg-type]
                reason=_free_text(
                    value["reason"],
                    "pair reason",
                    maximum=MAX_PAIR_REASON,
                ),
            )
            pairwise.append(
                replace(
                    partial_pair,
                    feedback_sha256=sha256_json(partial_pair.fragment_payload()),
                )
            )

        overall_comment = _free_text(
            request["overall_comment"],
            "overall_comment",
            maximum=MAX_OVERALL_COMMENT,
        )
        overall_feedback_ref = f"{review_id}:overall"
        overall_payload = {
            "feedback_ref": overall_feedback_ref,
            "overall_comment": overall_comment,
        }
        return HumanReview(
            schema_version=schema_version,
            review_id=review_id,
            round_id=self.round.round_id,
            round_sha256=self.round.round_sha256,
            run_id=self.round.run_id,
            reviewer_id=_require_safe_id(request["reviewer_id"], "reviewer_id"),
            reviewer_name=reviewer_name,
            submitted_at=submitted_at,
            request_sha256=request_sha256,
            independence=independence,
            concept_reviews=tuple(
                sorted(concept_reviews, key=lambda item: item.concept_ref)
            ),
            pairwise=tuple(sorted(pairwise, key=lambda item: item.pair_id)),
            overall_comment=overall_comment,
            overall_feedback_ref=overall_feedback_ref,
            overall_feedback_sha256=sha256_json(overall_payload),
            supersedes_review_id=_optional_safe_id(
                request["supersedes_review_id"], "supersedes_review_id"
            ),
        )

    def _build_resolution(
        self,
        request: Mapping[str, Any],
        *,
        request_sha256: str,
        latest: tuple[HumanReview, ...],
        fragments: Mapping[str, FeedbackFragment],
        coverage: tuple[ConceptCoverage, ...],
        closed_at: str,
    ) -> HumanResolution:
        curator_name = _free_text(
            request["curator_name"],
            "curator_name",
            maximum=MAX_REVIEWER_NAME,
            required=True,
            single_line=True,
        )
        uncovered = tuple(item.concept_ref for item in coverage if not item.covered)
        override = _optional_free_text(
            request["coverage_override_reason"],
            "coverage_override_reason",
            maximum=MAX_RESOLUTION_REASON,
        )
        if uncovered and not override:
            raise ReviewValidationError(
                "coverage override reason is required for uncovered Concepts"
            )
        if not uncovered and override is not None:
            raise ReviewValidationError(
                "coverage override reason is only allowed when coverage is incomplete"
            )

        merge_groups = _parse_merge_groups(
            request["merge_groups"],
            shortlist_refs=set(self.round.bindings),
        )
        group_by_source: dict[str, str] = {}
        for group in merge_groups:
            for source_ref in group.source_refs:
                if source_ref in group_by_source:
                    raise ReviewValidationError(
                        f"Concept {source_ref} appears in multiple merge groups"
                    )
                group_by_source[source_ref] = group.merge_group_id

        action_rows = _object_list(request["actions"], "resolution actions")
        if len(action_rows) != len(self.round.concepts):
            raise ReviewValidationError(
                "resolution must contain exactly one action per shortlisted Concept"
            )
        actions: list[ResolutionAction] = []
        seen_actions: set[str] = set()
        for row in action_rows:
            value = _exact_object(
                row,
                required={
                    "concept_ref",
                    "action",
                    "approved_feedback",
                    "curator_instruction",
                    "reason",
                    "merge_group_id",
                },
                label="resolution action",
            )
            concept_ref = _require_string(value["concept_ref"], "concept_ref")
            if concept_ref not in self.round.bindings:
                raise ReviewStaleError(
                    f"unknown shortlisted Concept action: {concept_ref}"
                )
            if concept_ref in seen_actions:
                raise ReviewValidationError(
                    f"duplicate resolution action: {concept_ref}"
                )
            seen_actions.add(concept_ref)
            action_name = _enum_string(value["action"], _RESOLUTION_ACTIONS, "action")
            reason = _free_text(
                value["reason"],
                "action reason",
                maximum=MAX_RESOLUTION_REASON,
            )
            if action_name == "taste_veto" and not reason.strip():
                raise ReviewValidationError("taste_veto requires a non-empty reason")
            merge_group_id = _optional_safe_id(
                value["merge_group_id"], "merge_group_id"
            )
            expected_group = group_by_source.get(concept_ref)
            if action_name == "merge":
                if merge_group_id is None or merge_group_id != expected_group:
                    raise ReviewValidationError(
                        f"merge action for {concept_ref} must name its merge group"
                    )
            elif merge_group_id is not None or expected_group is not None:
                raise ReviewValidationError(
                    f"non-merge action for {concept_ref} conflicts with merge groups"
                )

            approved = _approved_feedback(
                value["approved_feedback"],
                fragments=fragments,
                related_concept_ref=concept_ref,
            )
            instruction = _free_text(
                value["curator_instruction"],
                "curator_instruction",
                maximum=MAX_CURATOR_INSTRUCTION,
            )
            instruction_hash = sha256_text(instruction) if instruction.strip() else None
            has_fragment_guidance = any(
                fragments[item.feedback_ref].has_guidance for item in approved
            )
            if (
                action_name in {"revise", "merge"}
                and not has_fragment_guidance
                and instruction_hash is None
            ):
                raise ReviewValidationError(
                    f"{action_name} action for {concept_ref} requires approved "
                    "feedback or a curator instruction"
                )
            actions.append(
                ResolutionAction(
                    concept_ref=concept_ref,
                    action=action_name,  # type: ignore[arg-type]
                    approved_feedback=approved,
                    curator_instruction=instruction,
                    curator_instruction_sha256=instruction_hash,
                    reason=reason,
                    merge_group_id=merge_group_id,
                )
            )
        if seen_actions != set(self.round.bindings):
            missing = sorted(set(self.round.bindings) - seen_actions)
            raise ReviewValidationError(f"resolution actions are missing: {missing}")
        merge_action_sources = {
            item.concept_ref for item in actions if item.action == "merge"
        }
        if merge_action_sources != set(group_by_source):
            raise ReviewValidationError(
                "merge actions and merge group sources must match exactly"
            )

        ordered_actions = tuple(sorted(actions, key=lambda item: item.concept_ref))
        approved_set = sorted(
            {
                (item.feedback_ref, item.feedback_sha256)
                for action in ordered_actions
                for item in action.approved_feedback
            }
        )
        approved_bytes = sum(
            len(canonical_json_bytes(dict(fragments[reference].payload)))
            for reference, _sha256 in approved_set
        ) + sum(
            len(action.curator_instruction.encode("utf-8"))
            for action in ordered_actions
        )
        if approved_bytes > MAX_APPROVED_FEEDBACK_BYTES:
            raise ReviewValidationError(
                "approved feedback and curator instructions exceed 24 KiB"
            )
        partial = HumanResolution(
            resolution_id=_require_safe_id(request["resolution_id"], "resolution_id"),
            run_id=self.round.run_id,
            curator_name=curator_name,
            round_id=self.round.round_id,
            round_sha256=self.round.round_sha256,
            actions=ordered_actions,
            merge_groups=tuple(
                sorted(merge_groups, key=lambda item: item.merge_group_id)
            ),
            uncovered_concept_refs=uncovered,
            coverage_override_reason=override,
            latest_receipt_set_sha256=latest_receipt_set_sha256(latest),
            approved_feedback_set_sha256=sha256_json(
                [
                    {"feedback_ref": reference, "feedback_sha256": digest}
                    for reference, digest in approved_set
                ]
            ),
            closed_at=closed_at,
            request_sha256=request_sha256,
            resolution_sha256="0" * 64,
        )
        return replace(
            partial,
            resolution_sha256=sha256_json(partial.hash_payload()),
        )

    def _review_by_id(self, review_id: str) -> HumanReview | None:
        for raw in read_jsonl(self.reviews_path):
            if raw.get("review_id") == review_id:
                return self._review_from_record(raw)
        return None

    def _review_from_record(self, raw: Mapping[str, Any]) -> HumanReview:
        review = _human_review_from_record(raw, self.round)
        if review.schema_version != self.schema_version:
            raise ReviewValidationError(
                "persisted review schema_version does not match the run contract"
            )
        return review

    def _resolution_by_id(self, resolution_id: str) -> HumanResolution | None:
        for raw in read_jsonl(self.resolutions_path):
            if raw.get("resolution_id") == resolution_id:
                return _human_resolution_from_record(raw, self.round)
        return None

    def _single_resolution_unlocked(self) -> HumanResolution | None:
        records = [
            _human_resolution_from_record(raw, self.round)
            for raw in read_jsonl(self.resolutions_path)
            if raw.get("round_id") == self.round.round_id
        ]
        if len(records) > 1:
            raise ReviewValidationError(
                "review round has multiple persisted resolutions"
            )
        if not records:
            return None
        self._validate_persisted_resolution(records[0])
        return records[0]

    def _validate_persisted_resolution(
        self,
        resolution: HumanResolution,
    ) -> None:
        latest = self._latest_receipts_unlocked()
        if resolution.latest_receipt_set_sha256 != latest_receipt_set_sha256(latest):
            raise ReviewStaleError(
                "persisted resolution latest receipt set hash mismatch"
            )
        coverage = _coverage(self.round, latest)
        uncovered = tuple(item.concept_ref for item in coverage if not item.covered)
        if resolution.uncovered_concept_refs != uncovered:
            raise ReviewStaleError(
                "persisted resolution uncovered Concept set mismatch"
            )
        if uncovered and not resolution.coverage_override_reason:
            raise ReviewValidationError(
                "persisted resolution lacks required coverage override"
            )
        if not uncovered and resolution.coverage_override_reason is not None:
            raise ReviewValidationError(
                "persisted resolution has an unnecessary coverage override"
            )

        fragment_index = {
            item.feedback_ref: item
            for item in self._feedback_fragments_unlocked(latest)
        }
        action_refs = [item.concept_ref for item in resolution.actions]
        if len(action_refs) != len(set(action_refs)) or set(action_refs) != set(
            self.round.bindings
        ):
            raise ReviewValidationError(
                "persisted resolution must have exactly one action per Concept"
            )
        parsed_groups = _parse_merge_groups(
            [item.to_dict() for item in resolution.merge_groups],
            shortlist_refs=set(self.round.bindings),
        )
        group_by_source: dict[str, str] = {}
        for group in parsed_groups:
            for source_ref in group.source_refs:
                if source_ref in group_by_source:
                    raise ReviewValidationError("persisted merge groups overlap")
                group_by_source[source_ref] = group.merge_group_id

        approved_set: set[tuple[str, str]] = set()
        for action in resolution.actions:
            if action.action == "taste_veto" and not action.reason.strip():
                raise ReviewValidationError("persisted taste_veto lacks a reason")
            expected_group = group_by_source.get(action.concept_ref)
            if action.action == "merge":
                if (
                    action.merge_group_id is None
                    or action.merge_group_id != expected_group
                ):
                    raise ReviewValidationError(
                        "persisted merge action has the wrong group"
                    )
            elif action.merge_group_id is not None or expected_group is not None:
                raise ReviewValidationError(
                    "persisted non-merge action conflicts with a merge group"
                )
            approved = _approved_feedback(
                [item.to_dict() for item in action.approved_feedback],
                fragments=fragment_index,
                related_concept_ref=action.concept_ref,
            )
            approved_set.update(
                (item.feedback_ref, item.feedback_sha256) for item in approved
            )
            has_guidance = any(
                fragment_index[item.feedback_ref].has_guidance for item in approved
            )
            if (
                action.action in {"revise", "merge"}
                and not has_guidance
                and action.curator_instruction_sha256 is None
            ):
                raise ReviewValidationError(
                    "persisted revise/merge action lacks guidance"
                )
        if {
            item.concept_ref for item in resolution.actions if item.action == "merge"
        } != set(group_by_source):
            raise ReviewValidationError(
                "persisted merge actions do not match merge group sources"
            )
        expected_approved_hash = sha256_json(
            [
                {"feedback_ref": reference, "feedback_sha256": digest}
                for reference, digest in sorted(approved_set)
            ]
        )
        if resolution.approved_feedback_set_sha256 != expected_approved_hash:
            raise ReviewStaleError(
                "persisted resolution approved feedback set hash mismatch"
            )

    def _latest_receipts_unlocked(self) -> tuple[HumanReview, ...]:
        records = [
            self._review_from_record(raw)
            for raw in read_jsonl(self.reviews_path)
            if raw.get("round_id") == self.round.round_id
        ]
        latest: dict[str, HumanReview] = {}
        known_ids: dict[str, HumanReview] = {}
        for record in records:
            if record.review_id in known_ids:
                raise ReviewValidationError(
                    f"duplicate persisted review ID: {record.review_id}"
                )
            prior = latest.get(record.reviewer_id)
            if prior is None:
                if record.supersedes_review_id is not None:
                    raise ReviewValidationError(
                        "persisted first review unexpectedly supersedes a receipt"
                    )
                if record.independence != "pre_reveal":
                    raise ReviewValidationError(
                        "persisted first review must be pre_reveal"
                    )
            else:
                if record.supersedes_review_id != prior.review_id:
                    raise ReviewValidationError(
                        "persisted review does not supersede the latest receipt"
                    )
                if record.independence != "post_reveal":
                    raise ReviewValidationError(
                        "persisted superseding review must be post_reveal"
                    )
            known_ids[record.review_id] = record
            latest[record.reviewer_id] = record
        return tuple(latest[key] for key in sorted(latest))

    def _feedback_fragments_unlocked(
        self,
        latest: Sequence[HumanReview],
    ) -> tuple[FeedbackFragment, ...]:
        fragments: list[FeedbackFragment] = []
        all_concepts = tuple(self.round.bindings)
        for review in latest:
            for concept_item in review.concept_reviews:
                fragments.append(
                    FeedbackFragment(
                        feedback_ref=concept_item.feedback_ref,
                        feedback_sha256=concept_item.feedback_sha256,
                        kind="concept",
                        review_id=review.review_id,
                        reviewer_id=review.reviewer_id,
                        related_concept_refs=(concept_item.concept_ref,),
                        payload=MappingProxyType(concept_item.fragment_payload()),
                        has_guidance=True,
                    )
                )
            for pair_item in review.pairwise:
                fragments.append(
                    FeedbackFragment(
                        feedback_ref=pair_item.feedback_ref,
                        feedback_sha256=pair_item.feedback_sha256,
                        kind="pair",
                        review_id=review.review_id,
                        reviewer_id=review.reviewer_id,
                        related_concept_refs=tuple(
                            sorted((pair_item.left_ref, pair_item.right_ref))
                        ),
                        payload=MappingProxyType(pair_item.fragment_payload()),
                        has_guidance=True,
                    )
                )
            fragments.append(
                FeedbackFragment(
                    feedback_ref=review.overall_feedback_ref,
                    feedback_sha256=review.overall_feedback_sha256,
                    kind="overall",
                    review_id=review.review_id,
                    reviewer_id=review.reviewer_id,
                    related_concept_refs=all_concepts,
                    payload=MappingProxyType(review.overall_fragment_payload()),
                    has_guidance=bool(review.overall_comment.strip()),
                )
            )
        return tuple(sorted(fragments, key=lambda item: item.feedback_ref))


def canonical_request_sha256(payload: Mapping[str, Any]) -> str:
    """Hash a detached strict-JSON client request, preserving Unicode bytes."""

    normalized = normalize_json(dict(payload), label="review client request")
    if not isinstance(normalized, dict):
        raise ReviewValidationError("review client request must be an object")
    return sha256_json(normalized)


def latest_receipt_set_sha256(reviews: Sequence[HumanReview]) -> str:
    """Bind the exact latest receipt ID/request-hash set in reviewer order."""

    ordered = sorted(reviews, key=lambda item: item.reviewer_id)
    if len({item.reviewer_id for item in ordered}) != len(ordered):
        raise ReviewValidationError(
            "latest receipt set contains duplicate reviewer IDs"
        )
    return sha256_json(
        [
            {
                "reviewer_id": item.reviewer_id,
                "review_id": item.review_id,
                "request_sha256": item.request_sha256,
            }
            for item in ordered
        ]
    )


def _coverage(
    review_round: ReviewRound,
    latest: Sequence[HumanReview],
) -> tuple[ConceptCoverage, ...]:
    return tuple(
        ConceptCoverage(
            concept_ref=binding.concept_ref,
            reviewer_ids=tuple(
                sorted(
                    review.reviewer_id
                    for review in latest
                    if any(
                        item.concept_ref == binding.concept_ref
                        for item in review.concept_reviews
                    )
                )
            ),
        )
        for binding in review_round.concepts
    )


def _review_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    request = _exact_object(
        payload,
        required={
            "review_id",
            "round_id",
            "round_sha256",
            "run_id",
            "reviewer_id",
            "reviewer_name",
            "concept_reviews",
            "pairwise",
            "overall_comment",
            "supersedes_review_id",
        },
        optional={"schema_version"},
        label="human review request",
    )
    schema_version = _review_schema_version(request.get("schema_version"))
    if schema_version >= 2:
        request["schema_version"] = schema_version
    else:
        # Legacy v1 requests had no version field. Normalizing an explicitly
        # supplied ``1`` back to that shape preserves historical request hashes.
        request.pop("schema_version", None)
    request["concept_reviews"] = _sorted_object_rows(
        request["concept_reviews"],
        key="concept_ref",
        label="concept_reviews",
    )
    request["pairwise"] = _sorted_object_rows(
        request["pairwise"],
        key="pair_id",
        label="pairwise",
    )
    return request


def _resolution_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    request = _exact_object(
        payload,
        required={
            "resolution_id",
            "run_id",
            "curator_name",
            "round_id",
            "round_sha256",
            "actions",
            "merge_groups",
            "coverage_override_reason",
        },
        label="human resolution request",
    )
    actions = _sorted_object_rows(
        request["actions"],
        key="concept_ref",
        label="resolution actions",
    )
    for action in actions:
        action["approved_feedback"] = _sorted_object_rows(
            action.get("approved_feedback"),
            key="feedback_ref",
            label="approved_feedback",
        )
    groups = _sorted_object_rows(
        request["merge_groups"],
        key="merge_group_id",
        label="merge_groups",
    )
    for group in groups:
        source_refs = group.get("source_refs")
        if not isinstance(source_refs, list) or any(
            not isinstance(item, str) for item in source_refs
        ):
            raise ReviewValidationError(
                "merge group source_refs must be an array of strings"
            )
        group["source_refs"] = sorted(source_refs)
    request["actions"] = actions
    request["merge_groups"] = groups
    return request


def _approved_feedback(
    raw: Any,
    *,
    fragments: Mapping[str, FeedbackFragment],
    related_concept_ref: str,
) -> tuple[ApprovedFeedback, ...]:
    rows = _object_list(raw, "approved_feedback")
    if len(rows) > MAX_APPROVED_FRAGMENTS_PER_ACTION:
        raise ReviewValidationError(
            "one resolution action cannot approve more than 12 feedback fragments"
        )
    approved: list[ApprovedFeedback] = []
    seen: set[str] = set()
    for row in rows:
        value = _exact_object(
            row,
            required={"feedback_ref", "feedback_sha256"},
            label="approved feedback",
        )
        reference = _require_string(value["feedback_ref"], "feedback_ref")
        digest = _require_string(value["feedback_sha256"], "feedback_sha256")
        if reference in seen:
            raise ReviewValidationError(f"duplicate approved feedback ref: {reference}")
        seen.add(reference)
        fragment = fragments.get(reference)
        if fragment is None:
            raise ReviewStaleError(
                f"approved feedback is not in the latest receipt set: {reference}"
            )
        if digest != fragment.feedback_sha256:
            raise ReviewStaleError(f"approved feedback hash changed: {reference}")
        if related_concept_ref not in fragment.related_concept_refs:
            raise ReviewValidationError(
                f"feedback {reference} is unrelated to {related_concept_ref}"
            )
        approved.append(
            ApprovedFeedback(
                feedback_ref=reference,
                feedback_sha256=digest,
            )
        )
    return tuple(sorted(approved, key=lambda item: item.feedback_ref))


def _parse_merge_groups(
    raw: Any,
    *,
    shortlist_refs: set[str],
) -> tuple[MergeGroup, ...]:
    rows = _object_list(raw, "merge_groups")
    groups: list[MergeGroup] = []
    seen_ids: set[str] = set()
    for row in rows:
        value = _exact_object(
            row,
            required={"merge_group_id", "source_refs", "reason"},
            label="merge group",
        )
        group_id = _require_safe_id(value["merge_group_id"], "merge_group_id")
        if group_id in seen_ids:
            raise ReviewValidationError(f"duplicate merge group ID: {group_id}")
        seen_ids.add(group_id)
        source_values = value["source_refs"]
        if not isinstance(source_values, list):
            raise ReviewValidationError("merge group source_refs must be an array")
        source_refs = tuple(
            sorted(_require_string(item, "merge source ref") for item in source_values)
        )
        if len(source_refs) < 2:
            raise ReviewValidationError("merge group requires at least two sources")
        if len(source_refs) != len(set(source_refs)):
            raise ReviewValidationError("merge group contains duplicate sources")
        unknown = sorted(set(source_refs) - shortlist_refs)
        if unknown:
            raise ReviewStaleError(f"unknown merge group sources: {unknown}")
        reason = _free_text(
            value["reason"],
            "merge reason",
            maximum=MAX_RESOLUTION_REASON,
            required=True,
        )
        groups.append(
            MergeGroup(
                merge_group_id=group_id,
                source_refs=source_refs,
                reason=reason,
            )
        )
    return tuple(groups)


def _human_review_from_record(
    raw: Mapping[str, Any],
    review_round: ReviewRound,
) -> HumanReview:
    value = _exact_object(
        raw,
        required={
            "review_id",
            "round_id",
            "round_sha256",
            "run_id",
            "reviewer_id",
            "reviewer_name",
            "submitted_at",
            "request_sha256",
            "independence",
            "concept_reviews",
            "pairwise",
            "overall_comment",
            "overall_feedback_ref",
            "overall_feedback_sha256",
            "supersedes_review_id",
        },
        optional={"created_at", "schema_version"},
        label="persisted human review",
    )
    schema_version = _review_schema_version(value.get("schema_version"))
    if (
        value["run_id"] != review_round.run_id
        or value["round_id"] != review_round.round_id
        or value["round_sha256"] != review_round.round_sha256
    ):
        raise ReviewStaleError("persisted human review has stale round binding")
    review_id = _require_safe_id(value["review_id"], "review_id")
    concept_reviews: list[ConceptReview] = []
    seen_concepts: set[str] = set()
    for raw_item in _object_list(value["concept_reviews"], "persisted concept reviews"):
        concept_fields = {
            "feedback_ref",
            "feedback_sha256",
            "concept_ref",
            "concept_sha256",
            "one_sentence_retell",
            "share_target",
            "reactions",
            "recommendation",
            "comment",
        }
        if schema_version >= 2:
            concept_fields.update({"share_impulse", "demo_confidence"})
        item = _exact_object(
            raw_item,
            required=concept_fields,
            label="persisted concept review",
        )
        binding = review_round.bindings.get(
            _require_string(item["concept_ref"], "concept_ref")
        )
        if binding is None or item["concept_sha256"] != binding.concept_sha256:
            raise ReviewStaleError("persisted concept review binding is stale")
        if binding.concept_ref in seen_concepts:
            raise ReviewValidationError(
                f"duplicate persisted concept review: {binding.concept_ref}"
            )
        seen_concepts.add(binding.concept_ref)
        reactions = _reaction_mapping(item["reactions"])
        review = ConceptReview(
            feedback_ref=_require_string(item["feedback_ref"], "feedback_ref"),
            feedback_sha256=_require_string(item["feedback_sha256"], "feedback_sha256"),
            concept_ref=binding.concept_ref,
            concept_sha256=binding.concept_sha256,
            one_sentence_retell=_free_text(
                item["one_sentence_retell"],
                "one_sentence_retell",
                maximum=MAX_ONE_SENTENCE_RETELL,
            ),
            share_target=_free_text(
                item["share_target"],
                "share_target",
                maximum=MAX_SHARE_TARGET,
            ),
            share_impulse=(
                cast(
                    ShareImpulse,
                    _enum_string(
                        item["share_impulse"],
                        _SHARE_IMPULSES,
                        "share_impulse",
                    ),
                )
                if schema_version >= 2
                else None
            ),
            demo_confidence=(
                cast(
                    DemoConfidence,
                    _enum_string(
                        item["demo_confidence"],
                        _DEMO_CONFIDENCE_VALUES,
                        "demo_confidence",
                    ),
                )
                if schema_version >= 2
                else None
            ),
            reactions=MappingProxyType(reactions),
            recommendation=_enum_string(
                item["recommendation"],
                _RECOMMENDATIONS,
                "recommendation",
            ),  # type: ignore[arg-type]
            comment=_free_text(
                item["comment"],
                "comment",
                maximum=MAX_CONCEPT_COMMENT,
            ),
        )
        if review.share_impulse == "immediate" and not review.share_target.strip():
            raise ReviewValidationError(
                "persisted share_target is required when share_impulse is immediate"
            )
        if review.feedback_ref != f"{review_id}:concept:{binding.concept_ref}":
            raise ReviewStaleError("persisted concept feedback ref mismatch")
        if review.feedback_sha256 != sha256_json(review.fragment_payload()):
            raise ReviewStaleError("persisted concept feedback hash mismatch")
        concept_reviews.append(review)

    pairwise: list[PairwiseReview] = []
    seen_pairs: set[str] = set()
    for raw_item in _object_list(value["pairwise"], "persisted pairwise reviews"):
        item = _exact_object(
            raw_item,
            required={
                "feedback_ref",
                "feedback_sha256",
                "pair_id",
                "left_ref",
                "right_ref",
                "left_sha256",
                "right_sha256",
                "preference",
                "reason",
            },
            label="persisted pairwise review",
        )
        pair = review_round.pair_index.get(_require_string(item["pair_id"], "pair_id"))
        if pair is None or (
            item["left_ref"],
            item["right_ref"],
            item["left_sha256"],
            item["right_sha256"],
        ) != (
            pair.left_ref,
            pair.right_ref,
            pair.left_sha256,
            pair.right_sha256,
        ):
            raise ReviewStaleError("persisted pairwise binding is stale")
        if pair.pair_id in seen_pairs:
            raise ReviewValidationError(
                f"duplicate persisted pair review: {pair.pair_id}"
            )
        seen_pairs.add(pair.pair_id)
        pair_review = PairwiseReview(
            feedback_ref=_require_string(item["feedback_ref"], "feedback_ref"),
            feedback_sha256=_require_string(item["feedback_sha256"], "feedback_sha256"),
            pair_id=pair.pair_id,
            left_ref=pair.left_ref,
            right_ref=pair.right_ref,
            left_sha256=pair.left_sha256,
            right_sha256=pair.right_sha256,
            preference=_enum_string(
                item["preference"],
                _PAIR_PREFERENCES,
                "preference",
            ),  # type: ignore[arg-type]
            reason=_free_text(item["reason"], "pair reason", maximum=MAX_PAIR_REASON),
        )
        if pair_review.feedback_ref != f"{review_id}:pair:{pair.pair_id}":
            raise ReviewStaleError("persisted pair feedback ref mismatch")
        if pair_review.feedback_sha256 != sha256_json(pair_review.fragment_payload()):
            raise ReviewStaleError("persisted pair feedback hash mismatch")
        pairwise.append(pair_review)

    overall_comment = _free_text(
        value["overall_comment"],
        "overall_comment",
        maximum=MAX_OVERALL_COMMENT,
    )
    overall_ref = _require_string(value["overall_feedback_ref"], "overall_feedback_ref")
    overall_hash = _require_string(
        value["overall_feedback_sha256"], "overall_feedback_sha256"
    )
    if overall_ref != f"{review_id}:overall":
        raise ReviewStaleError("persisted overall feedback ref mismatch")
    if overall_hash != sha256_json(
        {"feedback_ref": overall_ref, "overall_comment": overall_comment}
    ):
        raise ReviewStaleError("persisted overall feedback hash mismatch")
    independence = _enum_string(
        value["independence"],
        frozenset({"pre_reveal", "post_reveal"}),
        "independence",
    )
    result = HumanReview(
        schema_version=schema_version,
        review_id=review_id,
        round_id=review_round.round_id,
        round_sha256=review_round.round_sha256,
        run_id=review_round.run_id,
        reviewer_id=_require_safe_id(value["reviewer_id"], "reviewer_id"),
        reviewer_name=_free_text(
            value["reviewer_name"],
            "reviewer_name",
            maximum=MAX_REVIEWER_NAME,
            required=True,
            single_line=True,
        ),
        submitted_at=_timestamp(value["submitted_at"], "submitted_at"),
        request_sha256=_require_sha256(value["request_sha256"], "request_sha256"),
        independence=independence,  # type: ignore[arg-type]
        concept_reviews=tuple(concept_reviews),
        pairwise=tuple(pairwise),
        overall_comment=overall_comment,
        overall_feedback_ref=overall_ref,
        overall_feedback_sha256=overall_hash,
        supersedes_review_id=_optional_safe_id(
            value["supersedes_review_id"], "supersedes_review_id"
        ),
    )
    if result.request_sha256 != canonical_request_sha256(
        _review_request(result.request_payload())
    ):
        raise ReviewStaleError("persisted human review request hash mismatch")
    return result


def _human_resolution_from_record(
    raw: Mapping[str, Any],
    review_round: ReviewRound,
) -> HumanResolution:
    value = _exact_object(
        raw,
        required={
            "resolution_id",
            "run_id",
            "curator_name",
            "round_id",
            "round_sha256",
            "actions",
            "merge_groups",
            "uncovered_concept_refs",
            "coverage_override_reason",
            "latest_receipt_set_sha256",
            "approved_feedback_set_sha256",
            "closed_at",
            "request_sha256",
            "resolution_sha256",
        },
        optional={"created_at"},
        label="persisted human resolution",
    )
    if (
        value["run_id"] != review_round.run_id
        or value["round_id"] != review_round.round_id
        or value["round_sha256"] != review_round.round_sha256
    ):
        raise ReviewStaleError("persisted resolution has stale round binding")
    actions: list[ResolutionAction] = []
    for raw_action in _object_list(value["actions"], "persisted resolution actions"):
        action = _exact_object(
            raw_action,
            required={
                "concept_ref",
                "action",
                "approved_feedback",
                "curator_instruction",
                "curator_instruction_sha256",
                "reason",
                "merge_group_id",
            },
            label="persisted resolution action",
        )
        instruction = _free_text(
            action["curator_instruction"],
            "curator_instruction",
            maximum=MAX_CURATOR_INSTRUCTION,
        )
        instruction_hash = _optional_string(
            action["curator_instruction_sha256"],
            "curator_instruction_sha256",
        )
        expected_instruction_hash = (
            sha256_text(instruction) if instruction.strip() else None
        )
        if instruction_hash != expected_instruction_hash:
            raise ReviewStaleError("curator instruction hash mismatch")
        approved = tuple(
            ApprovedFeedback(
                feedback_ref=_require_string(item["feedback_ref"], "feedback_ref"),
                feedback_sha256=_require_sha256(
                    item["feedback_sha256"], "feedback_sha256"
                ),
            )
            for item in (
                _exact_object(
                    raw_item,
                    required={"feedback_ref", "feedback_sha256"},
                    label="persisted approved feedback",
                )
                for raw_item in _object_list(
                    action["approved_feedback"],
                    "persisted approved feedback",
                )
            )
        )
        actions.append(
            ResolutionAction(
                concept_ref=_require_string(action["concept_ref"], "concept_ref"),
                action=_enum_string(action["action"], _RESOLUTION_ACTIONS, "action"),  # type: ignore[arg-type]
                approved_feedback=approved,
                curator_instruction=instruction,
                curator_instruction_sha256=instruction_hash,
                reason=_free_text(
                    action["reason"],
                    "action reason",
                    maximum=MAX_RESOLUTION_REASON,
                ),
                merge_group_id=_optional_safe_id(
                    action["merge_group_id"], "merge_group_id"
                ),
            )
        )
    merge_groups = tuple(
        MergeGroup(
            merge_group_id=_require_safe_id(group["merge_group_id"], "merge_group_id"),
            source_refs=tuple(
                _require_string(item, "merge source ref")
                for item in _string_list(group["source_refs"], "merge source refs")
            ),
            reason=_free_text(
                group["reason"],
                "merge reason",
                maximum=MAX_RESOLUTION_REASON,
                required=True,
            ),
        )
        for group in (
            _exact_object(
                raw_group,
                required={"merge_group_id", "source_refs", "reason"},
                label="persisted merge group",
            )
            for raw_group in _object_list(
                value["merge_groups"], "persisted merge groups"
            )
        )
    )
    partial = HumanResolution(
        resolution_id=_require_safe_id(value["resolution_id"], "resolution_id"),
        run_id=review_round.run_id,
        curator_name=_free_text(
            value["curator_name"],
            "curator_name",
            maximum=MAX_REVIEWER_NAME,
            required=True,
            single_line=True,
        ),
        round_id=review_round.round_id,
        round_sha256=review_round.round_sha256,
        actions=tuple(actions),
        merge_groups=merge_groups,
        uncovered_concept_refs=tuple(
            _string_list(value["uncovered_concept_refs"], "uncovered_concept_refs")
        ),
        coverage_override_reason=_optional_free_text(
            value["coverage_override_reason"],
            "coverage_override_reason",
            maximum=MAX_RESOLUTION_REASON,
        ),
        latest_receipt_set_sha256=_require_sha256(
            value["latest_receipt_set_sha256"],
            "latest_receipt_set_sha256",
        ),
        approved_feedback_set_sha256=_require_sha256(
            value["approved_feedback_set_sha256"],
            "approved_feedback_set_sha256",
        ),
        closed_at=_timestamp(value["closed_at"], "closed_at"),
        request_sha256=_require_sha256(value["request_sha256"], "request_sha256"),
        resolution_sha256=_require_sha256(
            value["resolution_sha256"], "resolution_sha256"
        ),
    )
    if partial.resolution_sha256 != sha256_json(partial.hash_payload()):
        raise ReviewStaleError("persisted resolution hash mismatch")
    if partial.request_sha256 != canonical_request_sha256(
        _resolution_request(partial.request_payload())
    ):
        raise ReviewStaleError("persisted resolution request hash mismatch")
    return partial


def _exact_object(
    value: Any,
    *,
    required: set[str],
    label: str,
    optional: set[str] | None = None,
) -> dict[str, Any]:
    normalized = normalize_json(value, label=label)
    if not isinstance(normalized, dict):
        raise ReviewValidationError(f"{label} must be an object")
    allowed = required | (optional or set())
    missing = sorted(required - set(normalized))
    unknown = sorted(set(normalized) - allowed)
    if missing:
        raise ReviewValidationError(f"{label} is missing fields: {missing}")
    if unknown:
        raise ReviewValidationError(f"{label} has unknown fields: {unknown}")
    return normalized


def _object_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ReviewValidationError(f"{label} must be an array")
    if any(not isinstance(item, dict) for item in value):
        raise ReviewValidationError(f"{label} entries must be objects")
    return list(value)


def _sorted_object_rows(value: Any, *, key: str, label: str) -> list[dict[str, Any]]:
    rows = _object_list(value, label)
    for row in rows:
        if not isinstance(row.get(key), str):
            raise ReviewValidationError(f"{label} entries require string {key}")
    return sorted(rows, key=lambda row: row[key])


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ReviewValidationError(f"{label} must be an array of strings")
    return list(value)


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ReviewValidationError(f"{label} must be a string")
    _valid_unicode(value, label)
    return value


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, label)


def _free_text(
    value: Any,
    label: str,
    *,
    maximum: int,
    required: bool = False,
    single_line: bool = False,
) -> str:
    text = _require_string(value, label)
    if len(text) > maximum:
        raise ReviewValidationError(
            f"{label} cannot exceed {maximum} Unicode characters"
        )
    if required and not text.strip():
        raise ReviewValidationError(f"{label} must not be blank")
    if single_line and any(character in text for character in "\r\n"):
        raise ReviewValidationError(f"{label} must be one line")
    return text


def _optional_free_text(
    value: Any,
    label: str,
    *,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    text = _free_text(value, label, maximum=maximum)
    return text if text.strip() else None


def _valid_unicode(value: str, label: str) -> None:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ReviewValidationError(f"{label} contains invalid Unicode") from exc


def _require_pattern(value: Any, pattern: re.Pattern[str], label: str) -> str:
    text = _require_string(value, label)
    if pattern.fullmatch(text) is None:
        raise ReviewValidationError(f"invalid {label}: {text!r}")
    return text


def _require_safe_id(value: Any, label: str) -> str:
    return _require_pattern(value, _SAFE_ID, label)


def _optional_safe_id(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _require_safe_id(value, label)


def _require_sha256(value: Any, label: str) -> str:
    return _require_pattern(value, _SHA256, label)


def _enum_string(value: Any, allowed: frozenset[str], label: str) -> str:
    text = _require_string(value, label)
    if text not in allowed:
        raise ReviewValidationError(f"{label} must be one of {sorted(allowed)}")
    return text


def _review_schema_version(value: Any) -> int:
    if value is None:
        return 1
    if type(value) is not int or value not in _REVIEW_SCHEMA_VERSIONS:
        raise ReviewValidationError(
            f"schema_version must be one of {sorted(_REVIEW_SCHEMA_VERSIONS)}"
        )
    return value


def _reaction_mapping(value: Any) -> dict[str, str]:
    reactions = _exact_object(
        value,
        required=set(_REACTION_KEYS),
        label="reactions",
    )
    return {
        key: _enum_string(reactions[key], _REACTION_VALUES, f"reaction {key}")
        for key in _REACTION_KEYS
    }


def _timestamp(value: Any, label: str) -> str:
    text = _require_string(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ReviewValidationError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ReviewValidationError(f"{label} must include a timezone")
    return text
