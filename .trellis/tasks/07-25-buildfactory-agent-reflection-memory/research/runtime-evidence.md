# Build Factory Reflection Memory — Runtime Evidence

## Repository state on `origin/main` (`d1cbe3c`)

- Active role specs:
  - `src/hacksome/stages/build/assets/agents/lead.yaml`
  - `src/hacksome/stages/build/assets/agents/ephemeral/team-worker.yaml`
  - `src/hacksome/stages/build/assets/agents/ephemeral/team-verifier.yaml`
- All three currently declare `skills: []`.
- Generic Skill copy/reconcile already exists in
  `src/hacksome/stages/build/agent_runtime/loadout.py` and is exercised by
  `tests/stages/build/agent_runtime/test_loadout.py`.
- Production tests currently assert that every active role has zero Skills and
  that `assets/skills/` does not exist; these assertions must become
  Lead-only rather than being deleted wholesale.

## Current continuity and state boundaries

- Lead explicitly opts into `session: resume`; Worker and Verifier default to
  fresh sessions, with a same-Goal Worker resume only after rework.
- Lead can read/write `/project`, but its charter and wake prompt prohibit
  direct implementation and plan/status artifacts.
- `TeamLayout` exposes only `/project` to model runtimes. Ledger, inbox,
  workers, reviews, control, sessions and telemetry remain control-plane state.
- TeamHub currently exposes only `create_goal`, `list_my_goals` and
  `cancel_goal` to Lead.
- `wake_context` returns identity and capabilities but no project memory.
- `goal_batch_drained` carries only `last_enqueue_seq`.
- The Lead-specific custom prompt builder currently discards the loaded
  `wake_context`; memory injection therefore requires an explicit data-flow
  change rather than only adding a Hub field.

## Observed four-Team behavior

Local resident telemetry for ShiftMeet, Handoff Rehearsal, YuYe and CPAP
Rehearsal showed:

- first successful Lead completion at 70,465–95,402 cumulative input tokens;
- structurally identical first action: inspect the two initializer references,
  find no implementation, create a broad first vertical-slice Goal;
- all 31 observed post-initial actionable wakes explicitly reread README;
- all 35 actionable wakes called `list_my_goals`;
- 31/35 listed the project tree and 27/35 searched source;
- later per-wake deltas derived from adjacent cumulative session snapshots
  commonly reached roughly 0.5–1.5 million input tokens.

Codex `turn.completed.usage` in these resumed sessions is a cumulative thread
snapshot. It must be differenced within one session before being described as
per-wake usage. Failed attempts without a completed snapshot prevent exact
attribution.

## Existing pattern worth reusing carefully

An older Company runtime had private replace-oriented Notes capped at 12,000
characters and accessed through Hub methods. The active Team runtime removed
that API. The useful properties are controller ownership, atomic replace and
no raw mount. The missing properties that this task must add are:

- UTF-8 byte rather than character cap;
- stable structured sections;
- compare-and-swap revision;
- Goal-sequence freshness;
- metadata-only telemetry and request redaction;
- explicit no-op/missing observability;
- untrusted-derived-data prompt boundary;
- Lead-only role scope.

## Architectural conclusion

The problem is not simply the absence of another Markdown file. It is the
combination of indefinite Lead session resume, repeated full-state
reconstruction, no bounded semantic checkpoint and no changed-state projection.

This task intentionally solves only the bounded checkpoint and Skill behavior.
Session rotation and Goal summary/delta APIs remain follow-up work so that the
first rollout can measure memory quality and failure modes independently.
