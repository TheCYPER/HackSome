# Creative 创意工作流技术设计

## 0. 文档状态

本文把 `prd.md` 中的产品要求收敛为可实施的技术合同。实现阶段可以调整内部命名，但不得悄然改变下列产品决定：

- Useful 与 Creative 是两条独立路线，不互相继承。
- C6 是唯一人工关卡。
- 人工反馈不采用模型自评式 1–10 总分。
- 第一批 C2/C3 和初始 C4 判断先于任何历史 Idea 或外部先例输入。
- C5M 历史灵感是一次性有界分支，不能递归，也不能绕过 C4/C5W。
- software-first 是 Controller-owned 的 route policy，不是 Agent 可稀释的审美偏好；普通设备内置 I/O 合法，定制硬件、实体制作和纯人工装置核心自动淘汰。
- C4 同时包含 C4H Hook/分享触发与 C4F Software Demo Feasibility 自动关卡，二者共享一次修复预算；C6 仍是唯一人工关卡。
- C4F 不能只检查“软件/非硬件”合规；还要在保守参考预算下检查冷启动、关键路径复杂度、最高风险假设、降级切片、预置状态和目标环境可靠性。
- C6B 只使用 categorical software-demo、surprise/fun、clarity、share-trigger、novelty evidence，不输出总分或排名。
- 一句话复述和立即分享是独立判断；portfolio 多样性按核心机制而不只按 Territory 标签判断。
- 每个修复、策展和反馈循环都有明确上限。
- 最终报告由控制器确定性生成，允许零个最终 Idea，并逐项保留处置原因。
- 只有已完成且验证通过的 Creative run 才产生可供未来运行读取的 Idea Memory Record。

## 1. 先说人话：这里的 Harness 是什么

在本项目里，Harness 不是“会替我们想创意的 Agent”，也不是一套允许任意画流程图的工作流语言。

它只是两条路线共同需要的可靠执行底座：

1. 把最终 Prompt 的精确字节先保存下来；
2. 启动一个隔离的 Codex Session；
3. 对 timeout、基础设施重试和结构化输出做统一处理；
4. 把任务、日志、产物、hash、事件和决策写进同一个 run；
5. 让 `status` 和 `validate` 能辨认这个 run 属于哪条路线。

“想什么、看什么资料、产出什么、什么叫通过”仍由 Useful 或 Creative 自己决定。

## 2. 设计目标与非目标

### 2.1 目标

- 在不改变当前 Useful v1 行为的前提下，引入 `creative` route。
- 把当前 `UsefulIdeaWorkflow._call()` 中已经被证明有效的任务执行骨架抽成薄共享层。
- 为 C0-C7 定义明确的输入、Prompt context allowlist、输出 Schema、产物路径和路由规则。
- 让每个进入 C5W/C6 的 Concept 都能说明并通过审查：软件运行入口、真实输入、可执行转换、可观察输出、可得依赖、最小比赛 cut 和具体分享产物。
- 为每个候选 revision 定义结构化处置原因，并为跨 run 灵感建立可冻结、可验证、可关闭的 Idea Memory。
- 在 C6 提供一个无需前端框架和数据库的本地团队评审页面。
- 把人工等待建模为正常状态，而不是错误或假装完成。
- 为所有 Concept 保留稳定身份、不可变 revision、来源和淘汰原因。
- 让 Creative 最终 Idea Card 可以通过稳定 JSON handoff 被后续 Build Team 使用，但本任务不启动 Build。

### 2.2 非目标

- 不设计通用 DAG/DSL、插件式工作流编辑器或任意 stage 注册系统。
- 不给 Useful 增加运行级恢复。
- 不让 Creative 复用 Useful 的 Problem、Audience 或 Red Team 产品语义。
- 不引入 React、Vue、FastAPI、数据库或登录系统。
- 不把 C6 页面部署到公共互联网。
- 不建立全局 registry、向量数据库、embedding 服务或跨 run 写事务；run 目录仍是唯一事实来源。
- v1 不自动把 Useful、failed/waiting Creative、fixture、外部笔记或完整旧 Idea Card 映射成历史灵感。
- 不在本任务中实现 Build Team、Pitch、发布或真实传播实验。
- 不把 C4F 或 reviewer 的 `demo_confidence` 宣称为已完成真实构建；它们只是 Build 前代理信号。

## 3. 当前基线与复用边界

### 3.1 当前代码的真实职责


| 现有模块           | 现在做什么                                                               | Creative 的处理                                                                                |
| -------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `codex.py`     | Codex CLI、并发、timeout、同一逻辑任务基础设施重试、结构化输出、日志                          | 原样复用                                                                                        |
| `state.py`     | 原子文件写入、严格 JSON、hash、幂等 JSONL                                        | 原样复用；补一个跨进程 run lease                                                                       |
| `hub.py`       | run、task、artifact、event、decision 的唯一持久化 owner；只能打开明确 run，不能发现历史 run | 保留为唯一 Hub；把 route-neutral 与 route-specific validation 分开；跨 run 扫描由 Creative memory owner 负责 |
| `prompting.py` | Prompt 分隔/注入算法 + Useful 私有注册表                                       | 保留渲染算法；公开 `PromptSpec/PromptCatalog`，注册表按 route 拆开                                          |
| `artifacts.py` | 通用 Markdown 检查 + Useful Problem/Idea composer                       | 通用检查保留；Creative composer 放独立模块                                                              |
| `workflow.py`  | 完整 Useful 七阶段拓扑和语义验证                                                | 保持 Useful owner；抽出任务执行骨架                                                                    |
| `cli.py`       | Useful `run/status/validate/doctor`                                 | 增加 route dispatch、Creative `review/resume/benchmark`                                        |


### 3.2 不采用的抽象

不新增与 `RunHub` 重叠的 `StateStore`、`ArtifactStore` 或“大而全的 WorkflowHarness”类。共享抽取只包含已经有第二个使用方的能力：

```text
RunHub
├── 单文件原子状态、事件、任务、产物与 ledger
├── RunContract（route-specific inspect / validate / result projection）
└── AgentTaskExecutor
    ├── PromptCatalog
    ├── CodexRunner
    └── route-specific semantic validator
```

`UsefulIdeaWorkflow` 与 `CreativeIdeaWorkflow` 都组合这些能力，但彼此不 import 对方内部类型。

### 3.3 与 Weston 流程图的关系

用户提供的 `mermaid-diagram.svg` 描述的是较早的 S0-S11 Useful 方案：它包含 Discovery/Compliance 双视图、并行 Research/Writer/Generator、Targeted Search、最多一次 repair、独立复审、Build Feasibility 和不调用 Agent 的 S11 汇总。

当前 HEAD 已把可执行 Useful 路线重写为七个 Agent stage，因此该图不是现行代码合同，不能照搬 stage ID、旧 resume 或 S0-S11 产物。Creative 只复用其中四个已经证明合理的编排思想：

- 约束视图与探索视图分开；
- 多个独立 Session 并行探索；
- Targeted repair 有明确次数上限且由 fresh Session 复审；
- 最终汇总由控制器确定性完成，Build 保持在 Idea 路线之外。

## 4. 总体拓扑

```text
输入 Challenge + 可选 Creative Brief
        │
        ▼
C0 Challenge & Constraints
        │
        ▼
C1 Creative Brief + frozen Software Demo Policy
        │
        ▼
C2 6 个独立 software-native Territory Explorer
        │
        ▼
C3 4 个独立 Concept Synthesizer
        │
        ▼
C4 每个 Concept：2 个独立 C4H + 1 个独立 C4F
        │
        ├── hardware/installation hard invalid ──┐
        ├── invalid / repair 后失败 ─────────────┤
        ├── repairable ─ 1 次修复 ────┤
        │                             │
        ▼                             │
C5M 读取 run 创建时冻结的历史快照     │
1 个 Recall + 最多 2 个 Remix          │
        │                             │
        ├── 0 个 challenger ─────────┤
        └── challenger ─> 同合同 C4H'+C4F' ─────┤
                                      │
        合并初始与 challenger 的 pass 集
        │
        ▼
C5W 每个通过 Concept 1 次联网 Novelty Scan
        │
        ▼
C6a 证据驱动修订
        │
C6b 2 个独立 Portfolio Curator
        │
        ▼
确定性 shortlist（最多 8 个）
        │
        ▼
status=waiting
本地团队评审页面
        │
Percy 关闭评审轮次
        │
        ▼
hacksome resume
        │
C6c 每个保留/合并项最多 1 次反馈修订
        │
        ▼
C7 控制器确定性报告 + Idea Cards + Handoff
        └── creative-memory-record.json 供未来 run 使用
```

初始 C4 后没有合格 Concept 不会立刻丢弃历史：若 frozen memory snapshot 与当前 Atom 可产生 challenger，C5M 仍有一次、最多两个的新分支机会。只有初始与 challenger 均无完整 C4H+C4F pass，或 C6B shortlist 为空时，控制器才发布 `concept_refs=[]`、`status=skipped_empty`、带精确 `skip_reason` 的空 C6 batch，不进入人工等待，直接产出零 Idea 报告。software-first v2 的前一种情况使用 `all_candidates_failed_concept_screen`；旧 v1 run 仍按冻结合同保留 `all_candidates_failed_hook`。空 batch 只是状态机的“没有待审对象”证明；所有 Concept、Hook/Feasibility Review、修复与淘汰原因仍进入 C7。

## 5. Route 与 Run 状态合同

### 5.1 `run.json` 版本

新运行继续写入 Hub `schema_version=2`；software-first 是 Creative route contract 的 v2，不是 Hub schema v3。`RunHub` 同时读取：

- v1：解释为当前 `useful` route，只允许 `status/validate` 和现有 Useful 行为；
- v2：必须显式包含 route metadata。

读取 v1 时只做内存投影，不自动重写用户已有 run。被 Weston 更早架构淘汰的旧 S0-S11 run 不在兼容范围内。

### 5.2 v2 顶层新增字段

```json
{
  "schema_version": 2,
  "route": {
    "id": "creative",
    "contract_version": "2",
    "prompt_policy_version": "2",
    "stage_policy_version": "2",
    "report_policy_version": "2"
  },
  "config_hashes": {
    "codex_config_sha256": "...",
    "workflow_settings_sha256": "..."
  },
  "resource_manifest": {
    "path": "resources/manifest.json",
    "sha256": "..."
  },
  "inputs": {
    "challenge": {
      "path": "input/challenge.md",
      "sha256": "..."
    },
    "creative_brief": {
      "path": "input/creative-brief-input.md",
      "sha256": "...",
      "source": "default|literal|file"
    },
    "software_demo_policy": {
      "path": "input/software-demo-policy.json",
      "sha256": "...",
      "policy_version": "2"
    },
    "idea_memory": {
      "path": "state/creative-memory/idea-memory-snapshot.json",
      "sha256": "...",
      "mode": "auto|off",
      "source": "runs_dir|disabled",
      "eligible_entry_count": 0,
      "diagnostic_count": 0
    }
  },
  "status": "created",
  "current_stage": null,
  "terminal_error": null,
  "secondary_errors": [],
  "transition_seq": 0,
  "pending_records": [],
  "result_artifact_ids": [],
  "wait": null
}
```

兼容规则：

- 新 Useful run 也写 v2 与 `route.id=useful`。
- v1 的 `input` 在只读投影中映射为 `inputs.challenge`；Creative Brief 与 Idea Memory Snapshot 的 path/hash/source/mode 是 v2 正式登记资源，不只是在磁盘上留下未登记文件。Snapshot 的正文放在 controller-owned `state/creative-memory/`，而不是容易被误解为每个 Agent 输入的 `input/`。
- 新 Creative run 的 route `contract/prompt/stage/report policy version` 全部使用 v2，并正式登记 controller-owned `SoftwareDemoPolicy` 的 path/hash/version；对应 C1/C2/C3/C4H/C4F/C5M Remix/C6A/C6B Prompt 资源也必须提升 template version。不能在任何 version `"1"` 资源下静默加入新 stage、reason enum 或 review receipt shape。
- 已存在的 Creative v1 `waiting` run（包括 `creative-hack-the-rest-20260724-04`）继续使用 run 创建时冻结的 v1 Prompt/Schema、双 Hook C4、review payload 和 `all_candidates_failed_hook`。`open/status/validate/review/resume` 必须按 persisted contract 分派，禁止拿 v2 默认值或 schema 重解释 v1 字节；未知/不支持版本 fail closed。
- Creative memory discovery 在新 run 目录创建前完成，验证过的 record bytes 被复制进 snapshot；绝对本地 `runs_dir` 不进入报告或 Prompt。之后源 run 新增、删除或改变都不会改变当前 run。
- Useful 继续维护 `idea_card_ids`，其 CLI 默认和输出格式不变。
- 共享层新增 `result_artifact_ids`，Creative 不伪装成 Useful Idea Card 集合。
- `status` 与 `validate` 先读取 route，再分派到对应 `RunContract`。
- v2 进入 `failed` 时必须持久化首个 controller-level `terminal_error={kind,message,stage,task_id,event_id,at}`；该首因不可覆盖。后续 partial-report 等错误只追加到 `secondary_errors`。

### 5.3 Creative 状态机

```text
created
  └─ execute ─> running
                  ├─ fatal failure ─> failed
                  ├─ empty C6 batch ─> C7 prepare ─> finalization publishing ─> completed
                  └─ C6 batch published ─> waiting
                                             │
                                  review round closed
                                             │
                                      resume command
                                             ▼
                                          running
                                             ├─ failure ─> failed
                                             └─ C7 prepare ─> finalization publishing ─> completed

finalization publishing
  ├─ process/publish interruption ─> 保持 running + resumable finalization
  ├─ resume exact frozen bytes ─> completed
  └─ frozen bytes/hash corruption ─> failed
```

`waiting` 是正常、可验证的终态片段，不应触发非零退出码。`wait` 保存：

```json
{
  "kind": "creative_human_review",
  "round_id": "creative-review-round-001",
  "round_artifact_id": "creative-review-batch-r001",
  "round_sha256": "...",
  "status": "open",
  "opened_at": "...",
  "closed_at": null,
  "resolution_id": null,
  "resolution_sha256": null,
  "latest_receipt_set_sha256": null,
  "approved_feedback": []
}
```

关闭轮次后 `run.status` 仍为 `waiting`，但 `wait.status=closed`。只有 `hacksome resume RUN_DIR` 将其转回 `running`。

`CreativeIdeaWorkflow.execute()` 不复用 Useful 的 `Path` 返回类型，而返回显式 outcome：

```python
@dataclass(frozen=True, slots=True)
class CreativeRunOutcome:
    status: Literal["waiting", "finalizing", "completed"]
    run_dir: Path
    primary_artifact: Path
    next_command: str | None
```

- `waiting`：`primary_artifact` 是 review batch，`next_command="hacksome review …"`，CLI 正常退出码 0；
- `finalizing`：只在 C7 manifest 已冻结但 publish 未完成时出现，`primary_artifact` 是 finalization manifest，`next_command="hacksome resume …"`；CLI 非零退出并明确说明这是可恢复发布中断，不是 Idea 失败；
- `completed`：`primary_artifact` 是 final report，`next_command=None`；
- fatal failure 仍通过 `WorkflowError`/非零 CLI 表达，并由 partial report 单独记录。

### 5.4 `resume` 的严格边界

- 只接受 `route.id=creative`，并且满足下列互斥条件之一：
  - `status=waiting`、`wait.kind=creative_human_review`、`wait.status=closed`：继续 C6C 业务流程；
  - `status=running`、`current_stage=creative-finalization`、存在合法 immutable finalization manifest：只重放 C7 已冻结产物。
- 它不是任意 crash recovery，不恢复 Useful，不重跑失败的 C0-C5；C7 recovery 也不重新 render、不调用模型、不采用新代码生成不同字节。
- 重复调用已完成的 run 返回清晰错误，不产生新任务。
- 轮次尚未关闭时返回状态说明，不调用模型、不改变 run。
- `resume` 必须通过唯一的 persisted-config decoder 恢复 `CodexConfig` 和 `CreativeWorkflowSettings`。JSON 会把 tuple 编码成 list，decoder 负责重新规范化、拒绝未知/缺失字段并验证 config hash；不能直接执行 `CodexConfig(**run["codex_config"])`。

### 5.5 重复状态转换与 Event ID

当前 Useful 的 event ID 由 `status + stage` 组成，同一个 stage 再次进入相同状态会与原 event 的时间戳冲突。Creative 的 repair、`waiting → running` 和 revision 会真实触发这种情况。

v2 state 因此增加单调递增的 `transition_seq`。每次状态转换取得唯一序号，事件 ID 使用：

```text
run:transition:<zero-padded-seq>
```

event payload 仍保存 `from_status`、`to_status`、`stage`、`reason` 和时间。Task、artifact 和 decision ID 同样必须包含 iteration/revision，不能只用 stage 名。

仅增加序号不能解决 `run.json` 已写、`events.jsonl` 未写时的崩溃窗口。v2 使用一个很小的 transactional outbox：

