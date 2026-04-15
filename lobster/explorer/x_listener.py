"""X (Twitter) API listener.

Reads mentions, replies, and tracked handles' recent tweets.
X API Free Tier: ~100 reads/month — budget carefully.

Strategy: 3 reads/day (09:30, 15:30, 22:00) = ~90/month with buffer.
"""

import os
import logging
import asyncio

logger = logging.getLogger("lobster.explorer.x_listener")


class XListener:
    def __init__(self):
        self.bearer_token = os.environ.get("TWITTER_BEARER_TOKEN", "")
        self._monthly_reads = 0

    def _get_client(self):
        import tweepy
        return tweepy.Client(bearer_token=self.bearer_token)

    async def fetch_mentions(self, user_id: str, since_id: str = None) -> list[dict]:
        """Fetch recent mentions of our account.

        Args:
            user_id: Our Twitter user ID.
            since_id: Only get mentions after this tweet ID.

        Returns:
            List of {id, text, author_id, conversation_id, created_at}.
        """
        if not self.bearer_token:
            logger.debug("No TWITTER_BEARER_TOKEN, skipping mentions")
            return []

        if self._monthly_reads >= 90:
            logger.warning("X API monthly read limit approaching, skipping")
            return []

        def _fetch():
            client = self._get_client()
            kwargs = {
                "id": user_id,
                "tweet_fields": ["conversation_id", "created_at", "author_id"],
                "max_results": 10,
            }
            if since_id:
                kwargs["since_id"] = since_id
            try:
                resp = client.get_users_mentions(**kwargs)
                self._monthly_reads += 1
                if not resp.data:
                    return []
                return [
                    {
                        "id": str(t.id),
                        "text": t.text,
                        "author_id": str(t.author_id),
                        "conversation_id": str(t.conversation_id) if t.conversation_id else None,
                        "created_at": t.created_at.isoformat() if t.created_at else None,
                    }
                    for t in resp.data
                ]
            except Exception as e:
                logger.error(f"Failed to fetch mentions: {e}")
                return []

        return await asyncio.get_event_loop().run_in_executor(None, _fetch)

    async def fetch_replies_to_post(self, conversation_id: str) -> list[dict]:
        """Fetch replies in a conversation thread.

        Args:
            conversation_id: The conversation/thread ID.

        Returns:
            List of {id, text, author_id, created_at}.
        """
        if not self.bearer_token or self._monthly_reads >= 90:
            return []

        def _fetch():
            client = self._get_client()
            try:
                resp = client.search_recent_tweets(
                    query=f"conversation_id:{conversation_id}",
                    tweet_fields=["author_id", "created_at", "in_reply_to_user_id"],
                    max_results=20,
                )
                self._monthly_reads += 1
                if not resp.data:
                    return []
                return [
                    {
                        "id": str(t.id),
                        "text": t.text,
                        "author_id": str(t.author_id),
                        "created_at": t.created_at.isoformat() if t.created_at else None,
                    }
                    for t in resp.data
                ]
            except Exception as e:
                logger.error(f"Failed to fetch replies for {conversation_id}: {e}")
                return []

        return await asyncio.get_event_loop().run_in_executor(None, _fetch)

    async def fetch_tweet_metrics(self, tweet_id: str) -> dict | None:
        """Fetch engagement metrics for a single tweet."""
        if not self.bearer_token or self._monthly_reads >= 90:
            return None

        def _fetch():
            client = self._get_client()
            try:
                resp = client.get_tweet(
                    tweet_id,
                    tweet_fields=["public_metrics"],
                )
                self._monthly_reads += 1
                if resp.data and resp.data.public_metrics:
                    m = resp.data.public_metrics
                    return {
                        "impressions": m.get("impression_count", 0),
                        "likes": m.get("like_count", 0),
                        "retweets": m.get("retweet_count", 0),
                        "replies": m.get("reply_count", 0),
                        "quotes": m.get("quote_count", 0),
                        "bookmarks": m.get("bookmark_count", 0),
                    }
            except Exception as e:
                logger.warning(f"Failed to fetch metrics for {tweet_id}: {e}")
            return None

        return await asyncio.get_event_loop().run_in_executor(None, _fetch)

    def get_monthly_reads(self) -> int:
        return self._monthly_reads

    def reset_monthly_reads(self):
        self._monthly_reads = 0
