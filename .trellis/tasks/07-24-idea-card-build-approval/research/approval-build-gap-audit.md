# Research: Useful + Creative Idea Card Approval 与 Build Team 启动缺口审计

- Query: 审计 Creative review UI/server、Useful/Creative 最终 Card、BuildFactory 单 Team runtime 及 planning-only 的 Team registry/pool/operator；识别共享 Approval 页面、zero/one/many、每批最多 10 张、确认 Build、幂等、崩溃恢复、队列状态和完整 E2E 的缺口。
- Scope: internal
- Date: 2026-07-24

## Findings

### 1. 结论

仓库已有两块可靠但未接通的基础：

1. Idea 侧有 Creative C6 的本地 capability 页面、安全 HTTP 边界、canonical request hash 幂等、durable outbox，以及 C7 两阶段 finalization。这些模式可复用，但现有 domain 只允许 C6 waiting Creative run，不能直接承担 Build Approval。
2. Build 侧有一个隔离 Team 的真实 `Lead → FIFO Goal → Worker → fresh Verifier` runtime、两份 reference 的原子初始化、method request-id 幂等和 restart 去重；但仍是手工启动的单 Team 栈，没有 handoff consumer、Team registry、global pool、operator pause/resume 或跨系统状态。

因此共享 Approval 不是简单 UI 接线，而是尚未实现的跨目录、跨进程控制平面。推荐 MVP：

```text
completed + offline-valid Useful/Creative run
  → route-neutral frozen ApprovalCatalog
  → local Approval page + immutable ApprovalLedger/outbox
  → versioned pure-JSON handoff boundary
  → Build-side TeamRegistry + PoolReconciler
  → read-only status projection back to page/CLI
```

Idea 与 Build 只通过序列化合同通信；父设计已禁止任一侧 import 对方私有 Python 类型（`.trellis/tasks/07-23-autonomous-build-teams/design.md:39-64`）。Creative C6 的 `keep/reject` 也不能充当 Build authorization。

### 2. 审计口径与关键文件

- **已实现**：当前源码存在，并有测试、active spec 或可执行入口。
- **仅规划**：只有 PRD/design/unchecked implement checklist，没有 active owner。
- 文档 checkbox 与源码漂移时以源码、测试和 active spec 为准；例如 Creative handoff checklist 仍未勾选（`.trellis/tasks/07-23-creative-idea-review-loop/implement.md:396-405`），但 renderer、validator 和测试已经存在。

| 文件 | 作用 |
| --- | --- |
| `src/hacksome/creative/review_server.py` | 单个 C6 round 的固定路由、capability/session、安全 header 和 HTTP relay。 |
| `src/hacksome/creative/review_backend.py` / `review.py` | C6 immutable binding、append-only ledger、request hash、durable close。 |
| `src/hacksome/review_ui/app.js` | Card 导航、本地草稿、hash binding、client ID 和确认交互。 |
| `src/hacksome/creative/report.py` / `finalization.py` | Creative 0..N Final Cards、handoffs 与 crash-replay finalization。 |
| `src/hacksome/routes.py` / `workflow.py` | Useful/Creative inspect/validate 与 Useful Card 发布。 |
| `buildfactory/orchestration/team_store.py` | 单 Team root 与精确两份 Agent-visible reference。 |
| `buildfactory/orchestration/team_scheduler.py` / `team_hub.py` | 单 Team Goal FIFO、Lead/Worker/Verifier lifecycle。 |
| `buildfactory/orchestration/method_adapter.py` / `team_http.py` | 内部 method idempotency 与 HTTP transport。 |
| `.trellis/tasks/07-23-team-pool-operator/*` | handoff/registry/pool/operator 的 planning-only 设计。 |

### 3. 已实现：Creative review 可复用模式，但不是 Approval

#### 3.1 Transport/security

