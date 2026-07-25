"""Runtime adapters + the runtime_for factory (07-07 codex-runtime).

`runtime_for(spec)` replaces the old `hacksome.stages.build.agent_runtime.spec.provider_for`: the role
yaml's `provider` field picks the adapter; every adapter implements the
neutral Runtime protocol (base.py) and is the ONLY file that knows its CLI.
Fresh instance per call — adapters are stateful per run (session token).
"""

from hacksome.stages.build.agent_runtime.runtimes.base import UNSET, RunRequest, RunResult, Runtime, UnsetType
from hacksome.stages.build.agent_runtime.runtimes.claude_code import ClaudeCodeRuntime
from hacksome.stages.build.agent_runtime.runtimes.codex import CodexRuntime


class OpenCodeRuntime:
    """Seam-only placeholder — not implemented (kept as a stub per PRD)."""

    name = "opencode"

    def _not_implemented(self, *args, **kwargs):
        raise NotImplementedError("provider 'opencode' not implemented; seam only")

    build_argv = parse_output = materialize_home = _not_implemented
    credential_kinds = home_env = _not_implemented


_RUNTIMES: dict[str, type[Runtime]] = {
    "claude-code": ClaudeCodeRuntime,
    "codex": CodexRuntime,
}


def runtime_by_name(provider: str) -> Runtime:
    """Factory: provider name → a fresh Runtime instance. For callers that
    carry only the provider string (the resident agent_loop) — spec-holding
    callers use runtime_for.

    A stub provider fails HERE, not at first method call: handing out an
    instance whose every method raises would defeat the callers' degrade
    paths (wake's WARN-and-default catches factory errors, not late blowups)."""
    if provider == "opencode":
        raise NotImplementedError("provider 'opencode' not implemented; seam only")
    cls = _RUNTIMES.get(provider)
    if cls is None:
        raise ValueError(f"unknown provider: {provider!r}")
    return cls()


def runtime_for(spec) -> Runtime:
    """Factory: spec.provider → a fresh Runtime instance."""
    return runtime_by_name(spec.provider)


__all__ = [
    "UNSET",
    "UnsetType",
    "RunRequest",
    "RunResult",
    "Runtime",
    "ClaudeCodeRuntime",
    "CodexRuntime",
    "OpenCodeRuntime",
    "runtime_by_name",
    "runtime_for",
]
