# C1W 真实运行合同 Break-loop

## Bug Analysis: 本地合法不等于 Agent 可产出、Codex 可接受、Controller 可发布

### 1. Root Cause Category

- **Category**: B - Cross-Layer Contract（并伴随 D - Test Coverage Gap 与
  E - Implicit Assumption）
- **Specific Cause**: C1W 的同一个输出同时受四层合同约束：
  Agent Prompt、JSON Schema、Codex structured-output 子集、Python semantic
  validator。最初实现把这四层分别看作局部正确，却没有证明它们的交集可由真实
  Agent 产出。结果依次暴露：
  1. `uniqueItems` 是合法 JSON Schema，但真实 Codex 不支持；
  2. `$ref` 与 `description` 各自合法，但真实 Codex 禁止 `$ref` sibling；
  3. Schema 要求完整 RFC3339，Python `fromisoformat()` 却接受更宽的 ISO
     profile，而 Prompt 没有足够明确地教 Agent 规范化 day-only 时间；
  4. Python 要求全 snapshot canonical URL 唯一，但 Prompt 未向 Agent公开该
     跨数组不变量，Schema 本身也无法表达。

### 2. Why Fixes Failed

1. **只修 unsupported keyword**：移除 `uniqueItems` 解决了第一个 400，但
   validator 仍是关键词黑名单，没有覆盖未知关键词和合法关键词的非法组合。
2. **只做正向 keyword allowlist**：能 fail closed 未知 keyword，却把
   `$ref + description` 误判为两个合法关键词；真实 API 的组合约束仍遗漏。
3. **只收紧 Prompt timestamp 文案**：Agent 输出形状改善，但 Python
   `fromisoformat()` 的 lexical profile 比 Schema 更宽；本地两个边界仍漂移。
4. **只依赖 semantic fail closed**：全局 URL 去重在代码中正确，但 Agent
   不知道它，导致一次有成本的成功联网与模型输出最终被 optional invalidation。
5. **离线 fake 只覆盖“能拒绝”**：没有使用真实 smoke 风格的 raw output 证明
   Agent 能在第一次尝试中满足所有隐藏 semantic invariants。

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
| --- | --- | --- | --- |
| P0 | Architecture | `validate_output_schema` 同时执行正向 keyword allowlist 与已证实的组合规则；`$ref` object 必须 pure | DONE |
| P0 | Cross-layer contract | Prompt 明示所有 Agent 可控制但 Schema 无法表达的 semantic invariant，包括全局 canonical URL 唯一 | DONE |
| P0 | Test coverage | 每个真实失败 raw shape 都变成双边界回归；验证 package 与 frozen exact bytes | DONE |
| P0 | Runtime probe | 完整 route 前先运行最小 C1W live probe，区分 Schema 400、Agent 输出和 semantic invalidation | DONE |
| P1 | Shared representation | Timestamp Schema pattern 与 Python 常量做 exact equality 测试；Python 先 lexical、后 calendar/window | DONE |
| P1 | Failure classification | 静态资源错误在 freeze/load 时 fatal；网络/模型/Agent semantic error 保持 optional task audit trail | DONE |
| P1 | Review checklist | 新增结构化输出字段时逐项标记：Schema 可表达 / semantic-only / Prompt 必须公开 / 是否需 live probe | DONE（backend spec） |
| P2 | Canary evidence | 保留最小 probe 的脱敏输入、错误类别和修复结论，不把手工修过的 raw output 冒充 Agent 成功 | TODO（由主会话决定证据落点） |

### 4. Systematic Expansion

- **Similar Issues**: 其他 stage 的 Schema 也可能包含真实 Codex 不接受的合法
  keyword 组合；任何 Python-only 的跨 candidate、跨 source 或 lineage
  invariant 若未出现在 Prompt，都可能造成“模型成功、发布失败”。
- **Design Improvement**: 将每个 stage 的输出合同视为
  `Prompt ∩ JSON Schema ∩ Codex subset ∩ semantic validator`，而不是以 JSON
  Schema 为唯一真相。Schema validator 只加入真实 API 证据确认的规则，不猜测
  或过宽禁止现有合法资源。
- **Process Improvement**: 对新 web stage 先冻结 catalog，再做单 stage 最小
  live probe；只有 Schema 与 structured output 成功后才跑完整 route。每次
  runtime failure 必须转成离线回归与规范条款。
- **Knowledge Gap**: JSON Schema Draft 2020-12 合法性、OpenAI/Codex
  structured-output 子集、Python ISO parser 接受范围是三个不同概念，评审时
  必须明确区分。

### 5. Knowledge Capture

- [x] 更新 `.trellis/spec/backend/creative-agent-workflow-contracts.md`
- [x] 更新 PRD、design 与 implement 的 C1W timestamp、`$ref`、URL 唯一合同
- [x] 增加 exact frozen bytes、unknown keyword、`$ref` sibling、timestamp
  lexical/calendar/window、全局 canonical URL 回归
- [x] 记录三次真实 runtime evidence 与最小 probe 的逐层结论
- [ ] 本轮由主会话统一 commit；checker 不单独 commit/push
