"""Ensure the repo root is importable as `orchestration` regardless of how
pytest is invoked (mirrors agent/tests/conftest.py)."""

import os
import sys
from pathlib import Path

import pytest
import yaml

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)


@pytest.fixture
def department_specs(tmp_path: Path) -> Path:
    """Self-contained legacy Company catalog for tests of retained source."""
    directory = tmp_path / "fixture-agents" / "departments"
    directory.mkdir(parents=True)
    public = {
        "strategist": (
            "Strategy Department",
            "研究产品、用户、机会、商业模式与战略选项，并向 CEO 提供判断。",
        ),
        "researcher": (
            "Research Department",
            "获取一手或二手证据、验证关键假设并形成可复用结论。",
        ),
        "builder": (
            "Build Department",
            "把已选择的方向转化为可运行、可交付、可验证的产品与技术资产。",
        ),
        "growth": (
            "Growth Department",
            "Responsible for distribution, content, user acquisition, channel "
            "experimentation, conversion, and growth feedback.",
        ),
    }
    for template_id, (name, description) in public.items():
        row = {
            "name": template_id,
            "public_name": name,
            "public_description": description,
            "heartbeat_secs": 900,
            "system_prompt": f"../assets/departments/{template_id}-charter.md",
        }
        (directory / f"{template_id}.yaml").write_text(
            yaml.safe_dump(row, allow_unicode=True),
            encoding="utf-8",
        )
    return directory
