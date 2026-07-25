# 跨路线 Idea Card Build Approval 与自动交接 — 实施计划

## 0. Execution gate and dependency ownership

- [ ] 先由用户确认最新版 `prd.md` 与 `design.md`；确认前保持 task=`planning`，不改
      产品代码。
- [ ] 确认 branch 仍为 `codex/idea-card-build-approval`，PR base 仍为
      `codex/creative-review-loop`；Creative 合入 main 后再 retarget。
- [x] 读取 `implement.jsonl` 中全部 active specs/research，执行 Trellis
      pre-development checklist。
- [x] 将 `.trellis/tasks/07-23-team-pool-operator/` 视为已被本任务吸收的
      planning-only dependency，不在另一分支并行实现 registry/pool。
- [x] 检查原工作区的用户改动仍与隔离 worktree 分离；不得复制、reset 或覆盖。

Review Gate 0：需求中不再存在 open question；明确保留多批 Approval、每批 1..10、
Card 唯一授权、显式不可逆 close、默认两 active、FIFO queue。

## 1. Contract fixtures and route-neutral catalog

### 1.1 Shared contract owner

- [x] 新建 `src/hacksome/contracts/post_card/contracts.py`，实现 strict
      `PostCardCatalogV1` / candidate / exact five-field handoff decoder、canonical
      encoder 与 hash。
- [x] 所有 mapping/list/string 都做 exact key、类型、边界与 duplicate 校验；不得让
      HTTP、CLI 或 Build adapter 各自 cast 同一 JSON。
- [x] 为 title、Card ID/path 等不可信文本保留原 bytes/opaque identity，不做
      route-agnostic prefix parsing。
- [ ] 增加 stable JSON fixtures：Useful 0/1/N、Creative 0/1/N、tampered/stale 与
      11-card batch。

### 1.2 Route adapters

- [x] 新建 provider registry，只允许 persisted `route.id + contract_version` 的
      exact adapter。
- [x] Useful adapter：要求 completed schema v2 + full offline validation；按
      `idea_card_ids` 读取 hash-verified Card 与 Challenge，并确定性物化五字段
      handoff。
- [x] Creative adapter：要求 completed + frozen C7 closure；按 C7 authority 读取
      Cards，加载并复核现有 exact handoff artifacts。
- [x] zero-card 输出合法空 catalog；waiting/failed/incomplete/run-schema-v1/
      unknown/tampered 均 fail closed、零写入；route contract 显式支持 Useful v1
      与 Creative v1/v2。
- [x] catalog 首次原子冻结；重开时重新投影并要求 exact match。

### 1.3 Tests

- [x] 新增 `tests/contracts/test_post_card_contracts.py`。
- [x] 新增 `tests/contracts/test_post_card_useful.py` 与
      `tests/contracts/test_post_card_creative.py`。
- [ ] 覆盖 stable order/hash、exact Card bytes、wrong route/raw state field、
      Creative handoff exact keys、Useful deterministic handoff、zero-card、source
      tamper。

Review Gate 1：给定同一 source run，多次 catalog projection bytes/hash 完全一致；
共享层不依赖 route-specific state field 的错误对称性，source run 无新增文件/event。

Rollback Point 1：此时只有只读 projection/fixtures；可移除未接线的新 package，不影响
现有 Useful/Creative CLI。

## 2. Durable multi-batch Approval domain

### 2.1 Store and ledger

- [x] 新建 `src/hacksome/stages/build/approval/contracts.py`，集中解析 authorize、close、
      snapshot、receipt 与 safe error DTO。
- [x] 新建 `store.py`，实现 control-root resolution、cross-process lock、immutable
      mutation file、atomic projection、sequence 与 offline validate。
- [x] 首个成功 open 冻结 `catalog.json`；后续 source mismatch 进入只读 integrity
      error，不改旧 authorization。
- [x] `authorize_batch` 服务端 enforce 1..10、catalog/Card hash binding、Card
      uniqueness 与 catalog ordinal canonical order。
- [x] 实现 request ID + canonical request hash：
      same/same replay、same/different conflict。
