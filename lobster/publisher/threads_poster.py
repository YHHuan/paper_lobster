"""Threads publisher via Meta Graph API.

Two-step flow: create media container → publish.
Dev mode: can only reply to own posts, not engage with strangers.
"""

import os
import logging

import httpx

logger = logging.getLogger("lobster.publisher.threads")

GRAPH_API = "https://graph.threads.net/v1.0"


class ThreadsPoster:
    def __init__(self):
        self.token = os.environ.get("THREADS_ACCESS_TOKEN", "")
        self.user_id = os.environ.get("THREADS_USER_ID", "")
        self.client = httpx.AsyncClient(timeout=30.0)

    def is_configured(self) -> bool:
        return bool(self.token and self.user_id)

    async def post(self, text: str) -> str | None:
        """Post a new thread. Returns threads_post_id or None."""
        if not self.is_configured():
            logger.warning("Threads not configured")
            return None

        try:
            # Step 1: create container
            create_resp = await self.client.post(
                f"{GRAPH_API}/{self.user_id}/threads",
                params={
                    "media_type": "TEXT",
                    "text": text,
                    "access_token": self.token,
                },
            )
            create_resp.raise_for_status()
            container_id = create_resp.json().get("id")
            if not container_id:
                logger.error("Failed to create Threads container")
                return None

            # Step 2: publish
            publish_resp = await self.client.post(
                f"{GRAPH_API}/{self.user_id}/threads_publish",
                params={
                    "creation_id": container_id,
                    "access_token": self.token,
                },
            )
            publish_resp.raise_for_status()
            post_id = publish_resp.json().get("id")
            logger.info(f"Posted to Threads: {post_id}")
            return post_id

        except Exception as e:
            logger.error(f"Threads post failed: {e}")
            return None

    async def reply(self, target_post_id: str, text: str) -> str | None:
        """Reply to a post (own posts only in dev mode)."""
        if not self.is_configured():
            return None

        try:
            create_resp = await self.client.post(
                f"{GRAPH_API}/{self.user_id}/threads",
                params={
                    "media_type": "TEXT",
                    "text": text,
                    "reply_to_id": target_post_id,
                    "access_token": self.token,
                },
            )
            create_resp.raise_for_status()
            container_id = create_resp.json().get("id")
            if not container_id:
                return None

            publish_resp = await self.client.post(
                f"{GRAPH_API}/{self.user_id}/threads_publish",
                params={
                    "creation_id": container_id,
                    "access_token": self.token,
                },
            )
            publish_resp.raise_for_status()
            return publish_resp.json().get("id")

        except Exception as e:
            logger.error(f"Threads reply failed: {e}")
            return None

    async def fetch_my_posts(self, limit: int = 25) -> list:
        """Fetch own recent posts."""
        if not self.is_configured():
            return []

        try:
            resp = await self.client.get(
                f"{GRAPH_API}/{self.user_id}/threads",
                params={
                    "fields": "id,text,timestamp,permalink",
                    "limit": limit,
                    "access_token": self.token,
                },
            )
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception as e:
            logger.error(f"Threads fetch posts failed: {e}")
            return []

    async def fetch_replies(self, threads_post_id: str) -> list:
        """Fetch replies to a specific post."""
        if not self.is_configured():
            return []

        try:
            resp = await self.client.get(
                f"{GRAPH_API}/{threads_post_id}/replies",
                params={
                    "fields": "id,text,username,timestamp",
                    "access_token": self.token,
                },
            )
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception as e:
            logger.error(f"Threads fetch replies failed: {e}")
            return []

    async def fetch_insights(self, threads_post_id: str) -> dict:
        """Fetch engagement metrics for a post."""
        if not self.is_configured():
            return {}

        try:
            resp = await self.client.get(
                f"{GRAPH_API}/{threads_post_id}/insights",
                params={
                    "metric": "views,likes,replies,reposts,quotes",
                    "access_token": self.token,
                },
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            return {item["name"]: item["values"][0]["value"] for item in data}
        except Exception as e:
            logger.error(f"Threads fetch insights failed: {e}")
            return {}

    async def close(self):
        await self.client.aclose()
