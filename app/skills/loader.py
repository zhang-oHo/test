from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator


FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


class SkillFormatError(ValueError):
    """Raised when a SKILL.md file does not follow the expected format."""


class SkillDefinition(BaseModel):
    skill_id: str
    name: str
    description: str
    category: str
    version: str = "0.1.0"
    use_when: list[str] = Field(default_factory=list)
    avoid_when: list[str] = Field(default_factory=list)
    default_temperature: float = 0.4
    rag_categories: list[str] = Field(default_factory=list)
    output_style: dict[str, Any] = Field(default_factory=dict)
    system_prompt: str
    source_path: Path | None = None

    @model_validator(mode="after")
    def ensure_prompt_present(self) -> "SkillDefinition":
        if not self.system_prompt.strip():
            raise ValueError("system_prompt body must not be empty")
        return self

    def to_seed_record(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "system_prompt": self.system_prompt,
            "use_when": self.use_when,
            "avoid_when": self.avoid_when,
            "output_style": self.output_style,
            "default_temperature": self.default_temperature,
            "version": self.version,
            "enabled": True,
        }


def parse_skill_markdown(markdown: str, source_path: Path | None = None) -> SkillDefinition:
    match = FRONTMATTER_PATTERN.match(markdown.strip())
    if match is None:
        raise SkillFormatError("SKILL.md must start with YAML frontmatter")

    frontmatter_text, body = match.groups()
    try:
        metadata = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as exc:
        raise SkillFormatError(f"Invalid YAML frontmatter: {exc}") from exc

    if not isinstance(metadata, dict):
        raise SkillFormatError("YAML frontmatter must decode to an object")

    metadata["system_prompt"] = body.strip()
    metadata["source_path"] = source_path

    try:
        return SkillDefinition.model_validate(metadata)
    except ValidationError as exc:
        raise SkillFormatError(str(exc)) from exc


def load_skill(path: Path) -> SkillDefinition:
    return parse_skill_markdown(path.read_text(encoding="utf-8"), source_path=path)


def load_skills(skills_root: Path) -> list[SkillDefinition]:
    if not skills_root.exists():
        raise SkillFormatError(f"Skills directory does not exist: {skills_root}")

    skill_files = sorted(skills_root.glob("*/SKILL.md"))
    if not skill_files:
        raise SkillFormatError(f"No SKILL.md files found under {skills_root}")

    return [load_skill(path) for path in skill_files]
