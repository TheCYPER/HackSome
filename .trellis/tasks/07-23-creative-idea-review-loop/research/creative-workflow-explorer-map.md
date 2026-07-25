# Research: Creative v3 工作流 Explorer 实现映射

- Query: 以 clean integration worktree 的实际实现为准，映射 Creative v3 从 C0/C1 到 C7 的目的、输入、Controller/fanout、输出、Prompt/Schema、失败/跳过语义与负责代码；重点核对 C1W、C3 四种产品语法、C4 单修复、C5 Memory/Novelty、C6A/C6B/人工/C6C 和无 Prompt 的 C7。
- Scope: internal
- Date: 2026-07-25

## Findings

### 1. Canonical package 与总拓扑

实际实现已经迁到 `src/hacksome/stages/ideation/creative/`。同名
`src/hacksome/creative/` 文件是兼容导入层，不应作为 Explorer 的模块归属真相。

主控制器硬编码的流程是：

```text
run create / freeze
  ├─ challenge
  ├─ Creative Brief input
  ├─ Software Demo Policy
  ├─ Idea Memory Snapshot
  └─ Prompt/Schema catalog

C0 Challenge Parse
→ C1 Brief Normalize
→ C1W Cultural Signal Scan（optional, fail-open）
→ C2 Territory Explore（默认 6 并行）
→ C3 Concept Synthesize（默认 4 并行、固定互斥 product grammar）
→ 每 Concept: C4H×2 + C4F×1（并行）
   ├─ 3 pass → C5
   ├─ hard invalid / 双 Hook invalid → eliminate
   └─ 其他非全 pass → C4R 恰好一次 → fresh C4H×2+C4F×1
→ C5M Recall≤1 → Remix≤2（optional）
→ Memory challengers 再走完整 C4
→ 每个 C4-pass revision: C5W×1（联网、fatal、不是 gate）
→ 每个 C4-pass revision: C6A×1
→ C6B curator×2 → deterministic shortlist
→ shortlist 空：跳过人工与 C6C，直接 C7
  shortlist 非空：唯一 Human wait
→ closed Human Resolution
→ C6C keep/revise/reject/taste_veto/merge
→ C7 deterministic projection/render/freeze/replay
```

执行顺序来自：

- `src/hacksome/stages/ideation/creative/workflow.py:585`
  `execute_c0_c5()`
- `src/hacksome/stages/ideation/creative/workflow.py:718`
  `execute()`
- `src/hacksome/stages/ideation/creative/workflow.py:848`
  `resume()`

全局规则：

- 每个 Agent 任务由 `AgentTaskExecutor.execute()` 先渲染并持久化 Prompt，再启动
  fresh `CodexTask`；Schema、web policy、parents、failure policy 同时落盘
  （`src/hacksome/core/task_executor.py:85`）。
- v3 只有 C1W、C5M Recall、C5M Remix 是 `optional_branch`；只有 C1W 与 C5W
  开启 web search
  （`src/hacksome/stages/ideation/creative/contracts.py:75-82`）。
- 其他任务失败或语义失效均 fatal：run=`failed` 并 best-effort 发布 partial
  report；除 closed C6 wait 或 frozen C7 plan 外没有通用 resume。
- Schema 只约束 transport shape；route semantic validator 在
  `src/hacksome/stages/ideation/creative/artifacts.py:252`。需要 task-specific
  context 的 C1W snapshot、C2、C3、C4R、C5M、C6A、C6B、C6C 还在 Controller
  边界再次验证，失败将 task 标为 `invalidated`
  （`workflow.py:3269` `_validate_completed_output()`）。

### 2. 当前 v3 Prompt/Schema catalog

新 v3 run 使用下列 frozen resources；历史 run 读取其 manifest 中的真实版本。
`_spec()` 默认 Prompt version=2。

| Stage | Version | Web | Prompt | Schema |
| --- | ---: | --- | --- | --- |
| C0 | 2 | no | `src/hacksome/stages/ideation/creative/prompts/creative-challenge-parse.md` | `src/hacksome/stages/ideation/creative/schemas/creative-challenge-parse.schema.json` |
| C1 | 2 | no | `.../prompts/creative-brief-normalize.md` | `.../schemas/creative-brief-normalize.schema.json` |
| C1W | 1 | yes | `.../prompts/creative-cultural-signal-scan.md` | `.../schemas/creative-cultural-signal-scan.schema.json` |
| C2 | 3 | no | `.../prompts/creative-territory-explore.md` | `.../schemas/creative-territory-explore.schema.json` |
| C3 | 7 | no | `.../prompts/creative-concept-synthesize.md` | `.../schemas/creative-concept-synthesize.schema.json` |
| C4H | 3 | no | `.../prompts/creative-cheap-hook-review.md` | `.../schemas/creative-cheap-hook-review.schema.json` |
| C4F | 4 | no | `.../prompts/creative-software-demo-review.md` | `.../schemas/creative-software-demo-review.schema.json` |
| C4R | 3 | no | `.../prompts/creative-cheap-hook-repair.md` | `.../schemas/creative-cheap-hook-repair.schema.json` |
| C5M Recall | 2 | no | `.../prompts/creative-memory-recall.md` | `.../schemas/creative-memory-recall-v3.schema.json` |
| C5M Remix | 2 | no | `.../prompts/creative-memory-remix.md` | `.../schemas/creative-memory-remix-v3.schema.json` |
| C5W | 2 | yes | `.../prompts/creative-novelty-scan.md` | `.../schemas/creative-novelty-scan.schema.json` |
| C6A | 4 | no | `.../prompts/creative-evidence-revise.md` | `.../schemas/creative-evidence-revise.schema.json` |
| C6B | 4 | no | `.../prompts/creative-portfolio-curate.md` | `.../schemas/creative-portfolio-curate.schema.json` |
| C6C | 2 | no | `.../prompts/creative-feedback-revise.md` | `.../schemas/creative-feedback-revise.schema.json` |
| C7 | — | no Agent | 无 Prompt | 无 Agent Schema |

