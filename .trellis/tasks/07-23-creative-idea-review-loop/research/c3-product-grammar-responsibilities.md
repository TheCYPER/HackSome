# Research: C3 product grammar responsibilities

- Query: 审计当前 `DEFAULT_TERRITORY_LENSES`、`SYNTHESIS_LENSES`、C3
  Prompt/version/workflow/context、机械去重和真实 C6B 结果；设计四个互斥且可识别
  的产品语法责任（Explorer/Simulator、Realtime Partner、Social Game/Relay、
  Creator/Transformer），并给出最小改动面、冻结版本兼容、反“抽象地图/节奏
  收据”同质化规则和测试缺口。
- Scope: internal
- Date: 2026-07-25

## Findings

### 1. 结论

当前 C6B 没有失效。真实 C3 v5 / C6B v4 smoke 中，两位 Red Team 正确发现了
两组机制重复，最终没有任何 `include`，Controller 合法发布
`shortlist_empty`。问题发生得更早：C3 的四个 `SYNTHESIS_LENSES` 是互相重叠的
创作提示，不是互斥的产品责任；四个 Session 又都能看到完整 Atom index，因而
会重复选择最显眼的 Atom，并把它们包装成不同标题或视觉皮肤。当前 Controller
只能去掉全文相同或 normalized Hook 相同的候选，无法在 C3 阶段识别这种语义
重复。

建议：

1. 不放松 C6B，不让 Controller 新增语义聚类器，也不改变 C6B Schema 或
   shortlist 算法。
2. 第一轮不改六个 `DEFAULT_TERRITORY_LENSES`，保留 C2 作为“机制素材池”，只把
   默认四个 C3 Session 从重叠的创作 lens 改为四个固定、互斥、带 stable ID 的
   产品语法责任。
3. 只将 `creative-concept-synthesize` 从 v5 提升到 v6；route-level
   contract/prompt/stage/report policy 仍为 v2，C3 JSON Schema 和十二个 H2
   不变。
4. v6 的每个 C3 Session 收到一个固定语法 ID，并只能为该语法生成 Concept；
   如果当前 Atoms 无法组成合格循环，返回零个 Concept。不得用“换一个视觉
   隐喻”填满配额。
5. 在已有 `Recognizable product grammar:` 行中要求回显 exact stable ID，并在
   C3 第二次语义校验时用 Controller 传入的 expected ID fail closed。这样不新增
   JSON 字段或 H2，也能让责任可识别、可测试。

### 2. Files found

| File | Relevant ownership |
| --- | --- |
| `src/hacksome/creative/contracts.py:61` | 六个默认 C2 Territory lens；同文件 `:139-154` 定义默认 6 个 explorer、4 个 synthesizer，`:185-196` 把最大值绑定为 6/4。 |
| `src/hacksome/creative/workflow.py:105` | 当前四个通用 `SYNTHESIS_LENSES`。 |
| `src/hacksome/creative/workflow.py:1709` | C2 按 slot 注入一个 Territory lens；每个 Agent 看不到 sibling。 |
| `src/hacksome/creative/workflow.py:1813` | C3 四个 Session 都读同一完整 Atom index，仅 `SYNTHESIS_LENS` 不同。 |
| `src/hacksome/creative/workflow.py:1864` | 跨 C3 Session 只按 normalized 全文与 normalized Hook 去重。 |
| `src/hacksome/creative/workflow.py:1177` | C6B 两个 fresh curator、v4-only `CURATOR_LENS` 注入和 Controller 聚合。 |
| `src/hacksome/creative/workflow.py:3215` | shortlist 只消费两份 `include|hold|exclude`；duplicate refs 不直接进入算法。 |
| `src/hacksome/creative/prompting.py:52` | 当前 C3 template v5、C6B v4；C3 显式兼容 v2/v3/v4，当前 v5 由 catalog 自动加入。 |
| `src/hacksome/prompts/creative/creative-concept-synthesize.md:1` | C3 v5 正文；要求 plain-language loop、自选 recognizable grammar、两个质量示例及格式自检。 |
| `src/hacksome/prompts/creative/creative-portfolio-curate.md:1` | C6B v4 的五维 categorical 判断、两类 Red Team 和跨池 duplicate 规则。 |
| `src/hacksome/creative/artifacts.py:449` | C3 section/ref/normalized Hook 语义验证；当前没有产品语法 ID 验证。 |
| `src/hacksome/creative/artifacts.py:821` | C6B 覆盖、五维顺序、机械 decision 和 duplicate ref 合法性验证。 |
| `src/hacksome/schemas/creative/creative-concept-synthesize.schema.json:1` | C3 envelope 只有 `markdown`、`primary_territory_ref`、`parent_atom_refs`。 |
| `src/hacksome/schemas/creative/creative-portfolio-curate.schema.json:1` | C6B 的五维与 `possible_duplicate_refs` shape。 |
| `src/hacksome/prompting.py:230` | frozen resource loader 按 stage allowlist 加载旧 template bytes，并保留 manifest 中真实版本。 |
| `tests/test_creative_prompting.py:48` | 当前版本矩阵、v4→v5 C3 frozen 兼容、plain-language markers。 |
| `tests/test_creative_workflow.py:323` | scripted C2/C3 runner 根据字符串 lens 反查 slot；尚未检查四类责任。 |
| `tests/test_creative_artifacts.py:132` | 只覆盖 Parent Atom、primary Territory、normalized Hook 和必需 H2。 |
| `tests/test_creative_curation_workflow.py:248` | C6B v4 两个 Red Team block/metadata 与 frozen v3 旧 shape 回归。 |
| `.trellis/spec/backend/creative-agent-workflow-contracts.md:214` | 当前 C6B、C3 v5、frozen version 和测试合同。 |
| `.trellis/tasks/07-23-creative-idea-review-loop/implement.md:73` | 第三次真实 smoke 的稳定摘要：7 个 base、4 个 C4 pass、C6B 零 shortlist、两组重复。 |
| `.trellis/tasks/07-23-creative-idea-review-loop/smoke-test-report.md:169` | 上一轮 v2 smoke 的 C6 shortlist、API/分享摩擦和机制聚类基线。 |

