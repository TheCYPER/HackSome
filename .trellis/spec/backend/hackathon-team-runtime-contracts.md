# Hackathon Team Runtime Contracts

> Active backend contract for the autonomous `Lead → Worker → Verify` product
> build loop. Production Python and Agent assets live under
> `src/hacksome/stages/build/`; operator configuration lives under `ops/build/`.

## 1. Runtime boundary

One approved Idea Card creates one Team. The Team mounts only its own
`ops/build/state/<team>/project/` at `/project`. The two files under
`project/reference/` initialize the Team but do not freeze its direction.

The only production AgentSpec manifests are
`src/hacksome/stages/build/assets/agents/lead.yaml`,
`src/hacksome/stages/build/assets/agents/ephemeral/team-worker.yaml`, and
`src/hacksome/stages/build/assets/agents/ephemeral/team-verifier.yaml`. The
generic materialization framework remains: Worker and Verifier declare
`skills: []`, while Lead alone declares the bundled `maintain-lead-brief`
Skill for its controller-owned reflection checkpoint.

The deterministic control plane owns Goal, Worker, review, command, session,
memory, and telemetry state. Model runtimes may change anything under
`/project`, but they do not mutate control-plane files directly.

The active v1 loop is:

```text
no active Goal → Lead wake → one or more Goals
Goal → one bound Worker turn → one Verifier review
FAIL → same Worker lifecycle resumes
PASS → Goal closes
no active Goal → next Lead wake
```

There is one Worker slot per Team. A Lead may create multiple Goals; the Hub
queues them rather than treating the slot as a product-selection mechanism.

### 1.1 Lead reflection checkpoint

#### 1. Scope / Trigger

`LEAD_REFLECTION_MEMORY_ENABLED=1` enables one bounded, controller-owned
orientation snapshot for the long-running Lead. The default is `0`. The Lead
receives the current projection before every permitted wake and must evaluate
exactly one `replace` or `no_op` checkpoint before a successful wake ends.
`goal_batch_drained`, a material project change, a new decision/risk/hypothesis,
and a reusable error lesson are explicit triggers.

Worker and fresh Verifier never receive the Skill, projection, capability, or
memory mount. Lead declares `session: refresh`: every resident wake opens a
new runtime session and restores orientation from the bounded brief, current
Goal projection, and live inspection. Runtime keeps `fresh` as the compatible
default and `resume` as an explicit opt-in used only where continuity is
required; Worker same-Goal resume and Verifier fresh behavior are unchanged.

#### 2. Signatures

```python
LEAD_BRIEF_MAX_BYTES = 8192

class LeadBriefStore:
    def read(
        self,
        *,
        current_goal_seq: int,
        goal_state_sha256: str,
        enabled: bool,
    ) -> dict: ...

    def checkpoint(
        self,
        request: LeadBriefCheckpointRequest,
        *,
        current_goal_seq: int,
        goal_state_sha256: str,
    ) -> dict: ...
```

Enabled `wake_context` adds `lead_brief` with schema version, revision, bounded
Markdown or `None`, UTF-8 byte count/hash, observed/current Goal sequence,
Goal-state fingerprint, stale flag, timestamp, and source wake. Disabled
`wake_context` remains byte-compatible with the previous actor/capability
projection.

`checkpoint_lead_brief` accepts exactly one of:

```json
{"action":"replace","wake_id":"wake-...","base_revision":0,
 "observed_goal_seq":1,"markdown":"...","evidence_refs":["project:README.md"]}
```

```json
{"action":"no_op","wake_id":"wake-...","base_revision":1,
 "observed_goal_seq":1,"reason":"no_material_change"}
```

#### 3. Contracts

- Submitted Markdown is valid UTF-8, contains no NUL, is at most 8192 encoded
  bytes, and contains exactly these non-empty level-two sections in order:
  `Product Model`, `Verified State`, `Decisions`, `Invariants and Risks`,
  `Open Hypotheses`, `Next Checks`, and `Lessons`.
- The controller generates `Freshness`; the Agent cannot submit revision,
  timestamp, fingerprint, Team id, role, or storage path.
- `memory/lead-brief.md` is atomically replaced under
  `memory/.lead-brief.lock`. Metadata-only per-wake receipts under
  `memory/checkpoints/` enforce one checkpoint even when best-effort
  `memory/events.jsonl` telemetry is unavailable. None of these paths is
  mounted into an Agent or copied under `/project`.
