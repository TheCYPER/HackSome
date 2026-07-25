# BuildFactory 驱动的自主 Hackathon Build Teams

## 目标

在 HackSome 已有的 Prompt → Idea Card 工作流之后，加入一个基于
BuildFactory 当前实现改造的长期自主 Build 系统。人只在 Idea Card 与 Build
之间进行一次显式授权；Team 启动后完全 human-out-of-the-loop，持续观察、构建、
验证和改进自己的项目。

系统不以产出唯一项目为目标。每张获准进入 Build 的 Idea Card 都可以形成一个
独立 Team；所有成功项目全部保留，不排名、不合并，也不自动筛掉其他项目。

## 子任务

1. `07-23-single-team-runtime`：完成一个 Team 的 Lead → Worker → Verifier 顺序闭环、
   项目状态、零 Skill loadout 和三角色 Prompt。
2. `07-23-team-pool-operator`：在单 Team runtime 之上实现 handoff bootstrap、Team
   registry、默认两个 active Team、排队与 operator pause/resume。

Idea Review Gate UI 与 `src/hacksome/` 接线不属于这两个 Build 子任务，后续以独立
integration task 完成。

## 已确认事实

- BuildFactory 当前受版本控制的本地快照已经放入仓库的 `buildfactory/` 子目录。
- `buildfactory/` 是 HackSome 仓库的一部分，不包含嵌套 `.git`，也未复制运行状态、
  账号凭证、虚拟环境或缓存。
- Build 运行时直接基于这份 BuildFactory 代码裁剪和改造，不重新实现另一套 Agent
  runtime、Hub、Worker 或 Verifier 系统。
- Prompt → Idea Card 的现有实现和正在进行的 Idea E2E benchmark 属于并行工作，
  本任务不得覆盖其未提交改动。

## 产品要求

### R1 — 一次性人工 Review Gate

- Idea 阶段可以产生任意数量的有效 Idea Card。
- Build 前必须暂停在人工 Review Gate，等待 operator 显式提交选择。
- 没有超时默认值；超时、空响应、非法响应或重启都不能自动批准任何 Card。
- operator 可以显式选择任意子集，包括全部或零张。
- 未选择的 Card 仍然是有效 Idea，只是不启动 Build；不得记录为质量 reject。
- Review Gate 对每个 Team 只发生一次。Team 启动后不再存在任何人工审批、
  reapproval 或 human-in-the-loop 分支。

### R2 — 每张 selected Card 创建独立 Team

- 每张被选择的 Idea Card 创建一个隔离的长期 Hackathon Build Team。
- Team 之间不共享项目状态、Repo、Agent session 或实现上下文。
- 每个 Team 初始化时的 Agent 可见 reference 只有：

  ```text
  reference/
    challenge.md
    initial-idea-card.md
  ```

- `challenge.md` 和 `initial-idea-card.md` 都只是初始参考，不是不可变 Objective、
  合规约束或持续成功判据。
- Idea Card 只负责初始化 Agent。Agent 可以修改、放弃或完全不继续原 Idea，并自主
  决定最终做什么。

### R2.1 — Idea 与 Build 代码边界

- Prompt → Idea Card 继续由现有 `src/hacksome/` 与对应 `tests/` 负责。
- Idea Card → 长期 Build Team 的代码、Prompt、角色配置和测试全部放在
  `buildfactory/` 下。
- 两个部分并行开发时不得跨目录移动、重命名或覆盖对方的未提交文件。
- 两边只通过明确的 handoff contract 传递 challenge、selected Idea Card、稳定 ID
  和内容 hash；Build runtime 不直接依赖 Idea workflow 的内部 Python 对象或状态机。

### R3 — 无确定性语义工作流

- Hub 不得通过固定 category、阶段 Schema 或状态机决定 Agent 应该做什么。
- 系统不得冻结 Audience、Problem、价值时刻、产品机制、PRD、架构或交付顺序。
- 系统不得要求 Agent 按 PRD → Build → Pitch 等预设阶段运行。
- Agent 自己决定是否创建 Objective、PRD、Roadmap、决策文档或其他项目结构。
- 确定性代码只负责机械边界，例如生命周期、并发、持久化、恢复和
  Worker/Verifier 仲裁；产品判断和下一步工作由常驻 Agent 决定。

### R4 — 长期运行语义

- Team 没有完成态、自动终态或业务上的 idle 态。
- 系统不设置 Hackathon Deadline，也不按时间自动结束 Team。
- Repo、Demo 或 Deck 发布后，Team 仍可继续观察、抠细节和改进。
- quiet timer 或周期 wake 只能是运行调度机制，不能被解释为 Team 已完成或无事可做。
- 只有 operator 可以显式停止一个 Team。

### R5 — 职责分离

- 每个 Team 只有一个常驻 Hackathon Lead；不保留 BuildFactory 的 Department 层。

