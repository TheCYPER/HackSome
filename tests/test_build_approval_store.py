from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hacksome.build_approval.build_adapter import InMemoryBuildControlAdapter
from hacksome.build_approval.contracts import (
    ApprovalClosedError,
    ApprovalIdempotencyError,
    ApprovalValidationError,
    CardAlreadyAuthorizedError,
)
from hacksome.build_approval.service import ApprovalService
from hacksome.build_approval.store import ApprovalStore
from hacksome.post_card.contracts import (
    ArtifactRefV1,
    BuildHandoffV1,
    CatalogSourceV1,
    PostCardCandidateV1,
    PostCardCatalogV1,
)
from hacksome.state import StateError, atomic_write_json, read_json_object, sha256_text


def make_catalog(count: int) -> PostCardCatalogV1:
    source = CatalogSourceV1("useful", "1", "source-run")
    cards = []
    for ordinal in range(count):
        card_id = f"card-{ordinal + 1:02d}"
        markdown = f"# Dispatch {ordinal + 1}\n\nExact Card {ordinal + 1}.\n"
        digest = sha256_text(markdown)
        cards.append(
            PostCardCandidateV1(
                ordinal=ordinal,
                card_id=card_id,
                title=f"Dispatch {ordinal + 1}",
                card_sha256=digest,
                card_markdown=markdown,
                source_artifact_ref=ArtifactRefV1(
                    card_id,
                    "idea_card",
                    f"artifacts/{card_id}.md",
                ),
                route_handoff_ref=None,
                handoff=BuildHandoffV1(
                    source_run_id=source.run_id,
                    idea_card_id=card_id,
                    idea_card_sha256=digest,
                    challenge_markdown="# Challenge\n\nDo real work.\n",
                    initial_idea_card_markdown=markdown,
                ),
            )
        )
    return PostCardCatalogV1.build(source=source, cards=tuple(cards))


def authorize_payload(
    catalog: PostCardCatalogV1,
    request_id: str,
    ordinals: list[int],
) -> dict:
    return {
        "schema_version": 1,
        "request_id": request_id,
        "catalog_sha256": catalog.catalog_sha256,
        "cards": [
            {
                "card_id": catalog.cards[index].card_id,
                "card_sha256": catalog.cards[index].card_sha256,
            }
            for index in ordinals
        ],
    }


