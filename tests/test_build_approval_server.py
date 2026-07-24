from __future__ import annotations

import http.client
import json
import tempfile
import time
import unittest
from pathlib import Path

from hacksome.build_approval.build_adapter import InMemoryBuildControlAdapter
from hacksome.build_approval.server import (
    ApprovalServerConfig,
    BuildApprovalServer,
)
from hacksome.build_approval.service import ApprovalService
from hacksome.build_approval.store import ApprovalStore

from tests.test_build_approval_store import authorize_payload, make_catalog


class BuildApprovalServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.catalog = make_catalog(3)
        store = ApprovalStore(root / "approval")
        store.initialize(self.catalog)
        service = ApprovalService(
            run_dir=root / "source",
            store=store,
            catalog=self.catalog,
            build_adapter=InMemoryBuildControlAdapter(max_active_teams=2),
            source_integrity_error=None,
        )
        self.server = BuildApprovalServer(
            service,
            ApprovalServerConfig(
                approval_root=store.root,
                host="127.0.0.1",
                port=0,
                reconcile_interval_seconds=60,
            ),
            join_token="join-token-safe-1234567890",
        ).start()
        self.addCleanup(self.server.stop)
        self.cookie = self._join()

    def _connection(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection(
            "127.0.0.1",
            self.server.bound_port,
            timeout=3,
        )

    def _join(self) -> str:
        connection = self._connection()
        connection.request("GET", "/join/join-token-safe-1234567890")
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 303)
        header = response.getheader("Set-Cookie")
        assert header is not None
        connection.close()
        return header.split(";", 1)[0]

    def _json_request(
        self,
        method: str,
        path: str,
        payload: dict,
        *,
        origin: str | None = None,
    ) -> tuple[http.client.HTTPResponse, dict]:
        connection = self._connection()
        headers = {
            "Cookie": self.cookie,
            "Content-Type": "application/json; charset=utf-8",
        }
        if origin is not None:
            headers["Origin"] = origin
        connection.request(
            method,
            path,
            body=json.dumps(payload),
            headers=headers,
        )
        response = connection.getresponse()
        value = json.loads(response.read().decode())
        connection.close()
        return response, value

    def _snapshot_after_delivery(self) -> dict:
        deadline = time.monotonic() + 3
        while True:
            connection = self._connection()
            connection.request(
                "GET",
                "/api/snapshot",
                headers={"Cookie": self.cookie},
            )
            response = connection.getresponse()
            snapshot = json.loads(response.read())
            connection.close()
            if all(
                card["status"] not in {"authorized"}
                for card in snapshot["cards"]
            ):
                return snapshot
            if time.monotonic() >= deadline:
                self.fail("background Build reconciliation did not finish")
            time.sleep(0.01)

    def test_join_assets_snapshot_detail_and_security_headers(self) -> None:
        connection = self._connection()
        connection.request(
            "GET",
            "/api/snapshot",
            headers={"Cookie": self.cookie},
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertEqual(len(payload["cards"]), 3)
        self.assertNotIn("card_markdown", payload["cards"][0])
        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        self.assertIn("frame-ancestors 'none'", response.getheader("Content-Security-Policy"))
        connection.close()

        connection = self._connection()
        connection.request(
            "GET",
            "/api/cards/0",
            headers={"Cookie": self.cookie},
        )
        response = connection.getresponse()
        detail = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertIn("# Dispatch 1", detail["card_markdown"])
        self.assertNotIn(str(Path(self.temporary.name)), json.dumps(detail))
        connection.close()

        connection = self._connection()
        connection.request("GET", "/assets/app.js", headers={"Cookie": self.cookie})
        response = connection.getresponse()
        javascript = response.read().decode()
        self.assertNotIn("innerHTML", javascript)
        self.assertNotIn("http://", javascript)
        self.assertNotIn("https://", javascript)
        self.assertIn('ui.approveDialog.returnValue = "";', javascript)
        connection.close()

    def test_authorize_replay_close_and_closed_status_remains_available(self) -> None:
        payload = authorize_payload(self.catalog, "server-batch", [0, 1])
        response, first = self._json_request(
            "POST",
            "/api/authorize",
            payload,
            origin=self.server.origin,
        )
        self.assertEqual(response.status, 202)
        response, replay = self._json_request(
            "POST",
            "/api/authorize",
            payload,
            origin=self.server.origin,
        )
        self.assertEqual(response.status, 202)
        self.assertEqual(replay, first)

        response, _ = self._json_request(
            "POST",
            "/api/close",
            {
                "schema_version": 1,
                "request_id": "server-close",
                "catalog_sha256": self.catalog.catalog_sha256,
            },
            origin=self.server.origin,
        )
        self.assertEqual(response.status, 200)
        snapshot = self._snapshot_after_delivery()
        self.assertEqual(snapshot["approval_status"], "closed")
        self.assertEqual(snapshot["cards"][2]["status"], "not_built")
        self.assertEqual(snapshot["cards"][0]["status"], "active")

    def test_transport_rejects_origin_host_method_and_non_strict_json(self) -> None:
        response, payload = self._json_request(
            "POST",
            "/api/reconcile",
            {},
            origin="http://evil.invalid",
        )
        self.assertEqual(response.status, 403)
        self.assertEqual(payload["code"], "invalid_origin")

        connection = self._connection()
        connection.request(
            "PUT",
            "/api/snapshot",
            headers={"Cookie": self.cookie},
        )
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 405)
        connection.close()

        connection = self._connection()
        connection.request(
            "GET",
            "/api/snapshot",
            headers={"Cookie": self.cookie, "Host": "evil.invalid"},
        )
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 400)
        connection.close()

        connection = self._connection()
        body = b'{"value":NaN}'
        connection.request(
            "POST",
            "/api/reconcile",
            body=body,
            headers={
                "Cookie": self.cookie,
                "Origin": self.server.origin,
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        self.assertEqual(response.status, 422)
        self.assertEqual(payload["code"], "non_strict_json")
        connection.close()

    def test_non_loopback_bind_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback-only"):
            ApprovalServerConfig(
                approval_root=Path(self.temporary.name),
                host="0.0.0.0",
            )


if __name__ == "__main__":
    unittest.main()
