from __future__ import annotations

import json
import re
import tempfile
import unittest
from dataclasses import replace
from typing import Any

from hacksome.stages.ideation.creative.artifacts import FEEDBACK_REVISION_HEADINGS
from hacksome.stages.ideation.creative.contracts import C6C_FEEDBACK_REVISE
from hacksome.stages.ideation.creative.finalize import (
    CreativeFeedbackError,
)
from hacksome.stages.ideation.creative.review import ReviewBatch, ReviewRound, ReviewStore
from hacksome.stages.ideation.creative.workflow import CreativeIdeaWorkflow
from hacksome.core.routes import validate_run
from hacksome.core.state import read_jsonl

from tests.stages.ideation.creative.test_creative_curation_workflow import (
    CreativeCurationRunner,
)
from tests.stages.ideation.creative.test_creative_review import (
    _action,
    _resolution_payload,
    _review_payload,
)
from tests.stages.ideation.creative.test_creative_workflow import (
    _concept_markdown,
    _settings,
)


class FeedbackCurationRunner(CreativeCurationRunner):
    def __init__(
        self,
        *,
        fail_c6c_source: str | None = None,
        invalid_primary: bool = False,
    ) -> None:
        super().__init__()
        self.fail_c6c_source = fail_c6c_source
        self.invalid_primary = invalid_primary

    async def run(self, task: Any) -> Any:
        if (
            self.fail_c6c_source is not None
            and task.task_id.startswith("creative-c6c-")
            and self.fail_c6c_source in task.task_id
        ):
            raise RuntimeError("feedback revision unavailable")
        return await super().run(task)

    def _output(self, task_id: str) -> dict[str, Any]:
        if task_id.startswith("creative-c6c-"):
            match = re.search(r"-s(?P<slot>[0-9]{2})-", task_id)
            slot = int(match.group("slot")) if match is not None else 1
            markdown = _concept_markdown(slot)
            markdown += "\n".join(
                (
                    f"## {FEEDBACK_REVISION_HEADINGS[0]}",
                    "",
                    "Used only the approved retell to sharpen the reveal.",
                    "",
                    f"## {FEEDBACK_REVISION_HEADINGS[1]}",
                    "",
                    "Did not treat conflicting reactions as a command.",
                    "",
                    f"## {FEEDBACK_REVISION_HEADINGS[2]}",
                    "",
                    "The live room timing still needs rehearsal.",
                    "",
                )
            )
            return {
                "markdown": markdown,
                "primary_territory_ref": (
                    "creative-territory-99"
                    if self.invalid_primary
                    else f"creative-territory-{slot:02d}"
                ),
            }
        return super()._output(task_id)


async def _waiting_workflow(
    directory: str,
    runner: FeedbackCurationRunner,
    *,
    max_feedback_revisions: int = 1,
) -> tuple[CreativeIdeaWorkflow, ReviewRound, ReviewStore]:
    settings = replace(
        _settings(),
        max_feedback_revisions=max_feedback_revisions,
    )
    workflow = CreativeIdeaWorkflow.create(
        "Make a legible interactive surprise.",
        directory,
        settings=settings,
        runner=runner,
    )
    outcome = await workflow.execute()
    batch = ReviewBatch.from_dict(
        json.loads(outcome.primary_artifact.read_text(encoding="utf-8"))
    )
    review_round = ReviewRound.open(batch)
    store = ReviewStore(workflow.hub, review_round)
    store.initialize()
    return workflow, review_round, store


def _approved_concept_feedback(
    store: ReviewStore,
    concept_ref: str,
) -> list[dict[str, str]]:
    fragment = next(
        item
        for item in store.feedback_fragments()
        if item.kind == "concept"
        and item.related_concept_refs == (concept_ref,)
    )
    return [
        {
            "feedback_ref": fragment.feedback_ref,
            "feedback_sha256": fragment.feedback_sha256,
        }
    ]


