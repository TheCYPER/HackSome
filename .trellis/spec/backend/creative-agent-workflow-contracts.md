# Creative Idea 工作流合同

> Creative route 的规范性后端合同。实现、CLI、离线 validator 与测试必须以
> 本文为准；PRD/design 用于解释产品意图，不能替代这里的可执行约束。

## 1. Scope / Trigger

当修改以下任一部分时必须读取本文：

- `src/hacksome/stages/ideation/creative/` 下的 C0–C7 工作流；
- Hub route、wait、human ledger、finalization 或 result artifact；
- `run --route creative`、`review`、Creative `resume` 或 `benchmark`；
- Idea Memory 的发现、冻结、Recall/Remix 或完成后回写；
- Creative report、Idea Card、partial report 或 Build handoff。
- `docs/creative-workflow-explorer/` 中面向人的 Creative 流程投影。

### 面向人的流程投影同步约定

`docs/creative-workflow-explorer/app.js` 是当前合同和指定真实 run 的只读人工维护
投影，不是 runtime 的第二份事实来源。修改 stage、fanout、Prompt/Schema
版本、Controller/Model/Web/Human 分工、产物路径、gate 或失败语义时，必须在
同一变更中同步该页面和 `tests/docs/test_creative_workflow_explorer.py`。

页面必须区分：

- 架构合同与某一次真实 run 的证据；
- Agent 返回内容与 Controller 接受、发布的内容；
- 自动“30 秒理解”代理信号与真实无背景人类测试；
- 有模型 Prompt 的节点与 C6 Human、C7 等无模型节点。

页面中的 Prompt、Schema 和代码链接必须是存在的 repo-relative path；C1W
fail-open 必须同时展示 optional branch 失效与主线继续，不能写成“信号已被后续
Agent 忽略”。页面不读取 run、不提交评审，也不能改变 runtime 合同。

Creative 从一道 challenge 开始，在 Idea 阶段结束。它不负责实现产品、创建
Repo、部署或 Pitch。C6 是唯一 Human-in-the-loop gate；C0–C5 不得增加人工
暂停。新 run 使用 Creative contract v3：它继承 v2 的 software-first
约束，核心体验必须由可执行软件产生，并有比赛期间可运行的真实端到端 Demo
路径与具体分享触发物；同时增加一次 optional、fail-open 的 C1W 文化信号扫描。

```text
C0 Challenge & Constraints
→ C1 Creative Brief + frozen Software Demo Policy
→ C1W Cultural Signal Scan
→ C2 Software-native Creative Territories
→ C3 Concept Synthesis
→ C4H Cheap Hook/Share Trigger + C4F Software Demo Feasibility
→ C5M Idea Memory / C5W Novelty Scan
→ C6A Evidence Revision / C6B Portfolio / C6C Human Feedback
→ C7 Deterministic Report
```

Useful 与 Creative 共享 `CodexRunner`、`RunHub`、Prompt/Schema freeze、
`AgentTaskExecutor`、原子文件和 route registry。两条路线不共享候选语义、
gate reason 或报告结构。

“淘汰硬件”只指淘汰定制/专用硬件、实体制作、设备搭建/搬运/校准作为核心；
普通电脑/手机及其内置 screen、keyboard、touch、camera、microphone、
speaker、accelerometer 合法。若去掉主持人、演员、卡片、椅子或舞台规则后
软件不能独立完成可观察转换，则属于纯装置/人工表演核心并自动淘汰。

## 2. Signatures

### Python

```python
CreativeIdeaWorkflow.create(
    challenge: str,
    runs_dir: str | Path,
    *,
    settings: CreativeWorkflowSettings | None = None,
    codex_config: CodexConfig | None = None,
    run_id: str | None = None,
    runner: Runner | None = None,
    creative_brief: str | None = None,
    creative_brief_file: str | Path | None = None,
    memory_snapshot: IdeaMemorySnapshot | None = None,
    run_timeout_seconds: float = 6 * 60 * 60,
) -> CreativeIdeaWorkflow

CreativeIdeaWorkflow.open(
    run_dir: str | Path,
    *,
    runner: Runner | None = None,
    run_timeout_seconds: float = 6 * 60 * 60,
) -> CreativeIdeaWorkflow

await workflow.execute() -> CreativeRunOutcome
await workflow.resume() -> CreativeRunOutcome

build_report_projection(
    run_dir_or_hub,
    *,
    producer_kind: Literal["live", "fixture"] = "live",
    snapshot: Mapping[str, Any] | None = None,
) -> CreativeReportProjection

render_success_report(
    projection: CreativeReportProjection,
) -> RenderedReportBundle

FinalizationCoordinator(hub).finalize(outputs_or_renderer)
FinalizationCoordinator(hub).replay()
```

`CreativeRunOutcome.status` 只能是：

- `waiting`：非空 C6 batch，等待人工评审；
- `finalizing`：C7 manifest 已冻结但尚未完成发布；
- `completed`：所有 C7 artifact 与 completion event 已闭合。

C2 Agent envelope 只包含 `territory_markdown` 与 `atoms[].markdown`。其中
Atom 的 `## Territory` 是给人和后续 Agent 阅读的自然语言语义，不承载内部
引用。C3 的 `CURRENT_ATOM_INDEX` 必须由 Controller 渲染为：

```text
## creative-atom-t01-01

Territory ref: creative-territory-01

<exact Atom Markdown>
```

Agent 不生成、猜测或从 `task_id` 推导 Territory/Atom 稳定 ID。

