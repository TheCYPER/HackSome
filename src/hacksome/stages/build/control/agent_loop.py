#!/usr/bin/env python3
"""Resident loop used by the Build Team's fixed Lead.

Every wake receives exactly one Hub-owned Inbox message or one quiet heartbeat.
The Hub injects the actor's current Objective, private Notes, and deterministic
method capabilities; the Agent receives no raw orchestration-state mount. A wake
is acknowledged only after the runtime succeeds, then the loop immediately
checks the FIFO head again before waiting for another heartbeat.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

# Runtime adapter (07-07 codex-runtime): argv building + output parsing live in
# hacksome.stages.build.agent_runtime.runtimes; the role yaml's `provider` picks the adapter per wake and the
# adapter owns the fleet-default model/effort (yaml key absent → UNSET →
# adapter default; explicit null → flag omitted). never-brick: when the agent
# package mount is missing the loop must still boot charter-only, so the
# import degrades to _runtime_by_name=None + a local UNSET sentinel and wake()
# falls back to a minimal literal claude argv.
try:
    from hacksome.stages.build.agent_runtime.runtimes import runtime_by_name as _runtime_by_name
    from hacksome.stages.build.agent_runtime.runtimes.base import UNSET, RunRequest
except Exception:  # noqa: BLE001 — degrade over brick
    _runtime_by_name = None  # type: ignore[assignment]
    UNSET = None  # type: ignore[assignment]  # degraded mode omits adapter flags

# The resident fleet's roleless default (a key with no agents/<key>.yaml).
DEFAULT_PROVIDER = "claude-code"

# In-container cua-local MCP config — the ROLELESS FALLBACK (never-brick). The
# template baseline comes from the selected AgentSpec; AGENT_MCP is only an
# explicit operator/debug override.
DEFAULT_MCP_CONFIG = "/opt/foundagent/mcp.json"
# Per-wake hard timeout. Hour-scale by decision (issue #206): the 600s default
# hard-killed real >10-min work three attempts in a row on firsttest day one,
# and V5 already established 1h single-run budgets as a hard requirement.
# ACCEPTED TRADEOFF: the loop is serial, so a wake this long is also how long
# the agent can go without reading its inbox — messages QUEUE (nothing is
# lost) and are handled when the wake returns. Mid-wake inbox delivery is a
# separate, deliberately deferred problem (issue #206 point 2).
CLAUDE_TIMEOUT = int(os.environ.get("AGENT_CLAUDE_TIMEOUT", "3600"))
# Wake/cost telemetry (07-07 longrun-hardening): one JSON line per wake appended
# to <TELEMETRY_DIR>/wake.<key>.jsonl (per-key file — no cross-container write
# contention on the shared mount). RECORDING ONLY: no threshold, budget, alert
# or stop logic rides on it. Rows carry cost_usd AND usage (07-09
# telemetry-usage): codex reports no dollar figure, so its token counts are the
# only cost signal a codex wake leaves.
DEFAULT_TELEMETRY_DIR = "/shared/telemetry"


# --- pure builders (unit-tested; no subprocess) ------------------------------

def build_v7_wake_prompt(
    event: dict | None,
    *,
    actor_id: str,
    wake_id: str,
    trigger: str,
    objective: str | None,
    notes: str | None,
    capabilities: tuple[str, ...] | list[str],
    now: str,
    objective_reviews_in_flight: list[dict] | None = None,
    idle: str = "proactive",
    strategic: bool = False,
) -> str:
    """Compose the V7 dynamic wake layer in one stable, auditable order.

    Charter and Skills remain runtime/system loadout.  This function injects
    exactly one triggering message (or a heartbeat) plus the current internal
    Objective/Notes projections; their raw stores are never mentioned as
    browseable paths.
    """
    strategic_line = (
        "Follow `think-strategically`; read and apply at least one routed cognitive Skill's complete SKILL.md before deciding."
        if strategic
        else "Reason within your role and Objective before acting."
    )
    if event is None and idle == "proactive":
        trigger_body = (
            "HEARTBEAT wake: the Inbox stayed quiet for this role's configured interval. "
            "Do not treat quiet or waiting as a complete operating state. Re-evaluate your "
            "Objective and make real, non-duplicative progress within your role; if one line "
            "depends on a pending event, advance another independent useful line."
        )
    else:
        trigger_body = _render_trigger(event or {})
    capability_lines = "\n".join(f"- {name}" for name in capabilities) or "- No mutation methods"
    review_lines = (
        json.dumps(
            objective_reviews_in_flight,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        if objective_reviews_in_flight
        else "(none)"
    )
    return (
        "WAKE CONTEXT\n"
        f"actor_id: {actor_id}\n"
        f"wake_id: {wake_id}\n"
        f"trigger: {trigger}\n"
        f"time: {now}\n"
        f"{strategic_line}\n"
        "---\n"
        "COMPANY ENTRY\n"
        "The company's durable shared state is the native folder /company. Start with a "
        "shallow listing, use descriptive names and scoped search to narrow the area, and "
        "read only relevant leaves. No orchestration directory is a Company State source.\n"
        "---\n"
        "CURRENT OBJECTIVE\n"
        f"{objective or '(no active Objective yet)'}\n"
        "---\n"
        "OBJECTIVE REVIEWS IN FLIGHT\n"
        f"{review_lines}\n"
        "An in-flight proposal is already submitted; do not duplicate it. It does not prevent "
        "progress on another independent strategic line.\n"
        "---\n"
        "NOTES\n"
        f"{notes or '(no private cross-wake note)'}\n"
        "---\n"
        "CAPABILITIES\n"
        f"{capability_lines}\n"
        "---\n"
        "TRIGGER\n"
        f"{trigger_body}\n"
        "---\n"
        "COMPLETION CONTRACT\n"
        "Handle this one trigger completely. Persist durable shared conclusions under /company; "
        "use Notes only for lightweight context for your own next wake. A message is acknowledged "
        "only after this wake succeeds."
    )


def _render_trigger(event: dict) -> str:
    """Render one validated five-field IME without legacy event branches."""
    body = event.get("body")
    rendered_body = (
        json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True)
        if isinstance(body, (dict, list))
        else str(body or "")
    )
    return (
        "You have one new Inbox message. Handle this message completely before "
        "the next FIFO message is delivered.\n"
        f"subject: {event.get('text', '')}\n"
        f"body:\n{rendered_body}"
    )


def _fallback_claude_argv(prompt: str, *, resume: str | None = None,
                          new_session: str | None = None,
                          charter: str | None = None,
                          mcp_config: str | None = None) -> list[str]:
    """never-brick literal argv, used ONLY when hacksome.stages.build.agent_runtime.runtimes failed to import
    (agent package mount missing): the loop still boots charter-only. Minimal
    by design — no model/effort (adapter defaults live in the unavailable
    adapter → account/CLI default), no stream-json (nothing to parse it).

    --strict-mcp-config is UNCONDITIONAL (07-03 mcp-loadout): with a config it
    loads ONLY that file (the official headless combo); with none it keeps
    claude from picking up ~/.claude.json or a
    workdir .mcp.json the agent may have written — off must mean OFF."""
    argv = ["claude", "-p", prompt]
    if resume:
        argv += ["--resume", resume]
    elif new_session:
        argv += ["--session-id", new_session]
    if charter:
        argv += ["--append-system-prompt", charter]
    if mcp_config:
        argv += ["--mcp-config", mcp_config]
    argv.append("--strict-mcp-config")
    argv.append("--dangerously-skip-permissions")
    return argv


# --- session id persistence (parametrized by path → per-agent) ---------------

def load_session(session_file: str | os.PathLike) -> str | None:
    try:
        return Path(session_file).read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None


def save_session(session_file: str | os.PathLike, sid: str) -> None:
    p = Path(session_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(sid, encoding="utf-8")


def _read_charter(charter_path: str | None) -> str | None:
    if not charter_path:
        return None
    try:
        return Path(charter_path).read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None


# --- wake/cost telemetry (07-07 longrun-hardening) ----------------------------

def _record_wake(key: str, trigger: str, started_at: str, started_mono: float,
                 session_id: str | None, cost_usd: float | None,
                 usage: dict | None, ok: bool,
                 error: str | None = None) -> None:
    """Append ONE telemetry line for a finished wake. NEVER-BRICK: any failure
    (missing dir, permission, serialization) logs one line and returns — the
    wake result is already decided and must not be affected. A missing
    telemetry dir (mount not present) is skipped WITHOUT creating state
    outside the mount.

    `usage` (07-09 telemetry-usage) is RunResult.usage passed through VERBATIM
    — each CLI's native token-count shape (claude: input/output/cache fields;
    codex: input/cached_input/output/reasoning_output), deliberately NOT
    normalized here: telemetry records, consumers interpret. None whenever no
    RunResult exists to read it from (timeout, degraded fallback)."""
    try:
        tdir = os.environ.get("TELEMETRY_DIR", DEFAULT_TELEMETRY_DIR)
        if not os.path.isdir(tdir):
            print(f"[agent_loop:{key}] telemetry: dir {tdir} missing — skipped",
                  flush=True)
            return
        row = {
            "key": key,
            "trigger": trigger,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "duration_secs": round(time.monotonic() - started_mono, 3),
            "session_id": session_id,
            "cost_usd": cost_usd,          # None for codex (no dollar field)
            "usage": usage,                # RunResult.usage verbatim; None = no RunResult
            "ok": ok,
            "error": error,                # None when ok — why this wake failed
        }
        with open(os.path.join(tdir, f"wake.{key}.jsonl"), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001 — telemetry must never affect the wake
        print(f"[agent_loop:{key}] WARN: telemetry write failed ({e!r})",
              flush=True)


# --- one wake (live: spawns a claude child) ----------------------------------


@dataclass(frozen=True)
class WakeOutcome:
    session_id: str | None
    ok: bool
    error: str | None = None


def _archive_wake(
    *,
    run_id: str,
    key: str,
    trigger: str,
    started_at: str,
    session_id: str | None,
    ok: bool,
    error: str | None,
    raw_output: str,
    stderr: str,
    model_output: str,
) -> None:
    try:
        from hacksome.stages.build.control.run_logs import recorder_from_env

        harness_log = (
            f"run_id={run_id}\n"
            f"agent_id={key}\n"
            f"trigger={trigger}\n"
            f"session_token={session_id or ''}\n"
            f"ok={ok}\n"
            f"error={error or ''}\n"
        )
        metadata = {
            "kind": "resident_wake",
            "agent_id": key,
            "trigger": trigger,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "session_token": session_id,
            "ok": ok,
            "error": error,
        }
        recorder = recorder_from_env()
        if recorder is not None:
            recorder.record(
                run_id=run_id,
                metadata=metadata,
                raw_output=raw_output,
                stderr=stderr,
                model_output=model_output,
                harness_log=harness_log,
            )
            return
        if os.environ.get("HUB_URL"):
            from hacksome.stages.build.control.control_client import HubClient

            HubClient().archive_run(
                {
                    "run_id": run_id,
                    "metadata": metadata,
                    "raw_output": raw_output,
                    "stderr": stderr,
                    "model_output": model_output,
                    "harness_log": harness_log,
                    "container_log": "",
                }
            )
    except Exception as exc:  # noqa: BLE001 — observability never changes the wake result
        print(f"[agent_loop:{key}] WARN: run archive failed ({exc!r})", flush=True)

def _make_runtime(provider: str | None):
    """The wake adapter for `provider` (None = roleless claude default), or
    None when unavailable → wake()'s literal claude fallback. An unknown /
    unimplemented provider degrades to the DEFAULT (with a LOUD WARN) rather
    than bricking the loop — the role lint whitelist keeps provisioned roles
    valid, so this only fires on a hand-edited yaml."""
    if _runtime_by_name is None:
        return None
    try:
        return _runtime_by_name(provider or DEFAULT_PROVIDER)
    except Exception as e:  # noqa: BLE001 — degrade over brick
        print(f"[agent_loop] WARN: provider {provider!r} unusable ({e!r}) — "
              f"waking on {DEFAULT_PROVIDER}", flush=True)
        return _runtime_by_name(DEFAULT_PROVIDER)


def wake(session_id: str | None, prompt: str, *, key: str = "agent",
         charter: str | None = None, mcp_config: str | None = None,
         model=UNSET, effort=UNSET, provider: str | None = None,
         trigger: str = "event", timeout: int = CLAUDE_TIMEOUT,
         return_outcome: bool = False, run_id: str | None = None
         ) -> str | None | WakeOutcome:
    """Run ONE agent turn — resume the session, or create it on the first wake.
    Returns the continuation token to persist (RunResult.session_token; for
    claude that is the same uuid this wake pre-set, so behavior matches the
    pre-adapter loop; for codex it is the thread id the CLI assigned).

    Argv + output parsing go through the runtime adapter picked by `provider`
    (07-07 codex-runtime; None = claude default); the wake log line prints the
    RunResult summary (ok/error + session token) and the final assistant text
    instead of raw stdout. When hacksome.stages.build.agent_runtime.runtimes is unavailable (missing mount)
    the literal fallback argv keeps the loop alive charter-only, with the old
    exit-code-only logging.

    `trigger` ("event" | "heartbeat", 07-07 longrun-hardening) is what woke the
    agent — recorded (with timing/cost/usage/ok/error) via _record_wake on
    every return path, including a timeout (ok=False + an explicit timeout
    error there: a wake that burned the full timeout is exactly what the
    telemetry is for).

    The full runtime stream and structured outcome are archived under ``run_id``
    for operator-side observability."""
    started_mono = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    run_id = run_id or f"wake-{uuid.uuid4().hex}"
    new_session = None if session_id else str(uuid.uuid4())
    runtime = _make_runtime(provider)
    # The token to keep when the run yields no session_token (timeout / died
    # early): for a hint-honoring runtime (claude; also the literal fallback,
    # which passes --session-id) the pre-minted uuid is real, so keep it — the
    # pre-adapter behavior. For codex the hint was IGNORED, so persisting it
    # would poison every later `exec resume`; keep the incoming token instead
    # (None on a first wake → nothing persisted, next wake starts fresh).
    hint_honored = runtime is None or getattr(runtime, "uses_session_hint", False)
    sid = (session_id or new_session) if hint_honored else session_id
    if runtime is not None:
        argv = runtime.build_argv(RunRequest(
            prompt=prompt, charter=charter, mcp_config=mcp_config,
            model=model, effort=effort,
            resume_token=session_id, session_hint=new_session))
    else:
        argv = _fallback_claude_argv(prompt, resume=session_id,
                                     new_session=new_session, charter=charter,
                                     mcp_config=mcp_config)
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           env=os.environ.copy())
    except subprocess.TimeoutExpired as exc:
        print(f"[agent_loop:{key}] wake TIMEOUT (session={sid or '(none)'})", flush=True)
        # hard-killed mid-run: no RunResult → cost AND usage unknowable (None)
        _record_wake(key, trigger, started_at, started_mono, sid, None, None,
                     False,
                     error=f"timeout after {timeout}s (hard-killed mid-run)")
        error = f"timeout after {timeout}s (hard-killed mid-run)"
        _archive_wake(
            run_id=run_id,
            key=key,
            trigger=trigger,
            started_at=started_at,
            session_id=sid,
            ok=False,
            error=error,
            raw_output=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
            model_output="",
        )
        outcome = WakeOutcome(sid, False, error)
        return outcome if return_outcome else outcome.session_id
    if runtime is None:
        ok = r.returncode == 0
        status = "ok" if ok else f"ERR:rc={r.returncode}"
        print(f"[agent_loop:{key}] woke session={sid} {status}", flush=True)
        print((r.stdout or r.stderr or "").strip(), flush=True)
        # degraded fallback parses no output → cost AND usage stay None
        _record_wake(key, trigger, started_at, started_mono, sid, None, None,
                     ok, error=None if ok else f"rc={r.returncode}")
        fallback_error = None if ok else f"rc={r.returncode}"
        _archive_wake(
            run_id=run_id,
            key=key,
            trigger=trigger,
            started_at=started_at,
            session_id=sid,
            ok=ok,
            error=fallback_error,
            raw_output=r.stdout or "",
            stderr=r.stderr or "",
            model_output=(r.stdout or r.stderr or "").strip(),
        )
        outcome = WakeOutcome(sid, ok, fallback_error)
        return outcome if return_outcome else outcome.session_id
    result = runtime.parse_output(r.stdout, r.returncode)
    result.raw_output = r.stdout or ""
    result.stderr = r.stderr or ""
    sid = result.session_token or sid
    status = "ok" if result.ok else f"ERR:{result.error}"
    print(f"[agent_loop:{key}] woke session={sid or '(none)'} {status}", flush=True)
    print((result.text or result.error or "").strip(), flush=True)
    _record_wake(key, trigger, started_at, started_mono, sid, result.cost_usd,
                 result.usage, result.ok,
                 error=None if result.ok else (result.error or "unknown"))
    _archive_wake(
        run_id=run_id,
        key=key,
        trigger=trigger,
        started_at=started_at,
        session_id=sid,
        ok=result.ok,
        error=None if result.ok else (result.error or "unknown"),
        raw_output=result.raw_output,
        stderr=result.stderr,
        model_output=result.text or result.error or "",
    )
    outcome = WakeOutcome(sid, result.ok, None if result.ok else (result.error or "unknown"))
    return outcome if return_outcome else outcome.session_id


# --- the loop ----------------------------------------------------------------


class ReliableInbox(Protocol):
    def peek_one(self, key: str) -> dict | None: ...

    def wait(self, key: str, timeout: float) -> bool: ...

    def ack_one(self, key: str) -> None: ...


def agent_loop(*, key: str, session_file: str | os.PathLike, heartbeat: float,
               charter_path: str | None = None, mcp_config: str | None = None,
               system_prompt: str | None = None,
               model=UNSET, effort=UNSET, provider: str | None = None,
               inbox: ReliableInbox,
               session_mode: str = "fresh", idle: str = "stop",
               strategic: bool = False,
               retry_backoff: float = 5.0,
               wake_completed: Callable[[dict], object] | None = None,
               context_loader: Callable[[], dict],
               prompt_builder: Callable[[dict | None, str, str, str], str] | None = None,
               wake_gate: Callable[[dict | None, dict], bool] | None = None,
               completion_owns_ack: bool = False) -> None:
    """Run one resident actor against the V7 Hub boundary.

    ``peek_one`` plus explicit completion preserves the FIFO head on runtime or
    context failure. Production passes ``RemoteInbox`` and lets the Hub own the
    acknowledgement transaction; tests may inject an equivalent facade.
    """
    resume = session_mode == "resume"
    fresh = not resume
    session_id = load_session(session_file) if resume else None
    # Normal resident startup uses AgentSpec's fully assembled system prompt.
    # AGENT_CHARTER remains an explicit operator/debug override, but a stale
    # path or empty file must not erase the production prompt.
    override_prompt = _read_charter(charter_path)
    charter = override_prompt if override_prompt is not None else system_prompt
    print(f"[agent_loop:{key}] start heartbeat={heartbeat}s "
          f"session={'fresh-per-wake' if fresh else (session_id or '(new)')}",
          flush=True)
    while True:
        event = inbox.peek_one(key)
        if event is None:
            inbox.wait(key, heartbeat)
            event = inbox.peek_one(key)
        try:
            context = context_loader()
            if not isinstance(context, dict):
                raise ValueError("wake context must be an object")
            if prompt_builder is None:
                objective = context.get("objective")
                objective_reviews_in_flight = context.get("objective_reviews_in_flight")
                if not isinstance(objective_reviews_in_flight, list):
                    raise ValueError("objective_reviews_in_flight must be a list")
                notes = context.get("notes")
                wake_capabilities = tuple(context.get("capabilities") or ())
            else:
                objective = None
                objective_reviews_in_flight = []
                notes = None
                wake_capabilities = ()
            wake_allowed = wake_gate(event, context) if wake_gate is not None else True
            if not isinstance(wake_allowed, bool):
                raise ValueError("wake gate must return a boolean")
        except Exception as exc:  # noqa: BLE001 — retain FIFO head and retry
            print(
                f"[agent_loop:{key}] context load failed ({exc!r}); retaining wake",
                flush=True,
            )
            time.sleep(max(0.0, retry_backoff))
            continue
        if not wake_allowed:
            print(
                f"[agent_loop:{key}] wake suppressed by gate; "
                f"message={event.get('id') if event else '(heartbeat)'} retained",
                flush=True,
            )
            if event is not None:
                time.sleep(max(0.0, heartbeat))
            continue
        trigger = "event" if event is not None else "heartbeat"
        wake_id = f"wake-{uuid.uuid4().hex}"
        print(f"[agent_loop:{key}] wake ({trigger})", flush=True)
        print(f"[agent_loop:{key}] objective: "
              + (f"injected {len(objective)} chars" if objective else "none"),
              flush=True)
        now = datetime.now(timezone.utc).isoformat()
        if prompt_builder is None:
            prompt = build_v7_wake_prompt(
                event,
                actor_id=key,
                wake_id=wake_id,
                trigger=trigger,
                objective=objective,
                notes=notes,
                capabilities=wake_capabilities,
                now=now,
                objective_reviews_in_flight=objective_reviews_in_flight,
                idle=idle,
                strategic=strategic,
            )
        else:
            prompt = prompt_builder(event, wake_id, trigger, now)
        outcome = wake(
            session_id,
            prompt,
            key=key,
            charter=charter,
            mcp_config=mcp_config,
            model=model,
            effort=effort,
            provider=provider,
            trigger=trigger,
            return_outcome=True,
            run_id=wake_id,
        )
        assert isinstance(outcome, WakeOutcome)
        if not outcome.ok:
            print(
                f"[agent_loop:{key}] wake failed; retaining "
                f"message={event.get('id') if event else '(heartbeat)'} for retry",
                flush=True,
            )
            time.sleep(max(0.0, retry_backoff))
            continue
        completion = {
            "agent_id": key,
            "message_id": event.get("id") if event else None,
            "wake_id": wake_id,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        if completion_owns_ack and wake_completed is not None:
            try:
                wake_completed(completion)
            except Exception as exc:  # noqa: BLE001 — remote ack is one Hub transaction
                print(
                    f"[agent_loop:{key}] wake completion failed ({exc!r}); retaining wake",
                    flush=True,
                )
                time.sleep(max(0.0, retry_backoff))
                continue
        else:
            if event is not None:
                inbox.ack_one(key)
            if wake_completed is not None:
                try:
                    wake_completed(completion)
                except Exception as exc:  # noqa: BLE001 — local ack already durable
                    print(
                        f"[agent_loop:{key}] WARN: wake_completed failed ({exc!r})",
                        flush=True,
                    )
        sid = outcome.session_id
        if fresh:
            continue      # token dropped on purpose; telemetry already has it
        session_id = sid
        if session_id and load_session(session_file) != session_id:
            # session-id persistence is only for cross-restart resume; in-memory
            # session_id already carries continuity for this process, so a write
            # failure must NOT kill the loop.
            try:
                save_session(session_file, session_id)
            except OSError as e:
                print(f"[agent_loop:{key}] WARN: could not persist session id: {e}",
                      flush=True)


def _role_config(key: str) -> tuple:
    """Resolve (provider, model, effort, mcp_config, session_mode, idle,
    strategic, system_prompt) from the fixed AgentSpec selected by
    ``AGENT_SPEC`` (falling back to ``agents/<AGENT_KEY>.yaml``).

    provider (07-07 codex-runtime): the yaml's runtime pick; no yaml / bad
    yaml → None (wake then uses the claude default).
    model/effort: yaml override; a missing key stays UNSET so the runtime
    adapter applies ITS fleet default (the constants live in each adapter
    since 07-07 codex-runtime); explicit `null` → None (flag omitted →
    account/CLI default).
    mcp_config (07-03 mcp-loadout): the yaml's per-role baseline, resolved
    against the yaml's own directory (spec.resolve — absolute paths pass
    through); no yaml → None (main() then falls back to DEFAULT_MCP_CONFIG).
    session_mode (issue #207): "fresh" | "resume"; missing yaml / missing key
    / unknown value → "fresh" (resume is the opt-in exception, and the
    never-brick degradation direction is lose-continuity, not brick).
    idle (07-08 proactive-idle): "stop" | "proactive"; missing yaml / missing
    key / unknown value → "stop" (proactive is the opt-in exception, and the
    degradation direction is stay-quiet, not brick).
    strategic (07-11 opportunity-viability-redteam): bool; missing yaml / key
    / non-bool → False (the opt-in can never leak into another role).
    system_prompt: AgentSpec's deterministic shared-fragments-then-charter
    assembly; missing yaml / bad asset → None.
    ANY failure → WARN + defaults so a bad template does not brick the loop."""
    agents_dir = os.environ.get(
        "AGENTS_DIR",
        "/opt/hacksome/hacksome/stages/build/assets/agents",
    )
    path = os.environ.get("AGENT_SPEC") or os.path.join(agents_dir, f"{key}.yaml")
    if not os.path.isfile(path):
        return None, UNSET, UNSET, None, "fresh", "stop", False, None
    try:
        from hacksome.stages.build.agent_runtime.spec import AgentSpec
        spec = AgentSpec.load(path)
        mcp = spec.resolve(spec.mcp_config) if spec.mcp_config else None
        session_mode = spec.session
        if session_mode not in ("fresh", "resume"):
            print(f"[agent_loop] WARN: session mode {session_mode!r} unknown — "
                  "waking fresh", flush=True)
            session_mode = "fresh"
        idle = spec.idle
        if idle not in ("stop", "proactive"):
            print(f"[agent_loop] WARN: idle mode {idle!r} unknown — "
                  "idling quiet", flush=True)
            idle = "stop"
        strategic = spec.strategic
        if not isinstance(strategic, bool):
            print(f"[agent_loop] WARN: strategic mode {strategic!r} is not a "
                  "boolean — strategic wake prompts disabled", flush=True)
            strategic = False
        system_prompt = spec.read_system_prompt()
        return (spec.provider, spec.model, spec.effort, mcp, session_mode, idle,
                strategic, system_prompt)
    except Exception as e:  # noqa: BLE001 — defaults over brick
        print(f"[agent_loop] WARN: role yaml config unusable ({e!r}) — "
              "fleet defaults", flush=True)
        return None, UNSET, UNSET, None, "fresh", "stop", False, None


def main() -> None:
    """Boot one V7 resident actor from a fixed template and bound Hub client."""
    key = os.environ.get("AGENT_KEY")
    if not key:
        raise SystemExit("AGENT_KEY is required")
    charter_path = os.environ.get("AGENT_CHARTER")
    session_file = os.environ.get("AGENT_SESSION_FILE", "/tmp/foundagent-session-id")
    heartbeat = int(os.environ.get("AGENT_HEARTBEAT_SECS", "900"))
    (provider, model, effort, role_mcp, session_mode, idle,
     strategic, role_prompt) = _role_config(key)
    # AGENT_MCP remains an operator/debug override; normal V7 startup resolves
    # the immutable Team role template selected by AGENT_SPEC.
    mcp_config = os.environ.get("AGENT_MCP") or role_mcp or DEFAULT_MCP_CONFIG
    from hacksome.stages.build.control.control_client import (
        HubClient,
        RemoteInbox,
        load_wake_context,
        notify_wake_completed,
    )

    client = HubClient()
    inbox = RemoteInbox(client)
    retry_backoff = float(os.environ.get("AGENT_RETRY_BACKOFF_SECS", "5"))
    prompt_source = f"override:{charter_path}" if charter_path is not None else "agent-spec"
    print(f"[agent_loop] boot key={key} provider={provider or DEFAULT_PROVIDER} "
          f"charter={prompt_source} mcp={mcp_config} model={model} "
          f"effort={effort} objective=hub inbox=hub session={session_mode} "
          f"idle={idle} strategic={str(strategic).lower()}",
          flush=True)
    agent_loop(key=key, session_file=session_file, heartbeat=heartbeat,
               charter_path=charter_path, system_prompt=role_prompt,
               mcp_config=mcp_config,
               model=model, effort=effort, provider=provider,
               session_mode=session_mode, idle=idle, strategic=strategic,
               retry_backoff=retry_backoff, inbox=inbox,
               context_loader=lambda: load_wake_context(client),
               wake_completed=lambda details: notify_wake_completed(details, client),
               completion_owns_ack=True)


if __name__ == "__main__":
    main()
