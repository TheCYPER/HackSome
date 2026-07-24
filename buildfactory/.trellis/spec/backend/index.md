# 后端开发规范

> 本目录记录项目已经实现并可验证的后端契约。

---

## 概览

规范应描述当前真实实现，而不是理想化设计；索引只负责路由，实施前仍需阅读对应全文。

---

## 规范索引

| 规范 | 说明 | 状态 |
|-------|-------------|--------|
| [目录结构](./directory-structure.md) | 模块组织与文件布局 | 待补充 |
| [账户包契约](./account-package-contracts.md) | 外部账户环境、文件与 foundagent.net 的 GSC / GA4 / DNS 验证边界 | E2E 已验证 |
| [数据库规范](./database-guidelines.md) | ORM、查询与迁移模式 | 待补充 |
| [错误处理](./error-handling.md) | 错误类型与处理策略 | 待补充 |
| [质量规范](./quality-guidelines.md) | 代码标准与禁止模式 | 待补充 |
| [日志规范](./logging-guidelines.md) | 结构化日志与级别 | 待补充 |
| [Agent 执行契约](./agent-execution-contracts.md) | 容器内 `claude` / `codex` 的结果解析、凭证隔离、Skill / charter materialization 与双 runtime 消费边界 | E2E 已验证 |
| [Hackathon Team Runtime 契约](./hackathon-team-runtime-contracts.md) | 当前 active：Lead → 单 Worker → fresh Verifier、`/project`、零 Skill 与无终止循环 | 单元/Compose 已验证 |
| [Team Registry 与 Pool 契约](./team-registry-pool-contracts.md) | Approval ingestion、稳定 Team identity、registry-before-side-effect、两 slot FIFO 与 operator pause/resume | 单元/跨进程已验证 |
| [V7 三层 Agent Company 契约](./three-layer-agent-company-contracts.md) | 上游历史参考：CEO、Department、Company Goal 与 mail | 非 active |
| [Company State 契约](./company-state-contracts.md) | 上游历史参考：`/company` 原生状态 | 非 active |
| [Peripheral 契约](./peripheral-layer-contracts.md) | 上游历史参考：IME、外部 adapter 与邮件接入 | 非 active |

---

## 编写要求

每一份规范都应：

1. 记录项目的真实约定，而不是抽象原则；
2. 提供来自当前代码的签名或示例；
3. 写明禁止模式及原因；
4. 固定容易重复出现的错误和测试入口。

目标是让后续 Agent 和开发者无需重新猜测系统边界。

---

**语言**：需要用户阅读或审阅的规范使用中文；纯底层历史契约可在后续触及时逐步翻译。
