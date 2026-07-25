# Account Provisioning Contract

`accounts/<id>/` 是一个 Team 的外部账号包。`make up` 会把
`accounts/${ACCOUNT:-foundagent}/secrets.env` 作为 env file 注入 resident Lead，
Worker/Verifier manager 也会把同一账号包交给动态 Agent，并把目录只读挂载到
容器内 `/account`。缺目录、缺文件或缺 token 都必须是合法状态：CLI 会保持
未认证，Agent 启动不应失败。

## 文件布局

```text
accounts/<id>/
  secrets.env          # KEY=VALUE，一行一个；已被 gitignore
  google-sa.json       # 可选，给 Google API / MCP loadout 使用
  cookies/storage-state.json  # 可选，登录态种子（Playwright storage-state 格式）
  workspace/           # 可选，ephemeral broker worker 的账号工作区
```

不要提交真实凭证。`secrets.env`、`*.env`、`google-sa.json` 和 cookies 目录已被
根目录 `.gitignore` 忽略。

## secrets.env 键名

```sh
# GitHub CLI (gh). 值是 GitHub fine-grained personal access token。
GH_TOKEN=

# Vercel CLI. 值是 Vercel account settings 里创建的 API token。
VERCEL_TOKEN=

# Cloudflare Wrangler. 值是 Cloudflare API token。
CLOUDFLARE_API_TOKEN=

# 可选：Wrangler 在无 wrangler.jsonc/account_id 的非交互环境里可能需要。
CLOUDFLARE_ACCOUNT_ID=

# GA4 / Google Search Console MCP（Lead/Worker 共用同一个 service account，
# 见下方 "Google Service Account"）。
GOOGLE_APPLICATION_CREDENTIALS=/account/google-sa.json

# GA4 Admin API。人工创建 GA4 account 后，把 account id 写这里。
GA4_ACCOUNT_ID=

# DataForSEO MCP（Lead/Worker）。控制台 https://app.dataforseo.com/api-access
# 生成的 API 凭证（Basic auth 用户名/密码，不是登录密码）。
# pay-as-you-go，$50 起充；缺省时 dataforseo server 连接失败，其余不受影响。
DATAFORSEO_USERNAME=
DATAFORSEO_PASSWORD=

# Stripe MCP（Lead/Worker）。Stripe Dashboard → Developers → API keys 的完整
# secret key（sk_live_...，非 restricted key，07-09 拍板）。
# 缺省时 stripe server 连接失败，其余不受影响。见下方 "Stripe" 一节。
STRIPE_SECRET_KEY=

# 可选：per-account 静态出口 IP（住宅/ISP proxy，如 Decodo/IPRoyal）。
# 见下方 "Proxy（静态出口 IP）" 一节。启用时取消注释并填完整 URL；
# 不用时保持注释——留空值的 CUA_PROXY= 也会被 env_file 注入容器，
# 注释掉才是真正的零影响。
# CUA_PROXY=http://user:pass@host:port
```

`GITHUB_PAT` 不是本项目的 env 键名；GitHub 的 fine-grained PAT 应填到
`GH_TOKEN`，这是 `gh` 原生识别的非交互认证变量。

## GitHub Token

1. 在 GitHub 创建 fine-grained personal access token。
2. Resource owner 选对应组织或个人。
3. Repository access 只选这个 Team 需要操作的仓库；不要给全账号权限。
4. 权限按任务最小化配置。常见 builder 需要：Contents 读写、Pull requests 读写、
   Issues 读写、Actions 只读或读写按实际 CI 操作决定。
5. 把 token 写入 `accounts/<id>/secrets.env` 的 `GH_TOKEN`。
6. 验证：容器内运行 `gh auth status`。

## Vercel Token

1. 在 Vercel Account Settings 创建 token。
2. Scope 选需要部署的个人账号或 team；生命周期按公司风险设置。
3. 把 token 写入 `VERCEL_TOKEN`。
4. 验证：容器内运行 `vercel whoami`。项目部署前仍应在仓库里完成
   `vercel link` 或提供 `.vercel/project.json`。

## Cloudflare Token

1. 在 Cloudflare 创建 API token，优先从编辑 Workers / Pages / DNS 的模板开始。
2. 只授予目标 account / zone；不要使用 Global API Key。
3. 如果任务会在无项目配置的目录里调用 Wrangler，同时写入
   `CLOUDFLARE_ACCOUNT_ID`。
4. 把 token 写入 `CLOUDFLARE_API_TOKEN`。
5. 验证：容器内运行 `wrangler whoami`。

## Google Service Account

GA4 MCP 和 Search Console MCP 由 Lead/Worker 共用同一个 service account：

1. GCP 项目里创建 service account，启用 Google Analytics Data API、
   Google Analytics Admin API、Search Console API。
