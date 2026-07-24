"""Versioned Prompt catalog for the four Pitch roles."""

from __future__ import annotations

from pathlib import Path

from hacksome.prompting import PromptCatalog, PromptSpec


_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_PROMPT_DIR = _PACKAGE_ROOT / "prompts" / "pitch"
_SCHEMA_DIR = _PACKAGE_ROOT / "schemas" / "pitch"


pitch_prompt_catalog = PromptCatalog(
    (
        PromptSpec(
            "pitch-director",
            "hacksome.pitch.director",
            "4",
            _PROMPT_DIR / "pitch-director.md",
            _SCHEMA_DIR / "pitch-director.schema.json",
        ),
        PromptSpec(
            "pitch-reviewer",
            "hacksome.pitch.reviewer",
            "4",
            _PROMPT_DIR / "accuracy-reviewer.md",
            _SCHEMA_DIR / "accuracy-reviewer.schema.json",
        ),
        PromptSpec(
            "pitch-html",
            "hacksome.pitch.html",
            "5",
            _PROMPT_DIR / "html-agent.md",
            _SCHEMA_DIR / "html-agent.schema.json",
        ),
        PromptSpec(
            "pitch-script",
            "hacksome.pitch.script",
            "4",
            _PROMPT_DIR / "script-agent.md",
            _SCHEMA_DIR / "script-agent.schema.json",
        ),
    )
)


__all__ = ["pitch_prompt_catalog"]
