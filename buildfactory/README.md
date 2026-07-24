# HackSome Build Runtime

这是 HackSome 的 Idea Card → Project 执行层。它保留 BuildFactory 已验证的
双模型 runtime adapter、幂等方法信封、日志、恢复和 Worker/Verifier lifecycle，
但 active runtime 不再是一家公司。

第一版一个 Team 固定由三部分组成：

```text
resident Lead
  -> FIFO Goal
  -> one Worker
  -> one fresh Verifier
  -> next Goal, or wake Lead when the batch drains
```

## 核心契约

- Lead 是唯一常驻 Agent，长期保留 session。
- Team 同时最多一个 Worker、一个 Verifier。
- Lead 可以一次创建任意数量 Goal；系统按创建顺序执行。
- 只要存在非终态 Goal，Lead 模型不会运行；整个 batch 清空后才再次启动 Lead。
- Verifier PASS 后停止当前 Worker，再启动下一 Goal。
- Verifier FAIL 后恢复同一个 Worker、workspace、home 和 session。
- 没有 deadline、`failed_time`、Objective、Department、Notes、mail、自动完成态
  或业务 idle 状态。
- quiet heartbeat 默认每 60 秒检查一次；只有 Goal 队列为空时才唤醒 Lead。
  batch 清空仍会通过 `goal_batch_drained` 立即唤醒。
- Lead 与 Worker 对 `/project` 完整读写；Verifier 的 canonical `/project` 只读。
- 三个 active AgentSpec 都是 `skills: []`。Skill 框架保留，但第一版不物化 Skill。

`/project/reference/challenge.md` 与
`/project/reference/initial-idea-card.md` 只是初始化材料。Agent 可以修改、
重新解释或完全忽略它们。

## 初始化与启动

```bash
make init TEAM=my-team \
  CHALLENGE_FILE=/absolute/path/challenge.md \
  IDEA_CARD_FILE=/absolute/path/initial-idea-card.md

make up TEAM=my-team ACCOUNT=foundagent
make logs-lead TEAM=my-team
make down TEAM=my-team
```

`make init` 只在 `/project` 中创建两份 reference；它拒绝覆盖已有 reference。
之后 `/project` 的组织方式完全由 Team 自己决定。

## Registry、全局 Pool 与 operator

共享 Build Approval 不直接拼 Compose 参数。它通过
`python -m orchestration.team_operator` 的 strict JSON 接口把每张获批 Card
登记为一个稳定 Team：

```bash
python3 -m orchestration.team_operator list \
  --build-root state/build-pool \
  --max-active-teams 2 \
  --json

python3 -m orchestration.team_operator inspect team-<identity> \
  --build-root state/build-pool \
  --max-active-teams 2 \
  --json
```

`authorize` 只从 stdin 接受 exact envelope；registry row 在任何
`TeamLayout.bootstrap()` 或 Compose side effect 之前持久化。Team identity 绑定
source run、Card ID 与 Card SHA；重放同一 authorization 只返回原 Team，内容漂移
则 fail closed。已有 Team root 只有在两份 reference bytes 完全相同时才可 adopt。

Pool 默认最多两个 slot，`queued` Team 不创建 project root 或容器。FIFO 顺序来自
registry 的单调 `enqueue_seq`。active Team 不会因 Goal 队列清空自动退出；显式
控制命令为：

```bash
python3 -m orchestration.team_operator pause team-<identity> \
  --request-id pause-<stable-id> \
  --build-root state/build-pool --json

python3 -m orchestration.team_operator resume team-<identity> \
  --request-id resume-<stable-id> \
  --build-root state/build-pool --json
```

pause 只有在所有 Team runtime 停止得到确认后才释放 slot；resume 保留原 Team
identity、project、Goal、session 与 telemetry，并以新的 enqueue sequence 入队。
控制面没有 delete、archive、score、winner 或自动轮转路径。

## 确定性方法

Lead Prompt 内直接包含：

```bash
python3 -m orchestration.control_client create_goal \
  --json '{"intent":"concrete work","acceptance":"optional verifier-only context"}' \
  --request-id 'goal-<stable-purpose-id>'

python3 -m orchestration.control_client list_my_goals

python3 -m orchestration.control_client cancel_goal \
  --json '{"goal_id":"goal-...","reason":"why"}' \
  --request-id 'cancel-<goal-id>'
```

Worker 使用空业务 payload 的 `submit_result`；Verifier 使用
`submit_verdict(PASS|FAIL, reason)`。自然语言声明不会推进 Hub 状态。

## 验证

```bash
make validate

# 完整 Python 回归
.venv-cua/bin/python -m pytest agent/tests orchestration/tests
```

Active 契约见
`.trellis/spec/backend/hackathon-team-runtime-contracts.md` 与
`.trellis/spec/backend/team-registry-pool-contracts.md`。旧 Company、mail、
Department 和 Peripheral 源码暂时保留为 BuildFactory 上游参考，但不进入
`docker-compose.yml` 的 active runtime。
