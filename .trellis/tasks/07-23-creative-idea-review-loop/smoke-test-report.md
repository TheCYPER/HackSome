# Creative Route 真实 Smoke Test 报告

## 1. 结论

`Hack the Rest — 重新创造休息` 已分别使用 frozen Creative contract v1 基线
和 software-first contract v2 跑到 C6 唯一人工关卡。最新有效 v2 run 为
`creative-hack-the-rest-v2-20260724-01`：

- 状态：`waiting / creative-human-review`
- Agent tasks：78 succeeded，0 failed
- 初始 Concept：12
- 完整 C4 screen pass：12
- C6 shortlist：8
- Review batch：`creative-review-batch-r001`
- 离线验证：`Run is valid.`

历史 v1 基线 run 为 `creative-hack-the-rest-20260724-04`：

- 状态：`waiting / creative-human-review`
- Agent tasks：65 succeeded，0 failed
- 初始 Concept：12
- C4 Hook-pass：12
- C6 shortlist：5
- shortlist 覆盖：4 个 primary Territory
- Review batch：`creative-review-batch-r001`
- 离线验证：`Run is valid.`

v1 仍可按自己的冻结资源打开、评审和 resume，但没有 C4F Software Demo
Feasibility gate，也没有 v2 的 software-first/viral benchmark。第 4–6 节先
保留 v1 基线，说明它为什么偏向装置艺术；第 7 节记录 v2 的真实结果以及本次
继续收紧 benchmark 的原因。

两次 run 都按约定没有伪造 reviewer、关闭 C6 或继续到 C7。因此现在得到的是
待人工评审的 Concept revision，而不是最终 Idea Card。Idea Card 只会在真实
人审 resolution 闭合后确定性生成。

真实 run 目录与 raw log 不提交到 Git；本报告只记录可复核的统计、首因与内容
摘要。

## 2. 运行配置

### v1 基线

- Route：`creative`
- Creative contract：`v1`（legacy waiting compatibility）
- Model：`gpt-5.6-terra`
- Reasoning：`medium`
- Idea Memory：`off`
- 最大并发：4
- 基础设施重试：1
- 单任务超时：600 秒
- 运行超时：7200 秒
- Creative Brief：约 30 秒内产生真实、可解释、可复述、让人想到分享对象的
  惊奇/好笑/神秘/诗意体验；排除仪表盘、普通冥想/番茄钟、AI 鸡汤、长文案和
  不可解释 AI 魔法。

### v2 software-first

- Route：`creative`
- Creative contract / Prompt policy / Stage policy / Report policy：`v2`
- Software Demo Policy：`v2`，controller-owned、随 run 冻结
- Model：`gpt-5.6-terra`
- Reasoning：`medium`
- Idea Memory：`off`
- 最大并发：4
- 基础设施重试：1
- 单任务超时：900 秒
- 运行超时：7200 秒
- Challenge 与 Brief：沿用同一 `Hack the Rest` 主题，但明确只接受普通电脑/
  手机上的真实软件闭环，排除定制硬件、实体制作、纯装置/人工核心、Figma、
  预录和 wizard-of-oz。

## 3. 三次 fail-closed 与对应修复

| Run | 停止点 | 发现 | 修复 |
| --- | --- | --- | --- |
| `-01` | C2 | Validator 要求 Atom 正文包含模型从未收到的 Controller Territory ID | `a9a8ecb`：正文恢复自然语言职责；Controller 用 ID、metadata、source refs 和显式 C3 Atom→Territory index 维护谱系 |
| `-02` | C2 | 一个 Explorer 把八个必需 H2 压进单个 `Mechanism` section | `9af471a`：C2 Prompt 加入逐字、逐段模板并禁止 inline/bold 压缩 |
| `-03` | C4R | 局部修复改写了 Validator 要求保持不变、但 Prompt 未明示的 source section | `c15e0ce`：C4R/C6A Prompt 明示三个不可变 section，并指明时序、风险与 Demo 澄清应写入哪些可变 section |
| `-04` | C6 | 65 个任务全部成功，生成非空 review batch | 目标达成；保留 open C6，不伪造人工反馈 |

这些失败均留下 immutable terminal error 与 partial report；它们不会进入 Idea
Memory，因为只有 completed、validated 的 Creative run 才可被未来 run 发现。

## 4. C6 Shortlist

