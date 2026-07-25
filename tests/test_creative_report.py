from __future__ import annotations

import json
import unittest
from dataclasses import replace

from hacksome.artifacts import validate_markdown
from hacksome.creative.artifacts import (
    CHALLENGE_BRIEF_HEADINGS,
    CONCEPT_HEADINGS,
    CREATIVE_BRIEF_HEADINGS,
    FINAL_IDEA_CARD_HEADINGS,
    LEGACY_CONCEPT_HEADINGS,
    LEGACY_CREATIVE_BRIEF_HEADINGS,
    NOVELTY_SCAN_HEADINGS,
)
from hacksome.creative.contracts import (
    LEGACY_CREATIVE_CONTRACT_VERSION,
    LEGACY_CREATIVE_PROMPT_POLICY_VERSION,
    LEGACY_CREATIVE_REPORT_POLICY_VERSION,
    LEGACY_CREATIVE_STAGE_POLICY_VERSION,
    DispositionOutcome,
    DispositionStage,
)
from hacksome.creative.memory import MemoryCapsuleRef, MemoryRecord
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
    render_success_report,
)
from hacksome.state import sha256_text


def _markdown(
    title: str,
    headings: tuple[str, ...],
    *,
    bodies: dict[str, str] | None = None,
) -> str:
    values = bodies or {}
    sections = "\n\n".join(
        f"## {heading}\n\n{values.get(heading, f'Exact {heading} text.')}"
        for heading in headings
    )
    return f"# {title}\n\n{sections}\n"


def _concept_markdown(
    title: str,
    *,
    hook: str,
    parent_atom_ref: str,
    legacy: bool = False,
) -> str:
    return _markdown(
        title,
        LEGACY_CONCEPT_HEADINGS if legacy else CONCEPT_HEADINGS,
        bodies={
            "Intended Reaction": "Surprise followed by delighted recognition.",
            "One-sentence Hook": hook,
            "First Impression": "A familiar object waits silently for one gesture.",
            "Audience Action": "The audience turns the object toward another person.",
            "Setup, Reveal and Aftertaste": (
                "The object first appears private, then reveals that everyone "
                "changed the same hidden scene, leaving a social aftertaste."
            ),
            "Real Input, Transformation and Output": (
                "A physical turn updates a shared state and reveals one coherent scene."
            ),
            "Why It Is Unexpected Yet Legible": (
                "The same ordinary gesture unexpectedly links the whole room."
            ),
            "Minimum Hackathon Demo": (
                "Two browsers and one physical dial demonstrate the complete loop."
            ),
            "Assumptions, Confusion and Risks": (
                "The shared-state reveal must remain understandable without narration."
            ),
            "Parent Atoms": f"- `{parent_atom_ref}`",
        },
    )


def _novelty() -> NoveltyProjection:
    markdown = _markdown(
        "Novelty Scan",
        NOVELTY_SCAN_HEADINGS,
        bodies={
            "Direct and Near Collisions": "No direct collision was verified.",
            "Distinctive Combination": (
                "The physical gesture and shared delayed reveal form the distinction."
            ),
            "Counterevidence and Uncertainty": (
                "Adjacent installations exist; the exact combination remains uncertain."
            ),
        },
    )
    return NoveltyProjection(
        novelty_ref="creative-novelty-creative-concept-s01-01-r002",
        sha256=sha256_text(markdown),
        markdown=markdown,
    )


def _disposition(
    suffix: str,
    *,
    stage: DispositionStage,
    outcome: DispositionOutcome,
    target_ref: str | None,
    reasons: tuple[str, ...],
    evidence: tuple[ReasonEvidenceProjection, ...] = (),
) -> DispositionProjection:
    return DispositionProjection(
        disposition_ref=f"creative-disposition-{suffix}",
        stage=stage,
        outcome=outcome,
        terminal=True,
        target_ref=target_ref,
        reason_codes=reasons,
        decision_ref=f"creative-decision-{suffix}",
        evidence_refs=tuple(
            item.source_review_ref for item in evidence
        ),
        task_refs=(),
        reason_evidence=evidence,
    )