- [x] 同 Card 跨 batch 重复时整个新 batch 零写入。
- [x] 实现独立、显式、不可逆、幂等 close；close 不改变已授权 delivery/Team。
- [x] state projection 可完全从 catalog + immutable mutations 重建；projection
      corruption 不得改变授权事实。

### 2.2 Outbox and service

- [x] 新建 `service.py`，将一个 batch commit 作为授权边界，再逐 Card 补齐 durable
      outbox。
- [x] per-card authorization ID、handoff/envelope hash 确定性稳定。
- [x] 实现 adapter protocol 与 fake adapter；生产 subprocess adapter 暂不接
      BuildFactory。
- [x] reconcile 仅遍历已 commit authorization，支持 missing outbox、response loss、
      retryable error 与 partial success。
- [x] status projection 区分 available/not_built/authorized/queued/starting/active/
      paused/error，不生成 reject、idle、completed 或 quality score。

### 2.3 Tests

- [x] 新增 `tests/stages/build/approval/test_build_approval_store.py`：
      1/10/11、duplicate、multi-batch、close/reclose、authorize-after-close、
      authorize-close race、stale、idempotency conflict、projection rebuild。
- [ ] 新增 `tests/stages/build/approval/test_build_approval_reconcile.py`：
      batch committed/outbox missing、adapter response loss、partial error、same Team
      receipt replay、restart。
- [ ] 断言 source run tree/hash/event/state 在全部 mutation 后不变。

Review Gate 2：测试完成 `batch A → restart → batch B → close → batch C conflict`；
A/B 每 Card 只有一个 authorization，close 后 A/B reconcile 继续。

Rollback Point 2：可以禁用 Approval CLI；control root 保留为前向兼容证据，不删除或
重写 committed mutations。

## 3. Local Approval server and Dispatch Board UI

### 3.1 HTTP/security

- [x] 新建 `server.py`，借用 Creative review server 的 transport/security pattern，
      不复用其 C6 domain/state machine。
- [x] loopback-only bind、capability→HttpOnly SameSite cookie、Host/Origin、
      fixed methods/routes、body limit、CSP/no-store/no-referrer/nosniff/frame deny。
- [x] 固定实现：
      `GET /api/snapshot`、`GET /api/cards/{ordinal}`、
      `POST /api/authorize`、`POST /api/close`、`POST /api/reconcile`。
- [x] snapshot 不包含完整 Markdown/绝对路径/traceback/token；detail ordinal 不参与
      path construction。
- [x] server 启动、authorize 后与 bounded background interval 运行 reconcile；
      batch commit 后 Browser 关闭不影响 durable intent。
- [x] server restart 生成新 capability，但恢复同一 Approval state。

### 3.2 UI implementation

- [x] 新建 package-owned `index.html/styles.css/app.js`，无前端框架、网络字体或远程
      asset。
- [x] 实现 ticket list、完整纯文本 detail、route/provenance/hash、native checkbox、
      single/multi、select next 10、clear 与 max-10 feedback。
- [x] 实现 sticky batch tray 与二次确认：selected / starts now / queues；
      主动作明确写“批准 N 张并开始 Build”。
- [x] 成功后清 draft、禁用已授权 Card、继续显示/轮询 Team ID 和 status，并允许
      下一批选择。
- [x] 实现 Launch Rail：两个 active slots、FIFO queue、真实状态数据；不是装饰性
      mock。
- [x] 实现 explicit close confirmation、closed read-only state、zero-card empty
      state 与 per-card partial error/retry。
- [x] 所有不可信内容用 DOM node/`textContent`；禁止 `innerHTML`。
- [x] 加 visible focus、keyboard/focus return、ARIA live、窄屏 sticky tray 与
      `prefers-reduced-motion`。

### 3.3 CLI integration

- [x] 在 `src/hacksome/cli.py` 增加 `approve`、`build-status`、
      `build-reconcile`，并对 path/host/port/build executable 做可信参数校验。
- [x] Useful 与 Creative completed/non-empty 输出同一 Approval next command；
      zero-card 输出准确 empty guidance。
