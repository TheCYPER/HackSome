"""Codex runtime adapter — the ONLY place that knows the `codex` CLI.

argv (design §4; verified live against codex-cli 0.142.5 on 2026-07-07 — the
JSONL fixtures under tests/fixtures/codex/ are real captures, not hand-written):

    first wake:  codex exec "<prompt>" --json --skip-git-repo-check \
                   -c developer_instructions="<charter>" \
                   [-m <model>] [-c model_reasoning_effort="<effort>"] \
                   --dangerously-bypass-approvals-and-sandbox \
                   --dangerously-bypass-hook-trust
    resume:      codex exec resume <thread-id> "<prompt>" --json ... (same flags)

Key runtime facts this adapter encodes (all fixture/live-verified):

  - session continuation: codex CANNOT pre-set a thread id (upstream open
    issues #13242/#15271/#15767), so RunRequest.session_hint is IGNORED — the
    only continuation token is the thread id the CLI assigns and emits via
    `thread.started`. `exec resume` RE-EMITS `thread.started` with the SAME
    thread id, so parse_output takes session_token from that event uniformly
    on both branches.
  - `item.completed` items with item.type=="error" can be NON-FATAL warnings
    (e.g. the skills context-budget notice) — a turn that still ends in
    `turn.completed` is a success. NEVER fail on error items alone.
  - a real failure emits a top-level `{"type":"error"}` event AND a final
    `turn.failed` (and exits non-zero): ok = saw turn.completed and no
    turn.failed / top-level error. The exit code is deliberately NOT consulted
    for ok — codex publishes no exit-code enumeration and SIGINT once returned
    0 (issue #4721); the event stream is authoritative (same stance as the
    claude adapter's is_error rule).
  - no dollar cost field: `turn.completed.usage` carries token counts only
    (input/cached_input/output/reasoning_output) → cost_usd is always None,
    usage passes through natively.
  - MCP: no per-invocation config flag — servers ride the per-role
    CODEX_HOME/config.toml that materialize_home renders from the SAME
    agents/mcp/<role>.json the claude adapter passes via --mcp-config. An
    isolated CODEX_HOME is naturally strict (nothing else can be picked up).
  - `-c key=value` values are TOML-parsed by codex (invalid TOML falls back to
    a raw string). We always pass a valid TOML basic string: json.dumps with
    ensure_ascii=False emits exactly the escape set TOML basic strings accept,
    so ANY charter text (newlines, quotes, CJK) survives verbatim.
  - `--dangerously-bypass-approvals-and-sandbox` (--yolo) is the official
    posture inside an externally hardened container (Landlock is unavailable
    in unprivileged containers) — mapped from bypass_permissions, omitted when
    False (parallel to claude's --dangerously-skip-permissions handling).
  - `--skip-git-repo-check` is unconditional: the agent workdir is not a git
    repo and codex refuses to run there without it.
  - hooks (07-09 codex-hooks, live-verified on 0.142.5): CODEX_HOME/hooks.json
    is ISOMORPHIC to claude's settings.json `hooks` key (same event → matcher
    groups → handlers shape, same Stop stdin/stdout contract incl.
    stop_hook_active), so materialize_home reuses the neutral merge/remove
    helpers from loadout.py. WITHOUT `--dangerously-bypass-hook-trust` codex
    SILENTLY skips every hook in headless --json (no warning anywhere), and
    hook trust cannot be pre-seeded non-interactively → build_argv passes the
    flag UNCONDITIONALLY (design §4).
"""

import json
import os
import re
import shutil

from hacksome.stages.build.agent_runtime.credentials import CodexApiKeyCreds, CodexSubscriptionCreds
from hacksome.stages.build.agent_runtime.loadout import (
    LoadoutInfo,
    MANIFEST_NAME,
    merge_hooks,
    read_manifest,
    remove_hooks,
    snippet_hooks,
    sync_skills,
    write_manifest,
)
from hacksome.stages.build.agent_runtime.runtimes.base import (
    RunRequest,
    RunResult,
    UnsetType,
)

