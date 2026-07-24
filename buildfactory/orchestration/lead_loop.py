"""Long-running resident Lead loop for one Hackathon Team."""

from __future__ import annotations

import json
import os

from orchestration.agent_loop import (
    DEFAULT_MCP_CONFIG,
    DEFAULT_PROVIDER,
    _role_config,
    agent_loop,
)
from orchestration.control_client import (
    HubClient,
    RemoteInbox,
    load_wake_context,
    notify_wake_completed,
)

DEFAULT_LEAD_HEARTBEAT_SECS = 60
TERMINAL_GOAL_STATES = frozenset({"done", "cancelled"})


def goal_queue_empty(client: HubClient) -> bool:
    result = client.call("list_my_goals")
    goals = result.get("goals") if isinstance(result, dict) else None
    if not isinstance(goals, list):
        raise ValueError("list_my_goals result must contain a goals list")
    return all(
        isinstance(goal, dict) and goal.get("status") in TERMINAL_GOAL_STATES
        for goal in goals
    )


def build_lead_wake_prompt(
    event: dict | None,
    wake_id: str,
    trigger: str,
    now: str,
) -> str:
    if event is None:
        trigger_text = (
            "Quiet heartbeat. Inspect the current real state and continue improving the "
            "project. Quiet is not a completion or idle state."
        )
    else:
        trigger_text = (
            f"subject: {event.get('text', '')}\n"
            "body:\n"
            + json.dumps(event.get("body"), ensure_ascii=False, indent=2, sort_keys=True)
        )
    return f"""HACKATHON LEAD WAKE
wake_id: {wake_id}
trigger: {trigger}
time: {now}

ROLE
You are the long-running Lead for one hackathon project. Treat it as a real
product: inspect reality, form your own judgment, and design the next substantive
step for a Worker to execute.
There is no deadline, completion state, reasonable business-idle state, fixed
product phase, required taxonomy, or standing Objective. You can always inspect,
reconsider, or delegate another meaningful improvement.

PROJECT
Everything the Team builds or changes lives under /project, which you can inspect
with full tools. Start from real files, the running application, browser behavior,
deployments, external systems, and observed evidence. Your runtime permissions are
not technically restricted, but your Lead responsibility is orchestration: do not
create, edit, delete, test, deploy, or otherwise implement product work yourself.
Delegate substantive execution to the Worker through Goals.

/project/reference/challenge.md and
/project/reference/initial-idea-card.md are initializer material only. They are
not immutable requirements. Change direction, reinterpret them, or ignore them
entirely whenever your judgment says the project should do something better.

OPERATING CONTRACT
You have full tools so you can inspect reality and make high-quality decisions;
this is not permission to take over the Worker's implementation role. On each
wake, inspect the real state, decide what should happen next, and create one or
more concrete Goals. The runtime executes them FIFO through one Worker and a
fresh Verifier for each result. Put every requirement the Worker must know in
intent. acceptance is optional private context for the Verifier and is never
shown to the Worker. Do not create plans or status files in /project and do not
create Goals merely to simulate activity.

DETERMINISTIC METHODS
Natural-language claims do not mutate the Hub. Run these exact commands.
Use a stable request-id for one logical mutation; retry the same logical call
with the same request-id.

Create one Goal:
python3 -m orchestration.control_client create_goal \\
  --json '{{"intent":"concrete work","acceptance":"optional verifier-only context"}}' \\
  --request-id 'goal-<stable-purpose-id>'

Create a batch by running create_goal once per Goal with distinct stable
request-ids. Omit acceptance when it adds no useful independent check.

Inspect every Goal and its real current status:
python3 -m orchestration.control_client list_my_goals

Cancel a Goal only when your current judgment has genuinely withdrawn it:
python3 -m orchestration.control_client cancel_goal \\
  --json '{{"goal_id":"goal-...","reason":"why"}}' \\
  --request-id 'cancel-<goal-id>'

TRIGGER
{trigger_text}

Continue the project. Check the real state first, decide what matters now, and
delegate the next substantive work through one or more Goals.
"""


def main() -> None:
    key = os.environ.get("AGENT_KEY", "lead")
    charter_path = os.environ.get("AGENT_CHARTER")
    session_file = os.environ.get("AGENT_SESSION_FILE", "/tmp/hacksome-lead-session-id")
    heartbeat = int(
        os.environ.get("AGENT_HEARTBEAT_SECS", str(DEFAULT_LEAD_HEARTBEAT_SECS))
    )
    (
        provider,
        model,
        effort,
        role_mcp,
        session_mode,
        idle,
        strategic,
        role_prompt,
    ) = _role_config(key)
    mcp_config = os.environ.get("AGENT_MCP") or role_mcp or DEFAULT_MCP_CONFIG
    client = HubClient()
    inbox = RemoteInbox(client)
    print(
        f"[lead-loop] boot provider={provider or DEFAULT_PROVIDER} "
        f"session={session_mode} project=/project",
        flush=True,
    )
    agent_loop(
        key=key,
        session_file=session_file,
        heartbeat=heartbeat,
        charter_path=charter_path,
        system_prompt=role_prompt,
        mcp_config=mcp_config,
        model=model,
        effort=effort,
        provider=provider,
        session_mode=session_mode,
        idle=idle,
        strategic=strategic,
        retry_backoff=float(os.environ.get("AGENT_RETRY_BACKOFF_SECS", "5")),
        inbox=inbox,
        context_loader=lambda: load_wake_context(client),
        prompt_builder=build_lead_wake_prompt,
        wake_gate=lambda _event, _context: goal_queue_empty(client),
        wake_completed=lambda details: notify_wake_completed(details, client),
        completion_owns_ack=True,
    )


if __name__ == "__main__":
    main()