### 3. Current C2 audit: six useful ingredient pools, but mixed axes

当前六个 lens 是：

1. direct manipulation / unusual interaction；
2. reversal / reveal；
3. multiplayer / collaboration / propagation；
4. mystery / hidden state；
5. ordinary-device I/O transformation；
6. viral remix / replay / shareable artifact。

来源：`src/hacksome/creative/contracts.py:61-74`。

它们不是同一层级的分类：1/2/4 偏交互或叙事手法，5 偏输入媒介，3/6 已接近
完整产品/传播形态。因而同一个“停止输入 → 显示抽象结果 → 发链接”可同时满足
1、2、4、5、6；C2 本身没有跨 Session 比较，因为每个 explorer 只收到自己的
lens（`src/hacksome/creative/workflow.py:1726-1761`）。

不过真实 v5 smoke 的 C2 已生成 6 个 Territory、18 个 Atom，素材并不只剩一种：
除了 `放手地图`，还有噪声、光标、双人同步、静音采样、相机稳定、呼气删句和
接力涂鸦等方向。问题是 C3 重复选择了少数高显著性 Atom。两条直接证据：

- `放手地图` 已在 C2 内完整规定 release/idle → node/map → share link：
  `/private/tmp/hacksome-creative-grounded-smoke-20260724/creative-hack-the-rest-grounded-20260724-03/artifacts/creative/atoms/creative-atom-t04-03.md:15-33`。
- `未保存的最后一件事` 已在 C2 内完整规定保存时清除语义 → 键入节奏可视化 →
  “未保存收据”：
  `/private/tmp/hacksome-creative-grounded-smoke-20260724/creative-hack-the-rest-grounded-20260724-03/artifacts/creative/atoms/creative-atom-t02-02.md:15-33`。

因此第一轮应保持 C2 不变，只改变 C3 选材和成型责任。这样同题 v5/v6 对照只
改变一个变量，也避免同时提升 C2 template、维护第二套 frozen lens context。
如果 v6 后仍发现 18 个 Atom 本身高度收敛，再单独把 C2 改为正交的“机制
ingredient”分类并做第二次版本实验；不应在本轮一起修改。

### 4. Current C3 audit: v5 improves legibility, not portfolio partition

#### 4.1 Version and prompt

当前代码明确使用 C3 v5（`src/hacksome/creative/prompting.py:57`；
`tests/test_creative_prompting.py:48-75`）。v5 做对了几件事：

- 强制 `User does:`、`Software immediately responds:`、
  `Why try or share again:`；
- 要求 `Recognizable product grammar:`；
- 用 relationship-path explorer 和 realtime Jam partner 校准“熟悉入口 +
  真实输入 + 即时回应 + 重复玩法 + 分享物”；
- 明确禁止复制两例表面题材；
- 约束 650–900 词并机械自检十二个 H2/ref。

见 `src/hacksome/prompts/creative/creative-concept-synthesize.md:47-90` 和
`:92-130`。