1. 在独占 `run.lock` 内生成完整 event record，`created_at` 只生成一次；
2. 把状态变化和精确 event record 一起写进 `run.json.pending_records`；
3. 把 pending record 幂等 append 到目标 JSONL；
4. 再从 `pending_records` 清除。

若在第 2/3/4 步之间崩溃，下一次 v2 writer 先用 outbox 中原始 timestamp/content 重放，因此不会因为新时间戳与同 ID 冲突。`status/validate` 不做隐式修复，只把 pending 状态显示为 `needs_reconcile`；`review/resume/run` 等 writer 在任何业务动作之前 reconcile。

`pending_records` 只允许写入预定义 ledger（events、decisions、human reviews/resolutions），不接受任意路径。它不是通用事务引擎。

所有 v2 writer 会自动 reconcile，但 terminal run 可能没有后续业务 writer，因此提供：

```bash
hacksome reconcile RUN_DIR
```

该命令只在独占 lock 下校验并 flush allowlisted pending record、清除 outbox；不改变业务 stage/status、不调用模型、不联网。v1 或没有 pending 的 v2 run 为明确 no-op/unsupported 结果。`status` 发现 pending 时显示这条恢复命令。

v1 兼容是严格只读：

- v1 `status/validate` 直接读取，不创建 `run.lock`、不写 projection、不要求 v2 outbox/config/transition 字段；
- `_mutate` 对 v1 run fail closed；
- 新 Useful/Creative run 才创建 lock 文件并使用 v2；
- 这与当前 Useful “已有 run 不 resume”合同一致。

### 5.6 `CreativeRunContract`

`CreativeRunContract` 是 Creative run 的唯一离线投影与语义验证 owner。

`inspect()` 至少返回：

```json
{
  "route_id": "creative",
  "run_id": "...",
  "status": "waiting",
  "current_stage": "creative-human-review",
  "task_counts": {},
  "concept_counts": {
    "base_generated": 0,
    "memory_challengers": 0,
    "generated_total": 0,
    "hook_passed": 0,
    "shortlisted": 0,
    "final": 0
  },
  "memory": {
    "mode": "auto",
    "snapshot_sha256": "...",
    "eligible_entry_count": 0,
    "selected_cue_count": 0,
    "status": "empty|disabled|completed|optional_failed"
  },
  "review": {
    "round_id": "...",
    "status": "open",
    "reviewer_count": 0,
    "covered_concept_count": 0,
    "shortlist_count": 0,
    "resumable": false
  },
  "finalization": {
    "status": "not_started|publishing|completed|corrupt",
    "manifest_ref": null,
    "planned_artifact_count": 0,
    "published_artifact_count": 0,
    "resumable": false
  },
  "zero_reason_code": null,
  "report_ref": null,
  "partial_report_ref": null
}
```

`validate()` 在 Hub core integrity 之后检查：

- route/policy/config version 与 hash；
- C0-C7 artifact type、必需 headings、revision 单调性和 source refs；
- task stage 与 PromptCatalog/schema/web policy 一致；
- 第一批 C2/C3/C4 的 Prompt、parent refs、registered context 与 stage input 不含 memory；snapshot path/hash/mode、来源 record schema/hash 和发现诊断自洽；
- failed task 默认是 fatal；completed run 只允许显式 `failure_policy=optional_branch` 的 C5M Recall/Remix failed task，并要求存在一一对应的 `optional_memory_stage_failed` event/diagnostic；
- C4 repair 次数、每个 revision 的 `ConceptDisposition`、稳定 reason codes 和 gate decision refs；
- memory challenger 最多两个、只有一代、同时引用当前 Atom 与跨 run 复合 memory ref，并重新走 C4；
- C5W 仅出现在初始或 challenger 的完整 C4H+C4F-pass Concept 上，且它是 Creative 唯一联网任务；
- shortlist 上限、territory 与排除理由；
- wait → round artifact/hash → review ledger → resolution 的闭包；
- human review 的 supersedes 链无环且只在 round 关闭前追加；
- final Idea、report JSON、Idea Card、handoff 和 memory record hash 互相一致；若存在 C7 finalization manifest，其 source projection、staged bytes、publish progress 和 completed transition 必须闭合；
- completed run 有 final report、memory record 和完整 terminal disposition；零 Idea 有合法 `zero_reason_code` 与空 C6 batch。failed run 有 terminal error/允许 partial report、waiting run 不得有 final handoff/memory record。

前端、CLI 和 report renderer 只消费这个 contract 提供的 typed projection，不各自解析 `run.json`/JSONL。

## 6. 共享任务执行设计

### 6.1 `PromptCatalog`

把当前私有 `_PromptSpec` 公开为不可变数据类：

```python
@dataclass(frozen=True, slots=True)
class PromptSpec:
    stage: str
    template_id: str
    version: str
    template_path: Path
    schema_path: Path
    web_search: bool = False
```

`PromptCatalog` 只负责按 stage 查找 spec；Prompt 内容、Schema 和联网策略仍由 route owner 提供：

```text
useful_prompt_catalog
creative_prompt_catalog
```

创建 v2 run 时，catalog 必须一次性冻结整条 route 的资源，包括条件式 C5M 和尚未执行的 C6C：

```text
RUN_DIR/resources/
├── manifest.json
├── prompts/<stage>.md
└── schemas/<stage>.schema.json
```

`manifest.json` 对每个 stage 保存 template ID/version/hash、schema hash、`web_search` policy 和相对路径。所有任务从 run-frozen copy 读取，不再从当前 package 读取；因此 C6 等待期间 `git pull` 不会改变 resume 的 Prompt。

Resume 前必须验证：

- manifest 自身 hash；
- 每个冻结文件 hash；
- route contract/stage policy version 仍被当前代码显式支持；
- stage 的 web policy 与 manifest 一致。

版本不受支持时 fail closed 并要求显式迁移，不能因为 package 中恰好还有同名文件就静默使用新语义。

渲染器继续使用带 hash 的 `<BEGIN_NAME_xxx>` 边界，并把 block 内容声明为不可信数据。

### 6.2 `AgentTaskExecutor`

从 `UsefulIdeaWorkflow._call()` 抽取以下固定顺序：

1. 从 route catalog 取得 `PromptSpec`；
2. 渲染最终 Prompt；
3. `RunHub.begin_task()` 保存 Prompt、request、schema hash 和 parent refs；
4. 构造 `CodexTask`；
5. 调用 `CodexRunner`；
6. 保存 result/output/log/session；
7. 调用 route 传入的 semantic validator；
8. 无效输出标记为 invalidated，基础设施失败标记为 failed。

接口不接收“下一阶段”或“通过/淘汰规则”，避免共享层演化为工作流 DSL。

每条 task record 增加默认值为 `fatal` 的 `failure_policy`：

```text
fatal | optional_branch
```

Useful 和除 C5M 外的 Creative task 始终使用 `fatal`。只有 route policy 明确 allowlist 的 `creative-memory-recall` / `creative-memory-remix` 可以使用 `optional_branch`；Executor 仍持久化真实的 failed/invalidated task，Controller 通过 typed all-settled result 决定跳过该分支。它不能把失败改写成合法空输出，也不能让任意新 stage 自行声明 optional。

### 6.3 Session 与工具策略

- 每个逻辑任务使用 fresh Session。
- 只有同一逻辑任务的基础设施重试可以 resume 原 Session。
- C5W Novelty Scan 是 Creative 唯一允许 `web_search=True` 的 stage。
- C0-C4、C5M、C6、C7 不允许网络、浏览器、apps、skills、多 Agent 自动扩散或图像生成。
- model、reasoning effort、timeout、并发和 retry 次数写入 run。
- 新建与 resume 都使用同一个 config serializer/decoder，确保禁用功能、sandbox 和 approval policy 不因 JSON round-trip 漂移。
- C7 不启动 Codex Session。

## 7. 标识符、Revision 与产物布局

### 7.1 稳定 ID

ID 由控制器根据稳定输入顺序分配，不使用并行完成顺序：

```text
creative-territory-01
creative-atom-t01-01
creative-concept-s01-01
creative-concept-m01
creative-idea-001
```

同一 Concept 的修改不换 Concept ID，只增加 revision：

```text
creative-concept-s01-01-r001
creative-concept-s01-01-r002
creative-concept-s01-01-r003
```

`creative-concept-mNN` 只用于 C5M challenger。它是一个新的 Concept，不是旧 Concept 的 revision；metadata 必须包含当前 run 的 `current_atom_refs` 和历史 `memory_source_refs`。跨 run ref 不能只写 artifact ID，必须包含 source run/route/contract/artifact/hash/memory-record hash。

合并两个 Concept 会生成新的 `creative-idea-NNN`，并把所有来源 revision 放进 `source_refs`。

### 7.2 不可变发布

`RunHub.publish_artifact()` 已拒绝覆盖同路径，因此 revision 使用新 artifact 与新路径：

```json
{
  "concept_id": "creative-concept-s01-01",
  "revision": 2,
  "supersedes_ref": "creative-concept-s01-01-r001",
  "revision_reason": "cheap_hook_repair"
}
```

旧 revision 永不覆写。Human review 始终绑定 artifact ID 与 sha256，而不是只绑定 Concept ID。

当前 `publish_artifact()` 是“先写内容文件，再登记到 `run.json`”，只保证每个文件自己的 atomic，不是跨文件事务。v2 保持简单但补足可恢复语义：

- 整个判断、写文件、登记和 event outbox 操作位于同一个方法级独占 `run.lock`；
- artifact ID 已登记，且 type/path/hash/task/source/metadata 与请求完全相同、文件 hash 也一致：视作幂等成功；
- artifact record 已登记但文件缺失：fail closed；不得根据调用方这次传入的 content 静默重建历史产物；
- artifact ID 已登记但任一字段不同：冲突失败；
- requested path 已由另一个 artifact ID 登记：冲突失败；
- 路径不存在且 ID 未登记：正常写内容、登记并把精确 publish event 放入 outbox；
- 路径已存在、尚未登记、且内容 hash 与本次请求一致：允许幂等 adopt、登记并写 event outbox；
- 路径已存在但 hash 不同：冲突失败；
- artifact record 已登记但 publish event 尚在 outbox：writer 先重放同一 event，再返回幂等成功；
- `validate` 扫描 Creative 规范目录并报告未登记 orphan；
- 不自动删除 orphan，也不把它当成正式产物。

#### 7.2.1 C7 多产物 Finalization

单文件幂等不足以证明 report、Idea Cards、handoffs 与 Memory Record 要么全部就绪、要么仍可恢复。C7 因而采用 route-owned 两段式发布：

1. 从已验证且加锁的 Hub projection 一次性预分配所有 artifact/event ID 与完成时间，并对输入 artifact 集、decision/human ledger heads、resolution 与终态 disposition 形成 canonical `FinalizationSourceManifest`；其 hash 不包含即将写入的 planned artifact/event，避免自引用；
2. 计算 report hash 后再渲染 Memory Record，因此 report 只引用预分配的 memory artifact ID，Memory Record 可以安全引用 report hash；
3. 把所有精确 bytes 写到 `state/creative-finalization/staged/`，逐个复核 hash；
4. 最后原子写入 immutable `finalization-manifest.json`，其中保存 source projection hash、每个 staged/final relative path、artifact type/ID/hash/size、固定 publish order、预分配 event ID 和 completed transition；
5. 只有 manifest 已持久化后才调用 `publish_artifact()`；发布完所有产物、重放完对应 outbox event 并再次验证闭包后，才写 `completed` transition。

最小 manifest 结构：

```json
{
  "schema_version": 2,
  "finalization_id": "creative-finalization-001",
  "source_projection_sha256": "...",
  "report_policy_version": "2",
  "outputs": [
    {
      "artifact_id": "...",
      "artifact_type": "...",
      "staged_path": "state/creative-finalization/staged/...",
      "final_path": "artifacts/creative/...",
      "sha256": "...",
      "size_bytes": 0,
      "publish_event_id": "..."
    }
  ],
  "completed_transition": {
    "event_id": "...",
    "transition_seq": 0,
    "at": "persisted-run-time"
  }
}
```

若进程在 manifest 之后中断，run 保持 `status=running`、`current_stage=creative-finalization`；已经复制但尚未登记的文件只在 manifest 精确匹配时视为可 adopt 的计划产物。`resume` 必须先复核 `FinalizationSourceManifest` 的所有输入/ledger heads 未变，并区分 manifest 已允许的 planned publish 记录，再复核所有 staged/existing bytes，按固定顺序幂等重放；它不能重新 render 或改变时间/ID/hash。staged bytes 或已发布 bytes 被篡改时 fail closed；任何未完成计划都不得进入 `result_artifact_ids`、不得被历史 discovery 或用户界面当成有效 Final Idea 输出。

### 7.3 目录

```text
RUN_DIR/
├── input/
│   ├── challenge.md
│   └── creative-brief-input.md
├── state/
│   ├── creative-memory/
│   │   └── idea-memory-snapshot.json
│   └── creative-finalization/
│       ├── finalization-manifest.json
│       └── staged/
├── tasks/
├── artifacts/
│   └── creative/
│       ├── challenge/
│       ├── brief/
│       ├── territories/
│       ├── atoms/
│       ├── concepts/
│       ├── cheap-hook-reviews/
│       ├── dispositions/
│       ├── memory/
│       ├── novelty-scans/
│       ├── curation/
│       ├── idea-cards/
│       ├── handoffs/
│       └── report/
├── events.jsonl
├── decisions.jsonl
├── human-reviews.jsonl
├── human-resolutions.jsonl
└── run.json
```

## 8. Creative 默认设置与成本上界

```python
CreativeWorkflowSettings(
    territory_explorers=6,
    max_atoms_per_territory=3,
    concept_synthesizers=4,
    max_concepts_per_synthesizer=3,
    hook_reviewers_per_concept=2,
    idea_memory_mode="auto",
    max_memory_runs=20,
    max_memory_entries=80,
    max_memory_snapshot_bytes=256 * 1024,
    memory_recallers=1,
    max_memory_selected_cues=8,
    memory_remixers=2,
    max_memory_challengers=2,
    novelty_researchers_per_concept=1,
    portfolio_curators=2,
    max_human_shortlist=8,
    max_hook_repairs=1,
    max_feedback_revisions=1,
)
```

这些是可配置的工程默认值，不是“六个 Agent 一定比五个更有创意”的产品真理。每个值有硬上界，CLI 拒绝无界 fanout。

公开 CLI 只暴露 `--idea-memory auto|off`；数量和字节上界由 `CreativeWorkflowSettings` 持久化，避免常用命令被调优参数淹没。Snapshot 先按 source run 的持久化 `created_at` 倒序、再按 `run_id` 与 `memory_entry_id` 排序，依次应用 run/entry/byte 上限；所有被截断或跳过的来源写入 diagnostics。文件系统枚举顺序不能改变快照。

修订预算是三个互不借用的 stage-local 合同，而不是一个含义模糊的“全程一次”：C4H Hook 与 C4F Feasibility 共享 0 或 1 次 C4 repair，C6A evidence revision 恰好 1 次，C6C human-feedback revision 为 0 或 1 次。因此同一 base Concept 或 memory challenger 的 lineage 最多新增三个模型 revision；每次的 `revision_reason` 继续分别是 `cheap_hook_repair`、`evidence_informed` 或 `human_feedback`，幂等重放不得生成新 revision。`merge` 的每个 source 也必须满足各自的预算，合并结果只消耗一次 C6C 调用。

每个 C5M challenger 从 revision 1 开始，消费自己的 C4/C6 stage-local budget；它不能把某个已淘汰 base Concept 换 ID 后视作“新 Idea”来绕过 repair 上限。Semantic validator 要求至少一个当前 Atom 和一个 memory cue，并拒绝与任一来源规范化 Hook 完全相同的输出。

六个默认 Territory lens 全部 software-native：

1. `Direct manipulation and unusual software interaction`；
2. `Reversal, reveal, and expectation shifts in a runnable interface`；
3. `Multiplayer, collaboration, and social propagation`；
4. `Mystery narratives built from software-visible hidden state`；
5. `Camera, microphone, text, code, time, or live-data transformation using ordinary device I/O`；
6. `Viral remix, replay, or shareable artifact generated by a technical mechanism`。

旧的纯 spatial/embodied/performance 与 wildcard cross-media lens 不进入 v2 默认列表；这些表现形式只有在软件真实读取输入、执行转换并产生可验证输出时才可作为某个 software-native lens 的呈现方式。

当 C0 没有给出团队、时长和运行环境时，C3/C4/C6 Prompt 使用下列保守
`Reference Implementation Budget`，但不新增 v2 JSON 字段：

- 最多 2 人，在 24 小时内完成可现场运行的最小 cut；
- 只承诺一个主要浏览器/设备切片，例如普通 laptop 的一个现代浏览器，或一台
  普通手机的一个浏览器；跨浏览器、跨桌面/手机和双设备同步都不是默认免费能力；
- 最多一个简单 backend：一个可部署进程中的轻量状态、生成或实时 endpoint，
  不包含多服务编排、复杂账号系统、异步数据管线或专门运维；
