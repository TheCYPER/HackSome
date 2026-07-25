# BuildFactory 驱动的自主 Hackathon Build Teams — 技术设计

## 1. 改造原则

第一版直接改造仓库内的 `buildfactory/` 快照，不重新实现 Agent runtime、Hub、
Worker Manager、Verifier Manager、幂等方法协议、持久化和容器执行层。

BuildFactory 的 Company 产品语义将被替换为 Hackathon Team 语义：

- 一个 selected Idea Card 对应一个长期 Team；
- Team 只有一个常驻 Lead、一个并发 Worker 和一个并发 Verifier；
- Lead 可以一次创建多个 Goal，Worker/Verifier 按 FIFO 串行完成整个 batch；
- Team 没有 Agent 自己产生的完成态、idle 态或 deadline；
- 第一版三个角色都不加载 Skill。

确定性代码管理运行与仲裁，不管理产品方向、阶段或内容。产品判断只存在于 Agent
Prompt、真实项目状态和模型行为中。

## 2. 总体拓扑

```text
HackSome Idea Workflow
  → Idea Cards
  → one explicit Human Review Gate
  → selected Cards
  → Global Team Pool (default active max = 2)
      ├─ Team A
      │   Lead → Goal batch → Worker → Verifier → ... → Lead
      └─ Team B
          Lead → Goal batch → Worker → Verifier → ... → Lead

queued Teams
  → operator pauses an active Team
  → next queued Team starts
```

Review Gate 只授权创建 Team，不验证或冻结 Idea 内容。Team 创建后不再有任何人工审批。

## 2.1 仓库目录边界

两个并行开发面保持物理分离：

```text
src/hacksome/             Idea workflow 实现
tests/                    Idea workflow 测试
buildfactory/             Build Team runtime、角色 Prompt、配置与测试
```

Build runtime 不 import `src/hacksome` 的内部 workflow、artifact 或 state 类型。Idea
workflow 也不 import `buildfactory/orchestration` 内部模块。集成只依赖稳定 handoff
contract，使两个并行 session 可以分别修改各自目录。

第一版 handoff 至少包含：

```text
source_run_id
idea_card_id
idea_card_sha256
challenge_markdown
initial_idea_card_markdown
```

Review selection、UI 和 Idea Card 的发布仍属于 Idea 面；Team bootstrap、排队和长期运行
属于 Build 面。

## 3. Team 状态

每个 Team 的 Agent 可见项目页挂载为 `/project`。初始化时只写入：

```text
/project/
  reference/
    challenge.md
    initial-idea-card.md
```

两个 reference 文件都只是初始化材料。Lead 可以继续、修改或完全放弃 Idea Card，也
可以不围绕 challenge 工作。系统不把 reference 解释为 Objective 或验收约束。

除 `reference/` 外，不预建 PRD、Roadmap、代码、Pitch、索引或固定 taxonomy。Lead 和
Worker 使用原生文件工具组织 `/project`。

控制面仍保存在 Agent 不需要直接浏览的独立目录中，包括 Inbox、Goal ledger、Worker、
Review、session、telemetry 和 method request cache。

## 4. 角色与权限

### 4.1 Lead

- 长期 resident session；
- 拥有完整项目读写、Shell、Playwright/CUA、MCP 和外部操作权限；
- 可以直接执行任何工作；
- Prompt 引导它优先把适合委派或独立验证的工作创建为 Goal，但代码不强制；
- 可以一次创建一个或多个 Goal；
- Goal batch 清空后再次 wake，重新检查项目并形成下一轮判断。

### 4.2 Worker

- 一个 Goal 对应一个 ephemeral Worker lifecycle；
- 第一版每个 Team 同时最多一个 Worker；
- 拥有与 Lead 接近的项目读写与执行工具；
- 只处理当前 Goal；
- 认为真实工作完成后调用 `submit_result`；
- Verifier FAIL 后恢复相同 Worker、workspace、home 和 session。

### 4.3 Verifier

- 每次 review 使用 fresh ephemeral session；
- 可以读取项目、运行检查、使用 Playwright/CUA 和外部核验工具；
- canonical `/project` 只读；
- 不能修复、发布或代替 Worker 完成工作；
- 唯一业务写入是为当前 review 调用一次 `submit_verdict`。

## 5. Skill 与工具

三个角色第一版均声明：

```yaml
skills: []
```

保留 BuildFactory 的通用 Skill materialization 机制，但不把复制来的 Company Skill
放入任何 active loadout。后续只有在真实 Team 运行中发现稳定、重复、可复用的方法缺口
时才新增 Skill。

角色能力来自：

- 模型和固定 Prompt；
- `/project`；
- Shell 与代码工具；
- Playwright/CUA；
- 明确配置的其他 MCP；
- Hub 的确定性方法。

### 5.1 共享 Tool-use Prompt

Tool-use 指引作为单一共享 prompt asset 维护，并由 `AgentSpec` 在运行时与角色自己的
charter 组装成最终 system prompt。三个角色的声明都显式引用这个共享 asset，因此：

- Agent 在 turn 开始前已经看到指引，不需要再读取某份说明文档；
- GitHub、Vercel 和 Markdown 持久化的说明只维护一份；
- 每个角色仍保留自己的 charter 和权限边界；
- 新增角色是否继承该指引仍由 AgentSpec 显式声明，不做隐式全局注入。

组装顺序为共享 tool-use 指引在前、角色 charter 在后。共享指引自身必须声明它不覆盖
角色 charter；Lead 和 Verifier 因此可以知道 `gh` / `vercel` 的存在并做获准的只读
检查，但不能据此执行角色禁止的 mutation。

## 6. Prompt 设计

