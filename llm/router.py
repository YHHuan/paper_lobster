"""LLM tier router for Lobster v3.

Two tiers:
  LOCAL  — gpt-oss-b on your own box. Free. Use for: reflect, hypothesize,
           extract, synthesize, evolve, query generation, hook check, AI-smell.
  REMOTE — OpenRouter (Sonnet by default). Costs money. Use for: connect (digest),
           high-quality writing, anything that needs long context + reasoning.

The router exposes a unified `chat()` and `chat_json()` API that takes a `tier`
argument. Token tracking is delegated to the underlying client.

Backward-compat shim: older code that imported `LLMClient` from `llm/client.py`
should now import `LLMRouter` from `llm/router.py` and either pass `tier="remote"`
explicitly or use the convenience methods.
"""

import logging
from typing import Literal

from .local_client import LocalLLMClient, LocalLLMError
from .remote_client import RemoteLLMClient, RemoteLLMError

logger = logging.getLogger("lobster.llm.router")

Tier = Literal["local", "remote"]


class LLMRouter:
    def __init__(self):
        self.local = LocalLLMClient()
        try:
            self.remote = RemoteLLMClient()
        except RemoteLLMError as e:
            logger.error(f"Remote client init failed: {e}")
            self.remote = None

    # ── Bookkeeping ──

    def inject_db(self, db):
        if self.remote:
            self.remote.inject_db(db)

    async def load_active_model_from_db(self):
        if self.remote:
            await self.remote.load_active_model_from_db()

    @property
    def active_model_name(self) -> str:
        return self.remote.active_model_name if self.remote else "local"

    def set_active_model(self, name: str) -> bool:
        return self.remote.set_active_model(name) if self.remote else False

    def get_model_info(self) -> dict:
        if self.remote:
            return self.remote.get_model_info()
        return {"name": "local", "model_id": self.local.model, "provider": "local"}

    @staticmethod
    def list_models() -> list[dict]:
        return RemoteLLMClient.list_models() + [{"name": "local", "model_id": "local"}]

    # ── Unified chat ──

    async def chat(
        self,
        agent: str,
        system_prompt: str,
        user_message: str,
        tier: Tier = "remote",
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        if tier == "local":
            if not self.local.available:
                logger.warning(f"[{agent}] LOCAL not available, falling back to REMOTE")
                tier = "remote"
            else:
                return await self.local.chat(
                    agent=agent,
                    system_prompt=system_prompt,
                    user_message=user_message,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
        if not self.remote:
            raise RuntimeError("Remote LLM not available and local fallback exhausted")
        return await self.remote.chat(
            agent=agent,
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=max_tokens or 2048,
            json_mode=json_mode,
        )

    async def chat_json(
        self,
        agent: str,
        system_prompt: str,
        user_message: str,
        tier: Tier = "remote",
        max_tokens: int | None = None,
    ) -> dict | list:
        if tier == "local" and self.local.available:
            return await self.local.chat_json(agent, system_prompt, user_message, max_tokens=max_tokens)
        if not self.remote:
            raise RuntimeError("Remote LLM not available")
        return await self.remote.chat_json(agent, system_prompt, user_message, max_tokens=max_tokens or 2048)

    # ── Convenience helpers ──

    async def chat_local(self, agent, system_prompt, user_message, **kw):
        return await self.chat(agent, system_prompt, user_message, tier="local", **kw)

    async def chat_remote(self, agent, system_prompt, user_message, **kw):
        return await self.chat(agent, system_prompt, user_message, tier="remote", **kw)

    async def json_local(self, agent, system_prompt, user_message, **kw):
        return await self.chat_json(agent, system_prompt, user_message, tier="local", **kw)

    async def json_remote(self, agent, system_prompt, user_message, **kw):
        return await self.chat_json(agent, system_prompt, user_message, tier="remote", **kw)

    async def embed(self, text: str):
        if self.remote:
            return await self.remote.embed(text)
        return None

    # ── Cost tracking (combined) ──

    def get_cost_breakdown(self) -> dict:
        out = self.remote.get_cost_breakdown() if self.remote else {"_total": {"tokens": 0, "calls": 0, "cost_usd": 0}}
        out["_local"] = {
            "tokens": self.local.total_tokens,
            "calls": self.local.total_calls,
            "cost_usd": 0.0,
        }
        return out

    def reset_cost_tracking(self):
        if self.remote:
            self.remote.reset_cost_tracking()
        self.local.total_tokens = 0
        self.local.total_calls = 0

    @property
    def total_tokens_used(self) -> int:
        # Compat shim for v2 code
        return (self.remote.total_tokens if self.remote else 0) + self.local.total_tokens

    async def close(self):
        await self.local.close()
        if self.remote:
            await self.remote.close()


# Backward-compat alias so old `from llm.client import LLMClient` still works
LLMClient = LLMRouter