| Concept | Primary Territory | 一句话 Hook | 初步判断 |
| --- | --- | --- | --- |
| `s01-01-r002` 房间的接力靠背 | 非常规互动机制 | 你靠住的三十秒里，房间会替你搭起一面不承重、但人人看得见的靠背。 | 规则清楚、低技术、现场共同完成；传播性更偏温暖而非爆笑 |
| `s01-02-r002` 空位的无声请假条 | 反转与揭示 | 你坐进空白三十秒，世界仍在动，但没有一件事可以穿过这张椅子来找你。 | “请求可见但不能穿过边界”很完整；稍有企业健康/艺术宣言气质 |
| `s01-03-r003` 闭眼后的影子借阅处 | 神秘叙事 | 你闭眼五秒，影子会替你把一声哈欠借出去；睁眼后，你得找回它去过哪里。 | 本批最神秘、最像可转述的小故事；低技术侦破机制也最完整 |
| `s02-03-r002` 放下以后，半句话开始唱 | 非常规互动机制 | 你放下手里的东西并停住半句话，大家才有资格替它唱完——但谁也不能替你回答。 | “只改形式、不代答、拿起即坍缩”是独特规则；需要主持人控制边界 |
| `s03-03-r002` 空位的反向合唱 | 社交传播与共同表演 | 你后退一步把位置留空，房间便只能为这段空白唱，不能替你补位。 | 集体参与和一句话复述较强；与无声请假条、半句话合唱存在近似 |

两个独立 Portfolio Curator 对前四项均给出 `include/include`。第五项得到
`include/hold`，由 Controller 的 Territory round-robin 与剩余容量选入。

## 5. 内容质量判断

### 已成立

- 所有入选项都能在约 30 秒内形成可见或可听的因果闭环。
- 最小 Demo 大多只需要卡片、纸张、椅子、桌面物件和现场参与者，不依赖虚假
  AI 能力或未授权数据；但按新的 v2 Policy，这恰好暴露了“核心因果由道具/
  参与者完成，软件技术含量不足”的问题，不能再算可落地软件 Demo 的正向证据。
- Hook 基本都能被一句话复述，且明确避开了“做一个休息 App”的惯性答案。
- Novelty Scan 没有把“搜不到”写成绝对原创；C6A 会披露近邻、文化边界和
  刻意未采用的证据。

### 仍不足

- 12 个初始 Concept 明显收敛到“空位、影子、哈欠、合唱、缺席”语义簇。
  六个 C2 Territory 确实不同，但四个 C3 Agent 看到完整 Atom index 后仍选择了
  相似的高显著性 Atom。
- 五项 shortlist 覆盖四个 Territory，但语义层面仍有三项围绕“留下空白、
  他人守住/回应”的近似结构。Controller 的 Territory round-robin 只能保证
  metadata 多样性，不能自动保证体验多样性。
- 整体更接近诗性参与艺术，惊奇和神秘已出现，但“好笑、会立刻录视频转发”
  的强度仍弱。
- 多数体验依赖主持人、三到六位参与者和预置卡片；技术上的 hackathon
  wow-factor 较低。

## 6. Harness 与成本观察

有效 run 的墙钟时间约 17 分 31 秒，共发布 132 个 artifact。65 个任务合计：

- input tokens：2,312,107
- cached input tokens：1,492,224
- output tokens：85,134
- reasoning output tokens：9,956

C5W 的 12 个 Novelty Scan 消耗 1,673,286 input tokens，占总 input 的约
72.4%；其中最慢任务约 404.7 秒。说明“每个 Hook-pass Concept 都独立联网查重”
是当前最主要的时延和 token 成本。

网络噪声审计：

- 49/65 个任务的 raw stderr 含 `ERROR` 或 `WARN`
- 共 166 条，主要是 WebSocket TLS、analytics 与瞬时重连
- 0 个 Prompt 或 structured output 含这些错误字符串

因此这些报错会保存在每个任务的 raw log 中用于诊断，但不会进入后续 Agent
上下文；本轮 65 个任务仍全部成功。裸 `codex exec` 的终端输出很吵，不代表
harness 的创意上下文被污染。

## 7. v2 真实运行结果与 benchmark 收紧

v2 已证明路线方向发生了实质变化，而不是把 C6 人审当作兜底：

- 新 run 冻结 Controller-owned Software Demo Policy；
- C2 使用 software-native lenses；
- C3 明示 software runtime、真实端到端 Demo 与具体 share artifact；
- C4 在联网 C5W 前新增 C4F feasibility 自动 gate，淘汰定制硬件、纯装置/
  人工核心和 mock-only Demo；普通设备内置 I/O 仍允许；
- C4H/C6B 强化立即分享触发，C6 人工回执增加 `share_impulse` 与
  `demo_confidence`。

真实 v2 run 共发布 145 个 artifact，墙钟约 37 分 03 秒。78 个任务合计：