缺口是 `Recognizable product grammar:` 由每个 Agent 自己命名“最近的 family”，
而不是 Controller 分配的责任；JSON 也没有 grammar 字段
（`src/hacksome/schemas/creative/creative-concept-synthesize.schema.json:5-33`）。
所以它能让单个 Concept 更好懂，但不能阻止四个 Agent 都选择
“shareable generator / relay map”。

#### 4.2 Four current synthesis lenses overlap

当前四个 lens（`src/hacksome/creative/workflow.py:105-110`）分别是：

1. legible interaction loop；
2. sharp reversal and reveal；
3. software-native share/replay/remix artifact；
4. hidden state or surprising technical mechanism。

这四项没有互斥的用户、状态、时序或“下一步动作”责任。一个 release map 同时是
legible loop、reveal、share artifact 和 hidden state；一个 rhythm receipt 同时
是 reversal、share artifact 和 technical mechanism。

真实 v5 run 保存的四个 exact C3 block 也只是上述单行字符串：

- slot 1：
  `/private/tmp/hacksome-creative-grounded-smoke-20260724/creative-hack-the-rest-grounded-20260724-03/tasks/creative-c3-synthesis-01/prompt.md:997-999`
- slot 2：
  `/private/tmp/hacksome-creative-grounded-smoke-20260724/creative-hack-the-rest-grounded-20260724-03/tasks/creative-c3-synthesis-02/prompt.md:997-999`
- slot 3：
  `/private/tmp/hacksome-creative-grounded-smoke-20260724/creative-hack-the-rest-grounded-20260724-03/tasks/creative-c3-synthesis-03/prompt.md:997-999`
- slot 4：
  `/private/tmp/hacksome-creative-grounded-smoke-20260724/creative-hack-the-rest-grounded-20260724-03/tasks/creative-c3-synthesis-04/prompt.md:997-999`

实际输出印证了重叠：

- slot 1 产出 `shareable scroll toy` 和 `shareable gesture generator`；后者是
  release map：
  `.../artifacts/creative/concepts/creative-concept-s01-02-r001.md:1-40`。
- slot 2 产出 `保存后清除语义 → 节奏收据`：
  `.../artifacts/creative/concepts/creative-concept-s02-01-r001.md:1-34`。
- slot 3 产出 `放手后生成并接力的地图`：
  `.../artifacts/creative/concepts/creative-concept-s03-01-r001.md:1-38`。
- slot 4 又产出一个相同 Parent Atoms 的接力地图和一个呼吸节奏收据：
  `.../artifacts/creative/concepts/creative-concept-s04-01-r001.md:1-42` 与
  `.../artifacts/creative/concepts/creative-concept-s04-02-r001.md:1-42`。

`run.json` 还显示 slot 3 和 slot 4 的地图都使用
`creative-atom-t04-03 + creative-atom-t03-01`，只是标题/Hook 不同：
`/private/tmp/hacksome-creative-grounded-smoke-20260724/creative-hack-the-rest-grounded-20260724-03/run.json:549-621`。

#### 4.3 Current context and dedup

每个 C3 Session 都读取完全相同的 Challenge、Constraint、Brief、Policy 和
全部 Atom index，只由 `SYNTHESIS_LENS` 区分
（`src/hacksome/creative/workflow.py:1822-1862`）。这符合“独立、无 Memory”
合同，但也让四个 Agent 都能抢同一高显著性 Atom。

Controller 的跨 Session 去重只有：

```text
normalized full Markdown OR normalized One-sentence Hook
```

见 `src/hacksome/creative/workflow.py:1864-1890`。单 Session validator 同样只拒绝
exact/normalized-Hook duplicate（`src/hacksome/creative/artifacts.py:449-492`）。
因此：

- “按住/松开/停顿 → 地图”与“按住/松开/空闲 → 接力地形”Hook 不同，会同时
  保留；
- “保存/删除原文 → 键入节奏收据”与“保存/呼气删除 → 节奏收据”Hook 不同，也
  会同时保留；
- `primary_territory_ref` 只证明 Parent Atom 谱系，不证明体验语法不同。

不建议在 C3 Controller 增加 embedding、LLM judge 或手写语义合并。现有设计已
明确把机械去重与语义审查分开；新的生成责任应降低重复概率，C6B 继续负责晚期
反证。

### 5. Current C6B audit: correct late rejection, not a generation fix

真实成功 run 的 frozen manifest 是 C3 v5 / C6B v4：
`/private/tmp/hacksome-creative-grounded-smoke-20260724/creative-hack-the-rest-grounded-20260724-03/resources/manifest.json:57-63`
和 `:169-175`。

四个 C6A Concept 的结果：

