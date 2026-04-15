"""Thin command wrappers. Phase 1 re-dispatches to lobster/bot/telegram.py
handlers. Each submodule exports `register(gateway)`.

During phase 1 the Telegram bot registers its own handlers in build_app(), so
these wrappers are primarily here so `lobster.commands.<name>` imports work
and future gateways (Hermes, CLI TUI) can register the same handlers by name.
"""
from __future__ import annotations

from importlib import import_module

_NAMES = [
    "menu", "status", "questions", "inject", "explore", "knowledge",
    "digest", "evolve", "stats", "pause", "resume", "rate", "track",
]


def register_all(gateway) -> None:
    for n in _NAMES:
        try:
            mod = import_module(f"lobster.commands.{n}")
            if hasattr(mod, "register"):
                mod.register(gateway)
        except Exception as e:  # pragma: no cover
            import logging
            logging.getLogger("lobster.commands").warning(
                f"register({n}) failed: {e}"
            )
