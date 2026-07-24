import importlib.util
from pathlib import Path

from orchestration.company_hub import CompanyHub
from orchestration.departments import DepartmentController
from orchestration.method_adapter import ActorContext


ROOT = Path(__file__).resolve().parents[2]


def _request(method, payload, request_id):
    return {
        "version": 1,
        "request_id": request_id,
        "method": method,
        "payload": payload,
    }


def test_v7_exposes_no_department_retirement_product_surface(
    tmp_path, department_specs
):
    hub = CompanyHub(
        tmp_path / "brand-new-company",
        department_specs_path=department_specs,
    )
    methods = set(hub.adapter._handlers)

    assert not methods.intersection(
        {
            "retire_department",
            "delete_department",
            "merge_department",
            "recreate_department",
            "drain_department",
        }
    )
    for name in ("retire", "delete", "merge", "recreate", "drain"):
        assert not hasattr(DepartmentController, name)

    assert importlib.util.find_spec("orchestration.role") is None
    assert importlib.util.find_spec("orchestration.provisioner") is None


def test_v6_product_modules_templates_and_protocol_skills_are_absent():
    for module in (
        "broker",
        "ceo_loop",
        "goal_ledger",
        "hub",
        "messaging",
        "objective",
        "receive_tool",
        "role",
        "provisioner",
    ):
        assert not (ROOT / "orchestration" / f"{module}.py").exists()

    for role in ("researcher", "builder", "growth", "verifier"):
        assert not (ROOT / "agents" / f"{role}.yaml").exists()
    for skill in (
        "create-role",
        "receive-goal",
        "review-objective",
        "review-role",
        "send-goal",
        "set-objective",
        "when-idle",
    ):
        assert not (
            ROOT / "agents" / "assets" / "skills" / skill / "SKILL.md"
        ).exists()

    assert not (ROOT / "agents" / "mcp" / "verifier.json").exists()
    assert not (ROOT / "orchestration" / "Dockerfile.broker").exists()


def test_v7_goal_has_no_supersede_method_or_relationship_fields(
    tmp_path, department_specs
):
    hub = CompanyHub(
        tmp_path / "brand-new-company",
        department_specs_path=department_specs,
    )
    assert "supersede_goal" not in hub.adapter._handlers

    # The scheduler is tested through the real Department method boundary;
    # seed only the already-verified organization projections needed to make
    # that actor active.
    (hub.layout.agents / "ceo").mkdir(parents=True, exist_ok=True)
    (hub.layout.agents / "ceo" / "objective.md").write_text("active", encoding="utf-8")
    from orchestration.runtime_store import atomic_write_json

    atomic_write_json(
        hub.layout.departments / "builder.json",
        {"id": "builder", "name": "Build", "status": "active"},
    )
    actor = ActorContext("department", "builder", department_id="builder")
    response = hub.call(
        actor,
        _request(
            "create_goal",
            {"intent": "Produce one concrete artifact."},
            "negative-contract-goal",
        ),
    )
    assert response["ok"] is True
    goal = hub.scheduler.get(response["result"]["id"])
    assert not {
        "superseded_by_goal_id",
        "supersedes_goal_id",
        "replacement_goal_id",
    }.intersection(goal)

    rejected = hub.call(
        actor,
        _request(
            "supersede_goal",
            {"goal_id": goal["id"], "replacement": "something else"},
            "negative-contract-supersede",
        ),
    )
    assert rejected["ok"] is False
    assert rejected["error"]["code"] == "unknown_method"
