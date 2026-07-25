# Foundagent — per-account static egress expansion (07-03-proxy-slot).
#
# Sourced by vm/docker/agent_startup.sh in the computer-server subshell ONLY,
# so the CUA desktop/browser subtree inherits one per-account exit IP while the
# agent_loop / claude subtree stays proxy-free (LLM traffic must not ride a
# metered residential proxy, and the claude CLI ignores host-based NO_PROXY —
# see the hook comment). Lives in agent/ (not vm/docker/) because agent/ is the
# dir the compose x-agent anchor ro-mounts into every role; vm/docker/ is not
# mounted beyond the single startup-hook file bind.
#
# Contract (same semantics for resident Agents and ephemeral Workers):
#   CUA_PROXY set   -> export upper+lowercase HTTP(S)_PROXY pairs (curl ignores
#                      uppercase HTTP_PROXY; tools disagree, so give both) plus
#                      NO_PROXY/no_proxy.
#   CUA_PROXY unset -> export nothing at all (host egress, behavior unchanged).
#
# The NO_PROXY default keeps local API surfaces (computer-server on localhost)
# off the proxy, plus Anthropic/claude.ai as defense in depth for curl-based
# tooling in this subtree. Dotted and bare spellings are both listed because
# NO_PROXY suffix-matching differs across curl / Node undici / Go. An explicit
# NO_PROXY in accounts/<id>/secrets.env overrides the whole default.
if [ -n "${CUA_PROXY:-}" ]; then
  export HTTP_PROXY="$CUA_PROXY" HTTPS_PROXY="$CUA_PROXY"
  export http_proxy="$CUA_PROXY" https_proxy="$CUA_PROXY"
  export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,.anthropic.com,anthropic.com,.claude.ai,claude.ai}"
  export no_proxy="$NO_PROXY"
fi
