from __future__ import annotations

import unittest

from hacksome.stages.ideation.useful.artifacts import (
    IDEA_HEADINGS,
    ArtifactError,
    compose_idea_card,
    compose_idea_index,
    validate_markdown,
)


def idea_markdown() -> str:
    sections = "\n\n".join(f"## {heading}\n\nvalue" for heading in IDEA_HEADINGS)
    return f"# Useful Product\n\n{sections}\n"


class ArtifactTests(unittest.TestCase):
    def test_required_sections_are_validated_deterministically(self) -> None:
        validate_markdown(idea_markdown(), required_h2=IDEA_HEADINGS, label="Idea")

        broken = idea_markdown().replace("## First Real Version", "## Prototype")
        with self.assertRaisesRegex(ArtifactError, "First Real Version"):
            validate_markdown(broken, required_h2=IDEA_HEADINGS, label="Idea")

    def test_duplicate_required_section_is_rejected(self) -> None:
        duplicate = idea_markdown() + "\n## User\n\nagain\n"
        with self.assertRaisesRegex(ArtifactError, "exactly one"):
            validate_markdown(duplicate, required_h2=IDEA_HEADINGS, label="Idea")

    def test_card_contains_lineage_exact_idea_and_review(self) -> None:
        review = "# Red Team Review\n\nThe flow delivers value.\n"
        card = compose_idea_card(
            idea_markdown=idea_markdown(),
            review_markdown=review,
            lineage={"idea_id": "idea-001", "red_team_session_id": "session-9"},
        )
        self.assertIn('"idea_id": "idea-001"', card)
        self.assertIn("## Product Experience\n\nvalue", card)
        self.assertIn("Decision: `pass`", card)
        self.assertIn("The flow delivers value.", card)

    def test_empty_index_is_valid(self) -> None:
        index = compose_idea_index([])
        self.assertIn("No Idea passed", index)


if __name__ == "__main__":
    unittest.main()
