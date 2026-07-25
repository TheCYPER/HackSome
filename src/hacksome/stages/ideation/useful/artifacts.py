"""Deterministic Markdown contracts for Problems, Ideas, and Idea Cards."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any


PROBLEM_HEADINGS = (
    "User",
    "Observed Problem",
    "Evidence",
    "Existing Workarounds",
    "Why It Matters",
)

IDEA_HEADINGS = (
    "User",
    "Problem",
    "Product",
    "Product Experience",
    "Core Mechanism",
    "First Real Version",
    "Assumptions and Risks",
    "Evidence",
)


class ArtifactError(ValueError):
    """A model-produced Markdown artifact is not publishable."""


_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)


def validate_markdown(
    markdown: str,
    *,
    required_h2: Sequence[str] = (),
    label: str = "Markdown",
) -> None:
    """Require one H1 and exactly one non-empty section per required H2."""

    if not isinstance(markdown, str) or not markdown.strip():
        raise ArtifactError(f"{label} must be non-empty Markdown")
    headings = [(len(level), title.strip()) for level, title in _HEADING.findall(markdown)]
    h1 = [title for level, title in headings if level == 1]
    if len(h1) != 1:
        raise ArtifactError(f"{label} must contain exactly one H1 heading")
    h2_counts = Counter(title for level, title in headings if level == 2)
    for heading in required_h2:
        if h2_counts[heading] != 1:
            raise ArtifactError(
                f"{label} requires exactly one H2 heading {heading!r}"
            )
        body = section_body(markdown, heading)
        if not body.strip():
            raise ArtifactError(f"{label} section {heading!r} must not be empty")


def section_body(markdown: str, heading: str) -> str:
    match = re.search(
        rf"^##[ \t]+{re.escape(heading)}[ \t]*\n(.*?)(?=^##[ \t]+|\Z)",
        markdown,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise ArtifactError(f"Markdown section {heading!r} does not exist")
    return match.group(1).strip()


def title_of(markdown: str) -> str:
    match = re.search(r"^#[ \t]+(.+?)[ \t]*$", markdown, flags=re.MULTILINE)
    if match is None:
        raise ArtifactError("Markdown does not contain an H1 title")
    return match.group(1).strip()


def compose_idea_card(
    *,
    idea_markdown: str,
    review_markdown: str,
    lineage: Mapping[str, Any],
) -> str:
    """Compose a human-readable card without asking another Agent."""

    validate_markdown(idea_markdown, required_h2=IDEA_HEADINGS, label="Idea")
    validate_markdown(review_markdown, label="Red Team review")
    title = title_of(idea_markdown)
    idea_without_title = re.sub(
        r"^#[ \t]+.+?[ \t]*\n+", "", idea_markdown, count=1, flags=re.MULTILINE
    ).strip()
    review_without_title = re.sub(
        r"^#[ \t]+.+?[ \t]*\n+", "", review_markdown, count=1, flags=re.MULTILINE
    ).strip()
    lineage_json = json.dumps(dict(lineage), ensure_ascii=False, indent=2, sort_keys=True)
    return (
        f"# {title}\n\n"
        "## Lineage\n\n"
        f"```json\n{lineage_json}\n```\n\n"
        f"{idea_without_title}\n\n"
        "## Red Team Validation\n\n"
        "Decision: `pass`\n\n"
        f"{review_without_title}\n"
    )


def compose_idea_index(cards: Sequence[Mapping[str, str]]) -> str:
    lines = ["# Idea Cards", ""]
    if not cards:
        lines.extend(["No Idea passed the absolute quality gates.", ""])
        return "\n".join(lines)
    lines.extend(
        [
            f"- [{card['title']}]({card['relative_path']}) — `{card['idea_id']}`"
            for card in cards
        ]
    )
    lines.append("")
    return "\n".join(lines)