2. 下载 service account JSON key，保存为 `accounts/<id>/google-sa.json`。
3. 在 `secrets.env` 保持
   `GOOGLE_APPLICATION_CREDENTIALS=/account/google-sa.json`。
4. **GA4**：analytics.google.com 里人工创建 GA4 account（这一步含 ToS，
   不能由 service account 代签），在 Account access management 把 SA 邮箱
   （`xxx@<project>.iam.gserviceaccount.com`）加为 Editor，并把 account id
   写入 `secrets.env` 的 `GA4_ACCOUNT_ID`。仓库不再附带 GA4 provisioning
   Skill；需要创建 property/data stream 时，由 Worker 通过现有工具或 API 完成。
5. **GSC**：Search Console 添加 Domain property `foundagent.net`，按 UI 给出的
   TXT 值在 Cloudflare apex 保留一条 `google-site-verification=...` TXT，然后
   在 Settings → Users and permissions 把同一个 SA 邮箱加为 Full 用户。这一步
   不做的话 gsc server 能起但列不到任何属性。

验证：Lead 容器内会话通过 MCP 检查 GSC、DataForSEO 与 GA4 连接状态；动态
Worker 使用同一 MCP 配置和账号包。

## foundagent.net domain rail

`foundagent.net` 是 foundagent 账号包的 fleet 域名。Search Console 已使用
Domain property 验证根域，覆盖 `foundagent.net` 及所有子域；新开
`*.foundagent.net` 子域不需要再做 Google 侧动作。

仓库不再附带域名部署 Skill。需要绑域时，由 Worker 根据当前项目、DNS 所有权和
本节安全边界执行，不能假设存在历史角色 Skill。

### 一次性 Google 前置状态

- `accounts/foundagent/google-sa.json`：service account key，供 GSC/GA4 MCP
  和 GA4 Admin API 使用。
- Search Console：`foundagent.net` Domain property 已验证，service account 已有
  Full 权限。
- GA4：service account 已在 GA4 property/account 侧获得 Editor 权限，
  `GA4_ACCOUNT_ID` 已写入 `accounts/foundagent/secrets.env`。

## DataForSEO

1. 注册 https://dataforseo.com/（pay-as-you-go，$50 起充）。
2. 控制台 API Access 页取 API login/password（独立于网站登录密码）。
3. 写入 `secrets.env` 的 `DATAFORSEO_USERNAME` / `DATAFORSEO_PASSWORD`。
4. 验证：Lead 容器内通过 MCP 看 dataforseo server 状态，或直接
   `curl -u "$DATAFORSEO_USERNAME:$DATAFORSEO_PASSWORD"
   https://api.dataforseo.com/v3/appendix/user_data`。

## Stripe

前置：Stripe 开户 + KYC 已人工完成（live 账户可收款）。Lead/Worker 使用的
`agents/mcp/ceo.json` 包含 Stripe；Verifier 的窄 MCP 配置不包含 Stripe。

1. Stripe Dashboard → Developers → API keys，取 **secret key**（`sk_live_...`，
   点 Reveal 复制）。本 fleet 用完整 secret key 而非 restricted key
   （07-09 拍板，"先给足权限、收窄后置"）。
2. 写入 `accounts/<id>/secrets.env` 的 `STRIPE_SECRET_KEY`。
3. 改完 `secrets.env` 需 `docker compose up -d --force-recreate` 重建容器
   才生效（env_file 在容器创建时注入）。
4. 验证：任一容器内 claude 会话 `/mcp` 看 stripe server 已连接；或宿主机
   `curl -u "$STRIPE_SECRET_KEY:" https://api.stripe.com/v1/balance`
   （注意冒号，Basic auth 密码为空）。

风险一句话：本地 `@stripe/mcp` 进程只是 mcp.stripe.com 的转发器，工具面 =
密钥权限面，无应用层白名单——full key 意味着 agent 也能退款、改订阅、处理
dispute；要收窄就换 restricted key（rk_）。

## X / 登录态 cookies（agent 的浏览器）

Agent 的 Playwright 浏览器（经 Build assets 中的 `browser_mcp.sh` 包装启动）默认加载
`accounts/<id>/cookies/storage-state.json`——一个浏览器带全部登录态，不搞
隐身模式（2026-07-06 拍板）。今天只有 X，以后 Gumroad/KDP 等平台直接往同一
文件叠加登录态，零代码变更。缺文件 = 未登录浏览器，完全合法，agent 照常
浏览公开页面。

### 一次性导出（宿主机人工操作）

1. 宿主机运行（建议用日常网络导出，避免 X 对陌生 IP 弹验证；容器侧配
   `CUA_PROXY` 再消费）：

   ```sh
   npx playwright open --save-storage=accounts/<id>/cookies/storage-state.json https://x.com
   ```

   浏览器弹出后人工登录 X，**关闭浏览器时自动保存**。加 `--channel chrome`
   可直接用系统 Chrome，免下载 playwright 浏览器。