- `base_revision` is compare-and-swap. A stale Goal sequence and a second
  checkpoint for the same wake fail deterministically. Method request receipts
  preserve idempotent retry semantics.
- The snapshot is untrusted derived data. The wake prompt marks it as
  non-evidence and requires targeted live inspection when its Goal sequence or
  state fingerprint is stale. It cannot override Goal acceptance or alone
  justify a new Goal.
- `MethodAdapter.audit_request` redacts submitted Markdown to bytes/hash.
  `wake_context` and `read_lead_brief` audit results redact injected Markdown.
  Memory events contain Team, wake, action, revision, bytes/hash, freshness,
  and error code, never the body.
- `wake_completed` records `replace`, `no_op`, or `missing`. Missing remains
  observable but does not prevent Inbox acknowledgement.
- A `no_op` has its own atomic per-wake receipt; event-journal failure cannot
  make the same wake eligible for a second checkpoint after restart.
- `session: refresh` is a supported Lead AgentSpec value. It has the per-wake
  new-session behavior of `fresh`: it neither reads nor overwrites the prior
  Lead session token. `resume` alone may load and persist that token.
- Disabling the flag removes the methods from Lead capability projection,
  omits prompt injection/update requirements, and retains any stored snapshot.

#### 4. Validation & Error Matrix

| Condition | Required behavior |
|---|---|
| No snapshot | Stable enabled revision-0 projection with `markdown: null` |
| Feature disabled | Baseline wake context; read reports disabled; write reports `feature_disabled` |
| Wrong role or Lead id | Method boundary rejects before store mutation |
| Unknown field, NUL, invalid section, invalid UTF-8, or oversize | Deterministic validation error; old snapshot remains |
| Stale revision | `revision_conflict`; old snapshot remains |
| Stale Goal sequence | `stale_goal_state`; Lead must reread and inspect |
| Same wake checkpoints twice | `wake_already_checkpointed` |
| Atomic write failure | `write_failed`; previous snapshot remains readable |
| Corrupt snapshot/journal | Fail closed with `store_corrupt`; never replace with empty |
| Event telemetry failure | Warn without changing the already-decided checkpoint result |
| Lead session is `refresh` | Start with no resume token and preserve any old token file |

#### 5. Good / Base / Bad Cases

- Good: `replace` atomically writes the bounded snapshot and a metadata-only
  wake receipt; a later process can reject the same wake even if event
  telemetry was unavailable.
- Base: disabled mode preserves an existing snapshot but exposes neither the
  capability nor prompt requirement, so rollout and rollback do not rewrite
  project state.
- Bad: use `events.jsonl` as the source of truth for whether a wake
  checkpointed. It is best-effort telemetry, so append failure would permit a
  duplicate after restart.
- Bad: copy the brief into `/project` or mount `memory/` into Lead. Either
  turns derived orientation into product evidence and bypasses the Hub
  validation/audit boundary.

#### 6. Tests Required

- `tests/stages/build/control/test_lead_brief.py`
  - assert schema/size/section validation, compare-and-swap, stale Goal
    rejection, atomic write preservation, and per-wake exactly-once receipts;
  - force event append failure, reconstruct the store, and assert both
    duplicate rejection and wake-completion recovery.
- `tests/stages/build/control/test_method_adapter.py`
  - assert request/result audit redaction and idempotent request receipts.
- `tests/stages/build/control/test_agent_loop_v7.py`
  - assert enabled injection, stale marking, checkpoint instruction, disabled
    byte-compatible wake context, and two `refresh` wakes that neither reuse
    nor overwrite a historical token.
- `tests/stages/build/agent_runtime/test_team_loadout.py`
  - assert only Lead materializes `maintain-lead-brief`, including both
    `SKILL.md` and `agents/openai.yaml`.

#### 7. Wrong vs Correct

Wrong:

```python
already_checkpointed = find_event(memory / "events.jsonl", wake_id)
```

This treats optional observability as durable correctness state.

Correct:

```python
already_checkpointed = (memory / "checkpoints" / f"{wake_id}.json").exists()
append_event_best_effort(...)
```

The atomic metadata receipt owns exactly-once recovery; the body stays only in
the bounded snapshot, and event logging cannot change a decided checkpoint.

## 2. Shared system prompt assembly

### 2.1 Scope / Trigger