- Server 明确只拥有 transport security、process-local capability/session、固定 UI 和 lifecycle lock（`src/hacksome/creative/review_server.py:1-7`）。
- 已有 `no-store`、`no-referrer`、`nosniff`、frame deny、same-origin resource policy、严格 CSP 和 256 KiB body limit（`src/hacksome/creative/review_server.py:33-64`）。
- join token 换成 HttpOnly、`SameSite=Strict` cookie；cookie 不回显 join token（`src/hacksome/creative/review_server.py:543-560,1036-1044`; `tests/test_creative_review_server.py:406-423`）。
- POST 校验 Origin，所有请求校验唯一 Host；query/fragment 和非 allowlist route fail closed（`src/hacksome/creative/review_server.py:498-541,763-791,992-1003`）。
- 测试覆盖固定资产、安全 `textContent` 渲染、响应式布局、auth/security header、Host/Origin/content-type/body limit 和 server lock（`tests/test_creative_review_server.py:271-309,375-423,491-590,631-665`）。

这些 transport 设计可复用。现有精确 API 只有 snapshot、reviewer session、review、resolve，没有 approval、build batch、team、queue、status 或 reconcile（`src/hacksome/creative/review_server.py:992-1003`）。

#### 3.2 Durable mutation/idempotency

- Review ledger 用 `O_EXCL` 创建且不覆盖（`src/hacksome/creative/review.py:843-880`）。
- Review/resolution 都计算 canonical request hash；同 ID+同 request 返回原记录，同 ID+不同内容冲突（`src/hacksome/creative/review.py:882-941,971-990`）。
- Resolution 把 closed wait 与 ledger row 一起写入 durable outbox，崩溃后可 reconcile（`src/hacksome/creative/review.py:1010-1034`; `src/hacksome/hub.py:488-549`）。
- UI 生成稳定 client ID，把 draft 绑定 round hash；stale hash 时禁止提交（`src/hacksome/review_ui/app.js:50-81,156-209`）。

Approval 应复用“stable mutation ID + canonical hash + same-replay/different-conflict + durable outbox”，而不是 C6 的 `keep|revise|reject|taste_veto|merge`（`src/hacksome/creative/review.py:55-78`）。父合同明确未选 Card 不是 reject（`.trellis/tasks/07-23-autonomous-build-teams/prd.md:35-43`）。

#### 3.3 Backend/UI 边界

- `RunReviewBackend` 每次读写重验 immutable C6 binding（`src/hacksome/creative/review_backend.py:54-71,162-211`）。
- 它硬要求 `route.id=creative`、`status=waiting`、`current_stage=creative-human-review`、无 pending outbox 和合法 C6 batch（`src/hacksome/creative/review_backend.py:267-325`）。
- CLI 也只允许 waiting Creative；resolution 后 server 退出，再 `resume` 完成 C6C/C7（`src/hacksome/cli.py:489-526,538-571`; `src/hacksome/creative/review_server.py:728-759`）。
- UI 能浏览 concept card/hash、保存 stale-bound draft，并在 close 前 `confirm()`（`src/hacksome/review_ui/app.js:182-209,227-294,950-985`）。
- 但没有 10 张一批的 selection、跨批 selected set、select-all/clear、Build 数量预估、Team ID/queue/error/status 或确认后的 polling。Resolution localStorage 只存 ID，不存完整 action form（`src/hacksome/review_ui/app.js:837-898`）。

Build Approval 必须是新的 route-neutral backend，输入为 **completed + offline-valid** run；确认后 server 还需显示异步 Team 状态，不能照搬“resolve 后退出”。

### 4. 已实现：最终 Card 与 handoff

#### 4.1 Creative

