from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from hacksome.codex import CodexRunner
from hacksome.config import CodexConfig
from hacksome.models import (
    CodexLogs,
    CodexResult,
    CodexRunStatus,
    CodexTask,
)
from hacksome.pitch.workflow import (
    PITCH_MODEL,
    PITCH_REASONING_EFFORT,
    ChromiumBrowserVerifier,
    PitchWorkflow,
    PitchWorkflowError,
    validate_html_contract,
    validate_outline,
    validate_review,
    validate_script,
)


OUTLINE = """\
# Deck Outline: Snapshot Product

## Slide s01 — Hook

Purpose: Show the completed product.

On-slide:
- Snapshot Product

Visual:
- Real product screen

## Slide s02 — Demo

Purpose: Demonstrate the real workflow.

On-slide:
- One action, real result

Visual:
- Live demo from the copied Project
"""

HTML = """\
<!doctype html>
<html>
<head>
<style>
html, body { margin: 0; overflow: hidden; }
.stage { width: 100vw; height: 100vh; aspect-ratio: 16 / 9; overflow: hidden; }
.slide { display: none; }
.slide.active { display: block; }
</style>
</head>
<body>
<main class="stage">
  <section class="slide active" id="s01" data-slide-id="s01">Hook</section>
  <section class="slide" id="s02" data-slide-id="s02">Demo</section>
</main>
<script>
const slides = [...document.querySelectorAll(".slide")];
let current = 0;
function show(index) {
  current = Math.max(0, Math.min(index, slides.length - 1));
  slides.forEach((slide, position) => {
    slide.classList.toggle("active", position === current);
  });
}
document.addEventListener("keydown", (event) => {
  if (["ArrowRight", "PageDown", "Space", " "].includes(event.key)) {
    show(current + 1);
  } else if (["ArrowLeft", "PageUp"].includes(event.key)) {
    show(current - 1);
  } else if (event.key === "Home") {
    show(0);
  } else if (event.key === "End") {
    show(slides.length - 1);
  }
});
</script>
</body>
</html>
"""

SCRIPT = """\
# Pitch Script

## Slide s01

Here is the completed product.

## Slide s02

Now let me show the real workflow.
"""


class _FakeBrowser:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, tuple[str, ...]]] = []

    def verify(self, html_path: Path, slide_ids: Sequence[str]) -> str:
        self.calls.append((html_path, tuple(slide_ids)))
        return "fake-chromium"

    def executable_path(self) -> str:
        return "/fake/bin/chromium"