- 关键路径最多三个独立子系统。这里的“子系统”指需要分别实现、配置、部署或
  调试，且可以独立让 Demo 失败的边界；同一 backend 内的 route 不重复计数，
  browser client、backend、外部模型/API 或第二设备协同分别计数；
- 必须指出一个最危险技术假设，以及能在开工前两小时内给出可证伪结果的最小
  probe；还必须给出该假设失败后的降级切片。降级切片可以降低效果质量，但仍要
  保留真实 input → executable transformation → observable output 和核心 reveal；
- 必须枚举预置状态及成本：账号/权限、房间和种子数据、模型下载或预热、第二设备
  配对、预先录制/整理内容、部署和现场人工动作。自动脚本也要计入准备时间，
  人工隐藏劳动不能记作零成本。

C0 的显式硬约束优先于该 fallback：更紧的预算必须收紧，明确且可信的更大团队/
更长赛时可以替换参考数字，但 Creative Brief 不能单独放宽它。这个 block 只收紧
Prompt 对既有 v2 sections 的解释，不改变 frozen `SoftwareDemoPolicy` 的字节、
Schema、reason code、route-level prompt policy version 或旧 run 的解释。六个
受影响 stage 的 Prompt template version 从 v2 前进到 v3，并把 v2 声明为兼容
资源；已经创建的 v2 run 继续使用其持久化 Prompt 字节与资源版本。

本轮“可理解性 + 双 Red Team”继续遵守同一兼容策略：只把
`creative-concept-synthesize`、`creative-evidence-revise` 与
`creative-portfolio-curate` 从 v3 前进到 v4，并把 v3 加入各自显式兼容
allowlist；v2 兼容项继续保留。route-level policy、Schema、reason code 与
既有 v2/v3 frozen run 均不重解释。

首次真实 v4 smoke 在 C3 暴露了输出完整性问题：一个合法 JSON 内的第二篇
Concept 漏掉最后的 `Parent Atoms` H2，Controller 正确 fail-closed。修复不
放宽 validator，也不修改已冻结 v4 字节；只有
`creative-concept-synthesize` 前进到 v5，并把 v4 加入兼容 allowlist。v5
要求单篇保持简洁，返回前机械自检全部十二个 H2、末尾 `Parent Atoms` 与
结构化 refs；必要时宁可少返回 Concept，也不能由 Controller 猜测补写。

第二次真实 smoke 已让 C3 v5 的四个 Session 全部通过并稳定发布 9 个 Concept，
但在 C4F 暴露了跨层映射歧义：代码/Spec 固定
`technical_demo_substance → core_is_manual_performance_or_installation`，旧 Prompt
却只分别列出维度与 reason code，模型把语义上更像的
`no_runnable_end_to_end_demo_path` 填入该维度，Controller 正确 fail-closed。
修复只把 `creative-software-demo-review` 前进到 v4，并把 v3 加入兼容
allowlist；Prompt 逐对写出七个 `dimension → reason_code`，测试从代码常量生成
同一映射断言。Schema、validator 与失败 run 均不修改。

## 9. C0-C7 阶段合同

### 9.1 统一输出 Envelope

Agent 只返回小型 JSON envelope；长文本放在 `markdown` 字段，稳定 ID、路径、revision 和 hash 由控制器补充。模型正文不承担内部引用完整性：例如 C2 Atom 的 `Territory` section 是自然语言语义，不能靠其中是否出现 `creative-territory-*` 子串来建立谱系。

候选列表必须保持生成顺序。JSON Schema 只检查形状，route semantic validator 继续检查标题、必需 section、数量上限、重复和引用。

### 9.2 阶段矩阵


| Stage                                   | Session fanout                    | 允许的 Prompt context                                                 | 输出                                              | 控制器路由             |
| --------------------------------------- | --------------------------------- | ------------------------------------------------------------------ | ----------------------------------------------- | ----------------- |
| C0 `creative-challenge-parse`           | 1                                 | 原始 Challenge                                                       | Challenge Brief + Constraint View               | 两份文档均合法才继续        |
| C1 `creative-brief-normalize`           | 1                                 | Challenge、C0、Brief input/default、Software Demo Policy              | Creative Brief；Policy 由 Controller 另行发布       | 不暂停；合法即继续         |
| C2 `creative-territory-explore`         | 6                                 | C0、C1、Software Demo Policy、单个 software-native lens                 | Territory + ≤3 Atoms                            | 保留所有合法输出          |
| C3 `creative-concept-synthesize`        | 4                                 | C0、C1、Software Demo Policy、Controller 生成且显式含 Atom→Territory ref 的全部 Atom index、单个 synthesis lens | 每 Session ≤3 Concepts + primary territory refs  | 合并并稳定去重           |
| C4H `creative-cheap-hook-review`        | 每 Concept 2                       | C0 Constraint、C1、Software Demo Policy、精确 Concept revision          | Hook/分享触发 categorical review                  | 与 C4F 聚合              |
| C4F `creative-software-demo-review`     | 每 Concept 1                       | 与 sibling C4H 相同，但看不到其结果                                      | Feasibility categorical review                  | 与 C4H 聚合              |
| C4R `creative-cheap-hook-repair`        | 最多每 Concept 1                     | 原 Concept + 两份 C4H + 一份 C4F + C0/C1/Policy                         | 新 Concept revision                              | 再做 fresh 2+1 review |
| C5M-R `creative-memory-recall`          | 0 或 1                             | C0/C1、Atom index、base Concept disposition index、冻结 memory snapshot | ≤8 Inspiration Cues + current relations         | 无历史/disabled 时不调用 |
| C5M-X `creative-memory-remix`           | 最多 2                              | C0/C1、Software Demo Policy、指定当前 Atom、指定 cues                      | 每 Session ≤1 challenger + primary territory ref | 总数 ≤2，不递归         |
| C4H'/C4F'                               | 每 challenger 同 C4H+C4F            | 与普通 C4 完全相同；不含 memory                                            | 3 reviews + 可选 revision                        | 与普通 Concept 同矩阵   |
| C5W `creative-novelty-scan`             | 每通过 Concept 1                     | C0、C1、精确 Concept revision                                          | Novelty Scan + sources                          | 唯一联网任务；只提供证据      |
| C6A `creative-evidence-revise`          | 每通过 Concept 1                     | Concept、Hook、Feasibility、Novelty、相关 Memory cues、C0/C1/Policy       | 新 Concept revision                              | 全部进入自动策展池         |
| C6B `creative-portfolio-curate`         | 2                                 | 所有 C6A Concept + Hook/Feasibility/Novelty 摘要 + Policy                | categorical dimensions + include/hold/exclude   | 控制器确定性 shortlist  |
| C6C `creative-feedback-revise`          | 每个 `revise/merge` 结果 1；`keep` 为 0 | 精确来源、批准反馈、C0/C1、必要证据                                               | Final Creative Idea                             | 最多一次              |
| C7                                      | 0                                 | 已验证 Hub 数据                                                         | 报告、Idea Cards、JSON handoff、Memory Record        | 控制器确定性完成          |


这张表中的三个 revision stage 分别消费上一节定义的独立预算。C5M 是唯一允许在第一轮 C4 之后新增 Concept ID 的分支，但只能运行一次且最多两个 challenger；challenger 的 C4H'/C4F' 不能回到 C5M。C4R 之后只能复审，C6A 之后只能进入 shortlist，C6C 之后只能进入 C7。C1–C5 没有人工等待；C6 始终是唯一 Human-in-the-loop gate。

### 9.3 C0 输出协议

`creative-challenge.schema.json`：

```json
{
  "challenge_brief_markdown": "...",
  "constraint_view_markdown": "..."
}
```

Challenge Brief 必需 H2：

- `Challenge Summary`
- `Judging Context`
- `Sponsor and Technology Context`
- `Ambiguities`

Constraint View 必需 H2：

- `Hard Rules`
- `Required Technology`
- `Data and Permission Boundaries`
- `Time, Team and Deliverables`
- `Open Questions`

事实、原文要求和推断必须用明确标签区分。缺失硬约束是任务无效，不允许 Agent 猜测补齐后静默继续。

### 9.4 C1 输出协议

输入优先级：

1. Percy 提供的 `--creative-brief-file`；
2. Percy 提供的 `--creative-brief`；
3. 控制器内置并持久化的默认简报。

两种显式参数互斥。默认简报也是 run input，后续报告必须可见，不能成为隐藏 Prompt。

Creative Brief 必需 H2：

- `Intended Reactions`
- `Anti-goals`
- `Audience and Experience Context`
- `Thirty-second Reveal Window`
- `Available Media and Boundaries`
- `Default Assumptions`

Controller 还必须发布并登记：

```json
{
  "schema_version": 2,
  "policy_version": "2",
  "medium": "software_first",
  "ordinary_device_io": "allowed",
  "custom_hardware_or_fabrication": "forbidden_as_core",
  "manual_performance_or_installation": "forbidden_as_core",
  "real_end_to_end_demo": "required",
  "mock_or_wizard_of_oz_core": "forbidden"
}
```

Policy bytes 不由 Brief Normalizer 生成或改写。Controller 对 canonical JSON
计算 SHA-256，登记在 `inputs.software_demo_policy` 并作为同一 frozen resource
进入 C1/C2/C3/C4H/C4F/C5M Remix/C6A/C6B。普通 laptop/phone 与其内置
screen、keyboard、touch、camera、microphone、speaker、accelerometer 合法；
Arduino、机器人、专用传感器、焊接、实体制作、设备搬运/校准不可作为核心。
投影/显示器可以是输出出口，但不能代替软件机制。C1 只规范化 Brief，不发明
Percy 没有表达的强品味结论，也不暂停等待批准。

### 9.5 C2 输出协议

每个 Territory 输出：

```json
{
  "territory_markdown": "...",
  "atoms": [
    {"markdown": "..."}
  ]
}
```

Creative Atom 必需 H2：

- `Territory`
- `Trigger`
- `Audience Action`
- `Mechanism`
- `Transformation`
- `Reveal`
- `Aftertaste`
- `Software Surface and Demo Proof`
- `Challenge Fit and Risks`

`Territory` section 用自然语言说明该 Atom 所属的机制空间，不要求也不依赖模型
回显 Controller 内部 ID。Controller 按 fanout slot 分配稳定 Territory/Atom ID，
发布 Atom 时用 `source_refs`、`territory_ref`、`territory_slot` 与
`atom_slot` 形成结构化绑定。给 C3 的 Atom index 必须显式渲染每个
`Atom ref → Territory ref`，再附上原始 Atom Markdown；C3 不得从自然语言或
`task_id` 猜测绑定。离线 validation 逐项复核 Atom ID、metadata、source refs
和目标 Territory artifact，任何不一致都 fail closed。

语义检查拒绝：

- 只有名称、视觉风格或营销措辞不同；
- 没有受众动作；
- “AI 自动生成惊喜内容”但没有可解释机制；
- 软件只计时/播放素材，核心因果由主持人、演员、道具或参与者协商完成；
- 依赖定制硬件、实体制作或普通团队在比赛期间无法取得的设备；
- 把网络先例当作输入。

### 9.6 C3 输出协议

Concept 必需 H2：

- `Intended Reaction`
- `One-sentence Hook`
- `First Impression`
- `Audience Action`
- `Setup, Reveal and Aftertaste`
- `Real Input, Transformation and Output`
- `Software Core and Runtime`
- `Share Trigger and Artifact`
- `Why It Is Unexpected Yet Legible`
- `Minimum Hackathon Demo`
- `Assumptions, Confusion and Risks`
- `Parent Atoms`

`Software Core and Runtime` 必须包含运行入口、主要 code/model/API/protocol、
真实 input 取得方式、executable transformation、observable output 与外部依赖。
`Share Trigger and Artifact` 必须说明立即分享冲动、实际分享的 URL/录屏/结果/
挑战/remix，以及明确的人群；单写“有传播性”无效。若唯一传播路径是用户手工
开始录屏、裁剪、上传再解释，必须把这些动作和耗时写出，不能把“系统允许录屏”
等同于低摩擦 share trigger。

Concept 还必须在既有 section 中呈现两段不增加 Schema/H2 的可读性合同：

- `Audience Action`、`Software Core and Runtime` 与
  `Why It Is Unexpected Yet Legible` 合起来必须能抽取三句朴素描述：
  “用户做什么”“软件立刻做出什么可观察回应”“为什么用户会再试或分享”。
  只写隐喻、情绪、世界观、氛围或技术名词不满足合同。
- `Why It Is Unexpected Yet Legible` 必须指出一个人们已经理解的
  recognizable product grammar，并说明本 Concept 保留了哪种熟悉入口、对核心
  机制做了什么变化。允许引用“关系路径探索器”“实时音乐搭档”“可分享生成
  玩具”“多人挑战”“创作工具”等产品家族，不要求或允许编造具体产品、URL 或
  研究事实。

Prompt 内提供两个只用于校准质量形状的正例：任意人物的六度关系路径探索器，
以及根据真人演奏实时回应的 Jam 搭档。它们共同证明“熟悉入口 + 真实输入 +
即时软件反馈 + 可重复玩法 + 自然分享物”是什么样子；Prompt 明确禁止复制
六度关系或 AI 乐手的表面题材。它们属于静态 Prompt rubric，不作为当前 run
的外部证据，也不改变 C3 只读取 C0-C2 data blocks 的 Harness 合同。

`Minimum Hackathon Demo` 必须给出比赛时间内的最小 build cut，并按固定顺序写清：

1. 从打开 URL/运行入口开始，到首个有感受输出为止的冷启动步骤与总时长；必要
   permission prompt、首个真实 input、模型 warm-up、room join 和设备 pairing
   都在约 30 秒时钟内；
2. 关键路径子系统列表与 `subsystem_count`；无 C0 明示预算时按第 8 节的最多三个
   子系统、一个简单 backend、一个主要浏览器/设备切片判断；
3. 唯一 `riskiest_technical_assumption`、两小时内的 falsification probe、成功
   证据和失败后的 degraded slice；
4. 每项预置状态、自动/人工动作和分钟成本；部署前准备可以列在 30 秒时钟之外，
   但仍计入 build/operation budget，不能从 Concept 中省略；
5. 现场验收证据。

提到 `getUserMedia`、MediaRecorder、Web Audio、WebSocket、Canvas 或模型 SDK
不构成可实现性证明；Concept 还要说明目标 browser/device、secure-context/
permission/user-gesture 要求、预期延迟、输入质量边界和失败路径。不能用 Figma、
预录视频、人工选择或 mock API 代替核心机制。

每个 Concept envelope 还必须返回 `primary_territory_ref`。四个 synthesizer 都能看到完整 Atom index，但各自收到不同、持久化的 synthesis lens。模型不能自行创建稳定 ID；semantic validator 要求 `primary_territory_ref` 对应至少一个 Parent Atom 的 Territory。它一经发布就属于 Concept identity metadata，后续 reviewer/curator 不能改写。

这四个任务的 parent refs、registered context 与最终 Prompt 必须只包含 C0-C2；即使 controller-owned Snapshot 已在 run 创建时冻结，也不能在 C3 前注入。`CreativeRunContract` 将任何提前出现的 memory block/ref 视为合同错误。

这是 Harness 可验证的上下文隔离，不是主机文件系统保密边界：当前 `CodexRunner` 的 `read-only` sandbox 不是 chroot。C2/C3/初始 C4 的 task policy 还必须明确禁止主动扫描 run 历史，但当前 Creative contracts 不声称能抵御恶意 Session 猜路径读取。若未来要提供该级别保证，需要独立容器/进程级文件系统 allowlist，不在本 PRD 范围内。

控制器的“去重”只处理字节相同或规范化 Hook 完全相同的机械重复；语义近似项不在此阶段自动合并。

### 9.7 C4H/C4F 判断与修复矩阵

#### 9.7.1 C4H Cheap Hook + Share Trigger

每份 Cheap Hook Review 对七项判断分别输出：

- `pass`
- `uncertain`
- `fail`

并给出 `overall_decision=pass|repairable|invalid` 和引用 Concept 原文的证据。七项判断是：

1. 铺垫能否迅速理解；
2. Reveal 是否改变预期；
3. 惊喜是否来自机制；
4. 约 30 秒内是否到达有感受的时刻；
5. 是否无需长篇解释即可复述；
6. 是否不依赖隐藏人工、不可能权限或虚假能力；
7. 是否存在具体、立即、可解释且有实际 artifact 的分享触发，而不是抽象宣称 viral。

第 4 项从用户打开真实入口开始计时，包含权限、首个输入、配对和 warm-up；不能从
已经预置好的“完美 reveal 前一秒”开始。第 5、7 项必须分别给 evidence 和 verdict：
一句话复述通过不能推导分享通过。若分享仍需要手工录屏、裁剪、上传和补充解释，
reviewer 应按真实步骤评估摩擦；仅写“可录屏”不足以通过第 7 项。

每个非 `pass` 维度还必须返回与顺序一一对应的稳定原因码：

