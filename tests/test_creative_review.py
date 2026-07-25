from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

from hacksome.config import CodexConfig
from hacksome.creative.review import (
    ConceptBinding,
    ReviewBatch,
    ReviewClosedError,
    ReviewConflictError,
    ReviewRound,
    ReviewStaleError,
    ReviewStore,
    ReviewValidationError,
    canonical_adjacent_pairs,
    display_pair_for_reviewer,
)
from hacksome.hub import RunHub
from hacksome.state import read_jsonl, sha256_text


def _concept(index: int) -> ConceptBinding:
    reference = f"creative-concept-s01-{index:02d}-r002"
    return ConceptBinding(
        concept_ref=reference,
        concept_sha256=sha256_text(f"Concept {index}"),
    )


def _review_payload(
    review_round: ReviewRound,
    *,
    review_id: str = "review-one",
    reviewer_id: str = "reviewer-one",
    reviewer_name: str = "Percy 🐉",
    concept_indexes: tuple[int, ...] = (0,),
    supersedes_review_id: str | None = None,
    schema_version: int | None = 2,
) -> dict[str, Any]:
    concept_reviews = [
        {
            "concept_ref": review_round.concepts[index].concept_ref,
            "concept_sha256": review_round.concepts[index].concept_sha256,
            "one_sentence_retell": "观众转动旋钮，然后整间房发现自己改的是同一个秘密。",
            "share_target": "会把它转发给做装置艺术的朋友",
            **(
                {
                    "share_impulse": "immediate",
                    "demo_confidence": "yes",
                }
                if schema_version == 2
                else {}
            ),
            "reactions": {
                "surprise": "yes",
                "fun": "yes",
                "mystery": "maybe",
                "confusion": "no",
            },
            "recommendation": "keep",
            "comment": "这个 reveal 很清楚，也有一点点荒诞感 ✨",
        }
        for index in concept_indexes
    ]
    pairwise = []
    if review_round.pairs:
        pair = review_round.pairs[0]
        pairwise.append(
            {
                **pair.to_dict(),
                "preference": "left",
                "reason": "左边的机制更容易在三十秒内讲清楚。",
            }
        )
    payload = {
        "review_id": review_id,
        "round_id": review_round.round_id,
        "round_sha256": review_round.round_sha256,
        "run_id": review_round.run_id,
        "reviewer_id": reviewer_id,
        "reviewer_name": reviewer_name,
        "concept_reviews": concept_reviews,
        "pairwise": pairwise,
        "overall_comment": "值得继续，但别把神秘感解释得太满。",
        "supersedes_review_id": supersedes_review_id,
    }
    if schema_version is not None:
        payload["schema_version"] = schema_version
    return payload


def _resolution_payload(
    review_round: ReviewRound,
    *,
    actions: list[dict[str, Any]],
    merge_groups: list[dict[str, Any]] | None = None,
    coverage_override_reason: str | None = None,
    resolution_id: str = "resolution-one",
) -> dict[str, Any]:
    return {
        "resolution_id": resolution_id,
        "run_id": review_round.run_id,
        "curator_name": "Percy",
        "round_id": review_round.round_id,
        "round_sha256": review_round.round_sha256,
        "actions": actions,
        "merge_groups": merge_groups or [],
        "coverage_override_reason": coverage_override_reason,
    }


def _action(
    concept_ref: str,
    *,
    action: str = "keep",
    approved_feedback: list[dict[str, str]] | None = None,
    curator_instruction: str = "",
    reason: str = "",
    merge_group_id: str | None = None,
) -> dict[str, Any]:
    return {
        "concept_ref": concept_ref,
        "action": action,
        "approved_feedback": approved_feedback or [],
        "curator_instruction": curator_instruction,
        "reason": reason,
        "merge_group_id": merge_group_id,
    }


class _Clock:
    def __init__(self) -> None:
        self.values: Iterator[str] = iter(
            (
                "2026-07-23T01:00:00+00:00",
                "2026-07-23T01:01:00+00:00",
                "2026-07-23T01:02:00+00:00",
                "2026-07-23T01:03:00+00:00",
            )
        )

    def __call__(self) -> str:
        return next(self.values)


class CreativeReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.hub = RunHub.create(
            "Make a strange shared experience",
            self.root,
            settings={},
            codex_config=CodexConfig(),
            run_id="creative-run",
            route={
                "id": "creative",
                "contract_version": "2",
                "prompt_policy_version": "2",
                "stage_policy_version": "2",
                "report_policy_version": "2",
            },
        )
        self.batch = ReviewBatch.build(
            run_id=self.hub.run_id,
            concepts=(_concept(1), _concept(2), _concept(3)),
        )
        self.review_round = ReviewRound.open(self.batch)
        self.store = ReviewStore(self.hub, self.review_round, clock=_Clock())
        self.store.initialize()

    def test_batch_round_hashes_and_canonical_pairs_are_stable(self) -> None:
        reversed_batch = ReviewBatch.build(
            run_id=self.hub.run_id,
            concepts=tuple(reversed(self.batch.concepts)),
        )
        self.assertEqual(reversed_batch.batch_sha256, self.batch.batch_sha256)
        self.assertEqual(
            [pair.pair_id for pair in self.review_round.pairs],
            ["creative-pair-001", "creative-pair-002", "creative-pair-003"],
        )
        self.assertEqual(
            self.review_round.pairs[-1].right_ref,
            self.review_round.concepts[0].concept_ref,
        )
        self.assertEqual(
            ReviewBatch.from_dict(self.batch.to_dict()),
            self.batch,
        )
        self.assertEqual(
            ReviewRound.from_dict(self.review_round.to_dict()),
            self.review_round,
        )

    def test_pair_generation_for_zero_one_two_and_limit(self) -> None:
        self.assertEqual(canonical_adjacent_pairs(()), ())
        self.assertEqual(canonical_adjacent_pairs((_concept(1),)), ())
        pair = canonical_adjacent_pairs((_concept(2), _concept(1)))
        self.assertEqual(len(pair), 1)
        self.assertEqual(pair[0].left_ref, _concept(1).concept_ref)
        with self.assertRaisesRegex(ReviewValidationError, "more than 8"):
            canonical_adjacent_pairs(tuple(_concept(index) for index in range(1, 10)))
        skipped = ReviewBatch.build(
            run_id=self.hub.run_id,
            concepts=(),
            skip_reason="all_candidates_failed_concept_screen",
        )
        self.assertEqual(skipped.status, "skipped_empty")

    def test_reviewer_display_swap_never_changes_canonical_pair(self) -> None:
        pair = self.review_round.pairs[0]
        displays = [
            display_pair_for_reviewer(pair, f"reviewer-{index}")
            for index in range(1, 20)
        ]
        self.assertTrue(any(item.swapped for item in displays))
        self.assertTrue(any(not item.swapped for item in displays))
        for item in displays:
            self.assertEqual(
                {item.left_ref, item.right_ref},
                {pair.left_ref, pair.right_ref},
            )
        self.assertEqual(self.review_round.pairs[0], pair)

    def test_review_preserves_unicode_and_generates_fragment_hashes(self) -> None:
        review = self.store.submit_review(
            _review_payload(self.review_round),
            expected_reviewer_id="reviewer-one",
        )

        self.assertEqual(review.reviewer_name, "Percy 🐉")
        self.assertEqual(review.independence, "pre_reveal")
        self.assertEqual(review.schema_version, 2)
        self.assertEqual(review.concept_reviews[0].share_impulse, "immediate")
        self.assertEqual(review.concept_reviews[0].demo_confidence, "yes")
        self.assertEqual(
            review.concept_reviews[0].feedback_ref,
            f"review-one:concept:{self.review_round.concepts[0].concept_ref}",
        )
        self.assertRegex(review.concept_reviews[0].feedback_sha256, r"^[0-9a-f]{64}$")
        records = read_jsonl(self.store.reviews_path)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["submitted_at"], "2026-07-23T01:00:00+00:00")
        self.assertEqual(records[0]["reviewer_name"], "Percy 🐉")
        self.assertEqual(records[0]["schema_version"], 2)
        self.assertEqual(
            records[0]["concept_reviews"][0]["share_impulse"],
            "immediate",
        )

    def test_v2_signals_are_hash_bound_and_immediate_requires_target(self) -> None:
        payload = _review_payload(self.review_round)
        baseline = self.store.submit_review(payload)
        fragment = baseline.concept_reviews[0]
        self.assertEqual(
            fragment.feedback_sha256,
            self.store.feedback_fragments()[0].feedback_sha256,
        )

        changed = _review_payload(
            self.review_round,
            review_id="review-two",
            reviewer_id="reviewer-two",
        )
        changed["concept_reviews"][0]["share_impulse"] = "maybe"
        second = self.store.submit_review(changed)
        self.assertNotEqual(
            second.concept_reviews[0].feedback_sha256,
            fragment.feedback_sha256,
        )

        invalid = _review_payload(
            self.review_round,
            review_id="review-three",
            reviewer_id="reviewer-three",
        )
        invalid["concept_reviews"][0]["share_target"] = "   "
        with self.assertRaisesRegex(ReviewValidationError, "share_target"):
            self.store.submit_review(invalid)

    def test_legacy_v1_receipt_without_new_signals_remains_readable(self) -> None:
        legacy_hub = RunHub.create(
            "Legacy Creative review",
            self.root,
            settings={},
            codex_config=CodexConfig(),
            run_id="creative-run-v1",
            route="creative",
        )
        legacy_batch = ReviewBatch.build(
            run_id=legacy_hub.run_id,
            concepts=(_concept(1),),
        )
        legacy_round = ReviewRound.open(legacy_batch)
        legacy_store = ReviewStore(
            legacy_hub,
            legacy_round,
            clock=_Clock(),
        )
        legacy_store.initialize()
        legacy = legacy_store.submit_review(
            _review_payload(
                legacy_round,
                schema_version=None,
            )
        )
        self.assertEqual(legacy.schema_version, 1)
        self.assertIsNone(legacy.concept_reviews[0].share_impulse)
        self.assertIsNone(legacy.concept_reviews[0].demo_confidence)
        record = read_jsonl(legacy_store.reviews_path)[0]
        self.assertNotIn("schema_version", record)
        self.assertNotIn("share_impulse", record["concept_reviews"][0])

        reloaded = ReviewStore(
            legacy_hub,
            legacy_round,
            clock=_Clock(),
        ).latest_receipts()
        self.assertEqual(reloaded, (legacy,))
        with self.assertRaisesRegex(
            ReviewValidationError,
            "run contract",
        ):
            self.store.submit_review(
                _review_payload(self.review_round, schema_version=None)
            )
        with self.assertRaisesRegex(
            ReviewValidationError,
            "run contract",
        ):
            legacy_store.submit_review(
                _review_payload(
                    legacy_round,
                    review_id="legacy-v2",
                    schema_version=2,
                )
            )

    def test_v2_payload_requires_signals_and_rejects_unknown_version(self) -> None:
        missing = _review_payload(self.review_round)
        del missing["concept_reviews"][0]["demo_confidence"]
        with self.assertRaisesRegex(ReviewValidationError, "missing fields"):
            self.store.submit_review(missing)
        with self.assertRaisesRegex(ReviewValidationError, "schema_version"):
            self.store.submit_review(
                _review_payload(self.review_round, schema_version=3)
            )

    def test_review_retry_is_idempotent_and_reuses_server_timestamp(self) -> None:
        payload = _review_payload(self.review_round)
        first = self.store.submit_review(payload)
        second = self.store.submit_review(payload)

        self.assertEqual(second, first)
        self.assertEqual(second.submitted_at, "2026-07-23T01:00:00+00:00")
        self.assertEqual(len(read_jsonl(self.store.reviews_path)), 1)
        with self.assertRaisesRegex(ReviewConflictError, "different request"):
            self.store.submit_review({**payload, "overall_comment": "changed"})

    def test_supersedes_is_latest_only_and_marks_post_reveal(self) -> None:
        first = self.store.submit_review(_review_payload(self.review_round))
        second_payload = _review_payload(
            self.review_round,
            review_id="review-two",
            supersedes_review_id=first.review_id,
        )
        second = self.store.submit_review(second_payload)

        self.assertEqual(second.independence, "post_reveal")
        self.assertEqual(self.store.latest_receipts(), (second,))
        with self.assertRaisesRegex(ReviewConflictError, "latest receipt"):
            self.store.submit_review(
                _review_payload(
                    self.review_round,
                    review_id="review-three",
                    supersedes_review_id=first.review_id,
                )
            )

    def test_review_rejects_stale_round_hash_and_display_order_pair(self) -> None:
        payload = _review_payload(self.review_round)
        with self.assertRaisesRegex(ReviewStaleError, "round_sha256"):
            self.store.submit_review({**payload, "round_sha256": "f" * 64})

        pair = payload["pairwise"][0]
        swapped = {
            **pair,
            "left_ref": pair["right_ref"],
            "right_ref": pair["left_ref"],
            "left_sha256": pair["right_sha256"],
            "right_sha256": pair["left_sha256"],
        }
        with self.assertRaisesRegex(ReviewStaleError, "canonical order"):
            self.store.submit_review(
                {
                    **payload,
                    "review_id": "review-swapped",
                    "pairwise": [swapped],
                }
            )

    def test_review_field_limits_and_unknown_fields_fail_closed(self) -> None:
        payload = _review_payload(self.review_round)
        with self.assertRaisesRegex(ReviewValidationError, "80 Unicode"):
            self.store.submit_review({**payload, "reviewer_name": "名" * 81})
        with self.assertRaisesRegex(ReviewValidationError, "unknown fields"):
            self.store.submit_review({**payload, "server_owned": True})

    def test_resolution_requires_coverage_or_explicit_override(self) -> None:
        self.store.submit_review(_review_payload(self.review_round))
        actions = [_action(item.concept_ref) for item in self.review_round.concepts]
        with self.assertRaisesRegex(ReviewValidationError, "coverage override"):
            self.store.submit_resolution(
                _resolution_payload(self.review_round, actions=actions)
            )

        resolution = self.store.submit_resolution(
            _resolution_payload(
                self.review_round,
                actions=actions,
                coverage_override_reason="两位队友离线，先由 Percy 做品味决议。",
            )
        )
        self.assertEqual(
            resolution.uncovered_concept_refs,
            tuple(item.concept_ref for item in self.review_round.concepts[1:]),
        )
        self.assertRegex(resolution.resolution_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(
            resolution.wait_close_payload()["latest_receipt_set_sha256"],
            resolution.latest_receipt_set_sha256,
        )

    def test_resolution_approves_only_latest_exact_relevant_fragment(self) -> None:
        first = self.store.submit_review(_review_payload(self.review_round))
        fragment = first.concept_reviews[0]
        actions = [
            _action(
                item.concept_ref,
                action="revise" if index == 0 else "keep",
                approved_feedback=(
                    [
                        {
                            "feedback_ref": fragment.feedback_ref,
                            "feedback_sha256": fragment.feedback_sha256,
                        }
                    ]
                    if index == 0
                    else []
                ),
            )
            for index, item in enumerate(self.review_round.concepts)
        ]
        resolution = self.store.submit_resolution(
            _resolution_payload(
                self.review_round,
                actions=actions,
                coverage_override_reason="其他两个候选由 Percy 直接处理。",
            )
        )
        self.assertEqual(
            resolution.actions[0].approved_feedback[0].feedback_ref,
            fragment.feedback_ref,
        )

    def test_revise_requires_feedback_or_hash_bound_instruction(self) -> None:
        self.store.submit_review(
            _review_payload(
                self.review_round,
                concept_indexes=(0, 1, 2),
            )
        )
        actions = [_action(item.concept_ref) for item in self.review_round.concepts]
        actions[0] = _action(
            self.review_round.concepts[0].concept_ref,
            action="revise",
        )
        with self.assertRaisesRegex(ReviewValidationError, "requires approved"):
            self.store.submit_resolution(
                _resolution_payload(self.review_round, actions=actions)
            )

        actions[0] = _action(
            self.review_round.concepts[0].concept_ref,
            action="revise",
            curator_instruction="保留旋钮机制，但让 reveal 发生在另一位观众身上。",
        )
        resolution = self.store.submit_resolution(
            _resolution_payload(self.review_round, actions=actions)
        )
        self.assertEqual(
            resolution.actions[0].curator_instruction_sha256,
            sha256_text(actions[0]["curator_instruction"]),
        )

    def test_resolution_rejects_superseded_or_unrelated_feedback(self) -> None:
        first = self.store.submit_review(
            _review_payload(
                self.review_round,
                concept_indexes=(0, 1, 2),
            )
        )
        second = self.store.submit_review(
            _review_payload(
                self.review_round,
                review_id="review-two",
                concept_indexes=(0, 1, 2),
                supersedes_review_id=first.review_id,
            )
        )
        refs = [item.concept_ref for item in self.review_round.concepts]
        superseded = first.concept_reviews[0]
        actions = [_action(ref) for ref in refs]
        actions[0] = _action(
            refs[0],
            action="revise",
            approved_feedback=[
                {
                    "feedback_ref": superseded.feedback_ref,
                    "feedback_sha256": superseded.feedback_sha256,
                }
            ],
        )
        with self.assertRaisesRegex(ReviewStaleError, "latest receipt set"):
            self.store.submit_resolution(
                _resolution_payload(self.review_round, actions=actions)
            )

        unrelated = second.concept_reviews[0]
        actions[0] = _action(refs[0])
        actions[1] = _action(
            refs[1],
            action="revise",
            approved_feedback=[
                {
                    "feedback_ref": unrelated.feedback_ref,
                    "feedback_sha256": unrelated.feedback_sha256,
                }
            ],
        )
        with self.assertRaisesRegex(ReviewValidationError, "unrelated"):
            self.store.submit_resolution(
                _resolution_payload(self.review_round, actions=actions)
            )

    def test_merge_groups_are_disjoint_and_require_reason(self) -> None:
        self.store.submit_review(
            _review_payload(
                self.review_round,
                concept_indexes=(0, 1, 2),
            )
        )
        refs = [item.concept_ref for item in self.review_round.concepts]
        actions = [
            _action(
                ref,
                action="merge" if index < 2 else "keep",
                curator_instruction=(
                    "把两者的物理触发和延迟揭示合成一个体验。"
                    if index < 2
                    else ""
                ),
                merge_group_id="merge-one" if index < 2 else None,
            )
            for index, ref in enumerate(refs)
        ]
        resolution = self.store.submit_resolution(
            _resolution_payload(
                self.review_round,
                actions=actions,
                merge_groups=[
                    {
                        "merge_group_id": "merge-one",
                        "source_refs": refs[:2],
                        "reason": "两个机制互补，而不是互相覆盖。",
                    }
                ],
            )
        )
        self.assertEqual(resolution.merge_groups[0].source_refs, tuple(refs[:2]))

    def test_overlapping_merge_groups_and_duplicate_actions_are_rejected(self) -> None:
        self.store.submit_review(
            _review_payload(
                self.review_round,
                concept_indexes=(0, 1, 2),
            )
        )
        refs = [item.concept_ref for item in self.review_round.concepts]
        with self.assertRaisesRegex(ReviewValidationError, "multiple merge groups"):
            self.store.submit_resolution(
                _resolution_payload(
                    self.review_round,
                    actions=[
                        _action(
                            ref,
                            action="merge",
                            curator_instruction="合并。",
                            merge_group_id="merge-one",
                        )
                        for ref in refs
                    ],
                    merge_groups=[
                        {
                            "merge_group_id": "merge-one",
                            "source_refs": refs[:2],
                            "reason": "第一组。",
                        },
                        {
                            "merge_group_id": "merge-two",
                            "source_refs": refs[1:],
                            "reason": "第二组。",
                        },
                    ],
                )
            )
        duplicate_actions = [
            _action(refs[0]),
            _action(refs[0]),
            _action(refs[2]),
        ]
        with self.assertRaisesRegex(ReviewValidationError, "duplicate resolution"):
            self.store.submit_resolution(
                _resolution_payload(
                    self.review_round,
                    actions=duplicate_actions,
                )
            )

    def test_taste_veto_requires_reason(self) -> None:
        self.store.submit_review(
            _review_payload(
                self.review_round,
                concept_indexes=(0, 1, 2),
            )
        )
        actions = [_action(item.concept_ref) for item in self.review_round.concepts]
        actions[0] = _action(
            self.review_round.concepts[0].concept_ref,
            action="taste_veto",
        )
        with self.assertRaisesRegex(ReviewValidationError, "taste_veto"):
            self.store.submit_resolution(
                _resolution_payload(self.review_round, actions=actions)
            )

    def test_resolution_retry_and_closed_round_reject_new_writes(self) -> None:
        self.store.submit_review(
            _review_payload(
                self.review_round,
                concept_indexes=(0, 1, 2),
            )
        )
        payload = _resolution_payload(
            self.review_round,
            actions=[
                _action(item.concept_ref)
                for item in self.review_round.concepts
            ],
        )
        first = self.store.submit_resolution(payload)
        self.assertEqual(self.store.submit_resolution(payload), first)
        self.assertEqual(len(read_jsonl(self.store.resolutions_path)), 1)
        with self.assertRaises(ReviewConflictError):
            self.store.submit_resolution(
                {**payload, "curator_name": "Another curator"}
            )
        with self.assertRaises(ReviewClosedError):
            self.store.submit_review(
                _review_payload(
                    self.review_round,
                    review_id="review-after-close",
                    reviewer_id="reviewer-two",
                )
            )
        snapshot = self.store.snapshot()
        self.assertEqual(snapshot.round.status, "closed")
        self.assertEqual(snapshot.resolution, first)
        self.assertEqual(
            self.hub.load_raw_state()["wait"]["resolution_sha256"],
            first.resolution_sha256,
        )

    def test_resolution_wait_and_ledger_reconcile_same_outbox_record(self) -> None:
        self.hub.set_wait(
            {
                "status": "open",
                "round_id": self.review_round.round_id,
                "round_sha256": self.review_round.round_sha256,
                "batch_id": self.review_round.batch_id,
            }
        )
        self.store.submit_review(
            _review_payload(
                self.review_round,
                concept_indexes=(0, 1, 2),
            )
        )
        payload = _resolution_payload(
            self.review_round,
            actions=[
                _action(item.concept_ref)
                for item in self.review_round.concepts
            ],
        )
        with patch("hacksome.hub.append_jsonl", side_effect=OSError("disk crash")):
            with self.assertRaisesRegex(OSError, "disk crash"):
                self.store.submit_resolution(payload)

        state = self.hub.load_raw_state()
        self.assertEqual(state["wait"]["status"], "closed")
        self.assertEqual(state["wait"]["batch_id"], self.review_round.batch_id)
        self.assertEqual(len(state["pending_records"]), 1)
        pending = state["pending_records"][0]["record"]
        self.assertEqual(
            state["wait"]["resolution_sha256"],
            pending["resolution_sha256"],
        )

        retried = self.store.submit_resolution(payload)
        self.assertEqual(
            retried.to_dict(),
            {key: value for key, value in pending.items() if key != "created_at"},
        )
        self.assertEqual(self.hub.load_raw_state()["pending_records"], [])
        self.assertEqual(len(read_jsonl(self.store.resolutions_path)), 1)


if __name__ == "__main__":
    unittest.main()
