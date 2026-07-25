from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hacksome import cli


class _FakeApprovalServer:
    instances: list["_FakeApprovalServer"] = []

    def __init__(self, service: object, config: object) -> None:
        self.service = service
        self.config = config
        self.approval_url = "http://127.0.0.1:9321/join/test-token"
        self.served = False
        self.stopped = False
        self.instances.append(self)

    def serve_forever(self) -> None:
        self.served = True

    def stop(self) -> None:
        self.stopped = True


class _FakeApprovalService:
    def __init__(self, root: Path) -> None:
        self.store = SimpleNamespace(root=root)
        self.catalog = SimpleNamespace(
            catalog_sha256="a" * 64,
            cards=(
                SimpleNamespace(
                    card_id="card-b",
                    card_sha256="b" * 64,
                ),
                SimpleNamespace(
                    card_id="card-a",
                    card_sha256="c" * 64,
                ),
            ),
        )
        self.authorize_calls: list[dict] = []
        self.reconcile_calls = 0
        self.snapshot_calls = 0

    def authorize(self, payload: dict) -> dict:
        self.authorize_calls.append(payload)
        return {
            "schema_version": 1,
            "status": "authorized",
            "batch_id": "batch-000001-test",
            "authorizations": [],
        }

    def snapshot(self) -> dict:
        self.snapshot_calls += 1
        return {
            "schema_version": 1,
            "run_id": "route-neutral-run",
            "route_id": "creative",
            "route_contract_version": "1",
            "catalog_sha256": "a" * 64,
            "approval_status": "open",
            "source_integrity_error": None,
            "max_active_teams": 2,
            "cards": [],
        }

    def reconcile(self) -> dict:
        self.reconcile_calls += 1
        return self.snapshot()

    def validate(self) -> list[str]:
        return []


