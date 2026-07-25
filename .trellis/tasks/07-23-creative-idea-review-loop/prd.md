# 创意构想工作流

## 目标

为 hackathon 构建一条只产出构想的 Creative 路线，系统性探索出人意料、好玩、神秘、值得立刻分享，并且能在比赛期间跑出真实软件 Demo 的概念，而不强迫它们接受 Useful 路线的需求频率与商业价值模型检验。

工作流从一道 hackathon 挑战开始，最终生成一份确定性报告，其中包含完整的候选项历史、每次淘汰的原因和证据，以及零个或多个最终 Creative Idea Card。完成的运行还会生成一份不含私人原始反馈的 Idea Memory Record，让未来运行可以受控地借用机制、反转结构或失败教训。它不会构建、部署或推介由此产生的产品。

主要的可观察成功信号是：

> 听完 30 秒的概念说明后，评审者能用一句话准确复述这个构想，并立刻想到一个自己想把它分享给的人。

这是构想阶段对创意清晰度与分享意愿的代理指标，并非对现实世界传播力的断言。路线还必须在进入联网查重和人审前证明存在可信的 `真实 input → 可执行软件转换 → 可观察 output` 最小路径；这仍是 Build 前的可落地性代理，不等于产品已经实际构建成功。

## 产品原则

- **构想就是产品。** 工作流优化的是 hackathon 概念的质量与广度，而不是把构想阶段当成编写代码之前短暂的前奏。
- **Creative 并不是降低证据要求的 Useful。** 两条路线共享可靠的执行机制，但采用不同的探索材料、产物、关卡、Prompt、基准和停止规则。
- **惊喜必须源自某种机制。** 神秘的描述、营销文案或无法解释的 AI 魔法都不够。
- **先让人看懂，再允许它神秘。** 评审者必须先能用朴素语言说清“用户做什么、软件回应什么、为什么还想再试或转发”，之后才讨论诗意、诡异或余韵。需要策展说明、世界观补课或审美训练才能成立的 Concept 不进入 shortlist。
- **先例提供交互语法，不提供可复制答案。** Concept 可以借鉴人们已经理解的产品/游戏/创作工具形态，但必须说明借用了哪种可识别的互动语法、核心机制做了什么实质变化，以及为何不是给旧产品换 AI 外皮。
- **软件必须承载核心因果。** 浏览器、手机、桌面、CLI、服务端或本地/云模型必须真正完成体验的关键转换；主持人、演员、卡片、椅子、舞台规则或投影布景不能代替软件完成核心机制。
- **能跑 Demo，而不只是能讲 Demo。** 最小演示必须使用真实可得输入和依赖，由代码、模型、API 或协议产生现场可观察、可录屏或可亲手操作的输出；Figma、预录视频、人工选结果和 wizard-of-oz 不能冒充核心技术。
- **技术名词不等于可落地。** 写出标准 Web API、WebSocket、模型或云服务名称，只能证明存在候选技术，不能证明权限、兼容性、时延、预热、部署和失败降级在比赛现场可控。若 Challenge 没有给出资源预算，路线按“最多 2 人、24 小时、一个简单 backend、一个主要浏览器/设备切片”的保守参考预算审查，而不是默认拥有完整产品团队。
- **30 秒从真实冷启动开始。** 观众打开入口、授予必要权限、提供第一个真实输入，直到看见第一个有感受的输出，目标路径约 30 秒；预置账号、房间、种子数据、模型预热、设备配对和人工准备不能从成本说明中消失。
- **传播性必须有具体触发物。** Concept 要说清观众为什么会立刻分享、分享什么，以及可能发给哪类具体的人；“很 viral”不是证据。
- **“可复述”与“想分享”是两项独立结果。** 一句话讲得清不代表值得转发；需要手工录屏、剪辑、上传和解释才能传播的 Concept，也不能仅凭“可以录屏”被视为具有立即分享触发物。
- **“淘汰硬件”指淘汰定制硬件核心。** 普通电脑/手机以及内置屏幕、键盘、触控、摄像头、麦克风、扬声器和加速度计可以使用；需要焊接、Arduino/机器人、专用传感器、实体制作、设备搬运或现场校准的核心方案自动淘汰。
- **先生成，再研究先例。** 现有成果研究在初步综合之后进行，以减少对熟悉产品和 hackathon 套路的锚定。
- **先独立创作，再读取历史。** 当前运行的第一批 C2/C3 与初始 C4 的受控上下文、Prompt 和 parent refs 不得注入过去的 Idea；历史只能在后续有界分支中提供抽象灵感或避坑线索。所有受支持 Creative contract 都把这定义为可审计的上下文隔离，而不是操作系统级机密隔离。
- **模型负责探索，人类掌握品味。** Agent 可以筛选、比较、批评和修订，但模型自行给出的 1-10 分不被视为事实依据。
- **不允许悄然消失。** 已生成、被拒绝、失败、合并、修订和入选的候选项都必须保持可追溯；零 Idea 必须解释候选集在哪一关变空以及为什么。
- **历史是材料，不是答案。** 过去的最终 Idea、未入 shortlist 的方向和失败分支具有不同含义；历史淘汰只代表它在当时的挑战、版本和证据下失败，不是跨挑战的永恒判决。
- **循环必须有界。** 每个修复或反馈循环都有明确上限。

## 背景与已确认事实

- 仓库当前提供本地 Python CLI 和具体的七阶段 `UsefulIdeaWorkflow`；尚无 Creative 路线、运行级恢复、HTTP 服务器或前端依赖（`pyproject.toml`、`src/hacksome/cli.py`、`src/hacksome/workflow.py`）。
- `CodexRunner` 已经提供有界并发、显式 timeout、精确 Session 基础设施重试、结构化输出和原始日志；这些能力可以原样共享（`src/hacksome/codex.py`）。
- `RunHub` 是当前运行状态、Prompt、任务、产物、事件和机器决策的唯一持久化所有者；`state.py` 只提供原子 JSON、内容哈希和幂等 JSONL 等路线中立原语（`src/hacksome/hub.py`、`src/hacksome/state.py`）。
- `RunHub` 的任务和产物基础能力较通用，但 `idea_card_ids`、`pass/reject` 决策枚举、状态集合、`inspect()` 与 `validate()` 仍包含 Useful 语义，不能直接视作已经完成的通用 Harness。
- 当前 `prompting.py` 的渲染算法可复用，但 Prompt 注册表、Schema 映射和语义验证属于 Useful；`UsefulIdeaWorkflow._call()` 中“渲染 → 先持久化 → 调用 Codex → 记录结果 → 语义验证”的执行骨架是最清晰的共享抽取点。
- 当前 `RunHub` 只能打开一个明确的 run 路径，没有跨 run 发现或索引能力；现有产物和 SHA-256 原语足以支持“扫描显式 runs 目录 → 验证完成的 Creative memory record → 复制成当前 run 的冻结快照”，v1 不需要新增全局数据库。
- 最新 Useful v1 明确不支持运行级 `resume`。Creative 的 Agent/业务工作流恢复只用于 C6 `waiting → resume`；C7 另允许一个不调用模型、只重放已冻结字节的发布恢复入口，二者都不能借机改变 Useful 的 CLI 与失败语义。
- Weston 负责 Useful/商业方向。Percy 负责 Creative hackathon 方向。两条路线可以在同一仓库中并行演进。

