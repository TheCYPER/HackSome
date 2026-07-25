# 跨路线 Idea Card Build Approval 与自动交接 — 技术设计

## 0. 文档状态与已冻结决定

本文把 `prd.md` 收敛为 Useful 与 Creative 共用的 post-Idea-Card 控制面。实现可以
调整内部文件名，但不得悄然改变这些决定：

- Idea Card 之前仍由 Useful、Creative 各自负责；最终 Card 之后才进入共享架构。
- Approval 是 Build 资源授权，不是第二次质量评审。
- 同一个 completed run 支持多个显式 Approval batch；每批 1..10 张。
- 每张 Card 最多授权一次；未选 Card 可以在后续 batch 再选。
- Approval 只在 operator 显式关闭后不可再提交；关闭不可逆，但不停止已授权 Team。
- 每张 approved Card 对应一个隔离 Team。
- 默认全局最多两个 Team 处于占用运行 slot 的生命周期；其余稳定 FIFO 排队。
- active Team 不因一轮 Goal 完成而自动结束或释放 slot；operator pause 才释放。
- completed source run 保持不变。Approval、handoff delivery 与 Build lifecycle 均由
  run 外部的新 owner 持久化。
- Build Agent 可以继续、修改或放弃初始 Idea Card；本系统不增加 Idea 忠实度 gate。

## 1. 产品对象、用户与单一任务

页面是 Percy/本地 operator 使用的 **Build Dispatch Board**。它只有一个核心任务：

> 从一个已经完成且离线验证通过的 Idea run 中，明确选择本批要投入 Build
> 资源的 Final Idea Cards，并看清每张 Card 是立即启动、排队还是交接失败。

页面不承担 Concept 策展、质量打分、Team 日常管理、代码评审或跨 run 项目排名。
这样 Creative C6 的内容判断与 Build Approval 的资源判断不会混在一起。

## 2. 系统边界与总体架构

```text
completed Useful run                  completed Creative run
        │                                      │
        └──────── route-specific adapters ─────┘
                              │
                    PostCardCatalogV1
                 exact bytes + hashes + order
                              │
               ApprovalStore outside source run
          catalog / batches / close / outbox / receipts
                              │
             local Approval HTTP server + static UI
                              │
               BuildControlAdapter (pure JSON)
                              │ subprocess, shell=False
                              ▼
          BuildFactory TeamRegistry + PoolReconciler
                 │                         │
          isolated Team roots         Docker/Compose
                 │                         │
                 └──── read-only status ───┘
                              │
                    Approval page / CLI
```

### 2.1 Trust and ownership boundaries

| Owner | Owns | Must not own |
| --- | --- | --- |
| Useful/Creative route | source run, route validation, final Card meaning/order | Approval or Team lifecycle |
| `PostCardCatalogProvider` | normalized read-only projection and exact handoff materialization | source mutation |
| `ApprovalStore` | catalog snapshot, mutation ledger, authorizations, delivery intent/receipt | Docker or Team internals |
| `BuildControlAdapter` | serialized process boundary and safe error mapping | business selection |
| `TeamRegistry` | Team identity, queue sequence, desired/observed lifecycle | Idea quality |
| `PoolReconciler` | bounded slots and lifecycle side effects | automatic winner/rotation |
| Browser UI | display, local draft, explicit operator mutations | arbitrary filesystem/argv/Team Hub access |

Approval package 不 import Build control 私有 Python 类型；Build control 不
import Approval 或 Ideation 私有类型。两侧只交换严格 JSON。
Browser 永远不连接 Team Hub，也不能提交路径、Compose service、环境变量或任意命令。

## 3. 代码所有权与预期文件

首版采用小而明确的模块，而不是把 Build 逻辑塞进 `workflow.py` 或复用 Creative
review domain：

```text
src/hacksome/contracts/post_card/
  contracts.py              # Catalog/Card/Handoff 的唯一 decoder/encoder
  catalog.py                # provider registry、catalog hash
  useful_adapter.py         # Useful route-owned projection
  creative_adapter.py       # Creative route-owned projection

src/hacksome/stages/build/approval/
  contracts.py              # HTTP mutation/status DTO
  store.py                  # immutable records、projection、lock、recovery
  service.py                # authorize/close/reconcile use cases
  build_adapter.py          # protocol + production subprocess adapter
  server.py                 # loopback HTTP/security/lifecycle

src/hacksome/stages/build/approval_ui/
  index.html
  styles.css
  app.js

src/hacksome/stages/build/control/
  handoff.py                # exact Build-side handoff/envelope decoder
  team_registry.py          # stable identity、registry row、enqueue sequence
  team_pool.py              # slot accounting、FIFO、reconcile
  team_operator.py          # fixed CLI surface for adapter/operator
```

