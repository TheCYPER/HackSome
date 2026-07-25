"""Claude Code runtime adapter — the ONLY place that knows the `claude` CLI.

This adapter is the single argv builder for both resident wakes and ephemeral
turns. Its canonical behavior is locked by golden tests against the historical
pre-adapter snapshots:

  1. `--output-format stream-json --verbose` is now UNCONDITIONAL — the
     resident path (which only looked at the exit code) gains structured
     error/cost/usage;
  2. `--strict-mcp-config` is UNCONDITIONAL (with a config, load ONLY that file;
     with none, keep claude from picking up ~/.claude.json or a workdir
     .mcp.json the agent may have written — off must mean OFF);
  3. session unification: resume_token → `--resume`, else `--session-id`
     (session_hint or a freshly minted uuid).

stream-json parsing (spike S1, real fields — do NOT use design's old assumptions):
    take the LAST NDJSON event with type=="result", then:
        ok       = not ev["is_error"]   # ⚠ MUST use is_error, NOT subtype
                                         #   (a 401 still reports subtype=="success")
        text     = ev["result"]         # final assistant text
        cost_usd = ev["total_cost_usd"]
        error    = ev["api_error_status"] or (text if is_error else None)

The adapter is STATEFUL per run: build_argv records the session token it put
on the argv and parse_output echoes it as RunResult.session_token (claude can
pre-set its id, so the token is known before the process runs). Use a fresh
instance per invocation — runtime_for() returns one.
"""

import json
import os
import uuid

from hacksome.stages.build.agent_runtime.credentials import ApiKeyCreds, SubscriptionCreds
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
# (RunRequest.model/effort is UNSET). An explicit `model: null` / `effort: null`
# arrives as None and omits the flag → account/CLI default. Claude-specific
# knowledge, so they live HERE, not in AgentSpec (design §3).
DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_EFFORT = "xhigh"


def parse_stream_json(stdout: str) -> RunResult:
    """Parse claude `--output-format stream-json` NDJSON → RunResult.

    Pure (no subprocess) so it is unit-testable against captured fixtures.
    session_token is left None — ClaudeCodeRuntime.parse_output fills it from
    the token build_argv pre-set."""
    result_ev: dict | None = None
    result_raw = ""
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict) and ev.get("type") == "result":
            result_ev = ev
            result_raw = line

    if result_ev is None:
        return RunResult(
            ok=False,
            text="",
            error="no result event in stream-json output",
            session_token=None,
            cost_usd=None,
            usage=None,
            raw_tail=stdout[-800:],
        )

    is_error = bool(result_ev.get("is_error"))
    text = result_ev.get("result") or ""
    cost = result_ev.get("total_cost_usd")
    api_err = result_ev.get("api_error_status")
    if api_err is not None:
        error = str(api_err)
    elif is_error:
        error = text or "agent reported error"
    else:
        error = None
    usage = result_ev.get("usage")
    return RunResult(ok=not is_error, text=text, error=error, session_token=None,
                     cost_usd=cost, usage=usage if isinstance(usage, dict) else None,
                     raw_tail=result_raw)


