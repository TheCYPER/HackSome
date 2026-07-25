# Pitch Stage

Pitch 为一个已完成 Project 生成可审计的 deck outline、HTML deck 和逐页讲稿。
流程固定为 Director → Accuracy Review → HTML → Script，Prompt 与 Schema
保存在本目录。

- 输入：operator 显式提供的 Project 目录、Idea Card 文件、challenge 文件和
  新的输出根目录。
- 输出：不可变输入 snapshot、pitch manifest、outline、HTML deck、script 与
  browser smoke 证据。
- 状态：每次运行只写入指定的 `--output-root`；不扫描 Build Team state。
- 启动：`hacksome pitch --project PROJECT --idea-card IDEA.md --challenge
  CHALLENGE.md --output-root OUTPUT`。
- 验证：HTML 发布前会运行 browser smoke；测试位于 `tests/stages/pitch/`。

Build → Pitch 是显式人工交接。`BuildToPitchInput` 只校验并记录来源，不负责发现
或选择 Team。
