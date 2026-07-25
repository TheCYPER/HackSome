"""Route registry and offline run projections."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Any, Mapping, Protocol

from hacksome.hub import (
    LEGACY_RUN_SCHEMA_VERSION,
    RUN_SCHEMA_VERSION,
    RunHub,
)
from hacksome.prompting import PromptResourceError, useful_prompt_catalog
from hacksome.state import (
    StateError,
    canonical_json_bytes,
    read_jsonl,
    sha256_bytes,
    sha256_text,
)


_SUCCESS_REPORT_TYPES = frozenset(
    {
        "creative_idea_report_json",
        "creative_idea_report_markdown",
    }
)
_SUCCESS_FINAL_TYPES = frozenset(
    {
        *_SUCCESS_REPORT_TYPES,
        "creative_idea_card",
        "creative_idea_card_index",
        "creative_build_handoff",
        "creative_memory_record",
    }
)
_PARTIAL_REPORT_TYPES = frozenset(
    {
        "creative_partial_report_json",
        "creative_partial_report_markdown",
    }
)
_LEGACY_REPORT_TYPES = frozenset(
    {
        "creative_report_json",
        "creative_report_markdown",
    }
)
_ZERO_REASON_CODES = frozenset(
    {
        "no_concepts_generated",
        "all_candidates_failed_hook",
        "all_candidates_failed_concept_screen",
        "shortlist_empty",
        "all_human_rejected",
    }
)
_CREATIVE_RUN_STATUSES = frozenset(
    {"created", "running", "waiting", "completed", "failed"}
)


@dataclass(frozen=True, slots=True)
class _FinalizationProjection:
    status: str
    manifest_ref: str | None
    planned_artifact_count: int
    published_artifact_count: int
    resumable: bool
    manifest: Any = None
    errors: tuple[str, ...] = ()


class RouteContractError(StateError):
    """A persisted run cannot be dispatched to a supported route contract."""


class RunContract(Protocol):
    """One route's offline inspect and semantic validation contract."""

    @property
    def route_id(self) -> str: ...

    @property
    def contract_version(self) -> str: ...

    @property
    def supported_schema_versions(self) -> frozenset[int]: ...

    def inspect(self, hub: RunHub, state: Mapping[str, Any]) -> dict[str, Any]: ...

    def validate(
        self,
        hub: RunHub,
        state: Mapping[str, Any],
    ) -> list[str]: ...


@dataclass(frozen=True, slots=True)
class UsefulRunContract:
    """The existing Useful projection, kept byte/field compatible."""

    route_id: str = "useful"
    contract_version: str = "1"
    supported_contract_versions: frozenset[str] = frozenset({"1"})
    supported_schema_versions: frozenset[int] = frozenset(
        {LEGACY_RUN_SCHEMA_VERSION, RUN_SCHEMA_VERSION}
    )

    def inspect(self, hub: RunHub, state: Mapping[str, Any]) -> dict[str, Any]:
        core = hub.core_inspect()
        cards = state.get("idea_card_ids", [])
        return {
            "run_id": core["run_id"],
            "status": core["status"],
            "current_stage": core["current_stage"],
            "task_counts": core["task_counts"],
            "decision_count": core["decision_count"],
            "idea_card_count": len(cards) if isinstance(cards, list) else 0,
            "run_dir": core["run_dir"],
        }

    def validate(
        self,
        hub: RunHub,
        state: Mapping[str, Any],
    ) -> list[str]:
        errors: list[str] = []
        if state.get("schema_version") == RUN_SCHEMA_VERSION:
            route = state.get("route")
            manifest = state.get("resource_manifest")
            if isinstance(route, dict) and isinstance(manifest, dict):
                try:
                    useful_prompt_catalog.load_frozen(
                        hub.run_dir,
                        route_id="useful",
                        contract_version=str(route.get("contract_version", "")),
                        prompt_policy_version=str(
                            route.get("prompt_policy_version", "")
                        ),
                        stage_policy_version=str(
                            route.get("stage_policy_version", "")
                        ),
                        manifest_sha256=str(manifest.get("sha256", "")),
                    )
                except PromptResourceError as exc:
                    errors.append(str(exc))
        try:
            decisions = read_jsonl(hub.decisions_path)
        except (OSError, StateError) as exc:
            errors.append(str(exc))
            decisions = []
        for index, row in enumerate(decisions, start=1):
            if not isinstance(row.get("decision_id"), str):
                errors.append(f"decision {index} has no decision_id")
            if row.get("decision") not in {"pass", "reject"}:
                errors.append(f"decision {index} has invalid decision")

        passed_ideas = {
            row.get("candidate_ref")
            for row in decisions
            if row.get("gate") == "idea-red-team" and row.get("decision") == "pass"
        }
        passed_problems = {
            row.get("candidate_ref")
            for row in decisions
            if row.get("gate") == "problem-gateway" and row.get("decision") == "pass"
        }
        artifacts = state.get("artifacts")
        if not isinstance(artifacts, dict):
            return errors
        cards = state.get("idea_card_ids", [])
        if not isinstance(cards, list):
            errors.append("idea_card_ids must be a list")
            cards = []
        for card_id in cards:
            record = artifacts.get(card_id)
            if not isinstance(record, dict) or record.get("artifact_type") != "idea_card":
                errors.append(f"Idea Card is not registered: {card_id}")
                continue
            source_refs = record.get("source_refs", [])
            if not isinstance(source_refs, list) or not any(
                source in passed_ideas for source in source_refs
            ):
                errors.append(f"Idea Card has no passed Idea source: {card_id}")
            if not isinstance(source_refs, list) or not any(
                source in passed_problems for source in source_refs
            ):
                errors.append(f"Idea Card has no passed Problem source: {card_id}")
        return errors


