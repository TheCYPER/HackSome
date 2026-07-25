"""Strict HTTP, ledger, adapter, and status DTOs for Build Approval."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from hacksome.contracts.post_card.contracts import (
    BuildHandoffV1,
    PostCardContractError,
    build_identity_sha256,
    stable_authorization_id,
    stable_team_id,
)
from hacksome.core.state import normalize_json, sha256_json


_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_AUTHORIZATION_ID = re.compile(r"^auth-[0-9a-f]{32}$")
_TEAM_ID = re.compile(r"^team-[0-9a-f]{24}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROUTE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_BUILD_OBSERVED_STATES = frozenset(
    {"queued", "bootstrapping", "starting", "active", "error"}
)
_TEAM_OBSERVED_STATES = frozenset(
    {
        "queued",
        "bootstrapping",
        "starting",
        "active",
        "pausing",
        "paused",
        "resuming",
        "error",
    }
)
_DESIRED_STATES = frozenset({"active", "paused"})


class ApprovalError(RuntimeError):
    """Base class with a stable browser-safe error taxonomy."""

    code = "approval_error"
    http_status = 400


class ApprovalValidationError(ApprovalError):
    code = "invalid_request"
    http_status = 422


class ApprovalConflictError(ApprovalError):
    code = "approval_conflict"
    http_status = 409


class ApprovalClosedError(ApprovalConflictError):
    code = "approval_closed"


class ApprovalStaleError(ApprovalConflictError):
    code = "stale_catalog"


class ApprovalIdempotencyError(ApprovalConflictError):
    code = "idempotency_conflict"


class CardAlreadyAuthorizedError(ApprovalConflictError):
    code = "card_already_authorized"


class SourceIntegrityError(ApprovalConflictError):
    code = "source_integrity_error"


class BuildAdapterError(ApprovalError):
    code = "build_adapter_error"
    http_status = 502

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


def _exact_object(
    value: Any,
    *,
    fields: frozenset[str],
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ApprovalValidationError(f"{label} must be an object")
    actual = set(value)
    if actual != fields:
        missing = sorted(fields - actual)
        unknown = sorted(actual - fields)
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown fields: {', '.join(unknown)}")
        raise ApprovalValidationError(f"{label} has " + "; ".join(details))
    return value


def _request_id(value: Any) -> str:
    if not isinstance(value, str) or not _REQUEST_ID.fullmatch(value):
        raise ApprovalValidationError(
            "request_id must be 1-128 bounded safe characters"
        )
    return value


def _sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ApprovalValidationError(f"{label} must be a lowercase SHA-256")
    return value


def _nonempty(value: Any, *, label: str, max_chars: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or len(value) > max_chars
    ):
        raise ApprovalValidationError(f"{label} must be bounded non-empty text")
    return value


@dataclass(frozen=True, slots=True)
class CardSelectionV1:
    card_id: str
    card_sha256: str

    @classmethod
    def from_mapping(cls, value: Any) -> "CardSelectionV1":
        raw = _exact_object(
            value,
            fields=frozenset({"card_id", "card_sha256"}),
            label="Card selection",
        )
        return cls(
            card_id=_nonempty(raw["card_id"], label="card_id"),
            card_sha256=_sha256(raw["card_sha256"], label="card_sha256"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "card_sha256": self.card_sha256,
        }


@dataclass(frozen=True, slots=True)
class AuthorizeRequestV1:
    schema_version: int
    request_id: str
    catalog_sha256: str
    cards: tuple[CardSelectionV1, ...]

    @classmethod
    def from_mapping(cls, value: Any) -> "AuthorizeRequestV1":
        raw = _exact_object(
            value,
            fields=frozenset(
                {"schema_version", "request_id", "catalog_sha256", "cards"}
            ),
            label="authorize request",
        )
        cards_value = raw["cards"]
        if not isinstance(cards_value, list):
            raise ApprovalValidationError("authorize cards must be an array")
        if not 1 <= len(cards_value) <= 10:
            raise ApprovalValidationError(
                "authorize_batch requires between 1 and 10 Cards"
            )
        cards = tuple(CardSelectionV1.from_mapping(card) for card in cards_value)
        ids = [card.card_id for card in cards]
        if len(ids) != len(set(ids)):
            raise ApprovalValidationError(
                "authorize request contains duplicate Card IDs"
            )
        if raw["schema_version"] != 1:
            raise ApprovalValidationError(
                f"unsupported authorize schema version: {raw['schema_version']!r}"
            )
        return cls(
            schema_version=1,
            request_id=_request_id(raw["request_id"]),
            catalog_sha256=_sha256(
                raw["catalog_sha256"], label="catalog_sha256"
            ),
            cards=cards,
        )


@dataclass(frozen=True, slots=True)
class CloseRequestV1:
    schema_version: int
    request_id: str
    catalog_sha256: str

    @classmethod
    def from_mapping(cls, value: Any) -> "CloseRequestV1":
        raw = _exact_object(
            value,
            fields=frozenset(
                {"schema_version", "request_id", "catalog_sha256"}
            ),
            label="close request",
        )
        if raw["schema_version"] != 1:
            raise ApprovalValidationError(
                f"unsupported close schema version: {raw['schema_version']!r}"
            )
        return cls(
            schema_version=1,
            request_id=_request_id(raw["request_id"]),
            catalog_sha256=_sha256(
                raw["catalog_sha256"], label="catalog_sha256"
            ),
        )


@dataclass(frozen=True, slots=True)
class BuildAuthorizationEnvelopeV1:
    schema_version: int
    authorization_id: str
    route_id: str
    route_contract_version: str
    catalog_sha256: str
    handoff: BuildHandoffV1

    @classmethod
    def from_mapping(cls, value: Any) -> "BuildAuthorizationEnvelopeV1":
        raw = _exact_object(
            value,
            fields=frozenset(
                {"schema_version", "authorization_id", "source", "handoff"}
            ),
            label="Build authorization envelope",
        )
        source = _exact_object(
            raw["source"],
            fields=frozenset(
                {"route_id", "route_contract_version", "catalog_sha256"}
            ),
            label="Build authorization source",
        )
        if raw["schema_version"] != 1:
            raise ApprovalValidationError(
                "unsupported Build authorization envelope version"
            )
        authorization_id = raw["authorization_id"]
        if (
            not isinstance(authorization_id, str)
            or not _AUTHORIZATION_ID.fullmatch(authorization_id)
        ):
            raise ApprovalValidationError("authorization_id is invalid")
        route_id = source["route_id"]
        if not isinstance(route_id, str) or not _ROUTE.fullmatch(route_id):
            raise ApprovalValidationError("source route_id is invalid")
        route_version = _nonempty(
            source["route_contract_version"],
            label="source route_contract_version",
            max_chars=64,
        )
        try:
            handoff = BuildHandoffV1.from_mapping(raw["handoff"])
        except PostCardContractError as exc:
            raise ApprovalValidationError(str(exc)) from exc
        if authorization_id != stable_authorization_id(handoff):
            raise ApprovalValidationError(
                "authorization_id does not match the handoff identity"
            )
        return cls(
            schema_version=1,
            authorization_id=authorization_id,
            route_id=route_id,
            route_contract_version=route_version,
            catalog_sha256=_sha256(
                source["catalog_sha256"], label="source catalog_sha256"
            ),
            handoff=handoff,
        )

    @classmethod
    def create(
        cls,
        *,
        route_id: str,
        route_contract_version: str,
        catalog_sha256: str,
        handoff: BuildHandoffV1,
    ) -> "BuildAuthorizationEnvelopeV1":
        value = {
            "schema_version": 1,
            "authorization_id": stable_authorization_id(handoff),
            "source": {
                "route_id": route_id,
                "route_contract_version": route_contract_version,
                "catalog_sha256": catalog_sha256,
            },
            "handoff": handoff.to_mapping(),
        }
        return cls.from_mapping(value)

    @property
    def identity_sha256(self) -> str:
        return build_identity_sha256(self.handoff)

    @property
    def envelope_sha256(self) -> str:
        return sha256_json(self.to_mapping())

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authorization_id": self.authorization_id,
            "source": {
                "route_id": self.route_id,
                "route_contract_version": self.route_contract_version,
                "catalog_sha256": self.catalog_sha256,
            },
            "handoff": self.handoff.to_mapping(),
        }


@dataclass(frozen=True, slots=True)
class BuildReceiptV1:
    schema_version: int
    authorization_id: str
    team_id: str
    identity_sha256: str
    observed_state: str

    @classmethod
    def from_mapping(
        cls,
        value: Any,
        *,
        envelope: BuildAuthorizationEnvelopeV1 | None = None,
    ) -> "BuildReceiptV1":
        raw = _exact_object(
            value,
            fields=frozenset(
                {
                    "schema_version",
                    "authorization_id",
                    "team_id",
                    "identity_sha256",
                    "observed_state",
                }
            ),
            label="Build receipt",
        )
        if raw["schema_version"] != 1:
            raise ApprovalValidationError("unsupported Build receipt version")
        authorization_id = raw["authorization_id"]
        team_id = raw["team_id"]
        identity = raw["identity_sha256"]
        observed = raw["observed_state"]
        if (
            not isinstance(authorization_id, str)
            or not _AUTHORIZATION_ID.fullmatch(authorization_id)
            or not isinstance(team_id, str)
            or not _TEAM_ID.fullmatch(team_id)
            or not isinstance(identity, str)
            or not _SHA256.fullmatch(identity)
            or observed not in _BUILD_OBSERVED_STATES
        ):
            raise ApprovalValidationError("Build receipt fields are invalid")
        receipt = cls(
            schema_version=1,
            authorization_id=authorization_id,
            team_id=team_id,
            identity_sha256=identity,
            observed_state=observed,
        )
        if envelope is not None and (
            receipt.authorization_id != envelope.authorization_id
            or receipt.identity_sha256 != envelope.identity_sha256
            or receipt.team_id != stable_team_id(envelope.handoff)
        ):
            raise ApprovalValidationError(
                "Build receipt does not close over the authorization envelope"
            )
        return receipt

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authorization_id": self.authorization_id,
            "team_id": self.team_id,
            "identity_sha256": self.identity_sha256,
            "observed_state": self.observed_state,
        }


@dataclass(frozen=True, slots=True)
class BuildTeamStatusV1:
    team_id: str
    desired_state: str
    observed_state: str
    queue_position: int | None

    @classmethod
    def from_mapping(cls, value: Any) -> "BuildTeamStatusV1":
        raw = _exact_object(
            value,
            fields=frozenset(
                {
                    "team_id",
                    "desired_state",
                    "observed_state",
                    "queue_position",
                }
            ),
            label="Build Team status",
        )
        team_id = raw["team_id"]
        desired = raw["desired_state"]
        observed = raw["observed_state"]
        queue_position = raw["queue_position"]
        if not isinstance(team_id, str) or not _TEAM_ID.fullmatch(team_id):
            raise ApprovalValidationError("Build Team status team_id is invalid")
        if desired not in _DESIRED_STATES:
            raise ApprovalValidationError(
                "Build Team desired_state is invalid"
            )
        if observed not in _TEAM_OBSERVED_STATES:
            raise ApprovalValidationError(
                "Build Team observed_state is invalid"
            )
        if queue_position is not None and (
            isinstance(queue_position, bool)
            or not isinstance(queue_position, int)
            or queue_position < 1
        ):
            raise ApprovalValidationError(
                "Build Team queue_position must be positive or null"
            )
        return cls(
            team_id=team_id,
            desired_state=desired,
            observed_state=observed,
            queue_position=queue_position,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "desired_state": self.desired_state,
            "observed_state": self.observed_state,
            "queue_position": self.queue_position,
        }


@dataclass(frozen=True, slots=True)
class BuildStatusSnapshotV1:
    schema_version: int
    max_active_teams: int
    teams: tuple[BuildTeamStatusV1, ...]

    @classmethod
    def from_mapping(cls, value: Any) -> "BuildStatusSnapshotV1":
        raw = _exact_object(
            value,
            fields=frozenset(
                {"schema_version", "max_active_teams", "teams"}
            ),
            label="Build status snapshot",
        )
        max_active = raw["max_active_teams"]
        teams_value = raw["teams"]
        if raw["schema_version"] != 1:
            raise ApprovalValidationError("unsupported Build status version")
        if (
            isinstance(max_active, bool)
            or not isinstance(max_active, int)
            or max_active < 1
            or max_active > 100
        ):
            raise ApprovalValidationError("max_active_teams is invalid")
        if not isinstance(teams_value, list):
            raise ApprovalValidationError("Build status teams must be an array")
        teams = tuple(BuildTeamStatusV1.from_mapping(team) for team in teams_value)
        ids = [team.team_id for team in teams]
        if len(ids) != len(set(ids)):
            raise ApprovalValidationError(
                "Build status contains duplicate Team IDs"
            )
        return cls(
            schema_version=1,
            max_active_teams=max_active,
            teams=teams,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "max_active_teams": self.max_active_teams,
            "teams": [team.to_mapping() for team in self.teams],
        }


def canonical_request_sha256(
    *,
    kind: str,
    request_id: str,
    source_run_id: str,
    catalog_sha256: str,
    cards: tuple[CardSelectionV1, ...] = (),
) -> str:
    value = {
        "kind": kind,
        "request_id": request_id,
        "source_run_id": source_run_id,
        "catalog_sha256": catalog_sha256,
        "cards": [card.to_mapping() for card in cards],
    }
    normalized = normalize_json(value, label="Approval request identity")
    return sha256_json(normalized)


__all__ = [
    "ApprovalClosedError",
    "ApprovalConflictError",
    "ApprovalError",
    "ApprovalIdempotencyError",
    "ApprovalStaleError",
    "ApprovalValidationError",
    "AuthorizeRequestV1",
    "BuildAdapterError",
    "BuildAuthorizationEnvelopeV1",
    "BuildReceiptV1",
    "BuildStatusSnapshotV1",
    "BuildTeamStatusV1",
    "CardAlreadyAuthorizedError",
    "CardSelectionV1",
    "CloseRequestV1",
    "SourceIntegrityError",
    "canonical_request_sha256",
]