现有 `src/hacksome/cli.py` 只做参数 dispatch 与人类可读输出。现有
`src/hacksome/stages/build/control/team_store.py` 继续拥有单 Team reference 初始化，
由 registry 层在验证 identity/handoff 后调用。

## 4. Route-neutral catalog contract

### 4.1 `PostCardCatalogV1`

Catalog 是 source run 的只读、确定性投影。首次打开 Approval 时，将其以 canonical
JSON 原子冻结到 source run 外部：

```json
{
  "schema_version": 1,
  "source": {
    "route_id": "useful|creative",
    "route_contract_version": "1",
    "run_id": "..."
  },
  "cards": [
    {
      "ordinal": 0,
      "card_id": "...",
      "title": "...",
      "card_sha256": "...",
      "card_markdown": "...",
      "source_artifact_ref": {
        "artifact_id": "...",
        "artifact_type": "...",
        "relative_path": "..."
      },
      "route_handoff_ref": null,
      "handoff": {
        "source_run_id": "...",
        "idea_card_id": "...",
        "idea_card_sha256": "...",
        "challenge_markdown": "...",
        "initial_idea_card_markdown": "..."
      }
    }
  ],
  "catalog_sha256": "..."
}
```

`catalog_sha256` 是去掉该字段后的 strict canonical JSON UTF-8 bytes 的 SHA-256。
Card 顺序由 route adapter 冻结；共享层不按标题或 ID 再排序。ID、path 与 Markdown
均视为不透明、不可信数据。

`handoff` 必须保持 Creative 已有合同的精确五字段。route/version/provenance 只在
catalog 与后续 authorization envelope 中出现，不能加入 handoff v1。

### 4.2 Catalog 创建与重开

1. 调用现有 route-aware `validate_run()`，要求 schema v2、`completed`、无离线错误。
2. 按 persisted route ID/version 选择唯一 adapter；未知组合 fail closed。当前
   显式支持 Useful v1，以及 Creative 的 frozen v1 与 main 当前 v2；这不是对未来
   route version 的自动兼容承诺。
3. adapter 读取并复核 exact artifact bytes/hash，输出稳定 Card 顺序。
4. 共享 decoder 验证 catalog/Card/handoff 不变量并计算 catalog hash。
5. 若不存在 `catalog.json`，原子写入；若已存在，重新投影并要求 byte-for-byte
   等价，否则进入只读 `source_integrity_error`，禁止新增 authorization。

已有 authorization 不因之后的 source tamper 被删除或取消；status 仍可离线查看。

### 4.3 Useful adapter

- 权威 Card 顺序来自 Useful v2 的 `idea_card_ids`，不解析 Markdown index。
- 每个 artifact 必须由 Hub hash-verified read 返回，并继续满足 Useful route
  validator 的 lineage/quality closure。
- Challenge 来自已登记的 `challenge-brief` exact Markdown。
- adapter 根据 exact Challenge 与 Card text 确定性构造五字段 handoff。
- zero-card completed run 输出合法空 catalog。

### 4.4 Creative adapter

- 权威 Card 顺序来自 C7 frozen success output/report contract，不读取
  `idea_card_ids`。
- 对每张 Card 读取其 C7 handoff artifact，要求 exact five keys，并复核 run ID、
  Card ID、Card SHA、Challenge 与 Card Markdown。
- catalog 使用已经冻结的 handoff value；不能重新序列化一个“语义相同”的替代 C7
  artifact 来冒充 route output。
- zero-card completed report 输出合法空 catalog。

## 5. Approval persistence and state machine

### 5.1 默认存储位置

默认 Approval control root：

```text
<source-run-parent>/.hacksome/approvals/<source-run-id>/
  catalog.json
  state.json
  mutations/
    000001-authorize-<request-id>.json
    000002-close-<request-id>.json
  outbox/<authorization-id>.json
  receipts/<authorization-id>.json
  lock
```

