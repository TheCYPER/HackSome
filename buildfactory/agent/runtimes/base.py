"""Neutral runtime contract (07-07 codex-runtime, design §2).

Every caller (resident Agent loop, ephemeral runner, loadout materializer, and
provisioner) faces ONLY this model; CLI details — argv, output parsing,
session continuation, credentials, home materialization — live in exactly
one adapter file per runtime (claude_code.py, codex.py). Extension rules:

  - a capability BOTH runtimes need → extend RunRequest/RunResult + implement
    once per adapter; callers change at most once;
  - a runtime-specific flag → touch only that adapter file;
  - a new caller → depends on this module only, never on a concrete adapter.

Session-continuation semantics (design §4): the "session id" is whatever
token the ADAPTER returns in RunResult.session_token — claude echoes its own
pre-set uuid, codex returns the CLI-assigned thread id. The interface never
assumes a caller can DICTATE the id (codex cannot pre-set one — upstream open
issue); RunRequest.session_hint is a best-effort preference adapters may
ignore, RunResult.session_token is the only authoritative value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Mapping, Protocol, runtime_checkable

if TYPE_CHECKING:  # import only for annotations — keep base.py dependency-free
    from agent.credentials import CredentialSource
    from agent.loadout import LoadoutInfo


class UnsetType:
    """Sentinel type for "the yaml key was ABSENT" (≠ an explicit `null`).

    Three-way model/effort semantics (design §3): UNSET → the adapter's own
    fleet default; None (explicit `model: null` in the yaml) → omit the flag
    entirely (account/CLI default); str → pass through. Falsy like None so a
    missed `is UNSET` check degrades to "omit the flag", never to passing the
    sentinel repr to a CLI — adapters must resolve `is UNSET` FIRST.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:  # singleton: `is UNSET` works across pickling
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET = UnsetType()

# Neutral effort vocabulary = the current fleet vocabulary. Adapters translate
# (claude: pass-through; codex: `max`→`xhigh`, rest pass-through — design §4).
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


@dataclass
class RunRequest:
    """One wake / one task, runtime-neutrally.

    `charter` is CONTENT (not a path) — the caller resolves and reads files.
    `mcp_config` is the resolved path of the role's mcpServers JSON; None =
    that runtime's "no MCP" posture (claude: no --mcp-config but still
    --strict-mcp-config so off means OFF; codex: nothing rendered)."""

    prompt: str
    charter: str | None = None
    mcp_config: str | None = None
    model: str | None | UnsetType = UNSET
    effort: str | None | UnsetType = UNSET
    resume_token: str | None = None       # last RunResult.session_token; None = new session
    # Preferred id for a NEW session, best-effort: claude honors it (--session-id,
    # lets a caller correlate its prepared session id; codex ignores it because
    # it cannot pre-set a thread id. Never combine
    # with resume_token — resume wins.
    session_hint: str | None = None
    bypass_permissions: bool = True
    workdir: str | None = None            # None = inherit the process cwd


@dataclass
class RunResult:
    """Structured outcome of one run + the continuation token for the next."""

    ok: bool
    text: str                             # final assistant message
    error: str | None
    timed_out: bool = False               # caller must retire any dedicated execution container
    session_token: str | None = None      # next RunRequest.resume_token; None = don't persist
    cost_usd: float | None = None         # codex has no dollar field → always None there
    usage: dict | None = None             # token counts, each CLI's native shape
    raw_tail: str = ""                    # last raw output line(s), for debugging
    raw_output: str = ""                  # complete runtime event stream, never truncated
    stderr: str = ""                      # complete CLI stderr for the run archive


@runtime_checkable
class Runtime(Protocol):
    """The five methods every runtime adapter implements (design §2).

    `uses_session_hint` declares whether build_argv honors
    RunRequest.session_hint (claude: True — the hint IS the session id;
    codex: False — the CLI assigns thread ids). Callers that mint a hint
    up front (the resident wake) must NOT persist it as a continuation
    token when the adapter ignores hints and the run yielded no
    session_token (timeout / died before the id event) — persisting an
    unhonored hint would poison every later resume."""

    name: str
    uses_session_hint: bool

    def build_argv(self, req: RunRequest) -> list[str]:
        """The full CLI argv for one run. May pre-set adapter state (e.g. the
        claude session token) that parse_output echoes back."""
        ...

    def parse_output(self, stdout: str, returncode: int) -> RunResult:
        """Structured result from the CLI's captured stdout + exit code."""
        ...

    def materialize_home(
        self,
        spec,
        home_root: str,
        *,
        environment: Mapping[str, str] | None = None,
        skills_root: str | None = None,
    ) -> "LoadoutInfo":
        """Materialize the spec's skills/hooks/config into this runtime's home
        under home_root (the per-role /sessions/<role> mount). Explicit
        environment/skills_root let a control process prepare another
        container's home without mutating its own process environment."""
        ...

    def credential_kinds(self) -> dict[str, type["CredentialSource"]]:
        """spec.credentials value ("subscription" | "api-key") → source class."""
        ...

    def home_env(self, home_root: str) -> dict[str, str]:
        """The env pointing the CLI at its home (CLAUDE_CONFIG_DIR / CODEX_HOME)."""
        ...
