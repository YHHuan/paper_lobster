"""Lobster v2.5 — Entry point.

Starts the Telegram bot with webhook (Railway) or polling (local),
initializes all components, and registers heartbeat schedule.
"""

import os
import sys
import logging
import asyncio

from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("lobster")


async def post_init(application):
    """Initialize all components after bot starts."""
    from llm.client import LLMClient
    from db.client import Database
    from explorer.search import TavilySearch
    from explorer.rss import RSSReader
    from explorer.reader import JinaReader
    from explorer.x_listener import XListener
    from publisher.threads_poster import ThreadsPoster
    from publisher.engagement_tracker import EngagementTracker
    from agent.lobster import Lobster
    from agent.mirror import Mirror
    from scheduler.heartbeat import setup_heartbeats

    # Initialize core services
    db = Database()
    await db.connect()
    llm = LLMClient()

    # Initialize explorers
    searcher = TavilySearch()
    rss_reader = RSSReader(db)
    jina_reader = JinaReader()
    x_listener = XListener()

    # Initialize publishers
    threads_poster = ThreadsPoster()

    # Get telegram bot reference
    telegram_bot = application.bot_data.get("telegram_bot")

    # Build main lobster agent
    lobster = Lobster(
        llm=llm,
        db=db,
        threads_poster=threads_poster,
        telegram=telegram_bot,
        searcher=searcher,
        rss_reader=rss_reader,
        jina_reader=jina_reader,
        x_listener=x_listener,
    )

    # Build mirror agent
    mirror = Mirror(llm=llm, db=db, telegram=telegram_bot)

    # Build engagement tracker
    engagement_tracker = EngagementTracker(
        db=db,
        x_listener=x_listener,
        threads_poster=threads_poster,
    )

    # Wire up telegram bot with initialized services
    telegram_bot.db = db
    telegram_bot.llm = llm
    telegram_bot.lobster = lobster

    # Store references
    application.bot_data["db"] = db
    application.bot_data["llm"] = llm
    application.bot_data["lobster"] = lobster
    application.bot_data["mirror"] = mirror

    # Setup heartbeat scheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler(timezone=os.environ.get("TZ", "Asia/Taipei"))
    setup_heartbeats(scheduler, lobster, mirror, engagement_tracker)
    scheduler.start()
    application.bot_data["scheduler"] = scheduler

    logger.info("🦞 Lobster v2.5 initialized — all systems go")
    if telegram_bot:
        await telegram_bot.notify("🦞 Lobster v2.5 is online!")


async def post_shutdown(application):
    """Cleanup on shutdown."""
    db = application.bot_data.get("db")
    if db:
        await db.close()

    llm = application.bot_data.get("llm")
    if llm:
        await llm.close()

    scheduler = application.bot_data.get("scheduler")
    if scheduler:
        scheduler.shutdown(wait=False)

    logger.info("Lobster v2.5 shut down")


def main():
    from bot.telegram import TelegramBot

    telegram_bot = TelegramBot()
    app = telegram_bot.build_app()
    app.bot_data["telegram_bot"] = telegram_bot

    # Wire up telegram bot's db/llm refs (will be set in post_init)
    app.post_init = post_init
    app.post_shutdown = post_shutdown

    webhook_url = os.environ.get("WEBHOOK_URL")
    port = int(os.environ.get("PORT", "8000"))

    if webhook_url:
        logger.info(f"Starting in webhook mode: {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            webhook_url=webhook_url,
            allowed_updates=["message", "callback_query"],
        )
    else:
        logger.info("Starting in polling mode (local dev)")
        app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
