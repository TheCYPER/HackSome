"""Bounded C6C feedback finalization for a closed human-review round.

The review store owns immutable receipts and the curator resolution.  This
module is the only owner of the business transition from that closed round to
Final Creative Ideas and terminal Concept dispositions.  It deliberately does
not render the C7 report.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from hacksome.stages.ideation.creative.contracts import (
    C6C_FEEDBACK_REVISE,
    RevisionReason,
    final_idea_id,
)
from hacksome.stages.ideation.creative.artifacts import CreativeValidationContext
from hacksome.stages.ideation.creative.review import (
    MAX_APPROVED_FEEDBACK_BYTES,
    MAX_APPROVED_FRAGMENTS_PER_ACTION,
    FeedbackFragment,
    HumanResolution,
    ResolutionAction,
    ReviewBatch,
    ReviewError,
    ReviewRound,
    ReviewStore,
)
from hacksome.core.state import canonical_json_bytes, sha256_json, sha256_text
from hacksome.core.task_executor import AgentTaskExecutionError

if TYPE_CHECKING:
    from hacksome.stages.ideation.creative.workflow import CreativeConcept, CreativeIdeaWorkflow


INTERNAL_C6_FEEDBACK_COMPLETE_STAGE = "creative-c6-feedback-complete-internal"


class CreativeFeedbackError(RuntimeError):
    """A closed C6 review round cannot be finalized safely."""


@dataclass(frozen=True, slots=True)
class CreativeFeedbackOutcome:
    """Validated hand-off from C6C to the deterministic C7 renderer."""

    run_dir: Any
    resolution_id: str
    final_idea_refs: tuple[str, ...]
    zero_reason_code: str | None


@dataclass(frozen=True, slots=True)
class _ResolutionContext:
    resolution: HumanResolution
    review_round: ReviewRound
    fragments: Mapping[str, FeedbackFragment]


@dataclass(frozen=True, slots=True)
class _FeedbackOperation:
    operation_key: str
    action: str
    sources: tuple[CreativeConcept, ...]
    resolution_actions: tuple[ResolutionAction, ...]
    merge_group_id: str | None

    @property
    def source_refs(self) -> tuple[str, ...]:
        return tuple(source.artifact_ref for source in self.sources)


@dataclass(frozen=True, slots=True)
class _ApprovedGuidance:
    fragments: tuple[FeedbackFragment, ...]
    instructions: tuple[tuple[str, str, str], ...]

    @property
    def fragment_bindings(self) -> tuple[dict[str, str], ...]:
        return tuple(
            {
                "feedback_ref": fragment.feedback_ref,
                "feedback_sha256": fragment.feedback_sha256,
            }
            for fragment in self.fragments
        )


@dataclass(frozen=True, slots=True)
class _PreparedFinalIdea:
    operation: _FeedbackOperation
    idea_ref: str
    markdown: str
    primary_territory_ref: str
    task_id: str | None


class CreativeFeedbackFinalizer:
    """Apply one immutable resolution without widening its feedback context."""

    def __init__(self, workflow: CreativeIdeaWorkflow) -> None:
        self.workflow = workflow
        self.hub = workflow.hub

    async def resume(self) -> CreativeFeedbackOutcome:
        """Finalize a closed round once, then hand verified state to C7."""

        self.hub.reconcile_pending()
        completed = self._completed_outcome()
        if completed is not None:
            return completed
        self._require_closed_wait()
        self.hub.set_run_status(
            "running",
            stage=C6C_FEEDBACK_REVISE,
            reason="closed human resolution accepted for bounded C6C finalization",
        )
        try:
            self.workflow._verify_execution_inputs()
            context = self._load_resolution_context()
            operations = self._resolution_operations(context.resolution)
            self._require_pristine_c6c(operations)
            guidance = {
                operation.operation_key: self._approved_guidance(
                    operation,
                    context.fragments,
                )
                for operation in operations
            }
            self._require_feedback_budgets(operations)

            final_operations = tuple(
                operation
                for operation in operations
                if operation.action in {"keep", "revise", "merge"}
            )
            prepared_finals: list[_PreparedFinalIdea] = []
            for idea_index, operation in enumerate(final_operations, start=1):
                prepared_finals.append(
                    await self._prepare_final_idea(
                        operation,
                        guidance[operation.operation_key],
                        idea_ref=final_idea_id(idea_index),
                        resolution=context.resolution,
                    )
                )

            # All requested Agent calls and semantic checks finish before the
            # first Final Idea is published.  A later C6C task failure can
            # therefore never strand an earlier unreferenced Final target.
            for prepared in prepared_finals:
                self._publish_prepared_final(
                    prepared,
                    guidance[prepared.operation.operation_key],
                    resolution=context.resolution,
                )
            target_by_operation = {
                prepared.operation.operation_key: prepared.idea_ref
                for prepared in prepared_finals
            }
            task_by_operation = {
                prepared.operation.operation_key: prepared.task_id
                for prepared in prepared_finals
            }

            # No terminal success is written until every requested Agent result
            # has passed schema, semantic, hash, and publication validation.
            for operation in operations:
                target_ref = target_by_operation.get(operation.operation_key)
                task_id = task_by_operation.get(operation.operation_key)
                binding_ref = self._publish_feedback_binding(
                    operation,
                    guidance[operation.operation_key],
                    resolution=context.resolution,
                    target_ref=target_ref,
                )
                decision_ref = self._record_resolution_decision(
                    operation,
                    resolution=context.resolution,
                    binding_ref=binding_ref,
                    target_ref=target_ref,
                    task_id=task_id,
                )
                self._publish_terminal_dispositions(
                    operation,
                    decision_ref=decision_ref,
                    binding_ref=binding_ref,
                    target_ref=target_ref,
                    task_id=task_id,
                )

            final_refs = tuple(
                target_by_operation[operation.operation_key]
                for operation in final_operations
            )
            zero_reason = None if final_refs else "all_human_rejected"
            self.hub.set_run_status(
                "running",
                stage=INTERNAL_C6_FEEDBACK_COMPLETE_STAGE,
                reason="C6C terminal dispositions are closed; ready for deterministic C7",
            )
            return CreativeFeedbackOutcome(
                run_dir=self.hub.run_dir,
                resolution_id=context.resolution.resolution_id,
                final_idea_refs=final_refs,
                zero_reason_code=zero_reason,
            )
        except Exception as exc:
            task_id = (
                exc.task_id
                if isinstance(exc, AgentTaskExecutionError)
                else None
            )
            self.hub.set_run_status(
                "failed",
                stage=C6C_FEEDBACK_REVISE,
                error=exc,
                task_id=task_id,
            )
            if isinstance(exc, CreativeFeedbackError):
                raise
            raise CreativeFeedbackError(str(exc)) from exc

    def _completed_outcome(self) -> CreativeFeedbackOutcome | None:
        """Return a verified prior C6C result without mutating the run."""

        state = self.hub.load_state()
        if not (
            state.get("status") == "running"
            and state.get("current_stage")
            == INTERNAL_C6_FEEDBACK_COMPLETE_STAGE
        ):
            return None
        context = self._load_resolution_context()
        operations = self._resolution_operations(context.resolution)
        artifacts = state.get("artifacts")
        if not isinstance(artifacts, dict):
            raise CreativeFeedbackError("run artifacts must be an object")
        final_refs = tuple(
            sorted(
                str(reference)
                for reference, record in artifacts.items()
                if isinstance(record, dict)
                and record.get("artifact_type") == "creative_final_idea"
            )
        )
        expected_final_count = sum(
            operation.action in {"keep", "revise", "merge"}
            for operation in operations
        )
        if len(final_refs) != expected_final_count:
            raise CreativeFeedbackError(
                "persisted C6C Final Idea count does not match its resolution"
            )
        final_set = set(final_refs)
        terminal_by_source: dict[str, list[dict[str, Any]]] = {
            source.artifact_ref: []
            for operation in operations
            for source in operation.sources
        }
        for reference, record in artifacts.items():
            if (
                not isinstance(record, dict)
                or record.get("artifact_type")
                != "creative_concept_disposition"
            ):
                continue
            try:
                payload = json.loads(self.hub.read_artifact(str(reference)))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise CreativeFeedbackError(
                    f"invalid Concept disposition {reference}: {exc}"
                ) from exc
            if (
                isinstance(payload, dict)
                and payload.get("stage") == "C6C"
                and payload.get("terminal") is True
                and payload.get("concept_revision_ref") in terminal_by_source
            ):
                terminal_by_source[
                    str(payload["concept_revision_ref"])
                ].append(payload)
        if any(len(rows) != 1 for rows in terminal_by_source.values()):
            raise CreativeFeedbackError(
                "persisted C6C result lacks exactly one terminal disposition "
                "per shortlisted Concept"
            )
        targets = {
            str(rows[0]["target_ref"])
            for rows in terminal_by_source.values()
            if rows[0].get("target_ref") is not None
        }
        if targets != final_set:
            raise CreativeFeedbackError(
                "persisted C6C dispositions do not close every Final Idea target"
            )
        for final_ref in final_refs:
            record = _artifact_record(self.workflow, final_ref)
            metadata = record.get("metadata")
            if (
                not isinstance(metadata, dict)
                or metadata.get("resolution_id")
                != context.resolution.resolution_id
                or metadata.get("resolution_sha256")
                != context.resolution.resolution_sha256
            ):
                raise CreativeFeedbackError(
                    f"Final Idea has stale resolution binding: {final_ref}"
                )
            self.hub.read_artifact(final_ref)
        return CreativeFeedbackOutcome(
            run_dir=self.hub.run_dir,
            resolution_id=context.resolution.resolution_id,
            final_idea_refs=final_refs,
            zero_reason_code=(
                None if final_refs else "all_human_rejected"
            ),
        )

    def _require_closed_wait(self) -> None:
        state = self.hub.load_state()
        wait = state.get("wait")
        if (
            state.get("route", {}).get("id")
            if isinstance(state.get("route"), dict)
            else None
        ) != "creative":
            raise CreativeFeedbackError("resume is only supported for a Creative run")
        if (
            state.get("status") != "waiting"
            or state.get("current_stage") != "creative-human-review"
            or not isinstance(wait, dict)
            or wait.get("kind") != "creative_human_review"
        ):
            raise CreativeFeedbackError(
                "C6C resume requires the persisted Creative human-review wait"
            )
        if wait.get("status") != "closed":
            raise CreativeFeedbackError(
                "the human-review round must be closed before resume"
            )
        if state.get("pending_records"):
            raise CreativeFeedbackError(
                "the closed resolution outbox must be reconciled before resume"
            )

    def _load_resolution_context(self) -> _ResolutionContext:
        state = self.hub.load_state()
        wait = state.get("wait")
        if not isinstance(wait, dict):
            raise CreativeFeedbackError("closed review wait is missing")
        batch_ref = wait.get("round_artifact_id")
        if not isinstance(batch_ref, str):
            raise CreativeFeedbackError("closed review wait has no batch artifact")
        batch_record = _artifact_record(self.workflow, batch_ref)
        if batch_record.get("artifact_type") != "creative_human_review_batch":
            raise CreativeFeedbackError("review wait does not reference a review batch")
        if wait.get("batch_artifact_sha256") != batch_record.get("sha256"):
            raise CreativeFeedbackError("review batch artifact hash changed")
        try:
            raw_batch = json.loads(self.hub.read_artifact(batch_ref))
            if not isinstance(raw_batch, dict):
                raise CreativeFeedbackError("review batch payload must be an object")
            batch = ReviewBatch.from_dict(raw_batch)
            review_round = ReviewRound.open(batch)
            store = ReviewStore(self.hub, review_round)
            snapshot = store.snapshot()
        except (OSError, UnicodeError, json.JSONDecodeError, ReviewError) as exc:
            raise CreativeFeedbackError(f"closed review data is invalid: {exc}") from exc

        if (
            batch.batch_id != batch_ref
            or batch.run_id != self.hub.run_id
            or wait.get("round_id") != review_round.round_id
            or wait.get("round_sha256") != review_round.round_sha256
            or wait.get("batch_sha256") != batch.batch_sha256
        ):
            raise CreativeFeedbackError("closed review binding is stale")
        resolution = snapshot.resolution
        if resolution is None or snapshot.round.status != "closed":
            raise CreativeFeedbackError("closed wait has no immutable resolution")
        if (
            wait.get("resolution_id") != resolution.resolution_id
            or wait.get("resolution_sha256") != resolution.resolution_sha256
            or wait.get("latest_receipt_set_sha256")
            != resolution.latest_receipt_set_sha256
            or wait.get("approved_feedback_set_sha256")
            != resolution.approved_feedback_set_sha256
        ):
            raise CreativeFeedbackError("closed wait does not match its resolution")

        for binding in review_round.concepts:
            record = _artifact_record(self.workflow, binding.concept_ref)
            if (
                record.get("artifact_type") != "creative_concept"
                or record.get("sha256") != binding.concept_sha256
            ):
                raise CreativeFeedbackError(
                    f"shortlisted Concept changed: {binding.concept_ref}"
                )
        fragments = {
            fragment.feedback_ref: fragment
            for fragment in store.feedback_fragments()
        }
        return _ResolutionContext(
            resolution=resolution,
            review_round=review_round,
            fragments=fragments,
        )

    def _resolution_operations(
        self,
        resolution: HumanResolution,
    ) -> tuple[_FeedbackOperation, ...]:
        action_by_ref = {
            action.concept_ref: action for action in resolution.actions
        }
        operations: list[_FeedbackOperation] = []
        merged_sources: set[str] = set()
        for group in resolution.merge_groups:
            sources = tuple(
                self.workflow._concept_from_artifact(reference)
                for reference in group.source_refs
            )
            actions = tuple(action_by_ref[reference] for reference in group.source_refs)
            operations.append(
                _FeedbackOperation(
                    operation_key=f"merge:{group.merge_group_id}",
                    action="merge",
                    sources=sources,
                    resolution_actions=actions,
                    merge_group_id=group.merge_group_id,
                )
            )
            merged_sources.update(group.source_refs)
        for action in resolution.actions:
            if action.concept_ref in merged_sources:
                continue
            source = self.workflow._concept_from_artifact(action.concept_ref)
            operations.append(
                _FeedbackOperation(
                    operation_key=f"{action.action}:{action.concept_ref}",
                    action=action.action,
                    sources=(source,),
                    resolution_actions=(action,),
                    merge_group_id=None,
                )
            )
        return tuple(
            sorted(
                operations,
                key=lambda operation: (
                    operation.source_refs,
                    operation.action,
                    operation.operation_key,
                ),
            )
        )

    def _require_pristine_c6c(
        self,
        operations: Sequence[_FeedbackOperation],
    ) -> None:
        state = self.hub.load_state()
        artifacts = state.get("artifacts")
        tasks = state.get("tasks")
        if not isinstance(artifacts, dict) or not isinstance(tasks, dict):
            raise CreativeFeedbackError("run task/artifact registries are invalid")
        if any(
            isinstance(record, dict)
            and record.get("artifact_type")
            in {
                "creative_final_idea",
                "creative_human_feedback_binding",
            }
            for record in artifacts.values()
        ):
            raise CreativeFeedbackError(
                "closed C6 round already contains feedback finalization artifacts"
            )
        if any(
            isinstance(record, dict)
            and record.get("stage") == C6C_FEEDBACK_REVISE
            for record in tasks.values()
        ):
            raise CreativeFeedbackError(
                "closed C6 round already consumed its feedback task budget"
            )

        shortlist_refs = {
            source.artifact_ref
            for operation in operations
            for source in operation.sources
        }
        terminal_counts = {reference: 0 for reference in shortlist_refs}
        shortlist_counts = {reference: 0 for reference in shortlist_refs}
        for artifact_id, record in artifacts.items():
            if (
                not isinstance(record, dict)
                or record.get("artifact_type")
                != "creative_concept_disposition"
            ):
                continue
            try:
                payload = json.loads(self.hub.read_artifact(str(artifact_id)))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise CreativeFeedbackError(
                    f"invalid Concept disposition {artifact_id}: {exc}"
                ) from exc
            if not isinstance(payload, dict):
                raise CreativeFeedbackError(
                    f"Concept disposition {artifact_id} must be an object"
                )
            reference = payload.get("concept_revision_ref")
            if reference not in shortlist_refs:
                continue
            if payload.get("terminal") is True:
                terminal_counts[str(reference)] += 1
            if (
                payload.get("stage") == "C6B"
                and payload.get("outcome") == "shortlisted"
                and payload.get("terminal") is False
            ):
                shortlist_counts[str(reference)] += 1
        if any(terminal_counts.values()):
            raise CreativeFeedbackError(
                "a shortlisted Concept already has a terminal disposition"
            )
        if any(count != 1 for count in shortlist_counts.values()):
            raise CreativeFeedbackError(
                "each resolved Concept requires exactly one shortlist disposition"
            )

    def _approved_guidance(
        self,
        operation: _FeedbackOperation,
        fragments: Mapping[str, FeedbackFragment],
    ) -> _ApprovedGuidance:
        approved: dict[str, FeedbackFragment] = {}
        instructions: list[tuple[str, str, str]] = []
        source_refs = set(operation.source_refs)
        for action in operation.resolution_actions:
            if (
                action.curator_instruction_sha256 is not None
                and sha256_text(action.curator_instruction)
                != action.curator_instruction_sha256
            ):
                raise CreativeFeedbackError("curator instruction hash changed")
            if action.curator_instruction_sha256 is not None:
                instructions.append(
                    (
                        action.concept_ref,
                        action.curator_instruction,
                        action.curator_instruction_sha256,
                    )
                )
            for binding in action.approved_feedback:
                fragment = fragments.get(binding.feedback_ref)
                if fragment is None:
                    raise CreativeFeedbackError(
                        f"approved feedback is no longer present: {binding.feedback_ref}"
                    )
                if (
                    fragment.feedback_sha256 != binding.feedback_sha256
                    or sha256_json(dict(fragment.payload))
                    != fragment.feedback_sha256
                ):
                    raise CreativeFeedbackError(
                        f"approved feedback hash changed: {binding.feedback_ref}"
                    )
                if not source_refs.intersection(fragment.related_concept_refs):
                    raise CreativeFeedbackError(
                        f"approved feedback is unrelated: {binding.feedback_ref}"
                    )
                approved[fragment.feedback_ref] = fragment
        ordered = tuple(approved[key] for key in sorted(approved))
        if len(ordered) > MAX_APPROVED_FRAGMENTS_PER_ACTION:
            raise CreativeFeedbackError(
                "one C6C task cannot inject more than 12 feedback fragments"
            )
        byte_count = sum(
            len(canonical_json_bytes(dict(fragment.payload)))
            for fragment in ordered
        ) + sum(
            len(instruction.encode("utf-8"))
            for _, instruction, _ in instructions
        )
        if byte_count > MAX_APPROVED_FEEDBACK_BYTES:
            raise CreativeFeedbackError(
                "one C6C task exceeds the 24 KiB feedback context budget"
            )
        if (
            operation.action in {"revise", "merge"}
            and not ordered
            and not instructions
        ):
            raise CreativeFeedbackError(
                f"{operation.action} requires explicitly approved guidance"
            )
        return _ApprovedGuidance(
            fragments=ordered,
            instructions=tuple(sorted(instructions)),
        )

    def _require_feedback_budgets(
        self,
        operations: Sequence[_FeedbackOperation],
    ) -> None:
        for operation in operations:
            if operation.action not in {"revise", "merge"}:
                continue
            for source in operation.sources:
                self.workflow._revision_budget(source.concept_id).consume(
                    RevisionReason.HUMAN_FEEDBACK,
                    settings=self.workflow.settings,
                )

    async def _prepare_final_idea(
        self,
        operation: _FeedbackOperation,
        guidance: _ApprovedGuidance,
        *,
        idea_ref: str,
        resolution: HumanResolution,
    ) -> _PreparedFinalIdea:
        task_id: str | None = None
        if operation.action == "keep":
            markdown = self.hub.read_artifact(operation.sources[0].artifact_ref)
            primary_territory_ref = operation.sources[0].primary_territory_ref
        else:
            task_id = _feedback_task_id(operation)
            evidence_refs = _operation_evidence_refs(self.workflow, operation)
            output = await self.workflow._execute(
                stage=C6C_FEEDBACK_REVISE,
                task_id=task_id,
                blocks=(
                    (
                        "CHALLENGE_BRIEF",
                        self.hub.read_artifact(
                            _single_artifact_ref(
                                self.workflow,
                                "creative_challenge_brief",
                            )
                        ),
                    ),
                    (
                        "CONSTRAINT_VIEW",
                        self.hub.read_artifact(
                            _single_artifact_ref(
                                self.workflow,
                                "creative_constraint_view",
                            )
                        ),
                    ),
                    (
                        "CREATIVE_BRIEF",
                        self.hub.read_artifact(
                            _single_artifact_ref(
                                self.workflow,
                                "creative_brief",
                            )
                        ),
                    ),
                    ("SOURCE_CONCEPTS", _source_context(self.workflow, operation)),
                    ("NECESSARY_EVIDENCE", _evidence_context(self.workflow, evidence_refs)),
                    ("APPROVED_FEEDBACK", _feedback_context(guidance.fragments)),
                    (
                        "CURATOR_INSTRUCTIONS",
                        _instruction_context(guidance.instructions),
                    ),
                    (
                        "RESOLUTION_BINDING",
                        _json_text(
                            {
                                "resolution_id": resolution.resolution_id,
                                "resolution_sha256": resolution.resolution_sha256,
                                "action": operation.action,
                                "merge_group_id": operation.merge_group_id,
                                "source_refs": list(operation.source_refs),
                            }
                        ),
                    ),
                ),
                parent_refs=(
                    *operation.source_refs,
                    *evidence_refs,
                    resolution.resolution_id,
                ),
            )
            allowed_primary = {
                source.primary_territory_ref for source in operation.sources
            }
            validation_context: CreativeValidationContext = {
                "allowed_primary_territory_refs": allowed_primary,
            }
            if operation.action == "revise":
                validation_context["expected_primary_territory_ref"] = (
                    operation.sources[0].primary_territory_ref
                )
            output = self.workflow._validate_completed_output(
                task_id=task_id,
                stage=C6C_FEEDBACK_REVISE,
                output=output,
                context=validation_context,
            )
            markdown = _required_output_text(output, "markdown")
            primary_territory_ref = _required_output_text(
                output,
                "primary_territory_ref",
            )

        return _PreparedFinalIdea(
            operation=operation,
            idea_ref=idea_ref,
            markdown=markdown,
            primary_territory_ref=primary_territory_ref,
            task_id=task_id,
        )

    def _publish_prepared_final(
        self,
        prepared: _PreparedFinalIdea,
        guidance: _ApprovedGuidance,
        *,
        resolution: HumanResolution,
    ) -> None:
        operation = prepared.operation
        source_records = [
            _artifact_record(self.workflow, source.artifact_ref)
            for source in operation.sources
        ]
        source_refs = operation.source_refs
        self.hub.publish_artifact(
            artifact_id=prepared.idea_ref,
            artifact_type="creative_final_idea",
            relative_path=(
                "artifacts/creative/ideas/"
                f"{prepared.idea_ref}.md"
            ),
            content=prepared.markdown,
            task_id=prepared.task_id,
            source_refs=source_refs,
            metadata={
                "idea_id": prepared.idea_ref,
                "action": operation.action,
                "source_concept_refs": list(source_refs),
                "source_concept_sha256s": [
                    str(record["sha256"]) for record in source_records
                ],
                "source_primary_territory_refs": [
                    source.primary_territory_ref
                    for source in operation.sources
                ],
                "primary_territory_ref": prepared.primary_territory_ref,
                "parent_atom_refs": sorted(
                    {
                        reference
                        for source in operation.sources
                        for reference in source.parent_atom_refs
                    }
                ),
                "resolution_id": resolution.resolution_id,
                "resolution_sha256": resolution.resolution_sha256,
                "approved_feedback": list(guidance.fragment_bindings),
                "curator_instruction_sha256s": [
                    digest for _, _, digest in guidance.instructions
                ],
                "revision_reason": (
                    "human_feedback"
                    if operation.action in {"revise", "merge"}
                    else None
                ),
                "merge_group_id": operation.merge_group_id,
            },
        )

    def _publish_feedback_binding(
        self,
        operation: _FeedbackOperation,
        guidance: _ApprovedGuidance,
        *,
        resolution: HumanResolution,
        target_ref: str | None,
    ) -> str:
        suffix = target_ref or operation.source_refs[0]
        binding_ref = f"creative-feedback-binding-{suffix}"
        payload = {
            "binding_id": binding_ref,
            "resolution_id": resolution.resolution_id,
            "resolution_sha256": resolution.resolution_sha256,
            "latest_receipt_set_sha256": resolution.latest_receipt_set_sha256,
            "approved_feedback_set_sha256": (
                resolution.approved_feedback_set_sha256
            ),
            "action": operation.action,
            "source_refs": list(operation.source_refs),
            "target_ref": target_ref,
            "merge_group_id": operation.merge_group_id,
            "approved_feedback": list(guidance.fragment_bindings),
            "curator_instructions": [
                {
                    "concept_ref": concept_ref,
                    "sha256": digest,
                }
                for concept_ref, _, digest in guidance.instructions
            ],
        }
        return self.hub.publish_artifact(
            artifact_id=binding_ref,
            artifact_type="creative_human_feedback_binding",
            relative_path=(
                "artifacts/creative/curation/"
                f"{binding_ref}.json"
            ),
            content=_json_text(payload),
            task_id=None,
            source_refs=(
                *operation.source_refs,
                *((target_ref,) if target_ref is not None else ()),
            ),
            metadata={
                "resolution_id": resolution.resolution_id,
                "action": operation.action,
                "source_refs": list(operation.source_refs),
                "target_ref": target_ref,
            },
        )

    def _record_resolution_decision(
        self,
        operation: _FeedbackOperation,
        *,
        resolution: HumanResolution,
        binding_ref: str,
        target_ref: str | None,
        task_id: str | None,
    ) -> str:
        stable_suffix = target_ref or operation.source_refs[0]
        decision_ref = f"creative-decision-c6c-{stable_suffix}"
        outcome, reason_code = _terminal_outcome(operation.action)
        self.hub.append_decision(
            {
                "decision_id": decision_ref,
                "route_id": "creative",
                "stage": "creative-human-curation",
                "decision_type": "human_resolution",
                "outcome": outcome,
                "reason_codes": [reason_code],
                "subject_refs": list(operation.source_refs),
                "evidence_refs": [binding_ref],
                "task_ids": [task_id] if task_id is not None else [],
                "metadata": {
                    "target_ref": target_ref,
                    "resolution_id": resolution.resolution_id,
                    "resolution_sha256": resolution.resolution_sha256,
                    "feedback_binding_ref": binding_ref,
                },
            }
        )
        return decision_ref

    def _publish_terminal_dispositions(
        self,
        operation: _FeedbackOperation,
        *,
        decision_ref: str,
        binding_ref: str,
        target_ref: str | None,
        task_id: str | None,
    ) -> None:
        outcome, reason_code = _terminal_outcome(operation.action)
        suffix = {
            "keep": "human-kept",
            "revise": "human-revised",
            "reject": "human-rejected",
            "taste_veto": "human-taste-vetoed",
            "merge": "human-merged",
        }[operation.action]
        for source in operation.sources:
            self.workflow._publish_disposition(
                source,
                stage="C6C",
                outcome=outcome,
                terminal=True,
                target_ref=target_ref,
                reason_codes=(reason_code,),
                decision_ref=decision_ref,
                evidence_refs=(binding_ref,),
                task_ids=((task_id,) if task_id is not None else ()),
                suffix=suffix,
            )


def _feedback_task_id(operation: _FeedbackOperation) -> str:
    if operation.action == "merge":
        if operation.merge_group_id is None:
            raise CreativeFeedbackError("merge operation has no group ID")
        return f"creative-c6c-merge-{operation.merge_group_id}"
    source = operation.sources[0]
    return (
        f"creative-c6c-revise-{source.concept_id}-"
        f"r{source.revision:03d}"
    )


def _terminal_outcome(action: str) -> tuple[str, str]:
    mapping = {
        "keep": ("promoted_to_final", "human_keep"),
        "revise": ("revised_into", "human_revise"),
        "reject": ("human_reject", "human_reject"),
        "taste_veto": ("human_taste_veto", "human_taste_veto"),
        "merge": ("merged_into", "human_merge"),
    }
    try:
        return mapping[action]
    except KeyError as exc:
        raise CreativeFeedbackError(
            f"unsupported resolution action: {action}"
        ) from exc


def _artifact_record(
    workflow: CreativeIdeaWorkflow,
    artifact_ref: str,
) -> dict[str, Any]:
    artifacts = workflow.hub.load_state().get("artifacts")
    if not isinstance(artifacts, dict):
        raise CreativeFeedbackError("run artifacts must be an object")
    record = artifacts.get(artifact_ref)
    if not isinstance(record, dict):
        raise CreativeFeedbackError(
            f"artifact is not registered: {artifact_ref}"
        )
    return record


def _single_artifact_ref(
    workflow: CreativeIdeaWorkflow,
    artifact_type: str,
) -> str:
    artifacts = workflow.hub.load_state().get("artifacts")
    if not isinstance(artifacts, dict):
        raise CreativeFeedbackError("run artifacts must be an object")
    matches = [
        str(reference)
        for reference, record in artifacts.items()
        if isinstance(record, dict)
        and record.get("artifact_type") == artifact_type
    ]
    if len(matches) != 1:
        raise CreativeFeedbackError(
            f"C6C requires exactly one {artifact_type} artifact"
        )
    return matches[0]


def _operation_evidence_refs(
    workflow: CreativeIdeaWorkflow,
    operation: _FeedbackOperation,
) -> tuple[str, ...]:
    references: set[str] = set()
    for source in operation.sources:
        metadata = _artifact_record(workflow, source.artifact_ref).get(
            "metadata"
        )
        if not isinstance(metadata, dict):
            raise CreativeFeedbackError(
                f"Concept has no metadata: {source.artifact_ref}"
            )
        for key in ("hook_disposition_ref", "novelty_scan_ref"):
            reference = metadata.get(key)
            if not isinstance(reference, str):
                raise CreativeFeedbackError(
                    f"Concept is missing {key}: {source.artifact_ref}"
                )
            _artifact_record(workflow, reference)
            references.add(reference)
    return tuple(sorted(references))


def _source_context(
    workflow: CreativeIdeaWorkflow,
    operation: _FeedbackOperation,
) -> str:
    rows = []
    for source in operation.sources:
        record = _artifact_record(workflow, source.artifact_ref)
        rows.append(
            {
                "concept_ref": source.artifact_ref,
                "concept_sha256": record["sha256"],
                "primary_territory_ref": source.primary_territory_ref,
                "markdown": workflow.hub.read_artifact(source.artifact_ref),
            }
        )
    return _json_text({"sources": rows})


def _evidence_context(
    workflow: CreativeIdeaWorkflow,
    references: Sequence[str],
) -> str:
    return _json_text(
        {
            "evidence": [
                {
                    "artifact_ref": reference,
                    "artifact_sha256": _artifact_record(
                        workflow,
                        reference,
                    )["sha256"],
                    "content": workflow.hub.read_artifact(reference),
                }
                for reference in references
            ]
        }
    )


def _feedback_context(
    fragments: Sequence[FeedbackFragment],
) -> str:
    return _json_text(
        {
            "approved_feedback": [
                {
                    "feedback_ref": fragment.feedback_ref,
                    "feedback_sha256": fragment.feedback_sha256,
                    "kind": fragment.kind,
                    "related_concept_refs": list(
                        fragment.related_concept_refs
                    ),
                    "payload": dict(fragment.payload),
                }
                for fragment in fragments
            ]
        }
    )


def _instruction_context(
    instructions: Sequence[tuple[str, str, str]],
) -> str:
    return _json_text(
        {
            "curator_instructions": [
                {
                    "concept_ref": concept_ref,
                    "instruction": instruction,
                    "sha256": digest,
                }
                for concept_ref, instruction, digest in instructions
            ]
        }
    )


def _required_output_text(output: Mapping[str, Any], key: str) -> str:
    value = output.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CreativeFeedbackError(
            f"C6C output requires non-empty {key}"
        )
    return value


def _json_text(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


__all__ = [
    "CreativeFeedbackError",
    "CreativeFeedbackFinalizer",
    "CreativeFeedbackOutcome",
    "INTERNAL_C6_FEEDBACK_COMPLETE_STAGE",
]