Use this contract whenever a Team role needs stable guidance shared across
multiple final system prompts. Shared guidance must be injected before the
turn; requiring the Agent to discover or read a document later is not
equivalent.

### 2.2 Signatures

```python
@dataclass
class AgentSpec:
    system_prompt_fragments: list[str]
    system_prompt: str | None

    def read_system_prompt(self) -> str | None: ...

def agent_loop(
    *,
    charter_path: str | None = None,
    system_prompt: str | None = None,
    ...,
) -> None: ...
```

`_role_config(key)` returns the assembled system prompt as its final tuple
element for resident runtimes. Ephemeral runtimes call
`AgentSpec.read_system_prompt()` through `run_task`.

### 2.3 Contracts

Each production role explicitly declares the same shared tool-use asset before
its role charter:

```yaml
system_prompt_fragments:
  - <relative-path>/shared-tool-use.md
system_prompt: <relative-path>/<role>-charter.md
```

`AgentSpec.read_system_prompt()` resolves every path relative to that role's
YAML, joins the declared fragments in order, then appends `system_prompt`. The
shared content therefore has one source file while every final Lead, Worker,
and Verifier system prompt contains it directly.

Environment contract:

- `AGENT_SPEC`: normal production source for provider, runtime settings, and
  the fully assembled resident system prompt.
- `AGENT_CHARTER`: optional operator/debug file override. Production Team
  Compose must not set it.
- A valid non-empty `AGENT_CHARTER` replaces the assembled prompt.
- A missing or empty override falls back to the assembled `AGENT_SPEC` prompt,
  so a stale debug setting cannot erase role or tool-use guidance.

The shared asset describes Git, `gh`, `vercel`, meaningful commit/push
checkpoints, authorized Repo/deployment work, and durable Markdown under
`/project`. It describes capabilities but never expands the following role
charter's permissions. Lead remains judgment/delegation-only and Verifier
remains read-only.

### 2.4 Validation & Error Matrix

| Condition | Required behavior |
|---|---|
| No fragments and no role charter | `read_system_prompt()` returns `None` |
| One or more fragments | Resolve in declaration order relative to the role YAML |
| Role charter present | Append it after every shared fragment |
| Declared asset missing/unreadable | Loading the assembled prompt fails; resident config logs a warning and degrades through its existing defaults |
| `AGENT_CHARTER` points to non-empty readable file | Use that file as the explicit override |
| `AGENT_CHARTER` missing, absent, or empty | Use the assembled AgentSpec prompt |
| Shared text conflicts with role charter | Role charter controls permission; shared text does not grant mutation authority |

### 2.5 Good / Base / Bad Cases

- Good: Lead, Worker, and Verifier each reference one
  `shared-tool-use.md`; changing that file updates every final prompt.
- Base: an older or test-only AgentSpec declares only `system_prompt`; its
  final prompt remains the single role charter byte content.
- Bad: copy the same tool-use prose into three charters. Later edits can drift
  and one role may lose a safety qualification.
- Bad: set production `AGENT_CHARTER` to the Lead charter. This bypasses
  AgentSpec assembly and drops all declared fragments.

### 2.6 Tests Required

- `tests/stages/build/agent_runtime/test_spec.py`
  - assert shared fragments precede the role charter;
  - assert all active roles resolve the same single asset;
  - assert required tool guidance and role-boundary text occur in final prompts.
- `tests/stages/build/agent_runtime/test_team_loadout.py`
  - assert the shared asset is present without adding any Skill.
- `tests/stages/build/control/test_agent_loop_v7.py`
  - assert resident Lead receives the assembled prompt;
  - assert a valid override wins;
  - assert missing and empty overrides fall back.
- `tests/stages/build/control/test_compose_accounts.py`
  - assert production Compose sets `AGENT_SPEC` and omits `AGENT_CHARTER`.

### 2.7 Wrong vs Correct

Wrong:

```python
charter = _read_charter(os.environ.get("AGENT_CHARTER"))
```

This resident-only path bypasses `AgentSpec.read_system_prompt()` and can erase
shared guidance.

Correct:

```python
override_prompt = _read_charter(charter_path)
charter = override_prompt if override_prompt is not None else system_prompt
```

The `system_prompt` argument is the content assembled from `AGENT_SPEC`; the
optional file override replaces it only when it resolves to non-empty content.

## 3. Goal and Worker continuity

`WorkerLaunch` binds these values:

```python
WorkerLaunch(
    goal_id: str,
    worker_id: str,
    intent: str,
    acceptance: str | None,
    owner_department: str,
    command_id: str,
)
```

For the lifetime of a Goal, retries and Verifier rework preserve:

- `worker_id`
- host-mounted Worker home and workspace
- `/project`
- the latest authoritative runtime `session_token`, when one was emitted

Hackathon Team Goal records do not need `owner_department`. Container recovery
uses the owner already persisted in the Worker lifecycle. Team mode may fall
back to the fixed `lead` owner only when an older lifecycle lacks the field.
Worker and Verifier module entrypoints are Team-only; no environment fallback
may restore the retired Company product mode.

Positive example: a missing `worker-20` container is recreated from
`worker-20.json` with the same Goal, owner, home, workspace, and session token.

Negative example: reading `persisted_goal["owner_department"]` in Team mode
raises `KeyError` and causes the same resume command to retry forever.

## 4. Turn timeout is not a Goal deadline

The Worker turn watchdog is an operational fault boundary, not a product
deadline or completion state. The default is six hours
(`WORKER_TURN_TIMEOUT_SECS=21600`). A Team and its Goal may continue across any
number of turns.

`run_task(...) -> RunResult` must preserve a partial runtime event stream on
timeout:

```python
RunResult(
    ok=False,
    error="timeout",
    timed_out=True,
    session_token=<thread id if emitted>,
    raw_output=<partial JSONL>,
    stderr=<partial stderr>,
)
```

The runtime adapter parses partial JSONL before returning. In particular,
Codex emits `thread.started` near the beginning of a turn; retaining that token
allows a later `codex exec resume` to continue the same thread.

## 5. Timeout cleanup ordering

Host-side `subprocess.run(..., timeout=...)` terminates the `docker exec`
client, not necessarily Codex, browser processes, dev servers, or children
inside the Worker container. Therefore the lifecycle owner must enforce this
ordering:

```text
turn timeout
  → parse and retain partial runtime output
  → stop and remove the dedicated Worker container
  → persist Worker state as missing
  → report the failed turn to Hub
  → Hub may enqueue resume
  → recreate the same Worker lifecycle
  → resume exactly one turn
```

The Hub must never receive a timeout result while the timed-out container is
still considered runnable. Successful cleanup records `state="missing"`.
Cleanup failure records `state="create_failed"` plus `last_error`; a same-name
container prevents blind duplicate creation.

Command receipts are written only after a turn returns. If Worker Manager
restarts while a command is in flight, the command is intentionally
unreceipted but the container may still contain the old Codex process. A fresh
manager has no process-local turn claim, so reconciliation must retire any
persisted `running` Worker container before replaying that command. Within one
manager process, a per-Worker turn claim rejects concurrent `run_worker`
calls. A completed non-timeout turn returns the lifecycle to `ready`; Hub state
determines whether it proceeds to verification or rework.

Positive example: after timeout, `backend.stop(definition)` completes before
`worker_turn_finished` can cause a resume command.

Negative example: killing only `docker exec` and leaving the container in
`state="running"` permits an old Codex turn and a new resume turn to write the
same `/project` concurrently.

## 6. Verification and regression assertions

The executable contract is covered by:

- `tests/stages/build/agent_runtime/test_runner.py`
  - timeout bytes and strings are normalized;
  - partial Codex JSONL retains `thread.started`;
  - `RunResult.timed_out` is explicit.
- `tests/stages/build/control/test_worker_manager.py`
  - a timeout retires the container;
  - lifecycle state becomes `missing`;
  - recreation uses the retained session token.
  - manager restart retires an orphaned in-container turn before command
    replay.
- `tests/stages/build/control/test_v7_runtime_services.py`
  - Team resume reconstructs a missing Worker from lifecycle ownership even
    though its Goal has no `owner_department`.

Required validation:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/stages/build -q
make -C ops/build validate
```

## 7. Repository and operator boundary

### 7.1 Scope / Trigger

Use this contract whenever Build Python, Agent assets, Compose, Dockerfiles,
account paths, state paths, module entrypoints, or package data change. These
paths cross the Python distribution, host operator surface, manager containers,
and Agent containers, so a local import pass alone is insufficient.

### 7.2 Signatures

```bash
make -C ops/build init \
  TEAM=<team> \
  CHALLENGE_FILE=/absolute/challenge.md \
  IDEA_CARD_FILE=/absolute/idea-card.md