| Concept | Meaning/Value | Hackathon Floor | Duplicate family |
| --- | --- | --- | --- |
| `s01-02-r002` release map | hold | hold | `s03-01-r002`；Floor 还把 `s02` 视为相邻机制 |
| `s02-01-r002` rhythm receipt | exclude | hold | `s04-02-r003` |
| `s03-01-r002` relay map | hold | hold | `s01-02-r002` |
| `s04-02-r003` breath receipt | exclude | hold | `s02-01-r002` |

Meaning/Value 的两项 receipt 在 `novel_combination` 上直接 `fail`：
`.../creative-portfolio-curation-r001-v01.json:72-79` 与 `:152-159`；两项 map
互相为 duplicate 且为 `uncertain`：同文件 `:32-39`、`:112-119`。Hackathon
Floor 四项都为 `hold`，并同样写出 duplicate refs：
`.../creative-portfolio-curation-r001-v02.json:4-40`、`:45-81`、
`:86-121`、`:126-161`。

Controller 只读取两份 categorical decision
（`src/hacksome/creative/workflow.py:1291-1303`），再按 approval tier +
Territory round-robin 选择（`:3215-3317`）。`possible_duplicate_refs` 是审计
证据，不直接删候选；它通过 `novel_combination` verdict 间接影响
include/hold/exclude。最终四项分别为 `hold/hold`、`exclude/hold`、
`hold/hold`、`exclude/hold`，没有一票 `include`，所以 shortlist 为空：

- decision ledger：
  `/private/tmp/hacksome-creative-grounded-smoke-20260724/creative-hack-the-rest-grounded-20260724-03/decisions.jsonl:16`
- empty batch：
  `/private/tmp/hacksome-creative-grounded-smoke-20260724/creative-hack-the-rest-grounded-20260724-03/artifacts/creative/curation/creative-review-batch-r001.json:1-7`

这正是当前 gate 应有的行为：不应为了得到非空 shortlist 而放松 novelty，也不
应改成“每组自动保留一个代表”。生成层先形成更不同的产品循环，C6B 仍有权把
四类全部 hold/exclude。

### 6. Proposed four mutually exclusive product grammar responsibilities

互斥轴不是视觉媒介、题材或是否可分享，而是：

> 软件回应之后，核心用户为了获得下一单位价值必须做什么？

每个 Concept 必须只有一个 primary next action。次要功能不能改变分类；若两类
都不可删除、无法指出唯一 primary loop，C3 应简化到一类或返回零 Concept。

稳定 ID 建议固定为：

| ID / label | Owns this value loop | Required evidence | Does not count |
| --- | --- | --- | --- |
| `explorer_simulator` / Explorer–Simulator | 用户提出查询、改变显式变量或操纵状态，软件计算一个可检查的关系/路径/情景/反事实；下一步是比较、追问或改变假设。 | 至少一个真实 query/config/state input；可解释的 computed state；第二次改变变量后可比较的结果；结果中的节点/轴/状态必须对应用户理解的实体或变量。 | 手势遥测被装饰成情绪地图；没有可追问变量的单次 reveal；静态总结卡；以产出漂亮 artifact 为主要价值。 |
| `realtime_partner` / Realtime Partner | 用户持续或按短节奏行动，软件在本轮结束前低延迟回应；用户根据回应改变下一次输入，形成 call-and-response / co-performance。 | streaming/rapid-sequence real input；明确 latency budget；软件回应先于下一动作；至少一个 mode/round 能改变双方行为。录制物只能是次要输出。 | 上传后批处理成图；会话结束才出现 map/receipt；另一个真人接力才成立；只有一次 AI 奇观。 |
| `social_game_relay` / Social Game–Relay | 至少另一位真人在规则约束下采取下一步，软件持有/裁决共享状态；下一步是另一个人的 move、turn、challenge 或 handoff。 | 明确角色/回合/共享状态；recipient 打开后有一项低摩擦、规则约束且会改变状态的动作；软件而非主持人执行状态转移；第二人缺席时核心价值不成立。 | 单人 generator 只把 PNG/链接发给被动观看者；排行榜/分享按钮附加在单人工具上；没有 recipient action 的“viral”。 |
| `creator_transformer` / Creator–Transformer | 用户用真实素材和有意义控制反复制作、编辑或变换一个可复用 artifact；下一步是 edit、remix、export 或继续创作。 | 真实 source material；至少两个会改变成品的 deliberate controls/iterations；可预览并修改；成品价值依赖用户选择而非只记录行为遥测。 | 自动生成“你刚才做了什么”的 receipt；不可编辑的一次性卡；主要目的是诊断/探索；实时软件搭档而非创作工具。 |

