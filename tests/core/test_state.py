from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hacksome.core.state import (
    StateConflictError,
    StateError,
    advisory_lease,
    append_jsonl,
    atomic_write_json,
    canonical_json_bytes,
    read_json_object,
    read_jsonl,
    sha256_json,
)


class StateTests(unittest.TestCase):
    def test_atomic_json_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            atomic_write_json(path, {"text": "中文", "count": 2})
            self.assertEqual(read_json_object(path), {"text": "中文", "count": 2})

    def test_jsonl_is_idempotent_by_stable_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            record = {"event_id": "event-1", "kind": "started"}
            self.assertTrue(append_jsonl(path, record, id_field="event_id"))
            self.assertFalse(append_jsonl(path, record, id_field="event_id"))
            self.assertEqual(read_jsonl(path), [record])

            with self.assertRaises(StateConflictError):
                append_jsonl(
                    path,
                    {"event_id": "event-1", "kind": "different"},
                    id_field="event_id",
                )

    def test_canonical_json_hash_ignores_object_key_order(self) -> None:
        first = {"b": [2, 1], "a": "中文"}
        second = {"a": "中文", "b": [2, 1]}
        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
        self.assertEqual(sha256_json(first), sha256_json(second))

    def test_read_only_lease_does_not_create_a_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.lock"
            with self.assertRaises(StateError):
                with advisory_lease(path, exclusive=False, create=False):
                    self.fail("missing lock must not be acquired")
            self.assertFalse(path.exists())

            with advisory_lease(path, exclusive=True):
                self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