可以通过 CLI 的可信参数覆盖 `approval_root`，但该路径从不由 Browser 提供。
`mutations/` 中每个文件不可变；`state.json` 是可重建、原子替换的快速投影。
sequence 分配、重复检查与 mutation commit 都在单一跨进程 lock 下完成。

### 5.2 Approval lifecycle

```text
open
  ├─ authorize 1..10 new Cards ─> open
  ├─ authorize another batch ───> open
  └─ explicit close ────────────> closed

closed
  ├─ status/reconcile ──────────> closed
  └─ any new authorize ─────────> conflict (no write)
```

Close 不改变已授权 Card 的 delivery/Team lifecycle。关闭后的未选 Card 显示
`not_built`，而不是 `rejected`。

### 5.3 Authorization request and binding

Browser 提交：

```json
{
  "schema_version": 1,
  "request_id": "client-generated bounded opaque id",
  "catalog_sha256": "...",
  "cards": [
    {"card_id": "...", "card_sha256": "..."}
  ]
}
```

Server 只接受 1..10 个不同 Card，逐项与 frozen catalog 比较，并按 catalog ordinal
规范化顺序。canonical request hash 绑定 mutation kind、request ID、run/catalog 与
所有 Card identity：

- 同 request ID、同 canonical hash：返回原 receipt，不写第二个 batch。
- 同 request ID、不同 payload/hash：`idempotency_conflict`。
- 已在旧 batch 授权的 Card：`card_already_authorized`，整个新 batch 零写入。
- stale catalog/Card hash：`stale_catalog`，整个 batch 零写入。
- Approval closed：`approval_closed`，零写入。

批内是一个授权决定：验证通过后，一个 immutable mutation 原子记录所有选中 Card
及其规范化 handoff intent。Team 创建是逐 Card 最终一致，不承诺跨多个 Docker
side effect 的事务。

### 5.4 Close request

Close 使用独立 body：

```json
{
  "schema_version": 1,
  "request_id": "...",
  "catalog_sha256": "..."
}
```

首次成功 close 写 immutable mutation。相同重放或后来等价 close 返回同一 closed
projection；authorize 与 close 竞争时由 Approval lock 决定严格先后。空 selection、
页面超时、Browser 关闭或 server 停止永远不等价于 close。

### 5.5 Per-card delivery state

每个 committed authorization 确定性获得
`authorization_id = auth-<hash(run/card/card-sha)>`，并投影为：

```text
authorized → delivering → accepted
                  └──────> delivery_error (retryable)
```

Reconciler 从 immutable batch 补齐缺失 outbox，因此即使在 “batch committed /
outbox missing” 之间崩溃也不会丢失授权。receipt 保存 Build 返回的 `team_id`、
identity hash 和当前 registry state。错误只更新 delivery projection，不抹掉
authorization。

## 6. Build-side ingestion contract

### 6.1 Outer envelope

Approval 向 Build 发送：

```json
{
  "schema_version": 1,
  "authorization_id": "...",
  "source": {
    "route_id": "...",
    "route_contract_version": "...",
    "catalog_sha256": "..."
  },
  "handoff": {
    "source_run_id": "...",
    "idea_card_id": "...",
    "idea_card_sha256": "...",
    "challenge_markdown": "...",
    "initial_idea_card_markdown": "..."
  }
}
```

Build-side decoder 是该 JSON 的唯一 owner，并在任何 registry/root 写入前验证：

- outer envelope 与 inner handoff exact key set/schema；
- supported version；
- non-empty source/Card identity 与 Markdown；
- Card Markdown exact UTF-8 SHA-256；
- authorization ID 格式；
- canonical handoff/envelope hash。

### 6.2 Process boundary

Production adapter 使用固定 executable/module/command allowlist，通过 stdin 写 JSON：

```text
<build-python> -m hacksome.stages.build.control.team_operator authorize
  --build-root <trusted-path> --json-stdin
```

实现必须使用 argv list、`shell=False`、bounded timeout、最小环境 allowlist 和
bounded stdout/stderr。Card/title/user text 不能进入 argv、environment 或 shell。
测试使用同一 protocol 的 fake adapter，不依赖 Docker。

Build 返回严格 JSON receipt：

```json
{
  "schema_version": 1,
  "authorization_id": "...",
  "team_id": "...",
  "identity_sha256": "...",
  "observed_state": "queued|bootstrapping|starting|active|error"
}
```

