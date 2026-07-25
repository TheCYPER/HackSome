from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hacksome.core.config import CodexConfig
from hacksome.stages.ideation.creative.partial_report import (
    PARTIAL_REPORT_JSON_ID,
    PARTIAL_REPORT_MARKDOWN_ID,
    publish_partial_report,
    render_partial_report,
)
from hacksome.core.hub import RunHub


def _failed_hub(root: Path) -> RunHub:
    hub = RunHub.create(
        "Make an honest strange interaction.",
        root,
        settings={"fixture": True},
        codex_config=CodexConfig(),
        run_id="creative-failed",
        route="creative",
    )
    hub.publish_artifact(
        artifact_id="creative-concept-s01-01-r001",
        artifact_type="creative_concept",
        relative_path=(
            "artifacts/creative/concepts/"
            "creative-concept-s01-01-r001.md"
        ),
        content="# Concept\n",
        task_id=None,
        metadata={
            "origin": "base",
            "revision": 1,
            "primary_territory_ref": "creative-territory-01",
        },
    )
    hub.set_run_status(
        "failed",
        stage="creative-novelty-scan",
        error=RuntimeError("network evidence unavailable"),
        task_id="creative-c5w-novelty-creative-concept-s01-01-r001",
    )
    return hub


class CreativePartialReportTests(unittest.TestCase):
    def test_render_is_exact_and_contains_no_terminal_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hub = _failed_hub(Path(directory))
            snapshot = hub.load_consistent_snapshot()

            first = render_partial_report(snapshot)
            second = render_partial_report(snapshot)

            self.assertEqual(first, second)
            payload = json.loads(first.json)
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["final_idea_card_ids"], [])
            self.assertEqual(payload["handoff_refs"], [])
            self.assertIsNone(payload["memory_record_ref"])
            self.assertIn(
                "creative-concept-s01-01-r001",
                {
                    row["artifact_id"]
                    for row in payload["persisted_artifacts"]
                },
            )

    def test_publish_is_idempotent_and_never_completes_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hub = _failed_hub(Path(directory))

            first = publish_partial_report(hub)
            state_after_first = hub.load_state()
            bytes_after_first = {
                artifact_id: hub.read_artifact(artifact_id)
                for artifact_id in first
            }
            second = publish_partial_report(hub)

            self.assertEqual(
                first,
                (PARTIAL_REPORT_MARKDOWN_ID, PARTIAL_REPORT_JSON_ID),
            )
            self.assertEqual(second, first)
            self.assertEqual(hub.load_state()["status"], "failed")
            self.assertEqual(hub.load_state()["result_artifact_ids"], [])
            self.assertEqual(
                {
                    artifact_id: hub.read_artifact(artifact_id)
                    for artifact_id in second
                },
                bytes_after_first,
            )
            self.assertEqual(
                state_after_first["terminal_error"],
                hub.load_state()["terminal_error"],
            )