完整绝对前缀均为
`src/hacksome/stages/ideation/creative/`。Catalog 证据：
`src/hacksome/stages/ideation/creative/prompting.py:31-87`。

### 3. Run create / freeze（Controller prerequisite）

**目的**

在 C0 前固定所有可审计输入，防止运行中采用 package 新默认值、发现当前 run 或
让 Brief 偷偷放宽 software-first policy。

**输入与行为**

- 原始 challenge；
- literal/file/default Creative Brief；
- Controller 生成的 exact `SOFTWARE_DEMO_POLICY` JSON；
- settings/Codex config；
- runs directory 中可验证的历史，或传入的 Idea Memory Snapshot；
- 当前 v3 PromptCatalog。

Memory Snapshot 在 `RunHub.create()` 之前构建，因此不会发现新 run 自己。
Controller 写并 hash-bind：

- `input/creative-brief-input.md` → `input:creative_brief`
- `input/software-demo-policy.json` → `input:software_demo_policy`
- frozen Idea Memory → `input:idea_memory`
- frozen Prompt/Schema resources + manifest

**失败**

输入为空、hash/config/resource/schema catalog 不合法均在 C0 前 fail closed。
Catalog 静态错误不能被 C1W 的 fail-open 转成 `unavailable`。

**代码**

`src/hacksome/stages/ideation/creative/workflow.py:348-478`
`CreativeIdeaWorkflow.create()`；
`workflow.py:479-584` `open()`；
Policy 字段见
`src/hacksome/stages/ideation/creative/contracts.py:144-161`。

### 4. C0 — Challenge & Constraints

**目的**

把挑战原文分成中立 Challenge Brief 与 Constraint View，不猜产品、用户需求、
许可、资源或缺失规则。

**精确输入**

- block `ORIGINAL_CHALLENGE`
- parent refs：空

**Controller/fanout**

固定 1 个 task：`creative-c0-challenge-parse`。

**Agent envelope**

```json
{
  "challenge_brief_markdown": "...",
  "constraint_view_markdown": "..."
}
```

**输出**

- `creative-challenge-brief-r001` (`creative_challenge_brief`) →
  `artifacts/creative/challenge/creative-challenge-brief-r001.md`
- `creative-constraint-view-r001` (`creative_constraint_view`) →
  `artifacts/creative/challenge/creative-constraint-view-r001.md`

**失败/跳过**

必跑；无合法空输出；task/schema/Markdown 错误均 fatal。

**代码**

`src/hacksome/stages/ideation/creative/workflow.py:1710`
`_run_c0()`；
Prompt `.../prompts/creative-challenge-parse.md:1-26`；
semantic validator `.../artifacts.py:393-408`。

### 5. C1 — Creative Brief + Software Demo Policy

**目的**

规范化 Percy 的可见体验/品味方向，同时忠实重述 Controller-owned software
Demo 边界；不是人工批准 gate。

**精确输入**

- `ORIGINAL_CHALLENGE`
- `CHALLENGE_BRIEF`
- `CONSTRAINT_VIEW`
- `CREATIVE_BRIEF_INPUT`
- `SOFTWARE_DEMO_POLICY`

Parents 另含 `input:creative_brief`、`input:software_demo_policy`。

**Controller/fanout**

固定 1 个 task：`creative-c1-brief-normalize`。

**Agent envelope / 输出**

`{"markdown":"..."}`；

- `creative-brief-r001` (`creative_brief`) →
  `artifacts/creative/brief/creative-brief-r001.md`

Markdown 必须含 Intended Reactions、Anti-goals、体验上下文、30 秒 reveal、
媒介/边界、默认假设、Software and Demo Boundaries。

**失败/跳过**

必跑、fatal；不暂停人审。Brief 只能收紧，不能取代或放宽单独冻结的 Policy。

**代码**

`src/hacksome/stages/ideation/creative/workflow.py:1741`
`_run_c1()`；
Prompt `.../prompts/creative-brief-normalize.md:1-25`。

### 6. C1W — Cultural Signal Scan

#### 6.1 目的、输入和 fanout

目的只是为 C2/C3 提供近期、可追溯、脱敏的文化参与模式；不是 demand、
virality、novelty、feasibility、安全或质量证据。

精确 blocks：

- `CHALLENGE_BRIEF`
- `CONSTRAINT_VIEW`
- `CREATIVE_BRIEF`
- `SCAN_WINDOW`

`SCAN_WINDOW` 由 run `created_at` 冻结为
`[created_at-30 days, created_at]`，含 max_signals=12、
max_sources_per_signal=4。执行时墙钟不改变 `as_of_utc`
（`src/hacksome/stages/ideation/creative/signals.py:311-343`）。

固定 1 个联网 task：
`creative-c1w-cultural-signal-scan-01`，failure policy=`optional_branch`。

Controller 实现：
`src/hacksome/stages/ideation/creative/workflow.py:1772`
`_run_c1w()`。

#### 6.2 Agent envelope 与唯一 Snapshot

```json
{
  "coverage": {
    "query_families": ["..."],
    "platforms_attempted": [{"name": "...", "kind": "..."}],
    "limitations": ["..."]
  },
  "signals": ["最多 12 个 structured signal"],
  "no_signal_reason": "string | null"
}
```