@dataclass(frozen=True, slots=True)
class CreativeRunContract:
    """Offline projection and currently implemented Creative invariants."""

    route_id: str = "creative"
    contract_version: str = "2"
    supported_contract_versions: frozenset[str] = frozenset({"1", "2"})
    supported_schema_versions: frozenset[int] = frozenset({RUN_SCHEMA_VERSION})

    def inspect(self, hub: RunHub, state: Mapping[str, Any]) -> dict[str, Any]:
        core = hub.core_inspect()
        artifacts = state.get("artifacts")
        if not isinstance(artifacts, dict):
            artifacts = {}
        concepts: dict[str, dict[str, Any]] = {
            str(artifact_id): record
            for artifact_id, record in artifacts.items()
            if isinstance(record, dict)
            and record.get("artifact_type") == "creative_concept"
        }
        base_generated = sum(
            1
            for record in concepts.values()
            if _metadata_value(record, "origin") == "base"
            and _metadata_value(record, "revision") == 1
        )
        memory_challengers = sum(
            1
            for record in concepts.values()
            if _metadata_value(record, "origin") == "memory_challenger"
            and _metadata_value(record, "revision") == 1
        )
        dispositions = _creative_dispositions(hub, artifacts)
        hook_passed = {
            row.get("concept_revision_ref")
            for row in dispositions
            if row.get("stage") == "C4" and row.get("outcome") == "pass"
        }
        shortlisted = {
            row.get("concept_revision_ref")
            for row in dispositions
            if row.get("outcome") == "shortlisted"
        }
        finals = {
            str(artifact_id)
            for artifact_id, record in artifacts.items()
            if isinstance(record, dict)
            and record.get("artifact_type") == "creative_final_idea"
        }
        inputs = state.get("inputs")
        memory_input: dict[str, Any] = {}
        if isinstance(inputs, dict):
            candidate_memory_input = inputs.get("idea_memory")
            if isinstance(candidate_memory_input, dict):
                memory_input = candidate_memory_input
        summary_records = [
            record
            for record in artifacts.values()
            if isinstance(record, dict)
            and record.get("artifact_type") == "creative_memory_stage_summary"
        ]
        summary_metadata = (
            summary_records[0].get("metadata", {})
            if len(summary_records) == 1
            else {}
        )
        wait = state.get("wait")
        review = wait if isinstance(wait, dict) else {}
        review_batch_ref = _first_artifact_of_type(
            artifacts, "creative_human_review_batch"
        )
        review_batch: dict[str, Any] = {}
        if review_batch_ref is not None:
            try:
                raw_batch = json.loads(hub.read_artifact(review_batch_ref))
            except (OSError, UnicodeError, json.JSONDecodeError, StateError):
                raw_batch = None
            if isinstance(raw_batch, dict):
                review_batch = raw_batch
        review_status = review.get("status")
        if not isinstance(review_status, str):
            candidate_status = review_batch.get("status")
            review_status = (
                candidate_status
                if isinstance(candidate_status, str)
                else "not_started"
            )
        round_id = review.get("round_id")
        if not isinstance(round_id, str):
            candidate_round = review_batch.get("round_id")
            round_id = candidate_round if isinstance(candidate_round, str) else None
        batch_refs = review_batch.get("concepts", [])
        batch_shortlist_count = (
            len(batch_refs) if isinstance(batch_refs, list) else 0
        )
        reviewer_count, covered_concept_count = (
            _creative_review_ledger_counts(
                hub,
                review_batch_ref=review_batch_ref,
                review_batch=review_batch,
            )
        )
        finalization = _creative_finalization_projection(
            hub,
            state,
            artifacts,
            needs_reconcile=bool(core["needs_reconcile"]),
        )
        report_payload: Mapping[str, Any] | None = None
        if finalization.manifest is not None and finalization.status in {
            "publishing",
            "completed",
        }:
            semantic_errors: list[str] = []
            report_payload = _validate_success_bundle(
                hub,
                state,
                artifacts,
                concepts,
                dispositions,
                finalization.manifest,
                semantic_errors,
            )
            if semantic_errors:
                finalization = replace(
                    finalization,
                    status="corrupt",
                    resumable=False,
                    errors=(
                        *finalization.errors,
                        *semantic_errors,
                    ),
                )
        zero_reason_code = state.get("zero_reason_code")
        if report_payload is not None:
            reported_reason = report_payload.get("zero_reason_code")
            if reported_reason is None or isinstance(reported_reason, str):
                zero_reason_code = reported_reason
        if zero_reason_code is None:
            candidate_reason = review_batch.get("skip_reason")
            if isinstance(candidate_reason, str):
                zero_reason_code = candidate_reason
        report_ref = (
            _first_artifact_of_type(
                artifacts, "creative_idea_report_json"
            )
            if core["status"] == "completed"
            and finalization.status == "completed"
            and report_payload is not None
            else None
        )
        partial_report_ref = _first_artifact_of_type(
            artifacts, "creative_partial_report_json"
        )
        return {
            "route_id": "creative",
            "run_id": core["run_id"],
            "status": core["status"],
            "current_stage": core["current_stage"],
            "task_counts": core["task_counts"],
            "concept_counts": {
                "base_generated": base_generated,
                "memory_challengers": memory_challengers,
                "generated_total": base_generated + memory_challengers,
                "hook_passed": len(hook_passed),
                "shortlisted": len(shortlisted),
                "final": len(finals),
            },
            "memory": {
                "mode": memory_input.get("mode"),
                "snapshot_sha256": memory_input.get("sha256"),
                "eligible_entry_count": memory_input.get(
                    "eligible_entry_count", 0
                ),
                "selected_cue_count": len(
                    summary_metadata.get("selected_cue_ids", [])
                )
                if isinstance(summary_metadata, dict)
                and isinstance(summary_metadata.get("selected_cue_ids", []), list)
                else 0,
                "status": summary_metadata.get("status", "not_started")
                if isinstance(summary_metadata, dict)
                else "not_started",
            },
            "review": {
                "round_id": round_id,
                "batch_ref": review_batch_ref,
                "status": review_status,
                "reviewer_count": reviewer_count,
                "covered_concept_count": covered_concept_count,
                "shortlist_count": max(
                    len(shortlisted),
                    batch_shortlist_count,
                ),
                "resumable": (
                    review.get("status") == "closed"
                    and core["status"] == "waiting"
                    and core["current_stage"] == "creative-human-review"
                    and not core["needs_reconcile"]
                ),
            },
            "finalization": {
                "status": finalization.status,
                "manifest_ref": finalization.manifest_ref,
                "planned_artifact_count": (
                    finalization.planned_artifact_count
                ),
                "published_artifact_count": (
                    finalization.published_artifact_count
                ),
                "resumable": finalization.resumable,
            },
            "zero_reason_code": zero_reason_code,
            "report_ref": report_ref,
            "partial_report_ref": partial_report_ref,
            "needs_reconcile": core["needs_reconcile"],
            "run_dir": core["run_dir"],
        }

    def validate(
        self,
        hub: RunHub,
        state: Mapping[str, Any],
    ) -> list[str]:
        from hacksome.config import (
            PersistedConfigError,
            decode_persisted_dataclass,
        )
        from hacksome.creative.contracts import (
            C6C_FEEDBACK_REVISE,
            CreativeContractError,
            CreativeWorkflowSettings,
            SOFTWARE_DEMO_POLICY,
            SOFTWARE_DEMO_POLICY_VERSION,
            atom_id,
            final_idea_id,
            territory_for_atom,
            territory_id,
        )
        from hacksome.creative.artifacts import PORTFOLIO_DIMENSIONS
        from hacksome.creative.memory import (
            MemoryCapsuleRef,
            MemoryRemixSlot,
            MemoryStageSummary,
            MemoryTaskSlot,
            MemoryValidationError,
        )
        from hacksome.creative.prompting import (
            creative_prompt_catalog_for_contract,
        )
        from hacksome.creative.review import (
            ReviewBatch,
            ReviewError,
            ReviewRound,
            ReviewStore,
        )

        errors: list[str] = []
        route = state.get("route")
        manifest = state.get("resource_manifest")
        contract_version = (
            str(route.get("contract_version", ""))
            if isinstance(route, dict)
            else ""
        )
        try:
            route_prompt_catalog = creative_prompt_catalog_for_contract(
                contract_version
            )
        except ValueError as exc:
            errors.append(str(exc))
            route_prompt_catalog = None
        if isinstance(route, dict) and isinstance(manifest, dict):
            try:
                if route_prompt_catalog is None:
                    raise PromptResourceError(
                        "Creative contract has no supported prompt catalog"
                    )
                route_prompt_catalog.load_frozen(
                    hub.run_dir,
                    route_id="creative",
                    contract_version=str(route.get("contract_version", "")),
                    prompt_policy_version=str(
                        route.get("prompt_policy_version", "")
                    ),
                    stage_policy_version=str(
                        route.get("stage_policy_version", "")
                    ),
                    manifest_sha256=str(manifest.get("sha256", "")),
                )
            except PromptResourceError as exc:
                errors.append(str(exc))

        settings: Any = None
        hashes = state.get("config_hashes")
        raw_settings = state.get("settings")
        if isinstance(hashes, dict) and isinstance(raw_settings, dict):
            expected = hashes.get("workflow_settings_sha256")
            if isinstance(expected, str):
                try:
                    settings = decode_persisted_dataclass(
                        CreativeWorkflowSettings,
                        raw_settings,
                        expected_sha256=expected,
                    )
                except PersistedConfigError as exc:
                    errors.append(str(exc))

        software_policy_block: str | None = None
        if contract_version == "2":
            inputs = state.get("inputs")
            policy_record = (
                inputs.get("software_demo_policy")
                if isinstance(inputs, dict)
                else None
            )
            if not isinstance(policy_record, dict):
                errors.append(
                    "Creative v2 run requires a frozen Software Demo Policy"
                )
            else:
                expected_policy_path = "input/software-demo-policy.json"
                if policy_record.get("path") != expected_policy_path:
                    errors.append("Creative Software Demo Policy path mismatch")
                if (
                    policy_record.get("policy_version")
                    != SOFTWARE_DEMO_POLICY_VERSION
                ):
                    errors.append("Creative Software Demo Policy version mismatch")
                if (
                    policy_record.get("sha256")
                    != sha256_text(SOFTWARE_DEMO_POLICY)
                ):
                    errors.append("Creative Software Demo Policy hash mismatch")
                if policy_record.get("source") != "controller":
                    errors.append("Creative Software Demo Policy source mismatch")
                try:
                    policy_text = (
                        hub.run_dir / "input" / "software-demo-policy.json"
                    ).read_text(encoding="utf-8")
                except (OSError, UnicodeError) as exc:
                    errors.append(
                        f"Creative Software Demo Policy cannot be read: {exc}"
                    )
                else:
                    if policy_text != SOFTWARE_DEMO_POLICY:
                        errors.append(
                            "Creative Software Demo Policy bytes changed"
                        )
            policy_digest = sha256_text(SOFTWARE_DEMO_POLICY)[:12]
            software_policy_block = (
                f"<BEGIN_SOFTWARE_DEMO_POLICY_{policy_digest}>\n"
                f"{SOFTWARE_DEMO_POLICY}\n"
                f"<END_SOFTWARE_DEMO_POLICY_{policy_digest}>"
            )

        try:
            events = read_jsonl(hub.events_path)
        except (OSError, StateError) as exc:
            errors.append(str(exc))
            events = []
        optional_failure_events: dict[str, list[dict[str, Any]]] = {}
        for row in events:
            if row.get("kind") != "optional_memory_stage_failed":
                continue
            data = row.get("data")
            task_ref = data.get("task_ref") if isinstance(data, dict) else None
            if not isinstance(task_ref, str) or not task_ref:
                errors.append(
                    "optional_memory_stage_failed event has no task_ref"
                )
                continue
            optional_failure_events.setdefault(task_ref, []).append(row)
        tasks = state.get("tasks")
        if not isinstance(tasks, dict):
            tasks = {}
        for task_id, raw in tasks.items():
            if not isinstance(raw, dict):
                continue
            stage = raw.get("stage")
            if (
                route_prompt_catalog is None
                or not isinstance(stage, str)
                or stage not in route_prompt_catalog
            ):
                errors.append(f"Creative task {task_id} has unsupported stage")
                continue
            spec = route_prompt_catalog[stage]
            if raw.get("web_search") is not spec.web_search:
                errors.append(f"Creative task {task_id} web policy mismatch")
            if bool(raw.get("web_search")) != (
                stage == "creative-novelty-scan"
            ):
                errors.append(
                    f"Creative task {task_id} violates novelty-only web policy"
                )
            if contract_version == "2":
                policy_stages = {
                    "creative-brief-normalize",
                    "creative-territory-explore",
                    "creative-concept-synthesize",
                    "creative-cheap-hook-review",
                    "creative-software-demo-review",
                    "creative-cheap-hook-repair",
                    "creative-memory-remix",
                    "creative-evidence-revise",
                    "creative-portfolio-curate",
                }
                parent_refs = raw.get("parent_refs")
                if not isinstance(parent_refs, list):
                    errors.append(
                        f"Creative task {task_id} has invalid parent_refs"
                    )
                    parent_refs = []
                policy_parent_count = parent_refs.count(
                    "input:software_demo_policy"
                )
                expects_policy = stage in policy_stages
                if expects_policy and policy_parent_count != 1:
                    errors.append(
                        f"Creative task {task_id} requires exactly one "
                        "Software Demo Policy parent"
                    )
                if not expects_policy and policy_parent_count:
                    errors.append(
                        f"Creative task {task_id} received Software Demo Policy "
                        "outside the stage allowlist"
                    )
                prompt = ""
                prompt_path = raw.get("prompt_path")
                if isinstance(prompt_path, str):
                    try:
                        prompt = hub.run_dir.joinpath(
                            *Path(prompt_path).parts
                        ).read_text(encoding="utf-8")
                    except (OSError, UnicodeError) as exc:
                        errors.append(
                            f"Creative task {task_id} Prompt cannot be read: {exc}"
                        )
                else:
                    errors.append(
                        f"Creative task {task_id} has no persisted Prompt"
                    )
                marker_count = prompt.count(
                    "<BEGIN_SOFTWARE_DEMO_POLICY_"
                )
                end_marker_count = prompt.count(
                    "<END_SOFTWARE_DEMO_POLICY_"
                )
                exact_count = (
                    prompt.count(software_policy_block)
                    if software_policy_block is not None
                    else 0
                )
                if expects_policy and (
                    exact_count != 1
                    or marker_count != 1
                    or end_marker_count != 1
                ):
                    errors.append(
                        f"Creative task {task_id} does not contain exactly one "
                        "frozen Software Demo Policy block"
                    )
                if not expects_policy and (marker_count or end_marker_count):
                    errors.append(
                        f"Creative task {task_id} Prompt contains Software Demo "
                        "Policy outside the stage allowlist"
                    )
            failure_policy = raw.get("failure_policy", "fatal")
            if failure_policy == "optional_branch" and stage not in {
                "creative-memory-recall",
                "creative-memory-remix",
            }:
                errors.append(
                    f"Creative task {task_id} illegally uses optional_branch"
                )
            if raw.get("status") in {"failed", "invalidated"}:
                if failure_policy == "optional_branch":
                    if len(optional_failure_events.get(str(task_id), [])) != 1:
                        errors.append(
                            f"optional Creative task {task_id} must have exactly "
                            "one diagnostic event"
                        )
                elif state.get("status") != "failed":
                    errors.append(
                        f"fatal Creative task {task_id} failed in a non-failed run"
                    )
            elif task_id in optional_failure_events:
                errors.append(
                    f"optional diagnostic references non-failed task {task_id}"
                )
            if stage in {
                "creative-territory-explore",
                "creative-concept-synthesize",
                "creative-cheap-hook-review",
                "creative-software-demo-review",
            }:
                parent_refs = raw.get("parent_refs", [])
                if isinstance(parent_refs, list) and any(
                    ref == "input:idea_memory"
                    or "memory-inspiration" in str(ref)
                    for ref in parent_refs
                ):
                    errors.append(
                        f"Creative task {task_id} received Idea Memory too early"
                    )
                prompt_path = raw.get("prompt_path")
                if isinstance(prompt_path, str):
                    try:
                        prompt = hub.run_dir.joinpath(
                            *Path(prompt_path).parts
                        ).read_text(encoding="utf-8")
                    except (OSError, UnicodeError):
                        prompt = ""
                    if "<BEGIN_IDEA_MEMORY_" in prompt or "<BEGIN_MEMORY_CUE_" in prompt:
                        errors.append(
                            f"Creative task {task_id} Prompt contains early memory context"
                        )

        for task_ref, matching_events in optional_failure_events.items():
            raw_task = tasks.get(task_ref)
            if not isinstance(raw_task, dict):
                errors.append(
                    f"optional diagnostic references unknown task {task_ref}"
                )
                continue
            if len(matching_events) != 1:
                errors.append(
                    f"optional Creative task {task_ref} must have exactly "
                    "one diagnostic event"
                )
            stage = raw_task.get("stage")
            data = matching_events[0].get("data") if matching_events else None
            if not isinstance(data, dict) or data.get("stage") != stage:
                errors.append(
                    f"optional diagnostic stage mismatch for task {task_ref}"
                )
            if raw_task.get("failure_policy") != "optional_branch":
                errors.append(
                    f"optional diagnostic references fatal task {task_ref}"
                )
            if raw_task.get("status") not in {"failed", "invalidated"}:
                errors.append(
                    f"optional diagnostic references non-failed task {task_ref}"
                )

        artifacts = state.get("artifacts")
        if not isinstance(artifacts, dict):
            return errors
        concepts = {
            str(artifact_id): record
            for artifact_id, record in artifacts.items()
            if isinstance(record, dict)
            and record.get("artifact_type") == "creative_concept"
        }
        final_ideas = {
            str(artifact_id): record
            for artifact_id, record in artifacts.items()
            if isinstance(record, dict)
            and record.get("artifact_type") == "creative_final_idea"
        }
        atom_records = {
            str(artifact_id): record
            for artifact_id, record in artifacts.items()
            if isinstance(record, dict)
            and record.get("artifact_type") == "creative_atom"
        }
        territory_records = {
            str(artifact_id): record
            for artifact_id, record in artifacts.items()
            if isinstance(record, dict)
            and record.get("artifact_type") == "creative_territory"
        }
        territory_slots: dict[str, int] = {}
        for territory_ref, record in territory_records.items():
            territory_metadata = record.get("metadata")
            if not isinstance(territory_metadata, dict):
                errors.append(
                    f"Creative Territory {territory_ref} has no metadata"
                )
                continue
            slot = territory_metadata.get("slot")
            if isinstance(slot, bool) or not isinstance(slot, int):
                errors.append(
                    f"Creative Territory {territory_ref} has invalid slot metadata"
                )
                continue
            try:
                expected_ref = territory_id(slot)
            except CreativeContractError:
                errors.append(
                    f"Creative Territory {territory_ref} has invalid slot metadata"
                )
                continue
            territory_slots[territory_ref] = slot
            if expected_ref != territory_ref:
                errors.append(
                    f"Creative Territory {territory_ref} slot metadata "
                    "does not match its ID"
                )

        for atom_ref, record in atom_records.items():
            try:
                encoded_territory_ref = territory_for_atom(atom_ref)
            except CreativeContractError:
                encoded_territory_ref = None
                errors.append(f"Creative Atom {atom_ref} has an invalid stable ID")

            raw_metadata = record.get("metadata")
            if not isinstance(raw_metadata, dict):
                errors.append(f"Creative Atom {atom_ref} has no metadata")
                atom_metadata: Mapping[str, Any] = {}
            else:
                atom_metadata = raw_metadata

            metadata_territory_ref = atom_metadata.get("territory_ref")
            if not isinstance(metadata_territory_ref, str):
                errors.append(
                    f"Creative Atom {atom_ref} has invalid territory_ref metadata"
                )
            elif (
                encoded_territory_ref is not None
                and metadata_territory_ref != encoded_territory_ref
            ):
                errors.append(
                    f"Creative Atom {atom_ref} territory_ref metadata "
                    "does not match its ID"
                )

            source_refs = record.get("source_refs")
            if (
                not isinstance(source_refs, list)
                or len(source_refs) != 1
                or source_refs[0] != metadata_territory_ref
            ):
                errors.append(
                    f"Creative Atom {atom_ref} source_refs must bind exactly "
                    "its metadata Territory"
                )

            if (
                isinstance(metadata_territory_ref, str)
                and metadata_territory_ref not in territory_records
            ):
                errors.append(
                    f"Creative Atom {atom_ref} references no Creative "
                    f"Territory artifact: {metadata_territory_ref}"
                )

            territory_slot = atom_metadata.get("territory_slot")
            atom_slot = atom_metadata.get("atom_slot")
            if (
                isinstance(territory_slot, bool)
                or not isinstance(territory_slot, int)
                or isinstance(atom_slot, bool)
                or not isinstance(atom_slot, int)
            ):
                errors.append(
                    f"Creative Atom {atom_ref} has invalid slot metadata"
                )
                continue
            try:
                expected_atom_ref = atom_id(territory_slot, atom_slot)
            except CreativeContractError:
                errors.append(
                    f"Creative Atom {atom_ref} has invalid slot metadata"
                )
                continue
            if expected_atom_ref != atom_ref:
                errors.append(
                    f"Creative Atom {atom_ref} slot metadata does not match its ID"
                )
            if isinstance(metadata_territory_ref, str):
                territory_slot_from_artifact = territory_slots.get(
                    metadata_territory_ref
                )
                if (
                    territory_slot_from_artifact is not None
                    and territory_slot != territory_slot_from_artifact
                ):
                    errors.append(
                        f"Creative Atom {atom_ref} territory_slot does not "
                        "match its Territory artifact"
                    )
        base_count = 0
        memory_count = 0
        revisions: dict[str, set[int]] = {}
        revision_reasons: dict[str, list[str]] = {}
        concept_metadata: dict[str, dict[str, Any]] = {}
        for artifact_id, record in concepts.items():
            metadata = record.get("metadata")
            if not isinstance(metadata, dict):
                errors.append(f"Creative Concept {artifact_id} has no metadata")
                continue
            concept_metadata[artifact_id] = metadata
            concept_id = metadata.get("concept_id")
            revision = metadata.get("revision")
            origin = metadata.get("origin")
            primary = metadata.get("primary_territory_ref")
            parents = metadata.get("parent_atom_refs")
            if not isinstance(concept_id, str) or not concept_id:
                errors.append(f"Creative Concept {artifact_id} has no concept_id")
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                errors.append(f"Creative Concept {artifact_id} has invalid revision")
            elif isinstance(concept_id, str):
                revisions.setdefault(concept_id, set()).add(revision)
                reason = metadata.get("revision_reason")
                if isinstance(reason, str):
                    revision_reasons.setdefault(concept_id, []).append(reason)
            if origin not in {"base", "memory_challenger"}:
                errors.append(f"Creative Concept {artifact_id} has invalid origin")
            elif revision == 1 and origin == "base":
                base_count += 1
            elif revision == 1 and origin == "memory_challenger":
                memory_count += 1
                raw_memory_refs = metadata.get("memory_source_refs")
                raw_cue_refs = metadata.get("memory_cue_refs")
                if (
                    not isinstance(raw_memory_refs, list)
                    or not raw_memory_refs
                ):
                    errors.append(
                        f"Memory challenger {artifact_id} has no memory refs"
                    )
                else:
                    for reference in raw_memory_refs:
                        try:
                            MemoryCapsuleRef.from_mapping(reference)
                        except MemoryValidationError as exc:
                            errors.append(
                                f"Memory challenger {artifact_id} has invalid "
                                f"memory ref: {exc}"
                            )
                if (
                    not isinstance(raw_cue_refs, list)
                    or not raw_cue_refs
                    or any(
                        not isinstance(reference, str) or not reference
                        for reference in raw_cue_refs
                    )
                    or len(raw_cue_refs) != len(set(raw_cue_refs))
                ):
                    errors.append(
                        f"Memory challenger {artifact_id} has invalid cue refs"
                    )
                source_task = record.get("task_id")
                source_task_record = (
                    tasks.get(source_task)
                    if isinstance(source_task, str)
                    else None
                )
                if (
                    not isinstance(source_task, str)
                    or not isinstance(source_task_record, dict)
                    or source_task_record.get("stage")
                    != "creative-memory-remix"
                    or source_task_record.get("status") != "succeeded"
                ):
                    errors.append(
                        f"Memory challenger {artifact_id} has no successful "
                        "Memory Remix task"
                    )
            if not isinstance(parents, list) or not parents:
                errors.append(f"Creative Concept {artifact_id} has no Parent Atoms")
            else:
                territories = {
                    _metadata_value(atom_records.get(str(parent), {}), "territory_ref")
                    for parent in parents
                }
                if primary not in territories:
                    errors.append(
                        f"Creative Concept {artifact_id} primary territory mismatch"
                    )
        if settings is not None:
            if base_count > (
                int(settings.concept_synthesizers)
                * int(settings.max_concepts_per_synthesizer)
            ):
                errors.append("base Creative Concept count exceeds persisted limit")
            if memory_count > int(settings.max_memory_challengers):
                errors.append("memory challenger count exceeds persisted limit")
        for concept_id, values in revisions.items():
            if values != set(range(1, max(values) + 1)):
                errors.append(f"Creative Concept {concept_id} revision gap")
            reasons = revision_reasons.get(concept_id, [])
            for reason, limit in (
                ("cheap_hook_repair", 1),
                ("evidence_informed", 1),
                ("human_feedback", 1),
            ):
                if reasons.count(reason) > limit:
                    errors.append(
                        f"Creative Concept {concept_id} exceeds {reason} budget"
                    )
        for artifact_id, metadata in concept_metadata.items():
            revision = metadata.get("revision")
            concept_id = metadata.get("concept_id")
            if (
                isinstance(revision, bool)
                or not isinstance(revision, int)
                or revision <= 1
                or not isinstance(concept_id, str)
            ):
                continue
            expected_source = f"{concept_id}-r{revision - 1:03d}"
            source_ref = metadata.get("supersedes_ref")
            if source_ref != expected_source:
                errors.append(
                    f"Creative Concept {artifact_id} has invalid supersedes_ref"
                )
                continue
            source_metadata = concept_metadata.get(expected_source)
            if source_metadata is None:
                errors.append(
                    f"Creative Concept {artifact_id} supersedes unknown revision"
                )
                continue
            for key in (
                "origin",
                "primary_territory_ref",
                "parent_atom_refs",
                "memory_cue_refs",
                "memory_source_refs",
            ):
                if metadata.get(key, []) != source_metadata.get(key, []):
                    errors.append(
                        f"Creative Concept {artifact_id} changed lineage field {key}"
                    )
            reason = metadata.get("revision_reason")
            source_task = concepts[artifact_id].get("task_id")
            task_record = tasks.get(source_task) if isinstance(source_task, str) else None
            expected_stage = {
                "cheap_hook_repair": "creative-cheap-hook-repair",
                "evidence_informed": "creative-evidence-revise",
                "human_feedback": "creative-feedback-revise",
            }.get(reason if isinstance(reason, str) else "")
            if expected_stage is None:
                errors.append(
                    f"Creative Concept {artifact_id} has invalid revision reason"
                )
            elif (
                not isinstance(task_record, dict)
                or task_record.get("stage") != expected_stage
                or task_record.get("status") != "succeeded"
            ):
                errors.append(
                    f"Creative Concept {artifact_id} has no successful "
                    f"{expected_stage} task"
                )

        decisions = []
        try:
            decisions = read_jsonl(hub.decisions_path)
        except (OSError, StateError) as exc:
            errors.append(str(exc))
        decision_ids = {
            row.get("decision_id")
            for row in decisions
            if row.get("route_id") == "creative"
        }
        dispositions = _creative_dispositions(hub, artifacts, errors=errors)
        terminal_counts: dict[str, int] = {}
        hook_passed: set[str] = set()
        c4_routing: dict[str, list[dict[str, Any]]] = {}
        dispositions_by_concept: dict[str, list[dict[str, Any]]] = {}
        for disposition in dispositions:
            concept_ref = disposition.get("concept_revision_ref")
            if concept_ref not in concepts:
                errors.append(
                    f"Creative disposition references unknown Concept: {concept_ref}"
                )
                continue
            concept_record = concepts[str(concept_ref)]
            dispositions_by_concept.setdefault(str(concept_ref), []).append(
                disposition
            )
            if disposition.get("concept_sha256") != concept_record.get("sha256"):
                errors.append(
                    f"Creative disposition Concept hash mismatch: {concept_ref}"
                )
            if disposition.get("decision_ref") not in decision_ids:
                errors.append(
                    f"Creative disposition has unknown decision: "
                    f"{disposition.get('decision_ref')}"
                )
            terminal = disposition.get("terminal")
            if terminal is True:
                terminal_counts[str(concept_ref)] = (
                    terminal_counts.get(str(concept_ref), 0) + 1
                )
            outcome = disposition.get("outcome")
            if outcome == "pass":
                hook_passed.add(str(concept_ref))
            if (
                disposition.get("stage") == "C4"
                and outcome
                in {"pass", "eliminated", "superseded_by_hook_repair"}
            ):
                c4_routing.setdefault(str(concept_ref), []).append(
                    disposition
                )
            target = disposition.get("target_ref")
            successor_concept_outcomes = {
                "superseded_by_hook_repair",
                "superseded_by_evidence_revision",
            }
            successor_final_outcomes = {
                "promoted_to_final",
                "revised_into",
                "merged_into",
            }
            if (
                target is not None
                and (
                    outcome in successor_concept_outcomes
                    and target not in concepts
                    or outcome in successor_final_outcomes
                    and target not in final_ideas
                    or outcome
                    not in successor_concept_outcomes
                    | successor_final_outcomes
                )
            ):
                errors.append(
                    f"Creative disposition target does not exist: {target}"
                )
            if outcome in successor_concept_outcomes | successor_final_outcomes and (
                target is None
            ):
                errors.append(
                    f"Creative disposition {outcome} requires target_ref"
                )
            if outcome in {
                "eliminated",
                "not_shortlisted",
                "human_reject",
                "human_taste_veto",
            } and target is not None:
                errors.append(
                    f"Creative disposition {outcome} must not have target_ref"
                )
            expected_stage = {
                "pass": "C4",
                "repair": "C4",
                "eliminated": "C4",
                "superseded_by_hook_repair": "C4",
                "superseded_by_evidence_revision": "C6A",
                "shortlisted": "C6B",
                "not_shortlisted": "C6B",
                "promoted_to_final": "C6C",
                "revised_into": "C6C",
                "human_reject": "C6C",
                "human_taste_veto": "C6C",
                "merged_into": "C6C",
            }.get(outcome if isinstance(outcome, str) else "")
            if expected_stage is not None and disposition.get("stage") != expected_stage:
                errors.append(
                    f"Creative disposition {outcome} must use stage {expected_stage}"
                )
            if outcome in {"pass", "repair", "shortlisted"}:
                if terminal is not False or target is not None:
                    errors.append(
                        f"Creative disposition {outcome} must be non-terminal"
                    )
            elif outcome in {
                "eliminated",
                "superseded_by_hook_repair",
                "superseded_by_evidence_revision",
                "not_shortlisted",
                "promoted_to_final",
                "revised_into",
                "human_reject",
                "human_taste_veto",
                "merged_into",
            } and terminal is not True:
                errors.append(
                    f"Creative disposition {outcome} must be terminal"
                )
        if any(count > 1 for count in terminal_counts.values()):
            errors.append("Creative Concept revision has multiple terminal dispositions")

        hook_review_records = {
            str(artifact_id): record
            for artifact_id, record in artifacts.items()
            if isinstance(record, dict)
            and record.get("artifact_type") == "creative_cheap_hook_review"
        }
        feasibility_review_records = {
            str(artifact_id): record
            for artifact_id, record in artifacts.items()
            if isinstance(record, dict)
            and record.get("artifact_type") == "creative_software_demo_review"
        }
        if contract_version == "2":
            all_review_refs = set(hook_review_records) | set(
                feasibility_review_records
            )

            def validate_review_task(
                *,
                artifact_id: str,
                record: Mapping[str, Any],
                concept_ref: str,
                expected_stage: str,
            ) -> str | None:
                source_refs = record.get("source_refs")
                if source_refs != [concept_ref]:
                    errors.append(
                        f"Concept Screen review {artifact_id} has invalid "
                        "Concept source"
                    )
                task_id = record.get("task_id")
                task_record = (
                    tasks.get(task_id) if isinstance(task_id, str) else None
                )
                if (
                    not isinstance(task_record, dict)
                    or task_record.get("stage") != expected_stage
                    or task_record.get("status") != "succeeded"
                    or task_record.get("web_search") is not False
                ):
                    errors.append(
                        f"Concept Screen review {artifact_id} has no fresh "
                        "successful non-networked task"
                    )
                    return None
                parent_refs = task_record.get("parent_refs")
                if not isinstance(parent_refs, list):
                    errors.append(
                        f"Concept Screen task {task_id} has invalid parent refs"
                    )
                    return str(task_id)
                expected_artifact_parent_types = {
                    "creative_constraint_view",
                    "creative_brief",
                }
                actual_artifact_parent_types = {
                    artifacts[reference].get("artifact_type")
                    for reference in parent_refs
                    if isinstance(reference, str)
                    and isinstance(artifacts.get(reference), dict)
                    and reference != concept_ref
                }
                if (
                    len(parent_refs) != 4
                    or parent_refs.count(concept_ref) != 1
                    or parent_refs.count("input:software_demo_policy") != 1
                    or actual_artifact_parent_types
                    != expected_artifact_parent_types
                    or any(
                        reference in all_review_refs
                        for reference in parent_refs
                    )
                ):
                    errors.append(
                        f"Concept Screen task {task_id} has non-isolated inputs"
                    )
                return str(task_id)

            for artifact_id, record in hook_review_records.items():
                source_refs = record.get("source_refs")
                concept_ref = (
                    source_refs[0]
                    if isinstance(source_refs, list)
                    and len(source_refs) == 1
                    and isinstance(source_refs[0], str)
                    else ""
                )
                if concept_ref not in concepts:
                    errors.append(
                        f"Hook review {artifact_id} has invalid Concept source"
                    )
                    continue
                validate_review_task(
                    artifact_id=artifact_id,
                    record=record,
                    concept_ref=concept_ref,
                    expected_stage="creative-cheap-hook-review",
                )

            for artifact_id, record in feasibility_review_records.items():
                source_refs = record.get("source_refs")
                concept_ref = (
                    source_refs[0]
                    if isinstance(source_refs, list)
                    and len(source_refs) == 1
                    and isinstance(source_refs[0], str)
                    else ""
                )
                if concept_ref not in concepts:
                    errors.append(
                        f"Software Demo review {artifact_id} has invalid "
                        "Concept source"
                    )
                    continue
                metadata = record.get("metadata")
                if (
                    not isinstance(metadata, dict)
                    or metadata.get("concept_revision_ref") != concept_ref
                    or metadata.get("policy_version")
                    != SOFTWARE_DEMO_POLICY_VERSION
                ):
                    errors.append(
                        f"Software Demo review {artifact_id} has stale metadata"
                    )
                validate_review_task(
                    artifact_id=artifact_id,
                    record=record,
                    concept_ref=concept_ref,
                    expected_stage="creative-software-demo-review",
                )

            for concept_ref, routing in sorted(c4_routing.items()):
                if len(routing) != 1:
                    continue
                evidence_refs = routing[0].get("evidence_refs")
                if not isinstance(evidence_refs, list):
                    errors.append(
                        f"C4 routing {concept_ref} has no evidence_refs"
                    )
                    continue
                source_hook_refs = [
                    ref
                    for ref, record in hook_review_records.items()
                    if record.get("source_refs") == [concept_ref]
                ]
                source_feasibility_refs = [
                    ref
                    for ref, record in feasibility_review_records.items()
                    if record.get("source_refs") == [concept_ref]
                ]
                if (
                    len(source_hook_refs) != 2
                    or len(set(source_hook_refs)) != 2
                ):
                    errors.append(
                        f"C4 routing {concept_ref} requires two Hook reviews"
                    )
                if len(source_feasibility_refs) != 1:
                    errors.append(
                        f"C4 routing {concept_ref} requires one Software Demo review"
                    )
                if (
                    len(evidence_refs) != 3
                    or set(evidence_refs)
                    != set(source_hook_refs) | set(source_feasibility_refs)
                ):
                    errors.append(
                        f"C4 routing {concept_ref} does not bind its exact fresh "
                        "2+1 review batch"
                    )
                revision_metadata = concepts[concept_ref].get("metadata")
                revision = (
                    revision_metadata.get("revision")
                    if isinstance(revision_metadata, dict)
                    else None
                )
                expected_cycle = 1 if revision == 1 else 2 if revision == 2 else None
                hook_slots: set[int] = set()
                review_task_ids: list[str] = []
                for hook_ref in source_hook_refs:
                    hook_record = hook_review_records[hook_ref]
                    metadata = hook_record.get("metadata")
                    if not isinstance(metadata, dict):
                        errors.append(
                            f"Hook review {hook_ref} has no metadata"
                        )
                        continue
                    cycle = metadata.get("cycle")
                    slot = metadata.get("reviewer_slot")
                    if (
                        metadata.get("concept_revision_ref") != concept_ref
                        or cycle != expected_cycle
                        or type(slot) is not int
                    ):
                        errors.append(
                            f"Hook review {hook_ref} has stale cycle/slot metadata"
                        )
                    else:
                        hook_slots.add(slot)
                    task_id = hook_record.get("task_id")
                    if isinstance(task_id, str):
                        review_task_ids.append(task_id)
                if hook_slots != {1, 2}:
                    errors.append(
                        f"C4 routing {concept_ref} requires reviewer slots 1 and 2"
                    )
                for feasibility_ref in source_feasibility_refs:
                    feasibility_record = feasibility_review_records[
                        feasibility_ref
                    ]
                    metadata = feasibility_record.get("metadata")
                    if (
                        not isinstance(metadata, dict)
                        or metadata.get("cycle") != expected_cycle
                    ):
                        errors.append(
                            f"Software Demo review {feasibility_ref} has stale cycle"
                        )
                    task_id = feasibility_record.get("task_id")
                    if isinstance(task_id, str):
                        review_task_ids.append(task_id)
                task_refs = routing[0].get("task_refs")
                if (
                    len(review_task_ids) != 3
                    or len(set(review_task_ids)) != 3
                    or not isinstance(task_refs, list)
                    or len(task_refs) != 3
                    or set(task_refs) != set(review_task_ids)
                ):
                    errors.append(
                        f"C4 routing {concept_ref} does not bind three distinct "
                        "fresh review tasks"
                    )

        novelty_records = {
            str(artifact_id): record
            for artifact_id, record in artifacts.items()
            if isinstance(record, dict)
            and record.get("artifact_type") == "creative_novelty_scan"
        }
        novelty_by_concept: dict[str, list[str]] = {}
        for artifact_id, record in novelty_records.items():
            source_refs = record.get("source_refs", [])
            concept_sources = [
                ref for ref in source_refs if isinstance(ref, str) and ref in concepts
            ] if isinstance(source_refs, list) else []
            if len(concept_sources) != 1 or concept_sources[0] not in hook_passed:
                errors.append(
                    f"Novelty Scan {artifact_id} has no C4-pass Concept source"
                )
            elif len(concept_sources) == 1:
                novelty_by_concept.setdefault(concept_sources[0], []).append(
                    artifact_id
                )

        if state.get("current_stage") in {
            "creative-c5-complete-internal",
            "creative-evidence-revise",
            "creative-portfolio-curate",
            "creative-human-review",
            "creative-c6-empty-complete-internal",
        }:
            for concept_ref in sorted(concepts):
                if _metadata_value(
                    concepts[concept_ref],
                    "revision_reason",
                ) in {"evidence_informed", "human_feedback"}:
                    continue
                routing = c4_routing.get(concept_ref, [])
                if len(routing) != 1:
                    errors.append(
                        f"Creative Concept {concept_ref} must have exactly one "
                        "final C4 routing outcome at C5 completion"
                    )
                    continue
                outcome = routing[0].get("outcome")
                scan_count = len(novelty_by_concept.get(concept_ref, []))
                if outcome == "pass" and scan_count != 1:
                    errors.append(
                        f"C4-pass Concept {concept_ref} must have exactly one "
                        "Novelty Scan"
                    )
                elif outcome != "pass" and scan_count:
                    errors.append(
                        f"non-pass Concept {concept_ref} must not have a "
                        "Novelty Scan"
                    )

        evidence_concepts = {
            artifact_id: record
            for artifact_id, record in concepts.items()
            if _metadata_value(record, "revision_reason") == "evidence_informed"
        }
        for artifact_id, record in evidence_concepts.items():
            metadata = record.get("metadata")
            if not isinstance(metadata, dict):
                continue
            source_ref = metadata.get("supersedes_ref")
            if source_ref not in hook_passed:
                errors.append(
                    f"C6A Concept {artifact_id} does not supersede a C4-pass source"
                )
            novelty_ref = metadata.get("novelty_scan_ref")
            if (
                not isinstance(novelty_ref, str)
                or novelty_ref not in novelty_records
                or novelty_ref
                not in novelty_by_concept.get(str(source_ref), [])
            ):
                errors.append(
                    f"C6A Concept {artifact_id} has no bound source Novelty Scan"
                )
            if contract_version == "2":
                c6a_feasibility_ref = metadata.get(
                    "software_demo_review_ref"
                )
                if (
                    not isinstance(c6a_feasibility_ref, str)
                    or c6a_feasibility_ref not in feasibility_review_records
                ):
                    errors.append(
                        f"C6A Concept {artifact_id} has no bound Software Demo review"
                    )
            source_dispositions = [
                row
                for row in dispositions_by_concept.get(str(source_ref), [])
                if row.get("outcome")
                == "superseded_by_evidence_revision"
                and row.get("target_ref") == artifact_id
            ]
            if len(source_dispositions) != 1:
                errors.append(
                    f"C6A Concept {artifact_id} requires exactly one source "
                    "successor disposition"
                )

        curation_records = {
            str(artifact_id): record
            for artifact_id, record in artifacts.items()
            if isinstance(record, dict)
            and record.get("artifact_type") == "creative_portfolio_curation"
        }
        expected_curation_refs = set(evidence_concepts)
        for artifact_id, record in curation_records.items():
            task_id = record.get("task_id")
            task_record = tasks.get(task_id) if isinstance(task_id, str) else None
            if (
                not isinstance(task_record, dict)
                or task_record.get("stage") != "creative-portfolio-curate"
                or task_record.get("status") != "succeeded"
            ):
                errors.append(
                    f"Portfolio curation {artifact_id} has no successful curator task"
                )
            source_refs = record.get("source_refs")
            if (
                not isinstance(source_refs, list)
                or set(source_refs) != expected_curation_refs
                or len(source_refs) != len(expected_curation_refs)
            ):
                errors.append(
                    f"Portfolio curation {artifact_id} has an invalid Concept pool"
                )
            try:
                raw_curation = json.loads(hub.read_artifact(artifact_id))
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                StateError,
            ) as exc:
                errors.append(f"invalid Portfolio curation {artifact_id}: {exc}")
                continue
            rows = (
                raw_curation.get("classifications")
                if isinstance(raw_curation, dict)
                else None
            )
            if not isinstance(rows, list):
                errors.append(
                    f"Portfolio curation {artifact_id} has no classifications"
                )
                continue
            classified_refs: list[str] = []
            for row in rows:
                if not isinstance(row, dict):
                    errors.append(
                        f"Portfolio curation {artifact_id} has invalid row"
                    )
                    continue
                reference = row.get("concept_ref")
                decision = row.get("decision")
                if not isinstance(reference, str):
                    errors.append(
                        f"Portfolio curation {artifact_id} has invalid Concept ref"
                    )
                else:
                    classified_refs.append(reference)
                if decision not in {"include", "hold", "exclude"}:
                    errors.append(
                        f"Portfolio curation {artifact_id} has invalid decision"
                    )
                if contract_version == "2":
                    dimensions = row.get("dimensions")
                    if not isinstance(dimensions, list):
                        errors.append(
                            f"Portfolio curation {artifact_id} has no dimensions"
                        )
                    else:
                        names = tuple(
                            dimension.get("dimension")
                            for dimension in dimensions
                            if isinstance(dimension, dict)
                        )
                        verdicts = tuple(
                            dimension.get("verdict")
                            for dimension in dimensions
                            if isinstance(dimension, dict)
                        )
                        expected_decision = (
                            "exclude"
                            if "fail" in verdicts
                            else "hold"
                            if "uncertain" in verdicts
                            else "include"
                        )
                        if (
                            names != PORTFOLIO_DIMENSIONS
                            or len(verdicts) != len(PORTFOLIO_DIMENSIONS)
                            or decision != expected_decision
                        ):
                            errors.append(
                                f"Portfolio curation {artifact_id} violates "
                                "categorical decision contract"
                            )
                if "primary_territory_ref" in row or "score" in row:
                    errors.append(
                        f"Portfolio curation {artifact_id} rewrites controller data"
                    )
            if (
                set(classified_refs) != expected_curation_refs
                or len(classified_refs) != len(expected_curation_refs)
            ):
                errors.append(
                    f"Portfolio curation {artifact_id} does not cover C6A exactly"
                )

        batch_records = {
            str(artifact_id): record
            for artifact_id, record in artifacts.items()
            if isinstance(record, dict)
            and record.get("artifact_type") == "creative_human_review_batch"
        }
        if len(batch_records) > 1:
            errors.append("Creative C6 may publish only one HumanReviewBatch")
        review_batch: ReviewBatch | None = None
        batch_id: str | None = None
        batch_record: dict[str, Any] | None = None
        shortlist_refs: set[str] = set()
        closed_resolution_id: str | None = None
        closed_resolution_sha256: str | None = None
        if len(batch_records) == 1:
            batch_id, batch_record = next(iter(batch_records.items()))
            try:
                raw_batch = json.loads(hub.read_artifact(batch_id))
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                StateError,
            ) as exc:
                errors.append(f"invalid HumanReviewBatch {batch_id}: {exc}")
            else:
                if isinstance(raw_batch, dict):
                    try:
                        review_batch = ReviewBatch.from_dict(raw_batch)
                    except ReviewError as exc:
                        errors.append(
                            f"invalid HumanReviewBatch {batch_id}: {exc}"
                        )
                else:
                    errors.append("HumanReviewBatch payload must be an object")

        if (
            review_batch is not None
            and batch_record is not None
            and batch_id is not None
        ):
            refs = list(review_batch.concept_refs)
            shortlist_refs = set(refs)
            skip_reason = review_batch.skip_reason
            if (
                review_batch.batch_id != batch_id
                or review_batch.run_id != state.get("run_id")
            ):
                errors.append("HumanReviewBatch identity does not match its run")
            max_shortlist = (
                int(settings.max_human_shortlist)
                if settings is not None
                else 8
            )
            if len(refs) > max_shortlist:
                errors.append("HumanReviewBatch exceeds persisted shortlist limit")
            if any(ref not in evidence_concepts for ref in refs):
                errors.append("HumanReviewBatch references a non-C6A Concept")
            for binding in review_batch.concepts:
                reference = binding.concept_ref
                batch_concept_record = concepts.get(reference)
                if (
                    not isinstance(batch_concept_record, dict)
                    or binding.concept_sha256 != batch_concept_record.get("sha256")
                ):
                    errors.append(
                        f"HumanReviewBatch Concept hash mismatch: {reference}"
                    )
            c6b_outcomes: dict[str, list[str]] = {}
            for reference in evidence_concepts:
                outcomes = [
                    str(row.get("outcome"))
                    for row in dispositions_by_concept.get(reference, [])
                    if row.get("stage") == "C6B"
                    and row.get("outcome")
                    in {"shortlisted", "not_shortlisted"}
                ]
                c6b_outcomes[reference] = outcomes
                if len(outcomes) != 1:
                    errors.append(
                        f"C6A Concept {reference} requires exactly one C6B disposition"
                    )
            disposition_shortlist = {
                reference
                for reference, outcomes in c6b_outcomes.items()
                if outcomes == ["shortlisted"]
            }
            if set(refs) != disposition_shortlist:
                errors.append(
                    "HumanReviewBatch refs do not match shortlisted dispositions"
                )
            wait = state.get("wait")
            if review_batch.status == "ready":
                if len(curation_records) != 2:
                    errors.append(
                        "non-empty C6 shortlist requires two independent curators"
                    )
                review_round = ReviewRound.open(review_batch)
                common_round_binding = (
                    isinstance(wait, dict)
                    and wait.get("kind") == "creative_human_review"
                    and wait.get("round_id") == review_round.round_id
                    and wait.get("round_artifact_id") == batch_id
                    and wait.get("round_sha256") == review_round.round_sha256
                    and wait.get("batch_sha256") == review_batch.batch_sha256
                    and wait.get("batch_artifact_sha256")
                    == batch_record.get("sha256")
                    and wait.get("status") in {"open", "closed"}
                )
                wait_status = wait.get("status") if isinstance(wait, dict) else None
                lifecycle_matches = (
                    wait_status == "open"
                    and state.get("status") == "waiting"
                    and state.get("current_stage") == "creative-human-review"
                ) or (
                    wait_status == "closed"
                    and (
                        (
                            state.get("status") == "waiting"
                            and state.get("current_stage")
                            == "creative-human-review"
                        )
                        or (
                            state.get("status") == "running"
                            and state.get("current_stage")
                            in {
                                "creative-feedback-revise",
                                "creative-c6-feedback-complete-internal",
                                "creative-finalization",
                            }
                        )
                        or state.get("status") in {"failed", "completed"}
                    )
                )
                if (
                    not common_round_binding
                    or not lifecycle_matches
                ):
                    errors.append(
                        "ready HumanReviewBatch does not match persisted ReviewRound"
                    )
                try:
                    review_snapshot = ReviewStore(
                        hub,
                        review_round,
                    ).snapshot()
                except (OSError, StateError, ReviewError) as exc:
                    errors.append(f"invalid persisted ReviewRound: {exc}")
                else:
                    resolution = review_snapshot.resolution
                    if wait_status == "open" and resolution is not None:
                        errors.append(
                            "open ReviewRound must not have a persisted resolution"
                        )
                    elif wait_status == "closed":
                        if resolution is None:
                            errors.append(
                                "closed ReviewRound has no persisted resolution"
                            )
                        else:
                            closed_resolution_id = resolution.resolution_id
                            closed_resolution_sha256 = (
                                resolution.resolution_sha256
                            )
                            if not isinstance(wait, dict) or any(
                                wait.get(key) != expected
                                for key, expected in (
                                    (
                                        "resolution_id",
                                        resolution.resolution_id,
                                    ),
                                    (
                                        "resolution_sha256",
                                        resolution.resolution_sha256,
                                    ),
                                    (
                                        "latest_receipt_set_sha256",
                                        resolution.latest_receipt_set_sha256,
                                    ),
                                    (
                                        "approved_feedback_set_sha256",
                                        resolution.approved_feedback_set_sha256,
                                    ),
                                )
                            ):
                                errors.append(
                                    "closed ReviewRound resolution binding is stale"
                                )
            else:
                if wait is not None or state.get("status") == "waiting":
                    errors.append("empty HumanReviewBatch must not create a wait")
                expected_reason = (
                    "no_concepts_generated"
                    if base_count + memory_count == 0
                    else (
                        "all_candidates_failed_concept_screen"
                        if contract_version == "2"
                        else "all_candidates_failed_hook"
                    )
                    if not hook_passed
                    else "shortlist_empty"
                )
                if skip_reason != expected_reason:
                    errors.append(
                        "empty HumanReviewBatch skip_reason does not match routing"
                    )
                if skip_reason == "shortlist_empty" and len(curation_records) != 2:
                    errors.append(
                        "shortlist_empty requires two independent curators"
                    )
                if skip_reason != "shortlist_empty" and curation_records:
                    errors.append(
                        "pre-curation empty batch must not run portfolio curators"
                    )
            if expected_curation_refs and set(hook_passed) != {
                str(_metadata_value(record, "supersedes_ref"))
                for record in evidence_concepts.values()
            }:
                errors.append(
                    "every C4-pass Concept must receive exactly one C6A revision"
                )

        c6c_tasks = {
            str(task_id): record
            for task_id, record in tasks.items()
            if isinstance(record, dict)
            and record.get("stage") == C6C_FEEDBACK_REVISE
        }
        for task_id, record in c6c_tasks.items():
            parent_refs = record.get("parent_refs")
            if (
                not isinstance(parent_refs, list)
                or any(not isinstance(ref, str) for ref in parent_refs)
            ):
                errors.append(f"C6C task {task_id} has invalid parent_refs")
                continue
            # C6C task parent refs deliberately span two namespaces:
            # artifacts provide source/evidence lineage, while exactly one
            # immutable resolution ledger ID authorizes the human-feedback
            # transition.
            if (
                closed_resolution_id is None
                or parent_refs.count(closed_resolution_id) != 1
            ):
                errors.append(
                    f"C6C task {task_id} must name its closed resolution "
                    "exactly once"
                )
            source_parents = {
                ref for ref in parent_refs if ref in concepts
            }
            if (
                not source_parents
                or not source_parents.issubset(shortlist_refs)
            ):
                errors.append(
                    f"C6C task {task_id} has invalid shortlisted Concept parents"
                )

        expected_final_refs = {
            final_idea_id(index)
            for index in range(1, len(final_ideas) + 1)
        }
        if set(final_ideas) != expected_final_refs:
            errors.append("Creative Final Idea IDs are not contiguous")
        for idea_ref, record in final_ideas.items():
            metadata = record.get("metadata")
            if not isinstance(metadata, dict):
                errors.append(f"Final Idea {idea_ref} has no metadata")
                continue
            action = metadata.get("action")
            source_refs = metadata.get("source_concept_refs")
            registered_sources = record.get("source_refs")
            if (
                not isinstance(source_refs, list)
                or not source_refs
                or any(not isinstance(ref, str) for ref in source_refs)
                or len(source_refs) != len(set(source_refs))
                or not set(source_refs).issubset(shortlist_refs)
                or registered_sources != source_refs
            ):
                errors.append(
                    f"Final Idea {idea_ref} has invalid shortlisted sources"
                )
                continue
            if (
                action in {"keep", "revise"}
                and len(source_refs) != 1
                or action == "merge"
                and len(source_refs) < 2
                or action not in {"keep", "revise", "merge"}
            ):
                errors.append(f"Final Idea {idea_ref} has invalid action lineage")
                continue
            source_records = [concepts[ref] for ref in source_refs]
            source_hashes = [source.get("sha256") for source in source_records]
            source_territories = {
                _metadata_value(source, "primary_territory_ref")
                for source in source_records
            }
            if metadata.get("source_concept_sha256s") != source_hashes:
                errors.append(f"Final Idea {idea_ref} source hash mismatch")
            if (
                metadata.get("resolution_id") != closed_resolution_id
                or metadata.get("resolution_sha256")
                != closed_resolution_sha256
            ):
                errors.append(f"Final Idea {idea_ref} resolution binding is stale")
            if metadata.get("primary_territory_ref") not in source_territories:
                errors.append(f"Final Idea {idea_ref} changed primary territory")

            task_id = record.get("task_id")
            if action == "keep":
                if task_id is not None or record.get("sha256") != source_hashes[0]:
                    errors.append(
                        f"kept Final Idea {idea_ref} is not byte-exact"
                    )
            else:
                task_record = (
                    tasks.get(task_id) if isinstance(task_id, str) else None
                )
                if (
                    not isinstance(task_record, dict)
                    or task_record.get("stage") != C6C_FEEDBACK_REVISE
                    or task_record.get("status") != "succeeded"
                ):
                    errors.append(
                        f"Final Idea {idea_ref} has no successful C6C task"
                    )
                else:
                    task_parents = task_record.get("parent_refs")
                    concept_parents = {
                        ref
                        for ref in task_parents
                        if isinstance(ref, str) and ref in concepts
                    } if isinstance(task_parents, list) else set()
                    if concept_parents != set(source_refs):
                        errors.append(
                            f"Final Idea {idea_ref} task/source lineage mismatch"
                        )

        c6c_dispositions = [
            row for row in dispositions if row.get("stage") == "C6C"
        ]
        for disposition in c6c_dispositions:
            if disposition.get("concept_revision_ref") not in shortlist_refs:
                errors.append(
                    "C6C disposition references a non-shortlisted Concept"
                )
        disposition_targets = {
            str(row["target_ref"])
            for row in c6c_dispositions
            if row.get("target_ref") is not None
        }
        if disposition_targets != set(final_ideas):
            errors.append(
                "C6C dispositions do not close every Final Idea target"
            )
        c6c_complete = (
            state.get("current_stage")
            in {
                "creative-c6-feedback-complete-internal",
                "creative-finalization",
            }
            or state.get("status") == "completed"
        )
        if c6c_complete:
            for concept_ref in shortlist_refs:
                source_rows = [
                    row
                    for row in c6c_dispositions
                    if row.get("concept_revision_ref") == concept_ref
                    and row.get("terminal") is True
                ]
                if len(source_rows) != 1:
                    errors.append(
                        f"shortlisted Concept {concept_ref} requires exactly "
                        "one terminal C6C disposition"
                    )

        summaries = [
            artifact_id
            for artifact_id, record in artifacts.items()
            if isinstance(record, dict)
            and record.get("artifact_type") == "creative_memory_stage_summary"
        ]
        reached_memory = any(
            isinstance(raw, dict)
            and raw.get("stage") in {
                "creative-memory-recall",
                "creative-memory-remix",
                "creative-novelty-scan",
            }
            for raw in tasks.values()
        ) or state.get("current_stage") in {
            "creative-c5-complete-internal",
            "creative-novelty-scan",
        }
        if reached_memory and len(summaries) != 1:
            errors.append("Creative C5 must publish exactly one MemoryStageSummary")
        elif len(summaries) == 1:
            summary_id = str(summaries[0])
            try:
                summary = MemoryStageSummary.from_mapping(
                    json.loads(hub.read_artifact(summary_id))
                )
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                StateError,
                MemoryValidationError,
            ) as exc:
                errors.append(f"invalid MemoryStageSummary {summary_id}: {exc}")
            else:
                summary_record = artifacts.get(summary_id)
                summary_metadata = (
                    summary_record.get("metadata")
                    if isinstance(summary_record, dict)
                    else None
                )
                if (
                    not isinstance(summary_metadata, dict)
                    or summary_metadata.get("status") != summary.status
                    or summary_metadata.get("selected_cue_ids")
                    != list(summary.selected_cue_ids)
                ):
                    errors.append(
                        "MemoryStageSummary metadata does not match its payload"
                    )
                referenced_diagnostics: set[str] = set()
                memory_slots: list[
                    tuple[MemoryTaskSlot | MemoryRemixSlot, str]
                ] = [
                    (summary.recall, "creative-memory-recall"),
                    *(
                        (slot, "creative-memory-remix")
                        for slot in summary.remix_slots
                    ),
                ]
                for slot, expected_stage in memory_slots:
                    if slot.task_ref is not None:
                        task_record = tasks.get(slot.task_ref)
                        if not isinstance(task_record, dict):
                            errors.append(
                                "MemoryStageSummary references unknown task "
                                f"{slot.task_ref}"
                            )
                        elif task_record.get("stage") != expected_stage:
                            errors.append(
                                "MemoryStageSummary task stage mismatch for "
                                f"{slot.task_ref}"
                            )
                        elif slot.status == "succeeded" and task_record.get(
                            "status"
                        ) != "succeeded":
                            errors.append(
                                "MemoryStageSummary marks non-successful task "
                                f"{slot.task_ref} as succeeded"
                            )
                        elif slot.status in {"failed", "invalidated"} and (
                            task_record.get("status")
                            not in {"failed", "invalidated"}
                        ):
                            errors.append(
                                "MemoryStageSummary failure status does not "
                                f"match task {slot.task_ref}"
                            )
                    if slot.diagnostic_ref is not None:
                        referenced_diagnostics.add(slot.diagnostic_ref)
                event_ids = {
                    str(row.get("event_id"))
                    for rows in optional_failure_events.values()
                    for row in rows
                    if isinstance(row.get("event_id"), str)
                }
                if referenced_diagnostics != event_ids:
                    errors.append(
                        "MemoryStageSummary diagnostic refs do not exactly "
                        "match optional failure events"
                    )
                for slot in summary.remix_slots:
                    if slot.challenger_ref is None:
                        continue
                    challenger = concepts.get(slot.challenger_ref)
                    if (
                        not isinstance(challenger, dict)
                        or _metadata_value(challenger, "origin")
                        != "memory_challenger"
                        or challenger.get("task_id") != slot.task_ref
                    ):
                        errors.append(
                            "MemoryStageSummary challenger/task link is invalid: "
                            f"{slot.challenger_ref}"
                        )
        errors.extend(
            _validate_creative_c7(
                hub,
                state,
                artifacts,
                concepts,
                dispositions,
            )
        )
        return errors


