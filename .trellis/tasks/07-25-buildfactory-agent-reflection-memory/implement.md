# Build Factory Agent Reflection Memory Skill — Implementation Plan

## 1. Contract and Store

- [x] 新增 canonical `lead_brief` module，集中定义 schema/version/byte cap、
      section validation、projection 和 error codes。
- [x] 扩展 `TeamLayout` 的 `memory` control domain；不得增加 Agent mount。
- [x] 实现 current Markdown snapshot、CAS replace、no-op、per-wake single
      checkpoint、restart recovery 和 metadata-only events。
- [x] 为 empty、CJK bytes、NUL、section order、oversize、stale revision、
      stale Goal seq、atomic failure 和 corrupt store 增加单元测试。

## 2. Hub Methods and Audit

- [x] 增加 `read_lead_brief` 与 `checkpoint_lead_brief`，仅允许固定 Lead actor。
- [x] `wake_context` 注入 canonical brief projection；feature disabled 时移除
      capability 和内容。
- [x] 扩展 MethodAdapter 以支持可选 request audit redactor，确保 Markdown
      不进入 `telemetry/index/methods.jsonl`。
- [x] `wake_completed` 记录 replace/no-op/missing，但 missing 不阻断 ack。
- [x] 测试 cross-role/cross-team denial、strict payload、idempotency、redaction、
      restart 和 disabled behavior。

## 3. Prompt and Client Data Flow

- [x] 让 custom prompt builder 显式接收已加载的 wake context；同步更新所有
      call sites 和 tests。
- [x] Lead prompt 在 enabled 时注入 bounded/untrusted brief、revision、
      staleness 和 checkpoint completion contract。
- [x] disabled 时断言 Lead prompt 与基线 byte-identical。
- [x] 为 `control_client` 增加受限 `--markdown-file` 入口，禁止在不匹配的
      method/action 上使用。
- [x] 测试 empty/current/stale/disabled prompt 以及 CLI UTF-8/文件错误。
- [x] 将 Lead YAML 从 `session: resume` 改为显式 `session: refresh`，runtime
      将 refresh 作为受支持的 per-wake fresh mode，不产生 unknown-mode warning。
- [x] 更新 AgentSpec/agent-loop tests，断言连续 Lead wake 不传入旧 session
      token、不读取或覆盖已有 session 文件；Worker/Verifier policy 不变。

## 4. Skill Loadout

- [x] 使用 Skill Creator `init_skill.py` 创建 `maintain-lead-brief`。
- [x] 写精简 SKILL.md：触发条件、live inspection、section compression、
      replace/no-op、禁止 raw chain-of-thought/日志/backlog、Hub 命令。
- [x] Lead YAML 声明 Skill；Worker 和 Verifier 保持零 Skill。
- [x] 更新 loadout/inventory tests，验证只有 Lead materialize 新 Skill。
- [x] 运行 Skill `quick_validate.py`。

## 5. Operations and Feature Flag

- [x] Compose 的 Hub/Lead 环境和 Team pool lifecycle 传播
      `LEAD_REFLECTION_MEMORY_ENABLED`。
- [x] 保持所有 Agent mount boundary 不变。
- [x] 更新 `ops/build/README.md`，说明 flag、state path、检查方法和 rollback。
- [x] 默认先关闭；pilot 通过后再决定是否在同一 PR 中切为默认开启。
- [x] 将已验证的 local-network Compose/Docker build overlay 迁移到 canonical
      `ops/build/`，不得提交 account/state 或本机绝对路径。
- [ ] 对仍在线的四个 Compose project 使用 canonical branch source 原地重建
      static services，保留 Team state/account 和动态 Worker/Verifier。

## 6. Verification

- [x] 运行 targeted store/Hub/prompt/loadout/compose tests。
- [x] 运行完整 Build Stage tests。
- [x] 运行变更范围 lint/type/static checks 与 `git diff --check`；全库 Ruff
      仍有 313 个与本任务无关的 baseline findings。
- [ ] 使用一个临时 Team 做 restart/read/replace/no-op/disabled smoke。
- [ ] 若本机运行条件允许，在一个代表 Team 上启用不少于三次 batch-drain，
      记录 brief 质量、missing rate、重复 README/全树读取和逐 wake token delta。
- [x] 独立 Trellis check Agent 复核 PRD/spec/data-flow/role isolation。

## 7. Rollback Points

- feature flag 关闭：停止注入和更新，保留 snapshot。
- 回退 Lead AgentSpec Skill declaration：loadout reconcile 删除由模板安装的
  Skill，不触碰手工 Skill。
- Store 文件不得在 rollback 时自动删除。
- 若 prompt/Hub integration 不稳定，先关闭 feature，不回滚 Goal/Worker/
  Verifier state。

## Validation Commands

```bash
python3 -m pytest \
  tests/stages/build/control/test_lead_brief.py \
  tests/stages/build/control/test_team_runtime.py \
  tests/stages/build/control/test_agent_loop_v7.py \
  tests/stages/build/agent_runtime/test_team_loadout.py \
  tests/stages/build/control/test_compose_accounts.py

python3 -m pytest tests/stages/build
python3 -m pytest tests
python3 -m compileall -q src/hacksome/stages/build
git diff --check
```

Skill validation command在实现时从已安装 `skill-creator` 目录解析，不能在产品
代码中硬编码用户 home path。