## 产品边界

### 范围内

- 一条明确的 Creative Idea 路线，包含下述八个阶段。
- 路线专属的 Prompt、Schema、产物、关卡、报告和基准。
- 一份由 Controller 持有、随 run 冻结并在后续允许阶段逐字复用的 `SoftwareDemoPolicy`；自由文本 Brief 只能收紧体验方向，不能悄然放宽 software-first、定制硬件和真实端到端 Demo 边界。
- C4 内独立的 C4H Hook/分享触发审查和 C4F Software Demo Feasibility 自动审查；二者共享一次局部修复预算，不新增人工暂停。
- 每个候选 revision 的结构化处置记录，包括阶段、结果、稳定原因码和证据引用。
- 一份由每个已完成 Creative run 确定性生成的 Idea Memory Record，以及当前 run 创建时冻结的历史快照。
- C5 内一个不新增人工暂停、最多生成两个 challenger 的历史灵感分支；所有 challenger 必须重新经过 Hook 与新颖性关卡。
- 可靠运行 Useful 与 Creative 所需的最小共享 Harness。
- C6 阶段内一个详细的 Human Curation 步骤。
- 本地持久化、C6 人工等待/继续、C7 frozen finalization 重放、状态查看、验证及可检查的审计轨迹；不承诺任意其他失败阶段的运行级恢复。
- 一个用于 C6 人工步骤的轻量团队评审页面。
- 最终 Idea Card 的稳定纯 JSON handoff，供独立的 Build Review Gate 后续选择；本任务不启动 Build。
- 确保多条路线并行开发安全的协作与 Git 集成规则。

### 范围外

- 构建、部署或推介最终 Idea 所描述的产品。
- 以 C4F 或人类 `demo_confidence` 宣称已经验证真实构建成功；真实 build success 只能由后续 Build benchmark 证明。
- 公共用户账户、组织管理或生产级身份系统。
- 通用工作流 DSL 或用户任意编写的阶段图。
- 全局可变 Idea 数据库、向量数据库、embedding 检索服务或跨 run 写事务；v1 只扫描显式 runs 目录中的可验证文件。
- 自动导入 Useful v1、失败/等待中的 Creative run、benchmark fixture、外部笔记或完整旧 Idea Card；以后如需支持，必须通过显式适配器和独立验收。
- 将评审者身份、未批准的原始反馈、任务日志或旧 Prompt 注入未来运行。
- 在 Creative 路线中重写 Useful 方法论。
- 根据 Idea Card 的评审行为宣称实际传播力。
- 无限制自我修复或无休止的 Agent 争论。

## 共享 Harness 与路线边界

目标架构是在现有 `RunHub` 上做最小、证据驱动的共享抽取，由两条独立路线组合使用：

```text
RunHub（共享持久化核心）
  ├── state.py 原子写入 / hash / JSONL
  ├── CodexRunner
  ├── AgentTaskExecutor
  └── PromptRenderer + 路线专属 PromptCatalog

UsefulIdeaWorkflow       CreativeIdeaWorkflow
UsefulRunContract        CreativeRunContract
```

要求：

- `CreativeIdeaWorkflow` 不得继承 `UsefulIdeaWorkflow`，也不得通过参数化 `UsefulIdeaWorkflow` 来实现。
- 不新建与现有 `RunHub` 重叠的 `StateStore` 或 `ArtifactStore`；共享层只抽取已经存在两个使用方的能力。
- 每次运行都持久化 route metadata，其中包含 `route.id`、contract version、Prompt policy、stage policy 和 report policy 版本。
- `run`、`status`、`validate` 和报告依据持久化的路线身份进行分派；`resume` 是可选的路线能力，只由 Creative 实现，并严格区分 C6 业务恢复与 C7 确定性发布重放。
- 通用 timeout、并发、同一逻辑任务的基础设施重试、Prompt 持久化、结构化输出验证、单文件原子写入、可恢复的产物登记和账本属于 Harness。
- 阶段 ID、拓扑、fanout 设置、上下文允许列表、输出契约、语义验证和路线报告属于各条路线。
- 在抽取 Harness 时必须保持 Useful 行为不变；不得将 Harness 变成臆想式的通用工作流语言。
- 每次尝试调用 Codex 前，都要保存并哈希最终 stdin Prompt 的精确字节，包括重试/纠正时添加的内容。
- 基础设施失败、有效的空输出、自动淘汰、人工拒绝和人工等待关卡是彼此不同的持久化状态。

## Creative Idea 工作流

该路线包含八个逻辑阶段，采用 Creative 命名空间（`C0`-`C7`），不复用 Useful 的 `S0`-`S11` 标识符。

### C0. 挑战与约束

**目的：** 明确挑战允许和要求什么，同时避免将赞助商技术或评审措辞直接变成预设的产品构想。

**行为：**

- 将原始挑战解析为中立的 Challenge Brief 和单独的 Constraint View。
- 保留硬性规则、必需技术、允许使用的数据、时间/团队限制、强制交付物、评审背景和含糊约束。
- 将有来源的事实与控制器或 Agent 的推断分开。
- 在适当情况下复用共享的解析与持久化机制，同时保持 Creative 解释契约为路线专属。

**输出：** `CreativeChallengeBrief` 和 `ConstraintView`。

**关卡：** 必需的硬约束均已存在、可追溯且内部一致；未解决的歧义必须清晰可见，而不是靠猜测消解。

