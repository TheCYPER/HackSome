from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import UTC, datetime
from typing import Any

from hacksome.stages.ideation.useful.artifacts import IDEA_HEADINGS, PROBLEM_HEADINGS
from hacksome.core.config import CodexConfig
from hacksome.core.models import CodexLogs, CodexResult, CodexRunStatus, CodexTask
from hacksome.stages.ideation.useful.workflow import UsefulIdeaWorkflow, WorkflowError, WorkflowSettings, validate_run


def _sections(headings: tuple[str, ...], value: str) -> str:
    return "\n\n".join(f"## {heading}\n\n{value}" for heading in headings)


def _problem(title: str) -> dict[str, str]:
    return {
        "markdown": f"# {title}\n\n{_sections(PROBLEM_HEADINGS, 'supported')}\n",
    }


def _idea(title: str) -> dict[str, str]:
    return {
        "markdown": f"# {title}\n\n{_sections(IDEA_HEADINGS, 'complete')}\n",
    }


class ScriptedRunner:
    def __init__(
        self,
        *,
        empty_audiences: bool = False,
        too_many: bool = False,
        zero_problems: bool = False,
        zero_ideas: bool = False,
        reject_all_ideas: bool = False,
        malformed_problem: bool = False,
    ) -> None:
        self.empty_audiences = empty_audiences
        self.too_many = too_many
        self.zero_problems = zero_problems
        self.zero_ideas = zero_ideas
        self.reject_all_ideas = reject_all_ideas
        self.malformed_problem = malformed_problem
        self.tasks: list[CodexTask] = []
        self.active = 0
        self.max_active = 0

    async def run(self, task: CodexTask) -> CodexResult:
        self.tasks.append(task)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if task.task_id.startswith("research-"):
                await asyncio.sleep(0.03)
            output = self._output(task.task_id)
            assert task.log_dir is not None
            task.log_dir.mkdir(parents=True, exist_ok=True)
            stdout = task.log_dir / "stdout.jsonl"
            stderr = task.log_dir / "stderr.jsonl"
            last = task.log_dir / "last-message.attempt-001.json"
            stdout.write_text('{"event":{"type":"turn.completed"}}\n', encoding="utf-8")
            stderr.write_text("", encoding="utf-8")
            last.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
            now = datetime.now(UTC).isoformat()
            return CodexResult(
                task_id=task.task_id,
                status=CodexRunStatus.SUCCEEDED,
                session_id=f"session-{task.task_id}",
                structured_output=output,
                usage={"input_tokens": 1, "output_tokens": 1},
                logs=CodexLogs(stdout=stdout, stderr=stderr, last_message=last),
                error=None,
                returncode=0,
                attempts=1,
                started_at=now,
                finished_at=now,
                duration_seconds=0.01,
            )
        finally:
            self.active -= 1

    def _output(self, task_id: str) -> dict[str, Any]:
        if task_id == "challenge-parse":
            return {"markdown": "# Challenge Brief\n\nBuild something useful.\n"}
        if task_id == "audience-expand":
            if self.empty_audiences:
                return {"audiences": []}
            count = 6 if self.too_many else 2
            return {
                "audiences": [
                    {"name": f"Group {number}", "description": f"Broad group {number}"}
                    for number in range(1, count + 1)
                ]
            }
        if task_id.startswith("research-"):
            return {
                "markdown": (
                    f"# Research {task_id}\n\nObserved pain. "
                    "Source: https://reddit.com/example and https://github.com/example\n"
                )
            }
        if task_id == "problem-write-audience-001":
            if self.zero_problems:
                return {"candidates": []}
            if self.malformed_problem:
                broken = _problem("Broken Problem")
                broken["markdown"] = broken["markdown"].replace(
                    "## Why It Matters", "## Missing"
                )
                return {"candidates": [broken]}
            return {"candidates": [_problem("Real Problem"), _problem("Weak Problem")]}
        if task_id == "problem-write-audience-002":
            return {"candidates": []}
        if task_id.endswith("problem-001") and task_id.startswith("problem-gateway"):
            return {"decision": "pass", "markdown": "# Gateway Review\n\nSupported.\n"}
        if task_id.endswith("problem-002") and task_id.startswith("problem-gateway"):
            return {"decision": "reject", "markdown": "# Gateway Review\n\nToo weak.\n"}
        if task_id.startswith("idea-generate-"):
            if self.zero_ideas:
                return {"candidates": []}
            if task_id.endswith("g03"):
                return {"candidates": [_idea("External-Action Idea")]}
            return {"candidates": [_idea("Similar Useful Idea")]}
        if task_id.startswith("idea-red-team-"):
            rejected = self.reject_all_ideas or "g03-idea-001" in task_id
            return {
                "decision": "reject" if rejected else "pass",
                "markdown": (
                    "# Red Team Review\n\n"
                    + ("Value depends on another actor.\n" if rejected else "User feels the delivered value.\n")
                ),
            }
        raise AssertionError(f"unexpected task: {task_id}")


