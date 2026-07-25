from pathlib import Path

import pytest

from hacksome.stages.build.control.runtime_store import CompanyLayout, INTERNAL_DOMAINS, StoreError


def test_new_company_layout_initializes_separate_control_domains(tmp_path):
    layout = CompanyLayout.initialize(tmp_path / "new-company")

    assert layout.company.is_dir()
    assert all((layout.root / name).is_dir() for name in INTERNAL_DOMAINS)
    assert (layout.telemetry / "runs").is_dir()
    assert (layout.reviews / "homes").is_dir()
    assert layout.mailboxes.is_dir()


def test_llm_state_mount_exposes_only_company(tmp_path):
    layout = CompanyLayout.initialize(tmp_path / "new-company")

    assert layout.agent_state_mount() == {
        "source": str(layout.company),
        "target": "/company",
        "mode": "rw",
    }
    assert layout.agent_state_mount(read_only=True)["mode"] == "ro"
    assert all(name not in layout.agent_state_mount()["source"] for name in INTERNAL_DOMAINS)


def test_actor_paths_reject_traversal(tmp_path):
    layout = CompanyLayout.initialize(tmp_path / "new-company")

    with pytest.raises(StoreError):
        layout.notes_path("../ceo")
    assert layout.objective_path("researcher") == Path(layout.agents / "researcher/objective.md")
