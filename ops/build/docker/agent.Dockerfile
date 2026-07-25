# Foundagent VM layer — agent-ready container (Claude-in-container architecture).
#
# Extends the fast-boot base (foundagent/cua-ubuntu) with a full in-container agent
# stack so a Claude Code session can run INSIDE the container on the user's
# subscription and drive the container's own desktop via the thin MCP — zero API key,
# headless, fully isolated from the host.
#
# Build from the repository root so production Python remains under src/:
#   docker build -f ops/build/docker/agent.Dockerfile \
#     -t foundagent/cua-agent:latest .
ARG CUA_BASE_IMAGE=foundagent/cua-ubuntu:latest
FROM ${CUA_BASE_IMAGE}

USER root

# Opt-in package mirrors for local-network builds. Empty defaults preserve the
# canonical image behavior. Configure Ubuntu sources before any apt transaction.
ARG UBUNTU_APT_MIRROR=
ARG UBUNTU_PORTS_MIRROR=
ARG NPM_REGISTRY=
RUN for sources in \
      /etc/apt/sources.list \
      /etc/apt/sources.list.d/ubuntu.sources; do \
      if [ -f "${sources}" ]; then \
        if [ -n "${UBUNTU_APT_MIRROR}" ]; then \
          mirror="${UBUNTU_APT_MIRROR%/}"; \
          sed -i -E \
            -e "s|https?://archive.ubuntu.com/ubuntu/?|${mirror}/|g" \
            -e "s|https?://security.ubuntu.com/ubuntu/?|${mirror}/|g" \
            "${sources}"; \
        fi; \
        if [ -n "${UBUNTU_PORTS_MIRROR}" ]; then \
          ports_mirror="${UBUNTU_PORTS_MIRROR%/}"; \
          sed -i -E \
            -e "s|https?://ports.ubuntu.com/ubuntu-ports/?|${ports_mirror}/|g" \
            "${sources}"; \
        fi; \
      fi; \
    done