#### 6.1 Boundary tests for mixed concepts

用“删掉哪一项后核心价值消失”判定 primary grammar：

- 删除 query/variable comparison 后价值消失 → Explorer/Simulator。
- 把实时输入替换为完成后的文件上传后价值消失 → Realtime Partner。
- 删除另一位真人的下一步动作后价值消失 → Social Game/Relay。
- 删除可修改/重做/导出的用户作品后价值消失 → Creator/Transformer。

若一个 Concept 声称两个答案，应删除次要 loop；不能以“这是混合类型”绕过互斥
责任。

#### 6.2 Exact slot responsibility

默认四个 C3 slot 建议固定：

1. `explorer_simulator`
2. `realtime_partner`
3. `social_game_relay`
4. `creator_transformer`

每个 slot 仍可看到完整 C0–C2 Atom index，但只允许输出其 assigned grammar。
它不必使用同名 Territory，也不能因某个 Atom 已经像完整产品就原样扩写。若
没有能满足 assigned grammar 的组合，输出 `concepts=[]`。

`concept_synthesizers < 4` 的显式测试/低成本设置只运行前 N 类；只有默认值 4
保证四类都被尝试。若产品要求任何运行都完整覆盖四类，则必须另行把
`concept_synthesizers` 从 bounded setting 改为 fixed 4，这会扩大合同和兼容
范围，本轮不建议。

#### 6.3 Exact English copy for C3 v6

Controller 每个 Session 只需注入：

```json
{
  "assigned_product_grammar_id": "explorer_simulator",
  "assigned_product_grammar_label": "Explorer / Simulator"
}
```

详细责任写入 frozen v6 Prompt。以下英文可直接作为规范性文案：

**Shared assignment rule**

> The assigned product grammar is a product-loop responsibility, not a theme,
> visual style, input medium, or suggestion. Produce only Concepts whose primary
> next user action matches the assigned grammar. Features from another grammar
> may be secondary, but deleting them must not destroy the primary loop. If a
> Concept needs two primary grammars, simplify it to one. If the supplied Atoms
> cannot support this grammar honestly, return zero Concepts instead of
> relabeling a decorative map, receipt, card, recording, or share link. In
> `Why It Is Unexpected Yet Legible`, write `Recognizable product grammar:
> <assigned_product_grammar_id> — ...` using the exact assigned ID.

**`explorer_simulator` — Explorer / Simulator**

> Build only an Explorer / Simulator. The primary loop is: the user asks a
> question or changes explicit variables; the software computes a grounded
> model, path, scenario, or counterfactual; the user inspects and compares the
> result, then changes the query or an assumption. Every node, axis, state, and
> transition must correspond to a user-understandable entity or variable. A
> gesture trace turned into decorative terrain, a mood map, or a one-shot reveal
> is not this grammar. Sharing may carry a query or computed state, but
> exploration and comparison—not artifact generation—must be the primary value.

**`realtime_partner` — Realtime Partner**

> Build only a Realtime Partner. The primary loop is: the user supplies real
> continuous or rapid-sequence input; the software returns a bounded-latency
> response before the round ends; the user changes the next action because of
> that response. State the latency budget, the adaptive rule, and a second mode
> or round that produces meaningfully different call-and-response behavior. A
> recording may be a secondary share artifact. Uploading input for later batch
> processing, or producing a map, card, score, or receipt only after the
> interaction ends, is not this grammar.

**`social_game_relay` — Social Game / Relay**

> Build only a Social Game / Relay. The primary loop is: one human action changes
> controller-owned shared state; another named participant joins or opens the
> handoff and performs a rule-bound move; the software applies that transition
> and creates the next turn, challenge, or relay state. The recipient's action
> is constitutive: remove it and the core value must collapse. A passive result
> link, a single-user generator with a share button, a leaderboard added to a
> solo tool, or a host-mediated performance is not this grammar. The shared
> state may be visual, but it must be an actionable board or handoff, not merely
> an abstract map to view.

**`creator_transformer` — Creator / Transformer**

> Build only a Creator / Transformer. The primary loop is: the user supplies
> authentic source material; makes at least two deliberate choices, edits, or
> transformations; sees the software preview the consequence; then revises,
> remixes, saves, or exports a reusable artifact. The artifact's value must
> depend on the user's creative decisions, not merely on telemetry the software
> recorded while the user acted. An automatically generated receipt, summary,
> mood card, or one-click filter with no meaningful edit loop is not this
> grammar. Sharing is valid when it carries the authored artifact; recipient
> participation is optional rather than the core state transition.

### 7. How this blocks abstract-map / receipt convergence