class BuildApprovalStoreTests(unittest.TestCase):
    def _service(
        self,
        root: Path,
        catalog: PostCardCatalogV1,
    ) -> ApprovalService:
        store = ApprovalStore(root)
        store.initialize(catalog)
        return ApprovalService(
            run_dir=root / "source-placeholder",
            store=store,
            catalog=catalog,
            build_adapter=InMemoryBuildControlAdapter(max_active_teams=2),
            source_integrity_error=None,
        )

    def test_multi_batch_restart_close_and_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approval"
            catalog = make_catalog(11)
            service = self._service(root, catalog)
            batch_a = authorize_payload(
                catalog, "authorize-a", list(range(10))
            )
            result_a = service.authorize(batch_a)
            replay_a = service.authorize(batch_a)
            self.assertEqual(replay_a, result_a)
            service.reconcile()
            snapshot = service.snapshot()
            self.assertEqual(
                [card["status"] for card in snapshot["cards"]].count("active"),
                2,
            )
            self.assertEqual(
                [card["status"] for card in snapshot["cards"]].count("queued"),
                8,
            )

            restarted = self._service(root, catalog)
            restarted.authorize(
                authorize_payload(catalog, "authorize-b", [10])
            )
            restarted.close(
                {
                    "schema_version": 1,
                    "request_id": "close-final",
                    "catalog_sha256": catalog.catalog_sha256,
                }
            )
            self.assertEqual(
                restarted.snapshot()["approval_status"],
                "closed",
            )
            with self.assertRaises(ApprovalClosedError):
                restarted.authorize(
                    authorize_payload(catalog, "authorize-c", [10])
                )
            self.assertEqual(len(restarted.store.outboxes()), 11)
            self.assertEqual(len(restarted.store.load_mutations()), 3)
            self.assertEqual(restarted.validate(), [])

    def test_batch_limits_duplicates_stale_and_idempotency_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = make_catalog(11)
            service = self._service(Path(directory) / "approval", catalog)
            with self.assertRaises(ApprovalValidationError):
                service.authorize(
                    {
                        "schema_version": 1,
                        "request_id": "empty",
                        "catalog_sha256": catalog.catalog_sha256,
                        "cards": [],
                    }
                )
            with self.assertRaises(ApprovalValidationError):
                service.authorize(
                    authorize_payload(
                        catalog, "too-many", list(range(11))
                    )
                )
            service.authorize(authorize_payload(catalog, "first", [0]))
            with self.assertRaises(CardAlreadyAuthorizedError):
                service.authorize(authorize_payload(catalog, "second", [0]))
            with self.assertRaises(ApprovalIdempotencyError):
                service.authorize(authorize_payload(catalog, "first", [1]))

    def test_projection_corruption_rebuilds_from_immutable_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = make_catalog(2)
            root = Path(directory) / "approval"
            service = self._service(root, catalog)
            service.authorize(authorize_payload(catalog, "first", [0]))
            (root / "state.json").write_text("{}", encoding="utf-8")
            self.assertTrue(service.store.validate())
            projection = service.store.rebuild_projection()
            self.assertEqual(projection["authorized_card_ids"], ["card-01"])
            self.assertEqual(service.store.validate(), [])

    def test_existing_approval_open_and_validate_are_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = make_catalog(1)
            service = self._service(root / "approval", catalog)
            service.authorize(authorize_payload(catalog, "first", [0]))
            service.store.state_path.write_text("{}\n", encoding="utf-8")
            before = service.store.state_path.read_bytes()
            source = root / "source"
            source.mkdir()

            with patch(
                "hacksome.build_approval.service.project_post_card_catalog",
                return_value=catalog,
            ):
                reopened = ApprovalService.open(
                    source,
                    approval_root=service.store.root,
                )
                self.assertTrue(reopened.validate())
                reopened.snapshot()

            self.assertEqual(service.store.state_path.read_bytes(), before)

    def test_immutable_mutation_tampering_fails_closed(self) -> None:
        def extra_field(row: dict) -> None:
            row["unexpected"] = True

        def changed_batch(row: dict) -> None:
            row["batch_id"] = "batch-000001-tampered"

        def changed_card_hash(row: dict) -> None:
            row["authorizations"][0]["card_sha256"] = "0" * 64

        def changed_ordinal(row: dict) -> None:
            row["authorizations"][0]["ordinal"] = 1

        def changed_envelope_hash(row: dict) -> None:
            row["authorizations"][0]["envelope_sha256"] = "0" * 64

        mutators = {
            "extra field": extra_field,
            "batch binding": changed_batch,
            "Card hash": changed_card_hash,
            "catalog ordinal": changed_ordinal,
            "envelope hash": changed_envelope_hash,
        }
        for label, mutate in mutators.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                catalog = make_catalog(2)
                root = Path(directory) / "approval"
                service = self._service(root, catalog)
                service.authorize(authorize_payload(catalog, "first", [0]))
                path = next(service.store.mutations_dir.glob("*.json"))
                row = read_json_object(path)
                mutate(row)
                atomic_write_json(path, row)

                with self.assertRaises(StateError):
                    service.store.load_mutations()
                self.assertTrue(service.store.validate())
                with self.assertRaises(StateError):
                    service.store.ensure_outboxes()

    def test_outbox_order_and_batch_binding_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = make_catalog(2)
            root = Path(directory) / "approval"
            service = self._service(root, catalog)
            service.authorize(authorize_payload(catalog, "first", [0, 1]))
            outbox_path = service.store.outbox_dir / (
                f"{service.snapshot()['cards'][0]['authorization_id']}.json"
            )
            outbox = read_json_object(outbox_path)
            outbox["batch_sequence"] = 99
            outbox["catalog_ordinal"] = 1
            atomic_write_json(outbox_path, outbox)

            self.assertTrue(service.store.validate())
            with self.assertRaises(StateError):
                service.store.ensure_outboxes()

    def test_committed_batch_recovers_when_outbox_creation_crashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = make_catalog(1)
            root = Path(directory) / "approval"
            service = self._service(root, catalog)
            with patch.object(
                service.store,
                "ensure_outboxes",
                side_effect=RuntimeError("fault after mutation commit"),
            ):
                with self.assertRaisesRegex(RuntimeError, "fault"):
                    service.authorize(
                        authorize_payload(catalog, "outbox-crash", [0])
                    )
            self.assertEqual(len(service.store.load_mutations()), 1)
            self.assertEqual(service.store.outboxes(), [])

            restarted = self._service(root, catalog)
            snapshot = restarted.reconcile()
            self.assertEqual(len(restarted.store.outboxes()), 1)
            self.assertEqual(snapshot["cards"][0]["status"], "active")

    def test_receipt_and_delivery_projection_tamper_is_per_card_and_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = make_catalog(1)
            service = self._service(Path(directory) / "approval", catalog)
            service.authorize(authorize_payload(catalog, "first", [0]))
            service.reconcile()
            authorization_id = service.snapshot()["cards"][0][
                "authorization_id"
            ]
            assert isinstance(authorization_id, str)

            receipt_path = (
                service.store.receipts_dir / f"{authorization_id}.json"
            )
            receipt = read_json_object(receipt_path)
            receipt["unexpected"] = str(Path(directory))
            atomic_write_json(receipt_path, receipt)
            snapshot = service.snapshot()
            self.assertEqual(snapshot["cards"][0]["status"], "error")
            self.assertEqual(
                snapshot["cards"][0]["error"]["code"],
                "receipt_integrity_error",
            )
            self.assertNotIn(
                str(Path(directory)),
                str(snapshot["cards"][0]["error"]),
            )
            self.assertTrue(service.validate())

            receipt.pop("unexpected")
            atomic_write_json(receipt_path, receipt)
            delivery_path = (
                service.store.deliveries_dir / f"{authorization_id}.json"
            )
            delivery = read_json_object(delivery_path)
            delivery["unexpected"] = "tampered"
            atomic_write_json(delivery_path, delivery)
            snapshot = service.snapshot()
            self.assertEqual(
                snapshot["cards"][0]["error"]["code"],
                "delivery_integrity_error",
            )
            self.assertTrue(service.validate())


if __name__ == "__main__":
    unittest.main()