### C1. 创意简报

**目的：** 在生成解决方案之前，先定义情绪与体验目标，并冻结本次运行不可被 Agent 稀释的软件 Demo 边界。

**行为：**

- Creative Brief 作为运行初始输入的一部分提供；CLI 允许 Percy 传入文本或 Markdown 文件。
- 未显式提供时，控制器写入并持久化一份可见的默认方向：惊喜、好玩、神秘和分享冲动，同时把“纯粹困惑、只靠文案和浓烈 AI 味”列为反目标。
- Agent 可以把 Percy 的输入规范化为结构化 `CreativeBrief`，但 C1 不暂停等待批准；C6 仍是唯一人工关卡。
- Controller 同时发布并 hash/freeze 一份可见的 `SoftwareDemoPolicy`，固定：
  - `medium=software_first`；
  - `ordinary_device_io=allowed`；
  - `custom_hardware_or_fabrication=forbidden_as_core`；
  - `manual_performance_or_installation=forbidden_as_core`；
  - `real_end_to_end_demo=required`；
  - `mock_or_wizard_of_oz_core=forbidden`。
- 该 Policy 是权威事实，必须以同一精确版本进入 C1、C2、C3、C4H、C4F、C5M Remix、C6A 和 C6B；Creative Brief 的模型正文不是它的唯一载体。
- 记录期望的受众反应，例如惊讶、欢笑、好奇、神秘感、愉悦、不安或诗意。
- 记录反目标：Percy 不希望出现的反应、陈词滥调、调性、交互模式和演示风格。
- 定义可能的观看/交互场景、大约 30 秒的揭示窗口、可用媒介，以及任何文化或安全边界。
- 区分有意营造的神秘感和意外造成的难以理解。
- 明确记录由 Percy 决定的选择；不得仅根据赞助商措辞推断品味。

**输出：** `CreativeBrief` 与 controller-owned `SoftwareDemoPolicy`。

**关卡：** 简报包含正向体验目标、反目标，以及足够清晰、可指导独立探索的场景；Policy 的路径、版本和 hash 与 run metadata 闭合。C1 不等待人工批准。

### C2. 创意领域

**目的：** 在确定完整产品概念之前，先探索真正不同的创意空间。

**行为：**

- 让相互独立的 Agent 探索六类 software-native 领域：
  - 直接操控与不寻常的软件交互；
  - 可运行界面中的反转、揭示与预期迁移；
  - 多人协作、社交玩法与传播；
  - 由软件可见隐藏状态驱动的神秘叙事；
  - 使用普通设备内置 I/O 的摄像头、麦克风、文本、代码、时间或实时数据转换；
  - 由技术机制生成的 viral remix、replay 或可分享产物。
- 产出创意原子：机制、触发器、转变、受众行动、揭示和余韵。
- 每个 Atom 还要指出软件运行表面、核心软件机制、可得依赖和最小技术证明；空间、表演或跨媒介只能是软件机制的呈现方式，不能独立充当 Concept 核心。
- 不要求商业痛点或需求频率证明。
- 此时不得研究先例。
- 以机制上的实质差异作为多样性；仅改变名称或视觉外观并不能形成新的领域。

**输出：** 与版本绑定的 `CreativeTerritory` 和 `CreativeAtom` 产物。

**关卡：** 该集合覆盖多个机制上实质不同的领域，并记录每个领域与简报相关的原因。

### C3. 概念综合

**目的：** 将相互兼容的创意原子转化为完整、易懂的 Concept。

**行为：**

- 多个相互独立的综合 Agent 可以跨领域组合创意原子。
- 第一批综合只能读取当前运行的 C0-C2；不得读取 Idea Memory、旧 Idea Card、过去淘汰原因或联网先例。
- 每个 Concept 都要说明：
  - 预期反应；
  - 一句话 Hook；
  - 受众首先看到什么；
  - 受众做什么；
  - 铺垫、转折/揭示和余韵；
  - 真实的输入、转换和输出；
  - `Software Core and Runtime`：运行入口、主要代码/模型/API/协议、真实输入取得方式、核心转换、可观察输出与外部依赖；
  - `Share Trigger and Artifact`：为何会立刻分享、实际分享的 URL/录屏/结果/挑战/remix，以及可能分享给哪类具体的人；
  - 结果为何出人意料但又可以理解；
  - 在既有 `Audience Action`、`Software Core and Runtime` 与 `Why It Is Unexpected Yet Legible` 中写清 `Plain-language Product Loop`：不用诗性修辞或技术名词，分别用一句话说明用户输入/动作、软件实时完成的可观察变化、用户为什么会再试一次或把结果发给别人；
  - 在既有 `Why It Is Unexpected Yet Legible` 中写清 `Recognizable Product Grammar`：指出最接近的、普通人已经理解的交互/产品家族（例如关系路径探索器、实时音乐搭档、可分享生成玩具、多人挑战或创作工具），再说明保留了哪种熟悉语法、改变了哪一项核心机制；不得伪造产品名、链接或研究事实；
  - `Minimum Hackathon Demo`：团队时间内的最小 build cut、从真实冷启动到第一个有效输出的约 30 秒路径、现场步骤、真实依赖、关键子系统数量、最危险且可快速验证的技术假设、该假设失败后的降级切片、预置状态成本和可验收证据；
  - 假设、可能造成的困惑，以及安全/文化风险。
- 保留父级领域/创意原子的谱系。
- 为每个 Concept 指定一个 `primary_territory_ref`，它必须来自其 Parent Atoms 所属的 Territory；这是后续组合多样性和历史分类的稳定来源，自动 curator 不能改写。
- 如果无法诚实地综合出任何 Concept，空输出是有效结果。

**输出：** revision-1 的 `CreativeConcept` 产物。

**关卡：** Concept 不能只是名称、口号、功能列表、美学换皮、环境氛围、需要策展说明的装置隐喻或无法解释的 AI 效果；必须完整描述可执行的软件核心、端到端 Demo 路径、可识别的产品循环和具体分享触发物。缺少必需结构是任务输出无效，不是候选被模型“拒绝”。

用于校准而非复制的正例包括：

