from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class SkillDef:
    name: str
    description: str
    instructions: str
    source_path: Path


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    if not raw.startswith("---\n"):
        raise ValueError("Skill file must start with YAML-like frontmatter delimited by ---")

    closing = raw.find("\n---\n", 4)
    if closing < 0:
        raise ValueError("Skill frontmatter is missing closing --- line")

    frontmatter_text = raw[4:closing]
    body = raw[closing + 5 :].lstrip("\n")
    metadata: dict[str, str] = {}
    for line in frontmatter_text.splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#"):
            continue
        if ":" not in clean:
            raise ValueError(f"Invalid frontmatter line: {line}")
        key, value = clean.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"').strip("'")
    return metadata, body


def load_skill(path: Path) -> SkillDef:
    raw = path.read_text(encoding="utf-8")
    metadata, body = _parse_frontmatter(raw)
    name = metadata.get("name", "").strip()
    description = metadata.get("description", "").strip()
    if not name:
        raise ValueError(f"Skill '{path}' is missing `name` in frontmatter")
    if not description:
        raise ValueError(f"Skill '{path}' is missing `description` in frontmatter")
    if not body.strip():
        raise ValueError(f"Skill '{path}' has empty instructions body")
    return SkillDef(name=name, description=description, instructions=body.strip(), source_path=path)


def load_skills(root: Path) -> dict[str, SkillDef]:
    skills: dict[str, SkillDef] = {}
    for skill_path in sorted(root.rglob("SKILL.md")):
        skill = load_skill(skill_path)
        skills[skill.name] = skill
    return skills
