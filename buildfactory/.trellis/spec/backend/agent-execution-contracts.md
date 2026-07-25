# Agent Execution Contracts (containerized headless `claude` / `codex`)

> Executable contracts for running and loading a single agent inside a
> `foundagent/cua-agent` container. All entries are **spike-verified** (real
> container/CLI runs), not assumed. Re-use these in the orchestration / memory
> layers and when debugging a headless runtime in a container.
>
> Since 07-07 codex-runtime the runtime is switchable per AgentSpec. The active
> manifests are `agents/lead.yaml`, `agents/ephemeral/team-worker.yaml`, and
> `agents/ephemeral/team-verifier.yaml` with `provider: claude-code | codex`;
> callers face ONLY
> the neutral contract in `agent/runtimes/base.py` (`RunRequest`/`RunResult`/
> `Runtime`); each CLI's argv/parsing/home knowledge lives in exactly one
> adapter file (`agent/runtimes/claude_code.py`, `agent/runtimes/codex.py`).
> Scenario A/B/C below are the claude-side contracts (now enforced inside the
> claude adapter); Scenario D is the codex side.
>
> Evidence: `.trellis/tasks/06-26-agent-layer/research/agent-spike.md` (S1-S3),
> `.trellis/tasks/06-26-agent-layer/research/ac6-e2e.md` (end-to-end),
> `.trellis/tasks/07-07-codex-runtime/research/` + `agent/tests/fixtures/codex/`
> (real codex 0.142.5 captures).
> Reference impl: `agent/runner.py`, `agent/credentials.py`, `agent/loadout.py`,
> `agent/runtimes/`.

---

## Scenario A: Parse `claude -p --output-format stream-json` result

### 1. Scope / Trigger
Any code that runs headless `claude` in a container and reads its outcome
(runner, orchestration result collection, debugging a run).

### 2. Signatures
```
claude -p "<task>" --mcp-config <path> [--append-system-prompt <text>] \
       --output-format stream-json --verbose [--dangerously-skip-permissions]
```
`<path>` must be `spec.resolve(spec.mcp_config)` — AgentSpec YAML files declare
yaml-relative paths; resolving against process cwd points nowhere. The merged
adapter pins `--strict-mcp-config` and a `--resume`/`--session-id` for both
resident wakes and ephemeral Worker/Verifier turns.
Output = **NDJSON** (one JSON event per line), event sequence:
`system/init → assistant → rate_limit_event → result`. Take the **last**
`type == "result"` event.

### 3. Contracts — `result` event fields
| Field | Type | Meaning |
|-------|------|---------|
| `is_error` | bool | **the only** success/failure signal |
| `result` | str | final assistant text |
| `total_cost_usd` | float | run cost |
| `subtype` | str | ⚠️ **NOT a success signal** (see error matrix) |
| `api_error_status` | int/null | HTTP status on API error (e.g. 401) |

Derivation: `ok = not is_error`; `text = result`;
`cost_usd = total_cost_usd`; `error = api_error_status or (result if is_error)`.

### 4. Validation & Error Matrix
| Condition | Correct handling |
|-----------|------------------|
| `is_error == true`, `subtype == "success"` (real 401 case!) | `ok = False` — **trust `is_error`, never `subtype`** |
| no `result` event in stream | `ok = False`, attach stderr to `raw_tail` |
| a line fails `json.loads` | skip that line (`continue`), keep scanning |
| process timeout | `RunResult(ok=False, error="timeout")` |

### 5. Good/Base/Bad
- Good: last `result` event, `is_error=false` → `ok=True, text=result`.
- Base: API 401 → `is_error=true` even though `subtype="success"` → `ok=False`.
- Bad: deriving `ok` from `subtype == "success"` → silently reports 401 as success.

### 6. Tests Required
- Fixture from real S1 sample → assert `ok/text/cost_usd`.
- Fixture `is_error=true & subtype="success"` → assert `ok is False` (pins the trap).
- Empty output / no-result / unparsable-line / timeout → assert graceful `ok=False`.
- (`agent/tests/test_runner.py` covers these.)

### 7. Wrong vs Correct
```python
# Wrong — 401 leaks through as success
ok = ev.get("subtype") == "success"
# Correct
ok = not ev["is_error"]
```

---

## Scenario B: Container `claude` credential priority & mutual exclusion

### 1. Scope / Trigger
Injecting auth env into a container `claude` (credential seam, account wiring).