- [x] `--no-open` 不调用 Browser；默认 URL 中 token 不进入 persistent state/log。
- [x] 确保现有 `run/status/validate/reconcile/review/resume` 语义与输出回归。

### 3.4 Tests and browser QA

- [x] 新增 `tests/stages/build/approval/test_build_approval_server.py` 覆盖 auth/security/fixed route/error
      mapping/server restart。
- [x] 新增 `tests/stages/build/approval/test_build_approval_cli.py` 覆盖 route-neutral lifecycle 和
      `--no-open`。
- [x] 静态测试断言无 `innerHTML`、远程 asset、任意 URL/path endpoint。
- [ ] 真 Browser QA：single/multi/select-next-10/clear/cancel/confirm、
      batch A+B、refresh、stale/conflict、partial error、queue/active、close、
      zero-card、keyboard、mobile、reduced motion。
- [ ] 截图/证据中移除 join token、cookie 和绝对 credential path。

Review Gate 3：用 fake Build adapter 在真实 Browser 完成多批 Approval；刷新/重启后
状态一致，页面没有 route-specific 分叉或通用 admin-template 漂移。

Rollback Point 3：关闭新 server/CLI 即停止新 authorization；已 commit batch 仍可由
离线 reconcile 恢复。

## 4. Build-side handoff ingestion and registry

### 4.1 Decoder and identity

- [x] 新建 `src/hacksome/stages/build/control/handoff.py`，作为 outer envelope 与 exact
      handoff 的唯一 strict decoder。
- [x] 在任何 state/root 写入前验证 schema、key set、supported version、non-empty、
      UTF-8 Card SHA 与 source identity。
- [x] 实现 canonical envelope/handoff hash、stable Team ID、full identity collision
      check 与 authorization idempotency/conflict。

### 4.2 Registry-before-side-effect

- [x] 新建 `team_registry.py`，用 registry lock + atomic per-Team rows +
      monotonic enqueue sequence。
- [x] registry 先持久化 intent，再调用现有 `TeamLayout.bootstrap()`。
- [x] existing root 只在两份 reference exact match 时 adopt；任何 mismatch fail
      closed，绝不覆盖。
- [x] 保存 desired/observed state、operation ID、attempt、safe error 与 timestamps。
- [x] concurrent same/different authorize 测试证明唯一 Team/root/sequence。

### 4.3 Tests

- [x] 新增 `tests/stages/build/control/test_handoff.py`。
- [x] 新增 `tests/stages/build/control/test_team_registry.py`。
- [ ] 覆盖 malformed/extra key/SHA mismatch、exact replay、changed SHA conflict、
      cross-run same Card ID、truncated ID collision、root-before-row/row-before-root
      recovery 与 partial reference。

Review Gate 4：fake lifecycle 下任意 handoff replay 只得到一个 stable Team；
Agent-visible初始输入仍只有两份 exact reference。

Rollback Point 4：registry rows 是 durable intent，不能删除；未启动的 row 可保持
queued，已启动实例只能通过明确 pause 停止。

## 5. Global pool and operator lifecycle

### 5.1 Pool reconciler

- [x] 新建 `team_pool.py`，默认 `max_active_teams=2`，拒绝零、负数或无界配置。
- [x] 定义 slot-consuming observed states；在 lock 内 reserve/transition，在 lock
      外执行 bootstrap/Compose side effect，再用 operation ID compare-and-apply。
- [x] 初始 queue 按 authorization batch sequence + catalog ordinal 分配
      `enqueue_seq`。
- [x] queued Team 不 create/start 任何 Lead/Worker/Verifier/manager container。
- [x] startup unknown 先 probe/adopt；确认无实例的 error 才释放 slot。
- [x] active Team 不因 Goal done/empty 自动释放 slot。

### 5.2 Operator commands

- [x] 新建 `team_operator.py` fixed CLI：
      authorize/list/inspect/reconcile/pause/resume。
- [x] 所有 mutation 使用 request/operation ID 幂等；输出 strict bounded JSON。
- [x] pause 在全部 Team 实例 stop confirmed 前保持 slot；完成后只释放一次并启动
      earliest queued。