- C7 按稳定 `idea_id` 生成 0..N cards/handoffs（`src/hacksome/creative/report.py:604-683`）。
- 每份 handoff 精确包含 `source_run_id`、`idea_card_id`、`idea_card_sha256`、`challenge_markdown`、`initial_idea_card_markdown`（`src/hacksome/creative/report.py:994-1012`）。
- 离线 validator 校验 Card/handoff path/type、Card UTF-8/H2、index ID/hash，以及 handoff exact fields、source run、Card SHA/Markdown 和 challenge 闭包（`src/hacksome/routes.py:2528-2546,2589-2626,2627-2668`）。
- Active spec 明确 handoff 不等于授权，Build 仍须复核 SHA，Team identity 至少绑定 run+card+sha（`.trellis/spec/backend/creative-agent-workflow-contracts.md:259-265`）；README 明确当前没有 consumer/自动启动（`README.md:175-194`）。

#### 4.2 Creative crash-replay 可借鉴但不覆盖 Build

- C7 先冻结 source、staged bytes 和 manifest，再按 frozen plan publish，最后才暴露 result IDs（`src/hacksome/creative/finalization.py:924-1017,1046-1098`）。
- 测试覆盖 manifest 前/后崩溃、部分 publish、篡改和 completion event/state replace 中断后的精确重放（`tests/test_creative_finalization.py:240-367,369-437,472-516`）。

这只证明 Idea 产物发布可恢复；authorization、delivery、Team root、registry、container lifecycle 都需要自己的 intent/outbox/reconciler。

#### 4.3 Useful gap

- Useful 发布每张 `idea_card`、index、`idea_card_ids` 后直接 completed（`src/hacksome/workflow.py:149-191,543-602`）。
- Hub 保存 immutable artifact path/SHA 并在读取时复核（`src/hacksome/hub.py:877-938,1269-1277`）；Useful validator 检查 Card 类型及 passed Idea/Problem lineage（`src/hacksome/routes.py:123-190`）。
- 但 Useful inspect 只投影 Card 数量（`src/hacksome/routes.py:100-121`），没有 Creative 等价 handoff。

共享 `ApprovalCatalog` adapter 必须：Creative 读取并重验现有 handoff；Useful 由 verified Card + run challenge 确定性投影同一 schema；两者都只接 completed 且完整 offline validation 通过的 run。

### 5. 已实现：BuildFactory 只有单 Team

- 已归档任务明确只做一个 resident Lead、一个 Worker、一个 Verifier，不做 multi-Team registry 或 Review Gate；验收/implement checklist 已完成（`.trellis/tasks/archive/2026-07/07-23-single-team-runtime/prd.md:5-7,32-50`; `.trellis/tasks/archive/2026-07/07-23-single-team-runtime/implement.md:8-53`）。
- `TeamLayout.bootstrap()` 在 staging directory 写两份 UTF-8 reference，再 rename 发布；partial-write 不留半套 reference（`buildfactory/orchestration/team_store.py:31-40,68-106`; `buildfactory/orchestration/tests/test_team_runtime.py:43-96`）。
- Team 内 Goal 按 enqueue sequence FIFO 且 `max_workers=1`（`buildfactory/orchestration/team_scheduler.py:51-58,84-90,154-179`）；PASS/FAIL、同 Worker/session、fresh Verifier、两 Goal FIFO 和 restart 去重有测试（`buildfactory/orchestration/tests/test_team_runtime.py:178-357`）。
- Compose 只有 hub/lead/worker-manager/verifier-manager，Team 内 Worker/Verifier 并发均 1（`buildfactory/orchestration/tests/test_compose_accounts.py:18-34,62-75`）。

现有 bootstrap **不是 handoff 级幂等**：

- CLI 只收 root/challenge file/idea-card file，没有 version、source run、Card ID/SHA 或 handoff hash（`buildfactory/orchestration/team_store.py:148-158`）。
- 成功发布 `reference/` 后重试会报 `already exist`，测试也只验证拒绝覆盖（`buildfactory/orchestration/team_store.py:92-105`; `buildfactory/orchestration/tests/test_team_runtime.py:68-73`）。
- Build registry 必须先用 stable identity/hash 判 replay/conflict，持久化 intent，再初始化 reference；reconcile 要能 adopt 内容匹配的既有 root，不能盲目重复 bootstrap。

