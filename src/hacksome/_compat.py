"""Helpers for temporary import-path compatibility modules."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType


def alias_module(old_name: str, canonical_name: str) -> ModuleType:
    """Make an old module path resolve to the canonical implementation module."""

    module = importlib.import_module(canonical_name)
    sys.modules[old_name] = module
    return module
