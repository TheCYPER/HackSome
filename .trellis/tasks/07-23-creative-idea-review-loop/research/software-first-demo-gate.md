# Research: Creative route 的 software-first、可运行 Demo 与传播性筛选

- Query: 针对用户的新要求，研究当前 Creative workflow 应如何用最小但完整的契约调整，优先生成可在黑客松期间跑起来的软件 Demo，自动淘汰硬件依赖和纯装置/表演艺术，同时保留惊喜、好玩、一句话可复述和强转发冲动。
- Scope: internal
- Date: 2026-07-24

## Findings

### 1. 结论摘要

建议不要新增第二个人工关卡，也不要把可实现性留到 C6 让 Percy 人肉兜底。最小而完整的调整是：

1. C1 固化一份 Controller-owned、可见且随 run 冻结的 `Software Demo Policy`，把 software-first 变成路线约束，而不是一次 Prompt 中可被模型稀释的偏好。
2. C2 把会主动引向装置/表演的默认 Territory lens 改成 software-native lens；仍然探索惊喜、反转、社交和神秘，但媒介必须落到浏览器、手机、桌面、CLI、服务端或普通设备内置 I/O。
3. C3 在 Concept 中显式写出 `Software Core and Runtime`、`Share Trigger and Artifact`，并把 `Minimum Hackathon Demo` 收紧成可执行的真实 input → code/model/API transformation → visible output。
4. 在 C4 内增加一个独立的自动子关卡 `C4F Software Demo Feasibility Review`。它与现有两份 Hook Review 互相独立，运行在昂贵的 C5W 之前；三份审查共享现有“最多一次 C4 局部修复”预算，不新增无界循环。
5. C5W 继续只负责先例/陈词滥调证据，不承担可实现性判决；Memory challenger 必须重新通过 C4 Hook + C4F。
6. C6B 把 shortlist 的自动标准明确为“软件 Demo 已过硬门槛 + 有趣/惊喜 + 明确分享触发”，仍使用 categorical verdict，不用 1–10 分。
7. C6 页面增加 `share_impulse` 和 `demo_confidence` 两个轻量人工信号，并展示原始软件 Demo 路径；普通 reviewer 不先看到机器 feasibility verdict，Percy curator 才看到完整审查证据。

这里把用户所说“硬件/纯装置艺术先 pass 掉”解释为“跳过、淘汰”，不是“判定通过”。上下文支持这个解释，但这是一个需要在最终设计说明中明确写出的语言边界。

### 1.1 真实 v2 smoke 的增量发现

2026-07-24 的真实 v2 smoke 证明第一轮调整方向有效，但 gate 强度仍不足：

- C2/C3 产物已经从椅子、卡片、主持人和装置，转为浏览器、Canvas、Web Audio、
  camera/mic、WebSocket 和可分享 URL 等软件核心；software-native generation
  本身成功。
- 首批 12 个 Concept 的 C4F 却全部 `pass`。其中仍能看到多子系统/多设备、
  浏览器权限与兼容性、模型或实时链路、预置房间/数据、手工录屏传播等实现风险。
  这说明当前 reviewer 主要在检查“是否用了软件、有没有写 input→transform→output”，
  还没有保守地判断“两人一天是否能稳定跑出第一版 Demo”。
- “使用标准 Web API”不等于目标浏览器中的权限、secure context、user gesture、
  性能、输入质量和失败恢复已经成立；“可录屏”也不等于用户愿意立刻开始录屏、
  裁剪、上传并补充解释。
- 因此下一步不是再加人工关卡，也不是更改 v2 Schema，而是收紧 C3/C4H/C4F/C6B
  Prompt：让同一组 categorical 字段和 reason code 同时审查冷启动、预算、风险、
  降级、预置状态、真实分享摩擦和跨候选机制同质化。

这是一条阶段性 smoke 学习，不是 Build benchmark。它证明了“软件化成功”和
“可交付性 gate 仍偏松”，不能证明这些 Idea 最终不能实现，也不能把自动 reviewer
的信心当成真实 build success。

### 2. 当前流程为什么会稳定地产出“过度 creative”的结果

#### 2.1 C1 只要求诚实可得，没有要求软件是核心

当前默认 Brief 只要求使用团队能获得和演示的媒介、数据、权限与能力：

- `src/hacksome/creative/contracts.py:79-82`

这意味着椅子、卡片、主持人、投影、现场合唱只要“能拿到”，都满足现有边界。现有 C1 Prompt 也只是规范化输入，不包含 software-first 的不可丢失政策：

- `src/hacksome/prompts/creative/creative-brief-normalize.md:1-18`
- `.trellis/tasks/07-23-creative-idea-review-loop/design.md:713-732`

因此，仅在下一次 CLI 里临时写一句“偏软件”不够：模型仍可能把它当作审美偏好，而不是硬路线约束。

#### 2.2 两个默认 Territory lens 明确鼓励装置/表演方向

当前六个默认 lens 中有：

- `Sensory, spatial, temporal, or embodied experience`
- `Wildcard: poetic, absurd, or cross-media combinations`

