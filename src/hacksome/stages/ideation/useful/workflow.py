"""Seven-step Useful Idea workflow with Prompt-injected context."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

from hacksome.stages.ideation.useful.artifacts import (
    IDEA_HEADINGS,
    PROBLEM_HEADINGS,
    ArtifactError,
    compose_idea_card,
    compose_idea_index,
    title_of,
    validate_markdown,
)
from hacksome.core.codex import CodexRunner
from hacksome.core.config import CodexConfig
from hacksome.core.hub import RunHub
from hacksome.core.models import CodexResult, CodexTask
from hacksome.core.prompting import PromptCatalog, useful_prompt_catalog
from hacksome.core.routes import inspect_run as inspect_saved_run
from hacksome.core.routes import validate_run as validate_saved_run
from hacksome.core.task_executor import AgentTaskExecutionError, AgentTaskExecutor


class WorkflowError(RuntimeError):
    """The run cannot safely continue."""


class Runner(Protocol):
    async def run(self, task: CodexTask) -> CodexResult: ...


@dataclass(frozen=True, slots=True)
class WorkflowSettings:
    max_audiences: int = 5
    researchers_per_audience: int = 1
    idea_generators_per_problem: int = 3
    task_timeout_seconds: float = 20 * 60
    run_timeout_seconds: float = 6 * 60 * 60

    def __post_init__(self) -> None:
        if isinstance(self.max_audiences, bool) or not 1 <= self.max_audiences <= 5:
            raise ValueError("max_audiences must be between 1 and 5")
        for name in ("researchers_per_audience", "idea_generators_per_problem"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be at least 1")
        for name in ("task_timeout_seconds", "run_timeout_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class Audience:
    audience_id: str
    name: str
    description: str
    artifact_ref: str


@dataclass(frozen=True, slots=True)
class Problem:
    problem_id: str
    artifact_ref: str
    audience: Audience
    research_refs: tuple[str, ...]
    gateway_ref: str | None = None
    gateway_task_id: str | None = None


@dataclass(frozen=True, slots=True)
class Idea:
    idea_id: str
    artifact_ref: str
    problem: Problem
    generator_task_id: str
    red_team_ref: str | None = None
    red_team_task_id: str | None = None


class UsefulIdeaWorkflow:
    """Orchestrate one new run. Run-level resume is intentionally absent."""

    def __init__(
        self,
        hub: RunHub,
        runner: Runner,
        *,
        settings: WorkflowSettings | None = None,
        prompt_catalog: PromptCatalog | None = None,
    ) -> None:
        self.hub = hub
        self.runner = runner
        self.settings = settings or WorkflowSettings()
        selected_catalog = prompt_catalog or useful_prompt_catalog
        self.task_executor = AgentTaskExecutor(
            hub,
            runner,
            selected_catalog,
            task_timeout_seconds=self.settings.task_timeout_seconds,
            semantic_validator=self._validate_task_output,
        )

    @property
    def run_dir(self) -> Path:
        return self.hub.run_dir

    @classmethod
    def create(
        cls,
        challenge: str,
        runs_dir: str | Path,
        *,
        settings: WorkflowSettings | None = None,
        codex_config: CodexConfig | None = None,
        run_id: str | None = None,
        runner: Runner | None = None,
    ) -> "UsefulIdeaWorkflow":
        selected_settings = settings or WorkflowSettings()
        selected_config = codex_config or CodexConfig()
        hub = RunHub.create(
            challenge,
            runs_dir,
            settings=asdict(selected_settings),
            codex_config=selected_config,
            run_id=run_id,
        )
        frozen = useful_prompt_catalog.freeze(
            hub.run_dir,
            route_id="useful",
            contract_version="1",
            prompt_policy_version="1",
            stage_policy_version="1",
        )
        hub.set_resource_manifest(frozen.manifest_reference())
        return cls(
            hub,
            runner or CodexRunner(selected_config),
            settings=selected_settings,
            prompt_catalog=frozen.catalog,
        )

    async def execute(self) -> Path:
        stage = "challenge-parse"
        self.hub.set_run_status("running", stage=stage)
        try:
            async with asyncio.timeout(self.settings.run_timeout_seconds):
                challenge_ref = await self._parse_challenge()
                stage = "audience-expand"
                self.hub.set_run_status("running", stage=stage)
                audiences = await self._expand_audiences(challenge_ref)

                stage = "audience-research"
                self.hub.set_run_status("running", stage=stage)
                research = await self._research_audiences(challenge_ref, audiences)

                stage = "problem-write"
                self.hub.set_run_status("running", stage=stage)
                problems = await self._write_problems(challenge_ref, audiences, research)

                stage = "problem-gateway"
                self.hub.set_run_status("running", stage=stage)
                passed_problems = await self._gate_problems(challenge_ref, problems)

                stage = "idea-generate"
                self.hub.set_run_status("running", stage=stage)
                ideas = await self._generate_ideas(challenge_ref, passed_problems)

                stage = "idea-red-team"
                self.hub.set_run_status("running", stage=stage)
                passed_ideas = await self._red_team_ideas(challenge_ref, ideas)

                stage = "idea-card-validate"
                self.hub.set_run_status("running", stage=stage)
                index = self._publish_idea_cards(passed_ideas)
        except TimeoutError as exc:
            self.hub.set_run_status("failed", stage=stage)
            raise WorkflowError("workflow exceeded the run timeout") from exc
        except Exception as exc:
            self.hub.set_run_status("failed", stage=stage)
            if isinstance(exc, WorkflowError):
                raise
            raise WorkflowError(str(exc)) from exc
        self.hub.set_run_status("completed", stage=None)
        return index

    async def _parse_challenge(self) -> str:
        output = await self._call(
            stage="challenge-parse",
            task_id="challenge-parse",
            blocks=(("ORIGINAL_CHALLENGE", self.hub.challenge()),),
            parent_refs=(),
        )
        markdown = _markdown(output)
        validate_markdown(markdown, label="Challenge Brief")
        if title_of(markdown) != "Challenge Brief":
            raise ArtifactError("Challenge Brief H1 must be exactly 'Challenge Brief'")
        return self.hub.publish_artifact(
            artifact_id="challenge-brief",
            artifact_type="challenge_brief",
            relative_path="artifacts/challenge/challenge-brief.md",
            content=markdown,
            task_id="challenge-parse",
        )

    async def _expand_audiences(self, challenge_ref: str) -> list[Audience]:
        output = await self._call(
            stage="audience-expand",
            task_id="audience-expand",
            blocks=(
                ("CHALLENGE_BRIEF", self.hub.read_artifact(challenge_ref)),
                ("LIMITS", f"Maximum Audience count: {self.settings.max_audiences}"),
            ),
            parent_refs=(challenge_ref,),
        )
        raw = output.get("audiences")
        if not isinstance(raw, list):
            raise WorkflowError("audience-expand output has no audiences array")
        if len(raw) > self.settings.max_audiences:
            raise WorkflowError(
                f"Audience output exceeds limit {self.settings.max_audiences}"
            )
        audiences: list[Audience] = []
        index_rows: list[dict[str, str]] = []
        for number, item in enumerate(raw, start=1):
            if not isinstance(item, dict):
                raise WorkflowError("Audience item must be an object")
            name = _nonempty(item.get("name"), "Audience name")
            description = _nonempty(item.get("description"), "Audience description")
            audience_id = f"audience-{number:03d}"
            markdown = f"# Audience: {name}\n\n{description}\n"
            artifact_ref = self.hub.publish_artifact(
                artifact_id=audience_id,
                artifact_type="audience",
                relative_path=f"artifacts/audiences/{audience_id}.md",
                content=markdown,
                task_id="audience-expand",
                source_refs=(challenge_ref,),
                metadata={"name": name, "description": description},
            )
            audiences.append(Audience(audience_id, name, description, artifact_ref))
            index_rows.append(
                {"audience_id": audience_id, "name": name, "description": description}
            )
        self.hub.publish_artifact(
            artifact_id="audience-index",
            artifact_type="audience_index",
            relative_path="artifacts/audiences/audiences.json",
            content=json.dumps(
                {"audiences": index_rows}, ensure_ascii=False, indent=2, sort_keys=True
            ) + "\n",
            task_id="audience-expand",
            source_refs=tuple(a.artifact_ref for a in audiences),
        )
        return audiences

    async def _research_audiences(
        self, challenge_ref: str, audiences: Sequence[Audience]
    ) -> dict[str, tuple[str, ...]]:
        calls: list[tuple[Audience, int, Any]] = []
        for audience in audiences:
            for researcher_number in range(1, self.settings.researchers_per_audience + 1):
                task_id = (
                    f"research-{audience.audience_id}-r{researcher_number:02d}"
                )
                calls.append(
                    (
                        audience,
                        researcher_number,
                        self._call(
                            stage="audience-research",
                            task_id=task_id,
                            blocks=(
                                ("CHALLENGE_BRIEF", self.hub.read_artifact(challenge_ref)),
                                ("AUDIENCE", self.hub.read_artifact(audience.artifact_ref)),
                            ),
                            parent_refs=(challenge_ref, audience.artifact_ref),
                        ),
                    )
                )
        outputs = await asyncio.gather(*(call[2] for call in calls))
        by_audience: dict[str, list[str]] = {a.audience_id: [] for a in audiences}
        for (audience, researcher_number, _), output in zip(calls, outputs, strict=True):
            markdown = _markdown(output)
            validate_markdown(markdown, label="Research")
            artifact_id = f"research-{audience.audience_id}-r{researcher_number:02d}"
            self.hub.publish_artifact(
                artifact_id=artifact_id,
                artifact_type="research",
                relative_path=f"artifacts/research/{artifact_id}.md",
                content=markdown,
                task_id=artifact_id,
                source_refs=(challenge_ref, audience.artifact_ref),
                metadata={"audience_id": audience.audience_id},
            )
            by_audience[audience.audience_id].append(artifact_id)
        return {key: tuple(value) for key, value in by_audience.items()}

    async def _write_problems(
        self,
        challenge_ref: str,
        audiences: Sequence[Audience],
        research: dict[str, tuple[str, ...]],
    ) -> list[Problem]:
        calls: list[tuple[Audience, tuple[str, ...], Any]] = []
        for audience in audiences:
            refs = research[audience.audience_id]
            blocks: list[tuple[str, str]] = [
                ("CHALLENGE_BRIEF", self.hub.read_artifact(challenge_ref)),
                ("AUDIENCE", self.hub.read_artifact(audience.artifact_ref)),
            ]
            blocks.extend(
                (f"RESEARCH_{number:03d}", self.hub.read_artifact(ref))
                for number, ref in enumerate(refs, start=1)
            )
            task_id = f"problem-write-{audience.audience_id}"
            calls.append(
                (
                    audience,
                    refs,
                    self._call(
                        stage="problem-write",
                        task_id=task_id,
                        blocks=tuple(blocks),
                        parent_refs=(challenge_ref, audience.artifact_ref, *refs),
                    ),
                )
            )
        outputs = await asyncio.gather(*(call[2] for call in calls))
        problems: list[Problem] = []
        for (audience, refs, _), output in zip(calls, outputs, strict=True):
            for number, candidate in enumerate(_candidates(output), start=1):
                markdown = _candidate_markdown(candidate, "Problem", PROBLEM_HEADINGS)
                problem_id = f"{audience.audience_id}-problem-{number:03d}"
                artifact_ref = self.hub.publish_artifact(
                    artifact_id=problem_id,
                    artifact_type="problem",
                    relative_path=(
                        f"artifacts/problems/{audience.audience_id}/{problem_id}.md"
                    ),
                    content=markdown,
                    task_id=f"problem-write-{audience.audience_id}",
                    source_refs=(audience.artifact_ref, *refs),
                    metadata={"audience_id": audience.audience_id},
                )
                problems.append(Problem(problem_id, artifact_ref, audience, refs))
        return problems

    async def _gate_problems(
        self, challenge_ref: str, problems: Sequence[Problem]
    ) -> list[Problem]:
        calls: list[tuple[Problem, str, Any]] = []
        for problem in problems:
            task_id = f"problem-gateway-{problem.problem_id}"
            blocks: list[tuple[str, str]] = [
                ("CHALLENGE_BRIEF", self.hub.read_artifact(challenge_ref)),
                ("AUDIENCE", self.hub.read_artifact(problem.audience.artifact_ref)),
            ]
            blocks.extend(
                (f"RESEARCH_{number:03d}", self.hub.read_artifact(ref))
                for number, ref in enumerate(problem.research_refs, start=1)
            )
            blocks.append(("PROBLEM", self.hub.read_artifact(problem.artifact_ref)))
            calls.append(
                (
                    problem,
                    task_id,
                    self._call(
                        stage="problem-gateway",
                        task_id=task_id,
                        blocks=tuple(blocks),
                        parent_refs=(problem.artifact_ref, *problem.research_refs),
                    ),
                )
            )
        outputs = await asyncio.gather(*(call[2] for call in calls))
        passed: list[Problem] = []
        for (problem, task_id, _), output in zip(calls, outputs, strict=True):
            decision, review = _review(output)
            review_ref = f"problem-review-{problem.problem_id}"
            self.hub.publish_artifact(
                artifact_id=review_ref,
                artifact_type="problem_review",
                relative_path=f"artifacts/problem-reviews/{review_ref}.md",
                content=review,
                task_id=task_id,
                source_refs=(problem.artifact_ref,),
                metadata={"decision": decision},
            )
            self.hub.record_decision(
                decision_id=f"decision-{review_ref}",
                gate="problem-gateway",
                candidate_ref=problem.artifact_ref,
                decision=decision,
                review_ref=review_ref,
                task_id=task_id,
            )
            if decision == "pass":
                passed.append(
                    Problem(
                        problem.problem_id,
                        problem.artifact_ref,
                        problem.audience,
                        problem.research_refs,
                        review_ref,
                        task_id,
                    )
                )
        return passed

    async def _generate_ideas(
        self, challenge_ref: str, problems: Sequence[Problem]
    ) -> list[Idea]:
        calls: list[tuple[Problem, int, str, Any]] = []
        for problem in problems:
            gateway_ref = problem.gateway_ref
            assert gateway_ref is not None
            for generator_number in range(1, self.settings.idea_generators_per_problem + 1):
                task_id = f"idea-generate-{problem.problem_id}-g{generator_number:02d}"
                blocks: list[tuple[str, str]] = [
                    ("CHALLENGE_BRIEF", self.hub.read_artifact(challenge_ref)),
                    ("AUDIENCE", self.hub.read_artifact(problem.audience.artifact_ref)),
                ]
                blocks.extend(
                    (f"RESEARCH_{number:03d}", self.hub.read_artifact(ref))
                    for number, ref in enumerate(problem.research_refs, start=1)
                )
                blocks.extend(
                    (
                        ("PASSED_PROBLEM", self.hub.read_artifact(problem.artifact_ref)),
                    )
                )
                calls.append(
                    (
                        problem,
                        generator_number,
                        task_id,
                        self._call(
                            stage="idea-generate",
                            task_id=task_id,
                            blocks=tuple(blocks),
                            parent_refs=(problem.artifact_ref, gateway_ref),
                        ),
                    )
                )
        outputs = await asyncio.gather(*(call[3] for call in calls))
        ideas: list[Idea] = []
        for (problem, generator_number, task_id, _), output in zip(
            calls, outputs, strict=True
        ):
            current_gateway_ref = problem.gateway_ref
            assert current_gateway_ref is not None
            for number, candidate in enumerate(_candidates(output), start=1):
                markdown = _candidate_markdown(candidate, "Idea", IDEA_HEADINGS)
                idea_id = (
                    f"{problem.problem_id}-g{generator_number:02d}-idea-{number:03d}"
                )
                artifact_ref = self.hub.publish_artifact(
                    artifact_id=idea_id,
                    artifact_type="idea",
                    relative_path=(
                        f"artifacts/ideas/{problem.problem_id}/g{generator_number:02d}/"
                        f"{idea_id}.md"
                    ),
                    content=markdown,
                    task_id=task_id,
                    source_refs=(problem.artifact_ref, current_gateway_ref),
                    metadata={
                        "problem_id": problem.problem_id,
                        "generator_number": generator_number,
                    },
                )
                ideas.append(Idea(idea_id, artifact_ref, problem, task_id))
        return ideas

    async def _red_team_ideas(
        self, challenge_ref: str, ideas: Sequence[Idea]
    ) -> list[Idea]:
        calls: list[tuple[Idea, str, Any]] = []
        for idea in ideas:
            gateway_ref = idea.problem.gateway_ref
            assert gateway_ref is not None
            task_id = f"idea-red-team-{idea.idea_id}"
            calls.append(
                (
                    idea,
                    task_id,
                    self._call(
                        stage="idea-red-team",
                        task_id=task_id,
                        blocks=(
                            ("CHALLENGE_BRIEF", self.hub.read_artifact(challenge_ref)),
                            ("AUDIENCE", self.hub.read_artifact(idea.problem.audience.artifact_ref)),
                            ("PASSED_PROBLEM", self.hub.read_artifact(idea.problem.artifact_ref)),
                            ("GATEWAY_REVIEW", self.hub.read_artifact(gateway_ref)),
                            ("IDEA", self.hub.read_artifact(idea.artifact_ref)),
                        ),
                        parent_refs=(idea.problem.artifact_ref, gateway_ref, idea.artifact_ref),
                    ),
                )
            )
        outputs = await asyncio.gather(*(call[2] for call in calls))
        passed: list[Idea] = []
        for (idea, task_id, _), output in zip(calls, outputs, strict=True):
            decision, review = _review(output)
            review_ref = f"idea-review-{idea.idea_id}"
            self.hub.publish_artifact(
                artifact_id=review_ref,
                artifact_type="idea_review",
                relative_path=f"artifacts/idea-reviews/{review_ref}.md",
                content=review,
                task_id=task_id,
                source_refs=(idea.artifact_ref,),
                metadata={"decision": decision},
            )
            self.hub.record_decision(
                decision_id=f"decision-{review_ref}",
                gate="idea-red-team",
                candidate_ref=idea.artifact_ref,
                decision=decision,
                review_ref=review_ref,
                task_id=task_id,
            )
            if decision == "pass":
                passed.append(
                    Idea(
                        idea.idea_id,
                        idea.artifact_ref,
                        idea.problem,
                        idea.generator_task_id,
                        review_ref,
                        task_id,
                    )
                )
        return passed

    def _publish_idea_cards(self, ideas: Sequence[Idea]) -> Path:
        card_ids: list[str] = []
        index_rows: list[dict[str, str]] = []
        state = self.hub.load_state()
        tasks = state.get("tasks", {})
        if not isinstance(tasks, dict):
            raise WorkflowError("run tasks are not an object")
        for idea in ideas:
            assert idea.red_team_ref is not None
            assert idea.red_team_task_id is not None
            generator_task = tasks.get(idea.generator_task_id, {})
            red_team_task = tasks.get(idea.red_team_task_id, {})
            if not isinstance(generator_task, dict) or not isinstance(red_team_task, dict):
                raise WorkflowError(f"missing task lineage for {idea.idea_id}")
            idea_markdown = self.hub.read_artifact(idea.artifact_ref)
            review_markdown = self.hub.read_artifact(idea.red_team_ref)
            card_id = f"idea-card-{idea.idea_id}"
            card = compose_idea_card(
                idea_markdown=idea_markdown,
                review_markdown=review_markdown,
                lineage={
                    "idea_id": idea.idea_id,
                    "idea_ref": idea.artifact_ref,
                    "problem_ref": idea.problem.artifact_ref,
                    "problem_gateway_ref": idea.problem.gateway_ref,
                    "generator_task_id": idea.generator_task_id,
                    "generator_session_id": generator_task.get("session_id"),
                    "red_team_ref": idea.red_team_ref,
                    "red_team_task_id": idea.red_team_task_id,
                    "red_team_session_id": red_team_task.get("session_id"),
                },
            )
            self.hub.publish_artifact(
                artifact_id=card_id,
                artifact_type="idea_card",
                relative_path=f"artifacts/idea-cards/{card_id}.md",
                content=card,
                task_id=None,
                source_refs=(idea.artifact_ref, idea.problem.artifact_ref, idea.red_team_ref),
                metadata={"idea_id": idea.idea_id},
            )
            card_ids.append(card_id)
            index_rows.append(
                {
                    "idea_id": idea.idea_id,
                    "title": title_of(idea_markdown),
                    "relative_path": f"{card_id}.md",
                }
            )
        index = compose_idea_index(index_rows)
        self.hub.publish_artifact(
            artifact_id="idea-card-index",
            artifact_type="idea_card_index",
            relative_path="artifacts/idea-cards/index.md",
            content=index,
            task_id=None,
            source_refs=tuple(card_ids),
        )
        self.hub.set_idea_cards(card_ids)
        return self.hub.run_dir / "artifacts" / "idea-cards" / "index.md"

    async def _call(
        self,
        *,
        stage: str,
        task_id: str,
        blocks: Sequence[tuple[str, str]],
        parent_refs: Sequence[str],
    ) -> dict[str, Any]:
        try:
            return await self.task_executor.execute(
                stage=stage,
                task_id=task_id,
                blocks=blocks,
                parent_refs=parent_refs,
            )
        except AgentTaskExecutionError as exc:
            raise WorkflowError(str(exc)) from exc

    def _validate_task_output(self, stage: str, output: dict[str, Any]) -> None:
        if stage == "challenge-parse":
            markdown = _markdown(output)
            validate_markdown(markdown, label="Challenge Brief")
            if title_of(markdown) != "Challenge Brief":
                raise ArtifactError(
                    "Challenge Brief H1 must be exactly 'Challenge Brief'"
                )
            return
        if stage == "audience-expand":
            raw = output.get("audiences")
            if not isinstance(raw, list):
                raise WorkflowError("audience-expand output has no audiences array")
            if len(raw) > self.settings.max_audiences:
                raise WorkflowError(
                    f"Audience output exceeds limit {self.settings.max_audiences}"
                )
            for item in raw:
                if not isinstance(item, dict):
                    raise WorkflowError("Audience item must be an object")
                _nonempty(item.get("name"), "Audience name")
                _nonempty(item.get("description"), "Audience description")
            return
        if stage == "audience-research":
            validate_markdown(_markdown(output), label="Research")
            return
        if stage == "problem-write":
            for candidate in _candidates(output):
                _candidate_markdown(candidate, "Problem", PROBLEM_HEADINGS)
            return
        if stage == "problem-gateway":
            _review(output)
            return
        if stage == "idea-generate":
            for candidate in _candidates(output):
                _candidate_markdown(candidate, "Idea", IDEA_HEADINGS)
            return
        if stage == "idea-red-team":
            _review(output)
            return
        raise WorkflowError(f"unsupported workflow stage: {stage}")


def inspect_run(run_dir: str | Path) -> dict[str, Any]:
    return inspect_saved_run(run_dir)


def validate_run(run_dir: str | Path) -> list[str]:
    return validate_saved_run(run_dir)


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowError(f"{label} must be a non-empty string")
    return value.strip()


def _markdown(output: dict[str, Any]) -> str:
    return _nonempty(output.get("markdown"), "markdown")


def _candidates(output: dict[str, Any]) -> list[dict[str, Any]]:
    raw = output.get("candidates")
    if not isinstance(raw, list):
        raise WorkflowError("candidate output has no candidates array")
    candidates: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise WorkflowError("candidate must be an object")
        candidates.append(item)
    return candidates


def _candidate_markdown(
    candidate: dict[str, Any], label: str, headings: Sequence[str]
) -> str:
    markdown = _nonempty(candidate.get("markdown"), f"{label} markdown")
    validate_markdown(markdown, required_h2=headings, label=label)
    return markdown


def _review(output: dict[str, Any]) -> tuple[str, str]:
    decision = output.get("decision")
    if decision not in {"pass", "reject"}:
        raise WorkflowError("review decision must be pass or reject")
    markdown = _nonempty(output.get("markdown"), "review markdown")
    validate_markdown(markdown, label="Review")
    return decision, markdown