现有 method idempotency 也只属于单 Team Agent method：

- `MethodAdapter` 缓存同 actor/request ID 的 method+payload+response；同请求 replay，不同内容 `idempotency_conflict`（`buildfactory/orchestration/method_adapter.py:111-175`; `buildfactory/orchestration/tests/test_method_adapter.py:44-82`）。
- Team Hub allowlist 没有 operator、bootstrap、pool、pause/resume/global status（`buildfactory/orchestration/team_hub.py:87-111`）。
- README/Makefile 仍要求逐 Team `make init`/`make up`（`buildfactory/README.md:36-49`; `buildfactory/Makefile:11-20,35-46`）；Compose 用单个 `${TEAM}` 物化静态栈（`buildfactory/docker-compose.yml:1-24,49-124`）。
- 当前 inspect 只有单 Team Goal/worker/verifier 局部状态（`buildfactory/orchestration/team_scheduler.py:379-389`; `buildfactory/orchestration/team_hub.py:552-567`）。

### 6. 仅规划、尚未实现

`07-23-team-pool-operator` 已规划 exact handoff、stable ID/hash conflict、默认两个 active、FIFO queued、pause 等实例 stop 后释放 slot、paused 保留项目/Goal/session/telemetry 和 resume（`.trellis/tasks/07-23-team-pool-operator/prd.md:15-24`），也设计了 `queued|starting|active|pausing|paused|resuming` 与 bootstrap/list/pause/resume/inspect CLI（`.trellis/tasks/07-23-team-pool-operator/design.md:20-50`）。

但该 task 仍是 `planning`，所有实现项未勾选（`.trellis/tasks/07-23-team-pool-operator/task.json:2-7`; `.trellis/tasks/07-23-team-pool-operator/implement.md:3-27`）。父任务也把 Review Gate/UI 接线留给后续 integration task（`.trellis/tasks/07-23-autonomous-build-teams/prd.md:13-21`; `.trellis/tasks/07-23-autonomous-build-teams/implement.md:5-20`）。当前 Approval task 本身仍是 planning（`.trellis/tasks/07-24-idea-card-build-approval/task.json:2-7`）。

### 7. Requirement gap matrix

| 能力 | 当前事实 | 必需缺口 |
| --- | --- | --- |
| Shared catalog | Creative 有 exact handoff；Useful 有 verified Card | route-neutral decoder/projection；completed+offline-valid；stable order、Card bytes/hash、catalog hash。 |
| Zero/one/many | Card renderer/index 支持 0..N，但无 Build selection | 明确 empty state；select/clear/select-all；未选不写 reject；显式 zero-build close，不能把空 payload/超时当授权。 |
| 每批 10 | 无 | 服务端 enforce 1..10 authorization batch；同 run 可多批；Card 唯一授权；最终显式 close；跨批 draft 绑定 catalog hash。 |
| Confirm-to-build | C6 有关闭 review 的 `confirm()` | 新确认必须展示创建/立即启动/queued 数；先 durable commit，再异步 reconcile。 |
| Approval idempotency | C6 ledger 模式可借鉴 | append-only ApprovalLedger；same ID/hash replay、different conflict；每卡唯一 authorization。 |
| Handoff delivery | Creative 只发布文件，无 consumer | per-card durable outbox、attempt/error/receipt；at-least-once delivery。 |
| Build ingest | reference rename 原子，但 replay 报错 | exact versioned JSON、UTF-8/Card SHA/source identity validation、stable Team ID、registry-before-side-effect、same replay/different conflict。 |
| Registry/pool | 无 | durable row、enqueue seq、default max active 2、FIFO；queued 不启动容器；lifecycle reconcile。 |
| Pause/resume | 无 | operator-only CLI；stop 全部实例后才释放 slot；resume 保留 identity/state，无 slot 回 queued。 |
| Status | Idea run status + 单 Team goal inspect | per-card authorization/delivery/Team ID/queue position/desired+observed lifecycle/error；不得发明 quality/idle/completed。 |
| Browser E2E | HTTP/unit 和静态 UI 断言 | 真浏览器覆盖 zero/one/many、10+1、confirm/cancel、refresh、stale、duplicate/conflict、partial error、polling。 |
| Cross-system E2E | 单 Team scripted test；Creative smoke 到 open C6 | Useful 与 completed Creative 各走同一 Approval→Build；至少一个真实 Lead→Worker 实质变更→fresh Verifier。 |

