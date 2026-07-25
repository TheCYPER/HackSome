#!/usr/bin/env bash
# Foundagent — the agent's own browser (07-03-social-rail MVP).
#
# Wrapper launching playwright-mcp so every agent has ONE browser that carries
# the account's full login state by default (2026-07-06 user decision: a human
# browses with their own browser, not incognito — no second "clean" instance).
# The MCP json cannot express conditional args, so each role's `playwright`
# server points here. It lives with packaged Build assets because Compose
# read-only mounts `src/hacksome` into every role at `/opt/hacksome/hacksome`;
# `ops/build/docker` contributes only the startup-hook bind and image config.
#
# Three INDEPENDENT graceful degradations (missing any is a legal state, never
# brick the server):
#   DISPLAY unset  -> add --headless (headed is playwright-mcp's default; with
#                     DISPLAY the browser runs headed on the kasm desktop, VNC-
#                     observable and better against anti-bot fingerprinting).
#   cookies seed   -> $ACCOUNT_DIR/cookies/storage-state.json present adds
#                     --isolated --storage-state <file>. The pair is mandatory:
#                     0.0.77 help says storage-state applies to ISOLATED
#                     sessions only. isolated = in-memory profile seeded from
#                     the file, never written back — matching the ro /account
#                     mount (read-only seed; expiry = re-export by hand).
#   CUA_PROXY set  -> add --proxy-server so ALL browser traffic rides the
#                     account IP (research browsing included — informed cost,
#                     PRD note). CUA_PROXY itself is a container-level env the
#                     claude subtree can read; proxy_env.sh only withholds the
#                     expanded HTTP(S)_PROXY vars from that subtree, so LLM
#                     traffic stays structurally off the proxy.
#
# --browser chromium is LOAD-BEARING: both playwright routes default to the
# branded-chrome channel, which the container does not ship (07-03
# playwright-vs-cli research) — dropping the flag bricks every navigation.
set -eu

ACCOUNT_DIR="${ACCOUNT_DIR:-/account}"
STORAGE_STATE="$ACCOUNT_DIR/cookies/storage-state.json"

args=(--browser chromium)
[ -z "${DISPLAY:-}" ] && args+=(--headless)
[ -f "$STORAGE_STATE" ] && args+=(--isolated --storage-state "$STORAGE_STATE")
[ -n "${CUA_PROXY:-}" ] && args+=(--proxy-server "$CUA_PROXY")

exec playwright-mcp "${args[@]}"