每 signal 含 kind、creative_role、label、neutral_summary、abstract_pattern、
creative_tension、participation_shape、surface_markers_to_avoid、safety_flags、
confidence、1–4 sources。Source 含 title/URL/publisher/platform、严格 timestamp、
locale 与 evidence。

唯一 artifact：

- `creative-cultural-signal-snapshot-r001`
  (`creative_cultural_signal_snapshot`) →
  `artifacts/creative/cultural-signals/creative-cultural-signal-snapshot-r001.json`

状态语义：

- `ready`：有 signals、无 limitations；
- `partial`：有 signals、有 limitations；
- `empty`：成功搜索但 signals 为空，必须有 `no_signal_reason`；
- `unavailable`：task failed/invalidated，signals 为空，必须有 diagnostic，
  `no_signal_reason=null`。

Snapshot contract：
`src/hacksome/stages/ideation/creative/signals.py:186-308`。

#### 6.3 两层 invalidation 与 fail-open

C1W 输出有两个失效点：

1. `AgentTaskExecutor` 的 Schema + route semantic 初检；失败将 task 标为
   `invalidated`
   （`src/hacksome/core/task_executor.py:130-149`）。
2. 初检通过后，`build_cultural_signal_snapshot()` 再绑定 exact window、
   task finished_at、全局 canonical URL 唯一性、RFC3339/时区/日期真实性；失败时
   `_invalidate_optional_task()` 将已完成 task 改为 `invalidated`
   （`workflow.py:1808-1839`, `workflow.py:3106`）。

两者都：

- 保留 failed/invalidated task；
- 写唯一 event
  `optional-cultural-signal-stage-failed:<task-id>`，kind
  `optional_cultural_signal_stage_failed`；
- 发布显式 `status=unavailable` snapshot；
- unavailable artifact 的 `task_id=None`，payload `task_ref` 仍指原 task；
- C2/C3 继续。

Event 代码：
`src/hacksome/stages/ideation/creative/workflow.py:3144`
`_record_cultural_signal_failure()`。

成功但找不到信号是 `empty`，不能伪装成失败；失败也不能伪装成
`no_signal_reason`。Schema/catalog 本身无法启动属于 run-create fatal，不走
fail-open。

#### 6.4 Safe Palette

raw URL/title/publisher/platform/evidence 只留在 snapshot。C2/C3 收到 slot-stable
safe projection：

- C2：最多 2 inspire + 2 avoid；
- C3：最多 2 inspire；
- 只含 `signal_ref/kind/creative_role/abstract_pattern/creative_tension/
  participation_shape`；
- empty/unavailable 仍注入同 shape、`signals:[]` 的 palette。

实现：
`src/hacksome/stages/ideation/creative/signals.py:479-546`。

### 7. C2 — Territory Explore

**目的**

在产品概念前并行探索 software-native 机制空间，生成 Territory 与 Atom。

**每 task 精确输入**

- `CHALLENGE_BRIEF`
- `CONSTRAINT_VIEW`
- `CREATIVE_BRIEF`
- `SOFTWARE_DEMO_POLICY`
- `CULTURAL_SIGNAL_PALETTE`（v3 必有，允许空）
- `TERRITORY_LENS`
- `LIMITS`（默认最多 3 Atom）

Parents：Challenge/Constraint/Brief、Policy、唯一 C1W snapshot。Agent 不见 raw
snapshot、Memory、历史或 siblings。

**fanout**

默认 6 个并行 task `creative-c2-territory-01...06`，固定 lenses：

1. direct manipulation / unusual software interaction
2. reversal/reveal/expectation shift
3. multiplayer/collaboration/social propagation
4. software-visible hidden-state mystery
5. ordinary-device camera/mic/text/code/time/live-data transformation
6. technical viral remix/replay/share artifact

**envelope**

```json
{"territory_markdown":"...", "atoms":[{"markdown":"..."}]}
```

Atoms 可为 0，最多 3。

**输出**

- `creative-territory-01...06` (`creative_territory`) →
  `artifacts/creative/territories/<id>.md`
- `creative-atom-t<territory>-<atom>` (`creative_atom`) →
  `artifacts/creative/atoms/<id>.md`

IDs 由 Controller 根据 slot/返回顺序分配，Agent 不生成。

**失败/跳过**

任一 task 失败/invalidated 为 fatal。0 Atom 合法；全局 0 Atom 时 C3 不启动。

**代码**

`src/hacksome/stages/ideation/creative/workflow.py:1860`
`_run_c2()`；
validator `.../artifacts.py:446-469`；
Prompt `.../prompts/creative-territory-explore.md:1-79`。

### 8. C3 — 四种互斥 Product Grammar

**目的**

把 current-run Atoms 合成为完整、可复述、software-first Concept；四个 fresh
Session 各承担一种 primary product loop。

**每 task 精确输入**

- `CHALLENGE_BRIEF`
- `CONSTRAINT_VIEW`
- `CREATIVE_BRIEF`
- `SOFTWARE_DEMO_POLICY`
- `CULTURAL_SIGNAL_PALETTE`
- `CURRENT_ATOM_INDEX`（全部 current Atom exact Markdown + Controller refs）
- `SYNTHESIS_LENS`（assigned grammar ID + label）
- `LIMITS`（默认最多 3 Concept）

没有 Memory、C4 dispositions、Novelty、raw signals 或 sibling output。

**固定 fanout / 语法**

当前 frozen C3 v7 固定 4 个 slot
（`src/hacksome/stages/ideation/creative/workflow.py:126-163`）：

