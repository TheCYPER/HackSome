from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping, Sequence
from unittest.mock import patch

from hacksome.creative.artifacts import (
    CHALLENGE_BRIEF_HEADINGS,
    CONCEPT_HEADINGS,
    CREATIVE_BRIEF_HEADINGS,
    NOVELTY_SCAN_HEADINGS,
)
from hacksome.creative.contracts import CreativeWorkflowSettings
from hacksome.creative.report import CreativeReportError
from hacksome.creative.report_projection import build_report_projection
from hacksome.creative.review import (
    ConceptBinding,
    ReviewBatch,
    ReviewRound,
    ReviewStore,
)
from hacksome.creative.workflow import CreativeIdeaWorkflow


def _markdown(
    title: str,
    headings: Sequence[str],
    *,
    bodies: Mapping[str, str] | None = None,
) -> str:
    replacements = bodies or {}
    sections = "\n\n".join(
        f"## {heading}\n\n"
        f"{replacements.get(heading, f'Exact {heading} evidence.')}"
        for heading in headings
    )
    return f"# {title}\n\n{sections}\n"


def _concept_markdown(title: str, atom_ref: str) -> str:
    return _markdown(
        title,
        CONCEPT_HEADINGS,
        bodies={
            "Intended Reaction": "Surprise followed by recognition.",
            "One-sentence Hook": f"{title} turns one gesture into a shared reveal.",
            "First Impression": "A familiar object waits for one gesture.",
            "Audience Action": "A participant turns the object toward a friend.",
            "Setup, Reveal and Aftertaste": (
                "The room first sees a private action, then discovers a shared "
                "state and remembers the reversal."
            ),
            "Real Input, Transformation and Output": (
                "A real gesture changes a local state and reveals a visible scene."
            ),
            "Why It Is Unexpected Yet Legible": (
                "The ordinary gesture unexpectedly links everyone through one rule."
            ),
            "Minimum Hackathon Demo": "Two browsers demonstrate the complete loop.",
            "Assumptions, Confusion and Risks": (
                "The reveal must remain understandable without narration."
            ),
            "Parent Atoms": f"- `{atom_ref}`",
        },
    )


