"""Foundagent Agent layer — single-agent capability + execution wrapper.

Turns the VM layer's "a bare CLI agent process inside a container" into a
declarable, task-runnable, runtime-swappable, skill/hook/prompt-loadable
single-agent abstraction. This layer owns ONE agent's capability + exec
interface only; multi-agent scheduling/teardown belongs to the orchestration
layer (it reuses VM-layer computer-use / browser / account-injection / proxy /
observability — never re-building them).

Public surface:
    AgentSpec, credential_for                          (spec.py)
    CredentialSource, SubscriptionCreds, ApiKeyCreds,
    CodexSubscriptionCreds, CodexApiKeyCreds           (credentials.py)
    Runtime, RunRequest, RunResult, UNSET, runtime_for (runtimes/)
    ClaudeCodeRuntime, parse_stream_json               (runtimes/claude_code.py)
    CodexRuntime                                       (runtimes/codex.py)
    LoadoutInfo                                        (loadout.py — neutral core)
    run_task                                           (runner.py)
"""

from hacksome.stages.build.agent_runtime.spec import AgentSpec, credential_for
from hacksome.stages.build.agent_runtime.credentials import (
    ALL_CREDENTIAL_VARS,
    ApiKeyCreds,
    CodexApiKeyCreds,
    CodexSubscriptionCreds,
    CredentialSource,
    SubscriptionCreds,
    injection_env,
)
from hacksome.stages.build.agent_runtime.runtimes import (
    ClaudeCodeRuntime,
    CodexRuntime,
    OpenCodeRuntime,
    Runtime,
    RunRequest,
    RunResult,
    UNSET,
    runtime_for,
)
from hacksome.stages.build.agent_runtime.runtimes.claude_code import parse_stream_json
from hacksome.stages.build.agent_runtime.loadout import LoadoutInfo
from hacksome.stages.build.agent_runtime.runner import run_task

__all__ = [
    "AgentSpec",
    "credential_for",
    "CredentialSource",
    "SubscriptionCreds",
    "ApiKeyCreds",
    "CodexSubscriptionCreds",
    "CodexApiKeyCreds",
    "injection_env",
    "ALL_CREDENTIAL_VARS",
    "Runtime",
    "RunRequest",
    "RunResult",
    "UNSET",
    "runtime_for",
    "ClaudeCodeRuntime",
    "CodexRuntime",
    "OpenCodeRuntime",
    "LoadoutInfo",
    "run_task",
    "parse_stream_json",
]
