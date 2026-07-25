"use strict";

const STAGE_DATA = Object.freeze(JSON.parse(String.raw`
[
  {
    "stageId": "C0",
    "title": "挑战与约束",
    "phase": "ORIENT",
    "actors": ["controller", "model"],
    "preview": "把原始赛题拆成中立 Brief 与可追溯 Constraint View。",
    "goal": "先固定赛题允许、要求和含糊之处，避免赞助商措辞直接变成预设产品。",
    "why": "后续每个 Agent 都需要同一份中立事实边界；来源事实与推断必须分开。",
    "inputs": ["用户提供的原始 challenge 文本。"],
    "actions": [
      "Controller — 创建 1 个 fresh task，保存精确 Prompt 与 Schema 绑定。",
      "Model — 一次解析同时返回 challenge_brief_markdown 与 constraint_view_markdown；不分配 artifact ID。",
      "Controller — 校验结构后发布两个稳定、hash-bound 的 Markdown artifact。"
    ],
    "outputs": [
      "artifacts/creative/challenge/creative-challenge-brief-r001.md",
      "artifacts/creative/challenge/creative-constraint-view-r001.md"
    ],
    "fanout": "1 个必需的 fresh Model Session；没有 Web，也没有 Human。",
    "gate": "两份文档都必须非空、满足 Markdown/结构语义并与同一 task 绑定。",
    "failureSemantics": "Prompt、Schema、模型执行或语义校验失败均为 fatal：run 标记 failed，发布 partial report，不进入 C1。",
    "promptFiles": ["src/hacksome/stages/ideation/creative/prompts/creative-challenge-parse.md"],
    "schemaFiles": ["src/hacksome/stages/ideation/creative/schemas/creative-challenge-parse.schema.json"],
    "codeFiles": [
      "src/hacksome/stages/ideation/creative/workflow.py",
      "src/hacksome/stages/ideation/creative/artifacts.py",
      "src/hacksome/stages/ideation/creative/prompting.py"
    ],
    "architecture": {
      "status": "必需 · fatal",
      "summary": "单次模型解析，Controller 持有 ID、路径、hash 与发布。",
      "diagnostic": "模型正文不是路由数据库；稳定 lineage 由 Hub 元数据拥有。",
      "tone": "controller"
    },
    "actualRun": {
      "status": "完成",
      "summary": "B 站 challenge 已被固定成后续阶段共同读取的 Brief 与 Constraint View。",
      "diagnostic": "本节点没有异常分支；后续 7 个 Concept 都继承这组约束。",
      "rail": "completed",
      "tone": "controller"
    },
    "misconception": "误解：C0 已经在选 Idea。实际：它只中立解析赛题，不产出解决方案。"
  },
  {
    "stageId": "C1",
    "title": "创意简报与软件边界",
    "phase": "ORIENT",
    "actors": ["controller", "model"],
    "preview": "规范化 Percy 的方向，同时由 Controller 冻结不可稀释的软件 Demo Policy。",
    "goal": "在生成前写清期待反应、反目标、场景与 30 秒揭示窗口，并冻结 software-first 边界。",
    "why": "Creative Brief 表达品味方向；Software Demo Policy 是权威运行事实，两者不能互相替代。",
    "inputs": [
      "C0 Challenge Brief 与 Constraint View。",
      "Percy 提供的 Creative Brief；未提供时使用可见默认文本。",
      "Controller-owned Software Demo Policy 的精确 bytes/hash。"
    ],
    "actions": [
      "Controller — 在 run 创建时写入并冻结 creative_brief input 与 Software Demo Policy。",
      "Model — 1 个 fresh Session 规范化 Brief；可以收紧方向，不能放宽 Policy。",
      "Controller — 单独发布 creative-brief-r001；Policy 继续作为 input artifact 被 C1、C2、C3、C4H、C4F、C5M Remix、C6A 与 C6B 复用。"
    ],
    "outputs": [
      "artifacts/creative/brief/creative-brief-r001.md",
      "input/software-demo-policy.json（Controller-owned、hash-bound）"
    ],
    "fanout": "1 个必需 Model Session；C1 不暂停等待批准，C6 仍是唯一人工关卡。",
    "gate": "Brief 必须含正向体验、反目标和可指导独立探索的场景；Policy 版本、路径和 hash 与 run metadata 闭合。",
    "failureSemantics": "规范化或绑定失败为 fatal；不会把 C1 变成第二个 Human-in-the-loop gate。",
    "promptFiles": ["src/hacksome/stages/ideation/creative/prompts/creative-brief-normalize.md"],
    "schemaFiles": ["src/hacksome/stages/ideation/creative/schemas/creative-brief-normalize.schema.json"],
    "codeFiles": [
      "src/hacksome/stages/ideation/creative/workflow.py",
      "src/hacksome/stages/ideation/creative/contracts.py",
      "src/hacksome/stages/ideation/creative/artifacts.py"
    ],
    "architecture": {
      "status": "必需 · fatal",
      "summary": "Model 规范化品味方向；Controller 独立拥有、冻结并传播 Software Demo Policy。",
      "diagnostic": "Policy 的控制器发布动作没有额外模型 Prompt；C1 的 Prompt 只用于 Brief normalization。",
      "tone": "controller"
    },
    "actualRun": {
      "status": "完成",
      "summary": "B 站运行冻结了 Creative v3 Brief 与同一份 software-first Policy，供后续生成和审查读取。",
      "diagnostic": "这一步没有人工批准；真实回执只会在 C6 Human 出现。",
      "rail": "completed",
      "tone": "controller"
    },
    "misconception": "误解：Creative Brief 写了 software-first 就足够。实际：Controller-owned Policy 才是不可被模型改写的权威边界。"
  },
  {
    "stageId": "C1W",
    "title": "文化信号扫描",
    "phase": "SENSE",
    "actors": ["controller", "model", "web"],
    "preview": "一次联网扫描；原始来源进 snapshot，C2/C3 只收脱敏 safe palette。",
    "goal": "在生成前提供少量近期、可追溯的参与模式，而不是拿趋势证明需求或 virality。",
    "why": "把“从当下文化获得灵感”变成可审计输入，同时隔离 URL、标题、平台与表面梗。",
    "inputs": [
      "C0 Challenge Brief、Constraint View 与 C1 Creative Brief。",
      "as_of_utc=run.created_at 的固定 30-day scan window。"
    ],
    "actions": [
      "Controller — 只启动 1 个 optional task，并固定窗口、parent refs 与 web_search=true。",
      "Model + Web — 检索信号及来源，返回严格时间戳、全局唯一 canonical URL 与 confidence。",
      "Controller — 语义校验来源、时间、窗口和跨 signal URL；发布唯一 raw snapshot。",
      "Controller — 按 slot 确定性投影 safe palette，删除 URL、标题、publisher、platform、label 与 surface copy。"
    ],
    "outputs": [
      "artifacts/creative/cultural-signals/creative-cultural-signal-snapshot-r001.json",
      "注入每个 C2/C3 Prompt 的 CULTURAL_SIGNAL_PALETTE（不另存 raw 副本）",
      "失败时唯一 optional_cultural_signal_stage_failed diagnostic event"
    ],
    "fanout": "1 个联网 Model Session；每个 C2 slot 最多 2 inspire + 2 avoid，每个 C3 slot 最多 2 inspire。",
    "gate": "Snapshot 只能是 ready、partial、empty 或 unavailable；high-confidence signal 必须至少有两个来源，URL 跨整个 signals[] 全局唯一。",
    "failureSemantics": "optional / fail-open。执行失败或语义 invalidation 保留 failed/invalidated task，发布 status=unavailable 的显式空 snapshot，主线继续到 C2。",
    "promptFiles": ["src/hacksome/stages/ideation/creative/prompts/creative-cultural-signal-scan.md"],
    "schemaFiles": ["src/hacksome/stages/ideation/creative/schemas/creative-cultural-signal-scan.schema.json"],
    "codeFiles": [
      "src/hacksome/stages/ideation/creative/workflow.py",
      "src/hacksome/stages/ideation/creative/signals.py",
      "src/hacksome/stages/ideation/creative/artifacts.py"
    ],
    "architecture": {
      "status": "可选分支 · fail-open",
      "summary": "唯一联网扫描先进入 hash-bound raw snapshot，再由 Controller 生成安全投影。",
      "diagnostic": "搜索结果存在不等于 snapshot 可用；Agent output 还必须通过 Controller semantic validator。",
      "tone": "signal"
    },
    "actualRun": {
      "status": "INVALIDATED → CONTINUE",
      "summary": "B 站运行中，一个 high-confidence signal 只有一个来源；整批输出被作废，snapshot=status=unavailable。",
      "diagnostic": "C2/C3 收到空 palette。琥珀断路代表 optional branch 失败；持续的主轨代表生成没有停止。",
      "rail": "broken / empty palette",
      "tone": "signal"
    },
    "misconception": "误解：热点搜索成功，只是 C2/C3 没采用。实际：Controller 没有接受该批信号，后续拿到的是显式空 palette。"
  },
  {
    "stageId": "C2",
    "title": "创意领域与原子",
    "phase": "DIVERGE",
    "actors": ["controller", "model"],
    "preview": "6 个独立 software-native lens 并发探索；此时不研究先例。",
    "goal": "先扩展机制空间，再组合完整产品，减少一开始就收敛到熟悉 AI 产品的风险。",
    "why": "多样性来自软件因果和互动机制，不来自换题材、换视觉或给同一循环改名字。",
    "inputs": [
      "C0 Challenge Brief、Constraint View、C1 Creative Brief。",
      "同一份 Software Demo Policy。",
      "每个 slot 自己的 C1W safe palette；empty/unavailable 仍注入同 shape 空 block。",
      "6 个稳定 software-native Territory lens。"
    ],
    "actions": [
      "Controller — 在调用前固定 6 个 slot 与 lens；内部 Territory ID 不注入 Prompt。",
      "Model — 6 个 fresh、彼此隔离、禁止联网的 Session 并发探索，每个最多返回 3 个 Atom。",
      "Controller — 校验 output 后分配 Territory/Atom 稳定 ID，并在 metadata 中绑定 atom→territory lineage。"
    ],
    "outputs": [
      "artifacts/creative/territories/creative-territory-*.md",
      "artifacts/creative/atoms/creative-atom-t*-*.md"
    ],
    "fanout": "默认 6 个独立 Model Session × 每个最多 3 Atom；全局并发有界，完成顺序不改变 ID。",
    "gate": "每个必需 task 的 Schema/Markdown/谱系必须有效；零 Atom 是合法空输出，C3 将自然变空。",
    "failureSemantics": "任何必需 task 执行或语义失败都是 fatal；不会把 task failure 当成“这个 lens 没点子”。",
    "promptFiles": ["src/hacksome/stages/ideation/creative/prompts/creative-territory-explore.md"],
    "schemaFiles": ["src/hacksome/stages/ideation/creative/schemas/creative-territory-explore.schema.json"],
    "codeFiles": [
      "src/hacksome/stages/ideation/creative/workflow.py",
      "src/hacksome/stages/ideation/creative/contracts.py",
      "src/hacksome/stages/ideation/creative/artifacts.py"
    ],
    "architecture": {
      "status": "6-way fanout · fatal",
      "summary": "独立生成 Territory/Atom；禁止 Web、Idea Memory 与先例研究。",
      "diagnostic": "Atom 正文是否写出 Territory ID 不决定 lineage；Controller 元数据才决定。",
      "tone": "model"
    },
    "actualRun": {
      "status": "完成 · EMPTY PALETTE",
      "summary": "B 站运行继续执行 C2，但每个 slot 收到的 C1W safe palette 都为空。",
      "diagnostic": "因此后续 Concept 没有使用网络梗，不是模型主动忽略了一个可用 palette。",
      "rail": "6 slots / no signals",
      "tone": "controller"
    },
    "misconception": "误解：C2 在选最终产品。实际：它只生产 Territory 和创意原子，不做 shortlist。"
  },
  {
    "stageId": "C3",
    "title": "Concept 综合",
    "phase": "SYNTHESIZE",
    "actors": ["controller", "model"],
    "preview": "4 个互斥产品语法各自综合 Concept；无法诚实满足时允许返回零项。",
    "goal": "把 Atom 组合成一眼可解释、software-first、能在 hackathon 跑真实 Demo 的完整 Concept。",
    "why": "四个稳定 product grammar 以“软件回应后用户的下一动作”切分，防止四个 Agent 生成同一种产品换皮。",
    "inputs": [
      "C0/C1、Software Demo Policy 与 Controller 生成的完整 Atom index。",
      "四个固定 assignment：explorer_simulator、realtime_partner、social_game_relay、creator_transformer。",
      "每个 slot 自己的 C1W safe palette；本次为空。"
    ],
    "actions": [
      "Controller — 绑定 4 个稳定 grammar slot 和 expected product grammar ID。",
      "Model — 4 个 fresh、彼此隔离、禁止联网的 Session 并发综合，每个最多 3 个 Concept。",
      "Model — 每个 Concept 写三句 plain-language loop、Software Core、Share Trigger、Minimum Hackathon Demo 与 Parent Atoms。",
      "Controller — 校验 exact grammar marker、Parent Atom/primary Territory；task 内重复使输出 invalidated，跨 synthesizer 的 exact Markdown/Hook 重复会跳过且不产生 disposition。"
    ],
    "outputs": ["artifacts/creative/concepts/creative-concept-s*-*-r001.md"],
    "fanout": "默认 4 个独立 Model Session × 每个最多 3 Concept；某个 grammar 无诚实组合时可以返回零项。",
    "gate": "必需 H2、software-first 字段、Parent refs 与当前 slot 的 exact grammar marker 必须闭合；不满足是 invalid output，不是 candidate reject。",
    "failureSemantics": "必需 task/schema/semantic failure 为 fatal；所有 Session 合法返回零 Concept 时，Controller 后续发布空 batch 并在 C7 生成零 Idea。",
    "promptFiles": ["src/hacksome/stages/ideation/creative/prompts/creative-concept-synthesize.md"],
    "schemaFiles": ["src/hacksome/stages/ideation/creative/schemas/creative-concept-synthesize.schema.json"],
    "codeFiles": [
      "src/hacksome/stages/ideation/creative/workflow.py",
      "src/hacksome/stages/ideation/creative/contracts.py",
      "src/hacksome/stages/ideation/creative/artifacts.py"
    ],
    "architecture": {
      "status": "4-way fanout · fatal",
      "summary": "四种互斥 primary product loop 负责组合 Concept，Controller 绑定 grammar 与谱系。",
      "diagnostic": "Controller 只机械校验 assigned marker、Parent refs 与 Markdown shape；它不理解或证明真实 product loop 分类。一句话写得清也不是 30 秒陌生观众实验。",
      "tone": "model"
    },
    "actualRun": {
      "status": "7 CONCEPTS",
      "summary": "B 站运行的 4 个综合 slot 共发布 7 个 Concept；它们全部基于空 cultural palette。",
      "diagnostic": "7 是 C3 发布数，不是 C4 pass 或最终候选数。",
      "rail": "7 concepts",
      "tone": "model"
    },
    "misconception": "误解：四个 slot 是“更清晰 / 更神秘 / 更病毒”的软风格。实际：它们是互斥的核心产品循环责任。"
  },
  {
    "stageId": "C4",
    "title": "Hook / Share / Demo 闸门",
    "phase": "SCREEN",
    "actors": ["controller", "model"],
    "preview": "每个 revision 同时接受 2 份 Hook 审查和 1 份 Demo 可行性审查。",
    "goal": "在联网查重和人审前，淘汰看不懂、无立即分享触发物或核心 Demo 不可真实运行的 Concept。",
    "why": "可讲的诗意装置不能冒充软件产品；retell、share 与 software feasibility 必须分别取证。",
    "inputs": [
      "一个 exact Concept revision 与 hash。",
      "Constraint View、Creative Brief 与同一份 Software Demo Policy。"
    ],
    "actions": [
      "Controller — 为每个 revision 并行启动 2 个 fresh C4H Hook/Share reviewer 和 1 个 fresh C4F Software Demo reviewer；三者互相看不到结果。",
      "Model — C4H 独立给出七维 pass/repairable/invalid；C4F 按固定 dimension→reason code 审查 software-first、依赖、预算与真实端到端路径。",
      "Controller — 只有 2×C4H pass 且 C4F pass 才放行；hard C4F invalid 或双 C4H invalid 直接淘汰。",
      "Model — 其他非 pass 形状共享最多 1 次 C4R 局部修复；修复后重新启动完整 fresh 2+1 审查。",
      "Controller — 记录 decision、evidence refs 与每个 revision 的 disposition。"
    ],
    "outputs": [
      "artifacts/creative/cheap-hook-reviews/creative-hook-review-*.json",
      "artifacts/creative/software-demo-reviews/creative-software-demo-review-*.json",
      "必要时 artifacts/creative/concepts/*-r002.md",
      "artifacts/creative/dispositions/creative-disposition-*.json"
    ],
    "fanout": "每个 revision 固定 2×C4H + 1×C4F 并行；每个 Concept 最多 1 次 repair，repair 后再跑完整 2+1。",
    "gate": "仅三份 review 全 pass 才进入 C5W/C6；hard software invalid 与 unresolved-after-repair 都是 terminal elimination。",
    "failureSemantics": "模型 task/schema failure 为 fatal；合法 invalid/reject 是成功 task + 明确淘汰。修复不能改写 Intended Reaction、Real Input/Transformation/Output 或 Parent Atoms。",
    "promptFiles": [
      "src/hacksome/stages/ideation/creative/prompts/creative-cheap-hook-review.md",
      "src/hacksome/stages/ideation/creative/prompts/creative-software-demo-review.md",
      "src/hacksome/stages/ideation/creative/prompts/creative-cheap-hook-repair.md"
    ],
    "schemaFiles": [
      "src/hacksome/stages/ideation/creative/schemas/creative-cheap-hook-review.schema.json",
      "src/hacksome/stages/ideation/creative/schemas/creative-software-demo-review.schema.json",
      "src/hacksome/stages/ideation/creative/schemas/creative-cheap-hook-repair.schema.json"
    ],
    "codeFiles": [
      "src/hacksome/stages/ideation/creative/workflow.py",
      "src/hacksome/stages/ideation/creative/artifacts.py",
      "src/hacksome/stages/ideation/creative/contracts.py"
    ],
    "architecture": {
      "status": "2+1 review · ≤1 repair",
      "summary": "独立模型给 evidence；Controller 用固定矩阵路由 pass、repair 或 terminal elimination。",
      "diagnostic": "C4H 读的是完整 Concept dossier，不是让陌生人只看 30 秒后复述。",
      "tone": "model"
    },
    "actualRun": {
      "status": "7 → 2 PASS",
      "summary": "B 站运行有 7 个 Concept 进入；一次有界修订完成后，只有 2 个通过完整 C4 screen。",
      "diagnostic": "淘汰不是 Top-K：每个 Concept 都对同一绝对门槛取证。",
      "rail": "7 in / 2 pass",
      "tone": "model"
    },
    "misconception": "误解：C4 是一个模型给总分。实际：三个 fresh reviewer 输出分类证据，Controller 执行固定聚合矩阵。"
  },
  {
    "stageId": "C5",
    "title": "Memory 分支与联网查重",
    "phase": "GROUND",
    "actors": ["controller", "model", "web"],
    "preview": "可选历史灵感最多产生 2 个 challenger；所有 C4 pass 再逐项联网查重。",
    "goal": "在初始生成完成后才借用历史机制与外部先例，既减少锚定，又为 C6A 提供真实 novelty evidence。",
    "why": "过去的 Idea 是材料而非答案；文化信号也不能代替 fatal 的先例与撞车审查。",
    "inputs": [
      "冻结的 Idea Memory Snapshot（可以 off 或 empty；hash/provenance 损坏不是合法空输入）。",
      "C2 Atom、全部 base Concept disposition 与 C4 pass 集。",
      "C5W 读取 Challenge Brief、Creative Brief 与每个 exact C4-pass revision。"
    ],
    "actions": [
      "Controller — 如有合格历史，最多启动 1 个 C5M Recall；off/empty 时不调用模型并发布显式 summary。",
      "Model — Recall 最多选 8 个抽象 cue；随后最多 2 个独立 Remix task 产生 challenger。",
      "Controller — challenger 重新走完整 C4，不能递归读 Memory。",
      "Model + Web — 对 base/challenger 的每个完整 C4 pass revision 各启动 1 个 fresh C5W Novelty Scan。",
      "Controller — 保存来源与 novelty Markdown；C5W 不直接输出 feasibility route decision。"
    ],
    "outputs": [
      "artifacts/creative/memory/creative-memory-inspiration-packet-r001.json（如 Recall 成功）",
      "artifacts/creative/memory/creative-memory-stage-summary-r001.json",
      "可选 artifacts/creative/concepts/creative-concept-m*-r001.md",
      "artifacts/creative/novelty-scans/creative-novelty-*.md"
    ],
    "fanout": "C5M：≤1 Recall、≤8 cues、≤2 Remix challenger；C5W：每个完整 C4 pass 恰好 1 个联网 task。",
    "gate": "C5M 是 optional branch；每个 challenger 仍须通过 C4。C5W 任务数必须与 C4 pass 集相等并生成可验证来源证据。",
    "failureSemantics": "C5M task/semantic failure 记录 diagnostic 后 fail-open，保留成功 sibling；冻结 Memory Snapshot 的 hash/provenance 损坏为 fatal；C5W 执行或验证失败为 fatal，不能伪装成“没有相似先例”。",
    "promptFiles": [
      "src/hacksome/stages/ideation/creative/prompts/creative-memory-recall.md",
      "src/hacksome/stages/ideation/creative/prompts/creative-memory-remix.md",
      "src/hacksome/stages/ideation/creative/prompts/creative-novelty-scan.md"
    ],
    "schemaFiles": [
      "src/hacksome/stages/ideation/creative/schemas/creative-memory-recall-v3.schema.json",
      "src/hacksome/stages/ideation/creative/schemas/creative-memory-remix-v3.schema.json",
      "src/hacksome/stages/ideation/creative/schemas/creative-novelty-scan.schema.json"
    ],
    "codeFiles": [
      "src/hacksome/stages/ideation/creative/workflow.py",
      "src/hacksome/stages/ideation/creative/memory.py",
      "src/hacksome/stages/ideation/creative/artifacts.py"
    ],
    "architecture": {
      "status": "Memory optional / Novelty fatal",
      "summary": "先有界读取历史，再为每个 C4 pass 做联网先例证据扫描。",
      "diagnostic": "C1W 与 C5W 都联网，但前者是可忽略灵感、fail-open；后者是 novelty evidence、fatal。",
      "tone": "signal"
    },
    "actualRun": {
      "status": "2 PASS → NOVELTY EVIDENCE",
      "summary": "B 站运行的 2 个 C4 pass Concept 均具有进入 C6A 所需的 C5W novelty evidence。",
      "diagnostic": "本页不把 C5W 的存在写成“证明绝对新颖”；它只是可追溯的先例与相似性证据。",
      "rail": "2 novelty scans",
      "tone": "signal"
    },
    "misconception": "误解：C5 用历史 Idea 自动替换当前方案。实际：历史分支有界且可空，challenger 必须重走 C4/C5W。"
  },
  {
    "stageId": "C6A",
    "title": "证据修订",
    "phase": "CONVERGE",
    "actors": ["controller", "model"],
    "preview": "每个 C4 pass Concept 恰好生成一个 evidence-informed successor。",
    "goal": "利用 Hook、Demo、Novelty 与相关 memory cue 澄清 Concept，而不改换它的核心身份。",
    "why": "最终自动策展应比较已吸收证据的同代 revision，而不是把初稿 polish 当成质量。",
    "inputs": [
      "每个完整 C4 pass Concept revision。",
      "该 revision 的 2 份 C4H、1 份 C4F 与 1 份 C5W evidence。",
      "C0/C1、Software Demo Policy 与仅与该 Concept 相关的 memory cues。"
    ],
    "actions": [
      "Controller — 对每个 C4 pass 验证完整 2+1 screen 和唯一 novelty ref。",
      "Model — 每个 Concept 启动 1 个 fresh C6A task，只能做 evidence-informed revision。",
      "Controller — 校验三个 identity section 逐字不变，发布 revision+1、supersession decision 与 disposition。"
    ],
    "outputs": [
      "artifacts/creative/concepts/creative-concept-*-r00N.md",
      "artifacts/creative/dispositions/creative-disposition-*-evidence-superseded.json"
    ],
    "fanout": "每个 C4 pass Concept 恰好 1 个 fresh Model Session；没有重试式自我修复循环。",
    "gate": "缺少任意 C4/C5W evidence 或改写 Intended Reaction、Real Input/Transformation/Output、Parent Atoms 时 fail closed。",
    "failureSemantics": "C6A 是必需阶段；task/schema/semantic failure 为 fatal。不能靠换软件核心把 C4 的失败 Concept 洗成新 revision。",
    "promptFiles": ["src/hacksome/stages/ideation/creative/prompts/creative-evidence-revise.md"],
    "schemaFiles": ["src/hacksome/stages/ideation/creative/schemas/creative-evidence-revise.schema.json"],
    "codeFiles": [
      "src/hacksome/stages/ideation/creative/workflow.py",
      "src/hacksome/stages/ideation/creative/artifacts.py",
      "src/hacksome/stages/ideation/creative/contracts.py"
    ],
    "architecture": {
      "status": "per-pass fanout · fatal",
      "summary": "每个 C4 pass 都有且只有一个证据修订 successor。",
      "diagnostic": "这不是第二次自由生成；identity section 与 primary Territory 仍被 Controller 机械约束。",
      "tone": "model"
    },
    "actualRun": {
      "status": "2 REVISIONS",
      "summary": "B 站运行的 2 个 C4 pass Concept 各产生 1 个 evidence-informed revision。",
      "diagnostic": "C6B 比较的是这 2 个新 revision，而不是原始 7 个 C3 Concept。",
      "rail": "2 successors",
      "tone": "model"
    },
    "misconception": "误解：C6A 可以根据先例发明一个更好但不同的 Concept。实际：它只能在固定 identity 内澄清。"
  },
  {
    "stageId": "C6B",
    "title": "双视角策展与确定性 shortlist",
    "phase": "CONVERGE",
    "actors": ["controller", "model"],
    "preview": "两个 fresh Red Team 分类同一池；Controller 不用分数，按分类确定 shortlist。",
    "goal": "用 meaning/value 与 hackathon-floor 两个相关但不同的反证视角，把证据充分的候选送给人。",
    "why": "模型的 1–10 分不是事实；每个候选必须在五个 categorical dimension 上留下证据。",
    "inputs": [
      "完整 C6A evidence-informed portfolio。",
      "同一份 Software Demo Policy。",
      "两个固定 CURATOR_LENS：meaning_value_red_team 与 hackathon_floor_red_team。"
    ],
    "actions": [
      "Controller — 同时启动 2 个 fresh curator task；二者都看完整候选池，但收到不同 lens。",
      "Model — 每个 curator 对每个 exact ref 的 5 个维度给 pass/uncertain/fail，并机械导出 include/hold/exclude；不得打分、排名或合并。",
      "Controller — 校验每位 curator 恰好覆盖全池；再按两个分类与 max_human_shortlist=8 做确定性 shortlist。",
      "Controller — 发布每个候选的 shortlisted / not_shortlisted disposition 和 immutable review batch。"
    ],
    "outputs": [
      "artifacts/creative/curation/creative-portfolio-curation-r001-v01.json",
      "artifacts/creative/curation/creative-portfolio-curation-r001-v02.json",
      "artifacts/creative/curation/creative-review-batch-r001.json",
      "artifacts/creative/dispositions/creative-disposition-*-shortlisted.json"
    ],
    "fanout": "固定 2 个 fresh Model Session，均完整分类所有 C6A Concept；shortlist 聚合只在 Controller 代码中执行。",
    "gate": "分类必须覆盖 exact pool 且维度与 decision 关系有效；两个视角后由确定性算法选择，非 Top-K 分数。",
    "failureSemantics": "curator task/schema/semantic failure 为 fatal。合法空 shortlist 发布 skip_reason=shortlist_empty 的空 batch，并直接进入 C7，不启动 Human Review。",
    "promptFiles": ["src/hacksome/stages/ideation/creative/prompts/creative-portfolio-curate.md"],
    "schemaFiles": ["src/hacksome/stages/ideation/creative/schemas/creative-portfolio-curate.schema.json"],
    "codeFiles": [
      "src/hacksome/stages/ideation/creative/workflow.py",
      "src/hacksome/stages/ideation/creative/artifacts.py",
      "src/hacksome/stages/ideation/creative/review.py"
    ],
    "architecture": {
      "status": "2 model views + deterministic gate",
      "summary": "模型提供五维 categorical evidence；Controller 才拥有 shortlist decision。",
      "diagnostic": "shortlist 不是两个模型平均分，也不是强制 Top-K；可以合法为空。",
      "tone": "controller"
    },
    "actualRun": {
      "status": "2 → 1 SHORTLIST",
      "summary": "B 站运行的 2 个 C6A revision 经双 Red Team 后，Controller 只 shortlist 1 个。",
      "diagnostic": "这一步是最终候选收敛点；后面的 Human Review 只看到这 1 个 exact revision。",
      "rail": "1 shortlisted",
      "tone": "controller"
    },
    "misconception": "误解：C6B 的两个 Agent 已经替 Percy 做了品味选择。实际：它们只提供分类反证，唯一人工 gate 仍在下一步。"
  },
  {
    "stageId": "C6 Human",
    "title": "唯一人工评审",
    "phase": "HUMAN GATE",
    "actors": ["controller", "human"],
    "preview": "immutable batch 进入 waiting；人类回执与 curator resolution 以 append-only 方式关闭轮次。",
    "goal": "把模型无法提供的外部品味、复述、分享冲动与 Demo confidence 作为唯一一次人工传感器。",
    "why": "Idea/taste 没有可靠环境真值；人类决策必须独立于模型评分，并绑定 exact Concept hash。",
    "inputs": [
      "C6B 发布的 immutable review batch 与每个 shortlisted Concept 的 exact revision/hash。",
      "独立 reviewer receipt；curator 关闭时选择 keep/revise/reject/taste_veto/merge。",
      "明确批准、hash 复核后才允许进入 C6C 的 feedback fragments。"
    ],
    "actions": [
      "Controller — 将非空 batch 写入 wait，run 转为 waiting/creative-human-review，并启动本机只读投影与提交服务。",
      "Human reviewer — 每个 Concept 写一句话复述、share_impulse/target、demo_confidence 与 recommendation；提交前看不到 peer 原文。",
      "Human curator — 查看覆盖与允许的机器证据，批准反馈、选择 resolution action，关闭 round。",
      "Controller — append-only 保存 receipt、feedback fragment、resolution 与 closed wait；不提前伪造 C6C 终态。"
    ],
    "outputs": [
      "artifacts/creative/curation/creative-review-batch-r001.json",
      "human-reviews.jsonl（append-only receipt 与其中的 feedback fragment bindings）",
      "human-resolutions.jsonl（append-only curator resolution）",
      "closed creative_human_review wait，绑定 resolution 与 receipt-set hash"
    ],
    "fanout": "人类 reviewer 数量可变；每个 shortlist revision 在 resolution 中恰好一个 action。空 batch 完全跳过本节点。",
    "gate": "这是 Creative 唯一 Human-in-the-loop gate；round 必须 closed 且 resolution/hash 闭合后，resume 才能进入 C6C。",
    "failureSemantics": "open round 继续 waiting；stale hash、冲突 request、越权 feedback 或不完整 resolution fail closed。自由文本始终是不可信数据。",
    "promptFiles": [],
    "schemaFiles": [],
    "codeFiles": [
      "src/hacksome/stages/ideation/creative/review.py",
      "src/hacksome/stages/ideation/creative/review_backend.py",
      "src/hacksome/stages/ideation/creative/review_server.py",
      "src/hacksome/stages/ideation/creative/review_ui/app.js"
    ],
    "noModelPrompt": true,
    "promptAbsence": "没有模型 Prompt，也没有模型输出 Schema：这是 Human-only gate。HTTP payload 与 ledger 由 review domain 的类型、hash 和语义校验拥有。",
    "architecture": {
      "status": "唯一 Human gate",
      "summary": "Controller 持久化 immutable batch 与 append-only ledger；人类提交和关闭 resolution。",
      "diagnostic": "回执是人类输入，但 retell/share/demo confidence 仍是小样本 proxy，不是传播率或 build success。",
      "tone": "human"
    },
    "actualRun": {
      "status": "1 SYNTHETIC RECEIPT",
      "summary": "B 站运行的 1 个 shortlist Concept 收到 synthetic E2E review receipt 并关闭轮次。",
      "diagnostic": "这份回执用于端到端测试，不是 Percy 的真实评审，也不能代表无背景观众看懂。",
      "rail": "synthetic E2E / not Percy",
      "tone": "human"
    },
    "misconception": "误解：存在一份 Human receipt 就验证了“30 秒能理解”。实际：本次 receipt 是 synthetic E2E，真实人类覆盖仍未建立。"
  },
  {
    "stageId": "C6C",
    "title": "按人工 resolution 收尾",
    "phase": "RESUME",
    "actors": ["controller", "model"],
    "preview": "close 后 resume；keep 直接复制，revise/merge 才调用模型，所有 shortlist 得到终态。",
    "goal": "只执行人类已冻结的 resolution，用受限反馈生成 Final Idea 或明确淘汰，并闭合所有 shortlist lineage。",
    "why": "人工自由文本不能直接变成可信指令；只有 curator 明确批准且 hash 绑定的 fragment 能进入有界修订。",
    "inputs": [
      "closed review wait、immutable HumanResolution 与 exact shortlisted Concept。",
      "每个 action 获批的 feedback fragments、curator instructions 与必要 evidence。"
    ],
    "actions": [
      "Controller — resume 只接受 closed C6 wait；先验证 round、batch、receipt set、resolution 与 source hashes。",
      "Controller — keep 逐字复制 source 为 Final Idea；reject/taste_veto 只写 terminal decision/disposition，这三种路径不调用模型。",
      "Model — 只有 revise 或 merge action 才各启动 1 个 fresh C6C task；上下文只含获批 feedback 和必要 evidence。",
      "Controller — 所有请求的模型输出先全部校验，再发布 Final Idea、feedback binding、decision 与每个 source 的唯一 terminal disposition。"
    ],
    "outputs": [
      "artifacts/creative/ideas/creative-idea-*.md（keep/revise/merge）",
      "artifacts/creative/curation/creative-feedback-binding-*.json",
      "artifacts/creative/dispositions/creative-disposition-*-human-*.json"
    ],
    "fanout": "每个 revise/merge operation 最多 1 个 Model Session；keep/reject/taste_veto 为 0 个。每个 Concept 的 feedback revision budget ≤1。",
    "gate": "closed resolution 必须覆盖每个 shortlist ref；每个 source 最终恰好一个 C6C terminal disposition，Final Idea target 与 action 完全闭合。",
    "failureSemantics": "任何 stale binding、越界反馈、模型或语义失败都使 run failed；在所有请求的 Agent 结果通过前不发布第一份 Final Idea。",
    "promptFiles": ["src/hacksome/stages/ideation/creative/prompts/creative-feedback-revise.md"],
    "schemaFiles": ["src/hacksome/stages/ideation/creative/schemas/creative-feedback-revise.schema.json"],
    "codeFiles": [
      "src/hacksome/stages/ideation/creative/finalize.py",
      "src/hacksome/stages/ideation/creative/workflow.py",
      "src/hacksome/stages/ideation/creative/review.py",
      "src/hacksome/stages/ideation/creative/artifacts.py"
    ],
    "promptAbsence": "路径分支：keep / reject / taste_veto 明确没有模型 Prompt；只有 revise / merge 使用上列 Prompt 与 Schema。",
    "architecture": {
      "status": "bounded resume · mixed actor",
      "summary": "Controller 执行冻结 resolution；仅 revise/merge 需要 Model，其他 action 为确定性收尾。",
      "diagnostic": "C6C 不是重新开放 brainstorm，也不是任意 failed stage 的通用 resume。",
      "tone": "controller"
    },
    "actualRun": {
      "status": "1 FINAL IDEA",
      "summary": "B 站 synthetic E2E resolution 收尾后产生 1 个 Final Idea，所有 shortlist disposition 闭合。",
      "diagnostic": "页面不推断该 resolution 等于 Percy 的 taste；这里只说明端到端合同完成。",
      "rail": "1 final idea",
      "tone": "controller"
    },
    "misconception": "误解：C6C 总会再调用一次模型美化。实际：keep 完全不调用模型，reject/taste_veto 也只写确定性终态。"
  },
  {
    "stageId": "C7",
    "title": "确定性发布",
    "phase": "PUBLISH",
    "actors": ["controller"],
    "preview": "从冻结 source snapshot 一次渲染、两阶段发布；中断后只重放同一字节。",
    "goal": "把完整候选历史、零个或多个 Final Idea、Idea Card、Memory Record 与 Build handoff 发布成可验证结果。",
    "why": "最终报告不能在恢复时漂移；所有输出必须来自同一 immutable snapshot 并共享确定性 ID、path、hash 与顺序。",
    "inputs": [
      "C0–C6C 的持久化 task、artifact、decision、disposition、review 与 Final Idea。",
      "一次冻结的 pre-C7 source state projection 和 source file bindings。"
    ],
    "actions": [
      "Controller — 构建 report projection，并在内存中一次渲染所有成功输出。",
      "Controller — 在发布任何最终 artifact 前冻结 staged bytes、final path、hash、ID、时间与 publish order 到 finalization manifest。",
      "Controller — 按 manifest 两阶段发布 report、cards、handoffs 与 memory；最后把 run 标记 completed。",
      "Controller — 如果 manifest 已存在，resume 只校验并 replay frozen bytes，不重新渲染、不调用模型。"
    ],
    "outputs": [
      "artifacts/creative/report/creative-idea-report.md",
      "artifacts/creative/report/creative-idea-report.json",
      "artifacts/creative/idea-cards/*.md 与 index.md",
      "artifacts/creative/handoffs/*.json",
      "artifacts/creative/memory/creative-memory-record.json",
      "state/creative-finalization/finalization-manifest.json"
    ],
    "fanout": "0 个 Model Session、0 个 Web、0 个 Human；输出数量由 Final Idea 数确定，可以合法为零。",
    "gate": "source snapshot、文件 bytes、artifact bindings、publish plan 与最终输出 hash 全部一致后才能 completed。",
    "failureSemantics": "manifest 前失败：run failed，只尽力发布 partial report，不暴露有效 Card/Memory/handoff。manifest 后中断：状态 finalizing，resume 只重放已冻结字节。",
    "promptFiles": [],
    "schemaFiles": [],
    "codeFiles": [
      "src/hacksome/stages/ideation/creative/workflow.py",
      "src/hacksome/stages/ideation/creative/finalization.py",
      "src/hacksome/stages/ideation/creative/report.py",
      "src/hacksome/stages/ideation/creative/report_projection.py",
      "src/hacksome/stages/ideation/creative/memory.py"
    ],
    "noModelPrompt": true,
    "promptAbsence": "没有模型 Prompt，也没有模型输出 Schema：C7 是 deterministic Controller-only finalization。恢复时也绝不重新渲染或调用模型。",
    "architecture": {
      "status": "deterministic · replayable",
      "summary": "Controller 从一个冻结 snapshot 生成并两阶段发布全部结果。",
      "diagnostic": "completed 证明 hash-bound 合同收敛，不证明 Idea 的真实传播力、可理解性或 build success。",
      "tone": "controller"
    },
    "actualRun": {
      "status": "1 FINAL CARD",
      "summary": "B 站运行从 1 个 Final Idea 确定性发布 1 张最终 Creative Idea Card，以及报告、Memory Record 与 Build handoff。",
      "diagnostic": "这张 Card 来自 synthetic E2E human receipt，不应标记为 Percy 真实认可。",
      "rail": "1 idea card",
      "tone": "controller"
    },
    "misconception": "误解：C7 还会让模型总结并选择最佳 Idea。实际：它只投影、冻结和发布已经闭合的事实。"
  }
]
`));