不要禁用 `map`、`card`、`PNG` 或 `receipt` 这些词；它们有合法用途。应按语法
责任判断它们是不是核心价值：

- Explorer 的 map 只有在节点/边/变量对应真实可理解的实体或 simulation state，
  且用户能改变 query/assumption 得到可比较结果时才成立。`release time →
  abstract terrain` 没有可追问的领域状态，不是 Explorer。
- Realtime Partner 的核心输出必须在输入进行中回来并改变用户下一动作；会话后
  才生成的 route/card/receipt 自动不合格。
- Social Game/Relay 可以使用 map，但它必须是可操作的共享 board/state；收件人
  必须按规则做一步并改变状态。被动 replay URL 不成立。真实 smoke 的 relay map
  至少接近这一类，而 passive release map 不应冒充同类。
- Creator/Transformer 可以输出 PNG/音频/卡片，但用户必须通过有意义控制进行
  edit/remix。`type → save deletes text → software emits typing-rhythm receipt`
  只是行为遥测的自动收据；除非改成用户可编辑、可组合的节奏创作工具，否则不
  是 Creator。

C3 v6 Prompt 还应明确写出：

1. “不同视觉皮肤、故事、传感器或分享格式”不能改变 grammar；
2. assigned grammar 的 required next action 必须在 `Audience Action` 和
   `Why It Is Unexpected Yet Legible` 中出现；
3. `Software immediately responds:` 必须证明该 grammar 的状态转移；
4. `Recognizable product grammar:` 使用 exact
   `<stable_id> — <plain-language explanation>`；
5. 不符合 assigned grammar 时返回零，不得把抽象 map/receipt 强行重命名；
6. relationship-path 和 Jam partner 仍是禁复制题材；v6 应以四类 acceptance
   contract 为主体，避免继续只用两个具体例子锚定全池。

### 8. Minimum affected files

#### 8.1 Recommended contract-safe minimum

1. `src/hacksome/creative/workflow.py`
   - 保留旧 `SYNTHESIS_LENSES` 供 frozen C3 v2–v5；
   - 新增四个 stable grammar assignments；
   - 仅当 frozen C3 template version 为 `"6"` 时，向四个 slot 注入对应 ID；
   - `_validate_completed_output` 的 context 仅在 v6 带 expected grammar ID。
2. `src/hacksome/prompts/creative/creative-concept-synthesize.md`
   - 加入四类完整定义、互斥 next-action/removal tests、map/receipt 反例；
   - 要求 exact ID marker 和不适配时返回零。
3. `src/hacksome/creative/prompting.py`
   - C3 `version="6"`；
   - compatible versions 变为 `("2", "3", "4", "5")`。
4. `src/hacksome/creative/artifacts.py`
   - `CreativeValidationContext` 增加 optional expected grammar ID；
   - `_validate_c3` 只在该 context 存在时检查 exact marker。旧版本不触发。
5. `tests/test_creative_prompting.py`
6. `tests/test_creative_workflow.py`
7. `tests/test_creative_artifacts.py`
8. 实施完成后用 `trellis-update-spec` 更新
   `.trellis/spec/backend/creative-agent-workflow-contracts.md`。

为了让责任定义随 frozen template bytes 固定，建议把四类详细规则写在 v6 Prompt
template 中；Controller block 只注入 stable ID/label，不在 Python 常量里复制整段
规则。这样以后修改规则必须提升 template version。

#### 8.2 Files that should remain unchanged in this iteration

- `src/hacksome/creative/contracts.py`：六个 `DEFAULT_TERRITORY_LENSES`、settings
  和 route-level policy 不变。
- `src/hacksome/schemas/creative/creative-concept-synthesize.schema.json`：不新增
  grammar JSON 字段；使用现有 Markdown marker + validation context。
- `src/hacksome/prompts/creative/creative-portfolio-curate.md` 和
  `creative-portfolio-curate.schema.json`：C6B v4 已正确工作。
- `_deterministic_shortlist`、C6B reason codes、C6 review payload/report：
  均不变。
- C6A/C4R Prompt：grammar 是 initial C3 generation provenance；C6A 仍按实际
  mechanism 和 C5W evidence 澄清，不允许换 core。若将来要求 grammar ID 成为
  每个 revision 的不可变 metadata，再单独设计贯穿 revision/report/memory 的
  schema，不要在本次 prompt patch 中半接线。

### 9. Version compatibility

当前 `PromptCatalog.load_frozen()` 会验证 manifest template version 是否在
stage allowlist 中，并加载 run-local exact template/schema bytes，而不是当前
package bytes（`src/hacksome/prompting.py:230-326`）。因此：

