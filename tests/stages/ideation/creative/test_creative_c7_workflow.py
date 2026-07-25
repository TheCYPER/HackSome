from __future__ import annotations

import json
import tempfile
import unittest
from typing import Any
from unittest.mock import patch

from hacksome.stages.ideation.creative.finalization import (
    FINALIZATION_MANIFEST_PATH,
    FinalizationCoordinator as RealFinalizationCoordinator,
)
from hacksome.stages.ideation.creative.workflow import (
    CreativeIdeaWorkflow,
    CreativeWorkflowError,
)

from tests.stages.ideation.creative.test_creative_curation_workflow import (
    CreativeCurationRunner,
)
from tests.stages.ideation.creative.test_creative_workflow import _settings


class _NoAgentRunner:
    async def run(self, task: Any) -> Any:
        raise AssertionError(f"resume unexpectedly invoked an Agent: {task.task_id}")


def _faulting_coordinator(point_to_raise: str) -> Any:
    def factory(hub: Any) -> RealFinalizationCoordinator:
        def fault(point: str) -> None:
            if point == point_to_raise:
                raise RuntimeError(f"simulated interruption at {point}")

        return RealFinalizationCoordinator(
            hub,
            fault_injector=fault,
        )

    return factory


class CreativeC7WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_manifest_interruption_resumes_without_render_or_agent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                settings=_settings(),
                runner=CreativeCurationRunner(empty_concepts=True),
                run_id="creative-c7-replay",
            )
            with patch(
                "hacksome.stages.ideation.creative.finalization.FinalizationCoordinator",
                _faulting_coordinator("after_manifest"),
            ):
                interrupted = await workflow.execute()

            self.assertEqual(interrupted.status, "finalizing")
            state = workflow.hub.load_state()
            self.assertEqual(state["status"], "running")
            self.assertEqual(
                state["current_stage"],
                "creative-finalization",
            )
            self.assertEqual(state["result_artifact_ids"], [])
            manifest_path = workflow.run_dir / FINALIZATION_MANIFEST_PATH
            manifest_bytes = manifest_path.read_bytes()
            task_count = len(state["tasks"])

            reopened = CreativeIdeaWorkflow.open(
                workflow.run_dir,
                runner=_NoAgentRunner(),
            )
            with patch(
                "hacksome.stages.ideation.creative.report_projection.build_report_projection",
                side_effect=AssertionError("C7 replay must not render"),
            ):
                completed = await reopened.resume()

            self.assertEqual(completed.status, "completed")
            self.assertEqual(manifest_path.read_bytes(), manifest_bytes)
            completed_state = workflow.hub.load_state()
            self.assertEqual(completed_state["status"], "completed")
            self.assertEqual(len(completed_state["tasks"]), task_count)
            self.assertIn(
                "creative-idea-report",
                completed_state["result_artifact_ids"],
            )

    async def test_pre_manifest_failure_publishes_only_partial_report(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                settings=_settings(),
                runner=CreativeCurationRunner(empty_concepts=True),
                run_id="creative-c7-failed",
            )

            with (
                patch(
                    "hacksome.stages.ideation.creative.finalization.FinalizationCoordinator",
                    _faulting_coordinator("after_stage:1"),
                ),
                self.assertRaisesRegex(
                    CreativeWorkflowError,
                    "deterministic finalization failed",
                ),
            ):
                await workflow.execute()

            state = workflow.hub.load_state()
            self.assertEqual(state["status"], "failed")
            self.assertEqual(state["result_artifact_ids"], [])
            self.assertFalse(
                (workflow.run_dir / FINALIZATION_MANIFEST_PATH).exists()
            )
            self.assertIn(
                "creative-partial-report",
                state["artifacts"],
            )
            self.assertIn(
                "creative-partial-report-json",
                state["artifacts"],
            )
            self.assertNotIn("creative-idea-report", state["artifacts"])
            self.assertFalse(
                any(
                    record["artifact_type"]
                    in {
                        "creative_idea_card",
                        "creative_build_handoff",
                        "creative_memory_record",
                    }
                    for record in state["artifacts"].values()
                )
            )

    async def test_tampered_frozen_output_fails_but_keeps_plan_for_audit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                settings=_settings(),
                runner=CreativeCurationRunner(empty_concepts=True),
                run_id="creative-c7-tampered",
            )
            with patch(
                "hacksome.stages.ideation.creative.finalization.FinalizationCoordinator",
                _faulting_coordinator("after_publish:1"),
            ):
                interrupted = await workflow.execute()

            self.assertEqual(interrupted.status, "finalizing")
            manifest_path = workflow.run_dir / FINALIZATION_MANIFEST_PATH
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            staged_path = (
                workflow.run_dir / manifest["outputs"][0]["staged_path"]
            )
            staged_path.write_bytes(b"tampered\n")

            with self.assertRaisesRegex(
                CreativeWorkflowError,
                "deterministic finalization failed",
            ):
                await workflow.resume()

            state = workflow.hub.load_state()
            self.assertEqual(state["status"], "failed")
            self.assertEqual(state["result_artifact_ids"], [])
            self.assertEqual(
                state["finalization"]["phase"],
                "publishing",
            )
            self.assertTrue(manifest_path.is_file())
            self.assertIn(
                "creative-idea-report",
                state["artifacts"],
            )
            self.assertIn(
                "creative-partial-report-json",
                state["artifacts"],
            )