# Fleet-wide defaults applied when the role yaml does not mention model/effort
# (RunRequest.model/effort is UNSET); explicit `null` omits the flag →
# account/CLI default. User decision (design §4): pinned symmetrically to the
# claude side (opus-4-8 + xhigh). `gpt-5.5` verified live 2026-07-07 as a valid
# model id under ChatGPT-subscription auth (the fixtures were captured with it).
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_EFFORT = "xhigh"

# Neutral effort vocabulary → codex model_reasoning_effort. Only `max` needs
# translation (codex tops out at xhigh); low|medium|high|xhigh pass through.
# codex's own `minimal` has no neutral counterpart and is never produced.
EFFORT_TO_CODEX = {"max": "xhigh"}

# Subscription auth seed (design §4): the user runs `codex login --device-auth`
# ONCE and parks the auth.json in accounts/<id>/ — the read-only /account mount
# both execution paths already provide. materialize_home copies it into the
# per-role CODEX_HOME (a per-role COPY, not a shared mount: codex refreshes
# tokens by writing auth.json back in place, which a shared ro file would break).
AUTH_SEED_ENV = "CODEX_AUTH_SEED"
DEFAULT_AUTH_SEED = "/account/codex-auth.json"

# ${VAR} / ${VAR:-default} references inside the mcpServers JSON. The claude
# CLI expands these itself at runtime; codex config has NO env expansion, so
# the adapter expands them at render time (same syntax role.py lints for).
_ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

_CONFIG_HEADER = (
    "# GENERATED by the codex runtime adapter (agent/runtimes/codex.py) — DO NOT EDIT.\n"
    "# Translated from this role's mcpServers JSON (agents/mcp/<role>.json is the\n"
    "# single source of truth; this file is re-rendered on every materialization).\n"
    "# ${VAR} refs were expanded at render time — codex has no in-config env\n"
    "# expansion — so expanded credential values live here: a recorded tradeoff\n"
    "# (design §4), mitigated by chmod 600.\n"
)


def _toml_str(value: str) -> str:
    """A TOML basic string for arbitrary text. json.dumps(ensure_ascii=False)
    emits exactly the escapes TOML basic strings accept (\\" \\\\ \\b \\f \\n
    \\r \\t, \\uXXXX only for control chars) — valid TOML for ANY input, and
    CJK text stays readable instead of being \\u-mangled."""
    return json.dumps(value, ensure_ascii=False)


