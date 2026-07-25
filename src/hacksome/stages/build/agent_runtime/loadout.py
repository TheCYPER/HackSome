"""Loadout neutral core: skills copy + manifest reconcile (AG4 / D6).

Runtime-NEUTRAL half of home materialization (07-07 codex-runtime split): the
skills-copy and the bookkeeping-manifest reconcile know nothing about which
runtime's home they land in — the claude adapter points them at
<claude_home>/skills, the codex adapter at its own skills dir. The runtime-
specific steps (claude's settings.json, codex's config.toml) live in each
adapter's materialize_home (agent/runtimes/*). The hooks helpers below are
neutral too (07-09 codex-hooks): they operate on ANY JSON file with a
top-level `hooks` key — claude's settings.json and codex's hooks.json share
that shape verbatim (event → matcher groups → handlers, live-verified on
codex-cli 0.142.5), so both adapters call the same three functions.

Reconcile (07-03 company-loadout-overlay): the home persists across restarts,
so "off" must UNDO what a previous run materialized. materialize_home keeps a
bookkeeping manifest <home>/.loadout-manifest.json recording what THE LOADOUT
itself put there — the skill names it copied and the hook ENTRIES it merged
(per event; the hook values are runtime-shaped and opaque to this core). Each
run first deletes skills in (previous manifest − current spec) and lets the
adapter value-remove previously merged hook entries. Anything NOT in the
manifest (agent-installed skills, agent-added settings keys/entries) is NEVER
touched. No/corrupt manifest = empty manifest → add-only, safe for first runs
and pre-feature homes.
"""

import json
import os
import shutil
from dataclasses import dataclass, field

MANIFEST_NAME = ".loadout-manifest.json"


@dataclass
class LoadoutInfo:
    """What materialize_home() prepared, for logging / callers / assertions.

    settings_path/hooks_merged are claude-specific outputs; other runtimes
    leave them at their defaults."""

    home: str
    system_prompt: str | None
    skills: list[str] = field(default_factory=list)   # skill names materialized
    settings_path: str = ""
    hooks_merged: bool = False
    warnings: list[str] = field(default_factory=list)  # non-fatal notes (caller prints)


def sync_skills(skills_root: str, skill_srcs: list[str], names: list[str],
                previous: list[str]) -> None:
    """Reconcile + copy the declared skills into skills_root.

    Deletes skill dirs the loadout materialized last run (per the manifest)
    but no longer declares, then (re-)copies each declared skill tree.
    Idempotent; never touches dirs absent from the manifest."""
    _remove_stale_skills(skills_root, previous, names)
    for src, name in zip(skill_srcs, names):
        dst = os.path.join(skills_root, name)
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)


def read_manifest(path: str) -> tuple[dict, list[str]]:
    """Previous run's bookkeeping, shape-validated. Missing = empty (first run /
    pre-feature home → add-only). Corrupt = empty + a warning, never a crash."""
    empty: dict[str, object] = {"skills": [], "hooks": {}}
    if not os.path.exists(path):
        return empty, []
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        data = None
    if not isinstance(data, dict):
        return dict(empty), [f"loadout manifest {path}: corrupt — treating as "
                             "empty (add-only, nothing removed this run)"]
    skills = data.get("skills")
    hooks = data.get("hooks")
    return {
        "skills": [s for s in skills if isinstance(s, str)]
        if isinstance(skills, list) else [],
        # per-event values must be entry LISTS or the adapter's hook removal
        # would trip on them; a garbage event degrades to add-only for that
        # event, no crash
        "hooks": {k: v for k, v in hooks.items() if isinstance(v, list)}
        if isinstance(hooks, dict) else {},
    }, []


def write_manifest(path: str, skills: list[str], hooks: dict) -> None:
    with open(path, "w") as f:
        json.dump({"skills": skills, "hooks": hooks}, f, indent=2)


def _remove_stale_skills(skills_root: str, previous: list[str],
                         current: list[str]) -> None:
    """Delete skill dirs the loadout materialized last run but dropped this run.
    Only names from the manifest are candidates — a dir the agent installed
    itself is not in the manifest and is never touched."""
    for name in previous:
        if not name or name in (".", "..") or os.path.basename(name) != name:
            continue  # defensive: a manifest name must be a bare dir name —
            # "." / ".." / anything with a separator would escape skills_root
        if name in current:
            continue
        stale = os.path.join(skills_root, name)
        if os.path.isdir(stale):
            shutil.rmtree(stale)


# --- hooks snippet merge/remove (07-09 codex-hooks: moved verbatim from
# runtimes/claude_code.py — the schema turned out runtime-neutral) ---------------
#
# All three operate on a JSON file whose top-level `hooks` key maps event names
# to entry lists (claude: <home>/settings.json; codex: CODEX_HOME/hooks.json —
# identical shape, so the merge/remove/dedup semantics carry over unchanged).

def snippet_hooks(snippet_path: str | None) -> dict:
    """The snippet's per-event hook entries; {} = no hooks this run."""
    if not snippet_path:
        return {}
    with open(snippet_path) as f:
        snippet = json.load(f)
    hooks = snippet.get("hooks", {})
    return hooks if isinstance(hooks, dict) else {}


def remove_hooks(hooks_file: str, stale_hooks: dict) -> None:
    """Reverse of merge_hooks: remove from the hooks file exactly the entries
    value-equal to what the previous run's manifest recorded. Every other key
    and entry — including hook entries the agent added under the same event —
    stays. An event whose list empties out is dropped."""
    if not os.path.exists(hooks_file):
        return
    try:
        with open(hooks_file) as f:
            doc = json.load(f)
    except json.JSONDecodeError:
        return
    if not isinstance(doc, dict):
        return
    hooks = doc.get("hooks")
    if not isinstance(hooks, dict):
        return

    changed = False
    for event, entries in stale_hooks.items():
        existing = hooks.get(event)
        if not isinstance(existing, list):
            continue
        stale = {json.dumps(e, sort_keys=True) for e in entries}
        kept = [e for e in existing if json.dumps(e, sort_keys=True) not in stale]
        if len(kept) == len(existing):
            continue
        changed = True
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]

    if changed:
        with open(hooks_file, "w") as f:
            json.dump(doc, f, indent=2)


def merge_hooks(hooks_file: str, snippet_hooks: dict) -> bool:
    """Merge the snippet's per-event entries into the hooks file. Preserves
    every existing top-level key and existing hook entries; appends only NEW
    hook entries (dedup by value → idempotent). Returns True when merged."""
    doc: dict = {}
    if os.path.exists(hooks_file):
        try:
            with open(hooks_file) as f:
                doc = json.load(f) or {}
        except json.JSONDecodeError:
            doc = {}
    if not isinstance(doc, dict):
        doc = {}

    hooks = doc.setdefault("hooks", {})
    for event, entries in snippet_hooks.items():
        existing = hooks.setdefault(event, [])
        seen = {json.dumps(e, sort_keys=True) for e in existing}
        for entry in entries:
            if json.dumps(entry, sort_keys=True) not in seen:
                existing.append(entry)

    with open(hooks_file, "w") as f:
        json.dump(doc, f, indent=2)
    return True