| Slot | Grammar | 必须成为 primary next action |
| ---: | --- | --- |
| 1 | `explorer_simulator` | query/改变显式变量 → 软件计算可检查的关系/路径/情景/反事实 → 用户比较并改假设 |
| 2 | `realtime_partner` | 连续/快速真实输入 → 本轮结束前 bounded-latency 自适应回应 → 用户改变下一动作 |
| 3 | `social_game_relay` | 一人改变 shared state → 另一真人做 rule-bound move → 软件产生下一轮/交接状态 |
| 4 | `creator_transformer` | 真实素材 + 至少两步有意义 edit/control/transformation → preview → revise/remix/save/export |

Prompt 的 removal test：

- 去掉 query/variable comparison 即失去价值 → Explorer；
- 把 live input 换成 completed upload 即失去价值 → Realtime；
- 去掉另一人的 next move 即失去价值 → Social Relay；
- 去掉 editable/remixable authored artifact 即失去价值 → Creator。

详细合同：
`.../prompts/creative-concept-synthesize.md:10-67`。

**envelope**

```json
{
  "concepts": [{
    "markdown": "...",
    "primary_territory_ref": "creative-territory-XX",
    "parent_atom_refs": ["creative-atom-tXX-YY"]
  }]
}
```

每 task 可返回 0，最多 3。每 Concept 必须有 12 个标准 H2，Parent Atoms
正文与 structured refs 完全一致，primary Territory 来自 Parent Atom。

在 `Why It Is Unexpected Yet Legible` 中必须恰好一行：

```text
Recognizable product grammar: <assigned-id> — <explanation>
```

Controller 将 marker 与该 task assigned ID 绑定；缺失、多条、错 slot、未知 ID
使整个 task invalidated，而不是 candidate reject
（`src/hacksome/stages/ideation/creative/artifacts.py:472-538`）。

**实现边界**

互斥 loop 的详细真实性是 frozen Prompt semantic contract。Python 机械检查
marker、refs 与 Markdown shape，但不会完整理解并证明真实 loop 分类。Explorer
应把“Prompt 要求互斥”与“Controller 验证 assigned marker”分开显示。

**输出**

- `creative-concept-s<slot>-<candidate>-r001`
  (`creative_concept`) →
  `artifacts/creative/concepts/<ref>.md`

metadata：origin=`base`、revision=1、revision_reason=`initial_synthesis`、
primary Territory、parent Atoms、synthesis/candidate slots。

**空/重复/失败**

- 所有 task 返回 0 合法；
- task 内重复 Markdown/normalized Hook → task invalidated；
- 跨 synthesizer exact normalized Markdown 或 Hook duplicate 在发布循环直接
  `continue`，不产生 disposition
  （`workflow.py:2093-2128`）；
- 任一 task execution/context validation 失败 fatal。

Controller：
`src/hacksome/stages/ideation/creative/workflow.py:1998`
`_run_c3()`。

### 9. C4 — C4H + C4F + 唯一 C4R

#### 9.1 每个 revision 的完整 screen

每个 initial/repaired revision 并行启动：

- 2 个 fresh C4H；
- 1 个 fresh C4F。

三者互相看不到结果
（`src/hacksome/stages/ideation/creative/workflow.py:2422`
`_screen_concept()`）。

#### 9.2 C4H Hook Review

输入：`CONSTRAINT_VIEW`、`CREATIVE_BRIEF`、`SOFTWARE_DEMO_POLICY`、
`CONCEPT_REVISION`。

Task：
`creative-c4-review-<concept>-r<revision>-c<cycle>-v1|v2`。

Envelope：
`overall_decision=pass|repairable|invalid`、Markdown、七个固定 dimensions：

1. `setup_legibility`
2. `expectation_shift`
3. `mechanism_driven_surprise`
4. `thirty_second_moment`
5. `one_sentence_retell`
6. `capability_integrity`
7. `share_trigger`

输出：
`creative-hook-review-...` (`creative_cheap_hook_review`) →
`artifacts/creative/cheap-hook-reviews/<id>.json`。

代码：
`workflow.py:2451` `_review_concept()`；
Prompt `.../prompts/creative-cheap-hook-review.md:1-50`。

#### 9.3 C4F Software Demo Review

输入 shape 与 C4H 相同，但独立 Session。

Task：
`creative-c4f-software-demo-<concept>-r<revision>-c<cycle>`。

固定 dimension → reason code：

1. `software_first_core` → `core_not_software_first`
2. `hardware_independence` → `requires_custom_hardware_or_fabrication`
3. `technical_demo_substance` → `core_is_manual_performance_or_installation`
4. `end_to_end_demo_path` → `no_runnable_end_to_end_demo_path`
5. `dependency_integrity` → `requires_unavailable_dependency_or_permission`
6. `hackathon_scope` → `not_buildable_within_hackathon_budget`
7. `core_proof` → `demo_does_not_prove_core_mechanism`

输出：
`creative-software-demo-review-...` (`creative_software_demo_review`) →
`artifacts/creative/software-demo-reviews/<id>.json`。

明确 custom hardware/manual installation/non-software/unavailable dependency hard
failure 必须 `invalid`；可局部澄清的 runtime/demo cut/integration gap 应
`repairable`
（`.../artifacts.py:579-638`）。

Controller：
`workflow.py:2505` `_review_software_demo()`；
Prompt `.../prompts/creative-software-demo-review.md:1-79`。

#### 9.4 Controller aggregation

第一轮：

- C4H=`pass,pass` 且 C4F=`pass` → non-terminal `pass`，继续；
- C4F=`invalid` 且含 hard reason → terminal
  `c4_software_demo_invalid`；
