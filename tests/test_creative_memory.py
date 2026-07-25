from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from hacksome.creative.contracts import CreativeWorkflowSettings
from hacksome.creative.memory import (
    MEMORY_RECORD_ARTIFACT_TYPE,
    IdeaMemorySnapshot,
    MemoryCapsule,
    MemoryRecord,
    MemoryRemixSlot,
    MemoryStageSummary,
    MemoryTaskSlot,
    MemoryValidationError,
    build_memory_snapshot,
    copy_risk_reasons,
    deduplicate_memory_cues,
    extract_exact_markdown_section,
    load_memory_snapshot,
    persist_memory_snapshot,
    validate_challenger_count,
    validate_memory_inspiration_packet,
    validate_remix_provenance,
    expected_memory_classification,
)
from hacksome.state import sha256_json, sha256_text


def _json_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def _memory_entry(
    *,
    entry_id: str,
    candidate_ref: str,
    candidate_sha256: str,
    final: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "memory_entry_id": entry_id,
        "source_kind": "final_idea" if final else "concept_revision",
        "source_candidate_ref": candidate_ref,
        "source_candidate_sha256": candidate_sha256,
        "source_concept_refs": [],
        "primary_territory_ref": "creative-territory-01",
        "one_sentence_hook": f"Hook for {entry_id}",
        "audience_action": "The audience turns a physical dial.",
        "core_mechanism": "The dial changes a shared hidden state.",
        "reveal_pattern": "The room discovers it changed the same object.",
        "intended_reaction": "Surprise and delight.",
        "terminal_outcome": "promoted_to_final" if final else "c4_eliminated",
        "reason_codes": [] if final else ["c4_double_invalid"],
        "reason_evidence": [],
        "evidence_refs": [],
        "classification": "positive" if final else "caution",
    }
    return {"capsule_sha256": sha256_json(payload), **payload}


def _write_source_run(
    root: Path,
    *,
    directory_name: str,
    run_id: str,
    created_at: str,
    status: str = "completed",
    route_id: str = "creative",
    contract_version: str = "1",
    report_policy_version: str = "1",
    producer_kind: str = "live",
    zero_idea: bool = False,
    entry_count: int = 1,
) -> Path:
    run_dir = root / directory_name
    memory_dir = run_dir / "artifacts" / "creative" / "memory"
    report_dir = run_dir / "artifacts" / "creative" / "report"
    idea_dir = run_dir / "artifacts" / "creative" / "ideas"
    memory_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    idea_dir.mkdir(parents=True)

    report_id = "creative-idea-report-json"
    report_text = '{"status":"completed"}\n'
    report_path = report_dir / "creative-idea-report.json"
    report_path.write_text(report_text, encoding="utf-8")

    artifacts: dict[str, Any] = {
        report_id: {
            "artifact_id": report_id,
            "artifact_type": "creative_idea_report_json",
            "path": "artifacts/creative/report/creative-idea-report.json",
            "sha256": sha256_text(report_text),
        }
    }
    entries: list[dict[str, Any]] = []
    for index in range(1, entry_count + 1):
        candidate_id = f"creative-idea-{index:03d}"
        candidate_text = f"# Idea {index}\n\nBody {run_id}\n"
        candidate_path = idea_dir / f"{candidate_id}.md"
        candidate_path.write_text(candidate_text, encoding="utf-8")
        candidate_hash = sha256_text(candidate_text)
        artifacts[candidate_id] = {
            "artifact_id": candidate_id,
            "artifact_type": "creative_final_idea",
            "path": f"artifacts/creative/ideas/{candidate_id}.md",
            "sha256": candidate_hash,
        }
        entries.append(
            _memory_entry(
                entry_id=f"memory-{run_id}-{index:03d}",
                candidate_ref=candidate_id,
                candidate_sha256=candidate_hash,
                final=not zero_idea,
            )
        )

    memory_record = {
        "memory_schema_version": 1,
        "source_run_id": run_id,
        "source_route": {"id": "creative", "contract_version": "1"},
        "source_report_artifact_id": report_id,
        "source_report_sha256": sha256_text(report_text),
        "created_at": created_at,
        "producer_kind": producer_kind,
        "zero_reason_code": "all_candidates_failed_hook" if zero_idea else None,
        "challenge_context": {
            "summary": f"Challenge for {run_id}",
            "intended_reactions": "Surprise and delight.",
        },
        "entries": entries,
    }
    memory_text = _json_text(memory_record)
    memory_path = memory_dir / "creative-memory-record.json"
    memory_path.write_text(memory_text, encoding="utf-8")
    memory_id = "creative-memory-record"
    artifacts[memory_id] = {
        "artifact_id": memory_id,
        "artifact_type": MEMORY_RECORD_ARTIFACT_TYPE,
        "path": "artifacts/creative/memory/creative-memory-record.json",
        "sha256": sha256_text(memory_text),
    }
    state = {
        "schema_version": 2,
        "run_id": run_id,
        "route": {
            "id": route_id,
            "contract_version": contract_version,
            "prompt_policy_version": "1",
            "stage_policy_version": "1",
            "report_policy_version": report_policy_version,
        },
        "status": status,
        "created_at": created_at,
        "artifacts": artifacts,
        "result_artifact_ids": [memory_id],
    }
    (run_dir / "run.json").write_text(_json_text(state), encoding="utf-8")
    return run_dir


class CreativeMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def test_off_and_no_history_are_distinct_legal_empty_snapshots(self) -> None:
        off = build_memory_snapshot(
            self.root / "does-not-exist",
            replace(CreativeWorkflowSettings(), idea_memory_mode="off"),
        )
        self.assertEqual(off.mode, "off")
        self.assertEqual(off.empty_reason, "disabled")
        self.assertFalse(off.has_eligible_entries)
        self.assertEqual(off.diagnostics, ())

        empty = build_memory_snapshot(
            self.root / "does-not-exist",
            CreativeWorkflowSettings(),
        )
        self.assertEqual(empty.mode, "auto")
        self.assertEqual(empty.empty_reason, "no_eligible_history")
        self.assertFalse(empty.has_eligible_entries)

    def test_discovery_is_stable_bounded_and_snapshot_is_self_contained(self) -> None:
        runs = self.root / "runs"
        runs.mkdir()
        old = _write_source_run(
            runs,
            directory_name="z-old",
            run_id="old-run",
            created_at="2026-07-20T00:00:00+00:00",
        )
        newest = _write_source_run(
            runs,
            directory_name="a-new",
            run_id="new-run",
            created_at="2026-07-22T00:00:00+00:00",
            entry_count=2,
        )
        settings = replace(
            CreativeWorkflowSettings(),
            max_memory_runs=1,
            max_memory_entries=1,
        )

        snapshot = build_memory_snapshot(
            runs,
            settings,
            source_validator=lambda _path: (),
        )

        self.assertTrue(snapshot.has_eligible_entries)
        self.assertEqual(snapshot.entries[0].memory_ref.source_run_id, "new-run")
        self.assertEqual(snapshot.eligible_entry_count, 1)
        self.assertTrue(snapshot.truncated)
        self.assertEqual(
            {item.code for item in snapshot.diagnostics},
            {"memory_run_limit_reached", "memory_entry_limit_reached"},
        )
        prompt_before = snapshot.capsule_prompt_text()
        for path in newest.rglob("*"):
            if path.is_file():
                path.write_text("tampered after snapshot", encoding="utf-8")
        self.assertEqual(snapshot.capsule_prompt_text(), prompt_before)
        self.assertNotIn(str(runs), prompt_before)
        self.assertTrue(old.is_dir())

    def test_persist_and_load_bind_exact_snapshot_hash(self) -> None:
        runs = self.root / "runs"
        runs.mkdir()
        _write_source_run(
            runs,
            directory_name="source",
            run_id="source-run",
            created_at="2026-07-22T00:00:00+00:00",
        )
        snapshot = build_memory_snapshot(
            runs,
            CreativeWorkflowSettings(),
            source_validator=lambda _path: (),
        )
        run_dir = self.root / "current"
        run_dir.mkdir()

        record = persist_memory_snapshot(snapshot, run_dir)

        self.assertEqual(
            record["path"],
            "state/creative-memory/idea-memory-snapshot.json",
        )
        self.assertEqual(record["mode"], "auto")
        self.assertEqual(record["source"], "runs_dir")
        self.assertEqual(record["eligible_entry_count"], 1)
        loaded = load_memory_snapshot(
            run_dir / record["path"],
            expected_sha256=record["sha256"],
        )
        self.assertEqual(loaded, snapshot)

        snapshot_path = run_dir / record["path"]
        snapshot_path.write_text(
            snapshot_path.read_text(encoding="utf-8") + " ",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(MemoryValidationError, "hash mismatch"):
            load_memory_snapshot(
                snapshot_path,
                expected_sha256=record["sha256"],
            )

    def test_snapshot_byte_limit_drops_tail_entries_deterministically(self) -> None:
        runs = self.root / "runs"
        runs.mkdir()
        _write_source_run(
            runs,
            directory_name="source",
            run_id="source-run",
            created_at="2026-07-22T00:00:00+00:00",
        )
        full = build_memory_snapshot(
            runs,
            CreativeWorkflowSettings(),
            source_validator=lambda _path: (),
        )
        byte_limit = len(full.to_json_bytes()) - 1
        limited = build_memory_snapshot(
            runs,
            replace(
                CreativeWorkflowSettings(),
                max_memory_snapshot_bytes=byte_limit,
            ),
            source_validator=lambda _path: (),
        )
        self.assertFalse(limited.has_eligible_entries)
        self.assertTrue(limited.truncated)
        self.assertLessEqual(len(limited.to_json_bytes()), byte_limit)
        self.assertIn(
            "memory_byte_limit_reached",
            {item.code for item in limited.diagnostics},
        )

    def test_bad_source_kinds_are_diagnostic_not_memory(self) -> None:
        runs = self.root / "runs"
        runs.mkdir()
        _write_source_run(
            runs,
            directory_name="useful",
            run_id="useful-run",
            created_at="2026-07-22T00:00:00+00:00",
            route_id="useful",
        )
        _write_source_run(
            runs,
            directory_name="failed",
            run_id="failed-run",
            created_at="2026-07-22T00:00:00+00:00",
            status="failed",
        )
        _write_source_run(
            runs,
            directory_name="fixture",
            run_id="fixture-run",
            created_at="2026-07-22T00:00:00+00:00",
            producer_kind="fixture",
        )
        _write_source_run(
            runs,
            directory_name="unknown-version",
            run_id="future-run",
            created_at="2026-07-22T00:00:00+00:00",
            contract_version="9",
        )
        corrupt = _write_source_run(
            runs,
            directory_name="corrupt",
            run_id="corrupt-run",
            created_at="2026-07-22T00:00:00+00:00",
        )
        memory_path = (
            corrupt
            / "artifacts"
            / "creative"
            / "memory"
            / "creative-memory-record.json"
        )
        memory_path.write_text("{}", encoding="utf-8")
        (runs / "linked-run").symlink_to(corrupt, target_is_directory=True)

        snapshot = build_memory_snapshot(
            runs,
            CreativeWorkflowSettings(),
            source_validator=lambda _path: (),
        )

        self.assertFalse(snapshot.has_eligible_entries)
        codes = {diagnostic.code for diagnostic in snapshot.diagnostics}
        self.assertTrue(
            {
                "unsupported_route",
                "source_not_completed",
                "fixture_source_rejected",
                "unsupported_contract_version",
                "memory_record_hash_mismatch",
                "source_symlink_rejected",
            }.issubset(codes)
        )

    def test_completed_zero_idea_source_can_contribute_caution(self) -> None:
        runs = self.root / "runs"
        runs.mkdir()
        _write_source_run(
            runs,
            directory_name="zero",
            run_id="zero-run",
            created_at="2026-07-22T00:00:00+00:00",
            zero_idea=True,
        )
        snapshot = build_memory_snapshot(
            runs,
            CreativeWorkflowSettings(),
            source_validator=lambda _path: (),
        )
        self.assertEqual(snapshot.eligible_entry_count, 1)
        self.assertEqual(snapshot.entries[0].entry.classification, "caution")
        self.assertEqual(
            snapshot.entries[0].entry.terminal_outcome, "c4_eliminated"
        )

    def test_symlinked_memory_artifact_is_rejected_without_following_it(self) -> None:
        runs = self.root / "runs"
        runs.mkdir()
        source = _write_source_run(
            runs,
            directory_name="source",
            run_id="source-run",
            created_at="2026-07-22T00:00:00+00:00",
        )
        memory_path = (
            source
            / "artifacts"
            / "creative"
            / "memory"
            / "creative-memory-record.json"
        )
        outside = self.root / "outside-memory.json"
        outside.write_bytes(memory_path.read_bytes())
        memory_path.unlink()
        memory_path.symlink_to(outside)

        snapshot = build_memory_snapshot(
            runs,
            CreativeWorkflowSettings(),
            source_validator=lambda _path: (),
        )

        self.assertFalse(snapshot.has_eligible_entries)
        self.assertIn(
            "memory_record_hash_mismatch",
            {item.code for item in snapshot.diagnostics},
        )

    def test_memory_record_rejects_privacy_and_capsule_hash_drift(self) -> None:
        candidate_hash = sha256_text("candidate")
        entry = _memory_entry(
            entry_id="memory-one",
            candidate_ref="creative-idea-001",
            candidate_sha256=candidate_hash,
        )
        record = {
            "memory_schema_version": 1,
            "source_run_id": "source-run",
            "source_route": {"id": "creative", "contract_version": "1"},
            "source_report_artifact_id": "report",
            "source_report_sha256": sha256_text("report"),
            "created_at": "2026-07-22T00:00:00+00:00",
            "producer_kind": "live",
            "zero_reason_code": None,
            "challenge_context": {
                "summary": "A challenge",
                "intended_reactions": "Surprise",
            },
            "entries": [entry],
        }
        MemoryRecord.from_mapping(record)

        private = {**record, "reviewer_name": "Percy"}
        with self.assertRaisesRegex(MemoryValidationError, "private field"):
            MemoryRecord.from_mapping(private)

        drifted = json.loads(json.dumps(record))
        drifted["entries"][0]["core_mechanism"] = "Changed"
        with self.assertRaisesRegex(MemoryValidationError, "capsule hash mismatch"):
            MemoryRecord.from_mapping(drifted)

    def test_exact_section_extraction_rejects_duplicates_and_local_paths(self) -> None:
        markdown = "# Idea\n\n## One-sentence Hook\n\nExact hook.\n\n## Next\n\nBody\n"
        self.assertEqual(
            extract_exact_markdown_section(markdown, "One-sentence Hook"),
            "Exact hook.",
        )
        with self.assertRaisesRegex(MemoryValidationError, "exactly once"):
            extract_exact_markdown_section(
                markdown + "\n## One-sentence Hook\n\nAgain\n",
                "One-sentence Hook",
            )
        with self.assertRaisesRegex(MemoryValidationError, "absolute local path"):
            extract_exact_markdown_section(
                "## One-sentence Hook\n\nRead /Users/percy/private.txt\n",
                "One-sentence Hook",
            )

    def test_memory_stage_summary_enforces_optional_failure_matrix(self) -> None:
        disabled = MemoryStageSummary(
            status="disabled",
            recall=MemoryTaskSlot("not_started", None, None),
            selected_cue_ids=(),
            remix_slots=(
                MemoryRemixSlot(1, "not_started", None, None, None),
                MemoryRemixSlot(2, "not_started", None, None, None),
            ),
        )
        self.assertEqual(
            MemoryStageSummary.from_mapping(disabled.to_dict()), disabled
        )

        partial = MemoryStageSummary(
            status="optional_failed",
            recall=MemoryTaskSlot("succeeded", "recall-task", None),
            selected_cue_ids=("memory-cue-01",),
            remix_slots=(
                MemoryRemixSlot(
                    1,
                    "succeeded",
                    "remix-task-1",
                    "creative-concept-m01-r001",
                    None,
                ),
                MemoryRemixSlot(
                    2,
                    "failed",
                    "remix-task-2",
                    None,
                    "diagnostic-2",
                ),
            ),
        )
        self.assertEqual(partial.status, "optional_failed")
        no_challenger = MemoryStageSummary(
            status="completed",
            recall=MemoryTaskSlot("succeeded", "recall-task", None),
            selected_cue_ids=("memory-cue-01",),
            remix_slots=(
                MemoryRemixSlot(
                    1,
                    "succeeded",
                    "remix-task-1",
                    None,
                    None,
                ),
            ),
        )
        self.assertEqual(
            MemoryStageSummary.from_mapping(no_challenger.to_dict()),
            no_challenger,
        )
        with self.assertRaisesRegex(MemoryValidationError, "cannot start"):
            MemoryStageSummary(
                status="optional_failed",
                recall=MemoryTaskSlot(
                    "failed", "recall-task", "recall-diagnostic"
                ),
                selected_cue_ids=(),
                remix_slots=(
                    MemoryRemixSlot(
                        1,
                        "succeeded",
                        "remix-task",
                        "creative-concept-m01-r001",
                        None,
                    ),
                ),
            )

    def test_recall_and_remix_helpers_reject_external_or_copied_sources(self) -> None:
        runs = self.root / "runs"
        runs.mkdir()
        _write_source_run(
            runs,
            directory_name="source",
            run_id="source-run",
            created_at="2026-07-22T00:00:00+00:00",
        )
        snapshot = build_memory_snapshot(
            runs,
            CreativeWorkflowSettings(),
            source_validator=lambda _path: (),
        )
        memory_ref = snapshot.entries[0].memory_ref
        packet = {
            "cues": [
                {
                    "cue_id": "memory-cue-01",
                    "source_memory_refs": [memory_ref.to_dict()],
                    "role": "inspire",
                    "transferable_pattern": "Shared hidden state",
                    "why_relevant": "It fits the current physical Atom.",
                    "current_atom_refs": ["creative-atom-t01-01"],
                    "related_concept_refs": [],
                    "elements_that_must_not_be_copied": ["The exact dial"],
                }
            ],
            "no_relevant_memory_reason": None,
        }
        cues = validate_memory_inspiration_packet(
            packet,
            snapshot=snapshot,
            current_atom_refs=("creative-atom-t01-01",),
        )
        self.assertEqual(len(cues), 1)
        self.assertEqual(deduplicate_memory_cues((*cues, *cues)), cues)

        validate_remix_provenance(
            current_atom_refs=("creative-atom-t01-01",),
            memory_source_refs=(memory_ref,),
            cue_refs=("memory-cue-01",),
            primary_territory_ref="creative-territory-01",
            atom_territories={
                "creative-atom-t01-01": "creative-territory-01"
            },
            snapshot=snapshot,
            cues=cues,
        )
        self.assertEqual(
            copy_risk_reasons(
                candidate_hook=snapshot.entries[0].entry.one_sentence_hook,
                candidate_mechanism=snapshot.entries[0].entry.core_mechanism,
                candidate_reveal=snapshot.entries[0].entry.reveal_pattern,
                source_capsules=snapshot.entries,
            ),
            ("normalized_hook_match", "mechanism_reveal_copy"),
        )
        self.assertEqual(
            validate_challenger_count(
                ("creative-concept-m01-r001", "creative-concept-m02-r001")
            ),
            ("creative-concept-m01-r001", "creative-concept-m02-r001"),
        )
        with self.assertRaisesRegex(MemoryValidationError, "count exceeds"):
            validate_challenger_count(
                (
                    "creative-concept-m01-r001",
                    "creative-concept-m02-r001",
                    "creative-concept-m03-r001",
                )
            )

        foreign_ref = replace(memory_ref, source_run_id="foreign-run")
        bad_packet = json.loads(json.dumps(packet))
        bad_packet["cues"][0]["source_memory_refs"] = [foreign_ref.to_dict()]
        with self.assertRaisesRegex(MemoryValidationError, "outside"):
            validate_memory_inspiration_packet(
                bad_packet,
                snapshot=snapshot,
                current_atom_refs=("creative-atom-t01-01",),
            )

    def test_capsule_round_trip_rechecks_composite_hash(self) -> None:
        runs = self.root / "runs"
        runs.mkdir()
        _write_source_run(
            runs,
            directory_name="source",
            run_id="source-run",
            created_at="2026-07-22T00:00:00+00:00",
        )
        snapshot = build_memory_snapshot(
            runs,
            CreativeWorkflowSettings(),
            source_validator=lambda _path: (),
        )
        capsule = snapshot.entries[0]
        self.assertEqual(MemoryCapsule.from_mapping(capsule.to_dict()), capsule)
        drifted = capsule.to_dict()
        drifted["challenge_context"]["summary"] = "Changed"
        with self.assertRaisesRegex(MemoryValidationError, "capsule hash mismatch"):
            MemoryCapsule.from_mapping(drifted)

    def test_snapshot_mapping_rejects_hidden_raw_feedback(self) -> None:
        snapshot = IdeaMemorySnapshot(
            schema_version=1,
            mode="auto",
            created_from="runs_dir",
            source_records=(),
            entries=(),
            diagnostics=(),
            truncated=False,
            empty_reason="no_eligible_history",
        )
        raw = snapshot.to_dict()
        raw["raw_feedback"] = "secret"
        with self.assertRaisesRegex(MemoryValidationError, "private field"):
            IdeaMemorySnapshot.from_mapping(raw)

    def test_all_software_demo_failures_remain_distinct_cautions(self) -> None:
        reasons = (
            "core_not_software_first",
            "requires_custom_hardware_or_fabrication",
            "core_is_manual_performance_or_installation",
            "no_runnable_end_to_end_demo_path",
            "requires_unavailable_dependency_or_permission",
            "not_buildable_within_hackathon_budget",
            "demo_does_not_prove_core_mechanism",
        )

        for reason in reasons:
            with self.subTest(reason=reason):
                self.assertEqual(
                    expected_memory_classification(
                        source_kind="concept_revision",
                        terminal_outcome="eliminated",
                        reason_codes=(
                            "c4_software_demo_invalid",
                            reason,
                        ),
                    ),
                    "caution",
                )


if __name__ == "__main__":
    unittest.main()