### 8. 推荐 owner、状态与幂等边界

Approval control root（不要改写 completed Idea run 的质量状态/result artifacts）最少保存：

```text
ApprovalCatalog:
  run/route/contract, ordered cards[{id,title,sha256,markdown,handoff_ref}],
  catalog_sha256
ApprovalBatch:
  batch_id, canonical_request_sha256, source_run_id, catalog_sha256,
  selected[{card_id,card_sha256,authorization_id}],
  committed | reconciling | delivered | partial_error
ApprovalOutboxRow:
  authorization_id, normalized_handoff, handoff_sha256,
  delivery_state, attempts, last_error, build_receipt
```

不变量：

- GET/刷新/超时/空或非法请求零写入。
- `authorize_batch` 为 1..10 张；“zero”用明确 `close_approval_without_build`，避免空 payload 歧义。
- 同一 Card 只可成功授权一次；未选项可留给后续批次，最终显式 close。
- authorization 与 outbox intent 本地原子保存；HTTP 可返回 `202/reconciling`，不能以容器全部启动作为授权持久化条件。
- request 绑定 catalog hash 与逐 Card hash；source tamper/stale view 必须 conflict。

Build registry 最少需要：

```text
TeamRegistryRow:
  team_id
  source_run_id / idea_card_id / idea_card_sha256 / handoff_sha256
  enqueue_seq / control_root
  desired_state = active | paused
  observed_state = queued | bootstrapping | starting | active
                   | pausing | paused | resuming | error
  operation_id / attempts / last_error / timestamps
```

Team key 至少绑定 source run+Card ID+Card SHA；建议再纳入 route/contract version。相同 logical source identity 但 SHA 不同必须 conflict。Pool 在 registry lock 下分配 slot/sequence，容器 create/start/stop 作为可重试 side effect 在锁外执行并写回观测状态。

active Team 按合同不会自动释放 slot（`.trellis/tasks/07-23-autonomous-build-teams/prd.md:147-159`），所以 UI 必须解释第三个以后可能一直 queued，直到 operator pause；这不是失败。单 Team Goal `done` 也不等于 Team completed，active spec 明确不存在 Team idle/自动完成语义（`buildfactory/.trellis/spec/backend/hackathon-team-runtime-contracts.md:47-58`）。

### 9. Crash/reconcile 必测矩阵

| 崩溃点 | 重启后的必需行为 |
| --- | --- |
| confirm 到达前/校验失败 | 零 authorization、零 Team。 |
| authorization 已写、HTTP response 未送达 | 同 request replay 返回同 receipt；不重复授权。 |
| authorization 已写、delivery 前 | reconcile 投递 exact outbox handoff。 |
| Build registry intent 后、root 创建前 | 同 Team ID 重试。 |
| reference 发布前/中 | 无半套 reference；registry 保留 retry intent。 |
| reference 已发布、registry projection/response 前 | 校验 handoff hash 后 adopt 同 root，不创建第二 Team。 |
| queued 已写、slot 分配前 | FIFO enqueue sequence 不变。 |
| slot 已分配、compose start 未确认 | 保持 stable operation ID；查询实际容器后 adopt/retry。 |
| pause 后部分实例已停 | slot 仍占用，直到 Lead/Worker/Verifier/manager 全部 stop confirmed。 |
| stop confirmed、next start 前 | 释放一次 slot并启动最早 queued。 |
| resume response 丢失 | same operation replay；project/Goal/session/telemetry 不变。 |