- input tokens：2,838,928
- cached input tokens：1,679,360
- output tokens：114,269
- reasoning output tokens：11,633

C5W 的 12 个 Novelty Scan 消耗 1,996,991 input tokens，占总 input 的约
70.3%。这次 C4 没有压缩候选，所以联网成本没有下降；这不是“增加 feasibility
gate 已经省钱”的正向证据，而是 C4F 判据需要继续收紧的直接证据。

### 7.1 v2 C6 shortlist

| Concept | 软件最小切片 | 分享物 | 本轮风险判断 |
| --- | --- | --- | --- |
| `s01-01-r002` 绕行路接力 | Pointer Events + SVG/Canvas + URL 编码 | 可继续接力的 URL | 强；端到端简单，分享本身就是下一位入口 |
| `s01-02-r002` 擦出的第二时间 | 麦克风 + Web Audio 实时滤波 + Canvas | 参数 URL 或手工录屏 | 偏险；权限、回授、低延迟音频和 30 秒冷启动叠加 |
| `s02-01-r002` 把待办捏成一团云 | 文本 + 粒子物理 + Canvas/WebGL | 手工录屏 | 易做，但传播路径摩擦较高 |
| `s02-03-r003` 静音接力云 | 两设备 + WebSocket + 麦克风 + 音频存储 | 房间 URL | 偏险；“预先打开房间”隐藏了冷启动和部署成本 |
| `s03-02-r002` 休息的回放局 | Pointer Events + SVG + URL fragment | 可继续接力的 URL | 强；无服务端，传播闭环清楚 |
| `s03-03-r002` 给下一位的静音字幕 | 麦克风特征 + Canvas + 参数 URL | 可继续录制的卡片 URL | 中等；分享成立，但与其他声音纹理方案接近 |
| `s04-01-r002` 擦出来的静默邮戳 | 麦克风 + Web Audio + PNG | PNG 或手工录屏 | 中等偏弱；仍有数字装置艺术感和录屏摩擦 |
| `s04-03-r002` 删字后，键盘开始下风 | 输入事件 + Canvas + Web Audio | 结果 URL + PNG | 强；机制好复述，降级路径也较诚实 |

两个 C6B curator 已能识别“影子/延迟镜”和“轨迹接力”等 duplicate family，
并把 12 项压到 8 项；但 C4F 对 12 个初稿与 1 个 repaired revision 全部给出
`pass`。这说明：

- **software-first 已生效：** 12/12 都是普通浏览器软件；0 个定制硬件核心，
  0 个纯实体装置/人工表演核心。11/12 可纯前端运行，只有“静音接力云”需要
  WebSocket 和短时音频存储。
- **Demo readiness 仍偏松：** reviewer 把列出标准 Web API 和最小流程当成了
  足够证明，未保守计算权限、secure context、兼容、跨设备、子系统数量和预置
  状态。
- **viral 判断仍会循环论证：** C4H 经常直接复述 Concept 自己写的
  One-sentence Hook、收件人和“会分享”理由；“作者写了分享对象”不等于真实
  recipient-side share impulse。
- **机制多样性不足：** 5 项使用麦克风、3 项使用摄像头、2 项是轨迹接力；
  “影子”和“声音变纹理/云/字幕”出现明显聚类。

### 7.2 已落地的第二轮收紧

不修改 v2 JSON shape、reason code、controller 聚合矩阵或 route-level policy
version，只把 C3/C4H/C4F/C4R/C6A/C6B 的 Prompt template 前进到 v3，并兼容
加载冻结的 template v2：

- 没有 C0 明示资源时，按 2 人、24 小时、最多一个简单 backend、一个主要
  browser/device target 和最多三个关键子系统评估；
- 30 秒从未打开 URL 的冷启动开始，权限、真实输入、处理、reveal、第二设备
  配对和预置状态都必须显式计时/计成本；
- Concept 必须写最高风险技术假设、两小时 falsifying spike 和保留 Hook 的
  fallback slice；只列 Canvas/Web Audio/getUserMedia/WebSocket 不算实现证明；
- C4H reviewer 必须独立写一句 retell 及偏差，不能复制作者 Hook；分享判断必须
  从收件人实际收到什么、为何会打开/接力以及摩擦出发；
- C6B 对手工录屏、账号/二设备准备和跨候选机制重复更严格。

这次 waiting run 保留为 template v2 的不可变基线，不用新 Prompt 重解释。
下一步需要用同一个 Challenge 新建 template v3 run，比较 C4F repair/reject
分布、C5W 任务数、shortlist 机制族和 false-pass；人工 `share_impulse`、
复述与 `demo_confidence` 仍只是代理信号，不能冒充真实传播率或 build success。
