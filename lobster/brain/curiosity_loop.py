"""brain/curiosity_loop.py — the heart of v3.

Event-driven orchestrator. Runs Forage → Extract → Connect → Synthesize loops
as long as there are open_questions, while respecting:

- daily hard cap (CURIOSITY_LOOP_MAX_ROUNDS_PER_DAY, default 10)
- inter-loop sleep (CURIOSITY_LOOP_SLEEP_BETWEEN_ROUNDS, default 900s)
- pause flag stored in identity_state
- connect rate stall (3 consecutive loops with rate < CONNECT_RATE_STALL_THRESHOLD)

Triggers:
- 06:00 / 18:00 seed cron — calls `seed()` which runs Reflect → Hypothesize and
  then starts the loop.
- Manual /inject or pasted URL — calls `inject_question()` / `inject_url()`.
- Manual /explore — same as inject_question with priority bump.
"""

import os
import asyncio
import logging
from datetime import datetime
from pathlib import Path

from lobster.explorer.sources.base import OpenQuestion

logger = logging.getLogger("lobster.brain.loop")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


SOUL_PATH = Path(__file__).parent.parent / "identity" / "soul.md"


def _load_soul() -> str:
    try:
        return SOUL_PATH.read_text()
    except Exception:
        return ""


class CuriosityLoop:
    def __init__(
        self,
        *,
        llm,
        db,
        knowledge,
        reflector,
        hypothesizer,
        forager,
        extractor,
        connector,
        synthesizer,
        telegram=None,
    ):
        self.llm = llm
        self.db = db
        self.knowledge = knowledge
        self.reflector = reflector
        self.hypothesizer = hypothesizer
        self.forager = forager
        self.extractor = extractor
        self.connector = connector
        self.synthesizer = synthesizer
        self.telegram = telegram

        self.max_rounds_per_day = _env_int("CURIOSITY_LOOP_MAX_ROUNDS_PER_DAY", 10)
        self.sleep_between = _env_int("CURIOSITY_LOOP_SLEEP_BETWEEN_ROUNDS", 900)
        self.stall_threshold = _env_float("CONNECT_RATE_STALL_THRESHOLD", 0.3)
        self.max_per_source = _env_int("FORAGE_MAX_PER_SOURCE", 3)

        self._task: asyncio.Task | None = None
        self._stall_streak = 0
        self._running = False

    # ── Public triggers ──

    async def seed(self, trigger: str = "morning_seed") -> dict:
        """Run Reflect → Hypothesize → kick the loop. Called by cron."""
        if await self.db.is_loop_paused():
            logger.info("loop is paused, skipping seed")
            return {"status": "paused"}

        logger.info(f"Seeding curiosity loop ({trigger})")
        memo = await self.reflector.reflect(trigger=trigger)
        questions = await self.hypothesizer.hypothesize(memo)
        logger.info(f"Seeded {len(questions)} new open_questions")

        if self.telegram:
            try:
                # Let truncate_for_telegram (4096) handle length — don't pre-cut at 500
                await self.telegram.notify(
                    f"🧠 Seed ({trigger})\n\n{memo}\n\n→ {len(questions)} 個新問題"
                )
            except Exception:
                pass

        # Kick the loop in background
        self.start()
        return {"status": "seeded", "memo": memo, "questions": questions}

    async def inject_question(self, question: str, priority: float = 0.9) -> int:
        qid = await self.db.insert_open_question(
            question=question,
            priority=priority,
            reasoning="manual injection",
        )
        self.start()
        return qid

    async def inject_url(self, url: str) -> dict:
        """Bypass forage — pull URL via Jina, extract, connect, synthesize."""
        rf = await self.forager.forage_url(url)
        if not rf:
            return {"status": "failed", "reason": "could not fetch url"}

        ext_id = await self.extractor.extract(rf)
        if not ext_id:
            return {"status": "failed", "reason": "extract failed"}

        conn = await self.connector.connect(ext_id)
        if not conn:
            return {"status": "failed", "reason": "connect failed"}

        soul = _load_soul()
        insights = await self.synthesizer.synthesize([conn], soul_md=soul)

        await self._notify_insights(insights)

        return {
            "status": "ok",
            "extract_id": ext_id,
            "connection": conn,
            "insights": insights,
        }

    def start(self):
        """Idempotent — kicks the loop if not already running."""
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_until_empty())

    async def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    @property
    def running(self) -> bool:
        return bool(self._task and not self._task.done())

    # ── Internal loop ──

    async def _run_until_empty(self):
        if self._running:
            return
        self._running = True
        try:
            while True:
                if await self.db.is_loop_paused():
                    logger.info("loop paused mid-run, exiting")
                    break

                if await self.db.get_today_loop_count() >= self.max_rounds_per_day:
                    logger.info(f"hit daily cap {self.max_rounds_per_day}, sleeping until tomorrow")
                    break

                pending = await self.db.get_pending_questions(limit=1)
                if not pending:
                    logger.info("no pending questions; loop done")
                    break

                if self._stall_streak >= 3:
                    logger.warning(f"connect rate stalled {self._stall_streak} loops, pausing")
                    if self.telegram:
                        try:
                            await self.telegram.notify(
                                "⏸ Curiosity loop 連續 3 輪 connect 率過低，自動暫停。"
                            )
                        except Exception:
                            pass
                    break

                question = pending[0]
                await self._run_one_round(question)

                # Inter-loop sleep (except if a brand-new question landed)
                if self.sleep_between > 0:
                    await asyncio.sleep(self.sleep_between)
        except asyncio.CancelledError:
            logger.info("loop cancelled")
            raise
        except Exception as e:
            logger.exception(f"loop crashed: {e}")
        finally:
            self._running = False

    async def _run_one_round(self, q_row: dict):
        run_id = await self.db.start_loop_run(questions_input=1)
        await self.db.mark_question_status(q_row["id"], "foraging")
        question = OpenQuestion.from_row(q_row)

        soul = _load_soul()

        # Track tokens for run accounting
        local_before = self.llm.local.total_tokens
        remote_before = self.llm.remote.total_tokens if self.llm.remote else 0

        extracts_count = 0
        connections_count = 0
        useful_connections: list[dict] = []
        try:
            finds = await self.forager.forage_question(question, max_per_source=self.max_per_source)

            for rf in finds:
                ext_id = await self.extractor.extract(rf)
                if not ext_id:
                    continue
                extracts_count += 1
                conn = await self.connector.connect(ext_id, soul_md=soul)
                if conn:
                    connections_count += 1
                    if conn.get("connection_type") != "irrelevant":
                        useful_connections.append(conn)

            insights = []
            if useful_connections:
                insights = await self.synthesizer.synthesize(useful_connections, soul_md=soul)
                await self._notify_insights(insights)

            # Stall detection: connect rate this round
            connect_rate = (len(useful_connections) / extracts_count) if extracts_count else 0
            if connect_rate < self.stall_threshold:
                self._stall_streak += 1
            else:
                self._stall_streak = 0

            await self.db.mark_question_status(q_row["id"], "resolved")

            local_used = self.llm.local.total_tokens - local_before
            remote_used = (self.llm.remote.total_tokens - remote_before) if self.llm.remote else 0

            await self.db.finish_loop_run(
                run_id,
                extracts_produced=extracts_count,
                connections_made=connections_count,
                insights_generated=len(insights),
                local_tokens_used=local_used,
                remote_tokens_used=remote_used,
                status="completed",
                notes=f"connect_rate={connect_rate:.2f}",
            )
        except Exception as e:
            logger.exception(f"round failed: {e}")
            await self.db.finish_loop_run(
                run_id,
                extracts_produced=extracts_count,
                connections_made=connections_count,
                status="failed",
                notes=str(e)[:200],
            )
            await self.db.mark_question_status(q_row["id"], "stale")

    async def _notify_insights(self, insights: list[dict]):
        if not (self.telegram and insights):
            return
        for ins in insights:
            try:
                title = ins.get("title", "(insight)")
                body = ins.get("body", "")  # no pre-truncation — telegram layer caps at 4096
                hook = ins.get("hook_score", "?")
                pub = "📤 publishable" if ins.get("publishable") else ""

                # Resolve source links from extract IDs
                source_lines = []
                for ext_id in (ins.get("source_extracts") or [])[:3]:
                    try:
                        ext = await self.db.get_extract(ext_id)
                        if ext:
                            label = ext.get("title", "")[:80] or ext_id
                            url = ext.get("url") or ""
                            sid = ext.get("source_id") or ""
                            if url:
                                source_lines.append(f"🔗 {label}\n   {url}")
                            elif sid:
                                source_lines.append(f"🔗 {label} [{sid}]")
                    except Exception:
                        pass

                msg = f"💡 {title}\n\n{body}\n\nhook={hook} {pub}"
                if source_lines:
                    msg += "\n\n── sources ──\n" + "\n".join(source_lines)
                await self.telegram.notify(msg)
            except Exception:
                pass
