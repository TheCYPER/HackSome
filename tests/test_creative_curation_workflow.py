from __future__ import annotations

import json
import re
import tempfile
import unittest
from typing import Any

from hacksome.creative.artifacts import (
    EVIDENCE_REVISION_HEADINGS,
    PORTFOLIO_DIMENSIONS,
)
from hacksome.creative.contracts import C6B_PORTFOLIO_CURATE
from hacksome.creative.prompting import creative_prompt_catalog
from hacksome.creative.workflow import (
    CreativeConcept,
    CreativeIdeaWorkflow,
    CreativeWorkflowError,
    _deterministic_shortlist,
)
from hacksome.prompting import PromptCatalog, PromptSpec
from hacksome.creative.review import ReviewBatch, ReviewRound, ReviewStore
from hacksome.routes import inspect_run, validate_run

from tests.test_creative_workflow import (
    CreativeScriptedRunner,
    _concept_markdown,
    _hook_review,
    _settings,
)
from tests.test_creative_review import (
    _action,
    _resolution_payload,
    _review_payload,
)


class CreativeCurationRunner(CreativeScriptedRunner):
    def __init__(
        self,
        *,
        empty_concepts: bool = False,
        reject_all_hooks: bool = False,
        curator_decisions: tuple[str, str] = ("include", "include"),
        fail_evidence_revision: bool = False,
    ) -> None:
        super().__init__()
        self.empty_concepts = empty_concepts
        self.reject_all_hooks = reject_all_hooks
        self.curator_decisions = curator_decisions
        self.fail_evidence_revision = fail_evidence_revision

    async def run(self, task: Any) -> Any:
        if (
            self.fail_evidence_revision
            and task.task_id.startswith("creative-c6a-evidence-")
        ):
            raise RuntimeError("evidence revision unavailable")
        return await super().run(task)

    def _output(self, task_id: str) -> dict[str, Any]:
        if self.empty_concepts and task_id.startswith(
            "creative-c3-synthesis-"
        ):
            return {"concepts": []}
        if (
            self.reject_all_hooks
            and task_id.startswith("creative-c4-review-")
        ):
            return _hook_review("invalid")
        if task_id.startswith("creative-c6a-evidence-"):
            match = re.search(r"-s(?P<slot>[0-9]{2})-", task_id)
            if match is None:
                raise AssertionError(f"unexpected C6A task ID: {task_id}")
            slot = int(match.group("slot"))
            markdown = _concept_markdown(slot)
            markdown += "\n".join(
                (
                    f"## {EVIDENCE_REVISION_HEADINGS[0]}",
                    "",
                    "Kept the legible mechanism while responding to prior art.",
                    "",
                    f"## {EVIDENCE_REVISION_HEADINGS[1]}",
                    "",
                    "Did not copy the adjacent project's presentation.",
                    "",
                )
            )
            return {"markdown": markdown}
        if task_id.startswith("creative-c6b-portfolio-curator-"):
            slot = int(task_id.rsplit("-", 1)[1])
            prompt = self.tasks[-1].prompt
            refs = sorted(
                set(
                    re.findall(
                        r'"concept_ref": '
                        r'"(creative-concept-(?:s[0-9]{2}-[0-9]{2}|m[0-9]{2})'
                        r'-r[0-9]{3})"',
                        prompt,
                    )
                )
            )
            return {
                "classifications": [
                    {
                        "concept_ref": reference,
                        "decision": self.curator_decisions[slot - 1],
                        "dimensions": [
                            {
                                "dimension": dimension,
                                "verdict": (
                                    "pass"
                                    if self.curator_decisions[slot - 1]
                                    == "include"
                                    else "uncertain"
                                    if self.curator_decisions[slot - 1] == "hold"
                                    else "fail"
                                ),
                                "reason": "Categorical fixture evidence.",
                                "evidence": "The exact Concept supplies this evidence.",
                            }
                            for dimension in PORTFOLIO_DIMENSIONS
                        ],
                        "rationale": "Categorical evidence supports this decision.",
                        "possible_duplicate_refs": [],
                    }
                    for reference in refs
                ]
            }
        return super()._output(task_id)


