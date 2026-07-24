# 自主 Pitch Deck 生成 — 技术设计

状态：已于 2026-07-24 实现；以代码、测试和 Pitch workflow spec 为准。

## 1. 设计原则

这个系统按人制作 Pitch 的自然顺序工作：

```text
先想每页讲什么
→ 找另一个人 Review 内容
→ 按通过的内容制作 PPT
→ 看着最终 PPT 写讲稿
```

Agent 负责理解和创作；Controller 只负责串行启动和文件交接。

## 2. ClaudeHack 中可复用的东西

ClaudeHack Stage 5 的实现位于：

- `/Users/weston/dev/ClaudeHack/control/stages/stage5.py`
- `/Users/weston/dev/ClaudeHack/prompts/stage5/storyteller.md`
- `/Users/weston/dev/ClaudeHack/prompts/stage5/deck-builder.md`

值得复用：

- 一个普通 Python control script 串行启动独立 Agent session；
- 每个角色有独立工作目录；
- 上一步通过文件把产物交给下一步；
- Session 失败或缺少目标文件时停止该项目；
- 不同项目之间可以独立、并行，不相互影响；
- HTML 使用单文件、自包含、键盘导航的演示形式。

需要改变：

- ClaudeHack 是 `Storyteller script → Deck Builder HTML`；新版改为
  `outline → review → HTML → script`。
- ClaudeHack Storyteller 同时理解产品、搜索 hook、写完整 script，职责太重。
- ClaudeHack Deck Builder 使用固定 6–8 页和固定 dark theme，新版不固定结构/风格。
- ClaudeHack 只有 `wc -l` 文件检查，没有真实浏览器视觉验证。
- ClaudeHack 通过 symlink 读取 live demo；新版所有 Agent 读取完整复制的 Project。

## 3. 总体流程

```text
Operator / outer flow
  → copy Project
  → create Pitch workspace

Pitch Director
  → deck-outline.md

Accuracy Reviewer (one session)
  → PASS
  → or issues → resume Pitch Director once/bounded → re-review

HTML Agent
  → pitch-deck.html
  → browser self-check

Script Agent
  → pitch-script.md

Controller
  → collect three final outputs
  → publish automatically
```

没有 Project Analyst、EvidenceBundle、Visual Reviewer 或跨阶段回退。

## 4. Workspace 与输入

```text
pitch-run/
  input/
    project/
    idea-card.md
    challenge.md
  director/
  review/
  html/
  script/
  output/
```

- `input/project/` 是启动 Pitch 时完整复制的 Project。
- 四个 Agent 都可以读取 `input/`。
- Agent 只能把自己的产物写入自己的工作目录。
- 下游 Agent 额外读取上游最终文件。
- Project 副本不是摘要，也不要求 Agent 先读取某个 controller 生成的产品说明。

## 5. Agent 1：Pitch Director

### 输入

- `input/project/`
- `input/idea-card.md`
- `input/challenge.md`

### 工作

1. 阅读 Project，理解真实功能、用户流程、demo 与产品当前完成度。
2. 结合 Idea Card 和题目，决定最有说服力的一条叙事主线。
3. 设计每一页实际要讲什么。
4. 主动删掉不重要、重复或只能口头补充的内容。

### 输出

`deck-outline.md` 使用简单 Markdown，不引入庞大 Schema：

```markdown
# Deck Outline: Product Name

## Slide s01 — Title

Purpose: 本页唯一要让评委记住的意思。

On-slide:
- 实际标题
- 实际短句

Visual:
- 应展示的真实产品画面、demo 动作或视觉构图

## Slide s02 — ...
```

章节名、页数和页面类型由 Director 自己判断。

## 6. Agent 2：Accuracy Reviewer

Reviewer 使用独立于 Director 的 session，读取与 Director 相同的完整输入，再读取
outline。

它只回答两个问题：

1. 这些页面是否真实、清楚、回应题目？
2. 哪些内容应该删、改或合并？

输出：

```markdown
# Outline Review

Verdict: PASS | REVISE

## Issues

- Slide: s03
  Problem: ...
  Required change: ...
```

如果 `REVISE`，Controller 把 review 交回原 Director session。Reviewer 不直接修改
outline。修订后恢复同一个 Reviewer，只验收它首次列出的问题；达到上限仍不通过
则本次 Pitch 失败。这样总共仍是四个角色 session，不会在验收阶段悄悄引入新的
评审视角。

## 7. Agent 3：HTML Agent

### 输入

- 最终 `deck-outline.md`
- 完整 `input/`

### 工作

- 把 outline 转换为单文件 `pitch-deck.html`；
- 自己决定视觉语言，而不是套固定 dark template；
- 使用 Project 中真实 assets、截图和界面；
- 必要时运行 Project，理解或捕获真实 demo；
- 保留 outline 的 slide ID；
- 不新增 outline 没有的产品主张或页面目的；
- 使用浏览器实际翻页检查并修复版面。

### 最低 HTML Contract

- 一个可直接打开的自包含 HTML；
- 每页是有稳定 ID 的 slide；
- 支持前后翻页、Home/End；
- 16:9 演示布局；
- 无溢出、遮挡或明显不可读内容；
- 不使用 placeholder 假装真实产品截图。

HTML 的具体主题、动画、字体和页数不由 Controller 固定。

## 8. Agent 4：Script Agent

### 输入

- 最终 `pitch-deck.html`
- 完整 `input/`

### 工作

- 按 HTML 的 slide 顺序和 ID 写讲稿；
- 每段只服务对应页面；
- 用自然口语连接所有页面；
- 可以加入停顿、转场和 demo cue；
- 不新增 deck 中没有的产品卖点；
- 不修改 HTML。

输出：

```markdown
# Pitch Script

## Slide s01

[讲稿]

## Slide s02

[讲稿]
```

## 9. Controller

Controller 可以参考 ClaudeHack 的 `control/stages/stage5.py`，但新版只需要一个更简单
的顺序驱动：

```python
copy_project()
run_director()
run_reviewer()
if review_requires_revision:
    resume_director()
    run_reviewer_again()
run_html_agent()
verify_html_exists_and_opens()
run_script_agent()
collect_outputs()
```

Controller 不读取源码来总结产品，不产生中间 EvidenceBundle，不决定 slide 内容，
也不管理 Build Team 状态。

每一步只检查：

- Agent session 是否成功；
- 要求的文件是否存在且非空；
- Review verdict 是否合法；
- HTML 是否能在浏览器打开和导航；
- script 的 slide IDs 是否与 HTML 一致。

## 10. Session 与模型

- 四个角色使用四个独立 session。
- Reviewer 首次检查使用独立 session；修订验收恢复该 Reviewer session。
- Director 修订时恢复原 session。
- 全部固定为 Codex `gpt-5.6-sol/xhigh`。
- 角色之间只通过文件交接，不共享对话。

## 11. 失败语义

- Director 失败/无 outline：停止。
- Reviewer 无合法 verdict：停止。
- Review 达到上限仍不通过：停止。
- HTML Agent 失败、HTML 无法打开或导航失败：停止。
- Script Agent 失败或 slide IDs 不匹配：停止。
- 一个 Project 的 Pitch 失败不影响其他 Project。
- 不发布不完整结果为 final。
