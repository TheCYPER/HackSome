"""Golden argv lock for the merged claude adapter (07-07 codex-runtime, AC1).

fixtures/claude_argv_golden.json holds PRE-refactor argv snapshots of both
legacy builders (hacksome.stages.build.control.agent_loop.build_claude_argv — resident path;
agent.provider.ClaudeCodeProvider.build_exec — broker path), captured before
either was deleted. The merged ClaudeCodeRuntime.build_argv must reproduce
every snapshot EXCEPT the three deliberate differences of design.md §3:

  1. resident path GAINS `--output-format stream-json --verbose`
     (structured error/cost/usage instead of exit-code-only);
  2. broker path GAINS `--strict-mcp-config`
     (catches up with the 07-03 mcp-loadout decision);
  3. session unification: resume_token → `--resume`, otherwise ALWAYS
     `--session-id` (session_hint or a fresh uuid) — the broker's previously
     session-less invocations now mint one.

Equality is on (prompt, flag/value multiset): the merged builder interleaves
flags in one canonical order, and flag order is meaningless to the CLI — any
NON-listed difference in flags or values fails the test.
"""

import json
import os
import re
import uuid

from hacksome.stages.build.agent_runtime.runtimes.base import UNSET, RunRequest
from hacksome.stages.build.agent_runtime.runtimes.claude_code import ClaudeCodeRuntime
from hacksome.stages.build.agent_runtime.spec import AgentSpec

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "claude_argv_golden.json")

# The claude flag lexicon as of the snapshot. canon() hard-fails on anything
# else, so the adapter cannot quietly grow/lose a flag without failing here.
VALUE_FLAGS = {"--resume", "--session-id", "--append-system-prompt",
               "--mcp-config", "--model", "--effort", "--output-format"}
BOOL_FLAGS = {"--verbose", "--strict-mcp-config", "--dangerously-skip-permissions"}

# The three deliberate diffs, encoded EXPLICITLY (design §3 table):
RESIDENT_GAINS = [("--output-format", "stream-json"), ("--verbose",)]   # diff 1
BROKER_GAINS = [("--strict-mcp-config",)]                               # diff 2
# diff 3 is value-level: broker snapshots without a session_id now carry a
# freshly minted ("--session-id", <uuid4>) pair — asserted per-case below.

UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _load():
    with open(FIXTURE) as f:
        return json.load(f)


def canon(argv: list[str]) -> tuple[str, list[tuple]]:
    """(prompt, sorted flag/value pairs) — order-free but value-exact."""
    assert argv[:2] == ["claude", "-p"], argv
    prompt = argv[2]
    pairs: list[tuple] = []
    i = 3
    while i < len(argv):
        flag = argv[i]
        if flag in VALUE_FLAGS:
            pairs.append((flag, argv[i + 1]))
            i += 2
        elif flag in BOOL_FLAGS:
            pairs.append((flag,))
            i += 1
        else:
            raise AssertionError(f"unknown flag in argv: {flag!r} ({argv})")
    return prompt, sorted(pairs)


def test_fixture_is_the_pre_refactor_capture():
    data = _load()
    assert len(data["resident"]) == 48
    assert len(data["broker"]) == 144


def test_resident_golden_only_gains_stream_json_verbose():
    """Old resident argv + diff 1 == merged adapter argv, for ALL 48 cases."""
    for case in _load()["resident"]:
        p = case["params"]
        req = RunRequest(
            prompt=p["prompt"],
            charter=p["charter"],
            mcp_config=p["mcp_config"],
            # legacy resident None meant "omit the flag" → maps to None, not UNSET
            model=p["model"],
            effort=p["effort"],
            resume_token=p["resume"],
            session_hint=p["new_session"],
        )
        new_prompt, new_pairs = canon(ClaudeCodeRuntime().build_argv(req))
        old_prompt, old_pairs = canon(case["argv"])
        assert new_prompt == old_prompt
        assert new_pairs == sorted(old_pairs + RESIDENT_GAINS), p


def test_broker_golden_only_gains_strict_mcp_and_session_id():
    """Old broker argv + diff 2 (+ diff 3 when session-less) == merged adapter
    argv, for ALL 144 cases."""
    for case in _load()["broker"]:
        p = case["params"]
        spec = AgentSpec(name="t", mcp_config=p["mcp_config"],
                         base_dir=p["base_dir"],
                         permission_mode=p["permission_mode"])
        req = RunRequest(
            prompt=p["task"],
            charter=p["system_prompt_arg"],
            # mirror run_task: resolve yaml-relative mcp against the yaml dir
            mcp_config=spec.resolve(spec.mcp_config),
            model=UNSET if p["model"] == "__default__" else p["model"],
            effort=UNSET if p["effort"] == "__default__" else p["effort"],
            session_hint=p["session_id"],
            bypass_permissions=spec.bypass_permissions,
        )
        new_prompt, new_pairs = canon(ClaudeCodeRuntime().build_argv(req))
        old_prompt, old_pairs = canon(case["argv"])
        assert new_prompt == old_prompt
        if p["session_id"] is None:
            # diff 3: the previously session-less broker run now pre-sets a
            # session id — exactly one pair, a well-formed uuid4, then excluded
            # from the flag-set comparison (its value is freshly minted).
            minted = [pair for pair in new_pairs if pair[0] == "--session-id"]
            assert len(minted) == 1, p
            assert UUID4_RE.match(minted[0][1]), minted
            new_pairs.remove(minted[0])
        assert new_pairs == sorted(old_pairs + BROKER_GAINS), p


def test_adapter_mints_a_fresh_uuid_per_new_session():
    """diff 3 hygiene: without resume/hint every run gets its OWN uuid (a
    shared/static id would collide sessions across agents)."""
    a = ClaudeCodeRuntime().build_argv(RunRequest(prompt="x"))
    b = ClaudeCodeRuntime().build_argv(RunRequest(prompt="x"))
    sid_a = a[a.index("--session-id") + 1]
    sid_b = b[b.index("--session-id") + 1]
    assert sid_a != sid_b
    assert uuid.UUID(sid_a).version == 4