Creative contract v2/v3 的每个 run 还必须冻结 controller-owned
`SoftwareDemoPolicy`。Policy 至少精确包含：

```text
medium = software_first
ordinary_device_io = allowed
custom_hardware_or_fabrication = forbidden_as_core
manual_performance_or_installation = forbidden_as_core
real_end_to_end_demo = required
mock_or_wizard_of_oz_core = forbidden
```

### CLI

```text
hacksome run (CHALLENGE | --prompt TEXT) --route creative
  [--creative-brief TEXT | --creative-brief-file PATH]
  [--idea-memory auto|off]
  [Codex runtime options]

hacksome review RUN_DIR
  [--host HOST] [--public-host HOST] [--port PORT] [--no-open]

hacksome resume RUN_DIR

hacksome benchmark --route creative MANIFEST.json
hacksome benchmark --continue BENCH_DIR [--worksheet PATH]
```

Creative-only 参数必须使用 `argparse.SUPPRESS` 或等价机制，在 route dispatch
后注入默认值。Useful 显式传 Creative 参数、Creative 显式传 Useful fanout
参数，都必须在创建 run 前报错。

## 3. Contracts

### 3.1 Run 与状态

Creative 使用 Hub `schema_version=2` state，并持久化：

- `route.id=creative` 和 contract/prompt/stage/report policy version；
- Challenge、Creative Brief、Software Demo Policy、Idea Memory Snapshot 的 path/hash；
- 完整 settings/Codex config 及其 canonical hash；
- frozen Prompt/Schema resource manifest；
- `wait`、`terminal_error`、`secondary_errors`、`transition_seq`、
  `pending_records`、`result_artifact_ids`；
- 可选 immutable `finalization` pointer。

`open()` 只能从这些 hash-bound 数据恢复 settings、Codex config、Prompt
catalog 与 Memory Snapshot，不能采用当前 package 默认值替换旧 run 的冻结值。
冻结 Prompt 的版本只能是当前版本或代码显式 allowlist 的历史版本；加载后
继续报告 manifest 中的真实版本，未知版本、ID、web policy、路径或 hash 漂移
一律 fail closed。

新 run 必须使用 Creative `contract/prompt/stage/report policy version=3`。
v3 在 software-first v2 基础上增加 C1W；不能用 v3 resources 重解释已存在的
v1/v2 run。v1/v2 waiting run 必须继续使用自身冻结 resources 完成
`inspect/status/validate/review/resume`，不得补写 Policy、补跑 C1W/C4F 或
改写旧 C2/C3 Prompt bytes。v1 允许 `all_candidates_failed_hook`；v2/v3 只
允许 `all_candidates_failed_concept_screen`。未知或未在 allowlist 中的版本
fail closed。

所有语义验证入口都必须显式绑定该 run 持久化的 `contract_version` 与
`FrozenPromptCatalog[stage].schema_path`，包括 task executor 的首次校验和
workflow 发布前的 `_validate_completed_output` 二次校验。任何一个入口回退到
当前 package 默认 Schema，都会错误拒绝合法的 frozen v1/v2 resume 输出。

Package catalog 冻结前必须让每个输出 Schema 同时通过离线 JSON Schema
合法性检查与 `CodexRunner` 使用的 structured-output 子集预检，并复用同一个
validator；Catalog 中任一 Schema 不兼容时，在复制任何 Prompt/Schema 字节前
fail closed。`Draft202012Validator.check_schema()` 接受某个关键词，不代表
Codex structured output 接受它。此静态资源错误属于 run 创建错误，不能由
C1W 的 optional fail-open 转写为 `unavailable`，否则会掩盖“该 stage 永远
无法启动”的缺陷。

子集预检必须使用正向、上下文感知的 Schema keyword allowlist：`properties`
下的业务字段名和 `$defs` 下的 definition 名不是 keyword；出现在 Schema
位置且未显式支持的未来 keyword 必须返回准确 JSON path 并 fail closed。关键词
各自合法不代表组合合法：任何 Schema-position object 一旦包含 `$ref`，就必须
是只含 `$ref` 的 pure reference；`description` 等说明应放在被引用的 `$defs`
定义或 Prompt 中。`$ref` sibling 必须在本地返回该 object 的准确 JSON path，
不能等真实 Codex 请求返回 `invalid_json_schema` 才发现。
Catalog 对每个 Schema 只读取一次 bytes，预检与最终冻结必须使用同一份 exact
bytes，禁止“先读待复制 bytes、再按路径二次读取验证”的 TOCTOU。整个 Catalog
预检通过后才可在临时目录写入，并以一次目录发布产生 `resources/`；失败不能
留下半冻结目录，也不能覆盖既有有效目录。`load_frozen` 必须对 manifest hash
绑定的 exact Schema bytes 再做同源预检，使历史坏资源在 workflow 启动前失败，
而不是进入 C1W optional task lifecycle。

Structured-output Schema 只约束 Agent envelope 能用 Codex 支持的词汇表达的
形状；不能表达的领域不变量继续由 route semantic validator 持有。例如 C1W
`safety_flags` 不在 Schema 中使用 Codex 不支持的 `uniqueItems`，但 Python
validator 必须在 task 首次校验与发布前二次校验中拒绝规范化后重复的 flag。
Agent 返回值未通过 JSON Schema/语义校验仍是 task invalidation，不得误报为
Catalog 资源兼容错误。

### 3.2 Agent 隔离与循环上限