1. `setup_not_quickly_legible`
2. `reveal_does_not_shift_expectation`
3. `surprise_not_mechanism_driven`
4. `misses_thirty_second_moment`
5. `not_one_sentence_retainable`
6. `requires_hidden_labor_or_impossible_capability`
7. `no_immediate_share_trigger`

#### 9.7.2 C4F Software Demo Feasibility

每个 exact revision 另启动一个 `creative-software-demo-review` fresh Session；
它看不到两份 C4H sibling、history、memory、novelty 或其他候选。七项固定维度
同样输出 `pass|uncertain|fail`、逐项 evidence，以及
`overall_decision=pass|repairable|invalid`：

| Dimension | 通过含义 | 非通过 reason code |
| --- | --- | --- |
| `software_first_core` | 核心体验由可执行软件产生 | `core_not_software_first` |
| `hardware_independence` | 不依赖定制硬件、实体制作、专用传感器或设备搭建 | `requires_custom_hardware_or_fabrication` |
| `technical_demo_substance` | 主持人、演员、参与者协商或道具不完成核心因果 | `core_is_manual_performance_or_installation` |
| `end_to_end_demo_path` | 真实 input → software transformation → observable output 完整 | `no_runnable_end_to_end_demo_path` |
| `dependency_integrity` | 数据、API、模型、权限与服务真实可得 | `requires_unavailable_dependency_or_permission` |
| `hackathon_scope` | 最小 cut 在 C0 团队/时间约束内可建 | `not_buildable_within_hackathon_budget` |
| `core_proof` | Demo 真正证明核心机制而非 mock/预录/wizard-of-oz | `demo_does_not_prove_core_mechanism` |

`invalid` 只用于 Concept 原文明示的硬失败；信息不足或可以缩小 Demo cut 澄清
时必须是 `repairable`。使用普通设备内置 I/O 不能单独触发 hardware failure。

C4F 的职责分成两层，两层都通过才可输出 `overall_decision=pass`：

1. **路线合规：** software-first、非定制硬件、非人工/装置核心、非 mock；
2. **参考实现可交付：** 冷启动路径可信，关键路径在预算内，最高风险假设可先行
   证伪，降级切片仍证明核心机制，预置状态可重复创建，目标环境依赖可稳定取得。

第二层按下列机械映射复用现有七维 shape/reason code：

| 新检查 | 归属现有维度 | 非通过时沿用的 reason code |
| --- | --- | --- |
| 冷启动步骤缺失，或真实输入到输出的 30 秒路径断裂 | `end_to_end_demo_path` | `no_runnable_end_to_end_demo_path` |
| 超过参考子系统/backend/device 预算，最高风险假设不可快速证伪，或没有仍能证明核心的降级切片 | `hackathon_scope` | `not_buildable_within_hackathon_budget` |
| 预置账号、数据、预热、配对或人工准备不可重复，或成本超出预算 | `hackathon_scope`；若依赖权限不可得则同时看 `dependency_integrity` | `not_buildable_within_hackathon_budget` / `requires_unavailable_dependency_or_permission` |
| 只列标准 Web API/SDK 名称，没有目标环境、permission、secure context、延迟和失败证据 | `dependency_integrity` | `requires_unavailable_dependency_or_permission` |
| 降级后只剩录屏、假数据或人工代劳，不能证明核心机制 | `core_proof` | `demo_does_not_prove_core_mechanism` |

信息缺失时这些维度为 `uncertain` 且整体为 `repairable`；Concept 已明确超出预算、
目标环境明确不支持，或失败后只能 mock 核心时才为 `fail/invalid`。因此“标准 API
存在”本身永远不足以得到 `pass`，但也不会因为 reviewer 没看到细节就被误判成
硬失败。

三份独立 review 的 Controller 聚合：

| C4H A | C4H B | C4F | 路由 |
| --- | --- | --- | --- |
| `pass` | `pass` | `pass` | 完整 C4 pass |
| 任意 | 任意 | `invalid` 且为明确 non-software/hardware/manual/install/dependency hard failure | `c4_software_demo_invalid` 终态淘汰 |
| `invalid` | `invalid` | 任意 | `c4_double_invalid` 终态淘汰 |
| 其他 | 其他 | 其他 | 使用共享的一次 `repairable` budget |

`repairable` 只允许一次局部修复，并必须保留 Concept 核心身份与 `primary_territory_ref`。为了让该边界可机械验证，`Intended Reaction`、`Real Input, Transformation and Output`、`Parent Atoms` 三个 section body 必须与 source 保持一致，Prompt 必须把这三个不可变 section 明示给 Agent；时长、铺垫、runtime、依赖、分享 artifact、风险和最小 Demo 的局部澄清只能写入其他 section。把装置/硬件核心改成 App 是新 Concept，不是局部修复。修复后由三份 fresh Session 重新执行 2×C4H+1×C4F：

- 三者均 `pass` 才通过；
- 任何其他结果都以 `unresolved_after_repair` 淘汰；
- 不开启第二轮修复。

任何 reviewer 任务失败都使 run 失败，不能被解释为该 Concept 的 `invalid`。

控制器为每个被路由的 revision 发布 `ConceptDisposition`：

```json
{
  "disposition_id": "creative-disposition-...",
  "concept_revision_ref": "...",
  "concept_sha256": "...",
  "stage": "C4",
  "outcome": "pass|repair|eliminated",
  "terminal": false,
  "target_ref": null,
  "reason_codes": ["c4_software_demo_invalid", "core_is_manual_performance_or_installation"],
  "decision_ref": "...",
  "evidence_refs": ["hook-review-ref-a", "hook-review-ref-b", "feasibility-review-ref"],
  "task_refs": ["..."]
}
```

C4F 明确硬失败的 controller 原因码是 `c4_software_demo_invalid`，双 C4H `invalid` 是 `c4_double_invalid`；修复后未获得 2+1 全 pass 是 `c4_unresolved_after_repair`。decision metadata 必须分开保存 `hook_review_refs`、`feasibility_review_ref` 与聚合矩阵版本。`pass/repair` 为 `terminal=false`，C4 淘汰为 `terminal=true`。进入 repair 的旧 revision 在修复产物验证并发布后，继续以 `superseded_by_hook_repair` 终结并把 `target_ref` 指向新 revision；新 revision 再拥有自己的 C4 disposition。基础设施/Schema/协议失败只写 task/run error，不得生成 `eliminated` disposition。

一个 revision 可以随阶段产生多个不可变 disposition，但 completed run 中每个 revision 必须恰好有一个 `terminal=true` disposition；例如 C4 pass 先是非终态，C6A 发布新 revision 时旧 revision 再以 `superseded_by_evidence_revision` 终结。指向后继 revision 或 Final Idea 的终态必须带 `target_ref`，直接淘汰/拒绝的终态必须为 `target_ref=null`。运行中允许存在尚未闭合的 revision；failed partial report 必须如实保留它们并引用 terminal error。Completed-run validator 拒绝没有终态、拥有两个终态或 target 不存在/类型错误的 revision。

### 9.8 C5M Idea Memory Recall / Remix

#### 9.8.1 Source discovery 与冻结

`CreativeIdeaWorkflow.create()` 在创建当前 run 目录前扫描显式 `runs_dir` 的直接子目录；不递归、不跟随 symlink，也不读取另一个任意路径。候选来源必须同时满足：

- `route.id=creative`；
- `status=completed`；
- 通过 Hub core 与 CreativeRunContract 离线验证；
- `creative-memory-record.json` 的 schema/contract/report policy 仍被当前代码支持；
- artifact record、文件和内部 capsule hash 一致；
- 不是 benchmark fixture；
- 不是当前待创建 run。

completed 的零 Idea run 合法且有价值；Useful、waiting、failed、partial、未知 route/version 和损坏来源默认排除。`auto` 模式对单个坏来源写 diagnostic 后继续，不能把它当成 caution Idea；若 snapshot 本身在创建后被篡改，当前 run fail closed。

发现结果按持久化 `created_at` 倒序，再按 `run_id`、`memory_entry_id` 排序，应用第 8 节的 run/entry/byte 上限，并复制为：

```text
state/creative-memory/idea-memory-snapshot.json
```

最小合同：

```json
{
  "schema_version": 2,
  "mode": "auto|off",
  "created_from": "runs_dir|disabled",
  "source_records": [
    {
      "source_run_id": "...",
      "source_route_id": "creative",
      "source_contract_version": "1|2",
      "source_memory_record_artifact_id": "...",
      "source_memory_record_sha256": "..."
    }
  ],
  "entries": [],
  "diagnostics": [],
  "truncated": false
}
```

snapshot 自包含所选 capsule；后续不再读取源 run。`mode=off` 与无历史也都写一个合法空 snapshot，分别使用 `empty_reason=disabled` 与 `empty_reason=no_eligible_history`，避免隐藏输入。

Snapshot 内每个 capsule 的跨 run 身份固定为：

```json
{
  "source_run_id": "...",
  "source_route_id": "creative",
  "source_contract_version": "1|2",
  "source_artifact_id": "...",
  "source_artifact_sha256": "...",
  "source_memory_record_artifact_id": "...",
  "source_memory_record_sha256": "...",
  "capsule_sha256": "..."
}
```

`source_artifact_id` 指 capsule 的 terminal Concept revision 或 Final Idea。Discovery 时验证 source artifact/hash 与 memory record 声明一致，再对复制进 snapshot 的 canonical capsule 单独计算 `capsule_sha256`。当前 run 后续只复核 snapshot/capsule hash，不追踪外部路径，也不假装能从摘要重算完整 source artifact hash。

#### 9.8.2 Memory Recall

只有 snapshot 非空并且当前 run 至少有一个合法 Atom 时才启动一个 `creative-memory-recall` fresh Session。允许上下文只有：

- C0/C1；
- 当前 Atom 的精简 index；
- 第一批 Concept 的 Hook/Feasibility 摘要、parent refs、C4 terminal
  outcome/reason codes；
- frozen capsule。

禁止输入旧完整 Idea Card、旧 Prompt/任务日志、reviewer ID/name、原始评论或未批准反馈。

所有 capsule/cue 都以 Prompt 数据边界注入并明确声明为不可信历史文本；其中的命令式内容不能改变工具、网络、stage、输出路径、数量上限或安全策略。

输出 `MemoryInspirationPacket`：

```json
{
  "cues": [
    {
      "cue_id": "memory-cue-01",
      "source_memory_refs": [],
      "role": "inspire|avoid",
      "transferable_pattern": "...",
      "why_relevant": "...",
      "current_atom_refs": [],
      "related_concept_refs": [],
      "elements_that_must_not_be_copied": []
    }
  ],
  "no_relevant_memory_reason": null
}
```

最多八条 cue。`avoid` 表示“在当时条件下失败或被主观否决”，不能升级为跨挑战真理；`portfolio_only` 也不能被解释为质量失败。

#### 9.8.3 Memory Remix challenger

控制器最多启动两个 `creative-memory-remix` fresh Session，每个只能看到 C0/C1、当前 run 的 exact Software Demo Policy、指定 current Atom 和指定 cue，并最多生成一个 challenger。过去的硬件/装置 Concept 可以贡献抽象 `inspire|avoid` 机制，但 challenger 不能继承旧媒介豁免。每个输出必须增加：

- `Current Atom Sources`
- `Past Inspiration Used`
- `What Was Transformed`
- `Why This Is Not A Copy`

metadata 必须包含至少一个 `current_atom_ref`、至少一个复合 `memory_source_ref`、cue refs 和 `primary_territory_ref`。Challenger 是新的 `creative-concept-mNN-r001`，不是任何 base/past Concept 的 revision。Semantic validator 要求 primary territory 属于 current Atom sources，并拒绝：

- 与来源规范化 Hook 完全相同；
- 只换名称/外观；
- 缺少当前 Atom；
- 直接重复 capsule 中的 mechanism + reveal 组合；
- 引用 snapshot 外来源；
- 超过两个 challenger。

所有 challenger 使用 9.7 的 2×C4H + 1×C4F、共享修复矩阵和预算，然后与 base pass 集合合并。C5M 只执行一次；challenger 不再触发 Recall/Remix。

在 `idea-memory=auto` 下，Recall/Remix 是可选增强。Recall 失败时不启动 Remix；Recall 成功后，至多两个 Remix 使用 all-settled 聚合，控制器等待所有已启动 sibling 进入终态。每个成功且通过 Schema/语义验证的 challenger 都保留并进入 C4；只跳过失败或无效的 sibling，不能因为另一个分支失败而回滚成功 challenger。

每个失败分支必须以 `optional_memory_stage_failed` event/diagnostic 可见地记录 task ref、stage、failure kind 和 sibling outcome，并继续使用已经持久化的 base/成功 challenger；它不能被记为“无历史”、不能生成伪 challenger，也不能改变 base Concept 的 C4 disposition。Completed Creative run 允许存在这种 failed/invalidated task，当且仅当 task 的 `failure_policy=optional_branch`、stage 属于 C5M allowlist，且有唯一匹配 diagnostic；其他 failed task 仍然 fatal。

控制器在 disabled、empty、Recall failure 和 Remix all-settled 等所有 C5M 路径上都恰好发布一个不调用模型的 `MemoryStageSummary`：

```json
{
  "status": "disabled|empty|completed|optional_failed",
  "recall": {
    "status": "succeeded|failed|invalidated|not_started",
    "task_ref": null,
    "diagnostic_ref": null
  },
  "selected_cue_ids": [],
  "remix_slots": [
    {
      "slot": 1,
      "status": "succeeded|failed|invalidated|not_started",
      "task_ref": null,
      "challenger_ref": null,
      "diagnostic_ref": null
    }
  ]
}
```

Recall 或任一 optional sibling 失败即为 `status=optional_failed`，即使另一个 sibling 成功；成功 challenger refs 仍必须保留，不能把该状态解释成“Memory 完全没有产出”。Disabled/empty 时 Recall 与全部 Remix slot 都是 `not_started`。

#### 9.8.4 C5W Novelty Scan

C5W 是唯一联网阶段，对 base 与 memory challenger 中每个通过完整 C4H+C4F screen 的 Concept 使用一个 fresh Session。C5W task 数必须严格等于该 pass 集数量；硬件/装置/不可运行项在这里之前已经终态淘汰。输出：

```json
{
  "markdown": "...",
  "sources": [
    {
      "title": "...",
      "url": "https://...",
      "relation": "direct|near|trope|adjacent|counterexample",
      "evidence": "简短释义"
    }
  ]
}
```

必需 H2：

- `Search Strategy`
- `Direct and Near Collisions`
- `Common Tropes and AI Smell`
- `Distinctive Combination`
- `Cultural and Safety References`
- `Counterevidence and Uncertainty`

规则：

- 优先保存项目、作者、比赛或机构的一手页面；
- 引用 URL 必须是绝对 HTTP(S) URL；
- 搜索失败是必需任务失败并产生 partial report，不是假装“没有先例”；
- Scan 不直接输出 route pass/reject；
- Scan 不重新判断 feasibility；
- 相似组件存在不等于核心组合无效；
- 除查找碰撞外，Scan 还要找出 Concept 最接近的 recognizable product
  grammar，并区分“可借用的熟悉入口/反馈循环”与“不得照抄的表面题材或核心
  机制”；这类证据仍写入现有 H2 与 `relation=adjacent|counterexample`，不新增
  Schema 字段；
- memory challenger 不因带 provenance 而免除外部查重。

### 9.9 C6A 证据驱动修订

每个完整 C4 pass Concept 根据四类有界证据生成恰好一个新 revision：

- Cheap Hook Review；
- Software Demo Feasibility Review；
- Novelty Scan。
- 与本 Concept 相关的 Memory cue/relation；没有相关 cue 时传入显式空集合。

C6A 必须把经 C5W 验证的先例证据用于降低理解门槛，而不是继续增加抽象性：
在可变的 `Why It Is Unexpected Yet Legible`、`Audience Action`、
`One-sentence Hook` 和风险/证据 sections 中，写清 Concept 借用了哪种熟悉
产品语法、用户如何开始、软件如何回应、为何值得重复或分享，以及核心机制与
最近先例的实质差异。若 C5W 没有支持某个具体先例，C6A 不得编造名称或 URL。
这种改写不能触碰三个机械不可变 identity sections，也不能改变 product core。

必需新增 H2：

- `Evidence-informed Changes`
- `Evidence Deliberately Not Adopted`

Agent 可以澄清 software runtime、依赖、最小 Demo cut、现场可观察证据和 share artifact，但不能把硬件/人工核心替换成软件核心，也不能更换核心机制或 `primary_territory_ref` 后仍声称是同一 revision；若确需根本变化，应在本轮保留原 Concept 并把建议记录为未来分支，不自动扩张候选数。

与 C4R 相同，C6A 必须逐字保留 source 的 `Intended Reaction`、
`Real Input, Transformation and Output` 与 `Parent Atoms` section body；
证据只允许改变其他标准 section 和两个新增 evidence section。Prompt 必须明示
该规则，不能让 semantic validator 形成模型不可见的后置条件。

