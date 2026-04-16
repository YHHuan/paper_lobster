"""Supabase REST API client for Lobster v3.0.

Uses HTTPS only (no direct PostgreSQL), works everywhere including WSL.

v2.5 tables (preserved): discoveries, posts, interactions, evolution_log,
  token_usage, rss_sources, tracked_handles, identity_state.

v3 tables (added): knowledge_clusters, extracts, connections, insights,
  open_questions, source_weights, loop_runs, evolution_proposals, reflections.
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

    # ============================================================
    # v3 ADDITIONS — curiosity loop / brain / digester
    # ============================================================

    # ── knowledge_clusters ──

    async def upsert_cluster(
        self,
        cluster_id: str,
        current_understanding: str,
        *,
        confidence: float = 0.5,
        key_sources: list[str] | None = None,
        open_gaps: list[str] | None = None,
        related_clusters: list[str] | None = None,
    ):
        existing = await self._select("knowledge_clusters", {
            "select": "id",
            "id": f"eq.{cluster_id}",
            "limit": "1",
        })
        data = {
            "current_understanding": current_understanding,
            "confidence": confidence,
            "key_sources": key_sources or [],
            "open_gaps": open_gaps or [],
            "related_clusters": related_clusters or [],
            "updated_at": datetime.utcnow().isoformat(),
        }
        if existing:
            await self._update("knowledge_clusters", {"id": cluster_id}, data)
        else:
            data["id"] = cluster_id
            await self._insert("knowledge_clusters", data)

    async def get_cluster(self, cluster_id: str) -> dict | None:
        rows = await self._select("knowledge_clusters", {
            "select": "*",
            "id": f"eq.{cluster_id}",
            "limit": "1",
        })
        return rows[0] if rows else None

    async def list_clusters(self, limit: int = 50) -> list[dict]:
        return await self._select("knowledge_clusters", {
            "select": "*",
            "order": "updated_at.desc",
            "limit": str(limit),
        })

    async def get_clusters_summary(self) -> str:
        """Compact text summary of all clusters — for prompts."""
        rows = await self.list_clusters(limit=30)
        lines = []
        for r in rows:
            understanding = (r.get('current_understanding') or '')[:200]
            lines.append(f"- {r['id']} (conf={r.get('confidence') or 0:.2f}): {understanding}")
        return "\n".join(lines) if lines else "(沒有 cluster — 龍蝦剛開始學習)"

    # ── extracts ──

    async def insert_extract(
        self,
        extract_id: str,
        source_type: str,
        structured_data: dict,
        *,
        source_id: str | None = None,
        url: str | None = None,
        title: str | None = None,
        one_liner: str | None = None,
    ) -> str:
        data = {
            "id": extract_id,
            "source_type": source_type,
            "structured_data": structured_data,
        }
        if source_id: data["source_id"] = source_id
        if url: data["url"] = url
        if title: data["title"] = title
        if one_liner: data["one_liner"] = one_liner
        await self._insert("extracts", data)
        return extract_id

    async def get_extract(self, extract_id: str) -> dict | None:
        rows = await self._select("extracts", {
            "select": "*",
            "id": f"eq.{extract_id}",
            "limit": "1",
        })
        return rows[0] if rows else None

    async def get_recent_extracts(self, days: int = 7, limit: int = 50) -> list[dict]:
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        return await self._select("extracts", {
            "select": "*",
            "created_at": f"gte.{since}",
            "order": "created_at.desc",
            "limit": str(limit),
        })

    # ── connections ──

    async def insert_connection(
        self,
        connection_id: str,
        extract_id: str,
        connection_type: str,
        *,
        connected_clusters: list[str] | None = None,
        insight: str | None = None,
        confidence: float | None = None,
        questions_spawned: list[str] | None = None,
    ):
        data = {
            "id": connection_id,
            "extract_id": extract_id,
            "connection_type": connection_type,
            "connected_clusters": connected_clusters or [],
            "questions_spawned": questions_spawned or [],
        }
        if insight: data["insight"] = insight
        if confidence is not None: data["confidence"] = confidence
        await self._insert("connections", data)

    async def get_connection_rate(self, source: str, days: int = 7) -> float:
        """Connection rate = non-irrelevant connections / total extracts for source over N days."""
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        # Get extracts for this source
        extracts = await self._select("extracts", {
            "select": "id",
            "source_type": f"eq.{source}",
            "created_at": f"gte.{since}",
        })
        if not extracts:
            return 0.0
        ext_ids = [e["id"] for e in extracts]
        # Get connections that aren't irrelevant
        # Supabase REST: in.(...) syntax
        ids_csv = ",".join(ext_ids)
        conns = await self._select("connections", {
            "select": "extract_id,connection_type",
            "extract_id": f"in.({ids_csv})",
            "connection_type": "neq.irrelevant",
        })
        return len(conns) / len(extracts)

    async def get_recent_connections(self, days: int = 7, limit: int = 100) -> list[dict]:
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        return await self._select("connections", {
            "select": "*",
            "created_at": f"gte.{since}",
            "order": "created_at.desc",
            "limit": str(limit),
        })

    # ── insights ──

    async def insert_insight(
        self,
        insight_id: str,
        type: str,
        title: str,
        body: str,
        *,
        soul_relevance: list[str] | None = None,
        publishable: bool = False,
        hook_score: int | None = None,
        source_extracts: list[str] | None = None,
    ) -> str:
        data = {
            "id": insight_id,
            "type": type,
            "title": title,
            "body": body,
            "soul_relevance": soul_relevance or [],
            "publishable": publishable,
            "source_extracts": source_extracts or [],
        }
        if hook_score is not None: data["hook_score"] = hook_score
        await self._insert("insights", data)
        return insight_id

    async def mark_insight_published(self, insight_id: str):
        await self._update("insights", {"id": insight_id}, {"published": True})

    async def rate_insight(self, insight_id: str, rating: int, comment: str | None = None):
        data = {"human_rating": rating}
        if comment: data["human_comment"] = comment
        await self._update("insights", {"id": insight_id}, data)

    async def get_recent_insights(self, days: int = 7, limit: int = 50) -> list[dict]:
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        return await self._select("insights", {
            "select": "*",
            "created_at": f"gte.{since}",
            "order": "created_at.desc",
            "limit": str(limit),
        })

    async def get_publishable_insights(self, limit: int = 10) -> list[dict]:
        return await self._select("insights", {
            "select": "*",
            "publishable": "eq.true",
            "published": "eq.false",
            "order": "hook_score.desc.nullslast,created_at.desc",
            "limit": str(limit),
        })

    # ── open_questions ──

    async def insert_open_question(
        self,
        question: str,
        *,
        soul_anchor: str | None = None,
        expected_source_types: list[str] | None = None,
        priority: float = 0.5,
        reasoning: str | None = None,
        parent_insight_id: str | None = None,
    ) -> int:
        data = {
            "question": question,
            "expected_source_types": expected_source_types or [],
            "priority": priority,
            "status": "pending",
        }
        if soul_anchor: data["soul_anchor"] = soul_anchor
        if reasoning: data["reasoning"] = reasoning
        if parent_insight_id: data["parent_insight_id"] = parent_insight_id
        row = await self._insert("open_questions", data)
        return row.get("id")

    async def get_pending_questions(self, limit: int = 10) -> list[dict]:
        return await self._select("open_questions", {
            "select": "*",
            "status": "eq.pending",
            "order": "priority.desc,created_at.asc",
            "limit": str(limit),
        })

    async def count_pending_questions(self) -> int:
        rows = await self._select("open_questions", {
            "select": "id",
            "status": "eq.pending",
        })
        return len(rows)

    async def mark_question_status(self, question_id: int, status: str):
        data = {"status": status}
        if status == "resolved":
            data["resolved_at"] = datetime.utcnow().isoformat()
        await self._update("open_questions", {"id": question_id}, data)

    async def get_recent_questions_text(self, limit: int = 20) -> list[str]:
        rows = await self._select("open_questions", {
            "select": "question",
            "order": "created_at.desc",
            "limit": str(limit),
        })
        return [r["question"] for r in rows]

    # ── source_weights ──

    async def get_source_weights(self) -> dict[str, float]:
        rows = await self._select("source_weights", {"select": "source,weight"})
        return {r["source"]: r.get("weight", 0.5) for r in rows}

    async def get_source_weights_full(self) -> list[dict]:
        return await self._select("source_weights", {"select": "*"})

    async def update_source_weight(self, source: str, weight: float, *, connect_rate_7d: float | None = None):
        data = {"weight": weight, "updated_at": datetime.utcnow().isoformat()}
        if connect_rate_7d is not None:
            data["connect_rate_7d"] = connect_rate_7d
        await self._update("source_weights", {"source": source}, data)

    async def bump_source_counters(self, source: str, *, extracts: int = 0, connects: int = 0):
        rows = await self._select("source_weights", {
            "select": "total_extracts,total_connects",
            "source": f"eq.{source}",
            "limit": "1",
        })
        if not rows:
            await self._insert("source_weights", {
                "source": source,
                "total_extracts": extracts,
                "total_connects": connects,
            })
            return
        cur = rows[0]
        await self._update("source_weights", {"source": source}, {
            "total_extracts": (cur.get("total_extracts") or 0) + extracts,
            "total_connects": (cur.get("total_connects") or 0) + connects,
            "updated_at": datetime.utcnow().isoformat(),
        })

    # ── loop_runs ──

    async def start_loop_run(self, questions_input: int) -> int:
        row = await self._insert("loop_runs", {
            "questions_input": questions_input,
            "status": "running",
        })
        return row.get("id")

    async def finish_loop_run(
        self,
        run_id: int,
        *,
        extracts_produced: int = 0,
        connections_made: int = 0,
        insights_generated: int = 0,
        local_tokens_used: int = 0,
        remote_tokens_used: int = 0,
        status: str = "completed",
        notes: str | None = None,
    ):
        data = {
            "finished_at": datetime.utcnow().isoformat(),
            "extracts_produced": extracts_produced,
            "connections_made": connections_made,
            "insights_generated": insights_generated,
            "local_tokens_used": local_tokens_used,
            "remote_tokens_used": remote_tokens_used,
            "status": status,
        }
        if notes: data["notes"] = notes
        await self._update("loop_runs", {"id": run_id}, data)

    async def get_today_loop_count(self) -> int:
        today = date.today().isoformat()
        rows = await self._select("loop_runs", {
            "select": "id",
            "started_at": f"gte.{today}",
        })
        return len(rows)

    async def get_recent_loop_stats(self, days: int = 7) -> dict:
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        rows = await self._select("loop_runs", {
            "select": "*",
            "started_at": f"gte.{since}",
        })
        empty = sum(1 for r in rows if (r.get("insights_generated") or 0) == 0)
        return {
            "total_loops": len(rows),
            "avg_loops_per_day": round(len(rows) / max(days, 1), 1),
            "empty_loops": empty,
            "extracts_produced": sum(r.get("extracts_produced") or 0 for r in rows),
            "connections_made": sum(r.get("connections_made") or 0 for r in rows),
            "insights_generated": sum(r.get("insights_generated") or 0 for r in rows),
            "local_tokens_used": sum(r.get("local_tokens_used") or 0 for r in rows),
            "remote_tokens_used": sum(r.get("remote_tokens_used") or 0 for r in rows),
        }

    # ── evolution_proposals ──

    async def insert_proposal(self, type: str, proposal: dict) -> int:
        row = await self._insert("evolution_proposals", {
            "type": type,
            "proposal": proposal,
        })
        return row.get("id")

    async def get_pending_proposals(self) -> list[dict]:
        return await self._select("evolution_proposals", {
            "select": "*",
            "status": "eq.pending",
            "order": "created_at.desc",
        })

    async def resolve_proposal(self, proposal_id: int, status: str):
        await self._update("evolution_proposals", {"id": proposal_id}, {
            "status": status,
            "resolved_at": datetime.utcnow().isoformat(),
        })

    # ── reflections ──

    async def insert_reflection(self, memo: str, trigger: str = "manual") -> int:
        row = await self._insert("reflections", {
            "memo": memo,
            "trigger": trigger,
        })
        return row.get("id")

    async def get_recent_reflections(self, days: int = 7, limit: int = 5) -> list[dict]:
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        return await self._select("reflections", {
            "select": "*",
            "created_at": f"gte.{since}",
            "order": "created_at.desc",
            "limit": str(limit),
        })

    async def get_recent_digest_summary(self, days: int = 7) -> str:
        """For Reflect prompt input — compact text of recent extracts + insights."""
        extracts = await self.get_recent_extracts(days=days, limit=20)
        insights = await self.get_recent_insights(days=days, limit=10)
        lines = ["## Recent extracts"]
        for e in extracts:
            title = (e.get('title') or '?')[:100]
            one_liner = (e.get('one_liner') or '')[:150]
            lines.append(f"- [{e.get('source_type') or '?'}] {title} — {one_liner}")
        lines.append("\n## Recent insights")
        for i in insights:
            ititle = i.get('title') or ''
            ibody = (i.get('body') or '')[:200]
            lines.append(f"- ({i.get('type') or '?'}) {ititle}: {ibody}")
        return "\n".join(lines) if (extracts or insights) else "(這 7 天沒有任何 digest)"

    # ── pause flag ──

    async def is_loop_paused(self) -> bool:
        v = await self.get_identity_state("curiosity_loop_paused")
        return (v or "").strip().lower() in ("true", "1", "yes")

    async def set_loop_paused(self, paused: bool):
        await self.update_identity_state("curiosity_loop_paused", "true" if paused else "false", "user")
