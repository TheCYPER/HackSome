import subprocess
from pathlib import Path

import orchestration.department_provisioner as dp
import orchestration.verifier_runtime as vr
import orchestration.worker_manager as wm
from orchestration.departments import DepartmentCatalog


ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_TARGETS = {
    "/control",
    "/telemetry",
    "/reviews",
    "/workers",
    "/inbox",
    "/ledger",
    "/departments",
    "/notes",
    "/agents",
    "/sessions",
    "/mailboxes",
    "/mail-global",
    "/shared/control",
    "/shared/telemetry",
    "/shared/reviews",
    "/shared/workers",
    "/shared/inbox",
    "/shared/ledger",
}


def _mounts(argv):
    return [argv[index + 1] for index, value in enumerate(argv[:-1]) if value == "-v"]


def _target(mount):
    parts = mount.rsplit(":", 2)
    return parts[-2] if parts[-1] in ("ro", "rw") else parts[-1]


def _assert_no_internal_mount(mounts):
    targets = {_target(value) for value in mounts}
    assert "/company" in targets
    assert not (targets & FORBIDDEN_TARGETS)
    assert not any("company_state_kit" in value for value in mounts)
    assert "/opt/company_state_kit" not in targets


def test_worker_runtime_mounts_company_rw_and_no_internal_state(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        wm,
        "materialize_ephemeral_home",
        lambda spec, home, **kwargs: Path(home).mkdir(parents=True, exist_ok=True),
    )
    monkeypatch.setattr(wm, "wait_for_computer_server", lambda *args, **kwargs: True)
    backend = wm.DockerWorkerBackend(repo=ROOT, company_id="new-company")
    monkeypatch.setattr(
        backend,
        "_run",
        lambda args: calls.append(args) or subprocess.CompletedProcess(args, 0, "", ""),
    )
    definition = wm.WorkerDefinition(
        company_id="new-company",
        worker_id="worker-1",
        goal_id="goal-1",
        owner_department="builder",
        container_name="new-company-worker-1",
        home=tmp_path / "home",
        workspace=tmp_path / "workspace",
        company_dir=tmp_path / "company",
    )

    backend.create(definition)
    mounts = _mounts(calls[-1])

    _assert_no_internal_mount(mounts)
    assert f"{definition.company_dir}:/company" in mounts
    assert f"{definition.home / 'skills'}:/home/kasm-user/.agents/skills:ro" in mounts
    assert "COMPANY_ROOT" not in "\n".join(calls[-1])


def test_verifier_runtime_mounts_company_read_only_and_no_internal_state(
    tmp_path, monkeypatch
):
    calls = []
    materialized = {}

    def materialize(spec, home, **kwargs):
        materialized.update(kwargs)
        Path(home).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        vr,
        "materialize_ephemeral_home",
        materialize,
    )
    monkeypatch.setattr(
        vr,
        "account_package_docker_args",
        lambda account_dir: [
            "--env-file",
            str(account_dir / "secrets.env"),
            "-v",
            f"{account_dir}:/account:ro",
        ],
    )
    monkeypatch.setattr(vr, "wait_for_computer_server", lambda *args, **kwargs: True)
    backend = vr.DockerVerifierBackend(repo=ROOT, company_id="new-company")
    monkeypatch.setattr(
        backend,
        "_run",
        lambda args: calls.append(args) or subprocess.CompletedProcess(args, 0, "", ""),
    )
    definition = vr.VerifierDefinition(
        company_id="new-company",
        review_id="review-1",
        instance_id="verifier-1-1",
        container_name="new-company-verifier-1-1",
        home=tmp_path / "home",
        workspace=tmp_path / "workspace",
        company_dir=tmp_path / "company",
    )

    backend.create(definition)
    mounts = _mounts(calls[-1])

    _assert_no_internal_mount(mounts)
    assert f"{definition.company_dir}:/company:ro" in mounts
    assert f"{definition.home / 'skills'}:/home/kasm-user/.agents/skills:ro" in mounts
    assert "--env-file" in calls[-1]
    assert any(value.endswith(":/account:ro") for value in mounts)
    assert materialized["include_account_secrets"] is True
    assert "COMPANY_ROOT" not in "\n".join(calls[-1])


def test_department_runtime_mounts_company_rw_and_uses_fixed_900_template(
    tmp_path, monkeypatch, department_specs
):
    calls = []
    catalog = DepartmentCatalog.load(department_specs)
    backend = dp.DockerDepartmentBackend(repo=ROOT, company_id="new-company")

    def run(args):
        calls.append(args)
        if args[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(args, 1, "", "not found")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(backend, "_run", run)
    template = catalog.internal("researcher")
    definition = dp.DepartmentDefinition(
        company_id="new-company",
        department_id="researcher",
        container_name="new-company-researcher",
        home=tmp_path / "home",
        company_dir=tmp_path / "company",
        template=template,
    )

    backend.ensure(definition)
    run_argv = calls[-1]
    mounts = _mounts(run_argv)

    _assert_no_internal_mount(mounts)
    assert f"{definition.company_dir}:/company" in mounts
    assert "AGENT_HEARTBEAT_SECS=900" in run_argv
    joined = "\n".join(run_argv)
    assert "AGENT_CONTEXT_FROM_HUB" not in joined
    assert "AGENT_REMOTE_INBOX" not in joined
    assert "AGENT_RELIABLE_INBOX" not in joined
    assert "AGENT_PROMPT_MODE" not in joined
    assert "COMPANY_ROOT" not in joined