### 2. Signatures
`claude` reads auth env keys: `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`.
`claude --help`: *"Anthropic auth is strictly ANTHROPIC_API_KEY or apiKeyHelper
… (OAuth and keychain are never read)"* — but in the cua-agent image the OAuth
token **is** honored when `ANTHROPIC_API_KEY` is absent.

### 3. Contracts — env keys
| Mode | Inject | Must be absent/empty |
|------|--------|----------------------|
| subscription (default) | `CLAUDE_CODE_OAUTH_TOKEN` | all other credential vars |
| api-key | `ANTHROPIC_API_KEY` | all other credential vars |

Since 07-07 the exclusion set is FOUR vars (`ALL_CREDENTIAL_VARS`):
`CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, `CODEX_API_KEY`,
`OPENAI_API_KEY` — `injection_env()` blanks every var the active source does
not own, so a claude run can never pick up a codex key and vice versa
(`OPENAI_API_KEY` is never injected by any source but always cleared).

`system/init.apiKeySource`: `"none"` (OAuth), `"ANTHROPIC_API_KEY"` (api-key).

### 4. Validation & Error Matrix
| Condition | Result |
|-----------|--------|
| both `ANTHROPIC_API_KEY` + OAuth set | **api-key silently wins**, OAuth ignored → if api-key wrong, 401 even with a valid subscription |
| subscription mode but `ANTHROPIC_API_KEY` leaked into env | subscription silently overridden — hidden bug |

### 5. Good/Base/Bad
- Good: subscription run with only `CLAUDE_CODE_OAUTH_TOKEN` → `apiKeySource="none"`, ok.
- Base: api-key run with only `ANTHROPIC_API_KEY` → `apiKeySource="ANTHROPIC_API_KEY"`.
- Bad: leave a stale `ANTHROPIC_API_KEY` in env during a subscription run.

### 6. Tests Required
- `SubscriptionCreds.env()` contains only the OAuth key; `ApiKeyCreds.env()` only the api-key.
- Injection helper sets the inactive var to empty string (mutual exclusion).
- (`agent/tests/test_credentials.py`.)

### 7. Wrong vs Correct
```python
# Wrong — only adds the active key, leaves the other one leaking
env.update(creds.env())
# Correct — exclusive: blank the other credential var via `-e VAR=`
env = injection_env(creds)   # sets inactive ANTHROPIC_API_KEY/OAUTH to ""
```
> **Caveat (open):** exclusion relies on container `claude` treating
> `-e VAR=` (empty string) as unset. Re-verify when a real `ANTHROPIC_API_KEY`
> is available (AC3 api-key end-to-end is still deferred).

---

## Scenario C: Skill / hook / charter loadout landing points

### 1. Scope / Trigger
Materializing declarative skill/hook/system-prompt before `docker run`
(loadout). The table below names Claude Code's landing points;
`AgentSpec.skill_paths()` and the neutral `sync_skills` core are shared with
Codex (Scenario D), so both runtimes consume the same source directories.
`claude_home` = `vm/data/<name>/claude` (bind-mounted to container
`/home/kasm-user/.claude`).

### 2. Signatures
`materialize(spec, claude_home) -> LoadoutInfo`

### 3. Contracts — landing points
| Carrier | Landing point | Mechanism |
|---------|---------------|-----------|
| skill | `<claude_home>/skills/<name>/SKILL.md` | copy dir; subscription `claude` discovers it (appears in `init.skills`) and invokes via the `Skill` tool |
| hook | `<claude_home>/settings.json` | **merge** the snippet's `hooks` into existing settings |
| system-prompt (short) | — | passed at exec via `--append-system-prompt` |
| system-prompt (long) | `<claude_home>/CLAUDE.md` | write file |

Skill catalog contract (both runtimes):

- The current Team manifests all declare `skills: []`, and the repository does
  not bundle a production business-Skill catalog.
- A role YAML declares top-level host skill directories. Each declared tree
  has exactly one discoverable entrypoint: its root `SKILL.md`.
- A vendored control layer nested below a host remains runtime-readable as
  `upstream-SKILL.md`; it must not retain the exact basename `SKILL.md`, or a
  recursive scanner may expose it as an unrelated sibling skill.
- Host frontmatter has exactly `name` and `description`. The parsed description
  is normalized one-line text that states both capability and trigger/boundary.
  Ordinary entries target 120–180 Unicode characters; hard limits are 200 per
  item and 2000 summed across one role.

### 4. Validation & Error Matrix
| Condition | Correct handling |
|-----------|------------------|
| `settings.json` already has unrelated keys / hooks | preserve them; only append |
| `materialize` runs twice | idempotent — dedup hook entries (`json.dumps(sort_keys)`) |
| overwriting the whole `settings.json` | **forbidden** — destroys existing config |
| declared tree contains another nested `SKILL.md` | rename the internal vendored entry to `upstream-SKILL.md` and update host routing; preserve vendored bytes |

### 5. Good/Base/Bad
- Good: hook entry appended, pre-existing `foo` key + existing hooks retained.
- Base: re-run `materialize` → no duplicate hook entries.
- Bad: write `settings.json` wholesale → clobbers container's existing settings.

### 6. Tests Required
- skill lands at `skills/<name>/SKILL.md`.
- production Team manifests resolve and materialize zero Skills
  (`agent/tests/test_team_loadout.py`).
- hooks merge preserves existing keys + entries; second run does not duplicate.
- system-prompt readable / passed as append-arg.
- (`agent/tests/test_loadout.py`; dynamic proof in `ac6-e2e.md`: `[charter-ack]`,
  `Skill hello-foundagent`, `hook.log` PreToolUse fired.)

### 7. Wrong vs Correct
```python
# Wrong — clobbers container's existing settings
write_json(settings_path, snippet)
# Correct — deep-merge hooks, keep everything else, dedup on re-run
merge_hooks(settings_path, snippet["hooks"])
```

---

## Scenario D: Codex runtime (`codex exec --json`) — argv, parsing, home

### 1. Scope / Trigger
Any code touching the codex side of the runtime seam (adapter changes, codex
debugging, upgrading the pinned CLI). All contracts below are live-verified
against codex-cli **0.142.5** (fixtures: `agent/tests/fixtures/codex/`).

### 2. Signatures
```
first wake:  codex exec "<prompt>" --json --skip-git-repo-check \
               -c developer_instructions=<toml-str> [-m <model>] \
               [-c model_reasoning_effort=<toml-str>] \
               --dangerously-bypass-approvals-and-sandbox