const ACTOR_LABELS = Object.freeze({
  controller: "Controller",
  model: "Model",
  web: "Web",
  human: "Human"
});

const stageRail = document.querySelector("#stage-rail");
const hoverPreview = document.querySelector("#hover-preview");
const detailContent = document.querySelector("#detail-content");
const stageTitle = document.querySelector("#stage-title");
const stagePhase = document.querySelector("#stage-phase");
const stageStatus = document.querySelector("#stage-status");
const evidenceTitle = document.querySelector("#evidence-title");
const evidenceSummary = document.querySelector("#evidence-summary");
const evidenceDiagnostic = document.querySelector("#evidence-diagnostic");
const copyStatus = document.querySelector("#copy-status");
const viewInputs = Array.from(
  document.querySelectorAll('input[name="workflow-view"]')
);
const actorLanes = Array.from(document.querySelectorAll("#actor-lanes li"));

let pinnedStageId = STAGE_DATA[0].stageId;
let viewMode = "architecture";
let copyStatusTimer = null;

function stageById(stageId) {
  return STAGE_DATA.find((stage) => stage.stageId === stageId);
}

function createTextList(items, className = "detail-list") {
  const list = document.createElement("ul");
  list.className = className;
  items.forEach((item) => {
    const row = document.createElement("li");
    row.textContent = item;
    list.append(row);
  });
  return list;
}