make -C ops/build up TEAM=<team> ACCOUNT=<account>
make -C ops/build validate

# opt-in local-network image sources; no account/state path is changed
make -C ops/build up-local TEAM=<team> ACCOUNT=<account>
make -C ops/build validate-local

python -m hacksome.stages.build.control.team_store ...
python -m hacksome.stages.build.control.team_hub
python -m hacksome.stages.build.control.worker_manager
python -m hacksome.stages.build.control.verifier_runtime
```

The Agent image is built from the repository root:

```bash
docker build -f ops/build/docker/agent.Dockerfile \
  -t foundagent/cua-agent:latest .
```

### 7.3 Contracts

- `src/hacksome/stages/build/` is the only Build production Python namespace.
- `ops/build/` contains Make, Compose, Dockerfiles, startup/config scripts, and
  account instructions; it must not contain production `.py` sources.
- `src/hacksome/stages/build/assets/` contains packaged AgentSpec YAML, charters,
  MCP JSON, and runtime shell assets.
- `src/hacksome/stages/build/agent_runtime/cua_mcp.py` is copied by
  `ops/build/docker/agent.Dockerfile` to `/opt/foundagent/cua_mcp.py`.
- Mutable Team state is under `ops/build/state/`; credentials and browser state
  are under `ops/build/accounts/`. Both are ignored and excluded from wheels.
- `HACKSOME_ROOT` and `BUILD_OPS_ROOT` are Compose interpolation inputs.
  Containers receive canonical `PYTHONPATH`, `FOUNDAGENT_HOST_REPO`,
  `TEAM_STATE_ROOT`, `TEAM`, `ACCOUNT`, `TEAM_NETWORK`, and `HUB_URL`.
- Worker and Verifier entrypoints always initialize `TeamLayout`, mount
  `/project`, and use one slot. `TEAM_MODE`/`COMPANY` do not select another
  product mode.
- `ops/build/docker-compose.local.yml` may override only image acquisition:
  registry/base-image build args, the locally built CUA Agent image, and
  `pull_policy`. It must not add credentials, workstation paths, state paths,
  or role/mount/lifecycle overrides.
- `ops/build/docker/Dockerfile.local` builds the optional mirrored CUA base;
  `agent.Dockerfile` accepts optional `CUA_BASE_IMAGE`, Ubuntu mirror, and npm
  registry args. Empty args preserve the canonical network behavior.

### 7.4 Validation & Error Matrix

| Condition | Required behavior |
|---|---|
| challenge or Idea Card argument missing | `make init` fails before Team bootstrap |
| `project/reference` initializer missing | `make up` fails at `check-init` |
| AgentSpec path moved without package-data update | wheel/resource test fails |
| Compose points to a non-canonical module or mount | Compose/entrypoint contract test fails |
| Worker receives control-plane mount | mount-boundary test fails |
| Verifier receives writable `/project` | mount-boundary test fails |
| account/state/credential payload becomes tracked | sensitive-path audit fails |
| production `.py` appears under `ops/build/` | repository-boundary audit fails |
| local overlay changes a state/account/mount/role field | static overlay contract test fails |
| local image arguments contain a secret or workstation path | static safety audit fails |
| namespace, Docker, mount, startup, AgentSpec, or account/state path migration deletes its compatibility path without a live smoke | migration is incomplete even when offline tests pass |
| Docker registry metadata lookup fails before a build reaches project layers | record an infrastructure failure and retry; do not report the image as built |
| live Worker or Verifier cannot start KasmVNC, `computer_server`, its model runtime, or a browser | migration fails and the compatibility path must remain |
| Verifier verdict is durably accepted before Hub cleanup terminates its still-open model process | reconcile the request receipt, Review, Goal, and method ledger as authoritative; preserve the non-zero runtime exit as cleanup evidence rather than relabeling the accepted verdict as failed |
| Verifier runtime exits non-zero without a durable verdict and matching Goal transition | live smoke fails; a runtime log alone cannot manufacture PASS/FAIL |

### 7.5 Good / Base / Bad Cases

- Good: the host checkout is mounted read-only into Agent containers at
  `/opt/hacksome/hacksome`, with `PYTHONPATH=/opt/hacksome`; managers use the
  same canonical package through the root checkout.
- Good for a high-risk migration: build both images, run an isolated disposable
  Team through a bounded real Worker → Verifier result, assert the Verifier
  mount is read-only, and separately boot the resident Lead behind a
  non-terminal-Goal wake gate before deleting the old path.
- Base: `make -C ops/build validate` checks Compose, compiles the Build package,
  and runs offline tests without starting a Team or model. This is sufficient
  for an ordinary local logic change only when no cross-container path or image
  boundary changed.
- Good: `make -C ops/build up-local` uses a local CUA image and mirror args
  while resolving the same canonical source, account, and Team state as `up`.
- Bad: copy `agent/` and `orchestration/` into `ops/build/` to make Compose
  imports work. That recreates a second Python product tree.
- Bad: build `agent.Dockerfile` from `ops/build/docker/`; its canonical Python
  `COPY src/...` source is intentionally resolved from repository-root context.
- Bad: treat Compose rendering, mocked lifecycle tests, or a headless browser
  launched directly from the image as proof that the CUA desktop runtime,
  dynamic Agent containers, model credentials, and read-only Verifier mount
  work together.
- Bad: put an account path, token, or a `/Users/...` override in the tracked
  local overlay. Network transport is the only allowed difference.

### 7.6 Tests Required

- `tests/stages/build/control/test_team_runtime.py`
  - assert canonical manager AgentSpecs;
  - assert Worker `/project` is writable and Verifier `/project` is read-only;
  - assert no control-plane mount reaches either Agent.
- `tests/stages/build/control/test_compose_accounts.py`
  - assert canonical module entrypoints, mounts, account paths, env wiring,
    local-overlay-only image acquisition, and secret-free portable Dockerfiles.
- `tests/stages/build/agent_runtime/test_mcp_assets.py`
  - assert active MCP assets resolve;
  - assert the Agent Dockerfile copies `cua_mcp.py` from `src/hacksome/`.
- Clean-wheel validation must import all four Stage resource families and load
  an active AgentSpec.
- A migration that changes any path or boundary named in section 7.3 must also
  preserve non-secret evidence from a live disposable smoke:
  - build `foundagent/control-plane` and `foundagent/cua-agent` from the current
    Dockerfiles, with the Agent image using repository-root context;
  - initialize a unique ignored Team under `ops/build/state/`;
  - start a real Hub, Worker Manager, and Verifier Manager;
  - submit one bounded Goal and observe a dynamic Worker running the rebuilt CUA
    image, a successful `computer_server` status, at least one real browser or
    Computer Use observation, and a real `submit_result`;
  - observe a fresh Verifier with read-only `/project`, a successful
    `computer_server`, and a real browser or Computer Use observation submit
    exactly one PASS or FAIL and the Goal reach the corresponding next state;
  - reconcile the exact-once `submit_result` / `submit_verdict` method events
    with the Worker, Review, and Goal records. If accepted-verdict cleanup
    terminates the still-open Verifier model process, report that non-zero run
    metadata explicitly; only the durable verdict and matching state
    transition establish success;
  - boot the Compose resident Lead on a separate disposable Team with a
    non-terminal Goal, assert the canonical `lead_loop` and
    `computer_server` are live, and assert the wake gate suppresses a model
    call;
  - stop and remove only the disposable containers and networks; keep ignored
    state/telemetry long enough to write the evidence report.

This live gate is intentionally not an unattended CI test: it consumes a local
CUA image, Docker Desktop capacity, and an ignored authenticated account. Never
copy account values or container environment dumps into tracked evidence.

### 7.7 Wrong vs Correct

Wrong:

```dockerfile
COPY cua_mcp.py /opt/foundagent/cua_mcp.py
```

This requires a production Python file inside the Docker config directory.

Correct:

```dockerfile
COPY src/hacksome/stages/build/agent_runtime/cua_mcp.py \
     /opt/foundagent/cua_mcp.py
```

Build from repository-root context so the Docker image consumes the same
canonical Python source as the rest of HackSome.

Wrong:

```bash
make -C ops/build validate
# Delete the old runtime path and report the migration complete.
```

This proves only the offline contract and Compose rendering.

Correct:

```text
offline validation
  → build both real images
  → disposable real Worker → fresh read-only Verifier verdict
  → resident Lead VM/startup wake-gate probe
  → remove the old compatibility path
```

The live sequence proves the same files, mounts, image, VM services, model
runtime, and Hub state transitions that production uses.
