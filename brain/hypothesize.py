"""brain/hypothesize.py — Hypothesize agent (LOCAL).

Takes a reflection memo + active projects + previously asked questions,
produces 2-5 new open_questions, persists them.
"""

import logging
import re
from pathlib import Path

from agent.prompts import HYPOTHESIZE_SYSTEM, HYPOTHESIZE_USER

logger = logging.getLogger("lobster.brain.hypothesize")

SOUL_PATH = Path(__file__).parent.parent / "identity" / "soul.md"


def _extract_active_projects() -> str:
    try:
        text = SOUL_PATH.read_text()
    except Exception:
        return "(no active projects)"
    # Find the "Active Projects" / "正在跑的研究" section
    pattern = re.compile(r"###\s*(?:正在跑的研究|Active Projects).*?\n(.*?)(?:\n###|\n##|\Z)", re.DOTALL)
    m = pattern.search(text)
    return m.group(1).strip() if m else "(active projects section not found)"


class Hypothesizer:
    def __init__(self, llm, db):
        self.llm = llm
        self.db = db

    async def hypothesize(self, reflection_memo: str) -> list[dict]:
        previous = await self.db.get_recent_questions_text(limit=20)
        try:
            data = await self.llm.json_local(
                agent="hypothesize",
                system_prompt=HYPOTHESIZE_SYSTEM,
                user_message=HYPOTHESIZE_USER.format(
                    reflection_memo=reflection_memo,
                    active_projects=_extract_active_projects(),
                    previous_questions="\n".join(f"- {q}" for q in previous) or "(none)",
                ),
                max_tokens=1500,
            )
        except Exception as e:
            logger.warning(f"hypothesize llm call failed: {e}")
            return []

        items = data if isinstance(data, list) else (data.get("questions") if isinstance(data, dict) else [])
        if not items:
            return []

        out = []
        for it in items[:5]:
            q = (it.get("question") or "").strip()
            if not q:
                continue
            try:
                qid = await self.db.insert_open_question(
                    question=q,
                    soul_anchor=it.get("soul_anchor"),
                    expected_source_types=it.get("expected_source_types") or [],
                    priority=float(it.get("priority", 0.5)),
                    reasoning=it.get("reasoning"),
                )
                it["id"] = qid
                out.append(it)
            except Exception as e:
                logger.warning(f"insert_open_question failed: {e}")
        return out
