from __future__ import annotations

import unittest

from hacksome.creative.artifacts import (
    ATOM_HEADINGS,
    CHALLENGE_BRIEF_HEADINGS,
    CONCEPT_HEADINGS,
    CONSTRAINT_VIEW_HEADINGS,
    CreativeArtifactError,
    EVIDENCE_REVISION_HEADINGS,
    FEEDBACK_REVISION_HEADINGS,
    FINAL_IDEA_CARD_HEADINGS,
    HOOK_DIMENSIONS,
    HOOK_REASON_BY_DIMENSION,
    MEMORY_REMIX_HEADINGS,
    NOVELTY_SCAN_HEADINGS,
    PORTFOLIO_DIMENSIONS,
    SOFTWARE_DEMO_DIMENSIONS,
    SOFTWARE_DEMO_REASON_BY_DIMENSION,
    compose_final_idea_card,
    normalized_hook,
    validate_creative_output,
)
from hacksome.creative.contracts import (
    C0_CHALLENGE_PARSE,
    C2_TERRITORY_EXPLORE,
    C3_CONCEPT_SYNTHESIZE,
    C4_CHEAP_HOOK_REVIEW,
    C4_SOFTWARE_DEMO_REVIEW,
    C5M_MEMORY_REMIX,
    C5W_NOVELTY_SCAN,
    C6A_EVIDENCE_REVISE,
    C6B_PORTFOLIO_CURATE,
    C6C_FEEDBACK_REVISE,
    CreativeWorkflowSettings,
)


SETTINGS = CreativeWorkflowSettings()


def _markdown(title: str, headings: tuple[str, ...]) -> str:
    sections = "\n\n".join(
        f"## {heading}\n\ncontent for {heading}" for heading in headings
    )
    return f"# {title}\n\n{sections}\n"


def _concept_markdown(
    *,
    hook: str = "A door answers in your own future voice.",
    parent_refs: tuple[str, ...] = ("creative-atom-t01-01",),
    extra_headings: tuple[str, ...] = (),
) -> str:
    bodies = {heading: f"content for {heading}" for heading in CONCEPT_HEADINGS}
    bodies["One-sentence Hook"] = hook
    bodies["Parent Atoms"] = "\n".join(f"- `{ref}`" for ref in parent_refs)
    headings = CONCEPT_HEADINGS + extra_headings
    sections = "\n\n".join(f"## {heading}\n\n{bodies.get(heading, 'value')}" for heading in headings)
    return f"# Concept\n\n{sections}\n"


def _memory_ref() -> dict[str, str]:
    return {
        "source_run_id": "run-001",
        "source_route_id": "creative",
        "source_contract_version": "1",
        "source_artifact_id": "creative-idea-001",
        "source_artifact_sha256": "a" * 64,
        "source_memory_record_artifact_id": "creative-memory-record",
        "source_memory_record_sha256": "b" * 64,
        "capsule_sha256": "c" * 64,
    }