- “任意两个人/角色的六度关系路径”：输入、反馈和重复玩法一眼可懂；每次查询能产生可分享路径，并可沉淀常见中转站与属性跨越等二次发现。
- “实时 Jam 搭档”：用户演奏是真实输入，软件扮演缺席的鼓手/吉他手/主唱并实时回应；Blues、Jazz 或多人 Solo 等模式改变的是可听见的互动机制。

Agent 应抽取这两个例子的共同质量形状——熟悉入口、真实输入、即时软件回应、可重复玩法、明确技术证明与自然传播物——而不是复用“六度关系”或“AI 乐手”题材。

### C4. 低成本 Concept 筛选（C4H + C4F）

**目的：** 在投入网络搜索和人工评审成本之前，同时淘汰无法形成清晰、可分享体验，以及不能在比赛期间跑出真实软件 Demo 的 Concept。

**行为：**

- 每个 exact Concept revision 使用三份全新且相互独立的评审 Session：两份 C4H `CheapHookReview` 与一份 C4F `SoftwareDemoFeasibilityReview`。三者只能获得 Creative Brief、Software Demo Policy、约束和一个 Concept，互相看不到 sibling 结果、历史或先例。
- C4H 评估分类式判断，而不是一个总体 1-10 分：
  - 铺垫可以快速理解；
  - 揭示会改变受众的预期；
  - 惊喜源自机制；
  - 从真实冷启动开始的约 30 秒路径能够抵达一个有感受的时刻；
  - 无需长篇解释即可复述 Concept；
  - 存在具体、立即、低摩擦且可解释的分享触发物，而不是只宣称“很 viral”或把手工录屏、剪辑、上传当作天然传播机制；复述与分享必须分别判断。
- C4F 独立判断：
  - 核心体验由可执行软件产生；
  - 不依赖定制硬件、实体制作、专用传感器或设备搭建；
  - 主持人、演员、参与者协商或道具不承担核心因果；
  - 真实 input → executable software transformation → observable output 路径完整；
  - 数据、API、模型、权限和服务真实可得；
  - 在 C0 没有更明确资源时，最小 cut 能落入 2 人/24 小时、至多一个简单 backend 和一个主要浏览器/设备切片的参考预算；
  - 关键路径子系统数量、最危险技术假设、可先行验证方式、降级切片和预置状态成本均已诚实收敛；
  - 标准 Web API 或常见 SDK 的存在不被当作稳定可用的证明，目标环境的权限、兼容性、延迟、预热和失败路径必须成立；
  - Demo 真正证明核心机制，而非 mock、预录或 wizard-of-oz。
- 输出 `pass`、`repairable` 或 `invalid` 之一，并为每项未通过的判断提供证据和稳定维度原因码。
- 三份审查共享现有一次 C4 局部修复预算。缺少可澄清的 Demo cut/依赖细节可以 repair；明确以定制硬件、实体制作或纯人工装置为核心则以 `c4_software_demo_invalid` 终态淘汰，不能通过一次修复偷换成新的 App Concept。
- 修复必须逐字保留 `Intended Reaction`、`Real Input, Transformation and Output` 与 `Parent Atoms`，之后重跑两份 fresh C4H 和一份 fresh C4F；只有三份都 `pass` 才继续，其他结果以 `c4_unresolved_after_repair` 淘汰，不开启第二轮。
- 控制器为每个 revision 写入不可变的处置记录，分别绑定 Hook 与 Feasibility evidence、聚合矩阵版本和稳定原因码；基础设施或协议失败不得伪装成淘汰。

**输出：** 不可变的 `CheapHookReview`、`SoftwareDemoFeasibilityReview`、`ConceptDisposition` 产物，以及可选的 Concept 修订。

**关卡：** 只有两份 C4H 和一份 C4F 全部 `pass` 的 Concept 才能进入先例研究。

### C5. Idea Memory + 新颖性 / 陈词滥调扫描

**目的：** 在第一批 Concept 和 Hook 判断已经冻结之后，受控地利用过去运行的机制与失败教训补充少量新方向，再检查所有通过 Hook 的 Concept 是否与熟悉项目或 AI 时代的陈词滥调相撞。

**行为：**

- 创建当前 run 时，控制器按稳定顺序扫描显式 runs 目录，只接受 `completed`、可离线验证、受支持版本且非 fixture 的 Creative Idea Memory Record；完成但零 Idea 的 run 仍可贡献失败教训。
- 历史快照被复制到当前 run 并绑定来源 run、artifact、contract 和内容 hash。`waiting`、`failed`、Useful、未知版本、hash 损坏和未验证来源不得进入 Agent 上下文；自动模式跳过单个坏来源并留下诊断。
- `--idea-memory auto|off` 默认使用 `auto`；无历史、没有相关线索或显式关闭都是合法空输入，并且不得产生隐藏 Prompt 内容。
- C5M Memory Recall 只在初始 C4 已落盘后运行。它只能看到当前 Challenge/Brief、当前 Atom index、第一批 Concept 的精简索引与处置原因，以及冻结的 memory capsule；不得读取旧完整 Idea Card、评审者姓名、原始评论、Prompt 或任务日志。
- Memory Recall 最多选择有界数量的 `inspire` / `avoid` 线索。历史失败原因必须连同原挑战与证据边界解释，不能被当成当前挑战的绝对真理。
- 最多两个 Memory Remix Agent 各生成至多一个 challenger。每个 challenger 必须组合至少一个当前 Creative Atom 与至少一个历史线索，拥有新 Concept ID，并明确记录借用了什么、改变了什么、为什么不是复制。
- challenger 不能再次触发 Memory Recall；它与第一批 Concept 使用完全相同的 C4H+C4F 合同、共享的一次 C4 repair 和淘汰规则，历史 positive provenance 不提供豁免。
- 只有第一批或 challenger 中通过完整 C4 Concept screen 的 Concept 才进入 C5W 联网扫描；C5W 不承担 feasibility 判决。
- C5W 搜索相关的 hackathon 项目、互动艺术、玩具、游戏、迷因、装置、表演及相邻产品，并将事实性的相似证据与品味判断分开。
- C5W 识别：
  - 直接或近乎直接的碰撞；
  - 常见的 hackathon 和生成式 AI 套路；
  - 采用熟悉机制但有实质不同揭示方式的 Concept；
  - 值得保留、尚未被充分探索的组合；
  - 团队可能遗漏的文化参照或风险。
