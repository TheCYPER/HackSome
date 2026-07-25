# 第一份真实 Cultural Signal Pack（2026-07-25）

> 状态：`partial`
>
> 用途：验证 C1W 的“原始来源快照 → 去表面化 Safe Palette”设计。它不是
> runtime artifact，不证明市场需求、传播性、创新性或社会共识，也不能替代
> C5W 的逐 Concept 撞车检查。

## 1. 采集范围与限制

- 采集时间：`2026-07-25T11:05:36+08:00`
- 主要观察窗口：过去 24 小时至 30 天
- 成功来源：
  - Google Trends 美国区 Trending Now；
  - 百度实时热榜；
  - Mastodon.social 公开趋势标签与标签时间线 API；
  - Bluesky 公开趋势主题与趋势 Feed API；
  - Know Your Meme 首页的近期 Meme / Explainer 索引。
- 受限来源：
  - TikTok Creative Center 返回 403；
  - Reddit Popular 被网络安全策略拦截；
  - Google 普通搜索触发 CAPTCHA；
  - Know Your Meme 的单篇解释页随后触发 Cloudflare，但首页索引仍可访问。

因此本包只能证明“这些来源当前展示了相应信号”，不能声称覆盖整个互联网。

## 2. 原始证据快照

| Evidence ref | 来源 | 当前可观察事实 | 只用于 |
| --- | --- | --- | --- |
| `E01` | [Google Trends Trending Now](https://trends.google.com/trending?geo=US) | 页面在 2026-07-25 10:56 本地时间更新；`bob cut` / `nordic bob` 在过去 24 小时成为 active search cluster，页面显示 20K+ searches。 | 近期搜索注意力的表面证据 |
| `E02` | [Know Your Meme 首页](https://knowyourmeme.com/) | 首页在近 1–14 天条目中列出 “No Correlation” scatter-plot reaction、低质量剪辑风格标签、人物与猫的相似性梗、短音频梗、体育人物与虚拟角色混搭等 Explainer/Meme。 | Meme 表面形态与发布时间 |
| `E03` | [Mastodon 趋势标签 API](https://mastodon.social/api/v1/trends/tags?limit=20) | 趋势列表出现短命题文字游戏、主题歌单、周期性 Friday 投稿和个人最近观看清单；API 同时给出按天 accounts/uses。 | 社交参与格式及粗粒度活跃度 |
| `E04` | [Mastodon 短命题文字游戏时间线](https://mastodon.social/api/v1/timelines/tag/NonChalantSongs?limit=10) | 多个公开参与者围绕同一极短规则改写熟悉歌名；每条投稿可独立理解，又共同形成一轮主题游戏。 | “共同规则 + 低门槛变体”的参与机制 |
| `E05` | [Mastodon 主题歌单时间线](https://mastodon.social/api/v1/timelines/tag/hotorcold?limit=10) | 参与者按一个二元主题选择歌曲或不同版本，并把各自选择汇入同一社交流。 | “个人选择 + 群体策展”的接力机制 |
| `E06` | [Bluesky 公开趋势主题 API](https://public.api.bsky.app/xrpc/app.bsky.unspecced.getTrendingTopics?limit=20) | `Art Fight` 位于当前公开趋势主题列表。 | 当前社交注意力 |
| `E07` | [Bluesky Art Fight 趋势 Feed](https://public.api.bsky.app/xrpc/app.bsky.feed.getFeed?feed=at%3A%2F%2Fdid%3Aplc%3Aqrz3lhbyuxbeilrc6nekdqme%2Fapp.bsky.feed.generator%2F806553225&limit=15) | 公开样本反复使用 attack、revenge、team 等规则词；参与者为另一人的原创角色制作作品，对方可回击，连续回合有可见编号和阵营。 | 互惠创作对战 / 接力结构 |
| `E08` | [百度实时热榜](https://top.baidu.com/board?tab=realtime) | 当前条目同时出现“高分考生主动选择软件职校”“商品展示与真实上身反差导致高退货”“高压线下打电话爆炸系谣言”等高讨论主题。 | 中文互联网中的价值冲突、表象反差与真假验证张力 |

原始名称、URL、人物、标签、搜索量和平台判断只停留在这一层，不进入 C2/C3
Prompt。

## 3. 原始信号归纳

| Signal ref | kind | evidence | 表面现象 | 可提炼但尚未安全投影的张力 |
| --- | --- | --- | --- | --- |
| `signal-01` | `trend` | `E06,E07` | 参与者把替别人创作称为“攻击”，允许回击并加入阵营。 | 赠予与竞争同时成立；作品天然指定下一位参与者。 |
| `signal-02` | `meme` | `E03,E04` | 一个极短文字规则触发大量对熟悉标题的微改写。 | 规则越窄，个人变体越容易被比较和接力。 |
| `signal-03` | `trend` | `E03,E05` | 参与者围绕二元主题贡献自己的媒体选择。 | 单次选择很轻，但群体集合逐渐形成可探索对象。 |
| `signal-04` | `meme` | `E02` | 散点图被用来回应“强行寻找关系”的表达。 | 人类渴望模式，同时也享受识破伪相关。 |
| `signal-05` | `controversy` | `E02` | 社群给一种被认为廉价的剪辑风格起了可传播的标签。 | 参与者会争论“这是风格还是低质量”，并尝试分类边界。 |
| `signal-06` | `meme` | `E02` | 现实人物与动物/虚拟形象因相似性被配对传播。 | 意外匹配比单纯生成更容易被复述和挑战。 |
| `signal-07` | `controversy` | `E08` | 优化过的商品展示和真实体验出现明显反差。 | 同一对象在不同表示系统中会产生不同结论。 |
| `signal-08` | `controversy` | `E08` | 高分评价体系与当事人的实际路径选择发生冲突。 | 外部排序和个人目标并不总是同一函数。 |
| `signal-09` | `controversy` | `E08` | 一个流传广泛的危险说法需要用物理机制验证。 | “听起来合理”与“可以模拟验证”之间存在体验空间。 |
| `signal-10` | `trend` | `E01` | 某种外观风格及其细分变体突然得到集中搜索。 | 用户希望快速看见“同一素材在相邻风格中的差异”。 |

`signal-04` 至 `signal-06` 目前只有聚合首页索引，单篇解释页随后被
Cloudflare 拦截；按 runtime source 规则只能标为 `context_only`。它们不能在
本轮进入生成 palette，直到存在可打开的一手页面或独立 corroboration。

## 4. URL-free / name-free Safe Palette

以下内容才允许被 Controller 有界注入 C2/C3。它不包含原始 URL、平台、账号、
人物、角色、hashtag、口号、搜索量或可直接复制的 Meme 名称。

```json
[
  {
    "signal_ref": "signal-01",
    "kind": "trend",
    "creative_role": "inspire",
    "abstract_pattern": "A participant transforms another participant's authored asset as a friendly move; the recipient can answer with a new transformation and the system keeps visible turn lineage.",
    "creative_tension": "Generosity feels more motivating when framed as a bounded contest.",
    "participation_shape": "choose a recipient -> transform their asset -> publish a rule-valid move -> recipient may answer"
  },
  {
    "signal_ref": "signal-02",
    "kind": "meme",
    "creative_role": "inspire",
    "abstract_pattern": "A very short shared rule lets many people make individually legible mutations of familiar material.",
    "creative_tension": "A narrow constraint can increase rather than reduce expressive variety.",
    "participation_shape": "receive one-line rule -> make one mutation -> compare with the stream -> issue the next rule"
  },
  {
    "signal_ref": "signal-03",
    "kind": "trend",
    "creative_role": "inspire",
    "abstract_pattern": "Small personal selections accumulate into a collective object that becomes more useful and surprising as viewpoints diverge.",
    "creative_tension": "A trivial contribution can change the meaning of the whole collection.",
    "participation_shape": "choose between a bounded contrast -> contribute one item -> inspect the emerging group pattern"
  },
  {
    "signal_ref": "signal-07",
    "kind": "controversy",
    "creative_role": "inspire",
    "abstract_pattern": "The same source object is rendered through two incentive systems, making the gap between optimized representation and lived outcome directly comparable.",
    "creative_tension": "Presentation can be technically truthful while still producing a misleading expectation.",
    "participation_shape": "supply one source -> apply two representation rules -> compare predicted and observed outcome"
  },
  {
    "signal_ref": "signal-10",
    "kind": "trend",
    "creative_role": "avoid",
    "abstract_pattern": "Users compare nearby style variants on the same authentic source rather than consuming unrelated generated examples.",
    "creative_tension": "Fast try-on is useful, but a temporary style label should not become the product's only idea.",
    "participation_shape": "supply source -> adjust interpretable style controls -> compare variants -> export chosen transformation"
  }
]
```

`signal-04` 至 `signal-06` 因来源证据不足，`signal-08` 因涉及未成年人，
`signal-09` 因涉及 misinformation，均应在 runtime 标为 `context_only`，不
进入 Safe Palette。保留在原始快照中只用于披露覆盖范围与风险。

## 5. 对四种 C3 产品语法的有界切片示例

这只是验证 deterministic slicing 的人工期望，不是最终 runtime 排序：

| C3 grammar | 最多两个 inspire refs |
| --- | --- |
| `explorer_simulator` | `signal-07` |
| `realtime_partner` | — |
| `social_game_relay` | `signal-01`, `signal-02` |
| `creator_transformer` | `signal-07` |

实时搭档方向在本轮来源中缺少强信号，系统不应为了“每类都有两个”而强行把
批处理趋势包装成 realtime。`signal-05` 与 `signal-10` 作为 `avoid` 只进入
C2 的避坑切片，不进入 C3 inspire 切片。

## 6. 明确避坑

- 不输出“把当前 Meme 做成 AI 版”；
- 不复制现成人物、角色、音频、口号或标签；
- 不把 search volume / uses 当作需求或传播性证明；
- 不让政治、战争、灾害或个体争议仅作为猎奇皮肤；
- 不把社交平台的单个公开帖子或账号带入下游 Prompt；
- Concept 必须在热点过期、表面素材被替换后仍能成立；
- 最终仍需经过 C4 Demo/Hook、C5W prior art 与 C6B Red Team。

## 7. 本轮结论

这份 `partial` Signal Pack 已足够验证 C1W 的核心边界：

1. 外部来源可以提供创作张力与参与格式；
2. Safe Palette 可以保留机制，同时删除可复制的表面符号；
3. 某个产品语法没有强信号时，允许少给或不给；
4. 真实热点不能替代项目本身的可理解性、软件闭环和 Demo 可行性。
