# Team Registry 与全局 Pool 契约

本文描述 `buildfactory/orchestration/handoff.py`、`team_registry.py`、
`team_pool.py` 和 `team_operator.py` 的 active 合同。单 Team 内部 Goal/Worker/
Verifier 仍由 `hackathon-team-runtime-contracts.md` 定义。

## Scope / Trigger

修改 authorization ingestion、Team identity/bootstrap、registry observed state、
全局 slot/FIFO 或 Compose operator 时必须应用本文。任何新的 side effect 都必须先
有 durable registry intent，并证明进程中断后可由同一个 operation 重放。

## Signatures

```python
TeamRegistry.authorize(
    envelope: BuildAuthorizationEnvelopeV1,
) -> dict[str, Any]
TeamPool.reconcile(*, retry_errors: bool = False) -> list[dict[str, Any]]
TeamPool.pause(team_id: str, *, request_id: str) -> dict[str, Any]
TeamPool.resume(team_id: str, *, request_id: str) -> dict[str, Any]
```

进程边界只允许 `python -m orchestration.team_operator
authorize|list|inspect|reconcile|pause|resume`；`authorize` 的 envelope 从 stdin
读取，其余参数必须是可信、有限的 operator 参数。

## 1. Ingestion 与稳定 identity

Build 进程只接受 strict `BuildAuthorizationEnvelopeV1`。outer envelope、source 与
五字段 handoff 都要求 exact key set；route/version allowlist 只支持 Useful v1
以及 Creative v1/v2。BuildFactory 不 import `hacksome` 私有类型；新增 route
contract 必须在两侧显式升级并补跨进程测试。
在任何 root/state 写入前必须复核 Card exact UTF-8 bytes 与 SHA。

稳定 identity：

```text
identity_sha256 = SHA256(canonical JSON {
  source_run_id, idea_card_id, idea_card_sha256
})
team_id          = "team-" + identity_sha256[:24]
authorization_id = "auth-" + identity_sha256[:32]
```

registry 必须检查 full identity，不能只信截断 Team ID。同 authorization exact
replay 返回原 row；changed envelope、同 source/Card changed SHA 或 truncated-ID
collision 都 fail closed。

## 2. Registry-before-side-effect

`TeamRegistry.authorize()` 在 registry lock 下分配单调 `enqueue_seq` 并原子写
per-Team row。只有 row 已持久化后，pool 才能调用 `TeamLayout.bootstrap()` 或
Compose。初始 Agent-visible 输入恰好是：

```text
project/reference/challenge.md
project/reference/initial-idea-card.md
```

existing reference root 只有两份 bytes exact match 才能 adopt；partial/mismatch
不得覆盖。queued Team 不 bootstrap root，不 create/start 容器。

registry row 保存 desired/observed state、operation ID、attempt、safe error 与
authorization receipt state。receipt state 在首次 authorize 后冻结，所以 Team
后来 pause/resume 时重放原 authorization 仍满足严格 receipt enum。

测试入口：`orchestration/tests/test_handoff.py`、
`test_team_registry.py`。

## 3. 两 slot FIFO pool

`TeamPool(..., max_active_teams=2)` 要求有限正整数（实现上限 100）。占 slot 的
observed states 是 `bootstrapping|starting|active|pausing|resuming`；`queued`、
`paused`、已确认 `error` 不占 slot。

reserve/transition 在 registry lock 内完成；bootstrap/Compose side effect 在 lock
外执行，并用 operation ID compare-and-apply。per-Team operation lease 防止并发
reconciler 重复 start/stop。start response unknown 继续占 slot，直到 probe 确认
active 或 stopped；不能乐观释放。

FIFO 使用 `enqueue_seq`。pause 在 stop confirmed 前保持 `pausing` 和 slot；成功后
转 `paused` 并启动最早 queued Team。resume 保留 Team root/project/Goal/session/
telemetry，分配新 enqueue sequence；无 slot 时稳定 queued。Goal done/queue empty
不映射为 Team completed/idle，也不会释放 slot。