不要追求 Idea run、Approval root、Build registry 和 Docker 的跨文件系统事务；正确模型是每个 owner 本地原子写 + at-least-once outbox + idempotent consumer + 可重复 reconcile。

### 10. Security / operational risks

#### P0：Team Hub 不得暴露给浏览器

- `method_adapter.py` 明确 actor binding 只是 attribution/misuse boundary，不是 adversarial authentication（`buildfactory/orchestration/method_adapter.py:1-6`）。
- Team HTTP 直接从 request headers 构造 actor，没有 token、Origin/Host/CSP 或 TLS 防线（`buildfactory/orchestration/team_http.py:40-74`）。

Approval server 只能调用独立 operator adapter/CLI；Team Hub 保持内部网络。Operator ingress 要有严格 method/schema/body allowlist、stable request ID 与可信本地边界。

#### P0：Docker socket、路径与命令注入

worker/verifier lifecycle manager 挂载宿主 Docker socket（`buildfactory/docker-compose.yml:26-47`; `buildfactory/orchestration/tests/test_compose_accounts.py:78-87`）。Pool operator 必须严格校验 Team ID/compose project/state root；禁止浏览器提供任意 path/argv/service/env；不得通过 shell 拼接 Card/title/user text；同 Team lifecycle operation 串行并带 operation ID。

#### P1：现有 review capability 是进程内、HTTP-only

- join/capability/session 保存在进程内 dict，每次 start 重新生成（`src/hacksome/creative/review_server.py:257-290`）。
- CLI 打印含 token 的 Review/Curator URL；非 loopback 明确警告无 TLS（`src/hacksome/cli.py:509-518`）。
- cookie 没有 `Secure`，因为现有 server 是 HTTP loopback（`src/hacksome/creative/review_server.py:1036-1044`）。

MVP 应严格 loopback-only；token/cookie 不进入状态、错误、E2E evidence 或 Agent context。重启恢复依赖 durable Approval domain，不依赖旧 cookie。

#### P1：不可信 Markdown与控制面泄漏

- 复用 `textContent`；Card Markdown 作为纯文本显示，不执行 raw HTML/script/image URL（`tests/test_creative_review_server.py:271-292`）。
- Status 必须 allowlist；不返回绝对 root、Docker details、session token、Agent logs 或其他 Team control state。
- 错误映射为稳定安全 code/message，不回传 traceback（`tests/test_creative_review_server.py:592-628`）。

#### P1：队列饥饿必须可见

默认两个 active 且 active 不自动释放时，第三个 Team 可能无限排队。页面必须显示 queue position、active cap 和“需 operator pause 才推进”，不能显示无限 spinner，也不能按质量自动轮转。

### 11. 推荐 MVP 边界

必须包含：

1. **Route-neutral catalog**：completed/offline-valid Useful+Creative；zero/one/N、stable order/catalog hash；Creative handoff adopt + Useful normalized handoff。
2. **Shared local Approval page/backend**：固定安全资产；完整 Card/provenance；select/clear/select-all；每批 1..10、可多批、显式 zero-build close；二次确认、hash binding、refresh/restart receipt/status。
3. **Durable Approval**：append-only batch/authorization ledger；canonical idempotency/conflict；per-card outbox、partial error、offline status/validate/reconcile。
4. **Build ingestion/registry/pool**：exact JSON + SHA；stable Team ID；registry-before-side-effect；默认 active 2、FIFO、queued 无容器；operator CLI list/inspect/pause/resume；desired/observed state 与 restart reconcile。
5. **Status**：逐 Card 显示 authorization/delivery/Team/queue/error；不引入 completed/idle/quality。
6. **Proof**：offline fault matrix、browser E2E、fake lifecycle integration、至少一次真实 Compose Team；Useful 和 completed Creative 各一条联合 E2E。

可明确排除：

