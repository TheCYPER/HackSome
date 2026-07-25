"""Production adapter between a persisted Creative run and the review server.

The HTTP server intentionally knows nothing about ``RunHub`` or JSONL.  This
module reconstructs the immutable C6 review binding from the run directory,
revalidates it before every read or mutation, and exposes only JSON-safe domain
projections to the transport layer.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
from typing import Any, Mapping

from hacksome.artifacts import (
    ArtifactError,
    section_body,
    title_of,
    validate_markdown,
)
from hacksome.creative.artifacts import (
    CONCEPT_HEADINGS,
    EVIDENCE_REVISION_HEADINGS,
    LEGACY_CONCEPT_HEADINGS,
    MEMORY_REMIX_HEADINGS,
    NOVELTY_SCAN_HEADINGS,
)
from hacksome.creative.memory import MemoryCapsuleRef, MemoryValidationError
from hacksome.creative.review import (
    FeedbackFragment,
    ReviewBatch,
    ReviewError,
    ReviewRound,
    ReviewSnapshot,
    ReviewStaleError,
    ReviewStore,
    ReviewValidationError,
)
from hacksome.creative.review_server import ReviewRole
from hacksome.hub import RunHub
from hacksome.routes import validate_run
from hacksome.state import StateError, normalize_json


_REVIEWER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class RunReviewBackend:
    """ReviewBackend implementation backed by one review-ready Creative run."""

    def __init__(self, run_dir: str | Path) -> None:
        try:
            self.hub = RunHub(run_dir)
            self.hub.reconcile_pending()
            state = self.hub.load_state()
            route = state.get("route")
            contract_version = (
                route.get("contract_version")
                if isinstance(route, dict)
                else None
            )
            if contract_version == "1":
                self.schema_version = 1
            elif contract_version == "2":
                self.schema_version = 2
            else:
                raise ReviewValidationError(
                    "unsupported Creative contract for human review"
                )
            batch_artifact_id, batch, review_round, _wait = self._load_binding(state)
            self.batch_artifact_id = batch_artifact_id
            self.batch = batch
            self.round = review_round
            self.store = ReviewStore(self.hub, review_round)
            self.store.initialize()
            self._verify_runtime_state()
        except ReviewError:
            raise
        except (ArtifactError, MemoryValidationError, OSError, StateError) as exc:
            raise ReviewValidationError(
                "the run is not a valid Creative human-review round"
            ) from exc

    def has_submitted(self, reviewer_id: str) -> bool:
        """Return whether the exact reviewer owns a latest receipt."""

        normalized_id = _reviewer_id(reviewer_id)
        _state, snapshot = self._verify_runtime_state()
        return any(
            review.reviewer_id == normalized_id for review in snapshot.latest_reviews
        )

    def snapshot(
        self,
        *,
        role: ReviewRole,
        reviewer_id: str | None,
        include_team_wall: bool,
    ) -> Mapping[str, Any]:
        """Return a trusted superset for the server's final role allowlist."""

        if role not in {"reviewer", "curator"}:
            raise ReviewValidationError("unsupported review role")
        if not isinstance(include_team_wall, bool):
            raise ReviewValidationError("include_team_wall must be a boolean")
        normalized_reviewer_id = (
            _reviewer_id(reviewer_id) if reviewer_id is not None else None
        )
        if role == "reviewer" and normalized_reviewer_id is None:
            raise ReviewValidationError(
                "reviewer snapshot requires an authenticated reviewer session"
            )

        state, domain = self._verify_runtime_state()
        concepts = [
            self._concept_projection(state, binding.concept_ref)
            for binding in self.round.concepts
        ]
        latest_by_reviewer = {
            review.reviewer_id: review for review in domain.latest_reviews
        }
        own_latest = (
            latest_by_reviewer.get(normalized_reviewer_id)
            if normalized_reviewer_id is not None
            else None
        )
        wall_allowed = role == "curator" or (
            include_team_wall and own_latest is not None
        )
        round_projection = domain.round.to_dict()
        round_projection.update(
            {
                "id": domain.round.round_id,
                "sha256": domain.round.round_sha256,
            }
        )
        coverage_summary = {
            "concept_count": len(domain.coverage),
            "shortlist_count": len(domain.coverage),
            "covered_concept_count": sum(item.covered for item in domain.coverage),
            "reviewer_count": len(domain.latest_reviews),
        }
        value: dict[str, Any] = {
            "schema_version": self.schema_version,
            "run_id": self.hub.run_id,
            "status": domain.round.status,
            "empty": False,
            "round": round_projection,
            "concepts": concepts,
            "pairs": [pair.to_dict() for pair in domain.round.pairs],
            "coverage_summary": coverage_summary,
            "viewer": {
                "latest_review_id": (
                    own_latest.review_id if own_latest is not None else None
                )
            },
            "next_command": (
                self._next_command()
                if role == "curator" and domain.round.status == "closed"
                else None
            ),
        }
        if wall_allowed:
            value["team_wall"] = [review.to_dict() for review in domain.latest_reviews]
        if role == "curator":
            value["curation"] = self._curation_projection(
                state,
                domain,
                concepts=concepts,
            )
        return _json_object(value, label="review backend snapshot")

    def submit_review(
        self,
        payload: Mapping[str, Any],
        *,
        expected_reviewer_id: str,
    ) -> Mapping[str, Any]:
        """Validate, append, and return one JSON-safe immutable receipt."""

        normalized_reviewer_id = _reviewer_id(expected_reviewer_id)
        self._verify_runtime_state()
        review = self.store.submit_review(
            payload,
            expected_reviewer_id=normalized_reviewer_id,
        )
        self._verify_runtime_state()
        return _json_object(
            {
                **review.to_dict(),
                "status": "saved",
                "next_command": None,
            },
            label="review submit result",
        )

    def submit_resolution(
        self,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Validate and atomically close the round through ReviewStore."""

        self._verify_runtime_state()
        resolution = self.store.submit_resolution(payload)
        _state, snapshot = self._verify_runtime_state()
        if (
            snapshot.round.status != "closed"
            or snapshot.resolution is None
            or snapshot.resolution.resolution_id != resolution.resolution_id
            or snapshot.resolution.resolution_sha256 != resolution.resolution_sha256
        ):
            raise ReviewStaleError(
                "persisted resolution does not close the bound review round"
            )
        return _json_object(
            {
                **resolution.to_dict(),
                "status": "closed",
                "next_command": self._next_command(),
            },
            label="resolution submit result",
        )

    def _verify_runtime_state(
        self,
    ) -> tuple[dict[str, Any], ReviewSnapshot]:
        """Re-bind immutable artifacts and mutable wait/ledger state."""

        state = self.hub.load_state()
        artifact_id, batch, review_round, wait = self._load_binding(state)
        if (
            artifact_id != self.batch_artifact_id
            or batch != self.batch
            or review_round != self.round
        ):
            raise ReviewStaleError("the persisted review binding has changed")

        errors = validate_run(self.hub.run_dir)
        if errors:
            raise ReviewValidationError(
                "the Creative run failed offline validation; run "
                "`hacksome validate` for details"
            )

        snapshot = self.store.snapshot()
        wait_status = wait.get("status")
        if wait_status != snapshot.round.status:
            raise ReviewStaleError("wait status does not match the human-review ledger")
        if snapshot.round.status == "open":
            if snapshot.resolution is not None:
                raise ReviewStaleError("open review wait unexpectedly has a resolution")
            for key in (
                "resolution_id",
                "resolution_sha256",
                "latest_receipt_set_sha256",
            ):
                if wait.get(key) is not None:
                    raise ReviewStaleError(
                        f"open review wait unexpectedly contains {key}"
                    )
        else:
            resolution = snapshot.resolution
            if resolution is None:
                raise ReviewStaleError("closed review wait has no immutable resolution")
            expected = {
                "resolution_id": resolution.resolution_id,
                "resolution_sha256": resolution.resolution_sha256,
                "latest_receipt_set_sha256": (resolution.latest_receipt_set_sha256),
                "approved_feedback_set_sha256": (
                    resolution.approved_feedback_set_sha256
                ),
            }
            for key, expected_value in expected.items():
                if wait.get(key) != expected_value:
                    raise ReviewStaleError(f"closed review wait has a stale {key}")
        return state, snapshot

    def _load_binding(
        self,
        state: Mapping[str, Any],
    ) -> tuple[str, ReviewBatch, ReviewRound, dict[str, Any]]:
        route = state.get("route")
        if not isinstance(route, dict) or route.get("id") != "creative":
            raise ReviewValidationError("human review backend requires a Creative run")
        if (
            state.get("status") != "waiting"
            or state.get("current_stage") != "creative-human-review"
        ):
            raise ReviewValidationError("Creative run is not at the human-review wait")
        pending = state.get("pending_records")
        if not isinstance(pending, list) or pending:
            raise ReviewValidationError("Creative run has unreconciled outbox records")
        raw_wait = state.get("wait")
        if not isinstance(raw_wait, dict):
            raise ReviewValidationError("Creative human-review wait is missing")
        wait = _json_object(raw_wait, label="Creative review wait")
        if wait.get("kind") != "creative_human_review" or wait.get("status") not in {
            "open",
            "closed",
        }:
            raise ReviewValidationError(
                "Creative human-review wait has an invalid kind or status"
            )

        artifact_id = wait.get("round_artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ReviewValidationError("Creative review wait has no batch artifact")
        record = _artifact_record(
            state,
            artifact_id,
            expected_type="creative_human_review_batch",
        )
        try:
            raw_batch = json.loads(self.hub.read_artifact(artifact_id))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ReviewValidationError("HumanReviewBatch is not valid JSON") from exc
        if not isinstance(raw_batch, dict):
            raise ReviewValidationError("HumanReviewBatch must be a JSON object")
        batch = ReviewBatch.from_dict(raw_batch)
        if batch.status != "ready":
            raise ReviewValidationError(
                "an empty HumanReviewBatch cannot open a review server"
            )
        if batch.batch_id != artifact_id or batch.run_id != state.get("run_id"):
            raise ReviewStaleError("HumanReviewBatch identity does not match its run")
        review_round = ReviewRound.open(batch)
        expected_wait_values = {
            "round_id": review_round.round_id,
            "round_sha256": review_round.round_sha256,
            "batch_sha256": batch.batch_sha256,
            "batch_artifact_sha256": record.get("sha256"),
        }
        for key, expected in expected_wait_values.items():
            if wait.get(key) != expected:
                raise ReviewStaleError(f"Creative review wait has a stale {key}")
        return artifact_id, batch, review_round, wait

    def _concept_projection(
        self,
        state: Mapping[str, Any],
        concept_ref: str,
    ) -> dict[str, Any]:
        binding = self.round.bindings.get(concept_ref)
        if binding is None:
            raise ReviewStaleError(f"unknown bound Concept revision: {concept_ref}")
        record = _artifact_record(
            state,
            concept_ref,
            expected_type="creative_concept",
        )
        if record.get("sha256") != binding.concept_sha256:
            raise ReviewStaleError(f"Concept hash changed for {concept_ref}")
        markdown = self.hub.read_artifact(concept_ref)
        route = state.get("route")
        contract_version = (
            route.get("contract_version") if isinstance(route, dict) else None
        )
        concept_headings = (
            LEGACY_CONCEPT_HEADINGS
            if contract_version == "1"
            else CONCEPT_HEADINGS
        )
        validate_markdown(
            markdown,
            required_h2=concept_headings + EVIDENCE_REVISION_HEADINGS,
            label=f"review Concept {concept_ref}",
        )
        metadata = _metadata(record, concept_ref)
        primary_territory_ref = _non_empty_string(
            metadata.get("primary_territory_ref"),
            f"{concept_ref} primary_territory_ref",
        )
        novelty = self._novelty_projection(state, metadata, concept_ref)
        return {
            "id": concept_ref,
            "ref": concept_ref,
            "concept_ref": concept_ref,
            "sha256": binding.concept_sha256,
            "concept_sha256": binding.concept_sha256,
            "title": title_of(markdown),
            "hook": section_body(markdown, "One-sentence Hook"),
            "one_sentence_hook": section_body(markdown, "One-sentence Hook"),
            "first_impression": section_body(markdown, "First Impression"),
            "first_thirty_seconds": section_body(markdown, "First Impression"),
            "audience_action": section_body(markdown, "Audience Action"),
            "reveal": section_body(markdown, "Setup, Reveal and Aftertaste"),
            "setup_reveal_aftertaste": section_body(
                markdown, "Setup, Reveal and Aftertaste"
            ),
            "core_mechanism": section_body(
                markdown, "Real Input, Transformation and Output"
            ),
            "software_core_and_runtime": (
                section_body(markdown, "Software Core and Runtime")
                if contract_version != "1"
                else section_body(
                    markdown,
                    "Real Input, Transformation and Output",
                )
            ),
            "share_trigger_and_artifact": (
                section_body(markdown, "Share Trigger and Artifact")
                if contract_version != "1"
                else ""
            ),
            "minimum_hackathon_demo": section_body(markdown, "Minimum Hackathon Demo"),
            "novelty": novelty,
            "novelty_and_references": novelty,
            "risks": section_body(markdown, "Assumptions, Confusion and Risks"),
            "assumptions_confusion_and_risks": section_body(
                markdown, "Assumptions, Confusion and Risks"
            ),
            "primary_territory_ref": primary_territory_ref,
        }

    def _novelty_projection(
        self,
        state: Mapping[str, Any],
        metadata: Mapping[str, Any],
        concept_ref: str,
    ) -> str:
        novelty_ref = _non_empty_string(
            metadata.get("novelty_scan_ref"),
            f"{concept_ref} novelty_scan_ref",
        )
        _artifact_record(
            state,
            novelty_ref,
            expected_type="creative_novelty_scan",
        )
        markdown = self.hub.read_artifact(novelty_ref)
        validate_markdown(
            markdown,
            required_h2=NOVELTY_SCAN_HEADINGS,
            label=f"Novelty Scan {novelty_ref}",
        )
        return "\n\n".join(
            (
                "Direct and near collisions:\n"
                + section_body(markdown, "Direct and Near Collisions"),
                "Distinctive combination:\n"
                + section_body(markdown, "Distinctive Combination"),
                "Counterevidence and uncertainty:\n"
                + section_body(markdown, "Counterevidence and Uncertainty"),
            )
        )

    def _curation_projection(
        self,
        state: Mapping[str, Any],
        snapshot: ReviewSnapshot,
        *,
        concepts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        fragments = self.store.feedback_fragments()
        confirmed = self.store.snapshot()
        if (
            confirmed.latest_receipt_set_sha256 != snapshot.latest_receipt_set_sha256
            or confirmed.round.status != snapshot.round.status
            or (
                confirmed.resolution.resolution_sha256
                if confirmed.resolution is not None
                else None
            )
            != (
                snapshot.resolution.resolution_sha256
                if snapshot.resolution is not None
                else None
            )
        ):
            raise ReviewStaleError(
                "review receipts changed while building the curator snapshot"
            )
        coverage = [
            {
                **item.to_dict(),
                "review_count": len(item.reviewer_ids),
            }
            for item in snapshot.coverage
        ]
        return {
            "coverage": coverage,
            "receipts": [review.to_dict() for review in snapshot.latest_reviews],
            "feedback_fragments": [
                self._feedback_fragment_projection(fragment) for fragment in fragments
            ],
            "memory_provenance": self._memory_provenance(
                state,
                concepts=concepts,
            ),
            "feasibility_evidence": self._feasibility_evidence(
                state,
                concepts=concepts,
            ),
            "uncovered_concept_refs": [
                item.concept_ref for item in snapshot.coverage if not item.covered
            ],
            "latest_receipt_set_sha256": (snapshot.latest_receipt_set_sha256),
            "resolution": (
                snapshot.resolution.to_dict()
                if snapshot.resolution is not None
                else None
            ),
            "resolution_controls": {
                "can_close": snapshot.round.status == "open",
                "requires_exactly_one_action_per_concept": True,
                "shortlist_refs": [concept["concept_ref"] for concept in concepts],
            },
        }

    def _feasibility_evidence(
        self,
        state: Mapping[str, Any],
        *,
        concepts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Project verified C4F evidence only to the curator workbench.

        Contract-v1 waiting runs do not have C4F artifacts. They intentionally
        produce an empty list while remaining reviewable.
        """

        rows: list[dict[str, Any]] = []
        for concept in concepts:
            concept_ref = str(concept["concept_ref"])
            concept_record = _artifact_record(
                state,
                concept_ref,
                expected_type="creative_concept",
            )
            metadata = _metadata(concept_record, concept_ref)
            review_ref = metadata.get("software_demo_review_ref")
            if review_ref is None:
                continue
            if not isinstance(review_ref, str) or not review_ref:
                raise ReviewValidationError(
                    f"{concept_ref} software_demo_review_ref must be a string"
                )
            _artifact_record(
                state,
                review_ref,
                expected_type="creative_software_demo_review",
            )
            try:
                raw = json.loads(self.hub.read_artifact(review_ref))
            except (json.JSONDecodeError, UnicodeError) as exc:
                raise ReviewValidationError(
                    f"Software Demo Review {review_ref} is not valid JSON"
                ) from exc
            payload = _json_object(
                raw,
                label=f"Software Demo Review {review_ref}",
            )
            dimensions = payload.get("dimensions")
            if not isinstance(dimensions, list):
                raise ReviewValidationError(
                    f"Software Demo Review {review_ref} dimensions must be an array"
                )
            projected_dimensions: list[dict[str, Any]] = []
            for index, dimension in enumerate(dimensions):
                item = _json_object(
                    dimension,
                    label=(
                        f"Software Demo Review {review_ref} "
                        f"dimension {index + 1}"
                    ),
                )
                reason_code = item.get("reason_code")
                if reason_code is not None and not isinstance(reason_code, str):
                    raise ReviewValidationError(
                        f"{review_ref} reason_code must be a string or null"
                    )
                projected_dimensions.append(
                    {
                        "dimension": _non_empty_string(
                            item.get("dimension"),
                            f"{review_ref} dimension",
                        ),
                        "verdict": _non_empty_string(
                            item.get("verdict"),
                            f"{review_ref} verdict",
                        ),
                        "reason_code": reason_code,
                        "evidence": _non_empty_string(
                            item.get("evidence"),
                            f"{review_ref} evidence",
                        ),
                    }
                )
            rows.append(
                {
                    "concept_ref": concept_ref,
                    "review_ref": review_ref,
                    "overall_decision": _non_empty_string(
                        payload.get("overall_decision"),
                        f"{review_ref} overall_decision",
                    ),
                    "dimensions": projected_dimensions,
                    "markdown": _non_empty_string(
                        payload.get("markdown"),
                        f"{review_ref} markdown",
                    ),
                }
            )
        return rows

    def _feedback_fragment_projection(
        self,
        fragment: FeedbackFragment,
    ) -> dict[str, Any]:
        payload = dict(fragment.payload)
        if fragment.kind == "concept":
            text = " · ".join(
                value
                for value in (
                    _optional_text(payload.get("one_sentence_retell")),
                    (
                        "share="
                        + _optional_text(payload.get("share_impulse"))
                        if _optional_text(payload.get("share_impulse"))
                        else ""
                    ),
                    _optional_text(payload.get("share_target")),
                    (
                        "demo="
                        + _optional_text(payload.get("demo_confidence"))
                        if _optional_text(payload.get("demo_confidence"))
                        else ""
                    ),
                    _optional_text(payload.get("comment")),
                )
                if value
            )
        elif fragment.kind == "pair":
            text = _optional_text(payload.get("reason"))
        else:
            text = _optional_text(payload.get("overall_comment"))
        return {
            **fragment.to_dict(),
            "concept_refs": list(fragment.related_concept_refs),
            "text": text or "(empty feedback fragment)",
            "has_guidance": fragment.has_guidance,
        }

    def _memory_provenance(
        self,
        state: Mapping[str, Any],
        *,
        concepts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        packet = self._memory_cue_index(state)
        rows: list[dict[str, Any]] = []
        for concept in concepts:
            concept_ref = str(concept["concept_ref"])
            record = _artifact_record(
                state,
                concept_ref,
                expected_type="creative_concept",
            )
            metadata = _metadata(record, concept_ref)
            raw_cue_ids = [
                *_string_sequence(
                    metadata.get("memory_cue_refs", []),
                    f"{concept_ref} memory_cue_refs",
                ),
                *_string_sequence(
                    metadata.get("relevant_memory_cue_ids", []),
                    f"{concept_ref} relevant_memory_cue_ids",
                ),
            ]
            cue_ids = tuple(dict.fromkeys(raw_cue_ids))
            raw_explicit_refs = metadata.get("memory_source_refs", [])
            if not isinstance(raw_explicit_refs, list):
                raise ReviewValidationError(
                    f"{concept_ref} memory_source_refs must be an array"
                )
            explicit_refs = tuple(
                MemoryCapsuleRef.from_mapping(value) for value in raw_explicit_refs
            )
            if not cue_ids:
                if explicit_refs:
                    raise ReviewStaleError(
                        f"{concept_ref} has memory sources without cue provenance"
                    )
                continue
            if not packet:
                raise ReviewStaleError(
                    f"{concept_ref} has memory cues but no inspiration packet"
                )

            source_markdown = self._memory_source_markdown(
                state,
                concept_ref,
            )
            evidence_changes = section_body(
                self.hub.read_artifact(concept_ref),
                "Evidence-informed Changes",
            )
            deliberately_not_adopted = section_body(
                self.hub.read_artifact(concept_ref),
                "Evidence Deliberately Not Adopted",
            )
            remix_transformation = _optional_section(
                source_markdown,
                "What Was Transformed",
            )
            remix_copy_note = _optional_section(
                source_markdown,
                "Why This Is Not A Copy",
            )
            supported_refs: set[tuple[str, ...]] = set()
            for cue_id in cue_ids:
                cue = packet.get(cue_id)
                if cue is None:
                    raise ReviewStaleError(
                        f"{concept_ref} references an unknown memory cue"
                    )
                for memory_ref in cue["source_memory_refs"]:
                    supported_refs.add(memory_ref.stable_key)
                    rows.append(
                        {
                            "concept_ref": concept_ref,
                            "origin": metadata.get("origin"),
                            "cue_id": cue_id,
                            "cue_role": cue["role"],
                            "transferable_pattern": cue["transferable_pattern"],
                            "elements_that_must_not_be_copied": cue[
                                "elements_that_must_not_be_copied"
                            ],
                            "source_run_id": memory_ref.source_run_id,
                            "source_ref": memory_ref.source_artifact_id,
                            "source_sha256": (memory_ref.source_artifact_sha256),
                            "source_memory_record_ref": (
                                memory_ref.source_memory_record_artifact_id
                            ),
                            "source_memory_record_sha256": (
                                memory_ref.source_memory_record_sha256
                            ),
                            "capsule_sha256": memory_ref.capsule_sha256,
                            "transformation": (
                                remix_transformation or evidence_changes
                            ),
                            "copy_risk": (remix_copy_note or deliberately_not_adopted),
                        }
                    )
            if any(
                reference.stable_key not in supported_refs
                for reference in explicit_refs
            ):
                raise ReviewStaleError(
                    f"{concept_ref} memory sources are not supported by its cues"
                )
        return sorted(
            rows,
            key=lambda row: (
                str(row["concept_ref"]),
                str(row["cue_id"]),
                str(row["source_run_id"]),
                str(row["source_ref"]),
            ),
        )

    def _memory_cue_index(
        self,
        state: Mapping[str, Any],
    ) -> dict[str, dict[str, Any]]:
        artifacts = _artifacts(state)
        packet_ids = sorted(
            str(artifact_id)
            for artifact_id, record in artifacts.items()
            if isinstance(record, dict)
            and record.get("artifact_type") == "creative_memory_inspiration_packet"
        )
        if not packet_ids:
            return {}
        if len(packet_ids) != 1:
            raise ReviewValidationError(
                "Creative run has multiple Memory Inspiration Packets"
            )
        packet_id = packet_ids[0]
        try:
            raw = json.loads(self.hub.read_artifact(packet_id))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ReviewValidationError(
                "Memory Inspiration Packet is not valid JSON"
            ) from exc
        value = _json_object(raw, label="Memory Inspiration Packet")
        raw_cues = value.get("cues")
        if not isinstance(raw_cues, list):
            raise ReviewValidationError(
                "Memory Inspiration Packet cues must be an array"
            )
        cues: dict[str, dict[str, Any]] = {}
        for raw_cue in raw_cues:
            cue = _json_object(raw_cue, label="memory cue")
            cue_id = _non_empty_string(cue.get("cue_id"), "memory cue_id")
            if cue_id in cues:
                raise ReviewValidationError(
                    "Memory Inspiration Packet has duplicate cue IDs"
                )
            role = cue.get("role")
            if role not in {"inspire", "avoid"}:
                raise ReviewValidationError("memory cue has an invalid role")
            raw_refs = cue.get("source_memory_refs")
            if not isinstance(raw_refs, list) or not raw_refs:
                raise ReviewValidationError("memory cue requires source_memory_refs")
            cues[cue_id] = {
                "role": role,
                "transferable_pattern": _non_empty_string(
                    cue.get("transferable_pattern"),
                    "memory cue transferable_pattern",
                ),
                "elements_that_must_not_be_copied": list(
                    _string_sequence(
                        cue.get("elements_that_must_not_be_copied"),
                        "memory cue elements_that_must_not_be_copied",
                    )
                ),
                "source_memory_refs": tuple(
                    MemoryCapsuleRef.from_mapping(reference) for reference in raw_refs
                ),
            }
        return cues

    def _memory_source_markdown(
        self,
        state: Mapping[str, Any],
        concept_ref: str,
    ) -> str:
        route = state.get("route")
        contract_version = (
            route.get("contract_version") if isinstance(route, dict) else None
        )
        concept_headings = (
            LEGACY_CONCEPT_HEADINGS
            if contract_version == "1"
            else CONCEPT_HEADINGS
        )
        visited: set[str] = set()
        current = concept_ref
        while current not in visited:
            visited.add(current)
            record = _artifact_record(
                state,
                current,
                expected_type="creative_concept",
            )
            markdown = self.hub.read_artifact(current)
            try:
                validate_markdown(
                    markdown,
                    required_h2=concept_headings + MEMORY_REMIX_HEADINGS,
                    label=f"Memory challenger {current}",
                )
            except ArtifactError:
                pass
            else:
                return markdown
            predecessor = _metadata(record, current).get("supersedes_ref")
            if not isinstance(predecessor, str) or not predecessor:
                break
            current = predecessor
        return self.hub.read_artifact(concept_ref)

    def _next_command(self) -> str:
        return shlex.join(("hacksome", "resume", str(self.hub.run_dir)))


def _artifacts(state: Mapping[str, Any]) -> Mapping[str, Any]:
    artifacts = state.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ReviewValidationError("Creative run artifacts must be an object")
    return artifacts


def _artifact_record(
    state: Mapping[str, Any],
    artifact_id: str,
    *,
    expected_type: str,
) -> dict[str, Any]:
    record = _artifacts(state).get(artifact_id)
    if not isinstance(record, dict):
        raise ReviewStaleError(f"unknown artifact: {artifact_id}")
    if (
        record.get("artifact_id") != artifact_id
        or record.get("artifact_type") != expected_type
    ):
        raise ReviewStaleError(f"artifact {artifact_id} is not a {expected_type}")
    digest = record.get("sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ReviewValidationError(
            f"artifact {artifact_id} has an invalid content hash"
        )
    return record


def _metadata(
    record: Mapping[str, Any],
    artifact_id: str,
) -> dict[str, Any]:
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        raise ReviewValidationError(f"artifact {artifact_id} has no metadata object")
    return metadata


def _reviewer_id(value: Any) -> str:
    if not isinstance(value, str) or _REVIEWER_ID.fullmatch(value) is None:
        raise ReviewValidationError("invalid reviewer_id")
    return value


def _non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewValidationError(f"{label} must be a non-empty string")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ReviewValidationError(f"{label} contains invalid Unicode") from exc
    return value


def _string_sequence(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ReviewValidationError(f"{label} must be an array of non-empty strings")
    if len(value) != len(set(value)):
        raise ReviewValidationError(f"{label} must not contain duplicates")
    return tuple(value)


def _optional_section(markdown: str, heading: str) -> str:
    try:
        return section_body(markdown, heading)
    except ArtifactError:
        return ""


def _optional_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _json_object(value: Any, *, label: str) -> dict[str, Any]:
    try:
        normalized = normalize_json(value, label=label)
    except StateError as exc:
        raise ReviewValidationError(f"{label} is not strict JSON") from exc
    if not isinstance(normalized, dict):
        raise ReviewValidationError(f"{label} must be an object")
    return normalized


__all__ = ["RunReviewBackend"]
