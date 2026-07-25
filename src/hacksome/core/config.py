"""Configuration for the concrete local Codex runtime."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import types
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import (
    Any,
    Literal,
    TypeAlias,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)


SandboxMode = Literal["read-only", "workspace-write", "danger-full-access"]
ApprovalPolicy = Literal["untrusted", "on-failure", "on-request", "never"]
ReasoningEffort = Literal["low", "medium", "high", "xhigh", "max", "ultra"]
JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
_T = TypeVar("_T")


class PersistedConfigError(ValueError):
    """Persisted configuration is incomplete, malformed, or has changed."""


@dataclass(frozen=True, slots=True)
class CodexConfig:
    """Runtime defaults shared by all Codex tasks.

    The defaults deliberately describe the v0.1 local execution boundary. They
    keep Codex inside the task workspace, prevent interactive approval prompts,
    and suppress ambient configuration that could make two stage sessions see
    different tools or instructions.
    """

    executable: str = "codex"
    max_concurrency: int = 4
    default_timeout_seconds: float = 20 * 60
    infrastructure_retries: int = 1
    termination_grace_seconds: float = 5.0
    doctor_timeout_seconds: float = 10.0
    subprocess_stream_limit_bytes: int = 1024 * 1024
    sandbox: SandboxMode = "read-only"
    approval_policy: ApprovalPolicy = "never"
    model: str | None = "gpt-5.6-terra"
    reasoning_effort: ReasoningEffort = "high"
    ignore_user_config: bool = True
    ignore_rules: bool = True
    skip_git_repo_check: bool = True
    strict_config: bool = True
    disabled_features: tuple[str, ...] = (
        "hooks",
        "apps",
        "goals",
        "multi_agent",
        "multi_agent_v2",
        "enable_fanout",
        "enable_mcp_apps",
        "plugins",
        "plugin_sharing",
        "browser_use",
        "browser_use_external",
        "browser_use_full_cdp_access",
        "computer_use",
        "image_generation",
        "in_app_browser",
    )
    config_overrides: tuple[str, ...] = (
        "project_doc_max_bytes=0",
        "skills.include_instructions=false",
    )

    def __post_init__(self) -> None:
        if not isinstance(self.executable, str) or not self.executable.strip():
            raise ValueError("Codex executable must not be empty")
        if (
            isinstance(self.max_concurrency, bool)
            or not isinstance(self.max_concurrency, int)
            or self.max_concurrency < 1
        ):
            raise ValueError("max_concurrency must be at least 1")
        if (
            isinstance(self.default_timeout_seconds, bool)
            or not isinstance(self.default_timeout_seconds, (int, float))
            or self.default_timeout_seconds <= 0
        ):
            raise ValueError("default_timeout_seconds must be positive")
        if (
            isinstance(self.infrastructure_retries, bool)
            or not isinstance(self.infrastructure_retries, int)
            or self.infrastructure_retries < 0
        ):
            raise ValueError("infrastructure_retries must be a non-negative integer")
        if (
            isinstance(self.termination_grace_seconds, bool)
            or not isinstance(self.termination_grace_seconds, (int, float))
            or self.termination_grace_seconds < 0
        ):
            raise ValueError("termination_grace_seconds must not be negative")
        if (
            isinstance(self.doctor_timeout_seconds, bool)
            or not isinstance(self.doctor_timeout_seconds, (int, float))
            or self.doctor_timeout_seconds <= 0
        ):
            raise ValueError("doctor_timeout_seconds must be positive")
        if (
            isinstance(self.subprocess_stream_limit_bytes, bool)
            or not isinstance(self.subprocess_stream_limit_bytes, int)
            or self.subprocess_stream_limit_bytes < 64 * 1024
        ):
            raise ValueError(
                "subprocess_stream_limit_bytes must be at least 65536 bytes"
            )
        if self.sandbox not in {"read-only", "workspace-write", "danger-full-access"}:
            raise ValueError(f"unsupported sandbox mode: {self.sandbox!r}")
        if self.approval_policy not in {
            "untrusted",
            "on-failure",
            "on-request",
            "never",
        }:
            raise ValueError(
                f"unsupported approval policy: {self.approval_policy!r}"
            )
        if self.model is not None and (
            not isinstance(self.model, str) or not self.model.strip()
        ):
            raise ValueError("model must be omitted or non-empty")
        if self.reasoning_effort not in {
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
            "ultra",
        }:
            raise ValueError(f"unsupported reasoning effort: {self.reasoning_effort!r}")
        for name, values in (
            ("disabled_features", self.disabled_features),
            ("config_overrides", self.config_overrides),
        ):
            if not isinstance(values, tuple) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ValueError(f"{name} must be a tuple of non-empty strings")


def _field_contract(
    dataclass_type: type[Any],
) -> tuple[tuple[str, Any], ...]:
    if not isinstance(dataclass_type, type) or not is_dataclass(dataclass_type):
        raise TypeError("persisted settings type must be a dataclass")
    try:
        annotations = get_type_hints(dataclass_type)
    except (NameError, TypeError) as exc:
        raise PersistedConfigError(
            f"cannot resolve {dataclass_type.__name__} field types: {exc}"
        ) from exc
    contract: list[tuple[str, Any]] = []
    for field in fields(dataclass_type):
        if not field.init:
            continue
        try:
            annotation = annotations[field.name]
        except KeyError as exc:
            raise PersistedConfigError(
                f"{dataclass_type.__name__}.{field.name} has no resolvable type"
            ) from exc
        contract.append((field.name, annotation))
    return tuple(contract)


def _validate_payload_fields(
    contract: tuple[tuple[str, Any], ...],
    payload: Mapping[str, object],
    *,
    context: str,
) -> None:
    expected_fields = {name for name, _ in contract}
    actual_fields = set(payload)
    missing = sorted(expected_fields - actual_fields)
    unknown = sorted(actual_fields - expected_fields)
    if not missing and not unknown:
        return

    problems: list[str] = []
    if missing:
        problems.append("missing fields: " + ", ".join(missing))
    if unknown:
        problems.append("unknown fields: " + ", ".join(unknown))
    raise PersistedConfigError(
        f"{context} persisted field mismatch ({'; '.join(problems)})"
    )


def _json_number(value: object, *, context: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PersistedConfigError(f"{context} must be a JSON number")
    if isinstance(value, float) and not math.isfinite(value):
        raise PersistedConfigError(f"{context} must be a finite JSON number")
    return value


def _encode_typed(value: object, annotation: Any, *, context: str) -> JsonValue:
    if annotation is Any:
        return _encode_untyped(value, context=context)
    if annotation is None or annotation is types.NoneType:
        if value is not None:
            raise PersistedConfigError(f"{context} must be null")
        return None
    if annotation is bool:
        if type(value) is not bool:
            raise PersistedConfigError(f"{context} must be a boolean")
        return cast(bool, value)
    if annotation is int:
        if type(value) is not int:
            raise PersistedConfigError(f"{context} must be an integer")
        return cast(int, value)
    if annotation is float:
        return _json_number(value, context=context)
    if annotation is str:
        if not isinstance(value, str):
            raise PersistedConfigError(f"{context} must be a string")
        return value

    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is Literal:
        if not any(type(value) is type(option) and value == option for option in arguments):
            choices = ", ".join(repr(option) for option in arguments)
            raise PersistedConfigError(f"{context} must be one of: {choices}")
        return _encode_untyped(value, context=context)
    if origin in {Union, types.UnionType}:
        return _encode_union(value, arguments, context=context)
    if origin is tuple:
        if not isinstance(value, tuple):
            raise PersistedConfigError(f"{context} must be a tuple before persistence")
        item_types = _tuple_item_types(arguments, len(value), context=context)
        return [
            _encode_typed(item, item_type, context=f"{context}[{index}]")
            for index, (item, item_type) in enumerate(zip(value, item_types))
        ]
    if origin is list:
        if not isinstance(value, list):
            raise PersistedConfigError(f"{context} must be a list")
        item_type = arguments[0] if arguments else Any
        return [
            _encode_typed(item, item_type, context=f"{context}[{index}]")
            for index, item in enumerate(value)
        ]
    if origin in {dict, Mapping}:
        if not isinstance(value, Mapping):
            raise PersistedConfigError(f"{context} must be an object")
        key_type, item_type = arguments if len(arguments) == 2 else (str, Any)
        if key_type is not str:
            raise PersistedConfigError(
                f"{context} uses unsupported non-string mapping keys"
            )
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PersistedConfigError(f"{context} keys must be strings")
            result[key] = _encode_typed(
                item,
                item_type,
                context=f"{context}.{key}",
            )
        return result
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        if not isinstance(value, annotation):
            raise PersistedConfigError(
                f"{context} must be a {annotation.__name__} value"
            )
        return _encode_untyped(value.value, context=context)
    if isinstance(annotation, type) and is_dataclass(annotation):
        if type(value) is not annotation:
            raise PersistedConfigError(
                f"{context} must be a {annotation.__name__} instance"
            )
        return _serialize_dataclass(value, context=context)
    raise PersistedConfigError(
        f"{context} uses unsupported persisted type {annotation!r}"
    )


def _encode_union(
    value: object,
    arguments: tuple[Any, ...],
    *,
    context: str,
) -> JsonValue:
    errors: list[str] = []
    for option in arguments:
        try:
            return _encode_typed(value, option, context=context)
        except PersistedConfigError as exc:
            errors.append(str(exc))
    raise PersistedConfigError(
        f"{context} does not match any allowed type: {'; '.join(errors)}"
    )


def _encode_untyped(value: object, *, context: str) -> JsonValue:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)):
        return _json_number(value, context=context)
    if isinstance(value, list):
        return [
            _encode_untyped(item, context=f"{context}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PersistedConfigError(f"{context} keys must be strings")
            result[key] = _encode_untyped(item, context=f"{context}.{key}")
        return result
    raise PersistedConfigError(f"{context} is not JSON-safe")


def _tuple_item_types(
    arguments: tuple[Any, ...],
    length: int,
    *,
    context: str,
) -> tuple[Any, ...]:
    if not arguments:
        return (Any,) * length
    if len(arguments) == 2 and arguments[1] is Ellipsis:
        return (arguments[0],) * length
    if len(arguments) != length:
        raise PersistedConfigError(
            f"{context} must contain exactly {len(arguments)} items"
        )
    return arguments


def _serialize_dataclass(value: object, *, context: str) -> dict[str, JsonValue]:
    dataclass_type = type(value)
    result: dict[str, JsonValue] = {}
    for name, annotation in _field_contract(dataclass_type):
        result[name] = _encode_typed(
            getattr(value, name),
            annotation,
            context=f"{context}.{name}",
        )
    return result


def _strict_json_value(value: object, *, context: str) -> JsonValue:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)):
        return _json_number(value, context=context)
    if isinstance(value, list):
        return [
            _strict_json_value(item, context=f"{context}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PersistedConfigError(f"{context} keys must be strings")
            result[key] = _strict_json_value(item, context=f"{context}.{key}")
        return result
    raise PersistedConfigError(f"{context} is not valid JSON data")


def _canonical_json_bytes(value: JsonValue) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def serialize_persisted_dataclass(value: object) -> dict[str, JsonValue]:
    """Return the complete JSON-safe persisted form of a settings dataclass."""

    if isinstance(value, type) or not is_dataclass(value):
        raise TypeError("persisted settings value must be a dataclass instance")
    payload = _serialize_dataclass(value, context=type(value).__name__)
    canonical = json.loads(_canonical_json_bytes(payload))
    if not isinstance(canonical, dict):  # pragma: no cover - guaranteed above.
        raise AssertionError("serialized dataclass must be an object")
    return cast(dict[str, JsonValue], canonical)


def persisted_dataclass_sha256(value: object) -> str:
    """Hash a settings dataclass using its canonical persisted JSON bytes."""

    payload = serialize_persisted_dataclass(value)
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _validate_expected_sha256(expected_sha256: str) -> None:
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise PersistedConfigError(
            "expected_sha256 must be a lowercase SHA-256 hexadecimal digest"
        )


def _decode_typed_json(value: JsonValue, annotation: Any, *, context: str) -> object:
    if annotation is Any:
        return value
    if annotation is None or annotation is types.NoneType:
        if value is not None:
            raise PersistedConfigError(f"{context} must be null")
        return None
    if annotation is bool:
        if type(value) is not bool:
            raise PersistedConfigError(f"{context} must be a boolean")
        return value
    if annotation is int:
        if type(value) is not int:
            raise PersistedConfigError(f"{context} must be an integer")
        return value
    if annotation is float:
        return _json_number(value, context=context)
    if annotation is str:
        if not isinstance(value, str):
            raise PersistedConfigError(f"{context} must be a string")
        return value

    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is Literal:
        if not any(type(value) is type(option) and value == option for option in arguments):
            choices = ", ".join(repr(option) for option in arguments)
            raise PersistedConfigError(f"{context} must be one of: {choices}")
        return value
    if origin in {Union, types.UnionType}:
        errors: list[str] = []
        for option in arguments:
            try:
                return _decode_typed_json(value, option, context=context)
            except PersistedConfigError as exc:
                errors.append(str(exc))
        raise PersistedConfigError(
            f"{context} does not match any allowed type: {'; '.join(errors)}"
        )
    if origin is tuple:
        if not isinstance(value, list):
            raise PersistedConfigError(
                f"{context} must be a JSON array for a tuple field"
            )
        item_types = _tuple_item_types(arguments, len(value), context=context)
        return tuple(
            _decode_typed_json(item, item_type, context=f"{context}[{index}]")
            for index, (item, item_type) in enumerate(zip(value, item_types))
        )
    if origin is list:
        if not isinstance(value, list):
            raise PersistedConfigError(f"{context} must be an array")
        item_type = arguments[0] if arguments else Any
        return [
            _decode_typed_json(item, item_type, context=f"{context}[{index}]")
            for index, item in enumerate(value)
        ]
    if origin in {dict, Mapping}:
        if not isinstance(value, dict):
            raise PersistedConfigError(f"{context} must be an object")
        key_type, item_type = arguments if len(arguments) == 2 else (str, Any)
        if key_type is not str:
            raise PersistedConfigError(
                f"{context} uses unsupported non-string mapping keys"
            )
        return {
            key: _decode_typed_json(
                item,
                item_type,
                context=f"{context}.{key}",
            )
            for key, item in value.items()
        }
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        for member in annotation:
            if type(value) is type(member.value) and value == member.value:
                return member
        raise PersistedConfigError(
            f"{context} is not a valid {annotation.__name__} value"
        )
    if isinstance(annotation, type) and is_dataclass(annotation):
        if not isinstance(value, dict):
            raise PersistedConfigError(f"{context} must be an object")
        return _decode_dataclass(annotation, value, context=context)
    raise PersistedConfigError(
        f"{context} uses unsupported persisted type {annotation!r}"
    )


def _decode_dataclass(
    dataclass_type: type[_T],
    payload: Mapping[str, JsonValue],
    *,
    context: str,
) -> _T:
    contract = _field_contract(dataclass_type)
    _validate_payload_fields(contract, payload, context=context)

    decoded = {
        name: _decode_typed_json(
            payload[name],
            annotation,
            context=f"{context}.{name}",
        )
        for name, annotation in contract
    }
    try:
        return dataclass_type(**decoded)
    except (TypeError, ValueError) as exc:
        raise PersistedConfigError(f"{context} rejected persisted values: {exc}") from exc


def decode_persisted_dataclass(
    dataclass_type: type[_T],
    payload: Mapping[str, object],
    *,
    expected_sha256: str,
) -> _T:
    """Strictly restore a settings dataclass from hash-bound JSON data."""

    if not isinstance(dataclass_type, type) or not is_dataclass(dataclass_type):
        raise TypeError("persisted settings type must be a dataclass")
    if not isinstance(payload, Mapping):
        raise PersistedConfigError("persisted settings must be a JSON object")
    normalized = _strict_json_value(payload, context=dataclass_type.__name__)
    if not isinstance(normalized, dict):  # pragma: no cover - Mapping guarantees this.
        raise AssertionError("persisted settings must normalize to an object")

    contract = _field_contract(dataclass_type)
    _validate_payload_fields(
        contract,
        normalized,
        context=dataclass_type.__name__,
    )

    _validate_expected_sha256(expected_sha256)
    actual_sha256 = hashlib.sha256(_canonical_json_bytes(normalized)).hexdigest()
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise PersistedConfigError(
            f"{dataclass_type.__name__} hash mismatch: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )
    return _decode_dataclass(
        dataclass_type,
        normalized,
        context=dataclass_type.__name__,
    )


def serialize_codex_config(config: CodexConfig) -> dict[str, JsonValue]:
    """Return the canonical JSON-safe persisted Codex configuration."""

    if not isinstance(config, CodexConfig):
        raise TypeError("config must be a CodexConfig")
    return serialize_persisted_dataclass(config)


def codex_config_sha256(config: CodexConfig) -> str:
    """Return the canonical persisted SHA-256 for a Codex configuration."""

    if not isinstance(config, CodexConfig):
        raise TypeError("config must be a CodexConfig")
    return persisted_dataclass_sha256(config)


def decode_codex_config(
    payload: Mapping[str, object],
    *,
    expected_sha256: str,
) -> CodexConfig:
    """Restore a complete, hash-bound Codex configuration."""

    return decode_persisted_dataclass(
        CodexConfig,
        payload,
        expected_sha256=expected_sha256,
    )


__all__ = [
    "ApprovalPolicy",
    "CodexConfig",
    "JsonScalar",
    "JsonValue",
    "PersistedConfigError",
    "ReasoningEffort",
    "SandboxMode",
    "codex_config_sha256",
    "decode_codex_config",
    "decode_persisted_dataclass",
    "persisted_dataclass_sha256",
    "serialize_codex_config",
    "serialize_persisted_dataclass",
]