普通 pool reconcile 必须继续所有 durable `pausing` operation：进程在写
`pausing` 后退出、stop 只完成部分实例或 stop response 丢失，都不能永久卡住该
slot。只有 probe/stop 再次确认全部实例停止后才转 `paused`；`pausing` 期间的
resume 必须 conflict，不能把仍可能运行的 Team 改回 `queued` 并提前释放 slot。

测试入口：`orchestration/tests/test_team_pool.py`、
`test_team_operator.py`。

## 4. Operator 与 Compose

固定 CLI surface：

```text
authorize  # stdin JSON
list
inspect TEAM_ID
reconcile
pause TEAM_ID --request-id ID
resume TEAM_ID --request-id ID
```

mutation request ID same/same 幂等，same/different 冲突。stdout 只输出 bounded
strict JSON；错误只输出 safe code/message。生产 lifecycle 只使用 fixed
Docker/Compose argv 与可信 registry path；不允许 handoff 文本进入 argv。
`TEAM_STATE_ROOT` 把每个 Compose project 挂到其隔离 Team root。

控制面禁止 delete、archive、score/rank/winner、automatic rotate。停止 pool
reconciler 不删除 row/root；恢复时先 probe/adopt 既有 runtime。

## Validation & Error Matrix

| 条件 | 必须结果 |
| --- | --- |
| envelope/handoff extra key、版本、UTF-8 或 Card SHA 不合法 | registry/root 零写入 |
| authorization exact replay | 返回原 Team 与冻结的首次 receipt state |
| 同 source/Card changed SHA、changed envelope 或截断 ID collision | conflict，绝不 adopt/覆盖 |
| 已有 root 两份 reference exact match | adopt；不重写 bytes |
| partial/mismatched reference root | fail closed；保留证据 |
| active/starting/pausing/resuming 已占满 slot | 新 Team 保持 queued，不 bootstrap |
| start response/probe unknown | 保持 slot 与 durable operation，后续 reconcile |
| pause partial stop 或进程在 `pausing` 后退出 | 保持 slot；reconcile 继续同一 stop operation |
| `pausing` 时 resume | conflict；不得转 queued 或提前释放 slot |
| stop 全部确认 | 转 paused，并只推进最早 `enqueue_seq` |

## Good / Base / Bad Cases

- **Good**：registry row 先写入；Compose start response 丢失后 probe 确认 active，
  operation lease 防止第二个 reconciler 再启动一次。
- **Base**：第三个 authorization 在两个 active slot 后保持 queued，且 Team root
  尚不存在。
- **Bad**：在 stop 未确认时把 Team 标成 paused，或把 `pausing` 排除在 reconcile
  之外；这会分别导致超卖 slot 或永久卡槽。

## Tests Required

- Decoder/identity：malformed/extra key/SHA mismatch、exact replay、changed SHA、
  cross-run same Card ID、truncated collision。
- Registry/bootstrap：20-way concurrent first authorization、row-before-root、
  exact adopt、partial reference、operation/request conflict。
- Pool：10 Teams/2 slots/FIFO、concurrent reconcile、start response loss/error、
  restart、partial/late stop、pause/resume no-slot、`pausing` crash recovery。
- Operator：strict stdin/stdout、安全 error、same/same request replay、
  same/different conflict；断言无 delete/rank/automatic rotate surface。

## Wrong vs Correct

```python
# Wrong: stop 调用一返回就释放 slot；崩溃后 pausing 无恢复路径。
lifecycle.stop(row)
registry.transition(team_id, observed_state="paused")

# Correct: pausing 是 durable、占 slot 的 operation；每次 reconcile 都继续 stop，
# 只有 probe/stop 确认全部实例停止后才转 paused 并推进 FIFO。
registry.begin_pause(team_id)
pool.reconcile()
```
