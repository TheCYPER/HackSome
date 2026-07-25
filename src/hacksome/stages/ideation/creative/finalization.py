"""Deterministic two-phase publication for Creative C7 outputs.

The report renderer owns output bytes.  This coordinator owns the durable
boundary around those bytes: one immutable source projection, exact planned
artifact records/events, staging, manifest binding, ordered publication, and
the final result exposure transition.  Replay never invokes the renderer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, Sequence

from hacksome.core.hub import RunHub, utc_now
from hacksome.core.state import (
    StateError,
    atomic_write_bytes,
    canonical_json_bytes,
    normalize_json,
    sha256_bytes,
    sha256_file,
    sha256_json,
)


FINALIZATION_STAGE = "creative-finalization"
FINALIZATION_ID = "creative-finalization-001"
FINALIZATION_SCHEMA_VERSION = 1
FINALIZATION_MANIFEST_PATH = (
    "state/creative-finalization/finalization-manifest.json"
)
FINALIZATION_STAGING_ROOT = "state/creative-finalization/staged"

_LEDGER_ID_FIELDS: Mapping[str, str] = MappingProxyType(
    {
        "events": "event_id",
        "decisions": "decision_id",
        "human_reviews": "review_id",
        "human_resolutions": "resolution_id",
    }
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FINALIZATION_ID = re.compile(r"^creative-finalization-[0-9]{3}$")


class FinalizationError(RuntimeError):
    """A frozen C7 plan cannot be created or replayed safely."""


class FinalizationValidationError(FinalizationError):
    """A supplied or persisted finalization value violates its contract."""


class FinalizationConflictError(FinalizationError):
    """Persisted state no longer matches the immutable finalization plan."""


class RenderedOutput(Protocol):
    """Minimal structural shape shared with ``creative.report`` outputs."""

    @property
    def artifact_id(self) -> str: ...

    @property
    def artifact_type(self) -> str: ...

    @property
    def relative_path(self) -> str: ...

    @property
    def content(self) -> bytes: ...

class FinalizationRenderer(Protocol):
    """Render all C7 outputs from one immutable Hub snapshot."""

    def __call__(
        self,
        source: FinalizationSourceManifest,
        snapshot: Mapping[str, Any],
    ) -> Sequence[RenderedOutput]: ...


@dataclass(frozen=True, slots=True)
class RenderedArtifact:
    """Small concrete :class:`RenderedOutput` adapter for report code/tests."""

    artifact_id: str
    artifact_type: str
    final_path: str
    content: bytes
    task_id: str | None = None
    source_refs: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    is_result: bool = True

    def __post_init__(self) -> None:
        _require_safe_id(self.artifact_id, "artifact_id")
        _require_nonempty(self.artifact_type, "artifact_type")
        _require_artifact_path(self.final_path, "final_path")
        if not isinstance(self.content, bytes):
            raise FinalizationValidationError("rendered content must be bytes")
        if self.task_id is not None:
            _require_safe_id(self.task_id, "task_id")
        refs = _string_tuple(self.source_refs, "source_refs")
        metadata = _normalized_object(self.metadata, "metadata")
        if type(self.is_result) is not bool:
            raise FinalizationValidationError("is_result must be a boolean")
        object.__setattr__(self, "source_refs", refs)
        object.__setattr__(self, "metadata", MappingProxyType(metadata))

    @property
    def relative_path(self) -> str:
        """Match the pure renderer DTO without weakening planned naming."""

        return self.final_path


@dataclass(frozen=True, slots=True)
class LedgerHead:
    """Exact immutable prefix identity for one append-only Hub ledger."""

    ledger: str
    record_count: int
    records_sha256: str
    last_record_id: str | None
    last_record_sha256: str | None

    def __post_init__(self) -> None:
        if self.ledger not in _LEDGER_ID_FIELDS:
            raise FinalizationValidationError(
                f"unsupported source ledger: {self.ledger!r}"
            )
        if (
            type(self.record_count) is not int
            or self.record_count < 0
        ):
            raise FinalizationValidationError(
                "ledger record_count must be a non-negative integer"
            )
        _require_sha256(self.records_sha256, "records_sha256")
        if self.record_count == 0:
            if (
                self.last_record_id is not None
                or self.last_record_sha256 is not None
            ):
                raise FinalizationValidationError(
                    "empty ledger head cannot have a last record"
                )
        else:
            _require_nonempty(self.last_record_id, "last_record_id")
            _require_sha256(
                self.last_record_sha256,
                "last_record_sha256",
            )

    @classmethod
    def freeze(
        cls,
        ledger: str,
        records: Sequence[Mapping[str, Any]],
    ) -> LedgerHead:
        id_field = _LEDGER_ID_FIELDS.get(ledger)
        if id_field is None:
            raise FinalizationValidationError(
                f"unsupported source ledger: {ledger!r}"
            )
        normalized = [
            _normalized_object(record, f"{ledger} record")
            for record in records
        ]
        last = normalized[-1] if normalized else None
        last_id = last.get(id_field) if last is not None else None
        if last is not None and (
            not isinstance(last_id, str) or not last_id
        ):
            raise FinalizationValidationError(
                f"{ledger} last record has no valid {id_field}"
            )
        return cls(
            ledger=ledger,
            record_count=len(normalized),
            records_sha256=sha256_json(normalized),
            last_record_id=last_id,
            last_record_sha256=(
                sha256_json(last) if last is not None else None
            ),
        )

    def matches(self, records: Sequence[Mapping[str, Any]]) -> bool:
        try:
            return self == LedgerHead.freeze(self.ledger, records)
        except FinalizationValidationError:
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ledger": self.ledger,
            "record_count": self.record_count,
            "records_sha256": self.records_sha256,
            "last_record_id": self.last_record_id,
            "last_record_sha256": self.last_record_sha256,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> LedgerHead:
        value = _exact_object(
            raw,
            {
                "ledger",
                "record_count",
                "records_sha256",
                "last_record_id",
                "last_record_sha256",
            },
            "ledger head",
        )
        return cls(
            ledger=_require_nonempty(value["ledger"], "ledger"),
            record_count=_require_integer(
                value["record_count"],
                "record_count",
                minimum=0,
            ),
            records_sha256=_require_nonempty(
                value["records_sha256"],
                "records_sha256",
            ),
            last_record_id=_optional_string(
                value["last_record_id"],
                "last_record_id",
            ),
            last_record_sha256=_optional_string(
                value["last_record_sha256"],
                "last_record_sha256",
            ),
        )


@dataclass(frozen=True, slots=True)
class SourceFileBinding:
    """One source file whose bytes are covered by the C7 projection."""

    path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        _require_run_path(self.path, "source file path")
        _require_sha256(self.sha256, "source file sha256")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise FinalizationValidationError(
                "source file size_bytes must be a non-negative integer"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> SourceFileBinding:
        value = _exact_object(
            raw,
            {"path", "sha256", "size_bytes"},
            "source file binding",
        )
        return cls(
            path=_require_nonempty(value["path"], "path"),
            sha256=_require_nonempty(value["sha256"], "sha256"),
            size_bytes=_require_integer(
                value["size_bytes"],
                "size_bytes",
                minimum=0,
            ),
        )


@dataclass(frozen=True, slots=True)
class FinalizationSourceManifest:
    """Canonical identity of the complete pre-publication C7 source."""

    schema_version: int
    run_id: str
    route_contract_version: str
    report_policy_version: str
    state_projection_sha256: str
    source_files: tuple[SourceFileBinding, ...]
    ledger_heads: tuple[LedgerHead, ...]
    transition_seq: int

    def __post_init__(self) -> None:
        if self.schema_version != FINALIZATION_SCHEMA_VERSION:
            raise FinalizationValidationError(
                "unsupported finalization source schema_version"
            )
        _require_safe_id(self.run_id, "run_id")
        _require_nonempty(
            self.route_contract_version,
            "route_contract_version",
        )
        _require_nonempty(
            self.report_policy_version,
            "report_policy_version",
        )
        _require_sha256(
            self.state_projection_sha256,
            "state_projection_sha256",
        )
        if tuple(sorted(self.source_files, key=lambda item: item.path)) != (
            self.source_files
        ):
            raise FinalizationValidationError(
                "source file bindings must be sorted by path"
            )
        if len({item.path for item in self.source_files}) != len(
            self.source_files
        ):
            raise FinalizationValidationError(
                "source file bindings must have unique paths"
            )
        if (
            type(self.transition_seq) is not int
            or self.transition_seq < 0
        ):
            raise FinalizationValidationError(
                "transition_seq must be a non-negative integer"
            )
        expected = tuple(sorted(_LEDGER_ID_FIELDS))
        actual = tuple(head.ledger for head in self.ledger_heads)
        if actual != expected:
            raise FinalizationValidationError(
                "source manifest requires the four sorted Hub ledger heads"
            )

    @property
    def source_projection_sha256(self) -> str:
        """Hash of the entire typed source manifest."""

        return sha256_json(self.to_dict())

    @classmethod
    def freeze(
        cls,
        snapshot: Mapping[str, Any],
        *,
        run_dir: Path,
    ) -> FinalizationSourceManifest:
        value = _exact_object(snapshot, {"state", "ledgers"}, "Hub snapshot")
        state = _normalized_object(value["state"], "run state")
        ledgers = _exact_object(
            _mapping(value["ledgers"], "snapshot ledgers"),
            set(_LEDGER_ID_FIELDS),
            "snapshot ledgers",
        )
        route = _mapping(state.get("route"), "route")
        if route.get("id") != "creative":
            raise FinalizationValidationError(
                "C7 finalization requires a Creative run"
            )
        if (
            state.get("status") != "running"
            or state.get("current_stage") != FINALIZATION_STAGE
        ):
            raise FinalizationValidationError(
                "source run must be running at creative-finalization"
            )
        if state.get("terminal_error") is not None:
            raise FinalizationValidationError(
                "a failed run cannot freeze successful C7 outputs"
            )
        if state.get("finalization") is not None:
            raise FinalizationValidationError(
                "source state is already bound to a finalization"
            )
        if state.get("result_artifact_ids") != []:
            raise FinalizationValidationError(
                "pre-finalization result_artifact_ids must be empty"
            )
        if state.get("pending_records") != []:
            raise FinalizationValidationError(
                "source snapshot contains unreconciled ledger records"
            )
        transition_seq = _require_integer(
            state.get("transition_seq"),
            "transition_seq",
            minimum=0,
        )
        contract_version = _require_nonempty(
            route.get("contract_version"),
            "route contract_version",
        )
        report_policy_version = _require_nonempty(
            route.get("report_policy_version"),
            "route report_policy_version",
        )
        heads = tuple(
            LedgerHead.freeze(
                ledger,
                _record_sequence(ledgers[ledger], ledger),
            )
            for ledger in sorted(_LEDGER_ID_FIELDS)
        )
        return cls(
            schema_version=FINALIZATION_SCHEMA_VERSION,
            run_id=_require_nonempty(state.get("run_id"), "run_id"),
            route_contract_version=contract_version,
            report_policy_version=report_policy_version,
            state_projection_sha256=sha256_json(
                _source_state_projection(state)
            ),
            source_files=_source_file_bindings(run_dir, state),
            ledger_heads=heads,
            transition_seq=transition_seq,
        )

    def head(self, ledger: str) -> LedgerHead:
        for head in self.ledger_heads:
            if head.ledger == ledger:
                return head
        raise FinalizationValidationError(
            f"source manifest has no {ledger!r} head"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "route_contract_version": self.route_contract_version,
            "report_policy_version": self.report_policy_version,
            "state_projection_sha256": self.state_projection_sha256,
            "source_files": [
                binding.to_dict() for binding in self.source_files
            ],
            "ledger_heads": [head.to_dict() for head in self.ledger_heads],
            "transition_seq": self.transition_seq,
        }

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, Any],
    ) -> FinalizationSourceManifest:
        value = _exact_object(
            raw,
            {
                "schema_version",
                "run_id",
                "route_contract_version",
                "report_policy_version",
                "state_projection_sha256",
                "source_files",
                "ledger_heads",
                "transition_seq",
            },
            "finalization source manifest",
        )
        heads = _sequence(value["ledger_heads"], "ledger_heads")
        source_files = _sequence(value["source_files"], "source_files")
        return cls(
            schema_version=_require_integer(
                value["schema_version"],
                "schema_version",
                minimum=1,
            ),
            run_id=_require_nonempty(value["run_id"], "run_id"),
            route_contract_version=_require_nonempty(
                value["route_contract_version"],
                "route_contract_version",
            ),
            report_policy_version=_require_nonempty(
                value["report_policy_version"],
                "report_policy_version",
            ),
            state_projection_sha256=_require_nonempty(
                value["state_projection_sha256"],
                "state_projection_sha256",
            ),
            source_files=tuple(
                SourceFileBinding.from_dict(
                    _mapping(item, "source file binding")
                )
                for item in source_files
            ),
            ledger_heads=tuple(
                LedgerHead.from_dict(_mapping(item, "ledger head"))
                for item in heads
            ),
            transition_seq=_require_integer(
                value["transition_seq"],
                "transition_seq",
                minimum=0,
            ),
        )


@dataclass(frozen=True, slots=True)
class PlannedArtifact:
    """One exact artifact record, event, byte payload, and publish position."""

    publish_order: int
    artifact_id: str
    artifact_type: str
    staged_path: str
    final_path: str
    sha256: str
    size_bytes: int
    publish_event_id: str
    created_at: str
    task_id: str | None
    source_refs: tuple[str, ...]
    metadata: Mapping[str, Any]
    is_result: bool

    def __post_init__(self) -> None:
        if type(self.publish_order) is not int or self.publish_order < 1:
            raise FinalizationValidationError(
                "publish_order must be a positive integer"
            )
        _require_safe_id(self.artifact_id, "artifact_id")
        _require_nonempty(self.artifact_type, "artifact_type")
        _require_run_path(self.staged_path, "staged_path")
        _require_artifact_path(self.final_path, "final_path")
        expected_staged = _staged_path(
            self.publish_order,
            self.artifact_id,
        )
        if self.staged_path != expected_staged:
            raise FinalizationValidationError(
                "staged_path does not match publish_order/artifact_id"
            )
        _require_sha256(self.sha256, "sha256")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise FinalizationValidationError(
                "size_bytes must be a non-negative integer"
            )
        if self.publish_event_id != (
            f"artifact:{self.artifact_id}:published"
        ):
            raise FinalizationValidationError(
                "publish_event_id does not match artifact_id"
            )
        _require_nonempty(self.created_at, "created_at")
        if self.task_id is not None:
            _require_safe_id(self.task_id, "task_id")
        refs = _string_tuple(self.source_refs, "source_refs")
        metadata = _normalized_object(self.metadata, "metadata")
        if type(self.is_result) is not bool:
            raise FinalizationValidationError("is_result must be a boolean")
        object.__setattr__(self, "source_refs", refs)
        object.__setattr__(self, "metadata", MappingProxyType(metadata))

    @property
    def artifact_record(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "path": self.final_path,
            "sha256": self.sha256,
            "task_id": self.task_id,
            "source_refs": list(self.source_refs),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }

    @property
    def publish_event(self) -> dict[str, Any]:
        return {
            "event_id": self.publish_event_id,
            "kind": "artifact.published",
            "data": {
                "artifact_id": self.artifact_id,
                "artifact_type": self.artifact_type,
            },
            "created_at": self.created_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "publish_order": self.publish_order,
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "staged_path": self.staged_path,
            "final_path": self.final_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "publish_event_id": self.publish_event_id,
            "created_at": self.created_at,
            "task_id": self.task_id,
            "source_refs": list(self.source_refs),
            "metadata": dict(self.metadata),
            "is_result": self.is_result,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PlannedArtifact:
        value = _exact_object(
            raw,
            {
                "publish_order",
                "artifact_id",
                "artifact_type",
                "staged_path",
                "final_path",
                "sha256",
                "size_bytes",
                "publish_event_id",
                "created_at",
                "task_id",
                "source_refs",
                "metadata",
                "is_result",
            },
            "planned artifact",
        )
        is_result = value["is_result"]
        if type(is_result) is not bool:
            raise FinalizationValidationError(
                "planned artifact is_result must be a boolean"
            )
        return cls(
            publish_order=_require_integer(
                value["publish_order"],
                "publish_order",
                minimum=1,
            ),
            artifact_id=_require_nonempty(
                value["artifact_id"],
                "artifact_id",
            ),
            artifact_type=_require_nonempty(
                value["artifact_type"],
                "artifact_type",
            ),
            staged_path=_require_nonempty(
                value["staged_path"],
                "staged_path",
            ),
            final_path=_require_nonempty(
                value["final_path"],
                "final_path",
            ),
            sha256=_require_nonempty(value["sha256"], "sha256"),
            size_bytes=_require_integer(
                value["size_bytes"],
                "size_bytes",
                minimum=0,
            ),
            publish_event_id=_require_nonempty(
                value["publish_event_id"],
                "publish_event_id",
            ),
            created_at=_require_nonempty(
                value["created_at"],
                "created_at",
            ),
            task_id=_optional_string(value["task_id"], "task_id"),
            source_refs=_string_tuple(
                _sequence(value["source_refs"], "source_refs"),
                "source_refs",
            ),
            metadata=_normalized_object(value["metadata"], "metadata"),
            is_result=is_result,
        )


@dataclass(frozen=True, slots=True)
class PlannedCompletion:
    """The exact final run transition chosen before publication starts."""

    event_id: str
    transition_seq: int
    at: str

    def __post_init__(self) -> None:
        if type(self.transition_seq) is not int or self.transition_seq < 1:
            raise FinalizationValidationError(
                "completion transition_seq must be positive"
            )
        if self.event_id != (
            f"run:transition:{self.transition_seq:08d}"
        ):
            raise FinalizationValidationError(
                "completion event_id does not match transition_seq"
            )
        _require_nonempty(self.at, "completion at")

    @property
    def event(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": "run.status",
            "data": {
                "from_status": "running",
                "to_status": "completed",
                "status": "completed",
                "stage": FINALIZATION_STAGE,
                "reason": "C7 frozen finalization published",
            },
            "created_at": self.at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "transition_seq": self.transition_seq,
            "at": self.at,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PlannedCompletion:
        value = _exact_object(
            raw,
            {"event_id", "transition_seq", "at"},
            "planned completion",
        )
        return cls(
            event_id=_require_nonempty(value["event_id"], "event_id"),
            transition_seq=_require_integer(
                value["transition_seq"],
                "transition_seq",
                minimum=1,
            ),
            at=_require_nonempty(value["at"], "at"),
        )


@dataclass(frozen=True, slots=True)
class FinalizationManifest:
    """Immutable C7 publish plan."""

    schema_version: int
    finalization_id: str
    source_projection_sha256: str
    report_policy_version: str
    source: FinalizationSourceManifest
    outputs: tuple[PlannedArtifact, ...]
    result_artifact_ids: tuple[str, ...]
    completed_transition: PlannedCompletion

    def __post_init__(self) -> None:
        if self.schema_version != FINALIZATION_SCHEMA_VERSION:
            raise FinalizationValidationError(
                "unsupported finalization manifest schema_version"
            )
        if not _FINALIZATION_ID.fullmatch(self.finalization_id):
            raise FinalizationValidationError(
                "invalid finalization_id"
            )
        _require_sha256(
            self.source_projection_sha256,
            "source_projection_sha256",
        )
        if (
            self.source_projection_sha256
            != self.source.source_projection_sha256
        ):
            raise FinalizationValidationError(
                "manifest source projection hash mismatch"
            )
        if self.report_policy_version != self.source.report_policy_version:
            raise FinalizationValidationError(
                "manifest report policy does not match its source"
            )
        expected_orders = tuple(range(1, len(self.outputs) + 1))
        if tuple(output.publish_order for output in self.outputs) != expected_orders:
            raise FinalizationValidationError(
                "planned outputs must use contiguous publish_order"
            )
        artifact_ids = tuple(output.artifact_id for output in self.outputs)
        final_paths = tuple(output.final_path for output in self.outputs)
        staged_paths = tuple(output.staged_path for output in self.outputs)
        if len(set(artifact_ids)) != len(artifact_ids):
            raise FinalizationValidationError(
                "planned output artifact IDs must be unique"
            )
        if len(set(final_paths)) != len(final_paths):
            raise FinalizationValidationError(
                "planned output final paths must be unique"
            )
        if len(set(staged_paths)) != len(staged_paths):
            raise FinalizationValidationError(
                "planned output staged paths must be unique"
            )
        expected_results = tuple(
            output.artifact_id
            for output in self.outputs
            if output.is_result
        )
        if self.result_artifact_ids != expected_results:
            raise FinalizationValidationError(
                "result_artifact_ids do not match planned result flags"
            )
        if (
            self.completed_transition.transition_seq
            != self.source.transition_seq + 1
        ):
            raise FinalizationValidationError(
                "completion transition is not the next source transition"
            )
        if any(
            output.created_at != self.completed_transition.at
            for output in self.outputs
        ):
            raise FinalizationValidationError(
                "all planned records/events must use the frozen completion time"
            )

    @property
    def manifest_sha256(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "finalization_id": self.finalization_id,
            "source_projection_sha256": self.source_projection_sha256,
            "report_policy_version": self.report_policy_version,
            "source": self.source.to_dict(),
            "outputs": [output.to_dict() for output in self.outputs],
            "result_artifact_ids": list(self.result_artifact_ids),
            "completed_transition": self.completed_transition.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> FinalizationManifest:
        value = _exact_object(
            raw,
            {
                "schema_version",
                "finalization_id",
                "source_projection_sha256",
                "report_policy_version",
                "source",
                "outputs",
                "result_artifact_ids",
                "completed_transition",
            },
            "finalization manifest",
        )
        outputs = _sequence(value["outputs"], "outputs")
        return cls(
            schema_version=_require_integer(
                value["schema_version"],
                "schema_version",
                minimum=1,
            ),
            finalization_id=_require_nonempty(
                value["finalization_id"],
                "finalization_id",
            ),
            source_projection_sha256=_require_nonempty(
                value["source_projection_sha256"],
                "source_projection_sha256",
            ),
            report_policy_version=_require_nonempty(
                value["report_policy_version"],
                "report_policy_version",
            ),
            source=FinalizationSourceManifest.from_dict(
                _mapping(value["source"], "source")
            ),
            outputs=tuple(
                PlannedArtifact.from_dict(
                    _mapping(item, "planned artifact")
                )
                for item in outputs
            ),
            result_artifact_ids=_string_tuple(
                _sequence(
                    value["result_artifact_ids"],
                    "result_artifact_ids",
                ),
                "result_artifact_ids",
            ),
            completed_transition=PlannedCompletion.from_dict(
                _mapping(
                    value["completed_transition"],
                    "completed_transition",
                )
            ),
        )


RenderInput = (
    Sequence[RenderedOutput]
    | FinalizationRenderer
    | Callable[
        [FinalizationSourceManifest, Mapping[str, Any]],
        Sequence[RenderedOutput],
    ]
)


class FinalizationCoordinator:
    """Freeze and replay one immutable Creative C7 publication."""

    def __init__(
        self,
        hub: RunHub,
        *,
        clock: Callable[[], str] = utc_now,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.hub = hub
        self.clock = clock
        self.fault_injector = fault_injector

    def finalize(self, rendered: RenderInput) -> FinalizationManifest:
        """Freeze output bytes, then publish the plan to completion."""

        manifest = self.freeze(rendered)
        self.replay()
        return manifest

    def freeze(self, rendered: RenderInput) -> FinalizationManifest:
        """Freeze bytes and bind an immutable manifest without publishing."""

        self.hub.reconcile_pending()
        existing = self._load_manifest_if_present(adopt_orphan=True)
        if existing is not None:
            self._verify_staged_and_existing(existing)
            self._validate_source_and_progress(
                existing,
                self.hub.load_consistent_snapshot(),
            )
            return existing

        state = self.hub.load_state()
        self._require_creative_run(state)
        if state.get("status") != "running":
            raise FinalizationValidationError(
                "C7 finalization can start only from a running run"
            )
        if state.get("finalization") is not None:
            raise FinalizationConflictError(
                "run points to a missing finalization manifest"
            )
        if state.get("result_artifact_ids") != []:
            raise FinalizationConflictError(
                "C7 cannot replace already exposed result artifacts"
            )
        if state.get("current_stage") != FINALIZATION_STAGE:
            self._fault("before_stage_transition")
            self.hub.set_run_status(
                "running",
                stage=FINALIZATION_STAGE,
                reason="freeze deterministic C7 publication",
            )
            self._fault("after_stage_transition")

        snapshot = self.hub.load_consistent_snapshot()
        source = FinalizationSourceManifest.freeze(
            snapshot,
            run_dir=self.hub.run_dir,
        )
        frozen_at = _require_nonempty(self.clock(), "frozen time")
        self._fault("before_render")
        outputs = self._render(rendered, source, snapshot)
        self._fault("after_render")
        planned = self._plan_outputs(
            source=source,
            outputs=outputs,
            frozen_at=frozen_at,
        )
        manifest = FinalizationManifest(
            schema_version=FINALIZATION_SCHEMA_VERSION,
            finalization_id=FINALIZATION_ID,
            source_projection_sha256=source.source_projection_sha256,
            report_policy_version=source.report_policy_version,
            source=source,
            outputs=planned,
            result_artifact_ids=tuple(
                output.artifact_id
                for output in planned
                if output.is_result
            ),
            completed_transition=PlannedCompletion(
                event_id=(
                    f"run:transition:{source.transition_seq + 1:08d}"
                ),
                transition_seq=source.transition_seq + 1,
                at=frozen_at,
            ),
        )

        self._require_no_output_collision(snapshot, manifest)
        for output, rendered_output in zip(
            manifest.outputs,
            outputs,
            strict=True,
        ):
            path = self._resolve(output.staged_path)
            if path.exists():
                _verify_file(
                    path,
                    expected_sha256=output.sha256,
                    expected_size=output.size_bytes,
                    label="staged output",
                )
            else:
                atomic_write_bytes(path, rendered_output.content)
            _verify_file(
                path,
                expected_sha256=output.sha256,
                expected_size=output.size_bytes,
                label="staged output",
            )
            self._fault(f"after_stage:{output.publish_order}")

        # Detect any concurrent source change before making the plan
        # discoverable.  A later race is still caught by replay before publish.
        self._validate_source_and_progress(
            manifest,
            self.hub.load_consistent_snapshot(),
        )
        manifest_path = self._resolve(FINALIZATION_MANIFEST_PATH)
        if manifest_path.exists():
            raise FinalizationConflictError(
                "a finalization manifest appeared during freeze"
            )
        self._fault("before_manifest")
        manifest_bytes = canonical_json_bytes(manifest.to_dict())
        atomic_write_bytes(manifest_path, manifest_bytes)
        _verify_file(
            manifest_path,
            expected_sha256=manifest.manifest_sha256,
            expected_size=len(manifest_bytes),
            label="finalization manifest",
        )
        self._fault("after_manifest")
        self.hub.bind_finalization_manifest(
            self._manifest_reference(manifest)
        )
        self._fault("after_bind")
        return manifest

    def replay(self) -> FinalizationManifest:
        """Publish only the exact bytes and events stored in a frozen plan."""

        self.hub.reconcile_pending()
        manifest = self._load_manifest_if_present(adopt_orphan=True)
        if manifest is None:
            raise FinalizationValidationError(
                "no complete finalization manifest is available for replay"
            )
        self._verify_staged_and_existing(manifest)
        self._validate_source_and_progress(
            manifest,
            self.hub.load_consistent_snapshot(),
        )

        for output in manifest.outputs:
            self._fault(f"before_publish:{output.publish_order}")
            content = self._resolve(output.staged_path).read_bytes()
            if (
                len(content) != output.size_bytes
                or sha256_bytes(content) != output.sha256
            ):
                raise FinalizationConflictError(
                    "staged C7 bytes changed before publication"
                )
            self.hub.publish_planned_artifact(
                artifact_record=output.artifact_record,
                publish_event=output.publish_event,
                content=content,
            )
            self._fault(f"after_publish:{output.publish_order}")

        self._verify_staged_and_existing(manifest)
        progress = self.hub.load_consistent_snapshot()
        self._validate_source_and_progress(manifest, progress)
        self._require_all_artifacts_published(manifest, progress)
        self._fault("before_completion")
        self.hub.commit_planned_completion(
            result_artifact_ids=manifest.result_artifact_ids,
            transition_event=manifest.completed_transition.event,
            finalization_id=manifest.finalization_id,
            manifest_sha256=manifest.manifest_sha256,
        )
        self._fault("after_completion")

        completed = self.hub.load_consistent_snapshot()
        self._validate_source_and_progress(manifest, completed)
        self._require_all_artifacts_published(manifest, completed)
        if completed["state"].get("status") != "completed":
            raise FinalizationConflictError(
                "planned completion was not persisted"
            )
        return manifest

    def _render(
        self,
        rendered: RenderInput,
        source: FinalizationSourceManifest,
        snapshot: Mapping[str, Any],
    ) -> tuple[RenderedArtifact, ...]:
        raw_outputs = (
            rendered(
                source,
                normalize_json(snapshot, label="renderer snapshot"),
            )
            if callable(rendered)
            else rendered
        )
        if (
            isinstance(raw_outputs, (str, bytes))
            or not isinstance(raw_outputs, Sequence)
        ):
            raise FinalizationValidationError(
                "renderer must return an ordered output sequence"
            )
        try:
            return tuple(_coerce_rendered_output(item) for item in raw_outputs)
        except TypeError as exc:
            raise FinalizationValidationError(
                "renderer must return an iterable of RenderedOutput values"
            ) from exc

    @staticmethod
    def _plan_outputs(
        *,
        source: FinalizationSourceManifest,
        outputs: Sequence[RenderedArtifact],
        frozen_at: str,
    ) -> tuple[PlannedArtifact, ...]:
        planned = tuple(
            PlannedArtifact(
                publish_order=index,
                artifact_id=output.artifact_id,
                artifact_type=output.artifact_type,
                staged_path=_staged_path(index, output.artifact_id),
                final_path=output.final_path,
                sha256=sha256_bytes(output.content),
                size_bytes=len(output.content),
                publish_event_id=(
                    f"artifact:{output.artifact_id}:published"
                ),
                created_at=frozen_at,
                task_id=output.task_id,
                source_refs=output.source_refs,
                metadata={
                    **dict(output.metadata),
                    "finalization_id": FINALIZATION_ID,
                    "source_projection_sha256": (
                        source.source_projection_sha256
                    ),
                },
                is_result=output.is_result,
            )
            for index, output in enumerate(outputs, start=1)
        )
        # Constructing the enclosing manifest performs the final uniqueness
        # checks; fail here as well so no staged path is touched on duplicates.
        ids = [item.artifact_id for item in planned]
        paths = [item.final_path for item in planned]
        if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
            raise FinalizationValidationError(
                "renderer returned duplicate artifact IDs or paths"
            )
        return planned

    def _load_manifest_if_present(
        self,
        *,
        adopt_orphan: bool,
    ) -> FinalizationManifest | None:
        state = self.hub.load_state()
        pointer = state.get("finalization")
        path = self._resolve(FINALIZATION_MANIFEST_PATH)
        if pointer is None and not path.exists():
            return None
        if not path.is_file() or path.is_symlink():
            raise FinalizationConflictError(
                "finalization manifest is missing or not a regular file"
            )
        try:
            raw_bytes = path.read_bytes()
            decoded = json.loads(raw_bytes.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FinalizationValidationError(
                "finalization manifest is not valid JSON"
            ) from exc
        manifest = FinalizationManifest.from_dict(
            _mapping(decoded, "finalization manifest")
        )
        canonical = canonical_json_bytes(manifest.to_dict())
        if raw_bytes != canonical:
            raise FinalizationConflictError(
                "finalization manifest bytes are not canonical"
            )
        if manifest.finalization_id != FINALIZATION_ID:
            raise FinalizationConflictError(
                "unexpected finalization manifest identity"
            )

        if pointer is None:
            if not adopt_orphan:
                raise FinalizationConflictError(
                    "finalization manifest is not bound to the run"
                )
            snapshot = self.hub.load_consistent_snapshot()
            self._validate_source_and_progress(manifest, snapshot)
            if snapshot["state"].get("status") == "completed":
                raise FinalizationConflictError(
                    "completed state cannot adopt an orphan finalization"
                )
            self.hub.bind_finalization_manifest(
                self._manifest_reference(manifest)
            )
            return manifest

        reference = _exact_object(
            _mapping(pointer, "finalization pointer"),
            {"id", "manifest_path", "manifest_sha256", "phase"},
            "finalization pointer",
        )
        expected = self._manifest_reference(manifest)
        if (
            reference.get("id") != expected["id"]
            or reference.get("manifest_path")
            != expected["manifest_path"]
            or reference.get("manifest_sha256")
            != expected["manifest_sha256"]
            or reference.get("phase") not in {"publishing", "completed"}
        ):
            raise FinalizationConflictError(
                "run finalization pointer does not match its manifest"
            )
        return manifest

    @staticmethod
    def _manifest_reference(
        manifest: FinalizationManifest,
    ) -> dict[str, str]:
        return {
            "id": manifest.finalization_id,
            "manifest_path": FINALIZATION_MANIFEST_PATH,
            "manifest_sha256": manifest.manifest_sha256,
            "phase": "publishing",
        }

    def _verify_staged_and_existing(
        self,
        manifest: FinalizationManifest,
    ) -> None:
        state = self.hub.load_state()
        artifacts = _mapping(state.get("artifacts"), "run artifacts")
        for output in manifest.outputs:
            _verify_file(
                self._resolve(output.staged_path),
                expected_sha256=output.sha256,
                expected_size=output.size_bytes,
                label="staged output",
            )
            existing = artifacts.get(output.artifact_id)
            final_path = self._resolve(output.final_path)
            if existing is not None:
                if existing != output.artifact_record:
                    raise FinalizationConflictError(
                        "published C7 artifact record changed"
                    )
                _verify_file(
                    final_path,
                    expected_sha256=output.sha256,
                    expected_size=output.size_bytes,
                    label="published output",
                )
            elif final_path.exists():
                _verify_file(
                    final_path,
                    expected_sha256=output.sha256,
                    expected_size=output.size_bytes,
                    label="adoptable output",
                )

    @staticmethod
    def _require_no_output_collision(
        snapshot: Mapping[str, Any],
        manifest: FinalizationManifest,
    ) -> None:
        state = _mapping(snapshot.get("state"), "snapshot state")
        artifacts = _mapping(state.get("artifacts"), "run artifacts")
        existing_paths = {
            record.get("path")
            for record in artifacts.values()
            if isinstance(record, dict)
        }
        if any(
            output.artifact_id in artifacts
            or output.final_path in existing_paths
            for output in manifest.outputs
        ):
            raise FinalizationConflictError(
                "planned C7 output collides with an existing artifact"
            )

    def _validate_source_and_progress(
        self,
        manifest: FinalizationManifest,
        snapshot: Mapping[str, Any],
    ) -> None:
        value = _exact_object(snapshot, {"state", "ledgers"}, "Hub snapshot")
        state = _normalized_object(value["state"], "run state")
        ledgers = _exact_object(
            _mapping(value["ledgers"], "snapshot ledgers"),
            set(_LEDGER_ID_FIELDS),
            "snapshot ledgers",
        )
        self._require_creative_run(state)
        if state.get("run_id") != manifest.source.run_id:
            raise FinalizationConflictError(
                "finalization source run identity changed"
            )
        route = _mapping(state.get("route"), "route")
        if (
            route.get("contract_version")
            != manifest.source.route_contract_version
            or route.get("report_policy_version")
            != manifest.source.report_policy_version
        ):
            raise FinalizationConflictError(
                "finalization route policy changed"
            )
        if state.get("pending_records") != []:
            raise FinalizationConflictError(
                "finalization replay has unreconciled ledger records"
            )

        completed = state.get("status") == "completed"
        if completed:
            if (
                state.get("current_stage") != FINALIZATION_STAGE
                or state.get("transition_seq")
                != manifest.completed_transition.transition_seq
                or state.get("result_artifact_ids")
                != list(manifest.result_artifact_ids)
            ):
                raise FinalizationConflictError(
                    "completed state does not match the frozen plan"
                )
        elif (
            state.get("status") != "running"
            or state.get("current_stage") != FINALIZATION_STAGE
            or state.get("transition_seq")
            != manifest.source.transition_seq
            or state.get("result_artifact_ids") != []
        ):
            raise FinalizationConflictError(
                "run state is outside the frozen finalization transition"
            )

        pointer = state.get("finalization")
        if pointer is not None:
            reference = _mapping(pointer, "finalization pointer")
            expected_phase = "completed" if completed else "publishing"
            if (
                reference.get("id") != manifest.finalization_id
                or reference.get("manifest_path")
                != FINALIZATION_MANIFEST_PATH
                or reference.get("manifest_sha256")
                != manifest.manifest_sha256
                or reference.get("phase") != expected_phase
            ):
                raise FinalizationConflictError(
                    "run finalization pointer changed"
                )

        artifacts = _mapping(state.get("artifacts"), "run artifacts")
        state_for_source = _normalized_object(state, "source state")
        source_artifacts = _normalized_object(
            state_for_source.get("artifacts"),
            "source artifacts",
        )
        state_for_source["artifacts"] = source_artifacts
        published_orders: list[int] = []
        for output in manifest.outputs:
            record = artifacts.get(output.artifact_id)
            if record is None:
                continue
            if record != output.artifact_record:
                raise FinalizationConflictError(
                    "planned artifact record conflicts with its manifest"
                )
            published_orders.append(output.publish_order)
            source_artifacts.pop(output.artifact_id, None)
        if published_orders != list(
            range(1, len(published_orders) + 1)
        ):
            raise FinalizationConflictError(
                "planned artifacts were not registered in publish order"
            )
        state_for_source.pop("finalization", None)
        if completed:
            state_for_source["status"] = "running"
            state_for_source["current_stage"] = FINALIZATION_STAGE
            state_for_source["transition_seq"] = (
                manifest.source.transition_seq
            )
            state_for_source["result_artifact_ids"] = []
        if (
            sha256_json(_source_state_projection(state_for_source))
            != manifest.source.state_projection_sha256
        ):
            raise FinalizationConflictError(
                "pre-C7 source state projection changed"
            )
        try:
            source_files = _source_file_bindings(
                self.hub.run_dir,
                state_for_source,
            )
        except FinalizationValidationError as exc:
            raise FinalizationConflictError(
                "pre-C7 source file bytes changed"
            ) from exc
        if source_files != manifest.source.source_files:
            raise FinalizationConflictError(
                "pre-C7 source file bindings changed"
            )

        expected_suffix = [
            output.publish_event for output in manifest.outputs
        ] + [manifest.completed_transition.event]
        for ledger in sorted(_LEDGER_ID_FIELDS):
            records = _record_sequence(ledgers[ledger], ledger)
            head = manifest.source.head(ledger)
            if len(records) < head.record_count or not head.matches(
                records[: head.record_count]
            ):
                raise FinalizationConflictError(
                    f"{ledger} source prefix changed"
                )
            suffix = [
                _normalized_object(record, f"{ledger} record")
                for record in records[head.record_count :]
            ]
            if ledger == "events":
                if suffix != expected_suffix[: len(suffix)]:
                    raise FinalizationConflictError(
                        "events contain an unplanned finalization suffix"
                    )
            elif suffix:
                raise FinalizationConflictError(
                    f"{ledger} changed after finalization freeze"
                )
        event_count = len(
            _record_sequence(ledgers["events"], "events")
        ) - manifest.source.head("events").record_count
        if completed and event_count != len(expected_suffix):
            raise FinalizationConflictError(
                "completed state lacks its full planned event suffix"
            )

    @staticmethod
    def _require_all_artifacts_published(
        manifest: FinalizationManifest,
        snapshot: Mapping[str, Any],
    ) -> None:
        state = _mapping(snapshot.get("state"), "snapshot state")
        artifacts = _mapping(state.get("artifacts"), "run artifacts")
        if any(
            artifacts.get(output.artifact_id) != output.artifact_record
            for output in manifest.outputs
        ):
            raise FinalizationConflictError(
                "not every planned artifact is published"
            )
        ledgers = _mapping(snapshot.get("ledgers"), "snapshot ledgers")
        events = _record_sequence(ledgers.get("events"), "events")
        event_ids = {
            event.get("event_id")
            for event in events
            if isinstance(event, dict)
        }
        if any(
            output.publish_event_id not in event_ids
            for output in manifest.outputs
        ):
            raise FinalizationConflictError(
                "not every planned artifact event is published"
            )

    @staticmethod
    def _require_creative_run(state: Mapping[str, Any]) -> None:
        route = _mapping(state.get("route"), "route")
        if route.get("id") != "creative":
            raise FinalizationValidationError(
                "C7 finalization is available only for Creative runs"
            )

    def _resolve(self, relative: str) -> Path:
        return _resolve_run_path(self.hub.run_dir, relative)

    def _fault(self, point: str) -> None:
        if self.fault_injector is not None:
            self.fault_injector(point)


def _coerce_rendered_output(value: RenderedOutput) -> RenderedArtifact:
    if isinstance(value, RenderedArtifact):
        return value
    try:
        final_path = getattr(value, "final_path", value.relative_path)
        return RenderedArtifact(
            artifact_id=value.artifact_id,
            artifact_type=value.artifact_type,
            final_path=final_path,
            content=value.content,
            task_id=getattr(value, "task_id", None),
            source_refs=tuple(getattr(value, "source_refs", ())),
            metadata=getattr(value, "metadata", {}),
            is_result=getattr(value, "is_result", True),
        )
    except AttributeError as exc:
        raise FinalizationValidationError(
            "renderer returned an incomplete RenderedOutput"
        ) from exc


def _source_state_projection(state: Mapping[str, Any]) -> dict[str, Any]:
    projection = _normalized_object(state, "source state")
    projection.pop("updated_at", None)
    projection.pop("finalization", None)
    return projection


def _source_file_bindings(
    run_dir: Path,
    state: Mapping[str, Any],
) -> tuple[SourceFileBinding, ...]:
    """Verify and bind every hashed file referenced directly by run state."""

    records: list[tuple[str, str, str]] = []

    def add(
        record: Mapping[str, Any],
        *,
        path_key: str,
        hash_key: str,
        label: str,
        optional: bool = False,
    ) -> None:
        path = record.get(path_key)
        digest = record.get(hash_key)
        if optional and path is None and digest is None:
            return
        if not isinstance(path, str) or not path:
            raise FinalizationValidationError(
                f"{label} has no valid {path_key}"
            )
        normalized_digest = _require_sha256(
            digest,
            f"{label} {hash_key}",
        )
        records.append((path, normalized_digest, label))

    inputs = _mapping(state.get("inputs"), "run inputs")
    for name, raw in sorted(inputs.items()):
        add(
            _mapping(raw, f"input {name}"),
            path_key="path",
            hash_key="sha256",
            label=f"input {name}",
        )
    resource_manifest = state.get("resource_manifest")
    if resource_manifest is not None:
        add(
            _mapping(resource_manifest, "resource manifest"),
            path_key="path",
            hash_key="sha256",
            label="resource manifest",
        )
    tasks = _mapping(state.get("tasks"), "run tasks")
    for task_id, raw in sorted(tasks.items()):
        task = _mapping(raw, f"task {task_id}")
        for path_key, hash_key, optional in (
            ("request_path", "request_sha256", False),
            ("prompt_path", "prompt_sha256", False),
            ("result_path", "result_sha256", True),
            ("output_path", "output_sha256", True),
        ):
            add(
                task,
                path_key=path_key,
                hash_key=hash_key,
                label=f"task {task_id}",
                optional=optional,
            )
    artifacts = _mapping(state.get("artifacts"), "run artifacts")
    for artifact_id, raw in sorted(artifacts.items()):
        add(
            _mapping(raw, f"artifact {artifact_id}"),
            path_key="path",
            hash_key="sha256",
            label=f"artifact {artifact_id}",
        )

    bindings: dict[str, SourceFileBinding] = {}
    for relative, expected_sha256, label in records:
        path = _resolve_run_path(run_dir, relative)
        if not path.is_file():
            raise FinalizationValidationError(
                f"{label} source file is missing"
            )
        try:
            actual_sha256 = sha256_file(path)
            size_bytes = path.stat().st_size
        except OSError as exc:
            raise FinalizationValidationError(
                f"{label} source file cannot be verified"
            ) from exc
        if actual_sha256 != expected_sha256:
            raise FinalizationValidationError(
                f"{label} source file hash mismatch"
            )
        binding = SourceFileBinding(
            path=relative,
            sha256=expected_sha256,
            size_bytes=size_bytes,
        )
        existing = bindings.get(relative)
        if existing is not None and existing != binding:
            raise FinalizationValidationError(
                "one source path has conflicting file bindings"
            )
        bindings[relative] = binding
    return tuple(bindings[path] for path in sorted(bindings))


def _staged_path(publish_order: int, artifact_id: str) -> str:
    return (
        f"{FINALIZATION_STAGING_ROOT}/"
        f"{publish_order:04d}-{artifact_id}.bin"
    )


def _verify_file(
    path: Path,
    *,
    expected_sha256: str,
    expected_size: int,
    label: str,
) -> None:
    if path.is_symlink() or not path.is_file():
        raise FinalizationConflictError(
            f"{label} is missing or not a regular file"
        )
    try:
        size = path.stat().st_size
        digest = sha256_file(path)
    except OSError as exc:
        raise FinalizationConflictError(
            f"{label} cannot be verified"
        ) from exc
    if size != expected_size or digest != expected_sha256:
        raise FinalizationConflictError(f"{label} bytes changed")


def _record_sequence(value: Any, label: str) -> list[Mapping[str, Any]]:
    sequence = _sequence(value, label)
    records: list[Mapping[str, Any]] = []
    for item in sequence:
        records.append(_mapping(item, f"{label} record"))
    return records


def _normalized_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FinalizationValidationError(f"{label} must be an object")
    try:
        normalized = normalize_json(dict(value), label=label)
    except StateError as exc:
        raise FinalizationValidationError(str(exc)) from exc
    if not isinstance(normalized, dict):
        raise FinalizationValidationError(f"{label} must be an object")
    return normalized


def _exact_object(
    value: Mapping[str, Any],
    keys: set[str],
    label: str,
) -> dict[str, Any]:
    normalized = _normalized_object(value, label)
    if set(normalized) != keys:
        raise FinalizationValidationError(
            f"{label} must contain exactly {sorted(keys)}"
        )
    return normalized


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FinalizationValidationError(f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise FinalizationValidationError(f"{label} must be an array")
    return value


def _string_tuple(values: Sequence[Any], label: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            raise FinalizationValidationError(
                f"{label} must contain only non-empty strings"
            )
        result.append(value)
    return tuple(result)


def _require_nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise FinalizationValidationError(
            f"{label} must be a non-empty string"
        )
    return value


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _require_nonempty(value, label)


def _require_integer(
    value: Any,
    label: str,
    *,
    minimum: int,
) -> int:
    if type(value) is not int or value < minimum:
        raise FinalizationValidationError(
            f"{label} must be an integer >= {minimum}"
        )
    return value


def _require_safe_id(value: Any, label: str) -> str:
    text = _require_nonempty(value, label)
    if not _SAFE_ID.fullmatch(text):
        raise FinalizationValidationError(f"{label} is not a safe ID")
    return text


def _require_sha256(value: Any, label: str) -> str:
    text = _require_nonempty(value, label)
    if not _SHA256.fullmatch(text):
        raise FinalizationValidationError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return text


def _require_run_path(value: Any, label: str) -> str:
    text = _require_nonempty(value, label)
    pure = PurePosixPath(text)
    if (
        "\x00" in text
        or pure.is_absolute()
        or not pure.parts
        or ".." in pure.parts
        or pure.as_posix() != text
    ):
        raise FinalizationValidationError(
            f"{label} must be a safe run-relative path"
        )
    return text


def _require_artifact_path(value: Any, label: str) -> str:
    text = _require_run_path(value, label)
    if not text.startswith("artifacts/creative/"):
        raise FinalizationValidationError(
            f"{label} must be under artifacts/creative/"
        )
    return text


def _resolve_run_path(run_dir: Path, relative: str) -> Path:
    text = _require_run_path(relative, "run-relative path")
    pure = PurePosixPath(text)
    root = run_dir.expanduser().resolve()
    candidate = root.joinpath(*pure.parts)
    cursor = root
    for part in pure.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise FinalizationValidationError(
                "finalization paths cannot contain symlinks"
            )
    resolved = candidate.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise FinalizationValidationError(
            "finalization path escapes the run directory"
        )
    return candidate


__all__ = [
    "FINALIZATION_ID",
    "FINALIZATION_MANIFEST_PATH",
    "FINALIZATION_SCHEMA_VERSION",
    "FINALIZATION_STAGE",
    "FinalizationConflictError",
    "FinalizationCoordinator",
    "FinalizationError",
    "FinalizationManifest",
    "FinalizationRenderer",
    "FinalizationSourceManifest",
    "FinalizationValidationError",
    "LedgerHead",
    "PlannedArtifact",
    "PlannedCompletion",
    "RenderedArtifact",
    "RenderedOutput",
    "SourceFileBinding",
]
