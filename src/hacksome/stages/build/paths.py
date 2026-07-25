"""Canonical package and operator paths for the Build stage."""

from __future__ import annotations

from pathlib import Path

from hacksome.stages.build import AGENTS_ROOT


def repository_agents_root(repository_root: str | Path | None = None) -> Path:
    """Resolve AgentSpec assets from a checkout or the installed package."""

    if repository_root is None:
        return AGENTS_ROOT
    return (
        Path(repository_root)
        / "src"
        / "hacksome"
        / "stages"
        / "build"
        / "assets"
        / "agents"
    )