- 引用来源并保留反例。
- 不得仅因 Idea 的某一组成部分存在先例就自动将其拒绝；应判断核心组合与受众感受是否仍保持独特。
- 非空 memory 快照上的 Recall/Remix 是可见的可选增强：自动模式下 Agent 失败不会抹掉第一批 Concept，也不会伪装成“没有历史”，而是记录 `optional_memory_stage_failed` 并继续原始分支。
- 多个 Remix 使用 all-settled 语义：控制器等待所有已启动分支结束，保留每个已经通过验证的 challenger，只跳过失败的 sibling。只有 C5M Recall/Remix 可被标记为 optional branch；completed run 中任何其他 failed task 都是合同错误。

**输出：** 冻结的 `IdeaMemorySnapshot`、`MemoryInspirationPacket`、controller-owned `MemoryStageSummary`、零到两个带历史谱系的 challenger，以及每个完整 C4-pass Concept 的不可变 `NoveltyScan`。

**关卡：** 历史分支已明确完成、跳过或以可见的可选失败结束；每个保留下来的 Concept 都通过相同 Hook 合同，拥有明确的 Memory 状态（相关 cue，或显式的空/关闭/失败诊断）和完整外部先例证据，以支持一次有界修订和后续人工评审。

### C6. 修订 + 人工策展

**目的：** 利用先例证据完善最有潜力的 Concept，将候选集合缩减成便于评审的组合，收集真实的团队品味判断，并依据这些判断进行最后一次有界修订。

这是唯一一个详细的人工评审阶段。

**修订预算：**

- software-first contract v2 使用按目的分开的有界预算，而不是“整个生命周期只能改一次”：C4H 与 C4F 共享最多一次局部修复，C6 自动准备恰好一次证据驱动修订，C6 人审关闭后最多一次反馈驱动修订。
- 因而，每个 base Concept 或 memory challenger 在最坏情况下最多经历三次模型修订；每次都有不同的原因、输入边界和版本谱系。某一阶段未使用的预算不能挪到另一阶段，也不能通过重试增加次数。

**自动准备：**

- 依据每个符合条件的 Concept 的 Cheap Hook Review、Software Demo Feasibility Review、Novelty Scan、相关 Memory Inspiration 和 Constraint View 进行修订，同时保留 Concept 身份与历史；C6A 只能澄清 runtime、Demo cut、依赖与分享产物，不能把硬件/人工核心改写成软件核心。
- C6A 还必须利用已验证的 Novelty Scan，把抽象描述翻译成可识别的产品循环：明确与先例共享的交互语法、实质变化和用户可见价值。它不能凭空补写未经 C5W 支持的先例，也不能为了“更独特”把表达改得更诗性或更难懂。
- 两个独立 C6B curator 使用相同五维 Schema，但承担两个固定且不同的 Red Team 视角：
  - **Meaning & Value Red Team：** 尝试证明 Concept 只是空洞隐喻、环境氛围、一次性 AI 效果或需要策展人解释的装置艺术；若不能用朴素语言说清用户动作、软件回应、可重复价值和存在意义，必须在现有维度中给出 `fail`。
  - **Hackathon Floor Red Team：** 站在真实展厅观众面前，判断它是否像一个能现场打开、亲手试玩、马上得到反馈并愿意再试/转发的技术 Demo；“看起来新奇”但不想亲自操作、只适合看作者表演、或 Demo 后没有真实使用欲望，都不能通过。
- 两位 curator 仍分别对 `software_demo_strength`、`surprise_fun_or_intrigue`、`one_sentence_clarity`、`immediate_share_trigger`、`novel_combination` 输出 `pass|uncertain|fail` 和 evidence；任一 `fail` → `exclude`，全 `pass` → `include`，其余 → `hold`。不得输出总分或排序，也不得因为角色不同而省略任何维度。
- `one_sentence_clarity` 与 `immediate_share_trigger` 必须独立判断；复述准确不能自动抬高分享判断，手工录屏/剪辑/上传的摩擦必须进入分享 evidence。
- 保留实质不同的机制，而不只保留不同的领域标签；如果多个候选复用相同的输入方式、转换骨架、揭示结构或分享产物，curator 必须显式标记同质组并只让有实质差异的代表项获得优先支持。
- 保留所有未进入候选名单的 Concept，并记录它们未进入人工批次的原因。
- 如果第一批与 memory challenger 均没有完整 C4 screen pass Concept，或自动 shortlist 最终为空，控制器仍发布 `concept_refs=[]` 的空 `HumanReviewBatch`，分别写 `all_candidates_failed_concept_screen` 或 `shortlist_empty`，跳过 `waiting` 和评审页面后直接进入 C7。这个 batch 只是证明“没有待审对象”，不会删除任何 Concept、Review 或淘汰原因。

**人工策展：**

- 针对候选名单中的精确修订版本，提供完善的 HTML/CSS/JavaScript 评审页面。
- 普通 reviewer 一次只看到一个 active Concept；它以一张独立项目卡展示标题、Hook，以及“用户做什么 / 软件如何回应 / 为什么会再试或分享”三块精简说明，紧接只属于该 Concept 的评审回执。较长的原始软件、Demo、先例与风险材料默认折叠。不得先展示整批说明，再把所有问题堆到页面底部。
- 评审者先填写一句话复述、建议或自由评论，再用显眼的 `✓ 保留`、`△ 需要修改`、`✕ 不成立` 完成本卡判断；动作只写入现有 `recommendation` 字段。选择后当前卡上滑/淡出，下一卡从卡叠后方进入。必须提供“上一张/目录/稍后再看”，因此动效不会制造不可逆决定。
- 评审者可以整张跳过任意项目；一张卡上的草稿、反应和自由评论必须按精确 Concept revision/hash 隔离，不能串到其他卡。评审者姓名和整批总评可以保持批次级。
- 动效必须尊重 `prefers-reduced-motion`；键盘与移动端都能完成前进、返回、填写和判断。卡片离场只是本地草稿交互，整批提交前仍可回看修改，并继续由服务端进行 exact revision/hash 校验。
- 允许多名具名队友独立评审。
- 收集准确的一句话复述、具体分享对象、`share_impulse=immediate|maybe|no`、`demo_confidence=yes|maybe|no`、轻量反应、自由文本评论，以及可选的保留/修订/拒绝或品味否决理由；`share_impulse=immediate` 时分享对象必填。
- 支持选定的两两比较，但不要求完成所有可能的配对。
- 当前评审者提交之前，不得展示更早评审者的答案。
- 普通 reviewer 能看到原始 `Software Core and Runtime`、`Minimum Hackathon Demo` 和 `Share Trigger and Artifact`，但首次提交前看不到机器 C4F verdict、peer feedback、Idea Memory 来源或历史淘汰标签；Percy 的策展模式可以查看完整 C4F evidence、逐人原始人工信号、来源、变换说明和 copy-risk，C7 最终完整披露。
- 每次提交都要绑定到确切的运行、评审轮次、Concept 修订版本和内容哈希；重试必须幂等，历史评审不可变。
- Percy 可以合并、拒绝、保留分歧、行使品味否决权，并关闭评审轮次。
- Percy 使用同一页面中的独立策展模式查看覆盖情况和已提交的原始反馈，选择允许注入 Agent 的反馈、配置 merge、填写覆盖例外原因并关闭轮次；普通 reviewer 始终看不到这些控制项。

