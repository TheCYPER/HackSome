# 前端组件规范

> 本文件记录 C6 评审页面已经实现且可由资源测试/浏览器 QA 验证的组件合同。

---

## 1. Scope / Trigger

修改 `src/hacksome/review_ui/` 中的候选呈现、普通 reviewer 表单、卡片导航、
草稿恢复或判断动作时，必须遵守本文件。Percy curator、Team Wall 与 pairwise
仍是独立模式，不能借单卡改造泄漏到普通 reviewer 首次提交前的投影。

## 2. Signatures

普通 reviewer 的可见单元是：

```text
article.project-review-card[data-concept-index]
  ├─ exact title / hook / ref / sha256
  ├─ 3 × section.fact-panel
  ├─ details.source-details
  └─ section.project-review-section
       └─ button[data-card-action=later|reject|revise|keep]
```

`reject|revise|keep` 只映射现有 receipt
`recommendation=reject|revise|keep`；`later` 不写 recommendation。HTTP API、
review payload、exact revision/hash binding 均不因卡片动效增加字段。

## 3. Contracts

### 3.1 单 active card

普通 reviewer 任一时刻只渲染一张 active Concept。`#concept-list` 可以展示全批
标题与完成状态，但不能同时展开其他 Concept 的描述或表单。当前卡按以下顺序：

1. exact Concept title、Hook、revision ref 与 hash；
2. “用户做什么 / 软件如何回应 / 为何会再试或分享”三块事实；
3. 默认折叠的 software/demo/precedent/risk 原始材料；
4. 只属于该 Concept 的 receipt；
5. `稍后再看 / ✕ 不成立 / △ 需要修改 / ✓ 保留`。

三块事实只重排 snapshot 现有字段，不调用模型、不生成新分数，并始终通过
`textContent` 写入 DOM。

### 3.2 卡片动作

- `reject|revise|keep` 前必须有非空 `one_sentence_retell`；缺失时留在当前卡、
  聚焦 retell 并显示 inline error。
- 动作先同步当前 DOM 字段到该 Concept 草稿，再写 recommendation；不能在重绘
  时丢失刚输入的 comment/share signal。
- 卡片离场后进入下一张未判断项；全部已判断时重绘当前卡组并提示可以回看/提交。
- `稍后再看` 允许空白卡，只移动 active ref，不把跳过解释为 reject。
- 目录和“上一张”可以回到任意已判断项；批量提交前一切仍可修改。

### 3.3 Curator compatibility

Curator 模式继续展开完整项目档案并使用独立 workbench。普通 reviewer 卡片不能
显示 C4F verdict/evidence、Idea Memory provenance、peer receipt 或 resolution
controls。

```js
// Correct: only one Concept owns the facts, review and actions.
card.append(facts, details, createConceptReviewSection(concept, index));
deck.replaceChildren(card);

// Wrong: descriptions and receipts become separate batch-level walls.
cards.append(...conceptSummaries);
page.append(sharedConceptQuestionnaire);
```

## 4. Validation & Error Matrix

| 条件 | 行为 |
| --- | --- |
| 判断动作但 retell 为空 | 不切卡；显示 error 并聚焦 textarea |
| 保存的 active ref 不在新 snapshot | 回到第一张未判断项；否则第一张 |
| round hash 变化 | 草稿标为 stale；禁止静默提交 |
| `prefers-reduced-motion: reduce` | 取消位移/旋转，立即完成切卡 |
| 普通 reviewer snapshot 含 curator-only 字段 | 后端 fail-closed projection；前端不得主动读取/渲染 |
| 当前 run 没有 Concept | 隐藏表单并显示零候选状态 |

## 5. Good / Base / Bad Cases

- Good：填写第一张 retell/comment，点击 `✓`，卡片上滑离场；刷新后回到已保存的
  active ref，第一张草稿仍绑定原 Concept。
- Base：点击“稍后再看”，当前卡保持空白，下一张出现；最终 payload 不包含空白卡。
- Bad：页面先展开八个 Concept 描述，再在底部放八组或一组问题。
- Bad：点击 `✕` 直接提交 HTTP receipt，导致误触不可逆；卡片动作只能修改本地
  batch 草稿。

## 6. Tests Required

- 资源测试断言只存在一个 active deck 渲染路径、三个事实标题、四个卡片动作、
  `active_concept_ref` 恢复、`textContent` 与 reduced-motion CSS。
- Node syntax 必须通过。
- 浏览器 QA 覆盖桌面与 390px：首屏可见 active 项目卡、填写后
  `✓/△/✕` 切卡、目录/上一张/稍后、刷新恢复、无横向滚动、console 无 error。
- Loopback 环境可用时运行完整 `tests.test_creative_review_server`，不能把 socket
  skip 当成最终 LAN QA。

## 7. Wrong vs Correct

### Wrong

```js
concepts.forEach((concept) => page.append(renderFacts(concept)));
concepts.forEach((concept) => page.append(renderReview(concept)));
```

### Correct

```js
const concept = concepts[activeConceptIndex()];
deck.replaceChildren(createConceptReviewCard(concept, activeConceptIndex(), concepts.length));
```

## Accessibility

- Use a semantic `article` per Concept and an `aria-labelledby` review region.
- Every input must have a unique label and ID derived from its Concept index.
- A blank dossier is a valid skip; do not force reviewers through every card.
- Mobile must not scroll horizontally, and focus order must follow visual order.
- After a card transition, move focus to the next Concept title and announce progress
  through `aria-live`.

---

## Common Mistakes

- 不要把所有 Concept 描述放在一组脱离上下文的问题上方。
- 不要在普通 reviewer 卡片里渲染 curator-only feasibility evidence。
- 不要只按显示位置保存草稿；使用 stable Concept ref，并在提交时绑定 exact
  revision/hash。
- 不要把卡片离场动画当作提交成功；真正提交仍是整批 receipt 的显式动作。
