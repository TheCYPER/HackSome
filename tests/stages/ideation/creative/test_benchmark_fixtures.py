from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[4]
    / ".trellis"
    / "tasks"
    / "archive"
    / "2026-07"
    / "07-22-hackathon-agent-product"
    / "fixtures"
)


class BenchmarkFixtureTests(unittest.TestCase):
    def test_prompts_are_independent_and_hash_bound(self) -> None:
        manifest = json.loads(
            (FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8")
        )
        benchmarks = manifest["benchmarks"]

        self.assertEqual(
            {item["id"] for item in benchmarks},
            {"pawn", "mihoyo-global-release"},
        )
        self.assertEqual(len(benchmarks), 2)

        contents: dict[str, bytes] = {}
        for item in benchmarks:
            content = (FIXTURE_ROOT / item["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), item["sha256"])
            contents[item["id"]] = content

        self.assertEqual(contents["pawn"], b"PAWN\n")
        self.assertNotIn(b"PAWN", contents["mihoyo-global-release"])
        self.assertNotIn(contents["mihoyo-global-release"], contents["pawn"])


if __name__ == "__main__":
    unittest.main()