**反馈引导的修订：**

- `keep` 将精确 Concept 修订原样提升，不调用模型；只有 `revise` 或 `merge` 才启动一个全新的 Agent Session。
- 新 Session 只能获得已绑定的 Concept、Percy 明确批准的相关反馈片段和/或 Percy 的策展指令、Creative Brief、Constraint View 和必要的先例证据；每个 `revise/merge` 至少需要一项具体的人类指导。
- 人类评论作为不受信任的数据引用；它们不能改变工具、网络策略、来源允许列表、输出路径或工作流规则。
- 下一修订版本要说明它采纳、拒绝或认定相互矛盾的反馈。
- 每个受支持 Creative contract 最多允许一次由反馈驱动的修订。

**输出：** `HumanReviewBatch`、不可变的评审提交、一份评审决议，以及最终的 `CreativeIdea` 修订版本。

**关卡：** 评审轮次已被明确关闭，并且每个最终 Idea 都拥有指向其所使用反馈的有效版本/哈希谱系。

### C7. 确定性 Idea 报告

**目的：** 生成可检查的结果，同时禁止最终 Agent 重写历史或捏造质量结论。

**行为：**

- 控制器代码在不启动 Codex 的情况下验证并渲染报告。
- 包含：
  - Challenge 和 Creative Brief；
  - 所有领域和已生成的 Concept；
  - Cheap Hook、Idea Memory 和 Novelty 的结果；
  - 每个 revision 的修复、合并、淘汰、处置原因码、证据引用和基础设施失败；
  - 自动生成候选名单的理由；
  - 人工评审覆盖情况和原始反馈引用；
  - 反馈处理情况和最终 Idea Card；
  - 未解决的分歧和推迟处理的风险；
  - 路线、Prompt、筛选和报告策略版本。
- 有效运行可以零个最终 Idea 结束，但必须写出稳定的 `zero_reason_code`，区分没有生成 Concept、所有候选未通过完整 C4 Concept screen、自动 shortlist 为空和人类全部拒绝/否决。新 v2 使用 `all_candidates_failed_concept_screen`；旧 v1 冻结 run 继续保留并识别 `all_candidates_failed_hook`，不得重写历史。
- 控制器为每个正常完成的 run 确定性生成 `creative-memory-record.json`，覆盖最终项、未入 shortlist 项和被淘汰项；它只保存有界的 Concept 结构、结果类别、原因码、与原因码绑定的机器评审证据摘录及可验证来源，不保存 reviewer 身份或未批准原始反馈。
- 在发布第一个最终文件之前，控制器先把报告、Idea Cards、handoffs 和 Memory Record 的精确字节、ID、路径及 hash 冻结为 C7 finalization plan。中途崩溃时 `resume` 只能幂等重放该 plan，不能重新渲染、调用模型或使用新时间；全部产物与 ledger event 就绪后才能标记 `completed`。
- 若某个必需任务发生致命基础设施或协议失败，run 仍保持 `failed`，但控制器根据当时已经持久化的内容生成确定性的 partial report；partial report 不包含最终 Idea Card，也不得把 run 标为完成。

**输出：** 成功运行生成确定性的 `creative-idea-report.md`、机器可读摘要和 `creative-memory-record.json`；失败运行生成 `creative-partial-report.md` 和对应摘要，任何版本的 partial run 都不进入未来 Idea Memory。

## 候选项与产物策略

- 稳定 ID 由控制器掌控，且不受并行完成顺序影响。
- 每个长篇产物都有路线类型、修订版本、来源引用、内容哈希、生产者类型，以及不可变的前序快照。
- 必须如实表示人类和 Agent 生产者；人工评审不得伪造 Codex Session 标识符。
- 自动评审者不得读取同级评审结果，除非后续明确规定的聚合阶段要求读取。
- Creative 允许相对比较和顾及多样性的候选名单筛选；Useful 路线对排名、合并和 Top-K 的专属禁令并不是共享 Harness 规则。
- 候选项数量、候选名单大小和 fanout 默认值均可配置并由基准调优，而非永久不变的产品约束。
- 缺失或失败的工作绝不能被解释为空候选集或自动拒绝。
- 跨 run 来源使用 `source_run_id + route/contract + artifact ID/hash + memory record hash` 组成的复合引用；裸 artifact ID 不能跨 run 解析。
- Idea Memory 只是 route-owned 的输入快照与产物，不扩张共享 Harness 为全局知识库。

## 基准与评估

基准在相同挑战和模型预算下，将完整工作流与一次性 Creative Idea 生成基线进行比较。

### 阶段级检查

- **C0：** 硬性规则召回率、无依据推断率和约束漂移。
- **C1：** 与 Percy 预期反应及反目标的一致性，以及 frozen Software Demo Policy 的版本/hash 完整性。
- **C2：** software-native 机制实质不同的数量，而非标题多样性；旧 spatial/performance/cross-media lens 不得作为独立目标回流。
- **C3：** 从铺垫到揭示的完整路径、software-first 合格率、冷启动 30 秒路径覆盖率、端到端技术路径完整率、关键子系统/最高风险假设/降级切片/预置成本覆盖率，以及具体 share artifact 覆盖率。
- **C4：** C4H/C4F 的 `pass|repairable|invalid` 分布与原因码；定制硬件和纯装置 fixture 的 false-pass、合法普通设备 I/O fixture 的 false-reject、标准 Web API 但现场不稳定的 false-pass、可修复缺信息 fixture 是否只使用一次 repair，以及手工录屏传播摩擦是否被正确识别。
- **C5：** 历史线索命中率、challenger 的非复制变换与 C4F 通过率、旧硬件模式再引入率、完整 C4 screen 后进入 C5W 的任务数及 token/wall-time 节省、有价值外部碰撞和引用有效性。
- **C6：** C6B categorical 维度分布、shortlist 中 `immediate_share_trigger=pass` 的占比、复述与分享判断的独立一致性、跨候选核心机制重复率、候选名单多样性、评审负担、一句话复述准确度、`share_impulse=immediate`、具体分享对象、`demo_confidence=yes`、困惑率、人类分歧，以及依据反馈修订的忠实度。
- **C7：** 谱系完整性、报告确定性，以及对每条候选项分支的完整记录。

