from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import hacksome.hub as hub_module
from hacksome.core.config import CodexConfig
from hacksome.stages.ideation.creative.finalization import (
    FINALIZATION_MANIFEST_PATH,
    FINALIZATION_STAGE,
    FinalizationConflictError,
    FinalizationCoordinator,
    FinalizationManifest,
    FinalizationValidationError,
    RenderedArtifact,
)
from hacksome.stages.ideation.creative.report import RenderedOutput as ReportRenderedOutput
from hacksome.core.hub import RunHub
from hacksome.core.state import read_jsonl


FROZEN_AT = "2026-07-23T12:34:56+00:00"


def _create_hub(root: Path) -> RunHub:
    hub = RunHub.create(
        "Make a surprising interaction.",
        root,
        settings={"route": "creative"},
        codex_config=CodexConfig(),
        run_id="creative-run-001",
        route={
            "id": "creative",
            "contract_version": "1",
            "prompt_policy_version": "1",
            "stage_policy_version": "1",
            "report_policy_version": "1",
        },
    )
    hub.set_run_status(
        "running",
        stage="creative-c6-feedback-complete-internal",
    )
    return hub


def _outputs() -> tuple[RenderedArtifact, ...]:
    return (
        RenderedArtifact(
            artifact_id="creative-report-json",
            artifact_type="creative_idea_report_json",
            final_path=(
                "artifacts/creative/report/creative-idea-report.json"
            ),
            content=b'{"status":"completed"}\n',
            source_refs=("creative-review-batch-r001",),
            metadata={"report_policy_version": "1"},
        ),
        RenderedArtifact(
            artifact_id="creative-support-index",
            artifact_type="creative_idea_card_index",
            final_path="artifacts/creative/idea-cards/index.md",
            content=b"# Final Ideas\n",
            is_result=False,
        ),
        RenderedArtifact(
            artifact_id="creative-memory-record",
            artifact_type="creative_memory_record",
            final_path=(
                "artifacts/creative/memory/"
                "creative-memory-record.json"
            ),
            content=b'{"memory_schema_version":1}\n',
            source_refs=("creative-report-json",),
        ),
    )


