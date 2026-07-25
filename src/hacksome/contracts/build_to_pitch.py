"""Validated manual inputs for the Build-to-Pitch boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class BuildToPitchInputError(ValueError):
    """The explicit Project, Idea Card, or challenge input is invalid."""


@dataclass(frozen=True, slots=True)
class BuildToPitchInput:
    project_directory: Path
    idea_card_file: Path
    challenge_file: Path

    @classmethod
    def validate(
        cls,
        project_directory: str | Path,
        idea_card_file: str | Path,
        challenge_file: str | Path,
    ) -> BuildToPitchInput:
        raw_project = Path(project_directory).expanduser()
        raw_idea_card = Path(idea_card_file).expanduser()
        raw_challenge = Path(challenge_file).expanduser()
        if raw_project.is_symlink():
            raise BuildToPitchInputError(
                f"Project directory must not be a symlink: {raw_project}"
            )
        project = raw_project.resolve()
        if not project.is_dir():
            raise BuildToPitchInputError(f"Project directory is missing: {project}")
        validated_files: list[Path] = []
        for label, raw_path in (
            ("Idea Card", raw_idea_card),
            ("challenge", raw_challenge),
        ):
            if raw_path.is_symlink():
                raise BuildToPitchInputError(
                    f"{label} file must not be a symlink: {raw_path}"
                )
            path = raw_path.resolve()
            if not path.is_file():
                raise BuildToPitchInputError(f"{label} file is missing: {path}")
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise BuildToPitchInputError(f"{label} cannot be read: {exc}") from exc
            if not content.strip():
                raise BuildToPitchInputError(f"{label} file must not be empty")
            validated_files.append(path)
        return cls(project, validated_files[0], validated_files[1])

    def source_record(self) -> dict[str, str]:
        """Record the operator-provided sources without implying auto-discovery."""

        return {
            "project_directory": str(self.project_directory),
            "idea_card_file": str(self.idea_card_file),
            "challenge_file": str(self.challenge_file),
            "handoff": "manual",
        }
