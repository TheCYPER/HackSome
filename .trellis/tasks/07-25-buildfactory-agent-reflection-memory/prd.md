# Build Factory Agent Reflection Memory Skill

## Goal

为 Build Factory 的长期运行 Lead 提供一个有界、可审计、可跨 wake 复用的
“Reflection Checkpoint”能力，使 Lead 不必只依赖不断增长的会话历史、README
和完整 Goal 历史来恢复项目理解。

该能力保存的是可供后续行动使用的结论摘要，而不是模型的原始
chain-of-thought。它应帮助 Lead 保留关键决策、已验证的项目理解、下一步需要
验证的假设，以及从错误中得到的可复用教训，同时避免成为第二套不受约束的
计划或事实来源。

## Background

- 最新 `origin/main` 中，Build Stage 的 Lead、Worker、Verifier AgentSpec 均为
  `skills: []`，但通用 Skill materialization 已经存在并有测试。
- Lead 使用长期 `session: resume`；Worker 通常每个 Goal 新建，同一 Goal 的
  Verifier FAIL 才 resume；Verifier 每次 review 都是 fresh。
- Lead 每次 wake 被要求检查真实 `/project`，并被明确禁止在 `/project`
  创建 plan/status 类 ceremonial artifact。
- Agent 只能看到 `/project`；Goal、Inbox、review、session、telemetry 等目录由
  deterministic control plane 独占，Agent 通过 Hub 方法访问。
- 当前 Lead Hub 能力只有 `create_goal`、`list_my_goals`、`cancel_goal`；
  `wake_context` 不包含项目摘要，`goal_batch_drained` 只包含
  `last_enqueue_seq`。
- 现有四队运行审计显示：首次 Lead wake 的累计输入为约 7–10 万；31/31 次
  后续有效 wake 都重新读取 README，35/35 次查询全部 Goals。后期单次 wake
  的相邻累计快照增量约为 50–150 万输入 token。
- 项目 README 已经承载大量产品和运行知识，但没有独立、紧凑、带 freshness
  信息的 Lead current-state/decision digest。

## Requirements

### R1. Reflection 保存结论，不保存原始思维链

Skill 必须明确禁止保存原始 chain-of-thought、逐步内心推理、完整工具输出或
聊天流水账。允许保存的是对后续工作有用、可审计的短结论：

- 当前产品、目标用户和核心使用循环；
- 已做出的重要决策、决策依据及被放弃的方向；
- 已验证事实与尚未验证假设；
- 当前关键约束、不变量和风险；
- 下一次判断前需要完成的少量 checks 或 hypotheses；
- 实质错误的根因、处理状态和可复用教训。

### R2. Memory 必须有界并采用 replace 语义

- 当前注入给 Lead 的 snapshot 必须有严格大小上限；MVP 采用 UTF-8 编码后
  `8 KiB` 上限。
- 更新采用整体 replace，不采用无限 append。
- 历史版本可以由控制面归档用于审计，但不得默认重新注入 Lead context。
- 不得复制完整 Goal intent、README、源代码、测试日志或 Verifier 输出。
- 连续多轮更新不能导致 snapshot 或默认注入量线性增长。

### R3. Memory 属于控制面，不属于产品

- Reflection memory 存放在 Team control state，不进入 `/project`，不污染最终
  产品 repository，也不放宽 Lead “不直接实现项目”的角色边界。
- Lead 不直接获得 control-plane filesystem mount；读取和更新必须通过
  actor-bound、deterministic Hub capability。
- 写入必须原子化、UTF-8 校验、拒绝 NUL/超限内容，并跨 Hub、Lead container
  和 Team restart 持久。
- 一个 Team 的 Lead 不得读取或修改其他 Team 或角色的 memory。

### R4. Snapshot 使用稳定、可读的结构

MVP memory 是人可以直接审查的 Markdown snapshot，固定包含：

1. `Product Model`：目标用户、核心问题、核心循环；
2. `Verified State`：已经由代码、运行结果或 Verifier 证实的能力；
3. `Decisions`：重要决策、简短依据、被放弃方向；
4. `Invariants and Risks`：不可破坏约束、当前风险；
5. `Open Hypotheses`：尚未证实的判断；
6. `Next Checks`：下一次决策前最多几项检查点；
7. `Lessons`：重要错误、根因、状态和教训；
8. `Freshness`：最新 Goal sequence、控制面 Goal-state fingerprint、更新时间
   及证据引用。

`Next Checks` 不能成为第二份 backlog。可执行工作仍以 Goal ledger 为唯一来源。

### R5. 更新必须定期但只在有意义时发生

- Lead 在每次 wake 做产品判断前获得当前 snapshot。
- 首次 Team wake 可以创建初始 snapshot。
- 每次包含实质项目变化、新决策、新风险或新错误教训的成功 Lead wake，
  结束前最多 replace 一次。
- 每次 `goal_batch_drained` wake 必须重新评估 snapshot；若无新结论，允许并
  记录 no-op，不能为了满足频率制造文字。
- 更新必须基于本次刚检查过的真实项目或 Verifier evidence，并同步 freshness。
- runtime/telemetry 能区分 `read`、`replace`、`no-op`、`stale` 和失败。