- 每个逻辑任务使用 fresh Codex Session；基础设施重试只恢复该任务自己的
  exact Session。
- C1/C2/C3/C4H/C4F/C5M Remix/C6A/C6B 必须读取 run 中同一 exact
  Software Demo Policy bytes/hash；自由文本 Brief 只能收紧体验方向，不能
  放宽该 Policy。C1 不因此暂停。
- v3 只有 C1W Cultural Signal Scan 与 C5W Novelty Scan 使用 web search；
  v1/v2 仍只有 C5W。C2/C3 在所有版本中都禁止联网。
- C0–C4、第一批 C3/C4 的 Prompt、parent refs 与 context 不得含 Idea Memory
  或历史 disposition。
- v3 的 C1W 必须在 C1 完成后、首个 C2 task 前恰好执行一次。它使用
  `as_of_utc=run.created_at` 的 30-day window；有发布时间用 `published_at`，
  无发布时间的 live trend surface 才允许
  `observed_at=as_of_utc`。Controller 完成时刻只写
  `retrieved_at_utc`。
- C1W 非 null `published_at/observed_at` 必须是带 seconds 与显式 `Z` 或数字
  offset 的完整 RFC3339，可包含 fractional seconds。日级来源必须由 Agent
  规范化为
  `YYYY-MM-DDT00:00:00Z` 并保持 `time_precision=day`；该 UTC midnight 是
  确定性 precision anchor，不是分钟级发布时间声明。分钟级时间没有明确时区
  时必须拒绝，Agent/Controller 不得猜测 UTC 或本地时区。`month/unknown`
  不得放宽 timestamp/timezone/window，也不允许补写缺失日期或时间。Controller
  只可把显式 offset 等价换算成 UTC；`observed_at` 必须与 supplied
  `as_of_utc` 文本完全相同。两字段在 Agent Schema 中引用同一 `$defs`
  pattern，Python lexical gate 必须使用同一 exact regex，再独立检查真实日历、
  timezone、互斥、day UTC-midnight、exact observed anchor 与 UTC window。
- 同一 canonical source URL 在整个 C1W `signals[]` 中最多出现一次，同 signal
  内与跨 signal 均不得复用；canonical key 忽略 host 大小写和 fragment。
  同 publisher 的不同 URL 合法，source count 不是 coverage 指标。该跨嵌套
  array 不变量无法由 Agent JSON Schema 表达，必须由 Python semantic validator
  使用全局 `seen_urls` fail closed；Controller 不得静默去重或把重复来源拆成
  多条 evidence。
- C1W Agent raw source 只能进入唯一
  `creative-cultural-signal-snapshot-r001`。Snapshot 状态严格区分
  `ready|partial|empty|unavailable`；unavailable 必须绑定 failed/invalidated
  optional task 与唯一 `optional_cultural_signal_stage_failed` event，不能用
  `no_signal_reason` 冒充成功搜索。C1W fail-open；C5W 仍 fatal。
- v3 每个 C2/C3 task 必须恰好引用一次 signal snapshot，并收到恰好一个按
  slot 确定性生成的 `CULTURAL_SIGNAL_PALETTE`。C2 上限为 2 inspire + 2 avoid，
  C3 为 2 inspire；empty/unavailable 仍注入同 shape 空 palette。
- Palette 只能包含 `signal_ref/kind/creative_role/abstract_pattern/
  creative_tension/participation_shape`，不得含 URL、title、publisher、
  platform、label、neutral summary、source evidence、surface marker、handle、
  hashtag、Markdown link 或 code fence。它只能作为可忽略灵感，不能作为
  demand、virality、novelty、feasibility、安全或质量证据。
- C5M 最多一次 Recall、八个 cue、两个 Remix challenger；challenger 不得递归
  Recall，仍须经过普通 C4H+C4F/C5W。
- 每个 Concept 的 budget 独立：C4 hook repair ≤1、C6A evidence revision
  恰好 1、C6C feedback revision ≤1。
- 每个 initial 或 repaired Concept revision 恰好启动两份 fresh C4H 与一份
  fresh C4F；三者互相看不到结果。三份 review 共享唯一 C4 repair budget，
  repaired revision 必须重新启动完整 fresh 2+1，只有三者全 pass 才继续。
- C4H 保留既有六维，并追加第七维具体、立即、可解释的 share
  trigger/artifact；非 pass 使用 `no_immediate_share_trigger`。
- C4F 固定维度/reason code：
  - `software_first_core` → `core_not_software_first`
  - `hardware_independence` → `requires_custom_hardware_or_fabrication`
  - `technical_demo_substance` → `core_is_manual_performance_or_installation`
  - `end_to_end_demo_path` → `no_runnable_end_to_end_demo_path`
  - `dependency_integrity` → `requires_unavailable_dependency_or_permission`
  - `hackathon_scope` → `not_buildable_within_hackathon_budget`
  - `core_proof` → `demo_does_not_prove_core_mechanism`
- 以上映射必须以显式 `dimension → reason_code` 对同时存在于代码常量、模型
  Prompt 与测试中；不能只给模型两个按顺序排列但未绑定的列表。reason code 是
  Controller 路由标签，不是模型可自由选择的诊断文案；细节写入 evidence。
- 明确定制硬件、实体制作、纯装置/人工核心或明确不可得依赖必须以
  `c4_software_demo_invalid` 终态淘汰，不得进入 C5W/C6；缺少可澄清细节应
  `repairable`，不能把不确定性伪装为 hard reject。普通设备内置 I/O 不能单独
  触发 hardware failure。
