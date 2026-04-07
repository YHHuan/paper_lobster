"""Hook strength evaluator.

Uses LLM to rate the opening of a draft on a 1-10 scale.
< 7 = reject and rewrite.
"""

import json
import logging

logger = logging.getLogger("lobster.utils.hook")

EVAL_PROMPT = """You are evaluating the opening hook of a social media post.

Rate the hook strength on a 1-10 scale:
- 1-3: No hook at all, reads like an abstract or press release
- 4-5: Has information but opening is flat, no reason to stop scrolling
- 6-7: Has a point of view but not sharp enough, opening doesn't grab
- 8-9: Counter-intuitive, creates tension, makes you want to read more
- 10: Genuinely makes you stop and think

Consider:
- Does it challenge an assumption?
- Does it create information gap or tension?
- Would someone scrolling fast actually stop for this?
- Is the first sentence doing work, or is it throat-clearing?

Respond in JSON: {"score": <int>, "reason": "<one sentence>"}"""


async def evaluate_hook(draft: str, language: str, llm_client) -> tuple[int, str]:
    """Evaluate hook strength of a draft.

    Args:
        draft: The full draft text.
        language: "zh" or "en".
        llm_client: LLMClient instance.

    Returns:
        (score, reason): score 1-10, reason string.
    """
    # Take first 2 sentences or 150 chars, whichever is shorter
    opening = draft[:150]

    user_msg = f"Language: {language}\n\nOpening to evaluate:\n{opening}"

    try:
        result = await llm_client.chat_json("lobster", EVAL_PROMPT, user_msg)
        score = int(result.get("score", 5))
        reason = result.get("reason", "")
        score = max(1, min(10, score))
        logger.info(f"Hook score: {score}/10 — {reason}")
        return score, reason
    except Exception as e:
        logger.warning(f"Hook evaluation failed: {e}, defaulting to 5")
        return 5, "evaluation failed"
