# Post-card 与 Build Approval 合同

本文记录 Useful/Creative 最终 Idea Card 之后的共享边界。它不定义两条路线如何判断
Idea 质量，也不把 Approval 变成第二次评审。

## Scope / Trigger

修改以下任一边界时必须应用本文：completed run → shared catalog、Approval
mutation/outbox/receipt、loopback HTTP/UI、root → Build subprocess。实现者必须同时
检查 source 完整性、幂等、崩溃重放与浏览器安全；只改其中一层而不追踪整条数据流
是不完整的。

## Signatures

```python
project_post_card_catalog(run_dir: str | Path) -> PostCardCatalogV1
ApprovalService.open(
    run_dir: str | Path,
    *,
    approval_root: str | Path | None = None,
    build_adapter: BuildControlAdapter | None = None,
) -> ApprovalService
ApprovalService.authorize(payload: Mapping[str, Any]) -> dict[str, Any]
ApprovalService.close(payload: Mapping[str, Any]) -> dict[str, Any]
ApprovalService.reconcile() -> dict[str, Any]
```

CLI surface 是 `hacksome approve|build-status|build-reconcile|build-validate
RUN_DIR`。Browser 只调用本文第 3 节列出的固定 HTTP 路由。

## 1. Route-neutral catalog

唯一入口是：

```python
project_post_card_catalog(run_dir: str | Path) -> PostCardCatalogV1
```

它只接受 schema v2、`completed`、`validate_run()` 无错误且
`route.id + contract_version` 已注册的 run。Useful 适配器从权威
`idea_card_ids` 与 `challenge-brief` 投影；Creative 适配器从 C7 success report
读取最终 Card/handoff 列表，并采用已冻结的 handoff bytes。共享层不得读取
route-specific state 字段。

`BuildHandoffV1` 永远只有以下五个字段：

```json
{
  "source_run_id": "run-id",
  "idea_card_id": "card-id",
  "idea_card_sha256": "<sha256>",
  "challenge_markdown": "# Challenge\n",
  "initial_idea_card_markdown": "# Card\n"
}
```

decoder 拒绝缺字段、额外字段、非 UTF-8/NUL、非 canonical SHA 以及 Card bytes/hash
不一致。Catalog 保留 route 权威顺序，ordinal 必须从 0 连续递增；catalog hash 是
去掉自身 hash 字段后的 canonical JSON SHA-256。zero-card catalog 合法。

测试入口：`tests/test_post_card_contracts.py`、
`tests/test_post_card_useful.py`、`tests/test_post_card_creative.py`。

## 2. Approval ledger 与 source 完整性

`ApprovalService.open()` 首次成功时在 source run 外冻结 `catalog.json`。重开会重新
投影 source；任何 mismatch/tamper 只设置 `source_integrity_error`，禁止新的
authorize/close，但不会撤销旧 authorization。既有 Approval 的 status/validate
不重写 source run 或损坏的 `state.json`。长生命周期 server 不能只信启动时检查；
每次 authorize/close mutation 前都必须重新投影并比对 frozen catalog。

每个 authorize request 必须：

- exact schema v1，稳定 `request_id`，绑定 frozen catalog hash；
- 选择 1–10 个不同、尚未授权且 Card ID/SHA exact match 的 Card；
- 在 server 内按 catalog ordinal canonicalize；
- 同 request/same content 重放原 batch；same request/different content 冲突；
- 任一 Card 已授权、stale 或 Approval closed 时整批零写入。

成功边界是一份 append-only mutation。mutation reader 必须重新验证 exact 字段、
sequence/filename、request hash、batch ID、Card ordinal/hash/order、envelope/hash
及 frozen catalog closure，不能信任可重建的 `state.json`。显式 close 独立、
不可逆、幂等；它不改变已授权 delivery/Team。

mutation commit 后，`ensure_outboxes()` 可补齐逐 Card outbox。outbox 必须 exact
绑定 batch sequence、catalog ordinal 与 envelope；Build receipt 只有在
authorization/team/identity 全闭包后才能冻结。response loss 或进程中断通过
`reconcile()` at-least-once 重放，不得生成第二个 Team。

HTTP authorize 的成功边界是 mutation + outbox intent 已 durable；它不能同步等待
可能超时的 Build subprocess。Server 只唤醒单一后台 reconciler，并立即返回 202；
timeout、invalid JSON、receipt mismatch 与 partial batch error 保留为逐 Card
delivery 状态，由后台或显式 reconcile 重试。

测试入口：`tests/test_build_approval_store.py`、
`tests/test_build_approval_integration.py`。

## 3. 本机 HTTP 与 UI

`BuildApprovalServer` 只允许 loopback bind。一次性 `/join/<token>` 只换取
HttpOnly、SameSite=Strict cookie；token 不写日志或持久化。固定路由只有：

