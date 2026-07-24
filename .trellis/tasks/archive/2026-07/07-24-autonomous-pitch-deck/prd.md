# 自主 Pitch Deck 生成

## Goal

在 Ideation 和 Building 之后增加一个简单、自动的 Pitch 流程。系统读取当时完整复制
出来的 Project、原始 Idea Card 和 hackathon 题目，像人制作演示一样依次完成：

```text
写每页大纲 → Review 大纲 → 制作 HTML deck → 根据 deck 写 script
```

核心价值是让 Agent 真正理解已经做出来的产品，并把它压缩成清楚、克制、有说服力、
可以直接演示的 Pitch，而不是设计复杂的 Build 生命周期或 Snapshot 状态机。

## Background

- 当前 Build Lead 明确不负责 pitch deck、speaker script 或 judge-facing 包装；
  Pitch 是 Building 之后的独立阶段。
- Pitch 启动、停止 BuildFactory 和复制 Project 可以由 operator/外层流程显式完成。
- 本任务的重点是复制完成之后，四个 Agent 如何把 Project 变成高质量 Pitch。
- ClaudeHack 的 Stage 5 已验证了“确定性 Python 中控 + 独立 Session + 文件式串行
  handoff”这条基本路径，但旧顺序是 script → HTML，且没有内容 Review。

## Requirements

### R1. 简单 Snapshot 输入

- Snapshot 就是把目标 Team 当时的完整 `project/` 目录复制到本次 Pitch workspace。
- 不生成 Snapshot 摘要、EvidenceBundle、事实投影或复杂 manifest。
- 四个 Pitch Agent 都可以只读访问同一份 Project 副本，并自行阅读源码、文档、
  assets、测试和现有 demo。
- Project 副本之外，workspace 还提供对应 Idea Card 与原始 hackathon 题目。
- Agent 不读取 live Project；复制完成后的 live 变化不会进入本次 Pitch。
- 如何暂停、停止或恢复 BuildFactory 不属于 Pitch Agent 编排的主体；第一版可以由
  operator/外层流程处理。

### R2. Pitch Director：先写每页大纲

- Pitch Director 读取完整 Project 副本、Idea Card 和 hackathon 题目。
- 它先理解产品实际做了什么，再设计整个 deck 的叙事主线。
- 输出 `deck-outline.md`，逐页写清：
  - 稳定 slide ID；
  - 本页唯一要传达的意思；
  - 页面上实际出现的标题与精简内容；
  - 建议使用的产品画面、demo 动作或视觉表达。
- Director 可以创造标题、hook、比喻、转场和有趣的叙事方式。
- 不固定 Useful/Creative 两套模板，也不固定 slide 数、章节名称或顺序。
- 必须保持克制：一页只承担一个主要意思；不为了显得完整而添加背景、技术细节、
  总结或重复页面。
- 不得把 Project 中不存在的功能写成已经完成。

### R3. Accuracy Reviewer：只 Review 内容

- Reviewer 使用独立于 Director 的 session，读取相同 Project 副本、Idea Card、hackathon
  题目和 `deck-outline.md`。
- 它只检查：
  - 是否准确描述了真实产品；
  - 是否回应题目；
  - 主线是否清楚；
  - 是否有重复、无关或过多内容；
  - demo 与关键主张是否由 Project 支持。
- Reviewer 不写 HTML、不写 script，也不直接修改 outline。
- Reviewer 输出 `outline-review.md`，只能给出 `PASS` 或有限、具体、可执行的问题。
- 若需要修改，Controller 恢复原 Pitch Director session 修订 outline，再恢复原
  Reviewer session 验收自己列出的问题；修订循环保持有界。

### R4. HTML Agent：把最终大纲做成 Deck

- HTML Agent 使用独立 session，读取最终 `deck-outline.md`、完整 Project 副本、
  Idea Card 和 hackathon 题目。
- 使用 `gpt-5.6-sol`、reasoning effort `xhigh` 生成最终 `pitch-deck.html`。
- HTML Agent 负责视觉系统、布局、字体、颜色、节奏、转场与具体 HTML/CSS/JS。
- 它可以读取和使用 Project 中的真实 assets、截图或产品画面；必要时可以实际运行
  Project 来理解或捕获 demo，但不能伪造产品 UI。
