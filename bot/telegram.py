"""Telegram bot for Lobster v3.0.

Handles:
- Automatic notifications (insights, evolution proposals, daily reports)
- v2.5 commands (post, explore, binge, relearn, model, track, rate, stats, pause)
- v3 NEW commands: /status /questions /inject /knowledge /digest /evolve
- URL input → routed to curiosity loop's `inject_url`
- Text input → natural-language chat with the lobster
"""

import os
import re
import json
import logging

from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters,
)

from publisher.formatter import truncate_for_telegram

logger = logging.getLogger("lobster.bot")

# Menu commands shown in Telegram (v3)
MENU_COMMANDS = [
    BotCommand("start",     "Show all commands"),
    BotCommand("health",    "Ping local + remote LLM + DB"),
    # ── 探索控制 (v3)
    BotCommand("status",    "Curiosity loop status"),
    BotCommand("questions", "Show pending open_questions"),
    BotCommand("inject",    "/inject <question> — push a new open_question"),
    BotCommand("knowledge", "/knowledge <topic> — show cluster understanding"),
    BotCommand("digest",    "Show recent digest results"),
    BotCommand("evolve",    "Trigger weekly Evolve now"),
    # ── 內容 (v2.5)
    BotCommand("post",      "Trigger a post now"),
    BotCommand("explore",   "/explore <topic> — quick web search"),
    BotCommand("binge",     "Binge explore N rounds (default 15, max 20)"),
    BotCommand("relearn",   "Re-ingest updated soul/style identity"),
    # ── 數據 / 控制
    BotCommand("stats",     "Monthly statistics & budget"),
    BotCommand("model",     "Show or switch active LLM model"),
    BotCommand("track",     "Track an X account"),
    BotCommand("rate",      "Rate insight/post: /rate <id> <1-5> [comment]"),
    BotCommand("pause",     "Pause curiosity loop + auto-posting"),
    BotCommand("resume",    "Resume curiosity loop + auto-posting"),
]