class ClaudeCodeRuntime:
    """Headless `claude -p` runtime (subscription or api-key)."""

    name = "claude-code"
    uses_session_hint = True   # --session-id: the hint IS the session id

    def __init__(self):
        # Set by build_argv, echoed by parse_output: claude's session id is
        # pre-settable, so the continuation token is known up front.
        self._session_token: str | None = None

    # --- argv ------------------------------------------------------------------

    def build_argv(self, req: RunRequest) -> list[str]:
        """The merged `claude -p` argv (module docstring: superset + 3 diffs)."""
        argv = ["claude", "-p", req.prompt]
        if req.resume_token:
            self._session_token = req.resume_token
            argv += ["--resume", req.resume_token]
        else:
            # Pin the session id up front so callers can correlate runtime
            # output and continuation state with the same pre-minted uuid.
            self._session_token = req.session_hint or str(uuid.uuid4())
            argv += ["--session-id", self._session_token]
        if req.charter:
            argv += ["--append-system-prompt", req.charter]
        if req.mcp_config:
            argv += ["--mcp-config", req.mcp_config]
        model = DEFAULT_MODEL if isinstance(req.model, UnsetType) else req.model
        effort = DEFAULT_EFFORT if isinstance(req.effort, UnsetType) else req.effort
        if model:
            argv += ["--model", model]
        if effort:
            argv += ["--effort", effort]
        argv.append("--strict-mcp-config")
        argv += ["--output-format", "stream-json", "--verbose"]
        if req.bypass_permissions:
            argv.append("--dangerously-skip-permissions")
        return argv

    # --- output ----------------------------------------------------------------

    def parse_output(self, stdout: str, returncode: int) -> RunResult:
        """parse_stream_json + the pre-set session token.

        returncode is deliberately NOT consulted: the result event's is_error
        is authoritative (spike S1: a 401 exits 0 with subtype=="success"),
        and a missing result event already yields ok=False. The token is
        returned even on error — the on-disk session usually exists once the
        process ran at all, and the old resident loop persisted it regardless."""
        res = parse_stream_json(stdout)
        res.session_token = self._session_token
        return res

    # --- home materialization ----------------------------------------------------

    def materialize_home(
        self,
        spec,
        home_root: str,
        *,
        environment=None,
        skills_root: str | None = None,
    ) -> LoadoutInfo:
        """Materialize the spec's skill/hook/prompt carriers into home_root
        (= CLAUDE_CONFIG_DIR, the per-agent `.claude`).

        Neutral core (loadout.py — since 07-09 codex-hooks that includes the
        hooks merge/remove helpers, shared with the codex adapter). Claude-
        specific here: the snippet's entries land in settings.json — never a
        whole-file overwrite, never touching keys or entries the agent added
        itself (the manifest records exactly what the loadout merged, so
        "off" can undo it later). Idempotent."""
        os.makedirs(home_root, exist_ok=True)
        settings_path = os.path.join(home_root, "settings.json")
        manifest_path = os.path.join(home_root, MANIFEST_NAME)

        # this run's effective carriers, resolved up front so reconcile can diff
        skill_srcs = spec.skill_paths()
        names = [os.path.basename(src.rstrip("/")) for src in skill_srcs]
        hooks = snippet_hooks(spec.hooks_path())

        previous, warnings = read_manifest(manifest_path)
        # hooks reconcile: undo what the LAST run merged and this run no longer wants
        if previous["hooks"] and previous["hooks"] != hooks:
            remove_hooks(settings_path, previous["hooks"])
        sync_skills(skills_root or os.path.join(home_root, "skills"), skill_srcs, names,
                    previous["skills"])
        hooks_merged = False
        if hooks:
            hooks_merged = merge_hooks(settings_path, hooks)
        write_manifest(manifest_path, names, hooks)

        return LoadoutInfo(
            home=home_root,
            system_prompt=spec.read_system_prompt(),
            skills=names,
            settings_path=settings_path,
            hooks_merged=hooks_merged,
            warnings=warnings,
        )

    # --- credentials / env --------------------------------------------------------

    def credential_kinds(self) -> dict[str, type]:
        return {"subscription": SubscriptionCreds, "api-key": ApiKeyCreds}

    def home_env(self, home_root: str) -> dict[str, str]:
        # CLAUDE_CONFIG_DIR is the claude CLI's own home-relocation var.
        # Auto-memory is killed fleet-wide (issue #207): durable state lives in
        # /company only, so the CLI must not grow a private per-role notebook
        # under <home>/projects/*/memory. Claude-specific knowledge (codex has
        # no such feature), hence HERE and not in runner.py; the resident path
        # gets the same var from the compose x-agent-env anchor.
        return {"CLAUDE_CONFIG_DIR": home_root,
                "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
