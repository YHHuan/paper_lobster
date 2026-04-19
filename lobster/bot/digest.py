"""Morning Telegram digest — categorise recent discoveries and broadcast.

Parallel path to Mode A (social posting): this is Mode B (情報簡報). It reads
discoveries untouched by the digester, groups them by channel (Reddit / HN /
Google News / RSS / arXiv), picks top-N per group by engagement, and asks the
LLM to rewrite each section as a Telegram message in the social-surfing style.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("lobster.bot.digest")


DIGEST_PROMPT = """你是在幫主人整理今早的情報簡報。必須照下面的格式輸出：

🗓 {category}
📅 {date} {slot}

📌 {source_bucket}

🔴 重點動態

1️⃣ {標題（繁中翻譯，保留英文專有名詞）}
🔖 {source_name} · {time} · {engagement_line}

{2-3 句繁中重點摘要，抓精華，不要逐字翻譯}

🔗 {URL}

2️⃣ ...

規則：
- 標題翻譯成繁體中文，但 LLM / GPT / Claude / RAG 等專有名詞保留英文
- 摘要抓精華，不要逐字翻譯，不要加沒有的內容
- 簡體字一律改成繁體
- 禁止「重磅」「炸裂」「驚人」「震撼」這類 AI 口吻
- URL 原樣保留
- engagement_line 依來源帶不同格式：
    Reddit → ⬆️ {upvotes} · 💬 {comments}
    Hacker News → ▲ {score} · 💬 {comments}
    其他 → 可省略或只寫 🕒 {time}
- 最多 5 則，不要超過。

素材 JSON：
{discoveries_json}
"""


class DigestGenerator:
    CATEGORY_ORDER = ["Reddit", "Hacker News", "科技新聞", "學術", "其他"]

    def __init__(self, db, llm, telegram=None):
        self.db = db
        self.llm = llm
        self.telegram = telegram

    # ── public entry ──

    async def generate_and_send(self, hours: int = 12) -> dict:
        """Pull last `hours` discoveries, group, render, send. Returns stats dict."""
        since = datetime.utcnow() - timedelta(hours=hours)
        discoveries = await self.db.get_discoveries_since(since, limit=200)
        if not discoveries:
            if self.telegram:
                await self.telegram.notify("今早沒抓到新內容 🦞💤")
            return {"sent": 0, "categories": {}, "discovery_ids": []}

        grouped = self._group(discoveries)
        selected: dict[str, list[dict]] = {}
        for cat in self.CATEGORY_ORDER:
            items = grouped.get(cat) or []
            if not items:
                continue
            items.sort(key=self._score, reverse=True)
            selected[cat] = items[:5]

        now_str = datetime.now().strftime("%m/%d")
        slot = self._slot_label()
        sent_ids: list[str] = []
        used_discovery_ids: list[str] = []
        categories_summary: dict[str, int] = {}

        for cat, items in selected.items():
            if not items:
                continue
            try:
                text = await self._render_section(cat, items, now_str, slot)
            except Exception as e:
                logger.error(f"digest render failed for {cat}: {e}", exc_info=True)
                continue
            if self.telegram:
                await self.telegram.notify(text)
                await asyncio.sleep(1)
            used_discovery_ids.extend([str(d["id"]) for d in items])
            categories_summary[cat] = len(items)

        if used_discovery_ids:
            try:
                await self.db.mark_discoveries_in_digest(used_discovery_ids)
            except Exception as e:
                logger.warning(f"mark_in_digest failed: {e}")
            try:
                await self.db.insert_digest_history(
                    categories=categories_summary,
                    discovery_ids=used_discovery_ids,
                    telegram_message_ids=sent_ids,
                )
            except Exception as e:
                logger.warning(f"insert_digest_history failed: {e}")

        return {
            "sent": sum(categories_summary.values()),
            "categories": categories_summary,
            "discovery_ids": used_discovery_ids,
        }

    # ── grouping ──

    def _group(self, discoveries: list[dict]) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {c: [] for c in self.CATEGORY_ORDER}
        for d in discoveries:
            stype = (d.get("source_type") or "").lower()
            sname = (d.get("source_name") or "").lower()
            if stype == "reddit":
                out["Reddit"].append(d)
            elif stype == "hn":
                out["Hacker News"].append(d)
            elif "arxiv" in sname or "biorxiv" in sname or stype in ("arxiv", "biorxiv", "pubmed"):
                out["學術"].append(d)
            elif stype in ("rss", "google_news"):
                out["科技新聞"].append(d)
            else:
                out["其他"].append(d)
        return out

    @staticmethod
    def _score(d: dict) -> float:
        meta = d.get("metadata") or {}
        return (
            (meta.get("upvotes") or 0)
            + (meta.get("score") or 0)
            + (meta.get("comments") or 0) * 2
        )

    @staticmethod
    def _slot_label() -> str:
        hour = datetime.now().hour
        if hour < 11:
            return "上午"
        if hour < 17:
            return "下午"
        return "晚上"

    # ── rendering ──

    async def _render_section(
        self,
        category: str,
        items: list[dict],
        date_str: str,
        slot: str,
    ) -> str:
        payload = []
        for d in items:
            meta = d.get("metadata") or {}
            payload.append({
                "title": d.get("title"),
                "source_name": d.get("source_name"),
                "url": d.get("url"),
                "raw_text": (d.get("raw_content") or d.get("summary") or "")[:300],
                "language": d.get("language"),
                "upvotes": meta.get("upvotes", 0),
                "score": meta.get("score", 0),
                "comments": meta.get("comments", 0),
                "published": meta.get("published"),
            })

        source_bucket = {
            "Reddit": "Reddit",
            "Hacker News": "HN",
            "科技新聞": "RSS / Google News",
            "學術": "arXiv / bioRxiv / PubMed",
            "其他": "其他",
        }.get(category, category)

        prompt = DIGEST_PROMPT.format(
            category=category,
            date=date_str,
            slot=slot,
            source_bucket=source_bucket,
            discoveries_json=json.dumps(payload, ensure_ascii=False, indent=2),
        )
        system = (
            "你是 Lobster 的情報簡報產生器。用繁體中文輸出，保留專有名詞英文。"
            "忠於素材 JSON，不要編造連結或數字。只輸出 Telegram 訊息本體，不要 markdown code fence。"
        )
        response = await self.llm.chat(
            "digest",
            system,
            prompt,
            tier="local",
            max_tokens=2000,
        )
        return (response or "").strip()