class CodexRuntime:
    """Headless `codex exec` runtime (ChatGPT subscription or api-key)."""

    name = "codex"
    uses_session_hint = False  # thread ids are CLI-assigned, never pre-set

    # --- argv ------------------------------------------------------------------

    def build_argv(self, req: RunRequest) -> list[str]:
        """The `codex exec` / `codex exec resume` argv (module docstring).

        req.session_hint is IGNORED: codex cannot pre-set a thread id, so a
        preferred id is unusable here — the authoritative token comes back in
        RunResult.session_token from the thread.started event. req.mcp_config
        is also unused: codex has no per-invocation MCP flag; the servers were
        rendered into CODEX_HOME/config.toml by materialize_home."""
        if req.resume_token:
            argv = ["codex", "exec", "resume", req.resume_token, req.prompt]
        else:
            argv = ["codex", "exec", req.prompt]
        argv += ["--json", "--skip-git-repo-check"]
        if req.charter:
            argv += ["-c", f"developer_instructions={_toml_str(req.charter)}"]
        model = DEFAULT_MODEL if isinstance(req.model, UnsetType) else req.model
        effort = DEFAULT_EFFORT if isinstance(req.effort, UnsetType) else req.effort
        if model:
            argv += ["-m", model]
        if effort:
            effort = EFFORT_TO_CODEX.get(effort, effort)
            argv += ["-c", f"model_reasoning_effort={_toml_str(effort)}"]
        if req.bypass_permissions:
            argv.append("--dangerously-bypass-approvals-and-sandbox")
        # 07-09 codex-hooks: UNCONDITIONAL (design §4) — hook trust cannot be
        # pre-seeded non-interactively, and without the flag codex SILENTLY
        # skips every hook in headless --json (the exact failure mode the
        # hooks translation exists to kill). Deliberately NOT gated on
        # bypass_permissions (trust is orthogonal to the permission mode) nor
        # on declared hooks (any conditional path that mispredicts falls back
        # to the unobservable silent skip); a hookless role has no
        # CODEX_HOME/hooks.json, so the flag grants it nothing.
        argv.append("--dangerously-bypass-hook-trust")
        return argv

    # --- output ----------------------------------------------------------------

    def parse_output(self, stdout: str, returncode: int) -> RunResult:
        """Parse the `--json` JSONL event stream → RunResult (module docstring
        for the fixture-verified semantics).

        Crash edge (design §4): a process that dies before `thread.started`
        yields session_token=None — the caller must not overwrite its session
        file, so the next wake opens a fresh session (same semantics as a
        claude wake timeout). On a failed-but-started turn the token IS
        returned: the thread exists on disk and stays resumable."""
        session_token: str | None = None
        text = ""
        usage: dict | None = None
        completed = False
        fail_msg: str | None = None    # turn.failed.error.message
        top_error: str | None = None   # top-level {"type":"error"} message
        raw_tail = ""
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            etype = ev.get("type")
            if etype == "thread.started":
                # resume re-emits thread.started with the SAME thread id, so
                # this is the one token source for both branches.
                session_token = ev.get("thread_id") or session_token
            elif etype == "item.completed":
                item = ev.get("item")
                if isinstance(item, dict) and item.get("type") == "agent_message":
                    text = item.get("text") or ""   # last agent_message wins
                # item.type=="error" is deliberately NOT a failure — see module
                # docstring (non-fatal warnings ride this item type; 07-09
                # codex-hooks: --dangerously-bypass-hook-trust adds 2 such
                # warning items per run, covered by this same stance).
            elif etype == "turn.completed":
                completed = True
                u = ev.get("usage")
                usage = u if isinstance(u, dict) else None
                raw_tail = line
            elif etype == "turn.failed":
                err = ev.get("error")
                msg = err.get("message") if isinstance(err, dict) else None
                fail_msg = msg or "turn.failed"
                raw_tail = line
            elif etype == "error":
                top_error = ev.get("message") or "codex error event"

        ok = completed and fail_msg is None and top_error is None
        if ok:
            error = None
        else:
            error = fail_msg or top_error or (
                f"no turn.completed in codex --json output (rc={returncode})")
        return RunResult(ok=ok, text=text, error=error,
                         session_token=session_token,
                         cost_usd=None,   # codex reports token counts only
                         usage=usage,
                         raw_tail=raw_tail or stdout[-800:])

    # --- home materialization ----------------------------------------------------

    def materialize_home(
        self,
        spec,
        home_root: str,
        *,
        environment=None,
        skills_root: str | None = None,
    ) -> LoadoutInfo:
        """Materialize the spec's carriers for codex under home_root (the
        per-role /sessions/<role> mount): CODEX_HOME = <home_root>/codex —
        nested so it never collides with the claude files living in home_root
        itself, and host-persisted so sessions/ rollouts survive restarts
        (resume needs them).

        never-brick stance (resident_loadout contract): the config render, the
        auth seed and the hooks reconcile each degrade to a WARN on failure so
        one broken carrier cannot take the others down; skill-copy errors
        propagate to the caller, which degrades the whole loadout to
        charter-only (same as claude)."""
        codex_home = os.path.join(home_root, "codex")
        os.makedirs(codex_home, exist_ok=True)
        warnings: list[str] = []

        # 1. config.toml: mcpServers JSON → [mcp_servers.*] tables. A falsy
        # mcp_config means NO tables — and the file is still (re)written so
        # servers from a previous materialization cannot linger: off means OFF.
        mcp_path = spec.resolve(spec.mcp_config) if spec.mcp_config else None
        try:
            _render_config(
                os.path.join(codex_home, "config.toml"),
                mcp_path,
                warnings,
                environment=environment,
            )
        except Exception as e:  # noqa: BLE001 — degrade over brick
            warnings.append(f"codex config.toml not rendered ({e!r}) — "
                            "MCP unavailable this run")

        # 2. auth.json seed (subscription): copy ONLY when absent — codex
        # refreshes tokens by rewriting the per-role copy in place, and a
        # re-seed would clobber a fresher token with the stale seed.
        try:
            _seed_auth(codex_home, warnings, environment=environment)
        except Exception as e:  # noqa: BLE001 — degrade over brick
            warnings.append(f"codex auth.json not seeded ({e!r}) — codex may "
                            "run unauthenticated")

        # 3. skills → the USER-LEVEL ~/.agents/skills (home_root-independent:
        # codex discovers skills at .agents/skills, ~/.agents/skills and
        # /etc/codex/skills — never under CODEX_HOME). Same SKILL.md open
        # standard as claude → zero conversion; the neutral core does the copy
        # + manifest reconcile, with the manifest kept in CODEX_HOME (the one
        # dir this adapter owns).
        skill_srcs = spec.skill_paths()
        names = [os.path.basename(src.rstrip("/")) for src in skill_srcs]
        manifest_path = os.path.join(codex_home, MANIFEST_NAME)
        previous, mwarns = read_manifest(manifest_path)
        warnings += mwarns
        target_skills_root = skills_root or os.path.join(
            os.path.expanduser("~"), ".agents", "skills"
        )
        sync_skills(target_skills_root, skill_srcs, names, previous["skills"])

        # 4. hooks (07-09 codex-hooks): snippet → CODEX_HOME/hooks.json, the
        # exact claude reconcile in a different file — codex's hooks.json is
        # shape-identical to claude's settings.json `hooks` key, so the SAME
        # neutral helpers undo what the LAST run merged and this run no longer
        # wants, then value-merge (dedup → idempotent) this run's entries.
        # Agent-added entries / other top-level keys are never touched; no
        # hooks declared → no file created (the verifier's hooklessness is a
        # design decision, it must not grow one). never-brick: a failed
        # reconcile degrades to WARN, and the manifest keeps the PREVIOUS
        # hooks record so a later healthy run can still undo that old merge.
        hooks_file = os.path.join(codex_home, "hooks.json")
        manifest_hooks = previous["hooks"]
        try:
            hooks = snippet_hooks(spec.hooks_path())
            if previous["hooks"] and previous["hooks"] != hooks:
                remove_hooks(hooks_file, previous["hooks"])
            if hooks:
                merge_hooks(hooks_file, hooks)
            manifest_hooks = hooks
        except Exception as e:  # noqa: BLE001 — degrade over brick
            warnings.append(f"codex hooks.json not reconciled ({e!r}) — hooks "
                            "unavailable this run")
        write_manifest(manifest_path, names, manifest_hooks)

        return LoadoutInfo(home=codex_home,
                           system_prompt=spec.read_system_prompt(),
                           skills=names,
                           warnings=warnings)

    # --- credentials / env --------------------------------------------------------

    def credential_kinds(self) -> dict[str, type]:
        return {"subscription": CodexSubscriptionCreds,
                "api-key": CodexApiKeyCreds}

    def home_env(self, home_root: str) -> dict[str, str]:
        # CODEX_HOME is the codex CLI's own home-relocation var (config.toml,
        # auth.json, sessions/ rollouts) — nested under the per-role mount.
        return {"CODEX_HOME": os.path.join(home_root, "codex")}


