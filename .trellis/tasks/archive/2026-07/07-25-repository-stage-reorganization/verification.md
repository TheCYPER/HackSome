# Repository Stage Reorganization — Verification

Date: 2026-07-25

## Verified

- Repository layout:
  - shared production code is under `src/hacksome/core/`;
  - manual handoff contracts are under `src/hacksome/contracts/`;
  - product code and resources are grouped under
    `src/hacksome/stages/{ideation,build,pitch}/`;
  - Build operator configuration is under `ops/build/`;
  - tests are grouped under `tests/{core,contracts,stages}/`.
- Compatibility:
  - the existing root CLI starts and exposes the prior commands;
  - legacy Python import paths are thin shims over canonical stage modules;
  - fresh-interpreter compatibility is covered by regression tests.
- Manual boundaries:
  - Creative validates and emits `IdeaToBuildHandoff`;
  - Pitch validates `BuildToPitchInput`;
  - neither handoff starts the downstream stage automatically.
- Tracked repository cleanup:
  - `git ls-files buildfactory` returns no tracked files;
  - duplicate nested Trellis and agent tooling is removed from the proposed tree;
  - local ignored `buildfactory/accounts`, `buildfactory/state`, and
    `buildfactory/.venv-cua` data is intentionally not deleted or migrated.
- Quality gates:
  - `.venv/bin/ruff check src tests`
  - `.venv/bin/mypy src`
  - `.venv/bin/python -m compileall -q src tests`
  - root unittest discovery: 308 tests passed
  - Build pytest suite: 229 tests passed
  - `make -C ops/build validate`
  - Compose configuration rendering
  - Creative review UI JavaScript syntax check
  - `git diff --check`
  - `.venv/bin/hacksome --help`
  - `.venv/bin/hacksome pitch --help`
- Distribution:
  - an isolated wheel was built from a clean temporary copy;
  - the wheel installed into a fresh virtual environment;
  - CLI startup and Useful, Creative, Build, and Pitch resource loading passed;
  - the wheel contains canonical stage resources and no legacy root
    `hacksome/prompts`, `hacksome/schemas`, or `hacksome/review_ui` paths.
- Repository hygiene:
  - ignored account/state paths remain ignored at both old and new locations;
  - no high-confidence credential pattern or tracked runtime state was found in
    the proposed repository tree.
- Live Build Docker/VM E2E:
  - ran the current `foundagent/control-plane` build from
    `ops/build/docker/control.Dockerfile`; Docker resolved the unchanged
    content-addressed image through its existing cache;
  - rebuilt `foundagent/cua-agent` from the repository-root context using
    `ops/build/docker/agent.Dockerfile`;
  - verified the source and image copies of `cua_mcp.py` have the same SHA-256;
  - started a new isolated Team named `reorg-e2e-20260725` from the migrated
    `ops/build/` operator surface;
  - observed healthy Hub, Worker Manager, and Verifier Manager services using
    the canonical `hacksome.stages.build.*` entrypoints;
  - injected one bounded Goal, `goal-9054424f415fb943`, to avoid changing the
    product while still exercising the real runtime;
  - observed a dynamically created Worker running the rebuilt CUA image, Codex,
    KasmVNC, `computer_server`, and Computer Use commands;
  - observed the Worker create only `/project/reorg-smoke/`, serve its page,
    open it in the VM desktop Firefox, and record the visibly rendered
    `HACKSOME_REORG_VM_OK` marker;
  - observed Worker `submit_result` transition the Goal to verification and
    preserve its Codex session token;
  - observed a fresh Verifier with read-only `/project`, a separate CUA
    desktop, real Codex, and real browser inspection;
  - review `review-eca2a223f8e1abb8` submitted an evidence-backed `PASS`;
  - the Goal reached `done`, with Worker state `stopped`, and both ephemeral
    Agent containers were removed;
  - the method ledger contains exactly one `submit_result` and one
    `submit_verdict`; the Goal's `last_review_id` binds that PASS review and
    the Worker lifecycle retains a non-empty Codex session token;
  - after the PASS was durably accepted, Hub cleanup stopped the still-open
    Verifier model process. Its run metadata therefore records
    `ok=false`, `rc=137`; the request receipt, Review `passed/PASS`, Goal
    `done`, and exact-once method events are the authoritative successful
    transition. This cleanup exit is preserved rather than hidden;
  - started a second isolated Team, `reorg-lead-smoke-20260725`, to exercise the
    resident Lead path without allowing an open-ended model run;
  - observed the migrated startup script mount, AgentSpec materialization,
    healthy Lead VM/computer server, canonical resident `lead_loop`, and
    `wake suppressed by gate` while a Goal was non-terminal. That message was
    observed in the disposable container log before removal; retained state
    independently records the non-terminal Goal and successful
    `peek_message → wake_context → list_my_goals` sequence with no model method;
  - stopped and removed both test Teams' containers and networks while keeping
    their ignored state and telemetry evidence.

## Not Verified End to End

- No real-model Ideation run was executed during this migration.
- The Lead startup and wake gate were verified, but the smoke intentionally did
  not allow Lead to call a model and autonomously choose a product Goal.
- The live Worker-to-Verifier cycle used a bounded migration marker page rather
  than a full hackathon product build.
- Failure/resume continuity was covered by offline tests, not forced during the
  live smoke.
- No newly generated Pitch deck was inspected in a real Chromium session.

The automated gates and live Docker smoke establish import, resource, contract,
orchestration, package, Compose, CUA image, mount, real-model Worker/Verifier,
and VM/browser compatibility. They do not claim a full Ideation-to-Build-to-Pitch
product run or a long-running failure-recovery soak.
