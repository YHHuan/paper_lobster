"""Local OpenAI-compatible LLM client (gpt-oss-b or any local endpoint).

Used for cheap, high-volume tasks: Reflect, Hypothesize, Extract, Synthesize,
Evolve, query generation, hook check, AI-smell check.
"""

import os
import json
import logging
import asyncio
import httpx

logger = logging.getLogger("lobster.llm.local")


class LocalLLMError(Exception):
    pass


class LocalLLMClient:
    """OpenAI-compatible local client. Free to call (you host it)."""

    def __init__(self):
        base = os.environ.get("LOCAL_LLM_BASE_URL", "").rstrip("/")
        if not base:
            # Fall back to OPENAI_BASE_URL for backward compat with v2
            base = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
        self.base_url = base
        self.model = os.environ.get("LOCAL_LLM_MODEL") or os.environ.get("LLM_MODEL", "gpt-oss-b")
        self.max_tokens_default = int(os.environ.get("LOCAL_LLM_MAX_TOKENS", "4096"))

        self._client: httpx.AsyncClient | None = None
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
        for attempt in range(max_retries + 1):
            try:
                resp = await self._client.post("/chat/completions", json=body)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                last_err = e
                logger.warning(f"[local/{agent}] HTTP {e.response.status_code} attempt {attempt + 1}")
                if e.response.status_code in (429, 503, 529):
                    await asyncio.sleep(2 ** attempt)
                continue
            except (httpx.RequestError, json.JSONDecodeError) as e:
                last_err = e
                logger.warning(f"[local/{agent}] {type(e).__name__}: {e}")
                continue

            usage = data.get("usage") or {}
            self.total_tokens += usage.get("total_tokens", 0)
            self.total_calls += 1

            choices = data.get("choices") or []
            if not choices:
                last_err = LocalLLMError(f"empty choices: {json.dumps(data)[:300]}")
                continue
            content = (choices[0].get("message") or {}).get("content")
            if content is None:
                last_err = LocalLLMError(f"null content: {json.dumps(data)[:300]}")
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
            l, r = text.find("{"), text.rfind("}")
            if l != -1 and r > l:
                try:
                    return json.loads(text[l : r + 1])
                except Exception:
                    pass
            l, r = text.find("["), text.rfind("]")
            if l != -1 and r > l:
                try:
                    return json.loads(text[l : r + 1])
                except Exception:
                    pass
            logger.warning(f"[local/{agent}] failed to parse JSON: {text[:200]}")
            return {}

    async def close(self):
        if self._client:
            await self._client.aclose()
