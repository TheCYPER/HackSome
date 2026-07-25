"""Build the typed C7 report projection from one consistent RunHub snapshot.

The renderer in :mod:`hacksome.creative.report` is deliberately pure.  This
module owns the opposite side of that boundary: decoding the persisted C0-C6
state, re-checking every hash-bound input, and refusing to project an
unfinished or ambiguous lineage.

When the caller does not already hold the finalization snapshot, exactly one
``RunHub.load_consistent_snapshot()`` call is used for run state and ledgers.
The finalization coordinator may instead pass its preloaded snapshot.  Artifact,
input, and frozen-resource bytes are then checked against that snapshot without
re-reading ``run.json`` or a JSONL ledger.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Mapping, Sequence

from hacksome.creative.contracts import (
    CREATIVE_CONTRACT_VERSION,
    CREATIVE_PROMPT_POLICY_VERSION,
    CREATIVE_REPORT_POLICY_VERSION,
    CREATIVE_STAGE_POLICY_VERSION,
    LEGACY_CREATIVE_CONTRACT_VERSION,
    LEGACY_CREATIVE_PROMPT_POLICY_VERSION,
    LEGACY_CREATIVE_REPORT_POLICY_VERSION,
    LEGACY_CREATIVE_STAGE_POLICY_VERSION,
    OPTIONAL_MEMORY_STAGES,
    ConceptDisposition,
    DispositionOutcome,
    DispositionStage,
    StableReasonCode,
    parse_concept_revision_ref,
)
from hacksome.creative.memory import (
    IdeaMemorySnapshot,
    MemoryCapsuleRef,
    MemoryStageSummary,
)
from hacksome.creative.prompting import creative_prompt_catalog_for_contract
from hacksome.creative.report import (
    ConceptProjection,
    ConceptRevisionProjection,
    CreativeReportError,
    CreativeReportProjection,
    DispositionProjection,
    FinalIdeaProjection,
    HumanSignalProjection,
    MemoryUseProjection,
    NoveltyProjection,
    ReasonEvidenceProjection,
    ReviewRoundProjection,
    TerritoryProjection,
)
from hacksome.creative.review import (
    FeedbackFragment,
    HumanResolution,
    HumanReview,
    ReviewBatch,
    ReviewRound,
    _human_resolution_from_record,
    _human_review_from_record,
    latest_receipt_set_sha256,
)
from hacksome.hub import RUN_SCHEMA_VERSION, RunHub
from hacksome.state import sha256_bytes, sha256_json


_EMPTY_COMPLETE_STAGE = "creative-c6-empty-complete-internal"
_FEEDBACK_COMPLETE_STAGE = "creative-c6-feedback-complete-internal"
_FINALIZATION_STAGE = "creative-finalization"
_ALLOWED_SOURCE_STAGES = frozenset(
    {
        _EMPTY_COMPLETE_STAGE,
        _FEEDBACK_COMPLETE_STAGE,
        _FINALIZATION_STAGE,
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LOCAL_PATH = re.compile(
    r"(?:^|[\s(])/(?:Users|home|private|tmp|var)/|"
    r"(?:^|[\s(])[A-Za-z]:\\"
)
_FINAL_OUTCOMES = frozenset(
    {
        DispositionOutcome.PROMOTED_TO_FINAL,
        DispositionOutcome.REVISED_INTO,
        DispositionOutcome.MERGED_INTO,
    }
)
_OUTCOME_BY_ACTION = {
    "keep": DispositionOutcome.PROMOTED_TO_FINAL,
    "revise": DispositionOutcome.REVISED_INTO,
    "merge": DispositionOutcome.MERGED_INTO,
}
_STAGE_BY_OUTCOME = {
    DispositionOutcome.PASS: DispositionStage.C4,
    DispositionOutcome.REPAIR: DispositionStage.C4,
    DispositionOutcome.ELIMINATED: DispositionStage.C4,
    DispositionOutcome.SUPERSEDED_BY_HOOK_REPAIR: DispositionStage.C4,
    DispositionOutcome.SUPERSEDED_BY_EVIDENCE_REVISION: DispositionStage.C6A,
    DispositionOutcome.SHORTLISTED: DispositionStage.C6B,
    DispositionOutcome.NOT_SHORTLISTED: DispositionStage.C6B,
    DispositionOutcome.PROMOTED_TO_FINAL: DispositionStage.C6C,
    DispositionOutcome.REVISED_INTO: DispositionStage.C6C,
    DispositionOutcome.HUMAN_REJECT: DispositionStage.C6C,
    DispositionOutcome.HUMAN_TASTE_VETO: DispositionStage.C6C,
    DispositionOutcome.MERGED_INTO: DispositionStage.C6C,
}
_MACHINE_REASON_CODES = frozenset(
    {
        StableReasonCode.SETUP_NOT_QUICKLY_LEGIBLE.value,
        StableReasonCode.REVEAL_DOES_NOT_SHIFT_EXPECTATION.value,
        StableReasonCode.SURPRISE_NOT_MECHANISM_DRIVEN.value,
        StableReasonCode.MISSES_THIRTY_SECOND_MOMENT.value,
        StableReasonCode.NOT_ONE_SENTENCE_RETAINABLE.value,
        StableReasonCode.REQUIRES_HIDDEN_LABOR_OR_IMPOSSIBLE_CAPABILITY.value,
        StableReasonCode.SHARE_TRIGGER_NOT_IMMEDIATE_OR_CONCRETE.value,
        StableReasonCode.CORE_NOT_SOFTWARE_FIRST.value,
        StableReasonCode.REQUIRES_CUSTOM_HARDWARE_OR_FABRICATION.value,
        StableReasonCode.CORE_IS_MANUAL_PERFORMANCE_OR_INSTALLATION.value,
        StableReasonCode.NO_RUNNABLE_END_TO_END_DEMO_PATH.value,
        StableReasonCode.REQUIRES_UNAVAILABLE_DEPENDENCY_OR_PERMISSION.value,
        StableReasonCode.NOT_BUILDABLE_WITHIN_HACKATHON_BUDGET.value,
        StableReasonCode.DEMO_DOES_NOT_PROVE_CORE_MECHANISM.value,
    }
)


@dataclass(frozen=True, slots=True)
class _Artifact:
    artifact_id: str
    artifact_type: str
    path: str
    sha256: str
    task_id: str | None
    source_refs: tuple[str, ...]
    metadata: Mapping[str, Any]
    created_at: str
    text: str


@dataclass(frozen=True, slots=True)
class _ReviewProjection:
    batch: ReviewBatch
    review_round: ReviewRound | None
    latest_reviews: tuple[HumanReview, ...]
    resolution: HumanResolution | None
    projection: ReviewRoundProjection


def build_report_projection(
    run_dir: str | Path | RunHub,
    *,
    producer_kind: Literal["live", "fixture"] = "live",
    snapshot: Mapping[str, Any] | None = None,
) -> CreativeReportProjection:
    """Decode a completed C6 hand-off into the pure C7 renderer contract.

    The function intentionally does not call ``RunHub.validate()`` because that
    would load a second state snapshot.  Every required route-neutral and
    Creative-specific invariant is checked against the supplied snapshot, or
    against the one snapshot loaded here when ``snapshot`` is omitted.
    """

    hub = run_dir if isinstance(run_dir, RunHub) else RunHub(run_dir)
    consistent_snapshot = (
        hub.load_consistent_snapshot() if snapshot is None else snapshot
    )
    return _ProjectionBuilder(
        hub.run_dir,
        consistent_snapshot,
        producer_kind=producer_kind,
    ).build()


class _ProjectionBuilder:
    def __init__(
        self,
        run_dir: Path,
        snapshot: Mapping[str, Any],
        *,
        producer_kind: Literal["live", "fixture"],
    ) -> None:
        if producer_kind not in {"live", "fixture"}:
            raise CreativeReportError("producer_kind must be live or fixture")
        self.run_dir = run_dir.resolve()
        self.producer_kind = producer_kind
        self.state = _mapping(snapshot.get("state"), "consistent snapshot state")
        self.ledgers = _mapping(
            snapshot.get("ledgers"),
            "consistent snapshot ledgers",
        )
        self.inputs: dict[str, Mapping[str, Any]] = {}
        self.tasks: dict[str, Mapping[str, Any]] = {}
        self.artifacts: dict[str, _Artifact] = {}
        self.decisions: dict[str, Mapping[str, Any]] = {}
        self.memory_snapshot: IdeaMemorySnapshot | None = None
        self.memory_summary: MemoryStageSummary | None = None

    def build(self) -> CreativeReportProjection:
        self._verify_run_envelope()
        self._verify_inputs_and_resources()
        self._verify_tasks()
        self._load_artifacts()
        self._load_decisions()

        challenge = self._single_artifact("creative_challenge_brief")
        brief = self._single_artifact("creative_brief")
        territories = tuple(
            TerritoryProjection(
                territory_ref=item.artifact_id,
                sha256=item.sha256,
                markdown=item.text,
            )
            for item in self._artifacts_of_type("creative_territory")
        )
        memory = self._memory_projection()
        concepts, revision_index = self._concept_projections(
            memory_successors=set(memory.successful_challenger_refs),
        )
        review = self._review_projection()
        final_ideas = self._final_idea_projections(
            revision_index,
            review=review,
        )
        zero_reason, skip_reason = self._zero_reason(
            concepts,
            final_ideas,
            review,
        )

        route = _mapping(self.state.get("route"), "route metadata")
        projection = CreativeReportProjection(
            run_id=_string(self.state.get("run_id"), "run_id"),
            created_at=_string(self.state.get("created_at"), "created_at"),
            producer_kind=self.producer_kind,
            challenge_ref=challenge.artifact_id,
            challenge_sha256=challenge.sha256,
            challenge_markdown=challenge.text,
            creative_brief_ref=brief.artifact_id,
            creative_brief_sha256=brief.sha256,
            creative_brief_markdown=brief.text,
            territories=territories,
            concepts=concepts,
            memory=memory,
            review_rounds=(review.projection,),
            final_ideas=final_ideas,
            zero_reason_code=zero_reason,
            empty_batch_skip_reason=skip_reason,
            route_contract_version=_string(
                route.get("contract_version"),
                "contract_version",
            ),
            prompt_policy_version=_string(
                route.get("prompt_policy_version"),
                "prompt_policy_version",
            ),
            stage_policy_version=_string(
                route.get("stage_policy_version"),
                "stage_policy_version",
            ),
            report_policy_version=_string(
                route.get("report_policy_version"),
                "report_policy_version",
            ),
        )
        self._verify_terminal_closure(projection)
        return projection

    def _verify_run_envelope(self) -> None:
        if self.state.get("schema_version") != RUN_SCHEMA_VERSION:
            raise CreativeReportError(
                "C7 report projection requires a v2 RunHub state"
            )
        route = _mapping(self.state.get("route"), "route metadata")
        contract_version = _string(
            route.get("contract_version"),
            "contract_version",
        )
        policy_by_contract = {
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
        policies = policy_by_contract.get(contract_version)
        expected_route = (
            {
                "id": "creative",
                "contract_version": contract_version,
                "prompt_policy_version": policies[0],
                "stage_policy_version": policies[1],
                "report_policy_version": policies[2],
            }
            if policies is not None
            else {"id": "creative", "contract_version": None}
        )
        for key, expected in expected_route.items():
            if route.get(key) != expected:
                raise CreativeReportError(
                    f"unsupported Creative route {key}: {route.get(key)!r}"
                )
        if self.state.get("status") != "running":
            raise CreativeReportError(
                "C7 report projection requires a running pre-publication run"
            )
        if self.state.get("current_stage") not in _ALLOWED_SOURCE_STAGES:
            raise CreativeReportError(
                "C7 report projection requires a completed C6 hand-off"
            )
        if self.state.get("terminal_error") is not None:
            raise CreativeReportError(
                "a run with a terminal error cannot produce a success report"
            )
        if self.state.get("pending_records") != []:
            raise CreativeReportError(
                "all Hub ledger outbox records must be reconciled before C7"
            )
        if self.state.get("result_artifact_ids") != []:
            raise CreativeReportError(
                "C7 projection cannot replace exposed result artifacts"
            )
        if self.state.get("finalization") is not None:
            raise CreativeReportError(
                "an existing finalization plan must be replayed, not re-rendered"
            )

        hashes = _mapping(self.state.get("config_hashes"), "config_hashes")
        for value_key, hash_key in (
            ("codex_config", "codex_config_sha256"),
            ("settings", "workflow_settings_sha256"),
        ):
            expected_hash = _sha256(hashes.get(hash_key), hash_key)
            if sha256_json(self.state.get(value_key)) != expected_hash:
                raise CreativeReportError(f"{value_key} hash mismatch")

    def _verify_inputs_and_resources(self) -> None:
        raw_inputs = _mapping(self.state.get("inputs"), "run inputs")
        for name, raw in sorted(raw_inputs.items()):
            record = _mapping(raw, f"input {name}")
            path = _string(record.get("path"), f"input {name} path")
            digest = _sha256(record.get("sha256"), f"input {name} sha256")
            self._read_hash_bound_file(path, digest, label=f"input {name}")
            self.inputs[name] = record
        for required in ("challenge", "creative_brief", "idea_memory"):
            if required not in self.inputs:
                raise CreativeReportError(f"Creative run is missing input {required}")

        manifest = _mapping(
            self.state.get("resource_manifest"),
            "resource manifest reference",
        )
        manifest_path = _string(
            manifest.get("path"),
            "resource manifest path",
        )
        manifest_sha256 = _sha256(
            manifest.get("sha256"),
            "resource manifest sha256",
        )
        self._read_hash_bound_file(
            manifest_path,
            manifest_sha256,
            label="resource manifest",
        )
        route = _mapping(self.state.get("route"), "route metadata")
        try:
            creative_prompt_catalog_for_contract(
                _string(route.get("contract_version"), "contract_version")
            ).load_frozen(
                self.run_dir,
                route_id="creative",
                contract_version=_string(
                    route.get("contract_version"),
                    "contract_version",
                ),
                prompt_policy_version=_string(
                    route.get("prompt_policy_version"),
                    "prompt_policy_version",
                ),
                stage_policy_version=_string(
                    route.get("stage_policy_version"),
                    "stage_policy_version",
                ),
                manifest_sha256=manifest_sha256,
            )
        except Exception as exc:
            raise CreativeReportError(
                f"frozen Creative resources failed verification: {exc}"
            ) from exc

    def _verify_tasks(self) -> None:
        raw_tasks = _mapping(self.state.get("tasks"), "run tasks")
        for task_id, raw in sorted(raw_tasks.items()):
            task = _mapping(raw, f"task {task_id}")
            if task.get("task_id") != task_id:
                raise CreativeReportError(f"task registry key mismatch: {task_id}")
            status = task.get("status")
            failure_policy = task.get("failure_policy", "fatal")
            stage = task.get("stage")
            if status != "succeeded":
                optional_failure = (
                    status in {"failed", "invalidated"}
                    and failure_policy == "optional_branch"
                    and stage in OPTIONAL_MEMORY_STAGES
                )
                if not optional_failure:
                    raise CreativeReportError(
                        f"unfinished or fatal task blocks C7: {task_id}"
                    )
            for path_key, hash_key in (
                ("request_path", "request_sha256"),
                ("prompt_path", "prompt_sha256"),
            ):
                self._verify_task_file(task, task_id, path_key, hash_key)
            if status == "succeeded":
                for path_key, hash_key in (
                    ("result_path", "result_sha256"),
                    ("output_path", "output_sha256"),
                ):
                    self._verify_task_file(task, task_id, path_key, hash_key)
            self.tasks[task_id] = task

    def _verify_task_file(
        self,
        task: Mapping[str, Any],
        task_id: str,
        path_key: str,
        hash_key: str,
    ) -> None:
        path = _string(task.get(path_key), f"task {task_id} {path_key}")
        digest = _sha256(task.get(hash_key), f"task {task_id} {hash_key}")
        self._read_hash_bound_file(
            path,
            digest,
            label=f"task {task_id} {path_key}",
        )

    def _load_artifacts(self) -> None:
        raw_artifacts = _mapping(self.state.get("artifacts"), "run artifacts")
        seen_paths: set[str] = set()
        for artifact_id, raw in sorted(raw_artifacts.items()):
            record = _mapping(raw, f"artifact {artifact_id}")
            expected_fields = {
                "artifact_id",
                "artifact_type",
                "path",
                "sha256",
                "task_id",
                "source_refs",
                "metadata",
                "created_at",
            }
            if set(record) != expected_fields:
                raise CreativeReportError(
                    f"artifact {artifact_id} has an invalid record shape"
                )
            if record.get("artifact_id") != artifact_id:
                raise CreativeReportError(
                    f"artifact registry key mismatch: {artifact_id}"
                )
            path = _string(record.get("path"), f"artifact {artifact_id} path")
            if path in seen_paths:
                raise CreativeReportError(f"duplicate artifact path: {path}")
            seen_paths.add(path)
            digest = _sha256(
                record.get("sha256"),
                f"artifact {artifact_id} sha256",
            )
            content = self._read_hash_bound_file(
                path,
                digest,
                label=f"artifact {artifact_id}",
            )
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CreativeReportError(
                    f"artifact {artifact_id} is not UTF-8"
                ) from exc
            task_id = record.get("task_id")
            if task_id is not None:
                task_id = _string(task_id, f"artifact {artifact_id} task_id")
                task = self.tasks.get(task_id)
                if task is None or task.get("status") != "succeeded":
                    raise CreativeReportError(
                        f"artifact {artifact_id} has no successful producer task"
                    )
            source_refs = _string_tuple(
                record.get("source_refs"),
                f"artifact {artifact_id} source_refs",
            )
            if len(source_refs) != len(set(source_refs)):
                raise CreativeReportError(
                    f"artifact {artifact_id} has duplicate source refs"
                )
            self.artifacts[artifact_id] = _Artifact(
                artifact_id=artifact_id,
                artifact_type=_string(
                    record.get("artifact_type"),
                    f"artifact {artifact_id} type",
                ),
                path=path,
                sha256=digest,
                task_id=task_id,
                source_refs=source_refs,
                metadata=_mapping(
                    record.get("metadata"),
                    f"artifact {artifact_id} metadata",
                ),
                created_at=_string(
                    record.get("created_at"),
                    f"artifact {artifact_id} created_at",
                ),
                text=text,
            )

        for artifact in self.artifacts.values():
            for reference in artifact.source_refs:
                if reference.startswith("input:"):
                    if reference.removeprefix("input:") not in self.inputs:
                        raise CreativeReportError(
                            f"{artifact.artifact_id} cites unknown input {reference}"
                        )
                elif reference in self.artifacts:
                    continue
                elif reference in self.tasks:
                    continue
                # Event IDs and hash-bound cross-run identifiers are valid
                # route-owned references but are not local artifact paths.

    def _load_decisions(self) -> None:
        rows = _row_list(self.ledgers.get("decisions"), "decision ledger")
        for row in rows:
            decision_id = _string(row.get("decision_id"), "decision_id")
            if decision_id in self.decisions:
                raise CreativeReportError(
                    f"duplicate decision ID: {decision_id}"
                )
            if row.get("route_id") != "creative":
                raise CreativeReportError(
                    f"non-Creative decision in Creative run: {decision_id}"
                )
            self.decisions[decision_id] = row

    def _memory_projection(self) -> MemoryUseProjection:
        input_record = self.inputs["idea_memory"]
        snapshot_path = _string(
            input_record.get("path"),
            "Idea Memory snapshot path",
        )
        snapshot_sha256 = _sha256(
            input_record.get("sha256"),
            "Idea Memory snapshot sha256",
        )
        snapshot_bytes = self._read_hash_bound_file(
            snapshot_path,
            snapshot_sha256,
            label="Idea Memory snapshot",
        )
        try:
            snapshot_raw = json.loads(snapshot_bytes)
            snapshot = IdeaMemorySnapshot.from_mapping(snapshot_raw)
        except Exception as exc:
            raise CreativeReportError(
                f"Idea Memory snapshot is invalid: {exc}"
            ) from exc
        if (
            input_record.get("mode") != snapshot.mode
            or input_record.get("source") != snapshot.created_from
            or input_record.get("eligible_entry_count")
            != snapshot.eligible_entry_count
            or input_record.get("diagnostic_count")
            != len(snapshot.diagnostics)
        ):
            raise CreativeReportError(
                "Idea Memory input metadata does not match its snapshot"
            )

        summary_artifact = self._single_artifact(
            "creative_memory_stage_summary"
        )
        try:
            summary_raw = json.loads(summary_artifact.text)
            summary = MemoryStageSummary.from_mapping(summary_raw)
        except Exception as exc:
            raise CreativeReportError(
                f"Idea Memory stage summary is invalid: {exc}"
            ) from exc
        if snapshot.mode == "off" and summary.status != "disabled":
            raise CreativeReportError(
                "disabled Idea Memory requires a disabled stage summary"
            )
        if (
            snapshot.mode == "auto"
            and not snapshot.entries
            and summary.status != "empty"
        ):
            raise CreativeReportError(
                "empty Idea Memory snapshot requires an empty stage summary"
            )
        self.memory_snapshot = snapshot
        self.memory_summary = summary

        successful = tuple(
            sorted(
                slot.challenger_ref
                for slot in summary.remix_slots
                if slot.status == "succeeded"
                and slot.challenger_ref is not None
            )
        )
        failed_tasks = tuple(
            sorted(
                {
                    *(
                        (summary.recall.task_ref,)
                        if summary.recall.status in {"failed", "invalidated"}
                        and summary.recall.task_ref is not None
                        else ()
                    ),
                    *(
                        slot.task_ref
                        for slot in summary.remix_slots
                        if slot.status in {"failed", "invalidated"}
                        and slot.task_ref is not None
                    ),
                }
            )
        )
        source_record_refs = tuple(
            sorted(
                f"{source.source_run_id}:{source.source_memory_record_artifact_id}"
                for source in snapshot.source_records
            )
        )
        return MemoryUseProjection(
            mode=snapshot.mode,
            snapshot_ref="input:idea_memory",
            snapshot_sha256=snapshot_sha256,
            status=summary.status,
            selected_cue_ids=tuple(sorted(summary.selected_cue_ids)),
            successful_challenger_refs=successful,
            failed_task_refs=failed_tasks,
            source_record_refs=source_record_refs,
        )

    def _concept_projections(
        self,
        *,
        memory_successors: set[str],
    ) -> tuple[
        tuple[ConceptProjection, ...],
        dict[str, ConceptRevisionProjection],
    ]:
        concept_artifacts = self._artifacts_of_type("creative_concept")
        dispositions = self._dispositions_by_revision()
        grouped: dict[str, list[_Artifact]] = {}
        for artifact in concept_artifacts:
            concept_id, revision = parse_concept_revision_ref(
                artifact.artifact_id
            )
            metadata = artifact.metadata
            if (
                metadata.get("concept_id") != concept_id
                or metadata.get("revision") != revision
            ):
                raise CreativeReportError(
                    f"Concept metadata identity mismatch: {artifact.artifact_id}"
                )
            grouped.setdefault(concept_id, []).append(artifact)

        concepts: list[ConceptProjection] = []
        revision_index: dict[str, ConceptRevisionProjection] = {}
        for concept_id, records in sorted(grouped.items()):
            ordered = sorted(
                records,
                key=lambda item: parse_concept_revision_ref(item.artifact_id)[1],
            )
            revision_numbers = [
                parse_concept_revision_ref(item.artifact_id)[1]
                for item in ordered
            ]
            if revision_numbers != list(range(1, len(ordered) + 1)):
                raise CreativeReportError(
                    f"{concept_id} revisions are not contiguous"
                )
            origin = _string(ordered[0].metadata.get("origin"), "Concept origin")
            if origin not in {"base", "memory_challenger"}:
                raise CreativeReportError(f"{concept_id} has invalid origin")
            primary = _string(
                ordered[0].metadata.get("primary_territory_ref"),
                "Concept primary_territory_ref",
            )
            parent_atoms = _string_tuple(
                ordered[0].metadata.get("parent_atom_refs"),
                "Concept parent_atom_refs",
            )
            if not parent_atoms:
                raise CreativeReportError(
                    f"{concept_id} requires Parent Atoms"
                )
            parent_territories: set[str] = set()
            for atom_ref in parent_atoms:
                atom = self.artifacts.get(atom_ref)
                if atom is None or atom.artifact_type != "creative_atom":
                    raise CreativeReportError(
                        f"{concept_id} cites a missing Parent Atom: {atom_ref}"
                    )
                parent_territories.add(
                    _string(
                        atom.metadata.get("territory_ref"),
                        f"Atom {atom_ref} territory_ref",
                    )
                )
            if primary not in parent_territories:
                raise CreativeReportError(
                    f"{concept_id} primary Territory is not from a Parent Atom"
                )
            memory_refs = self._memory_refs(ordered[0])
            memory_cues = _string_tuple(
                ordered[0].metadata.get("memory_cue_refs", []),
                "Concept memory_cue_refs",
            )
            if origin == "base" and (memory_refs or memory_cues):
                raise CreativeReportError(
                    f"base Concept claims memory provenance: {concept_id}"
                )
            if origin == "memory_challenger":
                if not memory_refs or not memory_cues:
                    raise CreativeReportError(
                        f"memory challenger lacks provenance: {concept_id}"
                    )
                if ordered[0].artifact_id not in memory_successors:
                    raise CreativeReportError(
                        f"memory summary omits challenger: {ordered[0].artifact_id}"
                    )
                summary = self.memory_summary
                if summary is None or not set(memory_cues).issubset(
                    summary.selected_cue_ids
                ):
                    raise CreativeReportError(
                        f"memory challenger cites an unselected cue: {concept_id}"
                    )

            revisions: list[ConceptRevisionProjection] = []
            for index, artifact in enumerate(ordered):
                metadata = artifact.metadata
                if (
                    metadata.get("origin") != origin
                    or metadata.get("primary_territory_ref") != primary
                    or tuple(metadata.get("parent_atom_refs", ())) != parent_atoms
                    or self._memory_refs(artifact) != memory_refs
                    or tuple(metadata.get("memory_cue_refs", ())) != memory_cues
                ):
                    raise CreativeReportError(
                        f"{concept_id} changed immutable lineage metadata"
                    )
                if index == 0:
                    if metadata.get("supersedes_ref") is not None:
                        raise CreativeReportError(
                            f"{artifact.artifact_id} cannot supersede an earlier revision"
                        )
                    expected_initial_reason = (
                        "initial_synthesis"
                        if origin == "base"
                        else "memory_remix"
                    )
                    if (
                        metadata.get("revision_reason")
                        != expected_initial_reason
                    ):
                        raise CreativeReportError(
                            f"{artifact.artifact_id} has an invalid initial "
                            "revision reason"
                        )
                elif metadata.get("supersedes_ref") != ordered[index - 1].artifact_id:
                    raise CreativeReportError(
                        f"{artifact.artifact_id} does not supersede its predecessor"
                    )
                elif metadata.get("revision_reason") not in {
                    "cheap_hook_repair",
                    "evidence_informed",
                }:
                    raise CreativeReportError(
                        f"{artifact.artifact_id} has an invalid revision reason"
                    )
                projected = ConceptRevisionProjection(
                    revision_ref=artifact.artifact_id,
                    sha256=artifact.sha256,
                    markdown=artifact.text,
                    primary_territory_ref=primary,
                    parent_atom_refs=parent_atoms,
                    dispositions=tuple(
                        sorted(
                            dispositions.get(artifact.artifact_id, ()),
                            key=lambda item: item.disposition_ref,
                        )
                    ),
                )
                projected.terminal_disposition
                revisions.append(projected)
                revision_index[artifact.artifact_id] = projected
            reasons = [
                artifact.metadata.get("revision_reason")
                for artifact in ordered[1:]
            ]
            if (
                reasons.count("cheap_hook_repair") > 1
                or reasons.count("evidence_informed") > 1
                or (
                    "cheap_hook_repair" in reasons
                    and reasons.index("cheap_hook_repair") != 0
                )
                or (
                    "evidence_informed" in reasons
                    and reasons[-1] != "evidence_informed"
                )
            ):
                raise CreativeReportError(
                    f"{concept_id} violates the bounded revision order"
                )
            concepts.append(
                ConceptProjection(
                    concept_id=concept_id,
                    origin=origin,  # type: ignore[arg-type]
                    revisions=tuple(revisions),
                    memory_source_refs=memory_refs,
                    memory_cue_refs=memory_cues,
                )
            )

        if set(dispositions) - set(revision_index):
            unknown = sorted(set(dispositions) - set(revision_index))
            raise CreativeReportError(
                f"dispositions cite unknown Concept revisions: {unknown}"
            )
        actual_memory = {
            concept.revisions[0].revision_ref
            for concept in concepts
            if concept.origin == "memory_challenger"
        }
        if actual_memory != memory_successors:
            raise CreativeReportError(
                "Idea Memory summary and challenger artifacts disagree"
            )
        return tuple(concepts), revision_index

    def _memory_refs(
        self,
        artifact: _Artifact,
    ) -> tuple[MemoryCapsuleRef, ...]:
        raw = artifact.metadata.get("memory_source_refs", [])
        if not isinstance(raw, list):
            raise CreativeReportError(
                f"{artifact.artifact_id} memory_source_refs must be an array"
            )
        try:
            values = tuple(MemoryCapsuleRef.from_mapping(item) for item in raw)
        except Exception as exc:
            raise CreativeReportError(
                f"{artifact.artifact_id} has invalid memory provenance: {exc}"
            ) from exc
        snapshot = self.memory_snapshot
        if snapshot is None:
            raise CreativeReportError(
                "Idea Memory snapshot must be loaded before Concepts"
            )
        allowed = {
            capsule.memory_ref.stable_key for capsule in snapshot.entries
        }
        if any(value.stable_key not in allowed for value in values):
            raise CreativeReportError(
                f"{artifact.artifact_id} cites memory outside the frozen snapshot"
            )
        return tuple(sorted(values, key=lambda item: item.stable_key))

    def _dispositions_by_revision(
        self,
    ) -> dict[str, list[DispositionProjection]]:
        result: dict[str, list[DispositionProjection]] = {}
        for artifact in self._artifacts_of_type(
            "creative_concept_disposition"
        ):
            raw = self._json_artifact(artifact)
            expected = {
                "disposition_id",
                "concept_revision_ref",
                "concept_sha256",
                "stage",
                "outcome",
                "terminal",
                "target_ref",
                "reason_codes",
                "decision_ref",
                "evidence_refs",
                "task_refs",
            }
            if set(raw) != expected:
                raise CreativeReportError(
                    f"disposition {artifact.artifact_id} has invalid fields"
                )
            try:
                disposition = ConceptDisposition(
                    disposition_id=_string(
                        raw.get("disposition_id"),
                        "disposition_id",
                    ),
                    concept_revision_ref=_string(
                        raw.get("concept_revision_ref"),
                        "concept_revision_ref",
                    ),
                    concept_sha256=_sha256(
                        raw.get("concept_sha256"),
                        "concept_sha256",
                    ),
                    stage=DispositionStage(
                        _string(raw.get("stage"), "disposition stage")
                    ),
                    outcome=DispositionOutcome(
                        _string(raw.get("outcome"), "disposition outcome")
                    ),
                    terminal=_boolean(
                        raw.get("terminal"),
                        "disposition terminal",
                    ),
                    target_ref=_optional_string(
                        raw.get("target_ref"),
                        "disposition target_ref",
                    ),
                    reason_codes=_string_tuple(
                        raw.get("reason_codes"),
                        "disposition reason_codes",
                    ),
                    decision_ref=_string(
                        raw.get("decision_ref"),
                        "disposition decision_ref",
                    ),
                    evidence_refs=_string_tuple(
                        raw.get("evidence_refs"),
                        "disposition evidence_refs",
                    ),
                    task_refs=_string_tuple(
                        raw.get("task_refs"),
                        "disposition task_refs",
                    ),
                )
            except Exception as exc:
                raise CreativeReportError(
                    f"invalid disposition {artifact.artifact_id}: {exc}"
                ) from exc
            if disposition.disposition_id != artifact.artifact_id:
                raise CreativeReportError(
                    f"disposition artifact ID mismatch: {artifact.artifact_id}"
                )
            if disposition.stage is not _STAGE_BY_OUTCOME[
                disposition.outcome
            ]:
                raise CreativeReportError(
                    f"disposition stage/outcome mismatch: {artifact.artifact_id}"
                )
            concept_artifact = self.artifacts.get(
                disposition.concept_revision_ref
            )
            if (
                concept_artifact is None
                or concept_artifact.artifact_type != "creative_concept"
                or concept_artifact.sha256 != disposition.concept_sha256
            ):
                raise CreativeReportError(
                    f"disposition has a stale Concept binding: {artifact.artifact_id}"
                )
            decision = self.decisions.get(disposition.decision_ref)
            if decision is None:
                raise CreativeReportError(
                    f"disposition has no machine decision: {artifact.artifact_id}"
                )
            if disposition.concept_revision_ref not in _string_tuple(
                decision.get("subject_refs"),
                f"decision {disposition.decision_ref} subject_refs",
            ):
                raise CreativeReportError(
                    f"decision omits disposition subject: {artifact.artifact_id}"
                )
            if not set(disposition.evidence_refs).issubset(
                _string_tuple(
                    decision.get("evidence_refs"),
                    f"decision {disposition.decision_ref} evidence_refs",
                )
            ):
                raise CreativeReportError(
                    f"decision omits disposition evidence: {artifact.artifact_id}"
                )
            if not set(disposition.task_refs).issubset(
                _string_tuple(
                    decision.get("task_ids"),
                    f"decision {disposition.decision_ref} task_ids",
                )
            ):
                raise CreativeReportError(
                    f"decision omits disposition tasks: {artifact.artifact_id}"
                )
            for reference in disposition.evidence_refs:
                if reference not in self.artifacts:
                    raise CreativeReportError(
                        f"disposition cites missing evidence artifact: {reference}"
                    )
            for task_ref in disposition.task_refs:
                if task_ref not in self.tasks:
                    raise CreativeReportError(
                        f"disposition cites missing task: {task_ref}"
                    )
            projected = DispositionProjection(
                disposition_ref=disposition.disposition_id,
                stage=disposition.stage,
                outcome=disposition.outcome,
                terminal=disposition.terminal,
                target_ref=disposition.target_ref,
                reason_codes=tuple(sorted(disposition.reason_codes)),
                decision_ref=disposition.decision_ref,
                evidence_refs=tuple(sorted(disposition.evidence_refs)),
                task_refs=tuple(sorted(disposition.task_refs)),
                reason_evidence=self._reason_evidence(disposition),
            )
            result.setdefault(
                disposition.concept_revision_ref,
                [],
            ).append(projected)
        return result

    def _reason_evidence(
        self,
        disposition: ConceptDisposition,
    ) -> tuple[ReasonEvidenceProjection, ...]:
        wanted = _MACHINE_REASON_CODES.intersection(
            disposition.reason_codes
        )
        rows: dict[tuple[str, str, str], ReasonEvidenceProjection] = {}
        if not wanted:
            return ()
        for reference in sorted(disposition.evidence_refs):
            artifact = self.artifacts.get(reference)
            if (
                artifact is None
                or artifact.artifact_type
                not in {
                    "creative_cheap_hook_review",
                    "creative_software_demo_review",
                }
            ):
                continue
            raw = self._json_artifact(artifact)
            dimensions = raw.get("dimensions")
            if not isinstance(dimensions, list):
                raise CreativeReportError(
                    f"Concept screen Review {reference} has no dimensions"
                )
            for item in dimensions:
                row = _mapping(
                    item,
                    f"Concept screen Review {reference} dimension",
                )
                reason_code = row.get("reason_code")
                if reason_code not in wanted:
                    continue
                evidence = _string(
                    row.get("evidence"),
                    f"Concept screen Review {reference} evidence",
                )
                projected = ReasonEvidenceProjection(
                    reason_code=str(reason_code),
                    evidence_excerpt=evidence,
                    source_review_ref=reference,
                    source_review_sha256=artifact.sha256,
                )
                rows[(str(reason_code), reference, evidence)] = projected
        return tuple(rows[key] for key in sorted(rows))

    def _review_projection(self) -> _ReviewProjection:
        batch_artifact = self._single_artifact(
            "creative_human_review_batch"
        )
        try:
            batch = ReviewBatch.from_dict(self._json_artifact(batch_artifact))
        except Exception as exc:
            raise CreativeReportError(f"invalid Human Review batch: {exc}") from exc
        if (
            batch.batch_id != batch_artifact.artifact_id
            or batch.run_id != self.state.get("run_id")
            or batch_artifact.metadata.get("batch_sha256")
            != batch.batch_sha256
            or batch_artifact.metadata.get("status") != batch.status
            or batch_artifact.metadata.get("skip_reason")
            != batch.skip_reason
        ):
            raise CreativeReportError("Human Review batch binding is stale")

        review_rows = _row_list(
            self.ledgers.get("human_reviews"),
            "human review ledger",
        )
        resolution_rows = _row_list(
            self.ledgers.get("human_resolutions"),
            "human resolution ledger",
        )
        if batch.status == "skipped_empty":
            if review_rows or resolution_rows:
                raise CreativeReportError(
                    "skipped Human Review batch cannot have human ledger records"
                )
            if self.state.get("wait") is not None:
                raise CreativeReportError(
                    "skipped Human Review batch cannot retain a wait"
                )
            projection = ReviewRoundProjection(
                round_id="creative-review-round-001",
                status="skipped_empty",
                concept_refs=(),
                receipt_ids=(),
                covered_concept_refs=(),
                resolution_id=None,
            )
            return _ReviewProjection(
                batch=batch,
                review_round=None,
                latest_reviews=(),
                resolution=None,
                projection=projection,
            )

        review_round = ReviewRound.open(batch)
        wait = _mapping(self.state.get("wait"), "closed Human Review wait")
        if (
            wait.get("kind") != "creative_human_review"
            or wait.get("status") != "closed"
            or wait.get("round_id") != review_round.round_id
            or wait.get("round_artifact_id") != batch_artifact.artifact_id
            or wait.get("round_sha256") != review_round.round_sha256
            or wait.get("batch_sha256") != batch.batch_sha256
            or wait.get("batch_artifact_sha256") != batch_artifact.sha256
        ):
            raise CreativeReportError(
                "ready Human Review batch requires an exact closed wait"
            )
        latest = self._latest_reviews(review_rows, review_round)
        if len(resolution_rows) != 1:
            raise CreativeReportError(
                "closed Human Review round requires exactly one resolution"
            )
        try:
            resolution = _human_resolution_from_record(
                resolution_rows[0],
                review_round,
            )
        except Exception as exc:
            raise CreativeReportError(
                f"persisted Human Resolution is invalid: {exc}"
            ) from exc
        self._validate_resolution(
            resolution,
            review_round=review_round,
            latest=latest,
        )
        if (
            wait.get("resolution_id") != resolution.resolution_id
            or wait.get("resolution_sha256") != resolution.resolution_sha256
            or wait.get("latest_receipt_set_sha256")
            != resolution.latest_receipt_set_sha256
            or wait.get("approved_feedback_set_sha256")
            != resolution.approved_feedback_set_sha256
        ):
            raise CreativeReportError(
                "closed wait does not match its Human Resolution"
            )
        covered = tuple(
            sorted(
                {
                    item.concept_ref
                    for review in latest
                    for item in review.concept_reviews
                }
            )
        )
        disagreements = self._round_disagreements(
            review_round,
            latest,
            resolution,
        )
        projection = ReviewRoundProjection(
            round_id=review_round.round_id,
            status="closed",
            concept_refs=tuple(
                item.concept_ref for item in review_round.concepts
            ),
            receipt_ids=tuple(
                sorted(review.review_id for review in latest)
            ),
            covered_concept_refs=covered,
            resolution_id=resolution.resolution_id,
            unresolved_disagreements=disagreements,
        )
        return _ReviewProjection(
            batch=batch,
            review_round=review_round,
            latest_reviews=latest,
            resolution=resolution,
            projection=projection,
        )

    def _latest_reviews(
        self,
        rows: Sequence[Mapping[str, Any]],
        review_round: ReviewRound,
    ) -> tuple[HumanReview, ...]:
        latest: dict[str, HumanReview] = {}
        known: set[str] = set()
        for raw in rows:
            try:
                review = _human_review_from_record(raw, review_round)
            except Exception as exc:
                raise CreativeReportError(
                    f"persisted Human Review is invalid: {exc}"
                ) from exc
            if review.review_id in known:
                raise CreativeReportError(
                    f"duplicate Human Review ID: {review.review_id}"
                )
            prior = latest.get(review.reviewer_id)
            if prior is None:
                if (
                    review.supersedes_review_id is not None
                    or review.independence != "pre_reveal"
                ):
                    raise CreativeReportError(
                        "first Human Review must be independent and pre-reveal"
                    )
            elif (
                review.supersedes_review_id != prior.review_id
                or review.independence != "post_reveal"
            ):
                raise CreativeReportError(
                    "Human Review edit must supersede that reviewer's latest receipt"
                )
            known.add(review.review_id)
            latest[review.reviewer_id] = review
        return tuple(latest[key] for key in sorted(latest))

    def _validate_resolution(
        self,
        resolution: HumanResolution,
        *,
        review_round: ReviewRound,
        latest: Sequence[HumanReview],
    ) -> None:
        if resolution.latest_receipt_set_sha256 != latest_receipt_set_sha256(
            latest
        ):
            raise CreativeReportError(
                "Human Resolution latest receipt set hash mismatch"
            )
        covered = {
            item.concept_ref
            for review in latest
            for item in review.concept_reviews
        }
        uncovered = tuple(
            binding.concept_ref
            for binding in review_round.concepts
            if binding.concept_ref not in covered
        )
        if resolution.uncovered_concept_refs != uncovered:
            raise CreativeReportError(
                "Human Resolution uncovered Concept set mismatch"
            )
        if uncovered and not resolution.coverage_override_reason:
            raise CreativeReportError(
                "Human Resolution lacks required coverage override"
            )
        if not uncovered and resolution.coverage_override_reason is not None:
            raise CreativeReportError(
                "Human Resolution has an unnecessary coverage override"
            )
        action_by_ref = {
            action.concept_ref: action for action in resolution.actions
        }
        if (
            len(action_by_ref) != len(resolution.actions)
            or set(action_by_ref) != set(review_round.bindings)
        ):
            raise CreativeReportError(
                "Human Resolution must act exactly once on every shortlist Concept"
            )
        group_by_source: dict[str, str] = {}
        for group in resolution.merge_groups:
            if len(group.source_refs) < 2:
                raise CreativeReportError("merge group requires at least two sources")
            for source in group.source_refs:
                if (
                    source not in review_round.bindings
                    or source in group_by_source
                ):
                    raise CreativeReportError(
                        "Human Resolution has invalid or overlapping merge sources"
                    )
                group_by_source[source] = group.merge_group_id
        fragments = self._feedback_fragments(review_round, latest)
        approved_set: set[tuple[str, str]] = set()
        for action in resolution.actions:
            expected_group = group_by_source.get(action.concept_ref)
            if action.action == "merge":
                if action.merge_group_id != expected_group:
                    raise CreativeReportError(
                        "merge action does not match its merge group"
                    )
            elif action.merge_group_id is not None or expected_group is not None:
                raise CreativeReportError(
                    "non-merge action conflicts with a merge group"
                )
            if action.action == "taste_veto" and not action.reason.strip():
                raise CreativeReportError("taste veto requires a reason")
            guidance = False
            for approved in action.approved_feedback:
                fragment = fragments.get(approved.feedback_ref)
                if (
                    fragment is None
                    or fragment.feedback_sha256 != approved.feedback_sha256
                    or action.concept_ref not in fragment.related_concept_refs
                ):
                    raise CreativeReportError(
                        f"Human Resolution cites stale feedback: "
                        f"{approved.feedback_ref}"
                    )
                approved_set.add(
                    (approved.feedback_ref, approved.feedback_sha256)
                )
                guidance = guidance or fragment.has_guidance
            if (
                action.action in {"revise", "merge"}
                and not guidance
                and action.curator_instruction_sha256 is None
            ):
                raise CreativeReportError(
                    f"{action.action} action lacks approved guidance"
                )
        if {
            action.concept_ref
            for action in resolution.actions
            if action.action == "merge"
        } != set(group_by_source):
            raise CreativeReportError(
                "Human Resolution merge actions and groups disagree"
            )
        expected_approved_hash = sha256_json(
            [
                {
                    "feedback_ref": reference,
                    "feedback_sha256": digest,
                }
                for reference, digest in sorted(approved_set)
            ]
        )
        if (
            resolution.approved_feedback_set_sha256
            != expected_approved_hash
        ):
            raise CreativeReportError(
                "Human Resolution approved feedback set hash mismatch"
            )

    def _feedback_fragments(
        self,
        review_round: ReviewRound,
        latest: Sequence[HumanReview],
    ) -> dict[str, FeedbackFragment]:
        result: dict[str, FeedbackFragment] = {}
        all_concepts = tuple(review_round.bindings)
        for review in latest:
            for concept_item in review.concept_reviews:
                result[concept_item.feedback_ref] = FeedbackFragment(
                    feedback_ref=concept_item.feedback_ref,
                    feedback_sha256=concept_item.feedback_sha256,
                    kind="concept",
                    review_id=review.review_id,
                    reviewer_id=review.reviewer_id,
                    related_concept_refs=(concept_item.concept_ref,),
                    payload=concept_item.fragment_payload(),
                    has_guidance=True,
                )
            for pair_item in review.pairwise:
                result[pair_item.feedback_ref] = FeedbackFragment(
                    feedback_ref=pair_item.feedback_ref,
                    feedback_sha256=pair_item.feedback_sha256,
                    kind="pair",
                    review_id=review.review_id,
                    reviewer_id=review.reviewer_id,
                    related_concept_refs=tuple(
                        sorted((pair_item.left_ref, pair_item.right_ref))
                    ),
                    payload=pair_item.fragment_payload(),
                    has_guidance=True,
                )
            result[review.overall_feedback_ref] = FeedbackFragment(
                feedback_ref=review.overall_feedback_ref,
                feedback_sha256=review.overall_feedback_sha256,
                kind="overall",
                review_id=review.review_id,
                reviewer_id=review.reviewer_id,
                related_concept_refs=all_concepts,
                payload=review.overall_fragment_payload(),
                has_guidance=bool(review.overall_comment.strip()),
            )
        return result

    def _round_disagreements(
        self,
        review_round: ReviewRound,
        latest: Sequence[HumanReview],
        resolution: HumanResolution,
    ) -> tuple[str, ...]:
        action_by_ref = {
            action.concept_ref: action.action for action in resolution.actions
        }
        values: list[str] = []
        for binding in review_round.concepts:
            recommendations = sorted(
                {
                    item.recommendation
                    for review in latest
                    for item in review.concept_reviews
                    if item.concept_ref == binding.concept_ref
                    and item.recommendation != "no_opinion"
                }
            )
            action = action_by_ref[binding.concept_ref]
            if len(recommendations) > 1:
                values.append(
                    f"{binding.concept_ref}: reviewer recommendations "
                    f"diverged ({', '.join(recommendations)})"
                )
            elif recommendations and recommendations[0] != action:
                values.append(
                    f"{binding.concept_ref}: reviewer recommendation "
                    f"{recommendations[0]} differed from curator action {action}"
                )
        return tuple(values)

    def _final_idea_projections(
        self,
        revision_index: Mapping[str, ConceptRevisionProjection],
        *,
        review: _ReviewProjection,
    ) -> tuple[FinalIdeaProjection, ...]:
        final_artifacts = self._artifacts_of_type("creative_final_idea")
        if final_artifacts and (
            review.review_round is None or review.resolution is None
        ):
            raise CreativeReportError(
                "Final Ideas require a closed Human Review resolution"
            )
        resolution = review.resolution
        action_by_ref = (
            {
                action.concept_ref: action
                for action in resolution.actions
            }
            if resolution is not None
            else {}
        )
        finals: list[FinalIdeaProjection] = []
        expected_ids = [
            f"creative-idea-{index:03d}"
            for index in range(1, len(final_artifacts) + 1)
        ]
        if [item.artifact_id for item in final_artifacts] != expected_ids:
            raise CreativeReportError(
                "Final Idea IDs must be contiguous and stably sorted"
            )
        for artifact in final_artifacts:
            metadata = artifact.metadata
            action = _string(metadata.get("action"), "Final Idea action")
            if action not in _OUTCOME_BY_ACTION:
                raise CreativeReportError(
                    f"{artifact.artifact_id} has invalid final action"
                )
            source_refs = _string_tuple(
                metadata.get("source_concept_refs"),
                "Final Idea source_concept_refs",
            )
            if (
                len(source_refs) != len(set(source_refs))
                or artifact.source_refs != source_refs
            ):
                raise CreativeReportError(
                    f"{artifact.artifact_id} source lineage is inconsistent"
                )
            if not source_refs or (
                action in {"keep", "revise"} and len(source_refs) != 1
            ) or (action == "merge" and len(source_refs) < 2):
                raise CreativeReportError(
                    f"{artifact.artifact_id} has invalid source count"
                )
            source_hashes = _string_tuple(
                metadata.get("source_concept_sha256s"),
                "Final Idea source_concept_sha256s",
            )
            if source_hashes != tuple(
                revision_index[reference].sha256
                if reference in revision_index
                else ""
                for reference in source_refs
            ):
                raise CreativeReportError(
                    f"{artifact.artifact_id} has stale source hashes"
                )
            source_territories = tuple(
                revision_index[reference].primary_territory_ref
                for reference in source_refs
            )
            if _string_tuple(
                metadata.get("source_primary_territory_refs"),
                "Final Idea source_primary_territory_refs",
            ) != source_territories:
                raise CreativeReportError(
                    f"{artifact.artifact_id} has stale source Territories"
                )
            primary_territory = _string(
                metadata.get("primary_territory_ref"),
                "Final Idea primary_territory_ref",
            )
            if primary_territory not in source_territories:
                raise CreativeReportError(
                    f"{artifact.artifact_id} invented a primary Territory"
                )
            resolution_id = _string(
                metadata.get("resolution_id"),
                "Final Idea resolution_id",
            )
            if (
                resolution is None
                or resolution_id != resolution.resolution_id
                or metadata.get("resolution_sha256")
                != resolution.resolution_sha256
            ):
                raise CreativeReportError(
                    f"{artifact.artifact_id} has stale resolution binding"
                )
            expected_outcome = _OUTCOME_BY_ACTION[action]
            terminal_dispositions = tuple(
                revision_index[reference].terminal_disposition
                for reference in source_refs
            )
            if any(
                item.outcome is not expected_outcome
                or item.target_ref != artifact.artifact_id
                for item in terminal_dispositions
            ):
                raise CreativeReportError(
                    f"{artifact.artifact_id} source dispositions do not match "
                    "its final action"
                )
            if any(
                action_by_ref.get(reference) is None
                or action_by_ref[reference].action != action
                for reference in source_refs
            ):
                raise CreativeReportError(
                    f"{artifact.artifact_id} does not match Human Resolution actions"
                )
            approved = self._approved_bindings(metadata)
            expected_approved = {
                (
                    binding.feedback_ref,
                    binding.feedback_sha256,
                )
                for reference in source_refs
                for binding in action_by_ref[reference].approved_feedback
            }
            if set(approved) != expected_approved:
                raise CreativeReportError(
                    f"{artifact.artifact_id} approved feedback is stale"
                )
            novelty = self._final_novelty(source_refs)
            human_signal = self._human_signal(
                source_refs,
                review=review,
                approved_feedback_refs=tuple(
                    sorted(reference for reference, _ in approved)
                ),
            )
            finals.append(
                FinalIdeaProjection(
                    idea_id=artifact.artifact_id,
                    sha256=artifact.sha256,
                    markdown=artifact.text,
                    primary_territory_ref=primary_territory,
                    source_concept_refs=tuple(sorted(source_refs)),
                    decision_refs=tuple(
                        sorted(
                            {
                                item.decision_ref
                                for item in terminal_dispositions
                            }
                        )
                    ),
                    resolution_id=resolution_id,
                    novelty=novelty,
                    human_signal=human_signal,
                )
            )
        return tuple(finals)

    def _approved_bindings(
        self,
        metadata: Mapping[str, Any],
    ) -> tuple[tuple[str, str], ...]:
        raw = metadata.get("approved_feedback", [])
        if not isinstance(raw, list):
            raise CreativeReportError(
                "Final Idea approved_feedback must be an array"
            )
        values: list[tuple[str, str]] = []
        for item in raw:
            row = _mapping(item, "Final Idea approved feedback")
            if set(row) != {"feedback_ref", "feedback_sha256"}:
                raise CreativeReportError(
                    "Final Idea approved feedback has invalid fields"
                )
            values.append(
                (
                    _string(row.get("feedback_ref"), "feedback_ref"),
                    _sha256(row.get("feedback_sha256"), "feedback_sha256"),
                )
            )
        if len(values) != len(set(values)):
            raise CreativeReportError(
                "Final Idea approved feedback contains duplicates"
            )
        return tuple(sorted(values))

    def _final_novelty(
        self,
        source_refs: Sequence[str],
    ) -> tuple[NoveltyProjection, ...]:
        refs: set[str] = set()
        for reference in source_refs:
            concept = self.artifacts[reference]
            novelty_ref = concept.metadata.get("novelty_scan_ref")
            if not isinstance(novelty_ref, str):
                # C6A stores the C5W scan on the evidence revision.  A fixture
                # may instead retain only the scan's source relation.
                candidates = [
                    item.artifact_id
                    for item in self._artifacts_of_type(
                        "creative_novelty_scan"
                    )
                    if reference in item.source_refs
                ]
                if len(candidates) != 1:
                    raise CreativeReportError(
                        f"{reference} requires exactly one Novelty Scan"
                    )
                novelty_ref = candidates[0]
            novelty = self.artifacts.get(novelty_ref)
            if (
                novelty is None
                or novelty.artifact_type != "creative_novelty_scan"
            ):
                raise CreativeReportError(
                    f"{reference} has a missing Novelty Scan"
                )
            refs.add(novelty_ref)
        return tuple(
            NoveltyProjection(
                novelty_ref=reference,
                sha256=self.artifacts[reference].sha256,
                markdown=self.artifacts[reference].text,
            )
            for reference in sorted(refs)
        )

    def _human_signal(
        self,
        source_refs: Sequence[str],
        *,
        review: _ReviewProjection,
        approved_feedback_refs: tuple[str, ...],
    ) -> HumanSignalProjection:
        source_set = set(source_refs)
        receipt_ids: set[str] = set()
        retells: set[str] = set()
        share_targets: set[str] = set()
        for receipt in review.latest_reviews:
            relevant = [
                item
                for item in receipt.concept_reviews
                if item.concept_ref in source_set
            ]
            if relevant:
                receipt_ids.add(receipt.review_id)
            for item in relevant:
                if item.one_sentence_retell.strip():
                    _reject_local_path(
                        item.one_sentence_retell,
                        "Human Signal retell",
                    )
                    retells.add(item.one_sentence_retell)
                if item.share_target.strip():
                    _reject_local_path(
                        item.share_target,
                        "Human Signal share target",
                    )
                    share_targets.add(item.share_target)
        disagreements = tuple(
            value
            for value in review.projection.unresolved_disagreements
            if any(value.startswith(f"{reference}:") for reference in source_set)
        )
        return HumanSignalProjection(
            retells=tuple(sorted(retells)),
            share_targets=tuple(sorted(share_targets)),
            disagreements=disagreements,
            receipt_ids=tuple(sorted(receipt_ids)),
            approved_feedback_fragment_refs=approved_feedback_refs,
        )

    def _zero_reason(
        self,
        concepts: Sequence[ConceptProjection],
        final_ideas: Sequence[FinalIdeaProjection],
        review: _ReviewProjection,
    ) -> tuple[str | None, str | None]:
        if final_ideas:
            if review.batch.status != "ready":
                raise CreativeReportError(
                    "Final Ideas cannot accompany a skipped Human Review batch"
                )
            return None, None
        if review.batch.status == "skipped_empty":
            if review.batch.skip_reason is None:
                raise CreativeReportError(
                    "empty Human Review batch has no skip reason"
                )
            return review.batch.skip_reason, review.batch.skip_reason
        if not concepts:
            raise CreativeReportError(
                "closed Human Review round cannot have no Concepts"
            )
        return "all_human_rejected", None

    def _verify_terminal_closure(
        self,
        projection: CreativeReportProjection,
    ) -> None:
        revision_index = {
            revision.revision_ref: revision
            for concept in projection.concepts
            for revision in concept.ordered_revisions
        }
        final_index = {idea.idea_id: idea for idea in projection.final_ideas}
        for revision in revision_index.values():
            terminal = revision.terminal_disposition
            if terminal.outcome in {
                DispositionOutcome.SUPERSEDED_BY_HOOK_REPAIR,
                DispositionOutcome.SUPERSEDED_BY_EVIDENCE_REVISION,
            }:
                concept_target = revision_index.get(terminal.target_ref or "")
                if concept_target is None:
                    raise CreativeReportError(
                        f"{revision.revision_ref} has a missing Concept successor"
                    )
                source_id, source_revision = parse_concept_revision_ref(
                    revision.revision_ref
                )
                target_id, target_revision = parse_concept_revision_ref(
                    concept_target.revision_ref
                )
                if (
                    target_id != source_id
                    or target_revision != source_revision + 1
                ):
                    raise CreativeReportError(
                        f"{revision.revision_ref} has an illegal successor"
                    )
                expected_reason = (
                    "cheap_hook_repair"
                    if terminal.outcome
                    is DispositionOutcome.SUPERSEDED_BY_HOOK_REPAIR
                    else "evidence_informed"
                )
                if (
                    self.artifacts[concept_target.revision_ref]
                    .metadata.get("revision_reason")
                    != expected_reason
                ):
                    raise CreativeReportError(
                        f"{revision.revision_ref} successor consumed the wrong "
                        "revision budget"
                    )
            elif terminal.outcome in _FINAL_OUTCOMES:
                final_target = final_index.get(terminal.target_ref or "")
                if (
                    final_target is None
                    or revision.revision_ref
                    not in final_target.source_concept_refs
                ):
                    raise CreativeReportError(
                        f"{revision.revision_ref} has a missing Final Idea target"
                    )
            elif terminal.target_ref is not None:
                raise CreativeReportError(
                    f"{revision.revision_ref} has an illegal terminal target"
                )
        for concept in projection.concepts:
            latest = concept.latest_revision
            if latest.terminal_disposition.outcome in {
                DispositionOutcome.NOT_SHORTLISTED,
                DispositionOutcome.PROMOTED_TO_FINAL,
                DispositionOutcome.REVISED_INTO,
                DispositionOutcome.HUMAN_REJECT,
                DispositionOutcome.HUMAN_TASTE_VETO,
                DispositionOutcome.MERGED_INTO,
            } and (
                self.artifacts[latest.revision_ref]
                .metadata.get("revision_reason")
                != "evidence_informed"
            ):
                raise CreativeReportError(
                    f"{latest.revision_ref} reached C6 without its fixed "
                    "evidence revision"
                )

    def _single_artifact(self, artifact_type: str) -> _Artifact:
        values = self._artifacts_of_type(artifact_type)
        if len(values) != 1:
            raise CreativeReportError(
                f"expected exactly one {artifact_type} artifact"
            )
        return values[0]

    def _artifacts_of_type(self, artifact_type: str) -> tuple[_Artifact, ...]:
        return tuple(
            sorted(
                (
                    artifact
                    for artifact in self.artifacts.values()
                    if artifact.artifact_type == artifact_type
                ),
                key=lambda item: item.artifact_id,
            )
        )

    def _json_artifact(self, artifact: _Artifact) -> dict[str, Any]:
        try:
            raw = json.loads(artifact.text)
        except json.JSONDecodeError as exc:
            raise CreativeReportError(
                f"artifact {artifact.artifact_id} contains invalid JSON"
            ) from exc
        return dict(_mapping(raw, f"artifact {artifact.artifact_id} JSON"))

    def _read_hash_bound_file(
        self,
        relative_path: str,
        expected_sha256: str,
        *,
        label: str,
    ) -> bytes:
        path = PurePosixPath(relative_path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or str(path) != relative_path
        ):
            raise CreativeReportError(f"{label} has an unsafe path")
        candidate = self.run_dir.joinpath(*path.parts)
        cursor = self.run_dir
        for part in path.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise CreativeReportError(f"{label} path contains a symlink")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.run_dir)
        except (OSError, ValueError) as exc:
            raise CreativeReportError(f"{label} file is missing or escapes the run") from exc
        if not resolved.is_file():
            raise CreativeReportError(f"{label} is not a regular file")
        content = resolved.read_bytes()
        if sha256_bytes(content) != expected_sha256:
            raise CreativeReportError(f"{label} hash mismatch")
        return content


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CreativeReportError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise CreativeReportError(f"{label} keys must be strings")
    return value


def _row_list(value: Any, label: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        raise CreativeReportError(f"{label} must be an array")
    return tuple(_mapping(item, f"{label} record") for item in value)


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CreativeReportError(f"{label} must be a non-empty string")
    return value


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise CreativeReportError(f"{label} must be an array of strings")
    return tuple(value)


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise CreativeReportError(f"{label} must be a lowercase SHA-256")
    return value


def _boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise CreativeReportError(f"{label} must be boolean")
    return value


def _reject_local_path(value: str, label: str) -> None:
    if _LOCAL_PATH.search(value):
        raise CreativeReportError(f"{label} contains an absolute local path")


__all__ = ["build_report_projection"]