见 `src/hacksome/creative/contracts.py:49-56`。

这与 smoke run 中“椅子、卡片、空位、合唱、影子、现场参与者”收敛高度一致。真实报告也已经记录：

- shortlist 整体更接近诗性参与艺术，技术 wow-factor 偏低；
- 多数体验依赖主持人、多人和预置卡片；
- `src` 测试 fixture 甚至把 “A sensor, a laptop, and one projected response” 当作标准最小 Demo。

证据：

- `.trellis/tasks/07-23-creative-idea-review-loop/smoke-test-report.md:50-85`
- `tests/test_creative_workflow.py:50-81`

#### 2.3 C3 只有一个自由文本 Demo 段，不能支撑严格的技术审查

Concept 目前只要求 `Minimum Hackathon Demo`，没有要求明确写出：

- 软件运行表面；
- 真实输入和取得方式；
- 哪段代码、模型或协议执行核心转换；
- 真实输出；
- 外部依赖/权限；
- 在比赛团队和时间约束内的最小 cut；
- Demo 如何证明核心机制不是 mock、主持人代劳或装置布景。

相关代码：

- `src/hacksome/creative/artifacts.py:72-83`
- `src/hacksome/prompts/creative/creative-concept-synthesize.md:13-24`
- `.trellis/tasks/07-23-creative-idea-review-loop/design.md:773-788`

Semantic validator 只验证这些 H2 存在和谱系一致，不验证 Demo 是否 software-first：

- `src/hacksome/creative/artifacts.py:342-384`

#### 2.4 C4 的 `capability_integrity` 太宽，装置/人工表演仍可通过

当前 C4 六项只检查可理解、预期反转、机制、30 秒、一句话复述、隐藏人工/不可能能力：

- `src/hacksome/creative/artifacts.py:122-140`
- `src/hacksome/prompts/creative/creative-cheap-hook-review.md:7-30`
- `.trellis/tasks/07-23-creative-idea-review-loop/design.md:796-838`

它没有单独判断：

- 软件是不是主要价值载体；
- 是否依赖定制硬件/搭建设备；
- 核心变化究竟由代码完成还是由主持人、参与者和道具完成；
- 是否有可运行的端到端技术路径；
- 依赖和权限是否在比赛期间真实可得；
- Demo 是否能证明核心技术机制。

控制器当前只在两份 Hook Review 都 `pass` 时放行：

- `src/hacksome/creative/workflow.py:1775-1835`

真实 run 的 12 个 Concept 全部 Hook-pass，证明现有 gate 对“低技术但诗性成立”的概念没有辨别力：

- `.trellis/tasks/07-23-creative-idea-review-loop/smoke-test-report.md:5-15`

#### 2.5 C5 与 C6 也不会自动补上这条硬门槛

C5W 明确是证据而不是 pass/reject gate：

- `src/hacksome/prompts/creative/creative-novelty-scan.md:22-24`
- `src/hacksome/creative/workflow.py:2575-2613`

C6B 的 Prompt 只要求 `include|hold|exclude`，没有列出 software/demo/viral 的判定维度：

- `src/hacksome/prompts/creative/creative-portfolio-curate.md:1-12`
- `src/hacksome/creative/workflow.py:1048-1178`

所以两个 curator 可以一致偏爱“艺术上成立”的 Concept。当前 deterministic shortlist 只能保证批准票层级和 Territory metadata 多样性，不能保证技术 Demo 或传播性：

- `.trellis/tasks/07-23-creative-idea-review-loop/design.md:1067-1106`

### 3. 推荐的边界定义

#### 3.1 `software-first` 的推荐定义

一个 Concept 只有在以下条件都成立时才是 software-first：

- 核心体验或结果由可执行软件产生，而不是由主持人、演员、参与者协商、实体道具或舞台布置产生；
- 核心 Demo 可以在普通开发设备上运行：浏览器、手机、桌面程序、CLI、服务端或本地/云模型；
- 普通设备已有的屏幕、键盘、触控、摄像头、麦克风、扬声器、加速度计可以使用，但不能要求焊接、定制电子元件、Arduino/机器人、专用传感器、实体制作或现场设备校准；
- 投影仪/显示器可以只是展示出口，不能是 Concept 成立的核心装置；
- 必须存在真实 input → executable software transformation → observable output 的端到端路径；
- 核心路径不能依赖 wizard-of-oz、手工整理、假数据、未取得的私有数据、不可用 API 权限或模型不具备的能力。

#### 3.2 “纯装置/表演艺术”的推荐判定

不按“是否发生在线下空间”判断，而按核心因果判断：

- 如果去掉主持人、演员、卡片、椅子、舞台规则或参与者之间的人工配合后，软件没有独立完成可观察转换，则属于 `core_is_manual_performance_or_installation`，自动淘汰。
- 如果体验在线下发生，但浏览器/手机/服务端软件真实读取输入、执行机制并产生可验证输出，则仍可通过。例如普通手机摄像头驱动一个实时多人 Web 体验，不因使用摄像头或投屏自动判为硬件。

