import importlib
import subprocess
import sys
import unittest


class CompatibilityImportTests(unittest.TestCase):
    def test_old_shared_module_paths_alias_canonical_implementations(self) -> None:
        for old, canonical in (
            ("hacksome.codex", "hacksome.core.codex"),
            ("hacksome.config", "hacksome.core.config"),
            ("hacksome.hub", "hacksome.core.hub"),
            ("hacksome.prompting", "hacksome.core.prompting"),
            ("hacksome.routes", "hacksome.core.routes"),
            ("hacksome.state", "hacksome.core.state"),
            (
                "hacksome.workflow",
                "hacksome.stages.ideation.useful.workflow",
            ),
        ):
            self.assertIs(
                importlib.import_module(old),
                importlib.import_module(canonical),
            )

    def test_old_stage_module_paths_alias_canonical_implementations(self) -> None:
        for old, canonical in (
            (
                "hacksome.creative.workflow",
                "hacksome.stages.ideation.creative.workflow",
            ),
            (
                "hacksome.creative.prompting",
                "hacksome.stages.ideation.creative.prompting",
            ),
            ("hacksome.pitch.workflow", "hacksome.stages.pitch.workflow"),
        ):
            self.assertIs(
                importlib.import_module(old),
                importlib.import_module(canonical),
            )

    def test_package_submodule_aliases_work_in_fresh_interpreter(self) -> None:
        script = """
import importlib
pairs = (
    ("hacksome.creative.workflow", "hacksome.stages.ideation.creative.workflow"),
    ("hacksome.creative.prompting", "hacksome.stages.ideation.creative.prompting"),
    ("hacksome.pitch.workflow", "hacksome.stages.pitch.workflow"),
    ("hacksome.pitch.prompting", "hacksome.stages.pitch.prompting"),
)
for old_name, canonical_name in pairs:
    old = importlib.import_module(old_name)
    canonical = importlib.import_module(canonical_name)
    if old is not canonical:
        raise SystemExit(f"{old_name} did not alias {canonical_name}")
"""
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
