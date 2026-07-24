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

## 2. Goal and Worker continuity

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

## 3. Turn timeout is not a Goal deadline

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

## 4. Timeout cleanup ordering

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

## 5. Verification and regression assertions

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
