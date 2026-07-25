"""Versioned PromptCatalog for every model-backed Creative stage."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

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
    LEGACY_CREATIVE_CONTRACT_VERSION,
    CreativeWorkflowSettings,
)
from hacksome.prompting import PromptCatalog, PromptSpec


_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_PROMPT_DIR = _PACKAGE_ROOT / "prompts" / "creative"
_SCHEMA_DIR = _PACKAGE_ROOT / "schemas" / "creative"


def _spec(
    stage: str,
    *,
    version: str = "2",
    web_search: bool = False,
) -> PromptSpec:
    short_name = stage.removeprefix("creative-")
    return PromptSpec(
        stage=stage,
        template_id=f"hacksome.creative.{short_name}",
        version=version,
        template_path=_PROMPT_DIR / f"{stage}.md",
        schema_path=_SCHEMA_DIR / f"{stage}.schema.json",
        web_search=web_search,
    )


creative_prompt_catalog = PromptCatalog(
    (
        _spec(C0_CHALLENGE_PARSE),
        _spec(C1_BRIEF_NORMALIZE),
        _spec(C2_TERRITORY_EXPLORE),
        _spec(C3_CONCEPT_SYNTHESIZE, version="5"),
        _spec(C4_CHEAP_HOOK_REVIEW, version="3"),
        _spec(C4_SOFTWARE_DEMO_REVIEW, version="4"),
        _spec(C4_CHEAP_HOOK_REPAIR, version="3"),
        _spec(C5M_MEMORY_RECALL),
        _spec(C5M_MEMORY_REMIX),
        _spec(C5W_NOVELTY_SCAN, web_search=True),
        _spec(C6A_EVIDENCE_REVISE, version="4"),
        _spec(C6B_PORTFOLIO_CURATE, version="4"),
        _spec(C6C_FEEDBACK_REVISE),
    ),
    compatible_template_versions={
        C3_CONCEPT_SYNTHESIZE: ("2", "3", "4"),
        C4_CHEAP_HOOK_REVIEW: ("2",),
        C4_SOFTWARE_DEMO_REVIEW: ("2", "3"),
        C4_CHEAP_HOOK_REPAIR: ("2",),
        C6A_EVIDENCE_REVISE: ("2", "3"),
        C6B_PORTFOLIO_CURATE: ("2", "3"),
    },
)


legacy_creative_prompt_catalog = PromptCatalog(
    (
        _spec(C0_CHALLENGE_PARSE, version="1"),
        _spec(C1_BRIEF_NORMALIZE, version="1"),
        _spec(C2_TERRITORY_EXPLORE, version="1"),
        _spec(C3_CONCEPT_SYNTHESIZE, version="1"),
        _spec(C4_CHEAP_HOOK_REVIEW, version="1"),
        _spec(C4_CHEAP_HOOK_REPAIR, version="1"),
        _spec(C5M_MEMORY_RECALL, version="1"),
        _spec(C5M_MEMORY_REMIX, version="1"),
        _spec(C5W_NOVELTY_SCAN, version="1", web_search=True),
        _spec(C6A_EVIDENCE_REVISE, version="1"),
        _spec(C6B_PORTFOLIO_CURATE, version="1"),
        _spec(C6C_FEEDBACK_REVISE, version="1"),
    )
)


def creative_prompt_catalog_for_contract(contract_version: str) -> PromptCatalog:
    if contract_version == CREATIVE_CONTRACT_VERSION:
        return creative_prompt_catalog
    if contract_version == LEGACY_CREATIVE_CONTRACT_VERSION:
        return legacy_creative_prompt_catalog
    raise ValueError(f"unsupported Creative contract version: {contract_version!r}")


def validate_creative_output(
    stage: str,
    output: Mapping[str, Any],
    *,
    settings: CreativeWorkflowSettings,
    context: Any = None,
    contract_version: str = CREATIVE_CONTRACT_VERSION,
    schema_path: Path | None = None,
) -> dict[str, Any]:
    """Validate through the route artifact owner without a module import cycle."""

    from hacksome.creative.artifacts import (
        validate_creative_output as validate_artifact,
    )

    return validate_artifact(
        stage,
        output,
        settings=settings,
        context=context,
        contract_version=contract_version,
        schema_path=schema_path,
    )


__all__ = [
    "creative_prompt_catalog",
    "creative_prompt_catalog_for_contract",
    "legacy_creative_prompt_catalog",
    "validate_creative_output",
]
