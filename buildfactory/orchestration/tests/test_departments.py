import shutil
from pathlib import Path

import pytest
import yaml

from orchestration.departments import DepartmentCatalog, DepartmentController, DepartmentError
from orchestration.objective_store import ObjectiveStore
from orchestration.verifier_manager import VerifierManager


DEPARTMENT_SPECS = Path(__file__).parents[2] / "agents" / "departments"


@pytest.fixture(autouse=True)
def _use_fixture_catalog(department_specs, monkeypatch):
    monkeypatch.setattr(
        "orchestration.tests.test_departments.DEPARTMENT_SPECS",
        department_specs,
    )


def _world(tmp_path):
    reviews = VerifierManager(tmp_path / "reviews")
    objectives = ObjectiveStore(tmp_path / "agents", reviews)
    catalog = DepartmentCatalog.load(DEPARTMENT_SPECS)
    controller = DepartmentController(
        tmp_path / "departments", catalog=catalog, objectives=objectives
    )
    return reviews, objectives, catalog, controller


def _copy_specs(tmp_path: Path) -> Path:
    return Path(shutil.copytree(DEPARTMENT_SPECS, tmp_path / "agents" / "departments"))


def _rewrite_spec(directory: Path, template_id: str, **updates) -> None:
    path = directory / f"{template_id}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data.update(updates)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _pass_next(reviews):
    launch = reviews.schedule()[0]
    reviews.submit_verdict(
        launch.review_id,
        instance_id=launch.instance_id,
        verdict="PASS",
        reason="approved",
    )
    return launch.review_id


def _activate_company(reviews, objectives):
    proposal = objectives.propose(
        actor_id="ceo",
        objective_kind="company",
        text="Build a durable business",
        requested_by="ceo",
        request_id="company-objective",
    )
    _pass_next(reviews)
    objectives.apply_review(proposal["review_id"])


def test_ceo_only_sees_public_id_name_and_description(tmp_path):
    _, _, catalog, controller = _world(tmp_path)

    options = controller.list_options()

    assert [row["id"] for row in options] == list(catalog.ALLOWED_IDS)
    assert all(set(row) == {"id", "name", "description"} for row in options)
    assert all("heartbeat" not in str(row) and "mcp" not in str(row) for row in options)


def test_catalog_derives_runtime_paths_from_each_department_spec():
    catalog = DepartmentCatalog.load(DEPARTMENT_SPECS)

    builder = catalog.internal("builder")

    assert builder.public_name == "Build Department"
    assert builder.public_description == (
        "把已选择的方向转化为可运行、可交付、可验证的产品与技术资产。"
    )
    assert builder.agent_spec == "departments/builder.yaml"
    assert builder.charter == "assets/departments/builder-charter.md"
    assert builder.heartbeat_secs == 900


def test_catalog_requires_exactly_the_fixed_department_files(tmp_path):
    missing = _copy_specs(tmp_path / "missing")
    (missing / "builder.yaml").unlink()
    with pytest.raises(DepartmentError, match="must contain exactly"):
        DepartmentCatalog.load(missing)

    extra = _copy_specs(tmp_path / "extra")
    shutil.copyfile(extra / "builder.yaml", extra / "extra.yaml")
    with pytest.raises(DepartmentError, match="must contain exactly"):
        DepartmentCatalog.load(extra)

    alternate_extension = _copy_specs(tmp_path / "alternate-extension")
    shutil.copyfile(
        alternate_extension / "builder.yaml", alternate_extension / "extra.yml"
    )
    with pytest.raises(DepartmentError, match="must contain exactly"):
        DepartmentCatalog.load(alternate_extension)


def test_catalog_requires_name_to_match_file_and_fixed_id(tmp_path):
    directory = _copy_specs(tmp_path)
    _rewrite_spec(directory, "builder", name="not-builder")

    with pytest.raises(DepartmentError, match="name must match"):
        DepartmentCatalog.load(directory)


def test_catalog_requires_each_department_spec_to_be_a_mapping(tmp_path):
    directory = _copy_specs(tmp_path)
    (directory / "builder.yaml").write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    with pytest.raises(DepartmentError, match="must be a mapping"):
        DepartmentCatalog.load(directory)


@pytest.mark.parametrize("field", ["public_name", "public_description"])
def test_catalog_requires_non_empty_public_text(tmp_path, field):
    directory = _copy_specs(tmp_path)
    _rewrite_spec(directory, "builder", **{field: "   "})

    with pytest.raises(DepartmentError, match=field):
        DepartmentCatalog.load(directory)


