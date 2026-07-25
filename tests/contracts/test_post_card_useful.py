from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hacksome.stages.build.approval.build_adapter import InMemoryBuildControlAdapter
from hacksome.stages.build.approval.contracts import SourceIntegrityError
from hacksome.stages.build.approval.service import ApprovalService
from hacksome.contracts.post_card.catalog import project_post_card_catalog
from hacksome.stages.ideation.useful.workflow import UsefulIdeaWorkflow

from tests.stages.build.approval.test_build_approval_store import authorize_payload
from tests.stages.ideation.useful.test_workflow import ScriptedRunner


class UsefulPostCardTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_useful_projects_exact_cards_and_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = UsefulIdeaWorkflow.create(
                "A real challenge",
                directory,
                run_id="useful-post-card",
                runner=ScriptedRunner(),
            )
            await workflow.execute()
            before = {
                path.relative_to(workflow.run_dir).as_posix(): path.read_bytes()
                for path in workflow.run_dir.rglob("*")
                if path.is_file()
            }
            catalog = project_post_card_catalog(workflow.run_dir)
            repeated = project_post_card_catalog(workflow.run_dir)
            self.assertEqual(catalog.to_mapping(), repeated.to_mapping())
            self.assertEqual(len(catalog.cards), 2)
            self.assertTrue(
                all(card.route_handoff_ref is None for card in catalog.cards)
            )
            self.assertTrue(
                all(
                    card.handoff.initial_idea_card_markdown
                    == card.card_markdown
                    for card in catalog.cards
                )
            )
            after = {
                path.relative_to(workflow.run_dir).as_posix(): path.read_bytes()
                for path in workflow.run_dir.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)

            adapter = InMemoryBuildControlAdapter()
            service = ApprovalService.open(
                workflow.run_dir,
                approval_root=Path(directory) / "approval",
                build_adapter=adapter,
            )
            service.authorize(
                authorize_payload(service.catalog, "useful-build", [0])
            )
            service.reconcile()
            unchanged = {
                path.relative_to(workflow.run_dir).as_posix(): path.read_bytes()
                for path in workflow.run_dir.rglob("*")
                if path.is_file()
            }
            self.assertEqual(unchanged, before)

        with tempfile.TemporaryDirectory() as directory:
            workflow = UsefulIdeaWorkflow.create(
                "A zero-card challenge",
                directory,
                run_id="useful-empty-post-card",
                runner=ScriptedRunner(empty_audiences=True),
            )
            await workflow.execute()
            self.assertEqual(
                project_post_card_catalog(workflow.run_dir).cards,
                (),
            )

    async def test_incomplete_useful_fails_before_approval_state_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = UsefulIdeaWorkflow.create(
                "Not run yet",
                directory,
                run_id="useful-incomplete",
                runner=ScriptedRunner(),
            )
            with self.assertRaisesRegex(Exception, "completed"):
                project_post_card_catalog(workflow.run_dir)
            self.assertFalse(
                (Path(directory) / ".hacksome" / "approvals").exists()
            )

    async def test_source_tamper_after_open_blocks_new_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = UsefulIdeaWorkflow.create(
                "A real challenge",
                directory,
                run_id="useful-source-tamper",
                runner=ScriptedRunner(),
            )
            await workflow.execute()
            adapter = InMemoryBuildControlAdapter()
            service = ApprovalService.open(
                workflow.run_dir,
                approval_root=Path(directory) / "approval",
                build_adapter=adapter,
            )
            card = service.catalog.cards[0]
            card_path = (
                workflow.run_dir
                / card.source_artifact_ref.relative_path
            )
            card_path.write_text("# Tampered after open\n", encoding="utf-8")

            with self.assertRaises(SourceIntegrityError):
                service.authorize(
                    authorize_payload(service.catalog, "stale-source", [0])
                )
            self.assertEqual(service.store.load_mutations(), [])
            self.assertEqual(adapter.status().teams, ())
            snapshot = service.snapshot()
            self.assertNotIn(
                str(Path(directory)),
                snapshot["source_integrity_error"],
            )


if __name__ == "__main__":
    unittest.main()
