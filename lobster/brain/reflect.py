"""brain/reflect.py — Reflect agent (LOCAL).

Reads soul + recent digests + recent interactions + knowledge state, produces
a free-form reflection memo. Memo is stored in `reflections` table and used as
input for the Hypothesize step.
"""

import logging
from pathlib import Path

from lobster.agent_logic.prompts import REFLECT_V3_SYSTEM, REFLECT_V3_USER

logger = logging.getLogger("lobster.brain.reflect")

SOUL_PATH = Path(__file__).parent.parent / "identity" / "soul.md"


def _load_soul() -> str:
    try:
        return SOUL_PATH.read_text()
    except Exception:
        return "(soul.md not found)"


class Reflector:
    def __init__(self, llm, db, knowledge):
        self.llm = llm
        self.db = db
        self.knowledge = knowledge

    async def reflect(self, trigger: str = "manual") -> str:
        soul = _load_soul()
        digests = await self.db.get_recent_digest_summary(days=7)
        # Recent interactions: pull from interactions table (last 20)
        interactions = await self._recent_interactions()
        knowledge = await self.knowledge.summary_text()

        try:
            memo = await self.llm.chat_local(
                agent="reflect",
                system_prompt=REFLECT_V3_SYSTEM,
                user_message=REFLECT_V3_USER.format(
                    soul_md=soul,
                    recent_digests=digests,
                    recent_interactions=interactions,
                    knowledge_state_summary=knowledge,
                ),
                max_tokens=1500,
            )
        except Exception as e:
            logger.warning(f"reflect llm call failed: {e}")
            memo = "(reflection failed; trying again next loop)"

        try:
            await self.db.insert_reflection(memo=memo, trigger=trigger)
        except Exception as e:
            logger.warning(f"persist reflection failed: {e}")

        return memo

    async def _recent_interactions(self) -> str:
        try:
            rows = await self.db._select("interactions", {
                "select": "type,other_user_text,my_reply_text,created_at",
                "order": "created_at.desc",
                "limit": "20",
            })
        except Exception:
            rows = []
        if not rows:
            return "(最近沒有互動紀錄)"
        lines = []
        for r in rows:
            t = r.get("type", "?")
            them = (r.get("other_user_text") or "")[:120]
            mine = (r.get("my_reply_text") or "")[:120]
            lines.append(f"- [{t}] them: {them} | me: {mine}")
        return "\n".join(lines)
