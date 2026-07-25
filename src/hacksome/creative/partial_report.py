"""Deterministic, non-terminal reports for failed Creative runs.

Partial reports are deliberately much smaller than successful C7 reports.  They
describe only facts that were already persisted before the fatal error.  They
never create Idea Cards, Build handoffs, an Idea Memory Record, a completion
event, or result artifact IDs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from hacksome.hub import RunHub
from hacksome.state import canonical_json_bytes, normalize_json


PARTIAL_REPORT_MARKDOWN_ID = "creative-partial-report"
PARTIAL_REPORT_JSON_ID = "creative-partial-report-json"
PARTIAL_REPORT_MARKDOWN_PATH = (
    "artifacts/creative/report/creative-partial-report.md"
)
PARTIAL_REPORT_JSON_PATH = (
    "artifacts/creative/report/creative-partial-report.json"
)

_FINAL_OUTPUT_TYPES = frozenset(
    {
        "creative_idea_report_markdown",
        "creative_idea_report_json",
        "creative_report_markdown",
        "creative_report_json",
        "creative_idea_card",
        "creative_idea_card_index",
        "creative_build_handoff",
        "creative_memory_record",
    }
)


class CreativePartialReportError(RuntimeError):
    """A failed run cannot be projected or published safely."""


@dataclass(frozen=True, slots=True)
class PartialReportBundle:
    """Exact partial-report bytes and their stable publication identities."""

    markdown: bytes
    json: bytes


def render_partial_report(
    snapshot: Mapping[str, Any],
) -> PartialReportBundle:
    """Render one failed-run snapshot without reading files or current time."""

    normalized = normalize_json(dict(snapshot), label="partial report snapshot")
    if not isinstance(normalized, dict):
        raise CreativePartialReportError("partial report snapshot must be an object")
    state = normalized.get("state")
    ledgers = normalized.get("ledgers")
    if not isinstance(state, dict) or not isinstance(ledgers, dict):
        raise CreativePartialReportError(
            "partial report snapshot requires state and ledgers"
        )
    route = state.get("route")
    if (
        not isinstance(route, dict)
        or route.get("id") != "creative"
        or state.get("status") != "failed"
        or not isinstance(state.get("terminal_error"), dict)
    ):
        raise CreativePartialReportError(
            "partial reports require a failed Creative run with a terminal error"
        )
    if state.get("result_artifact_ids") not in (None, []):
        raise CreativePartialReportError(
            "failed Creative runs cannot expose result artifacts"
        )

    tasks = state.get("tasks")
    artifacts = state.get("artifacts")
    if not isinstance(tasks, dict) or not isinstance(artifacts, dict):
        raise CreativePartialReportError(
            "partial report source registries must be objects"
        )

    task_rows = tuple(
        _task_projection(str(task_id), record)
        for task_id, record in sorted(tasks.items())
        if isinstance(record, dict)
    )
    artifact_rows = tuple(
        _artifact_projection(str(artifact_id), record)
        for artifact_id, record in sorted(artifacts.items())
        if isinstance(record, dict)
        and record.get("artifact_type") not in _FINAL_OUTPUT_TYPES
        and record.get("artifact_type")
        not in {
            "creative_partial_report_markdown",
            "creative_partial_report_json",
        }
    )
    completed_stages = sorted(
        {
            str(row["stage"])
            for row in task_rows
            if row["status"] == "succeeded" and row["stage"] is not None
        }
    )
    decisions = _safe_machine_decisions(ledgers.get("decisions"))
    review_refs = _human_ledger_refs(
        ledgers.get("human_reviews"),
        id_field="review_id",
        hash_fields=("request_sha256",),
    )
    resolution_refs = _human_ledger_refs(
        ledgers.get("human_resolutions"),
        id_field="resolution_id",
        hash_fields=(
            "resolution_sha256",
            "latest_receipt_set_sha256",
            "approved_feedback_set_sha256",
        ),
    )

    payload = {
        "schema_version": 1,
        "route": {
            "id": "creative",
            "contract_version": route.get("contract_version"),
        },
        "run_id": state.get("run_id"),
        "status": "failed",
        "failed_stage_id": state.get("current_stage"),
        "terminal_error": state["terminal_error"],
        "secondary_errors": state.get("secondary_errors", []),
        "completed_stage_ids": completed_stages,
        "tasks": list(task_rows),
        "persisted_artifacts": list(artifact_rows),
        "machine_decisions": decisions,
        "human_review_refs": review_refs,
        "human_resolution_refs": resolution_refs,
        "final_idea_card_ids": [],
        "handoff_refs": [],
        "memory_record_ref": None,
        "report_policy_version": route.get("report_policy_version"),
    }
    normalized_payload = normalize_json(payload, label="partial report payload")
    if not isinstance(normalized_payload, dict):
        raise AssertionError("partial report payload must normalize to an object")
    json_bytes = canonical_json_bytes(normalized_payload)
    markdown = _render_partial_markdown(normalized_payload).encode("utf-8")
    return PartialReportBundle(markdown=markdown, json=json_bytes)


def publish_partial_report(hub: RunHub) -> tuple[str, str]:
    """Idempotently publish both partial-report views on a failed run."""

    bundle = render_partial_report(hub.load_consistent_snapshot())
    payload = json.loads(bundle.json.decode("utf-8"))
    source_refs = _partial_source_refs(payload)
    report_policy_version = payload.get("report_policy_version")
    if not isinstance(report_policy_version, str) or not report_policy_version:
        raise CreativePartialReportError(
            "partial report requires a persisted report policy version"
        )
    markdown_id = hub.publish_artifact(
        artifact_id=PARTIAL_REPORT_MARKDOWN_ID,
        artifact_type="creative_partial_report_markdown",
        relative_path=PARTIAL_REPORT_MARKDOWN_PATH,
        content=bundle.markdown.decode("utf-8"),
        task_id=None,
        source_refs=source_refs,
        metadata={
            "status": "failed",
            "report_policy_version": report_policy_version,
        },
    )
    json_id = hub.publish_artifact(
        artifact_id=PARTIAL_REPORT_JSON_ID,
        artifact_type="creative_partial_report_json",
        relative_path=PARTIAL_REPORT_JSON_PATH,
        content=bundle.json.decode("utf-8"),
        task_id=None,
        source_refs=source_refs,
        metadata={
            "status": "failed",
            "report_policy_version": report_policy_version,
        },
    )
    return markdown_id, json_id


def _task_projection(task_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "stage": record.get("stage"),
        "status": record.get("status"),
        "failure_policy": record.get("failure_policy"),
        "parent_refs": record.get("parent_refs", []),
        "result_sha256": record.get("result_sha256"),
        "request_path": record.get("request_path"),
        "result_path": record.get("result_path"),
    }


def _artifact_projection(
    artifact_id: str,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = record.get("metadata")
    return {
        "artifact_id": artifact_id,
        "artifact_type": record.get("artifact_type"),
        "sha256": record.get("sha256"),
        "task_id": record.get("task_id"),
        "source_refs": record.get("source_refs", []),
        "metadata": metadata if isinstance(metadata, dict) else {},
    }


def _safe_machine_decisions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise CreativePartialReportError("decisions ledger must be an array")
    rows: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            raise CreativePartialReportError("decision record must be an object")
        rows.append(
            {
                "decision_id": raw.get("decision_id"),
                "stage": raw.get("stage"),
                "decision_type": raw.get("decision_type"),
                "outcome": raw.get("outcome"),
                "reason_codes": raw.get("reason_codes", []),
                "subject_refs": raw.get("subject_refs", []),
                "evidence_refs": raw.get("evidence_refs", []),
                "task_ids": raw.get("task_ids", []),
            }
        )
    return rows


def _human_ledger_refs(
    value: Any,
    *,
    id_field: str,
    hash_fields: Sequence[str],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise CreativePartialReportError(f"{id_field} ledger must be an array")
    rows: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            raise CreativePartialReportError(
                f"{id_field} ledger record must be an object"
            )
        rows.append(
            {
                id_field: raw.get(id_field),
                "round_id": raw.get("round_id"),
                **{field: raw.get(field) for field in hash_fields},
            }
        )
    return rows


def _partial_source_refs(payload: Mapping[str, Any]) -> tuple[str, ...]:
    refs = [
        str(row["artifact_id"])
        for row in payload.get("persisted_artifacts", [])
        if isinstance(row, dict) and isinstance(row.get("artifact_id"), str)
    ]
    error = payload.get("terminal_error")
    if isinstance(error, dict) and isinstance(error.get("event_id"), str):
        refs.append(str(error["event_id"]))
    return tuple(sorted(set(refs)))


def _render_partial_markdown(payload: Mapping[str, Any]) -> str:
    error = payload["terminal_error"]
    assert isinstance(error, dict)
    lines = [
        "# Creative Partial Report",
        "",
        "> 这是一份失败运行的审计快照，不是最终 Idea 报告。",
        "",
        "## Failure",
        "",
        f"- Stage: `{payload.get('failed_stage_id') or 'unknown'}`",
        f"- Kind: `{error.get('kind') or 'unknown'}`",
        f"- Message: {error.get('message') or 'No message was persisted.'}",
        f"- Task: `{error.get('task_id') or 'controller'}`",
        f"- Event: `{error.get('event_id') or 'unknown'}`",
        "",
        "## Completed Stages",
        "",
    ]
    completed = payload.get("completed_stage_ids")
    if isinstance(completed, list) and completed:
        lines.extend(f"- `{stage}`" for stage in completed)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Persisted Candidate History",
            "",
        ]
    )
    artifacts = payload.get("persisted_artifacts")
    if isinstance(artifacts, list) and artifacts:
        for row in artifacts:
            if not isinstance(row, dict):
                continue
            lines.append(
                "- "
                f"`{row.get('artifact_id')}` "
                f"({row.get('artifact_type')}, `{row.get('sha256')}`)"
            )
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Safety Boundary",
            "",
            "- Final Idea Cards: none",
            "- Build handoffs: none",
            "- Idea Memory Record: none",
            "- Run status remains `failed`.",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "CreativePartialReportError",
    "PARTIAL_REPORT_JSON_ID",
    "PARTIAL_REPORT_JSON_PATH",
    "PARTIAL_REPORT_MARKDOWN_ID",
    "PARTIAL_REPORT_MARKDOWN_PATH",
    "PartialReportBundle",
    "publish_partial_report",
    "render_partial_report",
]
