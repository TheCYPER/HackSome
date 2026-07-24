import hashlib
import json

import pytest

from orchestration.handoff import (
    BuildAuthorizationEnvelopeV1,
    HandoffError,
)


def envelope(
    *,
    run_id="run-1",
    card_id="card-1",
    markdown="# Card\n\nExact.\n",
):
    digest = hashlib.sha256(markdown.encode()).hexdigest()
    identity = hashlib.sha256(
        json.dumps(
            {
                "idea_card_id": card_id,
                "idea_card_sha256": digest,
                "source_run_id": run_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "authorization_id": f"auth-{identity[:32]}",
        "source": {
            "route_id": "useful",
            "route_contract_version": "1",
            "catalog_sha256": "c" * 64,
        },
        "handoff": {
            "source_run_id": run_id,
            "idea_card_id": card_id,
            "idea_card_sha256": digest,
            "challenge_markdown": "# Challenge\n\nBuild.\n",
            "initial_idea_card_markdown": markdown,
        },
    }


def test_handoff_exact_schema_sha_and_stable_identity():
    decoded = BuildAuthorizationEnvelopeV1.from_mapping(envelope())
    assert decoded.handoff.team_id.startswith("team-")
    assert decoded.authorization_id == decoded.handoff.authorization_id
    assert decoded.envelope_sha256 == decoded.envelope_sha256

    malformed = envelope()
    malformed["handoff"]["route_id"] = "useful"
    with pytest.raises(HandoffError, match="unknown fields"):
        BuildAuthorizationEnvelopeV1.from_mapping(malformed)

    stale = envelope()
    stale["handoff"]["initial_idea_card_markdown"] = "# Changed\n"
    with pytest.raises(HandoffError, match="does not match"):
        BuildAuthorizationEnvelopeV1.from_mapping(stale)
