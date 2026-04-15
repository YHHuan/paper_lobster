"""Heartbeat scheduler for Lobster v3.0.

v3 split:
  Social cron (kept from v2.5):
    09:30 — Morning engagement
    15:30 — Afternoon engagement
    12:00 — Midday create_post (only if there's a publishable insight)
    22:00 — Nightly reflection (memory.md update)
    Sun 23:00 — Mirror + Evolve

  Curiosity seeds (NEW):
    06:00 — Morning seed (Reflect → Hypothesize → loop)
    18:00 — Evening seed (humanities/cross-domain bias)

The curiosity loop is event-driven: between seeds it runs autonomously based on
open_questions. Cron only kicks it off and handles social/posting work.
"""

import random
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("lobster.scheduler")

TZ = "Asia/Taipei"
JITTER_MINUTES = 30


def setup_heartbeats(
    scheduler: AsyncIOScheduler,
    lobster,
    *,
    mirror=None,
    evolver=None,
    engagement_tracker=None,
    curiosity_loop=None,
):
    """Register all heartbeat jobs.

    Args:
        scheduler: APScheduler instance.
        lobster: v2.5 Lobster agent (still used for posting / engagement).
        mirror: v3 Mirror (upgraded inputs).
        evolver: v3 Evolver (called by mirror, but exposable directly).
        engagement_tracker: EngagementTracker.
        curiosity_loop: v3 brain.curiosity_loop.CuriosityLoop.
    """

    # ── Curiosity seeds (v3 NEW) ─────────────────────────────

    if curiosity_loop:
        async def morning_seed():
            await curiosity_loop.seed("morning_seed")

        async def evening_seed():
            await curiosity_loop.seed("evening_seed")

        scheduler.add_job(
            _run_with_jitter(morning_seed),
            CronTrigger(hour=6, minute=0, timezone=TZ),
            id="seed_morning",
            name="Morning Seed (Reflect→Hypothesize)",
        )
        scheduler.add_job(
            _run_with_jitter(evening_seed),
            CronTrigger(hour=18, minute=0, timezone=TZ),
            id="seed_evening",
            name="Evening Seed (humanities bias)",
        )

    # ── Social cron (kept from v2.5) ─────────────────────────

    scheduler.add_job(
        _run_with_jitter(lobster.engage, "morning"),
        CronTrigger(hour=9, minute=30, timezone=TZ),
        id="engage_morning",
        name="Morning Engagement",
    )

    scheduler.add_job(
        _run_with_jitter(lobster.create_post),
        CronTrigger(hour=12, minute=0, timezone=TZ),
        id="create_midday",
        name="Midday Creation",
    )

    scheduler.add_job(
        _run_with_jitter(lobster.engage, "afternoon"),
        CronTrigger(hour=15, minute=30, timezone=TZ),
        id="engage_afternoon",
        name="Afternoon Engagement",
    )

    # 22:00 — nightly reflect (memory.md update; lobster.reflect from v2.5)
    scheduler.add_job(
        _run_with_jitter(lobster.reflect),
        CronTrigger(hour=22, minute=0, timezone=TZ),
        id="reflect_night",
        name="Nightly Reflection",
    )

    # Engagement tracking every 2 hours
    if engagement_tracker:
        scheduler.add_job(
            engagement_tracker.update_pending_posts,
            CronTrigger(hour="*/2", timezone=TZ),
            id="engagement_track",
            name="Engagement Tracking",
        )

    # Weekly Mirror — chains into Evolve via Mirror's evolver ref
    if mirror:
        scheduler.add_job(
            mirror.weekly_reflection,
            CronTrigger(day_of_week="sun", hour=23, minute=0, timezone=TZ),
            id="mirror_weekly",
            name="Weekly Mirror + Evolve",
        )

    logger.info(f"Registered {len(scheduler.get_jobs())} heartbeat jobs")