- 两个 C4H 都 `invalid` → terminal `c4_double_invalid`；
- 其他非全 pass → 唯一 C4 repair。

代码：
`src/hacksome/stages/ideation/creative/workflow.py:2225`
`_gate_one_concept()`。

#### 9.5 C4R

输入：

- `CONSTRAINT_VIEW`
- `CREATIVE_BRIEF`
- `SOFTWARE_DEMO_POLICY`
- `CONCEPT_REVISION`
- `HOOK_REVIEW_A`
- `HOOK_REVIEW_B`
- `SOFTWARE_DEMO_REVIEW`

Task：`creative-c4-repair-<concept>-r001`；只有 revision 1 可进入。

Envelope：`{"markdown":"..."}`。

机械不变量：

- `Intended Reaction`
- `Real Input, Transformation and Output`
- `Parent Atoms`

三段正文逐字保留；primary Territory、parent atoms、concept ID 不变。输出
revision 2，metadata `revision_reason=cheap_hook_repair`。

Revision 2 必须 fresh 重跑 2×C4H+1×C4F；第二轮只有三者全 pass 才继续，
否则 terminal `c4_unresolved_after_repair`。没有第二次 repair。

代码：

- `workflow.py:2341-2420` repair 后重审
- `workflow.py:2557` `_repair_concept()`
- `.../artifacts.py:641-663` source preservation validator

#### 9.6 审计产物

每 cycle 产生 decision
`creative-decision-c4-<concept>-r<revision>-c<cycle>`；每个 pass/repair/
superseded/eliminated 产生 `creative_concept_disposition` →
`artifacts/creative/dispositions/<id>.json`。

代码：
`workflow.py:2643` `_record_hook_decision()`；
`workflow.py:2681` `_publish_disposition()`。

### 10. C5M Memory 与 C5W Novelty

#### 10.1 C5M Recall

**目的**

只在 base Concepts 完成初始 C4 后，从 frozen historical capsules 提取抽象
inspire/avoid cues；C0–第一批 C4 完全看不到历史。

**输入**

- `CHALLENGE_BRIEF`
- `CREATIVE_BRIEF`
- `CURRENT_ATOM_INDEX`
- `BASE_CONCEPT_DISPOSITION_INDEX`
- `IDEA_MEMORY_SNAPSHOT`

不联网。

**fanout/envelope**

最多 1 task `creative-c5m-memory-recall-01`；
`{"cues":[...],"no_relevant_memory_reason":"...|null"}`；最多 8 cues。每 cue
绑定完整 composite historical identity 与至少一个 current Atom。

**skip/failure**

- mode=`off` → no task，summary=`disabled`；
- 无 Atom 或无 eligible history → no task，summary=`empty`；
- 0 cues 合法；
- task 或 provenance/context invalid → optional fail-open，summary
  `optional_failed`，不启动 Remix。

**输出**

成功时 `creative-memory-inspiration-packet-r001`
(`creative_memory_inspiration_packet`) →
`artifacts/creative/memory/creative-memory-inspiration-packet-r001.json`。

代码：
`src/hacksome/stages/ideation/creative/workflow.py:2732`
`_run_c5m()` 前半。

#### 10.2 C5M Remix

**输入**

- `CHALLENGE_BRIEF`
- `CREATIVE_BRIEF`
- `SOFTWARE_DEMO_POLICY`
- 一个 round-robin `CURRENT_ATOM`
- 一个 round-robin `MEMORY_CUE`

不联网、不递归 Recall。

**fanout/envelope**

默认最多 2 个 task `creative-c5m-memory-remix-01|02`；
`{"concept":null|{markdown,primary_territory_ref,current_atom_refs,
memory_source_refs,cue_refs}}`。

null 合法。非空必须：

- 使用 current Atom，primary Territory 来自它；
- 使用完整 memory composite refs 与 cue refs；
- 不复制 historical normalized Hook 或 mechanism+reveal pair。

**输出**

`creative-concept-m01|m02-r001` (`creative_concept`) →
`artifacts/creative/concepts/<ref>.md`，origin=`memory_challenger`、
revision_reason=`memory_remix`。

每个 challenger 随后走普通完整 C4，并在 pass 后走 C5W。各 Remix slot
独立 optional fail-open，一个失败不取消成功 sibling。

#### 10.3 C5M summary

无论 disabled/empty/completed/optional_failed 都发布：

- `creative-memory-stage-summary-r001`
  (`creative_memory_stage_summary`) →
  `artifacts/creative/memory/creative-memory-stage-summary-r001.json`

包含 Recall 状态、selected cue IDs、每个 Remix slot、successful challengers 与
failed tasks。实现：`workflow.py:3163` `_publish_memory_summary()`。

#### 10.4 C5W Novelty

**目的**

对每个最终 C4-pass exact revision 联网搜索 direct/near collision、trope、
AI-smell、adjacent/counterexample。结果是 evidence，不是 pass/reject。

**输入**

- `CHALLENGE_BRIEF`
- `CREATIVE_BRIEF`
- `CONCEPT_REVISION`

**fanout/envelope**

每个 C4-pass base/repaired/memory challenger 1 task：
`creative-c5w-novelty-<concept>-r<revision>`。

```json
{
  "markdown": "...",
  "sources": [{"title":"...","url":"...","relation":"...","evidence":"..."}]
}
```

**输出**

`creative-novelty-<concept>-r<revision>` (`creative_novelty_scan`) →
`artifacts/creative/novelty-scans/<ref>.md`。

**失败/skip**