def _revision(
    reference: str,
    *,
    markdown: str,
    territory: str,
    atom: str,
    disposition: DispositionProjection,
) -> ConceptRevisionProjection:
    return ConceptRevisionProjection(
        revision_ref=reference,
        sha256=sha256_text(markdown),
        markdown=markdown,
        primary_territory_ref=territory,
        parent_atom_refs=(atom,),
        dispositions=(disposition,),
    )


def _memory_ref() -> MemoryCapsuleRef:
    return MemoryCapsuleRef(
        source_run_id="prior-run",
        source_route_id="creative",
        source_contract_version="1",
        source_artifact_id="creative-idea-009",
        source_artifact_sha256="a" * 64,
        source_memory_record_artifact_id="creative-memory-record",
        source_memory_record_sha256="b" * 64,
        capsule_sha256="c" * 64,
    )


def _challenge() -> str:
    return _markdown("Challenge", CHALLENGE_BRIEF_HEADINGS)


def _brief() -> str:
    return _markdown("Creative Brief", CREATIVE_BRIEF_HEADINGS)


def _territory(index: int) -> TerritoryProjection:
    markdown = f"# Territory {index}\n\nA distinct mechanism space.\n"
    return TerritoryProjection(
        territory_ref=f"creative-territory-{index:02d}",
        sha256=sha256_text(markdown),
        markdown=markdown,
    )


