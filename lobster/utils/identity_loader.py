"""Load identity context from mixed sources.

Static identity (soul.md, style.md) — from filesystem (git repo).
Dynamic state (curiosity, memory) — from Supabase identity_state table.

Human edits soul/style via GitHub (Cowork on phone).
Lobster updates curiosity/memory via DB (survives container restarts).
"""

import logging
from pathlib import Path

from lobster.utils.prompt_budget import join_sections, truncate_chars

logger = logging.getLogger("lobster.utils.identity")

IDENTITY_DIR = Path(__file__).parent.parent / "identity"
SKILLS_DIR = Path(__file__).parent.parent / "skills"

# Per-section char caps for the short "chat" profile. Keeps the Telegram
# system prompt readable without re-sending the entire soul/style/memory
# every turn.
_CHAT_SOUL_LIMIT = 1200
_CHAT_STYLE_LIMIT = 600
_CHAT_STATE_LIMIT = 400


async def load_identity(
    db,
    include_skill: str = None,
    platform: str = None,
    *,
    mode: str = "full",
    override_text: str = None,
    override_label: str = None,
) -> str:
    """Build a system prompt from identity files + dynamic DB state.

    Args:
        db: Database instance (for reading identity_state).
        include_skill: Skill name to append (e.g. "research_commentary").
        platform: "x" or "threads" — affects voice skill.
        mode: "full" (default, used for writer/reflect/connect) or "chat"
            (trimmed profile for Telegram replies — skips memory section
            and caps each block so the prompt stays short).
        override_text: Optional P1 prompt_override content appended at the tail.
        override_label: Label shown before the override block (e.g. "WRITER OVERRIDE v3 variant B").

    Returns:
        Complete system prompt string.
    """
    short = mode == "chat"
    parts: list[str] = []

    # 1. Static: soul.md (from filesystem)
    soul_limit = _CHAT_SOUL_LIMIT if short else None
    style_limit = _CHAT_STYLE_LIMIT if short else None
    for filename, limit in [("soul.md", soul_limit), ("style.md", style_limit)]:
        path = IDENTITY_DIR / filename
        if path.exists():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                parts.append(truncate_chars(content, limit) if limit else content)
        else:
            logger.warning(f"Identity file missing: {path}")

    # 2. Dynamic: curiosity + memory (from Supabase). Chat mode skips
    # memory because it tends to be multi-kilobyte and is rarely needed
    # for a one-turn conversational reply.
    if db:
        try:
            curiosity = await db.get_identity_state("curiosity")
            if curiosity:
                parts.append(
                    truncate_chars(curiosity, _CHAT_STATE_LIMIT) if short else curiosity
                )
        except Exception as e:
            logger.warning(f"Failed to load curiosity state: {e}")

        if not short:
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

    # 5. Prompt override (P1) — appended last so it takes precedence over earlier guidance
    if override_text:
        label = override_label or "PROMPT OVERRIDE"
        parts.append(f"## {label}\n\n{override_text.strip()}")

    return join_sections(parts)