- 公网/TLS/account/多人审批；
- 自动推荐/默认批准/ranking/Top-K/quality scheduling；
- Team delete/archive/merge、自动完成、自动释放 slot；
- Approval 页面内 pause/resume 写操作（MVP 页面可只读，控制留给 operator CLI，以缩小浏览器高权限面）；
- Build 后人工 gate/Idea 忠实度 enforcement；
- 跨 source-run 聚合 dashboard；
- 每次默认 CI 都启动真实 Codex/Docker；真实 Agent proof 可作为显式 smoke。

推荐拆为三个可用稳定 JSON fixture 并行开发的子任务：

1. Idea-side catalog + Approval ledger/server/UI；
2. Build-side handoff decoder + registry/pool/operator；
3. Integration reconciler + status + browser/Compose E2E。

Cross-Layer guide 要求 JSON/event 由单一 decoder/projection owner 解析，消费者不得各自 cast 字段（`.trellis/spec/guides/cross-layer-thinking-guide.md:74-101`）。

### 12. E2E 最小场景

1. completed Useful 0-card：empty + 显式 close；无 Team。
2. completed Creative 1-card：批准、response 丢失、same request replay；唯一 Team。
3. 11-card fixture：第一批 10 + 第二批 1；默认两 active，其余 FIFO queued；Card 不重复授权。
4. stale catalog/Card bytes：confirm conflict，Idea/Build 零写入。
5. same request ID + changed selection：idempotency conflict。
6. handoff SHA/schema 错：registry/root/reference 零写入。
7. 每个 crash point 重启：Team 数/ID/enqueue sequence/reference bytes 不变。
8. pause active：完全 stop 前不释放 slot；之后 earliest queued start；resume 保留 state。
9. browser QA：cancel、select all/clear、跨批、刷新、partial error、queued/active、token-free evidence。
10. Useful 与 Creative 各启动一个 Team；至少一个真实 Lead 建 Goal、Worker 写实质项目、fresh Verifier verdict。

当前 Creative 在线 smoke 不能算第 10 项：它只到 open C6，明确没有 resolution/C7，因此没有 Final Idea Card（`.trellis/tasks/07-23-creative-idea-review-loop/smoke-test-report.md:5-19`）。

### 13. Related specs

- `.trellis/spec/backend/creative-agent-workflow-contracts.md:167-198,213-281`：C6 ledger/idempotency、不可信文本、0..N handoff 与 C7 finalization。
- `buildfactory/.trellis/spec/backend/hackathon-team-runtime-contracts.md:6-58,157-186`：单 Team runtime、无 completed/idle、bootstrap 与 method replay。
- `.trellis/spec/guides/cross-layer-thinking-guide.md:19-52,74-101`：跨层 data flow/contract 与单一 decoder/projection owner。

### 14. External references

未使用外部文档或网络资料；仅基于当前 worktree 的源码、测试、active specs 和 Trellis task 文档。

## Caveats / Not Found

- 未发现 shared Approval backend/UI、Approval ledger/outbox、Useful normalized handoff、Build handoff consumer、Team registry、global pool、operator CLI 或跨层 status projection 的 active 实现。
- 未发现真实浏览器驱动的 review/Approval user-flow E2E；现有 UI 证据以静态资源断言和 HTTP unit/integration 为主，CLI 只 mock `webbrowser.open`。
- 未发现 root `tests/` 与 `buildfactory/orchestration/tests/` 之间的跨系统 E2E。
- Creative 在线 smoke 只到 C6 waiting；C7/Build 证据来自 deterministic tests，不是 completed live Creative→Build。
- 未执行 tests、Docker 或 Codex；这是 research-only 的静态源码/测试/规范审计。
- Team pool/operator 设计完整但实现项全部 unchecked；不能把规划文字视为已交付。
- 当前 Approval PRD 推荐“同 run 多个显式 batch、每批最多 10、每 Card 只授权一次、最终显式 close”（`.trellis/tasks/07-24-idea-card-build-approval/prd.md:221-230`）。若改成第一次确认后永久关闭，状态机更小但不能后续追加；实现前需冻结该选择。