- 新 run：C3 v6，四个 grammar assignment；
- frozen C3 v5/v4/v3/v2：继续加载各自字节；
- legacy contract v1：继续由 `legacy_creative_prompt_catalog` 加载 v1；
- route-level contract/prompt/stage/report policy 仍是 v2；
- C3 JSON envelope、H2、ID、fanout、C4/C5/C6 route policy 均不变。

必须额外 version-gate Controller context。当前 `_run_c3` 无条件读取同一个
`SYNTHESIS_LENSES` 常量（`src/hacksome/creative/workflow.py:1853-1862`）；如果
只原地替换常量，旧 frozen C3 template 也会收到新语义 block。应复制 C6B 已有
模式：它只在 frozen C6B version `"4"` 时注入新 lens/metadata
（`src/hacksome/creative/workflow.py:1187-1223`）。

建议的 C3 gating：

```text
template v2-v5 → 原来的单行 SYNTHESIS_LENS；不要求 exact grammar ID
template v6    → assigned grammar ID/label；要求 exact marker
```

这也使失败的 v4/v5 smoke 和已经完成的 v5 run 不被事后标成执行过四类责任。

### 10. Tests to add

#### 10.1 Prompt/catalog

- C3 current template version 是 v6；C6B 仍为 v4，其他 stage version 不漂移。
- v6 Prompt 包含四个 exact stable ID，且每类都有：
  - primary next action；
  - required loop/evidence；
  - 至少三个 other-grammar exclusion；
  - map/receipt 边界；
  - 不适配时返回零。
- 原有十二 H2、plain-language markers、650–900 词、自检、禁止复制
  relationship-path/Jam 例子的断言继续通过。
- frozen C3 v5 catalog 可加载并仍报告 template version `"5"`。

#### 10.2 Workflow/context

- 默认四个 C3 task 按 slot 精确收到
  `explorer_simulator`、`realtime_partner`、`social_game_relay`、
  `creator_transformer`，无重复或漏项。
- 四个 task 仍收到相同完整 Atom index、同一 Policy bytes，且不含 Memory/
  history。
- reduced `concept_synthesizers=N` 只启动前 N 个稳定 assignment，任务 ID 与
  deterministic ordering 不变。
- 用 frozen C3 v5 catalog 执行时仍收到旧 `SYNTHESIS_LENS` shape，不要求新
  grammar marker。
- v6 Concept 的 marker 与 assigned ID 一致；任务/artifact 的现有
  `synthesis_slot` 仍可追溯。

#### 10.3 Semantic validator

- exact assigned ID marker 通过；
- marker 缺失、未知、或把 slot 1 输出标成 `creator_transformer` 时
  invalidated；
- 没有 expected grammar context 的 v2–v5 output 保持兼容；
- C3 JSON Schema bytes、十二 H2、Parent Atom、primary Territory、
  normalized-Hook 去重行为不变。

#### 10.4 C6B non-regression

- 现有两类 Red Team、五维顺序、mechanical decision、v3 legacy block/metadata
  shape、empty shortlist 测试全部继续运行。
- 增加一个明确回归：`possible_duplicate_refs` 本身不能绕过或替代
  categorical decision；Controller 不因四个 grammar ID 各出现一次就自动
  include。
- 不要求 duplicate graph 全局对称。当前两位 curator 的 refs 本来可以不同；
  authority 是各自 `novel_combination` evidence/verdict。若未来要做 graph 指标，
  可在 benchmark projection 中无向归一化，不能改变在线 shortlist。

#### 10.5 Real same-challenge v5/v6 comparison

单元测试只能证明分配、marker 和 fail-closed，不能证明模型真的生成多样产品。
应使用相同 `Hack the Rest` challenge/Brief/Policy、Idea Memory off 新建 v6
run，对比 frozen v5 baseline，至少记录：

- 四个 grammar task 是否各执行一次、各自生成 0–N；
- 生成 Concept 的 grammar coverage；
- C4 pass 数与 C5W task/token 成本；
- C6B duplicate edge 数、无向 connected component 数、最大 family size；
- `abstract map` / `process receipt` family 数；
- shortlist 数只作为结果，不作为“必须非零”的成功条件。

成功标准应是重复 family 变少、产品循环可归类且边界清楚；不能以 C6B 变宽松或
强行每类保留一项制造表面改善。

#### 10.6 Minimum test matrix

