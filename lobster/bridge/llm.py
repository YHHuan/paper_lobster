"""Lobster v4 LLM bridge.

LobsterLLM is the default LLM entry point for v4. It wraps the existing v3
LLMRouter (local + remote tiers) and — when LOBSTER_USE_HERMES=1 — optionally
routes through hermes's smart_model_routing. If hermes isn't importable we
silently stay on the v3 router. The v3 router is the debug escape hatch.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("lobster.bridge.llm")

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "lobster.yaml"


def _load_cfg() -> dict:
    try:
        return yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _use_hermes() -> bool:
    return os.environ.get("LOBSTER_USE_HERMES", "").strip() in {"1", "true", "yes"}


class LobsterLLM:
    """Thin wrapper over v3 LLMRouter with optional hermes routing.

    Exposes the same surface v3 callers expect (chat, chat_json, inject_db,
    load_active_model_from_db, active_model_name, set_active_model, ...).
    """

    def __init__(self, db=None):
        cfg = _load_cfg().get("llm", {})
        self.default_local_model = cfg.get("default_local_model", "gemma-4")
        self.connect_remote_model = cfg.get("connect_remote_model")
        self._db = db
        self._hermes_router = None

        # Always initialise the v3 router as the safe base.
        from lobster.llm.router import LLMRouter
        self._fallback = LLMRouter()

        if _use_hermes():
            try:
                # TODO hermes-native: hermes smart_model_routing expects a rich
                # model-metadata context we don't have here. Import-only for now.
                from agent import smart_model_routing  # noqa: F401
                self._hermes_router = smart_model_routing
                logger.info("LobsterLLM: hermes smart_model_routing available (import-only).")
            except Exception as e:
                logger.info(f"LobsterLLM: hermes route unavailable ({e}); using v3 router.")

    # ── DB-backed cached model selection (keep v3 persistence) ──
    def inject_db(self, db):
        self._db = db
        self._fallback.inject_db(db)

    async def load_active_model_from_db(self):
        await self._fallback.load_active_model_from_db()

    async def refresh_local_models(self):
        return await self._fallback.refresh_local_models()

    @property
    def active_model_name(self) -> str:
        return self._fallback.active_model_name

    def set_active_model(self, name: str) -> bool:
        return self._fallback.set_active_model(name)

    def get_model_info(self) -> dict:
        return self._fallback.get_model_info()

    def list_models(self) -> list[dict]:
        return self._fallback.list_models()

    # ── Chat surface ──
    async def chat(self, agent, system_prompt, user_message, tier="local", **kw):
        # Hermes path is TODO; always delegate to v3 router for now.
        return await self._fallback.chat(agent, system_prompt, user_message, tier=tier, **kw)

    async def chat_json(self, agent, system_prompt, user_message, tier="local", **kw):
        return await self._fallback.chat_json(agent, system_prompt, user_message, tier=tier, **kw)

    async def chat_local(self, *a, **kw):
        return await self._fallback.chat_local(*a, **kw)

    async def chat_remote(self, *a, **kw):
        return await self._fallback.chat_remote(*a, **kw)

    async def json_local(self, *a, **kw):
        return await self._fallback.json_local(*a, **kw)

    async def json_remote(self, *a, **kw):
        return await self._fallback.json_remote(*a, **kw)

    async def embed(self, text: str):
        return await self._fallback.embed(text)

    def get_cost_breakdown(self) -> dict:
        return self._fallback.get_cost_breakdown()

    def reset_cost_tracking(self):
        self._fallback.reset_cost_tracking()

    @property
    def total_tokens_used(self) -> int:
        return self._fallback.total_tokens_used

    async def close(self):
        await self._fallback.close()
