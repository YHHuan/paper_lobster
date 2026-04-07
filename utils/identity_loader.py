"""Load identity context from mixed sources.

Static identity (soul.md, style.md) — from filesystem (git repo).
Dynamic state (curiosity, memory) — from Supabase identity_state table.

Human edits soul/style via GitHub (Cowork on phone).
Lobster updates curiosity/memory via DB (survives container restarts).
"""

import logging
from pathlib import Path

logger = logging.getLogger("lobster.utils.identity")

IDENTITY_DIR = Path(__file__).parent.parent / "identity"
SKILLS_DIR = Path(__file__).parent.parent / "skills"


async def load_identity(db, include_skill: str = None, platform: str = None) -> str:
    """Build full system prompt from files + DB.

    Args:
        db: Database instance (for reading identity_state).
        include_skill: Skill name to append (e.g. "research_commentary").
        platform: "x" or "threads" — affects voice skill.

    Returns:
        Complete system prompt string.
    """
    parts = []

    # 1. Static: soul.md (from filesystem)
    for filename in ["soul.md", "style.md"]:
        path = IDENTITY_DIR / filename
        if path.exists():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                parts.append(content)
        else:
            logger.warning(f"Identity file missing: {path}")

    # 2. Dynamic: curiosity + memory (from Supabase)
    if db:
        try:
            curiosity = await db.get_identity_state("curiosity")
            if curiosity:
                parts.append(curiosity)
        except Exception as e:
            logger.warning(f"Failed to load curiosity state: {e}")

        try:
            memory = await db.get_identity_state("memory")
            if memory:
                parts.append(memory)
        except Exception as e:
            logger.warning(f"Failed to load memory state: {e}")

    # 3. Platform-specific voice
    if platform == "threads":
        threads_voice = SKILLS_DIR / "threads_voice.md"
        if threads_voice.exists():
            parts.append(threads_voice.read_text(encoding="utf-8").strip())

    # 4. Skill
    if include_skill:
        skill_path = SKILLS_DIR / f"{include_skill}.md"
        if skill_path.exists():
            parts.append(skill_path.read_text(encoding="utf-8").strip())
        else:
            logger.warning(f"Skill file missing: {skill_path}")

    return "\n\n---\n\n".join(parts)
