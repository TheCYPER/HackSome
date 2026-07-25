"""Route registry and deterministic post-card catalog projection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Protocol

from hacksome.artifacts import ArtifactError, title_of
from hacksome.creative.contracts import (
    CREATIVE_CONTRACT_VERSION,
    LEGACY_CREATIVE_CONTRACT_VERSION,
    SUPPORTED_CREATIVE_CONTRACT_VERSIONS,
)
from hacksome.hub import RUN_SCHEMA_VERSION, RunHub
from hacksome.post_card.contracts import (
    ArtifactRefV1,
    BuildHandoffV1,
    CatalogSourceV1,
    PostCardCandidateV1,
    PostCardCatalogV1,
    PostCardContractError,
)
from hacksome.routes import validate_run
from hacksome.state import StateError


class PostCardCatalogError(StateError):
    """A source run cannot safely expose the shared post-card contract."""


class PostCardProvider(Protocol):
    route_id: str
    contract_version: str

    def project(
        self,
        hub: RunHub,
        state: Mapping[str, Any],
    ) -> PostCardCatalogV1: ...


def _artifact_ref(
    artifacts: Mapping[str, Any],
    artifact_id: str,
    *,
    expected_type: str,
) -> ArtifactRefV1:
    record = artifacts.get(artifact_id)
    if not isinstance(record, dict):
        raise PostCardCatalogError(f"artifact is not registered: {artifact_id}")
    artifact_type = record.get("artifact_type")
    relative_path = record.get("path")
    if artifact_type != expected_type or not isinstance(relative_path, str):
        raise PostCardCatalogError(
            f"artifact binding is invalid: {artifact_id}"
        )
    return ArtifactRefV1(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        relative_path=relative_path,
    )


def _artifacts(state: Mapping[str, Any]) -> Mapping[str, Any]:
    artifacts = state.get("artifacts")
    if not isinstance(artifacts, dict):
        raise PostCardCatalogError("run artifacts must be an object")
    return artifacts


def _source(state: Mapping[str, Any]) -> CatalogSourceV1:
    route = state.get("route")
    run_id = state.get("run_id")
    if not isinstance(route, dict) or not isinstance(run_id, str):
        raise PostCardCatalogError("run has no valid source identity")
    route_id = route.get("id")
    version = route.get("contract_version")
    if not isinstance(route_id, str) or not isinstance(version, str):
        raise PostCardCatalogError("run route identity is invalid")
    return CatalogSourceV1(
        route_id=route_id,
        route_contract_version=version,
        run_id=run_id,
    )


class UsefulPostCardProvider:
    route_id = "useful"
    contract_version = "1"

    def project(
        self,
        hub: RunHub,
        state: Mapping[str, Any],
    ) -> PostCardCatalogV1:
        artifacts = _artifacts(state)
        raw_card_ids = state.get("idea_card_ids")
        if not isinstance(raw_card_ids, list) or not all(
            isinstance(value, str) for value in raw_card_ids
        ):
            raise PostCardCatalogError("Useful idea_card_ids must be strings")
        card_ids = tuple(raw_card_ids)
        if len(card_ids) != len(set(card_ids)):
            raise PostCardCatalogError("Useful idea_card_ids contains duplicates")
        registered_cards = {
            str(artifact_id)
            for artifact_id, record in artifacts.items()
            if isinstance(record, dict)
            and record.get("artifact_type") == "idea_card"
        }
        if registered_cards != set(card_ids):
            raise PostCardCatalogError(
                "Useful Idea Card list does not close over registered cards"
            )

        challenge_ref = _artifact_ref(
            artifacts,
            "challenge-brief",
            expected_type="challenge_brief",
        )
        index_ref = _artifact_ref(
            artifacts,
            "idea-card-index",
            expected_type="idea_card_index",
        )
        index_record = artifacts[index_ref.artifact_id]
        if index_record.get("source_refs") != list(card_ids):
            raise PostCardCatalogError(
                "Useful Idea Card index does not bind the authoritative order"
            )
        challenge = hub.read_artifact(challenge_ref.artifact_id)
        hub.read_artifact(index_ref.artifact_id)

        source = _source(state)
        cards: list[PostCardCandidateV1] = []
        for ordinal, card_id in enumerate(card_ids):
            artifact_ref = _artifact_ref(
                artifacts,
                card_id,
                expected_type="idea_card",
            )
            markdown = hub.read_artifact(card_id)
            record = artifacts[card_id]
            digest = record.get("sha256")
            if not isinstance(digest, str):
                raise PostCardCatalogError(
                    f"Useful Idea Card has no hash: {card_id}"
                )
            try:
                title = title_of(markdown)
            except ArtifactError as exc:
                raise PostCardCatalogError(str(exc)) from exc
            handoff = BuildHandoffV1(
                source_run_id=source.run_id,
                idea_card_id=card_id,
                idea_card_sha256=digest,
                challenge_markdown=challenge,
                initial_idea_card_markdown=markdown,
            )
            cards.append(
                PostCardCandidateV1(
                    ordinal=ordinal,
                    card_id=card_id,
                    title=title,
                    card_sha256=digest,
                    card_markdown=markdown,
                    source_artifact_ref=artifact_ref,
                    route_handoff_ref=None,
                    handoff=handoff,
                )
            )
        return PostCardCatalogV1.build(source=source, cards=tuple(cards))


class CreativePostCardProvider:
    route_id = "creative"

    def __init__(
        self,
        contract_version: str = CREATIVE_CONTRACT_VERSION,
    ) -> None:
        if contract_version not in SUPPORTED_CREATIVE_CONTRACT_VERSIONS:
            raise ValueError(
                "unsupported Creative post-card contract version: "
                f"{contract_version!r}"
            )
        self.contract_version = contract_version

    def project(
        self,
        hub: RunHub,
        state: Mapping[str, Any],
    ) -> PostCardCatalogV1:
        artifacts = _artifacts(state)
        try:
            report = json.loads(hub.read_artifact("creative-idea-report-json"))
        except (json.JSONDecodeError, UnicodeError, StateError) as exc:
            raise PostCardCatalogError(
                f"Creative success report cannot be loaded: {exc}"
            ) from exc
        if not isinstance(report, dict):
            raise PostCardCatalogError("Creative success report must be an object")
        raw_card_ids = report.get("final_idea_card_ids")
        raw_handoff_ids = report.get("handoff_refs")
        if (
            not isinstance(raw_card_ids, list)
            or not all(isinstance(value, str) for value in raw_card_ids)
            or not isinstance(raw_handoff_ids, list)
            or not all(isinstance(value, str) for value in raw_handoff_ids)
            or len(raw_card_ids) != len(raw_handoff_ids)
        ):
            raise PostCardCatalogError(
                "Creative report Card/handoff lists are invalid"
            )
        if len(raw_card_ids) != len(set(raw_card_ids)):
            raise PostCardCatalogError(
                "Creative success report contains duplicate Cards"
            )

        source = _source(state)
        cards: list[PostCardCandidateV1] = []
        for ordinal, (card_id, handoff_id) in enumerate(
            zip(raw_card_ids, raw_handoff_ids, strict=True)
        ):
            artifact_ref = _artifact_ref(
                artifacts,
                card_id,
                expected_type="creative_idea_card",
            )
            _artifact_ref(
                artifacts,
                handoff_id,
                expected_type="creative_build_handoff",
            )
            markdown = hub.read_artifact(card_id)
            record = artifacts[card_id]
            digest = record.get("sha256")
            if not isinstance(digest, str):
                raise PostCardCatalogError(
                    f"Creative Idea Card has no hash: {card_id}"
                )
            try:
                raw_handoff = json.loads(hub.read_artifact(handoff_id))
                handoff = BuildHandoffV1.from_mapping(raw_handoff)
                title = title_of(markdown)
            except (
                ArtifactError,
                json.JSONDecodeError,
                PostCardContractError,
            ) as exc:
                raise PostCardCatalogError(str(exc)) from exc
            cards.append(
                PostCardCandidateV1(
                    ordinal=ordinal,
                    card_id=card_id,
                    title=title,
                    card_sha256=digest,
                    card_markdown=markdown,
                    source_artifact_ref=artifact_ref,
                    route_handoff_ref=handoff_id,
                    handoff=handoff,
                )
            )
        return PostCardCatalogV1.build(source=source, cards=tuple(cards))


_PROVIDERS: dict[tuple[str, str], PostCardProvider] = {
    ("useful", "1"): UsefulPostCardProvider(),
    (
        "creative",
        LEGACY_CREATIVE_CONTRACT_VERSION,
    ): CreativePostCardProvider(LEGACY_CREATIVE_CONTRACT_VERSION),
    (
        "creative",
        CREATIVE_CONTRACT_VERSION,
    ): CreativePostCardProvider(CREATIVE_CONTRACT_VERSION),
}


def register_post_card_provider(
    provider: PostCardProvider,
    *,
    replace: bool = False,
) -> None:
    key = (provider.route_id, provider.contract_version)
    if key in _PROVIDERS and not replace:
        raise PostCardCatalogError(
            f"post-card provider is already registered: {key[0]}/{key[1]}"
        )
    _PROVIDERS[key] = provider


def project_post_card_catalog(
    run_dir: str | Path,
) -> PostCardCatalogV1:
    """Project a completed, offline-valid v2 run without mutating it."""

    hub = RunHub(run_dir)
    state = hub.load_state()
    if state.get("schema_version") != RUN_SCHEMA_VERSION:
        raise PostCardCatalogError(
            "Build Approval supports only completed run schema v2"
        )
    if state.get("status") != "completed":
        raise PostCardCatalogError(
            "Build Approval requires a completed source run"
        )
    errors = validate_run(hub.run_dir)
    if errors:
        raise PostCardCatalogError(
            "source run failed offline validation: " + "; ".join(errors)
        )
    route = state.get("route")
    if not isinstance(route, dict):
        raise PostCardCatalogError("source run has no route metadata")
    key = (route.get("id"), route.get("contract_version"))
    if not all(isinstance(value, str) for value in key):
        raise PostCardCatalogError("source route identity is invalid")
    provider = _PROVIDERS.get((str(key[0]), str(key[1])))
    if provider is None:
        raise PostCardCatalogError(
            f"unsupported post-card route contract: {key[0]}/{key[1]}"
        )
    try:
        return provider.project(hub, state)
    except (OSError, UnicodeError, PostCardContractError) as exc:
        raise PostCardCatalogError(str(exc)) from exc


def default_approval_root(run_dir: str | Path) -> Path:
    hub = RunHub(run_dir)
    return (
        hub.run_dir.parent
        / ".hacksome"
        / "approvals"
        / hub.run_id
    )


__all__ = [
    "CreativePostCardProvider",
    "PostCardCatalogError",
    "PostCardProvider",
    "UsefulPostCardProvider",
    "default_approval_root",
    "project_post_card_catalog",
    "register_post_card_provider",
]
