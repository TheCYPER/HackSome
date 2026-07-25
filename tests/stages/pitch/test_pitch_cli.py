from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from hacksome import cli
from hacksome.core.config import CodexConfig


class _FakePitchWorkflow:
    calls: list[dict[str, object]] = []

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir

    @classmethod
    def create(
        cls,
        project: Path,
        idea_card: Path,
        challenge: Path,
        output_root: Path,
        **kwargs: object,
    ) -> _FakePitchWorkflow:
        cls.calls.append(
            {
                "project": project,
                "idea_card": idea_card,
                "challenge": challenge,
                "output_root": output_root,
                **kwargs,
            }
        )
        return cls(output_root)

    async def execute(self) -> SimpleNamespace:
        output = self.run_dir / "output"
        return SimpleNamespace(
            deck_outline=output / "deck-outline.md",
            pitch_deck=output / "pitch-deck.html",
            pitch_script=output / "pitch-script.md",
        )


class PitchCliTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakePitchWorkflow.calls.clear()

    def invoke(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_pitch_is_an_explicit_command_with_clear_file_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            idea = root / "idea.md"
            idea.write_text("Idea\n", encoding="utf-8")
            challenge = root / "challenge.md"
            challenge.write_text("Challenge\n", encoding="utf-8")
            output = root / "pitch"
            with patch.object(cli, "PitchWorkflow", _FakePitchWorkflow):
                code, stdout, stderr = self.invoke(
                    [
                        "pitch",
                        "--project",
                        str(project),
                        "--idea-card",
                        str(idea),
                        "--challenge",
                        str(challenge),
                        "--output-root",
                        str(output),
                        "--task-timeout",
                        "42",
                        "--infrastructure-retries",
                        "0",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn(f"Pitch run directory: {output}", stdout)
        self.assertIn(f"Pitch deck: {output}/output/pitch-deck.html", stdout)
        call = _FakePitchWorkflow.calls[0]
        self.assertEqual(call["project"], project)
        self.assertEqual(call["idea_card"], idea)
        self.assertEqual(call["challenge"], challenge)
        self.assertEqual(call["output_root"], output)
        self.assertEqual(call["task_timeout_seconds"], 42.0)
        config = cast(CodexConfig, call["codex_config"])
        self.assertEqual(config.infrastructure_retries, 0)
        self.assertEqual(config.model, "gpt-5.6-sol")
        self.assertEqual(config.reasoning_effort, "xhigh")

    def test_pitch_does_not_expose_model_or_reasoning_overrides(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            self.invoke(
                [
                    "pitch",
                    "--project",
                    "project",
                    "--idea-card",
                    "idea.md",
                    "--challenge",
                    "challenge.md",
                    "--output-root",
                    "pitch",
                    "--model",
                    "gpt-5.6-terra",
                ]
            )
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
