from __future__ import annotations

import json
import unittest
from dataclasses import replace
from typing import Any

from hacksome.stages.ideation.creative.benchmark import (
    ArmMetrics,
    BenchmarkArmPlan,
    BenchmarkArmResult,
    BenchmarkCase,
    BenchmarkManifest,
    BlindReviewPacket,
    CreativeBenchmarkError,
    FrozenBenchmarkMemory,
    PortfolioIdea,
    build_blind_packet,
    import_worksheet,
    plan_case_arms,
    summarize_benchmark,
    validate_arm_results,
)
from hacksome.core.state import canonical_json_bytes, sha256_bytes, sha256_text


def _case(
    case_id: str,
    comparison_kind: str,
    *,
    mode: str,
) -> BenchmarkCase:
    return BenchmarkCase(
        case_id=case_id,
        challenge_path=f"fixtures/{case_id}/challenge.md",
        creative_brief_path=f"fixtures/{case_id}/brief.md",
        review_fixture_path=(
            f"fixtures/{case_id}/review.json"
            if mode == "fixture"
            else None
        ),
        comparison_kind=comparison_kind,  # type: ignore[arg-type]
    )


def _manifest(
    *,
    mode: str = "live",
    cases: tuple[BenchmarkCase, ...] | None = None,
) -> BenchmarkManifest:
    selected = cases or (
        _case("case-zero", "workflow_vs_oneshot", mode=mode),
        _case("case-one", "memory_ablation", mode=mode),
        _case("case-many", "workflow_vs_oneshot", mode=mode),
    )
    return BenchmarkManifest(
        schema_version=1,
        benchmark_id="benchmark-creative-001",
        mode=mode,  # type: ignore[arg-type]
        model="gpt-test",
        reasoning_effort="high",
        cases=selected,
    )


def _memory(case_id: str, *, source_run_ids: tuple[str, ...] = ()) -> FrozenBenchmarkMemory:
    content = canonical_json_bytes(
        {
            "schema_version": 1,
            "case_id": case_id,
            "entries": ["frozen-before-arms"],
        }
    )
    return FrozenBenchmarkMemory(
        case_id=case_id,
        snapshot_ref=f"benchmark-memory-{case_id}",
        snapshot_sha256=sha256_bytes(content),
        snapshot_bytes=content,
        source_run_ids=source_run_ids,
    )


def _idea(index: int) -> PortfolioIdea:
    markdown = (
        f"# Blind Concept {index}\n\n"
        "## One-sentence Hook\n\n"
        f"A participant triggers an understandable reveal number {index}.\n"
    )
    return PortfolioIdea(
        idea_id=f"creative-idea-{index:03d}",
        idea_card_sha256=sha256_text(markdown),
        blind_markdown=markdown,
    )


def _metrics(
    *,
    candidate_count: int = 4,
    review_receipt_count: int = 2,
) -> ArmMetrics:
    return ArmMetrics(
        token_count=1200,
        wall_time_ms=900,
        task_count=6,
        candidate_count=candidate_count,
        shortlist_count=min(candidate_count, 2),
        review_receipt_count=review_receipt_count,
        memory_source_diagnostic_count=1,
        selected_cue_count=1,
        challenger_count=1,
        copy_reject_count=0,
    )


def _result(
    manifest: BenchmarkManifest,
    plan: BenchmarkArmPlan,
    *,
    portfolio_count: int,
    status: str = "completed",
) -> BenchmarkArmResult:
    return BenchmarkArmResult(
        case_id=plan.case_id,
        arm_id=plan.arm_id,
        source_run_id=f"run:{plan.arm_id}",
        status=status,  # type: ignore[arg-type]
        memory_policy=plan.memory_policy,
        memory_snapshot_sha256=plan.memory_snapshot_sha256,
        consumed_memory_snapshot=plan.consumes_memory_snapshot,
        portfolio=(
            tuple(_idea(index) for index in range(1, portfolio_count + 1))
            if status == "completed"
            else ()
        ),
        metrics=_metrics(
            candidate_count=max(portfolio_count, 1),
            review_receipt_count=0 if plan.arm_kind == "oneshot" else 2,
        ),
        review_producer_kind=(
            "none"
            if plan.arm_kind == "oneshot"
            else manifest.mode
        ),
    )