新 evidence revision 通过 Schema、语义与 hash 验证并发布后，控制器为 source revision 写 `terminal=true`、`outcome=superseded_by_evidence_revision`、`reason_code=c6_evidence_revision_published` 的 disposition，并把 `target_ref` 指向新 revision。新 revision 从 C6B 开始拥有自己的处置链；若 Agent/验证失败导致 run failed，不能伪造这条成功转移。

### 9.10 C6B 自动 shortlist

两个独立 Portfolio Curator 对每个候选的以下固定维度分别返回
`pass|uncertain|fail`、reason 和 evidence：

- `software_demo_strength`
- `surprise_fun_or_intrigue`
- `one_sentence_clarity`
- `immediate_share_trigger`
- `novel_combination`

Controller 按 slot 写入不可变 `CURATOR_LENS` data block，使两份 fresh
Session 的错误模式尽量不同：

| slot | 固定角色 | 首要反证问题 |
| --- | --- | --- |
| 1 | `meaning_value_red_team` | 去掉诗性文案和视觉氛围后，是否还有普通人能解释、会重复使用或愿意分享的真实产品循环？它是否只是需要策展说明的装置隐喻、一次性 AI 效果或无意义产物？ |
| 2 | `hackathon_floor_red_team` | 在真实黑客松展厅里，路人是否能在约 30 秒内亲手开始、看到技术反馈、愿意再试并拉朋友来玩？还是只能站着看作者表演、听长篇解释或相信尚不存在的 Demo？ |

每个 Lens 都必须评完同样五个维度，不能只输出自己偏好的部分。Lens 只改变
审查视角，不改变输出 Schema、reason enum、include/hold/exclude 机械关系或
Controller shortlist 算法。Artifact metadata 记录 `curator_slot` 和稳定
`curator_lens_id`，便于报告与离线 validator 证明两份任务没有拿到相同角色。
这两个 block/metadata 只属于 frozen C6B template v4；resume v2/v3 frozen run
时 Controller 必须保留旧 prompt block 与 artifact metadata shape，不能把旧
curator 事后标记成执行过新 lens。

Meaning/Value 角色把以下情况视为现有维度的明确失败证据：必须先读策展文案才
知道发生了什么；用户动作不能影响有意义的输出；除“看一个氛围/奇观”外没有
可重复玩法；产物对收件人没有可解释价值。Hackathon Floor 角色把以下情况视为
明确失败证据：观众不能亲自操作；反馈主要由作者/主持人/表演者完成；现场路径
依赖长设置或讲解；所谓“好玩”没有第二次输入、模式变化、挑战、创作或社交循环
支持。两者都必须区分“我个人不喜欢”与 Concept 中可引用的证据。

每位 curator 的 `decision` 由 Schema/semantic validator 机械约束：全部维度
`pass` → `include`；没有 `fail` 且至少一个 `uncertain` → `hold`；任一
`fail` → `exclude`。可以额外返回可能重复的候选引用，但不得输出或改写
`primary_territory_ref`，不得输出 1–10 总分或全排序。Controller 只使用
Concept metadata 中已经验证的 primary territory，且输入池只能包含 C4F pass
项。

五个维度彼此独立：`one_sentence_clarity=pass` 不能推导
`immediate_share_trigger=pass`；后者必须把手工录屏、剪辑、上传、复制链接和
额外解释作为真实摩擦。`software_demo_strength` 必须复核第 8 节参考预算和 C4F
证据，不能因出现标准 Web API 名称而通过。

每位 curator 还要在整个候选池中按四元组建立机制族：

```text
(audience input, executable transformation, reveal structure, share artifact/loop)
```

如果两个候选在其中至少三项实质相同，仅更换主题、视觉皮肤、文案或 Territory
标签，则必须互相写入现有 duplicate refs；`novel_combination` 只能让其中机制/
体验证据最完整的代表项通过，其余至少为 `uncertain`。两个 curator 可以独立选择
不同代表，Controller 仍只聚合 categorical decision，不新增语义聚类器或自动
合并。Territory round-robin 是第二层多样性，不能覆盖这个机制级判断。

控制器按以下确定性规则生成最多 8 个候选：

1. 先取两个 curator 都 `include` 的候选；
2. 再取一个 `include`、另一个 `hold` 的候选；
3. 仍有空位时取单个 `include` 的分歧项；
4. 每一层内先按尚未覆盖的 `primary_territory_ref` 做稳定 round-robin，再按 Concept ID；
5. 从不自动合并语义近似项；
6. 所有未入选项写明 curator 决定和控制器规则，不从 run 中删除。

这是“批准票 + 多样性约束”，不是把模型分数伪装成客观质量。

每个 shortlist/未入选 revision 都发布新的 `ConceptDisposition`。进入 shortlist 写 `outcome=shortlisted`、`terminal=false`；未入选写 `outcome=not_shortlisted`、`terminal=true`。未入选原因码至少区分：

- `curators_both_exclude`
- `insufficient_include_support`
- `portfolio_capacity`
- `territory_round_robin_capacity`

后两个是组合容量原因，不得写成“质量不合格”。若最终 shortlist 为空，仍发布：

```json
{
  "batch_id": "creative-review-batch-r001",
  "status": "skipped_empty",
  "concept_refs": [],
  "skip_reason": "no_concepts_generated|all_candidates_failed_concept_screen|shortlist_empty"
}
```

控制器不写 `wait`、不启动 review server，直接进入 C7。该 batch 与完整 disposition ledger 一起证明为什么没有人工评审。`all_candidates_failed_hook` 只属于 frozen v1 contract；loader/validator 根据 persisted contract version 分派，不能在 v2 新 batch 中继续写旧 code，也不能回写旧 run。

### 9.11 C6C 人类决议与反馈修订

Percy 的 resolution 对每个 shortlist revision 指定：

- `keep`
- `revise`
- `reject`
- `taste_veto`
- `merge`，并列出两个或更多 source refs

`keep` 由控制器把精确 Concept revision 提升为 Final Creative Idea，不调用模型；`revise` 与 `merge` 使用批准的反馈做一次修订；`reject/taste_veto` 不调用模型。这样 Human 的“保持不变”不会被一次无必要的润色悄然改写。

`keep/revise` 保留 source Concept 的 `primary_territory_ref`；`merge` 输出必须从 merge sources 已验证的 primary refs 中选择一个，并写入 Final Idea metadata。Agent 不能发明不属于来源 Atom 的新 primary territory。

关闭评审轮次时只验证并持久化 immutable resolution、latest receipt-set hash 与 `wait.status=closed`；此时不写任何 terminal disposition，因为 `revise/merge` 的目标 Final Idea 尚不存在。

`hacksome resume` 把 run 转回 `running` 后，按 resolution 为每个 shortlist revision 写恰好一个 terminal disposition：

- `keep` → `promoted_to_final`，`target_ref` 指向控制器直接提升的 Final Idea；
- `revise` → `revised_into`，`target_ref` 指向反馈修订后的 Final Idea；
- `reject` → `human_reject`，`target_ref=null`；
- `taste_veto` → `human_taste_veto`，`target_ref=null`；
- `merge` → 每个 source revision 都写 `merged_into`，并把 `target_ref` 指向同一个合并后的 Final Idea。

`keep` 必须先由控制器发布 Final Idea，`revise/merge` 必须先让 Agent 结果通过 Schema/语义/hash 验证并发布 Final Idea，之后才能写带 `target_ref` 的 disposition；`reject/taste_veto` 也统一在 resume 中闭合。若 C6C task 或验证失败，尚未处理的 source revision 保持非终态，failed partial report 引用 terminal error，绝不能提前声称修订/合并成功。

这些 disposition 引用 resolution 与 approved fragment/curator instruction hash，并分别使用稳定的 keep/revise/reject/taste-veto/merge 原因码。跨 run memory record 只保留 outcome 类别和 refs，不复制 reviewer 身份、原始评论或 curator instruction 正文。`taste_veto` 明确标记为主观品味，不得被未来 Agent 当成通用可行性失败。

每个 Agent 输出必须增加：

- `Feedback Adopted`
- `Feedback Rejected or Conflicting`
- `Unresolved Risks`

反馈是带边界的不可信数据，不能改变工具权限、Prompt 规则、输出路径、route 或循环上限。

### 9.12 C7 输出

正常完成时，控制器不调用模型，按稳定 ID 排序生成：

```text
artifacts/creative/report/creative-idea-report.md
artifacts/creative/report/creative-idea-report.json
artifacts/creative/idea-cards/<idea-id>.md
artifacts/creative/idea-cards/index.md
artifacts/creative/handoffs/<idea-id>.json
artifacts/creative/memory/creative-memory-record.json
```

若某个必需任务 fatal failure，controller 的顶层 error handler 在保留 `status=failed` 的前提下生成：

```text
artifacts/creative/report/creative-partial-report.md
artifacts/creative/report/creative-partial-report.json
```

在 finalization manifest 生成前，partial report 只读取失败发生前已验证并持久化的数据，包含 terminal error/task/log refs，但不得生成 Idea Card、handoff 或 `completed` event。Manifest 生成后的普通 publish/process 中断不转成 fatal，而是保留可恢复的 `creative-finalization`；只有 staged/existing bytes 篡改等不可安全重放的问题才 fail closed，此时 plan-linked 文件/record 也不得进入 `result_artifact_ids` 或被解释成有效 Final 输出。若 partial render 本身失败，保留原始 run failure，并追加一个 report-render error；不能覆盖最初错误。

正常报告包含所有生成、临时基础设施重试、修复、淘汰、shortlist、人工反馈、合并、分歧和最终项，并固定包含 `Candidate Fate Ledger`、`Idea Memory Used` 与 `Memory-derived Branches`。C4 fate 必须分别列出 Hook 与 Feasibility review refs、维度 reason codes 和证据；零 Idea 时再包含 `Zero-Idea Explanation`，逐项列出 terminal stage、reason codes、decision/evidence refs 和空 C6 batch 的 `skip_reason`。这些段落由控制器投影，不调用模型做事后归因。

重复渲染相同 Hub 数据必须得到字节完全相同的报告；动态时间戳只能来自已持久化事件，不在 render 时调用当前时间。

#### Final Creative Idea Card

每张卡必须且只能包含一个 H1，并包含下列非空 H2：

- `Intended Reaction`
- `One-sentence Hook`
- `First Thirty Seconds`
- `Audience Action`
- `Core Mechanism`
- `Reveal and Aftertaste`
- `Minimum Hackathon Demo`
- `Why Someone May Share It`
- `Novelty and References`
- `Human Signal`
- `Risks and Unresolved Disagreement`
- `Lineage`

`Core Mechanism` 必须保留 software runtime 与真实 input → transformation →
output；`Minimum Hackathon Demo` 必须保留最小 build cut、依赖和验收证据；
`Why Someone May Share It` 必须保留具体 share trigger/artifact。`Human Signal`
只能陈述本轮 reviewer 的复述、`share_impulse`、`demo_confidence`、分享对象和
分歧，必须标注为构想阶段代理信号，不能声称真实传播力或 build success。
`Lineage` 由控制器写入，至少包含 source Concept revisions、Hook/Feasibility
decision refs、receipt IDs、approved feedback fragment refs、resolution ID 和
Prompt/stage policy version。Idea Card 自身的最终内容 hash 只写在 Hub artifact
record 与 handoff 中，不能嵌回文件造成循环 hash。

#### Machine-readable report

成功摘要的最小顶层合同：

```json
{
  "schema_version": 2,
  "route": {"id": "creative", "contract_version": "2"},
  "run_id": "...",
  "status": "completed",
  "challenge_ref": "...",
  "creative_brief_ref": "...",
  "idea_memory": {
    "mode": "auto|off",
    "snapshot_ref": "...",
    "snapshot_sha256": "...",
    "status": "empty|disabled|completed|optional_failed",
    "selected_cue_ids": [],
    "successful_challenger_refs": [],
    "failed_task_refs": []
  },
  "counts": {},
  "territory_ids": [],
  "concepts": [
    {
      "concept_id": "...",
      "origin": "base|memory_challenger",
      "revision_refs": [],
      "memory_source_refs": [],
      "terminal_outcome": "c4_eliminated|not_shortlisted|promoted_to_final|revised_into|human_reject|human_taste_veto|merged_into",
      "dispositions": [
        {
          "disposition_ref": "...",
          "stage": "C4",
          "outcome": "eliminated",
          "reason_codes": [],
          "decision_ref": "...",
          "evidence_refs": []
        }
      ]
    }
  ],
  "review_rounds": [],
  "zero_reason_code": null,
  "final_idea_card_ids": [],
  "handoff_refs": [],
  "memory_record_ref": "...",
  "report_policy_version": "2"
}
```

零 Idea 成功运行必须显式写 `final_idea_card_ids=[]`、`handoff_refs=[]`，并且 `zero_reason_code` 只能是：

- `no_concepts_generated`
- `all_candidates_failed_concept_screen`
- `shortlist_empty`
- `all_human_rejected`

非零 Idea 时该字段必须为 `null`。v1 report loader 仍接受
`all_candidates_failed_hook`，但只对 persisted contract v1；v2 renderer 不能
生成它。partial JSON 使用 `status=failed`、`terminal_error`、
`completed_stage_ids`，并禁止 final card/handoff/memory-record 字段出现非空值。

#### Idea Memory Record

Memory Record 与 report 使用同一份已验证 Hub projection 确定性生成，但用途不同：report 面向人和审计，memory record 是下一次 run 的有界、去身份化输入。

所有 bytes 先按 7.2.1 写入 finalization staging 并冻结 manifest。逻辑发布顺序固定为：先 report/Idea Cards/handoffs，再发布已经使用 staged report hash 生成的 Memory Record，最后把 run 标为 `completed`。Report JSON 只写预先分配的 `memory_record_ref`，不嵌入 Memory Record hash；Memory Record 可以安全写入 report hash，避免循环 hash。中断恢复只重放 manifest，不按当前代码重新生成任何一个文件。

```json
{
  "memory_schema_version": 2,
  "source_run_id": "...",
  "source_route": {"id": "creative", "contract_version": "2"},
  "source_report_artifact_id": "...",
  "source_report_sha256": "...",
  "created_at": "persisted-run-time",
  "producer_kind": "live|fixture",
  "zero_reason_code": null,
  "challenge_context": {
    "summary": "从 C0 精确抽取的有界文本",
    "intended_reactions": "从 C1 精确抽取的有界文本"
  },
  "entries": [
    {
      "memory_entry_id": "memory-...",
      "capsule_sha256": "...",
      "source_kind": "concept_revision|final_idea",
      "source_candidate_ref": "...",
      "source_candidate_sha256": "...",
      "source_concept_refs": [],
      "primary_territory_ref": "...",
      "one_sentence_hook": "...",
      "audience_action": "...",
      "core_mechanism": "...",
      "software_core_and_runtime": "...",
      "share_trigger_and_artifact": "...",
      "minimum_hackathon_demo": "...",
      "reveal_pattern": "...",
      "intended_reaction": "...",
      "terminal_outcome": "...",
      "reason_codes": [],
      "reason_evidence": [
        {
          "reason_code": "...",
          "evidence_excerpt": "从机器 review 精确复制的有界文本",
          "source_review_ref": "...",
          "source_review_sha256": "..."
        }
      ],
      "evidence_refs": [],
      "classification": "positive|caution|portfolio_only|subjective|transformed"
    }
  ]
}
```

Memory Record 为每个 Final Idea 保存一个 `source_kind=final_idea` 的正向 entry。除直接 `promoted_to_final` 的 source Concept 外，每个 terminal Concept revision 都保存一个 `source_kind=concept_revision` entry；直接提升的 source 与 Final Idea 内容相同，省略前者以避免重复。Hook repair、证据修订、人类 revise 与 merge 的 source 因此仍可作为 `transformed` 经验，而变换后的最终成品另有 `positive` entry。`capsule_sha256` 对排除该 hash 字段本身后的 canonical entry 计算，避免 self-reference。

所有文本都是从已验证 section 做定长精确抽取，不新增模型总结。`reason_evidence` 只允许复制机器 Hook 或 Feasibility Review 中与稳定 reason code 绑定的证据；人类 reject/taste veto 只保留主观 outcome/code/ref，不复制原始人类措辞。`primary_territory_ref` 直接来自 Concept/Final Idea metadata，不从 C6B 推断。分类由 controller 根据 terminal outcome/reason code 决定：

- `source_kind=final_idea` → `positive`
- `portfolio_capacity` / `territory_round_robin_capacity` → `portfolio_only`
- `curators_both_exclude` / `insufficient_include_support` → `caution`，并保留“自动策展信号、非永恒质量判决”的来源语义
- C4 Hook 淘汰 → `caution`
- `core_not_software_first`、`requires_custom_hardware_or_fabrication`、
  `core_is_manual_performance_or_installation`、
  `no_runnable_end_to_end_demo_path`、
  `requires_unavailable_dependency_or_permission`、
  `not_buildable_within_hackathon_budget`、
  `demo_does_not_prove_core_mechanism` → 各自保留独立 reason/evidence 的
  `caution`，不得压成模糊的 Hook failure
- `human_reject/taste_veto` → `subjective`
- `superseded_by_hook_repair` / `superseded_by_evidence_revision` / `revised_into` / `merged_into` source → `transformed`

