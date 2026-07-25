# Repository Stage Reorganization — Implementation Plan

## Phase 0 — Freeze Evidence and Inventory

- [ ] 记录当前 `main`、完整质量门和 CLI help snapshot。
- [ ] 从 `ops entrypoint → imports → resources` 生成 Build active dependency closure。
- [ ] 分类 `buildfactory/` 文件：active、test-only legacy、tooling duplicate、
      mutable/secret boundary。
- [ ] 记录 Creative frozen-run fixtures 与 package resource manifest。
- [ ] 不移动任何代码，先审核删除清单和兼容清单。

Validation:

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy src
.venv/bin/python -m compileall -q src tests
CODEX_HOME=/private/tmp/hacksome-test-codex-home \
  .venv/bin/python -m unittest discover -s tests -q
node --check src/hacksome/review_ui/app.js
buildfactory/.venv-cua/bin/python -m pytest \
  buildfactory/agent/tests buildfactory/orchestration/tests -q
git diff --check
```

## Phase 1 — Remove Vendored Workspace Noise In Place

- [ ] 删除 `buildfactory/.trellis/.agents/.claude/.cursor/.codex` 与嵌套 AGENTS/CLAUDE
      配置；根 Trellis 成为唯一开发工作流。
- [ ] 删除 dependency closure 外的 Company/mail/Department/Peripheral 生产代码、
      测试、文档与配置。
- [ ] 保留 Worker/Verifier 实际复用的 runtime primitives，即使旧文件名暂时不好看。
- [ ] 更新 `buildfactory/README.md`，使其只描述当前 active Team runtime。
- [ ] 跑 Build 全量测试和 Compose config；条件允许时跑一次真实 Team smoke。

Rollback point: 此阶段不改 module path，只做减噪和死代码删除。

## Phase 2 — Create Core and Contract Boundaries

- [ ] 建立 `src/hacksome/core/`，移动真正跨 Stage 的 runner/state/prompt primitives。
- [ ] 建立 `src/hacksome/contracts/`，实现现有两类 handoff 的 typed validation。
- [ ] 保留旧根 module compatibility shim。
- [ ] 新增 contract round-trip、unknown-field、hash-drift 和 path-boundary 测试。

## Phase 3 — Rehome Ideation

- [ ] 把 Useful 根 workflow/artifact/Prompt/Schema 移到
      `stages/ideation/useful/`。
- [ ] 把 `creative/`、Creative Prompt/Schema、review UI 移到
      `stages/ideation/creative/`。
- [ ] 把 route registry 与 route-specific projection/validation 分开。
- [ ] 更新 package-data 和资源解析；保留 `hacksome.creative` shim。
- [ ] 验证现有 Useful/Creative CLI、review、resume、benchmark 与 frozen runs。

## Phase 4 — Rehome Pitch

- [ ] 把 `pitch/` 及其 Prompt/Schema 移到 `stages/pitch/`。
- [ ] 使用 `BuildToPitchInput` 记录和验证手工输入。
- [ ] 保留 `hacksome.pitch` shim 和 `hacksome pitch` CLI。
- [ ] 验证 immutable snapshot、revision loop、HTML resource boundary 和真实 Chromium
      smoke。

## Phase 5 — Internalize Build Runtime

- [ ] 创建 `stages/build/{control,agent_runtime,assets}`。
- [ ] 按 Phase 0 dependency closure 移动 active Build Python/runtime files。
- [ ] 把 Makefile、Compose、Docker 和账户模板移到 `ops/build/`。
- [ ] 统一 imports 到 `hacksome.stages.build.*`，更新 container module entrypoint、
      `PYTHONPATH`、volume mount 与 AgentSpec resource path。
- [ ] 把 Build tests 移到 `tests/stages/build/`。
- [ ] 提供短期旧 Make/module wrapper，验证后删除 `buildfactory/`。
- [ ] 跑单 Team、FAIL resume、batch drained、Verifier read-only 和容器恢复门禁。

## Phase 6 — Documentation and Final Cleanup

- [ ] 重写根 README 首屏为 Ideation → manual handoff → Build → manual handoff → Pitch。
- [ ] 为每个 Stage 写职责/输入/输出/状态/命令/验证的短 README。
- [ ] 重组测试目录并删除重复 conftest/fixtures。
- [ ] 搜索并移除非兼容用途的 `buildfactory`、Company、Department、mail 旧命名。
- [ ] 验证没有 tracked state、cookies、secrets、runs、build output 或 caches。
- [ ] 生成 wheel 并检查 Prompt/Schema/UI/Agent assets；若环境缺 build backend，
      明确记录为未验证。

## Final Gate

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy src
.venv/bin/python -m compileall -q src tests
CODEX_HOME=/private/tmp/hacksome-test-codex-home \
  .venv/bin/python -m unittest discover -s tests -q
node --check src/hacksome/stages/ideation/creative/review_ui/app.js
python -m build
git diff --check

# Build ops
make -C ops/build validate
docker compose -f ops/build/docker-compose.yml config
```

Final manual evidence:

- [ ] One Useful run fixture remains valid.
- [ ] One Creative frozen v1/v2 fixture remains valid.
- [ ] One current Creative run can reach its expected terminal/wait state.
- [ ] One Team can initialize and complete at least one Worker → Verifier cycle.
- [ ] One completed Project can produce a browser-verified Pitch deck.