# Node 20 — claude CLI dependency. Installed via nodesource because claude.ai/install.sh
# is CDN-blocked from inside containers (returns 403 / TLS reset); npm registry is reachable.
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y nodejs \
 && rm -rf /var/lib/apt/lists/*

# Shell tools used by resident agents. Ubuntu packages fd as `fdfind`; expose the
# shorter `fd` name agents expect.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      fd-find \
      imagemagick \
      jq \
      ripgrep \
      sqlite3 \
      tree \
      unzip \
      zip \
 && ln -sf /usr/bin/fdfind /usr/local/bin/fd \
 && rm -rf /var/lib/apt/lists/*

# Claude Code CLI (subscription auth via CLAUDE_CODE_OAUTH_TOKEN at runtime).
# Pinned since 07-07 codex-runtime (AC5) — the previous floating `latest` was a
# pre-existing reproducibility defect.
ARG CLAUDE_CODE_VERSION=2.1.202
RUN if [ -n "${NPM_REGISTRY}" ]; then npm config set registry "${NPM_REGISTRY}"; fi \
 && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"

# Codex CLI (07-07 codex-runtime): the second runtime a role can select via
# agents/<role>.yaml `provider: codex`. Subscription auth rides the per-role
# CODEX_HOME/auth.json seeded at startup (accounts/<id>/codex-auth.json);
# CODEX_API_KEY covers the api-key mode. The CLI's built-in self-update is
# naturally inert here — the install lives in a read-only image layer.
# gpt-5.6-sol is rejected by 0.142.5; 0.144.3 is live-verified by fourthtest.
ARG CODEX_VERSION=0.144.3
RUN npm install -g "@openai/codex@${CODEX_VERSION}" \
 && npm cache clean --force

# CLI-first external capability surface. Versions are pinned; credentials are
# provided at runtime via accounts/<id>/secrets.env.
ARG GH_VERSION=2.96.0
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in amd64|arm64) ;; *) echo "unsupported gh architecture: $arch" >&2; exit 1 ;; esac; \
    curl -fsSL -o /tmp/gh.deb "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${arch}.deb"; \
    apt-get update; \
    apt-get install -y --no-install-recommends /tmp/gh.deb; \
    rm -f /tmp/gh.deb; \
    rm -rf /var/lib/apt/lists/*

ARG VERCEL_VERSION=54.20.0
ARG WRANGLER_VERSION=4.86.0
ARG LINKINATOR_VERSION=7.6.1
RUN npm install -g "vercel@${VERCEL_VERSION}" "wrangler@${WRANGLER_VERSION}" "linkinator@${LINKINATOR_VERSION}" \
 && npm cache clean --force

# MCP loadout servers (07-03-mcp-loadout), pinned into the image so the per-role
# mcp.json baselines (agents/mcp/<role>.json) start with zero cold npm/pip
# install: DataForSEO (SERP/keywords/backlinks), GA4 (analytics-mcp) and GSC
# (mcp-gsc). Credentials arrive at runtime via accounts/<id>/secrets.env —
# nothing is baked in.
ARG DATAFORSEO_MCP_VERSION=2.9.11
RUN npm install -g "dataforseo-mcp-server@${DATAFORSEO_MCP_VERSION}" \
 && npm cache clean --force

# Playwright MCP (researcher web reading; won the 07-03 playwright-vs-cli
# timebox, see task research/). Chromium is baked into a shared root-owned
# path so the runtime user (uid 1000) finds it without a ~12-min cold
# download; no --with-deps — the kasm desktop image already ships the X libs.
# The install runs from inside the package dir so npx picks ITS pinned
# playwright dep (browser builds are keyed to the exact playwright version).
ARG PLAYWRIGHT_MCP_VERSION=0.0.77
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN npm install -g "@playwright/mcp@${PLAYWRIGHT_MCP_VERSION}" \
 && cd /usr/lib/node_modules/@playwright/mcp \
 && npx playwright install chromium \
 && chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH}" \
 && npm cache clean --force

# Stripe MCP (07-09 stripe-payment-rail): fleet-wide payment rail. The local
# process is a thin stdio->HTTP forwarder to Stripe's hosted mcp.stripe.com,
# so the tool surface equals the key's permission surface. The package's bin
# is literally `mcp`, which collides with the pip `mcp` console script
# installed below (/usr/local/bin wins on PATH) — expose a collision-free
# `stripe-mcp` name and never invoke the bare `mcp` bin. STRIPE_SECRET_KEY
# arrives at runtime via accounts/<id>/secrets.env (read natively by the
# server when --api-key is absent); nothing is baked in.
ARG STRIPE_MCP_VERSION=0.3.3
RUN npm install -g "@stripe/mcp@${STRIPE_MCP_VERSION}" \
 && ln -sf /usr/lib/node_modules/@stripe/mcp/dist/index.js /usr/local/bin/stripe-mcp \
 && npm cache clean --force

# Thin computer-use MCP deps: Claude (in-container) talks to the local computer-server.
# pyyaml: AgentSpec parses the packaged role YAML for startup loadout.
RUN pip install --no-cache-dir --break-system-packages cua-computer mcp pyyaml

# GA4 + GSC MCP servers (pip-distributed; same MCP-loadout pin as above).
ARG GA4_MCP_VERSION=0.6.0
ARG MCP_GSC_VERSION=0.1.0
RUN pip install --no-cache-dir --break-system-packages \
      "analytics-mcp==${GA4_MCP_VERSION}" \
      "mcp-gsc==${MCP_GSC_VERSION}"

# Thin MCP + its config (container-side mode → connects to localhost:8000 computer-server)
COPY --chmod=0755 src/hacksome/stages/build/agent_runtime/cua_mcp.py /opt/foundagent/cua_mcp.py
COPY ops/build/docker/agent-mcp.json /opt/foundagent/mcp.json

# back to the unprivileged desktop user (uid 1000 = kasm-user)
USER 1000
