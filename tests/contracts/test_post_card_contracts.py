from __future__ import annotations

import unittest
from dataclasses import replace

from hacksome.contracts.post_card.contracts import (
    ArtifactRefV1,
    BuildHandoffV1,
    CatalogSourceV1,
    PostCardCandidateV1,
    PostCardCatalogV1,
    PostCardContractError,
)
from hacksome.core.state import sha256_text


def _catalog(count: int = 1) -> PostCardCatalogV1:
    source = CatalogSourceV1(
        route_id="useful",
        route_contract_version="1",
        run_id="run-1",
    )
    cards = []
    for ordinal in range(count):
        card_id = f"card-{ordinal + 1}"
        markdown = f"# Card {ordinal + 1}\n\nExact body.\n"
        digest = sha256_text(markdown)
        handoff = BuildHandoffV1(
            source_run_id=source.run_id,
            idea_card_id=card_id,
            idea_card_sha256=digest,
            challenge_markdown="# Challenge\n\nBuild it.\n",
            initial_idea_card_markdown=markdown,
        )
        cards.append(
            PostCardCandidateV1(
                ordinal=ordinal,
                card_id=card_id,
                title=f"Card {ordinal + 1}",
                card_sha256=digest,
                card_markdown=markdown,
                source_artifact_ref=ArtifactRefV1(
                    artifact_id=card_id,
                    artifact_type="idea_card",
                    relative_path=f"artifacts/cards/{card_id}.md",
                ),
                route_handoff_ref=None,
                handoff=handoff,
            )
        )
    return PostCardCatalogV1.build(source=source, cards=tuple(cards))


class PostCardContractTests(unittest.TestCase):
    def test_catalog_round_trip_and_hash_are_stable(self) -> None:
        catalog = _catalog(3)
        decoded = PostCardCatalogV1.from_mapping(catalog.to_mapping())
        self.assertEqual(decoded, catalog)
        self.assertEqual(decoded.computed_sha256(), catalog.catalog_sha256)

    def test_exact_five_field_handoff_rejects_extra_and_hash_drift(self) -> None:
        catalog = _catalog()
        mapping = catalog.cards[0].handoff.to_mapping()
        with self.assertRaisesRegex(PostCardContractError, "unknown fields"):
            BuildHandoffV1.from_mapping({**mapping, "route_id": "useful"})
        with self.assertRaisesRegex(PostCardContractError, "does not match"):
            BuildHandoffV1.from_mapping(
                {
                    **mapping,
                    "initial_idea_card_markdown": "# Changed\n",
                }
            )

    def test_catalog_rejects_non_contiguous_order_and_stale_hash(self) -> None:
        catalog = _catalog(2)
        with self.assertRaisesRegex(PostCardContractError, "contiguous"):
            PostCardCatalogV1.build(
                source=catalog.source,
                cards=(replace(catalog.cards[0], ordinal=1),),
            )
        payload = catalog.to_mapping()
        payload["catalog_sha256"] = "0" * 64
        with self.assertRaisesRegex(PostCardContractError, "does not match"):
            PostCardCatalogV1.from_mapping(payload)


if __name__ == "__main__":
    unittest.main()
