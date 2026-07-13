"""Fast repository-local validation for all invest skill packages."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml


SKILLS = (
    "invest-core", "invest-financials", "invest-valuation", "invest-sotp",
    "invest-management", "invest-moat", "invest-distribution", "invest-compare",
    "invest-psychology", "invest-framework",
)
LINK_PATTERN = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")


def _frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError(f"missing YAML frontmatter: {path}")
    _, raw, _ = text.split("---\n", 2)
    value = yaml.safe_load(raw)
    if not isinstance(value, dict):
        raise ValueError(f"frontmatter must be an object: {path}")
    return value


def validate_skill(root: Path, name: str) -> None:
    skill_root = root / name
    skill_file = skill_root / "SKILL.md"
    metadata = _frontmatter(skill_file)
    if metadata.get("name") != name:
        raise ValueError(f"frontmatter name mismatch: {name}")
    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"missing frontmatter description: {name}")

    agent_file = skill_root / "agents" / "openai.yaml"
    agent = yaml.safe_load(agent_file.read_text(encoding="utf-8"))
    interface = agent.get("interface") if isinstance(agent, dict) else None
    if not isinstance(interface, dict):
        raise ValueError(f"missing interface metadata: {name}")
    for key in ("display_name", "short_description", "default_prompt"):
        if not isinstance(interface.get(key), str) or not interface[key].strip():
            raise ValueError(f"invalid interface.{key}: {name}")
    if not 25 <= len(interface["short_description"]) <= 64:
        raise ValueError(f"short_description must be 25-64 characters: {name}")
    if f"${name}" not in interface["default_prompt"]:
        raise ValueError(f"default_prompt must mention ${name}")

    for markdown in skill_root.rglob("*.md"):
        for target in LINK_PATTERN.findall(markdown.read_text(encoding="utf-8")):
            target = target.split("#", 1)[0]
            if not target or "://" in target or target.startswith(("#", "/")):
                continue
            if not (markdown.parent / target).resolve().exists():
                raise ValueError(f"broken relative link in {markdown}: {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate all invest skill packages")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    for name in SKILLS:
        validate_skill(args.root.resolve(), name)
    print(f"validated {len(SKILLS)} invest skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
