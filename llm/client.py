"""LLM client for Lobster v2.5.

Supports two providers:
- OpenRouter (Claude Sonnet, Gemini 2.5/3/3.1 via Google)
- Local OpenAI-compatible endpoint (gpt-oss-120b or any local model)

Active model can be switched at runtime via /model command and persists to DB.
"""

import os
import json
import logging
import httpx
from collections import defaultdict

logger = logging.getLogger("lobster.llm")

# Friendly name → (provider, model_id)
# "openrouter" uses OPENROUTER_API_KEY
# "local" uses OPENAI_BASE_URL + OPENAI_API_KEY
AVAILABLE_MODELS: dict[str, tuple[str, str]] = {
    "sonnet":       ("openrouter", "anthropic/claude-sonnet-4-5"),
    "gemini-2.5":   ("openrouter", os.environ.get("GEMINI_25_MODEL", "google/gemini-2.5-pro-preview")),
    "gemini-3":     ("openrouter", os.environ.get("GEMINI_3_MODEL",  "google/gemini-3")),
    "gemini-3.1":   ("openrouter", os.environ.get("GEMINI_31_MODEL", "google/gemini-3.1")),
    "local":        ("local",      os.environ.get("LLM_MODEL", "gpt-oss-120b")),
}

DEFAULT_MODEL = "sonnet"

# Cost per 1M tokens (USD) — used for client-side tracking
TOKEN_COST_PER_M: dict[str, float] = {
    "anthropic/claude-sonnet-4-5": 9.0,
    "google/gemini-2.5-pro-preview": 3.5,
    "google/gemini-3": 3.5,
    "google/gemini-3.1": 3.5,
    "mistralai/mistral-embed-2312": 0.1,
}

OPENROUTER_API = "https://openrouter.ai/api/v1"


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self):
        self._active_model_name: str = DEFAULT_MODEL
        self._db = None  # injected later for persistence

        # OpenRouter client
        self._or_client = httpx.AsyncClient(
            base_url=OPENROUTER_API,
            headers={
                "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                "Content-Type": "application/json",
            },
            timeout=120.0,
        )

        # Local OpenAI-compatible client (optional)
        local_base = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
        local_key = os.environ.get("OPENAI_API_KEY", "none")
        self._local_client: httpx.AsyncClient | None = None
        if local_base:
            self._local_client = httpx.AsyncClient(
                base_url=local_base,
                headers={
                    "Authorization": f"Bearer {local_key}",
                    "Content-Type": "application/json",
                },
                timeout=180.0,
            )
            logger.info(f"Local LLM client configured: {local_base}")

        # Token tracking (resets between heartbeats)
        self.total_tokens_used = 0
        self._agent_tokens: dict[str, int] = defaultdict(int)
        self._agent_calls: dict[str, int] = defaultdict(int)
        self._agent_cost: dict[str, float] = defaultdict(float)

    def inject_db(self, db):
        """Inject DB reference after initialization for model persistence."""
        self._db = db

    # ── Model switching ──

    @property
    def active_model_name(self) -> str:
        return self._active_model_name

    def set_active_model(self, name: str) -> bool:
        """Switch active model. Returns True if valid."""
        if name not in AVAILABLE_MODELS:
            return False
        self._active_model_name = name
        logger.info(f"Active model switched to: {name} → {AVAILABLE_MODELS[name]}")
        return True

    def get_model_info(self) -> dict:
        """Return current model info."""
        provider, model_id = AVAILABLE_MODELS[self._active_model_name]
        return {
            "name": self._active_model_name,
            "provider": provider,
            "model_id": model_id,
        }

    @staticmethod
    def list_models() -> list[dict]:
        return [
            {"name": name, "provider": p, "model_id": mid}
            for name, (p, mid) in AVAILABLE_MODELS.items()
        ]

    async def load_active_model_from_db(self):
        """Restore last-used model from DB on startup."""
        if not self._db:
            return
        try:
            saved = await self._db.get_identity_state("active_model")
            if saved and saved in AVAILABLE_MODELS:
                self._active_model_name = saved
                logger.info(f"Restored active model from DB: {saved}")
        except Exception as e:
            logger.warning(f"Could not restore active model from DB: {e}")

    async def save_active_model_to_db(self):
        """Persist current model choice to DB."""
        if not self._db:
            return
        try:
            await self._db.update_identity_state(
                "active_model", self._active_model_name, "user"
            )
        except Exception as e:
            logger.warning(f"Could not save active model to DB: {e}")

    # ── Core chat ──

    def _get_client_and_model(self) -> tuple[httpx.AsyncClient, str]:
        provider, model_id = AVAILABLE_MODELS[self._active_model_name]
        if provider == "local":
            if not self._local_client:
                raise LLMError("Local client not configured (OPENAI_BASE_URL missing)")
            return self._local_client, model_id
        return self._or_client, model_id

    async def chat(
        self,
        agent: str,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 1024,
        max_retries: int = 1,
        json_mode: bool = False,
    ) -> str:
        client, model = self._get_client_and_model()
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
                resp = await client.post("/chat/completions", json=body)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(f"[{agent}/{self._active_model_name}] HTTP {e.response.status_code} (attempt {attempt + 1})")
                if e.response.status_code in (429, 529):
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
                continue
            except (httpx.RequestError, json.JSONDecodeError) as e:
                last_error = e
                logger.warning(f"[{agent}/{self._active_model_name}] Request error: {e} (attempt {attempt + 1})")
                continue

            # Track usage
            usage = data.get("usage", {})
            tokens = (
                usage.get("total_tokens")
                or (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0))
            )
            self.total_tokens_used += tokens
            self._agent_tokens[agent] += tokens
            self._agent_calls[agent] += 1
            cost_per_m = TOKEN_COST_PER_M.get(model, 1.0)
            self._agent_cost[agent] += tokens * cost_per_m / 1_000_000

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

        raise last_error or LLMError(
            f"LLM call failed for {agent} ({self._active_model_name}) after {max_retries + 1} attempts"
        )

    async def chat_json(self, agent: str, system_prompt: str, user_message: str) -> dict:
        text = await self.chat(agent, system_prompt, user_message, json_mode=True)
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
            logger.warning(f"[{agent}] Failed to parse JSON: {text[:200]}")
            return {}

    async def embed(self, text: str) -> list[float] | None:
        """Generate embedding via OpenRouter (always uses OpenRouter regardless of active model)."""
        embed_model = "mistralai/mistral-embed-2312"
        try:
            resp = await self._or_client.post(
                "/embeddings",
                json={"model": embed_model, "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage", {})
            tokens = usage.get("total_tokens", 0)
            self.total_tokens_used += tokens
            self._agent_tokens["embedding"] += tokens
            self._agent_calls["embedding"] += 1
            cost_per_m = TOKEN_COST_PER_M.get(embed_model, 0.1)
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
        await self._or_client.aclose()
        if self._local_client:
            await self._local_client.aclose()
