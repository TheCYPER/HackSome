from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from hacksome import cli
from hacksome.core.state import canonical_json_bytes, sha256_bytes


class _FakeWorkflow:
    create_calls: list[tuple[str, Path, object, object, str | None]] = []

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir

    @classmethod
    def create(
        cls,
        challenge: str,
        runs_dir: Path,
        *,
        settings: object,
        codex_config: object,
        run_id: str | None,
    ) -> "_FakeWorkflow":
        cls.create_calls.append(
            (challenge, Path(runs_dir), settings, codex_config, run_id)
        )
        return cls(Path(runs_dir) / (run_id or "generated"))

    async def execute(self) -> Path:
        return self.run_dir / "artifacts" / "idea-cards" / "index.md"


class _FakeCreativeWorkflow:
    create_calls: list[dict[str, object]] = []
    open_calls: list[Path] = []
    execute_status = "waiting"
    resume_status = "completed"

    def __init__(self, run_dir: Path, *, resume: bool = False) -> None:
        self.run_dir = run_dir
        self._resume = resume

    @classmethod
    def create(
        cls,
        challenge: str,
        runs_dir: Path,
        **kwargs: object,
    ) -> "_FakeCreativeWorkflow":
        cls.create_calls.append(
            {
                "challenge": challenge,
                "runs_dir": Path(runs_dir),
                **kwargs,
            }
        )
        run_id = kwargs.get("run_id")
        return cls(Path(runs_dir) / (str(run_id) if run_id else "generated"))

    @classmethod
    def open(cls, run_dir: Path) -> "_FakeCreativeWorkflow":
        path = Path(run_dir)
        cls.open_calls.append(path)
        return cls(path, resume=True)

    def _outcome(self, status: str) -> SimpleNamespace:
        if status == "waiting":
            artifact = self.run_dir / "artifacts" / "review-batch.json"
            command = f"hacksome review {self.run_dir}"
        elif status == "finalizing":
            artifact = self.run_dir / "state" / "finalization" / "manifest.json"
            command = f"hacksome resume {self.run_dir}"
        else:
            artifact = self.run_dir / "artifacts" / "creative-report.md"
            command = None
        return SimpleNamespace(
            status=status,
            run_dir=self.run_dir,
            primary_artifact=artifact,
            next_command=command,
        )

    async def execute(self) -> SimpleNamespace:
        return self._outcome(self.execute_status)

    async def resume(self) -> SimpleNamespace:
        return self._outcome(self.resume_status)


def _write_run_state(
    root: Path,
    *,
    route: str,
    status: str,
    stage: str | None,
    wait: dict[str, object] | None = None,
) -> Path:
    run_dir = root / f"{route}-{status}"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "run_id": run_dir.name,
                "route": {"id": route},
                "status": status,
                "current_stage": stage,
                "wait": wait,
                "pending_records": [],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return run_dir


