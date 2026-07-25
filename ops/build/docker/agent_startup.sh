#!/bin/bash
# Foundagent — resident agent startup hook (06-29 rebuild ① stage 5).
#
# Mounted over /dockerstartup/custom_startup.sh. kasm's vnc_startup.sh calls this
# in the BACKGROUND once the desktop is up (DISPLAY set) and tracks its PID
# (KASM_PROCS['custom_startup']). So this is where an agent container gets its
# computer-server AND its resident loop, with the full kasm desktop already live.
#
# - computer-server (bundled 0.3.17) needs the X desktop (now present) → run it in
#   the BACKGROUND so the cua MCP (localhost:8000) works for this agent.
# - the resident agent_loop runs in the FOREGROUND so this hook stays alive for the
#   container's lifetime (kasm monitors its PID). key/charter/mcp come from the
#   container env (AGENT_KEY / AGENT_CHARTER / AGENT_MCP / PYTHONPATH).
#
# `claude` and `node` live in /usr/bin (always on PATH); no profile sourcing needed.
# AGENT_LOOP_MODULE lets the Hackathon Team select its Lead loop without
# replacing this startup hook and accidentally skipping computer-server.

# Per-account static egress (07-03-proxy-slot): expand CUA_PROXY (injected from
# accounts/<id>/secrets.env) into proxy env for the computer-server subtree ONLY
# — the CUA desktop/browser is the account-sensitive surface. The agent_loop /
# claude subtree must NEVER see HTTP(S)_PROXY: the claude CLI ignores host-based
# NO_PROXY entries (only "*" is honored, verified 2026-07-03), so keeping LLM
# traffic off a metered residential proxy has to be structural, not an exclusion
# list. Skills that need account-pinned API calls use `curl -x "$CUA_PROXY"`.
# Guarded: a missing snippet (stale image/mount) must never brick startup.
( [ -f /opt/hacksome/hacksome/stages/build/assets/scripts/proxy_env.sh ] && . /opt/hacksome/hacksome/stages/build/assets/scripts/proxy_env.sh
  exec /usr/bin/python3 -m computer_server ) &

# Materialize this agent's declared skills + hooks (agents/$AGENT_KEY.yaml) into
# ~/.claude so subscription claude auto-discovers them by description. Best-effort:
# on error it logs + exits 0, so a bad loadout degrades to charter-only rather than
# bricking the agent. The charter itself is injected per-wake by agent_loop, not here.
/usr/bin/python3 -m hacksome.stages.build.agent_runtime.resident_loadout

exec /usr/bin/python3 -m "${AGENT_LOOP_MODULE:-hacksome.stages.build.control.agent_loop}"