def _json_text(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


class _Fixture:
    def __init__(self, root: Path, *, run_id: str) -> None:
        self.workflow = CreativeIdeaWorkflow.create(
            "Make a surprising shared interaction.",
            root,
            settings=CreativeWorkflowSettings(idea_memory_mode="off"),
            run_id=run_id,
        )
        self.hub = self.workflow.hub
        self.hub.set_run_status("running", stage="fixture-seed")
        self._publish_base()
        self.concepts: dict[int, dict[int, str]] = {}
        self.atom_refs: dict[int, str] = {}

    def _publish_base(self) -> None:
        challenge = _markdown("Challenge", CHALLENGE_BRIEF_HEADINGS)
        brief = _markdown("Creative Brief", CREATIVE_BRIEF_HEADINGS)
        self.hub.publish_artifact(
            artifact_id="creative-challenge-brief-r001",
            artifact_type="creative_challenge_brief",
            relative_path=(
                "artifacts/creative/challenge/"
                "creative-challenge-brief-r001.md"
            ),
            content=challenge,
            task_id=None,
        )
        self.hub.publish_artifact(
            artifact_id="creative-brief-r001",
            artifact_type="creative_brief",
            relative_path="artifacts/creative/brief/creative-brief-r001.md",
            content=brief,
            task_id=None,
            source_refs=("creative-challenge-brief-r001",),
        )
        territory = "# Shared Reversal\n\nA distinct interaction territory.\n"
        self.hub.publish_artifact(
            artifact_id="creative-territory-01",
            artifact_type="creative_territory",
            relative_path=(
                "artifacts/creative/territories/creative-territory-01.md"
            ),
            content=territory,
            task_id=None,
            source_refs=(
                "creative-challenge-brief-r001",
                "creative-brief-r001",
            ),
        )
        summary = {
            "status": "disabled",
            "recall": {
                "status": "not_started",
                "task_ref": None,
                "diagnostic_ref": None,
            },
            "selected_cue_ids": [],
            "remix_slots": [
                {
                    "slot": slot,
                    "status": "not_started",
                    "task_ref": None,
                    "challenger_ref": None,
                    "diagnostic_ref": None,
                }
                for slot in (1, 2)
            ],
        }
        self.hub.publish_artifact(
            artifact_id="creative-memory-stage-summary-r001",
            artifact_type="creative_memory_stage_summary",
            relative_path=(
                "artifacts/creative/memory/"
                "creative-memory-stage-summary-r001.json"
            ),
            content=_json_text(summary),
            task_id=None,
        )

    def concept(
        self,
        index: int,
        *,
        revision: int,
        supersedes_ref: str | None = None,
        revision_reason: str | None = None,
        novelty_ref: str | None = None,
    ) -> str:
        atom_ref = self.atom_refs.get(index)
        if atom_ref is None:
            atom_ref = f"creative-atom-t01-{index:02d}"
            self.hub.publish_artifact(
                artifact_id=atom_ref,
                artifact_type="creative_atom",
                relative_path=f"artifacts/creative/atoms/{atom_ref}.md",
                content=f"# Atom {index}\n\nA real shared trigger.\n",
                task_id=None,
                source_refs=("creative-territory-01",),
                metadata={"territory_ref": "creative-territory-01"},
            )
            self.atom_refs[index] = atom_ref
        concept_id = f"creative-concept-s01-{index:02d}"
        reference = f"{concept_id}-r{revision:03d}"
        markdown = _concept_markdown(
            f"Concept {index} Revision {revision}",
            atom_ref,
        )
        metadata: dict[str, Any] = {
            "concept_id": concept_id,
            "origin": "base",
            "revision": revision,
            "revision_reason": (
                "initial_synthesis" if revision == 1 else revision_reason
            ),
            "primary_territory_ref": "creative-territory-01",
            "parent_atom_refs": [atom_ref],
        }
        if supersedes_ref is not None:
            metadata["supersedes_ref"] = supersedes_ref
        if novelty_ref is not None:
            metadata["novelty_scan_ref"] = novelty_ref
        self.hub.publish_artifact(
            artifact_id=reference,
            artifact_type="creative_concept",
            relative_path=f"artifacts/creative/concepts/{reference}.md",
            content=markdown,
            task_id=None,
            source_refs=tuple(
                reference
                for reference in (supersedes_ref, atom_ref, novelty_ref)
                if reference is not None
            ),
            metadata=metadata,
        )
        self.concepts.setdefault(index, {})[revision] = reference
        return reference

    def novelty(self, index: int, source_ref: str) -> str:
        reference = f"creative-novelty-{source_ref}"
        markdown = _markdown(
            f"Novelty {index}",
            NOVELTY_SCAN_HEADINGS,
        )
        self.hub.publish_artifact(
            artifact_id=reference,
            artifact_type="creative_novelty_scan",
            relative_path=(
                f"artifacts/creative/novelty-scans/{reference}.md"
            ),
            content=markdown,
            task_id=None,
            source_refs=(source_ref,),
            metadata={"concept_revision_ref": source_ref, "sources": []},
        )
        return reference

    def disposition(
        self,
        concept_ref: str,
        *,
        suffix: str,
        stage: str,
        outcome: str,
        terminal: bool,
        reason_codes: Sequence[str],
        target_ref: str | None = None,
        concept_sha256: str | None = None,
        decision_id: str | None = None,
        decision_subjects: Sequence[str] | None = None,
    ) -> str:
        state = self.hub.load_state()
        artifact = state["artifacts"][concept_ref]
        decision_ref = decision_id or f"creative-decision-{suffix}"
        if decision_ref not in {
            row["decision_id"]
            for row in self.hub.load_consistent_snapshot()["ledgers"]["decisions"]
        }:
            self.hub.append_decision(
                {
                    "decision_id": decision_ref,
                    "route_id": "creative",
                    "stage": f"creative-{stage.lower()}",
                    "decision_type": "candidate_gate",
                    "outcome": outcome,
                    "reason_codes": list(reason_codes),
                    "subject_refs": list(decision_subjects or (concept_ref,)),
                    "evidence_refs": [],
                    "task_ids": [],
                }
            )
        disposition_id = f"creative-disposition-{suffix}"
        payload = {
            "disposition_id": disposition_id,
            "concept_revision_ref": concept_ref,
            "concept_sha256": concept_sha256 or artifact["sha256"],
            "stage": stage,
            "outcome": outcome,
            "terminal": terminal,
            "target_ref": target_ref,
            "reason_codes": list(reason_codes),
            "decision_ref": decision_ref,
            "evidence_refs": [],
            "task_refs": [],
        }
        self.hub.publish_artifact(
            artifact_id=disposition_id,
            artifact_type="creative_concept_disposition",
            relative_path=(
                "artifacts/creative/dispositions/"
                f"{disposition_id}.json"
            ),
            content=_json_text(payload),
            task_id=None,
            source_refs=tuple(
                reference
                for reference in (concept_ref, target_ref)
                if reference is not None
            ),
            metadata={
                "concept_revision_ref": concept_ref,
                "outcome": outcome,
                "terminal": terminal,
                "target_ref": target_ref,
            },
        )
        return disposition_id

    def evidence_lineage(
        self,
        index: int,
        *,
        shortlist: bool,
    ) -> str:
        first = self.concept(index, revision=1)
        novelty = self.novelty(index, first)
        second = self.concept(
            index,
            revision=2,
            supersedes_ref=first,
            revision_reason="evidence_informed",
            novelty_ref=novelty,
        )
        self.disposition(
            first,
            suffix=f"c{index}-r1-pass",
            stage="C4",
            outcome="pass",
            terminal=False,
            reason_codes=("c4_hook_passed",),
        )
        self.disposition(
            first,
            suffix=f"c{index}-r1-evidence",
            stage="C6A",
            outcome="superseded_by_evidence_revision",
            terminal=True,
            reason_codes=("c6_evidence_revision_published",),
            target_ref=second,
        )
        if shortlist:
            self.disposition(
                second,
                suffix=f"c{index}-r2-shortlist",
                stage="C6B",
                outcome="shortlisted",
                terminal=False,
                reason_codes=("c6_shortlisted",),
            )
        else:
            self.disposition(
                second,
                suffix=f"c{index}-r2-not-shortlist",
                stage="C6B",
                outcome="not_shortlisted",
                terminal=True,
                reason_codes=("insufficient_include_support",),
            )
        return second

    def skipped_batch(self, reason: str) -> None:
        batch = ReviewBatch.build(
            run_id=self.hub.run_id,
            concepts=(),
            skip_reason=reason,
        )
        self._publish_batch(batch)
        self.hub.set_wait(None)
        self.hub.set_run_status(
            "running",
            stage="creative-c6-empty-complete-internal",
        )

    def open_review(
        self,
        concept_refs: Sequence[str],
        *,
        recommendations: Mapping[str, str],
        actions: Mapping[str, str],
        merge_sources: Sequence[str] = (),
    ) -> tuple[ReviewRound, Any]:
        state = self.hub.load_state()
        batch = ReviewBatch.build(
            run_id=self.hub.run_id,
            concepts=tuple(
                ConceptBinding(
                    concept_ref=reference,
                    concept_sha256=state["artifacts"][reference]["sha256"],
                )
                for reference in concept_refs
            ),
        )
        batch_ref = self._publish_batch(batch)
        batch_record = self.hub.load_state()["artifacts"][batch_ref]
        review_round = ReviewRound.open(batch)
        self.hub.set_wait(
            {
                "kind": "creative_human_review",
                "round_id": review_round.round_id,
                "round_artifact_id": batch_ref,
                "round_sha256": review_round.round_sha256,
                "batch_sha256": batch.batch_sha256,
                "batch_artifact_sha256": batch_record["sha256"],
                "status": "open",
                "opened_at": batch_record["created_at"],
                "closed_at": None,
                "resolution_id": None,
                "resolution_sha256": None,
                "latest_receipt_set_sha256": None,
                "approved_feedback": [],
            }
        )
        self.hub.set_run_status(
            "waiting",
            stage="creative-human-review",
        )
        store = ReviewStore(
            self.hub,
            review_round,
            clock=iter(
                (
                    "2026-07-23T01:00:00+00:00",
                    "2026-07-23T01:01:00+00:00",
                )
            ).__next__,
        )
        store.initialize()
        review = store.submit_review(
            {
                "schema_version": 2,
                "review_id": "review-001",
                "round_id": review_round.round_id,
                "round_sha256": review_round.round_sha256,
                "run_id": review_round.run_id,
                "reviewer_id": "reviewer-001",
                "reviewer_name": "Teammate",
                "concept_reviews": [
                    {
                        "concept_ref": binding.concept_ref,
                        "concept_sha256": binding.concept_sha256,
                        "one_sentence_retell": (
                            f"{binding.concept_ref} turns one gesture "
                            "into a shared reveal."
                        ),
                        "share_impulse": "maybe",
                        "share_target": "a friend who builds installations",
                        "demo_confidence": "yes",
                        "reactions": {
                            "surprise": "yes",
                            "fun": "yes",
                            "mystery": "maybe",
                            "confusion": "no",
                        },
                        "recommendation": recommendations[binding.concept_ref],
                        "comment": "The reveal is clear.",
                    }
                    for binding in review_round.concepts
                ],
                "pairwise": [],
                "overall_comment": "Keep the reveal legible.",
                "supersedes_review_id": None,
            }
        )
        fragments = {
            item.concept_ref: {
                "feedback_ref": item.feedback_ref,
                "feedback_sha256": item.feedback_sha256,
            }
            for item in review.concept_reviews
        }
        merge_set = set(merge_sources)
        resolution_actions = []
        for binding in review_round.concepts:
            action = actions[binding.concept_ref]
            resolution_actions.append(
                {
                    "concept_ref": binding.concept_ref,
                    "action": action,
                    "approved_feedback": (
                        [fragments[binding.concept_ref]]
                        if action in {"revise", "merge"}
                        else []
                    ),
                    "curator_instruction": "",
                    "reason": (
                        "A subjective veto."
                        if action == "taste_veto"
                        else ""
                    ),
                    "merge_group_id": (
                        "merge-001"
                        if binding.concept_ref in merge_set
                        else None
                    ),
                }
            )
        resolution = store.submit_resolution(
            {
                "resolution_id": "resolution-001",
                "run_id": review_round.run_id,
                "curator_name": "Percy",
                "round_id": review_round.round_id,
                "round_sha256": review_round.round_sha256,
                "actions": resolution_actions,
                "merge_groups": (
                    [
                        {
                            "merge_group_id": "merge-001",
                            "source_refs": list(merge_sources),
                            "reason": "The two mechanisms form one coherent reveal.",
                        }
                    ]
                    if merge_sources
                    else []
                ),
                "coverage_override_reason": None,
            }
        )
        return review_round, resolution

    def final_idea(
        self,
        idea_index: int,
        *,
        action: str,
        source_refs: Sequence[str],
        resolution: Any,
    ) -> str:
        reference = f"creative-idea-{idea_index:03d}"
        state = self.hub.load_state()
        action_by_ref = {
            item.concept_ref: item for item in resolution.actions
        }
        approved = sorted(
            (
                binding.to_dict()
                for source_ref in source_refs
                for binding in action_by_ref[source_ref].approved_feedback
            ),
            key=lambda item: item["feedback_ref"],
        )
        self.hub.publish_artifact(
            artifact_id=reference,
            artifact_type="creative_final_idea",
            relative_path=f"artifacts/creative/ideas/{reference}.md",
            content=_concept_markdown(
                f"Final Idea {idea_index}",
                self.atom_refs[
                    int(source_refs[0].split("-")[3][1:])
                    if source_refs[0].startswith("creative-concept-m")
                    else int(source_refs[0].split("-")[3])
                ],
            ),
            task_id=None,
            source_refs=tuple(source_refs),
            metadata={
                "idea_id": reference,
                "action": action,
                "source_concept_refs": list(source_refs),
                "source_concept_sha256s": [
                    state["artifacts"][source_ref]["sha256"]
                    for source_ref in source_refs
                ],
                "source_primary_territory_refs": [
                    "creative-territory-01" for _ in source_refs
                ],
                "primary_territory_ref": "creative-territory-01",
                "parent_atom_refs": [
                    self.atom_refs[int(source_ref.split("-")[3])]
                    for source_ref in source_refs
                ],
                "resolution_id": resolution.resolution_id,
                "resolution_sha256": resolution.resolution_sha256,
                "approved_feedback": approved,
                "curator_instruction_sha256s": [],
                "revision_reason": (
                    "human_feedback" if action in {"revise", "merge"} else None
                ),
                "merge_group_id": "merge-001" if action == "merge" else None,
            },
        )
        outcome = {
            "keep": "promoted_to_final",
            "revise": "revised_into",
            "merge": "merged_into",
        }[action]
        reason = {
            "keep": "human_keep",
            "revise": "human_revise",
            "merge": "human_merge",
        }[action]
        decision_id = f"creative-decision-final-{idea_index:03d}"
        for source_ref in source_refs:
            self.disposition(
                source_ref,
                suffix=(
                    f"final-{idea_index:03d}-"
                    f"{source_ref.removeprefix('creative-concept-')}"
                ),
                stage="C6C",
                outcome=outcome,
                terminal=True,
                reason_codes=(reason,),
                target_ref=reference,
                decision_id=decision_id,
                decision_subjects=source_refs,
            )
        return reference

    def reject(
        self,
        concept_ref: str,
        *,
        taste_veto: bool = False,
    ) -> None:
        self.disposition(
            concept_ref,
            suffix=f"reject-{concept_ref.removeprefix('creative-concept-')}",
            stage="C6C",
            outcome="human_taste_veto" if taste_veto else "human_reject",
            terminal=True,
            reason_codes=(
                "human_taste_veto" if taste_veto else "human_reject",
            ),
        )

    def feedback_complete(self) -> None:
        self.hub.set_run_status(
            "running",
            stage="creative-c6-feedback-complete-internal",
        )

    def _publish_batch(self, batch: ReviewBatch) -> str:
        return self.hub.publish_artifact(
            artifact_id=batch.batch_id,
            artifact_type="creative_human_review_batch",
            relative_path=(
                "artifacts/creative/curation/"
                f"{batch.batch_id}.json"
            ),
            content=_json_text(batch.to_dict()),
            task_id=None,
            source_refs=batch.concept_refs,
            metadata={
                "status": batch.status,
                "concept_refs": list(batch.concept_refs),
                "batch_sha256": batch.batch_sha256,
                "skip_reason": batch.skip_reason,
            },
        )


class CreativeReportProjectionTests(unittest.TestCase):
    def test_empty_batch_projects_all_three_pre_human_zero_paths(self) -> None:
        cases = (
            "no_concepts_generated",
            "all_candidates_failed_concept_screen",
            "shortlist_empty",
        )
        for reason in cases:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                fixture = _Fixture(Path(directory), run_id=f"run-{reason}")
                if reason == "all_candidates_failed_concept_screen":
                    concept = fixture.concept(1, revision=1)
                    fixture.disposition(
                        concept,
                        suffix="hook-eliminated",
                        stage="C4",
                        outcome="eliminated",
                        terminal=True,
                        reason_codes=("c4_double_invalid",),
                    )
                elif reason == "shortlist_empty":
                    fixture.evidence_lineage(1, shortlist=False)
                fixture.skipped_batch(reason)

                projection = build_report_projection(fixture.hub)

                self.assertEqual(projection.zero_reason_code, reason)
                self.assertEqual(projection.empty_batch_skip_reason, reason)
                self.assertEqual(projection.final_ideas, ())
                self.assertEqual(
                    projection.review_rounds[0].status,
                    "skipped_empty",
                )

    def test_nonzero_projection_keeps_revises_and_merges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _Fixture(Path(directory), run_id="run-nonzero")
            sources = tuple(
                fixture.evidence_lineage(index, shortlist=True)
                for index in range(1, 5)
            )
            actions = {
                sources[0]: "keep",
                sources[1]: "revise",
                sources[2]: "merge",
                sources[3]: "merge",
            }
            _, resolution = fixture.open_review(
                sources,
                recommendations={
                    source: "keep" if index != 1 else "revise"
                    for index, source in enumerate(sources)
                },
                actions=actions,
                merge_sources=sources[2:],
            )
            fixture.final_idea(
                1,
                action="keep",
                source_refs=(sources[0],),
                resolution=resolution,
            )
            fixture.final_idea(
                2,
                action="revise",
                source_refs=(sources[1],),
                resolution=resolution,
            )
            fixture.final_idea(
                3,
                action="merge",
                source_refs=sources[2:],
                resolution=resolution,
            )
            fixture.feedback_complete()

            projection = build_report_projection(fixture.hub)

            self.assertIsNone(projection.zero_reason_code)
            self.assertEqual(
                tuple(idea.idea_id for idea in projection.final_ideas),
                (
                    "creative-idea-001",
                    "creative-idea-002",
                    "creative-idea-003",
                ),
            )
            self.assertEqual(
                tuple(
                    len(idea.source_concept_refs)
                    for idea in projection.final_ideas
                ),
                (1, 1, 2),
            )
            self.assertEqual(
                projection.final_ideas[0]
                .human_signal.approved_feedback_fragment_refs,
                (),
            )
            self.assertTrue(
                projection.final_ideas[1]
                .human_signal.approved_feedback_fragment_refs
            )
            self.assertEqual(
                projection.final_ideas[0].human_signal.receipt_ids,
                ("review-001",),
            )

    def test_all_human_rejected_is_a_closed_zero_idea_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _Fixture(Path(directory), run_id="run-rejected")
            source = fixture.evidence_lineage(1, shortlist=True)
            fixture.open_review(
                (source,),
                recommendations={source: "reject"},
                actions={source: "reject"},
            )
            fixture.reject(source)
            fixture.feedback_complete()

            projection = build_report_projection(fixture.hub)

            self.assertEqual(
                projection.zero_reason_code,
                "all_human_rejected",
            )
            self.assertEqual(projection.final_ideas, ())
            self.assertEqual(
                projection.concepts[0]
                .latest_revision.terminal_disposition.outcome.value,
                "human_reject",
            )

    def test_tamper_missing_terminal_and_invalid_binding_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _Fixture(Path(directory), run_id="run-tamper")
            concept = fixture.concept(1, revision=1)
            fixture.disposition(
                concept,
                suffix="hook-eliminated",
                stage="C4",
                outcome="eliminated",
                terminal=True,
                reason_codes=("c4_double_invalid",),
            )
            fixture.skipped_batch("all_candidates_failed_concept_screen")
            record = fixture.hub.load_state()["artifacts"][concept]
            (fixture.hub.run_dir / record["path"]).write_text(
                "tampered\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CreativeReportError, "hash mismatch"):
                build_report_projection(fixture.hub)

        with tempfile.TemporaryDirectory() as directory:
            fixture = _Fixture(Path(directory), run_id="run-no-terminal")
            concept = fixture.concept(1, revision=1)
            fixture.disposition(
                concept,
                suffix="hook-pass-only",
                stage="C4",
                outcome="pass",
                terminal=False,
                reason_codes=("c4_hook_passed",),
            )
            fixture.skipped_batch("shortlist_empty")
            with self.assertRaisesRegex(
                CreativeReportError,
                "exactly one terminal disposition",
            ):
                build_report_projection(fixture.hub)

        with tempfile.TemporaryDirectory() as directory:
            fixture = _Fixture(Path(directory), run_id="run-stale-binding")
            concept = fixture.concept(1, revision=1)
            fixture.disposition(
                concept,
                suffix="hook-stale",
                stage="C4",
                outcome="eliminated",
                terminal=True,
                reason_codes=("c4_double_invalid",),
                concept_sha256="f" * 64,
            )
            fixture.skipped_batch("all_candidates_failed_concept_screen")
            with self.assertRaisesRegex(
                CreativeReportError,
                "stale Concept binding",
            ):
                build_report_projection(fixture.hub)

    def test_one_consistent_snapshot_and_stable_order_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _Fixture(Path(directory), run_id="run-deterministic")
            fixture.evidence_lineage(2, shortlist=False)
            fixture.evidence_lineage(1, shortlist=False)
            fixture.skipped_batch("shortlist_empty")
            frozen = fixture.hub.load_consistent_snapshot()
            with patch.object(
                fixture.hub,
                "load_consistent_snapshot",
                side_effect=(frozen,),
            ) as load:
                first = build_report_projection(fixture.hub)
            second = build_report_projection(fixture.hub)
            with patch.object(
                fixture.hub,
                "load_consistent_snapshot",
                side_effect=AssertionError("preloaded snapshot must be reused"),
            ) as skipped_load:
                from_preloaded = build_report_projection(
                    fixture.hub,
                    snapshot=frozen,
                )

            self.assertEqual(load.call_count, 1)
            self.assertEqual(skipped_load.call_count, 0)
            self.assertEqual(first, second)
            self.assertEqual(first, from_preloaded)
            self.assertEqual(
                tuple(concept.concept_id for concept in first.concepts),
                (
                    "creative-concept-s01-01",
                    "creative-concept-s01-02",
                ),
            )


if __name__ == "__main__":
    unittest.main()