def _directory_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _benchmark_manifest_payload(*, mode: str = "live") -> dict[str, object]:
    return {
        "schema_version": 1,
        "benchmark_id": "creative-benchmark-001",
        "mode": mode,
        "model": "gpt-test",
        "reasoning_effort": "high",
        "cases": [
            {
                "case_id": "case-one",
                "challenge_path": "inputs/challenge.md",
                "creative_brief_path": "inputs/brief.md",
                "review_fixture_path": (
                    "inputs/review.json" if mode == "fixture" else None
                ),
                "comparison_kind": "workflow_vs_oneshot",
            }
        ],
        "max_portfolio_size": 8,
    }


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeWorkflow.create_calls.clear()
        _FakeCreativeWorkflow.create_calls.clear()
        _FakeCreativeWorkflow.open_calls.clear()
        _FakeCreativeWorkflow.execute_status = "waiting"
        _FakeCreativeWorkflow.resume_status = "completed"

    def invoke(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_run_uses_v1_defaults_and_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(cli, "UsefulIdeaWorkflow", _FakeWorkflow):
                code, stdout, stderr = self.invoke(
                    [
                        "run",
                        "--prompt",
                        "Help a real user",
                        "--runs-dir",
                        directory,
                        "--run-id",
                        "cli-test",
                        "--max-audiences",
                        "4",
                        "--researchers-per-audience",
                        "2",
                        "--idea-generators-per-problem",
                        "6",
                    ]
                )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("Idea Cards:", stdout)
        prompt, _, settings, _, run_id = _FakeWorkflow.create_calls[0]
        self.assertEqual(prompt, "Help a real user")
        self.assertEqual(run_id, "cli-test")
        self.assertEqual(settings.max_audiences, 4)
        self.assertEqual(settings.researchers_per_audience, 2)
        self.assertEqual(settings.idea_generators_per_problem, 6)
        codex_config = _FakeWorkflow.create_calls[0][3]
        self.assertEqual(codex_config.model, "gpt-5.6-terra")
        self.assertEqual(codex_config.reasoning_effort, "high")

    def test_default_fanout_is_five_audiences_one_researcher_three_generators(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(cli, "UsefulIdeaWorkflow", _FakeWorkflow):
                code, _, _ = self.invoke(
                    ["run", "--prompt", "Prompt", "--runs-dir", directory]
                )
        self.assertEqual(code, 0)
        settings = _FakeWorkflow.create_calls[0][2]
        self.assertEqual(settings.max_audiences, 5)
        self.assertEqual(settings.researchers_per_audience, 1)
        self.assertEqual(settings.idea_generators_per_problem, 3)

    def test_explicit_useful_route_matches_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(cli, "UsefulIdeaWorkflow", _FakeWorkflow):
                default_result = self.invoke(
                    ["run", "--prompt", "Prompt", "--runs-dir", directory]
                )
                default_settings = _FakeWorkflow.create_calls[-1][2]
                explicit_result = self.invoke(
                    [
                        "run",
                        "--route",
                        "useful",
                        "--prompt",
                        "Prompt",
                        "--runs-dir",
                        directory,
                    ]
                )
                explicit_settings = _FakeWorkflow.create_calls[-1][2]
        self.assertEqual(default_result, explicit_result)
        self.assertEqual(default_settings, explicit_settings)

    def test_creative_route_uses_brief_memory_and_typed_wait_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                cli,
                "CreativeIdeaWorkflow",
                _FakeCreativeWorkflow,
            ):
                code, stdout, stderr = self.invoke(
                    [
                        "run",
                        "--route",
                        "creative",
                        "--prompt",
                        "Prompt",
                        "--runs-dir",
                        directory,
                        "--run-id",
                        "creative-cli",
                        "--creative-brief",
                        "Make it uncanny but legible.",
                        "--idea-memory",
                        "off",
                        "--run-timeout",
                        "42",
                    ]
                )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            stdout,
            (
                f"Run directory: {directory}/creative-cli\n"
                "Creative status: waiting\n"
                f"Review batch: {directory}/creative-cli/artifacts/"
                "review-batch.json\n"
                f"Next: hacksome review {directory}/creative-cli\n"
            ),
        )
        call = _FakeCreativeWorkflow.create_calls[0]
        self.assertEqual(call["challenge"], "Prompt")
        self.assertEqual(call["creative_brief"], "Make it uncanny but legible.")
        self.assertIsNone(call["creative_brief_file"])
        self.assertEqual(call["run_timeout_seconds"], 42.0)
        settings = call["settings"]
        self.assertEqual(settings.idea_memory_mode, "off")
        config = call["codex_config"]
        self.assertEqual(config.default_timeout_seconds, 1200)

    def test_useful_options_are_rejected_for_creative_route(self) -> None:
        with patch.object(cli, "CreativeIdeaWorkflow") as workflow:
            code, _, stderr = self.invoke(
                [
                    "run",
                    "--route",
                    "creative",
                    "--prompt",
                    "Prompt",
                    "--max-audiences",
                    "4",
                ]
            )
        self.assertEqual(code, 1)
        self.assertIn("--max-audiences can only be used", stderr)
        workflow.create.assert_not_called()

    def test_creative_options_are_rejected_for_useful_before_create(self) -> None:
        with patch.object(cli, "UsefulIdeaWorkflow") as workflow:
            code, _, stderr = self.invoke(
                [
                    "run",
                    "--prompt",
                    "Prompt",
                    "--creative-brief",
                    "Wrong route",
                ]
            )
        self.assertEqual(code, 1)
        self.assertIn("--creative-brief can only be used with --route creative", stderr)
        workflow.create.assert_not_called()

    def test_creative_brief_sources_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            self.invoke(
                [
                    "run",
                    "--route",
                    "creative",
                    "--prompt",
                    "Prompt",
                    "--creative-brief",
                    "literal",
                    "--creative-brief-file",
                    "brief.md",
                ]
            )
        self.assertEqual(raised.exception.code, 2)

    def test_model_and_reasoning_effort_can_be_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(cli, "UsefulIdeaWorkflow", _FakeWorkflow):
                code, _, _ = self.invoke(
                    [
                        "run",
                        "--prompt",
                        "Prompt",
                        "--runs-dir",
                        directory,
                        "--model",
                        "gpt-5.6-sol",
                        "--reasoning-effort",
                        "xhigh",
                    ]
                )
        self.assertEqual(code, 0)
        codex_config = _FakeWorkflow.create_calls[0][3]
        self.assertEqual(codex_config.model, "gpt-5.6-sol")
        self.assertEqual(codex_config.reasoning_effort, "xhigh")

    def test_challenge_file_is_read_as_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "challenge.md"
            path.write_text("真实赛题\n", encoding="utf-8")
            with patch.object(cli, "UsefulIdeaWorkflow", _FakeWorkflow):
                code, _, stderr = self.invoke(
                    ["run", str(path), "--runs-dir", directory]
                )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(_FakeWorkflow.create_calls[0][0], "真实赛题\n")

    def test_v1_rejects_more_than_five_audiences(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            self.invoke(["run", "--prompt", "Prompt", "--max-audiences", "6"])
        self.assertEqual(raised.exception.code, 2)

    def test_creative_finalizing_run_is_recoverable_and_nonzero(self) -> None:
        _FakeCreativeWorkflow.execute_status = "finalizing"
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                cli,
                "CreativeIdeaWorkflow",
                _FakeCreativeWorkflow,
            ):
                code, stdout, stderr = self.invoke(
                    [
                        "run",
                        "--route",
                        "creative",
                        "--prompt",
                        "Prompt",
                        "--runs-dir",
                        directory,
                    ]
                )
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertIn("Creative status: finalizing", stdout)
        self.assertIn("recoverable from its frozen publication plan", stdout)

    def test_status_and_validate_are_offline(self) -> None:
        status_payload = {
            "run_id": "run-1",
            "status": "completed",
            "current_stage": None,
            "task_counts": {"succeeded": 4},
            "decision_count": 2,
            "idea_card_count": 1,
        }
        with patch.object(cli, "inspect_run", return_value=status_payload):
            code, stdout, _ = self.invoke(["status", "runs/run-1"])
        self.assertEqual(code, 0)
        self.assertEqual(
            stdout,
            (
                "Run: run-1\n"
                "Status: completed\n"
                "Current stage: -\n"
                "Tasks: succeeded=4\n"
                "Decisions: 2\n"
                "Idea Cards: 1\n"
            ),
        )

        with patch.object(cli, "inspect_run", return_value=status_payload):
            code, stdout, stderr = self.invoke(
                ["status", "runs/run-1", "--json"]
            )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            stdout,
            (
                "{\n"
                '  "current_stage": null,\n'
                '  "decision_count": 2,\n'
                '  "idea_card_count": 1,\n'
                '  "run_id": "run-1",\n'
                '  "status": "completed",\n'
                '  "task_counts": {\n'
                '    "succeeded": 4\n'
                "  }\n"
                "}\n"
            ),
        )

        with patch.object(cli, "validate_run", return_value=[]):
            code, stdout, _ = self.invoke(["validate", "runs/run-1"])
        self.assertEqual(code, 0)
        self.assertIn("Run is valid", stdout)

    def test_creative_status_renders_route_memory_review_finalization_and_report(
        self,
    ) -> None:
        payload = {
            "route_id": "creative",
            "run_id": "creative-1",
            "status": "waiting",
            "current_stage": "creative-human-review",
            "task_counts": {"succeeded": 12},
            "concept_counts": {
                "base_generated": 4,
                "final": 0,
                "generated_total": 5,
                "hook_passed": 3,
                "memory_challengers": 1,
                "shortlisted": 2,
            },
            "memory": {
                "mode": "auto",
                "status": "succeeded",
                "eligible_entry_count": 7,
                "selected_cue_count": 2,
            },
            "review": {
                "status": "closed",
                "round_id": "creative-review-round-001",
                "reviewer_count": 3,
                "covered_concept_count": 2,
                "shortlist_count": 2,
                "resumable": True,
            },
            "finalization": {
                "status": "not_started",
                "published_artifact_count": 0,
                "planned_artifact_count": 0,
                "resumable": False,
            },
            "report_ref": None,
            "partial_report_ref": "creative-partial-report-json",
        }
        with patch.object(cli, "inspect_run", return_value=payload):
            code, stdout, stderr = self.invoke(
                ["status", "runs/creative-1"]
            )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("Route: creative\n", stdout)
        self.assertIn(
            "Memory: mode=auto, status=succeeded, entries=7, cues=2\n",
            stdout,
        )
        self.assertIn(
            "Review: status=closed, round=creative-review-round-001, "
            "reviewers=3, coverage=2/2, resumable=yes\n",
            stdout,
        )
        self.assertIn(
            "Finalization: status=not_started, published=0/0, resumable=no\n",
            stdout,
        )
        self.assertIn("Report: creative-partial-report-json\n", stdout)

    def test_review_serves_waiting_creative_run_without_real_socket(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = _write_run_state(
                Path(directory),
                route="creative",
                status="waiting",
                stage="creative-human-review",
                wait={
                    "kind": "creative_human_review",
                    "status": "open",
                },
            )
            backend = object()
            server = MagicMock()
            server.review_url = "http://127.0.0.1:4321/join/reviewer"
            server.curator_url = "http://127.0.0.1:4321/join/curator"
            with (
                patch.object(cli, "RunReviewBackend", return_value=backend),
                patch.object(
                    cli,
                    "CreativeReviewServer",
                    return_value=server,
                ) as server_class,
                patch.object(cli.webbrowser, "open") as open_browser,
            ):
                code, stdout, stderr = self.invoke(
                    [
                        "review",
                        str(run_dir),
                        "--host",
                        "127.0.0.1",
                        "--public-host",
                        "review.local",
                        "--port",
                        "4321",
                    ]
                )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn(f"Review URL: {server.review_url}\n", stdout)
        self.assertIn(f"Curator URL: {server.curator_url}\n", stdout)
        self.assertIn("Resume with: hacksome resume", stdout)
        open_browser.assert_called_once_with(server.curator_url)
        server.serve_forever.assert_called_once_with()
        server.stop.assert_called_once_with()
        config = server_class.call_args.args[1]
        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.public_host, "review.local")
        self.assertEqual(config.port, 4321)

    def test_review_no_open_skips_browser_and_rejects_non_waiting_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            waiting = _write_run_state(
                root,
                route="creative",
                status="waiting",
                stage="creative-human-review",
                wait={
                    "kind": "creative_human_review",
                    "status": "open",
                },
            )
            server = MagicMock(
                review_url="http://review",
                curator_url="http://curator",
            )
            with (
                patch.object(cli, "RunReviewBackend", return_value=object()),
                patch.object(cli, "CreativeReviewServer", return_value=server),
                patch.object(cli.webbrowser, "open") as open_browser,
            ):
                code, _, warning = self.invoke(
                    [
                        "review",
                        str(waiting),
                        "--host",
                        "0.0.0.0",
                        "--public-host",
                        "review.local",
                        "--no-open",
                    ]
                )
            self.assertEqual(code, 0)
            open_browser.assert_not_called()
            self.assertIn("WARNING: this server has no TLS", warning)

            completed = _write_run_state(
                root,
                route="creative",
                status="completed",
                stage=None,
            )
            before = _directory_bytes(completed)
            with patch.object(cli, "RunReviewBackend") as backend_cls:
                code, _, stderr = self.invoke(["review", str(completed)])
            self.assertEqual(code, 1)
            self.assertIn("waiting at human review", stderr)
            self.assertEqual(_directory_bytes(completed), before)
            backend_cls.assert_not_called()

    def test_resume_dispatches_closed_wait_completed_and_finalizing(self) -> None:
        cases = (
            (
                "waiting",
                "creative-human-review",
                {
                    "kind": "creative_human_review",
                    "status": "closed",
                },
                "waiting",
                0,
            ),
            ("completed", None, None, "completed", 0),
            (
                "running",
                "creative-finalization",
                None,
                "finalizing",
                1,
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (
                status,
                stage,
                wait,
                outcome_status,
                expected_code,
            ) in enumerate(cases):
                with self.subTest(status=status, outcome=outcome_status):
                    run_dir = _write_run_state(
                        root,
                        route="creative",
                        status=status,
                        stage=stage,
                        wait=wait,
                    )
                    renamed = run_dir.with_name(f"{run_dir.name}-{index}")
                    run_dir.rename(renamed)
                    _FakeCreativeWorkflow.resume_status = outcome_status
                    with patch.object(
                        cli,
                        "CreativeIdeaWorkflow",
                        _FakeCreativeWorkflow,
                    ):
                        code, stdout, stderr = self.invoke(
                            ["resume", str(renamed)]
                        )
                    self.assertEqual(code, expected_code)
                    self.assertEqual(stderr, "")
                    self.assertIn(
                        f"Creative status: {outcome_status}",
                        stdout,
                    )
                    self.assertEqual(
                        _FakeCreativeWorkflow.open_calls[-1],
                        renamed.resolve(),
                    )
                    if outcome_status == "finalizing":
                        self.assertIn("recoverable", stdout)

    def test_resume_rejects_useful_and_illegal_states_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            useful = _write_run_state(
                root,
                route="useful",
                status="completed",
                stage=None,
            )
            failed = _write_run_state(
                root,
                route="creative",
                status="failed",
                stage="creative-c5w-novelty-scan",
            )
            open_wait = _write_run_state(
                root,
                route="creative",
                status="waiting",
                stage="creative-human-review",
                wait={
                    "kind": "creative_human_review",
                    "status": "open",
                },
            )
            for run_dir in (useful, failed, open_wait):
                with self.subTest(run_dir=run_dir.name):
                    before = _directory_bytes(run_dir)
                    with patch.object(
                        cli,
                        "CreativeIdeaWorkflow",
                        _FakeCreativeWorkflow,
                    ):
                        code, _, stderr = self.invoke(
                            ["resume", str(run_dir)]
                        )
                    self.assertEqual(code, 1)
                    self.assertNotEqual(stderr, "")
                    self.assertEqual(_directory_bytes(run_dir), before)
            self.assertEqual(_FakeCreativeWorkflow.open_calls, [])

    def test_benchmark_manifest_is_strictly_validated_and_only_planned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs"
            inputs.mkdir()
            (inputs / "challenge.md").write_text(
                "Build something surprising.\n",
                encoding="utf-8",
            )
            (inputs / "brief.md").write_text(
                "Aim for a legible reveal.\n",
                encoding="utf-8",
            )
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(_benchmark_manifest_payload()),
                encoding="utf-8",
            )
            before = _directory_bytes(root)
            code, stdout, stderr = self.invoke(
                [
                    "benchmark",
                    "--route",
                    "creative",
                    str(manifest),
                ]
            )
            after = _directory_bytes(root)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(before, after)
        self.assertIn(
            "Creative benchmark plan validated; no arms were started.\n",
            stdout,
        )
        self.assertIn(
            "workflow(memory=off) vs oneshot(memory=off)",
            stdout,
        )
        self.assertIn("Next: connect a benchmark execution controller", stdout)

    def test_benchmark_rejects_unknown_manifest_fields_and_missing_route(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            payload = _benchmark_manifest_payload()
            payload["unknown"] = True
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            code, _, stderr = self.invoke(
                ["benchmark", "--route", "creative", str(manifest)]
            )
            self.assertEqual(code, 1)
            self.assertIn("unknown fields", stderr)

            code, _, stderr = self.invoke(["benchmark", str(manifest)])
            self.assertEqual(code, 1)
            self.assertIn("requires --route creative", stderr)

    def test_benchmark_continue_validates_bundle_and_worksheet_without_writes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bench_dir = Path(directory) / "bench"
            bench_dir.mkdir()
            manifest_payload = _benchmark_manifest_payload()
            (bench_dir / "benchmark-manifest.json").write_text(
                json.dumps(manifest_payload),
                encoding="utf-8",
            )
            packet_payload = {
                "schema_version": 1,
                "benchmark_id": "creative-benchmark-001",
                "cases": [
                    {
                        "case_id": "case-one",
                        "arm_a_ideas": [],
                        "arm_a_no_idea": True,
                        "arm_b_ideas": [],
                        "arm_b_no_idea": True,
                    }
                ],
            }
            packet_bytes = canonical_json_bytes(packet_payload) + b"\n"
            packet_sha256 = sha256_bytes(packet_bytes)
            (bench_dir / "blind-review-packet.json").write_bytes(packet_bytes)
            (bench_dir / "blind-review-packet.md").write_text(
                "# Blind packet\n",
                encoding="utf-8",
            )
            arm_map = {
                "schema_version": 1,
                "benchmark_id": "creative-benchmark-001",
                "packet_sha256": packet_sha256,
                "cases": [
                    {
                        "case_id": "case-one",
                        "arm_a_arm_id": "case-one:arm-1",
                        "arm_b_arm_id": "case-one:arm-2",
                        "arm_a_ideas": [],
                        "arm_b_ideas": [],
                    }
                ],
            }
            (bench_dir / "arm-map.json").write_bytes(
                canonical_json_bytes(arm_map) + b"\n"
            )
            worksheet = Path(directory) / "worksheet.json"
            worksheet.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "benchmark_id": "creative-benchmark-001",
                        "packet_sha256": packet_sha256,
                        "review_id": "review-001",
                        "reviewer_name": "Percy",
                        "cases": [
                            {
                                "case_id": "case-one",
                                "arm_a_ideas": [],
                                "arm_b_ideas": [],
                                "best_idea": {
                                    "arm_a": None,
                                    "arm_b": None,
                                },
                                "portfolio_preference": "neither",
                                "reason": "Neither arm produced an Idea.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            before = _directory_bytes(Path(directory))
            code, stdout, stderr = self.invoke(
                [
                    "benchmark",
                    "--continue",
                    str(bench_dir),
                    "--worksheet",
                    str(worksheet),
                ]
            )
            after = _directory_bytes(Path(directory))
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(before, after)
        self.assertIn("no execution-state controller", stderr)
        self.assertIn("validated but not persisted", stderr)
        self.assertIn("No arm was started or resumed", stderr)

    def test_reconcile_flushes_only_pending_records(self) -> None:
        fake_hub = MagicMock()
        fake_hub.reconcile_pending.return_value = 2
        with patch.object(cli, "RunHub", return_value=fake_hub):
            code, stdout, stderr = self.invoke(["reconcile", "runs/run-1"])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, "Reconciled records: 2\n")
        fake_hub.reconcile_pending.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
