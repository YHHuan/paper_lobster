"""Spawn sub-lobster for deep research on a topic.

When the main lobster encounters something worth digging deeper,
it spawns an independent API call with full identity context to
do focused research and return enriched content.
"""

import logging

from utils.identity_loader import load_identity

logger = logging.getLogger("lobster.agent.spawn")

SPAWN_PROMPT = """You are a research assistant helping the main lobster dig deeper into a specific topic.

Your task:
1. Read the source material carefully.
2. Identify the key claim or finding.
3. Look for: counter-intuitive angles, methodology strengths/weaknesses,
   cross-domain connections, effect sizes, limitations the authors don't mention.
4. Summarize your findings in a way that helps the main lobster write a compelling post.

Focus on SUBSTANCE over SUMMARY. What would a smart, skeptical colleague want to know?

Respond in JSON:
{
  "key_finding": "The core insight in one sentence",
  "counter_intuitive": "What most people would assume vs what the evidence shows",
  "methodology_note": "Anything notable about how they did this",
  "effect_size": "The actual magnitude (if applicable)",
  "limitations": "What the authors didn't mention",
  "cross_domain": "Does this connect to anything in other fields?",
  "hook_suggestion": "A possible opening line for a post about this",
  "worth_posting": true/false
}"""


async def spawn_research(llm_client, source_text: str, title: str = "") -> dict:
    """Spawn a sub-lobster to do deep research on a source.

    Args:
        llm_client: LLMClient instance.
        source_text: Full text of the source to analyze.
        title: Optional title for context.

    Returns:
        Research findings dict.
    """
    identity = load_identity()
    system = f"{identity}\n\n---\n\n{SPAWN_PROMPT}"
    user_msg = f"Title: {title}\n\nSource material:\n{source_text[:4000]}"

    try:
        result = await llm_client.chat_json("spawn", system, user_msg)
        logger.info(f"Spawn research for '{title[:50]}': worth_posting={result.get('worth_posting')}")
        return result
    except Exception as e:
        logger.error(f"Spawn research failed: {e}")
        return {"worth_posting": False, "key_finding": "research failed"}
