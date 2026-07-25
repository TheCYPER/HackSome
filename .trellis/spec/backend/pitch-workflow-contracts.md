# Pitch 工作流合同

> Building 后独立运行的 browser-native Pitch pipeline。实现位于
> `src/hacksome/stages/pitch/`，入口为 `hacksome pitch`。

## 1. Scope / Trigger 与入口

Trigger：Building 已有一个完成到可 Pitch 的 Project，operator 显式要求从当时的
完整 Project 副本生成一个 HTML deck 和对应讲稿。Pitch controller 不负责
Build Stage freeze/resume，也不生成 Project 摘要。

### Signatures

```text
hacksome pitch \
  --project <completed-project-dir> \
  --idea-card <idea-card.md> \
  --challenge <challenge.md> \
  --output-root <new-run-dir>
```

`PitchWorkflow.create()` 要求 Project 目录和两个非空 Markdown 文件都存在，且
`output-root` 尚不存在、既不位于 Project 内也不包含 Project。创建 run 时一次性
完整复制 Project 到 `input/project/`，同时复制 Idea Card 和 challenge。后续 prompt
只暴露该 snapshot 的绝对路径，不暴露 live Project，也不生成 Project summary。

Project 内部的相对 symlink（例如 `node_modules/.bin/*`）必须原样保留，保证复制后
仍可运行。任何 broken、cyclic 或最终 target 逃出 Project 的 symlink 在创建 run 前
fail closed；指向 Project 内部的绝对 symlink 会重写为 snapshot 内相对 link。复制后
再次验证所有 link 都只能解析到 `input/project/` 内。

## 2. Contracts：固定流程与 Session

唯一流程为：

```text
Pitch Director
→ fresh Accuracy Reviewer
→ 至多一次原 Director session revision
→ resume 原 Accuracy Reviewer，仅验收其已列问题
→ fresh HTML Agent
→ fresh Script Agent
```

Reviewer PASS 时跳过 revision 和第二次 Review。验收仍为 REVISE 时 run fail
closed。每个非 resume 角色必须返回非空且此前未出现过的 Codex session ID；
Director revision 必须返回原 Director session ID，Reviewer 验收必须返回原
Reviewer session ID。首次 Review 必须完整列出问题；验收不得开启新的全量 Review。

四个角色统一由 controller 固定为：

```text
model = gpt-5.6-sol
reasoning_effort = xhigh
sandbox = workspace-write
max_concurrency = 1
web_search = disabled
```

CLI 不提供 model/effort override。`CodexRunner` argv 必须显式包含
`--model gpt-5.6-sol` 和 `model_reasoning_effort="xhigh"`。

## 3. 文件合同

- Director 写 `director/deck-outline.md`。每个 `## Slide <id>` 必须有非空
  `Purpose:`、`On-slide:`、`Visual:`，ID 唯一。
- Reviewer 写 `review/outline-review.md` 和 schema-constrained result。Verdict
  只能为 PASS/REVISE；REVISE 为 1–10 个 issue，文件与 structured issues 必须逐项
  完全一致且只能引用当前 outline ID。
- HTML Agent 写 `html/pitch-deck.html`。`.slide` 的 `id` 和 `data-slide-id` 必须
  一致，ID/顺序必须与 outline 完全一致；HTML 必须单文件、自包含、16:9，并声明
  Arrow、Page、Home、End、Space 导航。
- Script Agent 写 `script/pitch-script.md`。每个 HTML slide ID 必须按顺序恰好出现
  一次且有非空讲稿。

各角色只以自己的目录为 cwd，通过冻结 prompt 内的 snapshot path 和上游 artifact
bytes 交接。Script 只在 HTML contract 和浏览器检查通过后启动。

四个角色使用 targeted product discovery，不穷举 Project。默认从 README/product
docs、package/application manifest、authored source entrypoint、相关 product tests
和当前叙事需要的真实 assets 开始；默认跳过 `node_modules`、vendor、cache、`.git`、
coverage、lockfile 和 generated/minified `dist`/`build`。只有 authored source 缺失
或某个具体 claim/asset 必须依赖时才读取例外目录。测试或 demo 也只在能实质验证
关键 claim 时运行。这个约束属于 Prompt 行为，不增加 summary Agent、controller
摘要或 controller 文件过滤。

HTML Agent 必须先完成并验证全 deck，再做可选素材增强；不得安装依赖、修复
`node_modules` 或修改 snapshot，启动 copied Project 最多尝试一次。环境不兼容时
应使用真实现有 assets 或明确为设计构图的 source-derived visual，不能让素材采集
阻止最终 deck 落盘。

