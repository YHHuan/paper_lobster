"""Lobster v3.0 — Entry point.

Starts the Telegram bot with webhook (Railway) or polling (local),
initializes all v2.5 components + v3 brain / digester / forage / evolve.
"""

import os
import logging

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("lobster")


async def post_init(application):
    """Initialize all components after bot starts."""
    from llm.router import LLMRouter
    from db.client import Database
    from explorer.search import TavilySearch
    from explorer.rss import RSSReader
    from explorer.reader import JinaReader
    from explorer.x_listener import XListener
    from explorer.academic import AcademicSearch
    from explorer.browser import HeadlessBrowser
    from explorer.pdf_reader import PDFReader
    from explorer.forage import Forager
    from agent.evolution import EvolutionEngine
    from agent.evolve import Evolver
    from agent.lobster import Lobster
    from agent.mirror import Mirror
    from brain.knowledge_state import KnowledgeState
    from brain.reflect import Reflector
    from brain.hypothesize import Hypothesizer
    from brain.curiosity_loop import CuriosityLoop
    from digester.extract import Extractor
    from digester.connect import Connector
    from digester.synthesize import Synthesizer
    from publisher.threads_poster import ThreadsPoster
    from publisher.engagement_tracker import EngagementTracker
    from scheduler.heartbeat import setup_heartbeats

    # ── Core services ──
    db = Database()
    await db.connect()

    llm = LLMRouter()
    llm.inject_db(db)
    await llm.load_active_model_from_db()
    await llm.refresh_local_models()  # discover models from local endpoint

    # ── v2.5 explorers ──
    searcher = TavilySearch()
    rss_reader = RSSReader(db)
    jina_reader = JinaReader()
    x_listener = XListener()
    academic_search = AcademicSearch()
    browser = HeadlessBrowser()
    pdf_reader = PDFReader()

    # ── v2.5 publishers ──
    threads_poster = ThreadsPoster()

    # ── Telegram bot ref ──
    telegram_bot = application.bot_data.get("telegram_bot")

    # ── v2.5 Evolution engine (pre-existing) ──
    evolution = EvolutionEngine(db=db, telegram=telegram_bot)

    # ── v2.5 Lobster agent (posting / engagement — still the social brain) ──
    lobster = Lobster(
        llm=llm,
        db=db,
        threads_poster=threads_poster,
        telegram=telegram_bot,
        searcher=searcher,
        rss_reader=rss_reader,
        jina_reader=jina_reader,
        x_listener=x_listener,
        academic_search=academic_search,
        browser=browser,
        pdf_reader=pdf_reader,
        evolution=evolution,
    )

    # ── v3 Brain modules ──
    ks_path = os.environ.get("KNOWLEDGE_STATE_PATH")
    knowledge = KnowledgeState(db, json_path=ks_path)
    reflector = Reflector(llm, db, knowledge)
    hypothesizer = Hypothesizer(llm, db)
    forager = Forager(llm=llm, db=db)
    extractor = Extractor(llm, db)
    connector = Connector(llm, db)
    synthesizer = Synthesizer(llm, db)

    curiosity_loop = CuriosityLoop(
        llm=llm,
        db=db,
        knowledge=knowledge,
        reflector=reflector,
        hypothesizer=hypothesizer,
        forager=forager,
        extractor=extractor,
        connector=connector,
        synthesizer=synthesizer,
        telegram=telegram_bot,
    )

    evolver = Evolver(llm=llm, db=db, telegram=telegram_bot)
    mirror = Mirror(llm=llm, db=db, telegram=telegram_bot, evolver=evolver)

    # ── Engagement tracker ──
    engagement_tracker = EngagementTracker(
        db=db,
        x_listener=x_listener,
        threads_poster=threads_poster,
    )

    # ── Wire telegram bot with all services ──
    telegram_bot.db = db
    telegram_bot.llm = llm
    telegram_bot.lobster = lobster
    telegram_bot.loop = curiosity_loop
    telegram_bot.evolver = evolver

    # ── Store references ──
    application.bot_data.update({
        "db": db,
        "llm": llm,
        "lobster": lobster,
        "mirror": mirror,
        "curiosity_loop": curiosity_loop,
        "evolver": evolver,
        "forager": forager,
    })

    # ── Scheduler ──
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler(timezone=os.environ.get("TZ", "Asia/Taipei"))
    setup_heartbeats(
        scheduler,
        lobster,
        mirror=mirror,
        evolver=evolver,
        engagement_tracker=engagement_tracker,
        curiosity_loop=curiosity_loop,
    )
    scheduler.start()
    application.bot_data["scheduler"] = scheduler

    await telegram_bot.set_menu()

    logger.info("🦞 Lobster v3.0 initialized — curiosity loop + social brain ready")
    if telegram_bot:
        await telegram_bot.notify("🦞 Lobster v3.0 is online!")


async def post_shutdown(application):
    db = application.bot_data.get("db")
    if db:
        await db.close()

    llm = application.bot_data.get("llm")
    if llm:
        await llm.close()

    forager = application.bot_data.get("forager")
    if forager:
        await forager.close()

    loop = application.bot_data.get("curiosity_loop")
    if loop:
        await loop.stop()

    scheduler = application.bot_data.get("scheduler")
    if scheduler:
        scheduler.shutdown(wait=False)

    logger.info("Lobster v3.0 shut down")


def main():
    from bot.telegram import TelegramBot

    telegram_bot = TelegramBot()
    app = telegram_bot.build_app()
    app.bot_data["telegram_bot"] = telegram_bot

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
