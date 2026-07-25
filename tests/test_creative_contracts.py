from __future__ import annotations

import unittest
from dataclasses import replace

from hacksome.creative.contracts import (
    CREATIVE_SETTING_HARD_MAXIMA,
    CREATIVE_STAGES,
    ConceptDisposition,
    ConceptRevisionMetadata,
    CreativeContractError,
    CreativeWorkflowSettings,
    CrossRunArtifactRef,
    DispositionOutcome,
    DispositionStage,
    RevisionBudget,
    RevisionReason,
    StableReasonCode,
    ZeroReasonCode,
    atom_id,
    base_concept_id,
    concept_revision_ref,
    final_idea_id,
    memory_concept_id,
    memory_cue_id,
    parse_concept_revision_ref,
    territory_for_atom,
    territory_id,
)
from hacksome.config import (
    decode_persisted_dataclass,
    persisted_dataclass_sha256,
    serialize_persisted_dataclass,
)


_SHA = "a" * 64


def _memory_ref() -> CrossRunArtifactRef:
    return CrossRunArtifactRef(
        source_run_id="run-001",
        source_route_id="creative",
        source_contract_version="1",
        source_artifact_id="creative-idea-001",
        source_artifact_sha256=_SHA,
        source_memory_record_artifact_id="creative-memory-record",
        source_memory_record_sha256="b" * 64,
        capsule_sha256="c" * 64,
    )


class CreativeSettingsTests(unittest.TestCase):
    def test_defaults_match_the_approved_bounded_design(self) -> None:
        settings = CreativeWorkflowSettings()

        self.assertEqual(settings.territory_explorers, 6)
        self.assertEqual(settings.max_atoms_per_territory, 3)
        self.assertEqual(settings.concept_synthesizers, 4)
        self.assertEqual(settings.max_concepts_per_synthesizer, 3)
        self.assertEqual(settings.hook_reviewers_per_concept, 2)
        self.assertEqual(settings.idea_memory_mode, "auto")
        self.assertEqual(settings.max_memory_runs, 20)
        self.assertEqual(settings.max_memory_entries, 80)
        self.assertEqual(settings.max_memory_snapshot_bytes, 256 * 1024)
        self.assertEqual(settings.max_memory_selected_cues, 8)
        self.assertEqual(settings.memory_remixers, 2)
        self.assertEqual(settings.max_memory_challengers, 2)
        self.assertEqual(settings.portfolio_curators, 2)
        self.assertEqual(settings.max_human_shortlist, 8)
        self.assertEqual(settings.max_hook_repairs, 1)
        self.assertEqual(settings.max_feedback_revisions, 1)

    def test_every_numeric_setting_rejects_bool_and_exceeding_hard_cap(self) -> None:
        settings = CreativeWorkflowSettings()

        for field_name, maximum in CREATIVE_SETTING_HARD_MAXIMA.items():
            with self.subTest(field=field_name, kind="boolean"):
                with self.assertRaises(CreativeContractError):
                    replace(settings, **{field_name: True})
            with self.subTest(field=field_name, kind="over-cap"):
                with self.assertRaises(CreativeContractError):
                    replace(settings, **{field_name: maximum + 1})

    def test_optional_branches_can_be_disabled_but_fixed_quorums_cannot(self) -> None:
        settings = CreativeWorkflowSettings(
            memory_remixers=0,
            max_memory_challengers=0,
            max_hook_repairs=0,
            max_feedback_revisions=0,
            idea_memory_mode="off",
        )

        self.assertEqual(settings.memory_remixers, 0)
        with self.assertRaisesRegex(CreativeContractError, "exactly 2"):
            replace(settings, hook_reviewers_per_concept=1)
        with self.assertRaisesRegex(CreativeContractError, "auto.*off"):
            replace(settings, idea_memory_mode="sometimes")  # type: ignore[arg-type]

    def test_settings_use_the_shared_hash_bound_persisted_codec(self) -> None:
        settings = CreativeWorkflowSettings(
            territory_explorers=4,
            idea_memory_mode="off",
            memory_remixers=0,
            max_memory_challengers=0,
        )
        payload = serialize_persisted_dataclass(settings)

        restored = decode_persisted_dataclass(
            CreativeWorkflowSettings,
            payload,
            expected_sha256=persisted_dataclass_sha256(settings),
        )

        self.assertEqual(restored, settings)