- `GET /`, `/assets/styles.css`, `/assets/app.js`
- `GET /api/snapshot`, `/api/cards/{ordinal}`
- `POST /api/authorize`, `/api/close`, `/api/reconcile`

所有请求执行 Host/Origin、method、Content-Type/charset、Content-Length/body
limit 与 strict JSON 检查。响应设置 no-store、no-referrer、nosniff、frame deny 与
无 inline/remote asset 的 CSP。Card detail 用 ordinal 查内存 catalog，不能参与
路径构造；snapshot 不返回绝对路径、完整 Markdown、token 或 traceback。

UI 只能用 `textContent`/DOM node 渲染不可信内容。批次上限、不可逆 close、两个
active slots、FIFO queue、partial error/retry 都必须来自真实 snapshot，不得做
装饰性 mock。

测试入口：`tests/test_build_approval_server.py`、
`tests/test_build_approval_cli.py`；静态检查还需运行
`node --check src/hacksome/build_approval_ui/app.js`。

## 4. Build process boundary

`SubprocessBuildControlAdapter` 只允许 fixed argv、`shell=False`、stdin strict
JSON、minimal environment、bounded timeout/output。root 侧不得 import
`buildfactory` 私有类型；Build 侧也不得 import `hacksome`。authorize receipt 与
list/reconcile status 都由各自 decoder allowlist 后才进入 Approval projection。

Browser API 永远不能提交 filesystem path、executable、Compose service、环境变量
或任意命令。这些只能由 CLI 的可信启动参数提供。

## Validation & Error Matrix

| 条件 | 必须结果 |
| --- | --- |
| run 非 completed/v2、离线校验失败或 route/version 未注册 | catalog projection fail closed；零 Approval/Build 写入 |
| frozen catalog 后 source bytes/hash 改变 | status 只读显示 integrity error；新的 authorize/close 冲突 |
| authorize 为空、超过 10、Card 重复、stale hash 或已授权 | 整批拒绝；不可留下部分 mutation |
| same request ID + same canonical payload | 返回原 batch，不重复 Team |
| same request ID + different payload | idempotency conflict |
| mutation/outbox/receipt 字段、hash、顺序或闭包被改 | offline validate/reconcile fail closed |
| Build timeout、坏 JSON、输出超限或 receipt mismatch | HTTP 已持久化 authorization 不回滚；逐 Card delivery error 可重试 |
| explicit close 后再 authorize | `approval_closed`；既有 queued/active Team 不变 |
| 非 loopback、Host/Origin/method/body 不合法 | 固定安全 HTTP error；不执行 mutation |

## Good / Base / Bad Cases

- **Good**：batch 已落盘、HTTP 立即返回 202；后台在 response loss 后重放 outbox，
  Build 返回同一个 Team receipt。
- **Base**：用户打开页面、刷新或提交空选择；没有 authorization，也不隐式 close。
- **Bad**：HTTP handler 同步等待 Compose，或只在 server 启动时校验 source；前者会
  把 durable success 误报为超时，后者允许打开页面后篡改 Card 再授权。

## Tests Required

- Catalog：Useful/Creative 0/1/N、stable order/hash、exact bytes、unknown/incomplete/
  tampered source；断言 source tree 不变。
- Ledger：1/10/11、multi-batch、duplicate、stale、same/same replay、
  same/different conflict、close race、projection/outbox/receipt tamper。
- Reconcile：missing outbox、timeout、invalid/oversize output、response loss、
  partial batch；断言 authorization/Team identity 唯一。
- HTTP/UI：fixed routes、cookie/Host/Origin/CSP/body limits、snapshot allowlist、
  text-only rendering、serialized polling、dialog cancel/confirm、多批与 close。
- 静态门禁：Ruff、mypy、compileall、Node syntax 与 `git diff --check`。

## Wrong vs Correct

```python
# Wrong: source 只在 server open 时检查，且 mutation request 同步等待 Build。
service = ApprovalService.open(run_dir)
receipt = build.authorize(service.commit(payload))

# Correct: 每次 mutation 前重投影 source；durable mutation + outbox 是 HTTP 边界，
# Build delivery 由单一后台/显式 reconciler at-least-once 执行。
service.authorize(payload)  # durable intent, immediate response
service.reconcile()         # idempotent delivery and strict receipt closure
```

## 禁止模式

- 不从 Markdown index、title prefix 或 raw route state 猜 Card；
- 不在 source run 内写 Approval/Team state；
- 不用 `state.json` 代替 immutable mutation 作为授权事实；
- 不因 Browser 关闭、Approval close 或 Goal done 撤销/停止 Team；
- 不增加 reject、quality score、winner、idle/completed 或自动轮转语义。