function createDetailBlock(title, content) {
  const section = document.createElement("section");
  section.className = "detail-block";

  const heading = document.createElement("h3");
  heading.textContent = title;

  const body = document.createElement("div");
  body.className = "detail-body";
  if (typeof content === "string") {
    const paragraph = document.createElement("p");
    paragraph.textContent = content;
    body.append(paragraph);
  } else {
    body.append(content);
  }

  section.append(heading, body);
  return section;
}

function repoHref(path) {
  return `../../${path}`;
}

function createResourceGroup(label, paths) {
  const group = document.createElement("section");
  group.className = "resource-group";

  const heading = document.createElement("h4");
  heading.textContent = label;
  group.append(heading);

  if (paths.length === 0) {
    const empty = document.createElement("p");
    empty.textContent = "无";
    group.append(empty);
    return group;
  }

  const list = document.createElement("ul");
  list.className = "resource-list";
  paths.forEach((path) => {
    const row = document.createElement("li");
    row.className = "resource-row";

    const link = document.createElement("a");
    link.className = "resource-path";
    link.href = repoHref(path);
    link.textContent = path;

    const copyButton = document.createElement("button");
    copyButton.type = "button";
    copyButton.className = "copy-path";
    copyButton.dataset.path = path;
    copyButton.textContent = "复制路径";
    copyButton.setAttribute("aria-label", `复制仓库路径：${path}`);

    row.append(link, copyButton);
    list.append(row);
  });
  group.append(list);
  return group;
}

