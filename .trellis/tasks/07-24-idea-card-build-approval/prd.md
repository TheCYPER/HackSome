# 跨路线 Idea Card Build Approval 与自动交接

## Goal

让 `useful` 与 `creative` 在各自产出最终 Idea Card 后收敛到同一条可观察、
可恢复的 Build 启动链路：

```text
route-specific Idea workflow
  → validated final Idea Cards
  → shared Build Approval page
  → operator selects zero, one, or many Cards
  → verified handoff batch
  → one isolated Build Team per approved Card
  → bounded global Team pool
```

用户不再需要手动复制 challenge、Idea Card 或执行逐卡 `make init`。一次明确的
Approval 可以批量授权多张 Card；确认后，系统立即创建对应 Team，并在全局并发
上限内启动可用 Team，其余 Team 进入可见队列。

## Background and Confirmed Facts

- Useful 已完成 `challenge → ... → Idea Card`，但
  `UsefulIdeaWorkflow.execute()` 在发布 Card index 后结束，没有 Build handoff 或
  Approval 生命周期（`src/hacksome/workflow.py:149-191,543-602`）。
- Creative C7 已为每张 Final Idea Card 生成纯 JSON handoff，字段为
  `source_run_id`、`idea_card_id`、`idea_card_sha256`、
  `challenge_markdown` 与 `initial_idea_card_markdown`，但没有消费者或 Team
  启动 adapter（`src/hacksome/creative/report.py:994-1013`、
  `README.md:175-191`）。
- Creative C6 的人工策展决定哪些 Concept 成为 Final Idea；本任务的 Approval
  决定哪些已经有效的 Final Idea Card 获得 Build 资源。两个判断不得合并。
- Creative review server 已证明本地固定路由页面、capability cookie、Host/Origin
  校验、CSP、no-store、锁和 mutation ledger 可行，但其 Concept review domain
  不能直接冒充 Build Approval domain
  （`src/hacksome/creative/review_server.py:227-382,519-591,770-1000`）。
- BuildFactory 已真实跑通一个 Team 的
  `Lead → Worker → fresh Verifier → Lead` 循环。当前 bootstrap 只接收两份
  Markdown 并拒绝覆盖已有 reference，不校验跨 run Card identity 或 SHA
  （`src/hacksome/stages/build/control/team_store.py:69-106,148-158`）。
- 现有 Build 规划已经确定：每张 approved Card 对应一个隔离 Team；默认最多两个
  active Team；其余 selected Team FIFO 排队；未选 Card 不是质量 reject
  （`.trellis/tasks/07-23-autonomous-build-teams/prd.md:35-69,147-159`）。
- Build-side handoff schema、Team registry、global pool 和 operator
  pause/resume 仍是 planning-only
  （`.trellis/tasks/07-23-team-pool-operator/implement.md:1-25`）。
- 两条 route 的当前完成态投影不对称：Useful 以 `idea_card_ids` 暴露 Card，
  Creative 以冻结的 C7 manifest/report/result IDs 暴露 Card 与 handoff。共享层
  必须使用 route adapter，不能把任一原始 state 字段重新解释为跨路线合同
  （`research/route-neutral-post-card-contract.md`）。
- Creative completed run 的 finalization 会校验精确 source state 与 event suffix；
  Approval、Build attempt 和 Team 状态必须保存在 source run 外部，不能追加到已完成
  的 route ledger。

## Product Principles

1. **Idea 之前分叉，Idea Card 之后收敛。** Useful 与 Creative 保留独立的发现、
   gate、报告与完成语义；Build Approval 不重新评价路线质量。
2. **Approval 是资源授权，不是质量评审。** 未选、稍后再选或关闭页面都不能把
   Card 改写为 reject。
3. **一个 Card，一个隔离 Team。** Team 不共享 Repo、项目状态或 Agent session。
4. **批量授权不等于无界并发。** 一批可包含多张 Card；实际运行受 global pool
   限制，超出容量的 Team 可见地排队。
5. **确认后不靠浏览器存活。** 用户关闭页面、服务重启或进程崩溃后，已确认的
   selection 与 Team 创建意图仍可恢复。
6. **Card 是 initializer，不是永久 Objective。** Build Agent 可继续、修改或放弃
   Card；系统不强制 Idea 忠实度。

## Requirements

### R1 — Route-neutral Build candidate contract

- Useful 与 Creative 的 completed、offline-valid run 都必须投影为同一个只读
  Build candidate catalog。
- 首版只接受当前 run schema v2；历史 Useful schema v1 不自动获得 Build Approval
  兼容承诺。
- 每个候选至少包含：
  - source route ID 与 route contract version；
  - source run ID；
  - Idea Card ID、标题、精确 UTF-8 Markdown 与 SHA-256；
  - 原始 challenge Markdown；
  - route-owned handoff/artifact refs。
- Catalog 必须冻结稳定顺序和每张 Card 的内容 hash；页面提交必须绑定 catalog
  hash，防止 stale selection。