- C4 repair 与 C6A evidence revision 都必须逐字保留 source 的
  `Intended Reaction`、`Real Input, Transformation and Output`、
  `Parent Atoms` section body；Prompt 必须公开这条机械校验规则。局部时序、
  表达、风险或 demo 澄清只能写入其他允许变化的 section，不能靠改写核心
  输入/转换/输出来伪装成同一 Concept。
- C4R/C6A 可以澄清 runtime、依赖、Demo cut、现场证据与 share artifact，
  但不能把硬件/人工/装置核心替换成软件核心；这种变化必须作为未来的新
  Concept，而不是当前 revision。
- C6B 使用 categorical include/hold/exclude 与 controller round-robin；
  每个 curator 先逐项输出 `software_demo_strength`、
  `surprise_fun_or_intrigue`、`one_sentence_clarity`、
  `immediate_share_trigger`、`novel_combination` 的
  `pass|uncertain|fail` + evidence；全 pass 才 include、无 fail 且有
  uncertain 为 hold、任一 fail 为 exclude。不允许模型 1–10 打分、Top-K 排名
  或 curator 改写 primary territory。
- 当前 v4 的两个 C6B fresh Session 使用相同五维 Schema，但 Controller 按
  slot 注入不同、稳定的 `CURATOR_LENS`：slot 1
  `meaning_value_red_team` 排除需要策展说明、没有可解释产品循环/重复价值的
  空洞装置或一次性 AI 奇观；slot 2 `hackathon_floor_red_team` 排除观众不能在
  约 30 秒内亲手开始、看见软件反馈、愿意再试/拉人试玩的展厅概念。两者必须
  完整判断所有五维，lens 不能变成第六维、分数或新 decision 规则；artifact
  metadata 保存 `curator_lens_id`。
- C6B Controller 只能在 frozen `creative-portfolio-curate` template version
  为 v4 时注入 `CURATOR_LENS` 并记录对应 metadata；恢复 v2/v3 frozen run
  必须保持旧 block/metadata shape，不能把旧 curator 事后标记成执行过新 lens。
- C3 v5 在既有 sections 内要求 `User does:`、
  `Software immediately responds:`、`Why try or share again:` 与
  `Recognizable product grammar:`。六度人物关系路径与实时 Jam 搭档只作为
  静态质量形状校准，Prompt 明确禁止输出两者的表面题材；它们不作为当前 run
  的外部 evidence。v1/v2 的 C3 只读取 C0-C2 data blocks；v3 仍不读取 raw
  signal snapshot，只额外接收 Controller 从该 snapshot 投影的 safe palette。
  v5 还限制单篇 Concept 的篇幅，并要求返回前机械自检全部必需 H2、末尾
  `Parent Atoms` 与结构化 refs；它不能放宽 validator 或由 Controller 补写
  缺失正文。frozen C3 v4 继续按原字节加载。C6A v4 只能使用 C5W 已验证先例
  降低解释门槛，不能编造具体项目/URL 或把 Concept 改得更抽象。
- C3 v6 把四个默认 synthesizer 从可重叠的软 lens 改为稳定且互斥的
  product-loop responsibility，slot 顺序固定为：
  `explorer_simulator`、`realtime_partner`、`social_game_relay`、
  `creator_transformer`。分类轴是软件回应后的 primary next action：
  query/variable comparison、bounded-latency call-and-response、另一位真人
  改变 shared state、或用户对真实素材进行多步 edit/remix。视觉、题材、输入
  传感器、分享按钮、地图或收据本身不能改变分类；无法诚实满足 assigned
  grammar 时必须返回零 Concept。
- v6 Controller 的 `SYNTHESIS_LENS` block 只提供 exact stable
  `assigned_product_grammar_id` 与 label；详细 acceptance/exclusion 规则属于
  frozen v6 Prompt。每个输出在 `Why It Is Unexpected Yet Legible` 中恰好写
  一行 `Recognizable product grammar: <assigned-id> — <explanation>`。
  context-aware semantic validation 将 marker 与当前 task 的 expected ID
  fail closed 绑定；缺失、未知或错 slot 会 invalidated，不是 candidate reject。
  frozen C3 v2–v5 继续收到旧 `SYNTHESIS_LENS` 文本，不注入新 assignment，也
  不要求 marker；v5 加入显式 compatible template allowlist。任何尚未注册
  context semantics 的未来 C3 template version 必须 fail closed，不能静默退回
  legacy lens。C3 JSON Schema、十二个 H2、software-first product semantics、
  C2 与 C6B 均不改变。
- v3 当前 C3 template version 为 v7：继续使用 v6 的四种互斥 product grammar
  语义，同时由 Controller 增加 safe palette block 与 snapshot parent。C2
  template version 为 v3。C2/C3 旧模板文件本身不修改，v2 catalog 仍冻结 C2
  v2 / C3 v6 的真实旧字节且完全没有 palette block。
- C2 fanout 的 slot 在调用 Agent 前已确定，但内部 Territory ID 不注入 C2
  Prompt，也不要求 Atom Markdown 回显。Controller 发布 Atom 时必须同时绑定
  Atom ID、`source_refs=(territory_ref,)`、`metadata.territory_ref`、
  `territory_slot` 与 `atom_slot`；C3 只能从 Controller 生成的显式索引读取
  Atom→Territory 映射。
