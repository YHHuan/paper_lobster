"""Interface-parity checks for the LobsterLLM wrapper.

Covers the chat surface, the tier clients (.local / .remote) that
CuriosityLoop and the Telegram bot read directly, and the token-snapshot
helper that lets callers do bookkeeping without touching tier internals.
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


def test_lobster_llm_exposes_tier_clients():
    # CuriosityLoop / evolve.py / telegram `/model` all read self.llm.local
    # and self.llm.remote directly. The wrapper must forward to the
    # underlying router.
    llm = LobsterLLM()
    assert hasattr(llm, "local"), "LobsterLLM must expose .local"
    assert hasattr(llm, "remote"), "LobsterLLM must expose .remote"


def test_token_snapshot_api():
    llm = LobsterLLM()
    snap = llm.get_token_snapshot()
    assert set(snap.keys()) == {"local", "remote"}
    assert all(isinstance(v, int) for v in snap.values())

    diff = llm.diff_token_snapshot(snap)
    assert diff == {"local": 0, "remote": 0}


def test_lobster_llm_close_is_awaitable():
    llm = LobsterLLM()
    asyncio.run(llm.close())