## 4. Chromium 合同

Controller 在 HTML turn 前解析一个实际可执行的 Chromium-family binary，优先使用
Playwright cache 中的 headless shell，并把绝对路径放入
`CHROMIUM_EXECUTABLE` context。HTML Agent 必须用该路径自检。

16:9 是 rendered contract，不是 CSS 字符串合同。Controller 不要求
`aspect-ratio: 16 / 9` 的字面写法；它在浏览器中检查每个 active slide 的实际
bounding box 比例，允许 1600×900、CSS variables 等等价实现。

Agent 完成后，controller 独立在真实 Chromium 中加载最终 HTML，并：

- 实际发送 ArrowLeft/ArrowRight、PageUp/PageDown、Home、End、Space；
- 用 ArrowRight 按 outline 顺序访问每个 slide；
- 验证每次按键激活预期 slide；
- 在 1280×720 presentation viewport 检查 slide 和 document overflow。

找不到 browser、HTML 打不开、导航不移动、ID 缺失或 overflow 均使 run 失败。
只查 HTML 字符串中是否出现按键名称不算 browser smoke。

## 5. Validation & Error Matrix

| 条件 | Controller 行为 |
|------|-----------------|
| 输入目录/文件缺失、空文件或 output boundary 非法 | `PitchWorkflowError`，不创建可执行 run |
| symlink broken/cyclic/逃逸 snapshot | snapshot 创建失败，不启动 Agent |
| Director/Reviewer artifact 或 structured result 不合法 | fail closed，不启动下游角色 |
| revision/verification 未返回原 session ID | fail closed，记录 task error |
| second Review 仍为 REVISE | fail closed，不启动 HTML |
| HTML ID/order、self-contained 或导航声明不合法 | fail closed，不启动 Script |
| rendered stage 非 16:9、导航不移动或出现 overflow | Chromium smoke 失败，不启动 Script |
| Script ID/order/内容不完整 | fail closed，不发布部分 output |
| 全部合同通过 | 原子 rename 发布三个文件，manifest 变为 `completed` |

## 6. Good / Base / Bad Cases

- Good：Reviewer 指出问题，原 Director 修订，同一 Reviewer 验收 PASS；HTML 与
  Script 通过真实 browser/ID 检查，三个文件一次性发布。
- Base：首次 Reviewer 直接 PASS；跳过两次 resume，按 Director → Reviewer →
  HTML → Script 发布。
- Bad：HTML Agent 自称 browser PASS，但实际文件按键不移动、slide overflow 或
  rendered stage 不是 16:9；controller 的独立 Chromium smoke 必须拒绝。

## 7. 发布与失败

所有 Agent、文件、schema、slide-ID 和 browser contracts 通过后，controller 才把
三个最终文件写入 staging directory，并以一次目录 rename 自动发布到 `output/`：

```text
deck-outline.md
pitch-deck.html
pitch-script.md
```

无人工 approval gate。任一步失败都把 `pitch-run.json.status` 设为 `failed`，保存
错误和已完成 task 记录，不启动不应运行的下游角色，也不留下部分 final output。

## 8. Tests Required

- `tests/stages/pitch/test_pitch_cli.py`：显式入口、输入参数、无 model override。
- `tests/stages/pitch/test_pitch_prompting.py`：四角色 catalog、snapshot boundary、Draft 2020-12
  validity，以及所有 Codex `const`/`enum` 节点显式声明 `type`。
- `tests/stages/pitch/test_pitch_workflow.py`：snapshot 隔离与 symlink 保真/逃逸拒绝、顺序、revision/resume session、
  fail-closed、实际 argv、outline/Review/HTML/script contracts、真实 Chromium
  正向与 broken-navigation 负向 smoke、自动发布。

质量门：

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy src
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

## 9. Wrong vs Correct

### Wrong：用字面 CSS 或新的 Reviewer 代替真实合同

```text
grep("aspect-ratio: 16 / 9")
fresh Reviewer after Director revision
```

字面正则会误拒 1600×900/CSS variables；第二个 fresh Reviewer 会开启新一轮审稿，
不断发现首次 Reviewer 未列的问题，破坏“四个角色、一条线”的边界。

### Correct：验证 rendered result，并恢复原 Reviewer

```text
Chromium: active slide/stage bounding box ≈ 16/9
Director revision → resume original Reviewer → verify prior issues only
```

实现等价写法都由真实浏览器结果裁决；内容修订仍由同一个 Reviewer 闭环验收。