- 离线 validator 必须证明 Atom ID 中的 slot、metadata slot/ref、唯一
  Territory source ref 与实际 `creative_territory` artifact 一致。正文中出现
  或缺少 `creative-territory-*` 字符串都不能代替结构化谱系验证。
- v2 六个 C2 lens 必须全部 software-native；C3 Concept 必须包含
  `Software Core and Runtime`、`Share Trigger and Artifact` 与真实
  `Minimum Hackathon Demo`。C5W 只对完整 C4 screen pass 项运行，task 数必须
  与 pass 集相等，且 C5W 不输出 feasibility route decision。

### 3.3 C6 人工评审

非空 shortlist 发布 immutable `creative_human_review_batch`，写：

```json
{
  "kind": "creative_human_review",
  "round_id": "...",
  "round_artifact_id": "...",
  "round_sha256": "...",
  "batch_sha256": "...",
  "status": "open | closed",
  "resolution_id": null
}
```

Review 与 resolution 是 append-only JSONL：

- v2/v3 `ConceptReview` 必须保存
  `share_impulse=immediate|maybe|no` 与
  `demo_confidence=yes|maybe|no`；`immediate` 必须有非空
  `share_target`，两个字段进入 request/feedback fragment hash；
- reviewer ID 与 display name 分离；
- 同 request ID + 同 canonical request hash 幂等返回原 timestamp；
- 同 ID 不同内容冲突；
- supersede 只能指向同 reviewer/round 的 latest receipt；
- round 关闭后禁止新 review；
- resolution 对每个 shortlist revision 恰好给一个
  `keep|revise|reject|taste_veto|merge` action；
- revise/merge 只可注入明确批准且 hash 复核的 fragment 或 curator
  instruction；单任务最多 12 fragments / 24 KiB；
- close 只冻结 resolution 和 wait，不提前伪造 C6C terminal disposition。

普通 reviewer 首次提交前看不到 peer 原文，提交后只获得只读 team wall；
但可以看到原始 `Software Core and Runtime`、`Minimum Hackathon Demo` 与
`Share Trigger and Artifact`。机器 C4F verdict/evidence、Memory provenance、
merge、feedback approval、coverage override 与 close controls 只属于 curator
projection；curator 还看到每位 reviewer 的原始 `share_impulse` /
`demo_confidence`。这些字段只是人类信号，不自动重开 C4F，也不能声称真实
传播或 build success。人类自由文本始终是不可信数据。

### 3.4 Idea Memory

新 run 创建前按直接子目录稳定扫描，只接受：

- `completed`、离线验证通过的 Creative run；
- 受支持的 route/report/memory schema；
- `producer_kind=live`；
- artifact path/hash 与 Memory Record 内所有 source binding 一致。

Snapshot 自包含复制 capsule，受 run/entry/byte 上限约束。Snapshot 创建后不得
再次读取 source run。Memory Record 不得包含 reviewer/curator 身份、原始人工
评论、curator instruction 正文、Prompt、日志、Session ID 或绝对路径。

v2 Memory Record 必须把 software core/runtime、share trigger/artifact、
minimum demo 及七类 C4F reason/evidence 作为独立有界字段/caution 保留，不能
压成一个模糊的 Hook failure。旧硬件/装置 capsule 可以作为 `inspire|avoid`
抽象线索，但 Remix 仍受当前 run Policy 与完整 C4H+C4F 约束。

### 3.5 C7 成功报告

成功输出的逻辑发布顺序固定：

```text
creative-idea-report.md
creative-idea-report.json
0..N Idea Cards
Idea Card index
0..N Build handoffs
creative-memory-record.json
completed transition
```

报告必须包含完整 Candidate Fate Ledger、Idea Memory Used、
Memory-derived Branches；零 Idea 还包含 Zero-Idea Explanation。合法
`zero_reason_code` 只有：

```text
no_concepts_generated
all_candidates_failed_concept_screen
shortlist_empty
all_human_rejected
```

该列表属于 v2；v1 loader 仍只按冻结合同识别
`all_candidates_failed_hook`。非零 Idea 时必须为 `null`。每个 completed Concept revision 必须恰好一个
terminal disposition；指向 successor 或 Final Idea 的 `target_ref` 必须存在
且类型正确。

Final Idea Card 只有一个 H1，并恰好包含十二个非空 H2：

```text
Intended Reaction
One-sentence Hook
First Thirty Seconds
Audience Action
Core Mechanism
Reveal and Aftertaste
Minimum Hackathon Demo
Why Someone May Share It
Novelty and References
Human Signal
Risks and Unresolved Disagreement
Lineage
```

`Core Mechanism` 必须保留 software runtime 与真实端到端转换；
`Minimum Hackathon Demo` 必须保留最小 build cut/依赖/验收证据；
`Why Someone May Share It` 必须保留具体 share trigger/artifact。
`Human Signal` 必须包含可用的 retell/share target/share impulse/demo
confidence，同时声明它只是构想阶段代理信号，不得声称真实传播力或构建成功率。
Build handoff 是纯 JSON，不能 import Build runtime。它的
`challenge_markdown` 与 `initial_idea_card_markdown` 对齐 Build Stage 的
bootstrap 输入，但发布 handoff 不等于授权启动 Team。Build-side adapter 必须
复核 `idea_card_sha256`，并用至少
`source_run_id + idea_card_id + idea_card_sha256` 构造跨 run 身份；任何一侧
都不能 import 对方的私有 Python 类型。

### 3.6 两阶段 finalization

C7 renderer 不调用模型、网络、随机数或当前时间。Coordinator：