### 端到端检查

- 盲测评审者在 30 秒的概念演示后，能够准确复述 Idea。
- 评审者会自发想到一个想把它展示给对方的具体人物。
- 惊喜被归因于可理解的交互或揭示，而不是困惑或解释性文案。
- Idea 会让人产生亲自互动或观察他人反应的欲望。
- 评审者相信最小软件 Demo 能在比赛时间内跑起来，并能指出技术机制，而不是主要依赖文案、主持人或布景；该判断始终标为 Build 前代理信号。
- 最终组合包含机制上实质不同的创意构想。
- 工作流产出获得的人类偏好高于一次性基线，且不会隐瞒显著增加的 token、时间或评审成本。
- 在摘要之外保留人类反馈的原始措辞。
- 构想阶段的复述/分享指标始终标注为代理指标，而不是实际传播力的证明。
- Memory-on/off 消融能区分“工作流本身”与“历史积累”带来的收益；benchmark 两个 arm 必须冻结同一份历史快照，禁止前一个 arm 的输出泄漏给后一个 arm。

离线 fixture 必须至少覆盖：浏览器/WebSocket 软件正例、普通设备 camera/mic 正例、定制硬件反例、纯装置/人工表演反例、Figma/预录/wizard-of-oz 伪技术反例、不可得权限反例、缺 Demo cut 的可修复例，以及能运行但缺少 surprise/share trigger 的弱 viral 例。

Percy 稍后将继续提供真实的 hackathon 挑战用于实际评估。默认自动化测试套件保持离线；付费/在线 Codex 基准运行必须显式选择启用。

Benchmark 的 `live` 模式经过正式 C6 团队评审后才计算人类指标；离线 `fixture` 模式只验证状态机与报告，必须明确标记为合成输入，不能伪装成真实 reviewer 或产品效果证据。

## 协作与 Git 工作流

- Weston 负责 Useful 路线的产品决策，并可继续修改其 Prompt、拓扑和基准。
- Percy 负责 Creative 路线的产品决策、Creative 基准判断和最终品味决策。
- 在添加 Creative 使用方之前，共享 Harness 变更必须有证明 Useful 行为保持不变的测试。
- 路线专属文件、阶段 ID、Prompt、产物目录和测试保持隔离，以尽量减少合并冲突。
- 同步 `origin/main`：
  - 工作会话开始时；
  - 冻结 `design.md` 之前；
  - 实现验证之前；
  - 推送或创建 PR 之前。
- 集成上游变更之前，检查它们是否与未提交文件重叠；绝不丢弃或悄然吸收 Weston、Trellis 或 onboarding 的变更。
- 优先采用易于评审的实现切片：
  1. 路线契约与精简的 Harness 抽取；
  2. Creative C0-C5 生成/筛选/历史记忆/研究流水线；
  3. C6 修订与人工策展；
  4. C7 报告、基准 fixture 和端到端验证。
- 每个切片都必须说明哪些共享契约发生了变化，以及运行了哪些 Useful 回归测试。

## 验收标准