Record 不含 reviewer/curator 身份、原始人类评论、curator instruction 正文、Prompt、task log、Session ID 或绝对本地路径。Fixture 可以生成 record 以测试确定性，但 discovery 必须排除 `producer_kind=fixture`。

每个 handoff 是纯 JSON：

```json
{
  "source_run_id": "...",
  "idea_card_id": "...",
  "idea_card_sha256": "...",
  "challenge_markdown": "...",
  "initial_idea_card_markdown": "..."
}
```

这只建立稳定边界。两个 Markdown 字段有意对齐 BuildFactory
`TeamLayout.bootstrap()`，但当前任务不实现 consumer 或启动 Team。未来
Build-side adapter 必须复核 `idea_card_sha256`，并以至少
`source_run_id + idea_card_id + idea_card_sha256` 生成跨 run 身份，不能只使用
会重复的 card ID。Build Review Gate 仍可以选零张卡，也不能把未选择解释为
Creative 质量 reject。

## 10. 决策与人工反馈 Ledger

### 10.1 机器决策

`RunHub.record_decision()` 保留为 Useful 兼容 wrapper。共享底层增加 route-neutral 记录：

```json
{
  "decision_id": "...",
  "route_id": "creative",
  "stage": "creative-cheap-hook",
  "decision_type": "candidate_gate",
  "outcome": "由 route contract 定义的稳定 stage-specific enum",
  "reason_codes": [],
  "subject_refs": ["..."],
  "evidence_refs": ["..."],
  "task_ids": ["..."],
  "metadata": {},
  "created_at": "..."
}
```

机器决策继续写 `decisions.jsonl`。

`reason_codes` 只能来自 route contract 的稳定枚举；面向人的详细原因保留在 evidence artifact 或 human resolution 中。Controller 不能在 C7 临时发明解释。每个 terminal `ConceptDisposition` 必须引用一条决策，反向也必须能从决策找到 subject/evidence/task。后继型 disposition 的 `target_ref` 还必须能从该决策解析到已验证的新 revision 或 Final Idea。

### 10.2 人工提交

人工提交单独写 `human-reviews.jsonl`，避免伪造机器 gate：

```json
{
  "schema_version": 2,
  "review_id": "review-uuid",
  "round_id": "creative-review-round-001",
  "round_sha256": "...",
  "run_id": "...",
  "reviewer_id": "browser-uuid",
  "reviewer_name": "Percy",
  "submitted_at": "...",
  "request_sha256": "...",
  "independence": "pre_reveal|post_reveal",
  "concept_reviews": [
    {
      "feedback_ref": "review-uuid:concept:creative-concept-...",
      "feedback_sha256": "...",
      "concept_ref": "...-r002",
      "concept_sha256": "...",
      "one_sentence_retell": "...",
      "share_target": "...",
      "share_impulse": "immediate|maybe|no",
      "demo_confidence": "yes|maybe|no",
      "reactions": {
        "surprise": "yes|maybe|no",
        "fun": "yes|maybe|no",
        "mystery": "yes|maybe|no",
        "confusion": "yes|maybe|no"
      },
      "recommendation": "keep|revise|reject|taste_veto|no_opinion",
      "comment": "任意自由文本"
    }
  ],
  "pairwise": [
    {
      "feedback_ref": "review-uuid:pair:creative-pair-001",
      "feedback_sha256": "...",
      "pair_id": "creative-pair-001",
      "left_ref": "...",
      "right_ref": "...",
      "left_sha256": "...",
      "right_sha256": "...",
      "preference": "left|right|both|neither|cannot_compare",
      "reason": "..."
    }
  ],
  "overall_comment": "...",
  "overall_feedback_ref": "review-uuid:overall",
  "overall_feedback_sha256": "...",
  "supersedes_review_id": null
}
```

规则：

- `review_id` 是幂等键；相同 ID 不同内容返回 409。
- server 先对规范化 client payload 计算 `request_sha256`；重复 ID + 相同 request hash 返回原记录和原 `submitted_at`，不同 hash 才返回 409，不能因重试重新生成时间戳而制造冲突。
- 修改意见通过 append 新记录和 `supersedes_review_id` 表达，不覆写。
- `supersedes_review_id` 只能指向同 reviewer、同 round 的当前 latest record；不能跨人、跨轮次或跳过最新版本。
- reviewer display name 随每条提交持久化；浏览器 `localStorage` 只负责预填和未提交草稿。
- 首次提交前看不到其他人的原文或结果，首次记录标为 `pre_reveal`；提交后可以看到 team wall，之后的 superseding edit 标为 `post_reveal`。Benchmark 的独立复述/分享指标只使用首份 `pre_reveal` receipt。
- 评审内容绑定精确 round、revision 和 hash；过期内容返回 409。
- `share_impulse=immediate` 时 `share_target` 必须非空；`maybe|no` 可以为空。
  `demo_confidence` 的问题固定为“看完最小 Demo 路径后，你相信团队能在比赛
  时间内跑起来吗？”，它与 `share_impulse` 都进入 feedback fragment canonical
  hash，但只是人工信号，不自动重开 C4F。
- concept evaluation、pair answer 和 overall comment 各有稳定 `feedback_ref`；`feedback_sha256` 对排除 hash 字段本身后的 canonical fragment 计算，避免 self-reference。
- shortlist 按 Concept ID 排序后，controller 生成一个连通但有界的相邻 pair 集：
  - 0/1 个候选：0 pair；
  - 2 个候选：1 pair；
  - 3 个以上：`(1,2)…(n-1,n),(n,1)`，最多等于 shortlist 数且不超过 8。
- `pair_id` 和 canonical 两端由 controller 固定；UI 可以依据 reviewer ID hash 交换左右显示以降低位置偏差，但提交必须还原 canonical refs/hash。
- Reviewer 可以回答零个到全部已提供 pair；不得提交自比较、未知 pair、重复 pair 或不属于精确 round 的 revision。
- pairwise 文案固定比较“更想立刻点开、转发或让别人试哪一个？为什么？”，
  但仍可全部跳过。
- 在 round 关闭前，人类可以主动追加 superseding edit；这是人工编辑历史，不是自动 Agent loop。round 一旦关闭，所有新 review/edit 都返回 409，且只有每个 reviewer 的最新非 superseded 版本进入 resolution。

### 10.3 Percy 决议

决议写入 `human-resolutions.jsonl`，包含：

- `resolution_id`
- `curator_name`
- `round_id` 与 `round_sha256`
- 每个候选的 action，以及该 action 对应的 approved feedback fragment refs/hash
- merge groups
- 可选的 Percy curator instruction 及其 hash
- 未覆盖候选及 override reason
- `closed_at`

默认要求每个 shortlist Concept 至少被一名具名评审者覆盖。Percy 可以显式
override，但必须填写原因。Curator projection 额外显示每个 exact revision 的
完整 C4F dimensions/reasons/evidence，以及 latest receipt 中逐人的
`share_impulse`/`demo_confidence` 原始值；这些字段不自动替 Percy 作决定。

Resolution 不变量：

- 每个 shortlist revision 必须恰好出现一次最终 action；未知 ref、缺失 ref 或重复 ref 拒绝。
- `merge` group 至少两个 source，所有 group 两两不相交；同一 source 不能同时 keep/revise/reject/veto 或进入两个 merge group。
- `taste_veto`、coverage override 和 merge 必须提供非空理由。
- approved feedback ref 必须存在于当前 round 的 latest non-superseded receipt、hash 一致，且与被处理的 Concept/merge source 有关；不能批准整条多 Concept receipt 后把无关评论一起注入。
- 每个 `revise/merge` action 至少有一个相关 approved feedback fragment，或一条非空、hash 绑定的 Percy curator instruction；`keep/reject/taste_veto` 不要求。
- resolution 按 canonical JSON 计算 `resolution_sha256`；C6C 注入前重新验证每个 exact fragment hash，不能只凭可复用字符串 ID。
- 关闭时额外保存 `latest_receipt_set_sha256`，它对按 reviewer ID 排序的最新 receipt ID/hash 集合计算；未批准进入 Agent 的原始反馈仍由 C7 完整追溯。
- 一个 resolution ID 的相同重试幂等，不同 payload 返回 409；已关闭 round 不接受第二个 resolution。
- resolution 同样保存规范化 client payload 的 `request_sha256`，重复请求返回原 timestamp/hash。
- controller 完整校验后，把 resolution record 与 `wait.status=closed`、exact resolution hash、latest receipt set hash、approved fragment hashes 一起写入 v2 state/outbox。若 ledger append 前崩溃，下一个 writer 先重放同一 resolution；outbox 未清空时 `resumable=false`。

## 11. C6 本地评审服务

### 11.1 CLI

```bash
hacksome review RUN_DIR
hacksome review RUN_DIR \
  --host 0.0.0.0 \
  --public-host percy-mac.local \
  --port 8765
```

默认：

- `host=127.0.0.1`
- `public-host=127.0.0.1`
- `port=0`，由系统选择空闲端口
- 自动打开浏览器；`--no-open` 可关闭

若显式绑定非 loopback 地址，`--public-host` 必填；它用于打印可分享 URL 和构建唯一 Host allowlist。CLI 同时打印醒目提示：页面无 TLS、只适合受信任的同一局域网，不应暴露到公网。

服务启动后生成两个不同的进程内 token：

- team review link：可读候选、写个人 review；
- Percy curation link：额外允许关闭轮次。

token 不写入 run。访问 `/join/<token>` 一次性入口后设置单一 `hacksome_cap` 的 `HttpOnly; SameSite=Strict; Path=/` cookie，值在 server 内映射为 review 或 curator role；新 join 明确替换旧 capability，避免两个 role cookie 的优先级歧义。随后跳转到无 token URL；server access log 必须关闭或把 token 路径完全脱敏。

### 11.2 固定 API


| 方法     | 路径                       | 权限             | 行为                                                       |
| ------ | ------------------------ | -------------- | -------------------------------------------------------- |
| `GET`  | `/join/<token>`          | 持有 link        | 设置对应 cookie 后重定向，不记录 token                               |
| `GET`  | `/`                      | review         | 返回固定 HTML                                                |
| `GET`  | `/assets/styles.css`     | review         | 返回固定 CSS                                                 |
| `GET`  | `/assets/app.js`         | review         | 返回固定 JS                                                  |
| `POST` | `/api/reviewer-sessions` | review         | 用浏览器 local reviewer ID 建立进程内 session 并设置 HttpOnly cookie |
| `GET`  | `/api/snapshot`          | review/curator | 按 cookie role 返回 reviewer 或 curator 投影                   |
| `POST` | `/api/reviews`           | review         | 校验并 append 一份 review                                     |
| `POST` | `/api/resolve`           | curator        | 校验覆盖与决议并关闭 round                                         |


不使用 `SimpleHTTPRequestHandler` 暴露 run 目录，不提供任意文件路径，不启用 CORS。

Snapshot 必须 role-aware：

- reviewer 首次提交前：候选体验正文（含原始 `Software Core and Runtime`、`Minimum Hackathon Demo`、`Share Trigger and Artifact`）、自己的草稿状态、匿名覆盖计数和 pair 集，不含 C4F verdict/evidence、peer 原文/推荐、memory provenance/历史淘汰标签或 resolution controls；
- reviewer 首次提交后：额外获得只读 team wall，但 round 关闭前仍不含 memory provenance，也没有 feedback approval、merge、override 或 close controls；后续 edit 明确标为 `post_reveal`；
- curator projection：额外包含每名 reviewer 的 latest non-superseded receipt 与原始 `share_impulse`/`demo_confidence`、每个 Concept 的覆盖矩阵、完整 C4F dimensions/reasons/evidence、完整 raw feedback、memory 来源/借用/规避/copy-risk、可批准 feedback fragment refs/hash、merge eligibility、未覆盖项和当前 draft resolution；
- curator 使用普通 review link 时仍看到 reviewer projection，必须显式进入 curator link 才能获得策展能力。

Reviewer personalization 不能只靠共享 team capability cookie。浏览器从 `localStorage` 读取/生成 `reviewer_id`，先调用 `/api/reviewer-sessions`；server 返回单独的 `hacksome_reviewer_session` HttpOnly cookie，并在进程内绑定 capability + reviewer ID。Review payload 的 reviewer ID 必须与 session 一致。Server 重启后页面重新注册 session，不改变已持久化 reviewer ID。

### 11.3 安全与一致性

- 只接受 `application/json`，body 上限 256 KiB。
- 校验 `Host`（精确 `public-host:port` allowlist）、`Origin`、capability/reviewer-session cookie 和 method。
- 所有 HTML/JS/CSS/API 响应设置 `Cache-Control: no-store`、`Referrer-Policy: no-referrer`、`X-Content-Type-Options: nosniff`；HTML 使用不含 inline script/style 的严格 CSP：`default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'none'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`。
- 所有自由文本通过 `textContent` 渲染，不进入 `innerHTML`。
- 字段上限：reviewer name 80 字符、one-sentence retell 400、share target 200、每 Concept comment 4000、pair reason 1000、overall comment 4000、curator instruction 4000。
- 每个 C6C task 最多注入 12 个 approved fragment 且 UTF-8 总量不超过 24 KiB；超出时策展台要求 Percy 减少选择，controller 不静默截断。
- API 只返回页面需要的投影，不返回 Prompt、原始日志、Codex Session 或完整 `run.json`。
- 服务器生命周期持有独占 `review-server.lock`，阻止同一 round 启动两个 review server。
- 每个 API 写操作和 `resume` 短暂取得独占 `run.lock`；`status/validate/snapshot` 取得共享 lock，从而既允许等待期间查看状态，也不会读取半条 JSONL。
- 进程内 `threading` lock 与跨进程 advisory lock 同时保留；不能假定 POSIX file lock 会替代 HTTP worker thread 的互斥。
- Percy 成功关闭后服务返回确认页并自动停止、释放 lock。
- 进程崩溃时 OS 释放 advisory lock；JSONL append 本身保持幂等。

## 12. 评审页面视觉与交互设计

本节采用 `frontend-design` 的“先定意图，再定视觉系统”的方式，避免做成通用 SaaS Dashboard。

### 12.1 设计意图

页面主题是“小团队的创意接力室（Relay Room）”：

- Agent 把候选递到团队手里；
- 每位评审者留下自己的“一句话接力”和“想转发给谁”；
- Percy 最后把接力棒交回 Agent 做一次修订。

页面的视觉重点是 Concept 和人的复述，不是指标卡、排行榜或炫技背景。

### 12.2 视觉系统


| Token                 | 值         | 用途                     |
| --------------------- | --------- | ---------------------- |
| `--night-ink`         | `#191934` | 主文字、深色轨道               |
| `--signal-periwinkle` | `#6667F4` | 选中、焦点、接力信号             |
| `--flash-coral`       | `#FF6B62` | Reveal、taste veto、重要提醒 |
| `--relay-mint`        | `#9CE6D2` | 已保存、分享对象               |
| `--cool-paper`        | `#F5F7FF` | 页面背景                   |
| `--quiet-slate`       | `#73758B` | 次级文字                   |


字体不依赖 CDN：

- Display：`"Arial Narrow", "Avenir Next Condensed", sans-serif`
- Body：`"Avenir Next", "Segoe UI", sans-serif`
- ID/状态：`ui-monospace, SFMono-Regular, monospace`

避免米白衬线“AI 文艺风”、黑底荧光“黑客风”、玻璃渐变和大量统计卡。

### 12.3 单卡接力状态模型

普通 reviewer 不再纵向展开整批项目。页面维护一个
`active_concept_ref`，只让一张 exact Concept `article` 可见、可聚焦；后方只
绘制最多两张不含可交互内容的装饰卡影，形成“待传递卡组”。草稿仍以
`concept_ref` 分桶，另持久化最近 active ref；刷新后优先回到该 ref，若不存在则
回到第一张未判断卡。

卡内信息顺序固定：

1. 标题、Hook、revision/hash；
2. 三块短事实：“用户做什么”“软件如何回应”“为何会再试/分享”；
3. 默认折叠的原始 software/demo/share/novelty/risk 材料；
4. 与本 Concept 同属一个 `article` 的一句话复述、分享/Demo 信号、建议与评论；
5. `✕ 不成立`、`△ 需要修改`、`✓ 保留` 三个显眼动作，以及独立的“稍后再看”。

前三个动作分别只写现有 `recommendation=reject|revise|keep`，不新增 API 字段。
用户至少写完一句话复述后才能完成判断；“稍后再看”允许完全空白并只移动
active ref。完成动作后卡片带方向色上移、轻微旋转和淡出，下一张从后方抬升；
动画结束后将焦点移到下一张标题并通过 `aria-live` 宣布进度。上一张/目录始终
可回到任意 Concept，所有选择在批量提交前都只是可修改的本地草稿。

### 12.4 Desktop Wireframe