这能避免把有趣的 software-native interaction 一并误杀。

#### 3.3 “能跑出 Demo”的推荐定义

不是要求生产级完成，也不是 Useful 路线的长期商业可用性。通过条件应是：

- `Minimum Hackathon Demo` 指出运行入口和实际操作步骤；
- 从观众打开真实入口开始，permission、首个输入、room join/device pairing 和
  warm-up 均计入约 30 秒冷启动路径；不能从预置好的 reveal 前一秒开始计时；
- 使用真实可得输入；
- 核心转换由实现中的代码/模型/API/协议完成；
- 输出可以现场观察、录屏或由评委亲手操作；
- 依赖和权限在 C0 的团队/时间/比赛约束内可获得；
- C0 未写资源时，按最多 2 人/24 小时、一个简单 backend、一个主要浏览器/设备
  切片和最多三个关键路径子系统评估，而不是默认完整产品团队；
- 明确唯一最高风险技术假设、可在开工前两小时证伪的 probe、失败后的降级切片，
  以及账号/权限/种子数据/预热/配对/预录/人工动作等预置状态成本；
- 最小 cut 能证明 Concept 的 surprise mechanism，而不只是展示预录视频、Figma、文案或模拟输出。

Useful Red Team 中“重建真实输入、权限、产品动作和具体变化”的做法可借用，但不要把 Useful 的“比赛后重复使用/商业价值”带入 Creative：

- `.trellis/spec/backend/agent-workflow-contracts.md:262-288`

### 4. 阶段级契约调整

| 阶段 | 调整 | 是否 gate |
| --- | --- | --- |
| C1 | 冻结并展示 `Software Demo Policy`；加入 software-first、普通设备边界、硬件/装置反目标、真实 Demo 定义 | 不是人工 gate；是后续硬约束 |
| C2 | 将默认 lens 改成 software-native；Atom 必须说明软件机制/运行表面/最小技术证明 | 生成约束 |
| C3 | 增加软件核心、分享触发和可执行 Demo 信息 | 输出完整性 gate |
| C4H | 保留现有两份 Hook Review，并增加明确 `share_trigger` 维度 | 自动 Hook gate |
| C4F | 新增独立 Software Demo Feasibility Review；在 C5W 前运行 | 自动绝对 gate |
| C5M | 历史 cue 仍可抽象借用；challenger 必须走同一 C4H+C4F | 不新增 gate |
| C5W | 继续查 novelty/cliché，不负责 feasibility | 证据，不 gate |
| C6A | 接收 Hook + Feasibility + Novelty + Memory 证据，最多一次现有 evidence revision | 有界修订 |
| C6B | 只从已通过 C4F 的池子里，以 software demo strength、surprise/fun、share trigger、novel combination 做 categorical shortlist | 自动 shortlist |
| C6 Human | 增加 share impulse/demo confidence 信号；Percy 保持唯一人工决策权 | 唯一人工 gate |
| C7/Memory | 报告和 Memory Record 区分 Hook 失败与 software/demo 失败 | 确定性记录 |

### 5. C1/C2/C3 的具体建议

#### 5.1 C1：Controller-owned policy，不能只靠默认文案

建议持久化一个可见、随 resources 一起 hash/freeze 的 policy block，例如：

```text
medium = software_first
ordinary_device_io = allowed
custom_hardware_or_fabrication = forbidden_as_core
manual_performance_or_installation = forbidden_as_core
real_end_to_end_demo = required
mock_or_wizard_of_oz_core = forbidden
```

它至少进入 C1、C2、C3、C4H、C4F、C5M Remix、C6A、C6B Prompt context。C1 可以把它渲染到新增的 `## Software and Demo Boundaries`，但模型输出不能成为唯一事实来源；Controller policy 才是权威值。

不要增加 C1 人工暂停。用户的这次决定就是默认政策，Percy 仍可通过显式 Brief 收紧体验方向，但不能在一次 run 中偷偷放宽硬件/装置禁令；以后真要支持 hardware track，应新增显式 route policy，而不是自由文本覆盖。

#### 5.2 C2：替换两个高风险 lens

推荐的六个方向仍保持创意多样性，但全部 software-native：

1. `Direct manipulation and unusual software interaction`
2. `Reversal, reveal, and expectation shifts in a runnable interface`
3. `Multiplayer, collaboration, and social propagation`
4. `Mystery narratives built from software-visible hidden state`
5. `Camera, microphone, text, code, time, or live-data transformation using ordinary device I/O`
6. `Viral remix, replay, or shareable artifact generated by a technical mechanism`

Atom 的 `Mechanism` 必须说清软件做什么；`Challenge Fit and Risks` 必须指出运行表面、依赖和最小技术证明。可以新增 `Software Surface and Demo Proof` H2；若为了减小 Markdown 迁移，也可把它作为现有两个 section 的强语义要求，但独立 H2 更容易被 reviewer 和 UI 稳定读取。

#### 5.3 C3：新增两个必需 H2，并收紧 Demo section

