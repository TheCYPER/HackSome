# Ideation Stage

Ideation 把 challenge 变成零张或多张可追踪的 Idea Card。`useful/` 使用绝对产品
价值门槛；`creative/` 运行 C0–C7、唯一一次 Human Review、Idea Memory 和
确定性发布。Prompt、Schema 与 Creative review UI 都与所属实现共址。

- 输入：challenge Markdown；Creative 可再接收 brief 与历史 memory policy。
- 输出：run 状态、报告、零张或多张 Idea Card；Creative 还发布带 SHA-256 的
  `IdeaToBuildHandoff` JSON。
- 状态：operator 指定的 `runs/` 下，每个 run 独立持久化。
- 启动：`hacksome run challenge.md`，或加 `--route creative`。
- 验证：`hacksome status RUN`、`hacksome validate RUN`；测试位于
  `tests/stages/ideation/`。

Ideation 不选择 Build Team，也不启动容器。operator 必须校验 handoff、选择
Idea Card，再手工执行 `make -C ops/build init ...`。