_CONTRACTS: dict[str, RunContract] = {
    "useful": UsefulRunContract(),
    "creative": CreativeRunContract(),
}


def register_run_contract(contract: RunContract, *, replace: bool = False) -> None:
    """Register a route contract; Creative uses this after its package loads."""

    route_id = contract.route_id
    if not isinstance(route_id, str) or not route_id:
        raise ValueError("route contract requires a non-empty route_id")
    if route_id in _CONTRACTS and not replace:
        raise RouteContractError(f"route contract is already registered: {route_id}")
    _CONTRACTS[route_id] = contract


def get_run_contract(
    state: Mapping[str, Any],
) -> RunContract:
    """Resolve and version-check the contract encoded in a run snapshot."""

    schema_version = state.get("schema_version")
    if schema_version not in {LEGACY_RUN_SCHEMA_VERSION, RUN_SCHEMA_VERSION}:
        raise RouteContractError(
            f"unsupported run schema version: {schema_version!r}"
        )
    route = state.get("route")
    if not isinstance(route, dict):
        raise RouteContractError("run has no route metadata")
    route_id = route.get("id")
    if not isinstance(route_id, str) or not route_id:
        raise RouteContractError("run route has no non-empty id")
    contract = _CONTRACTS.get(route_id)
    if contract is None:
        raise RouteContractError(f"unknown run route: {route_id!r}")
    if schema_version not in contract.supported_schema_versions:
        raise RouteContractError(
            f"route {route_id!r} does not support run schema {schema_version}"
        )
    contract_version = route.get("contract_version")
    supported_contract_versions = getattr(
        contract,
        "supported_contract_versions",
        frozenset({contract.contract_version}),
    )
    if contract_version not in supported_contract_versions:
        raise RouteContractError(
            f"unsupported {route_id!r} contract version: {contract_version!r}"
        )
    if schema_version == LEGACY_RUN_SCHEMA_VERSION and route_id != "useful":
        raise RouteContractError("schema v1 can only be projected as route 'useful'")
    if schema_version == RUN_SCHEMA_VERSION:
        for key in (
            "prompt_policy_version",
            "stage_policy_version",
            "report_policy_version",
        ):
            value = route.get(key)
            if not isinstance(value, str) or not value:
                raise RouteContractError(
                    f"route {route_id!r} has no valid {key}"
                )
    return contract