未知字段、非零退出、timeout、非法 JSON 或 receipt identity 不匹配都映射为安全、
逐 Card 的 adapter error；traceback 不发送给 Browser。

## 7. Team identity, registry, and pool

### 7.1 Stable Team identity

logical identity 是 canonical：

```text
source_run_id + idea_card_id + idea_card_sha256
```

`team_id` 使用该 identity hash 的固定安全前缀与截断 hex，例如
`team-<24-hex>`；registry 始终保存完整 identity/hash，并在理论截断碰撞时 fail
closed。route 不加入 logical identity，避免同一 frozen Card 因 adapter metadata
变化而产生第二 Team。

- exact envelope/handoff replay 返回同一 Team receipt。
- 同 source run/Card ID 但不同 Card SHA 是 identity conflict。
- 同 authorization ID 但不同 envelope hash 是 idempotency conflict。
- 跨 run 同名 Card 产生不同 Team。

### 7.2 Registry layout and row

```text
<build-root>/
  registry/
    lock
    sequence.json
    teams/<team-id>.json
    operations/<operation-id>.json
  teams/<team-id>/           # one isolated Team control root
```

Row 至少包含：

```text
team_id
source_run_id / idea_card_id / idea_card_sha256
handoff_sha256 / envelope_sha256 / authorization_id
enqueue_seq / control_root
desired_state = active | paused
observed_state =
  queued | bootstrapping | starting | active |
  pausing | paused | resuming | error
operation_id / attempts / last_error / timestamps
```

Registry lock 只保护 identity、sequence、row transition 与 slot reservation；耗时
filesystem bootstrap、Compose create/start/stop 和 health probe 在 lock 外执行，
之后再以 operation ID compare-and-apply 写回。

### 7.3 Bootstrap and reference adoption

1. registry 先持久化 Team intent 与 enqueue sequence。
2. 获得 slot 后进入 `bootstrapping`。
3. 调用现有 `TeamLayout.bootstrap()` 写 exact
   `reference/challenge.md` 与 `reference/initial-idea-card.md`。
4. 若 crash 后发现 root 已存在，只有两份 bytes 与 handoff exact match 才 adopt；
   任意不匹配都进入 conflict/error，不覆盖。
5. bootstrap 成功后才能尝试 Compose start。

### 7.4 Pool semantics

- `max_active_teams` 默认 2，只接受有限正整数配置。
- 新授权顺序先按 batch mutation sequence，再按 catalog ordinal；每个 row 获得单调
  `enqueue_seq`。
- `bootstrapping|starting|active|pausing|resuming` 占用 slot。
- `queued|paused` 不占 slot，也不启动 Agent/manager 容器。
- `error` 只有在确认没有运行实例后才释放 slot；authorization/row 保留并允许显式
  reconcile 重试。
- active Team 不因 Goal queue 暂空或一次 verdict 完成而释放 slot。
- pause 必须确认 Lead、Worker、Verifier 与 managers 全部停止后才写 `paused` 并释放
  slot；随后启动最早 queued Team。
- resume 有空 slot时进入 `resuming`；无空 slot 时以新的 enqueue sequence 回到
  `queued`，但 Team ID、project、Goal、session 与 telemetry 不变。

## 8. Reconcile and crash recovery

没有跨 source run、Approval root、Build registry 和 Docker 的全局事务。恢复模型是：

```text
owner-local atomic intent
  + at-least-once outbox
  + idempotent consumer
  + repeatable observed-state reconcile
```

Approval server 启动后、authorize 成功后及后台短周期都运行 bounded reconcile；
`hacksome build-reconcile RUN_DIR` 提供离线显式入口。Browser 是否继续打开不影响已
commit 的工作。

| Crash boundary | Required recovery |
| --- | --- |
| request 未完成验证 | 无 mutation、无 Team |
| batch committed，HTTP response 丢失 | same request replay 返回原 batch |
| batch committed，outbox missing | 从 immutable batch 重建 outbox |
| outbox exists，adapter 未调用/response 丢失 | 重放同 authorization，Build 幂等 |
| registry row exists，Team root missing | 同 Team ID 继续 bootstrap |
| Team reference 已发布，row 未更新 | exact bytes match 后 adopt |
| queued 已写，slot 尚未分配 | 保留原 enqueue sequence |
| start operation 已发出，结果未知 | probe 实际 Compose state 后 adopt/retry |
| pause 只停了一部分实例 | 继续占 slot，直到全部 stop confirmed |
| stop confirmed，projection 未写 | 同 operation 对账并只释放一次 slot |

