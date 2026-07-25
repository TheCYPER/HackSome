# Current Repository Inventory

Recorded on 2026-07-25 before implementation.

## Quality baseline

- Root package: 299 `unittest` tests passed.
- BuildFactory: 362 `pytest` tests passed.
- `ruff check src tests`, `mypy src`, `compileall src tests`,
  `node --check src/hacksome/review_ui/app.js`, and `git diff --check` passed.

These numbers are the pre-migration comparison point, not the final target test
layout.

## Tracked layout

- `buildfactory/`: 815 tracked files.
- `src/hacksome/`: 79 tracked files.
- root `tests/`: 31 tracked files.
- Copied BuildFactory tool metadata accounts for 688 tracked files:
  `.trellis/` 530, `.claude/` 53, `.cursor/` 52, `.agents/` 46, `.codex/` 7.

The copied tool metadata is not part of the product runtime and may be deleted
as an exact, pre-counted scope.

## Active Build entrypoints

The current operator surface invokes:

- `orchestration.team_store` from `buildfactory/Makefile`
- `orchestration.team_hub` from `buildfactory/docker-compose.yml`
- `orchestration.lead_loop` through `AGENT_LOOP_MODULE`
- `orchestration.worker_manager`
- `orchestration.verifier_runtime`
- `agent.resident_loadout` from `vm/docker/agent_startup.sh`

Starting from those entrypoints, static local imports reach the following
runtime modules:

- `agent`: `credentials`, `loadout`, `runner`, `resident_loadout`, `spec`, and
  the `runtimes` package (`base`, `claude_code`, `codex`)
- `orchestration`: `agent_loop`, `control_client`, `inbox`, `lead_loop`,
  `method_adapter`, `run_logs`, `runtime_materialization`, `runtime_store`,
  `scheduler`, `team_http`, `team_hub`, `team_scheduler`, `team_store`,
  `verifier_manager`, `verifier_runtime`, and `worker_manager`

The active shell/runtime assets additionally include:

- `agent/browser_mcp.sh` and `agent/proxy_env.sh`
- `agents/lead.yaml`
- `agents/ephemeral/team-worker.yaml`
- `agents/ephemeral/team-verifier.yaml`
- referenced charters/shared prompt fragments under `agents/assets/`
- `agents/mcp/ceo.json` and `agents/mcp/verifier-v7.json`
- `vm/docker/agent_startup.sh`
- `orchestration/Dockerfile.control`

The Docker image build sources under `vm/` remain operator assets when retained;
they belong under `ops/build/docker/`, not inside the Python package.

## Mutable and secret-bearing paths

`buildfactory/accounts/README.md` is tracked, but account payloads such as
`secrets.env`, `codex-auth.json`, cookies, and service-account JSON are ignored.
`buildfactory/state/` and local VM state are also ignored.

When the Build operator surface moves to `ops/build/`, equivalent root/ops ignore
rules must continue to exclude account credentials, team state, local env files,
browser state, and generated VM artifacts. No ignored payload should be moved,
staged, or added to package data.

## Migration boundary

- Production Python must move under `src/hacksome/`.
- Compose, Makefile, Dockerfiles, startup scripts, templates, and account
  instructions belong under `ops/build/`.
- Tests for the active Build dependency closure move under
  `tests/stages/build/`.
- Legacy Company/mail/Department/Peripheral modules and their tests are removed
  only when no active entrypoint, dynamic loader, asset, or retained test imports
  them.
- Ideation-to-Build and Build-to-Pitch remain explicit manual handoffs.
