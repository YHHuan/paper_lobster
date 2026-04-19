"""Local OpenAI-compatible LLM client.

Used for cheap, high-volume tasks: Reflect, Hypothesize, Extract, Synthesize,
Evolve, query generation, hook check, AI-smell check.
"""

import os
import json
import logging
import asyncio
import httpx

logger = logging.getLogger("lobster.llm.local")

DEFAULT_LOCAL_MODEL = "nemotron-super-1m"


class LocalLLMError(Exception):
    pass


class LocalLLMClient:
    """OpenAI-compatible local client. Free to call (you host it).

    Config resolution (highest priority first):
      base_url    LOCAL_LLM_BASE_URL > OPENAI_BASE_URL > base_url kwarg > ""
      model       LOCAL_LLM_MODEL > LLM_MODEL > model kwarg > DEFAULT_LOCAL_MODEL
      max_tokens  LOCAL_LLM_MAX_TOKENS > max_tokens_default kwarg > 4096

    The kwargs are where LLMRouter passes YAML-derived defaults.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        max_tokens_default: int | None = None,
    ):
        env_base = (
            os.environ.get("LOCAL_LLM_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
        )
        self.base_url = (env_base or base_url or "").rstrip("/")
        self.model = (
            os.environ.get("LOCAL_LLM_MODEL")
            or os.environ.get("LLM_MODEL")
            or model
            or DEFAULT_LOCAL_MODEL
        )
        env_mt = os.environ.get("LOCAL_LLM_MAX_TOKENS")
        if env_mt:
            self.max_tokens_default = int(env_mt)
        elif max_tokens_default is not None:
            self.max_tokens_default = int(max_tokens_default)
        else:
            self.max_tokens_default = 4096

        self._client: httpx.AsyncClient | None = None
        self._remote_models: list[str] | None = None  # cached from /models

        if self.base_url:
            key = os.environ.get("LOCAL_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY", "none")
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                timeout=180.0,
            )
            logger.info(f"Local LLM ready: {self.base_url} ({self.model})")
        else:
            logger.warning("LOCAL_LLM_BASE_URL not set — local tier will fail")

        # Token tracking — local tokens are free but useful for budget gates
        self.total_tokens = 0
        self.total_calls = 0

    @property
    def available(self) -> bool:
        return self._client is not None

    # ── Model discovery & switching ──

    async def fetch_models(self) -> list[str]:
        """Query the /models endpoint and return list of model IDs."""
        if not self._client:
            return []
        try:
            resp = await self._client.get("/models")
            resp.raise_for_status()
            data = resp.json()
            models = [m["id"] for m in data.get("data", [])]
            self._remote_models = models
            logger.info(f"Local endpoint models: {models}")
            if models and self.model not in models:
                preferred = ["gpt-oss-120b", "gemma4-31b", "gemma4-26b"]
                fallback = next((p for p in preferred if p in models), models[0])
                logger.warning(
                    f"Configured model {self.model!r} not served by endpoint; "
                    f"switching to {fallback!r}"
                )
                self.model = fallback
            return models
        except Exception as e:
            logger.warning(f"Failed to fetch local models: {e}")
            return self._remote_models or []

    def get_cached_models(self) -> list[str]:
        """Return previously fetched model list (no network call)."""
        return self._remote_models or []

    def set_model(self, model_id: str) -> bool:
        """Switch active local model. Returns True if accepted."""
        # Accept any model — the endpoint will reject invalid ones at call time
        old = self.model
        self.model = model_id
        logger.info(f"Local model switched: {old} → {model_id}")
        return True

    async def chat(
        self,
        agent: str,
        system_prompt: str,
        user_message: str,
        max_tokens: int | None = None,
        json_mode: bool = False,
        max_retries: int = 1,
    ) -> str:
        if not self._client:
            raise LocalLLMError("Local LLM not configured (LOCAL_LLM_BASE_URL missing)")

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": max_tokens or self.max_tokens_default,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        last_err = None
        # Reasoning models can blow through max_tokens during thinking → null
        # content + finish=length. We bump and retry *without* counting it as a
        # normal retry. LOCAL_LLM_MAX_TOKENS_CAP puts a hard ceiling, and
        # bump_attempts caps how many times we'll double within one call.
        cap = int(os.environ.get("LOCAL_LLM_MAX_TOKENS_CAP", "12288"))
        bump_attempts = 0
        attempt = 0
        while attempt <= max_retries:
            try:
                resp = await self._client.post("/chat/completions", json=body)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                last_err = e
                logger.warning(f"[local/{agent}] HTTP {e.response.status_code} attempt {attempt + 1}")
                if e.response.status_code in (429, 503, 529):
                    await asyncio.sleep(2 ** attempt)
                attempt += 1
                continue
            except (httpx.RequestError, json.JSONDecodeError) as e:
                last_err = e
                logger.warning(f"[local/{agent}] {type(e).__name__}: {e}")
                attempt += 1
                continue

            usage = data.get("usage") or {}
            self.total_tokens += usage.get("total_tokens", 0)
            self.total_calls += 1

            choices = data.get("choices") or []
            if not choices:
                last_err = LocalLLMError(f"empty choices: {json.dumps(data)[:300]}")
                attempt += 1
                continue
            message = choices[0].get("message") or {}
            content = message.get("content")
            finish_reason = choices[0].get("finish_reason")
            if content is None:
                current_cap = body.get("max_tokens") or self.max_tokens_default
                if finish_reason == "length" and current_cap < cap and bump_attempts < 4:
                    new_cap = min(current_cap * 2, cap)
                    logger.warning(
                        f"[local/{agent}] null content + finish=length at "
                        f"max_tokens={current_cap}; bumping to {new_cap}"
                    )
                    body["max_tokens"] = new_cap
                    bump_attempts += 1
                    last_err = LocalLLMError(
                        f"null content @ {current_cap} tokens "
                        f"(reasoning={bool(message.get('reasoning_content'))})"
                    )
                    continue
                last_err = LocalLLMError(f"null content: {json.dumps(data)[:300]}")
                attempt += 1
                continue
            return content

        raise last_err or LocalLLMError(f"local chat failed for {agent}")

    async def chat_json(self, agent: str, system_prompt: str, user_message: str, max_tokens: int | None = None) -> dict | list:
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
            # Try extracting between first { and last }
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
            logger.warning(f"[local/{agent}] failed to parse JSON: {text[:200]}")
            return {}

    async def close(self):
        if self._client:
            await self._client.aclose()
