from __future__ import annotations

from pathlib import Path

from space.skill.loader import load_skill, load_skills


def test_load_skill_parses_frontmatter_and_body(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        "---\n"
        "name: archive\n"
        "description: archive flow\n"
        "---\n\n"
        "Step 1\nStep 2\n",
        encoding="utf-8",
    )
    skill = load_skill(path)
    assert skill.name == "archive"
    assert skill.description == "archive flow"
    assert "Step 1" in skill.instructions


def test_load_skills_collects_all_skill_files(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: first\n---\n\nA",
        encoding="utf-8",
    )
    (tmp_path / "b" / "SKILL.md").write_text(
        "---\nname: beta\ndescription: second\n---\n\nB",
        encoding="utf-8",
    )
    skills = load_skills(tmp_path)
    assert sorted(skills.keys()) == ["alpha", "beta"]