def _nonzero_projection() -> CreativeReportProjection:
    concept_a_r1 = _concept_markdown(
        "Relay Dial Draft",
        hook="Turn one dial and discover that the whole room moved with you.",
        parent_atom_ref="creative-atom-t01-01",
    )
    concept_a_r2 = _concept_markdown(
        "Relay Dial",
        hook="Turn one dial and discover that the whole room moved with you.",
        parent_atom_ref="creative-atom-t01-01",
    )
    concept_a = ConceptProjection(
        concept_id="creative-concept-s01-01",
        origin="base",
        revisions=(
            _revision(
                "creative-concept-s01-01-r001",
                markdown=concept_a_r1,
                territory="creative-territory-01",
                atom="creative-atom-t01-01",
                disposition=_disposition(
                    "a-r001",
                    stage=DispositionStage.C6A,
                    outcome=DispositionOutcome.SUPERSEDED_BY_EVIDENCE_REVISION,
                    target_ref="creative-concept-s01-01-r002",
                    reasons=("c6_evidence_revision_published",),
                ),
            ),
            _revision(
                "creative-concept-s01-01-r002",
                markdown=concept_a_r2,
                territory="creative-territory-01",
                atom="creative-atom-t01-01",
                disposition=_disposition(
                    "a-r002",
                    stage=DispositionStage.C6C,
                    outcome=DispositionOutcome.PROMOTED_TO_FINAL,
                    target_ref="creative-idea-001",
                    reasons=("human_keep",),
                ),
            ),
        ),
    )

    hook_evidence = ReasonEvidenceProjection(
        reason_code="misses_thirty_second_moment",
        evidence_excerpt="The reveal appears only after a five-minute setup.",
        source_review_ref="creative-hook-review-memory-b",
        source_review_sha256="d" * 64,
    )
    concept_b_markdown = _concept_markdown(
        "Memory Maze",
        hook="A maze remembers an older project's reveal but changes its trigger.",
        parent_atom_ref="creative-atom-t02-01",
    )
    concept_b = ConceptProjection(
        concept_id="creative-concept-m01",
        origin="memory_challenger",
        revisions=(
            _revision(
                "creative-concept-m01-r001",
                markdown=concept_b_markdown,
                territory="creative-territory-02",
                atom="creative-atom-t02-01",
                disposition=_disposition(
                    "b-r001",
                    stage=DispositionStage.C4,
                    outcome=DispositionOutcome.ELIMINATED,
                    target_ref=None,
                    reasons=(
                        "c4_double_invalid",
                        "misses_thirty_second_moment",
                    ),
                    evidence=(hook_evidence,),
                ),
            ),
        ),
        memory_source_refs=(_memory_ref(),),
        memory_cue_refs=("memory-cue-01",),
    )

    concept_c_markdown = _concept_markdown(
        "Poetic Clock",
        hook="A clock reveals a collective rhythm when the room falls silent.",
        parent_atom_ref="creative-atom-t03-01",
    )
    concept_c = ConceptProjection(
        concept_id="creative-concept-s02-01",
        origin="base",
        revisions=(
            _revision(
                "creative-concept-s02-01-r001",
                markdown=concept_c_markdown,
                territory="creative-territory-03",
                atom="creative-atom-t03-01",
                disposition=_disposition(
                    "c-r001",
                    stage=DispositionStage.C6B,
                    outcome=DispositionOutcome.NOT_SHORTLISTED,
                    target_ref=None,
                    reasons=("portfolio_capacity",),
                ),
            ),
        ),
    )

    concept_d_markdown = _concept_markdown(
        "Uncanny Mirror",
        hook="A mirror delays one gesture until another person repeats it.",
        parent_atom_ref="creative-atom-t04-01",
    )
    concept_d = ConceptProjection(
        concept_id="creative-concept-s03-01",
        origin="base",
        revisions=(
            _revision(
                "creative-concept-s03-01-r001",
                markdown=concept_d_markdown,
                territory="creative-territory-04",
                atom="creative-atom-t04-01",
                disposition=_disposition(
                    "d-r001",
                    stage=DispositionStage.C6C,
                    outcome=DispositionOutcome.HUMAN_TASTE_VETO,
                    target_ref=None,
                    reasons=("human_taste_veto",),
                ),
            ),
        ),
    )

    concept_e_markdown = _concept_markdown(
        "Quiet Chorus",
        hook="Whispers become visible only when nobody speaks alone.",
        parent_atom_ref="creative-atom-t04-02",
    )
    concept_e = ConceptProjection(
        concept_id="creative-concept-s04-01",
        origin="base",
        revisions=(
            _revision(
                "creative-concept-s04-01-r001",
                markdown=concept_e_markdown,
                territory="creative-territory-04",
                atom="creative-atom-t04-02",
                disposition=_disposition(
                    "e-r001",
                    stage=DispositionStage.C6B,
                    outcome=DispositionOutcome.NOT_SHORTLISTED,
                    target_ref=None,
                    reasons=("curators_both_exclude",),
                ),
            ),
        ),
    )

    final_idea = FinalIdeaProjection(
        idea_id="creative-idea-001",
        sha256=sha256_text(concept_a_r2),
        markdown=concept_a_r2,
        primary_territory_ref="creative-territory-01",
        source_concept_refs=("creative-concept-s01-01-r002",),
        decision_refs=("creative-decision-a-r002",),
        resolution_id="creative-resolution-001",
        novelty=(_novelty(),),
        human_signal=HumanSignalProjection(
            retells=("One dial lets the whole room discover a shared change.",),
            share_targets=("a friend who builds interactive installations",),
            disagreements=("The physical enclosure may distract from the reveal.",),
            receipt_ids=("review-receipt-001",),
            approved_feedback_fragment_refs=("feedback-fragment-001",),
        ),
    )
    challenge = _challenge()
    brief = _brief()
    return CreativeReportProjection(
        run_id="creative-run-001",
        created_at="2026-07-23T09:00:00+08:00",
        producer_kind="live",
        challenge_ref="creative-challenge-brief",
        challenge_sha256=sha256_text(challenge),
        challenge_markdown=challenge,
        creative_brief_ref="creative-brief",
        creative_brief_sha256=sha256_text(brief),
        creative_brief_markdown=brief,
        territories=tuple(_territory(index) for index in range(1, 5)),
        concepts=(concept_a, concept_b, concept_c, concept_d, concept_e),
        memory=MemoryUseProjection(
            mode="auto",
            snapshot_ref="creative-memory-snapshot-001",
            snapshot_sha256="e" * 64,
            status="completed",
            selected_cue_ids=("memory-cue-01",),
            successful_challenger_refs=("creative-concept-m01-r001",),
            source_record_refs=("prior-run:creative-memory-record",),
        ),
        review_rounds=(
            ReviewRoundProjection(
                round_id="creative-review-round-001",
                status="closed",
                concept_refs=(
                    "creative-concept-s01-01-r002",
                    "creative-concept-s03-01-r001",
                ),
                receipt_ids=("review-receipt-001",),
                covered_concept_refs=(
                    "creative-concept-s01-01-r002",
                    "creative-concept-s03-01-r001",
                ),
                resolution_id="creative-resolution-001",
                unresolved_disagreements=(
                    "The physical enclosure may distract from the reveal.",
                ),
            ),
        ),
        final_ideas=(final_idea,),
        zero_reason_code=None,
        empty_batch_skip_reason=None,
    )