def _run_with_jitter(func, *args):
    """Wrap an async function with random time jitter."""
    import asyncio

    async def wrapper():
        jitter = random.randint(0, JITTER_MINUTES * 60)
        logger.info(f"Heartbeat {getattr(func, '__name__', 'job')} starting in {jitter}s (jitter)")
        await asyncio.sleep(jitter)
        try:
            if args:
                await func(*args)
            else:
                await func()
        except Exception as e:
            logger.error(f"Heartbeat failed: {e}", exc_info=True)

    wrapper.__name__ = getattr(func, '__name__', 'heartbeat')
    return wrapper


# ── v4 standalone worker entry ────────────────────────────────────────────
#
# `lobster loop` runs this. It spins up DB + LLM + brain modules WITHOUT the
# Telegram application, schedules the v3 heartbeat jobs, and idles forever.
# Any push-notification need is handled by bridge.gateway.send_email_notification
# or by the gateway worker's Telegram session (separate Railway process).

async def run_forever() -> None:
    """Standalone curiosity-loop worker. No Telegram dep."""
    import asyncio as _asyncio
    import os as _os
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    log = logging.getLogger("lobster.scheduler.worker")
    log.info("Starting lobster loop worker (no Telegram)")

    # Lazy imports to keep import-time cheap.
    from lobster.db.client import Database
    from lobster.bridge.llm import LobsterLLM
    from lobster.brain.knowledge_state import KnowledgeState
    from lobster.brain.reflect import Reflector
    from lobster.brain.hypothesize import Hypothesizer
    from lobster.brain.curiosity_loop import CuriosityLoop
    from lobster.digester.extract import Extractor
    from lobster.digester.connect import Connector
    from lobster.digester.synthesize import Synthesizer
    from lobster.explorer.forage import Forager
    from lobster.agent_logic.evolve import Evolver

    db = Database()
    await db.connect()
    llm = LobsterLLM(db=db)
    llm.inject_db(db)
    try:
        await llm.load_active_model_from_db()
        await llm.refresh_local_models()
    except Exception as e:
        log.warning(f"LLM init soft-failed: {e}")

    knowledge = KnowledgeState(db, json_path=_os.environ.get("KNOWLEDGE_STATE_PATH"))
    reflector = Reflector(llm, db, knowledge)
    hypothesizer = Hypothesizer(llm, db)
    forager = Forager(llm=llm, db=db)
    extractor = Extractor(llm, db)
    connector = Connector(llm, db)
    synthesizer = Synthesizer(llm, db)

    curiosity_loop = CuriosityLoop(
        llm=llm, db=db, knowledge=knowledge,
        reflector=reflector, hypothesizer=hypothesizer,
        forager=forager, extractor=extractor,
        connector=connector, synthesizer=synthesizer,
        telegram=None,
    )
    evolver = Evolver(llm=llm, db=db, telegram=None)

    scheduler = AsyncIOScheduler(timezone=_os.environ.get("TZ", TZ))

    # Curiosity seeds only — no social/posting jobs in the worker process.
    async def morning_seed():
        await curiosity_loop.seed("morning_seed")

    async def evening_seed():
        await curiosity_loop.seed("evening_seed")

    scheduler.add_job(_run_with_jitter(morning_seed),
                      CronTrigger(hour=6, minute=0, timezone=TZ),
                      id="seed_morning_worker")
    scheduler.add_job(_run_with_jitter(evening_seed),
                      CronTrigger(hour=18, minute=0, timezone=TZ),
                      id="seed_evening_worker")
    scheduler.add_job(_run_with_jitter(evolver.run_weekly),
                      CronTrigger(day_of_week="sun", hour=23, minute=0, timezone=TZ),
                      id="evolve_weekly_worker")

    scheduler.start()
    log.info(f"Worker scheduler started with {len(scheduler.get_jobs())} jobs")

    try:
        while True:
            await _asyncio.sleep(3600)
    except (KeyboardInterrupt, _asyncio.CancelledError):
        log.info("Worker shutting down")
    finally:
        scheduler.shutdown(wait=False)
        await curiosity_loop.stop()
        await forager.close()
        await llm.close()
        await db.close()