| Layer | Positive | Negative / compatibility |
| --- | --- | --- |
| Catalog | current C3=`6`; C6B=`4` | frozen C3 `5` loads exact and reports `5` |
| Prompt | four IDs occur once; each has required loop + exclusions | missing zero-output rule, exact marker, map/receipt boundary, or old example ban fails |
| Workflow | default slots map 1:1 to the four IDs; same Atom index/Policy, no history | v5 gets legacy lens block; v6 duplicate/missing ID fails |
| Artifact validation | exact assigned marker accepted | missing/unknown/wrong assigned ID invalidates only v6 context |
| Existing C3 contract | twelve H2, Parent Atom refs, primary Territory, exact/hook dedup pass | JSON Schema/H2 bytes or old-output behavior must not drift |
| C6B | two v4 Red Teams, five dimensions, mechanical decision, empty shortlist all pass | grammar coverage cannot force include; duplicate refs cannot replace decision |
| Real smoke | same challenge records grammar coverage and duplicate components | success is not “shortlist must be non-empty”; v5 bytes/results remain immutable |

## Code patterns

- Frozen compatibility pattern：current stage version + explicit historical
  allowlist，见 `src/hacksome/creative/prompting.py:68-75`；loader 保留旧 bytes，
  见 `src/hacksome/prompting.py:289-326`。
- Version-gated context pattern：C6B 仅 v4 注入 `CURATOR_LENS` 并记录 lens ID，
  见 `src/hacksome/creative/workflow.py:1187-1258`。C3 v6 应复用这种模式。
- Context-aware second semantic validation：stage output 发布前可传入 route facts，
  见 `src/hacksome/creative/workflow.py:3015-3040`。expected grammar ID 应在这里
  验证，不修改 frozen old schema。
- Mechanical-vs-semantic separation：C3 Controller 只做 exact/hook dedup，
  `src/hacksome/creative/workflow.py:1864-1890`；C6B Agent 做机制级反证，
  `src/hacksome/prompts/creative/creative-portfolio-curate.md:66-81`。
- Fixed-role fanout precedent：`_PORTFOLIO_CURATOR_LENSES` 的 stable ID + slot，
  `src/hacksome/creative/workflow.py:112-131`。四类 C3 responsibility 可沿用同一
  tuple 结构，但详细规则应留在 frozen v6 template。

## External references

未使用外部网页或第三方产品分类。此次结论来自仓库规范、当前实现、测试和
2026-07-24 的真实 frozen run。相关内部版本：

- Creative route contract/prompt/stage/report policy: v2
- Software Demo Policy: v2
- current C3 template: v5
- current C6B template: v4
- proposed C3 template: v6 only

## Related specs

- `.trellis/spec/backend/creative-agent-workflow-contracts.md:152-170` —
  frozen resources 与旧版本 fail-closed。
- `.trellis/spec/backend/creative-agent-workflow-contracts.md:214-251` —
  C6B categorical contract、C3 v5 markers、C2/C3 lineage。
- `.trellis/spec/backend/creative-agent-workflow-contracts.md:486-525` —
  当前测试矩阵。
- `.trellis/spec/guides/cross-layer-thinking-guide.md:1-42` — context、Prompt、
  validator、artifact/report 的跨层格式应由单一 owner 明确验证。
- `.trellis/spec/guides/code-reuse-thinking-guide.md:49-80` — stable grammar
  registry 与解析不能在 Prompt test、workflow 和 validator 各自复制不同版本。

## Caveats / Not Found

- 真实 C6B raw artifacts 位于 `/private/tmp`，未提交 Git，可能被清理。稳定仓库
  摘要仍在
  `.trellis/tasks/07-23-creative-idea-review-loop/implement.md:73-81`；本文件保留
  临时路径只为当前可复核审计，不能把它当长期 fixture。
- 当前 C6B validator 只检查 duplicate refs 合法、唯一、非 self，不要求两位
  curator 或同一 curator 的关系图完全对称
  （`src/hacksome/creative/artifacts.py:856-864`）。本次真实结果虽大体成对，
  Hackathon Floor 的邻接集合比 Meaning/Value 更宽；这是独立视角，不是错误。
- 四类责任是生成约束，不是确定性语义分类器。离线测试不能证明 LLM 没有用新
  名称包装旧 map/receipt；真实同题 run 是必需验收。
- C5M Remix challenger 当前不分配四类 grammar。第三次 smoke 使用 Memory off，
  所以本次根因与 C5M 无关；若以后 Memory-on benchmark 出现 grammar 回流，应
  单独扩展 C5M，而不是扩大本轮最小 C3 patch。
- 若未来决定修改 `DEFAULT_TERRITORY_LENSES`，其文本来自 Controller context，
  不是 Prompt template bytes。必须同时设计 C2 version gating/freeze 策略，
  不能只原地替换常量后声称旧 run context 不变。
