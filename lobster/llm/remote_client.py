"""Remote LLM client via OpenRouter.

Used for high-quality reasoning: Connect (digest layer) and high-quality Write.
Supports runtime model switching (sonnet / gemini-2.5 / gemini-3 / gemini-3.1).
"""

import os
import json
import logging
import asyncio
from collections import defaultdict

import httpx

logger = logging.getLogger("lobster.llm.remote")

OPENROUTER_API = "https://openrouter.ai/api/v1"

# Friendly name → OpenRouter model id
AVAILABLE_MODELS: dict[str, str] = {
    "sonnet":     "anthropic/claude-sonnet-4-5",
    "opus":       "anthropic/claude-opus-4-5",
    "gemini-2.5": os.environ.get("GEMINI_25_MODEL", "google/gemini-2.5-pro-preview"),
    "gemini-3":   os.environ.get("GEMINI_3_MODEL",  "google/gemini-3"),
    "gemini-3.1": os.environ.get("GEMINI_31_MODEL", "google/gemini-3.1"),
}

DEFAULT_MODEL = "sonnet"

# USD per 1M tokens (rough — for client-side budget tracking)
TOKEN_COST_PER_M: dict[str, float] = {
    "anthropic/claude-sonnet-4-5":   9.0,
    "anthropic/claude-opus-4-5":     45.0,
    "google/gemini-2.5-pro-preview": 3.5,
    "google/gemini-3":               3.5,
    "google/gemini-3.1":             3.5,
    "mistralai/mistral-embed-2312":  0.1,
}


class RemoteLLMError(Exception):
    pass


class RemoteLLMClient:
    def __init__(self):
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RemoteLLMError("OPENROUTER_API_KEY not set")

        self._client = httpx.AsyncClient(
            base_url=OPENROUTER_API,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=120.0,
        )

        self._active_model_name: str = DEFAULT_MODEL
        self._db = None  # injected for persistence

        self.total_tokens = 0
        self._agent_tokens: dict[str, int] = defaultdict(int)
        self._agent_calls: dict[str, int] = defaultdict(int)
        self._agent_cost: dict[str, float] = defaultdict(float)

    def inject_db(self, db):
        self._db = db

    # ── Model switching ──

    @property
    def active_model_name(self) -> str:
        return self._active_model_name

    def set_active_model(self, name: str) -> bool:
        if name not in AVAILABLE_MODELS:
            return False
        self._active_model_name = name
        logger.info(f"remote model switched → {name} ({AVAILABLE_MODELS[name]})")
        return True

    def get_model_info(self) -> dict:
        return {
            "name": self._active_model_name,
            "model_id": AVAILABLE_MODELS[self._active_model_name],
            "provider": "openrouter",
        }

    @staticmethod
    def list_models() -> list[dict]:
        return [{"name": n, "model_id": m} for n, m in AVAILABLE_MODELS.items()]

    async def load_active_model_from_db(self):
        if not self._db:
            return
        try:
            saved = await self._db.get_identity_state("active_model")
            if saved and saved in AVAILABLE_MODELS:
                self._active_model_name = saved
                logger.info(f"restored remote model from DB: {saved}")
        except Exception as e:
            logger.warning(f"could not restore active model: {e}")

    async def save_active_model_to_db(self):
        if not self._db:
            return
        try:
            await self._db.update_identity_state(
                "active_model", self._active_model_name, "user"
            )
        except Exception as e:
            logger.warning(f"could not save active model: {e}")

    # ── Chat ──

    async def chat(
        self,
        agent: str,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 2048,
        json_mode: bool = False,
        max_retries: int = 2,
        model_override: str | None = None,
    ) -> str:
        model_name = model_override or self._active_model_name
        model = AVAILABLE_MODELS.get(model_name, AVAILABLE_MODELS[DEFAULT_MODEL])

        body: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        last_err = None
        for attempt in range(max_retries + 1):
            try:
                resp = await self._client.post("/chat/completions", json=body)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                last_err = e
                logger.warning(f"[remote/{agent}] HTTP {e.response.status_code} attempt {attempt + 1}")
                if e.response.status_code in (429, 529):
                    await asyncio.sleep(2 ** attempt)
                continue
            except (httpx.RequestError, json.JSONDecodeError) as e:
                last_err = e
                logger.warning(f"[remote/{agent}] {type(e).__name__}: {e}")
                continue

            usage = data.get("usage") or {}
            tokens = usage.get("total_tokens") or (
                usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
            )
            self.total_tokens += tokens
            self._agent_tokens[agent] += tokens
            self._agent_calls[agent] += 1
            cost_per_m = TOKEN_COST_PER_M.get(model, 1.0)
            self._agent_cost[agent] += tokens * cost_per_m / 1_000_000

            choices = data.get("choices") or []
            if not choices:
                last_err = RemoteLLMError(f"empty choices: {json.dumps(data)[:300]}")
                continue
            content = (choices[0].get("message") or {}).get("content")
            if content is None:
                last_err = RemoteLLMError(f"null content: {json.dumps(data)[:300]}")
                continue
            return content

        raise last_err or RemoteLLMError(f"remote chat failed for {agent}")

    async def chat_json(self, agent: str, system_prompt: str, user_message: str, max_tokens: int = 2048) -> dict | list:
        text = await self.chat(agent, system_prompt, user_message, max_tokens=max_tokens, json_mode=True)
        text = (text or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3].strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            lo, hi = text.find("{"), text.rfind("}")
            if lo != -1 and hi > lo:
                try:
                    return json.loads(text[lo : hi + 1])
                except Exception:
                    pass
            lo, hi = text.find("["), text.rfind("]")
            if lo != -1 and hi > lo:
                try:
                    return json.loads(text[lo : hi + 1])
                except Exception:
                    pass
            logger.warning(f"[remote/{agent}] failed to parse JSON: {text[:200]}")
            return {}

    async def embed(self, text: str) -> list[float] | None:
        embed_model = "mistralai/mistral-embed-2312"
        try:
            resp = await self._client.post(
                "/embeddings",
                json={"model": embed_model, "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage") or {}
            tokens = usage.get("total_tokens", 0)
            self.total_tokens += tokens
            self._agent_tokens["embedding"] += tokens
            self._agent_calls["embedding"] += 1
            cost_per_m = TOKEN_COST_PER_M.get(embed_model, 0.1)
            self._agent_cost["embedding"] += tokens * cost_per_m / 1_000_000
            return data["data"][0]["embedding"]
        except Exception as e:
            logger.warning(f"embed failed: {e}")
            return None

    def get_cost_breakdown(self) -> dict:
        total_cost = sum(self._agent_cost.values())
        out = {}
        for agent in sorted(self._agent_tokens.keys()):
            out[agent] = {
                "tokens": self._agent_tokens[agent],
                "calls": self._agent_calls[agent],
                "cost_usd": round(self._agent_cost[agent], 4),
                "pct": round(self._agent_cost[agent] / total_cost * 100, 1) if total_cost else 0,
            }
        out["_total"] = {
            "tokens": self.total_tokens,
            "calls": sum(self._agent_calls.values()),
            "cost_usd": round(total_cost, 4),
        }
        return out

    def reset_cost_tracking(self):
        self._agent_tokens.clear()
        self._agent_calls.clear()
        self._agent_cost.clear()
        self.total_tokens = 0

    async def close(self):
        await self._client.aclose()
