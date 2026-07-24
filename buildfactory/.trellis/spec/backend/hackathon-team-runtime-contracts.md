# Hackathon Team Runtime 契约

> 本文描述 HackSome `buildfactory/` 的 active 第一版。旧 V7 Company Python 源码仍可
> 作为上游实现参考，但不再保留生产角色 YAML、业务 Skill 或独立 mail Compose，
> 也不得进入 active Compose、Prompt、角色 loadout 或方法白名单。

## 1. 固定内核

每个 Team 只有：

- 一个长期 resident Lead；
- 一个严格 FIFO Goal ledger；
- 最多一个一次性 Worker lifecycle；
- 最多一个 fresh Verifier instance；
- 一个确定性 Team Hub。

Lead 可以在一次 wake 中创建多条 Goal。系统依次执行
`Worker -> Verifier`；当前 Goal PASS 且 Worker 确认停止后才启动下一 Goal。
FAIL 恢复同一 Worker、workspace、home 与 session。队列清空后向 Lead 投递一次
稳定去重的 `goal_batch_drained` trigger。

Lead 模型只允许在所有 Goal 均为 `done` / `cancelled`（或尚无 Goal）时启动。
存在 `open / claimed / running / reported / verifying` Goal 时，resident loop 保留
消息并跳过模型调用。Heartbeat 只检查空队列，不得在 Worker/Verifier 执行期间让
Lead 继续扩充队列。

## 2. Project State

唯一 Agent-facing 状态是：

```text
state/<team>/project -> /project
```

Lead、Worker 为读写挂载，Verifier 为只读挂载。Ledger、Inbox、Workers、Reviews、
Control、Sessions 与 Telemetry 不挂载给模型。

Team bootstrap 只创建：

```text
project/reference/challenge.md
project/reference/initial-idea-card.md
```

两份文件只是 initializer，不是 Objective 或冻结需求。之后 Agent 可以修改、移动、
删除、重新解释或忽略它们，也可以自由组织 `/project`。

## 3. Goal 状态

```text
open -> claimed -> running -> reported -> verifying -> done
                                      FAIL -> running
```

另有显式 `cancelled`。不存在 deadline、`failed_time`、blocked、waiting、自动完成或
替代关系。系统只限制并发 Worker 数量为 1，不限制 open Goal 数量。

Worker 只看到 Goal intent。可选 acceptance 只保存到 review payload 并进入 Verifier
Prompt。`submit_result` 只接受空 payload。

## 4. Prompt 与 Skill

Lead Prompt 是固定运行契约加一个动态 trigger，包含：

- Hackathon Lead 定位和真实产品标准；
- `/project` 与 initializer 语义；
- `create_goal`、`list_my_goals`、`cancel_goal` 的完整 CLI；
- 保留完整工具权限，但职责上只检查、判断、设计并通过 Goal 委派实质工作；
- 禁止 Lead 自己创建、修改、测试或部署产品产物，真实实施只由 Worker 承担；
- 无 deadline、完成态、Objective、固定阶段或目录 taxonomy。

Worker Prompt 包含 Goal intent、`/project` 权限与完整 `submit_result` 命令。
Verifier Prompt 包含 intent、private acceptance、只读职责与完整
`submit_verdict` 命令。

生产 AgentSpec 只能是 `lead.yaml`、`team-worker.yaml` 和
`team-verifier.yaml`，三者必须精确声明 `skills: []`。Skill materialization
框架保留，但仓库不再附带、发现或物化任何业务 Skill。

## 5. Active 方法白名单

Lead：

```text
wake_context / peek_message / ack_message / wake_completed
create_goal / list_my_goals / cancel_goal
```

Worker：`submit_result`。

Verifier：`submit_verdict`。

Manager 只获得 Worker/Verifier lifecycle callback。Objective、Department、Notes、
mail、messaging 和 Peripheral 方法必须返回 `unknown_method`。

所有 mutation 保留 V7 版本化信封、actor binding、request-id 幂等缓存和审计。

## 6. Active Compose

`docker-compose.yml` 只能包含：

```text
hub / lead / worker-manager / verifier-manager
```

Lead 启动不得覆盖 CUA 镜像 startup hook；它通过 `AGENT_LOOP_MODULE` 选择
`orchestration.lead_loop`，从而保留 computer-server 与零 Skill materialization。

## 7. 最低质量门

```bash
.venv-cua/bin/python -m compileall -q agent orchestration
.venv-cua/bin/python -m pytest agent/tests orchestration/tests
docker compose config -q
git diff --check
```

必须覆盖：两 reference bootstrap、零 Skill、完整 Prompt 方法、acceptance 私有、
两 Goal FIFO、FAIL 同 session 返工、fresh Verifier、batch-drained 去重、旧 active
方法禁用以及 `/project` 权限边界。

## 8. 场景：维护或扩展 active Team Runtime

### 1. Scope / Trigger

修改 Team bootstrap、Prompt builder、Hub 方法、Goal/review payload、Compose service、
动态容器挂载或 resident startup 时，必须检查本节。active Team path 不得为了复用
HTTP transport 或 helper 而间接 import Company Objective、Department、mail 或
Peripheral 模块。

### 2. Signatures

Bootstrap：

```text
TeamLayout.bootstrap(
  root,
  challenge_markdown: str,
  initial_idea_card_markdown: str,
) -> TeamLayout
```

方法信封：