@pytest.mark.parametrize("heartbeat", [0, -1, "900", True])
def test_catalog_requires_positive_integer_heartbeat(tmp_path, heartbeat):
    directory = _copy_specs(tmp_path)
    _rewrite_spec(directory, "builder", heartbeat_secs=heartbeat)

    with pytest.raises(DepartmentError, match="positive integer"):
        DepartmentCatalog.load(directory)


@pytest.mark.parametrize(
    ("system_prompt", "message"),
    [("../../outside.md", "stay inside"), ("/tmp/charter.md", "must be relative")],
)
def test_catalog_rejects_system_prompt_outside_agents(tmp_path, system_prompt, message):
    directory = _copy_specs(tmp_path)
    _rewrite_spec(directory, "builder", system_prompt=system_prompt)

    with pytest.raises(DepartmentError, match=message):
        DepartmentCatalog.load(directory)


def test_creation_requires_active_company_objective_and_ceo_identity(tmp_path):
    _, _, _, controller = _world(tmp_path)

    with pytest.raises(DepartmentError, match="Company Objective"):
        controller.request_creation(
            option_id="researcher",
            initial_objective="Own evidence",
            requested_by="ceo",
            request_id="create-1",
        )
    with pytest.raises(DepartmentError, match="only CEO"):
        controller.request_creation(
            option_id="researcher",
            initial_objective="Own evidence",
            requested_by="builder",
            request_id="create-2",
        )


def test_department_does_not_exist_before_initial_objective_pass(tmp_path):
    reviews, objectives, _, controller = _world(tmp_path)
    _activate_company(reviews, objectives)
    request = controller.request_creation(
        option_id="researcher",
        initial_objective="Continuously validate important assumptions.",
        requested_by="ceo",
        request_id="create-research",
    )

    assert controller.list_departments() == []
    review_id = _pass_next(reviews)
    assert review_id == request["objective_review_id"]
    reconciled = controller.reconcile_creation(request["id"])

    assert reconciled["status"] == "provisioning"
    assert controller.list_departments() == []
    department = controller.mark_active(request["id"], service_name="new-company-researcher")
    assert department["id"] == "researcher"
    assert controller.mark_active(
        request["id"], service_name="new-company-researcher"
    ) == department
    assert objectives.current("researcher").startswith("Continuously")


def test_failed_initial_objective_creates_no_shell_department(tmp_path):
    reviews, objectives, _, controller = _world(tmp_path)
    _activate_company(reviews, objectives)
    request = controller.request_creation(
        option_id="builder",
        initial_objective="Build stuff",
        requested_by="ceo",
        request_id="create-builder",
    )
    launch = reviews.schedule()[0]
    reviews.submit_verdict(
        launch.review_id,
        instance_id=launch.instance_id,
        verdict="FAIL",
        reason="not an operational result boundary",
    )

    result = controller.reconcile_creation(request["id"])

    assert result["status"] == "objective_rejected"
    assert controller.list_departments() == []


def test_template_is_single_instance_and_there_is_no_retirement_api(tmp_path):
    reviews, objectives, _, controller = _world(tmp_path)
    _activate_company(reviews, objectives)
    request = controller.request_creation(
        option_id="growth",
        initial_objective="Own distribution learning and conversion.",
        requested_by="ceo",
        request_id="create-growth",
    )
    _pass_next(reviews)
    controller.reconcile_creation(request["id"])
    controller.mark_active(request["id"], service_name="new-company-growth")

    with pytest.raises(DepartmentError, match="already exists"):
        controller.request_creation(
            option_id="growth",
            initial_objective="Duplicate",
            requested_by="ceo",
            request_id="create-growth-again",
        )
    assert not hasattr(controller, "retire")
    assert not hasattr(controller, "delete")


def test_provision_failure_is_retryable_but_does_not_allow_second_creation(tmp_path):
    reviews, objectives, _, controller = _world(tmp_path)
    _activate_company(reviews, objectives)
    request = controller.request_creation(
        option_id="builder",
        initial_objective="Own delivery of verified products.",
        requested_by="ceo",
        request_id="create-builder",
    )
    _pass_next(reviews)
    controller.reconcile_creation(request["id"])

    failed = controller.mark_provision_failed(
        request["id"], reason="docker temporarily unavailable"
    )
    assert failed["status"] == "provision_failed"
    assert failed["provision_attempts"] == 1
    with pytest.raises(DepartmentError, match="already in progress"):
        controller.request_creation(
            option_id="builder",
            initial_objective="Duplicate request",
            requested_by="ceo",
            request_id="create-builder-again",
        )

    department = controller.mark_active(
        request["id"], service_name="new-company-builder"
    )
    assert department["status"] == "active"
