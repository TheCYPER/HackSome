# 前端状态管理

> C6 Review UI 使用原生 JavaScript、后端 snapshot 与有界 `localStorage` 草稿。

## 状态分类

- `state.snapshot`：服务端权威只读投影；refresh 后整体替换。
- `state.draft`：当前 reviewer 的未提交批次草稿；按 `concept_ref` 分桶。
- `state.activeConceptRef`：普通 reviewer 当前唯一可见项目。
- `state.navigationHistory` / `directoryOpen` / `isTransitioning`：仅本次页面会话的
  导航和动效状态。
- reviewer profile 与 resolution draft 使用不同 storage key，不能混入 Concept
  receipt。

## 草稿合同

```json
{
  "schema_version": 2,
  "round_sha256": "...",
  "review_id": "...",
  "reviewer_name": "...",
  "active_concept_ref": "creative-concept-...",
  "concept_reviews": {
    "creative-concept-...": {
      "concept_ref": "...",
      "concept_sha256": "...",
      "one_sentence_retell": "...",
      "recommendation": "keep"
    }
  }
}
```

`active_concept_ref` 只控制恢复位置，不进入提交 payload。加载时如果它不存在于
当前 snapshot，优先选择第一张未判断卡；全部已判断则选择第一张。

## 状态转换

卡片动作必须按顺序执行：

```text
sync current DOM fields
→ validate retell when action is reject/revise/keep
→ update only current Concept draft
→ persist draft
→ animate
→ choose next active ref
→ render one card
→ move focus / announce
```

任何一步都不提交 HTTP receipt。只有页面底部显式 batch submit 才构造 payload。

## Server State

- Snapshot 不做长期 cache；提交成功后重新读取。
- `round_sha256` 是浏览器草稿是否 stale 的唯一权威。hash 变化时禁止提交，直到
  用户显式清除旧草稿。
- Concept 草稿同时保留 `concept_ref + concept_sha256`；切卡不能重绑定 hash。

## Common Mistakes

- 只在 DOM 中更新 recommendation，切卡重绘后丢失。
- 用 active index 持久化位置；shortlist 顺序改变后会指向错误 Concept。
- 点击 ✓/✕ 就调用 `/api/reviews`，把可撤销的浏览动作变成不可变 ledger 写入。
- stale round 上恢复旧草稿并静默覆盖 exact revision/hash。