建议在现有 Concept H2 中增加：

- `Software Core and Runtime`
- `Share Trigger and Artifact`

其中：

- `Software Core and Runtime`：运行入口、主要代码/模型/API/协议、真实 input、核心 transformation、observable output、外部依赖。
- `Share Trigger and Artifact`：观众为什么会立刻发、发什么（URL、录屏、结果、挑战、remix）、可能发给哪类具体的人；不能只写“很 viral”。
- `Minimum Hackathon Demo`：团队时间内的最小 build cut、现场步骤、真实依赖、最难技术点和验收证据。

当前 `Real Input, Transformation and Output` 继续作为 Concept identity 的不可变核心。C4 repair 可以澄清 runtime、Demo cut 和 share artifact，但不能把原先的实体/人工核心改写成软件核心后冒充同一个 Concept。

### 6. C4F 自动 gate 的推荐合同

#### 6.1 为什么放在 C4，而不是 C5/C6

- C4 本来就是“投入联网和人工成本前”的廉价筛选，位置语义正确。
- 真实 run 的 C5W 占总 input token 约 72.4%；在它之前淘汰硬件/装置方案能直接避免昂贵搜索：
  - `.trellis/tasks/07-23-creative-idea-review-loop/smoke-test-report.md:87-98`
- 放到 C6 才处理会让 C5W、C6A、C6B 都浪费在不可能入选的 Concept 上，也会再次让人工评审被看得过重。

#### 6.2 新增 substage，而不是把全部问题塞进现有 Hook Reviewer

建议新增：

```text
creative-software-demo-review
```

逻辑编号为 C4F，仍属于 C4 自动 screen。默认每个 exact Concept revision 启动一个 fresh Session；它不看 sibling、history、memory、novelty 或其他 reviewer 结果，不联网。它与两份 C4H Hook Review可以并发执行。

单 reviewer 是“最小”选择。为了降低误杀：

- `invalid` 只用于 Concept 原文明确证明的硬失败；
- 缺信息或可通过缩小 Demo cut 澄清的情况必须是 `repairable`；
- evidence 必须引用 Concept 原文；
- 后续 benchmark 专门统计 false pass/false reject。如果误杀率不可接受，再把默认 reviewer 数从 1 增到 2，而不是现在先复制全部成本。

#### 6.3 Feasibility dimensions 与稳定原因码

建议固定以下顺序：

| Dimension | 通过含义 | 非通过 reason code |
| --- | --- | --- |
| `software_first_core` | 核心体验由可执行软件产生 | `core_not_software_first` |
| `hardware_independence` | 不依赖定制硬件、制作、专用传感器或设备搭建 | `requires_custom_hardware_or_fabrication` |
| `technical_demo_substance` | 不是主持人/演员/道具完成核心因果 | `core_is_manual_performance_or_installation` |
| `end_to_end_demo_path` | 真实 input → software transformation → observable output 完整 | `no_runnable_end_to_end_demo_path` |
| `dependency_integrity` | 数据、API、模型、权限和服务真实可得 | `requires_unavailable_dependency_or_permission` |
| `hackathon_scope` | 最小 cut 在 C0 团队/时间约束内可建 | `not_buildable_within_hackathon_budget` |
| `core_proof` | Demo 真正证明核心机制，不是 mock/wizard-of-oz/预录替代 | `demo_does_not_prove_core_mechanism` |

输出继续使用 `pass|repairable|invalid` 和逐维 `pass|uncertain|fail`，避免模型数值评分。

Smoke 后需要把这七维从“合规清单”收紧为“合规 + 保守可交付”：

- `end_to_end_demo_path` 同时检查从真实冷启动到首个有效输出的步骤，而不是只看
  Concept 是否出现 input/transformation/output 三个名词；
- `hackathon_scope` 检查关键路径子系统数量、一个 backend/一个主要 device slice
  的参考边界、最高风险假设、两小时 probe、降级切片和预置状态成本；
- `dependency_integrity` 不接受标准 Web API/SDK 名称作为 pass evidence，必须
  有目标环境、secure context、permission/user gesture、时延、输入质量和失败路径；
- `core_proof` 要求降级后仍用真实软件证明核心 reveal，不能退化成录屏、假数据或
  人工代劳。

这些检查不需要新字段。信息缺失继续映射现有 `uncertain/repairable`；明确超预算、
明确不支持或只能 mock 核心时才映射现有 `fail/invalid` 和既有 reason code。

#### 6.4 Controller 聚合矩阵

初次：

- Hook A=`pass`、Hook B=`pass`、Feasibility=`pass` → C4 pass；
- Feasibility=`invalid` 且包含前三个硬失败 reason，或 dependency 明确不可能 → 直接淘汰；
- Hook A/B 都 `invalid` → 按现有规则淘汰；
- 其他组合 → 使用现有一次 C4 repair budget。

修复后重新启动两份 fresh Hook Review 和一份 fresh Feasibility Review：

- 三者全部 `pass` 才通过；
- 其他任何结果都以 `c4_unresolved_after_repair` 淘汰；
- 不开启第二轮修复。

