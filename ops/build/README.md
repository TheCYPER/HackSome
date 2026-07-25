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