# --- config.toml rendering ------------------------------------------------------

def _expand_env_refs(
    value: str,
    warnings: list[str],
    context: str,
    *,
    environment=None,
) -> str:
    """Expand ${VAR} / ${VAR:-default} from the CURRENT environment. An unset
    var without a default expands to '' with a WARN — fail-slow and observable
    (same stance as role.py's lint), never a crash."""
    source = os.environ if environment is None else environment

    def sub(m: re.Match) -> str:
        var, default = m.group(1), m.group(2)
        if var in source:
            return source[var]
        if default is not None:
            return default
        warnings.append(
            f"config.toml {context}: ${{{var}}} is not set and has no default "
            "— expanded to '' (the server may fail at runtime)")
        return ""
    return _ENV_REF_RE.sub(sub, value)


def _render_config(
    config_path: str,
    mcp_path: str | None,
    warnings: list[str],
    *,
    environment=None,
) -> None:
    """Render CODEX_HOME/config.toml from the role's mcpServers JSON.

    Translates command/args/env per server (the codex [mcp_servers.<id>]
    schema uses the same key names); every string value gets its ${VAR} refs
    expanded. mcp_path=None (or an unreadable/corrupt json → WARN) renders a
    config with NO mcp_servers tables. chmod 600 — expanded credentials live
    in this file (deliberate tradeoff, design §4)."""
    servers: dict = {}
    if mcp_path is not None:
        try:
            with open(mcp_path) as f:
                data = json.load(f)
            found = data.get("mcpServers") if isinstance(data, dict) else None
            if isinstance(found, dict):
                servers = found
            else:
                warnings.append(f"config.toml: {mcp_path} has no mcpServers "
                                "object — rendering no servers")
        except (OSError, json.JSONDecodeError) as e:
            warnings.append(f"config.toml: mcp json {mcp_path} unusable ({e}) "
                            "— rendering no servers")

    lines = [_CONFIG_HEADER]
    for name, server in servers.items():
        if not isinstance(server, dict):
            warnings.append(f"config.toml: server {name!r} is not an object "
                            "— skipped")
            continue
        ctx = f"server {name!r}"
        lines.append(f"[mcp_servers.{_toml_str(name)}]")
        command = server.get("command")
        if isinstance(command, str):
            lines.append(
                f"command = {_toml_str(_expand_env_refs(command, warnings, ctx, environment=environment))}")
        args = server.get("args")
        if isinstance(args, list) and args:
            rendered = ", ".join(
                _toml_str(
                    _expand_env_refs(str(a), warnings, ctx, environment=environment)
                )
                for a in args
            )
            lines.append(f"args = [{rendered}]")
        env = server.get("env")
        if isinstance(env, dict) and env:
            pairs = ", ".join(
                f"{_toml_str(str(k))} = "
                f"{_toml_str(_expand_env_refs(str(v), warnings, ctx, environment=environment))}"
                for k, v in env.items())
            lines.append(f"env = {{ {pairs} }}")
        lines.append("")

    with open(config_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")
    os.chmod(config_path, 0o600)


# --- auth seed --------------------------------------------------------------------

def _seed_auth(codex_home: str, warnings: list[str], *, environment=None) -> None:
    """Seed CODEX_HOME/auth.json from the account package, ONLY when absent
    (idempotent: the per-role copy is where codex writes token refreshes back,
    so an existing file is always newer than the seed)."""
    target = os.path.join(codex_home, "auth.json")
    if os.path.exists(target):
        return
    source = os.environ if environment is None else environment
    seed = source.get(AUTH_SEED_ENV, DEFAULT_AUTH_SEED)
    if not os.path.isfile(seed):
        warnings.append(
            f"no codex auth seed at {seed} (override via ${AUTH_SEED_ENV}) — "
            "subscription auth unavailable until auth.json exists")
        return
    shutil.copyfile(seed, target)
    os.chmod(target, 0o600)   # bearer tokens — same posture as config.toml
