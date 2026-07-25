from __future__ import annotations

from dataclasses import replace
import json
import tempfile
import unittest
from pathlib import Path

from hacksome.creative.review import (
    ReviewStaleError,
    ReviewValidationError,
)
from hacksome.creative.review_backend import RunReviewBackend
from hacksome.creative.workflow import CreativeIdeaWorkflow
from hacksome.state import atomic_write_json, atomic_write_text

from tests.test_creative_curation_workflow import CreativeCurationRunner
from tests.test_creative_review import (
    _action,
    _resolution_payload,
    _review_payload,
)
from tests.test_creative_workflow import (
    _non_empty_memory_snapshot,
    _settings,
)


class CreativeReviewBackendTests(unittest.IsolatedAsyncioTestCase):
    async def _waiting_workflow(
        self,
        root: Path,
        *,
        with_memory: bool = False,
    ) -> CreativeIdeaWorkflow:
        runner = CreativeCurationRunner()
        settings = _settings()
        memory_snapshot = None
        if with_memory:
            memory_snapshot = _non_empty_memory_snapshot()
            runner.memory_ref = memory_snapshot.entries[0].memory_ref.to_dict()
            runner.hook_mode = "repair_success"
            settings = replace(
                settings,
                idea_memory_mode="auto",
                memory_remixers=0,
                max_memory_challengers=0,
            )
        workflow = CreativeIdeaWorkflow.create(
            "Make a legible interactive surprise.",
            root,
            settings=settings,
            runner=runner,
            memory_snapshot=memory_snapshot,
        )
        outcome = await workflow.execute()
        self.assertEqual(outcome.status, "waiting")
        return workflow

    async def test_projects_and_mutates_one_bound_review_round(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = await self._waiting_workflow(Path(directory))
            backend = RunReviewBackend(workflow.run_dir)

            before = backend.snapshot(
                role="reviewer",
                reviewer_id="reviewer-one",
                include_team_wall=True,
            )
            self.assertEqual(before["run_id"], workflow.hub.run_id)
            self.assertEqual(before["schema_version"], 2)
            self.assertEqual(before["round"]["sha256"], backend.round.round_sha256)
            self.assertEqual(
                [item["concept_ref"] for item in before["concepts"]],
                list(backend.batch.concept_refs),
            )
            self.assertTrue(all(item["hook"] for item in before["concepts"]))
            self.assertTrue(all(item["novelty"] for item in before["concepts"]))
            self.assertTrue(
                all(item["software_core_and_runtime"] for item in before["concepts"])
            )
            self.assertTrue(
                all(item["share_trigger_and_artifact"] for item in before["concepts"])
            )
            self.assertNotIn(
                "feasibility_evidence",
                json.dumps(before, ensure_ascii=False),
            )
            self.assertNotIn("team_wall", before)
            self.assertNotIn("curation", before)

            receipt_payload = _review_payload(
                backend.round,
                concept_indexes=tuple(range(len(backend.round.concepts))),
            )
            receipt_result = backend.submit_review(
                receipt_payload,
                expected_reviewer_id="reviewer-one",
            )
            json.dumps(receipt_result, ensure_ascii=False, allow_nan=False)
            self.assertEqual(receipt_result["status"], "saved")
            self.assertIsNone(receipt_result["next_command"])
            self.assertTrue(backend.has_submitted("reviewer-one"))

            stranger = backend.snapshot(
                role="reviewer",
                reviewer_id="reviewer-two",
                include_team_wall=True,
            )
            self.assertNotIn("team_wall", stranger)
            after = backend.snapshot(
                role="reviewer",
                reviewer_id="reviewer-one",
                include_team_wall=True,
            )
            self.assertEqual(len(after["team_wall"]), 1)
            wall_signal = after["team_wall"][0]["concept_reviews"][0]
            self.assertEqual(wall_signal["share_impulse"], "immediate")
            self.assertEqual(wall_signal["demo_confidence"], "yes")

            curator = backend.snapshot(
                role="curator",
                reviewer_id="curator-one",
                include_team_wall=True,
            )
            self.assertEqual(len(curator["curation"]["receipts"]), 1)
            curator_signal = curator["curation"]["receipts"][0]["concept_reviews"][0]
            self.assertEqual(curator_signal["share_impulse"], "immediate")
            self.assertEqual(curator_signal["demo_confidence"], "yes")
            self.assertEqual(
                len(curator["curation"]["coverage"]),
                len(backend.round.concepts),
            )
            self.assertTrue(curator["curation"]["feedback_fragments"])
            self.assertEqual(
                len(curator["curation"]["feasibility_evidence"]),
                len(backend.round.concepts),
            )
            self.assertTrue(
                all(
                    row["dimensions"]
                    for row in curator["curation"]["feasibility_evidence"]
                )
            )
            self.assertTrue(curator["curation"]["resolution_controls"]["can_close"])

            resolution_payload = _resolution_payload(
                backend.round,
                actions=[
                    _action(binding.concept_ref) for binding in backend.round.concepts
                ],
            )
            resolution_result = backend.submit_resolution(resolution_payload)
            json.dumps(resolution_result, ensure_ascii=False, allow_nan=False)
            self.assertEqual(resolution_result["status"], "closed")
            self.assertIn("hacksome resume", resolution_result["next_command"])
            self.assertIn(
                str(workflow.run_dir),
                resolution_result["next_command"],
            )
            self.assertEqual(
                workflow.hub.load_state()["wait"]["resolution_sha256"],
                resolution_result["resolution_sha256"],
            )

            retry = backend.submit_resolution(resolution_payload)
            self.assertEqual(retry["closed_at"], resolution_result["closed_at"])
            closed = backend.snapshot(
                role="curator",
                reviewer_id=None,
                include_team_wall=True,
            )
            self.assertEqual(closed["round"]["status"], "closed")
            self.assertFalse(closed["curation"]["resolution_controls"]["can_close"])

    async def test_curator_projection_includes_verified_memory_provenance(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = await self._waiting_workflow(
                Path(directory),
                with_memory=True,
            )
            backend = RunReviewBackend(workflow.run_dir)

            reviewer = backend.snapshot(
                role="reviewer",
                reviewer_id="reviewer-one",
                include_team_wall=False,
            )
            self.assertNotIn("curation", reviewer)
            self.assertNotIn(
                "memory_source_refs",
                json.dumps(reviewer, ensure_ascii=False),
            )

            curator = backend.snapshot(
                role="curator",
                reviewer_id=None,
                include_team_wall=True,
            )
            provenance = curator["curation"]["memory_provenance"]
            self.assertTrue(provenance)
            self.assertEqual(provenance[0]["cue_id"], "memory-cue-01")
            self.assertEqual(provenance[0]["cue_role"], "inspire")
            self.assertEqual(
                provenance[0]["source_run_id"],
                "historic-run",
            )
            self.assertTrue(provenance[0]["transformation"])
            self.assertTrue(provenance[0]["copy_risk"])

    async def test_rejects_stale_wait_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = await self._waiting_workflow(Path(directory))
            state = workflow.hub.load_raw_state()
            state["wait"]["round_sha256"] = "f" * 64
            atomic_write_json(workflow.hub.state_path, state)

            with self.assertRaisesRegex(ReviewStaleError, "round_sha256"):
                RunReviewBackend(workflow.run_dir)

    async def test_rejects_tampered_batch_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = await self._waiting_workflow(Path(directory))
            state = workflow.hub.load_state()
            record = state["artifacts"]["creative-review-batch-r001"]
            batch_path = workflow.run_dir / record["path"]
            atomic_write_text(batch_path, "{}\n")

            with self.assertRaises(ReviewValidationError):
                RunReviewBackend(workflow.run_dir)

    async def test_rejects_invalid_role_and_reviewer_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = await self._waiting_workflow(Path(directory))
            backend = RunReviewBackend(workflow.run_dir)

            with self.assertRaisesRegex(
                ReviewValidationError,
                "reviewer snapshot requires",
            ):
                backend.snapshot(
                    role="reviewer",
                    reviewer_id=None,
                    include_team_wall=False,
                )
            with self.assertRaisesRegex(
                ReviewValidationError,
                "invalid reviewer_id",
            ):
                backend.snapshot(
                    role="reviewer",
                    reviewer_id="unsafe:reviewer",
                    include_team_wall=False,
                )


if __name__ == "__main__":
    unittest.main()
