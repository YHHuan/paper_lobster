"""Autonomous evolution engine with tiered autonomy.

Changes are classified by risk level:
- low_risk: Auto-execute, notify via Telegram
- medium_risk: Notify, auto-execute after 24h if no veto
- high_risk: Require explicit /approve from owner

This allows the lobster to evolve without bottlenecking on human approval
for safe changes, while protecting core identity for risky ones.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("lobster.agent.evolution")

IDENTITY_DIR = Path(__file__).parent.parent / "identity"
SKILLS_DIR = Path(__file__).parent.parent / "skills"

# What changes fall into which risk tier
RISK_TIERS = {
    "low_risk": {
        "description": "Auto-execute, Telegram notification",
        "actions": [
            "update_curiosity",         # Already happens daily
            "update_memory",            # Already happens daily
            "adjust_query_weights",     # Which topics to search more
            "add_rss_source",           # New RSS feed
            "update_skill_preference",  # Lean toward better-performing skills
        ],
    },
    "medium_risk": {
        "description": "Notify owner, auto-execute after 24h if no veto",
        "actions": [
            "modify_style_voice",       # Tweak style.md voice descriptions
            "adjust_posting_schedule",  # Change frequency or timing
            "create_new_skill",         # New content skill
            "modify_banned_phrases",    # Add/remove AI smell phrases
        ],
    },
    "high_risk": {
        "description": "Require explicit /approve",
        "actions": [
            "modify_soul_values",       # Core identity changes
            "change_model",             # Switch LLM model
            "modify_budget",            # Change spending limits
            "enable_proactive",         # Turn on proactive engagement
            "modify_platform_config",   # Add/remove platforms
        ],
    },
}


def classify_risk(action: str) -> str:
    """Classify an evolution action by risk tier."""
    for tier, config in RISK_TIERS.items():
        if action in config["actions"]:
            return tier
    return "high_risk"  # Default to safest


class EvolutionEngine:
    def __init__(self, db, telegram=None):
        self.db = db
        self.telegram = telegram

    async def propose_and_execute(self, action: str, description: str,
                                   details: dict = None) -> bool:
        """Propose an evolution action. Execute immediately if low-risk,
        schedule if medium-risk, wait for approval if high-risk.

        Returns True if executed immediately.
        """
        risk = classify_risk(action)
        details = details or {}

        # Log the proposal
        await self.db.log_evolution(
            type=f"{risk}:{action}",
            description=description,
            diff_content=json.dumps(details, ensure_ascii=False),
        )

        if risk == "low_risk":
            success = await self._execute(action, details)
            if self.telegram and success:
                await self.telegram.notify(
                    f"🧬 Auto-evolution (low risk):\n"
                    f"Action: {action}\n"
                    f"{description}"
                )
            return success

        elif risk == "medium_risk":
            # Store as pending with 24h deadline
            await self.db.log_evolution(
                type=f"pending:{action}",
                description=f"[Auto in 24h] {description}",
                diff_content=json.dumps({
                    **details,
                    "auto_execute_after": (datetime.utcnow() + timedelta(hours=24)).isoformat(),
                }, ensure_ascii=False),
            )
            if self.telegram:
                await self.telegram.notify(
                    f"🧬 Evolution proposal (medium risk):\n"
                    f"Action: {action}\n"
                    f"{description}\n\n"
                    f"Will auto-execute in 24h unless you reply /veto"
                )
            return False

        else:  # high_risk
            if self.telegram:
                await self.telegram.notify(
                    f"🧬 Evolution proposal (HIGH risk — needs approval):\n"
                    f"Action: {action}\n"
                    f"{description}\n\n"
                    f"Reply /approve to execute, or ignore to reject."
                )
            return False

    async def execute_pending(self):
        """Check and execute medium-risk changes past their 24h window.

        Call this from a heartbeat (e.g., during nightly reflect).
        """
        try:
            pending = await self.db._select("evolution_log", {
                "select": "*",
                "type": "like.pending:%",
                "approved": "is.null",
                "order": "created_at.asc",
                "limit": "10",
            })

            now = datetime.utcnow()
            executed = 0

            for entry in pending:
                diff = entry.get("diff_content", "{}")
                if isinstance(diff, str):
                    diff = json.loads(diff)

                auto_after = diff.get("auto_execute_after")
                if not auto_after:
                    continue

                deadline = datetime.fromisoformat(auto_after)
                if now >= deadline:
                    action = entry["type"].replace("pending:", "")
                    success = await self._execute(action, diff)
                    if success:
                        await self.db._update(
                            "evolution_log",
                            {"id": str(entry["id"])},
                            {"approved": True},
                        )
                        executed += 1
                        if self.telegram:
                            await self.telegram.notify(
                                f"🧬 Auto-executed (24h passed, no veto):\n"
                                f"{entry.get('description', action)}"
                            )

            if executed:
                logger.info(f"Executed {executed} pending evolution actions")

        except Exception as e:
            logger.error(f"execute_pending failed: {e}")

    async def _execute(self, action: str, details: dict) -> bool:
        """Execute a specific evolution action."""
        try:
            if action == "update_curiosity":
                content = details.get("content", "")
                if content:
                    await self.db.update_identity_state("curiosity", content, "evolution")
                return bool(content)

            elif action == "update_memory":
                content = details.get("content", "")
                if content:
                    await self.db.update_identity_state("memory", content, "evolution")
                return bool(content)

            elif action == "add_rss_source":
                name = details.get("name", "")
                url = details.get("url", "")
                if name and url:
                    await self.db._insert("rss_sources", {
                        "name": name,
                        "url": url,
                        "category": details.get("category", "auto"),
                        "discovered_by": "evolution",
                    })
                    return True
                return False

            elif action == "update_skill_preference":
                # Store skill weights in identity_state
                weights = details.get("weights", {})
                if weights:
                    await self.db.update_identity_state(
                        "skill_preferences",
                        json.dumps(weights, ensure_ascii=False),
                        "evolution",
                    )
                    return True
                return False

            elif action == "adjust_query_weights":
                # Store in identity_state for dynamic query gen to pick up
                topics = details.get("topics", {})
                if topics:
                    await self.db.update_identity_state(
                        "query_preferences",
                        json.dumps(topics, ensure_ascii=False),
                        "evolution",
                    )
                    return True
                return False

            elif action == "modify_style_voice":
                section = details.get("section", "")
                new_content = details.get("new_content", "")
                if section and new_content:
                    # Read current style.md, apply change
                    style_path = IDENTITY_DIR / "style.md"
                    style_path.read_text(encoding="utf-8")
                    # Store the proposed change for git commit later
                    await self.db.log_evolution(
                        type="applied:modify_style_voice",
                        description=f"Modified style.md section: {section}",
                        file_changed="identity/style.md",
                        diff_content=json.dumps({
                            "section": section,
                            "new_content": new_content,
                        }, ensure_ascii=False),
                    )
                    return True
                return False

            else:
                logger.warning(f"Unknown evolution action: {action}")
                return False

        except Exception as e:
            logger.error(f"Evolution execution failed for {action}: {e}")
            return False

    async def veto(self, entry_id: str) -> bool:
        """Veto a pending evolution action."""
        try:
            await self.db._update(
                "evolution_log",
                {"id": entry_id},
                {"approved": False},
            )
            return True
        except Exception:
            return False