- HTML 必须自包含、可直接在浏览器打开、支持键盘前后翻页，并为每页保留稳定
  slide ID。
- HTML Agent 只能实现最终 outline，不能新增页面目的、产品功能或额外叙事。
- HTML Agent 必须自己在真实浏览器中检查页面，修正溢出、不可读、错位和导航问题。
- 第一版不增加独立 Visual Reviewer。

### R5. Script Agent：最后根据 Deck 写讲稿

- Script Agent 只在 `pitch-deck.html` 完成后运行。
- 它读取最终 HTML、完整 Project 副本、Idea Card 和 hackathon 题目。
- 输出 `pitch-script.md`，按 HTML 中的稳定 slide ID 分段。
- 每段讲稿只服务于对应页面，全部段落连起来是一篇自然、连续、可以直接讲的演讲。
- Script 可以补充口头转场、语气和 demo 提示，但不能反向修改 deck，也不能加入
  deck/Project 未支持的新产品事实。

### R6. 简单确定性 Controller

- Controller 是普通确定性程序，不是 Agent。
- 它只负责：
  - 建立 Pitch workspace；
  - 复制完整 Project；
  - 放入 Idea Card 与 hackathon 题目；
  - 按固定顺序启动四个 Agent session；
  - 检查上一步要求的文件存在且非空；
  - 在 outline Review 需要时恢复原 Director；
  - 收集并发布最终文件。
- Controller 不总结 Project、不评价内容、不设计页面，也不维护复杂的 Team
  frozen/unfrozen 状态机。
- 除 Director ↔ Reviewer 的一次有界修订外，流程保持单向。

### R7. 模型与自动发布

- 四个 Agent 均固定使用 `gpt-5.6-sol/xhigh`。
- 模型不可用时该项目 Pitch 失败，不自动降级。
- 通过文件 contract、HTML 浏览器检查和基本一致性检查后，自动发布 Pitch 输出，
  不设置人工 approval gate。

## Outputs

```text
pitch/
  input/
    project/              # 完整 Project 副本
    idea-card.md
    challenge.md
  director/
    deck-outline.md
  review/
    outline-review.md
  html/
    pitch-deck.html
  script/
    pitch-script.md
  output/
    deck-outline.md
    pitch-deck.html
    pitch-script.md
```

具体目录名可以在实现时适配现有 workspace 约定，但三个最终产物不变。

## Out of Scope

- BuildFactory pause/resume/freeze 状态机。
- Snapshot 摘要、EvidenceBundle、去敏投影或逐文件 provenance 系统。
- Product Analyst Agent。
- Visual Reviewer Agent。
- Agent 自由聊天、多候选 deck 或多套 Useful/Creative pipeline。
- 固定 slide 数、固定章节、固定视觉模板。
- PowerPoint、Keynote、Google Slides 或 PDF 作为第一版权威输出。

## Acceptance Criteria

- [x] AC1: 一次 Pitch run 使用一份完整 Project 副本；四个 Agent 读取同一副本，
      不读取 live Project。
- [x] AC2: Pitch Director 产出逐页 `deck-outline.md`，每页有稳定 ID、唯一信息、
      精简页面内容和视觉/demo 意图。
- [x] AC3: 独立 Reviewer 对 outline 输出 PASS 或有限问题；若修订，只有原
      Director 修改 outline。
- [x] AC4: HTML Agent 从最终 outline 生成可直接打开和键盘导航的自包含 HTML，
      并通过真实浏览器检查。
- [x] AC5: HTML 的 slide ID、页面目的和主张不超出最终 outline。
- [x] AC6: Script Agent 在 HTML 完成后，按有效 slide ID 生成连续讲稿，不修改 deck。
- [x] AC7: deck 与 script 不把 Project 中不存在的功能写成已经完成。
- [x] AC8: 四个 Agent 的实际运行记录均为 `gpt-5.6-sol/xhigh`。
- [x] AC9: Controller 严格执行 Director → Reviewer → HTML → Script 顺序；
      不存在 Product Analyst、Visual Reviewer 或其他 Agent 阶段。
- [x] AC10: 最终自动发布 `deck-outline.md`、`pitch-deck.html` 和
      `pitch-script.md`，无需人工审批。
