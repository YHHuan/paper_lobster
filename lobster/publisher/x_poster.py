"""X (Twitter) publisher using OAuth 1.0a via tweepy.

Handles tweet posting, thread splitting, and CJK-aware character counting.
Adapted from v1 with cleaner interface.
"""

import os
import re
import logging
import asyncio

logger = logging.getLogger("lobster.publisher.x")


def _get_client():
    import tweepy
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_SECRET"],
    )


def _twitter_weighted_len(text: str) -> int:
    """Twitter's weighted character count (CJK = 2, URLs = 23)."""
    url_pattern = re.compile(r'https?://\S+')
    cleaned = url_pattern.sub('x' * 23, text)
    count = 0
    for ch in cleaned:
        cp = ord(ch)
        if (0x1100 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF or
            0xFE30 <= cp <= 0xFE4F or 0x20000 <= cp <= 0x2FA1F or
            0xFF01 <= cp <= 0xFF60):
            count += 2
        else:
            count += 1
    return count


def _split_thread(text: str, url: str = None, max_chars: int = 280) -> list[str]:
    """Split long text into tweet thread with CJK-aware counting."""
    wlen = _twitter_weighted_len
    full = f"{text}\n\n{url}" if url else text
    if wlen(full) <= max_chars:
        return [full]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    tweets = []
    current = ""
    reserve = 15

    for para in paragraphs:
        test = f"{current}\n\n{para}".strip() if current else para
        if wlen(test) <= max_chars - reserve:
            current = test
        else:
            if current:
                tweets.append(current)
            if wlen(para) > max_chars - reserve:
                sentences = re.split(r'(?<=[。.!?！？])\s*', para)
                current = ""
                for sent in sentences:
                    test = f"{current} {sent}".strip() if current else sent
                    if wlen(test) <= max_chars - reserve:
                        current = test
                    else:
                        if current:
                            tweets.append(current)
                        current = sent[:max_chars - reserve]
            else:
                current = para

    if current:
        tweets.append(current)

    if url and tweets:
        first = tweets[0]
        if wlen(f"{first}\n\n{url}") <= max_chars:
            tweets[0] = f"{first}\n\n{url}"
        else:
            tweets.insert(0, f"🔗 {url}")

    if len(tweets) > 1:
        total = len(tweets)
        tweets = [f"{t}\n\n🧵 {i}/{total}" for i, t in enumerate(tweets, 1)]

    return tweets


def is_configured() -> bool:
    keys = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"]
    return all(os.environ.get(k) for k in keys)


async def post_tweet(text: str, url: str = None) -> dict:
    """Post a tweet (or thread if long). Returns {tweet_id, url, thread_length}."""
    tweets = _split_thread(text.strip(), url=url)
    logger.info(f"Posting {'thread' if len(tweets) > 1 else 'tweet'} ({len(tweets)} parts)")

    def _post():
        client = _get_client()
        handle = os.environ.get("TWITTER_HANDLE", "")
        reply_to = None
        first_tweet_id = None
        first_url = ""

        for i, tweet in enumerate(tweets):
            kwargs = {"text": tweet}
            if reply_to:
                kwargs["in_reply_to_tweet_id"] = reply_to
            try:
                resp = client.create_tweet(**kwargs)
            except Exception as e:
                logger.error(f"Tweet {i+1} failed: {e}")
                raise
            tweet_id = resp.data["id"]
            if first_tweet_id is None:
                first_tweet_id = tweet_id
                first_url = f"https://x.com/{handle}/status/{tweet_id}" if handle else ""
            reply_to = tweet_id

        return {
            "tweet_id": first_tweet_id,
            "url": first_url,
            "thread_length": len(tweets),
        }

    return await asyncio.get_event_loop().run_in_executor(None, _post)


async def post_reply(text: str, reply_to_id: str) -> dict:
    """Post a reply to an existing tweet."""
    def _post():
        client = _get_client()
        handle = os.environ.get("TWITTER_HANDLE", "")
        resp = client.create_tweet(text=text, in_reply_to_tweet_id=reply_to_id)
        tweet_id = resp.data["id"]
        url = f"https://x.com/{handle}/status/{tweet_id}" if handle else ""
        return {"tweet_id": tweet_id, "url": url}

    return await asyncio.get_event_loop().run_in_executor(None, _post)
