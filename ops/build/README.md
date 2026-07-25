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