1. 在一致 snapshot 上绑定 state、四条 ledger head 与所有 hash-bound source；
2. 预分配 artifact/event/completion ID 与唯一持久化时间；
3. 写 exact staged bytes；
4. 原子写 canonical manifest；
5. 绑定 run pointer；
6. 按 manifest 顺序 publish/adopt；
7. 最后一次原子状态变更才设置 `completed` 与 `result_artifact_ids`。

manifest 后中断保持 `running + creative-finalization`，`resume` 只能
`replay()`；不得重新 render 或调用 Agent。字节、source 或 ledger prefix
篡改必须 fail closed。

### 3.7 Failed partial

fatal run 保持 `failed`，保存第一条 immutable `terminal_error`，并尽力发布：

```text
creative-partial-report.md
creative-partial-report.json
```

partial 只记录失败前已持久化的 task/artifact/decision/ref，不生成有效
Idea Card、handoff、Memory Record、completion event 或 result IDs。manifest
后发现篡改时允许保留 manifest 与已发布的 exact plan prefix 供审计，但它们
不属于 `result_artifact_ids`，inspect 必须标记为不可恢复失败。

### 3.8 Software-first / Viral Benchmark

Benchmark 不得只统计 shortlist 数。自动指标至少包含：

- C3 software-first/端到端 Demo path 合格率；
- C4F verdict 与七类 reason 分布；
- 定制硬件、纯装置、mock/预录的 false-pass；
- 合法 browser/phone/built-in I/O 的 false-reject；
- 完整 C4 screen 后的 C5W task/token/wall-time；
- Memory challenger C4F 通过率与旧硬件模式再引入率；
- C6B `immediate_share_trigger=pass` 占比。

人工指标至少包含 30 秒 retell、具体 share target、
`share_impulse=immediate|maybe|no`、是否想亲自打开/操作、
`demo_confidence=yes|maybe|no` 与 pairwise 立即分享偏好。报告必须把后两者
标为 Idea 阶段代理信号。离线 fixture 必须覆盖 software/WebSocket 正例、
普通设备 camera/mic 正例、custom hardware、pure installation、mock/预录、
不可得权限、可修复缺信息和可运行但无 share trigger 的反例。

## 4. Validation & Error Matrix

| 条件 | 必需行为 |
| --- | --- |
| Challenge 为空或 Brief 参数冲突 | 创建 run 前报错 |
| Useful 传 Creative option，或反向 | 创建 run 前报错 |
| frozen config/resource/snapshot hash 漂移 | fatal + partial；不调用下一 Agent |
| v2 Software Demo Policy 缺失/hash 漂移，或允许阶段使用不同 bytes | fatal + partial；不调用下一 Agent |
| Atom ID、metadata、source refs 或 Territory artifact 不一致 | 离线 validation 失败；不得依赖 Markdown 子串修复或放行 |
| C3 缺 software runtime、share trigger 或可执行 Demo section | task invalidated + partial；不是 candidate reject |
| C3 v6/v7 缺少 exact grammar marker，或 marker 与 assigned slot 不同 | task invalidated + partial；不得改写 marker、换 slot 或把它当零候选 |
| C4F 明确定制硬件/实体制作/纯装置或不可得依赖 invalid | terminal `c4_software_demo_invalid` + 维度 reason/evidence；0 个后续 C5W/C6 task |
| C4H/C4F 有可修复缺口 | 共用一次 C4R；对 repaired revision 重跑 fresh 2+1 |
| repaired revision 任一 C4H/C4F 非 pass | `c4_unresolved_after_repair` 终态淘汰 |
| C4R/C6A 改写三个不可变 source section 任一项 | semantic validation 失败并产出 partial；Prompt 必须事先列出不可变 section |
| C5M optional task 失败 | 写匹配 diagnostic；保留成功 sibling；继续 base |
| C5W/其他 fatal task 失败 | run failed + partial，不能伪装“无先例/空候选” |
| v2/v3 base 与 challenger 均无完整 C4 screen pass | 空 batch + `all_candidates_failed_concept_screen`，直接 C7 |
| v1 frozen run 使用旧 zero reason/review shape | 按 v1 loader/validator；不迁移、不补 C4F |
| v1 task 首次校验使用 frozen schema、二次校验回退 package v2 schema | 契约错误；两次都必须绑定 persisted contract + frozen stage schema |
| C6B shortlist 为空 | 空 batch + `shortlist_empty`，直接 C7 |
| review hash/round 过期 | HTTP 409；不写 ledger |
| `share_impulse=immediate` 且 share target 为空 | HTTP 4xx；不写 ledger |
| coverage 不足且无显式 override reason | resolution 拒绝 |
| open round 执行 resume | 非零、零业务写入 |
| Useful run 执行 resume | 非零、目录字节不变 |
| closed C6 wait | C6C 一次，然后 C7 |
| frozen C7 plan | 只重放 exact manifest |
| C7 manifest 前 render/stage 失败 | failed + partial |
| manifest 后普通中断 | finalizing，可 resume |
| staged/published/source/ledger 篡改 | failed + partial；result IDs 为空 |
| partial render 失败 | 保留首因，追加 secondary error |

## 5. Good / Base / Bad Cases

- Good：base Concept 先独立生成；C5M 从冻结历史生成一个机制变换 challenger；
  二者用相同 C4H+C4F/C5W 标准，最终报告披露来源和变化。
