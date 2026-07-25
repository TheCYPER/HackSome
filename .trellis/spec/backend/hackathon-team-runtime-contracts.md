# Hackathon Team Runtime Contracts

> Active backend contract for the autonomous `Lead → Worker → Verify` product
> build loop under `buildfactory/`.

## 1. Runtime boundary

One approved Idea Card creates one Team. The Team mounts only its own
`state/<team>/project/` at `/project`. The two files under `project/reference/`
initialize the Team but do not freeze its direction.

The only production AgentSpec manifests are `agents/lead.yaml`,
`agents/ephemeral/team-worker.yaml`, and
`agents/ephemeral/team-verifier.yaml`. All three declare `skills: []`; the
generic materialization framework remains, but BuildFactory bundles no business
Skill catalog or independent mail Compose.

The deterministic control plane owns Goal, Worker, review, command, session,
and telemetry state. Model runtimes may change anything under `/project`, but
they do not mutate control-plane files directly.

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

- `agent/tests/test_spec.py`
  - assert shared fragments precede the role charter;
  - assert all active roles resolve the same single asset;
  - assert required tool guidance and role-boundary text occur in final prompts.
- `agent/tests/test_team_loadout.py`
  - assert the shared asset is present without adding any Skill.
- `orchestration/tests/test_agent_loop_v7.py`
  - assert resident Lead receives the assembled prompt;
  - assert a valid override wins;
  - assert missing and empty overrides fall back.
- `orchestration/tests/test_compose_accounts.py`
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
Company mode must fail closed if neither lifecycle nor Goal records an owner.

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

- `agent/tests/test_runner.py`
  - timeout bytes and strings are normalized;
  - partial Codex JSONL retains `thread.started`;
  - `RunResult.timed_out` is explicit.
- `orchestration/tests/test_worker_manager.py`
  - a timeout retires the container;
  - lifecycle state becomes `missing`;
  - recreation uses the retained session token.
  - manager restart retires an orphaned in-container turn before command
    replay.
- `orchestration/tests/test_v7_runtime_services.py`
  - Team resume reconstructs a missing Worker from lifecycle ownership even
    though its Goal has no `owner_department`.

Required validation:

```bash
cd buildfactory
.venv-cua/bin/python -m pytest agent/tests orchestration/tests
```
