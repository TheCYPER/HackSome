# HackSome

HackSome 是一个本地运行的黑客松工作流，生产代码统一位于 `src/hacksome/`。
产品有三个明确阶段：Ideation→Build 由 operator 在共享 Approval 页面授权，
Build→Pitch 仍由 operator 手工交接：

```text
Ideation ── IdeaToBuildHandoff JSON ──[人工批准，系统建 Team]──> Build
Build ── Project + Idea Card + Challenge ──[人工调用]──> Pitch
```

| Stage | 实现与资源 | 测试 | 运行入口 |
| --- | --- | --- | --- |
| Ideation | `src/hacksome/stages/ideation/` | `tests/stages/ideation/` | `hacksome run ...` |
| Build | `src/hacksome/stages/build/`、`ops/build/` | `tests/stages/build/` | `hacksome approve RUN`；或手工 `make -C ops/build init/up ...` |
| Pitch | `src/hacksome/stages/pitch/` | `tests/stages/pitch/` | `hacksome pitch ...` |

共享运行机制在 `src/hacksome/core/`，两种显式交接格式在
`src/hacksome/contracts/`。阶段说明见
[`Ideation`](src/hacksome/stages/ideation/README.md)、
[`Build`](src/hacksome/stages/build/README.md) 和
[`Pitch`](src/hacksome/stages/pitch/README.md)。

Ideation 有两条共享同一套 Harness 的路线：

- `useful`：寻找有真实需求与产品价值的 Idea；这是默认路线。
- `creative`：寻找能在约 30 秒内让人惊奇、好玩、神秘并愿意转述，同时可以
  用普通电脑或手机跑出真实软件 Demo 的 Idea；它保留候选的演化与淘汰原因，
  并在唯一一次人工评审后结束。

这里的 Harness 指控制器周围的可复用基础设施：Codex 进程与超时、并发、
Prompt/Schema 冻结、Hub 持久化、哈希绑定、日志、状态检查和失败处理。

## 安装

需要 Python 3.11+ 和已登录的 Codex CLI：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/hacksome doctor
```

## Useful 路线

Useful 是默认行为，兼容原有命令：

```bash
hacksome run challenge.md
hacksome run --prompt "为本地社区做一个真正有用的产品"
```

它使用绝对门槛而不是 Top-K：

```text
赛题解析 → 人群扩散 → Research → Problem Writer → Problem Gateway
       → Idea Generator → Idea Red Team → Idea Card
```

Useful 自身没有 Run 级 `resume`。同一个 Codex Task 的基础设施重试仍只会
恢复该 Task 自己的准确 Session。

## Creative 路线

Creative 从赛题开始，到确定性的 Idea 报告、零张或多张 Idea Card 和纯 JSON
Build handoff 为止：

```text
C0 赛题与硬约束
→ C1 Creative Brief + frozen Software Demo Policy
→ C2 Software-native Creative Territories
→ C3 Concept Synthesis
→ C4 Hook/Share Screen + Software Demo Feasibility
→ C5 Idea Memory + Novelty Scan
→ C6 自动 shortlist + 唯一一次人工策展
→ C7 确定性报告、Idea Card、Memory Record、Build handoff
```

新 run 使用 Creative contract v2：普通电脑/手机和内置 camera、microphone、
touch、screen、speaker 可以作为交互入口；定制硬件、实体制作、纯装置/
人工表演核心、mock 或 wizard-of-oz 核心不能进入后续查重和人审。每个 Concept
要先经过两份独立 Hook/传播审查和一份独立 Software Demo 可行性审查，三者
只共享一次有界修复机会。

启动：

```bash
hacksome run challenge.md \
  --route creative \
  --creative-brief-file brief.md \
  --idea-memory auto
```

也可以直接传 Brief，或关闭历史灵感：

```bash
hacksome run --prompt "为舞台互动设计一个意外体验" \
  --route creative \
  --creative-brief "希望观众惊奇但不困惑；避免纯文案型点子" \
  --idea-memory off
