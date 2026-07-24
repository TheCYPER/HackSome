"""Declarative AgentSpec (AG1 / D5) + credential factory.

An agent's config — provider, credential source, mounted skill/hook/prompt,
system prompt, mcp config — collapses into ONE declaration file (an AgentSpec YAML,
same style as accounts/<id>/secrets.env). Adding/adjusting an agent = edit a yaml,
NO code change (AC1).

Agent spec (capability axis) and account (identity axis) are orthogonal (D5):
a run instance = one AgentSpec YAML × one accounts/<id>/.

The runtime factory lives in agent.runtimes (runtime_for) — the spec stays a
pure declaration and carries model/effort with UNSET semantics: key absent in
the yaml → UNSET (the chosen runtime's own default applies); explicit `null`
→ None (flag omitted, account/CLI default); a string passes through.
"""

import os
from dataclasses import dataclass, field

import yaml

from agent.credentials import CredentialSource
from agent.runtimes.base import UNSET, UnsetType

# Known declaration fields (forward-compatible: unknown keys are ignored).
_FIELDS = (
    "name",
    "provider",
    "credentials",
    "model",
    "effort",
    "system_prompt_fragments",
    "system_prompt",
    "skills",
    "hooks",
    "mcp_config",
    "permission_mode",
    "session",
    "idle",
    "strategic",
)


@dataclass
class AgentSpec:
    """One agent's declarative capability definition (loaded from yaml)."""

    name: str
    provider: str = "claude-code"          # claude-code | codex | opencode(stub)
    credentials: str = "subscription"      # subscription | api-key
    model: str | None | UnsetType = UNSET    # UNSET=runtime default; null=CLI default; str=pin
    effort: str | None | UnsetType = UNSET   # neutral vocabulary low|medium|high|xhigh|max
    system_prompt_fragments: list[str] = field(default_factory=list)
                                             # ordered shared assets prepended to role charter
    system_prompt: str | None = None       # path (relative to base_dir) → charter injection
    skills: list[str] = field(default_factory=list)   # paths (relative to base_dir) → skills dir
    hooks: str | None = None               # path (relative to base_dir) → runtime hook merge
    mcp_config: str = "/opt/foundagent/mcp.json"      # in-container path (cua-local)
    permission_mode: str = "bypass"        # bypass → the runtime's skip-permissions flag
    session: str = "fresh"                 # fresh (default) | resume — cross-wake session
                                           # continuity (issue #207); resume is the opt-in
                                           # exception (today: the CEO), consumed by agent_loop
    idle: str = "stop"                     # stop (default) | proactive — empty-heartbeat stance
                                           # (07-08 proactive-idle); proactive is the opt-in
                                           # exception (today: the CEO), consumed by agent_loop
    strategic: bool = False                # every-wake strategic-reasoning stance; false keeps
                                           # the historical prompt byte-identical, consumed only
                                           # by the resident agent_loop
    base_dir: str = ""                     # dir of the yaml, for resolving relative asset paths

    @classmethod
    def load(cls, path: str) -> "AgentSpec":
        """Load an AgentSpec from a yaml declaration file.

        Only keys PRESENT in the yaml are passed through — an absent model/
        effort key keeps the UNSET default, while an explicit `model: null`
        arrives as None. That absent-vs-null distinction is load-bearing
        (design §3): UNSET → adapter default, None → omit the flag."""
        path = os.path.abspath(path)
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError(f"agent spec must be a mapping: {path}")
        kwargs = {k: data[k] for k in _FIELDS if k in data}
        if "name" not in kwargs:
            kwargs["name"] = os.path.splitext(os.path.basename(path))[0]
        kwargs["base_dir"] = os.path.dirname(path)
        return cls(**kwargs)

    # --- asset-path resolution (relative to the yaml's directory) -------------

    def resolve(self, rel: str) -> str:
        return rel if os.path.isabs(rel) else os.path.join(self.base_dir, rel)

    def read_system_prompt(self) -> str | None:
        """Assemble declared shared fragments followed by the role charter.

        Every path is relative to this spec's yaml. Fragments are explicit per
        role rather than globally injected, so adding a role does not silently
        change its system prompt.
        """
        prompt_paths = list(self.system_prompt_fragments)
        if self.system_prompt:
            prompt_paths.append(self.system_prompt)
        if not prompt_paths:
            return None
        parts: list[str] = []
        for path in prompt_paths:
            with open(self.resolve(path)) as f:
                parts.append(f.read().strip())
        return "\n\n".join(parts)

    def skill_paths(self) -> list[str]:
        return [self.resolve(s) for s in self.skills]

    def hooks_path(self) -> str | None:
        return self.resolve(self.hooks) if self.hooks else None

    @property
    def bypass_permissions(self) -> bool:
        return self.permission_mode == "bypass"


def credential_for(spec: AgentSpec) -> CredentialSource:
    """Factory: spec.credentials → CredentialSource instance, provider-aware
    (07-07 codex-runtime, design §5): the yaml vocabulary is runtime-relative,
    so the chosen runtime's credential_kinds() supplies the mapping (claude:
    OAuth token / Anthropic key; codex: auth.json seed / CODEX_API_KEY)."""
    from agent.runtimes import runtime_for  # lazy: the spec stays declaration-only at import time
    cls = runtime_for(spec).credential_kinds().get(spec.credentials)
    if cls is None:
        raise ValueError(f"unknown credential source: {spec.credentials!r}")
    return cls()