Feasibility 不新增独立 revision budget。C4R Prompt 同时读取两份 Hook 和一份 Feasibility evidence；它仍逐字保留：

- `Intended Reaction`
- `Real Input, Transformation and Output`
- `Parent Atoms`

因此“把装置改成 App”不可能被当作局部修复；这类概念应淘汰或在未来 run 作为新 Concept 重新生成。

#### 6.5 处置与零 Idea 语义

`ConceptDisposition.evidence_refs` 应同时绑定 Hook 与 Feasibility artifacts；decision metadata 分别记录：

- `hook_review_refs`
- `feasibility_review_ref`
- 聚合矩阵版本

新增稳定 terminal reason：

- `c4_software_demo_invalid`

并保留具体维度 reason codes。

当前 `all_candidates_failed_hook` 已不再准确。新 contract 建议使用：

- `all_candidates_failed_concept_screen`

旧 v1 run 仍保留并识别 `all_candidates_failed_hook`；不要重写冻结历史。

### 7. C5/C6 的具体调整

#### 7.1 C5M 与 C5W

- Memory Recall 可以读取过去装置/硬件 Concept 的抽象机制作为 `inspire`/`avoid`，但 Remix Prompt 必须获得当前 `Software Demo Policy`。
- 所有 challenger 与 base 一样通过 C4H + C4F；历史 positive 不具有豁免权。
- C5W 仍扫描 hackathon 项目、游戏、玩具、艺术和网络梗，因为这些材料仍有创意价值；它不输出 feasibility pass/reject。
- C5W 只对通过完整 C4 screen 的 Concept 执行。测试要直接断言 task 数等于完整 screen pass 数。

#### 7.2 C6A

C6A context 增加 C4F artifact。可修订：

- Demo cut；
- runtime/依赖说明；
- 现场可观察证据；
- share artifact 的表达。

不可修订：

- 把硬件/人工核心换成软件核心；
- 改写 `Real Input, Transformation and Output`；
- 绕过 C4F reason。

事实上，硬失败 Concept 不应到达 C6A；这里主要处理剩余风险与表达。

#### 7.3 C6B 自动 shortlist

Portfolio Curator 的每项分类建议增加 categorical evidence：

- `software_demo_strength`
- `surprise_fun_or_intrigue`
- `one_sentence_clarity`
- `immediate_share_trigger`
- `novel_combination`

每项为 `pass|uncertain|fail`，附 reason/evidence；`decision` 仍是 `include|hold|exclude`，不允许总分或排序。

推荐机械关系：

- 所有维度 `pass` → `include`
- 无 `fail`、至少一个 `uncertain` → `hold`
- 任一 `fail` → `exclude`

`one_sentence_clarity` 与 `immediate_share_trigger` 要独立取证；“讲得清”不能自动
变成“想分享”，仅能手工录屏、裁剪、上传再解释时应把摩擦计入后者。

Curator 还应在候选池中按 `(audience input, executable transformation, reveal,
share artifact/loop)` 比较机制族。不同 Territory 标签下若至少三项实质相同，
继续使用现有 duplicate refs，并让 `novel_combination` 只支持有真实机制差异的
代表项。Controller 仍使用现有 include/hold 分层和 Territory round-robin，不需要
新语义聚类器或人工 Top-K；Territory 多样性不能掩盖跨候选机制同质化。

这样 shortlist 首先保证 software/demo gate，随后把“有趣且立刻想分享”和“不是
同一套 camera/Canvas/reveal 换皮”从隐含 taste 变成可审计的自动分类。

#### 7.4 C6 人工字段和页面

当前页面已经展示核心机制和最小 Demo：

- `src/hacksome/review_ui/index.html:75-95`
- `src/hacksome/creative/review_backend.py:330-381`

但 human receipt 只有 retell、share target、四种反应和 recommendation：

- `src/hacksome/creative/review.py:507-535`
- `src/hacksome/creative/review.py:1060-1142`
- `src/hacksome/review_ui/index.html:179-219`

建议最小新增两个字段：

```json
{
  "share_impulse": "immediate|maybe|no",
  "demo_confidence": "yes|maybe|no"
}
```

约束：

- `share_impulse=immediate` 时必须填写非空 `share_target`；
- `demo_confidence` 问“看完最小 Demo 路径后，你相信团队能在比赛时间内跑起来吗？”；
- 保留一句话复述、surprise/fun/mystery/confusion、自由评论和 recommendation；
- 普通 reviewer 看到原始 `Software Core and Runtime` 与 `Minimum Hackathon Demo`，但不预先看到机器 C4F verdict，避免锚定；
- Percy curator 额外看到 C4F dimensions/reason/evidence，以及 human `share_impulse` / `demo_confidence` 的逐人原始值；
- 这些人工字段是信号，不自动重开 C4，也不伪装成真实传播力或实际构建成功。

Pairwise 文案可从“更想把哪一个拿给别人看”收紧为“更想立刻点开、转发或让别人试哪一个？为什么？”，仍完全可跳过。