def _artifacts_of_type(
    workflow: CreativeIdeaWorkflow,
    artifact_type: str,
) -> dict[str, dict[str, Any]]:
    return {
        str(reference): record
        for reference, record in workflow.hub.load_state()["artifacts"].items()
        if record["artifact_type"] == artifact_type
    }


def _dispositions(
    workflow: CreativeIdeaWorkflow,
    *,
    stage: str,
) -> list[dict[str, Any]]:
    return [
        json.loads(workflow.hub.read_artifact(reference))
        for reference in _artifacts_of_type(
            workflow,
            "creative_concept_disposition",
        )
        if json.loads(workflow.hub.read_artifact(reference))["stage"] == stage
    ]


class CreativeFeedbackWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_round_cannot_resume_and_does_not_mutate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = FeedbackCurationRunner()
            workflow, _, _ = await _waiting_workflow(directory, runner)
            before = workflow.hub.load_raw_state()

            with self.assertRaisesRegex(
                CreativeFeedbackError,
                "must be closed",
            ):
                await workflow.resume()

            self.assertEqual(workflow.hub.load_raw_state(), before)
            self.assertFalse(
                any(
                    task.task_id.startswith("creative-c6c-")
                    for task in runner.tasks
                )
            )

    async def test_keep_and_revise_publish_targets_before_terminal_dispositions(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = FeedbackCurationRunner()
            workflow, review_round, store = await _waiting_workflow(
                directory,
                runner,
            )
            store.submit_review(
                _review_payload(
                    review_round,
                    concept_indexes=(0, 1),
                )
            )
            first_ref, second_ref = review_round.bindings
            store.submit_resolution(
                _resolution_payload(
                    review_round,
                    actions=[
                        _action(first_ref, action="keep"),
                        _action(
                            second_ref,
                            action="revise",
                            approved_feedback=_approved_concept_feedback(
                                store,
                                second_ref,
                            ),
                        ),
                    ],
                )
            )

            outcome = await workflow.resume()

            self.assertEqual(outcome.status, "completed")
            self.assertEqual(
                workflow.hub.load_state()["current_stage"],
                "creative-finalization",
            )
            report = json.loads(
                workflow.hub.read_artifact(
                    "creative-idea-report-json"
                )
            )
            self.assertIsNone(report["zero_reason_code"])
            self.assertEqual(
                report["final_idea_card_ids"],
                [
                    "creative-idea-001-card",
                    "creative-idea-002-card",
                ],
            )
            finals = _artifacts_of_type(workflow, "creative_final_idea")
            self.assertEqual(
                set(finals),
                {"creative-idea-001", "creative-idea-002"},
            )
            self.assertEqual(
                workflow.hub.read_artifact("creative-idea-001"),
                workflow.hub.read_artifact(first_ref),
            )
            self.assertIsNone(finals["creative-idea-001"]["task_id"])
            self.assertEqual(
                finals["creative-idea-002"]["metadata"][
                    "primary_territory_ref"
                ],
                "creative-territory-02",
            )
            c6c_tasks = [
                task
                for task in runner.tasks
                if task.task_id.startswith("creative-c6c-")
            ]
            self.assertEqual(len(c6c_tasks), 1)
            self.assertFalse(c6c_tasks[0].web_search)
            self.assertIn(
                "这个 reveal 很清楚",
                c6c_tasks[0].prompt,
            )
            self.assertNotIn(
                "值得继续，但别把神秘感解释得太满",
                c6c_tasks[0].prompt,
            )
            terminal = _dispositions(workflow, stage="C6C")
            self.assertEqual(
                {
                    row["concept_revision_ref"]: (
                        row["outcome"],
                        row["target_ref"],
                    )
                    for row in terminal
                },
                {
                    first_ref: (
                        "promoted_to_final",
                        "creative-idea-001",
                    ),
                    second_ref: (
                        "revised_into",
                        "creative-idea-002",
                    ),
                },
            )
            bindings = _artifacts_of_type(
                workflow,
                "creative_human_feedback_binding",
            )
            self.assertEqual(len(bindings), 2)
            self.assertEqual(validate_run(workflow.run_dir), [])

            # A successful C6C replay is a read-only idempotent result.
            raw_state = workflow.hub.load_raw_state()
            decisions = read_jsonl(workflow.hub.decisions_path)
            replay = await workflow.resume()
            self.assertEqual(replay, outcome)
            self.assertEqual(workflow.hub.load_raw_state(), raw_state)
            self.assertEqual(read_jsonl(workflow.hub.decisions_path), decisions)

    async def test_merge_uses_one_task_and_one_target_for_all_sources(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = FeedbackCurationRunner()
            workflow, review_round, store = await _waiting_workflow(
                directory,
                runner,
            )
            store.submit_review(
                _review_payload(
                    review_round,
                    concept_indexes=(0, 1),
                )
            )
            first_ref, second_ref = review_round.bindings
            group_id = "merge-alpha"
            store.submit_resolution(
                _resolution_payload(
                    review_round,
                    actions=[
                        _action(
                            first_ref,
                            action="merge",
                            curator_instruction="Keep the first interaction rule.",
                            merge_group_id=group_id,
                        ),
                        _action(
                            second_ref,
                            action="merge",
                            approved_feedback=_approved_concept_feedback(
                                store,
                                second_ref,
                            ),
                            merge_group_id=group_id,
                        ),
                    ],
                    merge_groups=[
                        {
                            "merge_group_id": group_id,
                            "source_refs": [first_ref, second_ref],
                            "reason": "The mechanisms form one clearer reveal.",
                        }
                    ],
                )
            )

            outcome = await workflow.resume()

            self.assertEqual(outcome.status, "completed")
            self.assertEqual(
                json.loads(
                    workflow.hub.read_artifact(
                        "creative-idea-report-json"
                    )
                )["final_idea_card_ids"],
                ["creative-idea-001-card"],
            )
            c6c_tasks = [
                task
                for task in runner.tasks
                if task.task_id.startswith("creative-c6c-")
            ]
            self.assertEqual(len(c6c_tasks), 1)
            terminal = _dispositions(workflow, stage="C6C")
            self.assertEqual(len(terminal), 2)
            self.assertEqual(
                {row["outcome"] for row in terminal},
                {"merged_into"},
            )
            self.assertEqual(
                {row["target_ref"] for row in terminal},
                {"creative-idea-001"},
            )
            final_metadata = _artifacts_of_type(
                workflow,
                "creative_final_idea",
            )["creative-idea-001"]["metadata"]
            self.assertEqual(
                final_metadata["source_concept_refs"],
                [first_ref, second_ref],
            )
            self.assertIn(
                final_metadata["primary_territory_ref"],
                {"creative-territory-01", "creative-territory-02"},
            )
            self.assertEqual(validate_run(workflow.run_dir), [])

    async def test_reject_and_taste_veto_never_call_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = FeedbackCurationRunner()
            workflow, review_round, store = await _waiting_workflow(
                directory,
                runner,
            )
            store.submit_review(
                _review_payload(
                    review_round,
                    concept_indexes=(0, 1),
                )
            )
            first_ref, second_ref = review_round.bindings
            store.submit_resolution(
                _resolution_payload(
                    review_round,
                    actions=[
                        _action(first_ref, action="reject"),
                        _action(
                            second_ref,
                            action="taste_veto",
                            reason="The tone is not ours.",
                        ),
                    ],
                )
            )

            before_task_count = len(runner.tasks)
            outcome = await workflow.resume()

            self.assertEqual(len(runner.tasks), before_task_count)
            self.assertEqual(outcome.status, "completed")
            report = json.loads(
                workflow.hub.read_artifact(
                    "creative-idea-report-json"
                )
            )
            self.assertEqual(report["final_idea_card_ids"], [])
            self.assertEqual(
                report["zero_reason_code"],
                "all_human_rejected",
            )
            self.assertFalse(
                _artifacts_of_type(workflow, "creative_final_idea")
            )
            terminal = _dispositions(workflow, stage="C6C")
            self.assertEqual(
                {row["outcome"] for row in terminal},
                {"human_reject", "human_taste_veto"},
            )
            self.assertTrue(
                all(row["target_ref"] is None for row in terminal)
            )
            self.assertEqual(validate_run(workflow.run_dir), [])

    async def test_later_feedback_task_failure_leaves_no_final_or_success_disposition(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = FeedbackCurationRunner(fail_c6c_source="-s02-")
            workflow, review_round, store = await _waiting_workflow(
                directory,
                runner,
            )
            store.submit_review(
                _review_payload(
                    review_round,
                    concept_indexes=(0, 1),
                )
            )
            actions = [
                _action(
                    binding.concept_ref,
                    action="revise",
                    approved_feedback=_approved_concept_feedback(
                        store,
                        binding.concept_ref,
                    ),
                )
                for binding in review_round.concepts
            ]
            store.submit_resolution(
                _resolution_payload(
                    review_round,
                    actions=actions,
                )
            )

            with self.assertRaises(CreativeFeedbackError):
                await workflow.resume()

            self.assertEqual(workflow.hub.load_state()["status"], "failed")
            self.assertFalse(
                _artifacts_of_type(workflow, "creative_final_idea")
            )
            self.assertFalse(_dispositions(workflow, stage="C6C"))
            c6c_tasks = [
                task
                for task in workflow.hub.load_state()["tasks"].values()
                if task["stage"] == C6C_FEEDBACK_REVISE
            ]
            self.assertEqual(len(c6c_tasks), 2)
            self.assertEqual(
                {task["status"] for task in c6c_tasks},
                {"succeeded", "failed"},
            )

    async def test_invalid_primary_territory_fails_before_final_publication(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = FeedbackCurationRunner(invalid_primary=True)
            workflow, review_round, store = await _waiting_workflow(
                directory,
                runner,
            )
            store.submit_review(
                _review_payload(
                    review_round,
                    concept_indexes=(0, 1),
                )
            )
            first_ref, second_ref = review_round.bindings
            store.submit_resolution(
                _resolution_payload(
                    review_round,
                    actions=[
                        _action(first_ref),
                        _action(
                            second_ref,
                            action="revise",
                            approved_feedback=_approved_concept_feedback(
                                store,
                                second_ref,
                            ),
                        ),
                    ],
                )
            )

            with self.assertRaises(CreativeFeedbackError):
                await workflow.resume()

            self.assertFalse(
                _artifacts_of_type(workflow, "creative_final_idea")
            )
            self.assertFalse(_dispositions(workflow, stage="C6C"))
            c6c_task = next(
                task_id
                for task_id, task in workflow.hub.load_state()["tasks"].items()
                if task["stage"] == C6C_FEEDBACK_REVISE
            )
            self.assertEqual(
                workflow.hub.load_state()["tasks"][c6c_task]["status"],
                "failed",
            )

    async def test_disabled_feedback_budget_fails_before_agent_call(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = FeedbackCurationRunner()
            workflow, review_round, store = await _waiting_workflow(
                directory,
                runner,
                max_feedback_revisions=0,
            )
            store.submit_review(
                _review_payload(
                    review_round,
                    concept_indexes=(0, 1),
                )
            )
            first_ref, second_ref = review_round.bindings
            store.submit_resolution(
                _resolution_payload(
                    review_round,
                    actions=[
                        _action(first_ref),
                        _action(
                            second_ref,
                            action="revise",
                            approved_feedback=_approved_concept_feedback(
                                store,
                                second_ref,
                            ),
                        ),
                    ],
                )
            )

            before = len(runner.tasks)
            with self.assertRaises(CreativeFeedbackError):
                await workflow.resume()

            self.assertEqual(len(runner.tasks), before)
            self.assertFalse(
                _artifacts_of_type(workflow, "creative_final_idea")
            )


if __name__ == "__main__":
    unittest.main()