class BuildApprovalCliTests(unittest.TestCase):
    def invoke(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_approve_no_open_serves_and_never_launches_browser(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = _FakeApprovalService(Path(directory) / "approval")
            _FakeApprovalServer.instances.clear()
            with (
                patch.object(cli, "_approval_service", return_value=service),
                patch.object(cli, "BuildApprovalServer", _FakeApprovalServer),
                patch.object(cli.webbrowser, "open") as browser_open,
            ):
                code, stdout, stderr = self.invoke(
                    [
                        "approve",
                        str(Path(directory) / "source"),
                        "--no-open",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("Build Dispatch Board", stdout)
        browser_open.assert_not_called()
        server = _FakeApprovalServer.instances[0]
        self.assertTrue(server.served)
        self.assertTrue(server.stopped)

    def test_status_reconcile_and_validate_share_one_service_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = _FakeApprovalService(Path(directory) / "approval")
            with patch.object(cli, "_approval_service", return_value=service):
                status, status_stdout, _ = self.invoke(
                    ["build-status", directory, "--json"]
                )
                reconcile, reconcile_stdout, _ = self.invoke(
                    ["build-reconcile", directory, "--json"]
                )
                validate, validate_stdout, _ = self.invoke(
                    ["build-validate", directory, "--json"]
                )

        self.assertEqual((status, reconcile, validate), (0, 0, 0))
        self.assertEqual(
            json.loads(status_stdout)["run_id"],
            "route-neutral-run",
        )
        self.assertEqual(
            json.loads(reconcile_stdout)["approval_status"],
            "open",
        )
        self.assertTrue(json.loads(validate_stdout)["valid"])
        self.assertEqual(service.reconcile_calls, 1)

    def test_human_status_exposes_card_ids_for_cli_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = _FakeApprovalService(Path(directory) / "approval")
            snapshot = service.snapshot()
            snapshot["cards"] = [
                {
                    "ordinal": 0,
                    "card_id": "card-b",
                    "title": "Build the useful thing",
                    "status": "available",
                    "team_id": None,
                    "queue_position": None,
                }
            ]
            with (
                patch.object(cli, "_approval_service", return_value=service),
                patch.object(service, "snapshot", return_value=snapshot),
            ):
                code, stdout, stderr = self.invoke(["build-status", directory])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("card card-b", stdout)

    def test_approve_cards_authorizes_in_catalog_order_and_reconciles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = _FakeApprovalService(Path(directory) / "approval")
            with patch.object(cli, "_approval_service", return_value=service):
                code, stdout, stderr = self.invoke(
                    [
                        "approve",
                        str(Path(directory) / "source"),
                        "--cards",
                        "card-a",
                        "card-b",
                        "--yes",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("Authorized batch: batch-000001-test", stdout)
        self.assertEqual(service.reconcile_calls, 1)
        self.assertEqual(
            service.authorize_calls[0]["cards"],
            [
                {"card_id": "card-b", "card_sha256": "b" * 64},
                {"card_id": "card-a", "card_sha256": "c" * 64},
            ],
        )
        self.assertRegex(
            service.authorize_calls[0]["request_id"],
            r"^cli-[0-9a-f]{32}$",
        )

    def test_approve_cards_json_can_persist_without_reconcile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = _FakeApprovalService(Path(directory) / "approval")
            with patch.object(cli, "_approval_service", return_value=service):
                code, stdout, stderr = self.invoke(
                    [
                        "approve",
                        str(Path(directory) / "source"),
                        "--cards",
                        "card-a",
                        "--request-id",
                        "operator-request-1",
                        "--yes",
                        "--no-reconcile",
                        "--json",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["request_id"], "operator-request-1")
        self.assertEqual(
            payload["authorization"]["batch_id"],
            "batch-000001-test",
        )
        self.assertEqual(service.reconcile_calls, 0)
        self.assertEqual(service.snapshot_calls, 1)

    def test_approve_cards_requires_explicit_confirmation_before_open(self) -> None:
        with patch.object(cli, "_approval_service") as open_service:
            code, _, stderr = self.invoke(
                ["approve", "source", "--cards", "card-a"]
            )

        self.assertEqual(code, 1)
        self.assertIn("requires --yes", stderr)
        open_service.assert_not_called()

    def test_approve_cards_rejects_unknown_and_duplicate_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = _FakeApprovalService(Path(directory) / "approval")
            with patch.object(cli, "_approval_service", return_value=service):
                duplicate, _, duplicate_error = self.invoke(
                    [
                        "approve",
                        directory,
                        "--cards",
                        "card-a",
                        "card-a",
                        "--yes",
                    ]
                )
                unknown, _, unknown_error = self.invoke(
                    [
                        "approve",
                        directory,
                        "--cards",
                        "missing",
                        "--yes",
                    ]
                )

        self.assertEqual((duplicate, unknown), (1, 1))
        self.assertIn("duplicate Card IDs", duplicate_error)
        self.assertIn("unknown Card ID(s): missing", unknown_error)
        self.assertEqual(service.authorize_calls, [])

    def test_completed_routes_emit_the_same_approval_next_step(self) -> None:
        catalog = SimpleNamespace(cards=(object(),))
        stdout = io.StringIO()
        with (
            patch.object(
                cli,
                "project_post_card_catalog",
                return_value=catalog,
            ),
            redirect_stdout(stdout),
        ):
            cli._print_build_approval_next(Path("runs/useful-completed"))
            cli._print_build_approval_next(Path("runs/creative-completed"))

        self.assertEqual(
            stdout.getvalue().splitlines(),
            [
                "Next: hacksome approve runs/useful-completed",
                "Next: hacksome approve runs/creative-completed",
            ],
        )

    def test_build_python_must_be_an_executable_file(self) -> None:
        code, _, stderr = self.invoke(
            [
                "build-status",
                "run",
                "--build-python",
                str(Path(sys.executable).parent / "does-not-exist"),
            ]
        )
        self.assertEqual(code, 1)
        self.assertIn("--build-python must be an executable file", stderr)


if __name__ == "__main__":
    unittest.main()
