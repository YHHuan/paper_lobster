"""Load identity files and build system prompts for LLM calls.

Reads soul.md, style.md, curiosity.md, memory.md from identity/.
Optionally appends a skill file from skills/.
"""

import logging
from pathlib import Path

logger = logging.getLogger("lobster.utils.identity")

IDENTITY_DIR = Path(__file__).parent.parent / "identity"
SKILLS_DIR = Path(__file__).parent.parent / "skills"


def load_identity(include_skill: str = None, platform: str = None) -> str:
    """Build the full system prompt from identity files + optional skill.

    Args:
        include_skill: Skill name (e.g. "research_commentary") to append.
        platform: "x" or "threads" — affects which voice skill to use.

    Returns:
        Complete system prompt string.
    """
    parts = []

    # Core identity
    for filename in ["soul.md", "style.md", "curiosity.md", "memory.md"]:
        path = IDENTITY_DIR / filename
        if path.exists():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                parts.append(content)
        else:
            logger.warning(f"Identity file missing: {path}")

    # Platform-specific voice
    if platform == "threads":
        threads_voice = SKILLS_DIR / "threads_voice.md"
        if threads_voice.exists():
            parts.append(threads_voice.read_text(encoding="utf-8").strip())

    # Skill
    if include_skill:
        skill_path = SKILLS_DIR / f"{include_skill}.md"
        if skill_path.exists():
            parts.append(skill_path.read_text(encoding="utf-8").strip())
        else:
            logger.warning(f"Skill file missing: {skill_path}")

    return "\n\n---\n\n".join(parts)


def update_identity_file(filename: str, content: str, require_approval: bool = False) -> bool:
    """Update an identity file (only curiosity.md and memory.md auto-allowed).

    Args:
        filename: File to update (e.g. "curiosity.md").
        content: New file content.
        require_approval: If True, don't write — return False to signal approval needed.

    Returns:
        True if written, False if approval required.
    """
    SELF_MODIFIABLE = {"curiosity.md", "memory.md"}

    if filename not in SELF_MODIFIABLE and not require_approval:
        logger.info(f"Identity file {filename} requires owner approval")
        return False

    path = IDENTITY_DIR / filename
    path.write_text(content, encoding="utf-8")
    logger.info(f"Updated identity file: {filename}")
    return True