Reconcile 不能扩大授权集合：它只能处理 immutable batches 中已有 Card。

## 9. Shared status projection

UI/CLI 不直接拼接 Approval 与 registry JSON。`ApprovalService.snapshot()` 是唯一
跨层 projection owner，为每张 catalog Card 返回 allowlisted 状态：

```text
available              # Approval open，尚未授权
not_built              # Approval closed，尚未授权；不是 reject
authorized             # committed，Build 尚未接受
queued
starting               # bootstrapping/starting/resuming 的 UI 合并态
active
paused
error                  # 保留 retryable code/message
```

附加字段仅包括 stable Team ID、queue position、active cap、delivery attempts 和安全
错误码/文案。绝对路径、Docker socket/details、Agent log、session/cookie/token 与
其他 Team control data 不返回 Browser。

## 10. HTTP server and security

复用 Creative review server 已证明的 transport/security pattern，但新建 Approval
domain：

- 默认且首版只监听 loopback；拒绝非 loopback bind。
- 启动 URL 中的随机 join token 只用于换取 HttpOnly、`SameSite=Strict` cookie；
  token/cookie 不持久化、不写日志/证据。
- 严格 Host/Origin、method、Content-Type、body size 与 fixed-route allowlist。
- 所有响应使用 CSP、`no-store`、`nosniff`、`no-referrer`、frame deny 与
  same-origin resource policy。
- 同一 Approval root 使用 lifecycle lock，避免两个 server/reconciler 竞争。
- 静态资产随 Python package 发布，不读取客户端提供的 path。
- Markdown 只通过 DOM node + `textContent` 渲染；不使用 `innerHTML`，不执行 raw
  HTML、链接、图片或脚本。

固定 API：

```text
GET  /api/snapshot
GET  /api/cards/{ordinal}
POST /api/authorize
POST /api/close
POST /api/reconcile
```

`{ordinal}` 必须是 bounded decimal 并从 catalog lookup，不能映射为文件路径。
Snapshot 只含列表 metadata/status，完整 Markdown 由 detail endpoint 按需获取，
避免每次 polling 传全部 Card。

`POST /api/authorize` 在 durable mutation commit 后即成功；Build 交接可以返回
`202 reconciling` 或逐 Card error projection，不能因为容器未全部启动而回滚授权。

## 11. Approval UI design

### 11.1 Visual direction

视觉隐喻是 **workshop dispatch ticket + launch rail**，不是通用后台 dashboard：

- 背景像干净的工作台纸张，而非大片渐变或玻璃卡片。
- Card 是带序号、route stamp、hash 尾码的 dispatch ticket。
- 右侧/底部持续存在一条 Launch Rail，明确画出两个 active slots 和 FIFO queue。
- 确认一批后，ticket 只做一次短距离进入 rail 的状态动画；`prefers-reduced-motion`
  下立即切换，无位移动画。

建议 token：

```css
--paper: #f2f4f3;
--surface: #ffffff;
--ink: #17211b;
--muted: #5f6c65;
--line: #cbd2ce;
--cobalt: #1f4fdb;
--safety-orange: #e36b2c;
--approved-green: #2c7a55;
--queue-ochre: #a66b00;
--danger: #b42318;
```

Display 使用本地
`"Avenir Next Condensed", "Arial Narrow", sans-serif`，正文使用系统 sans，
ID/hash 使用 `ui-monospace`；不引入网络字体或图标依赖。

### 11.2 Desktop layout

```text
┌──────────────── Run / Route / Approval OPEN ────────────────┐
│ Build Dispatch Board                         catalog a91…    │
├──────── Ticket list ───────┬──── Card detail ────┬ Launch ──┤
│ [ ] 01  Card title         │ # Full title        │ SLOT 1    │
│ [x] 02  Card title         │ provenance / hash   │ active    │
│ [ ] 03  Card title         │ exact text preview  │ SLOT 2    │
│ ...                        │                     │ starting  │
│ select next 10 / clear     │                     │ QUEUE     │
├────────────────────────────┴─────────────────────┴───────────┤
│ 2 selected · 0 start now · 2 queue   [Approve 2 and build]  │
└─────────────────────────────────────────────────────────────┘
```

