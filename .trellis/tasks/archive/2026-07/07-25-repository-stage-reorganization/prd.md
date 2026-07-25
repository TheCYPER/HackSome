# 整理 Ideation、Build、Pitch 仓库结构

## Goal

把 HackSome 整理为一个按产品阶段可读的模块化单体，使新开发者只看顶层目录和
根 README 就能找到 Ideation、Build、Pitch 的实现、测试、资源和运行入口，同时
保留当前行为与手工 handoff。

## Background

- 当前根 Python package 主要承载 Ideation，并把 Useful 放在 package 根、
  Creative 放在 `creative/`、Pitch 放在 `pitch/`，阶段边界不对称。
- Build 位于独立的 `buildfactory/` 快照。该目录包含 815 个受控文件，其中约
  530 个是嵌套 `.trellis/`，并复制了 `.agents/.claude/.cursor/.codex`。
- `buildfactory/README.md` 明确说明旧 Company、mail、Department、Peripheral
  源码只保留作上游参考，不进入 active HackSome Team runtime。
- Ideation 已能发布带 hash 的 Build handoff，但当前没有自动 consumer；Build
  通过 `make init` 手工接收 challenge 与 Idea Card。
- Pitch 已由根 CLI 的 `hacksome pitch` 暴露，但需要手工传入 Project、Idea Card、
  challenge 和输出目录。

## Requirements

### R1 — 一个产品、三个清晰 Stage

- HackSome 保持单仓库、单 Python distribution，不拆成三个独立仓库或三个独立
  发布包。
- 生产代码按 `ideation`、`build`、`pitch` 三个阶段组织。
- 共享 Codex runner、Prompt/Schema loader、状态与基础类型放入 `core`；跨阶段
  handoff 类型放入 `contracts`。
- `buildfactory/` 历史名字最终从工作树消失。

### R2 — Build Runtime 内部化与减噪

- BuildFactory 不再作为独立产品或可同步 vendor snapshot；它只是 HackSome 的
  Build Stage 实现来源。
- 删除嵌套 Trellis/Agent 工具配置以及未进入 active Team runtime 的上游参考代码；
  Git 历史已经承担参考存档。
- 删除前必须从 Compose/Makefile/active entrypoints 建立实际依赖闭包，不能按目录
  名猜测或误删 Worker/Verifier 复用的底层模块。
- Docker、Compose、Makefile、镜像和账户模板等运行配置放在 `ops/build/`，不与
  Python domain modules 混在同一层。

### R3 — 行为与兼容性

- 本任务不改变 Useful/Creative 的判断标准、Agent fan-out、Human Review、Build
  Team 生命周期或 Pitch 工作流。
- 现有根 CLI 命令保持可用：
  `run/status/validate/reconcile/review/resume/benchmark/pitch/doctor`。
- 旧 Python import path 在迁移期通过薄 compatibility shim 保留；shim 不复制实现。
- Creative frozen runs 仍能 `status/validate/review/resume`，资源路径迁移不得破坏
  Prompt/Schema freeze。
- Build 的 Docker mount、module entrypoint、AgentSpec asset resolution 与
  Team state 路径必须保持有效。

### R4 — Handoff 仍为手工

- Ideation → Build 继续使用当前 JSON handoff 与人工选卡。
- operator 继续显式把 challenge 与 Idea Card 传给 Build 初始化。
- Build → Pitch 继续由 operator 显式传入 Team Project、Idea Card 与 challenge。
- 文档必须把两段手工步骤写成一条完整可执行路径，不能暗示已经自动接通。

### R5 — 测试与文档也按阶段可找

- 测试目录按 `core/ideation/build/pitch/contracts` 分组，避免 Build 自带第二套
  测试世界。
- Prompt、Schema、Agent charter 等资源与所属 stage 共址。
- 根 README 首屏先显示三阶段地图、代码位置、命令入口和两段手工 handoff。
- 每个 stage 有一个短 README，说明职责、输入、输出、状态归属和验证命令。

## Acceptance Criteria

- [ ] 顶层不存在 `buildfactory/`，也不存在第二套
      `.trellis/.agents/.claude/.cursor/.codex`。
- [ ] 所有生产 Python 代码位于 `src/hacksome/`，并能从
      `core/contracts/stages/{ideation,build,pitch}` 结构定位。
- [ ] Build 非 Python 运行配置只位于 `ops/build/`，没有遗留 Company 产品入口。
- [ ] `hacksome --help` 与现有命令兼容；Useful、Creative 和 Pitch CLI 回归通过。
- [ ] 当前受支持的 Creative frozen-run fixtures 仍可离线 inspect/validate/resume。
- [ ] `make`/Compose 的 Build 初始化、配置校验以及 Lead → Worker → Verifier
      核心测试通过。
- [ ] 根 Python 质量门、Build 质量门、Node review UI 检查、package resource/wheel
      检查与 `git diff --check` 全部通过。
- [ ] README 能让不了解历史的开发者在 30 秒内回答三件事：每个 Stage 在哪里、
      如何启动、handoff 是自动还是手工。
- [ ] 迁移没有提交 runtime state、账户数据、cookies、secrets、缓存或历史 run。

## Out of Scope

- 自动消费 Ideation Build handoff。
- 自动选择 Idea Card 或自动启动 Team。
- 自动从 Team state 启动 Pitch。
- 新增 `hacksome ideate/build` CLI 产品功能；可在整理完成后独立设计。
- 改写 Idea、Build 或 Pitch 的产品判断与 Agent prompt。
- 拆分 Git 仓库、独立发布 Stage package 或同步原 BuildFactory 仓库。
- 清理或迁移用户本地已有的 `runs/`、Build Team state 与账户目录。

## Risks and Deferred Items

- Build module import 与 Compose volume 大量依赖当前位置，必须在真实 Docker
  smoke 后才能删除兼容路径。
- Creative frozen resource resolution 是最容易被“纯移动”破坏的兼容面。
- Python wheel/resource 验证需要可用 build backend；不可用时必须报告未验证，
  不能视为通过。
- compatibility shim 至少保留一个迁移周期；最终删除另开小任务。
