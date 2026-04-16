"""Multi-agent role system for content creation.

Instead of a single LLM call producing the final post,
the creation pipeline now uses distinct roles:

1. Strategist: Picks topic + skill (with engagement data)
2. Writer: Writes initial draft
3. Critic: Reviews and finds weaknesses
4. Editor: Revises based on critique

Each role sees the full identity context but has a focused job.
"""

import json
import logging

from lobster.utils.identity_loader import load_identity

logger = logging.getLogger("lobster.agent.roles")


CRITIC_PROMPT = """You are the Critic — an internal voice that makes the lobster's posts better.

Your job: review the draft and find problems BEFORE publishing.

Draft to review:
---
{draft}
---

Source material:
---
{source_summary}
---

Platform: {platform} | Language: {language} | Skill: {skill}

Evaluate honestly:
1. Is the hook strong enough to stop someone scrolling?
2. Does it say something ORIGINAL or just restate the source?
3. Are there any claims without evidence?
4. Is it the right length? Too padded? Too thin?
5. Does the ending leave space for thought, or does it wrap up too neatly?
6. Would YOU stop scrolling for this? Be honest.

Respond in JSON:
{{
  "overall_quality": 1-10,
  "hook_assessment": "what works / what doesn't about the opening",
  "originality": "is there a fresh angle or just retelling?",
  "issues": ["specific issue 1", "specific issue 2"],
  "suggestions": ["concrete fix 1", "concrete fix 2"],
  "verdict": "publish" | "revise" | "kill"
}}"""


EDITOR_PROMPT = """You are the Editor — you take the Critic's feedback and improve the draft.

Original draft:
---
{draft}
---

Critic's feedback:
---
{critique}
---

Source material (for fact-checking):
---
{source_summary}
---

Rules:
- Fix the specific issues the Critic raised.
- Keep what works. Don't rewrite from scratch unless the Critic said "kill".
- Maintain the same voice and skill style.
- Don't add AI-sounding filler.
- {length_guide}

Write ONLY the revised post text. No explanation, no headers."""


async def run_critic(
    llm, db, draft: str, source_text: str,
    platform: str, language: str, skill: str,
    *,
    override_text: str = None,
    override_label: str = None,
) -> dict:
    """Run the Critic on a draft. Returns critique dict."""
    identity = await load_identity(
        db,
        override_text=override_text,
        override_label=override_label or "CRITIC OVERRIDE",
    )
    system = f"{identity}\n\n---\n\n"
    prompt = CRITIC_PROMPT.format(
        draft=draft,
        source_summary=source_text[:1500],
        platform=platform,
        language=language,
        skill=skill,
    )
    try:
        result = await llm.chat_json("lobster", system, prompt)
        logger.info(
            f"Critic verdict: {result.get('verdict')} "
            f"(quality={result.get('overall_quality')})"
        )
        return result
    except Exception as e:
        logger.error(f"Critic failed: {e}")
        return {"verdict": "publish", "overall_quality": 6, "issues": [], "suggestions": []}


async def run_editor(
    llm, db, draft: str, critique: dict,
    source_text: str, length_guide: str,
    *,
    override_text: str = None,
    override_label: str = None,
) -> str:
    """Run the Editor to revise a draft based on Critic feedback. Returns revised text."""
    identity = await load_identity(
        db,
        override_text=override_text,
        override_label=override_label or "EDITOR OVERRIDE",
    )
    system = identity
    prompt = EDITOR_PROMPT.format(
        draft=draft,
        critique=json.dumps(critique, ensure_ascii=False, indent=2),
        source_summary=source_text[:1500],
        length_guide=length_guide,
    )
    try:
        result = await llm.chat("lobster", system, prompt, max_tokens=3072)
        if result and len(result.strip()) > 50:
            logger.info(f"Editor revised draft ({len(result)} chars)")
            return result.strip()
        return draft  # Keep original if editor output is bad
    except Exception as e:
        logger.error(f"Editor failed: {e}")
        return draft