- 没有 C4-pass → 0 tasks；
- 无可靠先例时可成功并诚实记录不确定性；
- C5W 不是 optional，任务/输出失败 fatal；
- C5W 不淘汰，C6A 必须消费它。

代码：
`src/hacksome/stages/ideation/creative/workflow.py:3206`
`_run_c5w()`；
Prompt `.../prompts/creative-novelty-scan.md:1-24`。

### 11. C6A — Evidence Revision

**目的**

每个 C4-pass exact revision 恰好生成一个 evidence-informed successor，不扩张
候选集。

**精确输入**

- `CHALLENGE_BRIEF`
- `CONSTRAINT_VIEW`
- `CREATIVE_BRIEF`
- `SOFTWARE_DEMO_POLICY`
- `CONCEPT_REVISION`
- `CHEAP_HOOK_EVIDENCE`（恰好 2 份 C4H）
- `SOFTWARE_DEMO_FEASIBILITY_EVIDENCE`（恰好 1 份 C4F）
- `NOVELTY_SCAN`
- `RELEVANT_MEMORY_CUES`（可为空）

**Controller**

- 每 C4-pass Concept 并行 1 task；
- 检查完整 2+1 C4 evidence；
- evidence revision budget 必须恰好消费一次；
- `Intended Reaction`、`Real Input, Transformation and Output`、
  `Parent Atoms` 逐字保留；
- ID/primary Territory/parent atoms/origin 不变，revision+1；
- source terminal disposition=`superseded_by_evidence_revision`。

**envelope / output**

`{"markdown":"..."}`；
新 `creative_concept` →
`artifacts/creative/concepts/<next-revision>.md`，metadata 绑定
hook/feasibility/novelty/memory evidence。

**失败/skip**

无 pass candidates 时整个 C6A/B 跳过；否则任何 task、budget、lineage、
source-preservation 失败均 fatal；无合法空输出。

**代码**

`src/hacksome/stages/ideation/creative/workflow.py:1038`
`_run_c6a()`；
validator `.../artifacts.py:841-864`；
Prompt `.../prompts/creative-evidence-revise.md:1-66`。

### 12. C6B — 两个 Curator 与 deterministic shortlist

#### 12.1 Agent curators

**输入**

- `EVIDENCE_INFORMED_PORTFOLIO`：每个 C6A Concept + Hook disposition + C4F +
  Novelty + relevant memory cue IDs
- `SOFTWARE_DEMO_POLICY`
- `CURATOR_LENS`（v4）
- `CURATION_CONTRACT`

Controller 有意不暴露 primary Territory allocation；round-robin 在代码做
（`workflow.py:3448` `_curation_portfolio_text()`）。

固定 2 fresh tasks：

1. `meaning_value_red_team`
2. `hackathon_floor_red_team`

IDs：`creative-c6b-portfolio-curator-01|02`。

每个 curator 必须对全部 Concepts 的五维给 `pass|uncertain|fail`：

- `software_demo_strength`
- `surprise_fun_or_intrigue`
- `one_sentence_clarity`
- `immediate_share_trigger`
- `novel_combination`

Decision 机械确定：全 pass=`include`；无 fail 且有 uncertain=`hold`；任一
fail=`exclude`
（`src/hacksome/stages/ideation/creative/artifacts.py:867-910`）。

**输出**

`creative-portfolio-curation-r001-v01|v02`
(`creative_portfolio_curation`) →
`artifacts/creative/curation/<ref>.json`；metadata 保存 slot、concept refs、
`curator_lens_id`。

#### 12.2 Controller shortlist

`_deterministic_shortlist()` 的优先 tiers：

1. include+include
2. include+hold
3. include+exclude
4. 其他不入选

每 tier 内按稳定 primary Territory round-robin，最多 8。Reason codes：

- `curators_both_exclude`
- `insufficient_include_support`
- `territory_round_robin_capacity`
- `portfolio_capacity`
- selected 为 `c6_shortlisted`

Controller 写 decision `creative-decision-c6b-shortlist-r001`，并为每 Concept
发布 non-terminal `shortlisted` 或 terminal `not_shortlisted` disposition。

**失败/skip**

C6A pool 非空时必须有两个完整 curator outputs；漏/重 Concept、维度/decision
不匹配、任一 task 失败均 fatal。Shortlist 为空合法，直接 empty batch → C7。

**代码**

`src/hacksome/stages/ideation/creative/workflow.py:1250`
`_run_c6b()`；
`workflow.py:3486` `_deterministic_shortlist()`；
Prompt `.../prompts/creative-portfolio-curate.md:1-90`。

### 13. Human gate（唯一人工暂停）

**进入条件**

C6B shortlist 非空。

**artifact/state**

- `creative-review-batch-r001` (`creative_human_review_batch`) →
  `artifacts/creative/curation/creative-review-batch-r001.json`
- 每 Concept 绑定 exact ref+sha256；
- Controller 构造稳定 adjacent-pair ring；
- run=`waiting`，stage=`creative-human-review`；
- next command=`hacksome review <run-dir>`。

实现：
`src/hacksome/stages/ideation/creative/workflow.py:787-825`,
`workflow.py:1417` `_publish_review_batch()`；
batch/round contract：
`src/hacksome/stages/ideation/creative/review.py:260-465`。

**人类输入**

每份 concept review 可含：

- independent one-sentence retell
- surprise/fun/mystery/confusion
- share impulse + concrete target
- demo confidence
- recommendation=`keep|revise|reject|taste_veto|no_opinion`
- comment

另有 adjacent pair preference 与 overall comment。Append-only ledgers：

- `human-reviews.jsonl`
- `human-resolutions.jsonl`

Review shape：
`src/hacksome/stages/ideation/creative/review.py:519-665`。