def _read_artifacts(workflow: CreativeIdeaWorkflow, artifact_type: str) -> list[dict[str, Any]]:
    state = workflow.hub.load_state()
    artifacts = state["artifacts"]
    return [
        json.loads(workflow.hub.read_artifact(artifact_id))
        for artifact_id, record in sorted(artifacts.items())
        if record["artifact_type"] == artifact_type
    ]


def _catalog_with_frozen_v3_curator() -> PromptCatalog:
    return PromptCatalog(
        tuple(
            PromptSpec(
                stage=stage,
                template_id=spec.template_id,
                version=(
                    "3"
                    if stage == C6B_PORTFOLIO_CURATE
                    else spec.version
                ),
                template_path=spec.template_path,
                schema_path=spec.schema_path,
                web_search=spec.web_search,
            )
            for stage in creative_prompt_catalog
            for spec in (creative_prompt_catalog[stage],)
        )
    )


class CreativeCurationWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_empty_shortlist_enters_waiting_after_fixed_c6a_revision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = CreativeCurationRunner()
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                settings=_settings(),
                runner=runner,
            )

            outcome = await workflow.execute()

            self.assertEqual(outcome.status, "waiting")
            self.assertIn("hacksome review", outcome.next_command or "")
            state = workflow.hub.load_state()
            self.assertEqual(state["status"], "waiting")
            self.assertEqual(state["current_stage"], "creative-human-review")
            self.assertEqual(state["wait"]["status"], "open")
            batch = ReviewBatch.from_dict(
                json.loads(
                    outcome.primary_artifact.read_text(encoding="utf-8")
                )
            )
            self.assertEqual(batch.status, "ready")
            self.assertEqual(len(batch.concept_refs), 2)
            review_round = ReviewRound.open(batch)
            self.assertEqual(
                state["wait"]["round_sha256"],
                review_round.round_sha256,
            )
            self.assertEqual(
                state["wait"]["batch_sha256"],
                batch.batch_sha256,
            )
            self.assertEqual(
                state["wait"]["batch_artifact_sha256"],
                state["artifacts"]["creative-review-batch-r001"]["sha256"],
            )
            self.assertEqual(
                {
                    record["metadata"]["revision_reason"]
                    for record in state["artifacts"].values()
                    if record["artifact_type"] == "creative_concept"
                    and record["metadata"]["revision"] == 2
                },
                {"evidence_informed"},
            )
            superseded = [
                row
                for row in _read_artifacts(
                    workflow,
                    "creative_concept_disposition",
                )
                if row["outcome"] == "superseded_by_evidence_revision"
            ]
            self.assertEqual(len(superseded), 2)
            self.assertTrue(
                all(row["target_ref"] in batch.concept_refs for row in superseded)
            )
            c6_tasks = [
                task
                for task in runner.tasks
                if task.task_id.startswith(
                    ("creative-c6a-evidence-", "creative-c6b-portfolio-")
                )
            ]
            self.assertEqual(
                sum(
                    task.task_id.startswith("creative-c6a-evidence-")
                    for task in c6_tasks
                ),
                2,
            )
            self.assertEqual(
                sum(
                    task.task_id.startswith("creative-c6b-portfolio-")
                    for task in c6_tasks
                ),
                2,
            )
            self.assertTrue(all(not task.web_search for task in c6_tasks))
            curator_tasks = sorted(
                (
                    task
                    for task in c6_tasks
                    if task.task_id.startswith(
                        "creative-c6b-portfolio-curator-"
                    )
                ),
                key=lambda task: task.task_id,
            )
            lens_payloads = []
            for task in curator_tasks:
                match = re.search(
                    r"<BEGIN_CURATOR_LENS_[0-9a-f]{12}>\n"
                    r"(?P<payload>.*?)\n"
                    r"<END_CURATOR_LENS_[0-9a-f]{12}>",
                    task.prompt,
                    flags=re.DOTALL,
                )
                self.assertIsNotNone(match)
                assert match is not None
                lens_payloads.append(json.loads(match.group("payload")))
            self.assertEqual(
                [
                    payload["curator_lens_id"]
                    for payload in lens_payloads
                ],
                [
                    "meaning_value_red_team",
                    "hackathon_floor_red_team",
                ],
            )
            self.assertNotEqual(
                lens_payloads[0]["primary_counterevidence_question"],
                lens_payloads[1]["primary_counterevidence_question"],
            )
            curator_metadata = {
                record["metadata"]["curator_slot"]: record["metadata"]
                for record in state["artifacts"].values()
                if record["artifact_type"] == "creative_portfolio_curation"
            }
            self.assertEqual(
                {
                    slot: metadata["curator_lens_id"]
                    for slot, metadata in curator_metadata.items()
                },
                {
                    1: "meaning_value_red_team",
                    2: "hackathon_floor_red_team",
                },
            )
            self.assertEqual(validate_run(workflow.run_dir), [])
            self.assertEqual(
                inspect_run(workflow.run_dir)["review"]["shortlist_count"],
                2,
            )
            store = ReviewStore(workflow.hub, review_round)
            store.initialize()
            store.submit_review(
                _review_payload(
                    review_round,
                    concept_indexes=(0, 1),
                )
            )
            resolution = store.submit_resolution(
                _resolution_payload(
                    review_round,
                    actions=[
                        _action(binding.concept_ref)
                        for binding in review_round.concepts
                    ],
                )
            )
            closed = workflow.hub.load_state()["wait"]
            self.assertEqual(closed["status"], "closed")
            self.assertEqual(
                closed["resolution_sha256"],
                resolution.resolution_sha256,
            )
            self.assertEqual(validate_run(workflow.run_dir), [])

    async def test_frozen_v3_curator_keeps_legacy_prompt_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = CreativeCurationRunner()
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                settings=_settings(),
                runner=runner,
                prompt_catalog=_catalog_with_frozen_v3_curator(),
            )

            await workflow.execute()

            curator_tasks = [
                task
                for task in runner.tasks
                if task.task_id.startswith(
                    "creative-c6b-portfolio-curator-"
                )
            ]
            self.assertEqual(len(curator_tasks), 2)
            self.assertTrue(
                all(
                    "<BEGIN_CURATOR_LENS_" not in task.prompt
                    for task in curator_tasks
                )
            )
            state = workflow.hub.load_state()
            curator_metadata = [
                record["metadata"]
                for record in state["artifacts"].values()
                if record["artifact_type"]
                == "creative_portfolio_curation"
            ]
            self.assertEqual(len(curator_metadata), 2)
            self.assertTrue(
                all(
                    "curator_lens_id" not in metadata
                    for metadata in curator_metadata
                )
            )
            self.assertEqual(validate_run(workflow.run_dir), [])

    async def test_no_generated_concepts_publishes_empty_batch_without_wait(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = CreativeCurationRunner(empty_concepts=True)
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                settings=_settings(),
                runner=runner,
            )

            outcome = await workflow.execute()

            self.assertEqual(outcome.status, "completed")
            state = workflow.hub.load_state()
            self.assertEqual(state["status"], "completed")
            self.assertIsNone(state["wait"])
            batch = ReviewBatch.from_dict(
                json.loads(
                    workflow.hub.read_artifact(
                        "creative-review-batch-r001"
                    )
                )
            )
            self.assertEqual(batch.status, "skipped_empty")
            self.assertEqual(batch.concept_refs, ())
            self.assertEqual(batch.skip_reason, "no_concepts_generated")
            self.assertFalse(
                any(
                    task.task_id.startswith("creative-c6a-evidence-")
                    for task in runner.tasks
                )
            )
            self.assertEqual(validate_run(workflow.run_dir), [])
            self.assertEqual(
                inspect_run(workflow.run_dir)["zero_reason_code"],
                "no_concepts_generated",
            )

    async def test_all_concept_screen_rejects_have_distinct_empty_reason(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = CreativeCurationRunner(reject_all_hooks=True)
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                settings=_settings(),
                runner=runner,
            )

            await workflow.execute()

            batch = ReviewBatch.from_dict(
                json.loads(
                    workflow.hub.read_artifact(
                        "creative-review-batch-r001"
                    )
                )
            )
            self.assertEqual(
                batch.skip_reason,
                "all_candidates_failed_concept_screen",
            )
            self.assertIsNone(workflow.hub.load_state()["wait"])
            self.assertEqual(validate_run(workflow.run_dir), [])

    async def test_curator_support_can_produce_shortlist_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = CreativeCurationRunner(
                curator_decisions=("hold", "exclude"),
            )
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                settings=_settings(),
                runner=runner,
            )

            await workflow.execute()

            batch = ReviewBatch.from_dict(
                json.loads(
                    workflow.hub.read_artifact(
                        "creative-review-batch-r001"
                    )
                )
            )
            self.assertEqual(batch.skip_reason, "shortlist_empty")
            not_shortlisted = [
                row
                for row in _read_artifacts(
                    workflow,
                    "creative_concept_disposition",
                )
                if row["outcome"] == "not_shortlisted"
            ]
            self.assertEqual(len(not_shortlisted), 2)
            self.assertTrue(
                all(
                    row["reason_codes"] == ["insufficient_include_support"]
                    for row in not_shortlisted
                )
            )
            self.assertEqual(validate_run(workflow.run_dir), [])

    async def test_failed_evidence_task_does_not_publish_successor_disposition(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = CreativeCurationRunner(fail_evidence_revision=True)
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                settings=_settings(),
                runner=runner,
            )

            with self.assertRaises(CreativeWorkflowError):
                await workflow.execute()

            state = workflow.hub.load_state()
            self.assertEqual(state["status"], "failed")
            dispositions = _read_artifacts(
                workflow,
                "creative_concept_disposition",
            )
            self.assertFalse(
                any(
                    row["outcome"] == "superseded_by_evidence_revision"
                    for row in dispositions
                )
            )
            self.assertFalse(
                any(
                    record["artifact_type"] == "creative_concept"
                    and record["metadata"].get("revision_reason")
                    == "evidence_informed"
                    for record in state["artifacts"].values()
                )
            )