```

如果自动 shortlist 非空，`run` 会正常退出并打印评审命令：

```bash
hacksome review runs/<run-id>
```

Percy 在 curator 页面关闭轮次后，再执行：

```bash
hacksome resume runs/<run-id>
```

评审页面不是预先部署好的常驻网站。只有 run 到达
`waiting / creative-human-review` 后，执行上面的 `hacksome review` 才会在
本机临时启动服务，并在终端打印 `Review URL` 和 `Curator URL`；默认还会自动
打开 Curator 页面，自动化或手动复制链接时可加 `--no-open`。

`review` 默认只监听 `127.0.0.1` 的随机端口。可信局域网内共享时必须显式给出
公开主机名：

```bash
hacksome review runs/<run-id> \
  --host 0.0.0.0 \
  --public-host percy-mac.local \
  --port 8765
```

该页面没有账户系统或 TLS，只适合本机或可信局域网，不能暴露到公网。普通
评审者可以看到候选的软件核心、最小 Demo 与分享产物，但提交前看不到机器
可行性 verdict 或队友原文；提交后只能看只读 team wall。只有 curator 链接
能查看完整 C4F 证据、批准哪些反馈进入最后一次有界修订、合并候选或关闭
轮次。v2 回执还会记录 `share_impulse`、具体分享对象和
`demo_confidence`，这些只是 Idea 阶段代理信号，不代表真实传播率或构建成功。

### Idea Memory 是什么

`--idea-memory auto` 只从同一 `runs` 目录的直接子目录读取满足以下条件的
历史：

- `completed`、Creative、受支持版本且离线校验通过；
- 由真实工作流产生，而不是 benchmark fixture；
- 只读取去身份化的 `creative-memory-record.json`，不读取 Prompt、Session、
  原始人工评论或整个旧 Idea Card。

当前运行创建前会冻结一份带哈希的 Snapshot。C0–C4 先独立生成，之后 C5
才允许最多两个 memory challenger；challenger 仍需重走 Hook 与 Novelty
检查，且不能递归读取 Memory。`off`、没有合格历史或历史损坏都有明确记录，
不会偷偷退化成不透明的全局数据库。

### 空 batch 与零 Idea

没有完整 C4 Hook + Software Demo screen pass Concept，或自动 shortlist
为空时，控制器仍会发布一份带 `skip_reason` 的空 C6 batch，但不会启动空白
评审页。流程会直接进入 C7，生成零 Idea 报告。报告保留每个候选、revision、
Hook/Feasibility 淘汰原因和证据；“零 Idea”不是“什么都没发生”。

### C7 中断与恢复

C7 在发布第一份最终产物前，会冻结所有输出字节、路径、哈希、ID、时间和发布
顺序。若发布过程在清单生成后中断：

```bash
hacksome status runs/<run-id>
hacksome resume runs/<run-id>
```

此时 `resume` 只复核并重放已冻结字节，不重新调用模型、不重新渲染，也不改变
时间或 ID。若失败发生在清单生成前，run 保持 `failed`，并尽力生成只包含已
持久化事实的 partial report；partial report 不会产生有效 Idea Card、
Memory Record 或 Build handoff。

## 共享 Build Approval

Useful 与 Creative 的 completed run 都进入同一个 post-card 边界。先离线校验
source run，再把最终 Card 顺序、精确 Markdown、hash、provenance 与五字段
handoff 冻结到 run 外部的 Approval control root。source run 本身不会被修改。

打开本机 Dispatch Board：

```bash
hacksome approve runs/<run-id>
```

页面默认只监听 loopback，首次 URL 使用一次性 join token 换取 HttpOnly、
SameSite=Strict cookie。不要把 join URL、cookie 或本机 credential path 放进
日志、截图或报告。若只想打印 URL 而不自动打开浏览器：

```bash
hacksome approve runs/<run-id> --no-open
```

一次 Approval batch 必须选择 1–10 张尚未授权的 Card。同一个 run 可以连续提交
多批；每张 Card 最多授权一次，request ID 重放保持幂等。显式关闭 Approval 后
不能再授权未选 Card，但关闭不会 pause 或停止已经授权的 Team。空 catalog 也能
打开页面并显式关闭。

每张获批 Card 对应一个稳定、隔离的 Build Team。默认全局最多两个 Team 占用
active slot，其余按授权顺序 FIFO 排队；Team 完成一轮 Goal 不会自动释放 slot，
只有 Build operator 的显式 pause 才会释放。查看、重放交接或离线校验：

```bash
hacksome build-status runs/<run-id>
hacksome build-status runs/<run-id> --json
hacksome build-reconcile runs/<run-id>
hacksome build-validate runs/<run-id>
```

Approval ledger、outbox 和 receipt 默认位于
`<runs-dir>/.hacksome/approvals/<run-id>/`；Build registry 与 Team root 默认位于
`ops/build/state/build-pool/`。两侧通过 fixed-argv、`shell=False` 的纯 JSON
subprocess 边界通信。进程在 batch commit 或 Build response 后中断时，重复执行
`build-reconcile` 会补齐 outbox/receipt，而不会创建第二个 Team。

首次使用真实 Build runtime 前先确认 Docker/Compose、账户包和 Codex 登录：

```bash
make -C ops/build validate
hacksome doctor
```

可用 `--build-root`、`--build-python` 和 `--max-active-teams` 覆盖可信的本机启动
参数；Browser API 不接受路径、命令、Compose service 或环境变量。

## 查看、校验与 Benchmark

```bash
hacksome status runs/<run-id>
hacksome status runs/<run-id> --json
hacksome validate runs/<run-id>
hacksome reconcile runs/<run-id>
```

`status` 和 `validate` 都按 run 中持久化的 route 分派，不调用模型。
`reconcile` 只重放 Hub 中已冻结的 outbox 记录。

Creative benchmark 目前提供严格的离线规划和纯数据合同。下面的命令只校验
manifest 并打印计划，不创建 arm、run 或 benchmark 目录：

```bash
hacksome benchmark --route creative benchmark-manifest.json
```

支持 `workflow_vs_oneshot` 和 `memory_ablation`，后者要求两个 arm 共享同一份
benchmark-level Memory Snapshot。底层纯函数已经定义并测试 Memory 冻结、
盲化 A/B、独立 arm map、worksheet 导入和离线 evaluator，但当前 CLI 还没有
arm execution/state controller，因此不会假装执行真实 arm。

`--continue BENCH_DIR [--worksheet PATH]` 目前只用于严格验证一个由未来
controller 生成的既有 bundle；即使验证成功也会明确返回非零，不保存 worksheet
或推进状态。真实在线 benchmark 要等 execution controller 完成、Percy 提供
题目并显式运行。

## 数据边界与协作

Hub 保存中间 Markdown、完整 Prompt、Codex Session ID、原始 JSONL 日志、
结构化输出、机器决策和人工 ledger。Agent 不靠“自己去目录里找”获取上下文：
控制器把允许的精确文本嵌入 Prompt，并把 Prompt/Schema 冻结到 run 内。

Creative 的最终 Build handoff 只包含：

```json
{
  "source_run_id": "...",
  "idea_card_id": "...",
  "idea_card_sha256": "...",
  "challenge_markdown": "...",
  "initial_idea_card_markdown": "..."
}
```

其中两个 Markdown 字段有意对齐 Build Stage 的 `TeamLayout.bootstrap()` 输入。
共享 Approval adapter 会先复核 `idea_card_sha256`，再把 exact handoff 交给
Build registry。Team 身份绑定 `source_run_id + idea_card_id +
idea_card_sha256`，不会只使用可能跨 run 重复的 `idea_card_id`。

Idea 工作流到 Card 为止，Approval 是独立的 Build 资源决策。Build 侧可以选零张
或多张卡；未选择不等于 Creative 质量 reject。Build Agent 也可以修改、继续或
放弃初始 Card。Build 完成后，operator 仍需显式调用 Pitch；Pitch 不会扫描 Team
state：

```bash
hacksome pitch \
  --project /absolute/path/to/completed-project \
  --idea-card /absolute/path/idea-card.md \
  --challenge /absolute/path/challenge.md \
  --output-root /absolute/path/to/pitch-output
```

本仓库不把 Build 忠实度、GitHub 发布或 Pitch 偷塞进 Idea 阶段；Approval 与
Build 已连接，Build 到 Pitch 的人工边界仍然保留。

## 测试

默认测试使用脚本化 Runner 和假的 Codex 可执行程序，不调用付费模型：

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy src
.venv/bin/python -m compileall -q src tests
CODEX_HOME=/private/tmp/hacksome-test-codex-home \
  .venv/bin/python -m unittest discover -s tests -v
PYTHONPATH=src .venv/bin/python -m pytest tests/stages/build -q
make -C ops/build validate
node --check src/hacksome/stages/ideation/creative/review_ui/app.js
git diff --check
```