**关闭**

Curator 的 immutable HumanResolution 对每 shortlisted Concept 恰好一个：
`keep|revise|reject|taste_veto|merge`，并绑定 approved feedback、可选 curator
instruction、merge groups、coverage override、receipt/feedback set hashes
（`review.py:703-810`）。未覆盖 Concept 需要 override reason。

Closed 后 `wait.status=closed`，`resume` 才进入 C6C。

**空路径**

无 Concept 或 shortlist 空仍发布 `skipped_empty` batch，reason：

- `no_concepts_generated`
- v3 `all_candidates_failed_concept_screen`
- `shortlist_empty`

不进入 wait/human/C6C，直接 C7
（`workflow.py:734-756`, `workflow.py:771-785`）。

### 14. C6C — Human Feedback Finalization

**前置**

只接受 closed、hash-consistent human wait；shortlisted Concept、resolution、
receipt set、approved feedback set 必须未变；不得已有 Final Idea、feedback
binding 或 C6C task
（`src/hacksome/stages/ideation/creative/finalize.py:323-535`）。

**Action matrix**

| Human action | Agent call | Final Idea | terminal outcome |
| --- | --- | --- | --- |
| `keep` | 无，确定性复制 exact source | 1 | `promoted_to_final` / `human_keep` |
| `revise` | 1 | 1 | `revised_into` / `human_revise` |
| `reject` | 无 | 0 | `human_reject` |
| `taste_veto` | 无 | 0 | `human_taste_veto` |
| `merge` | 每 merge group 1 | 1 | 每 source `merged_into` / `human_merge` |

证据：
`src/hacksome/stages/ideation/creative/finalize.py:621-721`,
`finalize.py:897-922`。

**revise/merge Agent 输入**

- `CHALLENGE_BRIEF`
- `CONSTRAINT_VIEW`
- `CREATIVE_BRIEF`
- `SOURCE_CONCEPTS`
- `NECESSARY_EVIDENCE`
- `APPROVED_FEEDBACK`
- `CURATOR_INSTRUCTIONS`
- `RESOLUTION_BINDING`

只注入 resolution 批准的 fragments/instructions。每 action 最多 12 fragments、
总 24 KiB；revise/merge 没有 approved guidance 会失败
（`finalize.py:537-606`）。

注意：C6C 没有独立 `SOFTWARE_DEMO_POLICY` block；不要在 Explorer 中画成 C6A
同输入 shape。

**fanout/validation**

- revise task：
  `creative-c6c-revise-<concept>-r<revision>`
- merge task：
  `creative-c6c-merge-<merge-group-id>`
- envelope：
  `{"markdown":"...","primary_territory_ref":"creative-territory-XX"}`
- revise 保留 source primary Territory；
- merge 只能从 source Territories 中选；
- 每 source feedback budget≤1；
- 所有需要的 Agent calls 与 semantic checks 完成后才发布第一份 Final Idea，
  防止半套结果。

**输出**

- `creative-idea-001...` (`creative_final_idea`) →
  `artifacts/creative/ideas/<id>.md`
- `creative-feedback-binding-...`
  (`creative_human_feedback_binding`) →
  `artifacts/creative/curation/<id>.json`
- decision `creative-decision-c6c-...`
- 每 source terminal `creative_concept_disposition`

**失败/skip**

任何 hash/coverage/budget/Agent/Schema/semantic/publication 问题 fatal。
keep/reject/taste_veto 不调用模型。全 reject/veto 是成功的 0 Final Ideas，
zero reason=`all_human_rejected`。

主 Controller：
`src/hacksome/stages/ideation/creative/finalize.py:101-225`。

### 15. C7 — 完全 deterministic，无 Prompt

**边界**

C7 不调用 Agent、无 Prompt、无 Agent Schema、无 web：

1. `build_report_projection()` 从 consistent Hub snapshot 构建 typed projection；
2. `render_success_report()` 纯函数校验 lineage 并生成 exact bytes；
3. `FinalizationCoordinator.freeze()` 冻结 source、bytes、hash、publish order、
   completion event；
4. `replay()` 只发布 frozen exact bytes/events。

`report.py` 文件头明确 pure boundary：不读 run directory、不读 ledger、不调模型、
不用网络、不看当前时钟
（`src/hacksome/stages/ideation/creative/report.py:1-6`）。

Composition：
`src/hacksome/stages/ideation/creative/workflow.py:891-941`。

**输出**

- `creative-idea-report` (`creative_idea_report_markdown`) →
  `artifacts/creative/report/creative-idea-report.md`
- `creative-idea-report-json` (`creative_idea_report_json`) →
  `artifacts/creative/report/creative-idea-report.json`
- 每 Final Idea：`<idea-id>-card`（例如 `creative-idea-001-card`；
  `creative_idea_card`） →
  `artifacts/creative/idea-cards/<idea-id>.md`
- `creative-idea-card-index` (`creative_idea_card_index`) →
  `artifacts/creative/idea-cards/index.md`
- 每 Final Idea：`<idea-id>-handoff`（例如 `creative-idea-001-handoff`；
  (`creative_build_handoff`) →
  `artifacts/creative/handoffs/<idea-id>.json`
- `creative-memory-record` (`creative_memory_record`) →
  `artifacts/creative/memory/creative-memory-record.json`

Bundle：
`src/hacksome/stages/ideation/creative/report.py:63-71`,
`report.py:768-846`。

0 Final Ideas 时仍生成 Markdown/JSON report、空 card index、Memory Record；
不生成 per-idea card/handoff。

