"""Append-only Approval ledger, durable outbox, and rebuildable projection."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hacksome.build_approval.contracts import (
    ApprovalClosedError,
    ApprovalIdempotencyError,
    ApprovalStaleError,
    ApprovalValidationError,
    AuthorizeRequestV1,
    BuildAuthorizationEnvelopeV1,
    BuildReceiptV1,
    CardAlreadyAuthorizedError,
    CardSelectionV1,
    CloseRequestV1,
    canonical_request_sha256,
)
from hacksome.post_card.contracts import PostCardCatalogV1
from hacksome.state import (
    StateConflictError,
    StateError,
    advisory_lease,
    atomic_write_json,
    read_json_object,
    sha256_json,
)

_AUTHORIZATION_ID = re.compile(r"^auth-[0-9a-f]{32}$")
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ApprovalStore:
    """Single persistence owner for one source run's Build authorizations."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.catalog_path = self.root / "catalog.json"
        self.state_path = self.root / "state.json"
        self.mutations_dir = self.root / "mutations"
        self.outbox_dir = self.root / "outbox"
        self.receipts_dir = self.root / "receipts"
        self.deliveries_dir = self.root / "deliveries"
        self.lock_path = self.root / "lock"

    @staticmethod
    def _authorization_id(value: str) -> str:
        if not isinstance(value, str) or not _AUTHORIZATION_ID.fullmatch(value):
            raise StateError("Approval authorization_id is invalid")
        return value

    @property
    def exists(self) -> bool:
        return self.catalog_path.is_file()

    def initialize(self, catalog: PostCardCatalogV1) -> None:
        """Freeze a catalog once and restore the derived projection."""

        self.root.mkdir(parents=True, exist_ok=True)
        for path in (
            self.mutations_dir,
            self.outbox_dir,
            self.receipts_dir,
            self.deliveries_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        with advisory_lease(self.lock_path, exclusive=True):
            if self.catalog_path.exists():
                frozen = self.load_catalog()
                if frozen.to_mapping() != catalog.to_mapping():
                    raise StateConflictError(
                        "frozen Approval catalog differs from the source projection"
                    )
            else:
                atomic_write_json(self.catalog_path, catalog.to_mapping())
            self._write_projection_locked(catalog)

    def load_catalog(self) -> PostCardCatalogV1:
        if not self.catalog_path.is_file():
            raise StateError(f"Approval catalog does not exist: {self.catalog_path}")
        return PostCardCatalogV1.from_mapping(
            read_json_object(self.catalog_path)
        )

    def _mutation_paths(self) -> list[Path]:
        if not self.mutations_dir.exists():
            return []
        return sorted(
            path
            for path in self.mutations_dir.iterdir()
            if path.is_file() and path.suffix == ".json"
        )

    def load_mutations(self) -> list[dict[str, Any]]:
        catalog = self.load_catalog()
        mutations: list[dict[str, Any]] = []
        for expected_sequence, path in enumerate(self._mutation_paths(), start=1):
            if path.is_symlink():
                raise StateError(
                    f"Approval mutation must not be a symlink: {path.name}"
                )
            row = read_json_object(path)
            try:
                mutations.append(
                    self._validate_mutation(
                        catalog,
                        row,
                        path=path,
                        expected_sequence=expected_sequence,
                    )
                )
            except ApprovalValidationError as exc:
                raise StateError(
                    f"Approval mutation contract is invalid: {path.name}: {exc}"
                ) from exc
        return mutations

    def _validate_mutation(
        self,
        catalog: PostCardCatalogV1,
        row: dict[str, Any],
        *,
        path: Path,
        expected_sequence: int,
    ) -> dict[str, Any]:
        """Close every immutable ledger fact over the frozen catalog."""

        common = {
            "schema_version",
            "sequence",
            "kind",
            "mutation_id",
            "request_id",
            "request_sha256",
            "catalog_sha256",
            "created_at",
        }
        kind = row.get("kind")
        expected_fields = (
            common | {"batch_id", "authorizations"}
            if kind == "authorize"
            else common
        )
        if (
            kind not in {"authorize", "close"}
            or set(row) != expected_fields
            or row.get("schema_version") != 1
            or row.get("sequence") != expected_sequence
        ):
            raise StateError(
                f"Approval mutation shape/sequence is invalid: {path.name}"
            )
        if (
            row.get("catalog_sha256") != catalog.catalog_sha256
            or not isinstance(row.get("created_at"), str)
            or not row["created_at"]
        ):
            raise StateError(
                f"Approval mutation catalog/time binding is invalid: {path.name}"
            )

        request_id = row.get("request_id")
        if kind == "authorize":
            raw_authorizations = row.get("authorizations")
            if (
                not isinstance(raw_authorizations, list)
                or not 1 <= len(raw_authorizations) <= 10
            ):
                raise StateError(
                    f"Approval authorize mutation has invalid batch size: "
                    f"{path.name}"
                )
            selections: list[CardSelectionV1] = []
            ordinals: list[int] = []
            for authorization in raw_authorizations:
                if not isinstance(authorization, dict) or set(
                    authorization
                ) != {
                    "authorization_id",
                    "card_id",
                    "card_sha256",
                    "ordinal",
                    "envelope",
                    "envelope_sha256",
                }:
                    raise StateError(
                        f"Approval authorization row is invalid: {path.name}"
                    )
                ordinal = authorization.get("ordinal")
                if (
                    isinstance(ordinal, bool)
                    or not isinstance(ordinal, int)
                    or ordinal < 0
                    or ordinal >= len(catalog.cards)
                ):
                    raise StateError(
                        f"Approval authorization ordinal is invalid: {path.name}"
                    )
                card = catalog.cards[ordinal]
                selection = CardSelectionV1.from_mapping(
                    {
                        "card_id": authorization.get("card_id"),
                        "card_sha256": authorization.get("card_sha256"),
                    }
                )
                if (
                    selection.card_id != card.card_id
                    or selection.card_sha256 != card.card_sha256
                ):
                    raise StateError(
                        f"Approval authorization Card binding is invalid: "
                        f"{path.name}"
                    )
                envelope = BuildAuthorizationEnvelopeV1.from_mapping(
                    authorization.get("envelope")
                )
                expected_envelope = BuildAuthorizationEnvelopeV1.create(
                    route_id=catalog.source.route_id,
                    route_contract_version=(
                        catalog.source.route_contract_version
                    ),
                    catalog_sha256=catalog.catalog_sha256,
                    handoff=card.handoff,
                )
                if (
                    envelope.to_mapping() != expected_envelope.to_mapping()
                    or authorization.get("authorization_id")
                    != envelope.authorization_id
                    or authorization.get("envelope_sha256")
                    != envelope.envelope_sha256
                ):
                    raise StateError(
                        f"Approval authorization envelope binding is invalid: "
                        f"{path.name}"
                    )
                selections.append(selection)
                ordinals.append(ordinal)
            if ordinals != sorted(set(ordinals)):
                raise StateError(
                    f"Approval authorization order is not canonical: {path.name}"
                )
            authorize_request = AuthorizeRequestV1.from_mapping(
                {
                    "schema_version": 1,
                    "request_id": request_id,
                    "catalog_sha256": catalog.catalog_sha256,
                    "cards": [
                        selection.to_mapping() for selection in selections
                    ],
                }
            )
            request_sha256 = canonical_request_sha256(
                kind="authorize",
                request_id=authorize_request.request_id,
                source_run_id=catalog.source.run_id,
                catalog_sha256=catalog.catalog_sha256,
                cards=authorize_request.cards,
            )
            expected_id = (
                f"batch-{expected_sequence:06d}-{request_sha256[:12]}"
            )
            if (
                row.get("batch_id") != expected_id
                or row.get("mutation_id") != expected_id
            ):
                raise StateError(
                    f"Approval batch identity is invalid: {path.name}"
                )
        else:
            close_request = CloseRequestV1.from_mapping(
                {
                    "schema_version": 1,
                    "request_id": request_id,
                    "catalog_sha256": catalog.catalog_sha256,
                }
            )
            request_sha256 = canonical_request_sha256(
                kind="close",
                request_id=close_request.request_id,
                source_run_id=catalog.source.run_id,
                catalog_sha256=catalog.catalog_sha256,
            )
            expected_id = (
                f"close-{expected_sequence:06d}-{request_sha256[:12]}"
            )
            if row.get("mutation_id") != expected_id:
                raise StateError(
                    f"Approval close identity is invalid: {path.name}"
                )

        if row.get("request_sha256") != request_sha256:
            raise StateError(
                f"Approval request hash is invalid: {path.name}"
            )
        expected_name = (
            f"{expected_sequence:06d}-{kind}-{request_sha256[:16]}.json"
        )
        if path.name != expected_name:
            raise StateError(
                f"Approval mutation filename is invalid: {path.name}"
            )
        return row

    def projection(self) -> dict[str, Any]:
        catalog = self.load_catalog()
        return self._project(catalog, self.load_mutations())

    def _project(
        self,
        catalog: PostCardCatalogV1,
        mutations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        authorizations: dict[str, dict[str, Any]] = {}
        batches: list[dict[str, Any]] = []
        close: dict[str, Any] | None = None
        requests: dict[str, dict[str, Any]] = {}
        for mutation in mutations:
            request_id = mutation.get("request_id")
            request_sha256 = mutation.get("request_sha256")
            if not isinstance(request_id, str) or not isinstance(
                request_sha256, str
            ):
                raise StateError("Approval mutation request identity is invalid")
            existing_request = requests.get(request_id)
            if existing_request is not None:
                raise StateError(
                    f"Approval ledger contains duplicate request_id: {request_id}"
                )
            requests[request_id] = mutation
            if mutation["kind"] == "close":
                if close is not None:
                    raise StateError("Approval ledger contains multiple close records")
                close = mutation
                continue
            if close is not None:
                raise StateError("Approval ledger authorizes after close")
            raw_authorizations = mutation.get("authorizations")
            if not isinstance(raw_authorizations, list) or not raw_authorizations:
                raise StateError("authorize mutation has no authorizations")
            if len(raw_authorizations) > 10:
                raise StateError("authorize mutation exceeds the batch limit")
            for authorization in raw_authorizations:
                if not isinstance(authorization, dict):
                    raise StateError("authorization ledger row must be an object")
                card_id = authorization.get("card_id")
                authorization_id = authorization.get("authorization_id")
                if not isinstance(card_id, str) or not isinstance(
                    authorization_id, str
                ):
                    raise StateError("authorization identity is invalid")
                if card_id in authorizations:
                    raise StateError(
                        f"Card has multiple authorizations: {card_id}"
                    )
                envelope = BuildAuthorizationEnvelopeV1.from_mapping(
                    authorization.get("envelope")
                )
                if (
                    envelope.authorization_id != authorization_id
                    or envelope.handoff.idea_card_id != card_id
                ):
                    raise StateError(
                        f"authorization envelope closure is invalid: {card_id}"
                    )
                authorizations[card_id] = authorization
            batches.append(mutation)
        return {
            "schema_version": 1,
            "source_run_id": catalog.source.run_id,
            "catalog_sha256": catalog.catalog_sha256,
            "approval_status": "closed" if close is not None else "open",
            "next_sequence": len(mutations) + 1,
            "authorized_card_ids": list(authorizations),
            "authorizations": authorizations,
            "batch_ids": [batch["batch_id"] for batch in batches],
            "close": close,
            "request_ids": list(requests),
        }

    def _write_projection_locked(self, catalog: PostCardCatalogV1) -> None:
        atomic_write_json(
            self.state_path,
            self._project(catalog, self.load_mutations()),
        )

    def rebuild_projection(self) -> dict[str, Any]:
        with advisory_lease(self.lock_path, exclusive=True):
            catalog = self.load_catalog()
            self._write_projection_locked(catalog)
            return self._project(catalog, self.load_mutations())

    def _existing_request(
        self,
        mutations: list[dict[str, Any]],
        request_id: str,
        request_sha256: str,
    ) -> dict[str, Any] | None:
        for mutation in mutations:
            if mutation.get("request_id") != request_id:
                continue
            if mutation.get("request_sha256") != request_sha256:
                raise ApprovalIdempotencyError(
                    "request_id was already used with different content"
                )
            return mutation
        return None

    def commit_authorize(
        self,
        request: AuthorizeRequestV1,
    ) -> dict[str, Any]:
        with advisory_lease(self.lock_path, exclusive=True):
            catalog = self.load_catalog()
            if request.catalog_sha256 != catalog.catalog_sha256:
                raise ApprovalStaleError(
                    "catalog hash is stale; reload the Dispatch Board"
                )
            by_id = {card.card_id: card for card in catalog.cards}
            requested: list[tuple[int, CardSelectionV1]] = []
            for selection in request.cards:
                card = by_id.get(selection.card_id)
                if (
                    card is None
                    or selection.card_sha256 != card.card_sha256
                ):
                    raise ApprovalStaleError(
                        f"Card binding is stale: {selection.card_id}"
                    )
                requested.append((card.ordinal, selection))
            requested.sort(key=lambda item: item[0])
            canonical_cards = tuple(selection for _, selection in requested)
            request_sha256 = canonical_request_sha256(
                kind="authorize",
                request_id=request.request_id,
                source_run_id=catalog.source.run_id,
                catalog_sha256=catalog.catalog_sha256,
                cards=canonical_cards,
            )
            mutations = self.load_mutations()
            existing = self._existing_request(
                mutations, request.request_id, request_sha256
            )
            if existing is not None:
                return existing
            projection = self._project(catalog, mutations)
            if projection["approval_status"] == "closed":
                raise ApprovalClosedError(
                    "Approval is closed and cannot authorize another batch"
                )
            already_authorized = set(projection["authorized_card_ids"])
            duplicates = [
                selection.card_id
                for selection in canonical_cards
                if selection.card_id in already_authorized
            ]
            if duplicates:
                raise CardAlreadyAuthorizedError(
                    "Card is already authorized: " + ", ".join(duplicates)
                )

            sequence = len(mutations) + 1
            batch_id = f"batch-{sequence:06d}-{request_sha256[:12]}"
            authorizations: list[dict[str, Any]] = []
            for ordinal, selection in requested:
                card = by_id[selection.card_id]
                envelope = BuildAuthorizationEnvelopeV1.create(
                    route_id=catalog.source.route_id,
                    route_contract_version=(
                        catalog.source.route_contract_version
                    ),
                    catalog_sha256=catalog.catalog_sha256,
                    handoff=card.handoff,
                )
                authorizations.append(
                    {
                        "authorization_id": envelope.authorization_id,
                        "card_id": card.card_id,
                        "card_sha256": card.card_sha256,
                        "ordinal": ordinal,
                        "envelope": envelope.to_mapping(),
                        "envelope_sha256": envelope.envelope_sha256,
                    }
                )
            mutation = {
                "schema_version": 1,
                "sequence": sequence,
                "kind": "authorize",
                "mutation_id": batch_id,
                "batch_id": batch_id,
                "request_id": request.request_id,
                "request_sha256": request_sha256,
                "catalog_sha256": catalog.catalog_sha256,
                "created_at": _utc_now(),
                "authorizations": authorizations,
            }
            path = (
                self.mutations_dir
                / f"{sequence:06d}-authorize-{request_sha256[:16]}.json"
            )
            if path.exists():
                raise StateConflictError(
                    f"Approval mutation path already exists: {path.name}"
                )
            atomic_write_json(path, mutation)
            self._write_projection_locked(catalog)
            return mutation

    def commit_close(self, request: CloseRequestV1) -> dict[str, Any]:
        with advisory_lease(self.lock_path, exclusive=True):
            catalog = self.load_catalog()
            if request.catalog_sha256 != catalog.catalog_sha256:
                raise ApprovalStaleError(
                    "catalog hash is stale; reload the Dispatch Board"
                )
            request_sha256 = canonical_request_sha256(
                kind="close",
                request_id=request.request_id,
                source_run_id=catalog.source.run_id,
                catalog_sha256=catalog.catalog_sha256,
            )
            mutations = self.load_mutations()
            existing = self._existing_request(
                mutations, request.request_id, request_sha256
            )
            if existing is not None:
                return existing
            projection = self._project(catalog, mutations)
            existing_close = projection["close"]
            if isinstance(existing_close, dict):
                return existing_close
            sequence = len(mutations) + 1
            mutation = {
                "schema_version": 1,
                "sequence": sequence,
                "kind": "close",
                "mutation_id": f"close-{sequence:06d}-{request_sha256[:12]}",
                "request_id": request.request_id,
                "request_sha256": request_sha256,
                "catalog_sha256": catalog.catalog_sha256,
                "created_at": _utc_now(),
            }
            path = (
                self.mutations_dir
                / f"{sequence:06d}-close-{request_sha256[:16]}.json"
            )
            if path.exists():
                raise StateConflictError(
                    f"Approval mutation path already exists: {path.name}"
                )
            atomic_write_json(path, mutation)
            self._write_projection_locked(catalog)
            return mutation

    def ensure_outboxes(self) -> int:
        created = 0
        with advisory_lease(self.lock_path, exclusive=True):
            for mutation in self.load_mutations():
                if mutation["kind"] != "authorize":
                    continue
                for authorization in mutation["authorizations"]:
                    authorization_id = authorization["authorization_id"]
                    record = {
                        "schema_version": 1,
                        "authorization_id": authorization_id,
                        "batch_id": mutation["batch_id"],
                        "batch_sequence": mutation["sequence"],
                        "catalog_ordinal": authorization["ordinal"],
                        "envelope": authorization["envelope"],
                        "envelope_sha256": authorization["envelope_sha256"],
                    }
                    path = self.outbox_dir / f"{authorization_id}.json"
                    if path.exists():
                        if read_json_object(path) != record:
                            raise StateConflictError(
                                f"Approval outbox conflicts: {authorization_id}"
                            )
                        continue
                    atomic_write_json(path, record)
                    created += 1
        return created

    def outboxes(self) -> list[dict[str, Any]]:
        rows = [
            read_json_object(path)
            for path in sorted(self.outbox_dir.glob("auth-*.json"))
            if path.is_file()
        ]
        return sorted(
            rows,
            key=lambda row: (
                row.get("batch_sequence", 0),
                row.get("catalog_ordinal", 0),
            ),
        )

    def receipt(self, authorization_id: str) -> dict[str, Any] | None:
        authorization_id = self._authorization_id(authorization_id)
        path = self.receipts_dir / f"{authorization_id}.json"
        if not path.is_file():
            return None
        if path.is_symlink():
            raise StateError(
                f"Approval receipt must not be a symlink: {path.name}"
            )
        record = read_json_object(path)
        if (
            set(record)
            != {
                "schema_version",
                "authorization_id",
                "receipt",
                "received_at",
            }
            or record.get("schema_version") != 1
            or record.get("authorization_id") != authorization_id
            or not isinstance(record.get("receipt"), dict)
            or not isinstance(record.get("received_at"), str)
            or not record["received_at"]
        ):
            raise StateError(
                f"Approval receipt record is invalid: {path.name}"
            )
        return record

    def record_receipt(
        self,
        *,
        envelope: BuildAuthorizationEnvelopeV1,
        receipt: BuildReceiptV1,
    ) -> dict[str, Any]:
        record = {
            "schema_version": 1,
            "authorization_id": envelope.authorization_id,
            "receipt": receipt.to_mapping(),
            "received_at": _utc_now(),
        }
        path = self.receipts_dir / f"{envelope.authorization_id}.json"
        with advisory_lease(self.lock_path, exclusive=True):
            if path.exists():
                existing = self.receipt(envelope.authorization_id)
                assert existing is not None
                if existing.get("receipt") != record["receipt"]:
                    raise StateConflictError(
                        "Build receipt conflicts with the persisted receipt"
                    )
                return existing
            atomic_write_json(path, record)
        return record

    def delivery(self, authorization_id: str) -> dict[str, Any] | None:
        authorization_id = self._authorization_id(authorization_id)
        path = self.deliveries_dir / f"{authorization_id}.json"
        if not path.is_file():
            return None
        if path.is_symlink():
            raise StateError(
                f"Approval delivery must not be a symlink: {path.name}"
            )
        record = read_json_object(path)
        last_error = record.get("last_error")
        valid_error = last_error is None or (
            isinstance(last_error, dict)
            and set(last_error) == {"code", "message"}
            and isinstance(last_error.get("code"), str)
            and _ERROR_CODE.fullmatch(last_error["code"]) is not None
            and isinstance(last_error.get("message"), str)
            and 0 < len(last_error["message"]) <= 500
            and "\x00" not in last_error["message"]
        )
        attempts = record.get("attempts")
        if (
            set(record)
            != {
                "schema_version",
                "authorization_id",
                "attempts",
                "last_error",
                "updated_at",
            }
            or record.get("schema_version") != 1
            or record.get("authorization_id") != authorization_id
            or isinstance(attempts, bool)
            or not isinstance(attempts, int)
            or attempts < 1
            or not valid_error
            or not isinstance(record.get("updated_at"), str)
            or not record["updated_at"]
        ):
            raise StateError(
                f"Approval delivery record is invalid: {path.name}"
            )
        return record

    def record_delivery_attempt(
        self,
        authorization_id: str,
        *,
        error_code: str | None,
        error_message: str | None,
    ) -> dict[str, Any]:
        authorization_id = self._authorization_id(authorization_id)
        if (error_code is None) != (error_message is None):
            raise StateError(
                "delivery error code and message must both be present or absent"
            )
        if error_code is not None and (
            _ERROR_CODE.fullmatch(error_code) is None
            or error_message is None
            or not 0 < len(error_message) <= 500
            or "\x00" in error_message
        ):
            raise StateError("delivery error is not browser-safe")
        path = self.deliveries_dir / f"{authorization_id}.json"
        with advisory_lease(self.lock_path, exclusive=True):
            existing = self.delivery(authorization_id) or {}
            attempts = existing.get("attempts", 0)
            if isinstance(attempts, bool) or not isinstance(attempts, int):
                raise StateError("delivery attempt projection is invalid")
            record = {
                "schema_version": 1,
                "authorization_id": authorization_id,
                "attempts": attempts + 1,
                "last_error": (
                    {
                        "code": error_code,
                        "message": error_message,
                    }
                    if error_code is not None and error_message is not None
                    else None
                ),
                "updated_at": _utc_now(),
            }
            atomic_write_json(path, record)
            return record

    def validate(self) -> list[str]:
        errors: list[str] = []
        try:
            catalog = self.load_catalog()
            mutations = self.load_mutations()
            projection = self._project(catalog, mutations)
            if self.state_path.is_file():
                persisted = read_json_object(self.state_path)
                if persisted != projection:
                    errors.append(
                        "Approval state.json differs from immutable mutations"
                    )
            expected_outboxes: dict[str, dict[str, Any]] = {}
            for mutation in mutations:
                if mutation["kind"] != "authorize":
                    continue
                for authorization in mutation["authorizations"]:
                    authorization_id = authorization["authorization_id"]
                    expected_outboxes[f"{authorization_id}.json"] = {
                        "schema_version": 1,
                        "authorization_id": authorization_id,
                        "batch_id": mutation["batch_id"],
                        "batch_sequence": mutation["sequence"],
                        "catalog_ordinal": authorization["ordinal"],
                        "envelope": authorization["envelope"],
                        "envelope_sha256": authorization["envelope_sha256"],
                    }
            actual_paths = {
                path.name: path
                for path in self.outbox_dir.glob("*.json")
                if path.is_file()
            }
            if set(actual_paths) != set(expected_outboxes):
                errors.append(
                    "Approval outbox set differs from committed authorizations"
                )
            for name in sorted(set(actual_paths) & set(expected_outboxes)):
                path = actual_paths[name]
                if path.is_symlink():
                    errors.append(f"Approval outbox must not be a symlink: {name}")
                    continue
                row = read_json_object(path)
                if row != expected_outboxes[name]:
                    errors.append(
                        f"Approval outbox differs from its mutation: {name}"
                    )
                    continue
                envelope = BuildAuthorizationEnvelopeV1.from_mapping(
                    row.get("envelope")
                )
                if row.get("authorization_id") != envelope.authorization_id:
                    errors.append(
                        "Approval outbox authorization binding is invalid"
                    )
                if row.get("envelope_sha256") != sha256_json(
                    envelope.to_mapping()
                ):
                    errors.append(
                        f"Approval outbox hash is invalid: "
                        f"{envelope.authorization_id}"
                    )
                receipt = self.receipt(envelope.authorization_id)
                if receipt is not None:
                    BuildReceiptV1.from_mapping(
                        receipt.get("receipt"),
                        envelope=envelope,
                    )
            expected_names = set(expected_outboxes)
            receipt_paths = {
                path.name: path
                for path in self.receipts_dir.glob("*.json")
                if path.is_file()
            }
            extra_receipts = sorted(set(receipt_paths) - expected_names)
            if extra_receipts:
                errors.append(
                    "Approval receipt set contains unknown authorizations: "
                    + ", ".join(extra_receipts)
                )
            delivery_paths = {
                path.name: path
                for path in self.deliveries_dir.glob("*.json")
                if path.is_file()
            }
            extra_deliveries = sorted(set(delivery_paths) - expected_names)
            if extra_deliveries:
                errors.append(
                    "Approval delivery set contains unknown authorizations: "
                    + ", ".join(extra_deliveries)
                )
            for name in sorted(set(delivery_paths) & expected_names):
                self.delivery(name.removesuffix(".json"))
        except (OSError, StateError, ValueError) as exc:
            errors.append(str(exc))
        return errors


__all__ = ["ApprovalStore"]
