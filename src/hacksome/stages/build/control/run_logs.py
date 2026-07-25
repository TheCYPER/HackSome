"""Complete operator-only run archives for Agents and deterministic services."""

from __future__ import annotations

import os
import re
from pathlib import Path

from hacksome.stages.build.control.runtime_store import atomic_write_json, atomic_write_text


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class RunLogRecorder:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def record(
        self,
        *,
        run_id: str,
        metadata: dict,
        raw_output: str,
        stderr: str,
        model_output: str,
        harness_log: str = "",
        container_log: str = "",
    ) -> Path:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError(f"invalid run id: {run_id!r}")
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(run_dir / "metadata.json", metadata)
        files = {
            "runtime.jsonl": raw_output,
            "stderr.log": stderr,
            "model-output.txt": model_output,
            "harness.log": harness_log,
            "container.log": container_log,
        }
        for name, content in files.items():
            atomic_write_text(run_dir / name, content or "")
        return run_dir


def recorder_from_env() -> RunLogRecorder | None:
    root = os.environ.get("RUN_LOGS_DIR")
    if not root or not os.path.isdir(root):
        return None
    return RunLogRecorder(root)


def append_service_log(root: str | Path, service: str, line: str) -> None:
    """Append one complete service line to operator-only telemetry storage."""
    path = Path(root) / f"{service}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line.rstrip("\n") + "\n")