function createResources(stage) {
  const wrapper = document.createElement("div");
  wrapper.append(
    createResourceGroup("Prompts", stage.promptFiles),
    createResourceGroup("Schemas", stage.schemaFiles),
    createResourceGroup("Code", stage.codeFiles)
  );

  if (stage.promptAbsence) {
    const note = document.createElement("p");
    note.className = "no-prompt-note";
    note.textContent = stage.promptAbsence;
    wrapper.append(note);
  }
  return wrapper;
}

function setActiveActors(stage) {
  actorLanes.forEach((lane) => {
    const isActive = stage.actors.includes(lane.dataset.actor);
    lane.dataset.active = String(isActive);
    lane.setAttribute(
      "aria-label",
      `${ACTOR_LABELS[lane.dataset.actor]}，${
        isActive ? "当前阶段参与" : "当前阶段不参与"
      }`
    );
  });
}

function evidenceFor(stage) {
  return viewMode === "bilibili" ? stage.actualRun : stage.architecture;
}

function renderDetail(stage) {
  const evidence = evidenceFor(stage);
  stagePhase.textContent = `${stage.stageId} / ${stage.phase}`;
  stageTitle.textContent = stage.title;
  stageStatus.textContent = evidence.status;
  stageStatus.dataset.tone = evidence.tone;
  evidenceTitle.textContent =
    viewMode === "bilibili" ? "B 站真实运行" : "架构合同";
  evidenceSummary.textContent = evidence.summary;
  evidenceDiagnostic.textContent = evidence.diagnostic;

  const goalWrapper = document.createElement("div");
  const goal = document.createElement("p");
  goal.textContent = stage.goal;
  const why = document.createElement("p");
  why.className = "fanout-note";
  why.textContent = `为什么存在：${stage.why}`;
  goalWrapper.append(goal, why);

  const actionsWrapper = document.createElement("div");
  actionsWrapper.append(createTextList(stage.actions, "actor-actions"));
  const fanout = document.createElement("p");
  fanout.className = "fanout-note";
  fanout.textContent = `Fanout / 循环：${stage.fanout}`;
  actionsWrapper.append(fanout);

  const gateWrapper = document.createElement("div");
  const gate = document.createElement("p");
  gate.textContent = `Gate：${stage.gate}`;
  const failure = document.createElement("p");
  failure.className = "fanout-note";
  failure.textContent = `失败语义：${stage.failureSemantics}`;
  const misconception = document.createElement("p");
  misconception.className = "misconception-note";
  misconception.textContent = stage.misconception;
  gateWrapper.append(gate, failure, misconception);

  detailContent.replaceChildren(
    createDetailBlock("Goal / 目标", goalWrapper),
    createDetailBlock("Inputs / 输入", createTextList(stage.inputs)),
    createDetailBlock("What happens / 发生什么", actionsWrapper),
    createDetailBlock("Outputs / 产物", createTextList(stage.outputs)),
    createDetailBlock("Prompts · Schemas · Code", createResources(stage)),
    createDetailBlock("Gate / Failure", gateWrapper)
  );
  setActiveActors(stage);
}

