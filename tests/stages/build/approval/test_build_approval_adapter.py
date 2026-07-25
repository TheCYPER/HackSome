from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hacksome.stages.build.approval.build_adapter import (
    InMemoryBuildControlAdapter,
    SubprocessBuildControlAdapter,
)
from hacksome.stages.build.approval.contracts import (
    BuildAdapterError,
    BuildAuthorizationEnvelopeV1,
    BuildReceiptV1,
    BuildStatusSnapshotV1,
)
from hacksome.stages.build.approval.service import ApprovalService
from hacksome.stages.build.approval.store import ApprovalStore

from tests.stages.build.approval.test_build_approval_store import authorize_payload, make_catalog


class SubprocessBuildAdapterTests(unittest.TestCase):
    def _adapter(
        self,
        root: Path,
        *,
        max_output_bytes: int = 1024,
    ) -> SubprocessBuildControlAdapter:
        return SubprocessBuildControlAdapter(
            build_root=root / "build",
            build_python=Path("/usr/bin/python3"),
            repository_root=root,
            timeout_seconds=0.1,
            max_output_bytes=max_output_bytes,
        )

    @staticmethod
    def _result(
        stdout: bytes,
        *,
        stderr: bytes = b"",
        returncode: int = 0,
    ):
        def run(argv, **kwargs):
            kwargs["stdout"].write(stdout)
            kwargs["stderr"].write(stderr)
            return subprocess.CompletedProcess(argv, returncode)

        return run

    def test_timeout_invalid_json_and_bounded_output_are_safe_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = self._adapter(root, max_output_bytes=8)
            cases = (
                (
                    subprocess.TimeoutExpired(["operator"], 0.1),
                    "build_timeout",
                ),
                (OSError("operator missing"), "build_unavailable"),
                (self._result(b"123456789"), "build_output_too_large"),
            )
            for effect, code in cases:
                with self.subTest(code=code), patch(
                    "hacksome.stages.build.approval.build_adapter.subprocess.run",
                    side_effect=effect,
                ):
                    with self.assertRaises(BuildAdapterError) as raised:
                        adapter.status()
                    self.assertEqual(raised.exception.code, code)

            invalid = self._adapter(root, max_output_bytes=1024)
            with patch(
                "hacksome.stages.build.approval.build_adapter.subprocess.run",
                side_effect=self._result(b"not-json"),
            ):
                with self.assertRaises(BuildAdapterError) as raised:
                    invalid.status()
                self.assertEqual(
                    raised.exception.code,
                    "build_invalid_json",
                )

    def test_receipt_mismatch_and_status_shape_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = self._adapter(root)
            catalog = make_catalog(1)
            envelope = catalog.cards[0].handoff

            authorization = BuildAuthorizationEnvelopeV1.create(
                route_id="useful",
                route_contract_version="1",
                catalog_sha256=catalog.catalog_sha256,
                handoff=envelope,
            )
            mismatched = {
                "schema_version": 1,
                "authorization_id": authorization.authorization_id,
                "team_id": "team-" + "0" * 24,
                "identity_sha256": authorization.identity_sha256,
                "observed_state": "queued",
            }
            with patch(
                "hacksome.stages.build.approval.build_adapter.subprocess.run",
                side_effect=self._result(
                    json.dumps(mismatched).encode("utf-8")
                ),
            ):
                with self.assertRaises(BuildAdapterError) as raised:
                    adapter.authorize(authorization)
                self.assertEqual(
                    raised.exception.code,
                    "build_receipt_mismatch",
                )

            with patch(
                "hacksome.stages.build.approval.build_adapter.subprocess.run",
                side_effect=self._result(b'{"schema_version":1}'),
            ):
                with self.assertRaises(BuildAdapterError) as raised:
                    adapter.status()
                self.assertEqual(
                    raised.exception.code,
                    "build_status_invalid",
                )

    def test_authorize_commits_before_adapter_delivery(self) -> None:
        class FailingAdapter:
            def __init__(self) -> None:
                self.authorize_calls = 0

            def authorize(self, envelope):
                self.authorize_calls += 1
                raise BuildAdapterError(
                    "simulated timeout",
                    code="build_timeout",
                )

            def status(self):
                return BuildStatusSnapshotV1(
                    schema_version=1,
                    max_active_teams=2,
                    teams=(),
                )

            def reconcile(self):
                return self.status()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = make_catalog(1)
            store = ApprovalStore(root / "approval")
            store.initialize(catalog)
            adapter = FailingAdapter()
            service = ApprovalService(
                run_dir=root / "source",
                store=store,
                catalog=catalog,
                build_adapter=adapter,
                source_integrity_error=None,
            )

            service.authorize(
                authorize_payload(catalog, "durable-first", [0])
            )
            self.assertEqual(adapter.authorize_calls, 0)
            self.assertEqual(len(store.load_mutations()), 1)
            self.assertEqual(len(store.outboxes()), 1)

            snapshot = service.reconcile()
            self.assertEqual(adapter.authorize_calls, 1)
            self.assertEqual(snapshot["cards"][0]["status"], "error")
            self.assertEqual(
                snapshot["cards"][0]["error"]["code"],
                "build_timeout",
            )

    def test_service_revalidates_custom_adapter_receipt(self) -> None:
        class MismatchedAdapter:
            def authorize(self, envelope):
                return BuildReceiptV1(
                    schema_version=1,
                    authorization_id=envelope.authorization_id,
                    team_id="team-" + "0" * 24,
                    identity_sha256=envelope.identity_sha256,
                    observed_state="queued",
                )

            def status(self):
                return BuildStatusSnapshotV1(
                    schema_version=1,
                    max_active_teams=2,
                    teams=(),
                )

            def reconcile(self):
                return self.status()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = make_catalog(1)
            store = ApprovalStore(root / "approval")
            store.initialize(catalog)
            service = ApprovalService(
                run_dir=root / "source",
                store=store,
                catalog=catalog,
                build_adapter=MismatchedAdapter(),
                source_integrity_error=None,
            )
            service.authorize(authorize_payload(catalog, "mismatch", [0]))
            snapshot = service.reconcile()
            card = snapshot["cards"][0]
            self.assertEqual(card["status"], "error")
            self.assertEqual(
                card["error"]["code"],
                "build_receipt_mismatch",
            )
            self.assertIsNone(
                store.receipt(card["authorization_id"])
            )

    def test_response_loss_replay_and_partial_batch_are_per_card(self) -> None:
        class ResponseLossAdapter(InMemoryBuildControlAdapter):
            def __init__(self) -> None:
                super().__init__(max_active_teams=2)
                self.lost = False

            def authorize(self, envelope):
                receipt = super().authorize(envelope)
                if not self.lost:
                    self.lost = True
                    raise BuildAdapterError(
                        "simulated response loss",
                        code="build_response_lost",
                    )
                return receipt

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = make_catalog(1)
            store = ApprovalStore(root / "approval")
            store.initialize(catalog)
            adapter = ResponseLossAdapter()
            service = ApprovalService(
                run_dir=root / "source",
                store=store,
                catalog=catalog,
                build_adapter=adapter,
                source_integrity_error=None,
            )
            service.authorize(authorize_payload(catalog, "response-loss", [0]))
            first = service.reconcile()
            self.assertEqual(first["cards"][0]["status"], "error")
            recovered = service.reconcile()
            self.assertEqual(recovered["cards"][0]["status"], "active")
            self.assertEqual(len(adapter.status().teams), 1)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = make_catalog(2)
            failing_card = catalog.cards[0].card_id
            store = ApprovalStore(root / "approval")
            store.initialize(catalog)
            service = ApprovalService(
                run_dir=root / "source",
                store=store,
                catalog=catalog,
                build_adapter=InMemoryBuildControlAdapter(
                    fail_card_ids=frozenset({failing_card})
                ),
                source_integrity_error=None,
            )
            service.authorize(
                authorize_payload(catalog, "partial-batch", [0, 1])
            )
            snapshot = service.reconcile()
            self.assertEqual(
                [card["status"] for card in snapshot["cards"]],
                ["error", "active"],
            )
            self.assertEqual(len(store.load_mutations()), 1)


if __name__ == "__main__":
    unittest.main()