- Useful route adapter 必须根据 hash-verified Challenge 与 Card bytes 确定性物化
  Creative 已采用的五字段 handoff；不得新增另一种 Useful-only handoff，也不得让
  Build runtime import Useful/Creative 私有 Python 类型。
- Creative 必须读取并复核已经冻结的 handoff bytes，不能用语义相同的新 JSON
  代替 C7 产物；Useful 可由 route adapter 根据 hash-verified Card 确定性物化。
- zero-card completed run 是合法结果；它显示明确 empty state，不能启动 Team。

### R2 — Shared Build Approval page

- 同一个页面和后端支持 Useful 与 Creative，不按 route 复制两套 UI。
- 页面展示所有 Final Idea Card 的标题、完整内容、route/provenance、当前 Approval
  与 Team 状态。
- 用户可以：
  - 勾选一张或多张 Card；
  - select all / clear selection；
  - 对大量 Card 做批量选择；
  - 在确认前取消或修改选择；
  - 通过独立动作明确关闭 Approval 且不 Build；空 selection payload 本身不构成
    authorization 或 close。
- 确认前显示将创建、立即启动和排队的数量；确认动作必须再次明确表达“开始 Build”。
- 页面提交后显示每张 Card 的 `approved / queued / starting / active / failed`
  投影以及稳定 Team ID。
- 确认 batch 后页面保持可用并轮询异步交接/Team 状态；不能沿用 Creative C6
  “resolution 后 server 退出”的生命周期。
- 页面默认只监听 loopback；不提供公开账户系统或公网部署。
- 所有 run/Card/user 文本以安全文本方式渲染，不执行 Markdown 内 HTML、脚本或指令。

### R3 — Durable Approval ledger

- Approval 只由 operator 的显式提交产生；页面打开、超时、空 payload、刷新或服务
  重启都不能批准 Card。
- selection request 绑定 source run、catalog hash、Card ID 与 Card SHA。
- `authorize_batch` 每次必须包含 1..10 张 Card；zero-build 使用独立、显式且幂等的
  close mutation，避免把空 payload、超时或网络错误解释为用户决定。
- mutation 使用 client request hash 幂等；相同 request 重试返回原结果，不重复创建
  Team；相同 request ID 的不同 payload 必须冲突。
- 每张 Card 最多形成一个有效 Build authorization；未选 Card 不写 reject。
- 已确认 authorization、Team bootstrap intent 与逐卡交接状态持久化并可离线检查。
- ledger 与 outbox 位于 source run 外部；Approval/Build 不能向 completed Useful
  或 Creative run 追加 artifact、event、decision 或状态字段。
- 部分失败必须逐卡可见；不得把“已批准但 Team 尚未创建”伪装成未选择。

### R4 — Verified handoff and Build-side ingestion

- Approval 后端只向 Build 侧提交规范化的纯 JSON handoff，不直接 import
  `hacksome.stages.build.control` 私有模块。
- handoff v1 保持 Creative 已实现的精确五字段：
  `source_run_id`、`idea_card_id`、`idea_card_sha256`、
  `challenge_markdown`、`initial_idea_card_markdown`。`route_id` 与版本只放在
  外层 catalog/authorization envelope，避免破坏 Creative exact-key validator。
- Build 侧在写入任何 Team state 前必须验证：
  - handoff exact schema；
  - Idea Card UTF-8 bytes 的 SHA-256；
  - 非空 challenge 与 Card；
  - supported contract version；
  - source run/Card identity。
- Team identity 至少绑定
  `source_run_id + idea_card_id + idea_card_sha256`；跨 run 重名 Card 不能碰撞。
- 同一 handoff 重放幂等返回同一 Team；同一 source run/Card identity 的内容 hash
  冲突必须 fail closed。
- Agent 可见 `/project` 初始内容仍只有
  `reference/challenge.md` 与 `reference/initial-idea-card.md`。

### R5 — Batch bootstrap, Team registry, and global pool

- 同一个 completed source run 的 Approval 在 open 状态下可以按顺序提交多个显式
  Card batch；每批必须包含 1..10 张尚未授权的 Card。
- 每张 Card 在整个 Approval 生命周期内最多授权一次；先前未选的 Card 可以在后续
  batch 中授权。
- Approval 只有在 operator 执行独立、显式、不可逆且幂等的 close mutation 后才
  关闭；关闭只禁止新的 authorization，不取消或暂停已经 queued、starting 或
  active 的 Team。
- 关闭后的页面保留为只读状态页，继续展示并轮询已授权 Card 的交接与 Team 状态。
- batch 被持久化后，为每张 Card 创建独立 Team registry row 和 control root。
- batch submission 是持久授权边界，不承诺跨多个容器启动的全局事务；逐卡 bootstrap
  使用 outbox/reconcile 达到可重放的最终一致。