2. 文件已被 `.gitignore` 覆盖（`accounts/*/cookies/`），不会进 git。
3. 验证：Lead 或动态 Worker 会话里让浏览器打开 https://x.com，应显示
   已登录。

### 备选：浏览器扩展导出（2026-07-06 实测路线）

从日常浏览器用 Cookie-Editor / EditThisCookie 类扩展导出 JSON 也可以，但
扩展格式 ≠ storage-state 格式，需要转换（可直接让 Claude 现场转，不留脚本）：
外层包成 `{"cookies": [...], "origins": []}`；字段映射
`expirationDate`→`expires`（session cookie 用 `-1`）、`sameSite` 的
`no_restriction`→`None` / `lax`→`Lax` / `strict`→`Strict`（null 则省略该键）；
丢弃 `hostOnly`/`session`/`storeId`。首次接入 @Solvotheagent 即走此路线，
登录态 + 发帖 e2e 均通过。

### 叠加新平台（不丢已有登录态）

```sh
npx playwright open \
  --load-storage=accounts/<id>/cookies/storage-state.json \
  --save-storage=accounts/<id>/cookies/storage-state.json \
  https://<新平台>
```

### 只读种子语义

`/account` 是只读挂载，浏览器以 isolated 模式从文件种子启动：会话中新 set
的 cookies **不回写**。X 的核心 auth cookie 长寿命（数月级），登出/改密会
作废；失效表现 = 打开 x.com 未登录，处理 = 按上面步骤重导一次。

## Proxy（静态出口 IP）

社交账号 / 上架平台（X、Reddit、Gumroad、KDP、Etsy 等）要求账号流量来自
稳定的住宅/ISP IP。启用方式是在 `secrets.env` 写一行：

```sh
CUA_PROXY=http://user:pass@host:port
```

启动 hook（`ops/build/docker/agent_startup.sh`）会在 **computer-server 子树**里
把它展开成大小写两套 `HTTP_PROXY`/`HTTPS_PROXY` + `NO_PROXY`
（`src/hacksome/stages/build/assets/scripts/proxy_env.sh`）——CUA 桌面和浏览器流量走 proxy。要点：

- **不设置 = 零影响**：容器里不会出现任何 proxy 变量，走宿主出口。
- **LLM 流量永不走 proxy（结构性保证）**：agent_loop / claude 子树不
  注入这组变量，Claude API 恒走宿主出口。不能改回"全树注入 + NO_PROXY
  排除"：claude CLI 只认 `NO_PROXY="*"`，忽略一切按主机名的排除条目
  （2026-07-03 squid 实测，矩阵见任务 design.md）。
- **账号 API 调用显式走 proxy**：`CUA_PROXY` 本身是容器级 env，claude
  会话里的 Bash 随时可读。需要账号 IP 的 API 调用写
  `curl -x "$CUA_PROXY" ...`；gh/vercel/wrangler 等开发面流量保持直连，
  不烧住宅流量。
- **浏览器属账号面**：`CUA_PROXY` 存在时 agent 浏览器（playwright MCP，经
  Build `browser_mcp.sh` 传 `--proxy-server`）的全部流量走它——含研究浏览，
  知情成本（2026-07-06 拍板）。
- **per-account 语义**：IP 跟着账号包走；多个 Team 共用一个 `ACCOUNT` 即共享
  同一出口 IP。broker 旧路径的 `PROXY_<id>` 是同一插槽的 per-op 拼写，
  常驻路径只认 `CUA_PROXY`。
- **继承边界**：不经启动 hook 的桌面进程拿不到这组变量（best-effort，
  与 broker 路径同级）。浏览器级硬化（Chromium `--proxy-server`）留给
  use-accounts 线。
- 改完 `secrets.env` 需要 `docker compose up -d --force-recreate <role>`
  重建容器才生效（env_file 在创建时注入）。

验证（proxy 变量只在 computer-server 进程子树里，`exec` 新开的 shell 和
agent_loop 都看不到，所以查各自的 environ）：

```sh
# computer-server 子树：应看到六个展开变量（外加 CUA_PROXY 本体）
docker compose exec lead sh -c \
  'tr "\0" "\n" < /proc/$(pgrep -o -f computer_server)/environ | grep -i proxy'
# lead_loop（模型进程的父进程）：除 CUA_PROXY 本体外必须干净
docker compose exec lead sh -c \
  'tr "\0" "\n" < /proc/$(pgrep -o -f hacksome.stages.build.control.lead_loop)/environ | grep -i proxy'
```

## 冒烟命令

```sh
docker compose exec lead gh auth status
docker compose exec lead vercel whoami
docker compose exec lead wrangler whoami
```

没有 provisioned token 时，这些命令失败是正常的；不允许的是 `make up` 或任一
Team Agent 因缺 token 而启动失败。
