# ClaudeHack Pitch 实现研究与 HackSome 取舍

日期：2026-07-24

## 1. ClaudeHack 当前做法

本地仓库：`/Users/weston/dev/ClaudeHack`

Stage 5 是一个很直接的确定性串行流水线：

```text
Storyteller → pitch-script.md
Deck Builder → pitch-deck.html
```

证据：

- `control/stages/stage5.py:1-5` 明确定义两 session 串行；
- `control/stages/stage5.py:48-56` 为每个项目建立独立 workspace/output；
- `control/stages/stage5.py:70-78` 给 Storyteller 独立工作目录并把 demo 暴露进去；
- `control/stages/stage5.py:93-101` 通过 SessionManager 启动 Storyteller；
- `control/stages/stage5.py:103-119` session 失败或缺少输出文件就停止；
- `control/stages/stage5.py:135-157` 把 script 交给独立 Deck Builder；
- `control/stages/stage5.py:169-195` 检查并收集最终文件。

ClaudeHack README 的总体原则也适合复用：

- `README.md:270-275`：control script 是确定性 if/then，不是 AI；
- `README.md:276-279`：Session 相互隔离；
- `README.md:281-284`：阶段通过文件系统交接。

## 2. ClaudeHack Prompt 做了什么

Storyteller：

- 读取 concept/logic/technical 和 demo；
- 理解用户、问题、差异、流程；
- WebSearch 一个 hook；
- 直接写 400–600 字完整 script；
- 使用固定 Hook → Problem → Solution → Demo → Closing。

证据：`prompts/stage5/storyteller.md:28-54`、`prompts/stage5/storyteller.md:58-109`。

Deck Builder：

- 读取完整 script；
- 固定规划 6–8 页；
- 固定 title/hook/problem/solution/demo/architecture/closing；
- 固定 dark theme；
- 生成自包含 HTML 和键盘导航；
- 要求内容只能来自 script。

证据：`prompts/stage5/deck-builder.md:24-56`、`prompts/stage5/deck-builder.md:60-109`。

## 3. 值得复用

- 确定性中控；
- 独立 Agent session；
- 独立工作目录；
- 文件式 handoff；
- 上一步失败就不启动下一步；
- 每个 Project 独立，项目间可以并行；
- 自包含 HTML 和键盘导航。

## 4. 不应照搬

### 4.1 顺序相反

ClaudeHack 先写完整 script，再让 deck 迁就 script。新需求明确要求：

```text
先写每页大纲 → Review 内容 → 制作 HTML → 看最终 HTML 写 script
```

这样 deck 是主产物，script 服务于已经确定的视觉演示。

### 4.2 Storyteller 职责太重

旧 Storyteller 同时理解产品、研究 hook、决定结构、写完整讲稿。新版 Pitch Director
只负责每页大纲，内容 Reviewer 独立检查。

### 4.3 模板过早固定

旧 Prompt 固定页数、固定章节和 dark theme。新版保持一个 Planner，但让它根据
Project、Idea Card 和 challenge 自己决定结构和视觉方向。

### 4.4 验证太弱

旧 Deck Builder 最后的显式检查只是 `wc -l`；仓库未找到 Stage 5 专项测试或现存
实际 output 样例。新版至少需要真实浏览器打开、导航和逐页版面检查，但无需再增加
Visual Reviewer Agent。

### 4.5 输入应是 Project 副本

旧版通过 symlink 读取 live demo。新版 Snapshot 就是完整复制 Project，四个 Agent
都直接读这份副本；不需要 Snapshot summarizer 或 EvidenceBundle。

## 5. 对 HackSome 的最终建议

```text
Project copy + Idea Card + challenge
  → Pitch Director
  → Accuracy Reviewer
  → HTML Agent
  → Script Agent
```

Controller 保持 ClaudeHack 风格的简单 Python 顺序驱动。真正需要投入设计的是四个
Prompt，尤其是：

- Director 如何既理解产品又保持克制；
- Reviewer 如何只删错内容而不继续堆内容；
- HTML Agent 如何忠实实现 outline 并实际验证；
- Script Agent 如何严格跟随最终 deck。
