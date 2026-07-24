# 自主 Hackathon Build Teams — 父任务实施图

父任务拥有跨子任务需求、目录边界、最终集成验收，以及后续新增的跨角色共享 prompt
层。其余 Team runtime 与 Pool 仍由对应子任务实施。

## 子任务顺序

1. `07-23-single-team-runtime`
   - 先证明一个 Team 的三角色 Prompt、项目状态、零 Skill 和顺序 Goal batch。
2. `07-23-team-pool-operator`
   - 依赖单 Team runtime，再增加 handoff bootstrap、global pool 和 operator 控制。
3. 后续独立 integration task
   - 由 Idea 面实现显式 Human Review Gate，并调用稳定 handoff contract。

## 跨角色 Tool-use Prompt

- [x] 为 AgentSpec 增加显式的共享 system-prompt fragment 声明与确定性组装。
- [x] 新增一份 tool-use prompt asset，说明 Git/GitHub、Vercel 和 `/project` 内
      Markdown 持久化的可用方式。
- [x] 三个 active Team 角色都引用该 fragment，最终 prompt 均直接包含其内容。
- [x] 共享指引明确服从角色权限；Verifier 不获得外部 mutation 权限。
- [x] 增加 AgentSpec、active inventory 与角色边界回归测试。
- [x] 运行 `buildfactory/agent/tests` 及受影响的 orchestration prompt/runtime 测试。

## 跨子任务质量门

- [ ] 所有 Build 实现保持在 `buildfactory/`。
- [ ] Idea workflow 并行改动不被覆盖。
- [ ] 单 Team runtime 在引入 global pool 前独立通过真实 E2E。
- [ ] Pool 不改变 Team 内 Lead/Worker/Verifier Prompt 或 Goal 语义。
- [ ] 最终 handoff contract 不依赖 `src/hacksome` 私有 Python 类型。