Card list 与 Launch Rail 保持可见；detail 区滚动展示完整纯文本。底部 batch tray
sticky，始终显示 “selected / starts now / queues” 预估。窗口较窄时 detail 进入列表
下方，Launch Rail 变为 sticky bottom status drawer。

### 11.3 Interaction and copy

- 原生 checkbox 支持单选、多选与 keyboard；已授权 Card disabled 但仍可查看。
- “选择本批全部”最多选择当前顺序中前 10 张 available Card，并明确提示批上限；
  “清空本批”只清 draft。
- 选第 11 张时不静默替换已有选择，而是在 tray 中说明“每批最多 10 张”。
- 主按钮文案为 `Approve N and start build` / `批准 N 张并开始 Build`，不用含糊的
  `Submit`。
- confirmation sheet 再次显示 Card 列表、预计立即启动数和排队数；确认前仍可返回。
- 成功后清空 draft、锁定已授权 ticket、显示 Team ID/queue/status，并允许继续选择
  下一批。
- `Close Approval` 是次级但清晰的破坏性动作；确认文案说明剩余 Card 仍有效，只是
  不会 Build，并说明关闭不可撤销。
- zero-card 页面显示原因与唯一合法 mutation：显式关闭；绝不伪造 Team。
- 网络/adapter partial error 显示在对应 ticket，不抹掉已批准状态；提供固定
  “Retry pending handoffs” 动作。
- 使用 `aria-live` 宣告 mutation/status，focus 在 modal 关闭后回到触发按钮；所有
  controls 有可见 `:focus-visible`，颜色不是唯一状态信号。

### 11.4 Deliberate non-generic checks

- 不使用“左侧导航 + KPI 四卡 + 数据表”模板；页面围绕单个 run 和一次 dispatch。
- 不堆叠圆角卡片；层级主要靠 ticket edge、规则线、编号与 rail。
- 不用装饰性 hero、渐变标题、AI sparkle 或无意义图表。
- Launch Rail 必须真实反映 pool cap/queue，而不是仅为视觉装饰。
- 页面只提供 Approval 相关 mutation；pause/resume 保留在 operator CLI，避免把
  高权限 Docker 控制扩散到 Browser。

## 12. CLI and lifecycle integration

Idea-side public commands：

```text
hacksome approve RUN_DIR [--no-open] [--approval-root PATH]
                         [--build-root PATH] [--build-python PATH]
hacksome approve RUN_DIR --cards CARD_ID [CARD_ID ...] --yes
                         [--request-id ID] [--no-reconcile] [--json]
hacksome build-status RUN_DIR [--json]
hacksome build-reconcile RUN_DIR [--json]
```

- completed、offline-valid 且有 Card 的 Useful/Creative CLI 输出同一个
  `Next: hacksome approve ...`。
- zero-card completion 输出明确“没有可 Build Card”，仍允许显式打开 empty state
  并 close。
- waiting/failed/incomplete/tampered/unsupported run fail closed，零写入。
- `--no-open` 支持测试/远程终端；默认打开带一次性 join token 的本地 URL。
- `--cards` 进入一次性终端授权模式，不启动 HTTP server；`--yes` 是强制的显式
  mutation gate。CLI 从 frozen catalog 解出 Card SHA 并调用同一个
  `ApprovalService.authorize()`；默认随后执行一次 `reconcile()`，而
  `--no-reconcile` 只保存 durable authorization/outbox。
- 未提供 `--request-id` 时，CLI 根据 catalog hash 与按 catalog ordinal
  canonicalize 后的 selection 生成稳定安全 ID；相同命令自然走 same/same replay。
  Browser-only host/port/open 参数不得与 `--cards` 混用。

Build-side operator commands：

```text
team_operator authorize --build-root ... --json-stdin
team_operator list      --build-root ... [--json]
team_operator inspect   --build-root ... TEAM_ID [--json]
team_operator reconcile --build-root ... [--json]
team_operator pause     --build-root ... TEAM_ID --request-id ...
team_operator resume    --build-root ... TEAM_ID --request-id ...
```

所有 mutation 幂等。首版无 delete/archive/rank/score/automatic rotate。

## 13. Compatibility and migration

- Useful/Creative 原有 run schema、artifact ID、Card bytes、C6/C7 状态机与 validation
  不改变。