### 8. Benchmark 调整

#### 8.1 自动指标

新增：

- C3 `software-first` 合格率；
- 冷启动约 30 秒路径、关键子系统数、最高风险假设/两小时 probe、降级切片和
  预置状态成本的完整率；
- C4F `pass|repairable|invalid` 数及每个 reason code 分布；
- 硬件 fixture 的 false-pass；
- 纯装置/人工 fixture 的 false-pass；
- 合法软件 fixture 的 false-reject；
- permission/scope 不清晰 fixture 是否进入一次 repair，而不是错误 hard reject；
- 标准 Web API 兼容/权限/延迟陷阱的 false-pass；
- 仅靠手工录屏传播的 false-pass；
- C4 完整 screen 后进入 C5W 的数量与节省的 token/wall time；
- shortlist 中 C6B `immediate_share_trigger=pass` 的占比；
- retell/share verdict 的独立性、duplicate refs 覆盖率、shortlist 机制族数量与
  最大机制族占比；
- Memory challenger 的 C4F 通过率与旧硬件模式再引入率。

#### 8.2 人工指标

保留：

- 30 秒一句话复述准确度；
- surprise/fun/confusion；
- 具体分享对象。

新增：

- `share_impulse=immediate` 比例；
- immediate 且有具体 `share_target` 的比例；
- reviewer 是否想亲自打开/操作 Demo；
- `demo_confidence=yes` 比例；
- “技术机制可见”还是“主要靠文案/主持人/布景”的自由判断；
- pairwise 中更想立刻转发或让别人试的选择。

这些仍是 Idea 阶段代理指标。真正“能否构建成功”只有后续 Build benchmark 才能证实，当前 route 不应宣称已验证真实落地率。

#### 8.3 必需 fixture 组

至少加入：

1. **软件正例**：单一主要浏览器切片完成真实软件反转；普通 laptop 可运行，
   冷启动步骤和预置成本清楚。
2. **内置 I/O 正例**：手机/浏览器摄像头或麦克风驱动实时软件 transformation，无额外设备。
3. **定制硬件反例**：Arduino、机器人、定制传感器、焊接或实体制作是核心。
4. **纯装置反例**：椅子/卡片/演员/主持人完成核心机制，软件只播放素材或计时。
5. **伪技术反例**：Figma、预录视频、人工选择输出或 mock API 冒充真实机制。
6. **权限反例**：核心需要比赛期间拿不到的私有数据、后台权限或付费服务。
7. **可修复例**：软件核心明确，但 Demo cut/部署步骤/依赖边界没有写清，应 repair 一次。
8. **viral 弱例**：软件可运行但只是普通 dashboard/聊天壳，没有 surprise/share trigger，应在 Hook/C6B 淘汰。
9. **标准 API 陷阱**：写出 camera/mic/MediaRecorder/WebSocket，但目标环境缺
   secure context、permission gesture、兼容或延迟证据，应 repair 或 reject。
10. **复杂度反例**：四个以上关键子系统、多服务 backend 或多设备同步是核心，
    且没有能保留 reveal 的降级切片。
11. **预置状态反例**：依赖人工准备账号、房间、种子数据、模型 warm-up 或预录
    内容，却把这些成本隐藏在 30 秒体验之外。
12. **分享摩擦反例**：只有手工录屏、剪辑、上传和解释，没有生成 URL/artifact/
    challenge loop；retell 可以 pass，但 share trigger 应 fail/uncertain。
13. **机制同质组**：不同 Territory/标题复用相同 input、transformation、reveal
    和 share loop，C6B 应通过 duplicate refs 与 `novel_combination` 压缩。

### 9. Acceptance Criteria

- [ ] 每个新 Creative run 持久化并 hash/freeze 一个可见的 `Software Demo Policy`；C1/C2/C3/C4/C5M Remix/C6A/C6B 使用同一精确版本。
- [ ] 默认 policy 明确禁止定制硬件/实体制作/专用设备和纯人工装置作为核心，明确允许普通电脑/手机及其内置 I/O。
- [ ] C1 仍不暂停；C6 仍是唯一 Human-in-the-loop gate。
- [ ] 六个默认 Territory lens 全部 software-native，不再把 spatial/embodied/performance 或 cross-media 本身当作独立目标。
- [ ] 每个 C3 Concept 明确写出 software runtime、真实 input、可执行 transformation、observable output、依赖、最小 Demo cut 和 share artifact。
- [ ] C0 没有明确资源时，C3/C4F 按 2 人/24 小时、一个简单 backend、一个主要
  浏览器/设备切片和最多三个关键子系统审查；Concept 明示冷启动 30 秒、最高风险
  假设/两小时 probe、降级切片和预置状态成本。