def inspect_run(run_dir: str | Path) -> dict[str, Any]:
    hub = RunHub(run_dir)
    state = hub.load_state()
    contract = get_run_contract(state)
    return contract.inspect(hub, state)


def validate_run(run_dir: str | Path) -> list[str]:
    try:
        hub = RunHub(run_dir)
        state = hub.load_state()
        contract = get_run_contract(state)
    except (OSError, StateError) as exc:
        return [str(exc)]
    errors = hub.core_validate()
    errors.extend(contract.validate(hub, state))
    return errors


def _metadata_value(record: Mapping[str, Any], key: str) -> Any:
    metadata = record.get("metadata")
    return metadata.get(key) if isinstance(metadata, dict) else None


def _first_artifact_of_type(
    artifacts: Mapping[str, Any],
    artifact_type: str,
) -> str | None:
    values = sorted(
        str(artifact_id)
        for artifact_id, record in artifacts.items()
        if isinstance(record, dict) and record.get("artifact_type") == artifact_type
    )
    return values[0] if values else None


def _creative_dispositions(
    hub: RunHub,
    artifacts: Mapping[str, Any],
    *,
    errors: list[str] | None = None,
) -> list[dict[str, Any]]:
    dispositions: list[dict[str, Any]] = []
    for artifact_id, record in sorted(artifacts.items()):
        if not isinstance(record, dict) or record.get(
            "artifact_type"
        ) != "creative_concept_disposition":
            continue
        try:
            value = json.loads(hub.read_artifact(str(artifact_id)))
        except (OSError, UnicodeError, json.JSONDecodeError, StateError) as exc:
            if errors is not None:
                errors.append(f"invalid Creative disposition {artifact_id}: {exc}")
            continue
        if not isinstance(value, dict):
            if errors is not None:
                errors.append(
                    f"Creative disposition {artifact_id} must be an object"
                )
            continue
        dispositions.append(value)
    return dispositions


