from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from hacksome import cli
from hacksome.stages.build.approval.build_adapter import (
    InMemoryBuildControlAdapter,
    SubprocessBuildControlAdapter,
)
from hacksome.stages.build.approval.service import ApprovalService
from hacksome.stages.build.approval.store import ApprovalStore

from tests.stages.build.approval.test_build_approval_store import authorize_payload, make_catalog


class BuildApprovalProcessIntegrationTests(unittest.TestCase):
    def test_cli_authorization_uses_durable_service_and_replays(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = make_catalog(3)
            store = ApprovalStore(root / "approval")
            store.initialize(catalog)
            service = ApprovalService(
                run_dir=root / "source",
                store=store,
                catalog=catalog,
                build_adapter=InMemoryBuildControlAdapter(max_active_teams=2),
                source_integrity_error=None,
            )
            argv = [
                "approve",
                str(root / "source"),
                "--cards",
                catalog.cards[2].card_id,
                catalog.cards[0].card_id,
                "--yes",
                "--json",
            ]
            outputs: list[dict] = []
            with patch.object(cli, "_approval_service", return_value=service):
                for _ in range(2):
                    stdout = io.StringIO()
                    with redirect_stdout(stdout):
                        self.assertEqual(cli.main(argv), 0)
                    outputs.append(json.loads(stdout.getvalue()))

            self.assertEqual(
                outputs[0]["authorization"],
                outputs[1]["authorization"],
            )
            self.assertEqual(outputs[0]["request_id"], outputs[1]["request_id"])
            self.assertEqual(
                [card["status"] for card in outputs[0]["snapshot"]["cards"]],
                ["active", "available", "active"],
            )
            self.assertEqual(len(store.load_mutations()), 1)
            self.assertEqual(len(store.outboxes()), 2)

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