```text
┌───────────────────────────────────────────────────────────────┐
│ RELAY ROOM        03 / 08          [目录] [上一张]             │
│ 评审者姓名 [____________________]   草稿 2 / 8                 │
├───────────────────────────────────────────────────────────────┤
│                         ┌─ next card shadow ─┐                 │
│ 03 / 08  PROJECT TITLE                                        │
│ 一句话 Hook · exact concept ref / revision / hash              │
├───────────────────┬───────────────────┬───────────────────────┤
│ 用户做什么          │ 软件如何回应        │ 为何会再试 / 分享       │
│ 真实输入与动作       │ 可观察的核心转换     │ 重复循环与可转发物       │
├───────────────────────────────────────────────────────────────┤
│ 查看其余原始材料：机制、先例与风险（默认收起）                   │
├───────────────────────────────────────────────────────────────┤
│ 对 PROJECT TITLE 的评审                                        │
│ 一句话复述 [______________________________________________]   │
│ 想发给谁 [____________]  建议 / 评论 [____________________]   │
│ 分享冲动 [____]          Demo 信心 [____]                      │
│ 反应 chips / 更多评论                                          │
│                                                               │
│ [稍后再看]       [✕ 不成立] [△ 需要修改] [✓ 保留]              │
└───────────────────────────────────────────────────────────────┘
```

关键不变量：

- 普通 reviewer 任一时刻只有一张 active 项目卡；目录可以显示全批次标题/状态，但不得同时展开其他项目的描述或评审表。
- 标题、三块事实、折叠原文和项目回执必须位于同一个 `article`；不得把五道或更多评审问题抽成脱离项目的共享区域。
- 三块事实不是模型分数或新的 Agent 总结：它们只重排 snapshot 已提供的 Audience Action、software/runtime、Hook/share 字段，所有 run 文本仍用 `textContent` 渲染。
- 项目回执用 `concept_ref + revision + sha256` 绑定；浏览器草稿至少按 `concept_ref` 分桶。填写一张卡不能改变另一张卡的输入、完成状态或 reaction chips。
- 空白卡等价于跳过；批量提交只携带实际填写的 Concept review。评审者姓名和 `overall_comment` 可以保持批次级。
- pairwise、Team Wall 和 Percy 策展台是后续独立区域，不能插入普通 reviewer 的项目事实与项目回执之间。
- `prefers-reduced-motion: reduce` 时取消位移/旋转并立即切卡；卡片隐藏后必须同时从 tab order 与辅助技术阅读顺序移除。

### 12.5 Mobile Wireframe

```text
┌────────────────────────┐
│ RELAY ROOM [目录] [返回] │
│ 03 / 08                │
│ PROJECT TITLE          │
│ 一句话 Hook             │
├────────────────────────┤
│ 用户做什么              │
│ 真实输入 → 动作          │
├────────────────────────┤
│ 软件如何回应             │
│ 转换 → 可观察结果         │
├────────────────────────┤
│ 为何会再试 / 分享         │
│ 循环 → 可转发物           │
├────────────────────────┤
│ [展开其余原始材料]        │
├────────────────────────┤
│ 这张项目卡自己的回执      │
│ 一句话复述               │
│ 分享冲动 / 分享对象        │
│ Demo 信心 / 反应 / 评论    │
│ [稍后] [✕] [△] [✓]      │
└────────────────────────┘
```

移动端只改变列数，不改变信息归属：三块事实按单列展开，项目回执仍在同卡内紧随其后，页面不得横向滚动。底部判断按钮可以在 active card 内 sticky，但不能遮挡最后一个字段。

### 12.6 Percy 策展台

Curator cookie 启用同一应用中的独立模式：

```text
┌────────────────┬────────────────────────────────┬────────────────────┐
│ COVERAGE       │ CONCEPT 03 / 08                │ ROUND RESOLUTION   │
│ 03  3 reviews  │ 原始传递回执                    │ Action             │
│ 04  1 review   │ Percy：复述 / 分享冲动 / Demo信心│ keep / revise / ...│
│ 05  0 reviews  │ Weston：复述 / 分享对象…         │                    │
│                │ C4F evidence / Memory / copy-risk│ Approved fragments │
│ Merge groups   │ [完整自由评论与 pairwise 理由]   │ [✓ feedback-01]    │
│ [A + D]        │                                │ [  feedback-02]    │
│                │                                │ Override reason    │
│                │                                │ [______________]   │
│                │                                │ [关闭并交回 Agent]  │
└────────────────┴────────────────────────────────┴────────────────────┘
```

要求：

- 策展台显示 reviewer name 和原始文本，不用模型摘要替代；
- 策展台显示逐人的 `share_impulse`、`demo_confidence` 与完整 C4F evidence；
- 策展台显示 memory source refs、`inspire/avoid` cue、变换说明和 copy-risk；这些信息不进入普通 reviewer 投影；
- 每个 Concept 必须明确选择 action；
- merge group 使用明确的 source chips，并即时阻止重复归组；
- approved feedback fragment 默认全不选，由 Percy 主动勾选；若 action 为 `revise/merge`，至少勾选一个相关 fragment 或填写 curator instruction 才能关闭；
- coverage 不足时关闭按钮保持不可用，除非填写 override reason；
- 关闭前显示不可逆确认摘要；成功后进入只读状态并显示下一条命令 `hacksome resume RUN_DIR`。

### 12.6 Signature Interaction

提交后，表单收拢为一条“传递回执”：

```text
PERCY 复述：……
想递给：……
✓ 已绑定 concept-r002 / hash abc123
```

Pairwise 模式把两个 Concept 画成并排的“投影卡”，只问“更想立刻点开、转发或让别人试哪一个，为什么”，不显示模型名次。

保存时允许一次短促的 signal handoff 动画；除此之外保持克制，并完整支持 `prefers-reduced-motion`。

### 12.7 可访问性

- 全流程可键盘完成，焦点环使用 `signal-periwinkle` 且对比度达标。
- 不只依赖颜色表达选择和错误。
- textarea 有明确 label、字符状态和错误关联。
- mobile 不出现横向滚动；触控目标至少 44px。
- 页面刷新后从 `localStorage` 恢复未提交草稿，但若 round hash 改变则先提示过期，不自动提交。

## 13. CLI 与路由分派

### 13.1 保持 Useful 默认

现有命令继续有效：

```bash
hacksome run challenge.md
```

等价于：

```bash
hacksome run challenge.md --route useful
```

Creative：

```bash
hacksome run challenge.md \
  --route creative \
  --creative-brief-file brief.md \
  --idea-memory auto
```

route-specific 参数由 CLI 在 dispatch 后校验。Creative 不读取 `--max-audiences` 等 Useful fanout；Useful 不读取 Creative fanout。

`--idea-memory auto|off` 是 Creative-only，默认 `auto`，固定扫描本次 `--runs-dir` 的直接子目录；任何受支持版本都不开放任意 history path、全局 home 扫描或隐式联网。选择 `off` 仍生成并登记空 snapshot，让报告能证明没有使用历史输入。

为区分“parser 默认值”和“用户显式传入了另一 route 的参数”，所有 route-specific argparse option 使用 `default=argparse.SUPPRESS`。选定 route 后才由对应 settings builder 注入默认值：

- Creative + 显式 Useful option：CLI error；
- Useful + 显式 Creative option：CLI error；
- 未显式传 route option：保持当前 Useful 默认行为。

不能把所有 option 先填默认再猜用户意图。

### 13.2 新命令

```text
hacksome review RUN_DIR
hacksome resume RUN_DIR
hacksome reconcile RUN_DIR
hacksome benchmark --route creative MANIFEST.json
hacksome benchmark --continue BENCH_DIR
```

Creative `status` 输出 route、review round、覆盖和是否可 resume。Useful 的 human-readable 与 `--json` 输出保持当前字节/字段合同，不追加 route 行；route dispatch 在内部完成。实现使用迁移前 golden fixture 验证，而不只是比较“默认 Useful”和“显式 Useful”两个新调用。

`validate` 先做 Hub core validation，再做 route contract validation。

Benchmark 的 `live|fixture` 是 manifest 内的 `mode` 字段，不是 CLI `--mode`
参数。当前 Draft PR 的 CLI 只实现 manifest 规划校验；`--continue` 只校验
既有 bundle/worksheet 后 fail closed，不持久化或推进 arm。下文 controller、
持久化和 live/fixture 执行描述是后续实现合同，不能在 controller 接通前作为
已交付能力对外宣称。

## 14. Benchmark 设计

### 14.1 运行单位

一个 benchmark case 包含：

```json
{
  "case_id": "...",
  "challenge_path": "...",
  "creative_brief_path": "...",
  "review_fixture_path": null,
  "comparison_kind": "workflow_vs_oneshot|memory_ablation"
}
```

`workflow_vs_oneshot` 同一 case 运行：

1. 完整 Creative route；
2. 一次性 Creative Idea baseline。

该主比较固定 `idea_memory=off`，隔离工作流本身的收益。`memory_ablation` 则运行两条相同 Creative route，一条 `auto`、一条 `off`，专门测历史积累的增量。Live ablation 会增加人审负担，必须显式选择；fixture 必须覆盖它的离线状态/报告合同。

Benchmark controller 在启动任一 arm 前只扫描一次历史来源并冻结 benchmark-level memory snapshot；两个 arm 都登记同一 snapshot/hash，`off` arm 明确不消费它。所有 benchmark arm 输出在本 case 完成前不得反向进入该 snapshot，防止先运行的 arm 泄漏给后运行的 arm。

两边使用同一 model、reasoning effort、Challenge、Brief 和公开预算。报告同时展示 token、wall time、任务数、memory policy/snapshot hash 和人工负担，不用更昂贵的流程冒充纯质量胜出。

Benchmark 有两个明确模式。

#### `live`

- `review_fixture_path` 必须为 `null`。
- full-route 到 C6 正常进入 `waiting`；benchmark state 记录对应 run dir，命令以 `waiting_for_human` 正常返回。
- Percy/队友使用正式 review page，随后运行正式 `resume`。
- baseline 可以并行完成生成，但比较结果保持 `pending`。
- `hacksome benchmark --continue BENCH_DIR` 只在两个 arm 均完成且人工 worksheet 已录入后生成最终比较。
- 只有 `live` 结果可以计算“人类偏好、复述、分享对象”等真实人类指标。

#### `fixture`

- `review_fixture_path` 必须存在并通过独立 Schema。
- fixture importer 通过与 HTTP 相同的 domain validator 写入 review/resolution，但每条记录必须标记：

```json
{
  "producer_kind": "fixture",
  "fixture_id": "...",
  "fixture_sha256": "..."
}
```

- fixture 不能伪装成具名真人、不能进入 live 人类指标，也不能成为产品效果证据。
- 它只用于离线状态机、report 和 benchmark pipeline 回归，可以自动关闭 round 并继续 full-route。

Benchmark 根目录持久化 case/arm/run refs、模式、预算、状态和实际 usage；`--continue` 幂等，不重跑已完成 arm。

### 14.2 Blind worksheet 合同

Live benchmark 在两个 arm 都产生可评审输出后生成：

```text
BENCH_DIR/
├── blind-review-packet.md
├── blind-review-packet.json
├── arm-map.json
└── benchmark-reviews.jsonl
```

- packet 只显示稳定的 `Arm A/Arm B`，不显示 full-route/baseline、模型 Session、token 或流程 polish；
- A/B 分配由 `sha256(benchmark_id + case_id)` 确定，`arm-map.json` 单独保存，不进入 reviewer packet；
- 每个 arm 是按稳定 Idea ID 排序的 portfolio，允许 0 到多个 Idea；packet JSON 保存 exact card ref/hash 列表。Baseline 同样在一次 Session 中输出有界 portfolio，最大数量与 full-route 最终上限一致。
- 零 Idea arm 显式写 `ideas=[]` 和 `no_idea=true`；不能从缺失字段推断。
- reviewer 填写独立 `benchmark-review.json`，最小字段为：

```json
{
  "schema_version": 2,
  "benchmark_id": "...",
  "packet_sha256": "...",
  "review_id": "benchmark-review-uuid",
  "reviewer_name": "...",
  "cases": [
    {
      "case_id": "...",
      "arm_a_ideas": [
        {
          "blind_idea_id": "A1",
          "retell": "...",
          "share_target": "...",
          "share_impulse": "immediate|maybe|no",
          "demo_confidence": "yes|maybe|no",
          "surprise_source": "...",
          "interaction_desire": "yes|maybe|no"
        }
      ],
      "arm_b_ideas": [],
      "best_idea": {"arm_a": "A1", "arm_b": null},
      "portfolio_preference": "arm_a|arm_b|tie|neither",
      "reason": "..."
    }
  ]
}
```

导入命令：

```bash
hacksome benchmark --continue BENCH_DIR --worksheet benchmark-review.json
```

Importer 验证 benchmark ID、packet hash、case 完整性、每个 blind Idea 恰好一份评价、零 Idea arm 必须为空数组，以及字段上限；以 review ID/request hash 幂等 append。Live 至少一份完整 worksheet 才能生成含人类指标的最终比较；fixture 模式不要求 worksheet，并明确省略人类指标。

### 14.3 自动与人工指标

自动指标：

- 合法 Concept 数；
- 机制不同的 Territory/Atom 数；
- C3 software-first 合格率与端到端 Demo path 完整率；
- C3 冷启动 30 秒路径、关键子系统计数、最高风险假设/两小时 probe、降级切片和
  预置状态成本的完整率；
- C4H/C4F `pass|repairable|invalid`、修复、淘汰矩阵和七类 feasibility reason 分布；
- 定制硬件/纯装置/伪技术 fixture false-pass、合法普通设备 I/O false-reject；
- 只罗列标准 Web API 但权限/兼容/延迟不成立的 false-pass，以及手工录屏被误判为
  立即分享的 false-pass；
- 完整 C4 screen 后的 C5W task 数及相对 v1 的 token/wall-time 变化；
- memory 来源/跳过诊断、selected cues、challenger 数、challenger 通过率与 copy-reject 数；
- memory challenger 的 C4F 通过率与旧硬件/装置模式再引入率；
- 有效 source URL 和碰撞类型；
- C6B `immediate_share_trigger=pass` 占比及 categorical decision 一致性；
- C6B 的复述/分享 verdict 独立性、duplicate refs 覆盖率、shortlist 机制族数量与
  最大机制族占比；
- lineage 覆盖；
- 报告确定性；
- token 与时间。

人工 worksheet：

- 冷启动约 30 秒后一句话复述是否准确；
- 在不向 reviewer 暴露复述答案的独立问题中，是否立刻想到具体分享对象；
- `share_impulse=immediate` 且有具体分享对象的比例；
- 惊喜来自机制还是困惑；
- 是否想亲自互动或看别人反应；
- `demo_confidence=yes`，以及技术机制是否可见、是否主要依赖文案/主持人/布景；
- 两个流程输出的盲选偏好。

`share_impulse` 与 `demo_confidence` 仍是 Idea 阶段代理指标，不能被报告为真实
传播率或构建成功率。离线 fixture 至少覆盖 software/WebSocket 正例、内置 I/O
正例、定制硬件反例、纯装置反例、mock/预录反例、不可得权限反例、可修复的
Demo cut 缺失、标准 Web API 兼容/权限陷阱、预置状态超预算、无降级切片、
手工录屏高摩擦分享、跨 Territory 但核心机制重复，以及可运行但无 share trigger
的弱 viral 例。

默认单元测试不联网、不调用 Codex。实际 benchmark 必须显式运行，Percy 后续提供 Challenge 后再填真实结果。

## 15. 错误与空结果矩阵


