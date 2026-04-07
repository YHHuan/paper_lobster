"""Token budget tracking and enforcement.

Monitors monthly spend and triggers warnings/throttling.
"""

import os
import logging

logger = logging.getLogger("lobster.utils.tokens")


class TokenTracker:
    def __init__(self, db):
        self.db = db
        self.monthly_budget = float(os.environ.get("MONTHLY_TOKEN_BUDGET", "30"))

    async def get_monthly_spend(self) -> float:
        return await self.db.get_monthly_cost()

    async def get_budget_status(self) -> dict:
        spent = await self.get_monthly_spend()
        pct = (spent / self.monthly_budget * 100) if self.monthly_budget > 0 else 0
        return {
            "spent_usd": round(spent, 2),
            "budget_usd": self.monthly_budget,
            "pct": round(pct, 1),
            "warning": pct >= 80,
            "over_budget": pct >= 100,
            "throttle": pct >= 120,
        }

    async def should_explore(self) -> bool:
        """Returns False if budget is exceeded and exploration should stop."""
        status = await self.get_budget_status()
        if status["throttle"]:
            logger.warning(f"Budget throttle: {status['pct']}% used, exploration paused")
            return False
        return True