#### R5.1 — 固定 Prompt

- Lead 的稳定 Prompt 必须固定表达：
  1. 角色与定位：它是持续构建 Hackathon 项目的 Lead，并把项目当作真实产品；
  2. 确定性方法：如何创建、查看和取消 Goal；
  3. 操作范围：所有项目内容和长期状态都在 `/project`；
  4. 运行契约：检查真实现状、形成判断并推动实质进展。
- `/project`、reference、Goal 创建、Worker `submit_result` 和 Verifier
  `submit_verdict` 都是角色基础协议，必须直接写入对应 Prompt，不通过 Skill 发现。
- 第一版保留 BuildFactory 当前已验证的 `create_goal`、`list_my_goals`、`cancel_goal`、
  `submit_result` 和 `submit_verdict` 方法名称，不为了替代 Skill 而重命名 Hub 协议。
- 对应 Prompt 必须包含可直接执行的完整调用格式、参数语义、最小示例和 request-id
  幂等要求；只列出 capability 名称不满足要求。

#### R5.2 — 零 Skill

- 第一版 Lead、Worker 和 Verifier 的角色 loadout 都必须是 `skills: []`，不配置任何 Skill。
- 第一版能力只来自模型本身、角色 Prompt、项目文件和显式配置的 MCP/CLI 工具。
- 保留通用 Skill 物化框架，以便后续扩展；但复制自 BuildFactory 的 Company Skill 不进入
  任何角色 loadout，也不得被 Agent 自动发现。
- 只有真实 Team 运行暴露出反复出现、可复用的具体方法缺口后，才设计并加入对应 Skill；
  第一版不预设替代 Skill。

#### R5.3 — Lead 与 Worker

- Lead 负责长期判断、观察项目、维护自然项目状态、创建和取消 Goal。
- Lead 可以使用 Playwright、CUA 及其他真实项目检查能力，亲自打开本地或线上产品、
  走 User Flow、观察 UI 和确认当前行为，而不是只读取文件或等待 Verifier 摘要。
- Lead 与 Worker 可以共享大部分项目、浏览器和执行工具；两者的核心差异是生命周期、
  上下文范围、Goal 权限和提交契约，而不是人为制造不同的 Skill 目录。
- Lead 和 Worker 原则上获得完整工具与项目写入权限。系统不通过 sandbox、mount 或
  方法白名单确定性禁止 Lead 执行代码、设计、部署或其他工作。
- Lead prompt 应引导它把适合委派或独立验收的工作拆成下一条 Goal，但这只是行为
  引导，不是权限限制；Lead 仍可以自行判断并直接执行任何工作。
- 一次性 Worker 负责代码、设计、研究、测试、部署、Pitch 等实际工作。
- Worker 只看到完整 Goal intent；可选 `acceptance` 只进入 Verifier prompt。
  Worker 必须知道的产品要求必须写入 intent，private acceptance 只用于独立检查。

#### R5.3.1 — 固定 Tool-use Prompt

- Lead、Worker 和 Verifier 的最终 system prompt 都必须直接包含同一份 tool-use
  指引，不要求 Agent 先发现或读取独立文档。
- 指引必须明确说明 Agent 运行环境提供 Git、GitHub CLI (`gh`) 和 Vercel CLI
  (`vercel`)；GitHub 用于 Git 托管与版本管理，Vercel 用于部署真实可访问的产品。
- 对拥有写入与发布权限的角色，指引应鼓励在每个有意义、可独立验证的步骤完成后
  commit 并 push，而不是把整个项目积压成一个大提交；Agent 可以在自己的 GitHub
  账号下创建项目 Repo，并部署到其 Vercel 账号可用的域名。
- Agent 可以把过程中形成、但代码和显式需求本身未完整表达的重要结论、推论和上下文
  写成 Markdown，放在 `/project` 内自行选择或新建的目录中，供后续 Agent 延续判断。
- 共享 tool-use 指引只描述能力和推荐工作方式，不扩大角色权限：Lead 仍只负责判断与
  Goal 委派，Verifier 仍只读且不能 commit、push、创建 Repo、部署或修改外部系统。

#### R5.4 — 顺序 Goal batch

- 第一版每个 Team 使用顺序闭环。Lead 每次 wake 可以创建一个或多个 Goal，形成一个
  有序 batch；单 Worker 按 FIFO 逐个执行，每个 Goal 都由一个 Verifier 独立验证。
- 某个 Goal FAIL 时恢复原 Worker 继续同一 Goal；PASS 后直接进入 batch 中的下一条
  Goal。只有整个 Goal batch 清空后，才重新唤醒 Lead 形成下一轮判断。
- Hub 不限制一个 Team 只能存在一个非终态 Goal；限制的是同时执行的 Worker 数量。

#### R5.5 — Verifier

