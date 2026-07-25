from __future__ import annotations

import json
import tempfile
import unittest

from hacksome.creative.review import ReviewBatch, ReviewRound, ReviewStore
from hacksome.creative.workflow import CreativeIdeaWorkflow
from hacksome.post_card.catalog import project_post_card_catalog

from tests.test_creative_curation_workflow import CreativeCurationRunner
from tests.test_creative_review import (
    _action,
    _resolution_payload,
    _review_payload,
)
from tests.test_creative_workflow import _settings


class CreativePostCardTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_creative_adopts_frozen_handoff_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                settings=_settings(),
                runner=CreativeCurationRunner(),
                run_id="creative-post-card",
            )
            outcome = await workflow.execute()
            self.assertEqual(outcome.status, "waiting")
            batch = ReviewBatch.from_dict(
                json.loads(outcome.primary_artifact.read_text(encoding="utf-8"))
            )
            review_round = ReviewRound.open(batch)
            store = ReviewStore(workflow.hub, review_round)
            store.initialize()
            store.submit_review(
                _review_payload(
                    review_round,
                    concept_indexes=tuple(range(len(review_round.concepts))),
                )
            )
            store.submit_resolution(
                _resolution_payload(
                    review_round,
                    actions=[
                        _action(binding.concept_ref)
                        for binding in review_round.concepts
                    ],
                )
            )
            completed = await workflow.resume()
            self.assertEqual(completed.status, "completed")

            catalog = project_post_card_catalog(workflow.run_dir)
            self.assertEqual(catalog.source.route_contract_version, "2")
            self.assertEqual(len(catalog.cards), len(review_round.concepts))
            for card in catalog.cards:
                self.assertIsNotNone(card.route_handoff_ref)
                assert card.route_handoff_ref is not None
                frozen = json.loads(
                    workflow.hub.read_artifact(card.route_handoff_ref)
                )
                self.assertEqual(card.handoff.to_mapping(), frozen)

    async def test_zero_card_creative_catalog_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = CreativeIdeaWorkflow.create(
                "Make a legible interactive surprise.",
                directory,
                settings=_settings(),
                runner=CreativeCurationRunner(empty_concepts=True),
                run_id="creative-post-card-empty",
            )
            outcome = await workflow.execute()
            self.assertEqual(outcome.status, "completed")
            self.assertEqual(
                project_post_card_catalog(workflow.run_dir).cards,
                (),
            )


if __name__ == "__main__":
    unittest.main()
