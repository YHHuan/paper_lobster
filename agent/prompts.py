"""Prompt templates for Lobster v2.5 agents."""

EXPLORE_PROMPT = """You are exploring the internet for interesting content.
Your identity and taste are defined in the system prompt above.

Given the search results below, evaluate each item:
1. Would this genuinely surprise or intrigue your audience?
2. Is there a counter-intuitive angle?
3. Is the methodology or finding actually novel?
4. Does it connect to something you've been thinking about?

For each item, provide:
- interest_score (1-10): How interesting is this to YOU specifically?
- interest_reason: One sentence on why it's interesting (or boring).
- content_type: "research" | "trend" | "tool" | "news" | "opinion" | "oddity"
- language: "en" | "zh" — which language should the post be in?

Only score 7+ if you'd genuinely stop scrolling for it.
Score 9+ only for things that make you go "holy shit".

Respond in JSON: {"items": [{"title": "...", "url": "...", "interest_score": N, "interest_reason": "...", "content_type": "...", "language": "..."}]}"""

CREATE_POST_PROMPT = """You are writing a social media post based on the source material below.
Your identity, style, and the specific skill to use are in the system prompt above.

Rules:
- One post, one idea. Don't be greedy.
- Numbers must come directly from the source — never invent.
- If you're not sure about a number, don't include it.
- Open with a hook that challenges assumptions or creates tension.
- End with a question or open space, not a summary.
- {length_guide}

Write ONLY the post text. No headers, no metadata, no explanation."""

CREATE_POST_LENGTH = {
    "x": "English, 140-240 words. Concise, sharp.",
    "threads": "Traditional Chinese, 200-400 words. Conversational, can be playful.",
}

REPLY_PROMPT = """You are responding to someone who interacted with your post.
Your identity and reply style are in the system prompt above.

The conversation so far:
{thread_context}

Their latest message:
{other_text}

Rules:
- Read the full thread context before responding.
- Be concise (< {max_chars} characters).
- Don't explain obvious things.
- Don't fake agreement.
- If they're trolling, end gracefully.
- Match the energy — serious question gets serious answer, casual gets casual.

Write ONLY your reply text."""

REFLECT_PROMPT = """You are doing your nightly reflection.
Your identity is in the system prompt above.

Today's activities:
{today_summary}

Update the following:
1. curiosity.md — what topics are hot, what's cooling down?
2. memory.md — what did you post today, what worked, what didn't?

Respond in JSON:
{
  "curiosity_update": "full new content for curiosity.md",
  "memory_update": "full new content for memory.md",
  "insights": ["list of things you learned today"]
}"""

MIRROR_PROMPT = """You are doing your weekly self-reflection.
Your identity (soul.md + style.md) is in the system prompt above.

This week's data:
{weekly_data}

Analyze:
1. Which skill performed best/worst by engagement?
2. Which language (en/zh) got more response?
3. Which posting times worked best?
4. What hook patterns were effective?
5. Are you drifting from your soul.md values?
6. Cross-platform comparison: same discovery, which platform version did better?

Provide:
- Weekly report summary (for Telegram)
- Any proposed changes to soul.md or style.md (explain why)
- Updated curiosity directions

Respond in JSON:
{
  "report": "markdown formatted weekly report",
  "soul_changes": [{"section": "...", "current": "...", "proposed": "...", "reason": "..."}],
  "style_changes": [{"section": "...", "current": "...", "proposed": "...", "reason": "..."}],
  "curiosity_directions": ["topic1", "topic2"],
  "personality_drift_score": 0-10,
  "insights": ["insight1", "insight2"]
}"""

SKILL_SELECT_PROMPT = """Given this discovery, which skill should be used to write about it?

Discovery:
Title: {title}
Summary: {summary}
Content type: {content_type}

Available skills:
- research_commentary: A paper/preprint with surprising methodology or findings
- trend_analysis: Something multiple sources are discussing right now
- cross_domain: Two different fields that connect in unexpected ways
- hot_take: Mainstream consensus that deserves a different angle
- today_i_learned: A genuinely surprising fact or concept
- hype_check: Something popular that might be overrated

Respond in JSON: {{"skill": "skill_name", "reason": "one sentence"}}"""