class CreativeArtifactValidationTests(unittest.TestCase):
    def test_c0_requires_both_complete_markdown_contracts(self) -> None:
        valid = {
            "challenge_brief_markdown": _markdown(
                "Challenge", CHALLENGE_BRIEF_HEADINGS
            ),
            "constraint_view_markdown": _markdown(
                "Constraints", CONSTRAINT_VIEW_HEADINGS
            ),
        }

        self.assertEqual(
            validate_creative_output(
                C0_CHALLENGE_PARSE,
                valid,
                settings=SETTINGS,
            ),
            valid,
        )
        valid["constraint_view_markdown"] = valid[
            "constraint_view_markdown"
        ].replace("## Hard Rules", "## Soft Rules")
        with self.assertRaisesRegex(CreativeArtifactError, "Hard Rules"):
            validate_creative_output(
                C0_CHALLENGE_PARSE,
                valid,
                settings=SETTINGS,
            )

    def test_c2_accepts_natural_territory_text_and_enforces_atom_cap(
        self,
    ) -> None:
        atom = {"markdown": _markdown("Atom", ATOM_HEADINGS)}
        valid = {
            "territory_markdown": "# Territory\n\nA mechanism space.",
            "atoms": [atom],
        }

        self.assertNotIn("creative-territory-", atom["markdown"])
        self.assertEqual(
            validate_creative_output(
                C2_TERRITORY_EXPLORE,
                valid,
                settings=SETTINGS,
            ),
            valid,
        )
        over_limit = dict(valid, atoms=[atom, atom])
        with self.assertRaisesRegex(CreativeArtifactError, "configured"):
            validate_creative_output(
                C2_TERRITORY_EXPLORE,
                over_limit,
                settings=CreativeWorkflowSettings(max_atoms_per_territory=1),
            )

    def test_c3_binds_parent_atoms_primary_territory_and_normalized_hooks(
        self,
    ) -> None:
        concept = {
            "markdown": _concept_markdown(),
            "primary_territory_ref": "creative-territory-01",
            "parent_atom_refs": ["creative-atom-t01-01"],
        }

        validate_creative_output(
            C3_CONCEPT_SYNTHESIZE,
            {"concepts": [concept]},
            settings=SETTINGS,
            context={"allowed_atom_refs": {"creative-atom-t01-01"}},
        )
        bad = dict(concept, primary_territory_ref="creative-territory-02")
        with self.assertRaisesRegex(CreativeArtifactError, "primary_territory"):
            validate_creative_output(
                C3_CONCEPT_SYNTHESIZE,
                {"concepts": [bad]},
                settings=SETTINGS,
            )
        duplicate = dict(
            concept,
            markdown=_concept_markdown(
                hook="  A DOOR answers—in your own future voice! "
            ),
        )
        with self.assertRaisesRegex(CreativeArtifactError, "normalized-Hook"):
            validate_creative_output(
                C3_CONCEPT_SYNTHESIZE,
                {"concepts": [concept, duplicate]},
                settings=SETTINGS,
            )
        missing_runtime = dict(
            concept,
            markdown=concept["markdown"].replace(
                "## Software Core and Runtime",
                "## Runtime Details",
            ),
        )
        with self.assertRaisesRegex(
            CreativeArtifactError,
            "Software Core and Runtime",
        ):
            validate_creative_output(
                C3_CONCEPT_SYNTHESIZE,
                {"concepts": [missing_runtime]},
                settings=SETTINGS,
            )

    def test_hook_review_requires_stable_dimension_order_and_reason_mapping(
        self,
    ) -> None:
        dimensions = [
            {
                "dimension": dimension,
                "verdict": "pass",
                "reason_code": None,
                "evidence": "quoted Concept evidence",
            }
            for dimension in HOOK_DIMENSIONS
        ]
        output = {
            "overall_decision": "pass",
            "dimensions": dimensions,
            "markdown": "# Hook Review\n\nAll six dimensions pass.",
        }

        validate_creative_output(
            C4_CHEAP_HOOK_REVIEW,
            output,
            settings=SETTINGS,
        )
        dimensions[0]["verdict"] = "fail"
        dimensions[0]["reason_code"] = HOOK_REASON_BY_DIMENSION[
            dimensions[0]["dimension"]
        ]
        with self.assertRaisesRegex(CreativeArtifactError, "overall_decision"):
            validate_creative_output(
                C4_CHEAP_HOOK_REVIEW,
                output,
                settings=SETTINGS,
            )

    def test_software_demo_review_is_ordered_and_reason_bound(self) -> None:
        dimensions = [
            {
                "dimension": dimension,
                "verdict": "pass",
                "reason_code": None,
                "evidence": "The browser runs a real end-to-end transformation.",
            }
            for dimension in SOFTWARE_DEMO_DIMENSIONS
        ]
        output = {
            "overall_decision": "pass",
            "dimensions": dimensions,
            "markdown": "# Software Demo Review\n\nAll dimensions pass.",
        }

        validate_creative_output(
            C4_SOFTWARE_DEMO_REVIEW,
            output,
            settings=SETTINGS,
        )
        dimensions[1]["verdict"] = "fail"
        dimensions[1]["reason_code"] = SOFTWARE_DEMO_REASON_BY_DIMENSION[
            "hardware_independence"
        ]
        output["overall_decision"] = "invalid"
        validate_creative_output(
            C4_SOFTWARE_DEMO_REVIEW,
            output,
            settings=SETTINGS,
        )
        dimensions[1]["reason_code"] = (
            SOFTWARE_DEMO_REASON_BY_DIMENSION["hackathon_scope"]
        )
        with self.assertRaisesRegex(
            CreativeArtifactError,
            "requires_custom_hardware",
        ):
            validate_creative_output(
                C4_SOFTWARE_DEMO_REVIEW,
                output,
                settings=SETTINGS,
            )

    def test_portfolio_decision_is_mechanical_not_a_score(self) -> None:
        reference = "creative-concept-s01-01-r002"
        row = {
            "concept_ref": reference,
            "decision": "include",
            "dimensions": [
                {
                    "dimension": dimension,
                    "verdict": "pass",
                    "reason": "Categorical reason.",
                    "evidence": "Exact Concept evidence.",
                }
                for dimension in PORTFOLIO_DIMENSIONS
            ],
            "rationale": "All categorical dimensions pass.",
            "possible_duplicate_refs": [],
        }
        validate_creative_output(
            C6B_PORTFOLIO_CURATE,
            {"classifications": [row]},
            settings=SETTINGS,
            context={"allowed_concept_refs": {reference}},
        )
        row["dimensions"][0]["verdict"] = "uncertain"
        with self.assertRaisesRegex(CreativeArtifactError, "mechanically"):
            validate_creative_output(
                C6B_PORTFOLIO_CURATE,
                {"classifications": [row]},
                settings=SETTINGS,
                context={"allowed_concept_refs": {reference}},
            )

    def test_memory_remix_requires_complete_composite_refs(self) -> None:
        concept = {
            "markdown": _concept_markdown(
                parent_refs=("creative-atom-t02-01",),
                extra_headings=MEMORY_REMIX_HEADINGS,
            ),
            "primary_territory_ref": "creative-territory-02",
            "current_atom_refs": ["creative-atom-t02-01"],
            "memory_source_refs": [_memory_ref()],
            "cue_refs": ["memory-cue-01"],
        }

        validate_creative_output(
            C5M_MEMORY_REMIX,
            {"concept": concept},
            settings=SETTINGS,
        )
        concept["memory_source_refs"] = ["creative-idea-001"]
        with self.assertRaisesRegex(
            CreativeArtifactError,
            "failed JSON Schema",
        ):
            validate_creative_output(
                C5M_MEMORY_REMIX,
                {"concept": concept},
                settings=SETTINGS,
            )

    def test_novelty_rejects_non_http_and_credentialed_urls(self) -> None:
        output = {
            "markdown": _markdown("Novelty", NOVELTY_SCAN_HEADINGS),
            "sources": [
                {
                    "title": "Source",
                    "url": "file:///tmp/source",
                    "relation": "near",
                    "evidence": "A near collision.",
                }
            ],
        }

        with self.assertRaisesRegex(CreativeArtifactError, "absolute HTTP"):
            validate_creative_output(
                C5W_NOVELTY_SCAN,
                output,
                settings=SETTINGS,
            )

    def test_evidence_revision_preserves_bounded_source_sections(self) -> None:
        source = _concept_markdown()
        changed = _concept_markdown(
            hook="A sharper hook",
            extra_headings=EVIDENCE_REVISION_HEADINGS,
        )

        validate_creative_output(
            C6A_EVIDENCE_REVISE,
            {"markdown": changed},
            settings=SETTINGS,
            context={"source_markdown": source},
        )
        changed = changed.replace(
            "content for Real Input, Transformation and Output",
            "a wholly different mechanism",
        )
        with self.assertRaisesRegex(CreativeArtifactError, "must preserve"):
            validate_creative_output(
                C6A_EVIDENCE_REVISE,
                {"markdown": changed},
                settings=SETTINGS,
                context={"source_markdown": source},
            )

    def test_feedback_revision_cannot_invent_primary_territory(self) -> None:
        output = {
            "markdown": _concept_markdown(
                extra_headings=FEEDBACK_REVISION_HEADINGS
            ),
            "primary_territory_ref": "creative-territory-03",
        }

        with self.assertRaisesRegex(CreativeArtifactError, "come from a source"):
            validate_creative_output(
                C6C_FEEDBACK_REVISE,
                output,
                settings=SETTINGS,
                context={
                    "allowed_primary_territory_refs": {
                        "creative-territory-01",
                        "creative-territory-02",
                    }
                },
            )

    def test_final_card_composer_is_ordered_and_requires_all_sections(self) -> None:
        sections = {
            heading: f"body for {heading}" for heading in FINAL_IDEA_CARD_HEADINGS
        }
        card = compose_final_idea_card(title="Final Idea", sections=sections)

        self.assertEqual(card.count("# Final Idea"), 1)
        self.assertLess(card.index("## Intended Reaction"), card.index("## Lineage"))
        self.assertEqual(normalized_hook(_concept_markdown()), "a door answers in your own future voice")
        with self.assertRaisesRegex(CreativeArtifactError, "missing"):
            compose_final_idea_card(
                title="Incomplete",
                sections={
                    key: value for key, value in sections.items() if key != "Lineage"
                },
            )


if __name__ == "__main__":
    unittest.main()
