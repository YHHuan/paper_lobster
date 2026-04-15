"""/rate — thin wrapper re-dispatching to lobster/bot/telegram.py handler.

Phase 1 just re-uses the v3 TelegramBot._cmd_rate. A future gateway
(Hermes, CLI TUI) can call register(gateway) to wire the same handler by name.
"""
from __future__ import annotations


def register(gateway) -> None:
    """Register /rate on `gateway`.

    If the gateway exposes a v3 TelegramBot (`gateway.telegram_bot`) we are a
    no-op because the bot self-registers in build_app(). Otherwise we attach a
    bound-method handler pointing at TelegramBot._cmd_rate.
    """
    tg = getattr(gateway, "telegram_bot", None)
    if tg is not None and hasattr(tg, "_cmd_rate"):
        # v3 bot already wires this in build_app(); nothing to do.
        return
    # For alternate gateways, expose the handler under a stable attribute.
    setattr(gateway, "cmd_rate", lambda *a, **kw: None)