resume:      codex exec resume <thread-id> "<prompt>" ... (same flags)
```
Defaults (adapter-owned): model `gpt-5.5`, effort `xhigh` (neutral `max` →
codex `xhigh`). `-c` values must be valid TOML — emit via
`json.dumps(ensure_ascii=False)` so any charter text survives.

### 3. Contracts — `--json` JSONL events
| Event | Meaning |
|-------|---------|
| `thread.started.thread_id` | the ONLY continuation token; resume re-emits the SAME id |
| `item.completed` + `item.type=="agent_message"` | final text (last one wins) |
| `turn.completed.usage` | token counts incl. `reasoning_output_tokens`; **no dollar cost field** → `cost_usd=None` |
| `turn.failed` / top-level `error` | failure signals |

`ok = saw turn.completed AND no turn.failed AND no top-level error`.

### 4. Validation & Error Matrix
| Condition | Correct handling |
|-----------|------------------|
| `item.type=="error"` item present | **NOT a failure** — non-fatal warnings ride this item type (e.g. skills-budget notice); a turn ending in `turn.completed` is a success |
| exit code | **never consulted for ok** — no exit-code enumeration exists, SIGINT once returned 0 (codex #4721); rc only feeds the fallback error text |
| died before `thread.started` | `session_token=None` → caller must NOT persist its own hint (`uses_session_hint=False`): a codex thread id cannot be pre-set (codex #13242/#15271/#15767), persisting the hint poisons every later `exec resume` |
| `CODEX_API_KEY` set alongside a valid `auth.json` | **the env var silently wins** (verified: invalid key + valid auth.json → 401) — same trap shape as ANTHROPIC_API_KEY vs OAuth, covered by the four-var exclusion |

### 5. Contracts — home materialization landing points
| Carrier | Landing point | Mechanism |
|---------|---------------|-----------|
| MCP servers | `$CODEX_HOME/config.toml` (`/sessions/<role>/codex/`) | rendered from the SAME `agents/mcp/<role>.json` (single source of truth); `${VAR}`/`${VAR:-def}` expanded at render time (codex config has no env expansion) → chmod 600; an isolated per-role CODEX_HOME is the strict-mcp equivalent |
| subscription auth | `$CODEX_HOME/auth.json` | seeded from `/account/codex-auth.json` (env `CODEX_AUTH_SEED`) ONLY if absent — codex refreshes tokens by rewriting the per-role copy in place |
| skills | `~/.agents/skills/<name>/` | same top-level host SKILL.md dirs as Claude Code, zero conversion; internal `upstream-SKILL.md` files remain references; manifest reconcile via the neutral loadout core |
| hooks | `$CODEX_HOME/hooks.json` | claude-symmetric reconcile via the neutral `agent/loadout.py` `snippet_hooks/merge_hooks/remove_hooks` (both runtimes' hook files share the top-level `hooks` JSON shape); manifest-driven undo, agent-added entries untouched, corrupt snippet → WARN + previous manifest record kept (earlier merges stay undoable). REQUIRES `--dangerously-bypass-hook-trust` on argv (unconditional since 07-09 codex-hooks) — without it codex SILENTLY skips hooks; accepted gap: the flag also unlocks workdir `.codex/hooks.json` (parity with claude agents editing their own settings.json) |

### 6. Tests Required
- parse_output against the three REAL fixtures (`exec_first_wake` /
  `exec_resume` / `exec_bad_model`) — never hand-write codex JSONL.
- argv matrix incl. effort translation + UNSET/None/str model semantics.
- config.toml render → parse back with `tomllib` (validity proof).
- (`agent/tests/test_codex_runtime.py`.)

### 7. Wrong vs Correct
```python
# Wrong — treats a non-fatal warning item as failure
if item.get("type") == "error": ok = False
# Wrong — persists the self-minted uuid a codex run ignored
sid = result.session_token or my_minted_uuid
# Correct — event-stream ok; only adapter-returned tokens continue a session
ok = completed and fail_msg is None and top_error is None
sid = result.session_token or (hint if runtime.uses_session_hint else incoming)
```

## Scenario E: Dual-runtime consumer surfaces (07-09 codex-parity)

### 1. Scope / Trigger
The runtime seam (Scenario A/D) keeps CLI knowledge inside the adapters — but
several CONSUMERS outside the seam still touch runtime-divergent surfaces.
Trigger: any code, prompt, charter, or skill that references transcript
layouts, cost fields, subagent mechanisms, or skills install paths. Rule:
**handle BOTH providers, or state an explicit degraded mode** (what triggers
it + what it costs) — never silently assume claude.

### 2. Contracts — the runtime-divergent surface table
| Surface | claude-code | codex | Consumer discipline |
|---------|-------------|-------|---------------------|
| native transcripts | `<agent-home>/projects/**/*.jsonl` | `<agent-home>/codex/sessions/**/*.jsonl` (different event shapes) | orchestration must not parse these as its primary result channel; adapters return `RunResult`, and `RunLogRecorder` preserves the complete runtime stream |
| cost | `RunResult.cost_usd` (dollars) + usage | `cost_usd=None`, token-only `usage` | consume `usage` verbatim (native shape, no key renames); usage is codex's only built-in cost signal |
| runtime-internal subagents | runtime-dependent | runtime-dependent | never make Company Objective review, Goal verification, or Worker lifecycle correctness depend on an optional model-internal subagent feature |
| skills install path | runtime-specific home plus `~/.agents/skills/` discovery | runtime-specific home plus `~/.agents/skills/` discovery | use the runtime adapter's `materialize_home`; Skills must not hand-install themselves into one provider's private path |

### 3. Validation & Error Matrix
| Condition | Correct handling |
|-----------|------------------|
| consumer parses one provider's native transcript as the result API | consume `RunResult` and the unified run archive instead |
| Skill requires one provider's optional internal mechanism | provide a provider-neutral route or an explicit degraded mode; the duty itself is never waived |
| telemetry/report consumer reads only cost_usd | must also read `usage` or it is blind to every codex wake |

### 4. Tests Required
- Runtime argv/result contracts: `agent/tests/test_runtimes.py`,
  `agent/tests/test_claude_runtime_golden.py`, and `agent/tests/test_codex_runtime.py`.
- Resident run archives: `orchestration/tests/test_agent_loop_v7.py`.
- Ephemeral Worker/Verifier run archives:
  `orchestration/tests/test_v7_runtime_services.py`.

### 5. Wrong vs Correct
```
# Wrong — business orchestration parses a provider's private transcript tree
events = parse_glob("<agent-home>/projects/**/*.jsonl")
# Correct — adapters return the neutral result; telemetry stores the full stream
result = runtime.parse_output(stdout, returncode)
recorder.record(raw_output=result.raw_output, metadata={"usage": result.usage})
```
