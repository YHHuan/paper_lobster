"""Telegram bot for Lobster v2.5.

Handles:
- Automatic notifications (posts, engagement, daily/weekly reports)
- Manual commands (/rate, /pause, /resume, /stats, /explore, /track, etc.)
- URL/text input processing
"""

import os
import re
import json
import logging
from datetime import datetime

from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

from publisher.formatter import truncate_for_telegram

logger = logging.getLogger("lobster.bot")

# Menu commands shown in Telegram
MENU_COMMANDS = [
    BotCommand("start", "Show all commands"),
    BotCommand("stats", "Monthly statistics & budget"),
    BotCommand("explore", "Search a topic now"),
    BotCommand("track", "Track an X account"),
    BotCommand("pause", "Pause auto-posting"),
    BotCommand("resume", "Resume auto-posting"),
    BotCommand("rate", "Rate a post (1-5)"),
    BotCommand("post", "Trigger a post now"),
    BotCommand("enable_proactive", "Enable proactive engagement"),
]


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
        self.app.add_handler(CommandHandler("post", self._cmd_post))
        self.app.add_handler(CommandHandler("enable_proactive", self._cmd_enable_proactive))

        # URL and text messages
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.User(self.owner_id),
            self._handle_message,
        ))

        return self.app

    async def set_menu(self):
        """Register bot commands in Telegram menu."""
        if self.app and self.app.bot:
            await self.app.bot.set_my_commands(MENU_COMMANDS)
            logger.info("Telegram menu commands set")

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
            "🦞 Lobster v2.5\n\n"
            "📊 /stats — 本月統計 & 預算\n"
            "🔍 /explore <topic> — 立刻搜尋\n"
            "📝 /post — 立刻觸發一次發文\n"
            "👁 /track <handle> — 追蹤 X 帳號\n"
            "⭐ /rate <id> <1-5> <評語> — 評價推文\n"
            "⏸ /pause — 暫停自動發布\n"
            "▶️ /resume — 恢復\n"
            "🗑 /delete <id> — 刪除推文\n"
            "💬 /enable_proactive — 開啟主動互動\n"
            "\n📎 貼 URL → 立即處理\n"
            "💭 打字 → 存為 thought 素材"
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
            f"Token: ${budget['spent_usd']}/{budget['budget_usd']} "
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
        await update.message.reply_text("🚧 Delete not yet implemented")

    async def _cmd_explore(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        topic = " ".join(context.args) if context.args else None
        if not topic:
            await update.message.reply_text("Usage: /explore <topic>")
            return

        await update.message.reply_text(f"🔍 Exploring: {topic}...")

        if not self.lobster or not self.lobster.searcher:
            await update.message.reply_text("❌ Searcher not initialized")
            return

        if not self.lobster.searcher.api_key:
            await update.message.reply_text("❌ TAVILY_API_KEY not set in environment")
            return

        try:
            results = await self.lobster.searcher.search(topic, max_results=5)

            # Also search academic sources
            academic_results = []
            if self.lobster.academic_search:
                try:
                    academic_results = await self.lobster.academic_search.search_all(topic, max_results=2)
                except Exception as e:
                    logger.warning(f"Academic search in /explore failed: {e}")

            all_results = results + academic_results
            if not all_results:
                await update.message.reply_text(
                    f"No results found.\n"
                    f"API key: {self.lobster.searcher.api_key[:12]}...\n"
                    f"Try a different query?"
                )
                return

            # Show results
            msg_parts = [f"🔍 Found {len(results)} web + {len(academic_results)} academic results for '{topic}':\n"]
            for i, r in enumerate(all_results[:8], 1):
                title = r.get("title", "No title")[:70]
                url = r.get("url", "")
                source = r.get("source", "web")
                snippet = r.get("content", "")[:120]
                msg_parts.append(f"{i}. [{source}] {title}\n   {url}\n   {snippet}...\n")

            await update.message.reply_text("\n".join(msg_parts))

            # Also store high-quality results as discoveries
            if self.db:
                stored = 0
                for r in all_results:
                    if r.get("score", 0) > 0.5:
                        await self.db.insert_discovery(
                            source_type="manual_search",
                            title=r.get("title", ""),
                            summary=r.get("content", "")[:500],
                            url=r.get("url"),
                            content_type="article",
                            interest_score=6,
                            interest_reason=f"Manual search: {topic}",
                        )
                        stored += 1
                if stored:
                    await update.message.reply_text(f"💾 Stored {stored} results as discoveries.")

        except Exception as e:
            logger.error(f"Explore failed: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Search failed: {e}")

    async def _cmd_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Manually trigger a post creation cycle."""
        if not self.lobster:
            await update.message.reply_text("❌ Lobster agent not initialized")
            return

        await update.message.reply_text("🦞 Triggering post creation...")
        try:
            await self.lobster.create_post()
        except Exception as e:
            logger.error(f"Manual post failed: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Post creation failed: {e}")

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
        url_match = re.search(r'https?://\S+', text)
        if url_match:
            url = url_match.group(0)
            await update.message.reply_text(f"🔗 Processing: {url[:60]}...")

            # Read the URL and store as discovery
            if self.lobster and self.lobster.jina_reader:
                try:
                    content = await self.lobster.jina_reader.read(url)
                    if content and self.db:
                        title = content.split("\n")[0][:80] if content else url[:80]
                        doc_id = await self.db.insert_discovery(
                            source_type="manual_url",
                            title=title,
                            summary=content[:500],
                            url=url,
                            raw_content=content[:5000],
                            content_type="article",
                            interest_score=7,
                            interest_reason="Manually submitted by owner",
                        )
                        await update.message.reply_text(
                            f"✅ Stored as discovery.\n"
                            f"Title: {title}\n"
                            f"Content: {len(content)} chars\n\n"
                            f"Use /post to create a post from top discoveries."
                        )
                    elif content:
                        await update.message.reply_text(f"📄 Read {len(content)} chars but DB not connected.")
                    else:
                        await update.message.reply_text("❌ Could not read URL content.")
                except Exception as e:
                    await update.message.reply_text(f"❌ Failed to process URL: {e}")
            else:
                await update.message.reply_text("❌ Reader not initialized")
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