- Good：普通手机摄像头驱动实时 Web transformation，浏览器产生可录屏结果；
  没有额外设备，因此 C4F 可 pass。
- Good：同一 C6A portfolio 的两个 C6B task 分别收到 Meaning/Value 与
  Hackathon Floor lens；两者仍输出完全相同的五维 shape，Controller 只按既有
  categorical decision 聚合。
- Good：当前 v3 的 C3 v7 slot 2 收到 `realtime_partner` 与一个不含来源表面
  信息的 safe palette，输出的核心价值依赖本轮结束前的软件回应，并使用 exact
  marker；slot 2 没有合适 Atom 时返回空集合，而不是把批处理可视化改名为
  realtime。frozen Creative v2 仍按 C3 v6 运行且没有 palette。
- Good：C2 Atom 用自然语言说明“仪式化暂停”所属的创意空间；Controller 在
  C3 索引中另行给出 `creative-atom-t01-01 → creative-territory-01`。
- Good：两位 reviewer 独立复述，Percy 只批准一个相关 fragment；C6C Prompt
  不含未批准评论，报告仍完整审计所有 receipt ref。
- Base：没有历史、`--idea-memory off` 或所有 Concept 被淘汰；流程仍确定性
  完成并写零 Idea 报告与可供未来使用的失败经验。
- Base：manifest 发布到一半进程退出；下一次 resume 不调用 renderer，最终
  bytes/ID/timestamp 与 manifest 完全一致。
- Base：v1 waiting run 在 package 升级后仍用 frozen v1 schema 打开页面和
  resume；它不获得新 C4F，也不被标成 v2 benchmark 结果。
- Bad：C3 Prompt 含旧 Idea Card 或 Memory cue；测试必须失败。
- Bad：测试 runner 根据不可见的 `task_id` 给 C2 Markdown 偷塞
  `creative-territory-01`，从而掩盖真实 Prompt 没有提供的后置条件。
- Bad：把 missing/failed Agent task 当成 `candidates=[]`；必须 failed。
- Bad：椅子/卡片/主持人完成核心体验，软件只计时或播放声音，却因为“设备都
  能拿到”通过；必须以 `core_is_manual_performance_or_installation` 淘汰。
- Bad：要求 Arduino/机器人/专用传感器，并在 C6 交给 Percy 人肉判断；必须在
  C4F 前置淘汰。
- Bad：用 1–10 总分选 Top-K，再让人工只确认；这违反 C6 categorical +
  human curation 合同。
- Bad：两个 curator 只换 task ID 却收到相同审查角色，或 Meaning/Value
  reviewer 只输出“是否有意义”而跳过五维；测试必须失败。
- Bad：四个 C3 task 都产出“输入遥测 → 抽象地图/收据 → 分享链接”，仅用不同
  grammar label 包装；错 marker 必须由 v6 validator 拒绝，语义近似仍由 C6B
  反证，Controller 不得因为四个 ID 都出现就强制 include。
- Bad：完成状态缺 terminal disposition、report、Memory Record 或 exact
  finalization/result binding；离线 validation 必须失败。

## 6. Tests Required

默认质量门必须离线，不调用 Codex 或网络，并断言：

- C0–C6 Prompt allowlist、fresh sessions、web policy、稳定 fanout ID；
- v3 C1W 单次时序、四态 snapshot、source/time/URL 规则、optional diagnostic
  closure；只有 C1W/C5W 联网，C5W failure 仍 fatal；
- C1W 同 URL 在单 signal、跨 signal 与 canonical-equivalent fragment 形状都
  semantic reject；Schema 仍可接受该跨数组形状，同 publisher 不同 URL 通过；
- v1/v2/v3 package catalog 与真实 frozen Schema 字节全部通过运行器同源的
  Codex structured-output compatibility validator；人工把 `uniqueItems`
  加回 C1W Schema 或给 `$ref` 加 `description` sibling 时必须在 freeze
  写入前失败，而 pure `$ref` + `$defs` 合法；重复 `safety_flags` 继续由
  Python semantic validator 拒绝；
- C2/C3 snapshot parent 与 safe palette block 恰好一次、slot round-robin
  确定性、empty/unavailable shape、raw URL/title/label/evidence/marker 泄漏
  fail closed；v1/v2 无 C1W task/artifact/block；
- report 披露 snapshot ref/hash/status/window/count，而 Memory Record 不复制
  raw trend；snapshot/palette/hash/version/parent 任一篡改 fail closed；
- Software Demo Policy 在 C1/C2/C3/C4H/C4F/C5M Remix/C6A/C6B 使用同一
  exact bytes/hash；v2 C2 lens 不含纯 spatial/performance/cross-media 目标；
- C3 v7（继承 v6 语义）与 C6A/C6B v4 的 plain-language marker、正例禁复制、
  C5W 先例边界；C3 v7 还需断言四个 stable grammar assignment 按 slot
  一一分配、hard-role
  与 zero-output 规则、map/receipt 边界、exact marker/expected-ID
  invalidation、十二个 H2、末尾 `Parent Atoms`、ref 自检与 frozen v5 兼容；
  frozen v2–v5 继续使用旧 lens block 且不要求新 marker；
  C4F v4 必须从 `SOFTWARE_DEMO_REASON_BY_DIMENSION` 逐对断言 Prompt 显式
  映射，并兼容 frozen v3；两个
  `CURATOR_LENS` ID/正文互不相同、artifact metadata 记录 lens，五维 Schema
  与 mechanical decision 不变；v2/v3 frozen Prompt 仍可加载，且 C6B 不注入
  v4-only lens block/metadata；