def _creative_review_ledger_counts(
    hub: RunHub,
    *,
    review_batch_ref: str | None,
    review_batch: Mapping[str, Any],
) -> tuple[int, int]:
    """Project current reviewer/coverage counts from the durable ledger."""

    if review_batch_ref is None or not review_batch:
        return 0, 0
    from hacksome.creative.review import (
        ReviewBatch,
        ReviewError,
        ReviewRound,
        ReviewStore,
    )

    try:
        batch = ReviewBatch.from_dict(review_batch)
        if batch.status != "ready":
            return 0, 0
        snapshot = ReviewStore(hub, ReviewRound.open(batch)).snapshot()
    except (OSError, StateError, ReviewError):
        return 0, 0
    return (
        len(snapshot.latest_reviews),
        sum(item.covered for item in snapshot.coverage),
    )


def _creative_finalization_projection(
    hub: RunHub,
    state: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    *,
    needs_reconcile: bool,
) -> _FinalizationProjection:
    """Read and verify the immutable C7 plan without repairing persisted state."""

    from hacksome.creative.finalization import (
        FINALIZATION_MANIFEST_PATH,
        FINALIZATION_STAGE,
        FinalizationCoordinator,
        FinalizationError,
        FinalizationManifest,
    )

    manifest_path = hub.run_dir / FINALIZATION_MANIFEST_PATH
    pointer = state.get("finalization")
    if pointer is None and not manifest_path.exists():
        return _FinalizationProjection(
            status="not_started",
            manifest_ref=None,
            planned_artifact_count=0,
            published_artifact_count=0,
            resumable=False,
        )

    errors: list[str] = []
    manifest: FinalizationManifest | None = None
    phase = "publishing"
    failed_plan = False
    try:
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise StateError(
                "finalization manifest is missing or not a regular file"
            )
        raw_bytes = manifest_path.read_bytes()
        decoded = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise StateError("finalization manifest must be an object")
        manifest = FinalizationManifest.from_dict(decoded)
        canonical = canonical_json_bytes(manifest.to_dict())
        if raw_bytes != canonical:
            raise StateError("finalization manifest bytes are not canonical")
        manifest_sha256 = sha256_bytes(raw_bytes)
        if manifest_sha256 != manifest.manifest_sha256:
            raise StateError("finalization manifest hash is inconsistent")

        if pointer is not None:
            if not isinstance(pointer, dict) or set(pointer) != {
                "id",
                "manifest_path",
                "manifest_sha256",
                "phase",
            }:
                raise StateError(
                    "run finalization pointer has invalid fields"
                )
            phase_value = pointer.get("phase")
            if phase_value not in {"publishing", "completed"}:
                raise StateError("run finalization phase is invalid")
            phase = str(phase_value)
            if (
                pointer.get("id") != manifest.finalization_id
                or pointer.get("manifest_path")
                != FINALIZATION_MANIFEST_PATH
                or pointer.get("manifest_sha256") != manifest_sha256
            ):
                raise StateError(
                    "run finalization pointer does not match its manifest"
                )
        if manifest.source.run_id != state.get("run_id"):
            raise StateError("finalization manifest belongs to another run")
        route = state.get("route")
        if not isinstance(route, dict) or (
            manifest.source.route_contract_version
            != route.get("contract_version")
            or manifest.report_policy_version
            != route.get("report_policy_version")
        ):
            raise StateError("finalization manifest route policy mismatch")

        if phase == "completed":
            if (
                state.get("status") != "completed"
                or state.get("current_stage") != FINALIZATION_STAGE
            ):
                raise StateError(
                    "completed finalization has an invalid run lifecycle"
                )
            coordinator = FinalizationCoordinator(hub)
            coordinator._verify_staged_and_existing(manifest)
            coordinator._validate_source_and_progress(
                manifest,
                hub.load_consistent_snapshot(),
            )
        elif state.get("status") == "failed":
            if (
                pointer is None
                or state.get("current_stage") != FINALIZATION_STAGE
            ):
                raise StateError(
                    "failed finalization has an invalid run lifecycle"
                )
            failed_plan = True
            audit_errors = _failed_finalization_audit_errors(
                hub,
                state,
                artifacts,
                manifest,
            )
            if audit_errors:
                raise StateError("; ".join(audit_errors))
        else:
            if (
                state.get("status") != "running"
                or state.get("current_stage") != FINALIZATION_STAGE
            ):
                raise StateError(
                    "publishing finalization has an invalid run lifecycle"
                )
            coordinator = FinalizationCoordinator(hub)
            coordinator._verify_staged_and_existing(manifest)
            coordinator._validate_source_and_progress(
                manifest,
                hub.load_consistent_snapshot(),
            )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        StateError,
        FinalizationError,
        ValueError,
    ) as exc:
        errors.append(f"invalid Creative finalization: {exc}")

    planned = len(manifest.outputs) if manifest is not None else 0
    published = 0
    if manifest is not None:
        published = sum(
            artifacts.get(output.artifact_id) == output.artifact_record
            for output in manifest.outputs
        )
    if errors or failed_plan:
        status = "corrupt"
    else:
        status = "completed" if phase == "completed" else "publishing"
    return _FinalizationProjection(
        status=status,
        manifest_ref=(
            FINALIZATION_MANIFEST_PATH if manifest is not None else None
        ),
        planned_artifact_count=planned,
        published_artifact_count=published,
        resumable=(
            status == "publishing"
            and not needs_reconcile
        ),
        manifest=manifest,
        errors=tuple(errors),
    )