| 情况                                    | 持久化结果                                                      | Run 结果                                           |
| ------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------ |
| 输入为空或参数冲突                             | 不创建 run                                                    | CLI error                                        |
| Codex 基础设施重试耗尽                        | task failed + event + deterministic partial report         | `failed`                                         |
| JSON Schema/Markdown/语义无效             | task invalidated + deterministic partial report            | `failed`                                         |
| C2 合法返回空 Atom                         | 空集合产物                                                      | C3/C5M 均不调用，空 C6 batch + `no_concepts_generated` |
| C3 合法返回空 base Concept，但有 Atom/历史      | 空 base 集合产物                                                | C5M 仍可生成 ≤2 challenger                           |
| C4F 明确定制硬件/纯装置/不可得依赖 hard invalid | `c4_software_demo_invalid` + 维度 reason/evidence           | 终态淘汰；不启动 C5W/C6                             |
| C4H 两份 reviewer 均 invalid              | gate reject decision                                       | 继续                                               |
| C4H/C4F 可修复信息不足                       | 共享一次 C4 repair，重跑 fresh 2+1                            | 只有全部 pass 才继续                                 |
| C4 修复后仍不一致                            | `c4_unresolved_after_repair`                               | 继续                                               |
| 自动 history 发现单个坏/未知来源                 | snapshot diagnostic，不注入该来源                                 | 继续                                               |
| 冻结后的 snapshot/hash 被篡改                | validation error + deterministic partial report            | `failed`                                         |
| 无历史或 `idea-memory=off`                | 合法空 snapshot                                               | 不调用 C5M，继续                                       |
| C5M Recall 失败                         | allowlisted optional task + `optional_memory_stage_failed` | 不启动 Remix；base 分支继续                              |
| 两个 C5M Remix 一成一败                     | 保留成功 challenger；失败 sibling 写 task/event/diagnostic         | all-settled 后让成功 challenger 进入 C4                |
| v2 base 与 challenger 均无完整 C4 screen pass | 完整 disposition + 空 review batch                         | 跳过等待，C7 以 `all_candidates_failed_concept_screen` 完成 |
| frozen v1 run 无 Hook pass               | 按 v1 bytes/schema 解释                                      | 保留 `all_candidates_failed_hook`，不迁移                 |
| C5W 网络失败                              | task failed + deterministic partial report                 | `failed`，绝不写“无先例”                                |
| 自动 shortlist 为空                       | 带 `shortlist_empty` 的空 review batch                        | 跳过等待，C7 完成                                       |
| Review 提交 hash 过期                     | 不写 ledger，HTTP 409                                         | 仍 `waiting`                                      |
| Review body/schema 非法                 | 不写 ledger，HTTP 4xx                                         | 仍 `waiting`                                      |
| Percy 在覆盖不足时关闭                        | HTTP 409，或显式 override + reason                             | 仍 `waiting`/关闭                                   |
| 人工全部拒绝                                | resolution + 零 final                                       | resume 后 `completed`                             |
| C7 render/staging/manifest 生成失败       | event + error + 尝试 partial report                          | `failed`，无有效 Final 输出                            |
| Finalization manifest 后发布/进程中断        | frozen plan + staged bytes + publish progress              | 保持 `running`/resumable，`resume` 只重放              |
| Finalization staged/existing bytes 篡改 | validation error + plan-linked 输出标为无效 + 尝试 partial report  | `failed`，绝不 `completed`                          |
| Partial report 自身失败                   | 保留原 terminal error，再记 report error                         | `failed`，绝不覆盖首因                                  |


缺失或失败任务永远不能等价为“Agent 认为没有候选”。

## 16. 并发、锁与确定性

- Agent fanout 使用现有 `CodexRunner` semaphore。
- Controller 先按输入顺序分配 task/candidate ID，再并发执行，最后按 ID 聚合。
- `RunHub` 继续是单进程状态 owner。
- `run.lock` 使用短生命周期的 shared/exclusive advisory lease，保护跨进程 snapshot 与 mutation；`review-server.lock` 只负责保证单个评审服务。
- JSONL 以稳定 ID 幂等 append；冲突 ID 不同内容报错。
- v2 status event 使用 `transition_seq`，同一 stage 可以合法重复进入；缺失或重复序号由 validate 报告。
- artifact 发布只具备单文件 atomic + 幂等登记；跨文件不一致必须可检测。
- C7 在独占 lease 下冻结 finalization source/bytes/manifest；中断后的发布者只能采用同一 manifest，不能与新的 renderer 并行。
- 所有列表在持久化/报告前按合同定义的稳定顺序排列。
- 报告 render 不调用当前时间、随机数或模型。

## 17. 模块与文件责任

建议目标结构：

```text
src/hacksome/
├── cli.py                         # 公共命令与 route dispatch
├── codex.py                       # 不改语义
├── hub.py                         # v1/v2、route metadata、generic decision
├── state.py                       # 原子原语 + run lease
├── prompting.py                   # RenderedPrompt / PromptSpec / PromptCatalog
├── task_executor.py               # 共享 AgentTaskExecutor
├── workflow.py                    # Useful route owner
├── routes.py                      # route registry + RunContract protocol
├── creative/
│   ├── __init__.py
│   ├── artifacts.py               # Creative headings/composer/semantic checks
│   ├── contracts.py               # settings、DTO、stage constants
│   ├── prompting.py               # Creative PromptCatalog
│   ├── workflow.py                # C0-C7 orchestration
│   ├── report.py                  # deterministic report/handoff
│   ├── memory.py                  # 跨 run 发现、snapshot、capsule/ref 验证
│   ├── review.py                  # snapshot、ledger、resolution validation
│   └── review_server.py           # stdlib HTTP server
├── prompts/
│   └── creative/*.md
├── schemas/
│   └── creative/*.schema.json
└── review_ui/
    ├── index.html
    ├── styles.css
    └── app.js
```

`pyproject.toml` 的 package data 必须加入嵌套 Prompt、Schema 和 review UI 资产；测试要验证 wheel/resource 可读取，避免只在 editable install 工作。

测试按责任拆分：

```text
tests/test_hub.py
tests/test_prompting.py
tests/test_task_executor.py
tests/test_workflow.py                 # Useful 回归
tests/test_routes.py
tests/creative/test_contracts.py
tests/creative/test_workflow.py
tests/creative/test_memory.py
tests/creative/test_review.py
tests/creative/test_review_server.py
tests/creative/test_report.py
tests/test_cli.py
```

## 18. 测试与验收映射

### 18.1 共享层

- v1 Useful run 可以 inspect/validate；
- 新 Useful CLI 默认输出不变；
- Codex/Workflow config 经过 JSON round-trip 后精确恢复 tuple、枚举和值；未知字段 fail closed；
- Prompt 在 Codex 调用前已经落盘；
- semantic validator 失败会 invalidated；
- 同一 JSONL ID 的相同重试幂等，不同内容冲突；
- route registry 对未知 route/schema 拒绝；
- v1 inspect/validate 不创建 lock 或写 projection；
- outbox 在 state/ledger 各个崩溃点使用同一 timestamp/content 重放；
- terminal run 可用 `reconcile` 清空 allowlisted pending，且业务 status/产物不变；
- run-frozen Prompt/Schema 不受 package 更新影响，manifest/frozen bytes 篡改 fail closed；
- process lease 防止 review/resume 双写。

### 18.2 Creative Workflow

- fake runner 完整执行 C0-C7；
- 稳定 ID 与并发完成顺序无关；
- Software Demo Policy 在允许阶段使用同一 exact hash，C2 lens 不含纯
  spatial/performance/cross-media 目标；
- C3 缺 `Software Core and Runtime`、`Share Trigger and Artifact` 或可执行
  Demo 信息时 invalidated；
- 每个 initial/repaired revision 恰好 2 个 C4H + 1 个 C4F fresh task，三者互
  不读取 sibling；C4H/C4F 判断矩阵与七类 feasibility reason 逐项覆盖；
- custom hardware 与 pure installation fixture 终态淘汰且 C5W task=0；合法
  laptop/phone/browser/camera/mic fixture 不被误杀；缺 Demo detail 只 repair
  一次并重跑 2+1；
- 每个 C4/C6 terminal branch 都有稳定 disposition reason codes 与 evidence/decision refs；
- 每个 Concept 的 C4H/C4F 共享最多一次 Hook repair；
- 每个 base Concept/memory challenger 的 lineage 最多包含一次 C4 repair；每个进入 C6A 的 C4-pass Concept 恰好包含一次 evidence revision，最终最多再包含一次 C6C feedback revision；重试不新增 revision，三类预算互不借用；
- C5W task 数严格等于完整 C4 screen pass 数，且只有 C5W 设置 web search；
- C5W 失败不会变成“无撞车”；
- C6B 五个 categorical dimension 与 include/hold/exclude 机械关系、上限和
  Territory round-robin 确定；
- 空 shortlist 发布带 skip reason 的空 batch，不等待；
- 非空 shortlist 精确进入 `waiting`；
- 未关闭 round 不 resume；
- 关闭后 `keep` 保留精确 revision，`revise/merge` 各最多生成一次 final revision；
- 人工全部 reject 时合法零 Idea；
- 同一 Hub 重复 report/memory record render 字节相同；
- finalization 在 manifest 前、每个 planned artifact publish 前后、event outbox 与 completed transition 各崩溃点都能重放精确 bytes；没有完整 manifest 时不误恢复；
- fatal task 产生 status=failed 的 partial report，不把 card/handoff 暴露为有效结果；
- CreativeRunContract 对 revision、disposition、memory、gate、wait/review/resolution/report/handoff 非法 fixture fail closed。

### 18.3 Idea Memory

- C2/C3 与初始 C4 Prompt/parent refs/registered context/stage input 不含 snapshot、capsule 或历史 disposition；测试明确验证的是 Harness 上下文隔离而不是 OS chroot；
- history discovery 只扫描显式 runs root 直接子目录，顺序不依赖文件系统枚举；
- completed zero-Idea Creative 可贡献 caution；Useful、failed、waiting、fixture、未知版本、hash 损坏和 symlink 逃逸均排除并有 diagnostics；
- `off`、无历史、无当前 Atom、无 relevant cue 都形成不同的合法空状态，且不调用不需要的 Agent；
- source run 在 snapshot 后新增/删除/篡改不改变当前 run；snapshot 自身篡改 fail closed；
- 复合 ref 校验 run/route/contract/artifact/hash/memory-record hash；
- Recall ≤1、cue ≤8、Remix ≤2、challenger ≤2，challenger 不能递归 C5M；
- 每个 challenger 同时引用 current Atom 与 memory cue，拥有新 Concept ID，规范化 Hook 相同/直接 mechanism+reveal 复制被拒绝；
- base/challenger 的 `primary_territory_ref` 都来自其 current Parent Atoms，C6B 分歧不能改变；C4 淘汰 capsule 也可确定性读取该值；
- C5M Recall/Remix 的 failure policy allowlist 与 diagnostic 一一对应；一成一败保留成功 challenger，非 C5M failed task 不能出现在 completed run；
- challenger 重新执行完整 C4/C5W，不能直达 C6；
- memory record 从 report projection 确定性生成，不含身份、原始人类评论、Prompt、log、Session 或绝对路径；
- memory classification 对两种 curator-support caution、两种 portfolio capacity、C4 caution、human subjective、merge transformed 和 final positive 全覆盖；
- v2 `no_concepts_generated`、`all_candidates_failed_concept_screen`、
  `shortlist_empty`、`all_human_rejected` 与非零 `null` 的互斥合同逐项覆盖；
  legacy v1 `all_candidates_failed_hook` 只在 v1 validator 分支合法。

### 18.4 Review API

- 固定路由、method、content type、body limit；
- shared team capability 下不同 reviewer-session 的 pre/post-submit 状态互不泄漏；
- token/cookie、public-host/Host/Origin 检查；
- CSP、no-store、no-referrer、nosniff、字段上限和 approved feedback context budget；
- reviewer name 与自由文本正确保留 Unicode；
- `share_impulse` / `demo_confidence` exact enum、request/fragment hash、
  persist/reload/supersede；`immediate` + 空 share target 返回 4xx；
- concept/round hash 过期返回 409；
- retry 幂等、冲突提交 409；
- supersedes 不覆写旧记录；
- pair 生成有界，未知/重复/stale pair 拒绝；
- 非 curator token 无法关闭；
- pre-submit reviewer snapshot 含原始 software/demo/share sections 但不含 peer
  原文或 C4F verdict；post-submit team wall 只读；curator snapshot 才包含完整
  feasibility evidence、原始人工信号和 resolution controls；
- coverage 不足必须 override reason；
- merge group 不重叠，approved fragment exact hash 在 resume 前复核；
- revise/merge 必须有 approved fragment 或 curator instruction，latest receipt set hash 可复算；
- traversal、任意 run 文件和 `innerHTML` 注入不可达。

### 18.5 浏览器 QA

- Desktop 与 mobile 布局；
- 键盘完整评审；
- 未提交草稿恢复；
- submit loading/success/error；
- round 已关闭、hash 过期、空 shortlist；
- pairwise 可跳过；
- reviewer 首次提交前无法读取 peer feedback，提交后只读 team wall；
- curator 模式完成 coverage、feedback approval、merge、override 和 close；
- `prefers-reduced-motion`；
- 其他评审者答案在提交前不可见。

### 18.6 Benchmark

- blind packet 不含 route/arm mapping，Idea refs/hash 可验证；
- 0/1/N Idea portfolio 都有显式、稳定的 blind Idea 列表与完整 worksheet matching；
- A/B 映射对同一 benchmark/case 稳定；
- worksheet 的 benchmark/packet/case/hash 不匹配时拒绝；
- worksheet 重试幂等、冲突 ID 拒绝；
- benchmark 报告 hardware/install false-pass、software false-reject、C5W cost、
  `share_impulse`、retell 与 `demo_confidence`，并标明人工字段只是代理信号；
- live 缺少完整 worksheet 时保持 pending；
- fixture producer 永不进入真人指标。
- workflow-vs-one-shot 固定 memory off；memory ablation 的 auto/off arm 共享同一 benchmark-level snapshot/hash，arm 输出不反向污染来源；
- benchmark report 明示 comparison kind、memory policy、snapshot hash、cue/challenger 成本与覆盖。

### 18.7 质量门

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy src
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

付费/在线 benchmark 不属于默认质量门。

## 19. 迁移、回滚与协作

### 19.1 迁移

- 第一切片先加入 v1/v2 read compatibility 和 route metadata，再接入 Creative。
- software-first 变更提升 Creative contract、Prompt policy、stage policy、
  report/memory policy 和 review payload/snapshot schema 至 v2；所有新 run 使用
  v2。旧 `creative-hack-the-rest-20260724-04` 等 v1 waiting run 继续按冻结
  resource allowlist inspect/review/resume，不回填 Software Demo Policy、不补跑
  C4F，也不把旧 `all_candidates_failed_hook` 改名。
- loader 先按 persisted Creative contract version 分派，再验证相应
  Prompt/Schema/reason/receipt/report；不能用当前 package 默认值解释旧 run。
- Useful Prompt 与行为先迁到新的 `PromptCatalog/AgentTaskExecutor`，以现有测试证明等价。
- Creative 文件使用独立目录和 stage namespace，减少与 Weston 的冲突。
- 保留现有公开入口与默认语义：
  - `render_prompt(stage, blocks)`、`schema_path()`、`stages()` 默认使用 Useful catalog；
  - `inspect_run()`、`validate_run()` 保持签名，内部变为 route dispatch；
  - `RunHub.create()` 未传 route 时仍默认为 Useful；
  - Useful `decisions.jsonl` 的既有 pass/reject record shape 不改；
  - 现有 Useful Prompt template ID/version 不改。
- 原 `test_resume_command_does_not_exist` 改为更准确的合同：全局 CLI 存在 Creative-only `resume`，但对 Useful run fail closed、退出非零且不改变任何字节。
- 新增 `.trellis/spec/backend/creative-agent-workflow-contracts.md` 作为 Creative normative spec，并更新 backend index；现有 Useful spec 明确收窄为 Useful route，同时更新“项目 only Useful / CLI 无 resume”等已被新 route 改变的全局陈述。

### 19.2 回滚

- 共享抽取每一步都保持 Useful 测试绿色；若第二个使用方不能让抽象更简单，则回退到 route 内部重复少量代码。
- Creative 失败不影响 `--route useful`。
- Idea Memory 可以通过 `--idea-memory off` 独立关闭；没有兼容历史时流程自然退化为原先的 base C2-C7，不要求迁移旧 run。
- Review UI/Server 可以独立撤回，不改变已有 Creative run 的 C0-C5 产物。
- software-first v2 可以停止创建新 run，但不能删除 v1 loader 或让已经 waiting
  的 v1 run 失去只读 inspect/review/resume 能力；真正移除旧版本需另做显式迁移
  决策和数据保留说明。
- v2 读取支持是 additive；回滚 Creative route 时仍可明确报告“不支持该 route”，不应误读为 Useful。

### 19.3 与 Weston 并行开发

- 会话开始、冻结设计前、验证前、push/PR 前同步 `origin/main`。
- 同步前检查未提交文件与上游 overlap，不覆盖 Trellis/onboarding/队友改动。
- 共享文件改动集中在第一切片并配 Useful 回归；后续优先只改 `creative/`、Creative resources 和 Creative tests。
- `src/hacksome` 属于 Idea runtime；不得 import `buildfactory` 私有模块，反向也一样。
- Build 只读取 C7 的纯 JSON handoff。

## 20. 实施完成定义

只有同时满足以下条件才视为完成：

1. 当前 Useful v1 默认 CLI、七阶段行为和离线测试保持绿色；
2. Creative 先独立生成，再以冻结的 Idea Memory 做一次有界 Recall/Remix；没有历史时行为可预测地退化；
3. 每个候选的 terminal 原因、证据和跨 run 来源可追溯，零 Idea 仍生成完整报告和未来可读的 memory record；
4. 多名队友能通过页面提交绑定精确 revision/hash 的具名反馈；
5. Percy 能关闭轮次，`resume` 只执行有界反馈修订和 C7；
6. C7 能确定性输出全历史、零个或多个 Idea Card、Memory Record 与 Build handoff；
7. 离线质量门、HTTP 测试和浏览器 QA 均通过；
8. PR 明确列出共享契约变化、Useful 回归证据、Creative 演示步骤和未运行的在线 benchmark。
9. software-first v2 的硬件/装置反例、普通设备 I/O 正例、新 zero reason、旧
   v1 waiting compatibility、C6 人工新字段和至少一次新真实 route smoke 都有
   可复核证据；旧 v1 的五个诗性装置 shortlist 只作为问题基线，不得冒充 v2
   benchmark 成果。
