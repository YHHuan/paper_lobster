"""Supabase REST API client for Lobster v2.5.

Uses HTTPS only (no direct PostgreSQL), works everywhere including WSL.
Adapted from v1 with new schema: discoveries, posts, interactions,
evolution_log, token_usage, rss_sources, tracked_handles.
"""

import os
import re
import json
import logging
from typing import Optional
from datetime import date, datetime, timedelta

import httpx

logger = logging.getLogger("lobster.db")


class Database:
    def __init__(self):
        self.url = os.environ["SUPABASE_URL"].rstrip("/")
        self.key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["SUPABASE_ANON_KEY"]
        self.client: Optional[httpx.AsyncClient] = None

    async def connect(self):
        base = f"{self.url}/rest/v1"
        self.client = httpx.AsyncClient(
            base_url=base,
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            timeout=30.0,
        )
        logger.info(f"DB connected — base_url={base}")
        try:
            resp = await self.client.get("/discoveries", params={"select": "id", "limit": "1"})
            resp.raise_for_status()
            logger.info("DB health check passed")
        except Exception as e:
            logger.error(f"DB health check FAILED: {e}")

    async def close(self):
        if self.client:
            await self.client.aclose()

    # ── helpers ──

    def _log_error(self, method: str, url: str, resp: httpx.Response):
        try:
            body = resp.text[:500]
        except Exception:
            body = "(unreadable)"
        logger.error(f"DB {method} failed: {resp.status_code} url={resp.url} body={body}")

    async def _insert(self, table: str, data: dict) -> dict:
        resp = await self.client.post(f"/{table}", json=data)
        if resp.status_code >= 400:
            self._log_error("INSERT", f"/{table}", resp)
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else {}

    async def _select(self, table: str, params: dict = None) -> list[dict]:
        resp = await self.client.get(f"/{table}", params=params or {})
        if resp.status_code >= 400:
            self._log_error("SELECT", f"/{table}", resp)
        resp.raise_for_status()
        return resp.json()

    async def _update(self, table: str, match: dict, data: dict) -> list[dict]:
        params = {k: f"eq.{v}" for k, v in match.items()}
        resp = await self.client.patch(f"/{table}", params=params, json=data)
        if resp.status_code >= 400:
            self._log_error("UPDATE", f"/{table}", resp)
        resp.raise_for_status()
        return resp.json()

    async def _delete(self, table: str, match: dict):
        params = {k: f"eq.{v}" for k, v in match.items()}
        resp = await self.client.delete(f"/{table}", params=params)
        if resp.status_code >= 400:
            self._log_error("DELETE", f"/{table}", resp)
        resp.raise_for_status()

    async def _rpc(self, fn_name: str, params: dict) -> list[dict]:
        resp = await self.client.post(f"/rpc/{fn_name}", json=params)
        if resp.status_code >= 400:
            self._log_error("RPC", f"/rpc/{fn_name}", resp)
        resp.raise_for_status()
        return resp.json()

    # ── discoveries ──

    async def insert_discovery(
        self,
        source_type: str,
        title: str,
        summary: str,
        *,
        source_name: str = None,
        url: str = None,
        raw_content: str = None,
        content_type: str = None,
        interest_score: int = None,
        interest_reason: str = None,
        language: str = None,
        embedding: list[float] = None,
    ) -> str:
        # Dedup by URL
        if url:
            existing = await self._select("discoveries", {
                "select": "id",
                "url": f"eq.{url}",
                "limit": "1",
            })
            if existing:
                return str(existing[0]["id"])

        # Dedup by title prefix (within 7 days)
        if title and len(title) > 20:
            since = (date.today() - timedelta(days=7)).isoformat()
            prefix = title[:40]
            dupes = await self._select("discoveries", {
                "select": "id,title",
                "title": f"like.{prefix}%",
                "explored_at": f"gte.{since}",
                "limit": "5",
            })
            if dupes:
                norm = self._normalize_title(title)
                for d in dupes:
                    if self._normalize_title(d.get("title", "")) == norm:
                        return str(d["id"])

        data = {"source_type": source_type, "title": title, "summary": summary}
        if source_name: data["source_name"] = source_name
        if url: data["url"] = url
        if raw_content: data["raw_content"] = raw_content
        if content_type: data["content_type"] = content_type
        if interest_score is not None: data["interest_score"] = interest_score
        if interest_reason: data["interest_reason"] = interest_reason
        if language: data["language"] = language
        if embedding: data["embedding"] = embedding

        row = await self._insert("discoveries", data)
        return str(row["id"])

    async def get_top_discoveries(self, limit: int = 5, min_score: int = 7) -> list[dict]:
        return await self._select("discoveries", {
            "select": "*",
            "interest_score": f"gte.{min_score}",
            "selected_for_post": "eq.false",
            "order": "interest_score.desc,explored_at.desc",
            "limit": str(limit),
        })

    async def mark_discovery_selected(self, discovery_id: str):
        await self._update("discoveries", {"id": discovery_id}, {"selected_for_post": True})

    # ── posts ──

    async def insert_post(
        self,
        platform: str,
        skill_used: str,
        draft_text: str,
        language: str,
        *,
        discovery_id: str = None,
        posted_text: str = None,
        hook_score: int = None,
        ai_smell_check_passed: bool = None,
        x_post_id: str = None,
        threads_post_id: str = None,
        posted_at: str = None,
    ) -> str:
        data = {
            "platform": platform,
            "skill_used": skill_used,
            "draft_text": draft_text,
            "language": language,
        }
        if discovery_id: data["discovery_id"] = discovery_id
        if posted_text: data["posted_text"] = posted_text
        if hook_score is not None: data["hook_score"] = hook_score
        if ai_smell_check_passed is not None: data["ai_smell_check_passed"] = ai_smell_check_passed
        if x_post_id: data["x_post_id"] = x_post_id
        if threads_post_id: data["threads_post_id"] = threads_post_id
        if posted_at: data["posted_at"] = posted_at

        row = await self._insert("posts", data)
        return str(row["id"])

    async def update_post_engagement(self, post_id: str, interval: str, data: dict):
        field = f"engagement_{interval}"
        await self._update("posts", {"id": post_id}, {field: json.dumps(data)})

    async def link_twin_posts(self, post_id_a: str, post_id_b: str):
        await self._update("posts", {"id": post_id_a}, {"twin_post_id": post_id_b})
        await self._update("posts", {"id": post_id_b}, {"twin_post_id": post_id_a})

    async def get_posts_needing_engagement(self, interval: str) -> list[dict]:
        """Get posts where engagement_{interval} is still empty."""
        now = datetime.utcnow()
        hours = {"3h": 3, "24h": 24, "72h": 72}[interval]
        cutoff = (now - timedelta(hours=hours)).isoformat()
        field = f"engagement_{interval}"
        return await self._select("posts", {
            "select": "id,x_post_id,threads_post_id,platform,posted_at",
            f"{field}": "eq.{}",
            "posted_at": f"lte.{cutoff}",
            "order": "posted_at.desc",
            "limit": "20",
        })

    async def get_recent_posts(self, days: int = 7, platform: str = None) -> list[dict]:
        since = (date.today() - timedelta(days=days)).isoformat()
        params = {
            "select": "*",
            "posted_at": f"gte.{since}",
            "order": "posted_at.desc",
        }
        if platform:
            params["platform"] = f"eq.{platform}"
        return await self._select("posts", params)

    async def get_today_post_count(self, platform: str = None) -> int:
        today = date.today().isoformat()
        params = {
            "select": "id",
            "posted_at": f"gte.{today}",
        }
        if platform:
            params["platform"] = f"eq.{platform}"
        rows = await self._select("posts", params)
        return len(rows)

    # ── interactions ──

    async def insert_interaction(
        self,
        type: str,
        platform: str = "x",
        *,
        related_post_id: str = None,
        thread_id: str = None,
        other_user_handle: str = None,
        other_user_text: str = None,
        my_reply_text: str = None,
        my_reply_x_id: str = None,
        judged_as: str = None,
        thread_round: int = 1,
    ) -> str:
        data = {"type": type, "platform": platform}
        if related_post_id: data["related_post_id"] = related_post_id
        if thread_id: data["thread_id"] = thread_id
        if other_user_handle: data["other_user_handle"] = other_user_handle
        if other_user_text: data["other_user_text"] = other_user_text
        if my_reply_text: data["my_reply_text"] = my_reply_text
        if my_reply_x_id: data["my_reply_x_id"] = my_reply_x_id
        if judged_as: data["judged_as"] = judged_as
        data["thread_round"] = thread_round

        row = await self._insert("interactions", data)
        return str(row["id"])

    async def get_thread_round_count(self, thread_id: str) -> int:
        rows = await self._select("interactions", {
            "select": "id",
            "thread_id": f"eq.{thread_id}",
            "type": "eq.reply_sent",
        })
        return len(rows)

    async def get_today_reply_count(self, platform: str = "x") -> int:
        today = date.today().isoformat()
        rows = await self._select("interactions", {
            "select": "id",
            "type": "eq.reply_sent",
            "platform": f"eq.{platform}",
            "created_at": f"gte.{today}",
        })
        return len(rows)

    # ── token_usage ──

    async def log_token_usage(
        self,
        heartbeat_type: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        model: str,
    ):
        await self._insert("token_usage", {
            "date": date.today().isoformat(),
            "heartbeat_type": heartbeat_type,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "model": model,
        })

    async def get_monthly_cost(self) -> float:
        first_of_month = date.today().replace(day=1).isoformat()
        rows = await self._select("token_usage", {
            "select": "cost_usd",
            "date": f"gte.{first_of_month}",
        })
        return sum(r.get("cost_usd", 0) for r in rows)

    # ── rss_sources ──

    async def get_active_rss_sources(self) -> list[dict]:
        return await self._select("rss_sources", {
            "select": "*",
            "active": "eq.true",
        })

    async def update_rss_last_fetched(self, source_id: str):
        await self._update("rss_sources", {"id": source_id}, {
            "last_fetched_at": datetime.utcnow().isoformat(),
        })

    # ── tracked_handles ──

    async def get_tracked_handles(self) -> list[dict]:
        return await self._select("tracked_handles", {"select": "*"})

    async def add_tracked_handle(self, handle: str, reason: str = None):
        await self._insert("tracked_handles", {
            "handle": handle,
            "reason": reason,
        })

    # ── evolution_log ──

    async def log_evolution(self, type: str, description: str, file_changed: str = None, diff_content: str = None):
        await self._insert("evolution_log", {
            "type": type,
            "description": description,
            "file_changed": file_changed,
            "diff_content": diff_content,
        })

    # ── identity_state ──

    async def get_identity_state(self, key: str) -> str:
        """Read dynamic identity state (curiosity or memory) from DB."""
        rows = await self._select("identity_state", {
            "select": "content",
            "key": f"eq.{key}",
            "limit": "1",
        })
        if rows:
            return rows[0].get("content", "")
        return ""

    async def update_identity_state(self, key: str, content: str, updated_by: str = "lobster"):
        """Write dynamic identity state back to DB."""
        await self._update("identity_state", {"key": key}, {
            "content": content,
            "updated_at": datetime.utcnow().isoformat(),
            "updated_by": updated_by,
        })

    # ── vector search ──

    async def match_discoveries(self, query_embedding: list[float], threshold: float = 0.65, count: int = 10) -> list[dict]:
        return await self._rpc("match_discoveries", {
            "query_embedding": query_embedding,
            "match_threshold": threshold,
            "match_count": count,
        })

    # ── utils ──

    @staticmethod
    def _normalize_title(title: str) -> str:
        t = title.lower().strip()
        t = re.sub(r'^(the|a|an)\s+', '', t)
        t = re.sub(r'[^\w\s]', '', t)
        t = re.sub(r'\s+', ' ', t).strip()
        return t[:80]