- C3 缺 software runtime、share trigger 或 executable demo 时 invalidated；
- C2 fixture 使用不含内部 ID 的自然语言 `Territory`；C3 Prompt 显式包含
  Controller 生成的 Atom→Territory 映射；篡改 Atom ID、metadata ref/slot、
  source refs 或目标 artifact 任一项时 route validation 必须失败；
- C4H 七维 + C4F 七维 schema/reason/aggregation matrix、fresh 2+1、三类
  revision budget、disposition reason/evidence/target 闭包；
- software/WebSocket 与 built-in camera/mic 正例；custom hardware、pure
  installation、mock/预录、不可得权限反例；缺 Demo cut repair 一次；
- Memory off/empty/auto、source exclusion、snapshot cap/hash、Recall/Remix
  optional failure 与禁止递归；
- v2 空 batch 三类原因和人工全拒绝第四类原因；v1 legacy zero reason 分版本；
- review request 幂等、Unicode、supersede、pre/post reveal、role projection、
  `share_impulse`/`demo_confidence` enum/hash/immediate target、coverage、merge
  与 approved fragment budget；
- C6C keep/revise/reject/taste-veto/merge、重复 resume 与失败前不写伪终态；
- report exact bytes、十二个 H2、零/非零、隐私、Memory Record 分类与 handoff；
- finalization 在 stage/manifest/publish/event/completion 每个边界的 crash
  replay，以及 tamper fail-closed；
- failed partial 不暴露 result；
- Useful CLI golden 与 route behavior 不变；
- benchmark 两种 comparison、shared snapshot/no leakage、blind mapping、
  0/1/N Idea worksheet、software false-pass/false-reject、C5W cost、
  share impulse/demo confidence 和 live/fixture 指标边界；
- v1/v2 waiting run 继续 inspect/review/resume，资源/receipt/zero reason
  不被 v3 重解释；回归必须实际触发至少一个 C6C Agent 输出的首次与二次语义
  校验；新 v3 run 不加载旧 template bytes 冒充当前版本。
- `tests/docs/test_creative_workflow_explorer.py` 断言流程投影节点完整、所有
  Prompt/Schema/代码路径存在、C6 Human/C7 不伪造 Prompt、指定真实 run 的
  数量与 C1W invalidation 诊断没有漂移，并保留键盘、无脚本与 reduced-motion
  契约。

执行：

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy src
.venv/bin/python -m compileall -q src tests
CODEX_HOME=/private/tmp/hacksome-test-codex-home \
  .venv/bin/python -m unittest discover -s tests -v
git diff --check
```

## 7. Wrong vs Correct

### 错误：从当前 package 默认值恢复旧 run

```python
workflow = CreativeIdeaWorkflow(
    RunHub(run_dir),
    CodexRunner(CodexConfig()),
    settings=CreativeWorkflowSettings(),
)
```

### 正确：恢复 hash-bound frozen contract

```python
workflow = CreativeIdeaWorkflow.open(run_dir)
outcome = await workflow.resume()
```

### 错误：C7 中断后重新渲染

```python
bundle = render_success_report(build_report_projection(run_dir))
coordinator.finalize(bundle.outputs)
```

### 正确：存在 manifest 时只重放

```python
FinalizationCoordinator(RunHub(run_dir)).replay()
```

### 错误：把全部人工反馈塞给 Agent

```python
context = json.dumps(all_human_reviews)
```

### 正确：只注入 resolution 明确批准且复核 hash 的 fragments

```python
fragments = {
    fragment.feedback_ref: fragment
    for fragment in store.feedback_fragments()
}
approved = [
    fragments[feedback_ref]
    for feedback_ref in resolution.approved_feedback_refs
]
verify_fragment_hashes(approved)
```

### 错误：用模型正文承担 Controller 谱系

```python
if expected_territory_ref not in section_body(atom_markdown, "Territory"):
    raise CreativeArtifactError("missing Territory ref")
```

### 正确：结构化绑定，并给下游显式索引

```python
hub.publish_artifact(
    artifact_id=atom_id(territory_slot, atom_slot),
    source_refs=(territory_ref,),
    metadata={
        "territory_ref": territory_ref,
        "territory_slot": territory_slot,
        "atom_slot": atom_slot,
    },
)
atom_index = render_atom_index(hub, atom_refs)
```

### 错误：只给 C3 四个可重叠的审美强调

```python
SYNTHESIS_LENSES = (
    "make it legible",
    "make it surprising",
    "make it shareable",
    "make hidden state visible",
)
```

### 正确：稳定 slot 绑定互斥的 primary product loop

```python
SYNTHESIS_LENSES = (
    ("explorer_simulator", "Explorer / Simulator"),
    ("realtime_partner", "Realtime Partner"),
    ("social_game_relay", "Social Game / Relay"),
    ("creator_transformer", "Creator / Transformer"),
)
# v6 output marker is validated against the assigned ID.
# Frozen v2-v5 continue using their exact legacy lens bytes.
```

### 错误：把“用了电脑”当作 software-first

```python
if concept_mentions_laptop:
    feasibility = "pass"
```

### 正确：检查核心因果和真实端到端路径

```python
feasibility = review_software_demo(
    policy=frozen_software_demo_policy,
    concept=exact_concept_revision,
)
# 手机内置 camera + 实时 Web transformation 可以通过；
# 主持人/卡片完成核心、电脑只计时必须淘汰。
```
