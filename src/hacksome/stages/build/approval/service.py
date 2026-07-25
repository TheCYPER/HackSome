"""Approval use cases and the sole joined status projection owner."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from hacksome.stages.build.approval.build_adapter import BuildControlAdapter
from hacksome.stages.build.approval.contracts import (
    ApprovalValidationError,
    AuthorizeRequestV1,
    BuildAdapterError,
    BuildAuthorizationEnvelopeV1,
    BuildReceiptV1,
    BuildStatusSnapshotV1,
    CloseRequestV1,
    SourceIntegrityError,
)
from hacksome.stages.build.approval.store import ApprovalStore
from hacksome.contracts.post_card.catalog import (
    PostCardCatalogError,
    default_approval_root,
    project_post_card_catalog,
)
from hacksome.contracts.post_card.contracts import PostCardCatalogV1
from hacksome.core.state import StateError


_STARTING_STATES = frozenset(
    {"bootstrapping", "starting", "resuming", "pausing"}
)
_SOURCE_INTEGRITY_MESSAGE = (
    "source run no longer matches the frozen Approval catalog"
)
_DELIVERY_ERROR_MESSAGE = (
    "Build handoff failed; retry pending handoffs or inspect with the CLI"
)


class ApprovalService:
    """Coordinate source integrity, durable intent, delivery, and status."""

    def __init__(
        self,
        *,
        run_dir: Path,
        store: ApprovalStore,
        catalog: PostCardCatalogV1,
        build_adapter: BuildControlAdapter | None,
        source_integrity_error: str | None,
        verify_source_on_mutation: bool = False,
    ) -> None:
        self.run_dir = run_dir
        self.store = store
        self.catalog = catalog
        self.build_adapter = build_adapter
        self.source_integrity_error = source_integrity_error
        self.verify_source_on_mutation = verify_source_on_mutation

    @classmethod
    def open(
        cls,
        run_dir: str | Path,
        *,
        approval_root: str | Path | None = None,
        build_adapter: BuildControlAdapter | None = None,
    ) -> "ApprovalService":
        source_run = Path(run_dir).expanduser().resolve()
        root = (
            Path(approval_root).expanduser().resolve()
            if approval_root is not None
            else default_approval_root(source_run)
        )
        store = ApprovalStore(root)
        if not store.exists:
            catalog = project_post_card_catalog(source_run)
            store.initialize(catalog)
            integrity_error = None
        else:
            catalog = store.load_catalog()
            integrity_error = None
            try:
                current = project_post_card_catalog(source_run)
                if current.to_mapping() != catalog.to_mapping():
                    integrity_error = _SOURCE_INTEGRITY_MESSAGE
            except (OSError, StateError, PostCardCatalogError):
                integrity_error = _SOURCE_INTEGRITY_MESSAGE
        return cls(
            run_dir=source_run,
            store=store,
            catalog=catalog,
            build_adapter=build_adapter,
            source_integrity_error=integrity_error,
            verify_source_on_mutation=True,
        )

    def _verify_source_integrity(self) -> None:
        """Recheck the immutable source immediately before a new mutation."""

        if self.source_integrity_error is not None:
            raise SourceIntegrityError(self.source_integrity_error)
        if not self.verify_source_on_mutation:
            return
        try:
            current = project_post_card_catalog(self.run_dir)
            if current.to_mapping() != self.catalog.to_mapping():
                raise PostCardCatalogError(_SOURCE_INTEGRITY_MESSAGE)
        except (OSError, StateError, PostCardCatalogError) as exc:
            self.source_integrity_error = _SOURCE_INTEGRITY_MESSAGE
            raise SourceIntegrityError(self.source_integrity_error) from exc

    def authorize(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self._verify_source_integrity()
        request = AuthorizeRequestV1.from_mapping(payload)
        mutation = self.store.commit_authorize(request)
        self.store.ensure_outboxes()
        return {
            "schema_version": 1,
            "status": "authorized",
            "batch_id": mutation["batch_id"],
            "authorizations": [
                {
                    "authorization_id": row["authorization_id"],
                    "card_id": row["card_id"],
                    "card_sha256": row["card_sha256"],
                }
                for row in mutation["authorizations"]
            ],
        }

    def close(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self._verify_source_integrity()
        request = CloseRequestV1.from_mapping(payload)
        mutation = self.store.commit_close(request)
        return {
            "schema_version": 1,
            "status": "closed",
            "close_id": mutation["mutation_id"],
        }

    def reconcile(self) -> dict[str, Any]:
        self.store.ensure_outboxes()
        if self.build_adapter is not None:
            for outbox in self.store.outboxes():
                authorization_id = outbox["authorization_id"]
                if self.store.receipt(authorization_id) is not None:
                    continue
                envelope = BuildAuthorizationEnvelopeV1.from_mapping(
                    outbox["envelope"]
                )
                try:
                    receipt = self.build_adapter.authorize(envelope)
                except BuildAdapterError as exc:
                    self.store.record_delivery_attempt(
                        authorization_id,
                        error_code=exc.code,
                        error_message=str(exc),
                    )
                    continue
                try:
                    receipt = BuildReceiptV1.from_mapping(
                        receipt.to_mapping(),
                        envelope=envelope,
                    )
                except ApprovalValidationError:
                    self.store.record_delivery_attempt(
                        authorization_id,
                        error_code="build_receipt_mismatch",
                        error_message=(
                            "Build adapter returned a mismatched receipt"
                        ),
                    )
                    continue
                self.store.record_delivery_attempt(
                    authorization_id,
                    error_code=None,
                    error_message=None,
                )
                self.store.record_receipt(
                    envelope=envelope,
                    receipt=receipt,
                )
            try:
                self.build_adapter.reconcile()
            except BuildAdapterError:
                # Per-card delivery facts remain authoritative and retryable.
                pass
        return self.snapshot()

    def _build_status(self) -> BuildStatusSnapshotV1 | None:
        if self.build_adapter is None:
            return None
        try:
            return self.build_adapter.status()
        except BuildAdapterError:
            return None

    def snapshot(self) -> dict[str, Any]:
        projection = self.store.projection()
        build_status = self._build_status()
        status_by_team = (
            {team.team_id: team for team in build_status.teams}
            if build_status is not None
            else {}
        )
        max_active = (
            build_status.max_active_teams
            if build_status is not None
            else self._configured_active_cap()
        )
        cards: list[dict[str, Any]] = []
        for card in self.catalog.cards:
            authorization = projection["authorizations"].get(card.card_id)
            team_id: str | None = None
            queue_position: int | None = None
            attempts = 0
            error: dict[str, str] | None = None
            if authorization is None:
                status = (
                    "not_built"
                    if projection["approval_status"] == "closed"
                    else "available"
                )
            else:
                authorization_id = authorization["authorization_id"]
                projection_error: dict[str, str] | None = None
                try:
                    receipt_record = self.store.receipt(authorization_id)
                except StateError:
                    receipt_record = None
                    projection_error = {
                        "code": "receipt_integrity_error",
                        "message": "persisted Build receipt is invalid",
                    }
                try:
                    delivery = self.store.delivery(authorization_id)
                except StateError:
                    delivery = None
                    projection_error = {
                        "code": "delivery_integrity_error",
                        "message": "persisted Build delivery state is invalid",
                    }
                if isinstance(delivery, dict):
                    raw_attempts = delivery.get("attempts")
                    attempts = raw_attempts if isinstance(raw_attempts, int) else 0
                    raw_error = delivery.get("last_error")
                    if isinstance(raw_error, dict):
                        code = raw_error.get("code")
                        message = raw_error.get("message")
                        if isinstance(code, str) and isinstance(message, str):
                            error = {
                                "code": code,
                                "message": _DELIVERY_ERROR_MESSAGE,
                            }
                if projection_error is not None:
                    status = "error"
                    error = projection_error
                elif receipt_record is None:
                    status = "error" if error is not None else "authorized"
                else:
                    try:
                        receipt = BuildReceiptV1.from_mapping(
                            receipt_record.get("receipt"),
                            envelope=BuildAuthorizationEnvelopeV1.from_mapping(
                                authorization["envelope"]
                            ),
                        )
                    except ApprovalValidationError:
                        status = "error"
                        error = {
                            "code": "receipt_integrity_error",
                            "message": "persisted Build receipt is invalid",
                        }
                    else:
                        error = None
                        team_id = receipt.team_id
                        team_status = status_by_team.get(team_id)
                        observed = (
                            team_status.observed_state
                            if team_status is not None
                            else receipt.observed_state
                        )
                        if team_status is not None:
                            queue_position = team_status.queue_position
                        if observed == "queued":
                            status = "queued"
                        elif observed in _STARTING_STATES:
                            status = "starting"
                        elif observed == "active":
                            status = "active"
                        elif observed == "paused":
                            status = "paused"
                        elif observed == "error":
                            status = "error"
                        else:
                            status = "starting"
            cards.append(
                {
                    "ordinal": card.ordinal,
                    "card_id": card.card_id,
                    "title": card.title,
                    "card_sha256": card.card_sha256,
                    "route_handoff_ref": card.route_handoff_ref,
                    "status": status,
                    "authorization_id": (
                        authorization["authorization_id"]
                        if isinstance(authorization, dict)
                        else None
                    ),
                    "team_id": team_id,
                    "queue_position": queue_position,
                    "delivery_attempts": attempts,
                    "error": error,
                }
            )
        return {
            "schema_version": 1,
            "run_id": self.catalog.source.run_id,
            "route_id": self.catalog.source.route_id,
            "route_contract_version": (
                self.catalog.source.route_contract_version
            ),
            "catalog_sha256": self.catalog.catalog_sha256,
            "approval_status": projection["approval_status"],
            "source_integrity_error": self.source_integrity_error,
            "max_active_teams": max_active,
            "cards": cards,
        }

    def _configured_active_cap(self) -> int:
        value = getattr(self.build_adapter, "max_active_teams", 2)
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
            or value > 100
        ):
            return 2
        return value

    def card_detail(self, ordinal: int) -> dict[str, Any]:
        if (
            isinstance(ordinal, bool)
            or not isinstance(ordinal, int)
            or ordinal < 0
            or ordinal >= len(self.catalog.cards)
        ):
            raise ApprovalValidationError("Card ordinal is out of range")
        card = self.catalog.cards[ordinal]
        status = self.snapshot()["cards"][ordinal]
        return {
            "schema_version": 1,
            "ordinal": card.ordinal,
            "card_id": card.card_id,
            "title": card.title,
            "card_sha256": card.card_sha256,
            "card_markdown": card.card_markdown,
            "source_artifact_ref": card.source_artifact_ref.to_mapping(),
            "route_handoff_ref": card.route_handoff_ref,
            "status": status["status"],
            "team_id": status["team_id"],
        }

    def validate(self) -> list[str]:
        errors = self.store.validate()
        if self.source_integrity_error is not None:
            errors.append(self.source_integrity_error)
        return errors


__all__ = ["ApprovalService"]
