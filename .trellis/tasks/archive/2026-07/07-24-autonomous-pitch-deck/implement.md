# 自主 Pitch Deck 生成 — 实现计划

状态：已于 2026-07-24 完成实现与质量验证。

## 1. 建立简单 Pitch Workspace

- 增加一个 Pitch run 目录。
- 输入是：
  - 完整复制的 Project；
  - Idea Card；
  - hackathon challenge。
- 为 Director、Reviewer、HTML、Script 和 output 建独立工作目录。
- 四个 Agent 都能只读访问同一份 Project 副本。

## 2. 实现四个 Prompt

### Pitch Director

- 阅读完整 Project；
- 逐页输出 `deck-outline.md`；
- 强调一页一个意思、克制、真实功能和自由结构。

### Accuracy Reviewer

- 读取相同 Project 和 outline；
- 只输出 PASS/REVISE 与有限问题；
- 不直接修改 outline。

### HTML Agent

- 读取最终 outline 和 Project；
- 使用 `gpt-5.6-sol/xhigh` 生成 `pitch-deck.html`；
- 使用真实 assets/demo；
- 在浏览器中自检并修复。

### Script Agent

- 读取最终 HTML 和 Project；
- 按 slide ID 生成 `pitch-script.md`；
- 不反向修改 deck。

## 3. 实现确定性串行中控

- 参考 ClaudeHack `control/stages/stage5.py` 的 SessionManager、独立工作目录、
  文件存在检查和单项目失败隔离。
- 执行：

```text
copy project
→ Director
→ Reviewer
→ optional bounded Director revision
→ optional same-Reviewer verification
→ HTML
→ Script
→ collect output
```

- 固定所有 session 为 `gpt-5.6-sol/xhigh`。
- 不增加 Product Analyst、Visual Reviewer、EvidenceBundle 或 Build freeze state。

## 4. HTML 验证

- 验证文件非空且可由 Chromium 打开。
- 验证键盘导航与 slide IDs。
- 截取逐页预览，检查无溢出/遮挡/不可读文本。
- 这部分是 HTML Agent 的自检加确定性/browser smoke，不增加第五个 Agent。

## 5. Script 验证

- 提取 HTML slide IDs。
- 验证 script 每个 slide 有且只有一个对应分段，顺序一致。
- 验证 HTML 改变后必须重新生成 script。

## 6. 自动收集与发布

- 收集：
  - `deck-outline.md`
  - `pitch-deck.html`
  - `pitch-script.md`
- 只有所有阶段成功才发布 final output。
- 单个 Project 失败不影响其他 Project。

## 7. 测试

- Project 完整复制且四个角色看到同一副本。
- Director 输出缺失时 fail closed。
- Reviewer PASS 与 REVISE 两条路径。
- Director revision 恢复原 session。
- Reviewer 验收恢复原 session，只检查首次列出的问题。
- HTML 缺失、无法打开、导航失败和 slide ID 漂移。
- Script slide coverage/order 不一致。
- 实际 Codex argv 明确包含 `gpt-5.6-sol/xhigh`。
- 使用一个真实 Project 做完整浏览器 E2E，人工只观察证据，不参与发布 gate。

最低回归：

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy src
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```