- 默认 `max_active_teams = 2`，可配置但必须为有限正整数。
- 批量批准 10 张时，最多两个 Team 进入 `starting/active`，其余按稳定顺序进入
  `queued`；这仍视为一次成功的批量 Build 操作。
- queued 不启动 Agent 或 manager 容器，也不算失败或拒绝。
- Team 启动失败保留 authorization、registry row、错误与可重试状态；不得自动改选
  另一张 Card。
- operator pause/resume 保留现有 Build 规划中的项目、Goal、session 与 telemetry
  连续性；自动排名、winner、quality score 与自动轮转仍禁止。

### R6 — CLI and lifecycle integration

- Useful 成功完成且有 Card 时，CLI 打印共享 Approval next command。
- Creative C6/C7 生命周期保持不变；只有 C7 completed 且 offline-valid 后才能进入
  Build Approval，并打印同一 next command。
- 提供 route-neutral 命令打开 Approval 页面，并支持 `--no-open` 以便自动化测试。
- 提供离线 status/validate/reconcile 投影，能从 source Card 一直追到
  authorization、handoff、Team registry 与当前 pool state。
- 对 incomplete、waiting、failed、tampered 或 unsupported run 启动 Approval 必须
  fail closed，且不改变 source run 或 Build state。

### R7 — Crash safety and observability

- source run、Approval ledger、handoff outbox 与 Build registry 各自有单一 owner。
- 在以下边界注入崩溃后都可重放且不会多建 Team：
  - authorization 已保存、outbox 未写；
  - outbox 已写、Build adapter 未调用；
  - Team root 已创建、registry 未投影；
  - registry 已排队、容器启动未确认；
  - browser 已收到或未收到 response。
- 每张 Card 的状态链、错误、重试与 Team ID 可由页面和 CLI 检查。
- 日志和最终 Agent context 不泄露 capability token、原始浏览器 cookie 或其他
  Card 的私有控制面数据。

### R8 — Full end-to-end proof

- 使用至少一道真实 challenge 分别证明：
  - Useful run → Final Idea Cards → Approval → Build Team；
  - Creative completed run → Final Idea Cards → 同一 Approval → Build Team。
- 至少一次批量批准多个 Card，并证明 active 上限、FIFO queue 和逐 Team 隔离。
- 至少一个 Team 必须由真实 Lead 创建 Goal、Worker 产生实质项目变更、fresh
  Verifier 提交 verdict。
- 浏览器 QA 覆盖单选、多选、select all/clear、确认、刷新恢复、stale hash、重复提交、
  partial failure、queued/active 状态和 zero-card empty state。
- E2E 保存不含凭证的证据摘要、输入身份、Card hash、Team IDs、Goal/review 状态与
  可运行产物位置。

## Acceptance Criteria

- [ ] 同一个 Approval 页面可打开 completed Useful 或 Creative run，且使用同一
      candidate/selection API。
- [ ] 页面支持 zero/one/many selection、批量选择和明确确认；未确认不启动任何 Team。
- [ ] 同一 source run 可先批准 batch A、刷新或重启页面后再批准 batch B；已经授权的
      Card 不可再次选择或授权。显式关闭后 batch C 被拒绝，但 A/B 已创建或排队的
      Team 继续运行。
- [ ] 一批批准 10 张 Card 时创建 10 个稳定、隔离的 Team identity；默认最多两个
      active，其余 FIFO queued。
- [ ] 相同 submission 或 handoff 任意重放不会重复创建 Team；payload/hash 冲突
      fail closed。
- [ ] Useful 与 Creative 的 Card 都在 Build 写状态前通过 exact SHA 校验。
- [ ] 页面关闭或任一规定崩溃点发生后，reconcile 能完成已确认的交接且不扩大授权范围。
- [ ] 页面与 CLI 能逐 Card 展示 authorization、handoff、Team 和 pool 状态，并明确
      区分 desired 与 observed lifecycle；单 Team 的 Goal batch 完成不会被投影为
      Team completed 或自动释放 global slot。
- [ ] source run 不因 Approval/Build 状态而改变原 route 的质量决策或 completed 产物。
- [ ] 两条 route 的真实联合 E2E 均至少启动一个 Team，并有真实 Worker 结果和独立
      Verifier verdict。
- [ ] 完整 Useful、Creative 与 BuildFactory 回归通过；无凭证或 token 进入提交证据。

## Out of Scope

- 自动选择、排名、推荐或默认批准 Idea Card。
- 把 Creative C6 策展与 Build Approval 合并。
- 根据 route、Idea 内容或模型评分自动分配 Team 优先级。
- Team 自动完成、自动淘汰、winner/Top-K 或项目合并。
- Build 后的人工审批、Idea 忠实度 gate 或固定 PRD→Build→Pitch 阶段。
- 公网托管、生产账户、组织权限、TLS termination 或多人审批流。
- 在本任务中重新设计 Useful/Creative 的 pre-card 方法论。
- 为历史 Useful run schema v1 回填或迁移 Build Approval。
