"""Build stage: one Lead, one Worker lifecycle, and fresh Verifiers."""

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
ASSETS_ROOT = PACKAGE_ROOT / "assets"
AGENTS_ROOT = ASSETS_ROOT / "agents"

__all__ = ["AGENTS_ROOT", "ASSETS_ROOT", "PACKAGE_ROOT"]
