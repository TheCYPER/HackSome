"""Materialize one V7 resident Agent's fixed template loadout.

Runs ONCE from `ops/build/docker/agent_startup.sh`, before the resident
Agent loop. Reads the template selected by ``AGENT_SPEC`` (falling back to
`assets/agents/<AGENT_KEY>.yaml`) and materializes its declared Skills
+ hooks into ~/.claude, so subscription claude auto-discovers the skills by their
`description` (progressive disclosure). The charter is NOT handled here — it is
injected separately, per-wake, by agent_loop via `--append-system-prompt`.

Why a startup step (not a host pre-build): the resident path is pure
`docker compose up`; each container materializes its own loadout from the
bind-mounted canonical HackSome package. Claude auth rides on
`CLAUDE_CODE_OAUTH_TOKEN` (env), not `~/.claude`, so writing skills/settings
here cannot clobber credentials.

Best-effort by design: a misconfigured skill/hook must NOT brick the agent — the
charter is the floor. On any error we log LOUDLY (visible in `make logs`) and exit
0 so the loop still boots. This is a logged degradation, not a silent swallow.
"""

from __future__ import annotations

import os

# In-container defaults (Compose mounts `src/hacksome` under `/opt/hacksome`;
# `PYTHONPATH=/opt/hacksome` resolves canonical package imports). Overridable
# for tests.
AGENTS_DIR = os.environ.get(
    "AGENTS_DIR",
    "/opt/hacksome/hacksome/stages/build/assets/agents",
)
# CLAUDE_CONFIG_DIR is the claude CLI's own home-relocation var — compose points
# it at the host-persisted /sessions/<role>, so skills must land there too.
CLAUDE_HOME = (os.environ.get("CLAUDE_HOME")
               or os.environ.get("CLAUDE_CONFIG_DIR")
               or os.path.expanduser("~/.claude"))
def _warn(warnings) -> None:
    """Print loadout warnings LOUDLY (visible in `make logs`), then
    continue — WARN + per-entry degradation, never a brick."""
    for w in warnings:
        print(f"[resident_loadout] WARN {w}", flush=True)


def materialize_for(key: str, agents_dir: str = AGENTS_DIR,
                    claude_home: str = CLAUDE_HOME):
    """Load the selected immutable Agent template and materialize its assets.

    The fixed Team role selects its template through ``AGENT_SPEC``. The caller
    cannot add arbitrary Skills, charters, hooks, or MCP configuration.
    Returns ``None`` when no template exists so startup can degrade safely.
    """
    yaml_path = os.environ.get("AGENT_SPEC") or os.path.join(agents_dir, f"{key}.yaml")
    if not os.path.isfile(yaml_path):
        print(f"[resident_loadout] no yaml at {yaml_path} — charter only", flush=True)
        return None
    # Imported lazily so a missing PyYAML surfaces as the caught loadout error
    # (degrade to charter-only) rather than an import-time crash of the hook.
    from hacksome.stages.build.agent_runtime.runtimes import runtime_for
    from hacksome.stages.build.agent_runtime.spec import AgentSpec

    spec = AgentSpec.load(yaml_path)
    info = runtime_for(spec).materialize_home(spec, claude_home)
    _warn(info.warnings)
    print(f"[resident_loadout] {key}: skills={info.skills} "
          f"hooks_merged={info.hooks_merged} -> {claude_home}", flush=True)
    return info


def main() -> int:
    key = os.environ.get("AGENT_KEY")
    if not key:
        print("[resident_loadout] no AGENT_KEY set — nothing to materialize", flush=True)
        return 0
    # Resolve dirs from the environment at CALL time (not def-time defaults) so the
    # container env — and tests — can redirect them.
    agents_dir = os.environ.get("AGENTS_DIR", AGENTS_DIR)
    claude_home = (os.environ.get("CLAUDE_HOME")
                   or os.environ.get("CLAUDE_CONFIG_DIR") or CLAUDE_HOME)
    try:
        materialize_for(key, agents_dir, claude_home)
    except Exception as e:  # noqa: BLE001 — never brick the agent on a loadout error
        print(f"[resident_loadout] ERROR materializing {key!r}: {e!r} "
              "— continuing on charter only", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