def _failed_finalization_audit_errors(
    hub: RunHub,
    state: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    manifest: Any,
) -> tuple[str, ...]:
    """Validate the frozen plan as audit evidence after fail-closed C7."""

    from hacksome.creative.finalization import FINALIZATION_STAGE
    from hacksome.creative.partial_report import (
        PARTIAL_REPORT_JSON_ID,
        PARTIAL_REPORT_MARKDOWN_ID,
    )

    errors: list[str] = []
    if (
        state.get("status") != "failed"
        or state.get("current_stage") != FINALIZATION_STAGE
        or state.get("result_artifact_ids") != []
        or not isinstance(state.get("terminal_error"), dict)
        or state.get("transition_seq")
        != manifest.source.transition_seq + 1
    ):
        errors.append("failed C7 lifecycle does not match its frozen plan")
    if state.get("pending_records") != []:
        errors.append("failed C7 audit has unreconciled ledger records")

    planned_ids = {output.artifact_id for output in manifest.outputs}
    published_outputs: list[Any] = []
    saw_gap = False
    for output in manifest.outputs:
        record = artifacts.get(output.artifact_id)
        if record is None:
            saw_gap = True
            continue
        if saw_gap:
            errors.append(
                "failed C7 artifacts are not a contiguous manifest prefix"
            )
        published_outputs.append(output)
        if record != output.artifact_record:
            errors.append(
                f"failed C7 artifact record changed: {output.artifact_id}"
            )

    registered_success = _artifact_ids_of_types(
        artifacts,
        _SUCCESS_FINAL_TYPES,
    )
    published_ids = {output.artifact_id for output in published_outputs}
    if registered_success != published_ids:
        errors.append(
            "failed C7 final outputs are not the exact manifest prefix"
        )
    plan_linked_ids = {
        str(artifact_id)
        for artifact_id, record in artifacts.items()
        if isinstance(record, dict)
        and isinstance(record.get("metadata"), dict)
        and record["metadata"].get("finalization_id")
        == manifest.finalization_id
    }
    if plan_linked_ids != published_ids or not plan_linked_ids.issubset(
        planned_ids
    ):
        errors.append(
            "failed C7 plan-linked artifacts do not match the manifest"
        )

    try:
        snapshot = hub.load_consistent_snapshot()
    except (OSError, StateError) as exc:
        return (*errors, f"cannot read failed C7 audit ledgers: {exc}")
    ledgers = snapshot.get("ledgers")
    if not isinstance(ledgers, dict):
        return (*errors, "failed C7 audit ledgers are invalid")

    for head in manifest.source.ledger_heads:
        records = ledgers.get(head.ledger)
        if not isinstance(records, list):
            errors.append(f"failed C7 {head.ledger} ledger is invalid")
            continue
        if (
            len(records) < head.record_count
            or not head.matches(records[: head.record_count])
        ):
            errors.append(
                f"failed C7 {head.ledger} source prefix changed"
            )
        if head.ledger != "events" and len(records) != head.record_count:
            errors.append(
                f"failed C7 {head.ledger} ledger changed after freeze"
            )

    event_head = manifest.source.head("events")
    events = ledgers.get("events")
    if not isinstance(events, list) or len(events) < event_head.record_count:
        return (*errors, "failed C7 events ledger is invalid")
    suffix = events[event_head.record_count :]
    planned_events = [
        output.publish_event for output in published_outputs
    ]
    if suffix[: len(planned_events)] != planned_events:
        errors.append(
            "failed C7 events lack the exact planned publish prefix"
        )

    terminal_error = state.get("terminal_error")
    failure_event = {
        "event_id": manifest.completed_transition.event_id,
        "kind": "run.status",
        "data": {
            "from_status": "running",
            "to_status": "failed",
            "status": "failed",
            "stage": FINALIZATION_STAGE,
            "reason": None,
        },
        "created_at": (
            terminal_error.get("at")
            if isinstance(terminal_error, dict)
            else None
        ),
    }
    if (
        not isinstance(terminal_error, dict)
        or terminal_error.get("event_id") != failure_event["event_id"]
        or terminal_error.get("stage") != FINALIZATION_STAGE
    ):
        errors.append("failed C7 terminal error is not bound to its transition")

    partial_records: list[tuple[str, Mapping[str, Any]]] = []
    for artifact_id in (
        PARTIAL_REPORT_MARKDOWN_ID,
        PARTIAL_REPORT_JSON_ID,
    ):
        record = artifacts.get(artifact_id)
        if not isinstance(record, dict):
            continue
        partial_records.append((artifact_id, record))
    fixed_prefix = [*planned_events, failure_event]
    partial_suffix = suffix[len(fixed_prefix) :]
    partial_events_match = len(partial_suffix) == len(partial_records)
    for event, (artifact_id, record) in zip(
        partial_suffix,
        partial_records,
        strict=False,
    ):
        partial_events_match = partial_events_match and (
            isinstance(event, dict)
            and set(event) == {
                "event_id",
                "kind",
                "data",
                "created_at",
            }
            and event.get("event_id")
            == f"artifact:{artifact_id}:published"
            and event.get("kind") == "artifact.published"
            and event.get("data")
            == {
                "artifact_id": artifact_id,
                "artifact_type": record.get("artifact_type"),
            }
            and isinstance(event.get("created_at"), str)
            and bool(event.get("created_at"))
        )
    if (
        suffix[: len(fixed_prefix)] != fixed_prefix
        or not partial_events_match
    ):
        errors.append(
            "failed C7 events are not the exact plan/failure/partial sequence"
        )
    return tuple(errors)


