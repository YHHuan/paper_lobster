"""Engagement tracker for published posts.

Checks which posts need engagement data at 3h, 24h, 72h intervals
and fetches metrics from X and Threads APIs.
"""

import logging

logger = logging.getLogger("lobster.publisher.engagement")

INTERVALS = ["3h", "24h", "72h"]


class EngagementTracker:
    def __init__(self, db, x_listener=None, threads_poster=None):
        self.db = db
        self.x_listener = x_listener
        self.threads_poster = threads_poster

    async def update_pending_posts(self):
        """Check all intervals and update posts that are due."""
        for interval in INTERVALS:
            try:
                posts = await self.db.get_posts_needing_engagement(interval)
                for post in posts:
                    metrics = await self._fetch_metrics(post)
                    if metrics:
                        await self.db.update_post_engagement(
                            str(post["id"]), interval, metrics
                        )
                        logger.info(
                            f"Updated {interval} engagement for post {post['id']}: {metrics}"
                        )
            except Exception as e:
                logger.error(f"Engagement update failed for {interval}: {e}")

    async def _fetch_metrics(self, post: dict) -> dict | None:
        """Fetch metrics from the appropriate platform."""
        platform = post.get("platform", "x")

        if platform == "x" and self.x_listener and post.get("x_post_id"):
            return await self.x_listener.fetch_tweet_metrics(post["x_post_id"])

        if platform == "threads" and self.threads_poster and post.get("threads_post_id"):
            return await self.threads_poster.fetch_insights(post["threads_post_id"])

        return None

    async def get_weekly_summary(self) -> dict:
        """Generate summary for Mirror's weekly analysis."""
        posts = await self.db.get_recent_posts(days=7)

        total_impressions = 0
        total_likes = 0
        total_replies = 0
        posts_with_data = 0

        best_post = None
        worst_post = None
        best_engagement = -1
        worst_engagement = float("inf")

        for p in posts:
            eng = p.get("engagement_24h", {})
            if isinstance(eng, str):
                import json
                try:
                    eng = json.loads(eng)
                except Exception:
                    eng = {}

            if not eng or eng == {}:
                continue

            posts_with_data += 1
            impressions = eng.get("impressions", eng.get("views", 0))
            likes = eng.get("likes", eng.get("like_count", 0))
            replies = eng.get("replies", eng.get("reply_count", 0))

            total_impressions += impressions
            total_likes += likes
            total_replies += replies

            score = likes + replies * 2
            if score > best_engagement:
                best_engagement = score
                best_post = p
            if score < worst_engagement:
                worst_engagement = score
                worst_post = p

        return {
            "total_posts": len(posts),
            "posts_with_data": posts_with_data,
            "total_impressions": total_impressions,
            "total_likes": total_likes,
            "total_replies": total_replies,
            "avg_engagement_rate": (
                round((total_likes + total_replies) / total_impressions * 100, 2)
                if total_impressions > 0 else 0
            ),
            "best_post": (best_post.get("posted_text", "")[:80] if best_post else None),
            "worst_post": (worst_post.get("posted_text", "")[:80] if worst_post else None),
        }