function setPinnedStage(stage, shouldFocusHeading = false) {
  pinnedStageId = stage.stageId;
  stageRail.querySelectorAll(".stage-item").forEach((item) => {
    const isPinned = item.dataset.stageId === pinnedStageId;
    item.dataset.pinned = String(isPinned);
    const button = item.querySelector(".stage-node");
    button.setAttribute("aria-pressed", String(isPinned));
  });
  renderDetail(stage);
  hoverPreview.textContent = `${stage.stageId} · ${stage.preview}`;
  if (shouldFocusHeading) {
    stageTitle.focus({ preventScroll: true });
  }
}

function previewStage(stage, renderFullDetail = false) {
  hoverPreview.textContent = `${stage.stageId} · ${stage.preview}`;
  setActiveActors(stage);
  if (renderFullDetail) {
    renderDetail(stage);
  }
}

function restorePinnedStage() {
  const pinned = stageById(pinnedStageId);
  if (pinned) {
    renderDetail(pinned);
    hoverPreview.textContent = `${pinned.stageId} · ${pinned.preview}`;
  }
}

function renderRail() {
  const fragment = document.createDocumentFragment();
  STAGE_DATA.forEach((stage) => {
    const item = document.createElement("li");
    item.className = "stage-item";
    item.dataset.stageId = stage.stageId;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "stage-node";
    button.dataset.stageId = stage.stageId;
    button.setAttribute("aria-pressed", "false");
    button.setAttribute(
      "aria-label",
      `${stage.stageId} ${stage.title}：${stage.preview}`
    );

    const id = document.createElement("span");
    id.className = "stage-id";
    id.textContent = stage.stageId;

    const copy = document.createElement("span");
    copy.className = "stage-node-copy";
    const title = document.createElement("span");
    title.className = "stage-node-title";
    title.textContent = stage.title;
    const meta = document.createElement("span");
    meta.className = "stage-node-meta";
    meta.textContent =
      viewMode === "bilibili" ? stage.actualRun.rail : stage.phase;
    copy.append(title, meta);

    button.append(id, copy);
    button.addEventListener("mouseenter", () => previewStage(stage, true));
    button.addEventListener("mouseleave", restorePinnedStage);
    button.addEventListener("focus", () => previewStage(stage, true));
    button.addEventListener("blur", restorePinnedStage);
    button.addEventListener("click", () => setPinnedStage(stage, false));

    item.append(button);
    fragment.append(item);
  });
  stageRail.replaceChildren(fragment);
  setPinnedStage(stageById(pinnedStageId) || STAGE_DATA[0]);
}

async function writeClipboard(path) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(path);
    return;
  }

  const helper = document.createElement("textarea");
  helper.value = path;
  helper.setAttribute("readonly", "");
  helper.style.position = "fixed";
  helper.style.opacity = "0";
  document.body.append(helper);
  helper.select();
  const copied = document.execCommand("copy");
  helper.remove();
  if (!copied) {
    throw new Error("copy command was rejected");
  }
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest(".copy-path");
  if (!button) {
    return;
  }

  const path = button.dataset.path;
  try {
    await writeClipboard(path);
    copyStatus.textContent = `已复制：${path}`;
    button.textContent = "已复制";
  } catch (_error) {
    copyStatus.textContent = `无法自动复制；请选择路径：${path}`;
  }

  window.clearTimeout(copyStatusTimer);
  copyStatusTimer = window.setTimeout(() => {
    copyStatus.textContent = "";
    button.textContent = "复制路径";
  }, 2400);
});

viewInputs.forEach((input) => {
  input.addEventListener("change", () => {
    if (!input.checked) {
      return;
    }
    viewMode = input.value;
    document.body.dataset.viewMode = viewMode;
    renderRail();
  });
});

renderRail();