def _validate_creative_c7(
    hub: RunHub,
    state: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    concepts: Mapping[str, Mapping[str, Any]],
    dispositions: list[dict[str, Any]],
) -> list[str]:
    """Validate the status-specific C7 publication contract."""

    errors: list[str] = []
    for artifact_id, record in artifacts.items():
        if (
            isinstance(record, dict)
            and record.get("artifact_type") in _LEGACY_REPORT_TYPES
        ):
            errors.append(
                f"Creative report {artifact_id} uses a non-canonical artifact type"
            )

    finalization = _creative_finalization_projection(
        hub,
        state,
        artifacts,
        needs_reconcile=bool(state.get("pending_records")),
    )
    success_ids = _artifact_ids_of_types(artifacts, _SUCCESS_FINAL_TYPES)
    partial_ids = _artifact_ids_of_types(artifacts, _PARTIAL_REPORT_TYPES)
    raw_results = state.get("result_artifact_ids")
    result_ids = raw_results if isinstance(raw_results, list) else []
    status = state.get("status")
    if status not in _CREATIVE_RUN_STATUSES:
        errors.append(f"Creative run has unsupported status: {status!r}")
        return errors

    if status == "failed":
        if result_ids:
            errors.append("failed Creative run must not expose result artifact IDs")
        if finalization.manifest is None:
            if success_ids:
                errors.append(
                    "failed Creative run contains unplanned C7 outputs"
                )
        else:
            planned_ids = {
                output.artifact_id
                for output in finalization.manifest.outputs
            }
            if not success_ids.issubset(planned_ids):
                errors.append(
                    "failed Creative run contains unplanned C7 outputs"
                )
        if finalization.status == "not_started":
            pass
        elif (
            finalization.status != "corrupt"
            or finalization.manifest is None
        ):
            errors.extend(finalization.errors)
            errors.append(
                "failed Creative run has an invalid C7 audit manifest"
            )
        else:
            errors.extend(finalization.errors)
        _validate_partial_bundle(hub, state, artifacts, partial_ids, errors)
        return errors

    if status == "waiting":
        if success_ids or partial_ids:
            errors.append("waiting Creative run must not contain C7 outputs")
        if result_ids:
            errors.append("waiting Creative run must not expose result artifact IDs")
        if finalization.status != "not_started":
            errors.extend(finalization.errors)
            errors.append("waiting Creative run must not have a C7 finalization")
        return errors

    if status == "completed":
        if partial_ids:
            errors.append("completed Creative run must not contain partial reports")
        errors.extend(finalization.errors)
        if (
            finalization.manifest is not None
            and result_ids
            != list(finalization.manifest.result_artifact_ids)
        ):
            errors.append(
                "completed Creative result artifact IDs do not match the manifest"
            )
        if finalization.status != "completed" or finalization.manifest is None:
            errors.append(
                "completed Creative run requires a completed finalization manifest"
            )
            return errors
        report = _validate_success_bundle(
            hub,
            state,
            artifacts,
            concepts,
            dispositions,
            finalization.manifest,
            errors,
        )
        if report is None:
            return errors
        expected_results = list(finalization.manifest.result_artifact_ids)
        if result_ids != expected_results:
            errors.append(
                "completed Creative result artifact IDs do not match the manifest"
            )
        return errors

    if (
        status == "running"
        and state.get("current_stage") == "creative-finalization"
    ):
        if partial_ids:
            errors.append("publishing Creative run must not contain partial reports")
        if result_ids:
            errors.append(
                "publishing Creative run must not expose result artifact IDs"
            )
        errors.extend(finalization.errors)
        if (
            finalization.status != "publishing"
            or finalization.manifest is None
        ):
            errors.append(
                "Creative finalization stage requires a valid frozen manifest"
            )
            return errors
        _validate_success_bundle(
            hub,
            state,
            artifacts,
            concepts,
            dispositions,
            finalization.manifest,
            errors,
        )
        if not finalization.resumable:
            errors.append("Creative publishing manifest is not safely resumable")
        return errors

    if success_ids or partial_ids:
        errors.append("Creative run contains C7 outputs before finalization")
    if result_ids:
        errors.append("Creative run exposes result artifacts before completion")
    if finalization.status != "not_started":
        errors.extend(finalization.errors)
        errors.append("Creative run has a finalization outside the C7 lifecycle")
    return errors


def _artifact_ids_of_types(
    artifacts: Mapping[str, Any],
    artifact_types: frozenset[str],
) -> set[str]:
    return {
        str(artifact_id)
        for artifact_id, record in artifacts.items()
        if isinstance(record, dict)
        and record.get("artifact_type") in artifact_types
    }


def _validate_partial_bundle(
    hub: RunHub,
    state: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    partial_ids: set[str],
    errors: list[str],
) -> None:
    from hacksome.creative.partial_report import (
        PARTIAL_REPORT_JSON_ID,
        PARTIAL_REPORT_JSON_PATH,
        PARTIAL_REPORT_MARKDOWN_ID,
        PARTIAL_REPORT_MARKDOWN_PATH,
    )

    if not partial_ids:
        secondary = state.get("secondary_errors")
        if not isinstance(secondary, list) or not secondary:
            errors.append("failed Creative run has no deterministic partial report")
        return
    expected = {
        PARTIAL_REPORT_MARKDOWN_ID: (
            "creative_partial_report_markdown",
            PARTIAL_REPORT_MARKDOWN_PATH,
        ),
        PARTIAL_REPORT_JSON_ID: (
            "creative_partial_report_json",
            PARTIAL_REPORT_JSON_PATH,
        ),
    }
    if partial_ids != set(expected):
        errors.append(
            "failed Creative run requires exactly one partial Markdown and JSON report"
        )
        return
    for artifact_id, (artifact_type, path) in expected.items():
        record = artifacts.get(artifact_id)
        if (
            not isinstance(record, dict)
            or record.get("artifact_type") != artifact_type
            or record.get("path") != path
        ):
            errors.append(
                f"partial report artifact binding is invalid: {artifact_id}"
            )

    try:
        payload = json.loads(hub.read_artifact(PARTIAL_REPORT_JSON_ID))
    except (OSError, UnicodeError, json.JSONDecodeError, StateError) as exc:
        errors.append(f"invalid Creative partial report JSON: {exc}")
        return
    if not isinstance(payload, dict):
        errors.append("Creative partial report JSON must be an object")
        return
    if (
        payload.get("status") != "failed"
        or payload.get("run_id") != state.get("run_id")
        or payload.get("terminal_error") != state.get("terminal_error")
    ):
        errors.append("Creative partial report is not bound to its failed run")
    if (
        payload.get("final_idea_card_ids") != []
        or payload.get("handoff_refs") != []
        or payload.get("memory_record_ref") is not None
    ):
        errors.append("Creative partial report must not expose final outputs")


def _validate_success_bundle(
    hub: RunHub,
    state: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    concepts: Mapping[str, Mapping[str, Any]],
    dispositions: list[dict[str, Any]],
    manifest: Any,
    errors: list[str],
) -> Mapping[str, Any] | None:
    """Validate every staged C7 byte plus its cross-artifact references."""

    from hacksome.artifacts import ArtifactError, validate_markdown
    from hacksome.creative.artifacts import FINAL_IDEA_CARD_HEADINGS
    from hacksome.creative.memory import (
        MemoryRecord,
        MemoryValidationError,
    )
    from hacksome.creative.report import (
        IDEA_CARD_INDEX_ARTIFACT_ID,
        IDEA_CARD_INDEX_PATH,
        MEMORY_RECORD_ARTIFACT_ID,
        MEMORY_RECORD_PATH,
        REPORT_JSON_ARTIFACT_ID,
        REPORT_JSON_PATH,
        REPORT_MARKDOWN_ARTIFACT_ID,
        REPORT_MARKDOWN_PATH,
    )

    outputs = tuple(manifest.outputs)
    planned_ids = tuple(output.artifact_id for output in outputs)
    if manifest.result_artifact_ids != planned_ids:
        errors.append("C7 manifest must expose every planned output as a result")

    output_by_id = {output.artifact_id: output for output in outputs}
    if len(output_by_id) != len(outputs):
        errors.append("C7 manifest contains duplicate output IDs")
        return None
    if any(output.artifact_type not in _SUCCESS_FINAL_TYPES for output in outputs):
        errors.append("C7 manifest contains a non-canonical output type")

    registered_success = _artifact_ids_of_types(
        artifacts,
        _SUCCESS_FINAL_TYPES,
    )
    if not registered_success.issubset(output_by_id):
        errors.append("registered C7 outputs are absent from the frozen manifest")

    final_ideas = {
        str(artifact_id): record
        for artifact_id, record in artifacts.items()
        if isinstance(record, dict)
        and record.get("artifact_type") == "creative_final_idea"
    }
    expected_card_ids = tuple(
        f"{idea_id}-card" for idea_id in sorted(final_ideas)
    )
    expected_handoff_ids = tuple(
        f"{idea_id}-handoff" for idea_id in sorted(final_ideas)
    )
    expected_order = (
        REPORT_MARKDOWN_ARTIFACT_ID,
        REPORT_JSON_ARTIFACT_ID,
        *expected_card_ids,
        IDEA_CARD_INDEX_ARTIFACT_ID,
        *expected_handoff_ids,
        MEMORY_RECORD_ARTIFACT_ID,
    )
    if planned_ids != expected_order:
        errors.append(
            "C7 manifest output IDs/counts do not match Final Ideas"
        )

    fixed_outputs = {
        REPORT_MARKDOWN_ARTIFACT_ID: (
            "creative_idea_report_markdown",
            REPORT_MARKDOWN_PATH,
        ),
        REPORT_JSON_ARTIFACT_ID: (
            "creative_idea_report_json",
            REPORT_JSON_PATH,
        ),
        IDEA_CARD_INDEX_ARTIFACT_ID: (
            "creative_idea_card_index",
            IDEA_CARD_INDEX_PATH,
        ),
        MEMORY_RECORD_ARTIFACT_ID: (
            "creative_memory_record",
            MEMORY_RECORD_PATH,
        ),
    }
    for artifact_id, (artifact_type, path) in fixed_outputs.items():
        output = output_by_id.get(artifact_id)
        if (
            output is None
            or output.artifact_type != artifact_type
            or output.final_path != path
        ):
            errors.append(f"C7 output binding is invalid: {artifact_id}")
    for idea_id in sorted(final_ideas):
        card_id = f"{idea_id}-card"
        handoff_id = f"{idea_id}-handoff"
        card = output_by_id.get(card_id)
        handoff = output_by_id.get(handoff_id)
        if (
            card is None
            or card.artifact_type != "creative_idea_card"
            or card.final_path
            != f"artifacts/creative/idea-cards/{idea_id}.md"
        ):
            errors.append(f"Final Idea Card binding is invalid: {card_id}")
        if (
            handoff is None
            or handoff.artifact_type != "creative_build_handoff"
            or handoff.final_path
            != f"artifacts/creative/handoffs/{idea_id}.json"
        ):
            errors.append(f"Build handoff binding is invalid: {handoff_id}")

    content_by_id: dict[str, bytes] = {}
    for output in outputs:
        try:
            content_by_id[output.artifact_id] = (
                hub.run_dir / output.staged_path
            ).read_bytes()
        except OSError as exc:
            errors.append(
                f"cannot read staged C7 output {output.artifact_id}: {exc}"
            )
    report_bytes = content_by_id.get(REPORT_JSON_ARTIFACT_ID)
    if report_bytes is None:
        return None
    report = _decode_canonical_json_output(
        report_bytes,
        label="Creative success report JSON",
        errors=errors,
    )
    if report is None:
        return None
    _validate_success_report_payload(
        hub,
        state,
        concepts,
        dispositions,
        report,
        expected_card_ids=expected_card_ids,
        expected_handoff_ids=expected_handoff_ids,
        errors=errors,
    )

    report_markdown = _decode_utf8_output(
        content_by_id.get(REPORT_MARKDOWN_ARTIFACT_ID),
        label="Creative success report Markdown",
        errors=errors,
    )
    if report_markdown is not None and not report_markdown.startswith(
        "# Creative Idea Report\n"
    ):
        errors.append("Creative success report Markdown has an invalid title")

    card_markdown: dict[str, str] = {}
    for card_id in expected_card_ids:
        markdown = _decode_utf8_output(
            content_by_id.get(card_id),
            label=f"Final Idea Card {card_id}",
            errors=errors,
        )
        if markdown is None:
            continue
        card_markdown[card_id] = markdown
        try:
            validate_markdown(
                markdown,
                required_h2=FINAL_IDEA_CARD_HEADINGS,
                label=f"Final Idea Card {card_id}",
            )
        except ArtifactError as exc:
            errors.append(str(exc))

    index_markdown = _decode_utf8_output(
        content_by_id.get(IDEA_CARD_INDEX_ARTIFACT_ID),
        label="Creative Idea Card index",
        errors=errors,
    )
    if index_markdown is not None:
        for card_id in expected_card_ids:
            output = output_by_id.get(card_id)
            if (
                output is not None
                and (
                    index_markdown.count(card_id) != 1
                    or index_markdown.count(output.sha256) != 1
                )
            ):
                errors.append(
                    f"Creative Idea Card index does not bind {card_id}"
                )

    challenge_markdown: str | None = None
    challenge_ref = report.get("challenge_ref")
    if isinstance(challenge_ref, str) and challenge_ref in artifacts:
        try:
            challenge_markdown = hub.read_artifact(challenge_ref)
        except (OSError, UnicodeError, StateError) as exc:
            errors.append(f"invalid report Challenge reference: {exc}")
    else:
        errors.append("Creative success report has an unknown Challenge ref")

    for idea_id in sorted(final_ideas):
        card_id = f"{idea_id}-card"
        handoff_id = f"{idea_id}-handoff"
        handoff_bytes = content_by_id.get(handoff_id)
        if handoff_bytes is None:
            continue
        handoff = _decode_canonical_json_output(
            handoff_bytes,
            label=f"Build handoff {handoff_id}",
            errors=errors,
        )
        if handoff is None:
            continue
        card_output = output_by_id.get(card_id)
        if (
            set(handoff)
            != {
                "source_run_id",
                "idea_card_id",
                "idea_card_sha256",
                "challenge_markdown",
                "initial_idea_card_markdown",
            }
            or handoff.get("source_run_id") != state.get("run_id")
            or handoff.get("idea_card_id") != card_id
            or card_output is None
            or handoff.get("idea_card_sha256") != card_output.sha256
            or handoff.get("initial_idea_card_markdown")
            != card_markdown.get(card_id)
            or handoff.get("challenge_markdown") != challenge_markdown
        ):
            errors.append(f"Build handoff reference closure is invalid: {handoff_id}")

    memory_bytes = content_by_id.get(MEMORY_RECORD_ARTIFACT_ID)
    if memory_bytes is not None:
        memory_payload = _decode_canonical_json_output(
            memory_bytes,
            label="Creative Memory Record",
            errors=errors,
        )
        if memory_payload is not None:
            try:
                memory_record = MemoryRecord.from_mapping(memory_payload)
            except MemoryValidationError as exc:
                errors.append(f"invalid Creative Memory Record: {exc}")
            else:
                report_output = output_by_id.get(
                    REPORT_MARKDOWN_ARTIFACT_ID
                )
                _validate_memory_record_closure(
                    state,
                    artifacts,
                    concepts,
                    dispositions,
                    final_ideas,
                    memory_record,
                    report,
                    report_sha256=(
                        report_output.sha256
                        if report_output is not None
                        else None
                    ),
                    errors=errors,
                )
    return report


