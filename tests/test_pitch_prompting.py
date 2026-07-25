from __future__ import annotations

import json
import unittest

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from hacksome.pitch.prompting import pitch_prompt_catalog


class PitchPromptingTests(unittest.TestCase):
    def test_catalog_has_exactly_the_four_role_prompts(self) -> None:
        self.assertEqual(
            pitch_prompt_catalog.stages(),
            (
                "pitch-director",
                "pitch-reviewer",
                "pitch-html",
                "pitch-script",
            ),
        )
        for stage in pitch_prompt_catalog.stages():
            spec = pitch_prompt_catalog[stage]
            self.assertTrue(spec.template_path.is_file())
            self.assertTrue(spec.schema_path.is_file())
            schema = json.loads(spec.schema_path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            self._assert_codex_typed_constants(schema, path=stage)

    def _assert_codex_typed_constants(
        self,
        value: object,
        *,
        path: str,
    ) -> None:
        if isinstance(value, dict):
            if "const" in value or "enum" in value:
                self.assertIn(
                    "type",
                    value,
                    f"{path} const/enum must declare an explicit Codex schema type",
                )
            for key, child in value.items():
                self._assert_codex_typed_constants(child, path=f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self._assert_codex_typed_constants(child, path=f"{path}[{index}]")

    def test_role_prompts_pin_snapshot_and_responsibility_boundaries(self) -> None:
        prompts = {
            stage: pitch_prompt_catalog[stage].template_path.read_text(
                encoding="utf-8"
            )
            for stage in pitch_prompt_catalog.stages()
        }
        for text in prompts.values():
            self.assertIn("PROJECT_SNAPSHOT", text)
            self.assertIn("source Project", text)
        self.assertIn("deck-outline.md", prompts["pitch-director"])
        self.assertNotIn("pitch-deck.html", prompts["pitch-director"])
        self.assertIn("outline-review.md", prompts["pitch-reviewer"])
        self.assertIn("Do not edit it", prompts["pitch-reviewer"])
        self.assertIn("real Chromium-family browser", prompts["pitch-html"])
        self.assertIn("pitch-deck.html", prompts["pitch-html"])
        html_normalized = " ".join(prompts["pitch-html"].split())
        self.assertIn("Do not install dependencies", html_normalized)
        self.assertIn("at most one focused attempt", html_normalized)
        self.assertIn(
            "Never let optional capture work delay",
            html_normalized,
        )
        self.assertIn("pitch-script.md", prompts["pitch-script"])

    def test_all_roles_use_bounded_targeted_product_discovery(self) -> None:
        prompts = {
            stage: pitch_prompt_catalog[stage].template_path.read_text(
                encoding="utf-8"
            )
            for stage in pitch_prompt_catalog.stages()
        }
        for stage, text in prompts.items():
            with self.subTest(stage=stage):
                normalized = " ".join(text.split())
                self.assertIn("targeted product discovery", normalized)
                self.assertIn("not exhaustive traversal", normalized)
                self.assertIn("`node_modules`", normalized)
                self.assertIn("vendored code", normalized)
                self.assertIn("caches", normalized)
                self.assertIn("`.git`", normalized)
                self.assertIn("lockfiles", normalized)
                self.assertIn(
                    "generated or minified `dist`/`build`",
                    normalized,
                )
                self.assertIn("authored source is absent", normalized)
                self.assertIn("materially verifies a key claim", normalized)

    def test_review_and_revision_are_comprehensive_but_bounded(self) -> None:
        director = pitch_prompt_catalog[
            "pitch-director"
        ].template_path.read_text(encoding="utf-8")
        reviewer = pitch_prompt_catalog[
            "pitch-reviewer"
        ].template_path.read_text(encoding="utf-8")
        reviewer_normalized = " ".join(reviewer.split())
        self.assertIn("one bounded consistency pass", director)
        self.assertIn("remaining limitation", director)
        self.assertIn("one comprehensive content review", reviewer_normalized)
        self.assertIn(
            "Do not hold an issue for a later review",
            reviewer_normalized,
        )
        self.assertIn("`RUN_MODE` is `VERIFICATION`", reviewer_normalized)
        self.assertIn(
            "verify only that every required change was applied",
            reviewer_normalized,
        )

    def test_rendered_prompt_points_at_the_copied_tree(self) -> None:
        rendered = pitch_prompt_catalog.render(
            "pitch-director",
            (
                ("RUN_MODE", "INITIAL"),
                ("PROJECT_SNAPSHOT", "/pitch/input/project"),
                ("IDEA_CARD", "# Idea\n\nTruth"),
                ("HACKATHON_CHALLENGE", "# Challenge\n\nShip"),
            ),
        )
        self.assertIn("/pitch/input/project", rendered.text)
        self.assertIn("# Idea\n\nTruth", rendered.text)
        self.assertIn("# Challenge\n\nShip", rendered.text)


if __name__ == "__main__":
    unittest.main()