def _zero_concept(
    *,
    outcome: DispositionOutcome,
    stage: DispositionStage,
    reason: str,
    legacy: bool = False,
) -> ConceptProjection:
    markdown = _concept_markdown(
        "Zero Candidate",
        hook="A candidate that reaches a documented terminal outcome.",
        parent_atom_ref="creative-atom-t01-01",
        legacy=legacy,
    )
    return ConceptProjection(
        concept_id="creative-concept-s01-01",
        origin="base",
        revisions=(
            _revision(
                "creative-concept-s01-01-r001",
                markdown=markdown,
                territory="creative-territory-01",
                atom="creative-atom-t01-01",
                disposition=_disposition(
                    "zero-r001",
                    stage=stage,
                    outcome=outcome,
                    target_ref=None,
                    reasons=(reason,),
                ),
            ),
        ),
    )


def _zero_projection(reason: str) -> CreativeReportProjection:
    challenge = _challenge()
    legacy = reason == "all_candidates_failed_hook"
    brief = (
        _markdown("Creative Brief", LEGACY_CREATIVE_BRIEF_HEADINGS)
        if legacy
        else _brief()
    )
    concepts: tuple[ConceptProjection, ...]
    if reason == "no_concepts_generated":
        concepts = ()
    elif reason in {
        "all_candidates_failed_hook",
        "all_candidates_failed_concept_screen",
    }:
        concepts = (
            _zero_concept(
                outcome=DispositionOutcome.ELIMINATED,
                stage=DispositionStage.C4,
                reason=(
                    "c4_software_demo_invalid"
                    if reason == "all_candidates_failed_concept_screen"
                    else "c4_double_invalid"
                ),
                legacy=legacy,
            ),
        )
    elif reason == "shortlist_empty":
        concepts = (
            _zero_concept(
                outcome=DispositionOutcome.NOT_SHORTLISTED,
                stage=DispositionStage.C6B,
                reason="insufficient_include_support",
            ),
        )
    else:
        concepts = (
            _zero_concept(
                outcome=DispositionOutcome.HUMAN_REJECT,
                stage=DispositionStage.C6C,
                reason="human_reject",
            ),
        )
    skipped = reason != "all_human_rejected"
    review_rounds = (
        ReviewRoundProjection(
            round_id="creative-review-round-001",
            status="skipped_empty" if skipped else "closed",
            concept_refs=()
            if skipped
            else ("creative-concept-s01-01-r001",),
            receipt_ids=() if skipped else ("review-receipt-001",),
            covered_concept_refs=()
            if skipped
            else ("creative-concept-s01-01-r001",),
            resolution_id=None if skipped else "creative-resolution-001",
        ),
    )
    return CreativeReportProjection(
        run_id=f"creative-run-{reason}",
        created_at="2026-07-23T09:00:00+08:00",
        producer_kind="live",
        challenge_ref="creative-challenge-brief",
        challenge_sha256=sha256_text(challenge),
        challenge_markdown=challenge,
        creative_brief_ref="creative-brief",
        creative_brief_sha256=sha256_text(brief),
        creative_brief_markdown=brief,
        territories=()
        if reason == "no_concepts_generated"
        else (_territory(1),),
        concepts=concepts,
        memory=MemoryUseProjection(
            mode="off",
            snapshot_ref="creative-memory-snapshot-001",
            snapshot_sha256="f" * 64,
            status="disabled",
        ),
        review_rounds=review_rounds,
        final_ideas=(),
        zero_reason_code=reason,
        empty_batch_skip_reason=reason if skipped else None,
        route_contract_version=(
            LEGACY_CREATIVE_CONTRACT_VERSION if legacy else "2"
        ),
        prompt_policy_version=(
            LEGACY_CREATIVE_PROMPT_POLICY_VERSION if legacy else "2"
        ),
        stage_policy_version=(
            LEGACY_CREATIVE_STAGE_POLICY_VERSION if legacy else "2"
        ),
        report_policy_version=(
            LEGACY_CREATIVE_REPORT_POLICY_VERSION if legacy else "2"
        ),
    )