- Creative exact five-field handoff 保持不变。
- 新状态全部位于 source run 外部；删除/禁用 Approval 功能不会使原 run 无法
  `status/validate`。
- 首版仅支持 completed run schema v2；不自动迁移 Useful run schema v1。route
  contract 则显式支持 Useful v1 与 Creative v1/v2。
- 现有手工 `make -C ops/build init/up` 可继续使用，但不会自动进入新 registry。
- 当前分支已以 main-first 的普通 merge 吸收上游 `main`，Draft PR 直接以
  `west0nG/HackSome:main` 为 base；不得 rebase/force-push 改写已经发布的分支历史。

## 14. Validation strategy

### 14.1 Unit and contract tests

- 两个 route adapter：non-empty/zero、stable order、exact bytes/hash、unsupported、
  incomplete、tamper。
- catalog canonical hash、frozen reopen、source mismatch read-only。
- authorize 1/10/11、duplicate in batch/across batches、stale hash、same replay、
  request ID conflict、close/reclose/authorize-after-close、authorize-close race。
- committed batch→missing outbox、response loss、partial adapter failure、reconcile。
- Build exact decoder、SHA mismatch、stable Team ID、root adopt/conflict。
- pool 10 Cards/2 slots、FIFO、queued no container、start error、pause/resume/restart。
- status allowlist，确保无 path/token/cookie/traceback 泄漏。

### 14.2 HTTP and UI tests

- fixed routes、Host/Origin/cookie/CSP/body/method/content-type protection。
- snapshot/detail split 与 ordinal bounds。
- DOM 使用安全 text nodes，不出现 `innerHTML` 或网络资产。
- 真 Browser 覆盖单选、多选、select next 10、clear、confirm/cancel、多批、刷新、
  stale、replay/conflict、partial error、queue/active、close 与 zero-card。
- keyboard、focus、窄屏与 reduced motion 做一次人工/自动 QA。

### 14.3 Joined E2E

1. 真实 Useful challenge → completed Cards → Approval → Team。
2. completed Creative run → 同一 Approval → Team。
3. 11-card fixture：第一批 10、第二批 1，Card 不重复；显式 close 后第三批失败。
4. 默认最多两 active，其余按 batch sequence/catalog ordinal FIFO queued。
5. 至少一个真实 Team：Lead 创建 Goal、Worker 做实质 project 变更、fresh Verifier
   产生 verdict。
6. 保存无 token/凭证的 run ID、catalog/Card hashes、authorization IDs、Team IDs、
   queue/Goal/verdict 与产物位置证据。

真实 E2E 前先检查 Docker daemon、Compose、Codex 登录、账户/credential 隔离与
writable roots。默认单元测试不要求在线模型或真实 Docker。

## 15. Rollout, failure handling, and rollback

1. 先交付纯合同、route adapters 与 fake adapter tests，不启动 Docker。
2. 再交付 Approval ledger/server/UI；用 fake Build 验证多批与 crash recovery。
3. 再接 Build registry/pool/operator；以 JSON fixture 和 fake lifecycle 验证。
4. 最后启用真实 subprocess/Compose joined E2E，并给现有 CLI 增加 next hint。

任一阶段失败时可以关闭新 CLI 入口并保留 Approval/registry state 供修复版重放；
不得删除或重写已授权记录。回滚代码不自动 stop active Team，也不把 queued Card
标为 rejected。需要停止资源时必须由 operator 对明确 Team 执行 pause。

## 16. Rejected alternatives

- **第一次确认后自动永久关闭**：状态机更小，但阻断用户已确认需要的多批模式。
- **复用 Creative C6 keep/reject**：混淆内容策展与资源授权，也不支持 Useful。
- **把 Approval 写进 source run ledger**：会破坏 Creative C7 frozen finalization，
  并让 Build 状态污染 Idea 质量结果。
- **共享读取 `idea_card_ids`**：Creative 不使用该字段；会产生错误空 catalog。
- **Build import route private types**：形成双向耦合，无法独立验证/重放 JSON。
- **确认 10 张即同时启动 10 个 Compose stack**：违背 bounded pool，放大资源风险。
- **Browser 直接调用 Team Hub/Docker control**：现有 Team Hub 不是对抗性认证边界，
  浏览器也不应获得任意 lifecycle 权限。
- **跨目录全局事务**：文件系统、subprocess 与 Docker 无法提供真实原子性；durable
  intent + idempotent reconcile 更可验证。