- [x] resume 保留 Team identity/project/Goal/session/telemetry；无 slot 时以新
      enqueue sequence queued。
- [x] 不增加 delete/archive/score/rank/winner/automatic rotate。

### 5.3 Tests

- [x] 新增 `test_team_pool.py` 与 `test_team_operator.py`。
- [x] 10 Team/2 slots、FIFO、concurrent reconcile、start response loss、partial
      stop、late stop、restart、pause/resume no-slot、operation conflict。
- [ ] 断言 Team Goal lifecycle 不被错误映射为 Team completed/idle。
- [x] fake lifecycle 测试默认运行；Compose-specific tests 有清晰 marker/preflight。

Review Gate 5：10 个 authorization 创建 10 个隔离 identity，最多两个占 slot，其余
严格 FIFO；pause 完全停止前不推进 queue，推进后不改变任何 Idea 质量状态。

Rollback Point 5：停止 pool reconciler 不删除 row/root；operator 可对明确 Team 执行
pause。不得用 repo-wide destructive cleanup。

## 6. Cross-process adapter and joined status

- [x] 完成 production `SubprocessBuildControlAdapter`：fixed argv、`shell=False`、
      stdin JSON、bounded timeout/output、minimal environment 与 stable error code。
- [x] Approval authorize/reconcile 调用 Build `authorize`；same authorization 可
      at-least-once 重放。
- [x] Build receipt 的 authorization/team/identity 必须与请求闭包匹配后才能保存。
- [x] status 通过 fixed Build `inspect/list` JSON 回读并由 Approval service
      allowlist 投影；Browser 不读取 registry filesystem。
- [x] 验证 Build unavailable、timeout、invalid JSON、partial batch 和后续恢复。
- [x] 增加 root↔BuildFactory integration tests，默认使用 temporary roots/fake
      lifecycle，不需要 Docker。

Review Gate 6：从 HTTP confirm 到 registry row 的完整路径只跨纯 JSON；任一进程
response 丢失后可重放，Team 数、ID、enqueue sequence 与 reference bytes 不变。

## 7. Full regression, E2E, documentation, and spec capture

### 7.1 Regression commands

- [x] Root lint/type/compile：

  ```bash
  .venv/bin/ruff check src tests
  .venv/bin/mypy src
  .venv/bin/python -m compileall -q src tests
  ```

- [x] Root tests with isolated Codex state：

  ```bash
  CODEX_HOME=/private/tmp/hacksome-test-codex-home \
    .venv/bin/python -m unittest discover -s tests -v
  ```

- [x] BuildFactory tests/config：

  ```bash
  PYTHONPATH=src .venv/bin/python -m pytest tests/stages/build -q
  docker compose -f ops/build/docker-compose.yml config
  ```

- [x] Static UI/diff checks：

  ```bash
  node --check src/hacksome/stages/build/approval_ui/app.js
  git diff --check
  ```

若本机环境没有 Build venv，先使用项目既有安装方式；不得为了通过检查修改全局
Python/Node 环境。

### 7.2 Fault and browser matrix

- [ ] 跑完 design §8 的每个 crash boundary，保存 exact replay assertions。
- [ ] 跑完 design §14.2 Browser matrix，并检查 console/network 无错误或 token
      evidence。
- [ ] 运行 Useful 0-card explicit close、Creative 1-card response-loss replay、
      11-card 10+1 multi-batch/close。

### 7.3 Real joined E2E

- [ ] preflight Docker daemon、Compose、Codex login/account、credential separation、
      writable roots；不把 secret 打印进报告。
- [ ] 真实 Useful challenge → completed → shared Approval → Team。
- [ ] completed Creative → 同一 shared Approval → Team。
- [ ] 至少一个 Team 由真实 Lead 创建 Goal、Worker 产生实质 project diff、fresh
      Verifier verdict。
- [ ] 证明默认 active≤2、queued FIFO、Team root/project/session 隔离。
- [ ] 保存 token-free evidence report；失败时明确区分产品 bug 与外部账户/runtime
      blocker。

