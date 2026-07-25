from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from http.cookies import SimpleCookie
from importlib import resources
from pathlib import Path
from typing import Any, Mapping

import hacksome.creative.review_server as review_server_module
from hacksome.creative.review_server import (
    CAPABILITY_COOKIE,
    MAX_APPROVED_FRAGMENTS_PER_TASK,
    REVIEWER_SESSION_COOKIE,
    CreativeReviewServer,
    ReviewHTTPError,
    ReviewRole,
    ReviewServerConfig,
)
from hacksome.state import StateError


class FakeReviewBackend:
    def __init__(self) -> None:
        self.submitted: set[str] = set()
        self.review_calls: list[tuple[dict[str, Any], str]] = []
        self.resolution_calls: list[dict[str, Any]] = []
        self.snapshot_calls: list[tuple[ReviewRole, str | None, bool]] = []
        self._lock = threading.RLock()

    def has_submitted(self, reviewer_id: str) -> bool:
        with self._lock:
            return reviewer_id in self.submitted

    def snapshot(
        self,
        *,
        role: ReviewRole,
        reviewer_id: str | None,
        include_team_wall: bool,
    ) -> Mapping[str, Any]:
        with self._lock:
            self.snapshot_calls.append((role, reviewer_id, include_team_wall))
        # Deliberately return the superset. The HTTP layer must redact it.
        return {
            "schema_version": 2,
            "run_id": "creative-run-001",
            "round": {
                "id": "creative-review-round-001",
                "sha256": "a" * 64,
                "status": "open",
            },
            "concepts": [
                {
                    "ref": "creative-concept-s01-01-r002",
                    "sha256": "b" * 64,
                    "title": "会回望你的影子",
                    "hook": "灯熄灭后，影子继续完成你刚才没做完的动作。",
                    "software_core_and_runtime": "浏览器输入经过本地 JS 变换后返回动画。",
                    "share_trigger_and_artifact": "每人得到一个可转发 URL。",
                    "minimum_hackathon_demo": "两台浏览器跑通输入到可见输出。",
                    "software_demo_feasibility": "must-not-leak",
                    "memory_sources": ["must-not-leak"],
                    "memory_source_refs": ["must-not-leak"],
                    "memory_cue_refs": ["must-not-leak"],
                    "origin": "memory_challenger",
                    "copy_risk": "must-not-leak",
                }
            ],
            "pairs": [],
            "coverage_summary": {
                "covered_concept_count": 1,
                "reviewer_count": len(self.submitted),
            },
            "team_wall": [
                {
                    "reviewer_name": "Weston",
                    "schema_version": 2,
                    "concept_reviews": [
                        {
                            "concept_ref": "creative-concept-s01-01-r002",
                            "one_sentence_retell": "影子在你离开后继续表演。",
                            "share_impulse": "immediate",
                            "share_target": "会做网页实验的朋友",
                            "demo_confidence": "yes",
                            "reactions": {"surprise": "yes"},
                            "recommendation": "keep",
                            "comment": "想试。",
                        }
                    ],
                    "memory_provenance": "nested-secret",
                }
            ],
            "peer_feedback": [{"recommendation": "keep"}],
            "memory_provenance": [{"source_ref": "memory-secret"}],
            "receipts": [{"reviewer_name": "Weston", "comment": "raw-secret"}],
            "curation": {
                "coverage": [{"concept_ref": "creative-concept-s01-01-r002"}],
                "receipts": [{"reviewer_name": "Weston", "comment": "raw"}],
                "memory_provenance": [
                    {
                        "source_ref": "past-run",
                        "copy_risk": "low",
                    }
                ],
                "feedback_fragments": [{"feedback_ref": "feedback-001"}],
                "feasibility_evidence": [
                    {
                        "concept_ref": "creative-concept-s01-01-r002",
                        "overall_decision": "pass",
                        "dimensions": [
                            {
                                "dimension": "software_first_core",
                                "verdict": "pass",
                                "reason_code": None,
                                "evidence": "浏览器路径完整。",
                            }
                        ],
                    }
                ],
                "resolution_controls": {"can_close": True},
            },
        }

    def submit_review(
        self,
        payload: Mapping[str, Any],
        *,
        expected_reviewer_id: str,
    ) -> Mapping[str, Any]:
        copied = dict(payload)
        with self._lock:
            self.review_calls.append((copied, expected_reviewer_id))
            self.submitted.add(expected_reviewer_id)
        return {
            "review_id": copied.get("review_id", "review-001"),
            "status": "saved",
        }

    def submit_resolution(
        self,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        with self._lock:
            self.resolution_calls.append(dict(payload))
        return {
            "resolution_id": payload.get("resolution_id", "resolution-001"),
            "status": "closed",
            "next_command": "hacksome resume /safe/run",
        }


class CookieJar:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def absorb(self, headers: list[tuple[str, str]]) -> None:
        for key, value in headers:
            if key.lower() != "set-cookie":
                continue
            parsed = SimpleCookie()
            parsed.load(value)
            for name, morsel in parsed.items():
                if morsel["max-age"] == "0":
                    self.values.pop(name, None)
                else:
                    self.values[name] = morsel.value

    def header(self) -> str:
        return "; ".join(f"{key}={value}" for key, value in self.values.items())

    def without(self, name: str) -> "CookieJar":
        other = CookieJar()
        other.values = {key: value for key, value in self.values.items() if key != name}
        return other


class ReviewServerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run_dir = Path(self.temporary.name) / "creative-run-001"
        self.run_dir.mkdir()
        self.backend = FakeReviewBackend()
        try:
            self.server = CreativeReviewServer(
                self.backend,
                ReviewServerConfig(run_dir=self.run_dir),
                review_token="review-token-for-tests",
                curator_token="curator-token-for-tests",
            )
        except PermissionError:
            self.skipTest("loopback sockets are unavailable in this environment")
        self.server.start()
        self.addCleanup(self.server.stop)

    def request(
        self,
        method: str,
        path: str,
        *,
        jar: CookieJar | None = None,
        payload: Any | None = None,
        raw_body: bytes | None = None,
        host: str | None = None,
        origin: str | None = None,
        content_type: str | None = None,
    ) -> tuple[int, list[tuple[str, str]], bytes]:
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            self.server.bound_port,
            timeout=2,
        )
        headers = {
            "Host": host or self.server.authority,
            "Connection": "close",
        }
        if jar is not None and jar.header():
            headers["Cookie"] = jar.header()
        if origin is not None:
            headers["Origin"] = origin
        body = raw_body
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if body is not None:
            headers["Content-Type"] = content_type or "application/json"
            headers["Content-Length"] = str(len(body))
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        response_body = response.read()
        response_headers = response.getheaders()
        connection.close()
        if jar is not None:
            jar.absorb(response_headers)
        return response.status, response_headers, response_body

    def join(self, *, curator: bool = False) -> CookieJar:
        jar = CookieJar()
        token = (
            "curator-token-for-tests" if curator else "review-token-for-tests"
        )
        status, headers, _ = self.request("GET", f"/join/{token}", jar=jar)
        self.assertEqual(status, 303)
        self.assertEqual(dict(headers)["Location"], "/")
        self.assertIn(CAPABILITY_COOKIE, jar.values)
        self.assertNotIn(REVIEWER_SESSION_COOKIE, jar.values)
        return jar

    def register(self, jar: CookieJar, reviewer_id: str) -> None:
        status, _, body = self.request(
            "POST",
            "/api/reviewer-sessions",
            jar=jar,
            payload={"reviewer_id": reviewer_id},
            origin=self.server.origin,
        )
        self.assertEqual(status, 201, body)
        self.assertIn(REVIEWER_SESSION_COOKIE, jar.values)

    def snapshot(self, jar: CookieJar) -> dict[str, Any]:
        status, _, body = self.request("GET", "/api/snapshot", jar=jar)
        self.assertEqual(status, 200, body)
        value = json.loads(body)
        self.assertIsInstance(value, dict)
        return value

    def valid_review(self, reviewer_id: str) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "review_id": f"review-{reviewer_id}",
            "run_id": "creative-run-001",
            "round_id": "creative-review-round-001",
            "round_sha256": "a" * 64,
            "reviewer_id": reviewer_id,
            "reviewer_name": "评审者",
            "concept_reviews": [
                {
                    "concept_ref": "creative-concept-s01-01-r002",
                    "concept_sha256": "b" * 64,
                    "one_sentence_retell": "灯灭后，影子替我继续动作。",
                    "share_target": "做舞台的朋友",
                    "share_impulse": "immediate",
                    "demo_confidence": "yes",
                    "reactions": {
                        "surprise": "yes",
                        "fun": "maybe",
                        "mystery": "yes",
                        "confusion": "no",
                    },
                    "recommendation": "keep",
                    "comment": "第一次就能懂。",
                }
            ],
            "pairwise": [],
            "overall_comment": "",
            "supersedes_review_id": None,
        }