### R6. Snapshot 是派生且不可信的上下文

- `/project`、真实运行结果、测试和 Verifier evidence 始终优先于 memory。
- Goal sequence 或 Goal-state fingerprint 不匹配时，Lead 必须把
  snapshot 当作 stale orientation，并定向检查变化后再作决定。
- 项目文字复制进 memory 后不得获得 system-instruction 权限；注入时必须明确
  标记为 `untrusted derived data`，防止持久化 prompt injection。
- snapshot 中的结论不能单独支撑新 Goal，也不能覆盖 Goal acceptance。

### R7. Skill 与 runtime contract 必须一致

- 新 Skill 暂定命名为 `maintain-lead-brief`，使用简洁、verb-led 名称。
- Skill 的 description 必须覆盖触发条件：Lead 恢复项目上下文、
  `goal_batch_drained`、完成有实质变化的 wake、记录重要错误教训。
- Skill body 只保留压缩流程、字段约束、禁止内容和 Hub 命令；不复制大段
  runtime 规范。
- Lead AgentSpec 显式声明该 Skill；Worker 和 Verifier 保持 `skills: []`。
- wake prompt/role contract 必须明确要求读取和条件更新，不能只依赖
  progressive-disclosure 的概率触发来实现“定期”。
- Hub capability、存储合同、Skill 指令和测试必须共享同一字段和大小限制。

### R8. Fresh Verifier 的独立性必须保持

- MVP 只为长期运行 Lead 提供 reflection memory。
- Worker 不读取 Lead 私有判断；每个 Goal intent 仍必须自包含。
- Verifier 不读取 Lead memory，也不能把它作为 PASS 证据。
- 未来若需要 Worker continuity，必须另行设计 Goal-scoped schema，不能直接
  共享 Lead memory。

### R9. 功能必须可观察、可回滚

- telemetry 至少记录 Team、wake、snapshot revision、动作、字节数、stale
  判断和错误码，不记录未过滤的私密推理内容。
- 更新失败不能损坏上一份有效 snapshot，也不能被静默吞掉。
- rollout 必须有关闭开关；关闭后 Lead 回到当前行为，现有 snapshot 保留但不
  注入、不更新。
- usage 报告必须区分 Codex 原生累计 snapshot 与相邻 wake delta。

### R10. 初始版本不立即改变 session policy

- MVP 保持 Lead 的 `session: resume`，先验证 snapshot 的质量、边界和触发稳定性。
- 设计必须允许后续用 snapshot + Goal delta 启动 fresh/rotated Lead session。
- session rotation 和 Goal summary/delta API 的全面上线属于后续阶段，不在本
  PRD 中同时改变，以便隔离 Reflection Skill 的效果和风险。

## Acceptance Criteria

- [x] Lead AgentSpec materialize `maintain-lead-brief`；Worker 和 Verifier 的
      loadout 保持零 Skill。
- [x] Lead 每次 wake 都能获得当前 bounded snapshot 及 revision/freshness；
      没有 snapshot 时得到稳定的 empty projection。
- [x] Lead 可通过 Hub 原子 replace 自己的 snapshot，并支持幂等重试和 stale
      revision 冲突检测。
- [x] 非 Lead、错误 Team、未知字段、NUL、非 UTF-8 可表达内容和超过 `8 KiB`
      的内容都被确定性拒绝。
- [x] snapshot 跨 Hub、Lead container 和 Team restart 持久，且不出现在
      `/project` 或最终产品 Git 状态中。
- [x] 连续多轮 replace 不使默认注入上下文线性增长；历史版本不默认注入。
- [x] Skill 明确区分 verified facts、hypotheses、decisions、next checks 和
      lessons，并禁止 raw chain-of-thought、完整日志与 backlog 复制。
- [x] freshness mismatch 会在 prompt/Skill 中要求定向 live inspection；旧
      snapshot 不能作为创建新 Goal 的唯一证据。
- [x] fresh Verifier 和 Worker 的 prompt、mount、capability 与 Skill inventory
      不获得 Lead memory。
- [x] telemetry 能观察每次 wake 的 memory revision/action/bytes/staleness，
      且不会记录 snapshot 正文。
- [x] feature flag 关闭时，现有 Lead/Worker/Verifier 行为和历史 Team 均保持兼容。
- [ ] 至少在一个代表 Team 上完成不少于三轮 batch-drain 试验：没有重复 Goal、
      没有丢失已知安全/隐私不变量，并比较启用前后的 README/全树重复读取次数
      与逐 wake token delta。

## Out of Scope

- 保存、展示或要求模型输出原始 chain-of-thought。
- 把 reflection 文件作为产品 repository 的用户交付物。
- 用 memory 替代代码、测试、browser QA、Goal ledger 或 Verifier。
- 在 MVP 中给 Worker、Verifier 或不同 Team 共享私人 reflection。
- 自动从 snapshot 直接创建 Goal。
- 无上限的 append-only 日记。
- 在本 PRD 中启用自动 session rotation，或将 `list_my_goals` 改为
  summary/delta-first API。
- 为 Worker 设计独立的 Goal-scoped continuity memory。
- 提供用于浏览、diff 和恢复历史 reflection 的人类运营界面。