所有角色都采用“共享 tool-use 指引 + 稳定角色 charter + 当前 trigger/context”的
方式。稳定运行协议直接写入 Prompt，不通过 Skill 发现。

### 6.1 Lead 固定 Prompt

Lead Prompt 固定包含：

1. **角色与定位**
   - 长期 Hackathon Lead；
   - 把项目作为真实产品；
   - 没有固定 Objective、阶段、deadline、完成态或 idle 态；
   - reference 只是 initializer。
2. **确定性方法**
   - 完整命令、参数、示例与 request-id 规则；
   - 可以创建一个 Goal batch；
   - Goal 在 Team 内按 FIFO 串行运行。
3. **操作范围**
   - `/project` 是完整持久项目页；
   - 先检查真实文件、程序、浏览器体验、部署和外部结果；
   - 没有必需目录结构。
4. **运行契约**
   - 形成自己的判断；
   - 推动实质进展；
   - 可以直接行动，也可以创建 Goal；
   - 不制造仪式性文档或 busywork；
   - batch 清空后继续重新判断。
5. **当前 Trigger**
   - 首次启动、batch 清空、operator resume 或其他当前 wake 事件。

Lead Prompt 直接包含：

```bash
python3 -m orchestration.control_client create_goal \
  --json '{"intent":"concrete work","acceptance":"optional verifier-only context"}' \
  --request-id 'goal-<stable-purpose-id>'

python3 -m orchestration.control_client list_my_goals

python3 -m orchestration.control_client cancel_goal \
  --json '{"goal_id":"goal-...","reason":"why it is withdrawn"}' \
  --request-id 'cancel-<goal-id>'
```

Prompt 必须解释：

- 一个 batch 通过多次 `create_goal` 创建；
- `acceptance` 不向 Worker公开，只进入 Verifier context；
- 同一逻辑 mutation 重试时复用相同 request-id；
- 自然语言声称“已创建”不会改变 Hub 状态。

### 6.2 Worker 固定 Prompt

Worker Prompt 包含：

- 当前 `goal_id` 和完整 Goal intent；
- `/project` 的读写语义；
- 只完成当前 Goal；
- 执行真实工作而不是只写总结；
- FAIL 后继续同一 Goal；
- 无 deadline；
- 完成声明：

```bash
python3 -m orchestration.control_client submit_result \
  --request-id 'result-<goal-id>-<meaningful-revision>'
```

`submit_result` payload 仍为空。真实结果由 Verifier 自行寻找，不由 Worker提交摘要、
路径或证据清单。

### 6.3 Verifier 固定 Prompt

Verifier Prompt 包含：

- 当前 `review_id`、Goal intent 和可选 private acceptance；
- `/project` 是只读 canonical 项目；
- 独立寻找并检查真实结果；
- 可以使用检查工具，但不能修改、修复或发布；
- PASS 必须有实际观察证据；
- FAIL 必须给同一 Worker 可执行的具体反馈；
- verdict 调用：

```bash
python3 -m orchestration.control_client submit_verdict \
  --json '{"verdict":"PASS","reason":"specific observed evidence"}' \
  --request-id 'verdict-<review-id>'
```

只接受 `PASS` 或 `FAIL`。自然语言回答不能改变 review 状态。

## 7. Goal batch 循环

```text
Lead wake
  → create_goal × N
  → Lead wake ends
  → Worker runs Goal 1
  → Verifier reviews Goal 1
      FAIL → same Worker resumes → fresh Verifier
      PASS → Goal 2
  → ...
  → final Goal PASS
  → batch-empty event wakes Lead
```

第一版不限制 Lead 可以提前创建多少个 Goal，也不要求 batch 内 Goal 相互独立。只有一个
Worker，因此执行顺序严格由现有 enqueue sequence 决定。

## 8. 从 BuildFactory 删除或停用的产品面

第一版 active runtime 不再需要：

- Company/Department Objective 与 Objective Verifier；
- Department catalog、Department Provisioner 和 Department messaging；
- Company Notes；
- Company mailbox、email send/peek 和跨 Company mail router；
- Growth、Twitter、GA4 与 foundagent.net 专属部署能力；
- Company idle 语义；
- Goal absolute deadline 与 `failed_time`；
- resident/ephemeral Skill loadout 内容。

保留：

- Codex/Claude runtime adapter；
- resident wake/session continuity；
- native shared state mount；
- method envelope、actor binding、idempotency 与审计；
- Goal scheduler 的 FIFO 与 cancel；
- Worker Manager、Verifier Manager 和 FAIL 后原 Worker续接；
- run logs、telemetry、restart reconciliation；
- account package、Playwright/CUA 和容器运行基础。

## 9. Review Gate 交接

Review Gate 必须显式提交 selected Card IDs 与对应内容 hash。提交后：

1. 为每张 selected Card 建立独立 Team control root；
2. 写入两份 reference 文件；
3. 创建 Team registry row；
4. Global Team Pool 按 operator 顺序启动最多两个 Team；
5. 未选 Card 不创建 Team；排队 Team 不启动容器。

Gate 没有超时自动批准、非法输入默认批准或 Team 启动后的 reapproval。

## 10. 兼容与迁移

- `buildfactory/` 是一次性代码基线，不与原 `/Users/weston/dev/BuildFactory` 同步。
- 不迁移原 BuildFactory Company state、Objective、Department、mailbox 或 session。
- HackSome 现有 Idea workflow 保持独立；交接只消费其已发布 Idea Card 与 challenge。
- 第一版允许内部 Python 类名在安全迁移期间暂时保留 Company 命名，但 Agent-facing
  Prompt、mount、CLI 输出和新规范不得继续暴露 Company 产品语义。
