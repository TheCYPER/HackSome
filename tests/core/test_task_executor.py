from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from hacksome.core.models import (
    CodexError,
    CodexFailureKind,
    CodexLogs,
    CodexResult,
    CodexRunStatus,
    CodexTask,
)
from hacksome.core.prompting import PromptCatalog, PromptSpec
from hacksome.core.task_executor import (
    AgentTaskExecutionError,
    AgentTaskExecutor,
    OPTIONAL_BRANCH_FAILURE_POLICY,
)


class RecordingHub:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.begin_calls: list[dict[str, Any]] = []
        self.finished: list[CodexResult] = []
        self.failed: list[tuple[str, BaseException]] = []
        self.invalidated: list[tuple[str, BaseException]] = []
        self.events: list[str] = []

    def begin_task(
        self,
        *,
        task_id: str,
        stage: str,
        prompt: str,
        prompt_metadata: dict[str, str],
        output_schema: Path,
        web_search: bool,
        parent_refs: tuple[str, ...],
        failure_policy: str = "fatal",
    ) -> SimpleNamespace:
        self.begin_calls.append(
            {
                "task_id": task_id,
                "stage": stage,
                "prompt": prompt,
                "prompt_metadata": prompt_metadata,
                "output_schema": output_schema,
                "web_search": web_search,
                "parent_refs": parent_refs,
                "failure_policy": failure_policy,
            }
        )
        root = self.root / task_id
        workspace = root / "workspace"
        raw = root / "raw"
        workspace.mkdir(parents=True)
        raw.mkdir()
        self.events.append("begin")
        return SimpleNamespace(workspace=workspace, raw=raw)

    def finish_task(self, result: CodexResult) -> None:
        self.finished.append(result)
        self.events.append("finish")

    def fail_task(self, task_id: str, error: BaseException) -> None:
        self.failed.append((task_id, error))
        self.events.append("fail")

    def invalidate_task(self, task_id: str, error: BaseException) -> None:
        self.invalidated.append((task_id, error))
        self.events.append("invalidate")


class ScriptedRunner:
    def __init__(
        self,
        output: dict[str, Any] | None = None,
        *,
        error: BaseException | None = None,
        result_status: CodexRunStatus = CodexRunStatus.SUCCEEDED,
    ) -> None:
        self.output = output or {"value": "ok"}
        self.error = error
        self.result_status = result_status
        self.tasks: list[CodexTask] = []

    async def run(self, task: CodexTask) -> CodexResult:
        self.tasks.append(task)
        if self.error is not None:
            raise self.error
        assert task.log_dir is not None
        runner_error = None
        if self.result_status is not CodexRunStatus.SUCCEEDED:
            runner_error = CodexError(
                kind=CodexFailureKind.NON_ZERO_EXIT,
                message="runner rejected task",
                retryable=False,
                returncode=2,
            )
        return CodexResult(
            task_id=task.task_id,
            status=self.result_status,
            session_id="session-1",
            structured_output=self.output,
            usage={},
            logs=CodexLogs(
                stdout=task.log_dir / "stdout.jsonl",
                stderr=task.log_dir / "stderr.jsonl",
                last_message=task.log_dir / "last-message.json",
            ),
            error=runner_error,
            returncode=0 if runner_error is None else 2,
            attempts=1,
            started_at="2026-07-23T00:00:00+00:00",
            finished_at="2026-07-23T00:00:01+00:00",
            duration_seconds=1.0,
        )


class AgentTaskExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        template = self.root / "prompt.md"
        schema = self.root / "schema.json"
        template.write_text("# Test task\n", encoding="utf-8")
        schema.write_text('{"type":"object"}\n', encoding="utf-8")
        self.catalog = PromptCatalog(
            (
                PromptSpec(
                    stage="required-stage",
                    template_id="test.required",
                    version="1",
                    template_path=template,
                    schema_path=schema,
                    web_search=True,
                ),
                PromptSpec(
                    stage="creative-memory-recall",
                    template_id="test.recall",
                    version="1",
                    template_path=template,
                    schema_path=schema,
                ),
                PromptSpec(
                    stage="creative-memory-remix",
                    template_id="test.remix",
                    version="1",
                    template_path=template,
                    schema_path=schema,
                ),
            )
        )

    def executor(
        self,
        hub: RecordingHub,
        runner: ScriptedRunner,
        validator: Any,
        *,
        optional_branch_stages: tuple[str, ...] = (),
    ) -> AgentTaskExecutor:
        return AgentTaskExecutor(
            cast(Any, hub),
            runner,
            self.catalog,
            task_timeout_seconds=30,
            semantic_validator=validator,
            optional_branch_stages=optional_branch_stages,
        )

    async def test_success_uses_catalog_policy_and_fixed_lifecycle_order(self) -> None:
        hub = RecordingHub(self.root)
        runner = ScriptedRunner({"value": "accepted"})

        def validate(stage: str, output: dict[str, Any]) -> None:
            self.assertEqual(stage, "required-stage")
            self.assertEqual(output, {"value": "accepted"})
            hub.events.append("validate")

        executor = self.executor(hub, runner, validate)
        output = await executor.execute(
            stage="required-stage",
            task_id="task-1",
            blocks=(("CONTEXT", "exact context"),),
            parent_refs=("artifact-1",),
        )

        self.assertEqual(output, {"value": "accepted"})
        self.assertEqual(hub.events, ["begin", "finish", "validate"])
        self.assertEqual(hub.begin_calls[0]["failure_policy"], "fatal")
        self.assertTrue(hub.begin_calls[0]["web_search"])
        self.assertEqual(hub.begin_calls[0]["parent_refs"], ("artifact-1",))
        self.assertEqual(
            hub.begin_calls[0]["prompt_metadata"]["template_id"], "test.required"
        )
        self.assertTrue(runner.tasks[0].web_search)
        self.assertEqual(runner.tasks[0].timeout_seconds, 30)
        self.assertEqual(runner.tasks[0].output_schema, self.root / "schema.json")

    async def test_runner_exception_is_persisted_as_failed(self) -> None:
        hub = RecordingHub(self.root)
        runner = ScriptedRunner(error=RuntimeError("network unavailable"))
        executor = self.executor(hub, runner, lambda _stage, _output: None)

        with self.assertRaisesRegex(
            AgentTaskExecutionError, "failed before returning.*network unavailable"
        ) as raised:
            await executor.execute(
                stage="required-stage",
                task_id="task-2",
                blocks=(("CONTEXT", "value"),),
                parent_refs=(),
            )

        self.assertEqual(raised.exception.failure_policy, "fatal")
        self.assertEqual(hub.events, ["begin", "fail"])
        self.assertEqual(hub.failed[0][0], "task-2")
        self.assertEqual(hub.finished, [])

    async def test_cancel_is_persisted_and_reraised(self) -> None:
        hub = RecordingHub(self.root)
        runner = ScriptedRunner(error=asyncio.CancelledError())
        executor = self.executor(hub, runner, lambda _stage, _output: None)

        with self.assertRaises(asyncio.CancelledError):
            await executor.execute(
                stage="required-stage",
                task_id="task-3",
                blocks=(("CONTEXT", "value"),),
                parent_refs=(),
            )

        self.assertEqual(hub.events, ["begin", "fail"])
        self.assertIsInstance(hub.failed[0][1], asyncio.CancelledError)

    async def test_unsuccessful_result_is_finished_then_raised(self) -> None:
        hub = RecordingHub(self.root)
        runner = ScriptedRunner(result_status=CodexRunStatus.FAILED)
        executor = self.executor(hub, runner, lambda _stage, _output: None)

        with self.assertRaisesRegex(AgentTaskExecutionError, "runner rejected task"):
            await executor.execute(
                stage="required-stage",
                task_id="task-4",
                blocks=(("CONTEXT", "value"),),
                parent_refs=(),
            )

        self.assertEqual(hub.events, ["begin", "finish"])
        self.assertEqual(hub.finished[0].status, CodexRunStatus.FAILED)

    async def test_semantic_failure_invalidates_finished_task(self) -> None:
        hub = RecordingHub(self.root)
        runner = ScriptedRunner()

        def reject(_stage: str, _output: dict[str, Any]) -> None:
            hub.events.append("validate")
            raise ValueError("missing required heading")

        executor = self.executor(hub, runner, reject)
        with self.assertRaisesRegex(
            AgentTaskExecutionError, "returned invalid content.*required heading"
        ):
            await executor.execute(
                stage="required-stage",
                task_id="task-5",
                blocks=(("CONTEXT", "value"),),
                parent_refs=(),
            )

        self.assertEqual(hub.events, ["begin", "finish", "validate", "invalidate"])
        self.assertEqual(hub.invalidated[0][0], "task-5")

    async def test_optional_branch_requires_explicit_route_allowlist(self) -> None:
        hub = RecordingHub(self.root)
        executor = self.executor(
            hub,
            ScriptedRunner(),
            lambda _stage, _output: None,
            optional_branch_stages=("creative-memory-recall",),
        )

        await executor.execute(
            stage="creative-memory-recall",
            task_id="recall",
            blocks=(("CONTEXT", "value"),),
            parent_refs=(),
            failure_policy=OPTIONAL_BRANCH_FAILURE_POLICY,
        )
        self.assertEqual(hub.begin_calls[0]["failure_policy"], "optional_branch")

        with self.assertRaisesRegex(ValueError, "not allowlisted"):
            await executor.execute(
                stage="creative-memory-remix",
                task_id="remix",
                blocks=(("CONTEXT", "value"),),
                parent_refs=(),
                failure_policy=OPTIONAL_BRANCH_FAILURE_POLICY,
            )

    def test_optional_route_allowlist_is_globally_bounded(self) -> None:
        hub = RecordingHub(self.root)
        with self.assertRaisesRegex(ValueError, "unsupported optional branch stage"):
            self.executor(
                hub,
                ScriptedRunner(),
                lambda _stage, _output: None,
                optional_branch_stages=("required-stage",),
            )


if __name__ == "__main__":
    unittest.main()