```json
{"version":1,"request_id":"stable-id","method":"create_goal","payload":{"intent":"...","acceptance":"..."}}
```

Active 环境变量：

```text
TEAM / TEAM_STATE_ROOT / TEAM_NETWORK / TEAM_MODE=1
AGENT_KEY=lead / AGENT_KIND=lead
AGENT_LOOP_MODULE=orchestration.lead_loop
AGENT_HEARTBEAT_SECS=60（默认，可由 LEAD_HEARTBEAT_SECS 覆盖）
WORKER_MAX=1 / VERIFIER_MAX=1
```

### 3. Contracts

- Bootstrap 在同一文件系统 staging directory 中写好两个 UTF-8 leaf，再以一次目录
  rename 发布 `reference/`；失败不得留下半套 reference。
- Team HTTP transport 只依赖 method adapter、run logs 与 Team Hub，不 import
  `company_hub.py`。
- resident Lead 不覆盖镜像 entrypoint。`vm/docker/agent_startup.sh` 仍先启动
  computer-server、运行 loadout materialization，再执行 `AGENT_LOOP_MODULE`。
- resident Lead 的 quiet heartbeat 默认 60 秒；Goal batch 清空继续使用即时
  `goal_batch_drained` trigger，不等待 heartbeat。每次模型 wake 前必须通过
  `list_my_goals` gate；任一非终态 Goal 都会抑制该次 wake。
- Worker 动态容器挂载 `<project>:/project`；Verifier 挂载
  `<project>:/project:ro`。
- Team 动态容器使用 `hacksome.team=<team>` label，必须与 `make down` 的过滤器一致。
- `acceptance` 只能从 Goal ledger 流向 review payload 和 Verifier Prompt，不能进入
  Worker command/prompt 或 Lead 的 Goal projection。

### 4. Validation & Error Matrix

| 条件 | 结果 |
|---|---|
| challenge 或 idea card 不是可编码 UTF-8 文本，或含 NUL | `StoreError`，不发布 reference |
| `reference/` 已存在 | `StoreError`，不覆盖 Agent 已修改的 initializer |
| 第二份 reference 写入失败 | 清理 staging，`project/` 中无半套 reference |
| Lead 调用 Objective/Department/Notes/mail 方法 | `unknown_method` |
| Worker `submit_result` payload 非空 | `invalid_state`，Goal 不推进 |
| Verifier review id 或 instance 不匹配 actor binding | `invalid_state`，verdict 不接受 |
| 相同 request id 重放相同方法/payload | 返回原响应，不重复创建 Goal |
| 相同 request id 改变方法或 payload | `idempotency_conflict` |
| Team Hub restart 时 batch 已通知 | 不重复追加 `goal_batch_drained` |

### 5. Good / Base / Bad

- Good：Lead 一次创建两条 Goal；第二条保持 `open`，第一条 PASS 且 Worker stop 后
  才 claim 第二条。
- Good：Worker 或 Verifier 执行期间 heartbeat 到期，resident Lead 只记录
  `wake suppressed by gate`，不启动模型、不追加 Goal。
- Good：Lead 读取 `/project` 形成判断，但只通过 Goal intent 推动产品修改；权限层
  不禁止写入，Prompt 的职责分离禁止它取代 Worker。
- Base：Worker 首次结果 FAIL；相同 worker id、home、workspace 与 session 收到
  `resume_worker`，修复后由新 Verifier review。
- Good：Lead heartbeat 没有消息时仍检查真实项目并继续改进，但 Hub 不创建 idle 或
  completion 状态。
- Bad：从 Team Hub import `CompanyHub` 只是为了复用 HTTP handler；这会让 active
  启动重新加载 Department/PyYAML 等 Company 产品依赖。
- Bad：在 Compose 为 Lead 设置新 entrypoint；这会绕过 CUA computer-server 与
  materialization startup hook。
- Bad：Lead 因为拥有 `/project` 读写挂载就直接搭 demo；完整权限是能力边界，不是
  角色职责，实质产品工作必须形成 Goal 交给 Worker。
- Bad：降低 heartbeat 后不检查 Goal 状态，导致 Lead 在 Worker 执行期间每分钟追加
  新 Goal；heartbeat 必须先经过空队列 gate。

### 6. Tests Required

- `orchestration/tests/test_team_runtime.py`
  - atomic two-reference bootstrap 和 partial-write cleanup；
  - 两 Goal FIFO、PASS/FAIL、same-session resume、fresh Verifier；
  - request-id replay、acceptance 私有、batch-drained restart 去重；
  - Worker `/project:rw` 与 Verifier `/project:ro` Docker argv。
- `agent/tests/test_team_loadout.py`
  - Lead、Worker、Verifier 的 AgentSpec 与真实 materialization 均为零 Skill。
- `orchestration/tests/test_compose_accounts.py`
  - active service 精确集合、Team env、startup module 和 Docker socket 边界。

### 7. Wrong vs Correct

Wrong：

```python
from orchestration.company_hub import HubHTTPServer
# Team 启动因此间接加载 Objective、Department 和 mail 产品面。
```

Correct：

```python
from orchestration.team_http import TeamHTTPServer
# Transport 只依赖 Team active contract。
```

Wrong：

```yaml
lead:
  entrypoint: ["python3", "-m", "orchestration.lead_loop"]
```

Correct：

```yaml
lead:
  environment:
    AGENT_LOOP_MODULE: orchestration.lead_loop
```
