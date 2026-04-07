"""Heartbeat scheduler for Lobster v2.5.

6 daily heartbeats in Asia/Taipei timezone:
06:00 — Morning exploration
09:30 — Morning engagement
12:00 — Midday content creation
15:30 — Afternoon engagement
18:00 — Evening exploration + optional second post
22:00 — Nightly reflection

Plus weekly: Sunday 23:00 — Mirror self-reflection
"""

import random
import logging
from datetime import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("lobster.scheduler")

TZ = "Asia/Taipei"
JITTER_MINUTES = 45


def setup_heartbeats(scheduler: AsyncIOScheduler, lobster, mirror=None, engagement_tracker=None):
    """Register all heartbeat jobs.

    Args:
        scheduler: APScheduler instance.
        lobster: Lobster agent instance.
        mirror: Mirror agent instance (optional).
        engagement_tracker: EngagementTracker instance (optional).
    """

    # 06:00 — Morning exploration
    scheduler.add_job(
        _run_with_jitter(lobster.explore, "morning"),
        CronTrigger(hour=6, minute=0, timezone=TZ),
        id="exploration_morning",
        name="Morning Exploration",
    )

    # 09:30 — Morning engagement
    scheduler.add_job(
        _run_with_jitter(lobster.engage, "morning"),
        CronTrigger(hour=9, minute=30, timezone=TZ),
        id="engage_morning",
        name="Morning Engagement",
    )

    # 12:00 — Midday content creation
    scheduler.add_job(
        _run_with_jitter(lobster.create_post),
        CronTrigger(hour=12, minute=0, timezone=TZ),
        id="create_midday",
        name="Midday Creation",
    )

    # 15:30 — Afternoon engagement
    scheduler.add_job(
        _run_with_jitter(lobster.engage, "afternoon"),
        CronTrigger(hour=15, minute=30, timezone=TZ),
        id="engage_afternoon",
        name="Afternoon Engagement",
    )

    # 18:00 — Evening exploration (+ optional second post)
    async def evening_cycle():
        await lobster.explore("evening")
        # Chance of a second post
        if random.random() > 0.5:
            await lobster.create_post()

    scheduler.add_job(
        _run_with_jitter(evening_cycle),
        CronTrigger(hour=18, minute=0, timezone=TZ),
        id="exploration_evening",
        name="Evening Exploration",
    )

    # 22:00 — Nightly reflection
    scheduler.add_job(
        _run_with_jitter(lobster.reflect),
        CronTrigger(hour=22, minute=0, timezone=TZ),
        id="reflect_night",
        name="Nightly Reflection",
    )

    # Engagement tracking (every 2 hours)
    if engagement_tracker:
        scheduler.add_job(
            engagement_tracker.update_pending_posts,
            CronTrigger(hour="*/2", timezone=TZ),
            id="engagement_track",
            name="Engagement Tracking",
        )

    # Weekly Mirror (Sunday 23:00)
    if mirror:
        scheduler.add_job(
            mirror.weekly_reflection,
            CronTrigger(day_of_week="sun", hour=23, minute=0, timezone=TZ),
            id="mirror_weekly",
            name="Weekly Mirror",
        )

    logger.info(f"Registered {len(scheduler.get_jobs())} heartbeat jobs")


def _run_with_jitter(func, *args):
    """Wrap an async function with random time jitter."""
    import asyncio

    async def wrapper():
        jitter = random.randint(0, JITTER_MINUTES * 60)
        logger.info(f"Heartbeat {func.__name__} starting in {jitter}s (jitter)")
        await asyncio.sleep(jitter)
        try:
            if args:
                await func(*args)
            else:
                await func()
        except Exception as e:
            logger.error(f"Heartbeat {func.__name__} failed: {e}", exc_info=True)

    wrapper.__name__ = getattr(func, '__name__', 'heartbeat')
    return wrapper