class TelegramBot:
    def __init__(self, db=None, llm=None, lobster_agent=None, curiosity_loop=None, evolver=None):
        self.token = os.environ["TELEGRAM_BOT_TOKEN"]
        self.owner_id = int(os.environ.get("TELEGRAM_USER_ID") or os.environ["ALLOWED_USER_ID"])
        self.db = db
        self.llm = llm
        self.lobster = lobster_agent
        self.loop = curiosity_loop  # v3 brain.curiosity_loop.CuriosityLoop
        self.evolver = evolver       # v3 agent.evolve.Evolver
        self.app: Application = None
        self._paused = False

    def build_app(self) -> Application:
        self.app = Application.builder().token(self.token).build()

        # v2.5 commands
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("stats", self._cmd_stats))
        self.app.add_handler(CommandHandler("pause", self._cmd_pause))
        self.app.add_handler(CommandHandler("resume", self._cmd_resume))
        self.app.add_handler(CommandHandler("rate", self._cmd_rate))
        self.app.add_handler(CommandHandler("explore", self._cmd_explore))
        self.app.add_handler(CommandHandler("track", self._cmd_track))
        self.app.add_handler(CommandHandler("post", self._cmd_post))
        self.app.add_handler(CommandHandler("relearn", self._cmd_relearn))
        self.app.add_handler(CommandHandler("binge", self._cmd_binge))
        self.app.add_handler(CommandHandler("model", self._cmd_model))

        # v3 NEW commands
        self.app.add_handler(CommandHandler("health",    self._cmd_health))
        self.app.add_handler(CommandHandler("status",    self._cmd_status))
        self.app.add_handler(CommandHandler("questions", self._cmd_questions))
        self.app.add_handler(CommandHandler("inject",    self._cmd_inject))
        self.app.add_handler(CommandHandler("knowledge", self._cmd_knowledge))
        self.app.add_handler(CommandHandler("digest",    self._cmd_digest))
        self.app.add_handler(CommandHandler("evolve",    self._cmd_evolve))

        # URL + natural language
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.User(self.owner_id),
            self._handle_message,
        ))

        return self.app

    async def set_menu(self):
        if self.app and self.app.bot:
            await self.app.bot.set_my_commands(MENU_COMMANDS)
            logger.info("Telegram menu commands set")

    def is_paused(self) -> bool:
        return self._paused

    async def notify(self, text: str):
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
            "🦞 Lobster v3.0 — 你的研究探索龍蝦\n\n"
            "🏥 /health — ping local + remote LLM + DB\n"
            "\n── 🔬 探索控制 ──\n"
            "📊 /status — 龍蝦現在在幹嘛\n"
            "❓ /questions — 目前的 open questions\n"
            "💉 /inject <問題> — 手動塞一個探索問題\n"
            "🧠 /knowledge <topic> — 查 cluster 理解\n"
            "📚 /digest — 最近一次消化結果\n"
            "🧬 /evolve — 立刻觸發進化提案\n"
            "\n── 📝 內容 (v2.5) ──\n"
            "📝 /post — 立刻觸發一次發文\n"
            "🔍 /explore <topic> — 立刻 web 搜尋\n"
            "🍽 /binge [n] — 狂探索 n 輪\n"
            "🧠 /relearn — 重新內化 soul/style\n"
            "\n── ⚙️ 系統 ──\n"
            "📊 /stats — 本月統計 & 預算\n"
            "🤖 /model [name] — 看/切換模型\n"
            "👁 /track <handle> — 追蹤 X 帳號\n"
            "⭐ /rate <id> <1-5> [評語] — 評價\n"
            "⏸ /pause — 暫停\n"
            "▶️ /resume — 恢復\n"
            "\n📎 貼 URL → 立即進入 Forage→Digest\n"
            "💭 打字 → 跟龍蝦聊天"
        )

    # ── v3 NEW commands ──

    async def _cmd_health(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Ping local + remote LLM + DB. Acks immediately, then runs probes in parallel."""
        import asyncio
        import time

        # Immediate ack so the user knows we received the command
        try:
            placeholder = await update.message.reply_text("🏥 Running health check...")
        except Exception as e:
            logger.error(f"/health placeholder reply failed: {e}")
            return

        async def probe_local():
            if not (self.llm and self.llm.local.available):
                return ("LOCAL", None, None, "not_configured", "設 LOCAL_LLM_BASE_URL 才能用")
            try:
                t0 = time.monotonic()
                reply = await asyncio.wait_for(
                    self.llm.chat_local(
                        agent="health",
                        system_prompt="You are a connectivity test responder.",
                        user_message="Reply with exactly one word: pong",
                        max_tokens=10,
                    ),
                    timeout=10.0,
                )
                return ("LOCAL", self.llm.local.model, (time.monotonic() - t0) * 1000, "ok", reply)
            except asyncio.TimeoutError:
                return ("LOCAL", self.llm.local.model, None, "timeout", ">10s")
            except Exception as e:
                return ("LOCAL", self.llm.local.model, None, type(e).__name__, str(e)[:120])

        async def probe_remote():
            if not (self.llm and self.llm.remote):
                return ("REMOTE", None, None, "not_configured", "OPENROUTER_API_KEY 沒設?")
            info = self.llm.get_model_info()
            label = f"{info['name']} ({info['model_id']})"
            try:
                t0 = time.monotonic()
                reply = await asyncio.wait_for(
                    self.llm.chat_remote(
                        agent="health",
                        system_prompt="You are a connectivity test responder.",
                        user_message="Reply with exactly one word: pong",
                        max_tokens=10,
                    ),
                    timeout=10.0,
                )
                return ("REMOTE", label, (time.monotonic() - t0) * 1000, "ok", reply)
            except asyncio.TimeoutError:
                return ("REMOTE", label, None, "timeout", ">10s")
            except Exception as e:
                return ("REMOTE", label, None, type(e).__name__, str(e)[:120])

        async def probe_db():
            if not self.db:
                return ("DB", None, None, "not_connected", None)
            try:
                t0 = time.monotonic()
                weights = await asyncio.wait_for(self.db.get_source_weights(), timeout=5.0)
                dt_ms = (time.monotonic() - t0) * 1000
                extras = {"source_weights": len(weights)}
                try:
                    extras["pending_q"] = await asyncio.wait_for(self.db.count_pending_questions(), timeout=3.0)
                    extras["loops_today"] = await asyncio.wait_for(self.db.get_today_loop_count(), timeout=3.0)
                except Exception as e:
                    extras["v3_tables_error"] = f"{type(e).__name__} — schema_v3.sql 跑了嗎？"
                return ("DB", "Supabase", dt_ms, "ok", extras)
            except asyncio.TimeoutError:
                return ("DB", "Supabase", None, "timeout", ">5s")
            except Exception as e:
                return ("DB", "Supabase", None, type(e).__name__, str(e)[:120])

        async def probe_loop():
            if not (self.loop and self.db):
                return ("LOOP", None, None, "not_initialized", None)
            try:
                running = "running" if self.loop.running else "idle"
                paused = await asyncio.wait_for(self.db.is_loop_paused(), timeout=3.0)
                state = "⏸ paused" if paused else f"🏃 {running}"
                return ("LOOP", "Curiosity loop", None, "ok", state)
            except Exception as e:
                return ("LOOP", "Curiosity loop", None, type(e).__name__, str(e)[:80])

        # Run all four in parallel — total wall time ≈ slowest probe (~10s max)
        try:
            results = await asyncio.wait_for(
                asyncio.gather(probe_local(), probe_remote(), probe_db(), probe_loop()),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            try:
                await placeholder.edit_text("❌ /health timed out (>15s overall)")
            except Exception:
                pass
            return
        except Exception as e:
            logger.exception("/health gather failed")
            try:
                await placeholder.edit_text(f"❌ /health crashed: {type(e).__name__}: {e}")
            except Exception:
                pass
            return

        # Format
        lines = ["🏥 Health check\n"]
        for name, label, dt_ms, status, extra in results:
            if status == "ok":
                if name == "DB":
                    lines.append(f"✅ {name}  {label} ({dt_ms:.0f}ms)")
                    if isinstance(extra, dict):
                        sw = extra.get("source_weights", "?")
                        pq = extra.get("pending_q", "?")
                        lt = extra.get("loops_today", "?")
                        lines.append(f"   weights={sw}  pending_q={pq}  loops_today={lt}")
                        if extra.get("v3_tables_error"):
                            lines.append(f"   ⚠️ {extra['v3_tables_error']}")
                elif name == "LOOP":
                    lines.append(f"✅ {name}  {extra}")
                else:
                    got_pong = "pong" in (str(extra) or "").lower()
                    mark = "✅" if got_pong else "⚠️"
                    snippet = (str(extra) or "").strip()[:50]
                    lines.append(f"{mark} {name}  {label}")
                    lines.append(f"   {dt_ms:.0f}ms  reply: {snippet!r}")
                    if not got_pong:
                        lines.append("   (連上但沒回 pong — endpoint OK，prompt-following 弱)")
            elif status == "not_configured":
                lines.append(f"⚠️ {name}  not configured")
                if extra:
                    lines.append(f"   {extra}")
            elif status in ("not_connected", "not_initialized"):
                lines.append(f"❌ {name}  {status.replace('_', ' ')}")
            elif status == "timeout":
                lines.append(f"❌ {name}  {label or ''}  timeout {extra or ''}")
            else:  # exception class name
                lines.append(f"❌ {name}  {label or ''}")
                lines.append(f"   {status}: {extra}")
            lines.append("")  # spacer

        text = "\n".join(lines).rstrip()
        try:
            await placeholder.edit_text(text)
        except Exception as e:
            logger.error(f"/health edit failed: {e}")
            try:
                await update.message.reply_text(text)
            except Exception:
                pass

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.db:
            await update.message.reply_text("DB not connected")
            return
        pending = await self.db.count_pending_questions()
        today_loops = await self.db.get_today_loop_count()
        paused = await self.db.is_loop_paused()
        loop_running = self.loop.running if self.loop else False
        cost = self.llm.get_cost_breakdown() if self.llm else {"_total": {"tokens": 0, "cost_usd": 0}}
        total = cost.get("_total", {})
        local = cost.get("_local", {"tokens": 0})

        msg = (
            f"🦞 Curiosity Loop\n\n"
            f"狀態: {'⏸ paused' if paused else ('🏃 running' if loop_running else '😴 idle')}\n"
            f"今日 loops: {today_loops} / max\n"
            f"Pending questions: {pending}\n"
            f"\n💰 Tokens (since last reset)\n"
            f"  Remote: {total.get('tokens', 0)} (${total.get('cost_usd', 0)})\n"
            f"  Local:  {local.get('tokens', 0)} (free)\n"
        )
        await update.message.reply_text(msg)

    async def _cmd_questions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.db:
            await update.message.reply_text("DB not connected")
            return
        rows = await self.db.get_pending_questions(limit=10)
        if not rows:
            await update.message.reply_text("沒有 pending 問題。/inject <q> 來丟一個。")
            return
        lines = ["❓ Pending open_questions\n"]
        for r in rows:
            lines.append(
                f"#{r['id']} [p={r.get('priority', 0):.2f}] {r['question']}"
            )
            if r.get("soul_anchor"):
                lines.append(f"  ⚓ {r['soul_anchor']}")
        await update.message.reply_text("\n".join(lines))

    async def _cmd_inject(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /inject <question>")
            return
        question = " ".join(context.args)
        if not self.loop:
            await update.message.reply_text("❌ curiosity loop not initialized")
            return
        qid = await self.loop.inject_question(question, priority=0.95)
        await update.message.reply_text(f"💉 Injected question #{qid}\n龍蝦會在背景去找答案。")

    async def _cmd_knowledge(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            # Show all clusters
            summary = await self.db.get_clusters_summary()
            await update.message.reply_text(f"🧠 All clusters:\n\n{summary}")
            return
        topic = "_".join(context.args).lower()
        cluster = await self.db.get_cluster(topic)
        if not cluster:
            # Try fuzzy: list any cluster id containing the keyword
            all_c = await self.db.list_clusters(limit=50)
            matches = [c for c in all_c if topic in c["id"].lower()]
            if not matches:
                await update.message.reply_text(f"沒有找到 cluster: {topic}")
                return
            cluster = matches[0]
        body = (
            f"🧠 {cluster['id']} (conf={cluster.get('confidence', 0):.2f})\n\n"
            f"{cluster.get('current_understanding', '')}\n\n"
        )
        gaps = cluster.get("open_gaps") or []
        if gaps:
            body += "Open gaps:\n" + "\n".join(f"  • {g}" for g in gaps)
        await update.message.reply_text(body)

    async def _cmd_digest(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = await self.db.get_recent_digest_summary(days=2)
        await update.message.reply_text(f"📚 Recent digest (2d):\n\n{text}")

    async def _cmd_evolve(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.evolver:
            await update.message.reply_text("❌ evolver not initialized")
            return
        await update.message.reply_text("🧬 Running Evolve...")
        try:
            result = await self.evolver.run_weekly()
            await update.message.reply_text(
                f"✅ Evolve done. status={result.get('status')}\n"
                f"sq={len(result.get('source_quality') or [])} "
                f"frontiers={len(result.get('new_frontiers') or [])} "
                f"deprecations={len(result.get('deprecations') or [])}"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Evolve failed: {e}")

    # ── v2.5 commands (kept) ──

    async def _cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.db:
            await update.message.reply_text("DB not connected")
            return
        from utils.token_tracker import TokenTracker
        tracker = TokenTracker(self.db)
        budget = await tracker.get_budget_status()
        posts_7d = await self.db.get_recent_posts(days=7)
        posts_today = await self.db.get_today_post_count()
        loop_stats_7d = await self.db.get_recent_loop_stats(days=7)

        msg = (
            f"📊 Lobster Stats\n\n"
            f"Token: ${budget['spent_usd']}/{budget['budget_usd']} ({budget['pct']}%)\n"
            f"{'⚠️ WARNING' if budget['warning'] else '✅ OK'}\n\n"
            f"Posts today: {posts_today}\n"
            f"Posts 7d: {len(posts_7d)}\n\n"
            f"🦞 Curiosity 7d:\n"
            f"  Loops: {loop_stats_7d.get('total_loops', 0)} ({loop_stats_7d.get('avg_loops_per_day', 0)}/day)\n"
            f"  Empty loops: {loop_stats_7d.get('empty_loops', 0)}\n"
            f"  Extracts: {loop_stats_7d.get('extracts_produced', 0)}\n"
            f"  Insights: {loop_stats_7d.get('insights_generated', 0)}\n"
            f"  Local tokens: {loop_stats_7d.get('local_tokens_used', 0)}\n"
            f"  Remote tokens: {loop_stats_7d.get('remote_tokens_used', 0)}\n\n"
            f"Status: {'⏸ PAUSED' if self._paused else '▶️ ACTIVE'}"
        )
        await update.message.reply_text(msg)

    async def _cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._paused = True
        if self.db:
            await self.db.set_loop_paused(True)
        if self.loop:
            await self.loop.stop()
        await update.message.reply_text("⏸ Paused (auto-post + curiosity loop)")

    async def _cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._paused = False
        if self.db:
            await self.db.set_loop_paused(False)
        await update.message.reply_text("▶️ Resumed. /inject 任何問題或等下次 seed。")

    async def _cmd_rate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args
        if not args or len(args) < 2:
            await update.message.reply_text("Usage: /rate <id> <1-5> [comment]")
            return
        target_id = args[0]
        try:
            rating = int(args[1])
            assert 1 <= rating <= 5
        except (ValueError, AssertionError):
            await update.message.reply_text("Rating must be 1-5")
            return
        comment = " ".join(args[2:]) if len(args) > 2 else None
        # Try insight first (id starts with ins_), else post
        try:
            if target_id.startswith("ins_"):
                await self.db.rate_insight(target_id, rating, comment)
                await update.message.reply_text(f"✅ Rated insight {target_id} as {rating}/5")
            else:
                await self.db._update("posts", {"id": target_id}, {
                    "owner_rating": rating,
                    "owner_feedback": comment,
                })
                await update.message.reply_text(f"✅ Rated post {target_id[:8]}... as {rating}/5")
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {e}")

    async def _cmd_explore(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        topic = " ".join(context.args) if context.args else None
        if not topic:
            await update.message.reply_text("Usage: /explore <topic>")
            return
        # In v3, /explore = inject as a high-priority question
        if self.loop:
            qid = await self.loop.inject_question(topic, priority=0.95)
            await update.message.reply_text(
                f"🔍 Pushed as question #{qid}. 龍蝦背景跑 forage → digest，有結果會通知你。"
            )
            return
        await update.message.reply_text("❌ curiosity loop not initialized")

    async def _cmd_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.lobster:
            await update.message.reply_text("❌ Lobster agent not initialized")
            return

        # If a URL is passed as an arg, route through inject_url first.
        # /post <url> means "digest this URL into the v3 pipeline so I can post about it later".
        if context.args:
            url_arg = next((a for a in context.args if a.startswith("http")), None)
            if url_arg:
                if not self.loop:
                    await update.message.reply_text("❌ curiosity loop not initialized")
                    return
                await update.message.reply_text(
                    f"🔗 /post 帶了 URL — 我先 digest 這篇而不是抓 top discovery\n{url_arg[:80]}"
                )
                try:
                    result = await self.loop.inject_url(url_arg)
                    if result.get("status") == "ok":
                        conn = result.get("connection") or {}
                        n_ins = len(result.get("insights") or [])
                        await update.message.reply_text(
                            f"✅ Digested.\n"
                            f"connection_type: {conn.get('connection_type')}\n"
                            f"insight: {(conn.get('insight') or '')[:300]}\n"
                            f"產出 insights: {n_ins}\n\n"
                            f"再打 /post（不帶參數）可以從消化結果挑一個發 X/Threads。"
                        )
                    else:
                        await update.message.reply_text(f"❌ {result.get('reason', 'digest failed')}")
                except Exception as e:
                    logger.exception("/post URL digest failed")
                    await update.message.reply_text(f"❌ digest error: {type(e).__name__}: {e}")
                return

        # Default v2.5 behavior — pick top discovery and run publish pipeline
        await update.message.reply_text("🦞 Triggering post creation...")
        try:
            await self.lobster.create_post()
        except Exception as e:
            logger.error(f"Manual post failed: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Post creation failed: {e}")

    async def _cmd_model(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.llm:
            await update.message.reply_text("❌ LLM not initialized")
            return
        if not context.args:
            info = self.llm.get_model_info()
            lines = [f"🤖 Current: {info['name']} ({info['model_id']})\n", "Available:"]
            for m in self.llm.list_models():
                marker = "▶" if m["name"] == info["name"] else " "
                lines.append(f"{marker} {m['name']} — {m['model_id']}")
            lines.append("\nUsage: /model <name>")
            await update.message.reply_text("\n".join(lines))
            return
        name = context.args[0].lower()
        if self.llm.set_active_model(name):
            await self.llm.remote.save_active_model_to_db() if self.llm.remote else None
            info = self.llm.get_model_info()
            await update.message.reply_text(f"✅ Switched to: {info['name']} ({info['model_id']})")
        else:
            await update.message.reply_text(f"❌ Unknown model: {name}")

    async def _cmd_binge(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.lobster:
            await update.message.reply_text("❌ Lobster agent not initialized")
            return
        rounds = 15
        if context.args:
            try:
                rounds = max(1, min(20, int(context.args[0])))
            except ValueError:
                await update.message.reply_text("Usage: /binge [rounds] (1-20, default 15)")
                return
        await update.message.reply_text(f"🍽 Binge exploring: {rounds} rounds")

        import asyncio

        async def run_binge():
            try:
                result = await self.lobster.binge_explore(rounds)
                await self.notify(
                    f"✅ Binge done!\n完成: {result['completed']}/{result['rounds']} 輪"
                )
            except Exception as e:
                await self.notify(f"❌ Binge failed: {e}")

        asyncio.create_task(run_binge())

    async def _cmd_relearn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.lobster:
            await update.message.reply_text("❌ Lobster agent not initialized")
            return
        await update.message.reply_text("🧠 Syncing identity...")
        try:
            result = await self.lobster.sync_identity()
            if result.get("ok"):
                insights = result.get("insights", [])
                msg = "✅ Identity synced!\n\nInsights:\n"
                msg += "\n".join(f"• {i}" for i in insights) if insights else "（無新洞察）"
                await update.message.reply_text(msg)
            else:
                await update.message.reply_text(f"❌ Sync failed: {result.get('error', 'unknown')}")
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {e}")

    async def _cmd_track(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /track <handle>")
            return
        handle = context.args[0].lstrip("@")
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else None
        await self.db.add_tracked_handle(handle, reason)
        await update.message.reply_text(f"✅ Now tracking @{handle}")

    # ── Message handling ──

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip()

        # URL detection → route to curiosity loop's inject_url
        url_match = re.search(r'https?://\S+', text)
        if url_match:
            url = url_match.group(0)
            await update.message.reply_text(f"🔗 Processing: {url[:60]}...")
            if not self.loop:
                await update.message.reply_text("❌ curiosity loop not initialized")
                return
            try:
                result = await self.loop.inject_url(url)
                if result.get("status") == "ok":
                    n_ins = len(result.get("insights") or [])
                    conn = result.get("connection") or {}
                    await update.message.reply_text(
                        f"✅ Digested.\n"
                        f"connection_type: {conn.get('connection_type')}\n"
                        f"insight: {(conn.get('insight') or '')[:300]}\n"
                        f"產出 insights: {n_ins}"
                    )
                else:
                    await update.message.reply_text(f"❌ {result.get('reason', 'failed')}")
            except Exception as e:
                logger.error(f"URL inject failed: {e}", exc_info=True)
                await update.message.reply_text(f"❌ URL inject error: {e}")
            return

        # Natural language chat — with conversation memory + reply context + anti-hallucination
        if self.llm and self.lobster:
            try:
                from utils.identity_loader import load_identity
                identity = await load_identity(self.db)

                # Pull per-user sliding-window history (last 6 turns = 12 messages)
                history = context.user_data.setdefault("chat_history", [])

                # If user is replying to a specific bot message in Telegram,
                # inject that message as load-bearing context. This is the
                # main fix for "回覆會不知道我在回哪一則訊息".
                replied_to_block = ""
                rtm = update.message.reply_to_message
                if rtm and rtm.text:
                    replied_to_block = (
                        "\n\n[使用者用 Telegram 的「回覆」功能引了你之前發的這則訊息，"
                        "他現在的話是針對這則的回應/延伸：]\n"
                        f"{rtm.text[:1500]}\n"
                        "[/引用結束]\n"
                    )

                system = (
                    f"{identity}\n\n"
                    "你現在在跟你的主人 Salmon 用 Telegram 聊天。\n"
                    "用繁體中文回覆，語氣自然口語，保持你的個性風格。\n"
                    "回覆要完整，不要在句子中間停。但也不要硬撐長度——夠了就停。\n"
                    "\n"
                    "幾條硬規則（很重要）：\n"
                    "1. 你在 chat 模式下沒有網路、沒有搜尋工具、沒有 PubMed/arXiv access。\n"
                    "   絕對不要編造 URL、paper title、作者名字、PMID、arXiv ID。\n"
                    "   如果 Salmon 問你某篇 paper 的連結，誠實說：『我 chat 模式下沒有網路，\n"
                    "   你要我用 /inject <關鍵字> 去 arXiv/PubMed 真的找一下嗎？』\n"
                    "2. 仔細看上文。Salmon 說「這個」「那個」「剛剛那篇」時，去歷史紀錄裡\n"
                    "   找他真正在指什麼。看不出來就主動問清楚，不要瞎猜然後繞回 soul.md。\n"
                    "3. 如果 [使用者用 Telegram 的「回覆」功能引了你之前發的這則訊息] 標記出現，\n"
                    "   那就是 Salmon 真正在回應的對象，把那則內容當成首要 context。\n"
                    "4. 你之前發給 Salmon 的 insight 通知是真實的（從 digester 出來的）。\n"
                    "   如果他在問某則 insight 的細節，你可以承認你只記得那則的 title/body，\n"
                    "   不記得 source URL；要他用 /digest 看完整版。\n"
                    f"{replied_to_block}"
                )

                # Flatten history into a single user message with role labels
                history_text_parts = []
                for h in history[-12:]:
                    role_label = "Salmon" if h["role"] == "user" else "你（Lobster）"
                    history_text_parts.append(f"{role_label}: {h['content']}")
                history_block = "\n\n".join(history_text_parts)

                if history_block:
                    user_msg = (
                        "以下是你跟 Salmon 最近的對話（最舊在上）：\n\n"
                        f"{history_block}\n\n"
                        f"Salmon 現在說：{text}\n\n"
                        "你的回覆："
                    )
                else:
                    user_msg = f"Salmon 說：{text}\n\n你的回覆："

                reply = await self.llm.chat(
                    agent="lobster_chat",
                    system_prompt=system,
                    user_message=user_msg,
                    max_tokens=1500,
                )
                reply = (reply or "").strip()
                if not reply:
                    reply = "（空白回覆 — model 可能 timeout 或 max_tokens 撐不住，再講一次？）"

                # Telegram 4096 char hard limit — let the formatter handle it
                await update.message.reply_text(truncate_for_telegram(reply))

                # Persist exchange (cap at last 12 messages)
                history.append({"role": "user", "content": text})
                history.append({"role": "assistant", "content": reply})
                if len(history) > 12:
                    del history[: len(history) - 12]

            except Exception as e:
                logger.exception("Chat reply failed")
                await update.message.reply_text(
                    f"❌ Chat error: {type(e).__name__}: {str(e)[:200]}"
                )
        elif self.db:
            await self.db.insert_discovery(
                source_type="thought",
                title=text[:80],
                summary=text,
                content_type="thought",
                interest_score=5,
            )
            await update.message.reply_text("💭 Stored as thought.")