class ExplodingRunner(ScriptedRunner):
    async def run(self, task: CodexTask) -> CodexResult:
        if task.task_id.startswith("research-"):
            raise RuntimeError("network unavailable")
        return await super().run(task)


class SlowRunner(ScriptedRunner):
    async def run(self, task: CodexTask) -> CodexResult:
        await asyncio.sleep(1)
        return await super().run(task)


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_e2e_parallel_prompt_transport_gates_and_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = ScriptedRunner()
            workflow = UsefulIdeaWorkflow.create(
                "Original challenge text",
                directory,
                settings=WorkflowSettings(),
                codex_config=CodexConfig(),
                run_id="e2e",
                runner=runner,
            )
            index = await workflow.execute()

            state = workflow.hub.load_state()
            self.assertEqual(state["schema_version"], 2)
            self.assertEqual(state["route"]["id"], "useful")
            self.assertEqual(state["status"], "completed")
            self.assertTrue(index.is_file())
            self.assertEqual(len(state["idea_card_ids"]), 2)
            self.assertGreaterEqual(runner.max_active, 2)
            manifest = state["resource_manifest"]
            self.assertEqual(manifest["path"], "resources/manifest.json")
            self.assertTrue(
                (workflow.run_dir / manifest["path"]).is_file()
            )

            research_tasks = [task for task in runner.tasks if task.task_id.startswith("research-")]
            self.assertEqual(len(research_tasks), 2)
            self.assertTrue(all(task.web_search for task in research_tasks))
            self.assertTrue(
                all(
                    not task.web_search
                    for task in runner.tasks
                    if not task.task_id.startswith("research-")
                )
            )

            generator_tasks = [
                task for task in runner.tasks if task.task_id.startswith("idea-generate-")
            ]
            self.assertEqual(len(generator_tasks), 3)
            red_team_tasks = [
                task for task in runner.tasks if task.task_id.startswith("idea-red-team-")
            ]
            self.assertEqual(len(red_team_tasks), 3)
            self.assertEqual(
                len({f"session-{task.task_id}" for task in red_team_tasks}), 3
            )

            problem_text = workflow.hub.read_artifact("audience-001-problem-001")
            idea_prompt = generator_tasks[0].prompt
            self.assertIn(problem_text, idea_prompt)
            self.assertNotIn("artifacts/problems/", idea_prompt)
            gateway_review = workflow.hub.read_artifact(
                "problem-review-audience-001-problem-001"
            )
            self.assertNotIn(gateway_review, idea_prompt)
            self.assertNotIn("GATEWAY_REVIEW", idea_prompt)

            decisions = workflow.hub.decisions_path.read_text(encoding="utf-8")
            self.assertIn('"decision": "reject"', decisions)
            self.assertIn('"decision": "pass"', decisions)

            for task_id, record in state["tasks"].items():
                task_root = workflow.run_dir / "tasks" / task_id
                for name in ("request.json", "prompt.md", "result.json", "output.json"):
                    self.assertTrue((task_root / name).is_file(), (task_id, name))
                self.assertTrue((task_root / "raw" / "stdout.jsonl").is_file())
                self.assertTrue((task_root / "raw" / "stderr.jsonl").is_file())
                self.assertEqual(record["session_id"], f"session-{task_id}")
                request = json.loads(
                    (task_root / "request.json").read_text(encoding="utf-8")
                )
                expected_schema = (
                    "audiences.schema.json"
                    if record["stage"] == "audience-expand"
                    else "candidates.schema.json"
                    if record["stage"] in {"problem-write", "idea-generate"}
                    else "review.schema.json"
                    if record["stage"] in {"problem-gateway", "idea-red-team"}
                    else "document.schema.json"
                )
                self.assertEqual(
                    request["output_schema"]["name"],
                    expected_schema,
                )

            self.assertEqual(validate_run(workflow.run_dir), [])

    async def test_zero_audiences_produces_valid_empty_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = ScriptedRunner(empty_audiences=True)
            workflow = UsefulIdeaWorkflow.create(
                "Prompt", directory, run_id="empty", runner=runner
            )
            index = await workflow.execute()
            self.assertIn("No Idea passed", index.read_text(encoding="utf-8"))
            self.assertEqual(workflow.hub.load_state()["idea_card_ids"], [])
            self.assertEqual(validate_run(workflow.run_dir), [])

    async def test_zero_problems_ideas_and_passes_each_end_cleanly(self) -> None:
        scenarios = (
            ("zero-problems", {"zero_problems": True}),
            ("zero-ideas", {"zero_ideas": True}),
            ("zero-passes", {"reject_all_ideas": True}),
        )
        for run_id, options in scenarios:
            with self.subTest(run_id=run_id), tempfile.TemporaryDirectory() as directory:
                workflow = UsefulIdeaWorkflow.create(
                    "Prompt",
                    directory,
                    run_id=run_id,
                    runner=ScriptedRunner(**options),
                )
                index = await workflow.execute()
                self.assertIn("No Idea passed", index.read_text(encoding="utf-8"))
                self.assertEqual(workflow.hub.load_state()["idea_card_ids"], [])
                self.assertEqual(validate_run(workflow.run_dir), [])

    async def test_audience_hard_limit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = ScriptedRunner(too_many=True)
            workflow = UsefulIdeaWorkflow.create(
                "Prompt", directory, run_id="too-many", runner=runner
            )
            with self.assertRaisesRegex(WorkflowError, "exceeds limit 5"):
                await workflow.execute()
            self.assertEqual(workflow.hub.load_state()["status"], "failed")

    async def test_runner_exception_is_persisted_and_stops_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = UsefulIdeaWorkflow.create(
                "Prompt", directory, run_id="failure", runner=ExplodingRunner()
            )
            with self.assertRaisesRegex(WorkflowError, "network unavailable"):
                await workflow.execute()
            state = workflow.hub.load_state()
            failed = [task for task in state["tasks"].values() if task["status"] == "failed"]
            self.assertTrue(failed)
            result_path = workflow.run_dir / failed[0]["result_path"]
            self.assertIn("network unavailable", result_path.read_text(encoding="utf-8"))

    async def test_offline_validation_detects_prompt_and_artifact_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = UsefulIdeaWorkflow.create(
                "Prompt",
                directory,
                run_id="tamper",
                runner=ScriptedRunner(empty_audiences=True),
            )
            await workflow.execute()
            prompt = workflow.run_dir / "tasks" / "challenge-parse" / "prompt.md"
            prompt.write_text(prompt.read_text(encoding="utf-8") + "tampered", encoding="utf-8")
            audience_index = workflow.run_dir / "artifacts" / "audiences" / "audiences.json"
            audience_index.write_text("{}\n", encoding="utf-8")
            errors = validate_run(workflow.run_dir)
            self.assertTrue(any("prompt_path hash mismatch" in error for error in errors))
            self.assertTrue(any("audience-index hash mismatch" in error for error in errors))

    async def test_run_timeout_persists_cancelled_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = UsefulIdeaWorkflow.create(
                "Prompt",
                directory,
                run_id="timeout",
                settings=WorkflowSettings(run_timeout_seconds=0.01),
                runner=SlowRunner(),
            )
            with self.assertRaisesRegex(WorkflowError, "run timeout"):
                await workflow.execute()
            state = workflow.hub.load_state()
            self.assertEqual(state["status"], "failed")
            task = state["tasks"]["challenge-parse"]
            self.assertEqual(task["status"], "failed")
            result = workflow.run_dir / task["result_path"]
            self.assertTrue(result.is_file())
            self.assertIn("CancelledError", result.read_text(encoding="utf-8"))

    async def test_invalid_markdown_is_a_failed_task_not_a_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = UsefulIdeaWorkflow.create(
                "Prompt",
                directory,
                run_id="invalid-markdown",
                runner=ScriptedRunner(malformed_problem=True),
            )
            with self.assertRaisesRegex(WorkflowError, "returned invalid content"):
                await workflow.execute()
            task = workflow.hub.load_state()["tasks"]["problem-write-audience-001"]
            self.assertEqual(task["status"], "failed")
            result = json.loads(
                (workflow.run_dir / task["result_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(result["status"], "failed")
            self.assertIn("Why It Matters", result["validation_error"]["message"])
            self.assertTrue((workflow.run_dir / task["output_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
