"""C1W Cultural Signal Scan contracts and deterministic safe projections.

Raw web-derived source material is retained only in the hash-bound snapshot.
C2/C3 consume a small controller-authored palette that deliberately omits
labels, source metadata, URLs, platform names, and surface markers.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Mapping, Sequence
from urllib.parse import urlsplit


CULTURAL_SIGNAL_SNAPSHOT_SCHEMA_VERSION = 1
CULTURAL_SIGNAL_PALETTE_SCHEMA_VERSION = 1
CULTURAL_SIGNAL_LOOKBACK_DAYS = 30
CULTURAL_SIGNAL_MAX_SIGNALS = 12
CULTURAL_SIGNAL_MAX_SOURCES = 4
CULTURAL_SIGNAL_RFC3339_TIMESTAMP_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
CULTURAL_SIGNAL_SNAPSHOT_ARTIFACT_ID = (
    "creative-cultural-signal-snapshot-r001"
)
CULTURAL_SIGNAL_SNAPSHOT_ARTIFACT_TYPE = (
    "creative_cultural_signal_snapshot"
)
CULTURAL_SIGNAL_SNAPSHOT_RELATIVE_PATH = (
    "artifacts/creative/cultural-signals/"
    "creative-cultural-signal-snapshot-r001.json"
)

CulturalSignalStatus = Literal["ready", "partial", "empty", "unavailable"]
CulturalSignalRole = Literal["inspire", "avoid", "context_only"]
CulturalSignalKind = Literal[
    "trend", "meme", "controversy", "counter_signal"
]
CulturalSignalPalettePurpose = Literal["c2", "c3"]

_SIGNAL_KINDS = frozenset(
    {"trend", "meme", "controversy", "counter_signal"}
)
_CREATIVE_ROLES = frozenset({"inspire", "avoid", "context_only"})
_SOURCE_KINDS = frozenset(
    {
        "primary_post",
        "platform_trend_page",
        "first_party_statement",
        "news_report",
        "analysis",
    }
)
_PLATFORM_KINDS = frozenset(
    {
        "social",
        "video",
        "forum",
        "news",
        "blog",
        "project",
        "search_trend",
        "other",
    }
)
_TIME_PRECISIONS = frozenset({"minute", "day", "month", "unknown"})
_CONFIDENCE = frozenset({"low", "medium", "high"})
_SAFETY_FLAGS = frozenset(
    {
        "none",
        "harassment",
        "privacy",
        "misinformation",
        "political",
        "graphic",
        "minors",
    }
)
_HIGH_RISK_FLAGS = _SAFETY_FLAGS - {"none"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SIGNAL_ID = re.compile(r"^cultural-signal-(?P<slot>[0-9]{3})$")
_RFC3339_TIMESTAMP = re.compile(
    CULTURAL_SIGNAL_RFC3339_TIMESTAMP_PATTERN
)
_OFFSETLESS_TIMESTAMP_SHAPE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"(?:T[0-9]{2}:[0-9]{2}"
    r"(?::[0-9]{2}(?:\.[0-9]+)?)?)?$"
)
_UNSAFE_SAFE_TEXT = re.compile(
    r"https?://|www\.|@[A-Za-z0-9_]|#[A-Za-z0-9_]|"
    r"\[[^\]]+\]\([^)]+\)|```|<a\b",
    flags=re.IGNORECASE,
)
_MAX_TEXT_CHARS = 2_000


class CulturalSignalError(ValueError):
    """A raw signal, snapshot, or safe palette violates the v3 contract."""


@dataclass(frozen=True, slots=True)
class CulturalSignalWindow:
    as_of_utc: str
    start_utc: str
    end_utc: str
    lookback_days: int
    captured_at_utc: str

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
    ) -> CulturalSignalWindow:
        raw = _strict_object(
            value,
            expected={
                "as_of_utc",
                "start_utc",
                "end_utc",
                "lookback_days",
                "captured_at_utc",
            },
            label="cultural signal window",
        )
        lookback_days = raw["lookback_days"]
        if (
            isinstance(lookback_days, bool)
            or not isinstance(lookback_days, int)
            or lookback_days != CULTURAL_SIGNAL_LOOKBACK_DAYS
        ):
            raise CulturalSignalError(
                "cultural signal lookback_days must be exactly 30"
            )
        as_of = _timestamp(raw["as_of_utc"], "window as_of_utc")
        start = _timestamp(raw["start_utc"], "window start_utc")
        end = _timestamp(raw["end_utc"], "window end_utc")
        captured = _timestamp(
            raw["captured_at_utc"],
            "window captured_at_utc",
        )
        if as_of != end:
            raise CulturalSignalError(
                "cultural signal as_of_utc must equal end_utc"
            )
        if start != end - timedelta(days=lookback_days):
            raise CulturalSignalError(
                "cultural signal window does not match lookback_days"
            )
        if captured < as_of:
            raise CulturalSignalError(
                "cultural signal captured_at_utc precedes as_of_utc"
            )
        return cls(
            as_of_utc=_timestamp_text(as_of),
            start_utc=_timestamp_text(start),
            end_utc=_timestamp_text(end),
            lookback_days=lookback_days,
            captured_at_utc=_timestamp_text(captured),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_utc": self.as_of_utc,
            "start_utc": self.start_utc,
            "end_utc": self.end_utc,
            "lookback_days": self.lookback_days,
            "captured_at_utc": self.captured_at_utc,
        }

    @property
    def start(self) -> datetime:
        return _timestamp(self.start_utc, "window start")

    @property
    def end(self) -> datetime:
        return _timestamp(self.end_utc, "window end")


@dataclass(frozen=True, slots=True)
class CulturalSignalSnapshot:
    status: CulturalSignalStatus
    window: CulturalSignalWindow
    task_ref: str
    diagnostic_ref: str | None
    coverage: Mapping[str, Any]
    signals: tuple[Mapping[str, Any], ...]
    no_signal_reason: str | None

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
    ) -> CulturalSignalSnapshot:
        raw = _strict_object(
            value,
            expected={
                "schema_version",
                "status",
                "window",
                "task_ref",
                "diagnostic_ref",
                "coverage",
                "signals",
                "no_signal_reason",
            },
            label="cultural signal snapshot",
        )
        if raw["schema_version"] != CULTURAL_SIGNAL_SNAPSHOT_SCHEMA_VERSION:
            raise CulturalSignalError(
                "unsupported cultural signal snapshot schema version"
            )
        status = raw["status"]
        if status not in {"ready", "partial", "empty", "unavailable"}:
            raise CulturalSignalError("cultural signal status is invalid")
        task_ref = _identifier(raw["task_ref"], "cultural signal task_ref")
        diagnostic_ref = _optional_identifier(
            raw["diagnostic_ref"],
            "cultural signal diagnostic_ref",
        )
        window = CulturalSignalWindow.from_mapping(
            _mapping(raw["window"], "cultural signal window")
        )
        coverage = _validate_coverage(raw["coverage"])
        raw_signals = raw["signals"]
        if not isinstance(raw_signals, list):
            raise CulturalSignalError("cultural signals must be an array")
        if len(raw_signals) > CULTURAL_SIGNAL_MAX_SIGNALS:
            raise CulturalSignalError("too many cultural signals")
        seen_urls: set[str] = set()
        signals = tuple(
            _validate_snapshot_signal(
                item,
                expected_slot=slot,
                window=window,
                seen_urls=seen_urls,
            )
            for slot, item in enumerate(raw_signals, start=1)
        )
        no_signal_reason = _optional_text(
            raw["no_signal_reason"],
            "cultural signal no_signal_reason",
            max_chars=1_000,
        )
        limitations = coverage["limitations"]
        if status == "ready":
            if not signals or limitations:
                raise CulturalSignalError(
                    "ready signal snapshot requires signals and no limitations"
                )
            if diagnostic_ref is not None or no_signal_reason is not None:
                raise CulturalSignalError(
                    "ready signal snapshot cannot carry failure/empty fields"
                )
        elif status == "partial":
            if not signals or not limitations:
                raise CulturalSignalError(
                    "partial signal snapshot requires signals and limitations"
                )
            if diagnostic_ref is not None or no_signal_reason is not None:
                raise CulturalSignalError(
                    "partial signal snapshot cannot carry failure/empty fields"
                )
        elif status == "empty":
            if signals or no_signal_reason is None:
                raise CulturalSignalError(
                    "empty signal snapshot requires a no-signal reason"
                )
            if diagnostic_ref is not None:
                raise CulturalSignalError(
                    "empty signal snapshot cannot carry a failure diagnostic"
                )
        else:
            if signals or diagnostic_ref is None or no_signal_reason is not None:
                raise CulturalSignalError(
                    "unavailable signal snapshot requires only a diagnostic"
                )
            if not limitations:
                raise CulturalSignalError(
                    "unavailable signal snapshot requires a limitation"
                )
        return cls(
            status=status,
            window=window,
            task_ref=task_ref,
            diagnostic_ref=diagnostic_ref,
            coverage=coverage,
            signals=signals,
            no_signal_reason=no_signal_reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CULTURAL_SIGNAL_SNAPSHOT_SCHEMA_VERSION,
            "status": self.status,
            "window": self.window.to_dict(),
            "task_ref": self.task_ref,
            "diagnostic_ref": self.diagnostic_ref,
            "coverage": _json_copy(self.coverage),
            "signals": [_json_copy(item) for item in self.signals],
            "no_signal_reason": self.no_signal_reason,
        }


def cultural_signal_window(
    run_created_at: str,
    *,
    captured_at: str,
) -> CulturalSignalWindow:
    as_of = _timestamp(run_created_at, "run created_at")
    captured = _timestamp(captured_at, "cultural signal captured_at")
    return CulturalSignalWindow.from_mapping(
        {
            "as_of_utc": _timestamp_text(as_of),
            "start_utc": _timestamp_text(
                as_of - timedelta(days=CULTURAL_SIGNAL_LOOKBACK_DAYS)
            ),
            "end_utc": _timestamp_text(as_of),
            "lookback_days": CULTURAL_SIGNAL_LOOKBACK_DAYS,
            "captured_at_utc": _timestamp_text(captured),
        }
    )


def cultural_signal_window_prompt(run_created_at: str) -> str:
    as_of = _timestamp(run_created_at, "run created_at")
    payload = {
        "as_of_utc": _timestamp_text(as_of),
        "start_utc": _timestamp_text(
            as_of - timedelta(days=CULTURAL_SIGNAL_LOOKBACK_DAYS)
        ),
        "end_utc": _timestamp_text(as_of),
        "lookback_days": CULTURAL_SIGNAL_LOOKBACK_DAYS,
        "max_signals": CULTURAL_SIGNAL_MAX_SIGNALS,
        "max_sources_per_signal": CULTURAL_SIGNAL_MAX_SOURCES,
    }
    return _json_text(payload)


def validate_cultural_signal_agent_output(
    value: Mapping[str, Any],
    *,
    window: CulturalSignalWindow | None = None,
) -> dict[str, Any]:
    """Validate the model envelope without assigning controller IDs."""

    raw = _strict_object(
        value,
        expected={"coverage", "signals", "no_signal_reason"},
        label="cultural signal Agent output",
    )
    coverage = _validate_coverage(raw["coverage"])
    raw_signals = raw["signals"]
    if not isinstance(raw_signals, list):
        raise CulturalSignalError("cultural signals must be an array")
    if len(raw_signals) > CULTURAL_SIGNAL_MAX_SIGNALS:
        raise CulturalSignalError("too many cultural signals")
    seen_urls: set[str] = set()
    signals = [
        _validate_agent_signal(
            item,
            window=window,
            seen_urls=seen_urls,
        )
        for item in raw_signals
    ]
    no_signal_reason = _optional_text(
        raw["no_signal_reason"],
        "cultural signal no_signal_reason",
        max_chars=1_000,
    )
    if signals and no_signal_reason is not None:
        raise CulturalSignalError(
            "non-empty signal output cannot carry no_signal_reason"
        )
    if not signals and no_signal_reason is None:
        raise CulturalSignalError(
            "empty signal output requires no_signal_reason"
        )
    return {
        "coverage": coverage,
        "signals": signals,
        "no_signal_reason": no_signal_reason,
    }


def build_cultural_signal_snapshot(
    output: Mapping[str, Any],
    *,
    run_created_at: str,
    captured_at: str,
    task_ref: str,
) -> CulturalSignalSnapshot:
    window = cultural_signal_window(
        run_created_at,
        captured_at=captured_at,
    )
    normalized = validate_cultural_signal_agent_output(
        output,
        window=window,
    )
    limitations = normalized["coverage"]["limitations"]
    signals: list[dict[str, Any]] = []
    for slot, item in enumerate(normalized["signals"], start=1):
        sources = [
            {
                **source,
                "retrieved_at_utc": window.captured_at_utc,
            }
            for source in item["sources"]
        ]
        signals.append(
            {
                "signal_id": f"cultural-signal-{slot:03d}",
                **{key: value for key, value in item.items() if key != "sources"},
                "sources": sources,
            }
        )
    status: CulturalSignalStatus
    if not signals:
        status = "empty"
    elif limitations:
        status = "partial"
    else:
        status = "ready"
    return CulturalSignalSnapshot.from_mapping(
        {
            "schema_version": CULTURAL_SIGNAL_SNAPSHOT_SCHEMA_VERSION,
            "status": status,
            "window": window.to_dict(),
            "task_ref": task_ref,
            "diagnostic_ref": None,
            "coverage": normalized["coverage"],
            "signals": signals,
            "no_signal_reason": normalized["no_signal_reason"],
        }
    )


def unavailable_cultural_signal_snapshot(
    *,
    run_created_at: str,
    captured_at: str,
    task_ref: str,
    diagnostic_ref: str,
    failure_kind: str,
) -> CulturalSignalSnapshot:
    window = cultural_signal_window(
        run_created_at,
        captured_at=captured_at,
    )
    return CulturalSignalSnapshot.from_mapping(
        {
            "schema_version": CULTURAL_SIGNAL_SNAPSHOT_SCHEMA_VERSION,
            "status": "unavailable",
            "window": window.to_dict(),
            "task_ref": task_ref,
            "diagnostic_ref": diagnostic_ref,
            "coverage": {
                "query_families": [],
                "platforms_attempted": [],
                "limitations": [
                    "Optional Cultural Signal Scan unavailable "
                    f"({failure_kind}); generation continued without signals."
                ],
            },
            "signals": [],
            "no_signal_reason": None,
        }
    )


def cultural_signal_palette(
    snapshot: CulturalSignalSnapshot,
    *,
    slot: int,
    purpose: CulturalSignalPalettePurpose,
) -> dict[str, Any]:
    if isinstance(slot, bool) or not isinstance(slot, int) or slot < 1:
        raise CulturalSignalError("palette slot must be a positive integer")
    if purpose not in {"c2", "c3"}:
        raise CulturalSignalError("palette purpose must be c2 or c3")
    if snapshot.status not in {"ready", "partial"}:
        return {
            "schema_version": CULTURAL_SIGNAL_PALETTE_SCHEMA_VERSION,
            "status": snapshot.status,
            "as_of_utc": snapshot.window.as_of_utc,
            "signals": [],
        }

    eligible = tuple(
        signal
        for signal in snapshot.signals
        if _signal_is_palette_eligible(signal, snapshot.window)
    )
    inspire = tuple(
        signal for signal in eligible if signal["creative_role"] == "inspire"
    )
    avoid = tuple(
        signal for signal in eligible if signal["creative_role"] == "avoid"
    )
    inspire_offset = (slot - 1) if purpose == "c2" else (slot - 1) * 2
    selected = list(_rotated_take(inspire, inspire_offset, 2))
    if purpose == "c2":
        selected.extend(_rotated_take(avoid, slot - 1, 2))
    palette_signals = [
        _safe_signal_projection(signal)
        for signal in selected
    ]
    return {
        "schema_version": CULTURAL_SIGNAL_PALETTE_SCHEMA_VERSION,
        "status": snapshot.status,
        "as_of_utc": snapshot.window.as_of_utc,
        "signals": palette_signals,
    }


def render_cultural_signal_palette(
    snapshot: CulturalSignalSnapshot,
    *,
    slot: int,
    purpose: CulturalSignalPalettePurpose,
) -> str:
    palette = _json_text(
        cultural_signal_palette(snapshot, slot=slot, purpose=purpose)
    )
    return (
        "This palette is optional creative material, not a coverage checklist. "
        "It is not evidence of demand, frequency, market size, sponsor intent, "
        "cultural consensus, safety, novelty, or virality. Use only the "
        "abstract_pattern, creative_tension, and participation_shape; never "
        "recreate a name, slogan, character, hashtag, dispute, visual template, "
        "fixed punchline, or exact interaction format. The software mechanism, "
        "real input/output, repeatable product loop, and share trigger must "
        "still work after the signal becomes stale. C0 constraints, the C1 "
        "brief, and the Software Demo Policy always take priority. Never claim "
        "that trending proves people want the product, and never invent a "
        "signal, source, product, URL, or adoption fact.\n\n"
        + palette
    )


def validate_cultural_signal_palette(
    value: Mapping[str, Any],
    *,
    snapshot: CulturalSignalSnapshot,
    slot: int,
    purpose: CulturalSignalPalettePurpose,
) -> None:
    expected = cultural_signal_palette(
        snapshot,
        slot=slot,
        purpose=purpose,
    )
    if _json_copy(value) != expected:
        raise CulturalSignalError(
            "Cultural Signal Palette is not the deterministic slot projection"
        )


def _validate_coverage(value: Any) -> dict[str, Any]:
    raw = _strict_object(
        value,
        expected={"query_families", "platforms_attempted", "limitations"},
        label="cultural signal coverage",
    )
    query_families = _text_list(
        raw["query_families"],
        "coverage query_families",
        max_items=16,
        max_chars=300,
    )
    limitations = _text_list(
        raw["limitations"],
        "coverage limitations",
        max_items=12,
        max_chars=1_000,
    )
    attempts_raw = raw["platforms_attempted"]
    if not isinstance(attempts_raw, list) or len(attempts_raw) > 24:
        raise CulturalSignalError(
            "coverage platforms_attempted must be a bounded array"
        )
    attempts: list[dict[str, str]] = []
    seen_attempts: set[tuple[str, str]] = set()
    for item in attempts_raw:
        attempt = _strict_object(
            item,
            expected={"name", "kind"},
            label="coverage platform attempt",
        )
        name = _text(attempt["name"], "platform name", max_chars=160)
        kind = attempt["kind"]
        if kind not in _PLATFORM_KINDS:
            raise CulturalSignalError("platform kind is invalid")
        key = (_normalized(name), str(kind))
        if key in seen_attempts:
            raise CulturalSignalError("duplicate platform attempt")
        seen_attempts.add(key)
        attempts.append({"name": name, "kind": str(kind)})
    return {
        "query_families": query_families,
        "platforms_attempted": attempts,
        "limitations": limitations,
    }


def _validate_agent_signal(
    value: Any,
    *,
    window: CulturalSignalWindow | None,
    seen_urls: set[str],
) -> dict[str, Any]:
    raw = _strict_object(
        value,
        expected={
            "kind",
            "creative_role",
            "label",
            "neutral_summary",
            "abstract_pattern",
            "creative_tension",
            "participation_shape",
            "surface_markers_to_avoid",
            "safety_flags",
            "confidence",
            "sources",
        },
        label="cultural signal",
    )
    kind = raw["kind"]
    role = raw["creative_role"]
    confidence = raw["confidence"]
    if kind not in _SIGNAL_KINDS:
        raise CulturalSignalError("cultural signal kind is invalid")
    if role not in _CREATIVE_ROLES:
        raise CulturalSignalError("cultural signal creative_role is invalid")
    if confidence not in _CONFIDENCE:
        raise CulturalSignalError("cultural signal confidence is invalid")
    label = _text(raw["label"], "signal label", max_chars=160)
    neutral_summary = _text(
        raw["neutral_summary"],
        "signal neutral_summary",
        max_chars=1_200,
    )
    abstract_pattern = _safe_palette_text(
        raw["abstract_pattern"],
        "signal abstract_pattern",
    )
    creative_tension = _safe_palette_text(
        raw["creative_tension"],
        "signal creative_tension",
    )
    participation_shape = _safe_palette_text(
        raw["participation_shape"],
        "signal participation_shape",
    )
    markers = _text_list(
        raw["surface_markers_to_avoid"],
        "surface_markers_to_avoid",
        max_items=8,
        max_chars=200,
    )
    safety_flags = _text_list(
        raw["safety_flags"],
        "safety_flags",
        max_items=len(_SAFETY_FLAGS),
        max_chars=32,
    )
    if not safety_flags or any(flag not in _SAFETY_FLAGS for flag in safety_flags):
        raise CulturalSignalError("signal safety_flags are invalid")
    if "none" in safety_flags and len(safety_flags) != 1:
        raise CulturalSignalError(
            "signal safety flag none cannot accompany another flag"
        )
    if (
        kind == "controversy"
        and set(safety_flags).intersection(_HIGH_RISK_FLAGS)
        and role != "context_only"
    ):
        raise CulturalSignalError(
            "high-risk controversy must be context_only"
        )
    forbidden = (label, *markers)
    for field_name, field_value in (
        ("abstract_pattern", abstract_pattern),
        ("creative_tension", creative_tension),
        ("participation_shape", participation_shape),
    ):
        _reject_surface_copy(
            field_value,
            forbidden=forbidden,
            label=field_name,
        )
    sources_raw = raw["sources"]
    if (
        not isinstance(sources_raw, list)
        or not 1 <= len(sources_raw) <= CULTURAL_SIGNAL_MAX_SOURCES
    ):
        raise CulturalSignalError(
            "each cultural signal requires one to four sources"
        )
    sources = [
        _validate_source(
            item,
            seen_urls=seen_urls,
            include_retrieved_at=False,
        )
        for item in sources_raw
    ]
    for source_raw, source in zip(sources_raw, sources, strict=True):
        if source["published_at"] is not None:
            continue
        if source["source_kind"] != "platform_trend_page":
            raise CulturalSignalError(
                "observed_at-only evidence must be a live platform trend page"
            )
        if (
            window is not None
            and _mapping(
                source_raw,
                "cultural signal source",
            ).get("observed_at")
            != window.as_of_utc
        ):
            raise CulturalSignalError(
                "live trend observed_at must equal the supplied as_of_utc"
            )
    if confidence == "high" and len(sources) < 2:
        raise CulturalSignalError(
            "high-confidence signal requires at least two sources"
        )
    if window is not None:
        if not any(_source_is_in_window(source, window) for source in sources):
            raise CulturalSignalError(
                "each cultural signal requires an in-window source"
            )
    return {
        "kind": str(kind),
        "creative_role": str(role),
        "label": label,
        "neutral_summary": neutral_summary,
        "abstract_pattern": abstract_pattern,
        "creative_tension": creative_tension,
        "participation_shape": participation_shape,
        "surface_markers_to_avoid": markers,
        "safety_flags": safety_flags,
        "confidence": str(confidence),
        "sources": sources,
    }


def _validate_snapshot_signal(
    value: Any,
    *,
    expected_slot: int,
    window: CulturalSignalWindow,
    seen_urls: set[str],
) -> dict[str, Any]:
    raw = _strict_object(
        value,
        expected={
            "signal_id",
            "kind",
            "creative_role",
            "label",
            "neutral_summary",
            "abstract_pattern",
            "creative_tension",
            "participation_shape",
            "surface_markers_to_avoid",
            "safety_flags",
            "confidence",
            "sources",
        },
        label="snapshot cultural signal",
    )
    signal_id = _identifier(raw["signal_id"], "cultural signal ID")
    match = _SIGNAL_ID.fullmatch(signal_id)
    if match is None or int(match.group("slot")) != expected_slot:
        raise CulturalSignalError(
            "cultural signal IDs must be sequential controller IDs"
        )
    agent_shape = {
        key: value for key, value in raw.items() if key != "signal_id"
    }
    sources_raw = agent_shape["sources"]
    if not isinstance(sources_raw, list):
        raise CulturalSignalError("snapshot signal sources must be an array")
    agent_shape["sources"] = [
        {
            key: value
            for key, value in _mapping(
                source,
                "snapshot signal source",
            ).items()
            if key != "retrieved_at_utc"
        }
        for source in sources_raw
    ]
    normalized = _validate_agent_signal(
        agent_shape,
        window=window,
        seen_urls=seen_urls,
    )
    snapshot_sources = [
        _validate_source(
            source,
            seen_urls=set(),
            include_retrieved_at=True,
        )
        for source in sources_raw
    ]
    if any(
        source["retrieved_at_utc"] != window.captured_at_utc
        for source in snapshot_sources
    ):
        raise CulturalSignalError(
            "source retrieved_at_utc must equal snapshot capture time"
        )
    return {
        "signal_id": signal_id,
        **{key: value for key, value in normalized.items() if key != "sources"},
        "sources": snapshot_sources,
    }


def _validate_source(
    value: Any,
    *,
    seen_urls: set[str],
    include_retrieved_at: bool,
) -> dict[str, Any]:
    expected = {
        "title",
        "url",
        "publisher",
        "source_kind",
        "platform",
        "published_at",
        "observed_at",
        "time_precision",
        "locale",
        "evidence_summary",
    }
    if include_retrieved_at:
        expected.add("retrieved_at_utc")
    raw = _strict_object(
        value,
        expected=expected,
        label="cultural signal source",
    )
    url = _absolute_http_url(raw["url"])
    url_key = _canonical_url_key(url)
    if url_key in seen_urls:
        raise CulturalSignalError("cultural signal source URLs must be unique")
    seen_urls.add(url_key)
    source_kind = raw["source_kind"]
    if source_kind not in _SOURCE_KINDS:
        raise CulturalSignalError("cultural signal source_kind is invalid")
    platform = _strict_object(
        raw["platform"],
        expected={"name", "kind"},
        label="cultural signal source platform",
    )
    platform_kind = platform["kind"]
    if platform_kind not in _PLATFORM_KINDS:
        raise CulturalSignalError("cultural signal platform kind is invalid")
    published = _optional_timestamp(
        raw["published_at"],
        "source published_at",
    )
    observed = _optional_timestamp(
        raw["observed_at"],
        "source observed_at",
    )
    if published is None and observed is None:
        raise CulturalSignalError(
            "source requires published_at or observed_at"
        )
    if published is not None and observed is not None:
        raise CulturalSignalError(
            "source published_at and observed_at are mutually exclusive"
        )
    precision = raw["time_precision"]
    if precision not in _TIME_PRECISIONS:
        raise CulturalSignalError("source time_precision is invalid")
    if precision == "day" and (
        published is None or not published.endswith("T00:00:00Z")
    ):
        raise CulturalSignalError(
            "day-precision source published_at must use the UTC midnight anchor"
        )
    result = {
        "title": _text(raw["title"], "source title", max_chars=300),
        "url": url,
        "publisher": _text(
            raw["publisher"],
            "source publisher",
            max_chars=200,
        ),
        "source_kind": str(source_kind),
        "platform": {
            "name": _text(
                platform["name"],
                "source platform name",
                max_chars=160,
            ),
            "kind": str(platform_kind),
        },
        "published_at": published,
        "observed_at": observed,
        "time_precision": str(precision),
        "locale": _text(raw["locale"], "source locale", max_chars=40),
        "evidence_summary": _text(
            raw["evidence_summary"],
            "source evidence_summary",
            max_chars=1_000,
        ),
    }
    if include_retrieved_at:
        result["retrieved_at_utc"] = _timestamp_text(
            _timestamp(
                raw["retrieved_at_utc"],
                "source retrieved_at_utc",
            )
        )
    return result


def _safe_signal_projection(signal: Mapping[str, Any]) -> dict[str, str]:
    projected = {
        "signal_ref": str(signal["signal_id"]),
        "kind": str(signal["kind"]),
        "creative_role": str(signal["creative_role"]),
        "abstract_pattern": str(signal["abstract_pattern"]),
        "creative_tension": str(signal["creative_tension"]),
        "participation_shape": str(signal["participation_shape"]),
    }
    forbidden = (
        str(signal["label"]),
        *tuple(str(item) for item in signal["surface_markers_to_avoid"]),
    )
    for key in (
        "abstract_pattern",
        "creative_tension",
        "participation_shape",
    ):
        _safe_palette_text(projected[key], f"palette {key}")
        _reject_surface_copy(
            projected[key],
            forbidden=forbidden,
            label=f"palette {key}",
        )
    serialized = json.dumps(
        projected,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    for source in signal["sources"]:
        for forbidden_raw in (
            source["url"],
            source["title"],
            source["publisher"],
            source["platform"]["name"],
            source["evidence_summary"],
        ):
            if _contains_normalized_copy(
                serialized,
                str(forbidden_raw),
            ):
                raise CulturalSignalError(
                    "safe palette leaked raw source material"
                )
    return projected


def _signal_is_palette_eligible(
    signal: Mapping[str, Any],
    window: CulturalSignalWindow,
) -> bool:
    if signal["creative_role"] not in {"inspire", "avoid"}:
        return False
    if set(signal["safety_flags"]) != {"none"}:
        return False
    return any(_source_is_in_window(source, window) for source in signal["sources"])


def _source_is_in_window(
    source: Mapping[str, Any],
    window: CulturalSignalWindow,
) -> bool:
    for key in ("published_at", "observed_at"):
        value = source.get(key)
        if value is None:
            continue
        timestamp = _timestamp(value, f"source {key}")
        if window.start <= timestamp <= window.end:
            return True
    return False


def _rotated_take(
    values: Sequence[Mapping[str, Any]],
    offset: int,
    limit: int,
) -> tuple[Mapping[str, Any], ...]:
    if not values:
        return ()
    start = offset % len(values)
    rotated = (*values[start:], *values[:start])
    return tuple(rotated[: min(limit, len(rotated))])


def _safe_palette_text(value: Any, label: str) -> str:
    text = _text(value, label, max_chars=800)
    if _UNSAFE_SAFE_TEXT.search(text):
        raise CulturalSignalError(
            f"{label} contains a URL, handle, hashtag, link, or code fence"
        )
    return text


def _reject_surface_copy(
    value: str,
    *,
    forbidden: Sequence[str],
    label: str,
) -> None:
    for marker in forbidden:
        if _contains_normalized_copy(value, marker):
            raise CulturalSignalError(
                f"{label} copies a raw label or surface marker"
            )


def _contains_normalized_copy(value: str, candidate: str) -> bool:
    normalized_value = _normalized(value)
    normalized_candidate = _normalized(candidate)
    if not normalized_candidate:
        return False
    if len(normalized_candidate) >= 4:
        return normalized_candidate in normalized_value
    return (
        f" {normalized_candidate} "
        in f" {normalized_value} "
    )


def _strict_object(
    value: Any,
    *,
    expected: set[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CulturalSignalError(f"{label} must be an object")
    raw = dict(value)
    missing = sorted(expected - raw.keys())
    unknown = sorted(raw.keys() - expected)
    if missing:
        raise CulturalSignalError(f"{label} is missing fields: {missing}")
    if unknown:
        raise CulturalSignalError(f"{label} has unknown fields: {unknown}")
    return raw


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CulturalSignalError(f"{label} must be an object")
    return value


def _text(value: Any, label: str, *, max_chars: int = _MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CulturalSignalError(f"{label} must be a non-empty string")
    text = value.strip()
    if len(text) > max_chars:
        raise CulturalSignalError(f"{label} exceeds its text budget")
    return text


def _optional_text(
    value: Any,
    label: str,
    *,
    max_chars: int,
) -> str | None:
    if value is None:
        return None
    return _text(value, label, max_chars=max_chars)


def _text_list(
    value: Any,
    label: str,
    *,
    max_items: int,
    max_chars: int,
) -> list[str]:
    if not isinstance(value, list) or len(value) > max_items:
        raise CulturalSignalError(f"{label} must be a bounded array")
    result = [
        _text(item, f"{label} item", max_chars=max_chars)
        for item in value
    ]
    normalized = [_normalized(item) for item in result]
    if len(normalized) != len(set(normalized)):
        raise CulturalSignalError(f"{label} must not contain duplicates")
    return result


def _identifier(value: Any, label: str) -> str:
    text = _text(value, label, max_chars=256)
    if not _SAFE_ID.fullmatch(text):
        raise CulturalSignalError(f"{label} is not a safe identifier")
    return text


def _optional_identifier(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, label)


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise CulturalSignalError(f"{label} must be an RFC3339 timestamp")
    if _RFC3339_TIMESTAMP.fullmatch(value) is None:
        if _OFFSETLESS_TIMESTAMP_SHAPE.fullmatch(value) is not None:
            raise CulturalSignalError(f"{label} must include a timezone")
        raise CulturalSignalError(f"{label} must be an RFC3339 timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise CulturalSignalError(
            f"{label} must be an RFC3339 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise CulturalSignalError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def _optional_timestamp(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _timestamp_text(_timestamp(value, label))


def _timestamp_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _absolute_http_url(value: Any) -> str:
    text = _text(value, "source URL", max_chars=2_048)
    parsed = urlsplit(text)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise CulturalSignalError(
            "source URL must be an absolute credential-free HTTP(S) URL"
        )
    return text


def _canonical_url_key(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname.casefold() if parsed.hostname else ""
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise CulturalSignalError("source URL has an invalid port") from exc
    port = f":{parsed_port}" if parsed_port is not None else ""
    return (
        f"{parsed.scheme.casefold()}://{host}{port}"
        f"{parsed.path or '/'}?{parsed.query}"
    )


def _normalized(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"\w+", normalized, flags=re.UNICODE))


def _json_copy(value: Any) -> Any:
    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _json_text(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


__all__ = [
    "CULTURAL_SIGNAL_LOOKBACK_DAYS",
    "CULTURAL_SIGNAL_MAX_SIGNALS",
    "CULTURAL_SIGNAL_MAX_SOURCES",
    "CULTURAL_SIGNAL_PALETTE_SCHEMA_VERSION",
    "CULTURAL_SIGNAL_RFC3339_TIMESTAMP_PATTERN",
    "CULTURAL_SIGNAL_SNAPSHOT_ARTIFACT_ID",
    "CULTURAL_SIGNAL_SNAPSHOT_ARTIFACT_TYPE",
    "CULTURAL_SIGNAL_SNAPSHOT_RELATIVE_PATH",
    "CULTURAL_SIGNAL_SNAPSHOT_SCHEMA_VERSION",
    "CulturalSignalError",
    "CulturalSignalSnapshot",
    "CulturalSignalWindow",
    "build_cultural_signal_snapshot",
    "cultural_signal_palette",
    "cultural_signal_window",
    "cultural_signal_window_prompt",
    "render_cultural_signal_palette",
    "unavailable_cultural_signal_snapshot",
    "validate_cultural_signal_agent_output",
    "validate_cultural_signal_palette",
]
