"""Lobster v4 skills loader.

Scans lobster/skills/*.md, prepends agentskills.io-style YAML frontmatter
(name, description, type) if missing, then — when LOBSTER_USE_HERMES=1 —
registers each skill with the hermes skill registry.

The md files are pure prompt fragments. We infer description from the first
non-empty paragraph after the top-level heading.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("lobster.bridge.skills_loader")

_SKILLS_DIR = Path(__file__).parent.parent / "skills"
_FRONTMATTER_MARKER = "---"


def _has_frontmatter(text: str) -> bool:
    return text.lstrip().startswith("---\n") or text.lstrip().startswith("---\r\n")


def _infer_description(body: str) -> str:
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        return s[:200]
    return "Lobster skill prompt fragment."


def _add_frontmatter(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if _has_frontmatter(text):
        return False
    name = path.stem
    desc = _infer_description(text)
    fm = (
        "---\n"
        f"name: {name}\n"
        f"description: {desc!s}\n"
        "type: prompt-fragment\n"
        "---\n\n"
    )
    path.write_text(fm + text, encoding="utf-8")
    return True


def ensure_frontmatter(skills_dir: Path = _SKILLS_DIR) -> list[str]:
    updated = []
    for p in sorted(skills_dir.glob("*.md")):
        if _add_frontmatter(p):
            updated.append(p.name)
    if updated:
        logger.info(f"Added frontmatter to {len(updated)} skill files: {updated}")
    return updated


def _use_hermes() -> bool:
    return os.environ.get("LOBSTER_USE_HERMES", "").strip() in {"1", "true", "yes"}


def register_with_hermes(skills_dir: Path = _SKILLS_DIR) -> int:
    """Register each md skill with the hermes skill registry. No-op without hermes."""
    if not _use_hermes():
        return 0
    try:
        # TODO hermes-native: wire the actual registry call.
        # vendor/hermes-agent-main/agent/skill_commands.py + skill_utils.py
        # expose skill-loading helpers but their contract is file-tree based;
        # we'd point them at lobster/skills/ and let them scan.
        from agent import skill_utils  # noqa: F401
        logger.info("Hermes skill_utils available — registration is TODO.")
        return 0
    except Exception as e:
        logger.info(f"Hermes skill registry unavailable ({e})")
        return 0


def load_all() -> dict:
    """Entry point: normalise frontmatter then (optionally) register."""
    updated = ensure_frontmatter()
    registered = register_with_hermes()
    return {"frontmatter_added": updated, "registered_count": registered}