class CreativeReportTests(unittest.TestCase):
    def test_nonzero_bundle_sections_lineage_handoff_and_memory(self) -> None:
        projection = _nonzero_projection()
        bundle = render_success_report(projection)

        self.assertEqual(
            [output.artifact_id for output in bundle.outputs],
            [
                "creative-idea-report",
                "creative-idea-report-json",
                "creative-idea-001-card",
                "creative-idea-card-index",
                "creative-idea-001-handoff",
                "creative-memory-record",
            ],
        )
        report_markdown = bundle.report_markdown.content.decode("utf-8")
        for heading in (
            "## Candidate Fate Ledger",
            "## Idea Memory Used",
            "## Memory-derived Branches",
        ):
            self.assertIn(heading, report_markdown)
        self.assertNotIn("## Zero-Idea Explanation", report_markdown)
        self.assertIn("creative-concept-m01", report_markdown)
        self.assertIn("c4_double_invalid", report_markdown)

        card = bundle.idea_cards[0].content.decode("utf-8")
        validate_markdown(
            card,
            required_h2=FINAL_IDEA_CARD_HEADINGS,
            label="rendered Final Idea Card",
        )
        self.assertIn("concept-stage proxy signal", card)
        self.assertIn("creative-resolution-001", card)
        self.assertIn("feedback-fragment-001", card)

        handoff = json.loads(bundle.handoffs[0].content)
        self.assertEqual(handoff["idea_card_id"], "creative-idea-001-card")
        self.assertEqual(
            handoff["idea_card_sha256"],
            bundle.idea_cards[0].sha256,
        )
        self.assertEqual(handoff["initial_idea_card_markdown"], card)

        report = json.loads(bundle.report_json.content)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(
            report["final_idea_card_ids"],
            ["creative-idea-001-card"],
        )
        memory_concept = next(
            item
            for item in report["concepts"]
            if item["concept_id"] == "creative-concept-m01"
        )
        self.assertEqual(memory_concept["origin"], "memory_challenger")

        memory = MemoryRecord.from_mapping(
            json.loads(bundle.memory_record.content)
        )
        classifications = {entry.classification for entry in memory.entries}
        self.assertEqual(
            classifications,
            {
                "positive",
                "caution",
                "portfolio_only",
                "subjective",
                "transformed",
            },
        )
        by_ref = {
            entry.source_candidate_ref: entry for entry in memory.entries
        }
        self.assertNotIn("creative-concept-s01-01-r002", by_ref)
        self.assertEqual(
            by_ref["creative-concept-m01-r001"].reason_evidence[0].reason_code,
            "misses_thirty_second_moment",
        )
        self.assertEqual(
            memory.source_report_sha256,
            bundle.report_markdown.sha256,
        )

    def test_all_zero_reasons_have_per_candidate_explanation(self) -> None:
        reasons = (
            "no_concepts_generated",
            "all_candidates_failed_hook",
            "all_candidates_failed_concept_screen",
            "shortlist_empty",
            "all_human_rejected",
        )
        for reason in reasons:
            with self.subTest(reason=reason):
                bundle = render_success_report(_zero_projection(reason))
                report_markdown = bundle.report_markdown.content.decode("utf-8")
                report = json.loads(bundle.report_json.content)
                memory = MemoryRecord.from_mapping(
                    json.loads(bundle.memory_record.content)
                )

                self.assertIn("## Zero-Idea Explanation", report_markdown)
                self.assertIn(f"`{reason}`", report_markdown)
                self.assertEqual(report["zero_reason_code"], reason)
                self.assertEqual(report["final_idea_card_ids"], [])
                self.assertEqual(report["handoff_refs"], [])
                self.assertEqual(memory.zero_reason_code, reason)
                self.assertFalse(
                    any(
                        entry.source_kind == "final_idea"
                        for entry in memory.entries
                    )
                )
                if reason == "no_concepts_generated":
                    self.assertIn(
                        "there is no candidate disposition to omit",
                        report_markdown,
                    )
                else:
                    self.assertIn("terminal stage:", report_markdown)
                    self.assertIn("reason codes:", report_markdown)
                    self.assertIn("decision:", report_markdown)
                    self.assertIn("evidence:", report_markdown)

    def test_input_order_does_not_change_any_output_byte(self) -> None:
        projection = _nonzero_projection()
        baseline = render_success_report(projection)
        reversed_concepts = tuple(
            replace(
                concept,
                revisions=tuple(
                    replace(
                        revision,
                        dispositions=tuple(reversed(revision.dispositions)),
                        parent_atom_refs=tuple(reversed(revision.parent_atom_refs)),
                    )
                    for revision in reversed(concept.revisions)
                ),
                memory_source_refs=tuple(reversed(concept.memory_source_refs)),
                memory_cue_refs=tuple(reversed(concept.memory_cue_refs)),
            )
            for concept in reversed(projection.concepts)
        )
        reversed_ideas = tuple(
            replace(
                idea,
                source_concept_refs=tuple(reversed(idea.source_concept_refs)),
                decision_refs=tuple(reversed(idea.decision_refs)),
                novelty=tuple(reversed(idea.novelty)),
                human_signal=replace(
                    idea.human_signal,
                    retells=tuple(reversed(idea.human_signal.retells)),
                    share_targets=tuple(
                        reversed(idea.human_signal.share_targets)
                    ),
                    disagreements=tuple(
                        reversed(idea.human_signal.disagreements)
                    ),
                    receipt_ids=tuple(
                        reversed(idea.human_signal.receipt_ids)
                    ),
                    approved_feedback_fragment_refs=tuple(
                        reversed(
                            idea.human_signal.approved_feedback_fragment_refs
                        )
                    ),
                ),
            )
            for idea in reversed(projection.final_ideas)
        )
        disturbed = replace(
            projection,
            territories=tuple(reversed(projection.territories)),
            concepts=reversed_concepts,
            review_rounds=tuple(reversed(projection.review_rounds)),
            final_ideas=reversed_ideas,
            memory=replace(
                projection.memory,
                selected_cue_ids=tuple(
                    reversed(projection.memory.selected_cue_ids)
                ),
                successful_challenger_refs=tuple(
                    reversed(
                        projection.memory.successful_challenger_refs
                    )
                ),
                failed_task_refs=tuple(
                    reversed(projection.memory.failed_task_refs)
                ),
                source_record_refs=tuple(
                    reversed(projection.memory.source_record_refs)
                ),
            ),
        )
        replay = render_success_report(disturbed)
        self.assertEqual(
            [(item.artifact_id, item.content) for item in replay.outputs],
            [(item.artifact_id, item.content) for item in baseline.outputs],
        )

    def test_outputs_exclude_private_fields_and_absolute_local_paths(self) -> None:
        bundle = render_success_report(_nonzero_projection())
        combined = b"\n".join(item.content for item in bundle.outputs)
        for forbidden in (
            b"reviewer_id",
            b"reviewer_name",
            b"curator_name",
            b"raw_feedback",
            b"curator_instruction",
            b"prompt_text",
            b"task_log",
            b"session_id",
            b"/Users/",
        ):
            self.assertNotIn(forbidden, combined)

        projection = _nonzero_projection()
        leaked_challenge = projection.challenge_markdown.replace(
            "Exact Challenge Summary text.",
            "Read /Users/percy/private-notes.md.",
        )
        with self.assertRaisesRegex(
            CreativeReportError,
            "absolute local path",
        ):
            replace(
                projection,
                challenge_markdown=leaked_challenge,
                challenge_sha256=sha256_text(leaked_challenge),
            )

    def test_lineage_must_close_before_rendering(self) -> None:
        projection = _nonzero_projection()
        concept = projection.concepts[0]
        source_revision = concept.revisions[1]
        broken_disposition = replace(
            source_revision.dispositions[0],
            target_ref="creative-idea-999",
        )
        broken_revision = replace(
            source_revision,
            dispositions=(broken_disposition,),
        )
        broken_concept = replace(
            concept,
            revisions=(concept.revisions[0], broken_revision),
        )
        broken_projection = replace(
            projection,
            concepts=(broken_concept, *projection.concepts[1:]),
        )

        with self.assertRaisesRegex(
            CreativeReportError,
            "missing Final Idea",
        ):
            render_success_report(broken_projection)

    def test_zero_reason_and_empty_batch_contract_are_mutually_consistent(
        self,
    ) -> None:
        projection = _zero_projection("shortlist_empty")
        with self.assertRaisesRegex(
            CreativeReportError,
            "must equal zero_reason_code",
        ):
            replace(
                projection,
                empty_batch_skip_reason="all_candidates_failed_hook",
            )


if __name__ == "__main__":
    unittest.main()
