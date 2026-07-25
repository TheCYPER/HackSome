# Build operations

这里是 HackSome Build Stage 的 operator surface，不是第二个 Python 产品。
生产模块和 Agent assets 位于 `src/hacksome/stages/build/`；本目录只保存
Makefile、Compose、Docker 配置和账户模板。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'

make -C ops/build init TEAM=my-team \
  CHALLENGE_FILE=/absolute/path/challenge.md \
  IDEA_CARD_FILE=/absolute/path/idea-card.md
make -C ops/build up TEAM=my-team
make -C ops/build logs TEAM=my-team
make -C ops/build down TEAM=my-team
```

可变 Team 状态写到 `ops/build/state/TEAM/`。账户 cookies、secrets 和 CLI 配置
放在 `ops/build/accounts/ACCOUNT/`；两者均被 Git 忽略。模板说明见
`account-templates/README.md`。

`make -C ops/build validate` 校验 Compose、编译 Build package 并运行 Build
测试。它不会初始化 Team、启动容器或调用模型。

## Registry、全局 Pool 与 operator

共享 Build Approval 通过统一 package 中的 strict JSON operator 把每张获批
Card 登记为稳定 Team：

```bash
PYTHONPATH=src .venv/bin/python \
  -m hacksome.stages.build.control.team_operator list \
  --build-root ops/build/state/build-pool \
  --max-active-teams 2 --json
```

Registry row 会先于 `TeamLayout.bootstrap()` 或 Compose side effect 持久化。
Pool 默认最多占用两个 slot，其他 Team 按 `enqueue_seq` FIFO 排队；queued Team
不会创建 project root 或容器。`pause` 只有在所有 Team runtime 停止得到确认后才
释放 slot，`resume` 保留原 Team identity、project、Goal、session 与 telemetry。
控制面不提供 delete、score、winner 或自动轮转。

## Lead reflection memory rollout

Lead 的 bounded reflection checkpoint 默认关闭。只对明确的试验 Team 开启：

```bash
LEAD_REFLECTION_MEMORY_ENABLED=1 make -C ops/build up TEAM=my-team
```

开启后，Hub 在每次 Lead wake 注入至多一份当前 snapshot，并只向固定 `lead`
actor 暴露 `read_lead_brief` 与 `checkpoint_lead_brief`。Worker 和 fresh
Verifier 不获得该 Skill、Hub capability 或 control-state mount。当前 snapshot
位于 `ops/build/state/TEAM/memory/lead-brief.md`；`events.jsonl` 只含 revision、
action、byte/hash、freshness 和错误码等元数据，不含 Markdown 正文。两者都属于
控制面，不应出现在 `/project` 或产品 Git 状态中。

Rollout 检查应至少覆盖三个 `goal_batch_drained` wake：观察 `read`、`replace`、
`no_op`、`stale`、`missing`、`error` 事件，确认没有重复 Goal、已知安全/隐私
不变量仍在 brief 中，并比较重复 README/全树读取次数。Codex
`turn.completed.usage` 现在来自独立的 refreshed Lead session；应把每个 wake
的 snapshot 直接作为该轮用量，不能跨 session 相减。

回滚时把 `LEAD_REFLECTION_MEMORY_ENABLED` 设回 `0` 并重启该 Team。Hub 会停止
注入和更新、移除 brief capabilities，既有 `memory/lead-brief.md` 保留，方便
之后恢复；不要删除或搬入 `/project`。

## Local-network image builds

网络环境无法稳定访问默认 Docker/Ubuntu/npm endpoints 时，可显式使用
`docker-compose.local.yml`。它只改变镜像获取与构建来源，不改变 Team state、
账户目录、角色 mount 或 lifecycle：

```bash
make -C ops/build up-local TEAM=my-team ACCOUNT=foundagent
make -C ops/build validate-local
make -C ops/build down-local TEAM=my-team ACCOUNT=foundagent
```

默认 local build 先从 `registry-1.docker.io` 构建
`foundagent/cua-ubuntu:local`，再用可配置的 Ubuntu 与 npm mirror 构建
`foundagent/cua-agent:local`；控制面基础镜像默认通过 DaoCloud 的 Docker Hub
mirror 获取。所有值都可在命令行覆盖，例如
`BASE_REGISTRY=registry-1.docker.io`、`CONTROL_BASE_REGISTRY=docker.io/library`
或 `NPM_REGISTRY=https://registry.npmjs.org`。

这个 overlay 不包含 proxy、credential、account/state 内容或本机绝对路径。
`validate-local` 只渲染 Compose 并运行静态回归；它不能证明 registry、apt、npm
或 Docker daemon 当前可达。首次部署仍需运行 `build-local`/`up-local`，并检查
Lead、动态 Worker 和 Verifier 的 desktop、`computer_server` 与模型 runtime。
