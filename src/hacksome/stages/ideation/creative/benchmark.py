"""Pure offline contracts for Creative benchmark planning and evaluation.

The module deliberately does not start Codex, inspect run directories, read the
clock, or write files.  Callers freeze inputs and collect arm results; this
module validates those facts, creates blind review bytes, imports complete
worksheets idempotently, and renders a deterministic comparison summary.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal, Mapping, Sequence, cast

from hacksome.core.state import canonical_json_bytes, sha256_bytes, sha256_text


ComparisonKind = Literal["workflow_vs_oneshot", "memory_ablation"]
BenchmarkMode = Literal["live", "fixture"]
MemoryPolicy = Literal["auto", "off"]
ArmKind = Literal["workflow", "oneshot"]
ArmStatus = Literal["completed", "waiting_for_human", "failed"]
ReviewProducerKind = Literal["live", "fixture", "none"]
SummaryStatus = Literal[
    "completed",
    "pending_worksheet",
    "waiting_for_human",
    "failed",
]

_COMPARISON_KINDS = frozenset({"workflow_vs_oneshot", "memory_ablation"})
_MODES = frozenset({"live", "fixture"})
_INTERACTION_DESIRES = frozenset({"yes", "maybe", "no"})
_PORTFOLIO_PREFERENCES = frozenset(
    {"arm_a", "arm_b", "tie", "neither"}
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REASONING_EFFORTS = frozenset(
    {"low", "medium", "high", "xhigh", "max", "ultra"}
)
_PROXY_INTERPRETATION = (
    "concept_stage_proxy_only_not_evidence_of_real_world_sharing_or_virality"
)


class CreativeBenchmarkError(ValueError):
    """A benchmark contract is incomplete, inconsistent, or not safely blind."""


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    challenge_path: str
    creative_brief_path: str
    review_fixture_path: str | None
    comparison_kind: ComparisonKind

    def __post_init__(self) -> None:
        _require_id(self.case_id, "benchmark case_id")
        _require_relative_path(self.challenge_path, "challenge_path")
        _require_relative_path(
            self.creative_brief_path,
            "creative_brief_path",
        )
        if self.review_fixture_path is not None:
            _require_relative_path(
                self.review_fixture_path,
                "review_fixture_path",
            )
        if self.comparison_kind not in _COMPARISON_KINDS:
            raise CreativeBenchmarkError("comparison_kind is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> BenchmarkCase:
        raw = _strict_object(
            value,
            expected=frozenset(
                {
                    "case_id",
                    "challenge_path",
                    "creative_brief_path",
                    "review_fixture_path",
                    "comparison_kind",
                }
            ),
            label="benchmark case",
        )
        return cls(
            case_id=raw["case_id"],
            challenge_path=raw["challenge_path"],
            creative_brief_path=raw["creative_brief_path"],
            review_fixture_path=raw["review_fixture_path"],
            comparison_kind=raw["comparison_kind"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "challenge_path": self.challenge_path,
            "creative_brief_path": self.creative_brief_path,
            "review_fixture_path": self.review_fixture_path,
            "comparison_kind": self.comparison_kind,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkManifest:
    schema_version: int
    benchmark_id: str
    mode: BenchmarkMode
    model: str
    reasoning_effort: str
    cases: tuple[BenchmarkCase, ...]
    max_portfolio_size: int = 8

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise CreativeBenchmarkError("unsupported benchmark schema version")
        _require_id(self.benchmark_id, "benchmark_id")
        if self.mode not in _MODES:
            raise CreativeBenchmarkError("benchmark mode is invalid")
        _require_text(self.model, "benchmark model", max_bytes=256)
        if self.reasoning_effort not in _REASONING_EFFORTS:
            raise CreativeBenchmarkError("benchmark reasoning_effort is invalid")
        if not self.cases:
            raise CreativeBenchmarkError("benchmark requires at least one case")
        _require_unique(
            tuple(case.case_id for case in self.cases),
            "benchmark case IDs",
        )
        if (
            type(self.max_portfolio_size) is not int
            or not 1 <= self.max_portfolio_size <= 8
        ):
            raise CreativeBenchmarkError(
                "max_portfolio_size must be an integer from 1 through 8"
            )
        for case in self.cases:
            if self.mode == "live" and case.review_fixture_path is not None:
                raise CreativeBenchmarkError(
                    "live benchmark cases cannot use review fixtures"
                )
            if self.mode == "fixture" and case.review_fixture_path is None:
                raise CreativeBenchmarkError(
                    "fixture benchmark cases require review_fixture_path"
                )

    @property
    def ordered_cases(self) -> tuple[BenchmarkCase, ...]:
        return tuple(sorted(self.cases, key=lambda case: case.case_id))

    @classmethod
    def from_mapping(cls, value: Any) -> BenchmarkManifest:
        raw = _strict_object(
            value,
            expected=frozenset(
                {
                    "schema_version",
                    "benchmark_id",
                    "mode",
                    "model",
                    "reasoning_effort",
                    "cases",
                    "max_portfolio_size",
                }
            ),
            label="benchmark manifest",
        )
        cases = _object_array(raw["cases"], "benchmark manifest cases")
        return cls(
            schema_version=raw["schema_version"],
            benchmark_id=raw["benchmark_id"],
            mode=raw["mode"],
            model=raw["model"],
            reasoning_effort=raw["reasoning_effort"],
            cases=tuple(BenchmarkCase.from_mapping(case) for case in cases),
            max_portfolio_size=raw["max_portfolio_size"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "benchmark_id": self.benchmark_id,
            "mode": self.mode,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "cases": [case.to_dict() for case in self.ordered_cases],
            "max_portfolio_size": self.max_portfolio_size,
        }


@dataclass(frozen=True, slots=True)
class FrozenBenchmarkMemory:
    """Exact benchmark-level memory bytes frozen before either arm starts."""

    case_id: str
    snapshot_ref: str
    snapshot_sha256: str
    snapshot_bytes: bytes
    source_run_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_id(self.case_id, "memory snapshot case_id")
        _require_id(self.snapshot_ref, "memory snapshot_ref")
        _require_sha(self.snapshot_sha256, "memory snapshot_sha256")
        if not isinstance(self.snapshot_bytes, bytes) or not self.snapshot_bytes:
            raise CreativeBenchmarkError(
                "memory snapshot_bytes must be non-empty bytes"
            )
        if sha256_bytes(self.snapshot_bytes) != self.snapshot_sha256:
            raise CreativeBenchmarkError("benchmark memory snapshot hash mismatch")
        _require_unique(self.source_run_ids, "memory snapshot source_run_ids")
        for run_id in self.source_run_ids:
            _require_id(run_id, "memory snapshot source run ID")


@dataclass(frozen=True, slots=True)
class BenchmarkArmPlan:
    case_id: str
    arm_id: str
    arm_kind: ArmKind
    memory_policy: MemoryPolicy
    memory_snapshot_sha256: str
    consumes_memory_snapshot: bool

    def __post_init__(self) -> None:
        _require_id(self.case_id, "arm plan case_id")
        _require_id(self.arm_id, "arm_id")
        if self.arm_kind not in {"workflow", "oneshot"}:
            raise CreativeBenchmarkError("arm_kind is invalid")
        if self.memory_policy not in {"auto", "off"}:
            raise CreativeBenchmarkError("arm memory_policy is invalid")
        _require_sha(
            self.memory_snapshot_sha256,
            "arm memory_snapshot_sha256",
        )
        if type(self.consumes_memory_snapshot) is not bool:
            raise CreativeBenchmarkError(
                "consumes_memory_snapshot must be boolean"
            )
        if self.consumes_memory_snapshot != (self.memory_policy == "auto"):
            raise CreativeBenchmarkError(
                "only an auto-memory arm may consume the frozen snapshot"
            )


def plan_case_arms(
    case: BenchmarkCase,
    memory: FrozenBenchmarkMemory,
) -> tuple[BenchmarkArmPlan, BenchmarkArmPlan]:
    """Return the two stable arm contracts for one benchmark case."""

    if case.case_id != memory.case_id:
        raise CreativeBenchmarkError("case and memory snapshot IDs do not match")
    if case.comparison_kind == "workflow_vs_oneshot":
        specs: tuple[tuple[str, ArmKind, MemoryPolicy], ...] = (
            ("workflow", "workflow", "off"),
            ("oneshot", "oneshot", "off"),
        )
    else:
        specs = (
            ("memory-auto", "workflow", "auto"),
            ("memory-off", "workflow", "off"),
        )
    return cast(
        tuple[BenchmarkArmPlan, BenchmarkArmPlan],
        tuple(
            BenchmarkArmPlan(
                case_id=case.case_id,
                arm_id=f"{case.case_id}:{suffix}",
                arm_kind=arm_kind,
                memory_policy=memory_policy,
                memory_snapshot_sha256=memory.snapshot_sha256,
                consumes_memory_snapshot=memory_policy == "auto",
            )
            for suffix, arm_kind, memory_policy in specs
        ),
    )


@dataclass(frozen=True, slots=True)
class PortfolioIdea:
    """One controller-approved blind card; source identity stays in arm-map."""

    idea_id: str
    idea_card_sha256: str
    blind_markdown: str

    def __post_init__(self) -> None:
        _require_id(self.idea_id, "portfolio idea_id")
        _require_sha(self.idea_card_sha256, "portfolio idea_card_sha256")
        _require_text(
            self.blind_markdown,
            "portfolio blind_markdown",
            max_bytes=128 * 1024,
        )
        if sha256_text(self.blind_markdown) != self.idea_card_sha256:
            raise CreativeBenchmarkError("portfolio Idea Card hash mismatch")


@dataclass(frozen=True, slots=True)
class ArmMetrics:
    token_count: int
    wall_time_ms: int
    task_count: int
    candidate_count: int
    shortlist_count: int
    review_receipt_count: int
    memory_source_diagnostic_count: int
    selected_cue_count: int
    challenger_count: int
    copy_reject_count: int

    def __post_init__(self) -> None:
        for name in (
            "token_count",
            "wall_time_ms",
            "task_count",
            "candidate_count",
            "shortlist_count",
            "review_receipt_count",
            "memory_source_diagnostic_count",
            "selected_cue_count",
            "challenger_count",
            "copy_reject_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise CreativeBenchmarkError(
                    f"arm metric {name} must be a non-negative integer"
                )
        if self.shortlist_count > self.candidate_count:
            raise CreativeBenchmarkError(
                "shortlist_count cannot exceed candidate_count"
            )

    def to_dict(self) -> dict[str, int]:
        return {
            "token_count": self.token_count,
            "wall_time_ms": self.wall_time_ms,
            "task_count": self.task_count,
            "candidate_count": self.candidate_count,
            "shortlist_count": self.shortlist_count,
            "review_receipt_count": self.review_receipt_count,
            "memory_source_diagnostic_count": (
                self.memory_source_diagnostic_count
            ),
            "selected_cue_count": self.selected_cue_count,
            "challenger_count": self.challenger_count,
            "copy_reject_count": self.copy_reject_count,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkArmResult:
    case_id: str
    arm_id: str
    source_run_id: str
    status: ArmStatus
    memory_policy: MemoryPolicy
    memory_snapshot_sha256: str
    consumed_memory_snapshot: bool
    portfolio: tuple[PortfolioIdea, ...]
    metrics: ArmMetrics
    review_producer_kind: ReviewProducerKind
    failure_kind: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.case_id, "arm result case_id")
        _require_id(self.arm_id, "arm result arm_id")
        _require_id(self.source_run_id, "arm result source_run_id")
        if self.status not in {"completed", "waiting_for_human", "failed"}:
            raise CreativeBenchmarkError("arm result status is invalid")
        if self.memory_policy not in {"auto", "off"}:
            raise CreativeBenchmarkError("arm result memory_policy is invalid")
        _require_sha(
            self.memory_snapshot_sha256,
            "arm result memory_snapshot_sha256",
        )
        if type(self.consumed_memory_snapshot) is not bool:
            raise CreativeBenchmarkError(
                "arm result consumed_memory_snapshot must be boolean"
            )
        if self.consumed_memory_snapshot != (self.memory_policy == "auto"):
            raise CreativeBenchmarkError(
                "arm result snapshot consumption conflicts with memory policy"
            )
        _require_unique(
            tuple(idea.idea_id for idea in self.portfolio),
            "portfolio idea IDs",
        )
        if self.status != "completed" and self.portfolio:
            raise CreativeBenchmarkError(
                "non-completed arm cannot expose a final portfolio"
            )
        if self.review_producer_kind not in {"live", "fixture", "none"}:
            raise CreativeBenchmarkError("review_producer_kind is invalid")
        if self.status == "failed":
            _require_text(
                self.failure_kind,
                "failed arm failure_kind",
                max_bytes=512,
            )
        elif self.failure_kind is not None:
            raise CreativeBenchmarkError(
                "only a failed arm may have failure_kind"
            )


def validate_arm_results(
    manifest: BenchmarkManifest,
    case: BenchmarkCase,
    memory: FrozenBenchmarkMemory,
    results: Sequence[BenchmarkArmResult],
) -> tuple[BenchmarkArmResult, BenchmarkArmResult]:
    """Validate exact arm plans, shared snapshot binding, and no arm leakage."""

    plans = plan_case_arms(case, memory)
    plan_by_id = {plan.arm_id: plan for plan in plans}
    if len(results) != 2:
        raise CreativeBenchmarkError(
            f"{case.case_id} requires exactly two arm results"
        )
    result_by_id = {result.arm_id: result for result in results}
    if len(result_by_id) != len(results) or set(result_by_id) != set(plan_by_id):
        raise CreativeBenchmarkError(
            f"{case.case_id} arm results do not match the frozen plan"
        )
    source_run_ids = tuple(result.source_run_id for result in results)
    _require_unique(source_run_ids, f"{case.case_id} arm source_run_ids")
    leaked = set(source_run_ids).intersection(memory.source_run_ids)
    if leaked:
        raise CreativeBenchmarkError(
            "benchmark memory snapshot contains an output run from this case: "
            + ", ".join(sorted(leaked))
        )
    ordered: list[BenchmarkArmResult] = []
    for plan in plans:
        result = result_by_id[plan.arm_id]
        if result.case_id != case.case_id:
            raise CreativeBenchmarkError("arm result belongs to another case")
        if (
            result.memory_policy != plan.memory_policy
            or result.memory_snapshot_sha256
            != plan.memory_snapshot_sha256
            or result.consumed_memory_snapshot
            != plan.consumes_memory_snapshot
        ):
            raise CreativeBenchmarkError(
                f"{result.arm_id} drifted from its memory arm plan"
            )
        if len(result.portfolio) > manifest.max_portfolio_size:
            raise CreativeBenchmarkError(
                f"{result.arm_id} exceeds max_portfolio_size"
            )
        if plan.arm_kind == "oneshot":
            if result.review_producer_kind != "none":
                raise CreativeBenchmarkError(
                    "one-shot arm cannot claim a C6 review producer"
                )
            if result.metrics.review_receipt_count != 0:
                raise CreativeBenchmarkError(
                    "one-shot arm cannot claim C6 review receipts"
                )
        elif manifest.mode == "live" and result.status == "completed":
            if result.review_producer_kind != "live":
                raise CreativeBenchmarkError(
                    "completed live workflow arm requires live review provenance"
                )
        elif manifest.mode == "fixture" and result.status == "completed":
            if result.review_producer_kind != "fixture":
                raise CreativeBenchmarkError(
                    "completed fixture workflow arm requires fixture provenance"
                )
        if len(result.portfolio) > result.metrics.candidate_count:
            raise CreativeBenchmarkError(
                f"{result.arm_id} portfolio exceeds its candidate count"
            )
        ordered.append(result)
    return cast(
        tuple[BenchmarkArmResult, BenchmarkArmResult],
        tuple(ordered),
    )


@dataclass(frozen=True, slots=True)
class BlindIdeaBinding:
    blind_idea_id: str
    source_idea_id: str
    idea_card_sha256: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[AB][1-8]", self.blind_idea_id):
            raise CreativeBenchmarkError("blind_idea_id is invalid")
        _require_id(self.source_idea_id, "blind source_idea_id")
        _require_sha(self.idea_card_sha256, "blind Idea Card sha256")


@dataclass(frozen=True, slots=True)
class BlindCaseMap:
    case_id: str
    arm_a_arm_id: str
    arm_b_arm_id: str
    arm_a_ideas: tuple[BlindIdeaBinding, ...]
    arm_b_ideas: tuple[BlindIdeaBinding, ...]

    def __post_init__(self) -> None:
        _require_id(self.case_id, "blind map case_id")
        _require_id(self.arm_a_arm_id, "blind map arm_a_arm_id")
        _require_id(self.arm_b_arm_id, "blind map arm_b_arm_id")
        if self.arm_a_arm_id == self.arm_b_arm_id:
            raise CreativeBenchmarkError("blind arms must map to different results")
        for label, bindings in (
            ("arm_a_ideas", self.arm_a_ideas),
            ("arm_b_ideas", self.arm_b_ideas),
        ):
            _require_unique(
                tuple(item.blind_idea_id for item in bindings),
                f"blind map {label}",
            )
            _require_unique(
                tuple(item.source_idea_id for item in bindings),
                f"blind map source {label}",
            )


@dataclass(frozen=True, slots=True)
class BlindReviewPacket:
    """Public blind bytes plus the separate private arm map bytes."""

    benchmark_id: str
    mode: BenchmarkMode
    packet_sha256: str
    packet_json_bytes: bytes
    packet_markdown_bytes: bytes
    arm_map_json_bytes: bytes
    case_maps: tuple[BlindCaseMap, ...]

    def __post_init__(self) -> None:
        _require_id(self.benchmark_id, "blind packet benchmark_id")
        if self.mode not in _MODES:
            raise CreativeBenchmarkError("blind packet mode is invalid")
        _require_sha(self.packet_sha256, "blind packet_sha256")
        if sha256_bytes(self.packet_json_bytes) != self.packet_sha256:
            raise CreativeBenchmarkError("blind packet hash mismatch")
        for label, content in (
            ("packet_json_bytes", self.packet_json_bytes),
            ("packet_markdown_bytes", self.packet_markdown_bytes),
            ("arm_map_json_bytes", self.arm_map_json_bytes),
        ):
            if not isinstance(content, bytes) or not content:
                raise CreativeBenchmarkError(
                    f"blind packet {label} must be non-empty bytes"
                )
        _require_unique(
            tuple(item.case_id for item in self.case_maps),
            "blind packet case IDs",
        )
        _validate_packet_bindings(self)


def _validate_packet_bindings(packet: BlindReviewPacket) -> None:
    try:
        public = json.loads(packet.packet_json_bytes)
        private = json.loads(packet.arm_map_json_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CreativeBenchmarkError(
            f"blind packet contains invalid JSON: {exc}"
        ) from exc
    public_raw = _strict_object(
        public,
        expected=frozenset({"schema_version", "benchmark_id", "cases"}),
        label="blind public packet",
    )
    if (
        type(public_raw["schema_version"]) is not int
        or public_raw["schema_version"] != 1
        or public_raw["benchmark_id"] != packet.benchmark_id
    ):
        raise CreativeBenchmarkError("blind public packet identity mismatch")
    public_cases = _object_array(public_raw["cases"], "blind public cases")
    public_by_case: dict[str, dict[str, Any]] = {}
    for value in public_cases:
        case = _strict_object(
            value,
            expected=frozenset(
                {
                    "case_id",
                    "arm_a_ideas",
                    "arm_a_no_idea",
                    "arm_b_ideas",
                    "arm_b_no_idea",
                }
            ),
            label="blind public case",
        )
        case_id = _require_id(case["case_id"], "blind public case_id")
        if case_id in public_by_case:
            raise CreativeBenchmarkError(
                "blind public packet has duplicate case IDs"
            )
        public_by_case[case_id] = case
    if set(public_by_case) != {item.case_id for item in packet.case_maps}:
        raise CreativeBenchmarkError(
            "blind public packet case set does not match arm map"
        )
    for case_map in packet.case_maps:
        public_case = public_by_case[case_map.case_id]
        for side, bindings in (
            ("a", case_map.arm_a_ideas),
            ("b", case_map.arm_b_ideas),
        ):
            ideas = _object_array(
                public_case[f"arm_{side}_ideas"],
                f"blind public arm_{side}_ideas",
            )
            expected = {
                item.blind_idea_id: item.idea_card_sha256
                for item in bindings
            }
            actual: dict[str, str] = {}
            for idea in ideas:
                raw_idea = _strict_object(
                    idea,
                    expected=frozenset(
                        {
                            "blind_idea_id",
                            "idea_card_sha256",
                            "idea_card_markdown",
                        }
                    ),
                    label="blind public Idea",
                )
                blind_id = raw_idea["blind_idea_id"]
                if not isinstance(blind_id, str) or not re.fullmatch(
                    r"[AB][1-8]",
                    blind_id,
                ):
                    raise CreativeBenchmarkError(
                        "blind public Idea ID is invalid"
                    )
                if blind_id in actual:
                    raise CreativeBenchmarkError(
                        "blind public packet has duplicate Idea IDs"
                    )
                markdown = _require_text(
                    raw_idea["idea_card_markdown"],
                    "blind public Idea Card",
                    max_bytes=128 * 1024,
                )
                digest = _require_sha(
                    raw_idea["idea_card_sha256"],
                    "blind public Idea Card sha256",
                )
                if sha256_text(markdown) != digest:
                    raise CreativeBenchmarkError(
                        "blind public Idea Card hash mismatch"
                    )
                actual[blind_id] = digest
            if actual != expected:
                raise CreativeBenchmarkError(
                    f"blind public arm_{side} Idea bindings mismatch"
                )
            no_idea = public_case[f"arm_{side}_no_idea"]
            if type(no_idea) is not bool or no_idea != (not bindings):
                raise CreativeBenchmarkError(
                    f"blind public arm_{side} no-Idea flag mismatch"
                )

    expected_private = {
        "schema_version": 1,
        "benchmark_id": packet.benchmark_id,
        "packet_sha256": packet.packet_sha256,
        "cases": [
            {
                "case_id": item.case_id,
                "arm_a_arm_id": item.arm_a_arm_id,
                "arm_b_arm_id": item.arm_b_arm_id,
                "arm_a_ideas": [
                    {
                        "blind_idea_id": binding.blind_idea_id,
                        "source_idea_id": binding.source_idea_id,
                        "idea_card_sha256": binding.idea_card_sha256,
                    }
                    for binding in item.arm_a_ideas
                ],
                "arm_b_ideas": [
                    {
                        "blind_idea_id": binding.blind_idea_id,
                        "source_idea_id": binding.source_idea_id,
                        "idea_card_sha256": binding.idea_card_sha256,
                    }
                    for binding in item.arm_b_ideas
                ],
            }
            for item in packet.case_maps
        ],
    }
    if private != expected_private:
        raise CreativeBenchmarkError(
            "private arm map bytes do not match packet bindings"
        )


def build_blind_packet(
    manifest: BenchmarkManifest,
    memories: Sequence[FrozenBenchmarkMemory],
    results: Sequence[BenchmarkArmResult],
) -> BlindReviewPacket:
    """Create stable public A/B bytes and a separate private mapping."""

    memory_by_case = _memory_by_case(manifest, memories)
    results_by_case = _results_by_case(manifest, results)
    packet_cases: list[dict[str, Any]] = []
    case_maps: list[BlindCaseMap] = []
    markdown_lines = [
        "# Blind Creative Benchmark Packet",
        "",
        (
            "Judge only the concepts below. Process identity, model sessions, "
            "token cost, and arm mapping are intentionally absent."
        ),
        "",
    ]
    for case in manifest.ordered_cases:
        ordered_results = validate_arm_results(
            manifest,
            case,
            memory_by_case[case.case_id],
            results_by_case[case.case_id],
        )
        if any(result.status != "completed" for result in ordered_results):
            raise CreativeBenchmarkError(
                "blind packet requires both arms to be completed"
            )
        arm_a, arm_b = _blind_arm_order(
            manifest.benchmark_id,
            case.case_id,
            ordered_results,
        )
        arm_a_ideas, arm_a_bindings = _blind_portfolio("A", arm_a.portfolio)
        arm_b_ideas, arm_b_bindings = _blind_portfolio("B", arm_b.portfolio)
        packet_cases.append(
            {
                "case_id": case.case_id,
                "arm_a_ideas": arm_a_ideas,
                "arm_a_no_idea": not arm_a_ideas,
                "arm_b_ideas": arm_b_ideas,
                "arm_b_no_idea": not arm_b_ideas,
            }
        )
        case_maps.append(
            BlindCaseMap(
                case_id=case.case_id,
                arm_a_arm_id=arm_a.arm_id,
                arm_b_arm_id=arm_b.arm_id,
                arm_a_ideas=arm_a_bindings,
                arm_b_ideas=arm_b_bindings,
            )
        )
        markdown_lines.extend(
            [
                f"## Case {case.case_id}",
                "",
                "### Arm A",
                "",
            ]
        )
        _append_blind_markdown_portfolio(
            markdown_lines,
            arm_a_ideas,
        )
        markdown_lines.extend(["### Arm B", ""])
        _append_blind_markdown_portfolio(
            markdown_lines,
            arm_b_ideas,
        )

    packet_payload = {
        "schema_version": 1,
        "benchmark_id": manifest.benchmark_id,
        "cases": packet_cases,
    }
    packet_json_bytes = _json_file_bytes(packet_payload)
    packet_sha256 = sha256_bytes(packet_json_bytes)
    arm_map_payload = {
        "schema_version": 1,
        "benchmark_id": manifest.benchmark_id,
        "packet_sha256": packet_sha256,
        "cases": [
            {
                "case_id": item.case_id,
                "arm_a_arm_id": item.arm_a_arm_id,
                "arm_b_arm_id": item.arm_b_arm_id,
                "arm_a_ideas": [
                    {
                        "blind_idea_id": binding.blind_idea_id,
                        "source_idea_id": binding.source_idea_id,
                        "idea_card_sha256": binding.idea_card_sha256,
                    }
                    for binding in item.arm_a_ideas
                ],
                "arm_b_ideas": [
                    {
                        "blind_idea_id": binding.blind_idea_id,
                        "source_idea_id": binding.source_idea_id,
                        "idea_card_sha256": binding.idea_card_sha256,
                    }
                    for binding in item.arm_b_ideas
                ],
            }
            for item in case_maps
        ],
    }
    return BlindReviewPacket(
        benchmark_id=manifest.benchmark_id,
        mode=manifest.mode,
        packet_sha256=packet_sha256,
        packet_json_bytes=packet_json_bytes,
        packet_markdown_bytes="\n".join(markdown_lines).encode("utf-8"),
        arm_map_json_bytes=_json_file_bytes(arm_map_payload),
        case_maps=tuple(case_maps),
    )


def _blind_arm_order(
    benchmark_id: str,
    case_id: str,
    results: tuple[BenchmarkArmResult, BenchmarkArmResult],
) -> tuple[BenchmarkArmResult, BenchmarkArmResult]:
    digest = sha256_text(benchmark_id + case_id)
    return results if int(digest, 16) % 2 == 0 else (results[1], results[0])


def _blind_portfolio(
    label: Literal["A", "B"],
    portfolio: Sequence[PortfolioIdea],
) -> tuple[list[dict[str, str]], tuple[BlindIdeaBinding, ...]]:
    ideas: list[dict[str, str]] = []
    bindings: list[BlindIdeaBinding] = []
    for index, idea in enumerate(
        sorted(portfolio, key=lambda item: item.idea_id),
        start=1,
    ):
        blind_id = f"{label}{index}"
        ideas.append(
            {
                "blind_idea_id": blind_id,
                "idea_card_sha256": idea.idea_card_sha256,
                "idea_card_markdown": idea.blind_markdown,
            }
        )
        bindings.append(
            BlindIdeaBinding(
                blind_idea_id=blind_id,
                source_idea_id=idea.idea_id,
                idea_card_sha256=idea.idea_card_sha256,
            )
        )
    return ideas, tuple(bindings)


def _append_blind_markdown_portfolio(
    lines: list[str],
    ideas: Sequence[Mapping[str, str]],
) -> None:
    if not ideas:
        lines.extend(["No Idea was produced by this arm.", ""])
        return
    for idea in ideas:
        lines.extend(
            [
                f"#### {idea['blind_idea_id']}",
                "",
                idea["idea_card_markdown"],
                "",
            ]
        )


@dataclass(frozen=True, slots=True)
class WorksheetIdeaReview:
    blind_idea_id: str
    retell: str
    share_target: str
    surprise_source: str
    interaction_desire: Literal["yes", "maybe", "no"]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[AB][1-8]", self.blind_idea_id):
            raise CreativeBenchmarkError("worksheet blind_idea_id is invalid")
        _require_text(self.retell, "worksheet retell", max_bytes=400)
        _require_text(
            self.share_target,
            "worksheet share_target",
            max_bytes=200,
            allow_empty=True,
        )
        _require_text(
            self.surprise_source,
            "worksheet surprise_source",
            max_bytes=1000,
        )
        if self.interaction_desire not in _INTERACTION_DESIRES:
            raise CreativeBenchmarkError(
                "worksheet interaction_desire is invalid"
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "blind_idea_id": self.blind_idea_id,
            "retell": self.retell,
            "share_target": self.share_target,
            "surprise_source": self.surprise_source,
            "interaction_desire": self.interaction_desire,
        }


@dataclass(frozen=True, slots=True)
class WorksheetCaseReview:
    case_id: str
    arm_a_ideas: tuple[WorksheetIdeaReview, ...]
    arm_b_ideas: tuple[WorksheetIdeaReview, ...]
    best_arm_a_idea: str | None
    best_arm_b_idea: str | None
    portfolio_preference: Literal["arm_a", "arm_b", "tie", "neither"]
    reason: str

    def __post_init__(self) -> None:
        _require_id(self.case_id, "worksheet case_id")
        for label, reviews in (
            ("arm_a_ideas", self.arm_a_ideas),
            ("arm_b_ideas", self.arm_b_ideas),
        ):
            _require_unique(
                tuple(item.blind_idea_id for item in reviews),
                f"worksheet {label}",
            )
        for value, label in (
            (self.best_arm_a_idea, "best_arm_a_idea"),
            (self.best_arm_b_idea, "best_arm_b_idea"),
        ):
            if value is not None and not re.fullmatch(r"[AB][1-8]", value):
                raise CreativeBenchmarkError(f"worksheet {label} is invalid")
        if self.portfolio_preference not in _PORTFOLIO_PREFERENCES:
            raise CreativeBenchmarkError(
                "worksheet portfolio_preference is invalid"
            )
        _require_text(self.reason, "worksheet reason", max_bytes=4000)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "arm_a_ideas": [
                item.to_dict()
                for item in sorted(
                    self.arm_a_ideas,
                    key=lambda value: value.blind_idea_id,
                )
            ],
            "arm_b_ideas": [
                item.to_dict()
                for item in sorted(
                    self.arm_b_ideas,
                    key=lambda value: value.blind_idea_id,
                )
            ],
            "best_idea": {
                "arm_a": self.best_arm_a_idea,
                "arm_b": self.best_arm_b_idea,
            },
            "portfolio_preference": self.portfolio_preference,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkWorksheet:
    schema_version: int
    benchmark_id: str
    packet_sha256: str
    review_id: str
    reviewer_name: str
    cases: tuple[WorksheetCaseReview, ...]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise CreativeBenchmarkError("unsupported worksheet schema version")
        _require_id(self.benchmark_id, "worksheet benchmark_id")
        _require_sha(self.packet_sha256, "worksheet packet_sha256")
        _require_id(self.review_id, "worksheet review_id")
        _require_text(
            self.reviewer_name,
            "worksheet reviewer_name",
            max_bytes=80,
        )
        _require_unique(
            tuple(case.case_id for case in self.cases),
            "worksheet case IDs",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "benchmark_id": self.benchmark_id,
            "packet_sha256": self.packet_sha256,
            "review_id": self.review_id,
            "reviewer_name": self.reviewer_name,
            "cases": [
                case.to_dict()
                for case in sorted(self.cases, key=lambda value: value.case_id)
            ],
        }

    @classmethod
    def from_mapping(
        cls,
        value: Any,
        *,
        packet: BlindReviewPacket,
    ) -> BenchmarkWorksheet:
        raw = _strict_object(
            value,
            expected=frozenset(
                {
                    "schema_version",
                    "benchmark_id",
                    "packet_sha256",
                    "review_id",
                    "reviewer_name",
                    "cases",
                }
            ),
            label="benchmark worksheet",
        )
        if raw["benchmark_id"] != packet.benchmark_id:
            raise CreativeBenchmarkError("worksheet benchmark_id mismatch")
        if raw["packet_sha256"] != packet.packet_sha256:
            raise CreativeBenchmarkError("worksheet packet_sha256 mismatch")
        case_values = _object_array(raw["cases"], "worksheet cases")
        expected_maps = {item.case_id: item for item in packet.case_maps}
        raw_by_id: dict[str, dict[str, Any]] = {}
        for item in case_values:
            case_id = item.get("case_id")
            if not isinstance(case_id, str):
                raise CreativeBenchmarkError(
                    "worksheet case_id must be a string"
                )
            if case_id in raw_by_id:
                raise CreativeBenchmarkError(
                    "worksheet contains duplicate case IDs"
                )
            raw_by_id[case_id] = item
        if set(raw_by_id) != set(expected_maps):
            raise CreativeBenchmarkError(
                "worksheet case set does not match the blind packet"
            )
        cases = tuple(
            _parse_worksheet_case(
                raw_by_id[case_id],
                expected_maps[case_id],
            )
            for case_id in sorted(expected_maps)
        )
        worksheet = cls(
            schema_version=raw["schema_version"],
            benchmark_id=raw["benchmark_id"],
            packet_sha256=raw["packet_sha256"],
            review_id=raw["review_id"],
            reviewer_name=raw["reviewer_name"],
            cases=cases,
        )
        return worksheet


def _parse_worksheet_case(
    value: Any,
    expected: BlindCaseMap,
) -> WorksheetCaseReview:
    raw = _strict_object(
        value,
        expected=frozenset(
            {
                "case_id",
                "arm_a_ideas",
                "arm_b_ideas",
                "best_idea",
                "portfolio_preference",
                "reason",
            }
        ),
        label="worksheet case",
    )
    if raw["case_id"] != expected.case_id:
        raise CreativeBenchmarkError("worksheet case_id mismatch")
    arm_a = _parse_worksheet_idea_array(
        raw["arm_a_ideas"],
        expected.arm_a_ideas,
        label="worksheet arm_a_ideas",
    )
    arm_b = _parse_worksheet_idea_array(
        raw["arm_b_ideas"],
        expected.arm_b_ideas,
        label="worksheet arm_b_ideas",
    )
    best = _strict_object(
        raw["best_idea"],
        expected=frozenset({"arm_a", "arm_b"}),
        label="worksheet best_idea",
    )
    expected_a_ids = {item.blind_idea_id for item in expected.arm_a_ideas}
    expected_b_ids = {item.blind_idea_id for item in expected.arm_b_ideas}
    _validate_best_idea(best["arm_a"], expected_a_ids, "arm_a")
    _validate_best_idea(best["arm_b"], expected_b_ids, "arm_b")
    return WorksheetCaseReview(
        case_id=expected.case_id,
        arm_a_ideas=arm_a,
        arm_b_ideas=arm_b,
        best_arm_a_idea=best["arm_a"],
        best_arm_b_idea=best["arm_b"],
        portfolio_preference=raw["portfolio_preference"],
        reason=raw["reason"],
    )


def _parse_worksheet_idea_array(
    value: Any,
    expected: Sequence[BlindIdeaBinding],
    *,
    label: str,
) -> tuple[WorksheetIdeaReview, ...]:
    raw_items = _object_array(value, label)
    expected_ids = {item.blind_idea_id for item in expected}
    parsed: list[WorksheetIdeaReview] = []
    for raw in raw_items:
        item = _strict_object(
            raw,
            expected=frozenset(
                {
                    "blind_idea_id",
                    "retell",
                    "share_target",
                    "surprise_source",
                    "interaction_desire",
                }
            ),
            label="worksheet Idea review",
        )
        parsed.append(
            WorksheetIdeaReview(
                blind_idea_id=item["blind_idea_id"],
                retell=item["retell"],
                share_target=item["share_target"],
                surprise_source=item["surprise_source"],
                interaction_desire=item["interaction_desire"],
            )
        )
    actual_ids = [item.blind_idea_id for item in parsed]
    if len(actual_ids) != len(set(actual_ids)):
        raise CreativeBenchmarkError(
            f"{label} contains duplicate blind Idea IDs"
        )
    if set(actual_ids) != expected_ids:
        raise CreativeBenchmarkError(
            f"{label} must evaluate every blind Idea exactly once"
        )
    return tuple(sorted(parsed, key=lambda item: item.blind_idea_id))


def _validate_best_idea(
    value: Any,
    expected_ids: set[str],
    label: str,
) -> None:
    if not expected_ids:
        if value is not None:
            raise CreativeBenchmarkError(
                f"zero-Idea {label} must have null best_idea"
            )
        return
    if value not in expected_ids:
        raise CreativeBenchmarkError(
            f"{label} best_idea must select one blind Idea"
        )


@dataclass(frozen=True, slots=True)
class WorksheetReceipt:
    review_id: str
    request_sha256: str
    worksheet: BenchmarkWorksheet

    def __post_init__(self) -> None:
        if self.review_id != self.worksheet.review_id:
            raise CreativeBenchmarkError(
                "worksheet receipt review_id mismatch"
            )
        _require_sha(self.request_sha256, "worksheet request_sha256")
        if sha256_bytes(
            canonical_json_bytes(self.worksheet.to_dict())
        ) != self.request_sha256:
            raise CreativeBenchmarkError(
                "worksheet receipt request hash mismatch"
            )


def import_worksheet(
    packet: BlindReviewPacket,
    payload: Mapping[str, Any],
    *,
    existing_receipts: Sequence[WorksheetReceipt] = (),
) -> WorksheetReceipt:
    """Validate one live worksheet and apply request-ID idempotency."""

    if packet.mode != "live":
        raise CreativeBenchmarkError(
            "fixture benchmarks do not accept human worksheets"
        )
    worksheet = BenchmarkWorksheet.from_mapping(payload, packet=packet)
    request_sha256 = sha256_bytes(
        canonical_json_bytes(worksheet.to_dict())
    )
    matches = [
        receipt
        for receipt in existing_receipts
        if receipt.review_id == worksheet.review_id
    ]
    if len(matches) > 1:
        raise CreativeBenchmarkError(
            "existing worksheet receipts contain duplicate review IDs"
        )
    if matches:
        existing = matches[0]
        if existing.request_sha256 != request_sha256:
            raise CreativeBenchmarkError(
                "worksheet review_id was reused with different content"
            )
        return existing
    return WorksheetReceipt(
        review_id=worksheet.review_id,
        request_sha256=request_sha256,
        worksheet=worksheet,
    )


@dataclass(frozen=True, slots=True)
class RenderedBenchmarkSummary:
    status: SummaryStatus
    json_bytes: bytes

    def __post_init__(self) -> None:
        if self.status not in {
            "completed",
            "pending_worksheet",
            "waiting_for_human",
            "failed",
        }:
            raise CreativeBenchmarkError("benchmark summary status is invalid")
        if not isinstance(self.json_bytes, bytes) or not self.json_bytes:
            raise CreativeBenchmarkError(
                "benchmark summary must contain JSON bytes"
            )


def summarize_benchmark(
    manifest: BenchmarkManifest,
    memories: Sequence[FrozenBenchmarkMemory],
    results: Sequence[BenchmarkArmResult],
    *,
    packet: BlindReviewPacket | None = None,
    worksheet_receipts: Sequence[WorksheetReceipt] = (),
) -> RenderedBenchmarkSummary:
    """Render operational costs and explicitly bounded human proxy signals."""

    memory_by_case = _memory_by_case(manifest, memories)
    results_by_case = _results_by_case(manifest, results)
    validated: dict[str, tuple[BenchmarkArmResult, BenchmarkArmResult]] = {}
    for case in manifest.ordered_cases:
        validated[case.case_id] = validate_arm_results(
            manifest,
            case,
            memory_by_case[case.case_id],
            results_by_case[case.case_id],
        )
    statuses = {
        result.status
        for case_results in validated.values()
        for result in case_results
    }
    if "failed" in statuses:
        status: SummaryStatus = "failed"
    elif "waiting_for_human" in statuses:
        status = "waiting_for_human"
    elif manifest.mode == "live" and not worksheet_receipts:
        status = "pending_worksheet"
    else:
        status = "completed"

    complete = statuses == {"completed"}
    verified_packet: BlindReviewPacket | None = None
    if complete:
        expected_packet = build_blind_packet(manifest, memories, results)
        if packet is None:
            verified_packet = expected_packet
        else:
            if (
                packet.benchmark_id != expected_packet.benchmark_id
                or packet.mode != expected_packet.mode
                or packet.packet_json_bytes
                != expected_packet.packet_json_bytes
                or packet.packet_markdown_bytes
                != expected_packet.packet_markdown_bytes
                or packet.arm_map_json_bytes
                != expected_packet.arm_map_json_bytes
            ):
                raise CreativeBenchmarkError(
                    "provided blind packet does not match arm results"
                )
            verified_packet = packet
    elif packet is not None:
        raise CreativeBenchmarkError(
            "incomplete benchmark cannot expose a blind packet"
        )

    if manifest.mode == "fixture" and worksheet_receipts:
        raise CreativeBenchmarkError(
            "fixture benchmark cannot consume human worksheet receipts"
        )
    if worksheet_receipts:
        if verified_packet is None:
            raise CreativeBenchmarkError(
                "worksheet receipts require a completed blind packet"
            )
        _validate_receipts(verified_packet, worksheet_receipts)

    human_by_case_arm = (
        _aggregate_human_proxy(verified_packet, worksheet_receipts)
        if manifest.mode == "live" and worksheet_receipts
        else {}
    )
    case_payloads: list[dict[str, Any]] = []
    for case in manifest.ordered_cases:
        case_results = validated[case.case_id]
        arm_payloads = []
        for result in case_results:
            arm_payloads.append(
                {
                    "arm_id": result.arm_id,
                    "arm_kind": _arm_kind_for_result(case, result),
                    "status": result.status,
                    "source_run_id": result.source_run_id,
                    "memory_policy": result.memory_policy,
                    "memory_snapshot_sha256": (
                        result.memory_snapshot_sha256
                    ),
                    "consumed_memory_snapshot": (
                        result.consumed_memory_snapshot
                    ),
                    "portfolio_size": len(result.portfolio),
                    "metrics": result.metrics.to_dict(),
                    "human_proxy": _human_proxy_payload(
                        manifest,
                        case_id=case.case_id,
                        arm_id=result.arm_id,
                        values=human_by_case_arm,
                        benchmark_status=status,
                    ),
                }
            )
        case_payloads.append(
            {
                "case_id": case.case_id,
                "comparison_kind": case.comparison_kind,
                "memory_snapshot_ref": (
                    memory_by_case[case.case_id].snapshot_ref
                ),
                "memory_snapshot_sha256": (
                    memory_by_case[case.case_id].snapshot_sha256
                ),
                "memory_snapshot_source_run_ids": sorted(
                    memory_by_case[case.case_id].source_run_ids
                ),
                "arms": arm_payloads,
            }
        )
    payload = {
        "schema_version": 1,
        "benchmark_id": manifest.benchmark_id,
        "mode": manifest.mode,
        "status": status,
        "model": manifest.model,
        "reasoning_effort": manifest.reasoning_effort,
        "packet_sha256": (
            verified_packet.packet_sha256
            if verified_packet is not None
            else None
        ),
        "worksheet_count": len(worksheet_receipts),
        "human_proxy_interpretation": _PROXY_INTERPRETATION,
        "cases": case_payloads,
    }
    return RenderedBenchmarkSummary(
        status=status,
        json_bytes=_json_file_bytes(payload),
    )


def _arm_kind_for_result(
    case: BenchmarkCase,
    result: BenchmarkArmResult,
) -> ArmKind:
    if (
        case.comparison_kind == "workflow_vs_oneshot"
        and result.arm_id.endswith(":oneshot")
    ):
        return "oneshot"
    return "workflow"


def _validate_receipts(
    packet: BlindReviewPacket,
    receipts: Sequence[WorksheetReceipt],
) -> None:
    _require_unique(
        tuple(receipt.review_id for receipt in receipts),
        "worksheet receipt review IDs",
    )
    for receipt in receipts:
        if (
            receipt.worksheet.benchmark_id != packet.benchmark_id
            or receipt.worksheet.packet_sha256 != packet.packet_sha256
        ):
            raise CreativeBenchmarkError(
                "worksheet receipt is bound to another packet"
            )


def _aggregate_human_proxy(
    packet: BlindReviewPacket | None,
    receipts: Sequence[WorksheetReceipt],
) -> dict[tuple[str, str], dict[str, Any]]:
    if packet is None:
        return {}
    case_maps = {item.case_id: item for item in packet.case_maps}
    totals: dict[tuple[str, str], dict[str, Any]] = {}
    for case_map in packet.case_maps:
        for arm_id in (case_map.arm_a_arm_id, case_map.arm_b_arm_id):
            totals[(case_map.case_id, arm_id)] = {
                "worksheet_response_count": 0,
                "idea_evaluation_count": 0,
                "retell_response_count": 0,
                "specific_share_target_count": 0,
                "surprise_source_response_count": 0,
                "interaction_desire": {"yes": 0, "maybe": 0, "no": 0},
                "best_idea_selection_count": 0,
                "portfolio_preference": {
                    "preferred": 0,
                    "tie": 0,
                    "neither": 0,
                    "other_arm": 0,
                },
            }
    for receipt in receipts:
        for review in receipt.worksheet.cases:
            case_map = case_maps[review.case_id]
            for side, arm_id, idea_reviews, best in (
                (
                    "arm_a",
                    case_map.arm_a_arm_id,
                    review.arm_a_ideas,
                    review.best_arm_a_idea,
                ),
                (
                    "arm_b",
                    case_map.arm_b_arm_id,
                    review.arm_b_ideas,
                    review.best_arm_b_idea,
                ),
            ):
                values = totals[(review.case_id, arm_id)]
                values["worksheet_response_count"] += 1
                values["idea_evaluation_count"] += len(idea_reviews)
                values["retell_response_count"] += sum(
                    bool(item.retell.strip()) for item in idea_reviews
                )
                values["specific_share_target_count"] += sum(
                    bool(item.share_target.strip()) for item in idea_reviews
                )
                values["surprise_source_response_count"] += sum(
                    bool(item.surprise_source.strip()) for item in idea_reviews
                )
                interaction = cast(dict[str, int], values["interaction_desire"])
                for item in idea_reviews:
                    interaction[item.interaction_desire] += 1
                if best is not None:
                    values["best_idea_selection_count"] += 1
                preference = cast(
                    dict[str, int],
                    values["portfolio_preference"],
                )
                if review.portfolio_preference == side:
                    preference["preferred"] += 1
                elif review.portfolio_preference == "tie":
                    preference["tie"] += 1
                elif review.portfolio_preference == "neither":
                    preference["neither"] += 1
                else:
                    preference["other_arm"] += 1
    return totals


def _human_proxy_payload(
    manifest: BenchmarkManifest,
    *,
    case_id: str,
    arm_id: str,
    values: Mapping[tuple[str, str], dict[str, Any]],
    benchmark_status: SummaryStatus,
) -> dict[str, Any]:
    if manifest.mode == "fixture":
        return {
            "status": "omitted_fixture",
            "interpretation": _PROXY_INTERPRETATION,
            "metrics": None,
        }
    if benchmark_status in {"waiting_for_human", "pending_worksheet"}:
        return {
            "status": "pending",
            "interpretation": _PROXY_INTERPRETATION,
            "metrics": None,
        }
    return {
        "status": "computed",
        "interpretation": _PROXY_INTERPRETATION,
        "metrics": values.get((case_id, arm_id)),
    }


def _memory_by_case(
    manifest: BenchmarkManifest,
    memories: Sequence[FrozenBenchmarkMemory],
) -> dict[str, FrozenBenchmarkMemory]:
    result = {memory.case_id: memory for memory in memories}
    if len(result) != len(memories):
        raise CreativeBenchmarkError(
            "benchmark has duplicate memory snapshots for one case"
        )
    expected = {case.case_id for case in manifest.cases}
    if set(result) != expected:
        raise CreativeBenchmarkError(
            "benchmark memory snapshot set does not match manifest cases"
        )
    return result


def _results_by_case(
    manifest: BenchmarkManifest,
    results: Sequence[BenchmarkArmResult],
) -> dict[str, tuple[BenchmarkArmResult, ...]]:
    grouped: dict[str, list[BenchmarkArmResult]] = {
        case.case_id: [] for case in manifest.cases
    }
    for result in results:
        if result.case_id not in grouped:
            raise CreativeBenchmarkError(
                "arm result belongs to an unknown benchmark case"
            )
        grouped[result.case_id].append(result)
    if any(len(case_results) != 2 for case_results in grouped.values()):
        raise CreativeBenchmarkError(
            "every benchmark case requires exactly two arm results"
        )
    return {
        case_id: tuple(case_results)
        for case_id, case_results in grouped.items()
    }


def _strict_object(
    value: Any,
    *,
    expected: frozenset[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CreativeBenchmarkError(f"{label} must be an object")
    raw = dict(value)
    missing = sorted(expected - raw.keys())
    unknown = sorted(raw.keys() - expected)
    if missing:
        raise CreativeBenchmarkError(f"{label} is missing fields: {missing}")
    if unknown:
        raise CreativeBenchmarkError(f"{label} has unknown fields: {unknown}")
    return raw


def _object_array(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise CreativeBenchmarkError(f"{label} must be an array")
    if not all(isinstance(item, Mapping) for item in value):
        raise CreativeBenchmarkError(f"{label} must contain objects")
    return [dict(item) for item in value]


def _require_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise CreativeBenchmarkError(f"{label} must be a safe identifier")
    return value


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise CreativeBenchmarkError(f"{label} must be a lowercase SHA-256")
    return value


def _require_relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CreativeBenchmarkError(f"{label} must be a relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value:
        raise CreativeBenchmarkError(f"{label} must be a safe relative path")
    return value


def _require_text(
    value: Any,
    label: str,
    *,
    max_bytes: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise CreativeBenchmarkError(f"{label} must be a string")
    if not allow_empty and not value.strip():
        raise CreativeBenchmarkError(f"{label} must not be empty")
    if len(value.encode("utf-8")) > max_bytes:
        raise CreativeBenchmarkError(f"{label} exceeds its text budget")
    return value


def _require_unique(values: Sequence[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise CreativeBenchmarkError(f"{label} contains duplicates")


def _json_file_bytes(value: Any) -> bytes:
    return canonical_json_bytes(value) + b"\n"


__all__ = [
    "ArmMetrics",
    "BenchmarkArmPlan",
    "BenchmarkArmResult",
    "BenchmarkCase",
    "BenchmarkManifest",
    "BenchmarkWorksheet",
    "BlindCaseMap",
    "BlindIdeaBinding",
    "BlindReviewPacket",
    "CreativeBenchmarkError",
    "FrozenBenchmarkMemory",
    "PortfolioIdea",
    "RenderedBenchmarkSummary",
    "WorksheetCaseReview",
    "WorksheetIdeaReview",
    "WorksheetReceipt",
    "build_blind_packet",
    "import_worksheet",
    "plan_case_arms",
    "summarize_benchmark",
    "validate_arm_results",
]