class CreativeIdentityTests(unittest.TestCase):
    def test_stable_ids_are_derived_only_from_stable_slots(self) -> None:
        self.assertEqual(territory_id(1), "creative-territory-01")
        self.assertEqual(atom_id(1, 3), "creative-atom-t01-03")
        self.assertEqual(base_concept_id(4, 2), "creative-concept-s04-02")
        self.assertEqual(memory_concept_id(2), "creative-concept-m02")
        self.assertEqual(
            concept_revision_ref("creative-concept-s04-02", 3),
            "creative-concept-s04-02-r003",
        )
        self.assertEqual(final_idea_id(7), "creative-idea-007")
        self.assertEqual(memory_cue_id(8), "memory-cue-08")
        self.assertEqual(
            parse_concept_revision_ref("creative-concept-m02-r003"),
            ("creative-concept-m02", 3),
        )
        self.assertEqual(
            territory_for_atom("creative-atom-t06-02"),
            "creative-territory-06",
        )

        for invalid in (0, -1, True, 1000):
            with self.subTest(index=invalid):
                with self.assertRaises(CreativeContractError):
                    final_idea_id(invalid)  # type: ignore[arg-type]

    def test_revision_metadata_enforces_parent_territory_and_monotonic_lineage(
        self,
    ) -> None:
        initial = ConceptRevisionMetadata(
            concept_id="creative-concept-s01-01",
            revision=1,
            origin="base",
            primary_territory_ref="creative-territory-01",
            parent_atom_refs=("creative-atom-t01-01", "creative-atom-t02-01"),
        )
        repaired = ConceptRevisionMetadata(
            concept_id=initial.concept_id,
            revision=2,
            origin="base",
            primary_territory_ref=initial.primary_territory_ref,
            parent_atom_refs=initial.parent_atom_refs,
            supersedes_ref=initial.revision_ref,
            revision_reason=RevisionReason.CHEAP_HOOK_REPAIR,
        )

        self.assertEqual(initial.revision_ref, "creative-concept-s01-01-r001")
        self.assertEqual(repaired.revision_ref, "creative-concept-s01-01-r002")
        with self.assertRaisesRegex(CreativeContractError, "Parent Atom"):
            replace(initial, primary_territory_ref="creative-territory-03")
        with self.assertRaisesRegex(CreativeContractError, "must supersede"):
            replace(repaired, supersedes_ref="creative-concept-s01-01-r999")

    def test_memory_challenger_requires_current_and_hash_bound_history(self) -> None:
        challenger = ConceptRevisionMetadata(
            concept_id="creative-concept-m01",
            revision=1,
            origin="memory_challenger",
            primary_territory_ref="creative-territory-02",
            parent_atom_refs=("creative-atom-t02-01",),
            memory_source_refs=(_memory_ref(),),
            memory_cue_refs=("memory-cue-01",),
        )

        self.assertEqual(challenger.origin, "memory_challenger")
        with self.assertRaisesRegex(CreativeContractError, "cross-run"):
            replace(challenger, memory_source_refs=())


class CreativeRevisionAndDispositionTests(unittest.TestCase):
    def test_revision_budgets_are_independent_and_fail_closed(self) -> None:
        settings = CreativeWorkflowSettings()
        budget = RevisionBudget()
        budget = budget.consume(
            RevisionReason.CHEAP_HOOK_REPAIR,
            settings=settings,
        )
        budget = budget.consume(
            RevisionReason.EVIDENCE_INFORMED,
            settings=settings,
        )
        budget = budget.consume(
            RevisionReason.HUMAN_FEEDBACK,
            settings=settings,
        )

        self.assertEqual(budget, RevisionBudget(1, 1, 1))
        budget.require_evidence_revision()
        for reason in RevisionReason:
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(CreativeContractError, "exhausted"):
                    budget.consume(reason, settings=settings)

    def test_disposition_target_and_reason_contracts(self) -> None:
        disposition = ConceptDisposition(
            disposition_id="creative-disposition-concept-1-superseded",
            concept_revision_ref="creative-concept-s01-01-r001",
            concept_sha256=_SHA,
            stage=DispositionStage.C4,
            outcome=DispositionOutcome.SUPERSEDED_BY_HOOK_REPAIR,
            terminal=True,
            target_ref="creative-concept-s01-01-r002",
            reason_codes=(
                StableReasonCode.C4_HOOK_REPAIR_PUBLISHED.value,
            ),
            decision_ref="creative-decision-c4-001",
        )

        self.assertTrue(disposition.terminal)
        with self.assertRaisesRegex(CreativeContractError, "requires.*target"):
            replace(disposition, target_ref=None)
        with self.assertRaisesRegex(CreativeContractError, "requires one of"):
            replace(
                disposition,
                reason_codes=(StableReasonCode.C4_DOUBLE_INVALID.value,),
            )

    def test_zero_reason_enum_contains_legacy_and_v2_screen_causes(self) -> None:
        self.assertEqual(
            {reason.value for reason in ZeroReasonCode},
            {
                "no_concepts_generated",
                "all_candidates_failed_hook",
                "all_candidates_failed_concept_screen",
                "shortlist_empty",
                "all_human_rejected",
            },
        )
        self.assertEqual(len(CREATIVE_STAGES), 13)


if __name__ == "__main__":
    unittest.main()
