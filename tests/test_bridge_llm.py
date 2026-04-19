"""Interface-parity checks for the LobsterLLM wrapper.

Phase 0: pin the stable surface (chat / chat_json / close / cost tracking).
Phase 2 extends this file with `.local` / `.remote` tier-client assertions
once those properties are added.
"""
from __future__ import annotations

import asyncio

from lobster.bridge.llm import LobsterLLM


def test_lobster_llm_exposes_core_methods():
    llm = LobsterLLM()
    for name in (
        "chat", "chat_json",
        "chat_local", "chat_remote",
        "json_local", "json_remote",
        "inject_db", "load_active_model_from_db",
        "get_cost_breakdown", "reset_cost_tracking",
        "close",
    ):
        assert hasattr(llm, name), f"LobsterLLM missing required attr: {name}"


def test_lobster_llm_close_is_awaitable():
    llm = LobsterLLM()
    asyncio.run(llm.close())