### 7.4 Documentation and Trellis

- [x] 更新 README 的 post-card/Approval/Build 操作说明、multi-batch/close/queue
      语义与 preflight。
- [x] 将稳定的跨路线 catalog、Approval ledger/outbox 与 Build registry/pool 合同
      写回对应 `.trellis/spec/`；不要把一次性 task checklist 复制进 spec。
- [x] 更新/归档被本任务吸收的 `07-23-team-pool-operator` planning task，避免后续
      重复实现。
- [x] 运行 `trellis-check`，修复 spec drift、lint/type/test/cross-layer 问题。
- [x] 按逻辑边界 review diff；不得夹带原 workspace 的无关改动。

Review Gate 7 / Done：`prd.md` 全部 Acceptance Criteria 有可定位测试或 E2E 证据；
Useful 与 Creative 共用同一页面/API/Build boundary；无 token/credential、无 source
run mutation、无 duplicate Team。

### 7.5 Trellis check evidence（2026-07-24）

- Root：ruff、mypy（37 source files）、compileall、Node syntax 与
  `git diff --check` 通过；`unittest discover` 285 tests 全通过。
- BuildFactory：新 registry/pool 文件定向 ruff、compileall、Compose config 通过；
  原 BuildFactory `agent/tests` 与 `orchestration/tests` 合计 410 tests 全通过。
- 新增并通过 source-open 后篡改、mutation→outbox crash、subprocess
  unavailable/timeout/invalid JSON/output cap、receipt mismatch、response loss、
  partial batch、start response loss、partial stop/restart、resume-before-pause 与
  partial reference regressions。
- in-app Browser 已实测 12 Cards：batch 10 后 2 active/8 queued，batch 2 后
  2 active/10 queued，close 后状态与队列保持；375px 无横向 overflow，
  console warning/error 为 0。审查修复后又复验 cancel 不授权，以及 HTTP durable
  success 后由后台从 `authorized` 收敛到 2 active/8 queued。stale、
  partial-error、zero-card、keyboard 与 reduced-motion Browser matrix 仍未实测，
  因此上方 Browser QA 保持未勾选。
- 真实 joined E2E 仍受环境阻塞：Docker Desktop daemon 可以启动且当时没有运行中
  容器，但本机缺少 `foundagent/cua-agent:latest` 及其 base image；为避免未经确认
  下载/构建数 GB runtime，本轮没有继续。Codex CLI 已登录但 doctor 因全局
  `AGENTS.md` 非空而 unhealthy。对应真实 E2E 条目保持未勾选；核验后 Docker
  Desktop 已关闭，且未复制 runtime credential。

### 7.6 main 合并回归（2026-07-25）

- 合并 main 后补充 Creative route contract v2 的 post-card 与 Build ingestion
  allowlist；保留 frozen Creative v1 和 Useful v1，并以 current Creative workflow
  projection 及 Build route/version 正反例锁定兼容性。
- 保留 main 的 Creative software-first v2、Pitch CLI/resources、Build shared
  system prompt、六小时 Worker turn timeout/cleanup，以及 legacy role/Skill/mail
  Compose 清理。
- Root `unittest discover` 329 tests、BuildFactory `pytest` 375 tests 全通过；
  Ruff、mypy（40 source files）、compileall、Node syntax、Compose config 与
  staged/unstaged `git diff --check` 全通过。

## 8. Suggested commit sequence and PR handoff

1. `post-card catalog contracts and route adapters`
2. `durable multi-batch approval ledger`
3. `local build dispatch board and CLI`
4. `build handoff registry and bounded team pool`
5. `connect approval outbox to build operator`
6. `prove joined routes and document operations`

每个 commit 都应可运行相关局部测试。当前分支
`codex/idea-card-build-approval` 已改为面向上游 `main` 的 Draft PR，并以普通
merge 吸收最新 main；后续主线漂移继续使用 main-first 冲突处理和完整回归。不要在
未通过真实 joined E2E 与剩余 Browser matrix 时把 PR 标为 ready。