def _complete_inputs(
    manifest: BenchmarkManifest,
) -> tuple[
    tuple[FrozenBenchmarkMemory, ...],
    tuple[BenchmarkArmResult, ...],
]:
    portfolio_sizes = {
        "case-zero": (0, 0),
        "case-one": (1, 1),
        "case-many": (3, 2),
    }
    memories: list[FrozenBenchmarkMemory] = []
    results: list[BenchmarkArmResult] = []
    for case in manifest.ordered_cases:
        memory = _memory(case.case_id, source_run_ids=("historical-run",))
        memories.append(memory)
        plans = plan_case_arms(case, memory)
        sizes = portfolio_sizes.get(case.case_id, (1, 1))
        results.extend(
            _result(
                manifest,
                plan,
                portfolio_count=size,
            )
            for plan, size in zip(plans, sizes, strict=True)
        )
    return tuple(memories), tuple(results)


def _worksheet_payload(
    packet: BlindReviewPacket,
    *,
    review_id: str = "benchmark-review-001",
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for case in packet.case_maps:
        arm_a = [
            {
                "blind_idea_id": item.blind_idea_id,
                "retell": f"Retell for {item.blind_idea_id}",
                "share_target": (
                    f"a teammate interested in {item.blind_idea_id}"
                ),
                "surprise_source": "The surprise comes from a legible mechanism.",
                "interaction_desire": "yes",
            }
            for item in case.arm_a_ideas
        ]
        arm_b = [
            {
                "blind_idea_id": item.blind_idea_id,
                "retell": f"Retell for {item.blind_idea_id}",
                "share_target": "",
                "surprise_source": "The reveal is clear but less surprising.",
                "interaction_desire": "maybe",
            }
            for item in case.arm_b_ideas
        ]
        cases.append(
            {
                "case_id": case.case_id,
                "arm_a_ideas": arm_a,
                "arm_b_ideas": arm_b,
                "best_idea": {
                    "arm_a": (
                        case.arm_a_ideas[0].blind_idea_id
                        if case.arm_a_ideas
                        else None
                    ),
                    "arm_b": (
                        case.arm_b_ideas[0].blind_idea_id
                        if case.arm_b_ideas
                        else None
                    ),
                },
                "portfolio_preference": "arm_a",
                "reason": "Arm A has the clearer interaction.",
            }
        )
    return {
        "schema_version": 1,
        "benchmark_id": packet.benchmark_id,
        "packet_sha256": packet.packet_sha256,
        "review_id": review_id,
        "reviewer_name": "Percy",
        "cases": cases,
    }


class CreativeBenchmarkTests(unittest.TestCase):
    def test_typed_manifest_round_trip_is_strict_and_stably_ordered(self) -> None:
        manifest = _manifest()
        mapping = manifest.to_dict()
        replay = BenchmarkManifest.from_mapping(mapping)

        self.assertEqual(replay.to_dict(), mapping)
        self.assertEqual(
            [item["case_id"] for item in mapping["cases"]],
            ["case-many", "case-one", "case-zero"],
        )
        drifted = {**mapping, "unexpected": True}
        with self.assertRaisesRegex(
            CreativeBenchmarkError,
            "unknown fields",
        ):
            BenchmarkManifest.from_mapping(drifted)

    def test_comparison_kinds_freeze_shared_snapshot_before_arms(self) -> None:
        manifest = _manifest()
        workflow_case, ablation_case = manifest.cases[:2]
        workflow_memory = _memory(workflow_case.case_id)
        ablation_memory = _memory(ablation_case.case_id)

        workflow_plans = plan_case_arms(workflow_case, workflow_memory)
        self.assertEqual(
            [(item.arm_kind, item.memory_policy) for item in workflow_plans],
            [("workflow", "off"), ("oneshot", "off")],
        )
        self.assertFalse(
            any(item.consumes_memory_snapshot for item in workflow_plans)
        )
        ablation_plans = plan_case_arms(ablation_case, ablation_memory)
        self.assertEqual(
            [(item.arm_kind, item.memory_policy) for item in ablation_plans],
            [("workflow", "auto"), ("workflow", "off")],
        )
        self.assertTrue(ablation_plans[0].consumes_memory_snapshot)
        self.assertFalse(ablation_plans[1].consumes_memory_snapshot)
        self.assertEqual(
            {item.memory_snapshot_sha256 for item in ablation_plans},
            {ablation_memory.snapshot_sha256},
        )

    def test_blind_packet_supports_zero_one_and_many_without_mapping_leak(
        self,
    ) -> None:
        manifest = _manifest()
        memories, results = _complete_inputs(manifest)
        packet = build_blind_packet(manifest, memories, results)
        payload = json.loads(packet.packet_json_bytes)
        by_case = {item["case_id"]: item for item in payload["cases"]}

        self.assertTrue(by_case["case-zero"]["arm_a_no_idea"])
        self.assertTrue(by_case["case-zero"]["arm_b_no_idea"])
        self.assertEqual(
            len(by_case["case-one"]["arm_a_ideas"]),
            1,
        )
        self.assertEqual(
            sorted(
                (
                    len(by_case["case-many"]["arm_a_ideas"]),
                    len(by_case["case-many"]["arm_b_ideas"]),
                )
            ),
            [2, 3],
        )
        public_bytes = (
            packet.packet_json_bytes + packet.packet_markdown_bytes
        )
        for result in results:
            self.assertNotIn(result.arm_id.encode(), public_bytes)
            self.assertNotIn(result.source_run_id.encode(), public_bytes)
        for forbidden in (
            b"workflow_vs_oneshot",
            b"memory_ablation",
            b"memory_policy",
            b"token_count",
            b"oneshot",
            b"full-route",
        ):
            self.assertNotIn(forbidden, public_bytes)
        self.assertIn(b"arm_a_arm_id", packet.arm_map_json_bytes)

    def test_packet_and_arm_map_are_stable_under_input_order_changes(self) -> None:
        manifest = _manifest()
        memories, results = _complete_inputs(manifest)
        first = build_blind_packet(manifest, memories, results)
        reversed_results = tuple(
            replace(result, portfolio=tuple(reversed(result.portfolio)))
            for result in reversed(results)
        )
        disturbed_manifest = replace(
            manifest,
            cases=tuple(reversed(manifest.cases)),
        )
        replay = build_blind_packet(
            disturbed_manifest,
            tuple(reversed(memories)),
            reversed_results,
        )

        self.assertEqual(first.packet_sha256, replay.packet_sha256)
        self.assertEqual(first.packet_json_bytes, replay.packet_json_bytes)
        self.assertEqual(
            first.packet_markdown_bytes,
            replay.packet_markdown_bytes,
        )
        self.assertEqual(first.arm_map_json_bytes, replay.arm_map_json_bytes)

    def test_blind_packet_rejects_card_or_private_map_tampering(self) -> None:
        manifest = _manifest()
        memories, results = _complete_inputs(manifest)
        packet = build_blind_packet(manifest, memories, results)
        public = json.loads(packet.packet_json_bytes)
        idea = next(
            idea
            for case in public["cases"]
            for key in ("arm_a_ideas", "arm_b_ideas")
            for idea in case[key]
        )
        idea["idea_card_markdown"] += "\nTampered."
        public_bytes = canonical_json_bytes(public) + b"\n"
        public_hash = sha256_bytes(public_bytes)
        private = json.loads(packet.arm_map_json_bytes)
        private["packet_sha256"] = public_hash

        with self.assertRaisesRegex(
            CreativeBenchmarkError,
            "Idea Card hash mismatch",
        ):
            BlindReviewPacket(
                benchmark_id=packet.benchmark_id,
                mode=packet.mode,
                packet_sha256=public_hash,
                packet_json_bytes=public_bytes,
                packet_markdown_bytes=packet.packet_markdown_bytes,
                arm_map_json_bytes=canonical_json_bytes(private) + b"\n",
                case_maps=packet.case_maps,
            )

        private = json.loads(packet.arm_map_json_bytes)
        private["cases"][0]["arm_a_arm_id"] = "unknown-arm"
        with self.assertRaisesRegex(
            CreativeBenchmarkError,
            "private arm map",
        ):
            BlindReviewPacket(
                benchmark_id=packet.benchmark_id,
                mode=packet.mode,
                packet_sha256=packet.packet_sha256,
                packet_json_bytes=packet.packet_json_bytes,
                packet_markdown_bytes=packet.packet_markdown_bytes,
                arm_map_json_bytes=canonical_json_bytes(private) + b"\n",
                case_maps=packet.case_maps,
            )

    def test_arm_outputs_cannot_flow_back_into_frozen_snapshot(self) -> None:
        manifest = _manifest(
            cases=(
                _case(
                    "case-one",
                    "memory_ablation",
                    mode="live",
                ),
            )
        )
        memory = _memory("case-one")
        plans = plan_case_arms(manifest.cases[0], memory)
        results = tuple(
            _result(manifest, plan, portfolio_count=1) for plan in plans
        )
        leaked_memory = _memory(
            "case-one",
            source_run_ids=(results[0].source_run_id,),
        )

        with self.assertRaisesRegex(
            CreativeBenchmarkError,
            "contains an output run",
        ):
            validate_arm_results(
                manifest,
                manifest.cases[0],
                leaked_memory,
                results,
            )
        drifted = replace(
            results[0],
            memory_snapshot_sha256="0" * 64,
        )
        with self.assertRaisesRegex(
            CreativeBenchmarkError,
            "drifted from its memory arm plan",
        ):
            validate_arm_results(
                manifest,
                manifest.cases[0],
                memory,
                (drifted, results[1]),
            )

    def test_worksheet_validates_hash_case_and_every_blind_idea(self) -> None:
        manifest = _manifest()
        memories, results = _complete_inputs(manifest)
        packet = build_blind_packet(manifest, memories, results)
        payload = _worksheet_payload(packet)
        receipt = import_worksheet(packet, payload)

        tampered_hash = {**payload, "packet_sha256": "0" * 64}
        with self.assertRaisesRegex(
            CreativeBenchmarkError,
            "packet_sha256 mismatch",
        ):
            import_worksheet(packet, tampered_hash)

        missing_case = json.loads(json.dumps(payload))
        missing_case["cases"].pop()
        with self.assertRaisesRegex(
            CreativeBenchmarkError,
            "case set",
        ):
            import_worksheet(packet, missing_case)

        missing_idea = json.loads(json.dumps(payload))
        case_many = next(
            item
            for item in missing_idea["cases"]
            if item["case_id"] == "case-many"
        )
        target_key = (
            "arm_a_ideas"
            if case_many["arm_a_ideas"]
            else "arm_b_ideas"
        )
        case_many[target_key].pop()
        with self.assertRaisesRegex(
            CreativeBenchmarkError,
            "every blind Idea exactly once",
        ):
            import_worksheet(packet, missing_idea)

        self.assertEqual(receipt.review_id, payload["review_id"])

    def test_worksheet_import_is_normalized_idempotent_and_conflict_safe(
        self,
    ) -> None:
        manifest = _manifest()
        memories, results = _complete_inputs(manifest)
        packet = build_blind_packet(manifest, memories, results)
        payload = _worksheet_payload(packet)
        receipt = import_worksheet(packet, payload)

        reordered = json.loads(json.dumps(payload))
        reordered["cases"].reverse()
        for case in reordered["cases"]:
            case["arm_a_ideas"].reverse()
            case["arm_b_ideas"].reverse()
        replay = import_worksheet(
            packet,
            reordered,
            existing_receipts=(receipt,),
        )
        self.assertIs(replay, receipt)

        conflict = json.loads(json.dumps(payload))
        conflict["cases"][0]["reason"] = "Changed decision."
        with self.assertRaisesRegex(
            CreativeBenchmarkError,
            "reused with different content",
        ):
            import_worksheet(
                packet,
                conflict,
                existing_receipts=(receipt,),
            )

    def test_live_summary_waits_for_worksheet_then_reports_proxy_only(
        self,
    ) -> None:
        manifest = _manifest()
        memories, results = _complete_inputs(manifest)
        packet = build_blind_packet(manifest, memories, results)

        pending = summarize_benchmark(
            manifest,
            memories,
            results,
            packet=packet,
        )
        pending_payload = json.loads(pending.json_bytes)
        self.assertEqual(pending.status, "pending_worksheet")
        self.assertEqual(
            pending_payload["cases"][0]["arms"][0]["human_proxy"]["status"],
            "pending",
        )
        self.assertIn(
            "not_evidence_of_real_world_sharing_or_virality",
            pending_payload["human_proxy_interpretation"],
        )

        receipt = import_worksheet(
            packet,
            _worksheet_payload(packet),
        )
        completed = summarize_benchmark(
            manifest,
            memories,
            results,
            packet=packet,
            worksheet_receipts=(receipt,),
        )
        completed_payload = json.loads(completed.json_bytes)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed_payload["worksheet_count"], 1)
        arm = completed_payload["cases"][1]["arms"][0]
        self.assertEqual(arm["human_proxy"]["status"], "computed")
        self.assertIn("token_count", arm["metrics"])
        self.assertIn("wall_time_ms", arm["metrics"])
        self.assertIn("task_count", arm["metrics"])
        self.assertIn("candidate_count", arm["metrics"])
        self.assertIn("shortlist_count", arm["metrics"])
        self.assertGreaterEqual(
            arm["human_proxy"]["metrics"]["retell_response_count"],
            1,
        )

    def test_fixture_summary_omits_human_metrics_and_rejects_worksheet(
        self,
    ) -> None:
        manifest = _manifest(mode="fixture")
        memories, results = _complete_inputs(manifest)
        packet = build_blind_packet(manifest, memories, results)
        summary = summarize_benchmark(
            manifest,
            memories,
            results,
            packet=packet,
        )
        payload = json.loads(summary.json_bytes)

        self.assertEqual(summary.status, "completed")
        self.assertEqual(payload["worksheet_count"], 0)
        for case in payload["cases"]:
            for arm in case["arms"]:
                self.assertEqual(
                    arm["human_proxy"],
                    {
                        "status": "omitted_fixture",
                        "interpretation": (
                            "concept_stage_proxy_only_not_evidence_of_"
                            "real_world_sharing_or_virality"
                        ),
                        "metrics": None,
                    },
                )
        with self.assertRaisesRegex(
            CreativeBenchmarkError,
            "do not accept human worksheets",
        ):
            import_worksheet(packet, _worksheet_payload(packet))

    def test_waiting_live_arm_produces_waiting_summary_without_packet(
        self,
    ) -> None:
        manifest = _manifest(
            cases=(
                _case(
                    "case-zero",
                    "workflow_vs_oneshot",
                    mode="live",
                ),
            )
        )
        memory = _memory("case-zero")
        workflow, oneshot = plan_case_arms(manifest.cases[0], memory)
        results = (
            _result(
                manifest,
                workflow,
                portfolio_count=0,
                status="waiting_for_human",
            ),
            _result(manifest, oneshot, portfolio_count=1),
        )
        summary = summarize_benchmark(
            manifest,
            (memory,),
            results,
        )

        self.assertEqual(summary.status, "waiting_for_human")
        self.assertIsNone(json.loads(summary.json_bytes)["packet_sha256"])


if __name__ == "__main__":
    unittest.main()
