from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from hacksome.contracts.build_to_pitch import (
    BuildToPitchInput,
    BuildToPitchInputError,
)
from hacksome.contracts.idea_to_build import (
    IdeaToBuildHandoff,
    IdeaToBuildHandoffError,
)


class IdeaToBuildHandoffTests(unittest.TestCase):
    def _payload(self) -> dict[str, str]:
        card = "# Idea\n\nA real product.\n"
        return {
            "source_run_id": "creative-run",
            "idea_card_id": "creative-idea-card-001",
            "idea_card_sha256": sha256(card.encode()).hexdigest(),
            "challenge_markdown": "# Challenge\n",
            "initial_idea_card_markdown": card,
        }

    def test_round_trip_preserves_the_manual_handoff(self) -> None:
        payload = self._payload()
        handoff = IdeaToBuildHandoff.from_mapping(payload)

        self.assertEqual(handoff.to_dict(), payload)
        self.assertEqual(
            handoff.identity,
            ":".join(
                (
                    payload["source_run_id"],
                    payload["idea_card_id"],
                    payload["idea_card_sha256"],
                )
            ),
        )

    def test_unknown_fields_fail_closed(self) -> None:
        payload = self._payload()
        payload["automatic_build"] = "true"

        with self.assertRaisesRegex(IdeaToBuildHandoffError, "unknown fields"):
            IdeaToBuildHandoff.from_mapping(payload)

    def test_hash_drift_fails_closed_for_mapping_and_file(self) -> None:
        payload = self._payload()
        payload["initial_idea_card_markdown"] += "changed"
        with self.assertRaisesRegex(IdeaToBuildHandoffError, "hash"):
            IdeaToBuildHandoff.from_mapping(payload)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(IdeaToBuildHandoffError, "hash"):
                IdeaToBuildHandoff.from_json_file(path)


class BuildToPitchInputTests(unittest.TestCase):
    def test_validates_three_explicit_operator_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            idea = root / "idea.md"
            challenge = root / "challenge.md"
            idea.write_text("# Idea\n", encoding="utf-8")
            challenge.write_text("# Challenge\n", encoding="utf-8")

            inputs = BuildToPitchInput.validate(project, idea, challenge)

            self.assertEqual(inputs.project_directory, project.resolve())
            self.assertEqual(inputs.source_record()["handoff"], "manual")

    def test_missing_or_empty_input_fails_before_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            idea = root / "idea.md"
            idea.write_text("", encoding="utf-8")

            with self.assertRaises(BuildToPitchInputError):
                BuildToPitchInput.validate(project, idea, root / "missing.md")

    def test_top_level_symlink_inputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            project_link = root / "project-link"
            project_link.symlink_to(project, target_is_directory=True)
            idea = root / "idea.md"
            challenge = root / "challenge.md"
            idea.write_text("# Idea\n", encoding="utf-8")
            challenge.write_text("# Challenge\n", encoding="utf-8")
            idea_link = root / "idea-link.md"
            idea_link.symlink_to(idea)

            with self.assertRaisesRegex(BuildToPitchInputError, "symlink"):
                BuildToPitchInput.validate(project_link, idea, challenge)
            with self.assertRaisesRegex(BuildToPitchInputError, "symlink"):
                BuildToPitchInput.validate(project, idea_link, challenge)
