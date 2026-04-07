"""OpenRouter API client for Lobster v2.5.

All agents use Sonnet via OpenRouter. Token tracking per agent type.
Adapted from v1 router.py with simplified agent mapping.
"""

import os
import json
import logging
import httpx
from collections import defaultdict

logger = logging.getLogger("lobster.llm")

MODELS = {
    "lobster": "anthropic/claude-sonnet-4-5",
    "mirror": "anthropic/claude-sonnet-4-5",
    "spawn": "anthropic/claude-sonnet-4-5",
    "embedding": "mistralai/mistral-embed-2312",
}

# Estimated cost per 1M tokens (USD)
TOKEN_COST_PER_M = {
    "anthropic/claude-sonnet-4-5": 9.0,
    "mistralai/mistral-embed-2312": 0.1,
}

OPENROUTER_API = "https://openrouter.ai/api/v1"


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self):
        self.api_key = os.environ["OPENROUTER_API_KEY"]
        self.client = httpx.AsyncClient(
            base_url=OPENROUTER_API,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=120.0,
        )
        self.total_tokens_used = 0
        self._agent_tokens: dict[str, int] = defaultdict(int)
        self._agent_calls: dict[str, int] = defaultdict(int)
        self._agent_cost: dict[str, float] = defaultdict(float)

    async def chat(
        self,
        agent: str,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 1024,
        max_retries: int = 1,
        json_mode: bool = False,
    ) -> str:
        model = MODELS.get(agent, MODELS["lobster"])
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        body: dict = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                resp = await self.client.post("/chat/completions", json=body)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(f"[{agent}] HTTP {e.response.status_code} (attempt {attempt + 1})")
                if e.response.status_code in (429, 529):
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
                continue
            except (httpx.RequestError, json.JSONDecodeError) as e:
                last_error = e
                logger.warning(f"[{agent}] Request error: {e} (attempt {attempt + 1})")
                continue

            # Track usage
            usage = data.get("usage", {})
            tokens = usage.get("total_tokens", 0)
            self.total_tokens_used += tokens
            self._agent_tokens[agent] += tokens
            self._agent_calls[agent] += 1
            cost_per_m = TOKEN_COST_PER_M.get(model, 1.0)
            self._agent_cost[agent] += tokens * cost_per_m / 1_000_000

            # Extract content
            choices = data.get("choices")
            if not choices or not isinstance(choices, list):
                logger.warning(f"[{agent}] No choices: {json.dumps(data)[:300]}")
                last_error = LLMError(f"No choices in API response for {agent}")
                continue

            content = choices[0].get("message", {}).get("content")
            if content is None:
                logger.warning(f"[{agent}] Null content: {json.dumps(data)[:300]}")
                last_error = LLMError(f"Null content in API response for {agent}")
                continue

            return content

        raise last_error or LLMError(f"LLM call failed for {agent} after {max_retries + 1} attempts")

    async def chat_json(self, agent: str, system_prompt: str, user_message: str) -> dict:
        text = await self.chat(agent, system_prompt, user_message, json_mode=True)
        text = (text or "").strip()
        # Strip markdown code fences
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3].strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"[{agent}] Failed to parse JSON: {text[:200]}")
            return {}

    async def embed(self, text: str) -> list[float] | None:
        """Generate embedding via OpenRouter."""
        try:
            resp = await self.client.post(
                "/embeddings",
                json={"model": MODELS["embedding"], "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage", {})
            tokens = usage.get("total_tokens", 0)
            self.total_tokens_used += tokens
            self._agent_tokens["embedding"] += tokens
            self._agent_calls["embedding"] += 1
            cost_per_m = TOKEN_COST_PER_M.get(MODELS["embedding"], 0.1)
            self._agent_cost["embedding"] += tokens * cost_per_m / 1_000_000
            return data["data"][0]["embedding"]
        except Exception:
            return None

    def get_cost_breakdown(self) -> dict:
        total_cost = sum(self._agent_cost.values())
        breakdown = {}
        for agent in sorted(self._agent_tokens.keys()):
            tokens = self._agent_tokens[agent]
            calls = self._agent_calls[agent]
            cost = self._agent_cost[agent]
            pct = (cost / total_cost * 100) if total_cost > 0 else 0
            breakdown[agent] = {
                "tokens": tokens,
                "calls": calls,
                "cost_usd": round(cost, 4),
                "pct": round(pct, 1),
            }
        breakdown["_total"] = {
            "tokens": self.total_tokens_used,
            "calls": sum(self._agent_calls.values()),
            "cost_usd": round(total_cost, 4),
        }
        return breakdown

    def reset_cost_tracking(self):
        self._agent_tokens.clear()
        self._agent_calls.clear()
        self._agent_cost.clear()
        self.total_tokens_used = 0

    async def close(self):
        await self.client.aclose()
