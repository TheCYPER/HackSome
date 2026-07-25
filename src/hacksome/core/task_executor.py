"""Shared execution lifecycle for route-owned Agent tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Sequence
from typing import Any, Literal, Protocol

from hacksome.core.hub import RunHub
from hacksome.core.models import CodexResult, CodexTask
from hacksome.core.prompting import PromptCatalog


FailurePolicy = Literal["fatal", "optional_branch"]
SemanticValidator = Callable[[str, dict[str, Any]], None]

FATAL_FAILURE_POLICY: FailurePolicy = "fatal"
OPTIONAL_BRANCH_FAILURE_POLICY: FailurePolicy = "optional_branch"
OPTIONAL_BRANCH_STAGE_ALLOWLIST = frozenset(
    {
        "creative-cultural-signal-scan",
        "creative-memory-recall",
        "creative-memory-remix",
    }
)


class Runner(Protocol):
    async def run(self, task: CodexTask) -> CodexResult: ...


class AgentTaskExecutionError(RuntimeError):
    """A persisted Agent task failed or returned semantically invalid output."""

    def __init__(
        self,
        message: str,
        *,
        task_id: str,
        stage: str,
        failure_policy: FailurePolicy,
    ) -> None:
        super().__init__(message)
        self.task_id = task_id
        self.stage = stage
        self.failure_policy = failure_policy


class AgentTaskExecutor:
    """Execute one Agent task without owning route progression or gate policy."""

    def __init__(
        self,
        hub: RunHub,
        runner: Runner,
        catalog: PromptCatalog,
        *,
        task_timeout_seconds: float,
        semantic_validator: SemanticValidator,
        optional_branch_stages: Iterable[str] = (),
    ) -> None:
        if (
            isinstance(task_timeout_seconds, bool)
            or not isinstance(task_timeout_seconds, (int, float))
            or task_timeout_seconds <= 0
        ):
            raise ValueError("task_timeout_seconds must be positive")
        selected_optional_stages = frozenset(optional_branch_stages)
        unsupported = selected_optional_stages - OPTIONAL_BRANCH_STAGE_ALLOWLIST
        if unsupported:
            rendered = ", ".join(sorted(unsupported))
            raise ValueError(f"unsupported optional branch stage: {rendered}")
        missing = selected_optional_stages - frozenset(catalog.stages())
        if missing:
            rendered = ", ".join(sorted(missing))
            raise ValueError(f"optional branch stage is not in prompt catalog: {rendered}")

        self.hub = hub
        self.runner = runner
        self.catalog = catalog
        self.task_timeout_seconds = float(task_timeout_seconds)
        self.semantic_validator = semantic_validator
        self.optional_branch_stages = selected_optional_stages

    async def execute(
        self,
        *,
        stage: str,
        task_id: str,
        blocks: Sequence[tuple[str, str]],
        parent_refs: Sequence[str],
        failure_policy: FailurePolicy = FATAL_FAILURE_POLICY,
    ) -> dict[str, Any]:
        self._validate_failure_policy(stage, failure_policy)
        spec = self.catalog.lookup(stage)
        rendered = self.catalog.render(stage, blocks)
        paths = self.hub.begin_task(
            task_id=task_id,
            stage=stage,
            prompt=rendered.text,
            prompt_metadata=rendered.metadata(),
            output_schema=spec.schema_path,
            web_search=spec.web_search,
            parent_refs=parent_refs,
            failure_policy=failure_policy,
        )
        task = CodexTask(
            task_id=task_id,
            prompt=rendered.text,
            cwd=paths.workspace,
            output_schema=spec.schema_path,
            web_search=spec.web_search,
            timeout_seconds=self.task_timeout_seconds,
            log_dir=paths.raw,
        )
        try:
            result = await self.runner.run(task)
        except asyncio.CancelledError as exc:
            self.hub.fail_task(task_id, exc)
            raise
        except Exception as exc:
            self.hub.fail_task(task_id, exc)
            raise AgentTaskExecutionError(
                f"{task_id} failed before returning a result: {exc}",
                task_id=task_id,
                stage=stage,
                failure_policy=failure_policy,
            ) from exc

        self.hub.finish_task(result)
        if not result.success:
            message = result.error.message if result.error is not None else result.status.value
            raise AgentTaskExecutionError(
                f"{task_id} failed: {message}",
                task_id=task_id,
                stage=stage,
                failure_policy=failure_policy,
            )

        try:
            self.semantic_validator(stage, result.structured_output)
        except Exception as exc:
            self.hub.invalidate_task(task_id, exc)
            raise AgentTaskExecutionError(
                f"{task_id} returned invalid content: {exc}",
                task_id=task_id,
                stage=stage,
                failure_policy=failure_policy,
            ) from exc
        return result.structured_output

    def _validate_failure_policy(
        self,
        stage: str,
        failure_policy: FailurePolicy,
    ) -> None:
        if failure_policy not in {
            FATAL_FAILURE_POLICY,
            OPTIONAL_BRANCH_FAILURE_POLICY,
        }:
            raise ValueError(f"unsupported failure policy: {failure_policy!r}")
        if (
            failure_policy == OPTIONAL_BRANCH_FAILURE_POLICY
            and stage not in self.optional_branch_stages
        ):
            raise ValueError(
                f"stage {stage!r} is not allowlisted for optional_branch failure"
            )