class TestReviewUIResources(unittest.TestCase):
    def test_fixed_assets_are_packaged_and_use_safe_dynamic_rendering(self) -> None:
        root = resources.files("hacksome").joinpath("review_ui")
        html = root.joinpath("index.html").read_text(encoding="utf-8")
        css = root.joinpath("styles.css").read_text(encoding="utf-8")
        javascript = root.joinpath("app.js").read_text(encoding="utf-8")

        self.assertIn("Relay Room", html)
        self.assertIn("/assets/styles.css", html)
        self.assertIn("/assets/app.js", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<style>", html)
        for color in ("#191934", "#6667f4", "#ff6b62", "#9ce6d2", "#f5f7ff"):
            self.assertIn(color, css.lower())
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn("@media (max-width: 820px)", css)
        self.assertIn("min-height: 44px", css)
        self.assertIn("textContent", javascript)
        self.assertNotIn("innerHTML", javascript)
        self.assertNotIn("insertAdjacentHTML", javascript)
        self.assertIn("round_sha256", javascript)
        self.assertIn("localStorage", javascript)
        self.assertIn("share_impulse", javascript)
        self.assertIn("demo_confidence", javascript)
        self.assertIn("软件核心与运行入口", javascript)
        self.assertIn("分享触发与可转发物", javascript)

    def test_ui_renders_one_active_relay_card_with_its_own_review(self) -> None:
        root = resources.files("hacksome").joinpath("review_ui")
        html = root.joinpath("index.html").read_text(encoding="utf-8")
        css = root.joinpath("styles.css").read_text(encoding="utf-8")
        javascript = root.joinpath("app.js").read_text(encoding="utf-8")

        self.assertIn('id="concept-review-cards"', html)
        self.assertIn('class="concept-review-deck"', html)
        self.assertIn('id="active-concept-stage"', html)
        self.assertIn('id="toggle-concept-directory"', html)
        self.assertIn('id="previous-concept"', html)
        self.assertIn('id="relay-announcer"', html)
        self.assertNotIn('class="concept-review-stack"', html)
        self.assertNotIn('id="review-panel"', html)
        self.assertNotIn('id="retell"', html)
        self.assertIn("function createConceptReviewCard(", javascript)
        self.assertIn("createConceptReviewSection(concept, index)", javascript)
        self.assertIn('"用户做什么"', javascript)
        self.assertIn('"软件如何回应"', javascript)
        self.assertIn('"为何会再试 / 分享"', javascript)
        self.assertIn('"one_sentence_retell"', javascript)
        self.assertIn('"share_impulse"', javascript)
        self.assertIn('"demo_confidence"', javascript)
        self.assertIn("active_concept_ref", javascript)
        self.assertIn('["reject", "revise", "keep"]', javascript)
        self.assertIn('finishCardAction("later")', javascript)
        self.assertIn("nextUndecidedIndex", javascript)
        self.assertIn("globalThis.matchMedia", javascript)
        self.assertIn(".project-review-card", css)
        self.assertIn(".project-facts", css)
        self.assertIn(".project-review-section", css)
        self.assertIn(".concept-deck-shell", css)
        self.assertIn("@keyframes card-exit-keep", css)
        self.assertIn(".card-actions", css)

    def test_non_loopback_binding_requires_a_public_host(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "public_host is required"):
                ReviewServerConfig(run_dir=Path(directory), host="0.0.0.0")
            configured = ReviewServerConfig(
                run_dir=Path(directory),
                host="0.0.0.0",
                public_host="percy-mac.local",
                port=8765,
            )
            self.assertEqual(configured.public_host, "percy-mac.local")
            with self.assertRaisesRegex(ValueError, "must not include a port"):
                ReviewServerConfig(
                    run_dir=Path(directory),
                    public_host="localhost:8765",
                )


class TestRoleProjection(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = FakeReviewBackend()
        self.raw = self.backend.snapshot(
            role="curator",
            reviewer_id="reviewer-alpha",
            include_team_wall=True,
        )

    def assert_memory_metadata_hidden(self, projection: Mapping[str, Any]) -> None:
        serialized = json.dumps(projection, ensure_ascii=False)
        for forbidden in (
            "memory_source_refs",
            "memory_cue_refs",
            '"origin"',
            "memory_sources",
            "memory_provenance",
            "copy_risk",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_pre_submit_reviewer_uses_fail_closed_allowlist(self) -> None:
        projection = review_server_module._project_snapshot(
            self.raw,
            role="reviewer",
            reviewer_id="reviewer-alpha",
            has_submitted=False,
        )
        self.assert_memory_metadata_hidden(projection)
        self.assertNotIn("team_wall", projection)
        self.assertEqual(
            projection["concepts"][0]["hook"],
            "灯熄灭后，影子继续完成你刚才没做完的动作。",
        )
        self.assertEqual(
            projection["concepts"][0]["software_core_and_runtime"],
            "浏览器输入经过本地 JS 变换后返回动画。",
        )
        self.assertEqual(
            projection["concepts"][0]["share_trigger_and_artifact"],
            "每人得到一个可转发 URL。",
        )
        self.assertNotIn(
            "software_demo_feasibility",
            json.dumps(projection, ensure_ascii=False),
        )

    def test_post_submit_reviewer_gets_wall_but_not_memory_metadata(self) -> None:
        projection = review_server_module._project_snapshot(
            self.raw,
            role="reviewer",
            reviewer_id="reviewer-alpha",
            has_submitted=True,
        )
        self.assert_memory_metadata_hidden(projection)
        self.assertEqual(
            projection["team_wall"][0]["concept_reviews"][0]["one_sentence_retell"],
            "影子在你离开后继续表演。",
        )
        self.assertEqual(
            projection["team_wall"][0]["concept_reviews"][0]["share_impulse"],
            "immediate",
        )
        self.assertEqual(
            projection["team_wall"][0]["concept_reviews"][0]["demo_confidence"],
            "yes",
        )

    def test_curator_keeps_complete_memory_metadata(self) -> None:
        projection = review_server_module._project_snapshot(
            self.raw,
            role="curator",
            reviewer_id="reviewer-alpha",
            has_submitted=True,
        )
        concept = projection["concepts"][0]
        self.assertEqual(concept["origin"], "memory_challenger")
        self.assertEqual(concept["memory_source_refs"], ["must-not-leak"])
        self.assertEqual(concept["memory_cue_refs"], ["must-not-leak"])
        self.assertIn("memory_provenance", projection)
        self.assertIn("curation", projection)
        self.assertIn("feasibility_evidence", projection["curation"])


class TestReviewServerHTTP(ReviewServerTestCase):
    def test_fixed_routes_auth_and_security_headers(self) -> None:
        status, headers, _ = self.request("GET", "/")
        self.assertEqual(status, 401)
        header_map = {key.lower(): value for key, value in headers}
        self.assertEqual(header_map["cache-control"], "no-store")
        self.assertEqual(header_map["referrer-policy"], "no-referrer")
        self.assertEqual(header_map["x-content-type-options"], "nosniff")
        self.assertIn("default-src 'self'", header_map["content-security-policy"])
        self.assertNotIn("access-control-allow-origin", header_map)

        jar = self.join()
        status, headers, body = self.request("GET", "/", jar=jar)
        self.assertEqual(status, 200)
        self.assertIn(b"Relay Room", body)
        self.assertEqual(
            {key.lower(): value for key, value in headers}["content-type"],
            "text/html; charset=utf-8",
        )
        self.assertEqual(
            self.request("GET", "/assets/styles.css", jar=jar)[0],
            200,
        )
        self.assertEqual(self.request("GET", "/assets/app.js", jar=jar)[0], 200)

        status, headers, _ = self.request("PUT", "/", jar=jar)
        self.assertEqual(status, 405)
        self.assertEqual(dict(headers)["Allow"], "GET")
        self.assertEqual(self.request("GET", "/assets/../run.json", jar=jar)[0], 404)
        self.assertEqual(self.request("GET", "/?path=run.json", jar=jar)[0], 404)

    def test_join_uses_http_only_strict_cookie_and_never_echoes_token(self) -> None:
        status, headers, body = self.request(
            "GET",
            "/join/review-token-for-tests",
        )
        self.assertEqual(status, 303)
        set_cookies = [
            value for key, value in headers if key.lower() == "set-cookie"
        ]
        self.assertEqual(len(set_cookies), 2)
        capability_cookie = next(
            value for value in set_cookies if value.startswith(f"{CAPABILITY_COOKIE}=")
        )
        self.assertIn("HttpOnly", capability_cookie)
        self.assertIn("SameSite=Strict", capability_cookie)
        self.assertIn("Path=/", capability_cookie)
        self.assertNotIn("review-token-for-tests", capability_cookie)
        self.assertNotIn(b"review-token-for-tests", body)

    def test_reviewer_sessions_isolate_pre_and_post_submit_projection(self) -> None:
        first = self.join()
        self.register(first, "reviewer-alpha")
        before = self.snapshot(first)
        serialized_before = json.dumps(before, ensure_ascii=False)
        self.assertFalse(before["viewer"]["has_submitted"])
        self.assertNotIn("team_wall", before)
        self.assertNotIn("memory_provenance", serialized_before)
        self.assertNotIn("copy_risk", serialized_before)
        self.assertNotIn("curation", before)
        self.assertNotIn("receipts", serialized_before)
        self.assertEqual(
            self.backend.snapshot_calls[-1],
            ("reviewer", "reviewer-alpha", False),
        )

        status, _, body = self.request(
            "POST",
            "/api/reviews",
            jar=first,
            payload=self.valid_review("reviewer-alpha"),
            origin=self.server.origin,
        )
        self.assertEqual(status, 200, body)
        after = self.snapshot(first)
        serialized_after = json.dumps(after, ensure_ascii=False)
        self.assertTrue(after["viewer"]["has_submitted"])
        self.assertIn("team_wall", after)
        self.assertNotIn("memory_provenance", serialized_after)
        self.assertNotIn("copy_risk", serialized_after)
        self.assertNotIn("curation", after)
        self.assertEqual(
            self.backend.snapshot_calls[-1],
            ("reviewer", "reviewer-alpha", True),
        )

        second = first.without(REVIEWER_SESSION_COOKIE)
        self.register(second, "reviewer-bravo")
        second_snapshot = self.snapshot(second)
        self.assertFalse(second_snapshot["viewer"]["has_submitted"])
        self.assertNotIn("team_wall", second_snapshot)

    def test_curator_projection_requires_explicit_curator_link(self) -> None:
        reviewer = self.join()
        self.register(reviewer, "reviewer-alpha")
        reviewer_snapshot = self.snapshot(reviewer)
        self.assertEqual(reviewer_snapshot["viewer"]["role"], "reviewer")
        self.assertNotIn("curation", reviewer_snapshot)

        curator = self.join(curator=True)
        curator_snapshot = self.snapshot(curator)
        self.assertEqual(curator_snapshot["viewer"]["role"], "curator")
        self.assertIn("curation", curator_snapshot)
        self.assertIn("memory_provenance", curator_snapshot)
        self.assertIn("receipts", curator_snapshot)

        status, _, _ = self.request(
            "POST",
            "/api/resolve",
            jar=reviewer,
            payload={"resolution_id": "resolution-denied", "actions": []},
            origin=self.server.origin,
        )
        self.assertEqual(status, 403)
        self.assertEqual(self.backend.resolution_calls, [])

    def test_host_origin_content_type_body_and_session_are_checked(self) -> None:
        self.assertEqual(
            self.request(
                "GET",
                "/join/review-token-for-tests",
                host=f"evil.invalid:{self.server.bound_port}",
            )[0],
            400,
        )
        jar = self.join()

        status, _, _ = self.request(
            "POST",
            "/api/reviewer-sessions",
            jar=jar,
            payload={"reviewer_id": "reviewer-alpha"},
        )
        self.assertEqual(status, 403)
        status, _, _ = self.request(
            "POST",
            "/api/reviewer-sessions",
            jar=jar,
            raw_body=b"{}",
            origin=self.server.origin,
            content_type="text/plain",
        )
        self.assertEqual(status, 415)

        self.register(jar, "reviewer-alpha")
        mismatched = self.valid_review("reviewer-bravo")
        status, _, _ = self.request(
            "POST",
            "/api/reviews",
            jar=jar,
            payload=mismatched,
            origin=self.server.origin,
        )
        self.assertEqual(status, 403)
        self.assertEqual(self.backend.review_calls, [])

        malformed_status, _, _ = self.request(
            "POST",
            "/api/reviews",
            jar=jar,
            raw_body=b"{",
            origin=self.server.origin,
        )
        self.assertEqual(malformed_status, 400)

        too_large = b"{" + b"x" * (256 * 1024) + b"}"
        large_status, _, _ = self.request(
            "POST",
            "/api/reviews",
            jar=jar,
            raw_body=too_large,
            origin=self.server.origin,
        )
        self.assertEqual(large_status, 413)

    def test_text_and_feedback_context_limits_fail_without_truncation(self) -> None:
        reviewer = self.join()
        self.register(reviewer, "reviewer-alpha")
        review = self.valid_review("reviewer-alpha")
        review["concept_reviews"][0]["one_sentence_retell"] = "字" * 401
        status, _, body = self.request(
            "POST",
            "/api/reviews",
            jar=reviewer,
            payload=review,
            origin=self.server.origin,
        )
        self.assertEqual(status, 422)
        self.assertIn(b"text_field_too_long", body)
        self.assertEqual(self.backend.review_calls, [])

        review = self.valid_review("reviewer-alpha")
        review["concept_reviews"][0]["share_target"] = ""
        status, _, body = self.request(
            "POST",
            "/api/reviews",
            jar=reviewer,
            payload=review,
            origin=self.server.origin,
        )
        self.assertEqual(status, 422)
        self.assertIn(b"share_target_required", body)
        self.assertEqual(self.backend.review_calls, [])

        curator = self.join(curator=True)
        resolution = {
            "resolution_id": "resolution-too-many",
            "curator_name": "Percy",
            "actions": [
                {
                    "concept_ref": "creative-concept-s01-01-r002",
                    "action": "revise",
                    "approved_feedback": [
                        {"feedback_ref": f"feedback-{index:02d}"}
                        for index in range(MAX_APPROVED_FRAGMENTS_PER_TASK + 1)
                    ],
                }
            ],
        }
        status, _, body = self.request(
            "POST",
            "/api/resolve",
            jar=curator,
            payload=resolution,
            origin=self.server.origin,
        )
        self.assertEqual(status, 422)
        self.assertIn(b"too_many_approved_fragments", body)
        self.assertEqual(self.backend.resolution_calls, [])

    def test_safe_backend_errors_are_mapped_without_internal_details(self) -> None:
        class RejectingBackend(FakeReviewBackend):
            def submit_review(
                self,
                payload: Mapping[str, Any],
                *,
                expected_reviewer_id: str,
            ) -> Mapping[str, Any]:
                raise ReviewHTTPError(409, "stale_round", "round hash changed")

        self.server.stop()
        self.backend = RejectingBackend()
        self.server = CreativeReviewServer(
            self.backend,
            ReviewServerConfig(run_dir=self.run_dir),
            review_token="review-token-for-tests-2",
            curator_token="curator-token-for-tests-2",
        )
        self.server.start()
        self.addCleanup(self.server.stop)
        jar = CookieJar()
        status, _, _ = self.request(
            "GET",
            "/join/review-token-for-tests-2",
            jar=jar,
        )
        self.assertEqual(status, 303)
        self.register(jar, "reviewer-alpha")
        status, _, body = self.request(
            "POST",
            "/api/reviews",
            jar=jar,
            payload=self.valid_review("reviewer-alpha"),
            origin=self.server.origin,
        )
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["code"], "stale_round")


class TestReviewServerLifecycle(unittest.TestCase):
    def test_review_server_lock_is_held_for_the_whole_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            try:
                first = CreativeReviewServer(
                    FakeReviewBackend(),
                    ReviewServerConfig(run_dir=run_dir),
                )
            except PermissionError:
                self.skipTest(
                    "loopback sockets are unavailable in this environment"
                )
            second = CreativeReviewServer(
                FakeReviewBackend(),
                ReviewServerConfig(run_dir=run_dir),
            )
            try:
                first.start()
                self.assertTrue((run_dir / "review-server.lock").is_file())
                with self.assertRaisesRegex(StateError, "already held"):
                    second.start()
            finally:
                first.stop()
                second.server_close()

            third = CreativeReviewServer(
                FakeReviewBackend(),
                ReviewServerConfig(run_dir=run_dir),
            )
            try:
                third.start()
            finally:
                third.stop()
