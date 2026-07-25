from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import dataclass
from typing import Literal

from hacksome.core.config import (
    CodexConfig,
    PersistedConfigError,
    codex_config_sha256,
    decode_codex_config,
    decode_persisted_dataclass,
    persisted_dataclass_sha256,
    serialize_codex_config,
    serialize_persisted_dataclass,
)


def _payload_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class _ExampleSettings:
    count: int = 2
    enabled: bool = True
    labels: tuple[str, ...] = ("alpha",)
    mode: Literal["fast", "safe"] = "safe"
    note: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.count, bool) or self.count < 1:
            raise ValueError("count must be positive")


class CodexConfigCodecTests(unittest.TestCase):
    def test_round_trip_is_canonical_json_and_restores_tuples(self) -> None:
        config = CodexConfig(
            executable="codex-你好",
            model="gpt-test",
            disabled_features=("hooks", "apps"),
            config_overrides=("project_doc_max_bytes=0",),
        )

        payload = serialize_codex_config(config)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = codex_config_sha256(config)
        restored = decode_codex_config(
            json.loads(encoded),
            expected_sha256=digest,
        )

        self.assertIn("你好".encode(), encoded)
        self.assertEqual(digest, hashlib.sha256(encoded).hexdigest())
        self.assertEqual(payload["disabled_features"], ["hooks", "apps"])
        self.assertEqual(
            payload["config_overrides"],
            ["project_doc_max_bytes=0"],
        )
        self.assertEqual(restored, config)
        self.assertIsInstance(restored.disabled_features, tuple)
        self.assertIsInstance(restored.config_overrides, tuple)

    def test_hash_is_independent_of_json_object_key_order(self) -> None:
        config = CodexConfig()
        payload = serialize_codex_config(config)
        reordered = dict(reversed(tuple(payload.items())))

        restored = decode_codex_config(
            reordered,
            expected_sha256=codex_config_sha256(config),
        )

        self.assertEqual(restored, config)

    def test_decoder_rejects_missing_and_unknown_fields_before_construction(
        self,
    ) -> None:
        payload = serialize_codex_config(CodexConfig())

        missing = dict(payload)
        del missing["strict_config"]
        with self.assertRaisesRegex(
            PersistedConfigError,
            r"missing fields: strict_config",
        ):
            decode_codex_config(
                missing,
                expected_sha256=_payload_sha256(missing),
            )

        unknown = dict(payload)
        unknown["future_safety_switch"] = True
        with self.assertRaisesRegex(
            PersistedConfigError,
            r"unknown fields: future_safety_switch",
        ):
            decode_codex_config(
                unknown,
                expected_sha256=_payload_sha256(unknown),
            )

    def test_decoder_rejects_hash_drift(self) -> None:
        config = CodexConfig()
        payload = serialize_codex_config(config)
        expected_sha256 = codex_config_sha256(config)
        payload["model"] = "different-model"

        with self.assertRaisesRegex(PersistedConfigError, "hash mismatch"):
            decode_codex_config(
                payload,
                expected_sha256=expected_sha256,
            )

    def test_decoder_rejects_non_json_tuple_input(self) -> None:
        config = CodexConfig()
        payload: dict[str, object] = dict(serialize_codex_config(config))
        payload["disabled_features"] = config.disabled_features

        with self.assertRaisesRegex(PersistedConfigError, "not valid JSON data"):
            decode_codex_config(
                payload,
                expected_sha256=codex_config_sha256(config),
            )

    def test_decoder_strictly_distinguishes_boolean_and_integer_fields(self) -> None:
        payload = serialize_codex_config(CodexConfig())
        payload["max_concurrency"] = True
        with self.assertRaisesRegex(PersistedConfigError, "must be an integer"):
            decode_codex_config(
                payload,
                expected_sha256=_payload_sha256(payload),
            )

        payload = serialize_codex_config(CodexConfig())
        payload["ignore_rules"] = 1
        with self.assertRaisesRegex(PersistedConfigError, "must be a boolean"):
            decode_codex_config(
                payload,
                expected_sha256=_payload_sha256(payload),
            )

    def test_serializer_rejects_invalid_runtime_types_and_non_finite_numbers(
        self,
    ) -> None:
        wrong_boolean = CodexConfig(ignore_rules=1)  # type: ignore[arg-type]
        with self.assertRaisesRegex(PersistedConfigError, "must be a boolean"):
            serialize_codex_config(wrong_boolean)

        non_finite = CodexConfig(default_timeout_seconds=float("nan"))
        with self.assertRaisesRegex(PersistedConfigError, "finite JSON number"):
            serialize_codex_config(non_finite)

    def test_expected_hash_must_be_a_canonical_sha256_digest(self) -> None:
        payload = serialize_codex_config(CodexConfig())

        for digest in ("", "ABC", "A" * 64, "g" * 64):
            with self.subTest(digest=digest):
                with self.assertRaisesRegex(
                    PersistedConfigError,
                    "lowercase SHA-256",
                ):
                    decode_codex_config(payload, expected_sha256=digest)


class GenericPersistedSettingsCodecTests(unittest.TestCase):
    def test_generic_helper_round_trips_complete_settings(self) -> None:
        settings = _ExampleSettings(
            count=3,
            enabled=False,
            labels=("你好", "beta"),
            mode="fast",
            note="saved",
        )
        payload = serialize_persisted_dataclass(settings)
        digest = persisted_dataclass_sha256(settings)

        restored = decode_persisted_dataclass(
            _ExampleSettings,
            json.loads(json.dumps(payload, ensure_ascii=False)),
            expected_sha256=digest,
        )

        self.assertEqual(payload["labels"], ["你好", "beta"])
        self.assertEqual(digest, _payload_sha256(payload))
        self.assertEqual(restored, settings)
        self.assertIsInstance(restored.labels, tuple)

    def test_generic_helper_requires_defaulted_fields_to_be_persisted(self) -> None:
        settings = _ExampleSettings()
        payload = serialize_persisted_dataclass(settings)
        del payload["note"]

        with self.assertRaisesRegex(PersistedConfigError, "missing fields: note"):
            decode_persisted_dataclass(
                _ExampleSettings,
                payload,
                expected_sha256=_payload_sha256(payload),
            )

    def test_generic_helper_runs_dataclass_validation(self) -> None:
        payload = serialize_persisted_dataclass(_ExampleSettings())
        payload["count"] = 0

        with self.assertRaisesRegex(
            PersistedConfigError,
            "rejected persisted values: count must be positive",
        ):
            decode_persisted_dataclass(
                _ExampleSettings,
                payload,
                expected_sha256=_payload_sha256(payload),
            )

    def test_generic_helper_rejects_non_dataclass_types_and_values(self) -> None:
        with self.assertRaisesRegex(TypeError, "value must be a dataclass"):
            serialize_persisted_dataclass({"count": 1})
        with self.assertRaisesRegex(TypeError, "type must be a dataclass"):
            decode_persisted_dataclass(
                dict,
                {"count": 1},
                expected_sha256="0" * 64,
            )


if __name__ == "__main__":
    unittest.main()
