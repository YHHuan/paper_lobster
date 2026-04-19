"""Telegram bot for Lobster v3.0.

Handles:
- Automatic notifications (insights, evolution proposals, daily reports)
- v2.5 commands (post, explore, binge, relearn, model, track, rate, stats, pause)
- v3 NEW commands: /status /questions /inject /knowledge /digest /evolve
- URL input → routed to curiosity loop's `inject_url`
- Text input → natural-language chat with the lobster

Reply context: ALL user messages (commands and free text) pass through
_enrich_reply_context() which extracts the replied-to message and resolves
entity references (#id, ins_xxx) from the DB.  The enriched context is stored
in `context.chat_data["reply_ctx"]` so every handler can use it.
"""

import os
import re
import json
import logging
from datetime import datetime

from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters,
)

from lobster.publisher.formatter import truncate_for_telegram

logger = logging.getLogger("lobster.bot")

# Menu commands shown in Telegram. Grouped by purpose; order = display order.
MENU_COMMANDS = [
    BotCommand("start",     "Show all commands"),

    # ── Curiosity loop (v3) ──
    BotCommand("status",    "Loop status + token usage"),
    BotCommand("questions", "List pending open_questions"),
    BotCommand("inject",    "/inject <q> — push a new open_question"),
    BotCommand("knowledge", "/knowledge <topic> — cluster understanding"),
    BotCommand("pause",     "Pause loop + auto-posting"),
    BotCommand("resume",    "Resume loop + auto-posting"),

    # ── v4 multi-source feeds + morning digest ──
    BotCommand("feedcrawl", "Run v4 multi-source crawl now"),
    BotCommand("feeddigest","/feeddigest [hours] — send digest now (default 12h)"),
    BotCommand("digest",    "Show stored digest summary (last 2d)"),

    # ── Content publishing (v2.5) ──
    BotCommand("post",      "Trigger one post now"),
    BotCommand("explore",   "/explore <topic> — quick web search"),
    BotCommand("binge",     "Binge explore N rounds (default 15, max 20)"),
    BotCommand("relearn",   "Re-ingest soul/style identity"),

    # ── Evolution (weekly + v5 prompt overrides) ──
    BotCommand("evolve",    "Trigger weekly Evolve now"),
    BotCommand("prompt_override",   "/prompt_override [activate] — diff writer/editor/critic/hook"),
    BotCommand("overrides",         "List active + dry_run prompt overrides"),
    BotCommand("activate_override", "/activate_override <id> — promote dry_run → active"),
    BotCommand("rollback_override", "/rollback_override <id> [reason]"),
    BotCommand("override",          "/override <post_id> — revive a killed draft"),
    BotCommand("killed",            "List recent Critic-killed drafts"),

    # ── System ──
    BotCommand("stats",     "Monthly stats + budget"),
    BotCommand("model",     "Show / switch active LLM"),
    BotCommand("track",     "/track <handle> — track X account"),
    BotCommand("rate",      "/rate <id> <1-5> [comment]"),
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

    # Owner-only gate ────────────────────────────────────────────────
    # Every CommandHandler is wrapped so only the configured owner can
    # invoke it. Without this, anyone who finds the bot can trigger
    # /post, /evolve, /prompt_override, etc.

    def _owner_filter(self):
        return filters.User(self.owner_id)

    def _register_cmd(self, name: str, callback):
        self.app.add_handler(CommandHandler(name, callback, filters=self._owner_filter()))

    async def _reject_unauthorized(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Catch-all for any command from a non-owner — log only, no reply."""
        user = update.effective_user
        logger.warning(
            "unauthorized command from user_id=%s username=%s text=%r",
            getattr(user, "id", None),
            getattr(user, "username", None),
            (update.message.text[:80] if update.message and update.message.text else None),
        )

    def build_app(self) -> Application:
        self.app = Application.builder().token(self.token).build()

        # v2.5 commands
        self._register_cmd("start",     self._cmd_start)
        self._register_cmd("stats",     self._cmd_stats)
        self._register_cmd("pause",     self._cmd_pause)
        self._register_cmd("resume",    self._cmd_resume)
        self._register_cmd("rate",      self._cmd_rate)
        self._register_cmd("explore",   self._cmd_explore)
        self._register_cmd("track",     self._cmd_track)
        self._register_cmd("post",      self._cmd_post)
        self._register_cmd("relearn",   self._cmd_relearn)
        self._register_cmd("binge",     self._cmd_binge)
        self._register_cmd("model",     self._cmd_model)
        self._register_cmd("testemail", self._cmd_testemail)

        # v3 NEW commands
        self._register_cmd("status",     self._cmd_status)
        self._register_cmd("questions",  self._cmd_questions)
        self._register_cmd("inject",     self._cmd_inject)
        self._register_cmd("knowledge",  self._cmd_knowledge)
        self._register_cmd("digest",     self._cmd_digest)
        self._register_cmd("feedcrawl",  self._cmd_feedcrawl)
        self._register_cmd("feeddigest", self._cmd_feeddigest)
        self._register_cmd("evolve",     self._cmd_evolve)

        # Evolution v5 commands (P1 + P4)
        self._register_cmd("prompt_override",    self._cmd_prompt_override)
        self._register_cmd("overrides",          self._cmd_overrides)
        self._register_cmd("activate_override",  self._cmd_activate_override)
        self._register_cmd("rollback_override",  self._cmd_rollback_override)
        self._register_cmd("override",           self._cmd_override)
        self._register_cmd("killed",             self._cmd_killed)

        # URL + natural language (already owner-gated)
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.User(self.owner_id),
            self._handle_message,
        ))

        # Catch-all: any command from a non-owner just gets logged and dropped.
        self.app.add_handler(MessageHandler(
            filters.COMMAND & ~filters.User(self.owner_id),
            self._reject_unauthorized,
        ))

        return self.app

    # ── Universal reply context ──

    async def _enrich_reply_context(self, update: Update) -> dict:
        """Extract replied-to message and resolve entity references from DB.

        Returns a dict with:
          raw_text:  the full text of the replied-to message (empty str if none)
          entities:  list of resolved dicts, e.g.:
                     {"type": "question", "id": 60, "detail": "..."}
                     {"type": "insight",  "id": "ins_xxx", "detail": "..."}
                     {"type": "extract",  "id": "ext_xxx", "url": "...", "title": "..."}
        """
        reply = update.message.reply_to_message
        if not reply or not reply.text:
            return {"raw_text": "", "entities": []}

        raw = reply.text
        entities = []

        # Resolve #<number> → open_question
        for m in re.finditer(r'#(\d+)', raw):
            qid = int(m.group(1))
            if self.db:
                try:
                    rows = await self.db._select("open_questions", {
                        "select": "id,question,soul_anchor,priority",
                        "id": f"eq.{qid}",
                        "limit": "1",
                    })
                    if rows:
                        q = rows[0]
                        entities.append({
                            "type": "question",
                            "id": qid,
                            "detail": q.get("question", ""),
                            "soul_anchor": q.get("soul_anchor"),
                        })
                except Exception:
                    pass

        # Resolve ins_xxx → insight
        for m in re.finditer(r'(ins_\w+)', raw):
            iid = m.group(1)
            if self.db:
                try:
                    rows = await self.db._select("insights", {
                        "select": "id,title,body,source_extracts",
                        "id": f"eq.{iid}",
                        "limit": "1",
                    })
                    if rows:
                        ins = rows[0]
                        entities.append({
                            "type": "insight",
                            "id": iid,
                            "detail": f"{ins.get('title', '')}: {ins.get('body', '')[:300]}",
                            "source_extracts": ins.get("source_extracts") or [],
                        })
                except Exception:
                    pass

        # Resolve ext_xxx → extract (with URL)
        for m in re.finditer(r'(ext_\w+)', raw):
            eid = m.group(1)
            if self.db:
                try:
                    ext = await self.db.get_extract(eid)
                    if ext:
                        entities.append({
                            "type": "extract",
                            "id": eid,
                            "title": ext.get("title", ""),
                            "url": ext.get("url", ""),
                            "source_id": ext.get("source_id", ""),
                        })
                except Exception:
                    pass

        return {"raw_text": raw, "entities": entities}

    def _format_reply_context(self, ctx: dict) -> str:
        """Turn enriched reply context into a text block for LLM input."""
        if not ctx.get("raw_text"):
            return ""

        parts = [
            "[主人正在回覆這則訊息]",
            "───",
            ctx["raw_text"][:2000],
            "───",
        ]

        if ctx.get("entities"):
            parts.append("\n[以下是從資料庫查到的相關資訊]")
            for e in ctx["entities"]:
                if e["type"] == "question":
                    parts.append(
                        f"  問題 #{e['id']}: {e['detail']}"
                        + (f" (⚓ {e['soul_anchor']})" if e.get("soul_anchor") else "")
                    )
                elif e["type"] == "insight":
                    parts.append(f"  Insight {e['id']}: {e['detail']}")
                elif e["type"] == "extract":
                    line = f"  Extract {e['id']}: {e.get('title', '')}"
                    if e.get("url"):
                        line += f"\n    URL: {e['url']}"
                    if e.get("source_id"):
                        line += f" [{e['source_id']}]"
                    parts.append(line)

        return "\n".join(parts)

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
        # Split long messages at paragraph boundaries instead of silently truncating
        for chunk in self._split_for_telegram(text):
            try:
                await self.app.bot.send_message(chat_id=self.owner_id, text=chunk)
            except Exception as e:
                logger.error(f"Telegram notify failed: {e}")
                return

    @staticmethod
    def _split_for_telegram(text: str, max_len: int = 3900) -> list[str]:
        """Split text at paragraph boundaries so Telegram's 4096 limit doesn't eat content."""
        if len(text) <= max_len:
            return [text]
        chunks = []
        remaining = text
        while len(remaining) > max_len:
            # Prefer splitting at double newline, then single newline, then hard cut
            split_at = remaining.rfind("\n\n", 0, max_len)
            if split_at < max_len // 2:
                split_at = remaining.rfind("\n", 0, max_len)
            if split_at < max_len // 2:
                split_at = max_len
            chunks.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()
        if remaining:
            chunks.append(remaining)
        return chunks

    # ── Commands ──

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🦞 Lobster v4 — 你的研究探索龍蝦\n\n"
            "── 🔬 Curiosity Loop ──\n"
            "📊 /status — 龍蝦現在在幹嘛\n"
            "❓ /questions — 目前的 open questions\n"
            "💉 /inject <問題> — 手動塞一個探索問題\n"
            "🧠 /knowledge <topic> — 查 cluster 理解\n"
            "⏸ /pause　▶️ /resume — 暫停 / 恢復 loop\n"
            "\n── 📰 v4 多源爬蟲 + 晨間 Digest ──\n"
            "🔎 /feedcrawl — 立刻跑一輪 multi-source 爬蟲\n"
            "📨 /feeddigest [hours] — 立刻生 digest 並送到聊天室（預設 12h）\n"
            "📚 /digest — 看最近 2 天已存的 digest summary\n"
            "\n── 📝 內容發文 (v2.5) ──\n"
            "📝 /post — 立刻觸發一次發文\n"
            "🔍 /explore <topic> — 立刻 web 搜尋\n"
            "🍽 /binge [n] — 狂探索 n 輪\n"
            "🧠 /relearn — 重新內化 soul/style\n"
            "\n── 🧬 Evolution ──\n"
            "🧬 /evolve — 立刻觸發 weekly Evolve\n"
            "🧪 /prompt_override [activate] — 跑 P1 prompt diff（預設 dry-run）\n"
            "📋 /overrides — 列出 active + dry_run overrides\n"
            "✅ /activate_override <id> — dry_run → active\n"
            "↩️ /rollback_override <id> [reason]\n"
            "🪦 /killed　🔁 /override <post_id> — 看/復活被 Critic 殺掉的 draft\n"
            "\n── ⚙️ 系統 ──\n"
            "📊 /stats — 本月統計 & 預算\n"
            "🤖 /model [name] — 看 / 切換模型\n"
            "👁 /track <handle> — 追蹤 X 帳號\n"
            "⭐ /rate <id> <1-5> [評語] — 評價 insight/post\n"
            "\n📎 貼 URL → 立即 Forage → Digest\n"
            "💭 打字 → 跟龍蝦聊天"
        )

    # ── v3 NEW commands ──

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

    async def _cmd_feedcrawl(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/feedcrawl — run FeedCoordinator once (morning tier mix)."""
        fc = context.bot_data.get("feed_coordinator")
        if not fc:
            await update.message.reply_text("❌ feed_coordinator not initialized")
            return
        await update.message.reply_text("🔎 Running v4 feed crawl (morning mode)...")
        try:
            result = await fc.run_exploration(mode="morning")
            await update.message.reply_text(
                f"✅ Crawl done.\n"
                f"  inserted: {result.get('inserted', 0)}\n"
                f"  considered: {result.get('considered', 0)}\n"
                f"  batch_id: {result.get('batch_id', '-')}"
            )
        except Exception as e:
            logger.error(f"feedcrawl failed: {e}", exc_info=True)
            await update.message.reply_text(f"❌ feedcrawl failed: {e}")

    async def _cmd_feeddigest(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/feeddigest [hours] — render and send morning digest now."""
        dg = context.bot_data.get("digest_generator")
        if not dg:
            await update.message.reply_text("❌ digest_generator not initialized")
            return
        hours = 12
        if context.args:
            try:
                hours = int(context.args[0])
            except ValueError:
                await update.message.reply_text("❌ usage: /feeddigest [hours]")
                return
        await update.message.reply_text(f"📰 Generating digest (last {hours}h)...")
        try:
            result = await dg.generate_and_send(hours=hours)
            cats = result.get("categories") or {}
            cats_str = ", ".join(f"{k}:{v}" for k, v in cats.items()) or "-"
            await update.message.reply_text(
                f"✅ Digest sent.\n"
                f"  items: {result.get('sent', 0)}\n"
                f"  breakdown: {cats_str}"
            )
        except Exception as e:
            logger.error(f"feeddigest failed: {e}", exc_info=True)
            await update.message.reply_text(f"❌ feeddigest failed: {e}")

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

    # ── Evolution v5: prompt_overrides (P1) + revive killed drafts (P4) ──

    async def _cmd_prompt_override(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/prompt_override [activate] — run P1 diff now. Defaults to dry-run."""
        if not self.evolver:
            await update.message.reply_text("❌ evolver not initialized")
            return
        activate = bool(context.args and context.args[0].lower() in ("activate", "live"))
        await update.message.reply_text(
            f"🧪 Running prompt_override { '(ACTIVATE mode)' if activate else '(dry-run)' }..."
        )
        try:
            result = await self.evolver.run_prompt_override(activate=activate)
            status = result.get("status")
            if status == "skipped":
                await update.message.reply_text(
                    f"⏭ Skipped: {result.get('reason')} (posts with engagement: {result.get('count', 0)})"
                )
            elif status == "failed":
                await update.message.reply_text(f"❌ Failed: {result.get('error', 'unknown')}")
            else:
                created = result.get("created") or []
                await update.message.reply_text(
                    f"✅ Done. {len(created)} override(s) stored as "
                    f"{'active' if activate else 'dry_run'}. "
                    f"Top/bot baseline: {result.get('top_baseline'):.1f} / "
                    f"{result.get('bottom_baseline'):.1f}"
                )
        except Exception as e:
            logger.error(f"prompt_override failed: {e}", exc_info=True)
            await update.message.reply_text(f"❌ prompt_override failed: {e}")

    async def _cmd_overrides(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/overrides — list active + dry_run prompt_overrides."""
        if not self.db:
            await update.message.reply_text("❌ DB not connected")
            return
        try:
            rows = await self.db.list_prompt_overrides(limit=30)
        except Exception as e:
            await update.message.reply_text(f"❌ Query failed: {e}")
            return
        if not rows:
            await update.message.reply_text("(沒有任何 prompt_override)")
            return
        by_status = {"active": [], "dry_run": [], "validated": [], "superseded": [], "rolled_back": []}
        for r in rows:
            by_status.setdefault(r["status"], []).append(r)
        lines = ["🧪 Prompt overrides:"]
        for st in ("active", "dry_run", "validated", "superseded", "rolled_back"):
            bucket = by_status.get(st) or []
            if not bucket:
                continue
            lines.append(f"\n— {st} ({len(bucket)}) —")
            for r in bucket[:8]:
                content_preview = (r.get("content") or "")[:90].replace("\n", " ")
                lines.append(
                    f"  [{r['id'][:8]}] {r['target']} v{r['version']} variant {r['variant']} "
                    f"baseline={r.get('baseline_engagement')}"
                )
                lines.append(f"    {content_preview}")
        lines.append("\nActivate: /activate_override <id>")
        lines.append("Rollback: /rollback_override <id>")
        await update.message.reply_text("\n".join(lines)[:4000])

    async def _cmd_activate_override(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/activate_override <id> — promote dry_run to active (supersedes prior)."""
        if not (context.args and self.db):
            await update.message.reply_text("Usage: /activate_override <override_id>")
            return
        override_id = context.args[0]
        try:
            ok = await self.db.activate_override(override_id)
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {e}")
            return
        if not ok:
            await update.message.reply_text(f"❌ No override with id={override_id}")
            return
        await update.message.reply_text(f"✅ Activated {override_id[:8]} — next post uses this in variant B (50/50 A/B split).")

    async def _cmd_rollback_override(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/rollback_override <id> — mark as rolled_back."""
        if not (context.args and self.db):
            await update.message.reply_text("Usage: /rollback_override <override_id> [reason]")
            return
        override_id = context.args[0]
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else None
        try:
            await self.db.rollback_override(override_id, note=reason)
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {e}")
            return
        await update.message.reply_text(f"✅ Rolled back {override_id[:8]}")

    async def _cmd_override(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/override <killed_post_id> [note] — revive a Critic-killed draft (P4)."""
        if not (context.args and self.db and self.lobster):
            await update.message.reply_text(
                "Usage: /override <post_id>\n"
                "(post_id 來自 Critic killed 通知訊息)"
            )
            return
        post_id = context.args[0]
        note = " ".join(context.args[1:]) if len(context.args) > 1 else None
        try:
            post = await self.db.get_killed_post(post_id)
        except Exception as e:
            await update.message.reply_text(f"❌ DB failed: {e}")
            return
        if not post:
            await update.message.reply_text(f"❌ Not found: {post_id}")
            return
        if post.get("status") != "killed_by_critic":
            await update.message.reply_text(
                f"⚠️ Post {post_id[:8]} status={post.get('status')}; "
                f"only killed_by_critic drafts can be revived."
            )
            return

        platform = post.get("platform")
        draft_text = post.get("draft_text") or ""
        await update.message.reply_text(
            f"🔧 Reviving killed draft ({platform}):\n{draft_text[:200]}...\nPublishing now..."
        )
        try:
            # Publish raw (skip Critic since user overrode it)
            published_url = None
            post_platform_id = None
            if platform == "x" and getattr(self.lobster, "x_poster", None):
                result = await self.lobster.x_poster.post_tweet(draft_text)
                post_platform_id = result.get("tweet_id")
                published_url = result.get("url")
            elif platform == "threads" and getattr(self.lobster, "threads_poster", None):
                post_platform_id = await self.lobster.threads_poster.post(draft_text)
            else:
                await update.message.reply_text(f"❌ No poster wired for platform={platform}")
                return

            # Update post row: status=human_override, write actual platform id
            patch = {
                "status": "human_override",
                "human_override_at": datetime.utcnow().isoformat(),
                "posted_text": draft_text,
                "posted_at": datetime.utcnow().isoformat(),
            }
            if note:
                patch["human_override_note"] = note
            if post_platform_id:
                if platform == "x":
                    patch["x_post_id"] = post_platform_id
                else:
                    patch["threads_post_id"] = post_platform_id
            await self.db._update("posts", {"id": post_id}, patch)
            reply_bits = [f"✅ Published via override: {post_id[:8]}"]
            if published_url:
                reply_bits.append(published_url)
            await update.message.reply_text("\n".join(reply_bits))
        except Exception as e:
            logger.error(f"/override failed for {post_id}: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Publish failed: {e}")

    async def _cmd_killed(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/killed — list recent critic-killed drafts (for /override)."""
        if not self.db:
            await update.message.reply_text("❌ DB not connected")
            return
        days = 7
        if context.args:
            try:
                days = int(context.args[0])
            except ValueError:
                pass
        try:
            rows = await self.db.list_killed_posts(days=days, limit=15)
        except Exception as e:
            await update.message.reply_text(f"❌ Query failed: {e}")
            return
        if not rows:
            await update.message.reply_text(f"(過去 {days} 天沒有 killed draft)")
            return
        lines = [f"🚫 Killed drafts (last {days}d, {len(rows)}):"]
        for r in rows:
            reason = (r.get("kill_reason") or {}) or {}
            issues = reason.get("issues") or []
            issue_str = issues[0][:60] if issues else reason.get("verdict", "?")
            preview = (r.get("draft_text") or "")[:80].replace("\n", " ")
            lines.append(
                f"\n[{r['id']}] {r.get('platform')} skill={r.get('skill_used')} "
                f"killed={r.get('killed_at', '')[:16]}"
                f"\n  reason: {issue_str}"
                f"\n  draft: {preview}..."
            )
        lines.append("\nRevive with: /override <post_id>")
        await update.message.reply_text("\n".join(lines)[:4000])

    # ── v2.5 commands (kept) ──

    async def _cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.db:
            await update.message.reply_text("DB not connected")
            return
        from lobster.utils.token_tracker import TokenTracker
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

        # /model refresh — re-fetch models from local endpoint
        if context.args and context.args[0].lower() == "refresh":
            models = await self.llm.refresh_local_models()
            if models:
                await update.message.reply_text(
                    f"🔄 Local endpoint models:\n" + "\n".join(f"  • {m}" for m in models)
                )
            else:
                await update.message.reply_text("❌ Could not fetch models from local endpoint")
            return

        if not context.args:
            info = self.llm.get_model_info()
            local_model = self.llm.local.model if self.llm.local else None
            local_available = bool(self.llm.local and self.llm.local.available)
            lines = [
                f"💬 Chat 預設: 🖥 LOCAL ({local_model})"
                + ("  ✅" if local_available else "  ⚠️ local endpoint 沒回應，會 fallback 到 remote"),
                f"🧠 Connect / Mirror: 🌐 REMOTE ({info['name']})",
                "",
                "── 🖥 Local (chat + 大部分 agent 用這個) ──",
            ]
            local_models = self.llm.local.get_cached_models()
            if local_models:
                for mid in local_models:
                    marker = "▶" if mid == local_model else " "
                    lines.append(f"{marker} {mid}")
            else:
                lines.append(f"▶ {local_model}  (沒跑過 /model refresh，僅顯示預設)")

            lines.append("")
            lines.append("── 🌐 Remote (只給 Connect 深度推理用) ──")
            for m in self.llm.list_models():
                if m.get("tier") == "local":
                    continue
                marker = "▶" if m["name"] == info["name"] else " "
                lines.append(f"{marker} {m['name']} — {m['model_id']}")

            lines.append("\nUsage: /model <name> | /model refresh")
            await update.message.reply_text("\n".join(lines))
            return

        name = context.args[0].lower()
        # Try local models first (exact match on model ID)
        local_models = self.llm.local.get_cached_models()
        if name in local_models:
            self.llm.local.set_model(name)
            await update.message.reply_text(f"✅ Local model → {name}")
            return
        # Then remote
        if self.llm.set_active_model(name):
            if self.llm.remote:
                await self.llm.remote.save_active_model_to_db()
            info = self.llm.get_model_info()
            await update.message.reply_text(f"✅ Switched to: {info['name']} ({info['model_id']})")
        else:
            await update.message.reply_text(f"❌ Unknown model: {name}\nTry /model refresh to update available models")

    async def _cmd_testemail(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        from lobster.bridge.gateway import send_email_notification
        await update.message.reply_text("📧 Sending test email…")
        ok = await send_email_notification(
            "Lobster v4 SMTP test",
            "If you are reading this, the email gateway works. 🦞",
        )
        await update.message.reply_text("✅ sent" if ok else "❌ failed (check logs)")

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
        reply_ctx = await self._enrich_reply_context(update)
        reply_block = self._format_reply_context(reply_ctx)

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
                    insight_text = conn.get('insight') or ''
                    # Show produced insight titles + bodies if any
                    ins_summary = ""
                    for ins in (result.get("insights") or [])[:3]:
                        ins_summary += f"\n\n💡 {ins.get('title', '')}\n{ins.get('body', '')}"
                    msg = (
                        f"✅ Digested.\n"
                        f"connection_type: {conn.get('connection_type')}\n\n"
                        f"{insight_text}\n"
                        f"{ins_summary}"
                    )
                    await update.message.reply_text(truncate_for_telegram(msg))
                else:
                    await update.message.reply_text(f"❌ {result.get('reason', 'failed')}")
            except Exception as e:
                logger.error(f"URL inject failed: {e}", exc_info=True)
                await update.message.reply_text(f"❌ URL inject error: {e}")
            return

        # Natural language chat
        if self.llm and self.lobster:
            try:
                from lobster.utils.identity_loader import load_identity
                identity = await load_identity(self.db)

                # Build user message with reply context
                if reply_block:
                    user_msg = f"{reply_block}\n\n主人說：{text}"
                else:
                    user_msg = text

                system = (
                    f"{identity}\n\n"
                    "你現在在跟你的主人用 Telegram 聊天。\n"
                    "用繁體中文回覆，語氣自然口語，保持你的個性風格。\n"
                    "回覆簡短（200字以內），不用正式開場白或結尾。\n\n"
                    "關於你自己的能力（事實，不要搞錯）：\n"
                    "- 你確實會自動發文到 X 和 Threads，每天有排程 heartbeat 會跑 create_post\n"
                    "- 你會定期寄 Telegram 通知給主人（insight 產出、發文結果、進化提案）\n"
                    "- 如果主人問「你剛剛發了什麼」，去翻 telegram 聊天紀錄或回答不知道；不要說「我沒有主動發送權限」\n"
                    "- 你的主要 commands：/status /questions /inject /knowledge /digest /evolve /post /explore /binge /stats /model /pause /resume\n\n"
                    "回覆上下文規則：\n"
                    "- 回覆上下文（[主人正在回覆這則訊息] 區塊）是主人正在談論的內容，必須優先參考\n"
                    "- [從資料庫查到的相關資訊] 是真實資料，引用時必須使用這些資訊，不可編造\n"
                    "- 「這個」「這篇」「上面那個」「#數字」= 回覆上下文裡的內容\n"
                    "- 如果主人問「原文」「連結」「paper」，從回覆上下文的 URL 或 source 資訊回答\n"
                    "- 絕對不要說「你指的是哪個」——如果有回覆上下文，你就知道是哪個\n"
                    "- 不知道的就說不知道，不要編造論文標題、連結、或內容"
                )
                reply = await self.llm.chat("lobster", system, user_msg, max_tokens=500)
                await update.message.reply_text(reply.strip())
            except Exception as e:
                logger.error(f"Chat reply failed: {e}")
                if self.db:
                    await self.db.insert_discovery(
                        source_type="thought",
                        title=text[:80],
                        summary=text,
                        content_type="thought",
                        interest_score=5,
                    )
                    await update.message.reply_text("💭 Stored as thought.")
        elif self.db:
            await self.db.insert_discovery(
                source_type="thought",
                title=text[:80],
                summary=text,
                content_type="thought",
                interest_score=5,
            )
            await update.message.reply_text("💭 Stored as thought.")