- [ ] 运行会被明确创建为 `route.id=creative`，可以在不依赖 Useful 专属假设的情况下检查和验证，并只在 C6 已关闭的人审等待点继续。
- [ ] C0 将硬性挑战约束与创意解释分开保留。
- [ ] C1 记录明确的预期反应、反目标、交互场景和歧义边界。
- [ ] 每个新 Creative run 持久化并 hash/freeze 可见的 Software Demo Policy；C1/C2/C3/C4H/C4F/C5M Remix/C6A/C6B 使用同一精确版本，且 C1 不增加人工暂停。
- [ ] 默认 Policy 只淘汰定制硬件、实体制作、专用设备和纯人工装置核心；普通电脑/手机及其内置 camera/mic/screen/touch 等 I/O 合法。
- [ ] C2 在不受先例锚定且不强制要求商业痛点的情况下，使用六个 software-native lens 产出多个实质不同的创意领域。
- [ ] C3 产出版本化 Concept，包含完整的 30 秒铺垫、受众行动、揭示、机制、余韵、Software Core and Runtime、Share Trigger and Artifact 及可执行 Minimum Hackathon Demo。
- [ ] C0 未提供更明确资源时，C3/C4F 使用 2 人/24 小时、至多一个简单 backend 和一个主要浏览器/设备切片的保守参考预算；Concept 明示冷启动 30 秒路径、关键子系统、最危险技术假设、降级切片和预置状态成本。
- [ ] 每个 base Concept 和 memory challenger 的 `primary_territory_ref` 都属于其 current Parent Atoms；C4/C6 revision 与 C6B curator 不能重写该值，merge 只能从 source primary refs 中选择。
- [ ] 当前 run 的第一批 C2/C3 与初始 C4 判断冻结之前，Controller 不向其 Prompt、parent refs、registered context 或 stage input 注入过去 Idea、历史淘汰原因或外部先例；合同与测试不把 Codex `read-only` sandbox 误称为 chroot，且明确禁止这些 Session 主动扫描 run 历史。
- [ ] 每个初始或 repaired Concept revision 恰好有两份 fresh C4H 和一份 fresh C4F，三者互相看不到结果；只有全部 `pass` 才继续。
- [ ] 明确定制硬件、实体制作或纯装置/人工核心的 Concept 以 `c4_software_demo_invalid` 终态淘汰，不启动 C5W/C6A/C6B/人审；缺少可修复细节时共享现有一次 C4 repair，不能改写三个 identity section 偷换软件核心。
- [ ] C5M 从当前 run 创建时冻结、hash 绑定的 completed Creative memory record 中选择线索；无历史或 `--idea-memory off` 时不调用 Recall Agent，且行为退化为原始流程。
- [ ] C5M 最多生成两个“当前 Atom × 历史线索”的 challenger，不递归读取 memory；每个 challenger 具有新身份、完整来源和变换说明，并重新通过与普通 Concept 相同的 C4H+C4F/C5W。
- [ ] C5M Remix 使用 all-settled：一成一败时保留已验证 challenger，失败 sibling 留下可核验 optional diagnostic；只有带 C5M allowlist policy 与匹配 event 的 failed task 可存在于 completed run。
- [ ] C5W 只对完整 C4 screen pass 的初始/Memory Remix Concept 联网，并记录有引用的现有成果、碰撞、陈词滥调和独特性证据；它不输出 feasibility route decision。
- [ ] C6A 接收 feasibility/novelty evidence，并把抽象描述收敛为可识别的产品循环；C6B 两位 Red Team 分别审查“意义/价值/反装置”与“真实展厅是否好玩、想试”，同时都完整使用 software demo、surprise/fun、clarity、share-trigger、novelty categorical evidence，不输出 1–10 总分或排序。
- [ ] C4H/C6B 分别判断一句话复述与立即分享，不把“可手工录屏”视为低摩擦分享证据；C6B 还要识别跨 Territory 标签重复的输入、转换、揭示或分享机制，避免同质候选占满 shortlist。
- [ ] 每个 completed run 中的 Concept revision 恰好有一个 terminal disposition；它能区分 Hook 淘汰、被修订取代、未入选、提升为 Final、依据反馈改写、人工拒绝、taste veto 与合并，并在存在后继时引用确切的新 revision 或 Final Idea。
- [ ] 没有待审 Concept 时仍生成带 `skip_reason` 的空 C6 batch，不进入人工等待；v2 完整 screen 为空使用 `all_candidates_failed_concept_screen`，所有 Hook/Feasibility 判断与淘汰原因仍出现在 C7。
- [ ] 多名具名评审者可以用单卡接力界面评估候选名单中的精确修订版本；描述与本卡评审一一相邻，`✓/△/✕` 后卡片离场并进入下一项，且可返回修改。每份回执记录一句话复述、`share_impulse`、`demo_confidence` 与具体分享对象，且 `immediate` 必须填写对象。
- [ ] 成对比较完全可选：评审者可以回答任意子集，也可以全部跳过，未回答的 pair 不被解释为平局、拒绝或缺失回执。
- [ ] 每个 reviewer 在首次提交前看不到他人答案；提交后的团队视图与 Percy 策展权限不会因共享链接或 cookie 混淆身份。
- [ ] 普通 reviewer 首次提交前能看原始软件 Demo 路径，但无法读取 C4F verdict、peer feedback 或 memory provenance；Percy curator 能审查完整 feasibility evidence、原始人类信号、历史来源、借用/规避内容和 copy-risk。
- [ ] Percy 可以关闭一轮评审；每个 `revise/merge` 决议最多生成一个与版本绑定的反馈修订并记录反馈处理情况，`keep` 不会被模型悄然重写。
- [ ] 关闭轮次只冻结 resolution；`keep/revise/merge` 的目标 Final Idea 在 `resume` 中成功验证并发布后，才允许写带目标引用的 terminal disposition，失败不得被预记为成功。
- [ ] revision ledger 能证明每个 base Concept 和 memory challenger 最多发生一次 C4 Hook 修复、一次 C6 证据修订和一次 C6 人类反馈修订，重试不会额外消耗或绕过这些预算。
- [ ] C6 等待期间即使代码库同步更新，`resume` 仍使用 run 创建时冻结并校验的 Prompt/Schema；已存在的 v1 waiting run 继续使用 v1 review/report/zero-reason 合同，新 run 使用 software-first v2，禁止用 v2 资源重解释 v1 字节。
- [ ] C7 确定性地记录每个已生成、失败、修复、合并、淘汰、进入候选名单、接受评审和最终保留的候选项；零 Idea 报告逐项列出最终淘汰阶段、原因码和证据，并包含稳定 `zero_reason_code`。
- [ ] C7 在任何最终产物发布前冻结包含精确 bytes/hash 的 finalization plan；逐文件发布中断后可以不调用模型地幂等恢复，且只有全部计划产物和事件就绪后才能进入 `completed`。
- [ ] 每个 completed Creative run 生成可验证的 `creative-memory-record.json`；completed 的零 Idea run 可贡献 caution 线索，failed/waiting/fixture/Useful/篡改来源和未批准原始人类反馈均不能进入下一次运行。
- [ ] Memory Record 区分 C4 Hook caution、hardware/install/manual/dependency/scope/core-proof feasibility caution、自动 curator 支持不足、仅因 portfolio 容量未入选、人类主观否决、merge 变换和 final 正向模式，未来 Agent 不会把这些结果压成同一种“失败”。
- [ ] 当前 run 在创建时复制并哈希 Idea Memory Snapshot；之后新增、删除或修改历史 run 不改变本 run 的 Memory Recall、resume 或报告。
- [ ] fatal run 保持 `failed`，同时生成不把任何未完成 finalization 产物暴露为有效结果的确定性 partial report，不丢失已持久化的候选和错误信息。
- [ ] 一次有效完成的运行可以包含零个最终 Idea。
- [ ] 基准输出与一次性基线比较，并报告 software false-pass/false-reject、C5W 成本变化、质量、多样性、share impulse、retell、demo confidence、token/时间成本、评审负担及不完整覆盖；后两类人类字段明确是代理信号。
- [ ] 共享 Harness 变更始终保持当前 Useful v1 的行为、CLI 默认值和已有 v1 运行检查能力不变；不承诺兼容已被 Weston 架构重写淘汰的旧 S0-S11 运行。
- [ ] 每张最终 Creative Idea Card 都能生成稳定、hash 绑定的纯 JSON Build handoff，但 Idea route 不 import 或启动 Build runtime。
- [ ] 离线测试覆盖路线分派、状态转换、产物/哈希完整性、有界循环、确定性排序、人工等待/恢复、反馈注入隔离和报告确定性。
- [ ] 浏览器 QA 覆盖 C6 评审页面的桌面端/移动端、键盘操作、保存/恢复、空白/错误/过期状态和减少动态效果。