def _decode_utf8_output(
    content: bytes | None,
    *,
    label: str,
    errors: list[str],
) -> str | None:
    if content is None:
        errors.append(f"{label} is missing from the frozen C7 plan")
        return None
    try:
        return content.decode("utf-8")
    except UnicodeError as exc:
        errors.append(f"{label} is not UTF-8: {exc}")
        return None


def _decode_canonical_json_output(
    content: bytes,
    *,
    label: str,
    errors: list[str],
) -> dict[str, Any] | None:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"{label} is not valid JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} must be a JSON object")
        return None
    if content != canonical_json_bytes(value) + b"\n":
        errors.append(f"{label} bytes are not canonical")
    return value


def _validate_success_report_payload(
    hub: RunHub,
    state: Mapping[str, Any],
    concepts: Mapping[str, Mapping[str, Any]],
    dispositions: list[dict[str, Any]],
    report: Mapping[str, Any],
    *,
    expected_card_ids: tuple[str, ...],
    expected_handoff_ids: tuple[str, ...],
    errors: list[str],
) -> None:
    expected_keys = {
        "schema_version",
        "route",
        "run_id",
        "status",
        "challenge_ref",
        "creative_brief_ref",
        "idea_memory",
        "counts",
        "territory_ids",
        "concepts",
        "review_rounds",
        "zero_reason_code",
        "empty_batch_skip_reason",
        "final_idea_card_ids",
        "handoff_refs",
        "memory_record_ref",
        "report_policy_version",
    }
    if set(report) != expected_keys:
        errors.append("Creative success report JSON has invalid top-level fields")
    route = state.get("route")
    report_route = report.get("route")
    if (
        report.get("schema_version") != 1
        or report.get("status") != "completed"
        or report.get("run_id") != state.get("run_id")
        or not isinstance(route, dict)
        or report_route
        != {
            "id": "creative",
            "contract_version": route.get("contract_version"),
        }
        or report.get("report_policy_version")
        != route.get("report_policy_version")
    ):
        errors.append("Creative success report identity/policy binding is invalid")
    if report.get("final_idea_card_ids") != list(expected_card_ids):
        errors.append("Creative success report Idea Card refs are not exact")
    if report.get("handoff_refs") != list(expected_handoff_ids):
        errors.append("Creative success report handoff refs are not exact")
    if report.get("memory_record_ref") != "creative-memory-record":
        errors.append("Creative success report has an invalid Memory Record ref")

    zero_reason = report.get("zero_reason_code")
    if expected_card_ids:
        if zero_reason is not None:
            errors.append("non-zero Creative report must not have zero_reason_code")
    elif zero_reason not in _ZERO_REASON_CODES:
        errors.append("zero-Idea Creative report requires a valid zero_reason_code")
    persisted_reason = state.get("zero_reason_code")
    if persisted_reason is not None and persisted_reason != zero_reason:
        errors.append("Creative report zero_reason_code is stale")

    counts = report.get("counts")
    concept_id_to_refs: dict[str, list[str]] = {}
    for artifact_id, record in concepts.items():
        concept_id = _metadata_value(record, "concept_id")
        if isinstance(concept_id, str):
            concept_id_to_refs.setdefault(concept_id, []).append(artifact_id)
    if (
        not isinstance(counts, dict)
        or counts.get("concepts") != len(concept_id_to_refs)
        or counts.get("concept_revisions") != len(concepts)
        or counts.get("final_ideas") != len(expected_card_ids)
    ):
        errors.append("Creative success report counts do not match persisted artifacts")

    terminal_by_ref = {
        concept_ref: [
            row
            for row in dispositions
            if row.get("concept_revision_ref") == concept_ref
            and row.get("terminal") is True
        ]
        for concept_ref in concepts
    }
    for concept_ref, rows in terminal_by_ref.items():
        if len(rows) != 1:
            errors.append(
                f"completed Concept {concept_ref} requires exactly one "
                "terminal disposition"
            )

    report_concepts = report.get("concepts")
    if not isinstance(report_concepts, list):
        errors.append("Creative success report concepts must be an array")
        return
    reported_by_id: dict[str, Mapping[str, Any]] = {}
    for row in report_concepts:
        if not isinstance(row, dict):
            errors.append("Creative success report has an invalid Concept row")
            continue
        concept_id = row.get("concept_id")
        if not isinstance(concept_id, str) or concept_id in reported_by_id:
            errors.append("Creative success report has duplicate/invalid Concept IDs")
            continue
        reported_by_id[concept_id] = row
    if set(reported_by_id) != set(concept_id_to_refs):
        errors.append("Creative success report does not cover every Concept")
        return
    for concept_id, revision_refs in concept_id_to_refs.items():
        row = reported_by_id[concept_id]
        expected_revisions = sorted(revision_refs)
        if row.get("revision_refs") != expected_revisions:
            errors.append(
                f"Creative success report revision closure is invalid: {concept_id}"
            )
        reported_dispositions = row.get("dispositions")
        if not isinstance(reported_dispositions, list):
            errors.append(
                f"Creative success report dispositions are invalid: {concept_id}"
            )
            continue
        reported_refs = [
            item.get("disposition_ref")
            for item in reported_dispositions
            if isinstance(item, dict)
        ]
        expected_refs = sorted(
            str(item.get("disposition_id"))
            for item in dispositions
            if item.get("concept_revision_ref") in revision_refs
        )
        if (
            len(reported_refs) != len(reported_dispositions)
            or sorted(str(item) for item in reported_refs) != expected_refs
        ):
            errors.append(
                f"Creative success report disposition closure is invalid: {concept_id}"
            )
        latest_ref = expected_revisions[-1]
        terminal = terminal_by_ref.get(latest_ref, [])
        if len(terminal) == 1:
            expected_outcome = terminal[0].get("outcome")
            if expected_outcome == "eliminated":
                expected_outcome = "c4_eliminated"
            if row.get("terminal_outcome") != expected_outcome:
                errors.append(
                    f"Creative success report terminal outcome is stale: {concept_id}"
                )

    batch_ref = _first_artifact_of_type(
        state.get("artifacts", {})
        if isinstance(state.get("artifacts"), dict)
        else {},
        "creative_human_review_batch",
    )
    batch_reason: str | None = None
    if batch_ref is not None:
        try:
            batch_payload = json.loads(hub.read_artifact(batch_ref))
        except (OSError, UnicodeError, json.JSONDecodeError, StateError):
            batch_payload = None
        if isinstance(batch_payload, dict):
            candidate_reason = batch_payload.get("skip_reason")
            if isinstance(candidate_reason, str):
                batch_reason = candidate_reason
    if report.get("empty_batch_skip_reason") != batch_reason:
        errors.append("Creative success report empty-batch reason is stale")
    if zero_reason in {
        "no_concepts_generated",
        "all_candidates_failed_hook",
        "all_candidates_failed_concept_screen",
        "shortlist_empty",
    } and batch_reason != zero_reason:
        errors.append("zero-Idea report does not match its empty review batch")
    if zero_reason == "all_human_rejected" and batch_reason is not None:
        errors.append("all_human_rejected cannot use an empty review batch")


def _validate_memory_record_closure(
    state: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    concepts: Mapping[str, Mapping[str, Any]],
    dispositions: list[dict[str, Any]],
    final_ideas: Mapping[str, Mapping[str, Any]],
    memory_record: Any,
    report: Mapping[str, Any],
    *,
    report_sha256: str | None,
    errors: list[str],
) -> None:
    if (
        memory_record.source_run_id != state.get("run_id")
        or memory_record.source_report_artifact_id
        != "creative-idea-report"
        or memory_record.source_report_sha256 != report_sha256
        or memory_record.zero_reason_code != report.get("zero_reason_code")
    ):
        errors.append("Creative Memory Record report/run binding is invalid")

    terminal_by_ref = {
        concept_ref: [
            row
            for row in dispositions
            if row.get("concept_revision_ref") == concept_ref
            and row.get("terminal") is True
        ]
        for concept_ref in concepts
    }
    promoted_sources = {
        concept_ref
        for concept_ref, rows in terminal_by_ref.items()
        if len(rows) == 1
        and rows[0].get("outcome") == "promoted_to_final"
        and rows[0].get("target_ref") in final_ideas
    }
    expected_sources = (set(concepts) - promoted_sources) | set(final_ideas)
    actual_sources = {
        entry.source_candidate_ref for entry in memory_record.entries
    }
    if actual_sources != expected_sources:
        errors.append("Creative Memory Record source count/closure is invalid")
    final_entries = {
        entry.source_candidate_ref
        for entry in memory_record.entries
        if entry.source_kind == "final_idea"
    }
    if final_entries != set(final_ideas):
        errors.append("Creative Memory Record Final Idea closure is invalid")
    for entry in memory_record.entries:
        record = artifacts.get(entry.source_candidate_ref)
        expected_type = (
            "creative_final_idea"
            if entry.source_kind == "final_idea"
            else "creative_concept"
        )
        if (
            not isinstance(record, dict)
            or record.get("artifact_type") != expected_type
            or record.get("sha256") != entry.source_candidate_sha256
        ):
            errors.append(
                "Creative Memory Record has a stale source: "
                f"{entry.source_candidate_ref}"
            )
