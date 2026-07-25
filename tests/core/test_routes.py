from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from unittest.mock import patch

from hacksome.core.config import CodexConfig
from hacksome.stages.ideation.creative.contracts import CreativeWorkflowSettings
from hacksome.stages.ideation.creative.finalization import (
    FINALIZATION_MANIFEST_PATH,
    FinalizationCoordinator as RealFinalizationCoordinator,
)
from hacksome.stages.ideation.creative.review import ReviewBatch, ReviewRound, ReviewStore
from hacksome.stages.ideation.creative.workflow import (
    CreativeIdeaWorkflow,
    CreativeWorkflowError,
)
from hacksome.core.hub import RunHub
from hacksome.core.prompting import useful_prompt_catalog
from hacksome.core.routes import get_run_contract, inspect_run, validate_run
from hacksome.core.state import atomic_write_json, sha256_file

from tests.stages.ideation.creative.test_creative_curation_workflow import (
    CreativeCurationRunner,
)
from tests.stages.ideation.creative.test_creative_review import _review_payload
from tests.stages.ideation.creative.test_creative_workflow import _settings


class RouteContractTests(unittest.TestCase):
    def freeze_useful_manifest(self, hub: RunHub) -> None:
        frozen = useful_prompt_catalog.freeze(
            hub.run_dir,
            route_id="useful",
            contract_version="1",
            prompt_policy_version="1",
            stage_policy_version="1",
        )
        hub.set_resource_manifest(frozen.manifest_reference())

    def freeze_placeholder_manifest(self, hub: RunHub) -> None:
        path = hub.run_dir / "resources" / "manifest.json"
        atomic_write_json(path, {})
        hub.set_resource_manifest(
            {"path": "resources/manifest.json", "sha256": sha256_file(path)}
        )

    def test_useful_projection_preserves_existing_inspect_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hub = RunHub.create(
                "challenge",
                directory,
                settings={},
                codex_config=CodexConfig(),
                run_id="useful-run",
            )
            self.freeze_useful_manifest(hub)
            projection = inspect_run(hub.run_dir)
            self.assertEqual(
                list(projection),
                [
                    "run_id",
                    "status",
                    "current_stage",
                    "task_counts",
                    "decision_count",
                    "idea_card_count",
                    "run_dir",
                ],
            )
            self.assertEqual(validate_run(hub.run_dir), [])

    def test_creative_route_uses_registered_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = CreativeIdeaWorkflow.create(
                "challenge",
                directory,
                run_id="creative-run",
                settings=CreativeWorkflowSettings(idea_memory_mode="off"),
            )
            projection = inspect_run(workflow.run_dir)
            self.assertEqual(projection["route_id"], "creative")
            self.assertEqual(validate_run(workflow.run_dir), [])

    def test_unknown_route_and_contract_version_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hub = RunHub.create(
                "challenge",
                directory,
                settings={},
                codex_config=CodexConfig(),
                run_id="unknown-run",
            )
            self.freeze_placeholder_manifest(hub)
            state = hub.load_raw_state()
            state["route"]["id"] = "unknown"
            atomic_write_json(hub.state_path, state)
            self.assertIn("unknown run route", validate_run(hub.run_dir)[0])

            state["route"]["id"] = "useful"
            state["route"]["contract_version"] = "999"
            atomic_write_json(hub.state_path, state)
            self.assertIn("unsupported 'useful' contract", validate_run(hub.run_dir)[0])

    def test_contract_resolution_accepts_projected_v1_useful(self) -> None:
        state = {
            "schema_version": 1,
            "route": {"id": "useful", "contract_version": "1"},
        }
        self.assertEqual(get_run_contract(state).route_id, "useful")

    def test_completed_creative_c7_projects_and_validates_exact_results(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                run_id="creative-c7-completed",
                settings=_settings(),
                runner=CreativeCurationRunner(empty_concepts=True),
            )

            outcome = asyncio.run(workflow.execute())

            self.assertEqual(outcome.status, "completed")
            projection = inspect_run(workflow.run_dir)
            self.assertEqual(
                projection["finalization"],
                {
                    "status": "completed",
                    "manifest_ref": (
                        "state/creative-finalization/"
                        "finalization-manifest.json"
                    ),
                    "planned_artifact_count": 4,
                    "published_artifact_count": 4,
                    "resumable": False,
                },
            )
            self.assertEqual(
                projection["zero_reason_code"],
                "no_concepts_generated",
            )
            state = workflow.hub.load_state()
            self.assertEqual(
                state["result_artifact_ids"],
                [
                    "creative-idea-report",
                    "creative-idea-report-json",
                    "creative-idea-card-index",
                    "creative-memory-record",
                ],
            )
            self.assertEqual(
                state["artifacts"]["creative-idea-report"][
                    "artifact_type"
                ],
                "creative_idea_report_markdown",
            )
            self.assertEqual(
                state["artifacts"]["creative-idea-report-json"][
                    "artifact_type"
                ],
                "creative_idea_report_json",
            )
            self.assertEqual(validate_run(workflow.run_dir), [])

            state["result_artifact_ids"] = state["result_artifact_ids"][:-1]
            atomic_write_json(workflow.hub.state_path, state)
            self.assertTrue(
                any(
                    "result artifact IDs" in error
                    for error in validate_run(workflow.run_dir)
                )
            )

    def test_completed_creative_c7_rejects_final_output_record_rebinding(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                run_id="creative-c7-completed-tamper",
                settings=_settings(),
                runner=CreativeCurationRunner(empty_concepts=True),
            )
            outcome = asyncio.run(workflow.execute())
            self.assertEqual(outcome.status, "completed")

            state = workflow.hub.load_state()
            report_record = state["artifacts"][
                "creative-idea-report-json"
            ]
            report_path = workflow.run_dir / report_record["path"]
            report_path.write_bytes(b'{"malicious":true}\n')
            report_record["sha256"] = sha256_file(report_path)
            atomic_write_json(workflow.hub.state_path, state)

            errors = validate_run(workflow.run_dir)
            self.assertTrue(
                any(
                    "published output" in error
                    or "artifact record changed" in error
                    for error in errors
                ),
                errors,
            )
            projection = inspect_run(workflow.run_dir)
            self.assertEqual(
                projection["finalization"]["status"],
                "corrupt",
            )
            self.assertIsNone(projection["report_ref"])

    def test_creative_route_rejects_unknown_persisted_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                run_id="creative-unknown-status",
                settings=_settings(),
            )
            state = workflow.hub.load_state()
            state["status"] = "banana"
            atomic_write_json(workflow.hub.state_path, state)

            self.assertTrue(
                any(
                    "unsupported status" in error
                    for error in validate_run(workflow.run_dir)
                )
            )

    def test_frozen_creative_publication_is_projected_as_resumable(
        self,
    ) -> None:
        def interrupted_coordinator(hub: RunHub) -> RealFinalizationCoordinator:
            def fault(point: str) -> None:
                if point == "after_manifest":
                    raise RuntimeError("simulated publish interruption")

            return RealFinalizationCoordinator(
                hub,
                fault_injector=fault,
            )

        with tempfile.TemporaryDirectory() as directory:
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                run_id="creative-c7-publishing",
                settings=_settings(),
                runner=CreativeCurationRunner(empty_concepts=True),
            )
            with patch(
                "hacksome.stages.ideation.creative.finalization.FinalizationCoordinator",
                interrupted_coordinator,
            ):
                outcome = asyncio.run(workflow.execute())

            self.assertEqual(outcome.status, "finalizing")
            projection = inspect_run(workflow.run_dir)
            self.assertEqual(
                projection["finalization"]["status"],
                "publishing",
            )
            self.assertEqual(
                projection["finalization"]["planned_artifact_count"],
                4,
            )
            self.assertEqual(
                projection["finalization"]["published_artifact_count"],
                0,
            )
            self.assertTrue(projection["finalization"]["resumable"])
            self.assertEqual(validate_run(workflow.run_dir), [])

    def test_review_projection_uses_latest_persisted_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                run_id="creative-review-projection",
                settings=_settings(),
                runner=CreativeCurationRunner(),
            )
            outcome = asyncio.run(workflow.execute())
            batch = ReviewBatch.from_dict(
                json.loads(outcome.primary_artifact.read_text(encoding="utf-8"))
            )
            review_round = ReviewRound.open(batch)
            store = ReviewStore(workflow.hub, review_round)
            store.initialize()
            first = store.submit_review(
                _review_payload(
                    review_round,
                    concept_indexes=(0, 1),
                )
            )
            store.submit_review(
                _review_payload(
                    review_round,
                    review_id="review-two",
                    concept_indexes=(0,),
                    supersedes_review_id=first.review_id,
                )
            )

            projection = inspect_run(workflow.run_dir)

            self.assertEqual(projection["review"]["reviewer_count"], 1)
            self.assertEqual(
                projection["review"]["covered_concept_count"],
                1,
            )

    def test_failed_creative_c7_allows_only_partial_reports(self) -> None:
        def failing_coordinator(hub: RunHub) -> RealFinalizationCoordinator:
            def fault(point: str) -> None:
                if point == "after_stage:1":
                    raise RuntimeError("simulated pre-manifest failure")

            return RealFinalizationCoordinator(
                hub,
                fault_injector=fault,
            )

        with tempfile.TemporaryDirectory() as directory:
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                run_id="creative-c7-partial",
                settings=_settings(),
                runner=CreativeCurationRunner(empty_concepts=True),
            )
            with (
                patch(
                    "hacksome.stages.ideation.creative.finalization.FinalizationCoordinator",
                    failing_coordinator,
                ),
                self.assertRaisesRegex(
                    CreativeWorkflowError,
                    "deterministic finalization failed",
                ),
            ):
                asyncio.run(workflow.execute())

            projection = inspect_run(workflow.run_dir)
            self.assertEqual(projection["status"], "failed")
            self.assertIsNone(projection["report_ref"])
            self.assertEqual(
                projection["partial_report_ref"],
                "creative-partial-report-json",
            )
            self.assertEqual(
                projection["finalization"]["status"],
                "not_started",
            )
            self.assertEqual(validate_run(workflow.run_dir), [])

    def test_failed_creative_c7_keeps_exact_plan_prefix_for_audit(
        self,
    ) -> None:
        def interrupted_coordinator(
            hub: RunHub,
        ) -> RealFinalizationCoordinator:
            def fault(point: str) -> None:
                if point == "after_publish:1":
                    raise RuntimeError("simulated publish interruption")

            return RealFinalizationCoordinator(
                hub,
                fault_injector=fault,
            )

        with tempfile.TemporaryDirectory() as directory:
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                run_id="creative-c7-failed-audit",
                settings=_settings(),
                runner=CreativeCurationRunner(empty_concepts=True),
            )
            with patch(
                "hacksome.stages.ideation.creative.finalization.FinalizationCoordinator",
                interrupted_coordinator,
            ):
                outcome = asyncio.run(workflow.execute())

            self.assertEqual(outcome.status, "finalizing")
            manifest_path = workflow.run_dir / FINALIZATION_MANIFEST_PATH
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            staged_path = (
                workflow.run_dir
                / manifest["outputs"][0]["staged_path"]
            )
            staged_path.write_bytes(b"tampered\n")

            with self.assertRaisesRegex(
                CreativeWorkflowError,
                "deterministic finalization failed",
            ):
                asyncio.run(workflow.resume())

            projection = inspect_run(workflow.run_dir)
            self.assertEqual(projection["status"], "failed")
            self.assertEqual(
                projection["finalization"],
                {
                    "status": "corrupt",
                    "manifest_ref": FINALIZATION_MANIFEST_PATH,
                    "planned_artifact_count": 4,
                    "published_artifact_count": 1,
                    "resumable": False,
                },
            )
            self.assertIsNone(projection["report_ref"])
            self.assertEqual(
                projection["partial_report_ref"],
                "creative-partial-report-json",
            )
            self.assertEqual(validate_run(workflow.run_dir), [])

            state = workflow.hub.load_state()
            state["finalization"]["phase"] = "completed"
            atomic_write_json(workflow.hub.state_path, state)
            self.assertTrue(
                any(
                    "invalid C7 audit manifest" in error
                    or "invalid Creative finalization" in error
                    for error in validate_run(workflow.run_dir)
                )
            )

    def test_waiting_run_rejects_premature_final_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                run_id="creative-waiting-final-output",
                settings=_settings(),
                runner=CreativeCurationRunner(),
            )
            asyncio.run(workflow.execute())
            workflow.hub.publish_artifact(
                artifact_id="premature-creative-report",
                artifact_type="creative_idea_report_json",
                relative_path=(
                    "artifacts/creative/report/premature-report.json"
                ),
                content='{"status":"completed"}\n',
                task_id=None,
            )

            self.assertTrue(
                any(
                    "waiting Creative run must not contain C7 outputs"
                    in error
                    for error in validate_run(workflow.run_dir)
                )
            )


if __name__ == "__main__":
    unittest.main()