class CreativeFinalizationTests(unittest.TestCase):
    def coordinator(
        self,
        hub: RunHub,
        *,
        fault: Any = None,
    ) -> FinalizationCoordinator:
        return FinalizationCoordinator(
            hub,
            clock=lambda: FROZEN_AT,
            fault_injector=fault,
        )

    def test_manifest_contract_is_strict_and_freezes_all_ledger_heads(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hub = _create_hub(Path(directory))
            manifest = self.coordinator(hub).freeze(())

            self.assertEqual(
                [head.ledger for head in manifest.source.ledger_heads],
                [
                    "decisions",
                    "events",
                    "human_resolutions",
                    "human_reviews",
                ],
            )
            self.assertEqual(
                [binding.path for binding in manifest.source.source_files],
                ["input/challenge.md"],
            )
            self.assertEqual(
                manifest.source.transition_seq,
                hub.load_state()["transition_seq"],
            )
            self.assertEqual(
                FinalizationManifest.from_dict(manifest.to_dict()),
                manifest,
            )
            with self.assertRaises(FinalizationValidationError):
                FinalizationManifest.from_dict(
                    {**manifest.to_dict(), "unexpected": True}
                )

    def test_zero_output_finalize_and_repeat_do_not_call_renderer_again(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hub = _create_hub(Path(directory))
            calls = 0

            def renderer(source: Any, snapshot: Any) -> tuple[Any, ...]:
                nonlocal calls
                calls += 1
                self.assertEqual(source.run_id, hub.run_id)
                self.assertEqual(snapshot["state"]["status"], "running")
                return ()

            coordinator = self.coordinator(hub)
            first = coordinator.finalize(renderer)
            run_after_first = (hub.run_dir / "run.json").read_bytes()
            events_after_first = hub.events_path.read_bytes()
            manifest_after_first = (
                hub.run_dir / FINALIZATION_MANIFEST_PATH
            ).read_bytes()

            second = coordinator.finalize(renderer)

            self.assertEqual(calls, 1)
            self.assertEqual(first, second)
            self.assertEqual(hub.load_state()["status"], "completed")
            self.assertEqual(hub.load_state()["result_artifact_ids"], [])
            self.assertEqual(
                (hub.run_dir / "run.json").read_bytes(),
                run_after_first,
            )
            self.assertEqual(hub.events_path.read_bytes(), events_after_first)
            self.assertEqual(
                (hub.run_dir / FINALIZATION_MANIFEST_PATH).read_bytes(),
                manifest_after_first,
            )

    def test_multiple_outputs_preserve_order_bytes_time_and_result_flags(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hub = _create_hub(Path(directory))
            manifest = self.coordinator(hub).finalize(_outputs())

            self.assertEqual(
                [output.publish_order for output in manifest.outputs],
                [1, 2, 3],
            )
            self.assertEqual(
                manifest.result_artifact_ids,
                (
                    "creative-report-json",
                    "creative-memory-record",
                ),
            )
            state = hub.load_state()
            self.assertEqual(
                state["result_artifact_ids"],
                list(manifest.result_artifact_ids),
            )
            for output, rendered in zip(
                manifest.outputs,
                _outputs(),
                strict=True,
            ):
                self.assertEqual(output.created_at, FROZEN_AT)
                self.assertEqual(
                    (hub.run_dir / output.final_path).read_bytes(),
                    rendered.content,
                )
                self.assertEqual(
                    state["artifacts"][output.artifact_id],
                    output.artifact_record,
                )
            suffix = read_jsonl(hub.events_path)[
                manifest.source.head("events").record_count :
            ]
            self.assertEqual(
                suffix,
                [
                    *(output.publish_event for output in manifest.outputs),
                    manifest.completed_transition.event,
                ],
            )

    def test_pure_report_output_uses_the_narrow_structural_adapter(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hub = _create_hub(Path(directory))
            output = ReportRenderedOutput(
                artifact_id="creative-idea-report",
                artifact_type="creative_idea_report_markdown",
                relative_path=(
                    "artifacts/creative/report/"
                    "creative-idea-report.md"
                ),
                content=b"# Creative Idea Report\n",
            )

            manifest = self.coordinator(hub).finalize((output,))

            self.assertEqual(
                manifest.outputs[0].final_path,
                output.relative_path,
            )
            self.assertEqual(
                (hub.run_dir / output.relative_path).read_bytes(),
                output.content,
            )

    def test_crash_before_manifest_has_no_replayable_plan_or_results(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hub = _create_hub(Path(directory))

            def crash(point: str) -> None:
                if point == "before_manifest":
                    raise OSError("before manifest")

            with self.assertRaisesRegex(OSError, "before manifest"):
                self.coordinator(hub, fault=crash).freeze(_outputs())

            state = hub.load_state()
            self.assertEqual(state["current_stage"], FINALIZATION_STAGE)
            self.assertEqual(state["result_artifact_ids"], [])
            self.assertIsNone(state.get("finalization"))
            self.assertFalse(
                (hub.run_dir / FINALIZATION_MANIFEST_PATH).exists()
            )
            with self.assertRaisesRegex(
                FinalizationValidationError,
                "no complete finalization manifest",
            ):
                self.coordinator(hub).replay()

            # A pre-manifest retry may render again, but it must freeze the
            # same staged bytes before exposing anything.
            self.coordinator(hub).finalize(_outputs())
            self.assertEqual(hub.load_state()["status"], "completed")

    def test_complete_orphan_manifest_is_adopted_without_renderer(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hub = _create_hub(Path(directory))

            def crash(point: str) -> None:
                if point == "after_manifest":
                    raise OSError("after manifest")

            with self.assertRaisesRegex(OSError, "after manifest"):
                self.coordinator(hub, fault=crash).freeze(_outputs())
            self.assertIsNone(hub.load_state().get("finalization"))
            self.assertTrue(
                (hub.run_dir / FINALIZATION_MANIFEST_PATH).is_file()
            )

            manifest = self.coordinator(hub).replay()

            state = hub.load_state()
            self.assertEqual(state["status"], "completed")
            self.assertEqual(
                state["finalization"]["manifest_sha256"],
                manifest.manifest_sha256,
            )

    def test_orphan_manifest_is_not_adopted_after_source_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hub = _create_hub(Path(directory))

            def crash(point: str) -> None:
                if point == "after_manifest":
                    raise OSError("after manifest")

            with self.assertRaises(OSError):
                self.coordinator(hub, fault=crash).freeze(_outputs())
            hub.append_decision(
                {
                    "decision_id": "late-decision",
                    "kind": "unexpected-after-freeze",
                }
            )

            with self.assertRaisesRegex(
                FinalizationConflictError,
                "decisions changed",
            ):
                self.coordinator(hub).replay()
            state = hub.load_state()
            self.assertIsNone(state.get("finalization"))
            self.assertEqual(state["result_artifact_ids"], [])

    def test_publish_interruption_replays_exact_plan_and_is_byte_stable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hub = _create_hub(Path(directory))

            def crash(point: str) -> None:
                if point == "after_publish:1":
                    raise OSError("after first publish")

            with self.assertRaisesRegex(OSError, "after first publish"):
                self.coordinator(hub, fault=crash).finalize(_outputs())
            partial = hub.load_state()
            first_record = partial["artifacts"]["creative-report-json"]
            first_event = read_jsonl(hub.events_path)[-1]
            self.assertEqual(partial["result_artifact_ids"], [])

            coordinator = self.coordinator(hub)
            coordinator.replay()
            self.assertEqual(
                hub.load_state()["artifacts"]["creative-report-json"],
                first_record,
            )
            self.assertIn(first_event, read_jsonl(hub.events_path))

            tracked = {
                path.relative_to(hub.run_dir).as_posix(): path.read_bytes()
                for path in (
                    hub.run_dir / "run.json",
                    hub.events_path,
                    hub.run_dir / FINALIZATION_MANIFEST_PATH,
                    *(
                        hub.run_dir / output.staged_path
                        for output in coordinator.replay().outputs
                    ),
                )
            }
            coordinator.replay()
            self.assertEqual(
                tracked,
                {
                    relative: (hub.run_dir / relative).read_bytes()
                    for relative in tracked
                },
            )

    def test_staged_or_published_tamper_fails_without_result_exposure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hub = _create_hub(Path(directory))
            manifest = self.coordinator(hub).freeze(_outputs())
            (hub.run_dir / manifest.outputs[0].staged_path).write_bytes(
                b"tampered staged bytes"
            )

            with self.assertRaisesRegex(
                FinalizationConflictError,
                "staged output bytes changed",
            ):
                self.coordinator(hub).replay()
            self.assertEqual(hub.load_state()["result_artifact_ids"], [])
            self.assertFalse(
                (hub.run_dir / manifest.outputs[0].final_path).exists()
            )

        with tempfile.TemporaryDirectory() as directory:
            hub = _create_hub(Path(directory))

            def crash(point: str) -> None:
                if point == "after_publish:1":
                    raise OSError("published once")

            with self.assertRaises(OSError):
                self.coordinator(hub, fault=crash).finalize(_outputs())
            final_path = hub.run_dir / _outputs()[0].final_path
            final_path.write_bytes(b"tampered published bytes")

            with self.assertRaisesRegex(
                FinalizationConflictError,
                "published output bytes changed",
            ):
                self.coordinator(hub).replay()
            self.assertEqual(hub.load_state()["result_artifact_ids"], [])

    def test_source_file_tamper_is_detected_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hub = _create_hub(Path(directory))
            hub.publish_artifact(
                artifact_id="creative-final-idea-001",
                artifact_type="creative_final_idea",
                relative_path=(
                    "artifacts/creative/final-ideas/"
                    "creative-final-idea-001.md"
                ),
                content="# Frozen source\n",
                task_id=None,
            )
            manifest = self.coordinator(hub).freeze(_outputs())
            source_path = (
                hub.run_dir
                / "artifacts/creative/final-ideas/"
                "creative-final-idea-001.md"
            )
            source_path.write_text("# Changed source\n", encoding="utf-8")

            with self.assertRaisesRegex(
                FinalizationConflictError,
                "source file bytes changed",
            ):
                self.coordinator(hub).replay()
            self.assertEqual(hub.load_state()["result_artifact_ids"], [])
            self.assertFalse(
                (hub.run_dir / manifest.outputs[0].final_path).exists()
            )

    def test_manifest_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hub = _create_hub(Path(directory))
            self.coordinator(hub).freeze(_outputs())
            manifest_path = hub.run_dir / FINALIZATION_MANIFEST_PATH
            manifest_path.write_bytes(manifest_path.read_bytes() + b" ")

            with self.assertRaisesRegex(
                FinalizationConflictError,
                "not canonical",
            ):
                self.coordinator(hub).replay()
            self.assertEqual(hub.load_state()["result_artifact_ids"], [])

    def test_exact_unregistered_final_file_is_adopted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hub = _create_hub(Path(directory))
            manifest = self.coordinator(hub).freeze(_outputs())
            first = manifest.outputs[0]
            final_path = hub.run_dir / first.final_path
            final_path.parent.mkdir(parents=True, exist_ok=True)
            final_path.write_bytes(
                (hub.run_dir / first.staged_path).read_bytes()
            )

            self.coordinator(hub).replay()

            self.assertEqual(
                hub.load_state()["artifacts"][first.artifact_id],
                first.artifact_record,
            )
            self.assertEqual(final_path.read_bytes(), _outputs()[0].content)

    def test_completion_event_before_state_crash_is_replayed_exactly(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hub = _create_hub(Path(directory))
            coordinator = self.coordinator(hub)
            manifest = coordinator.freeze(_outputs()[:1])
            original_write = hub_module.atomic_write_json

            def crash_completed_state(
                path: Any,
                value: Any,
            ) -> Any:
                if (
                    isinstance(value, dict)
                    and value.get("status") == "completed"
                ):
                    raise OSError("completion state replace crash")
                return original_write(path, value)

            with patch(
                "hacksome.core.hub.atomic_write_json",
                side_effect=crash_completed_state,
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "completion state replace crash",
                ):
                    coordinator.replay()

            self.assertEqual(hub.load_state()["status"], "running")
            self.assertEqual(hub.load_state()["result_artifact_ids"], [])
            self.assertEqual(
                read_jsonl(hub.events_path)[-1],
                manifest.completed_transition.event,
            )

            coordinator.replay()
            state = hub.load_state()
            self.assertEqual(state["status"], "completed")
            self.assertEqual(
                read_jsonl(hub.events_path).count(
                    manifest.completed_transition.event
                ),
                1,
            )


if __name__ == "__main__":
    unittest.main()
