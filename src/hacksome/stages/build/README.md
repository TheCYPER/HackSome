# Build Stage

Build 使用一个常驻 Lead、至多一个 Worker 和每轮新建的 Verifier，把选中的
challenge 与 Idea Card 落成 Project。Python runtime 在本目录；Compose、
Docker、Makefile 和账户模板在 `ops/build/`。

- 输入：operator 显式提供的 challenge 和 Idea Card 文件。
- 输出：`ops/build/state/TEAM/project/` 下的 Project，以及 ledger、review 和
  telemetry 状态。
- 状态：`ops/build/state/`；账户材料在 `ops/build/accounts/`。两者都被 Git
  忽略，不属于 package。
- 初始化：`make -C ops/build init TEAM=my-team CHALLENGE_FILE=/abs/challenge.md
  IDEA_CARD_FILE=/abs/idea.md`。
- 启动：`make -C ops/build up TEAM=my-team`。
- 验证：`make -C ops/build validate`；测试位于 `tests/stages/build/`。

Build 不自动读取 Ideation runs。完成后也不会自动启动 Pitch；operator 需要把
Project、Idea Card 和 challenge 显式传给 `hacksome pitch`。
