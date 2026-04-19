"""Tests for identity_loader mode switching.

`mode="chat"` is the short profile the Telegram bot uses per reply.
It must (a) be strictly smaller than `mode="full"` and (b) drop the
memory block so a multi-kilobyte memory note doesn't get re-sent
every turn.
"""
from __future__ import annotations

import asyncio

from lobster.utils import identity_loader


class _FakeDB:
    def __init__(self, states: dict[str, str]):
        self._states = states

    async def get_identity_state(self, key: str):
        return self._states.get(key)


def _load_sync(db, **kw):
    return asyncio.run(identity_loader.load_identity(db, **kw))


def test_chat_mode_drops_memory_section():
    # Memory section should not leak into chat mode, even when it's present
    # in the DB. Use a distinctive marker so an accidental inclusion is obvious.
    marker = "MEMORY_MARKER_" + ("x" * 500)
    db = _FakeDB({"curiosity": "short curiosity note", "memory": marker})

    chat = _load_sync(db, mode="chat")
    full = _load_sync(db, mode="full")

    assert marker not in chat
    assert marker in full


def test_chat_mode_caps_curiosity_block():
    db = _FakeDB({"curiosity": "x" * 5000, "memory": ""})
    chat = _load_sync(db, mode="chat")
    full = _load_sync(db, mode="full")
    # Chat should be strictly shorter than full.
    assert len(chat) < len(full)


def test_default_mode_is_full():
    db = _FakeDB({"curiosity": "c", "memory": "m"})
    default = _load_sync(db)
    full = _load_sync(db, mode="full")
    assert default == full