- [ ] 每个初始或 repaired Concept revision 恰好有两份 fresh Hook Review 和一份 fresh C4F Review；三者互相看不到结果。
- [ ] 明确定制硬件、实体制作或纯装置/人工核心的 Concept 在 C4 终态淘汰，且绝不启动 C5W、C6A、C6B 或人审。
- [ ] 使用普通 laptop/phone/browser 和内置 camera/mic 的合法 software demo 不因“使用硬件”被误杀。
- [ ] C4F 缺少可修复细节时进入现有一次 C4 repair；硬件/装置核心不能通过 repair 偷换成新 Concept。
- [ ] repair 后重新执行全部 Hook + Feasibility reviews；只有全部 pass 才继续，最多一轮。
- [ ] Memory challenger 与 base 使用完全相同的 C4H+C4F，不能因历史 positive provenance 绕过。
- [ ] C5W task 数严格等于完整 C4 screen pass 数，C5W 不输出 feasibility route decision。
- [ ] C6A 接收 feasibility evidence，但只做有界澄清；C6B 输入池不含 C4F 未通过项。
- [ ] C6B 使用 categorical software/demo、surprise/fun、clarity、share-trigger、novelty evidence，不输出 1–10 分或总排序。
- [ ] C4H/C6B 分别判断 retell 与 share；手工录屏不自动算立即分享。C6B 使用
  既有 duplicate refs/`novel_combination` 识别跨 Territory 机制同质化。
- [ ] C6 reviewer receipt 保存 `share_impulse` 与 `demo_confidence`；`immediate` 必须有 share target；字段继续绑定 exact round/concept/hash 并进入 feedback fragment hash。
- [ ] 普通 reviewer 不在首次提交前看到机器 feasibility verdict 或 peer 反馈；Percy curator 能查看完整 feasibility evidence 和原始人类信号。
- [ ] C7 报告逐项记录 Hook 与 Feasibility fate；zero reason 能区分新完整 screen 为空，旧 run 的 `all_candidates_failed_hook` 仍可读取。
- [ ] Idea Memory 把 hardware/install/manual/permission/scope reason 保存为独立 caution，不压成 Hook 模糊失败。
- [ ] Useful route 的 Prompt、stage、CLI 默认和回归行为不变。
- [ ] benchmark 报告 software false-pass/false-reject、C5W 成本变化、share impulse、retell 和 demo-confidence，同时明确后两者只是代理信号。

### 10. Required Tests

#### Prompt / Schema / semantic validator

- `Software Demo Policy` 在允许阶段出现且 hash 一致；不应出现的旧 run/外部先例仍隔离。
- C2 lens 快照测试不含纯 spatial/performance/cross-media 目标。
- C3 缺 software runtime、share trigger 或可执行 Demo 信息时 invalidated，不转成 candidate reject。
- C4F dimensions 顺序、verdict/reason 对应、pass 聚合和 evidence 非空。
- C6B categorical dimension 与 include/hold/exclude 机械关系。

#### Workflow routing

- software pass：2 Hook pass + C4F pass → C5W。
- custom hardware：C4F invalid → terminal disposition；0 C5W。
- pure installation/manual performance：C4F invalid → terminal disposition；0 C5W。
- missing Demo detail：C4F repairable → 一次 repair → fresh 2+1 review → pass 或 terminal reject。
- repair 试图改变 `Real Input, Transformation and Output` 或把装置换成 App → semantic failure/partial，不伪造淘汰。
- memory challenger 硬件化 → 同样被 C4F 淘汰。
- base/challenger 全部未过完整 screen → 新 zero reason + 空 C6 batch，不等待。
- 乱序并发完成不改变 review ID、decision、disposition 或最终顺序。

#### Review API / UI

- `share_impulse`、`demo_confidence` 的 exact enum、request hash、persist/reload、supersede 和 fragment hash。
- immediate + 空 share target 返回 4xx/validation error；maybe/no 可为空。
- reviewer snapshot 有原始软件 Demo 文本但无 C4F verdict；curator snapshot 有完整 feasibility evidence。
- Team Wall、receipt、curator workbench 和 report 正确显示新字段。
- Desktop/mobile/keyboard/localStorage/stale draft 回归。

#### Report / Memory / compatibility

- C7 Candidate Fate Ledger 区分 Hook 与 Feasibility reason。
- Memory classification 对七个 feasibility reason 全覆盖。
- 新 contract 的 zero reason 与 legacy `all_candidates_failed_hook` 分版本验证。
- 已冻结的 v1 waiting run 仍能 inspect/review/resume；新代码不能用 v2 Prompt/Schema 重解释旧资源。
- Prompt/stage/contract policy 版本必须提升；新 stage、reason enum 和 review receipt shape 不可在 version `1` 下静默替换。
- 完整 Useful suite 不变。
- 本次 smoke 后的收紧只修改 v2 Prompt 语义；v2 JSON shape、dimension/reason
  enum、controller 聚合矩阵和 frozen v1/v2 loader 分派保持不变；新 run 使用
  前进后的 Prompt template/policy version，既有 v2 run 继续绑定原 Prompt 字节。

### 11. 版本与迁移建议

这不是单纯文案调整，因为它增加 stage、改变 C4 聚合、增加 reason code、改变 review receipt 和报告语义。应至少提升：

