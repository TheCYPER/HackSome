# 后端开发规范

> 本目录记录项目已经实现、可由测试执行的后端合同。

---

## 索引

| 文档 | 说明 | 状态 |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization and file layout | To fill |
| [Database Guidelines](./database-guidelines.md) | ORM patterns, queries, migrations | To fill |
| [Error Handling](./error-handling.md) | Error types, handling strategies | To fill |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns | To fill |
| [Logging Guidelines](./logging-guidelines.md) | Structured logging, log levels | To fill |
| [Useful Idea 工作流合同](./agent-workflow-contracts.md) | Useful route 的 Prompt、Hub、绝对 gate 与 Idea Card | Active |
| [Creative Idea 工作流合同](./creative-agent-workflow-contracts.md) | Creative C0–C7、software-first Demo gate、Idea Memory、C6 唯一人审与确定性发布 | Active |
| [Post-card 与 Build Approval 合同](./post-card-build-approval-contracts.md) | 跨路线 catalog、multi-batch ledger/outbox、本机 Dispatch Board 与 Build JSON 边界 | Active |
| [Hackathon Team Runtime 合同](./hackathon-team-runtime-contracts.md) | Build 阶段的 Goal、Worker 连续性、超时清理与恢复 | Active |
| [Pitch 工作流合同](./pitch-workflow-contracts.md) | Project snapshot、四角色串行交接、Chromium 检查与自动发布 | Active |

新规范应记录代码中的实际合同，而不是愿望；必须包含签名、验证/错误、正反例和
测试断言。Percy 的协作文档默认使用中文，代码标识符和外部协议名保留原文。
