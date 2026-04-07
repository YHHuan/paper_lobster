"""Telegram bot for Lobster v2.5.

Handles:
- Automatic notifications (posts, engagement, daily/weekly reports)
- Manual commands (/rate, /pause, /resume, /stats, /explore, /track, etc.)
- URL/text input processing
"""

import os
import json
import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

from publisher.formatter import truncate_for_telegram

logger = logging.getLogger("lobster.bot")


class TelegramBot:
    def __init__(self, db=None, llm=None, lobster_agent=None):
        self.token = os.environ["TELEGRAM_BOT_TOKEN"]
        self.owner_id = int(os.environ.get("TELEGRAM_USER_ID") or os.environ["ALLOWED_USER_ID"])
        self.db = db
        self.llm = llm
        self.lobster = lobster_agent
        self.app: Application = None
        self._paused = False

    def build_app(self) -> Application:
        """Build the telegram application with all handlers."""
        self.app = Application.builder().token(self.token).build()

        # Commands
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("stats", self._cmd_stats))
        self.app.add_handler(CommandHandler("pause", self._cmd_pause))
        self.app.add_handler(CommandHandler("resume", self._cmd_resume))
        self.app.add_handler(CommandHandler("rate", self._cmd_rate))
        self.app.add_handler(CommandHandler("delete", self._cmd_delete))
        self.app.add_handler(CommandHandler("explore", self._cmd_explore))
        self.app.add_handler(CommandHandler("track", self._cmd_track))
        self.app.add_handler(CommandHandler("enable_proactive", self._cmd_enable_proactive))

        # URL and text messages
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.User(self.owner_id),
            self._handle_message,
        ))

        return self.app

    def is_paused(self) -> bool:
        return self._paused

    async def notify(self, text: str):
        """Send a notification to the owner."""
        if not self.app or not self.app.bot:
            logger.warning("Bot not initialized, can't send notification")
            return
        text = truncate_for_telegram(text)
        try:
            await self.app.bot.send_message(chat_id=self.owner_id, text=text)
        except Exception as e:
            logger.error(f"Telegram notify failed: {e}")

    # ── Commands ──

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🦞 Lobster v2.5 is alive.\n\n"
            "Commands:\n"
            "/stats — Monthly statistics\n"
            "/pause — Pause auto-posting\n"
            "/resume — Resume auto-posting\n"
            "/rate <post_id> <1-5> <comment> — Rate a post\n"
            "/explore <topic> — Search a topic now\n"
            "/track <handle> — Track an X account\n"
            "\nSend a URL to process immediately.\n"
            "Send text to store as a thought."
        )

    async def _cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.db:
            await update.message.reply_text("DB not connected")
            return

        from utils.token_tracker import TokenTracker
        tracker = TokenTracker(self.db)
        budget = await tracker.get_budget_status()

        posts_7d = await self.db.get_recent_posts(days=7)
        posts_today = await self.db.get_today_post_count()

        msg = (
            f"📊 Lobster Stats\n\n"
            f"Token budget: ${budget['spent_usd']}/{budget['budget_usd']} "
            f"({budget['pct']}%)\n"
            f"{'⚠️ WARNING' if budget['warning'] else '✅ OK'}\n\n"
            f"Today: {posts_today} posts\n"
            f"This week: {len(posts_7d)} posts\n"
            f"Status: {'⏸ PAUSED' if self._paused else '▶️ ACTIVE'}"
        )
        await update.message.reply_text(msg)

    async def _cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._paused = True
        await update.message.reply_text("⏸ Auto-posting paused.")

    async def _cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._paused = False
        await update.message.reply_text("▶️ Auto-posting resumed.")

    async def _cmd_rate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args
        if not args or len(args) < 2:
            await update.message.reply_text("Usage: /rate <post_id> <1-5> [comment]")
            return

        post_id = args[0]
        try:
            rating = int(args[1])
            assert 1 <= rating <= 5
        except (ValueError, AssertionError):
            await update.message.reply_text("Rating must be 1-5")
            return

        comment = " ".join(args[2:]) if len(args) > 2 else ""

        try:
            await self.db._update("posts", {"id": post_id}, {
                "owner_rating": rating,
                "owner_feedback": comment,
            })
            await update.message.reply_text(f"✅ Rated post {post_id[:8]}... as {rating}/5")
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {e}")

    async def _cmd_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # TODO: Delete from X/Threads via API
        await update.message.reply_text("🚧 Delete not yet implemented")

    async def _cmd_explore(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        topic = " ".join(context.args) if context.args else None
        if not topic:
            await update.message.reply_text("Usage: /explore <topic>")
            return
        await update.message.reply_text(f"🔍 Exploring: {topic}...")
        # TODO: Trigger immediate exploration
        if self.lobster and self.lobster.searcher:
            results = await self.lobster.searcher.search(topic, max_results=5)
            if results:
                msg = "\n\n".join(
                    f"• {r['title'][:60]}\n  {r['url']}"
                    for r in results[:5]
                )
                await update.message.reply_text(f"Found:\n\n{msg}")
            else:
                await update.message.reply_text("No results found.")

    async def _cmd_track(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /track <handle>")
            return
        handle = context.args[0].lstrip("@")
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else None
        await self.db.add_tracked_handle(handle, reason)
        await update.message.reply_text(f"✅ Now tracking @{handle}")

    async def _cmd_enable_proactive(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        os.environ["PROACTIVE_ENGAGEMENT_ENABLED"] = "true"
        await update.message.reply_text(
            "✅ Proactive engagement enabled (X only).\n"
            "The lobster will now reply to tracked accounts' posts."
        )

    # ── Message handling ──

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip()

        # URL detection
        import re
        url_match = re.search(r'https?://\S+', text)
        if url_match:
            url = url_match.group(0)
            await update.message.reply_text(f"🔗 Processing URL: {url[:60]}...")
            # TODO: Ingest URL → discovery → optional post
            return

        # Store as thought
        if self.db:
            await self.db.insert_discovery(
                source_type="thought",
                title=text[:80],
                summary=text,
                content_type="thought",
                interest_score=5,
            )
            await update.message.reply_text("💭 Stored as thought.")
