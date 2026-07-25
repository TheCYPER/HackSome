from concurrent.futures import ThreadPoolExecutor

import pytest

from hacksome.stages.build.control.handoff import BuildAuthorizationEnvelopeV1
from hacksome.stages.build.control.team_registry import RegistryConflictError, TeamRegistry

from tests.stages.build.control.test_handoff import envelope


def test_concurrent_first_authorizations_allocate_unique_monotonic_sequence(
    tmp_path,
):
    registry = TeamRegistry(tmp_path / "build")
    envelopes = [
        BuildAuthorizationEnvelopeV1.from_mapping(
            envelope(
                run_id=f"run-{index}",
                card_id=f"card-{index}",
                markdown=f"# Card {index}\n\nExact {index}.\n",
            )
        )
        for index in range(20)
    ]
    with ThreadPoolExecutor(max_workers=8) as executor:
        rows = list(executor.map(registry.authorize, envelopes))
    assert sorted(row["enqueue_seq"] for row in rows) == list(range(1, 21))
    assert len({row["team_id"] for row in rows}) == 20
    assert registry.sequence_path.read_text().count("21") == 1


def test_registry_replay_conflict_and_exact_reference_adoption(tmp_path):
    registry = TeamRegistry(tmp_path / "build")
    decoded = BuildAuthorizationEnvelopeV1.from_mapping(envelope())
    first = registry.authorize(decoded)
    replay = registry.authorize(decoded)
    assert replay["team_id"] == first["team_id"]
    registry.bootstrap(first["team_id"])
    _, adopted = registry.bootstrap(first["team_id"])
    assert adopted is True

    card = (
        registry.build_root
        / first["control_root"]
        / "project/reference/initial-idea-card.md"
    )
    card.write_text("# Tampered\n")
    with pytest.raises(RegistryConflictError, match="conflict"):
        registry.bootstrap(first["team_id"])


def test_same_source_card_changed_hash_fails_closed(tmp_path):
    registry = TeamRegistry(tmp_path / "build")
    registry.authorize(
        BuildAuthorizationEnvelopeV1.from_mapping(envelope())
    )
    changed = BuildAuthorizationEnvelopeV1.from_mapping(
        envelope(markdown="# Card\n\nChanged exact bytes.\n")
    )
    with pytest.raises(RegistryConflictError, match="different hash"):
        registry.authorize(changed)


def test_partial_reference_tree_is_never_adopted_or_overwritten(tmp_path):
    registry = TeamRegistry(tmp_path / "build")
    decoded = BuildAuthorizationEnvelopeV1.from_mapping(envelope())
    row = registry.authorize(decoded)
    references = (
        registry.build_root
        / row["control_root"]
        / "project/reference"
    )
    references.mkdir(parents=True)
    challenge = references / "challenge.md"
    challenge.write_text(
        decoded.handoff.challenge_markdown,
        encoding="utf-8",
    )

    with pytest.raises(RegistryConflictError, match="conflict"):
        registry.bootstrap(row["team_id"])
    assert challenge.read_text(encoding="utf-8") == (
        decoded.handoff.challenge_markdown
    )
    assert not (references / "initial-idea-card.md").exists()
