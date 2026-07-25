from hacksome.stages.build import AGENTS_ROOT
from hacksome.stages.build.agent_runtime.spec import AgentSpec
from hacksome.stages.build.control.runtime_materialization import (
    account_package_docker_args,
    materialize_ephemeral_home,
    read_env_file,
    wait_for_computer_server,
)


def test_env_file_parser_never_evaluates_shell_text(tmp_path):
    env_file = tmp_path / "secrets.env"
    env_file.write_text(
        "# comment\nTOKEN='literal value'\nDANGEROUS=$(touch /tmp/never-run)\n",
        encoding="utf-8",
    )

    values = read_env_file(env_file)

    assert values == {
        "TOKEN": "literal value",
        "DANGEROUS": "$(touch /tmp/never-run)",
    }


def test_ephemeral_worker_home_gets_zero_skills_auth_and_account_env(tmp_path):
    account = tmp_path / "account"
    account.mkdir()
    (account / "codex-auth.json").write_text('{"tokens":"seed"}', encoding="utf-8")
    (account / "secrets.env").write_text(
        "DATAFORSEO_USERNAME=test-user\n"
        "DATAFORSEO_PASSWORD=test-pass\n"
        "STRIPE_SECRET_KEY=test-stripe\n",
        encoding="utf-8",
    )
    spec = AgentSpec.load(
        str(AGENTS_ROOT / "ephemeral" / "team-worker.yaml")
    )
    home = tmp_path / "home"

    info = materialize_ephemeral_home(
        spec,
        home,
        account_dir=account,
        include_account_secrets=True,
    )

    assert info.skills == []
    skills_root = home / "skills"
    assert not skills_root.exists() or list(skills_root.iterdir()) == []
    assert (home / "codex" / "auth.json").read_text(encoding="utf-8") == '{"tokens":"seed"}'
    config = (home / "codex" / "config.toml").read_text(encoding="utf-8")
    assert "test-user" in config
    assert "test-stripe" in config


def test_verifier_materialization_keeps_zero_skill_loadout_without_serializing_unused_secret(
    tmp_path,
):
    account = tmp_path / "account"
    account.mkdir()
    (account / "codex-auth.json").write_text('{"tokens":"seed"}', encoding="utf-8")
    (account / "secrets.env").write_text(
        "STRIPE_SECRET_KEY=must-not-appear\n", encoding="utf-8"
    )
    spec = AgentSpec.load(
        str(AGENTS_ROOT / "ephemeral" / "team-verifier.yaml")
    )
    home = tmp_path / "home"

    materialize_ephemeral_home(
        spec,
        home,
        account_dir=account,
        include_account_secrets=True,
    )

    config = (home / "codex" / "config.toml").read_text(encoding="utf-8")
    assert "must-not-appear" not in config
    assert "stripe" not in config.lower()
    assert "playwright" in config
    skills_root = home / "skills"
    assert not skills_root.exists() or list(skills_root.iterdir()) == []


def test_account_package_docker_args_share_env_file_and_read_only_mount(tmp_path):
    account = tmp_path / "account"
    account.mkdir()
    env_file = account / "secrets.env"
    env_file.write_text("TOKEN=value\n", encoding="utf-8")

    assert account_package_docker_args(account) == [
        "--env-file",
        str(env_file),
        "-v",
        f"{account}:/account:ro",
    ]


def test_computer_server_readiness_poll_is_bounded(monkeypatch):
    attempts = []
    clock = iter([0.0, 0.0, 0.01, 0.02])
    monkeypatch.setattr("hacksome.stages.build.control.runtime_materialization.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("hacksome.stages.build.control.runtime_materialization.time.sleep", lambda _: None)

    def run(args):
        attempts.append(args)
        from subprocess import CompletedProcess

        return CompletedProcess(args, 1, "", "not ready")

    assert wait_for_computer_server(run, "worker-1", timeout_secs=0.02) is False
    assert len(attempts) == 3
    assert all(call[:3] == ["docker", "exec", "worker-1"] for call in attempts)


def test_computer_server_readiness_accepts_listening_port():
    from subprocess import CompletedProcess

    def run(args):
        return CompletedProcess(args, 0, "up\n", "")

    assert wait_for_computer_server(run, "verifier-1", timeout_secs=0) is True
