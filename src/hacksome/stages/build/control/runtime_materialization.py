"""Prepare an Agent runtime home from a control process without env leakage."""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Callable

from hacksome.stages.build.agent_runtime import AgentSpec, runtime_for


_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def read_env_file(path: str | Path) -> dict[str, str]:
    """Read the small KEY=VALUE subset used by account ``secrets.env`` files.

    No shell evaluation, interpolation, or command substitution is performed.
    Matching single/double quotes around a whole value are removed.
    """

    source = Path(path)
    if not source.is_file():
        return {}
    values: dict[str, str] = {}
    for line_number, raw in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not _ENV_KEY.fullmatch(key):
            raise ValueError(f"invalid env entry at {source}:{line_number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def account_materialization_environment(
    account_dir: str | Path,
    *,
    include_secrets: bool,
) -> dict[str, str]:
    account = Path(account_dir)
    environment = dict(os.environ)
    if include_secrets:
        environment.update(read_env_file(account / "secrets.env"))
    # Codex subscription auth is copied into the per-Agent writable home.
    environment["CODEX_AUTH_SEED"] = str(account / "codex-auth.json")
    return environment


def account_package_docker_args(account_dir: str | Path) -> list[str]:
    """Return the shared read-only account package Docker arguments."""

    account = Path(account_dir)
    args: list[str] = []
    env_file = account / "secrets.env"
    if env_file.is_file():
        args += ["--env-file", str(env_file)]
    if account.is_dir():
        args += ["-v", f"{account}:/account:ro"]
    return args


def prepare_container_tree(root: str | Path, *, uid: int = 1000, gid: int = 1000) -> None:
    """Make a manager-created bind tree usable by the image's kasm-user.

    Native Linux managers run as root and can assign uid/gid 1000. In a
    rootless/Desktop filesystem where chown is unavailable, permissive modes
    are the compatibility fallback; these paths are per-company internal state.
    """

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    paths = [root, *root.rglob("*")]
    for path in paths:
        owned = False
        if os.geteuid() == 0:
            try:
                os.chown(path, uid, gid)
                owned = True
            except OSError:
                pass
        try:
            if path.is_dir():
                path.chmod(0o700 if owned else 0o777)
            else:
                path.chmod(0o600 if owned else 0o666)
        except OSError:
            pass


def materialize_ephemeral_home(
    spec: AgentSpec,
    home: str | Path,
    *,
    account_dir: str | Path,
    include_account_secrets: bool,
):
    """Materialize runtime config/auth plus an explicitly mountable Skill tree."""

    home = Path(home)
    skills = home / "skills"
    info = runtime_for(spec).materialize_home(
        spec,
        str(home),
        environment=account_materialization_environment(
            account_dir, include_secrets=include_account_secrets
        ),
        skills_root=str(skills),
    )
    prepare_container_tree(home)
    return info


def wait_for_computer_server(
    run_command: Callable[[list[str]], subprocess.CompletedProcess],
    container_name: str,
    *,
    timeout_secs: float = 80.0,
    poll_secs: float = 2.0,
) -> bool:
    """Wait until the CUA image's in-container server is listening on :8000.

    ``docker run -d`` only proves that the container process was accepted. A
    model turn started before computer-server is listening fails
    nondeterministically while its MCP clients connect, so readiness belongs
    to container creation rather than to the first turn.
    """

    deadline = time.monotonic() + max(0.0, timeout_secs)
    while True:
        result = run_command(
            [
                "docker",
                "exec",
                container_name,
                "sh",
                "-lc",
                "(ss -tlnp 2>/dev/null || netstat -tln 2>/dev/null) "
                "| grep -q ':8000' && echo up",
            ]
        )
        if result.returncode == 0 and "up" in result.stdout.split():
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(max(0.01, poll_secs), remaining))