class _FakeRunner:
    def __init__(
        self,
        reviews: tuple[str, ...] = ("PASS",),
        *,
        omit_outline: bool = False,
    ) -> None:
        self.reviews = reviews
        self.omit_outline = omit_outline
        self.tasks: list[CodexTask] = []

    async def run(self, task: CodexTask) -> CodexResult:
        self.tasks.append(task)
        output: dict[str, object]
        session_id: str
        if task.task_id == "pitch-director":
            if not self.omit_outline:
                (task.cwd / "deck-outline.md").write_text(OUTLINE, encoding="utf-8")
            output = {"status": "completed", "artifact": "deck-outline.md"}
            session_id = "director-session"
        elif task.task_id == "pitch-director-revision-1":
            self._assert_resume(task)
            (task.cwd / "deck-outline.md").write_text(
                OUTLINE.replace("Show the completed", "Accurately show the completed"),
                encoding="utf-8",
            )
            output = {"status": "completed", "artifact": "deck-outline.md"}
            session_id = "director-session"
        elif task.task_id.startswith("pitch-review-"):
            attempt = int(task.task_id.rsplit("-", 1)[1])
            if attempt == 2:
                if not task.resume or task.session_id != "review-session-1":
                    raise AssertionError(
                        "Reviewer verification did not resume its session"
                    )
            verdict = self.reviews[attempt - 1]
            issues: list[dict[str, str]] = []
            if verdict == "PASS":
                markdown = "# Outline Review\n\nVerdict: PASS\n"
            else:
                issues = [
                    {
                        "slide_id": "s01",
                        "problem": "Claim needs tighter evidence.",
                        "required_change": "Tie the claim to the completed flow.",
                    }
                ]
                markdown = (
                    "# Outline Review\n\nVerdict: REVISE\n\n## Issues\n\n"
                    "- Slide: s01\n"
                    "  Problem: Claim needs tighter evidence.\n"
                    "  Required change: Tie the claim to the completed flow.\n"
                )
            (task.cwd / "outline-review.md").write_text(markdown, encoding="utf-8")
            output = {
                "verdict": verdict,
                "artifact": "outline-review.md",
                "issues": issues,
            }
            session_id = "review-session-1"
        elif task.task_id == "pitch-html":
            (task.cwd / "pitch-deck.html").write_text(HTML, encoding="utf-8")
            output = {
                "status": "completed",
                "artifact": "pitch-deck.html",
                "browser_check": {
                    "opened": True,
                    "keyboard_navigation": True,
                    "checked_slide_ids": ["s01", "s02"],
                },
            }
            session_id = "html-session"
        elif task.task_id == "pitch-script":
            (task.cwd / "pitch-script.md").write_text(SCRIPT, encoding="utf-8")
            output = {"status": "completed", "artifact": "pitch-script.md"}
            session_id = "script-session"
        else:
            raise AssertionError(f"unexpected task: {task.task_id}")
        return _result(task, session_id=session_id, output=output)

    def _assert_resume(self, task: CodexTask) -> None:
        if not task.resume or task.session_id != "director-session":
            raise AssertionError("Director revision did not resume its session")


class _ReusedHtmlSessionRunner(_FakeRunner):
    async def run(self, task: CodexTask) -> CodexResult:
        result = await super().run(task)
        if task.task_id == "pitch-html":
            return replace(result, session_id="director-session")
        return result


def _result(
    task: CodexTask,
    *,
    session_id: str,
    output: dict[str, object],
) -> CodexResult:
    log_dir = task.log_dir or task.cwd / "raw"
    log_dir.mkdir(parents=True, exist_ok=True)
    logs = CodexLogs(
        stdout=log_dir / "stdout.jsonl",
        stderr=log_dir / "stderr.jsonl",
        last_message=log_dir / "last-message.json",
    )
    return CodexResult(
        task_id=task.task_id,
        status=CodexRunStatus.SUCCEEDED,
        session_id=session_id,
        structured_output=output,
        usage={"input_tokens": 1, "output_tokens": 1},
        logs=logs,
        error=None,
        returncode=0,
        attempts=1,
        started_at="2026-07-24T00:00:00Z",
        finished_at="2026-07-24T00:00:01Z",
        duration_seconds=1.0,
    )


class PitchWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "live-project"
        (self.project / "src" / "nested").mkdir(parents=True)
        (self.project / "README.md").write_text("# Real Product\n", encoding="utf-8")
        (self.project / "src" / "nested" / "proof.txt").write_text(
            "snapshot bytes\n",
            encoding="utf-8",
        )
        self.idea_card = self.root / "idea-card.md"
        self.idea_card.write_text("# Idea Card\n\nBuild the real thing.\n", encoding="utf-8")
        self.challenge = self.root / "challenge.md"
        self.challenge.write_text("# Challenge\n\nHelp users.\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_workflow(
        self,
        runner: _FakeRunner,
        browser: _FakeBrowser,
        *,
        name: str = "pitch-run",
    ) -> PitchWorkflow:
        return PitchWorkflow.create(
            self.project,
            self.idea_card,
            self.challenge,
            self.root / name,
            runner=runner,
            browser_verifier=browser,
        )

    async def test_pass_path_copies_snapshot_runs_four_roles_and_publishes(self) -> None:
        runner = _FakeRunner()
        browser = _FakeBrowser()
        workflow = self.create_workflow(runner, browser)
        snapshot_proof = workflow.project_snapshot / "src" / "nested" / "proof.txt"
        self.assertEqual(snapshot_proof.read_text(encoding="utf-8"), "snapshot bytes\n")

        (self.project / "src" / "nested" / "proof.txt").write_text(
            "live mutation\n",
            encoding="utf-8",
        )
        outcome = await workflow.execute()

        self.assertEqual(snapshot_proof.read_text(encoding="utf-8"), "snapshot bytes\n")
        self.assertEqual(
            [task.task_id for task in runner.tasks],
            ["pitch-director", "pitch-review-1", "pitch-html", "pitch-script"],
        )
        snapshot_path = str(workflow.project_snapshot.resolve())
        live_path = str(self.project.resolve())
        for task in runner.tasks:
            self.assertIn(snapshot_path, task.prompt)
            self.assertNotIn(live_path, task.prompt)
            self.assertFalse(task.web_search)
        self.assertIn(
            "/fake/bin/chromium",
            next(task.prompt for task in runner.tasks if task.task_id == "pitch-html"),
        )
        self.assertEqual(outcome.deck_outline.read_text(encoding="utf-8"), OUTLINE)
        self.assertEqual(outcome.pitch_deck.read_text(encoding="utf-8"), HTML)
        self.assertEqual(outcome.pitch_script.read_text(encoding="utf-8"), SCRIPT)
        self.assertEqual(browser.calls[0][1], ("s01", "s02"))

        manifest = json.loads(
            (workflow.run_dir / "pitch-run.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(manifest["model"], PITCH_MODEL)
        self.assertEqual(manifest["reasoning_effort"], PITCH_REASONING_EFFORT)
        self.assertTrue(manifest["browser_smoke"]["opened"])
        self.assertEqual(
            {task["model"] for task in manifest["tasks"]},
            {PITCH_MODEL},
        )

    async def test_revise_resumes_original_director_and_reviewer_once(self) -> None:
        runner = _FakeRunner(("REVISE", "PASS"))
        workflow = self.create_workflow(runner, _FakeBrowser(), name="revised")

        await workflow.execute()

        self.assertEqual(
            [task.task_id for task in runner.tasks],
            [
                "pitch-director",
                "pitch-review-1",
                "pitch-director-revision-1",
                "pitch-review-2",
                "pitch-html",
                "pitch-script",
            ],
        )
        revision = runner.tasks[2]
        self.assertTrue(revision.resume)
        self.assertEqual(revision.session_id, "director-session")
        self.assertFalse(runner.tasks[1].resume)
        self.assertTrue(runner.tasks[3].resume)
        self.assertEqual(runner.tasks[3].session_id, "review-session-1")
        manifest = json.loads(
            (workflow.run_dir / "pitch-run.json").read_text(encoding="utf-8")
        )
        reviewer_sessions = [
            task["session_id"]
            for task in manifest["tasks"]
            if task["stage"] == "pitch-reviewer"
        ]
        self.assertEqual(reviewer_sessions, ["review-session-1", "review-session-1"])

    async def test_second_revise_fails_closed_without_publication(self) -> None:
        workflow = self.create_workflow(
            _FakeRunner(("REVISE", "REVISE")),
            _FakeBrowser(),
            name="bounded-failure",
        )
        with self.assertRaisesRegex(PitchWorkflowError, "bounded retry"):
            await workflow.execute()
        self.assertEqual(list((workflow.run_dir / "output").iterdir()), [])
        manifest = json.loads(
            (workflow.run_dir / "pitch-run.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["status"], "failed")

    async def test_missing_director_artifact_stops_before_review(self) -> None:
        runner = _FakeRunner(omit_outline=True)
        workflow = self.create_workflow(
            runner,
            _FakeBrowser(),
            name="missing-outline",
        )
        with self.assertRaisesRegex(PitchWorkflowError, "deck outline is missing"):
            await workflow.execute()
        self.assertEqual([task.task_id for task in runner.tasks], ["pitch-director"])

    async def test_role_boundary_rejects_reused_session(self) -> None:
        workflow = self.create_workflow(
            _ReusedHtmlSessionRunner(),
            _FakeBrowser(),
            name="reused-session",
        )
        with self.assertRaisesRegex(PitchWorkflowError, "fresh independent session"):
            await workflow.execute()
        self.assertEqual(list((workflow.run_dir / "output").iterdir()), [])

    def test_pitch_runtime_is_pinned_independent_of_idea_defaults(self) -> None:
        workflow = PitchWorkflow.create(
            self.project,
            self.idea_card,
            self.challenge,
            self.root / "config-pin",
            codex_config=CodexConfig(
                model="gpt-5.6-terra",
                reasoning_effort="high",
                max_concurrency=4,
                sandbox="read-only",
            ),
        )
        self.assertIsInstance(workflow.runner, CodexRunner)
        assert isinstance(workflow.runner, CodexRunner)
        self.assertEqual(workflow.runner.config.model, PITCH_MODEL)
        self.assertEqual(
            workflow.runner.config.reasoning_effort,
            PITCH_REASONING_EFFORT,
        )
        self.assertEqual(workflow.runner.config.max_concurrency, 1)
        self.assertEqual(workflow.runner.config.sandbox, "workspace-write")
        task = CodexTask(
            task_id="pitch-argv-proof",
            prompt="proof",
            cwd=workflow.run_dir / "director",
            output_schema=workflow.catalog["pitch-director"].schema_path,
        )
        command = workflow.runner._build_command(
            task=task,
            cwd=task.cwd,
            schema=task.output_schema,
            last_message=workflow.run_dir / "argv-last-message.json",
            resume=False,
            session_id=None,
        )
        self.assertIn("--model", command)
        self.assertEqual(command[command.index("--model") + 1], PITCH_MODEL)
        self.assertIn(
            f'model_reasoning_effort="{PITCH_REASONING_EFFORT}"',
            command,
        )

    def test_rejects_output_inside_project_before_copying(self) -> None:
        destination = self.project / "pitch"
        with self.assertRaisesRegex(PitchWorkflowError, "live inside"):
            PitchWorkflow.create(
                self.project,
                self.idea_card,
                self.challenge,
                destination,
                runner=_FakeRunner(),
                browser_verifier=_FakeBrowser(),
            )
        self.assertFalse(destination.exists())

    def test_snapshot_preserves_internal_relative_tool_symlink(self) -> None:
        package = self.project / "node_modules" / "vitest"
        binary = self.project / "node_modules" / ".bin"
        package.mkdir(parents=True)
        binary.mkdir()
        (package / "vitest.mjs").write_text(
            'import "./dist/cli.js";\n',
            encoding="utf-8",
        )
        link = binary / "vitest"
        link.symlink_to("../vitest/vitest.mjs")

        workflow = self.create_workflow(
            _FakeRunner(),
            _FakeBrowser(),
            name="symlink-snapshot",
        )

        snapshot_link = (
            workflow.project_snapshot / "node_modules" / ".bin" / "vitest"
        )
        self.assertTrue(snapshot_link.is_symlink())
        self.assertEqual(snapshot_link.readlink(), Path("../vitest/vitest.mjs"))
        self.assertTrue(snapshot_link.resolve().is_relative_to(workflow.project_snapshot))
        self.assertEqual(
            snapshot_link.read_text(encoding="utf-8"),
            'import "./dist/cli.js";\n',
        )

    def test_snapshot_rejects_symlink_that_escapes_project(self) -> None:
        external = self.root / "external-secret.txt"
        external.write_text("outside\n", encoding="utf-8")
        (self.project / "escape").symlink_to(external)
        destination = self.root / "escaping-snapshot"

        with self.assertRaisesRegex(PitchWorkflowError, "escapes"):
            PitchWorkflow.create(
                self.project,
                self.idea_card,
                self.challenge,
                destination,
                runner=_FakeRunner(),
                browser_verifier=_FakeBrowser(),
            )

        self.assertFalse(destination.exists())


class PitchContractTests(unittest.TestCase):
    def test_outline_html_and_script_contracts(self) -> None:
        ids = validate_outline(OUTLINE)
        self.assertEqual(ids, ("s01", "s02"))
        self.assertEqual(validate_html_contract(HTML, ids), ids)
        validate_script(SCRIPT, ids)

    def test_html_contract_accepts_equivalent_fixed_16_by_9_stage(self) -> None:
        html = HTML.replace(
            "width: 100vw; height: 100vh; aspect-ratio: 16 / 9;",
            "width: 1600px; height: 900px;",
        )
        self.assertEqual(
            validate_html_contract(html, ("s01", "s02")),
            ("s01", "s02"),
        )

    def test_html_rejects_id_drift_and_external_resources(self) -> None:
        with self.assertRaisesRegex(PitchWorkflowError, "IDs/order"):
            validate_html_contract(HTML.replace('id="s02"', 'id="s03"'), ("s01", "s02"))
        external = HTML.replace(
            "</head>",
            '<link rel="stylesheet" href="https://example.com/theme.css"></head>',
        )
        with self.assertRaisesRegex(PitchWorkflowError, "external"):
            validate_html_contract(external, ("s01", "s02"))

    def test_script_rejects_missing_or_reordered_slides(self) -> None:
        with self.assertRaisesRegex(PitchWorkflowError, "IDs/order"):
            validate_script(SCRIPT.replace("## Slide s02", "## Slide s03"), ("s01", "s02"))

    def test_review_file_issues_must_match_structured_result(self) -> None:
        review = """\
# Outline Review

Verdict: REVISE

## Issues

- Slide: s01
  Problem: File problem.
  Required change: File correction.
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outline-review.md"
            path.write_text(review, encoding="utf-8")
            with self.assertRaisesRegex(PitchWorkflowError, "exactly match"):
                validate_review(
                    path,
                    {
                        "verdict": "REVISE",
                        "artifact": "outline-review.md",
                        "issues": [
                            {
                                "slide_id": "s01",
                                "problem": "Different structured problem.",
                                "required_change": "File correction.",
                            }
                        ],
                    },
                    ("s01", "s02"),
                )

    def test_real_chromium_opens_and_renders_deck_when_available(self) -> None:
        verifier = ChromiumBrowserVerifier()
        try:
            verifier._resolve_executable()
        except PitchWorkflowError:
            self.skipTest("no local Chromium-family browser")
        with tempfile.TemporaryDirectory() as directory:
            html_path = Path(directory) / "pitch-deck.html"
            html_path.write_text(HTML, encoding="utf-8")
            browser_name = verifier.verify(html_path, ("s01", "s02"))
        self.assertTrue(browser_name)

    def test_real_chromium_rejects_navigation_that_does_not_move_when_available(
        self,
    ) -> None:
        verifier = ChromiumBrowserVerifier()
        try:
            verifier._resolve_executable()
        except PitchWorkflowError:
            self.skipTest("no local Chromium-family browser")
        broken_html = HTML.replace("show(current + 1);", "void current;")
        with tempfile.TemporaryDirectory() as directory:
            html_path = Path(directory) / "pitch-deck.html"
            html_path.write_text(broken_html, encoding="utf-8")
            with self.assertRaisesRegex(PitchWorkflowError, "ArrowRight"):
                verifier.verify(html_path, ("s01", "s02"))


if __name__ == "__main__":
    unittest.main()
