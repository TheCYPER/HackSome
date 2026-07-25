"""Creative Markdown composers and stage-envelope semantic validation."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import Any, NotRequired, TypedDict, cast
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from hacksome.artifacts import (
    ArtifactError,
    section_body,
    title_of,
    validate_markdown,
)
from hacksome.creative.contracts import (
    C0_CHALLENGE_PARSE,
    C1_BRIEF_NORMALIZE,
    C2_TERRITORY_EXPLORE,
    C3_CONCEPT_SYNTHESIZE,
    C4_CHEAP_HOOK_REPAIR,
    C4_CHEAP_HOOK_REVIEW,
    C4_SOFTWARE_DEMO_REVIEW,
    C5M_MEMORY_RECALL,
    C5M_MEMORY_REMIX,
    C5W_NOVELTY_SCAN,
    C6A_EVIDENCE_REVISE,
    C6B_PORTFOLIO_CURATE,
    C6C_FEEDBACK_REVISE,
    CREATIVE_CONTRACT_VERSION,
    CREATIVE_STAGES,
    CreativeWorkflowSettings,
    LEGACY_CREATIVE_CONTRACT_VERSION,
    StableReasonCode,
    SUPPORTED_CREATIVE_CONTRACT_VERSIONS,
    parse_concept_revision_ref,
    territory_for_atom,
)


CHALLENGE_BRIEF_HEADINGS = (
    "Challenge Summary",
    "Judging Context",
    "Sponsor and Technology Context",
    "Ambiguities",
)
CONSTRAINT_VIEW_HEADINGS = (
    "Hard Rules",
    "Required Technology",
    "Data and Permission Boundaries",
    "Time, Team and Deliverables",
    "Open Questions",
)
LEGACY_CREATIVE_BRIEF_HEADINGS = (
    "Intended Reactions",
    "Anti-goals",
    "Audience and Experience Context",
    "Thirty-second Reveal Window",
    "Available Media and Boundaries",
    "Default Assumptions",
)
CREATIVE_BRIEF_HEADINGS = (
    *LEGACY_CREATIVE_BRIEF_HEADINGS,
    "Software and Demo Boundaries",
)
LEGACY_ATOM_HEADINGS = (
    "Territory",
    "Trigger",
    "Audience Action",
    "Mechanism",
    "Transformation",
    "Reveal",
    "Aftertaste",
    "Challenge Fit and Risks",
)
ATOM_HEADINGS = (
    *LEGACY_ATOM_HEADINGS[:-1],
    "Software Surface and Demo Proof",
    LEGACY_ATOM_HEADINGS[-1],
)
LEGACY_CONCEPT_HEADINGS = (
    "Intended Reaction",
    "One-sentence Hook",
    "First Impression",
    "Audience Action",
    "Setup, Reveal and Aftertaste",
    "Real Input, Transformation and Output",
    "Why It Is Unexpected Yet Legible",
    "Minimum Hackathon Demo",
    "Assumptions, Confusion and Risks",
    "Parent Atoms",
)
CONCEPT_HEADINGS = (
    "Intended Reaction",
    "One-sentence Hook",
    "First Impression",
    "Audience Action",
    "Setup, Reveal and Aftertaste",
    "Real Input, Transformation and Output",
    "Software Core and Runtime",
    "Share Trigger and Artifact",
    "Why It Is Unexpected Yet Legible",
    "Minimum Hackathon Demo",
    "Assumptions, Confusion and Risks",
    "Parent Atoms",
)
MEMORY_REMIX_HEADINGS = (
    "Current Atom Sources",
    "Past Inspiration Used",
    "What Was Transformed",
    "Why This Is Not A Copy",
)
NOVELTY_SCAN_HEADINGS = (
    "Search Strategy",
    "Direct and Near Collisions",
    "Common Tropes and AI Smell",
    "Distinctive Combination",
    "Cultural and Safety References",
    "Counterevidence and Uncertainty",
)
EVIDENCE_REVISION_HEADINGS = (
    "Evidence-informed Changes",
    "Evidence Deliberately Not Adopted",
)
FEEDBACK_REVISION_HEADINGS = (
    "Feedback Adopted",
    "Feedback Rejected or Conflicting",
    "Unresolved Risks",
)
FINAL_IDEA_CARD_HEADINGS = (
    "Intended Reaction",
    "One-sentence Hook",
    "First Thirty Seconds",
    "Audience Action",
    "Core Mechanism",
    "Reveal and Aftertaste",
    "Minimum Hackathon Demo",
    "Why Someone May Share It",
    "Novelty and References",
    "Human Signal",
    "Risks and Unresolved Disagreement",
    "Lineage",
)

LEGACY_HOOK_DIMENSIONS = (
    "setup_legibility",
    "expectation_shift",
    "mechanism_driven_surprise",
    "thirty_second_moment",
    "one_sentence_retell",
    "capability_integrity",
)
HOOK_DIMENSIONS = (
    *LEGACY_HOOK_DIMENSIONS,
    "share_trigger",
)
HOOK_REASON_BY_DIMENSION: Mapping[str, str] = {
    "setup_legibility": StableReasonCode.SETUP_NOT_QUICKLY_LEGIBLE.value,
    "expectation_shift": StableReasonCode.REVEAL_DOES_NOT_SHIFT_EXPECTATION.value,
    "mechanism_driven_surprise": (
        StableReasonCode.SURPRISE_NOT_MECHANISM_DRIVEN.value
    ),
    "thirty_second_moment": StableReasonCode.MISSES_THIRTY_SECOND_MOMENT.value,
    "one_sentence_retell": StableReasonCode.NOT_ONE_SENTENCE_RETAINABLE.value,
    "capability_integrity": (
        StableReasonCode.REQUIRES_HIDDEN_LABOR_OR_IMPOSSIBLE_CAPABILITY.value
    ),
    "share_trigger": (
        StableReasonCode.SHARE_TRIGGER_NOT_IMMEDIATE_OR_CONCRETE.value
    ),
}

SOFTWARE_DEMO_DIMENSIONS = (
    "software_first_core",
    "hardware_independence",
    "technical_demo_substance",
    "end_to_end_demo_path",
    "dependency_integrity",
    "hackathon_scope",
    "core_proof",
)
SOFTWARE_DEMO_REASON_BY_DIMENSION: Mapping[str, str] = {
    "software_first_core": StableReasonCode.CORE_NOT_SOFTWARE_FIRST.value,
    "hardware_independence": (
        StableReasonCode.REQUIRES_CUSTOM_HARDWARE_OR_FABRICATION.value
    ),
    "technical_demo_substance": (
        StableReasonCode.CORE_IS_MANUAL_PERFORMANCE_OR_INSTALLATION.value
    ),
    "end_to_end_demo_path": (
        StableReasonCode.NO_RUNNABLE_END_TO_END_DEMO_PATH.value
    ),
    "dependency_integrity": (
        StableReasonCode.REQUIRES_UNAVAILABLE_DEPENDENCY_OR_PERMISSION.value
    ),
    "hackathon_scope": (
        StableReasonCode.NOT_BUILDABLE_WITHIN_HACKATHON_BUDGET.value
    ),
    "core_proof": StableReasonCode.DEMO_DOES_NOT_PROVE_CORE_MECHANISM.value,
}

PORTFOLIO_DIMENSIONS = (
    "software_demo_strength",
    "surprise_fun_or_intrigue",
    "one_sentence_clarity",
    "immediate_share_trigger",
    "novel_combination",
)


class CreativeArtifactError(ArtifactError):
    """A Creative model envelope is not safe to publish."""


class CreativeValidationContext(TypedDict):
    """Optional cross-artifact facts supplied by the route controller."""

    allowed_atom_refs: NotRequired[Collection[str]]
    allowed_cue_refs: NotRequired[Collection[str]]
    allowed_concept_refs: NotRequired[Collection[str]]
    atom_territories: NotRequired[Mapping[str, str]]
    memory_cues: NotRequired[Sequence[Any]]
    memory_snapshot: NotRequired[Any]
    expected_primary_territory_ref: NotRequired[str]
    allowed_primary_territory_refs: NotRequired[Collection[str]]
    source_markdown: NotRequired[str]
    source_hooks: NotRequired[Collection[str]]
    source_mechanism_reveals: NotRequired[Collection[tuple[str, str]]]
    contract_version: NotRequired[str]


_ATOM_REF = re.compile(r"creative-atom-t[0-9]{2}-[0-9]{2}")
_CONCEPT_REF = re.compile(
    r"creative-concept-(?:s[0-9]{2}-[0-9]{2}|m[0-9]{2})-r[0-9]{3}"
)


def validate_creative_output(
    stage: str,
    output: Mapping[str, Any],
    *,
    settings: CreativeWorkflowSettings,
    context: CreativeValidationContext | None = None,
    contract_version: str = CREATIVE_CONTRACT_VERSION,
    schema_path: Path | None = None,
) -> dict[str, Any]:
    """Validate one schema-constrained envelope plus route semantic invariants."""

    if contract_version not in SUPPORTED_CREATIVE_CONTRACT_VERSIONS:
        raise CreativeArtifactError(
            f"unsupported Creative contract version: {contract_version!r}"
        )
    if stage not in CREATIVE_STAGES or (
        contract_version == LEGACY_CREATIVE_CONTRACT_VERSION
        and stage == C4_SOFTWARE_DEMO_REVIEW
    ):
        raise CreativeArtifactError(f"unknown Creative stage: {stage!r}")
    if not isinstance(settings, CreativeWorkflowSettings):
        raise TypeError("settings must be CreativeWorkflowSettings")
    normalized = _normalize_json_object(output)
    _validate_stage_schema(
        stage,
        normalized,
        contract_version=contract_version,
        schema_path=schema_path,
    )
    validator = _STAGE_VALIDATORS[stage]
    validation_context = cast(
        CreativeValidationContext,
        dict(context or {}),
    )
    validation_context["contract_version"] = contract_version
    try:
        validator(normalized, settings, validation_context)
    except CreativeArtifactError:
        raise
    except ArtifactError as exc:
        raise CreativeArtifactError(str(exc)) from exc
    return normalized


def normalized_section(markdown: str, heading: str) -> str:
    """Normalize one validated section for deterministic identity comparisons."""

    return _normalize_text(section_body(markdown, heading))


def normalized_hook(markdown: str) -> str:
    return normalized_section(markdown, "One-sentence Hook")


def compose_final_idea_card(
    *,
    title: str,
    sections: Mapping[str, str],
) -> str:
    """Compose a deterministic final card from already validated controller text."""

    if not isinstance(title, str) or not title.strip():
        raise CreativeArtifactError("Final Idea title must not be empty")
    expected = set(FINAL_IDEA_CARD_HEADINGS)
    missing = sorted(expected - set(sections))
    unknown = sorted(set(sections) - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise CreativeArtifactError(
            "Final Idea Card section mismatch (" + "; ".join(details) + ")"
        )
    lines = [f"# {title.strip()}", ""]
    for heading in FINAL_IDEA_CARD_HEADINGS:
        body = sections[heading]
        if not isinstance(body, str) or not body.strip():
            raise CreativeArtifactError(
                f"Final Idea Card section {heading!r} must not be empty"
            )
        lines.extend((f"## {heading}", "", body.strip(), ""))
    card = "\n".join(lines)
    validate_markdown(
        card,
        required_h2=FINAL_IDEA_CARD_HEADINGS,
        label="Final Creative Idea Card",
    )
    return card


def _normalize_json_object(output: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(output, Mapping):
        raise CreativeArtifactError("Creative output must be a JSON object")
    try:
        normalized = json.loads(
            json.dumps(
                dict(output),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    except (TypeError, ValueError) as exc:
        raise CreativeArtifactError(f"Creative output is not strict JSON: {exc}") from exc
    if not isinstance(normalized, dict):
        raise CreativeArtifactError("Creative output must be a JSON object")
    return cast(dict[str, Any], normalized)


def _validate_stage_schema(
    stage: str,
    output: Mapping[str, Any],
    *,
    contract_version: str,
    schema_path: Path | None,
) -> None:
    from hacksome.creative.prompting import creative_prompt_catalog_for_contract

    path = (
        schema_path
        if schema_path is not None
        else creative_prompt_catalog_for_contract(contract_version)[stage].schema_path
    )
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CreativeArtifactError(
            f"Creative schema for {stage} cannot be loaded: {exc}"
        ) from exc
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(output), key=lambda error: list(error.path))
    if not errors:
        return
    error = errors[0]
    location = ".".join(str(part) for part in error.absolute_path)
    suffix = f" at {location}" if location else ""
    raise CreativeArtifactError(
        f"{stage} output failed JSON Schema{suffix}: {error.message}"
    )


def _validate_c0(
    output: dict[str, Any],
    settings: CreativeWorkflowSettings,
    context: CreativeValidationContext,
) -> None:
    del settings, context
    validate_markdown(
        output["challenge_brief_markdown"],
        required_h2=CHALLENGE_BRIEF_HEADINGS,
        label="Creative Challenge Brief",
    )
    validate_markdown(
        output["constraint_view_markdown"],
        required_h2=CONSTRAINT_VIEW_HEADINGS,
        label="Creative Constraint View",
    )


def _validate_c1(
    output: dict[str, Any],
    settings: CreativeWorkflowSettings,
    context: CreativeValidationContext,
) -> None:
    del settings
    headings = (
        LEGACY_CREATIVE_BRIEF_HEADINGS
        if _is_legacy(context)
        else CREATIVE_BRIEF_HEADINGS
    )
    validate_markdown(
        output["markdown"],
        required_h2=headings,
        label="Creative Brief",
    )


def _validate_c2(
    output: dict[str, Any],
    settings: CreativeWorkflowSettings,
    context: CreativeValidationContext,
) -> None:
    headings = LEGACY_ATOM_HEADINGS if _is_legacy(context) else ATOM_HEADINGS
    validate_markdown(output["territory_markdown"], label="Creative Territory")
    atoms = output["atoms"]
    if len(atoms) > settings.max_atoms_per_territory:
        raise CreativeArtifactError(
            "Territory exceeds configured max_atoms_per_territory"
        )
    seen: set[str] = set()
    for index, atom in enumerate(atoms):
        markdown = atom["markdown"]
        validate_markdown(
            markdown,
            required_h2=headings,
            label=f"Creative Atom {index + 1}",
        )
        normalized = _normalize_text(markdown)
        if normalized in seen:
            raise CreativeArtifactError("Territory contains duplicate Atom Markdown")
        seen.add(normalized)


def _validate_c3(
    output: dict[str, Any],
    settings: CreativeWorkflowSettings,
    context: CreativeValidationContext,
) -> None:
    headings = LEGACY_CONCEPT_HEADINGS if _is_legacy(context) else CONCEPT_HEADINGS
    concepts = output["concepts"]
    if len(concepts) > settings.max_concepts_per_synthesizer:
        raise CreativeArtifactError(
            "Concept output exceeds configured max_concepts_per_synthesizer"
        )
    allowed_atoms = _optional_allowed(context, "allowed_atom_refs")
    markdown_seen: set[str] = set()
    hook_seen: set[str] = set()
    for index, concept in enumerate(concepts):
        markdown = concept["markdown"]
        validate_markdown(
            markdown,
            required_h2=headings,
            label=f"Creative Concept {index + 1}",
        )
        parent_refs = _unique_string_list(
            concept["parent_atom_refs"],
            label=f"Concept {index + 1} parent_atom_refs",
        )
        if allowed_atoms is not None and not set(parent_refs).issubset(allowed_atoms):
            raise CreativeArtifactError("Concept cites an unknown Parent Atom ref")
        _validate_parent_territory(
            primary_territory_ref=concept["primary_territory_ref"],
            parent_atom_refs=parent_refs,
        )
        section_refs = set(_ATOM_REF.findall(section_body(markdown, "Parent Atoms")))
        if section_refs != set(parent_refs):
            raise CreativeArtifactError(
                "Concept Parent Atoms section and parent_atom_refs must match exactly"
            )
        normalized = _normalize_text(markdown)
        hook = normalized_hook(markdown)
        if normalized in markdown_seen or hook in hook_seen:
            raise CreativeArtifactError(
                "Concept output contains an exact or normalized-Hook duplicate"
            )
        markdown_seen.add(normalized)
        hook_seen.add(hook)


def _validate_c4_review(
    output: dict[str, Any],
    settings: CreativeWorkflowSettings,
    context: CreativeValidationContext,
) -> None:
    del settings
    validate_markdown(output["markdown"], label="Cheap Hook Review")
    dimensions = output["dimensions"]
    names = tuple(item["dimension"] for item in dimensions)
    expected_dimensions = (
        LEGACY_HOOK_DIMENSIONS if _is_legacy(context) else HOOK_DIMENSIONS
    )
    if names != expected_dimensions:
        raise CreativeArtifactError(
            "Cheap Hook dimensions must appear once in the stable contract order"
        )
    all_pass = True
    for item in dimensions:
        verdict = item["verdict"]
        reason_code = item["reason_code"]
        expected_reason = HOOK_REASON_BY_DIMENSION[item["dimension"]]
        if verdict == "pass":
            if reason_code is not None:
                raise CreativeArtifactError(
                    "passing Hook dimensions must use a null reason_code"
                )
        else:
            all_pass = False
            if reason_code != expected_reason:
                raise CreativeArtifactError(
                    f"{item['dimension']} must use reason code {expected_reason}"
                )
    if (output["overall_decision"] == "pass") is not all_pass:
        raise CreativeArtifactError(
            "overall_decision=pass must match all passing Hook dimensions"
        )


def _validate_c4_software_demo_review(
    output: dict[str, Any],
    settings: CreativeWorkflowSettings,
    context: CreativeValidationContext,
) -> None:
    del settings
    if _is_legacy(context):
        raise CreativeArtifactError("C4F does not exist in Creative contract v1")
    validate_markdown(output["markdown"], label="Software Demo Review")
    dimensions = output["dimensions"]
    names = tuple(item["dimension"] for item in dimensions)
    if names != SOFTWARE_DEMO_DIMENSIONS:
        raise CreativeArtifactError(
            "Software Demo dimensions must appear once in stable contract order"
        )
    all_pass = True
    hard_failure = False
    has_non_pass = False
    has_fail = False
    for item in dimensions:
        verdict = item["verdict"]
        reason_code = item["reason_code"]
        expected_reason = SOFTWARE_DEMO_REASON_BY_DIMENSION[item["dimension"]]
        if verdict == "pass":
            if reason_code is not None:
                raise CreativeArtifactError(
                    "passing Software Demo dimensions require null reason_code"
                )
        else:
            all_pass = False
            has_non_pass = True
            has_fail = has_fail or verdict == "fail"
            if reason_code != expected_reason:
                raise CreativeArtifactError(
                    f"{item['dimension']} must use reason code {expected_reason}"
                )
            if verdict == "fail" and item["dimension"] in {
                "software_first_core",
                "hardware_independence",
                "technical_demo_substance",
                "dependency_integrity",
            }:
                hard_failure = True
    decision = output["overall_decision"]
    if (decision == "pass") is not all_pass:
        raise CreativeArtifactError(
            "overall_decision=pass must match all passing Software Demo dimensions"
        )
    if decision == "repairable" and not has_non_pass:
        raise CreativeArtifactError(
            "overall_decision=repairable requires a non-passing dimension"
        )
    if decision == "invalid" and not has_fail:
        raise CreativeArtifactError(
            "overall_decision=invalid requires a failed dimension"
        )
    if hard_failure and decision != "invalid":
        raise CreativeArtifactError(
            "hard Software Demo failures require overall_decision=invalid"
        )


def _validate_c4_repair(
    output: dict[str, Any],
    settings: CreativeWorkflowSettings,
    context: CreativeValidationContext,
) -> None:
    if settings.max_hook_repairs < 1:
        raise CreativeArtifactError("C4 repair is disabled by max_hook_repairs")
    markdown = output["markdown"]
    headings = LEGACY_CONCEPT_HEADINGS if _is_legacy(context) else CONCEPT_HEADINGS
    validate_markdown(
        markdown,
        required_h2=headings,
        label="Hook-repaired Concept",
    )
    _validate_source_preservation(
        markdown,
        context,
        headings=(
            "Intended Reaction",
            "Real Input, Transformation and Output",
            "Parent Atoms",
        ),
    )


def _validate_memory_recall(
    output: dict[str, Any],
    settings: CreativeWorkflowSettings,
    context: CreativeValidationContext,
) -> None:
    cues = output["cues"]
    if len(cues) > settings.max_memory_selected_cues:
        raise CreativeArtifactError(
            "Memory Recall exceeds configured max_memory_selected_cues"
        )
    reason = output["no_relevant_memory_reason"]
    if cues and reason is not None:
        raise CreativeArtifactError(
            "non-empty Memory cues require null no_relevant_memory_reason"
        )
    if not cues and (not isinstance(reason, str) or not reason.strip()):
        raise CreativeArtifactError(
            "empty Memory cues require no_relevant_memory_reason"
        )
    allowed_atoms = _optional_allowed(context, "allowed_atom_refs")
    allowed_concepts = _optional_allowed(context, "allowed_concept_refs")
    snapshot = context.get("memory_snapshot")
    if snapshot is not None and allowed_atoms is not None:
        from hacksome.creative.memory import (
            MemoryValidationError,
            validate_memory_inspiration_packet,
        )

        try:
            validate_memory_inspiration_packet(
                output,
                snapshot=snapshot,
                current_atom_refs=tuple(sorted(allowed_atoms)),
                related_concept_refs=tuple(sorted(allowed_concepts or ())),
                max_cues=settings.max_memory_selected_cues,
            )
        except MemoryValidationError as exc:
            raise CreativeArtifactError(str(exc)) from exc
        return
    cue_ids: list[str] = []
    for cue in cues:
        cue_ids.append(cue["cue_id"])
        atom_refs = _unique_string_list(
            cue["current_atom_refs"], label="Memory cue current_atom_refs"
        )
        _memory_capsule_refs(
            cue["source_memory_refs"], label="Memory cue source_memory_refs"
        )
        concept_refs = _unique_string_list(
            cue["related_concept_refs"], label="Memory cue related_concept_refs"
        )
        _require_subset(atom_refs, allowed_atoms, label="current Atom")
        _require_subset(concept_refs, allowed_concepts, label="related Concept")
    if len(cue_ids) != len(set(cue_ids)):
        raise CreativeArtifactError("Memory cue IDs must not repeat")


def _validate_memory_remix(
    output: dict[str, Any],
    settings: CreativeWorkflowSettings,
    context: CreativeValidationContext,
) -> None:
    if settings.memory_remixers < 1 or settings.max_memory_challengers < 1:
        if output["concept"] is not None:
            raise CreativeArtifactError("Memory Remix is disabled by settings")
        return
    concept = output["concept"]
    if concept is None:
        return
    markdown = concept["markdown"]
    validate_markdown(
        markdown,
        required_h2=(
            (LEGACY_CONCEPT_HEADINGS if _is_legacy(context) else CONCEPT_HEADINGS)
            + MEMORY_REMIX_HEADINGS
        ),
        label="Memory challenger",
    )
    atom_refs = _unique_string_list(
        concept["current_atom_refs"], label="challenger current_atom_refs"
    )
    memory_refs = _memory_capsule_refs(
        concept["memory_source_refs"], label="challenger memory_source_refs"
    )
    cue_refs = _unique_string_list(
        concept["cue_refs"], label="challenger cue_refs"
    )
    _require_subset(
        atom_refs,
        _optional_allowed(context, "allowed_atom_refs"),
        label="current Atom",
    )
    _require_subset(
        cue_refs,
        _optional_allowed(context, "allowed_cue_refs"),
        label="Memory cue",
    )
    _validate_parent_territory(
        primary_territory_ref=concept["primary_territory_ref"],
        parent_atom_refs=atom_refs,
    )
    snapshot = context.get("memory_snapshot")
    memory_cues = context.get("memory_cues")
    atom_territories = context.get("atom_territories")
    if (
        snapshot is not None
        and memory_cues is not None
        and atom_territories is not None
    ):
        from hacksome.creative.memory import (
            MemoryValidationError,
            validate_remix_provenance,
        )

        try:
            validate_remix_provenance(
                current_atom_refs=atom_refs,
                memory_source_refs=memory_refs,
                cue_refs=cue_refs,
                primary_territory_ref=concept["primary_territory_ref"],
                atom_territories=atom_territories,
                snapshot=snapshot,
                cues=memory_cues,
            )
        except MemoryValidationError as exc:
            raise CreativeArtifactError(str(exc)) from exc
    section_refs = set(_ATOM_REF.findall(section_body(markdown, "Parent Atoms")))
    if section_refs != set(atom_refs):
        raise CreativeArtifactError(
            "challenger Parent Atoms section must match current_atom_refs"
        )
    hook = normalized_hook(markdown)
    source_hooks = context.get("source_hooks", ())
    if hook in {_normalize_text(value) for value in source_hooks}:
        raise CreativeArtifactError("challenger duplicates a source normalized Hook")
    mechanism_reveal = (
        normalized_section(markdown, "Real Input, Transformation and Output"),
        normalized_section(markdown, "Setup, Reveal and Aftertaste"),
    )
    source_pairs = {
        (_normalize_text(mechanism), _normalize_text(reveal))
        for mechanism, reveal in context.get("source_mechanism_reveals", ())
    }
    if mechanism_reveal in source_pairs:
        raise CreativeArtifactError(
            "challenger directly copies a source mechanism-and-reveal pair"
        )


def _validate_novelty(
    output: dict[str, Any],
    settings: CreativeWorkflowSettings,
    context: CreativeValidationContext,
) -> None:
    del settings, context
    validate_markdown(
        output["markdown"],
        required_h2=NOVELTY_SCAN_HEADINGS,
        label="Novelty Scan",
    )
    seen_urls: set[str] = set()
    for source in output["sources"]:
        url = source["url"]
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise CreativeArtifactError(
                f"Novelty source URL must be absolute HTTP(S): {url!r}"
            )
        if parsed.username is not None or parsed.password is not None:
            raise CreativeArtifactError("Novelty source URL must not embed credentials")
        if url in seen_urls:
            raise CreativeArtifactError("Novelty source URLs must not repeat")
        seen_urls.add(url)


def _validate_evidence_revision(
    output: dict[str, Any],
    settings: CreativeWorkflowSettings,
    context: CreativeValidationContext,
) -> None:
    del settings
    markdown = output["markdown"]
    validate_markdown(
        markdown,
        required_h2=(
            (LEGACY_CONCEPT_HEADINGS if _is_legacy(context) else CONCEPT_HEADINGS)
            + EVIDENCE_REVISION_HEADINGS
        ),
        label="Evidence-informed Concept",
    )
    _validate_source_preservation(
        markdown,
        context,
        headings=(
            "Intended Reaction",
            "Real Input, Transformation and Output",
            "Parent Atoms",
        ),
    )


def _validate_portfolio(
    output: dict[str, Any],
    settings: CreativeWorkflowSettings,
    context: CreativeValidationContext,
) -> None:
    del settings
    classifications = output["classifications"]
    refs = [item["concept_ref"] for item in classifications]
    if len(refs) != len(set(refs)):
        raise CreativeArtifactError("Portfolio classifications must not repeat a ref")
    allowed = _optional_allowed(context, "allowed_concept_refs")
    if allowed is not None and set(refs) != allowed:
        raise CreativeArtifactError(
            "Portfolio classifications must cover every allowed Concept exactly once"
        )
    for item in classifications:
        if not _is_legacy(context):
            dimensions = item["dimensions"]
            names = tuple(dimension["dimension"] for dimension in dimensions)
            if names != PORTFOLIO_DIMENSIONS:
                raise CreativeArtifactError(
                    "Portfolio dimensions must appear once in stable contract order"
                )
            verdicts = tuple(dimension["verdict"] for dimension in dimensions)
            expected_decision = (
                "exclude"
                if "fail" in verdicts
                else "hold"
                if "uncertain" in verdicts
                else "include"
            )
            if item["decision"] != expected_decision:
                raise CreativeArtifactError(
                    "Portfolio decision must mechanically match categorical dimensions"
                )
        possible = _unique_string_list(
            item["possible_duplicate_refs"],
            label="possible_duplicate_refs",
        )
        if item["concept_ref"] in possible:
            raise CreativeArtifactError("a Concept cannot duplicate itself")
        _require_subset(possible, allowed, label="possible duplicate Concept")
        for reference in (item["concept_ref"], *possible):
            parse_concept_revision_ref(reference)


def _validate_feedback_revision(
    output: dict[str, Any],
    settings: CreativeWorkflowSettings,
    context: CreativeValidationContext,
) -> None:
    if settings.max_feedback_revisions < 1:
        raise CreativeArtifactError(
            "C6C feedback revision is disabled by max_feedback_revisions"
        )
    markdown = output["markdown"]
    validate_markdown(
        markdown,
        required_h2=(
            (LEGACY_CONCEPT_HEADINGS if _is_legacy(context) else CONCEPT_HEADINGS)
            + FEEDBACK_REVISION_HEADINGS
        ),
        label="Feedback-revised Final Idea",
    )
    primary = output["primary_territory_ref"]
    expected = context.get("expected_primary_territory_ref")
    allowed = _optional_allowed(context, "allowed_primary_territory_refs")
    if expected is not None and primary != expected:
        raise CreativeArtifactError(
            "feedback revision must preserve the source primary Territory"
        )
    if allowed is not None and primary not in allowed:
        raise CreativeArtifactError(
            "merged Final Idea primary Territory must come from a source"
        )


def _validate_parent_territory(
    *,
    primary_territory_ref: str,
    parent_atom_refs: Sequence[str],
) -> None:
    try:
        territories = {territory_for_atom(reference) for reference in parent_atom_refs}
    except ValueError as exc:
        raise CreativeArtifactError(str(exc)) from exc
    if primary_territory_ref not in territories:
        raise CreativeArtifactError(
            "primary_territory_ref must belong to a current Parent Atom"
        )


def _validate_source_preservation(
    markdown: str,
    context: CreativeValidationContext,
    *,
    headings: Sequence[str],
) -> None:
    source = context.get("source_markdown")
    if source is None:
        return
    for heading in headings:
        if normalized_section(markdown, heading) != normalized_section(source, heading):
            raise CreativeArtifactError(
                f"bounded revision must preserve source section {heading!r}"
            )


def _optional_allowed(
    context: CreativeValidationContext,
    key: str,
) -> set[str] | None:
    raw = context.get(key)  # type: ignore[literal-required]
    if raw is None:
        return None
    return {str(value) for value in cast(Collection[object], raw)}


def _require_subset(
    values: Collection[str],
    allowed: set[str] | None,
    *,
    label: str,
) -> None:
    if allowed is not None and not set(values).issubset(allowed):
        raise CreativeArtifactError(f"output cites an unknown {label} ref")


def _unique_string_list(values: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(values, list):
        raise CreativeArtifactError(f"{label} must be a JSON array")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise CreativeArtifactError(f"{label} must contain non-empty strings")
    normalized = tuple(cast(list[str], values))
    if len(normalized) != len(set(normalized)):
        raise CreativeArtifactError(f"{label} must not contain duplicates")
    return normalized


def _memory_capsule_refs(values: object, *, label: str) -> tuple[Any, ...]:
    from hacksome.creative.memory import MemoryCapsuleRef, MemoryValidationError

    if not isinstance(values, list) or not values:
        raise CreativeArtifactError(f"{label} must be a non-empty JSON array")
    try:
        references = tuple(MemoryCapsuleRef.from_mapping(value) for value in values)
    except MemoryValidationError as exc:
        raise CreativeArtifactError(f"{label}: {exc}") from exc
    stable_keys = tuple(reference.stable_key for reference in references)
    if len(stable_keys) != len(set(stable_keys)):
        raise CreativeArtifactError(f"{label} must not contain duplicates")
    return references


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"\w+", normalized, flags=re.UNICODE))


def _is_legacy(context: CreativeValidationContext) -> bool:
    return context.get("contract_version") == LEGACY_CREATIVE_CONTRACT_VERSION


_STAGE_VALIDATORS = {
    C0_CHALLENGE_PARSE: _validate_c0,
    C1_BRIEF_NORMALIZE: _validate_c1,
    C2_TERRITORY_EXPLORE: _validate_c2,
    C3_CONCEPT_SYNTHESIZE: _validate_c3,
    C4_CHEAP_HOOK_REVIEW: _validate_c4_review,
    C4_SOFTWARE_DEMO_REVIEW: _validate_c4_software_demo_review,
    C4_CHEAP_HOOK_REPAIR: _validate_c4_repair,
    C5M_MEMORY_RECALL: _validate_memory_recall,
    C5M_MEMORY_REMIX: _validate_memory_remix,
    C5W_NOVELTY_SCAN: _validate_novelty,
    C6A_EVIDENCE_REVISE: _validate_evidence_revision,
    C6B_PORTFOLIO_CURATE: _validate_portfolio,
    C6C_FEEDBACK_REVISE: _validate_feedback_revision,
}


__all__ = [
    "ATOM_HEADINGS",
    "CHALLENGE_BRIEF_HEADINGS",
    "CONCEPT_HEADINGS",
    "CONSTRAINT_VIEW_HEADINGS",
    "CREATIVE_BRIEF_HEADINGS",
    "CreativeArtifactError",
    "CreativeValidationContext",
    "EVIDENCE_REVISION_HEADINGS",
    "FEEDBACK_REVISION_HEADINGS",
    "FINAL_IDEA_CARD_HEADINGS",
    "HOOK_DIMENSIONS",
    "HOOK_REASON_BY_DIMENSION",
    "LEGACY_ATOM_HEADINGS",
    "LEGACY_CONCEPT_HEADINGS",
    "LEGACY_CREATIVE_BRIEF_HEADINGS",
    "MEMORY_REMIX_HEADINGS",
    "NOVELTY_SCAN_HEADINGS",
    "PORTFOLIO_DIMENSIONS",
    "SOFTWARE_DEMO_DIMENSIONS",
    "SOFTWARE_DEMO_REASON_BY_DIMENSION",
    "compose_final_idea_card",
    "normalized_hook",
    "normalized_section",
    "section_body",
    "title_of",
    "validate_creative_output",
]
