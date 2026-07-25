"""Deterministic C7 projection and rendering for the Creative route.

This module is intentionally a pure boundary.  It accepts one fully validated,
typed projection and returns exact bytes ready for the finalization planner.  It
does not inspect a run directory, read a ledger, call a model, use the network,
or consult the current clock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal, Mapping, Sequence

from hacksome.artifacts import ArtifactError, title_of, validate_markdown
from hacksome.creative.artifacts import (
    CHALLENGE_BRIEF_HEADINGS,
    CONCEPT_HEADINGS,
    CREATIVE_BRIEF_HEADINGS,
    FINAL_IDEA_CARD_HEADINGS,
    LEGACY_CONCEPT_HEADINGS,
    LEGACY_CREATIVE_BRIEF_HEADINGS,
    NOVELTY_SCAN_HEADINGS,
    compose_final_idea_card,
)
from hacksome.creative.contracts import (
    CREATIVE_CONTRACT_VERSION,
    CREATIVE_PROMPT_POLICY_VERSION,
    CREATIVE_REPORT_POLICY_VERSION,
    CREATIVE_STAGE_POLICY_VERSION,
    LEGACY_CREATIVE_CONTRACT_VERSION,
    LEGACY_CREATIVE_PROMPT_POLICY_VERSION,
    LEGACY_CREATIVE_REPORT_POLICY_VERSION,
    LEGACY_CREATIVE_STAGE_POLICY_VERSION,
    DispositionOutcome,
    DispositionStage,
    StableReasonCode,
    ZeroReasonCode,
    parse_concept_revision_ref,
)
from hacksome.creative.memory import (
    MemoryCapsuleRef,
    MemoryReasonEvidence,
    MemoryRecord,
    MemoryValidationError,
    expected_memory_classification,
    extract_exact_markdown_section,
    reject_private_memory_fields,
)
from hacksome.state import (
    canonical_json_bytes,
    sha256_bytes,
    sha256_json,
    sha256_text,
)


REPORT_MARKDOWN_ARTIFACT_ID = "creative-idea-report"
REPORT_JSON_ARTIFACT_ID = "creative-idea-report-json"
IDEA_CARD_INDEX_ARTIFACT_ID = "creative-idea-card-index"
MEMORY_RECORD_ARTIFACT_ID = "creative-memory-record"

REPORT_MARKDOWN_PATH = "artifacts/creative/report/creative-idea-report.md"
REPORT_JSON_PATH = "artifacts/creative/report/creative-idea-report.json"
IDEA_CARD_INDEX_PATH = "artifacts/creative/idea-cards/index.md"
MEMORY_RECORD_PATH = "artifacts/creative/memory/creative-memory-record.json"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_LOCAL_PATH = re.compile(
    r"(?:^|[\s(])/(?:Users|home|private|tmp|var)/|(?:^|[\s(])[A-Za-z]:\\"
)
_ZERO_REASONS = frozenset(reason.value for reason in ZeroReasonCode)
_EMPTY_BATCH_REASONS = frozenset(
    {
        ZeroReasonCode.NO_CONCEPTS_GENERATED.value,
        ZeroReasonCode.ALL_CANDIDATES_FAILED_HOOK.value,
        ZeroReasonCode.ALL_CANDIDATES_FAILED_CONCEPT_SCREEN.value,
        ZeroReasonCode.SHORTLIST_EMPTY.value,
    }
)


class CreativeReportError(ValueError):
    """A C7 projection cannot be rendered without inventing or leaking data."""


@dataclass(frozen=True, slots=True)
class ReasonEvidenceProjection:
    """Machine-review evidence already bound to one stable reason code."""

    reason_code: str
    evidence_excerpt: str
    source_review_ref: str
    source_review_sha256: str

    def __post_init__(self) -> None:
        try:
            MemoryReasonEvidence.from_mapping(self.to_dict())
        except MemoryValidationError as exc:
            raise CreativeReportError(str(exc)) from exc

    def to_dict(self) -> dict[str, str]:
        return {
            "reason_code": self.reason_code,
            "evidence_excerpt": self.evidence_excerpt,
            "source_review_ref": self.source_review_ref,
            "source_review_sha256": self.source_review_sha256,
        }


@dataclass(frozen=True, slots=True)
class DispositionProjection:
    """One immutable disposition projected from the machine decision ledger."""

    disposition_ref: str
    stage: DispositionStage
    outcome: DispositionOutcome
    terminal: bool
    target_ref: str | None
    reason_codes: tuple[str, ...]
    decision_ref: str
    evidence_refs: tuple[str, ...] = ()
    task_refs: tuple[str, ...] = ()
    reason_evidence: tuple[ReasonEvidenceProjection, ...] = ()

    def __post_init__(self) -> None:
        _require_ref(self.disposition_ref, "disposition_ref")
        _require_ref(self.decision_ref, "decision_ref")
        if not isinstance(self.stage, DispositionStage):
            raise CreativeReportError("disposition stage must be a DispositionStage")
        if not isinstance(self.outcome, DispositionOutcome):
            raise CreativeReportError(
                "disposition outcome must be a DispositionOutcome"
            )
        if type(self.terminal) is not bool:
            raise CreativeReportError("disposition terminal must be boolean")
        if self.target_ref is not None:
            _require_ref(self.target_ref, "disposition target_ref")
        _require_unique_refs(self.evidence_refs, "disposition evidence_refs")
        _require_unique_refs(self.task_refs, "disposition task_refs")
        _require_unique_refs(self.reason_codes, "disposition reason_codes")
        allowed_reasons = {reason.value for reason in StableReasonCode}
        unknown = sorted(set(self.reason_codes) - allowed_reasons)
        if unknown:
            raise CreativeReportError(
                "disposition has unknown reason codes: " + ", ".join(unknown)
            )
        evidence_codes = {item.reason_code for item in self.reason_evidence}
        if not evidence_codes.issubset(self.reason_codes):
            raise CreativeReportError(
                "reason evidence must bind to a disposition reason code"
            )
        if self.terminal and self.outcome in {
            DispositionOutcome.PASS,
            DispositionOutcome.REPAIR,
            DispositionOutcome.SHORTLISTED,
        }:
            raise CreativeReportError(
                f"{self.outcome.value} cannot be a terminal disposition"
            )
        if not self.terminal and self.outcome not in {
            DispositionOutcome.PASS,
            DispositionOutcome.REPAIR,
            DispositionOutcome.SHORTLISTED,
        }:
            raise CreativeReportError(
                f"{self.outcome.value} must be a terminal disposition"
            )

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "disposition_ref": self.disposition_ref,
            "stage": self.stage.value,
            "outcome": self.outcome.value,
            "terminal": self.terminal,
            "target_ref": self.target_ref,
            "reason_codes": sorted(self.reason_codes),
            "decision_ref": self.decision_ref,
            "evidence_refs": sorted(self.evidence_refs),
            "task_refs": sorted(self.task_refs),
        }


@dataclass(frozen=True, slots=True)
class ConceptRevisionProjection:
    """One immutable Concept revision plus all of its dispositions."""

    revision_ref: str
    sha256: str
    markdown: str
    primary_territory_ref: str
    parent_atom_refs: tuple[str, ...]
    dispositions: tuple[DispositionProjection, ...]

    def __post_init__(self) -> None:
        parse_concept_revision_ref(self.revision_ref)
        _require_sha(self.sha256, "Concept revision sha256")
        if sha256_text(self.markdown) != self.sha256:
            raise CreativeReportError(
                f"Concept revision hash mismatch: {self.revision_ref}"
            )
        _validate_concept_markdown(
            self.markdown,
            label=f"Creative Concept {self.revision_ref}",
        )
        _reject_local_path(self.markdown, f"Concept {self.revision_ref}")
        _require_ref(self.primary_territory_ref, "primary_territory_ref")
        _require_unique_refs(self.parent_atom_refs, "parent_atom_refs")
        if not self.parent_atom_refs:
            raise CreativeReportError("Concept revision requires Parent Atoms")
        disposition_refs = tuple(
            disposition.disposition_ref for disposition in self.dispositions
        )
        _require_unique_refs(disposition_refs, "Concept disposition refs")

    @property
    def terminal_disposition(self) -> DispositionProjection:
        terminal = tuple(item for item in self.dispositions if item.terminal)
        if len(terminal) != 1:
            raise CreativeReportError(
                f"{self.revision_ref} requires exactly one terminal disposition"
            )
        return terminal[0]


@dataclass(frozen=True, slots=True)
class ConceptProjection:
    """All revisions and cross-run provenance for one stable Concept identity."""

    concept_id: str
    origin: Literal["base", "memory_challenger"]
    revisions: tuple[ConceptRevisionProjection, ...]
    memory_source_refs: tuple[MemoryCapsuleRef, ...] = ()
    memory_cue_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.origin not in {"base", "memory_challenger"}:
            raise CreativeReportError("Concept origin is invalid")
        if not self.revisions:
            raise CreativeReportError("Concept must contain at least one revision")
        parsed = [parse_concept_revision_ref(item.revision_ref) for item in self.revisions]
        if any(concept_id != self.concept_id for concept_id, _ in parsed):
            raise CreativeReportError(
                "Concept revisions must share the declared concept_id"
            )
        revision_numbers = sorted(revision for _, revision in parsed)
        if revision_numbers != list(range(1, revision_numbers[-1] + 1)):
            raise CreativeReportError(
                f"{self.concept_id} revisions must be contiguous from revision 1"
            )
        territories = {item.primary_territory_ref for item in self.revisions}
        if len(territories) != 1:
            raise CreativeReportError(
                f"{self.concept_id} revisions changed primary territory"
            )
        _require_unique_refs(self.memory_cue_refs, "memory_cue_refs")
        memory_keys = tuple(item.stable_key for item in self.memory_source_refs)
        if len(memory_keys) != len(set(memory_keys)):
            raise CreativeReportError("memory_source_refs contains duplicates")
        if self.origin == "base" and (
            self.memory_source_refs or self.memory_cue_refs
        ):
            raise CreativeReportError(
                "base Concept cannot claim Idea Memory provenance"
            )
        if self.origin == "memory_challenger" and (
            not self.memory_source_refs or not self.memory_cue_refs
        ):
            raise CreativeReportError(
                "memory challenger requires source refs and cue refs"
            )

    @property
    def ordered_revisions(self) -> tuple[ConceptRevisionProjection, ...]:
        return tuple(
            sorted(
                self.revisions,
                key=lambda item: parse_concept_revision_ref(item.revision_ref)[1],
            )
        )

    @property
    def latest_revision(self) -> ConceptRevisionProjection:
        return self.ordered_revisions[-1]


@dataclass(frozen=True, slots=True)
class TerritoryProjection:
    territory_ref: str
    sha256: str
    markdown: str

    def __post_init__(self) -> None:
        _require_ref(self.territory_ref, "territory_ref")
        if not self.territory_ref.startswith("creative-territory-"):
            raise CreativeReportError("territory_ref must be a Creative Territory")
        _require_sha(self.sha256, "Territory sha256")
        if sha256_text(self.markdown) != self.sha256:
            raise CreativeReportError(
                f"Territory hash mismatch: {self.territory_ref}"
            )
        validate_markdown(self.markdown, label=f"Territory {self.territory_ref}")
        _reject_local_path(self.markdown, f"Territory {self.territory_ref}")


@dataclass(frozen=True, slots=True)
class NoveltyProjection:
    novelty_ref: str
    sha256: str
    markdown: str

    def __post_init__(self) -> None:
        _require_ref(self.novelty_ref, "novelty_ref")
        _require_sha(self.sha256, "Novelty sha256")
        if sha256_text(self.markdown) != self.sha256:
            raise CreativeReportError(
                f"Novelty hash mismatch: {self.novelty_ref}"
            )
        validate_markdown(
            self.markdown,
            required_h2=NOVELTY_SCAN_HEADINGS,
            label=f"Novelty Scan {self.novelty_ref}",
        )
        _reject_local_path(self.markdown, f"Novelty Scan {self.novelty_ref}")


@dataclass(frozen=True, slots=True)
class HumanSignalProjection:
    """De-identified structured signals approved for the final Idea Card."""

    retells: tuple[str, ...] = ()
    share_targets: tuple[str, ...] = ()
    disagreements: tuple[str, ...] = ()
    receipt_ids: tuple[str, ...] = ()
    approved_feedback_fragment_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for label, values in (
            ("retells", self.retells),
            ("share_targets", self.share_targets),
            ("disagreements", self.disagreements),
        ):
            _require_unique_text(values, label)
        _require_unique_refs(self.receipt_ids, "Human Signal receipt_ids")
        _require_unique_refs(
            self.approved_feedback_fragment_refs,
            "Human Signal approved_feedback_fragment_refs",
        )


@dataclass(frozen=True, slots=True)
class FinalIdeaProjection:
    """One validated Final Idea before its controller-owned card is composed."""

    idea_id: str
    sha256: str
    markdown: str
    primary_territory_ref: str
    source_concept_refs: tuple[str, ...]
    decision_refs: tuple[str, ...]
    resolution_id: str
    novelty: tuple[NoveltyProjection, ...]
    human_signal: HumanSignalProjection

    def __post_init__(self) -> None:
        _require_ref(self.idea_id, "Final Idea ID")
        if not re.fullmatch(r"creative-idea-[0-9]{3}", self.idea_id):
            raise CreativeReportError("Final Idea ID is invalid")
        _require_sha(self.sha256, "Final Idea sha256")
        if sha256_text(self.markdown) != self.sha256:
            raise CreativeReportError(f"Final Idea hash mismatch: {self.idea_id}")
        _validate_concept_markdown(
            self.markdown,
            label=f"Final Idea {self.idea_id}",
        )
        _reject_local_path(self.markdown, f"Final Idea {self.idea_id}")
        _require_ref(self.primary_territory_ref, "Final Idea primary territory")
        _require_unique_refs(
            self.source_concept_refs, "Final Idea source_concept_refs"
        )
        if not self.source_concept_refs:
            raise CreativeReportError("Final Idea requires source Concept refs")
        for reference in self.source_concept_refs:
            parse_concept_revision_ref(reference)
        _require_unique_refs(self.decision_refs, "Final Idea decision_refs")
        if not self.decision_refs:
            raise CreativeReportError("Final Idea requires decision refs")
        _require_ref(self.resolution_id, "Final Idea resolution_id")
        novelty_refs = tuple(item.novelty_ref for item in self.novelty)
        _require_unique_refs(novelty_refs, "Final Idea novelty refs")
        if not self.novelty:
            raise CreativeReportError("Final Idea requires Novelty evidence")


@dataclass(frozen=True, slots=True)
class MemoryUseProjection:
    mode: Literal["auto", "off"]
    snapshot_ref: str
    snapshot_sha256: str
    status: Literal["empty", "disabled", "completed", "optional_failed"]
    selected_cue_ids: tuple[str, ...] = ()
    successful_challenger_refs: tuple[str, ...] = ()
    failed_task_refs: tuple[str, ...] = ()
    source_record_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in {"auto", "off"}:
            raise CreativeReportError("Idea Memory mode is invalid")
        if self.status not in {
            "empty",
            "disabled",
            "completed",
            "optional_failed",
        }:
            raise CreativeReportError("Idea Memory status is invalid")
        _require_ref(self.snapshot_ref, "Idea Memory snapshot_ref")
        _require_sha(self.snapshot_sha256, "Idea Memory snapshot_sha256")
        for label, values in (
            ("selected_cue_ids", self.selected_cue_ids),
            ("successful_challenger_refs", self.successful_challenger_refs),
            ("failed_task_refs", self.failed_task_refs),
            ("source_record_refs", self.source_record_refs),
        ):
            _require_unique_refs(values, f"Idea Memory {label}")


@dataclass(frozen=True, slots=True)
class ReviewRoundProjection:
    """De-identified review coverage; raw receipts remain in their ledger."""

    round_id: str
    status: Literal["closed", "skipped_empty"]
    concept_refs: tuple[str, ...]
    receipt_ids: tuple[str, ...]
    covered_concept_refs: tuple[str, ...]
    resolution_id: str | None
    unresolved_disagreements: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_ref(self.round_id, "review round_id")
        if self.status not in {"closed", "skipped_empty"}:
            raise CreativeReportError("completed report has an invalid review status")
        for label, values in (
            ("review concept_refs", self.concept_refs),
            ("review receipt_ids", self.receipt_ids),
            ("review covered_concept_refs", self.covered_concept_refs),
        ):
            _require_unique_refs(values, label)
        if not set(self.covered_concept_refs).issubset(self.concept_refs):
            raise CreativeReportError(
                "review covered_concept_refs must belong to the round"
            )
        _require_unique_text(
            self.unresolved_disagreements,
            "review unresolved_disagreements",
        )
        if self.status == "closed":
            if self.resolution_id is None:
                raise CreativeReportError("closed review requires a resolution_id")
            _require_ref(self.resolution_id, "review resolution_id")
        elif (
            self.concept_refs
            or self.receipt_ids
            or self.covered_concept_refs
            or self.resolution_id is not None
        ):
            raise CreativeReportError("skipped-empty review must be empty")


@dataclass(frozen=True, slots=True)
class CreativeReportProjection:
    """Canonical, de-identified input to the successful C7 renderer."""

    run_id: str
    created_at: str
    producer_kind: Literal["live", "fixture"]
    challenge_ref: str
    challenge_sha256: str
    challenge_markdown: str
    creative_brief_ref: str
    creative_brief_sha256: str
    creative_brief_markdown: str
    territories: tuple[TerritoryProjection, ...]
    concepts: tuple[ConceptProjection, ...]
    memory: MemoryUseProjection
    review_rounds: tuple[ReviewRoundProjection, ...]
    final_ideas: tuple[FinalIdeaProjection, ...]
    zero_reason_code: str | None
    empty_batch_skip_reason: str | None
    route_contract_version: str = CREATIVE_CONTRACT_VERSION
    prompt_policy_version: str = CREATIVE_PROMPT_POLICY_VERSION
    stage_policy_version: str = CREATIVE_STAGE_POLICY_VERSION
    report_policy_version: str = CREATIVE_REPORT_POLICY_VERSION

    def __post_init__(self) -> None:
        _require_ref(self.run_id, "run_id")
        if self.producer_kind not in {"live", "fixture"}:
            raise CreativeReportError("producer_kind must be live or fixture")
        policy_versions = {
            CREATIVE_CONTRACT_VERSION: (
                CREATIVE_PROMPT_POLICY_VERSION,
                CREATIVE_STAGE_POLICY_VERSION,
                CREATIVE_REPORT_POLICY_VERSION,
            ),
            LEGACY_CREATIVE_CONTRACT_VERSION: (
                LEGACY_CREATIVE_PROMPT_POLICY_VERSION,
                LEGACY_CREATIVE_STAGE_POLICY_VERSION,
                LEGACY_CREATIVE_REPORT_POLICY_VERSION,
            ),
        }
        expected_policies = policy_versions.get(self.route_contract_version)
        if expected_policies is None:
            raise CreativeReportError("unsupported Creative contract version")
        if (
            self.prompt_policy_version,
            self.stage_policy_version,
            self.report_policy_version,
        ) != expected_policies:
            raise CreativeReportError(
                "Creative route policy versions do not match its contract"
            )
        concept_headings = (
            LEGACY_CONCEPT_HEADINGS
            if self.route_contract_version == LEGACY_CREATIVE_CONTRACT_VERSION
            else CONCEPT_HEADINGS
        )
        for concept in self.concepts:
            for revision in concept.ordered_revisions:
                validate_markdown(
                    revision.markdown,
                    required_h2=concept_headings,
                    label=f"Creative Concept {revision.revision_ref}",
                )
        for idea in self.final_ideas:
            validate_markdown(
                idea.markdown,
                required_h2=concept_headings,
                label=f"Final Idea {idea.idea_id}",
            )
        _require_ref(self.challenge_ref, "challenge_ref")
        _require_sha(self.challenge_sha256, "challenge_sha256")
        if sha256_text(self.challenge_markdown) != self.challenge_sha256:
            raise CreativeReportError("Challenge Brief hash mismatch")
        validate_markdown(
            self.challenge_markdown,
            required_h2=CHALLENGE_BRIEF_HEADINGS,
            label="Creative Challenge Brief",
        )
        _reject_local_path(self.challenge_markdown, "Challenge Brief")
        _require_ref(self.creative_brief_ref, "creative_brief_ref")
        _require_sha(self.creative_brief_sha256, "creative_brief_sha256")
        if sha256_text(self.creative_brief_markdown) != self.creative_brief_sha256:
            raise CreativeReportError("Creative Brief hash mismatch")
        validate_markdown(
            self.creative_brief_markdown,
            required_h2=(
                LEGACY_CREATIVE_BRIEF_HEADINGS
                if self.route_contract_version
                == LEGACY_CREATIVE_CONTRACT_VERSION
                else CREATIVE_BRIEF_HEADINGS
            ),
            label="Creative Brief",
        )
        _reject_local_path(self.creative_brief_markdown, "Creative Brief")
        _require_unique_refs(
            tuple(item.territory_ref for item in self.territories),
            "territory refs",
        )
        concept_ids = tuple(item.concept_id for item in self.concepts)
        _require_unique_refs(concept_ids, "concept IDs")
        _require_unique_refs(
            tuple(item.idea_id for item in self.final_ideas),
            "Final Idea IDs",
        )
        _require_unique_refs(
            tuple(item.round_id for item in self.review_rounds),
            "review round IDs",
        )
        if self.zero_reason_code is not None:
            if self.zero_reason_code not in _ZERO_REASONS:
                raise CreativeReportError("zero_reason_code is invalid")
            if (
                self.route_contract_version == LEGACY_CREATIVE_CONTRACT_VERSION
                and self.zero_reason_code
                == ZeroReasonCode.ALL_CANDIDATES_FAILED_CONCEPT_SCREEN.value
            ):
                raise CreativeReportError(
                    "Creative v1 cannot use the v2 Concept Screen zero reason"
                )
            if (
                self.route_contract_version == CREATIVE_CONTRACT_VERSION
                and self.zero_reason_code
                == ZeroReasonCode.ALL_CANDIDATES_FAILED_HOOK.value
            ):
                raise CreativeReportError(
                    "Creative v2 cannot use the legacy Hook zero reason"
                )
            if self.final_ideas:
                raise CreativeReportError(
                    "zero_reason_code cannot accompany Final Ideas"
                )
        elif not self.final_ideas:
            raise CreativeReportError(
                "a completed report without Final Ideas requires zero_reason_code"
            )
        if self.empty_batch_skip_reason is not None:
            if self.empty_batch_skip_reason not in _EMPTY_BATCH_REASONS:
                raise CreativeReportError("empty batch skip reason is invalid")
            if self.empty_batch_skip_reason != self.zero_reason_code:
                raise CreativeReportError(
                    "empty batch skip reason must equal zero_reason_code"
                )
        if self.zero_reason_code in _EMPTY_BATCH_REASONS:
            if self.empty_batch_skip_reason is None:
                raise CreativeReportError(
                    "pre-human zero result requires an empty batch skip reason"
                )
            if any(round_.status != "skipped_empty" for round_ in self.review_rounds):
                raise CreativeReportError(
                    "pre-human zero result cannot contain a closed review round"
                )
        if self.zero_reason_code == ZeroReasonCode.ALL_HUMAN_REJECTED.value:
            if self.empty_batch_skip_reason is not None:
                raise CreativeReportError(
                    "all_human_rejected cannot have an empty batch skip reason"
                )
            if not any(round_.status == "closed" for round_ in self.review_rounds):
                raise CreativeReportError(
                    "all_human_rejected requires a closed review round"
                )
        _validate_zero_reason_semantics(self)


@dataclass(frozen=True, slots=True)
class RenderedOutput:
    """One exact finalization output, including its stable publish identity."""

    artifact_id: str
    artifact_type: str
    relative_path: str
    content: bytes

    def __post_init__(self) -> None:
        _require_ref(self.artifact_id, "rendered artifact_id")
        _require_ref(self.artifact_type, "rendered artifact_type")
        path = PurePosixPath(self.relative_path)
        if path.is_absolute() or ".." in path.parts or str(path) != self.relative_path:
            raise CreativeReportError("rendered relative_path is unsafe")
        if not isinstance(self.content, bytes) or not self.content:
            raise CreativeReportError("rendered output content must be non-empty bytes")

    @property
    def sha256(self) -> str:
        return sha256_bytes(self.content)

    @property
    def size_bytes(self) -> int:
        return len(self.content)


@dataclass(frozen=True, slots=True)
class RenderedReportBundle:
    """All successful C7 bytes in deterministic logical publish order."""

    report_markdown: RenderedOutput
    report_json: RenderedOutput
    idea_cards: tuple[RenderedOutput, ...]
    idea_card_index: RenderedOutput
    handoffs: tuple[RenderedOutput, ...]
    memory_record: RenderedOutput

    @property
    def outputs(self) -> tuple[RenderedOutput, ...]:
        return (
            self.report_markdown,
            self.report_json,
            *self.idea_cards,
            self.idea_card_index,
            *self.handoffs,
            self.memory_record,
        )


def render_success_report(
    projection: CreativeReportProjection,
) -> RenderedReportBundle:
    """Render a successful zero-or-more-Idea C7 bundle without side effects."""

    _validate_completed_lineage(projection)
    ordered_ideas = tuple(sorted(projection.final_ideas, key=lambda item: item.idea_id))
    cards = tuple(_render_idea_card(projection, idea) for idea in ordered_ideas)
    card_by_idea = {
        idea.idea_id: card for idea, card in zip(ordered_ideas, cards, strict=True)
    }
    handoffs = tuple(
        _render_handoff(projection, idea, card_by_idea[idea.idea_id])
        for idea in ordered_ideas
    )
    report_json_payload = _report_json_payload(
        projection,
        ordered_ideas=ordered_ideas,
    )
    reject_private_memory_fields(report_json_payload)
    report_json = RenderedOutput(
        artifact_id=REPORT_JSON_ARTIFACT_ID,
        artifact_type="creative_idea_report_json",
        relative_path=REPORT_JSON_PATH,
        content=_json_file_bytes(report_json_payload),
    )
    report_markdown = RenderedOutput(
        artifact_id=REPORT_MARKDOWN_ARTIFACT_ID,
        artifact_type="creative_idea_report_markdown",
        relative_path=REPORT_MARKDOWN_PATH,
        content=_report_markdown_bytes(
            projection,
            cards=card_by_idea,
        ),
    )
    idea_card_index = _render_card_index(ordered_ideas, card_by_idea)
    memory_payload = _memory_record_payload(
        projection,
        report_sha256=report_markdown.sha256,
    )
    memory_record = MemoryRecord.from_mapping(memory_payload)
    canonical_memory_payload = memory_record.to_dict()
    reject_private_memory_fields(canonical_memory_payload)
    rendered_memory = RenderedOutput(
        artifact_id=MEMORY_RECORD_ARTIFACT_ID,
        artifact_type="creative_memory_record",
        relative_path=MEMORY_RECORD_PATH,
        content=_json_file_bytes(canonical_memory_payload),
    )
    return RenderedReportBundle(
        report_markdown=report_markdown,
        report_json=report_json,
        idea_cards=cards,
        idea_card_index=idea_card_index,
        handoffs=handoffs,
        memory_record=rendered_memory,
    )


def _validate_completed_lineage(projection: CreativeReportProjection) -> None:
    revisions: dict[str, ConceptRevisionProjection] = {}
    for concept in projection.concepts:
        for revision in concept.ordered_revisions:
            if revision.revision_ref in revisions:
                raise CreativeReportError(
                    f"duplicate Concept revision: {revision.revision_ref}"
                )
            revisions[revision.revision_ref] = revision
            terminal = revision.terminal_disposition
            if terminal.target_ref is not None:
                if terminal.outcome in {
                    DispositionOutcome.SUPERSEDED_BY_HOOK_REPAIR,
                    DispositionOutcome.SUPERSEDED_BY_EVIDENCE_REVISION,
                }:
                    target = revisions.get(terminal.target_ref)
                    if target is None:
                        # The target may appear later in input order; the complete
                        # existence check below is deliberately order-independent.
                        pass
                elif terminal.outcome not in {
                    DispositionOutcome.PROMOTED_TO_FINAL,
                    DispositionOutcome.REVISED_INTO,
                    DispositionOutcome.MERGED_INTO,
                }:
                    raise CreativeReportError(
                        "terminal disposition has an unsupported target"
                    )

    final_ids = {idea.idea_id for idea in projection.final_ideas}
    final_by_id = {idea.idea_id: idea for idea in projection.final_ideas}
    for revision in revisions.values():
        terminal = revision.terminal_disposition
        if terminal.outcome in {
            DispositionOutcome.SUPERSEDED_BY_HOOK_REPAIR,
            DispositionOutcome.SUPERSEDED_BY_EVIDENCE_REVISION,
        }:
            if terminal.target_ref not in revisions:
                raise CreativeReportError(
                    f"{revision.revision_ref} points to a missing successor"
                )
        elif terminal.outcome in {
            DispositionOutcome.PROMOTED_TO_FINAL,
            DispositionOutcome.REVISED_INTO,
            DispositionOutcome.MERGED_INTO,
        } and terminal.target_ref not in final_ids:
            raise CreativeReportError(
                f"{revision.revision_ref} points to a missing Final Idea"
            )
        elif terminal.outcome in {
            DispositionOutcome.PROMOTED_TO_FINAL,
            DispositionOutcome.REVISED_INTO,
            DispositionOutcome.MERGED_INTO,
        }:
            assert terminal.target_ref is not None
            if revision.revision_ref not in final_by_id[
                terminal.target_ref
            ].source_concept_refs:
                raise CreativeReportError(
                    f"{revision.revision_ref} is absent from its Final Idea lineage"
                )

    rounds_by_resolution = {
        round_.resolution_id: round_
        for round_ in projection.review_rounds
        if round_.resolution_id is not None
    }
    for idea in projection.final_ideas:
        if any(reference not in revisions for reference in idea.source_concept_refs):
            raise CreativeReportError(
                f"{idea.idea_id} cites an unknown source Concept revision"
            )
        source_territories = {
            revisions[reference].primary_territory_ref
            for reference in idea.source_concept_refs
        }
        if idea.primary_territory_ref not in source_territories:
            raise CreativeReportError(
                f"{idea.idea_id} primary territory is not from its sources"
            )
        target_dispositions = [
            revisions[reference].terminal_disposition
            for reference in idea.source_concept_refs
        ]
        if any(item.target_ref != idea.idea_id for item in target_dispositions):
            raise CreativeReportError(
                f"{idea.idea_id} source dispositions do not target the Final Idea"
            )
        if not set(idea.decision_refs).issuperset(
            item.decision_ref for item in target_dispositions
        ):
            raise CreativeReportError(
                f"{idea.idea_id} lineage omits a source decision"
            )
        round_ = rounds_by_resolution.get(idea.resolution_id)
        if round_ is None:
            raise CreativeReportError(
                f"{idea.idea_id} resolution is absent from review_rounds"
            )
        if not set(idea.source_concept_refs).issubset(round_.concept_refs):
            raise CreativeReportError(
                f"{idea.idea_id} source Concepts are absent from its review round"
            )
        if not set(idea.human_signal.receipt_ids).issubset(round_.receipt_ids):
            raise CreativeReportError(
                f"{idea.idea_id} Human Signal cites an unknown receipt"
            )


def _validate_zero_reason_semantics(
    projection: CreativeReportProjection,
) -> None:
    reason = projection.zero_reason_code
    if reason is None:
        return
    latest_outcomes = {
        concept.latest_revision.terminal_disposition.outcome
        for concept in projection.concepts
    }
    if reason == ZeroReasonCode.NO_CONCEPTS_GENERATED.value:
        if projection.concepts:
            raise CreativeReportError(
                "no_concepts_generated requires an empty Concept set"
            )
        return
    if not projection.concepts:
        raise CreativeReportError(f"{reason} requires at least one Concept")
    if reason in {
        ZeroReasonCode.ALL_CANDIDATES_FAILED_HOOK.value,
        ZeroReasonCode.ALL_CANDIDATES_FAILED_CONCEPT_SCREEN.value,
    }:
        if latest_outcomes != {DispositionOutcome.ELIMINATED}:
            raise CreativeReportError(
                f"{reason} requires every latest revision "
                "to be eliminated at C4"
            )
        return
    if reason == ZeroReasonCode.SHORTLIST_EMPTY.value:
        if DispositionOutcome.NOT_SHORTLISTED not in latest_outcomes:
            raise CreativeReportError(
                "shortlist_empty requires a not_shortlisted terminal revision"
            )
        if latest_outcomes - {
            DispositionOutcome.ELIMINATED,
            DispositionOutcome.NOT_SHORTLISTED,
        }:
            raise CreativeReportError(
                "shortlist_empty cannot contain a human terminal outcome"
            )
        return
    human_outcomes = {
        DispositionOutcome.HUMAN_REJECT,
        DispositionOutcome.HUMAN_TASTE_VETO,
    }
    if not latest_outcomes.intersection(human_outcomes):
        raise CreativeReportError(
            "all_human_rejected requires a human reject or taste veto"
        )
    if latest_outcomes - {
        DispositionOutcome.ELIMINATED,
        DispositionOutcome.NOT_SHORTLISTED,
        *human_outcomes,
    }:
        raise CreativeReportError(
            "all_human_rejected has a non-rejected terminal outcome"
        )


def _render_idea_card(
    projection: CreativeReportProjection,
    idea: FinalIdeaProjection,
) -> RenderedOutput:
    first_thirty_seconds = extract_exact_markdown_section(
        idea.markdown,
        "First Impression",
    )
    reveal = extract_exact_markdown_section(
        idea.markdown,
        "Setup, Reveal and Aftertaste",
    )
    risks = extract_exact_markdown_section(
        idea.markdown,
        "Assumptions, Confusion and Risks",
    )
    if idea.human_signal.disagreements:
        risks = (
            risks
            + "\n\nUnresolved review disagreement:\n"
            + "\n".join(
                f"- {item}" for item in sorted(idea.human_signal.disagreements)
            )
        )
    lineage = {
        "idea_id": idea.idea_id,
        "source_concept_refs": sorted(idea.source_concept_refs),
        "decision_refs": sorted(idea.decision_refs),
        "receipt_ids": sorted(idea.human_signal.receipt_ids),
        "approved_feedback_fragment_refs": sorted(
            idea.human_signal.approved_feedback_fragment_refs
        ),
        "resolution_id": idea.resolution_id,
        "primary_territory_ref": idea.primary_territory_ref,
        "prompt_policy_version": projection.prompt_policy_version,
        "stage_policy_version": projection.stage_policy_version,
    }
    sections: Mapping[str, str] = {
        "Intended Reaction": extract_exact_markdown_section(
            idea.markdown,
            "Intended Reaction",
        ),
        "One-sentence Hook": extract_exact_markdown_section(
            idea.markdown,
            "One-sentence Hook",
        ),
        "First Thirty Seconds": first_thirty_seconds,
        "Audience Action": extract_exact_markdown_section(
            idea.markdown,
            "Audience Action",
        ),
        "Core Mechanism": extract_exact_markdown_section(
            idea.markdown,
            "Real Input, Transformation and Output",
        ),
        "Reveal and Aftertaste": reveal,
        "Minimum Hackathon Demo": extract_exact_markdown_section(
            idea.markdown,
            "Minimum Hackathon Demo",
        ),
        "Why Someone May Share It": extract_exact_markdown_section(
            idea.markdown,
            "Why It Is Unexpected Yet Legible",
        ),
        "Novelty and References": _novelty_card_text(idea.novelty),
        "Human Signal": _human_signal_text(idea.human_signal),
        "Risks and Unresolved Disagreement": risks,
        "Lineage": "```json\n"
        + canonical_json_bytes(lineage).decode("utf-8")
        + "\n```",
    }
    if set(sections) != set(FINAL_IDEA_CARD_HEADINGS):
        raise AssertionError("Final Idea Card mapping drifted from its contract")
    markdown = compose_final_idea_card(
        title=title_of(idea.markdown),
        sections=sections,
    )
    return RenderedOutput(
        artifact_id=_card_artifact_id(idea.idea_id),
        artifact_type="creative_idea_card",
        relative_path=f"artifacts/creative/idea-cards/{idea.idea_id}.md",
        content=markdown.encode("utf-8"),
    )


def _novelty_card_text(novelty: Sequence[NoveltyProjection]) -> str:
    chunks: list[str] = []
    for item in sorted(novelty, key=lambda value: value.novelty_ref):
        chunks.extend(
            [
                f"Evidence `{item.novelty_ref}`:",
                "",
                "Direct and near collisions:",
                extract_exact_markdown_section(
                    item.markdown,
                    "Direct and Near Collisions",
                ),
                "",
                "Distinctive combination:",
                extract_exact_markdown_section(
                    item.markdown,
                    "Distinctive Combination",
                ),
                "",
                "Counterevidence and uncertainty:",
                extract_exact_markdown_section(
                    item.markdown,
                    "Counterevidence and Uncertainty",
                ),
            ]
        )
    return "\n".join(chunks)


def _human_signal_text(signal: HumanSignalProjection) -> str:
    lines = [
        (
            "This is a concept-stage proxy signal from the bounded review round; "
            "it is not evidence of real-world sharing or virality."
        ),
        "",
        "De-identified one-sentence retells:",
    ]
    lines.extend(
        f"- {item}" for item in sorted(signal.retells)
    )
    if not signal.retells:
        lines.append("- No approved retell was available.")
    lines.extend(("", "Specific share targets mentioned:"))
    lines.extend(
        f"- {item}" for item in sorted(signal.share_targets)
    )
    if not signal.share_targets:
        lines.append("- No specific share target was recorded.")
    lines.extend(("", "Unresolved disagreement:"))
    lines.extend(
        f"- {item}" for item in sorted(signal.disagreements)
    )
    if not signal.disagreements:
        lines.append("- None recorded in the approved projection.")
    return "\n".join(lines)


def _render_handoff(
    projection: CreativeReportProjection,
    idea: FinalIdeaProjection,
    card: RenderedOutput,
) -> RenderedOutput:
    payload = {
        "source_run_id": projection.run_id,
        "idea_card_id": card.artifact_id,
        "idea_card_sha256": card.sha256,
        "challenge_markdown": projection.challenge_markdown,
        "initial_idea_card_markdown": card.content.decode("utf-8"),
    }
    reject_private_memory_fields(payload)
    return RenderedOutput(
        artifact_id=_handoff_artifact_id(idea.idea_id),
        artifact_type="creative_build_handoff",
        relative_path=f"artifacts/creative/handoffs/{idea.idea_id}.json",
        content=_json_file_bytes(payload),
    )


def _render_card_index(
    ideas: Sequence[FinalIdeaProjection],
    cards: Mapping[str, RenderedOutput],
) -> RenderedOutput:
    lines = ["# Creative Idea Cards", ""]
    if not ideas:
        lines.extend(
            [
                "This completed Creative run produced zero Final Idea Cards.",
                "",
            ]
        )
    else:
        for idea in ideas:
            card = cards[idea.idea_id]
            lines.append(
                f"- [{title_of(idea.markdown)}](./{idea.idea_id}.md) "
                f"— `{card.artifact_id}` / `{card.sha256}`"
            )
        lines.append("")
    return RenderedOutput(
        artifact_id=IDEA_CARD_INDEX_ARTIFACT_ID,
        artifact_type="creative_idea_card_index",
        relative_path=IDEA_CARD_INDEX_PATH,
        content="\n".join(lines).encode("utf-8"),
    )


def _report_json_payload(
    projection: CreativeReportProjection,
    *,
    ordered_ideas: Sequence[FinalIdeaProjection],
) -> dict[str, Any]:
    concepts = []
    for concept in sorted(projection.concepts, key=lambda item: item.concept_id):
        dispositions = [
            disposition.to_report_dict()
            for revision in concept.ordered_revisions
            for disposition in sorted(
                revision.dispositions,
                key=lambda item: item.disposition_ref,
            )
        ]
        terminal = concept.latest_revision.terminal_disposition
        concepts.append(
            {
                "concept_id": concept.concept_id,
                "origin": concept.origin,
                "revision_refs": [
                    item.revision_ref for item in concept.ordered_revisions
                ],
                "primary_territory_ref": (
                    concept.latest_revision.primary_territory_ref
                ),
                "memory_source_refs": [
                    item.to_dict()
                    for item in sorted(
                        concept.memory_source_refs,
                        key=lambda value: value.stable_key,
                    )
                ],
                "memory_cue_refs": sorted(concept.memory_cue_refs),
                "terminal_outcome": _report_terminal_outcome(terminal.outcome),
                "dispositions": dispositions,
            }
        )
    rounds = [
        {
            "round_id": item.round_id,
            "status": item.status,
            "concept_refs": sorted(item.concept_refs),
            "receipt_ids": sorted(item.receipt_ids),
            "covered_concept_refs": sorted(item.covered_concept_refs),
            "resolution_id": item.resolution_id,
            "unresolved_disagreements": sorted(
                item.unresolved_disagreements
            ),
        }
        for item in sorted(projection.review_rounds, key=lambda value: value.round_id)
    ]
    counts = {
        "territories": len(projection.territories),
        "concepts": len(projection.concepts),
        "concept_revisions": sum(
            len(item.revisions) for item in projection.concepts
        ),
        "memory_challengers": sum(
            item.origin == "memory_challenger" for item in projection.concepts
        ),
        "review_rounds": len(projection.review_rounds),
        "final_ideas": len(ordered_ideas),
    }
    return {
        "schema_version": 1,
        "route": {
            "id": "creative",
            "contract_version": projection.route_contract_version,
        },
        "run_id": projection.run_id,
        "status": "completed",
        "challenge_ref": projection.challenge_ref,
        "creative_brief_ref": projection.creative_brief_ref,
        "idea_memory": {
            "mode": projection.memory.mode,
            "snapshot_ref": projection.memory.snapshot_ref,
            "snapshot_sha256": projection.memory.snapshot_sha256,
            "status": projection.memory.status,
            "selected_cue_ids": sorted(projection.memory.selected_cue_ids),
            "successful_challenger_refs": sorted(
                projection.memory.successful_challenger_refs
            ),
            "failed_task_refs": sorted(projection.memory.failed_task_refs),
            "source_record_refs": sorted(projection.memory.source_record_refs),
        },
        "counts": counts,
        "territory_ids": sorted(
            item.territory_ref for item in projection.territories
        ),
        "concepts": concepts,
        "review_rounds": rounds,
        "zero_reason_code": projection.zero_reason_code,
        "empty_batch_skip_reason": projection.empty_batch_skip_reason,
        "final_idea_card_ids": [
            _card_artifact_id(item.idea_id) for item in ordered_ideas
        ],
        "handoff_refs": [
            _handoff_artifact_id(item.idea_id) for item in ordered_ideas
        ],
        "memory_record_ref": MEMORY_RECORD_ARTIFACT_ID,
        "report_policy_version": projection.report_policy_version,
    }


def _report_markdown_bytes(
    projection: CreativeReportProjection,
    *,
    cards: Mapping[str, RenderedOutput],
) -> bytes:
    lines = [
        "# Creative Idea Report",
        "",
        f"Run: `{projection.run_id}`",
        "",
        f"Route contract: `creative/{projection.route_contract_version}`",
        "",
        "## Challenge",
        "",
        f"Artifact: `{projection.challenge_ref}` / `{projection.challenge_sha256}`",
        "",
    ]
    _append_exact_sections(
        lines,
        projection.challenge_markdown,
        CHALLENGE_BRIEF_HEADINGS,
    )
    lines.extend(
        [
            "## Creative Brief",
            "",
            (
                f"Artifact: `{projection.creative_brief_ref}` / "
                f"`{projection.creative_brief_sha256}`"
            ),
            "",
        ]
    )
    _append_exact_sections(
        lines,
        projection.creative_brief_markdown,
        (
            LEGACY_CREATIVE_BRIEF_HEADINGS
            if projection.route_contract_version
            == LEGACY_CREATIVE_CONTRACT_VERSION
            else CREATIVE_BRIEF_HEADINGS
        ),
    )
    lines.extend(["## Creative Territories", ""])
    if projection.territories:
        for territory in sorted(
            projection.territories,
            key=lambda item: item.territory_ref,
        ):
            lines.extend(
                [
                    f"### {territory.territory_ref} — {title_of(territory.markdown)}",
                    "",
                    f"Content hash: `{territory.sha256}`",
                    "",
                ]
            )
    else:
        lines.extend(["No Territory was generated.", ""])

    lines.extend(["## All Concepts", ""])
    if projection.concepts:
        for concept in sorted(
            projection.concepts,
            key=lambda item: item.concept_id,
        ):
            lines.extend(
                [
                    f"### {concept.concept_id}",
                    "",
                    f"Origin: `{concept.origin}`",
                    "",
                ]
            )
            for revision in concept.ordered_revisions:
                lines.extend(
                    [
                        f"#### {revision.revision_ref}",
                        "",
                        (
                            "One-sentence Hook: "
                            + extract_exact_markdown_section(
                                revision.markdown,
                                "One-sentence Hook",
                            )
                        ),
                        "",
                        (
                            "Audience Action: "
                            + extract_exact_markdown_section(
                                revision.markdown,
                                "Audience Action",
                            )
                        ),
                        "",
                        (
                            "Core Mechanism: "
                            + extract_exact_markdown_section(
                                revision.markdown,
                                "Real Input, Transformation and Output",
                            )
                        ),
                        "",
                        (
                            "Reveal: "
                            + extract_exact_markdown_section(
                                revision.markdown,
                                "Setup, Reveal and Aftertaste",
                            )
                        ),
                        "",
                    ]
                )
    else:
        lines.extend(["No Concept was generated.", ""])

    lines.extend(["## Candidate Fate Ledger", ""])
    if projection.concepts:
        for concept in sorted(
            projection.concepts,
            key=lambda item: item.concept_id,
        ):
            for revision in concept.ordered_revisions:
                lines.append(
                    f"- `{revision.revision_ref}` / `{revision.sha256}`"
                )
                for disposition in sorted(
                    revision.dispositions,
                    key=lambda item: item.disposition_ref,
                ):
                    target = (
                        f"; target `{disposition.target_ref}`"
                        if disposition.target_ref is not None
                        else ""
                    )
                    reasons = ", ".join(sorted(disposition.reason_codes)) or "none"
                    evidence = ", ".join(sorted(disposition.evidence_refs)) or "none"
                    lines.append(
                        "  - "
                        f"`{disposition.stage.value}` → "
                        f"`{disposition.outcome.value}` "
                        f"(terminal={str(disposition.terminal).lower()}{target}); "
                        f"reasons: {reasons}; decision: "
                        f"`{disposition.decision_ref}`; evidence: {evidence}"
                    )
        lines.append("")
    else:
        lines.extend(["The candidate ledger is empty.", ""])

    lines.extend(
        [
            "## Idea Memory Used",
            "",
            f"Mode: `{projection.memory.mode}`",
            "",
            f"Status: `{projection.memory.status}`",
            "",
            (
                f"Frozen snapshot: `{projection.memory.snapshot_ref}` / "
                f"`{projection.memory.snapshot_sha256}`"
            ),
            "",
            (
                "Selected cues: "
                + _inline_refs(projection.memory.selected_cue_ids)
            ),
            "",
            (
                "Source records: "
                + _inline_refs(projection.memory.source_record_refs)
            ),
            "",
            (
                "Optional failed tasks: "
                + _inline_refs(projection.memory.failed_task_refs)
            ),
            "",
            "## Memory-derived Branches",
            "",
        ]
    )
    memory_concepts = [
        concept
        for concept in projection.concepts
        if concept.origin == "memory_challenger"
    ]
    if memory_concepts:
        for concept in sorted(memory_concepts, key=lambda item: item.concept_id):
            terminal = concept.latest_revision.terminal_disposition
            source_refs = [
                item.source_artifact_id
                for item in sorted(
                    concept.memory_source_refs,
                    key=lambda value: value.stable_key,
                )
            ]
            lines.extend(
                [
                    f"- `{concept.concept_id}`",
                    f"  - cues: {_inline_refs(concept.memory_cue_refs)}",
                    f"  - historical sources: {_inline_refs(source_refs)}",
                    (
                        "  - terminal fate: "
                        f"`{terminal.outcome.value}` / "
                        f"{', '.join(sorted(terminal.reason_codes)) or 'no reason code'}"
                    ),
                ]
            )
        lines.append("")
    else:
        lines.extend(["No memory-derived challenger was produced.", ""])

    lines.extend(["## Human Review", ""])
    if projection.review_rounds:
        for round_ in sorted(
            projection.review_rounds,
            key=lambda item: item.round_id,
        ):
            lines.extend(
                [
                    f"- `{round_.round_id}`: `{round_.status}`",
                    f"  - candidates: {len(round_.concept_refs)}",
                    f"  - de-identified receipts: {len(round_.receipt_ids)}",
                    f"  - covered candidates: {len(round_.covered_concept_refs)}",
                    (
                        "  - resolution: "
                        + (
                            f"`{round_.resolution_id}`"
                            if round_.resolution_id is not None
                            else "none"
                        )
                    ),
                ]
            )
        lines.append("")
    else:
        lines.extend(["No human review round was required.", ""])

    lines.extend(["## Final Ideas", ""])
    if projection.final_ideas:
        for idea in sorted(projection.final_ideas, key=lambda item: item.idea_id):
            card = cards[idea.idea_id]
            lines.extend(
                [
                    (
                        f"- `{card.artifact_id}` — {title_of(idea.markdown)} "
                        f"(`{card.sha256}`)"
                    ),
                    (
                        "  - Human Signal is a concept-stage proxy signal, "
                        "not proof of real-world sharing."
                    ),
                ]
            )
        lines.append("")
    else:
        lines.extend(["This run produced zero Final Ideas.", ""])

    if projection.zero_reason_code is not None:
        lines.extend(
            [
                "## Zero-Idea Explanation",
                "",
                f"Zero reason: `{projection.zero_reason_code}`",
                "",
                (
                    "Empty C6 batch skip reason: "
                    + (
                        f"`{projection.empty_batch_skip_reason}`"
                        if projection.empty_batch_skip_reason is not None
                        else "not applicable; the human round closed with no kept Idea"
                    )
                ),
                "",
            ]
        )
        if projection.concepts:
            for concept in sorted(
                projection.concepts,
                key=lambda item: item.concept_id,
            ):
                terminal = concept.latest_revision.terminal_disposition
                lines.extend(
                    [
                        f"- `{concept.latest_revision.revision_ref}`",
                        f"  - terminal stage: `{terminal.stage.value}`",
                        f"  - outcome: `{terminal.outcome.value}`",
                        (
                            "  - reason codes: "
                            + (", ".join(sorted(terminal.reason_codes)) or "none")
                        ),
                        f"  - decision: `{terminal.decision_ref}`",
                        (
                            "  - evidence: "
                            + _inline_refs(terminal.evidence_refs)
                        ),
                    ]
                )
            lines.append("")
        else:
            lines.extend(
                [
                    (
                        "- No Concept was generated, so there is no candidate "
                        "disposition to omit."
                    ),
                    "",
                ]
            )
    return "\n".join(lines).encode("utf-8")


def _memory_record_payload(
    projection: CreativeReportProjection,
    *,
    report_sha256: str,
) -> dict[str, Any]:
    final_ids = {idea.idea_id for idea in projection.final_ideas}
    promoted_sources = {
        revision.revision_ref
        for concept in projection.concepts
        for revision in concept.ordered_revisions
        if (
            revision.terminal_disposition.outcome
            is DispositionOutcome.PROMOTED_TO_FINAL
            and revision.terminal_disposition.target_ref in final_ids
        )
    }
    entries: list[dict[str, Any]] = []
    for concept in sorted(projection.concepts, key=lambda item: item.concept_id):
        for revision in concept.ordered_revisions:
            if revision.revision_ref in promoted_sources:
                continue
            terminal = revision.terminal_disposition
            classification = expected_memory_classification(
                source_kind="concept_revision",
                terminal_outcome=terminal.outcome.value,
                reason_codes=terminal.reason_codes,
            )
            reason_evidence = (
                [
                    item.to_dict()
                    for item in sorted(
                        terminal.reason_evidence,
                        key=lambda value: (
                            value.reason_code,
                            value.source_review_ref,
                        ),
                    )
                ]
                if (
                    terminal.stage is DispositionStage.C4
                    and terminal.outcome is DispositionOutcome.ELIMINATED
                )
                else []
            )
            entries.append(
                _memory_entry(
                    memory_entry_id=f"memory-{revision.revision_ref}",
                    source_kind="concept_revision",
                    source_candidate_ref=revision.revision_ref,
                    source_candidate_sha256=revision.sha256,
                    source_concept_refs=(concept.concept_id,),
                    primary_territory_ref=revision.primary_territory_ref,
                    markdown=revision.markdown,
                    terminal_outcome=terminal.outcome.value,
                    reason_codes=terminal.reason_codes,
                    reason_evidence=reason_evidence,
                    evidence_refs=terminal.evidence_refs,
                    classification=classification,
                    include_software_fields=(
                        projection.route_contract_version
                        == CREATIVE_CONTRACT_VERSION
                    ),
                )
            )
    for idea in sorted(projection.final_ideas, key=lambda item: item.idea_id):
        entries.append(
            _memory_entry(
                memory_entry_id=f"memory-{idea.idea_id}",
                source_kind="final_idea",
                source_candidate_ref=idea.idea_id,
                source_candidate_sha256=idea.sha256,
                source_concept_refs=idea.source_concept_refs,
                primary_territory_ref=idea.primary_territory_ref,
                markdown=idea.markdown,
                terminal_outcome="promoted_to_final",
                reason_codes=(),
                reason_evidence=[],
                evidence_refs=tuple(
                    sorted(
                        {
                            *idea.decision_refs,
                            *(item.novelty_ref for item in idea.novelty),
                        }
                    )
                ),
                classification="positive",
                include_software_fields=(
                    projection.route_contract_version
                    == CREATIVE_CONTRACT_VERSION
                ),
            )
        )
    entries.sort(key=lambda item: str(item["memory_entry_id"]))
    payload = {
        "memory_schema_version": (
            1
            if projection.route_contract_version
            == LEGACY_CREATIVE_CONTRACT_VERSION
            else 2
        ),
        "source_run_id": projection.run_id,
        "source_route": {
            "id": "creative",
            "contract_version": projection.route_contract_version,
        },
        "source_report_artifact_id": REPORT_MARKDOWN_ARTIFACT_ID,
        "source_report_sha256": report_sha256,
        "created_at": projection.created_at,
        "producer_kind": projection.producer_kind,
        "zero_reason_code": projection.zero_reason_code,
        "challenge_context": {
            "summary": extract_exact_markdown_section(
                projection.challenge_markdown,
                "Challenge Summary",
            ),
            "intended_reactions": extract_exact_markdown_section(
                projection.creative_brief_markdown,
                "Intended Reactions",
            ),
        },
        "entries": entries,
    }
    reject_private_memory_fields(payload)
    return payload


def _memory_entry(
    *,
    memory_entry_id: str,
    source_kind: Literal["concept_revision", "final_idea"],
    source_candidate_ref: str,
    source_candidate_sha256: str,
    source_concept_refs: Sequence[str],
    primary_territory_ref: str,
    markdown: str,
    terminal_outcome: str,
    reason_codes: Sequence[str],
    reason_evidence: Sequence[Mapping[str, str]],
    evidence_refs: Sequence[str],
    classification: str,
    include_software_fields: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "memory_entry_id": memory_entry_id,
        "source_kind": source_kind,
        "source_candidate_ref": source_candidate_ref,
        "source_candidate_sha256": source_candidate_sha256,
        "source_concept_refs": sorted(source_concept_refs),
        "primary_territory_ref": primary_territory_ref,
        "one_sentence_hook": extract_exact_markdown_section(
            markdown,
            "One-sentence Hook",
        ),
        "audience_action": extract_exact_markdown_section(
            markdown,
            "Audience Action",
        ),
        "core_mechanism": extract_exact_markdown_section(
            markdown,
            "Real Input, Transformation and Output",
        ),
        "reveal_pattern": extract_exact_markdown_section(
            markdown,
            "Setup, Reveal and Aftertaste",
        ),
        "intended_reaction": extract_exact_markdown_section(
            markdown,
            "Intended Reaction",
        ),
        "terminal_outcome": terminal_outcome,
        "reason_codes": sorted(reason_codes),
        "reason_evidence": list(reason_evidence),
        "evidence_refs": sorted(evidence_refs),
        "classification": classification,
    }
    if include_software_fields:
        payload.update(
            {
                "software_core_and_runtime": extract_exact_markdown_section(
                    markdown,
                    "Software Core and Runtime",
                ),
                "share_trigger_and_artifact": extract_exact_markdown_section(
                    markdown,
                    "Share Trigger and Artifact",
                ),
                "minimum_hackathon_demo": extract_exact_markdown_section(
                    markdown,
                    "Minimum Hackathon Demo",
                ),
            }
        )
    return {
        "capsule_sha256": sha256_json(payload),
        **payload,
    }


def _report_terminal_outcome(outcome: DispositionOutcome) -> str:
    if outcome is DispositionOutcome.ELIMINATED:
        return "c4_eliminated"
    return outcome.value


def _append_exact_sections(
    lines: list[str],
    markdown: str,
    headings: Sequence[str],
) -> None:
    for heading in headings:
        lines.extend(
            [
                f"### {heading}",
                "",
                extract_exact_markdown_section(markdown, heading),
                "",
            ]
        )


def _inline_refs(values: Sequence[str]) -> str:
    return ", ".join(f"`{value}`" for value in sorted(values)) or "none"


def _json_file_bytes(value: Any) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def _card_artifact_id(idea_id: str) -> str:
    return f"{idea_id}-card"


def _handoff_artifact_id(idea_id: str) -> str:
    return f"{idea_id}-handoff"


def _require_sha(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise CreativeReportError(f"{label} must be a lowercase SHA-256")


def _require_ref(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_REF.fullmatch(value):
        raise CreativeReportError(f"{label} must be a safe stable reference")


def _require_unique_refs(values: Sequence[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise CreativeReportError(f"{label} contains duplicates")
    for value in values:
        _require_ref(value, label)


def _require_unique_text(values: Sequence[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise CreativeReportError(f"{label} contains duplicates")
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise CreativeReportError(f"{label} must contain non-empty strings")
        _reject_local_path(value, label)
        if len(value.encode("utf-8")) > 8 * 1024:
            raise CreativeReportError(f"{label} exceeds its text budget")


def _reject_local_path(value: str, label: str) -> None:
    if _LOCAL_PATH.search(value):
        raise CreativeReportError(f"{label} contains an absolute local path")


def _validate_concept_markdown(markdown: str, *, label: str) -> None:
    """Accept exact v2 or frozen v1 Concept section contracts."""

    try:
        validate_markdown(
            markdown,
            required_h2=CONCEPT_HEADINGS,
            label=label,
        )
    except ArtifactError as current_error:
        try:
            validate_markdown(
                markdown,
                required_h2=LEGACY_CONCEPT_HEADINGS,
                label=label,
            )
        except ArtifactError:
            raise current_error


__all__ = [
    "CreativeReportError",
    "CreativeReportProjection",
    "DispositionProjection",
    "FinalIdeaProjection",
    "HumanSignalProjection",
    "IDEA_CARD_INDEX_ARTIFACT_ID",
    "MEMORY_RECORD_ARTIFACT_ID",
    "MemoryUseProjection",
    "NoveltyProjection",
    "REPORT_JSON_ARTIFACT_ID",
    "REPORT_MARKDOWN_ARTIFACT_ID",
    "ReasonEvidenceProjection",
    "RenderedOutput",
    "RenderedReportBundle",
    "ReviewRoundProjection",
    "TerritoryProjection",
    "ConceptProjection",
    "ConceptRevisionProjection",
    "render_success_report",
]