class DeterministicShortlistTests(unittest.TestCase):
    def test_approval_tiers_and_territory_round_robin_are_stable(self) -> None:
        concepts = tuple(
            CreativeConcept(
                concept_id=f"creative-concept-s{slot:02d}-01",
                revision=2,
                artifact_ref=f"creative-concept-s{slot:02d}-01-r002",
                primary_territory_ref=(
                    "creative-territory-01"
                    if slot in {1, 2}
                    else f"creative-territory-{slot:02d}"
                ),
                parent_atom_refs=(
                    (
                        "creative-atom-t01-01"
                        if slot in {1, 2}
                        else f"creative-atom-t{slot:02d}-01"
                    ),
                ),
                origin="base",
                task_id=f"task-{slot}",
            )
            for slot in range(1, 5)
        )
        votes = {
            concepts[0].artifact_ref: ("include", "include"),
            concepts[1].artifact_ref: ("include", "include"),
            concepts[2].artifact_ref: ("include", "include"),
            concepts[3].artifact_ref: ("include", "hold"),
        }

        shortlist, reasons = _deterministic_shortlist(
            tuple(reversed(concepts)),
            votes,
            limit=2,
        )

        self.assertEqual(
            tuple(item.artifact_ref for item in shortlist),
            (
                "creative-concept-s01-01-r002",
                "creative-concept-s03-01-r002",
            ),
        )
        self.assertEqual(
            reasons["creative-concept-s02-01-r002"],
            "territory_round_robin_capacity",
        )
        self.assertEqual(
            reasons["creative-concept-s04-01-r002"],
            "portfolio_capacity",
        )


if __name__ == "__main__":
    unittest.main()