Idea Card 从 Final Idea exact sections、Novelty、去标识化 Human Signal 与 lineage
拼装；handoff 绑定 challenge/card hash；Memory Record 将 terminal revisions 和
Final Ideas 投影成下一 run 可冻结的 capsules，不含私人原始反馈
（`report.py:1017-1099`, `report.py:1160-1178`,
`report.py:1679-1802`）。

**freeze/replay**

- manifest：
  `state/creative-finalization/finalization-manifest.json`
- staged bytes：
  `state/creative-finalization/staged/...`
- ID：`creative-finalization-001`

`freeze()` stage 全部 bytes 并最后绑定 manifest；`replay()` 每次验证 source 与
staged hashes，幂等发布，最后一次性提交 results+completed transition
（`src/hacksome/stages/ideation/creative/finalization.py:917-1044`,
`finalization.py:1046-1098`）。

Manifest 已冻结但发布中断 → status=`finalizing`，`resume` 只 replay，不重 render、
不调 Agent。C7 在可恢复 plan 形成前失败 → run failed + partial report。

### 16. Explorer 应展示的节点与边类型

建议将 UI 明确区分：

1. **Agent nodes**：C0、C1、C1W、C2、C3、C4H、C4F、C4R、C5M Recall、
   C5M Remix、C5W、C6A、C6B、C6C revise/merge。
2. **Deterministic Controller nodes**：freeze、C1W snapshot/palette、C4
   aggregation、C6B shortlist、review batch、C6C keep/reject/veto/publication、
   C7 projection/render/freeze/replay。
3. **Human node**：reviews、coverage、approved feedback、resolution/merge。
4. **Artifact nodes**：Concept revisions、reviews、dispositions、Novelty、batch、
   Final Idea、C7 outputs。

边/状态需分开：

- fanout：C2×6、C3×4、每 revision C4H×2+C4F×1、Remix≤2、C5W×pass、
  C6A×pass、C6B×2；
- optional fail-open：C1W、C5M；
- fatal：其余 Agent 与 deterministic invariant；
- valid empty：C2 atoms=0、C3 concepts=0、Recall cues=0、Remix=null、
  shortlist empty、all human rejected；
- candidate disposition：C4/C6B/C6C；
- task invalidation：Schema/semantic/context 错误，不是 candidate reject；
- human wait：只在 non-empty shortlist；
- resume：closed human wait 或 frozen C7 manifest。

### 17. Files found

- `src/hacksome/stages/ideation/creative/workflow.py` — C0–C6B 主 Controller、
  fanout、C4 aggregation、optional branches、C7 composition。
- `src/hacksome/stages/ideation/creative/signals.py` — C1W window、Snapshot、
  status、安全 Palette。
- `src/hacksome/stages/ideation/creative/artifacts.py` — Creative envelopes 的
  semantic validators。
- `src/hacksome/stages/ideation/creative/contracts.py` — stage IDs、policy、
  fanout limits、stable IDs/reasons/revision budgets。
- `src/hacksome/stages/ideation/creative/prompting.py` — frozen Prompt/Schema
  catalog。
- `src/hacksome/stages/ideation/creative/memory.py` — Memory Snapshot/capsule 与
  provenance。
- `src/hacksome/stages/ideation/creative/review.py` — Human batch/round/review/
  resolution。
- `src/hacksome/stages/ideation/creative/finalize.py` — C6C bounded finalizer。
- `src/hacksome/stages/ideation/creative/report_projection.py` — C7 typed
  projection。
- `src/hacksome/stages/ideation/creative/report.py` — C7 pure renderer、Cards、
  handoff、Memory Record。
- `src/hacksome/stages/ideation/creative/finalization.py` — C7 freeze/replay。
- `src/hacksome/core/task_executor.py` — shared Agent task lifecycle。
- `src/hacksome/stages/ideation/creative/prompts/*.md` — Agent semantic contracts。
- `src/hacksome/stages/ideation/creative/schemas/*.json` — structured outputs。
- `tests/stages/ideation/creative/test_creative_workflow.py` — fanout/repair/
  Memory/C6 regressions。
- `tests/stages/ideation/creative/test_creative_signals.py` — C1W failure/window/
  palette regressions。
- `tests/stages/ideation/creative/test_creative_finalization.py` — C7 freeze/replay。

### 18. Related specs

- `.trellis/spec/backend/creative-agent-workflow-contracts.md`
- `.trellis/spec/backend/agent-workflow-contracts.md`
- `.trellis/tasks/07-23-creative-idea-review-loop/prd.md`

### 19. External references

无。本研究只使用 clean integration worktree 中的代码、Prompt、Schema、spec 与
tests。

## Caveats / Not Found

- 本 worktree 内未找到 Bilibili/哔哩哔哩/B站 run evidence，因此未用示例 run
  推断实现；Explorer 不应虚构 Bilibili 的具体数量或产物。
- 当前 C3 package Prompt 是 v7；spec 仍保留 v5/v6 演进说明。当前 Explorer 应标
  v7，历史 run 必须按 manifest 展示真实版本。
- C3 互斥 grammar 的完整真实性是 Prompt-level contract；代码机械绑定 marker，
  不等于独立语义分类器证明。
- C3 跨 synthesizer duplicate 会直接跳过，没有 disposition，这是当前实现的
  audit caveat。
- C5W 虽联网但不是 gate；它失败 fatal，成功仅提供 C6A evidence。
- C6C 没有独立 Software Demo Policy block。
- C7 完全无 Prompt；任何“模型总结报告/Card/Memory”的描述均与实现不符。
- `src/hacksome/creative/*` 是兼容入口；canonical 归属是
  `src/hacksome/stages/ideation/creative/*`。
