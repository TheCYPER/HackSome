from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from hacksome.stages.build.approval.build_adapter import (
    SubprocessBuildControlAdapter,
)
from hacksome.stages.build.approval.service import ApprovalService
from hacksome.stages.build.approval.store import ApprovalStore

from tests.stages.build.approval.test_build_approval_store import authorize_payload, make_catalog


class BuildApprovalProcessIntegrationTests(unittest.TestCase):
    def test_catalog_to_ledger_to_subprocess_registry_and_pool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = make_catalog(3)
            store = ApprovalStore(root / "approval")
            store.initialize(catalog)
            adapter = SubprocessBuildControlAdapter(
                build_root=root / "build",
                build_python=sys.executable,
                fake_lifecycle=True,
                max_active_teams=2,
                timeout_seconds=10,
            )
            service = ApprovalService(
                run_dir=root / "source",
                store=store,
                catalog=catalog,
                build_adapter=adapter,
                source_integrity_error=None,
            )
            payload = authorize_payload(
                catalog,
                "process-batch",
                [0, 1, 2],
            )
            first = service.authorize(payload)
            replay = service.authorize(payload)
            self.assertEqual(replay, first)
            snapshot = service.reconcile()
            self.assertEqual(
                [card["status"] for card in snapshot["cards"]],
                ["active", "active", "queued"],
            )

            registry_rows = sorted(
                (root / "build/registry/teams").glob("team-*.json")
            )
            self.assertEqual(len(registry_rows), 3)
            active_cards = snapshot["cards"][:2]
            for card in active_cards:
                team_root = root / "build/teams" / card["team_id"]
                self.assertEqual(
                    (
                        team_root
                        / "project/reference/initial-idea-card.md"
                    ).read_text(encoding="utf-8"),
                    catalog.cards[card["ordinal"]].card_markdown,
                )
            queued_root = (
                root
                / "build/teams"
                / snapshot["cards"][2]["team_id"]
            )
            self.assertFalse(queued_root.exists())

            # Simulate a lost Approval-side response after Build accepted it.
            authorization_id = snapshot["cards"][0]["authorization_id"]
            assert authorization_id is not None
            (store.receipts_dir / f"{authorization_id}.json").unlink()
            recovered = service.reconcile()
            self.assertEqual(recovered["cards"][0]["status"], "active")
            self.assertEqual(
                len(list((root / "build/registry/teams").glob("team-*.json"))),
                3,
            )


if __name__ == "__main__":
    unittest.main()