- Creative contract version；
- Prompt policy / 相关 template version；
- stage policy version；
- review payload/snapshot schema version；
- report/memory policy（若 zero reason 和 memory classification 改变）。

当前设计承诺 waiting run 使用创建时冻结的 Prompt/Schema：

- `.trellis/spec/backend/creative-agent-workflow-contracts.md:122-165`

因此不能直接把所有 `version="1"` 的资源原地覆盖。现有 v1 run 可以：

- 保持 v1 inspect/review/resume；
- 新 run 使用 v2 policy；
- report/validator 根据 persisted contract 分派合法 reason/schema。

如果团队明确决定真实 smoke run 只是一次性临时数据、不需要继续，仍应在文档中写出“不兼容废弃”的显式决定，不能悄然让它失败。

### 12. Files Found

- `.trellis/tasks/07-23-creative-idea-review-loop/prd.md` — C0–C7 产品目标、现有 Hook/Novelty/Human benchmark 与验收合同。
- `.trellis/tasks/07-23-creative-idea-review-loop/design.md` — 阶段矩阵、C4 聚合、C6 shortlist、review ledger/API/UI 和 benchmark 设计。
- `.trellis/tasks/07-23-creative-idea-review-loop/implement.md` — 当前实现切片、测试门和真实 smoke 完成状态。
- `.trellis/tasks/07-23-creative-idea-review-loop/smoke-test-report.md` — 真实 run 中 12/12 Hook-pass、诗性装置偏移和 C5W 成本证据。
- `.trellis/spec/backend/creative-agent-workflow-contracts.md` — Creative route 的规范性状态、Prompt freeze、循环上限、C6 与 C7 合同。
- `.trellis/spec/backend/agent-workflow-contracts.md` — Useful Red Team 对真实 input、权限和 mock-only 结果的现有审查模式。
- `src/hacksome/creative/contracts.py` — 当前 stage、默认 Brief、Territory lens、settings 和 reason code。
- `src/hacksome/creative/artifacts.py` — C1/C2/C3/C4/C5/C6 schema 后的 semantic validator。
- `src/hacksome/creative/workflow.py` — 当前 C4 双 Hook reviewer 聚合、C5W fanout、C6A/C6B 和空 batch 路由。
- `src/hacksome/creative/review.py` — HumanReview、ConceptReview、reaction/retell/share 字段和 append-only validation。
- `src/hacksome/creative/review_backend.py` — reviewer/curator snapshot 投影和 Concept Demo 展示。
- `src/hacksome/review_ui/index.html` — 当前 Concept 详情、评审表单、pairwise 和 Percy 策展台。
- `src/hacksome/review_ui/app.js` — 当前 reaction、草稿、payload 与渲染逻辑。
- `src/hacksome/prompts/creative/*.md` — C1–C6 当前角色说明；C4/C6B 尚无独立 software/demo/viral rubric。
- `src/hacksome/schemas/creative/*.json` — 当前 envelope shape；没有 C4F schema。
- `tests/test_creative_workflow.py` — fake runner、C4 路由和现有 sensor/projector Demo fixture。
- `tests/test_creative_artifacts.py` — Hook dimensions、Concept/revision semantic validation。
- `tests/test_creative_review.py` — review receipt、hash、supersede、coverage 和 resolution 测试。
- `tests/test_creative_review_backend.py` — role-aware snapshot 与真实 waiting workflow 测试。
- `tests/test_creative_review_server.py` — HTTP redaction、cookie/session 和 review payload 测试。

## External References

无。本次结论来自仓库当前合同、实现、测试和 2026-07-24 真实 smoke run，不需要外部资料。

## Related Specs

- `.trellis/spec/backend/creative-agent-workflow-contracts.md`
- `.trellis/spec/backend/agent-workflow-contracts.md`
- `.trellis/spec/backend/index.md`

## Caveats / Not Found

- “硬件 idea”需要产品上明确普通设备内置 camera/mic/accelerometer 是否允许。本研究推荐允许普通设备内置 I/O，只淘汰定制/专用/需搬运配置的硬件；如果 Percy 希望连 camera/mic 也禁用，应把 policy 再收紧。
- 当前 Idea route 到 C7 结束，不实际构建产品。因此 `demo_confidence` 和自动 C4F 只能是可落地代理信号，不能声称已经验证真实 build success。
- 真实 v2 smoke 已证明 software-native generation 有效，也证明 C4F 目前更像
  媒介合规检查；本研究提出的预算/冷启动/风险收紧仍需用同题重跑和后续 Build
  benchmark 验证 false-pass/false-reject。
- 当前 online benchmark controller 仍是 plan-only；本轮可以先完成离线 fixture 与 route smoke，对 live A/B 的实际统计不能伪装成已交付。
- 真实 v1 smoke run 位于 `/private/tmp` 且未提交。是否长期兼容它是产品决定，但 frozen-contract 原则要求显式处理，不能无意破坏。
- 本研究初稿没有修改业务代码；本次 post-smoke addendum 同步更新 PRD、design
  与 implement，但仍不修改业务代码、spec、task metadata 或 smoke report。
