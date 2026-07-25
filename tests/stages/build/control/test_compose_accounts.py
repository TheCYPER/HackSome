"""Active Team Compose boundaries and project-state isolation."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[4] / "ops" / "build"
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
SERVICES = COMPOSE["services"]
LOCAL_COMPOSE = yaml.safe_load((ROOT / "docker-compose.local.yml").read_text())
LOCAL_SERVICES = LOCAL_COMPOSE["services"]


def _target(value: str) -> str:
    parts = value.rsplit(":", 2)
    return parts[-2] if parts[-1] in ("ro", "rw") else parts[-1]


def test_static_stack_is_one_lead_plus_team_kernel():
    assert set(SERVICES) == {
        "lead",
        "hub",
        "worker-manager",
        "verifier-manager",
    }
    for removed in (
        "ceo",
        "department-provisioner",
        "peripheral",
        "mail-router",
        "researcher",
        "builder",
        "growth",
    ):
        assert removed not in SERVICES


def test_lead_has_project_and_account_but_no_control_plane_mounts():
    lead = SERVICES["lead"]
    targets = {_target(str(value)) for value in lead["volumes"]}
    assert "/project" in targets
    assert "/account" in targets
    assert "/company" not in targets
    forbidden = {
        "/control",
        "/memory",
        "/telemetry",
        "/reviews",
        "/workers",
        "/inbox",
        "/ledger",
        "/sessions",
        "/mailboxes",
        "/mail-global",
    }
    assert not targets.intersection(forbidden)
    assert lead["environment"]["AGENT_KIND"] == "lead"
    assert lead["environment"]["AGENT_SPEC"].endswith("/agents/lead.yaml")
    assert "AGENT_CHARTER" not in lead["environment"]
    assert lead["environment"]["AGENT_LOOP_MODULE"] == "hacksome.stages.build.control.lead_loop"
    assert lead["environment"]["AGENT_HEARTBEAT_SECS"] == "${LEAD_HEARTBEAT_SECS:-60}"
    assert (
        lead["environment"]["LEAD_REFLECTION_MEMORY_ENABLED"]
        == "${LEAD_REFLECTION_MEMORY_ENABLED:-0}"
    )
    assert "entrypoint" not in lead


def test_hub_and_managers_use_team_state_with_single_concurrency():
    hub = SERVICES["hub"]
    assert hub["environment"]["TEAM_STATE_ROOT"] == "/state"
    assert "COMPANY" not in hub["environment"]
    assert "MAIL_GLOBAL_ROOT" not in hub["environment"]
    assert "GOAL_TIMEOUT_SECS" not in hub["environment"]
    assert "hacksome.stages.build.control.team_hub" in " ".join(hub["entrypoint"])
    assert (
        hub["environment"]["LEAD_REFLECTION_MEMORY_ENABLED"]
        == "${LEAD_REFLECTION_MEMORY_ENABLED:-0}"
    )

    worker = SERVICES["worker-manager"]["environment"]
    verifier = SERVICES["verifier-manager"]["environment"]
    assert worker["TEAM_MODE"] == "1"
    assert verifier["TEAM_MODE"] == "1"
    assert worker["WORKER_MAX"] == "1"
    assert verifier["VERIFIER_MAX"] == "1"


def test_only_lifecycle_managers_receive_docker_socket():
    with_socket = {
        name
        for name, service in SERVICES.items()
        if any(
            str(value).startswith("/var/run/docker.sock:")
            for value in service.get("volumes", [])
        )
    }
    assert with_socket == {"worker-manager", "verifier-manager"}


def test_makefile_bootstraps_exact_references_and_has_no_company_services():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "hacksome.stages.build.control.team_store" in makefile
    assert "--challenge-file" in makefile
    assert "--idea-card-file" in makefile
    assert "project/reference/challenge.md" in makefile
    assert "project/reference/initial-idea-card.md" in makefile
    assert "/memory" in makefile
    assert "label=hacksome.team=$(TEAM)" in makefile
    for removed in (
        "mail-up:",
        "department-provisioner",
        "logs-ceo",
        "COMPANY ?=",
    ):
        assert removed not in makefile


def test_local_network_overlay_only_changes_image_acquisition():
    assert set(LOCAL_SERVICES) == set(SERVICES)
    assert LOCAL_SERVICES["lead"] == {
        "image": "${CUA_AGENT_IMAGE:-foundagent/cua-agent:local}",
        "pull_policy": "never",
    }
    for name in ("hub", "worker-manager", "verifier-manager"):
        assert LOCAL_SERVICES[name]["build"]["args"]["BASE_REGISTRY"] == (
            "${CONTROL_BASE_REGISTRY:-m.daocloud.io/docker.io/library}"
        )
    assert LOCAL_SERVICES["worker-manager"]["environment"]["CUA_AGENT_IMAGE"] == (
        "${CUA_AGENT_IMAGE:-foundagent/cua-agent:local}"
    )
    assert LOCAL_SERVICES["verifier-manager"]["environment"]["CUA_AGENT_IMAGE"] == (
        "${CUA_AGENT_IMAGE:-foundagent/cua-agent:local}"
    )
    overlay_text = (ROOT / "docker-compose.local.yml").read_text(encoding="utf-8")
    assert "/Users/" not in overlay_text
    assert "accounts/" not in overlay_text
    assert "state/" not in overlay_text


def test_local_network_make_targets_use_canonical_contexts_and_build_args():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "up-local: shared check-init build-agent-local" in makefile
    assert "build-local: build-agent-local" in makefile
    assert "validate-local:" in makefile
    assert "$(OPS_ROOT)/docker/Dockerfile.local" in makefile
    assert "$(OPS_ROOT)/docker/agent.Dockerfile" in makefile
    assert "$(REPO_ROOT)" in makefile
    for build_arg in (
        "BASE_REGISTRY",
        "CONTROL_BASE_REGISTRY",
        "CUA_BASE_IMAGE",
        "CUA_AGENT_IMAGE",
        "UBUNTU_APT_MIRROR",
        "UBUNTU_PORTS_MIRROR",
        "NPM_REGISTRY",
    ):
        assert build_arg in makefile


def test_local_network_dockerfiles_are_portable_and_secret_free():
    local_base = (ROOT / "docker" / "Dockerfile.local").read_text(encoding="utf-8")
    agent = (ROOT / "docker" / "agent.Dockerfile").read_text(encoding="utf-8")
    assert "ARG BASE_REGISTRY=registry-1.docker.io" in local_base
    assert "FROM ${BASE_REGISTRY}/trycua/cua-ubuntu:latest" in local_base
    assert "COPY --chmod=0755 cua_base_startup.sh" in local_base
    assert "ARG CUA_BASE_IMAGE=foundagent/cua-ubuntu:latest" in agent
    assert "FROM ${CUA_BASE_IMAGE}" in agent
    for build_arg in ("UBUNTU_APT_MIRROR", "UBUNTU_PORTS_MIRROR", "NPM_REGISTRY"):
        assert f"ARG {build_arg}=" in agent
    combined = local_base + agent
    assert "/Users/" not in combined
    assert "password" not in combined.lower()
    assert "token=" not in combined.lower()