- 独立的一次性 Verifier 检查真实结果；FAIL 后恢复原 Worker 继续返工。
- Verifier 是完整写入权限原则的例外：它可以使用文件读取、测试、Playwright、CUA
  和核验所需的外部工具，但 canonical 项目文件与项目状态必须只读。
- Verifier 不能修复、发布或代替 Worker 完成工作；它唯一的业务写入是为当前 review
  提交一次 PASS/FAIL verdict。
- Team 启动后的所有 Lead、Worker 和 Verifier 都是 Agent，不引入人类审批。

### R6 — 两层 Pool

- Global Team Pool 只限制同时 active 的 Team 数量，默认 `max_active_teams = 2`。
- 超出全局槽位的 selected Team 保持排队，不算拒绝或失败。
- active Team 不会自动完成、idle、轮转或释放槽位。
- 只有 operator 显式暂停 active Team 后，系统才释放槽位并启动排队中的下一个 Team。
- operator 暂停使用可恢复的 `paused` 控制状态：停止相关运行实例后保留 Repo、
  Team state、Goal ledger、session token 和排队工作；以后可以恢复同一个 Team。
- `paused` 不是 Agent 的 idle、完成或失败状态。永久删除必须是独立且明确的破坏性操作。
- 第一版每个 active Team 的 `worker_max = 1`，不在一个 Team 内并行多个 Worker。
- 每个 Team 使用自己的 Goal/Worker/Verifier 闭环；Team 之间不共享 Worker。
- 多 Worker、并行 Goal 或更复杂的 Team 内调度属于后续扩展，不进入第一版。
- 系统不得根据 Idea 或项目质量自动调整 Team 顺序、资源或存活状态。

## 验收标准

- [ ] Review Gate 只有显式 operator 提交才能形成选择结果，任何隐式或超时路径都不会启动 Team。
- [ ] 一次选择多张 Card 后，每张 Card 都形成隔离 Team，所有可用全局槽位并行启动。
- [ ] Idea 代码与测试保持在现有 `src/hacksome/` 和 `tests/`，Build runtime 的新增或
      修改保持在 `buildfactory/`，两边通过 handoff contract 集成。
- [ ] 默认最多两个 Team active；其他 selected Team 排队，直到 operator 暂停一个 active Team。
- [ ] 暂停并恢复 Team 后，Repo、Team state、Goal ledger 和可用 session 连续性仍然存在。
- [ ] 每个 active Team 同时最多运行一个 Worker；同一 Team 不会并行执行两个 Goal。
- [ ] Worker 完成后必须经过独立 Verifier；FAIL 恢复原 Worker，PASS 后按 FIFO 执行
      batch 中的下一条 Goal；队列清空才触发下一次 Lead 规划。
- [ ] Team 状态只预置 `reference/challenge.md` 与
      `reference/initial-idea-card.md` 两份 Agent 可见输入。
- [ ] Team 可以在不遵循 Idea Card、没有预设 PRD/Build/Pitch 阶段的情况下继续运行。
- [ ] Lead 和 Worker 通过独立 prompt、session 范围与 Goal 契约形成职责分工，
      但 Lead 的工具或项目写入权限不会被确定性削减。
- [ ] Verifier 能使用真实检查工具，但不能修改 canonical 项目文件或状态，也不能执行
      修复和发布；每次 review 使用 fresh session。
- [ ] Lead、Worker 和 Verifier 无需读取 Skill，就能从各自 prompt 理解 `/project`、
      Goal 创建、结果提交和 verdict 提交等基础运行协议。
- [x] Lead、Worker 和 Verifier 的最终 system prompt 都直接包含共享 tool-use 指引；
      Worker 能据此使用 GitHub/Vercel 和持久 Markdown，Lead/Verifier 的既有权限边界
      不被覆盖。
- [ ] 第一版三个角色的物化结果均不包含任何 Skill；移除 Skill 不影响 Prompt、MCP、
      Goal、Worker 或 Verifier 的正常运行。
- [ ] Worker 结果由独立 Verifier 检查；FAIL 恢复原 Worker，而不是交给人审批。
- [ ] 已经发布 Repo、Demo 或 Deck 的 Team 不会被系统自动标记完成或停止。
- [ ] 多个成功 Team 的项目全部保留，系统不生成 winner、Top-K、合并结果或自动淘汰。
- [ ] BuildFactory 原仓库和 HackSome 现有 Idea workflow 的并行未提交改动均未被覆盖。

## 不在范围内

- 自动选择或排名 Idea Card。
- Build 后的人工审批或方向复核。
- Team 自动轮转、自动让出全局槽位或基于质量的资源调度。
- 固定产品阶段、强制交付顺序和 Idea 一致性检查。
- 迁移 BuildFactory 现有 Company 运行状态、邮箱或外部账号数据。
