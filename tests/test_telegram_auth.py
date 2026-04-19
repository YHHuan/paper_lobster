"""Auth / owner-filter checks for the Telegram bot.

Phase 0: pin down the baseline — owner_id is resolved correctly from env
(supports both canonical names) and build_app() wires a message filter.
Phase 1 extends this file to assert every CommandHandler enforces the same
filter.

Skips entirely if python-telegram-bot isn't installed in the environment.
"""
from __future__ import annotations

import pytest

pytest.importorskip("telegram")


@pytest.fixture
def owner_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234:test-token")
    monkeypatch.setenv("ALLOWED_USER_ID", "424242")
    monkeypatch.delenv("TELEGRAM_USER_ID", raising=False)


def test_telegram_bot_reads_owner_id_from_allowed_user_id(owner_env):
    from lobster.bot.telegram import TelegramBot
    bot = TelegramBot()
    assert bot.owner_id == 424242


def test_telegram_user_id_overrides_allowed_user_id(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234:test-token")
    monkeypatch.setenv("ALLOWED_USER_ID", "111")
    monkeypatch.setenv("TELEGRAM_USER_ID", "222")
    from lobster.bot.telegram import TelegramBot
    bot = TelegramBot()
    assert bot.owner_id == 222


def test_build_app_registers_commands(owner_env):
    from lobster.bot.telegram import TelegramBot
    from telegram.ext import CommandHandler
    bot = TelegramBot()
    app = bot.build_app()
    cmd_handlers = [
        h for group in app.handlers.values() for h in group
        if isinstance(h, CommandHandler)
    ]
    assert cmd_handlers, "expected at least one CommandHandler"
    for h in cmd_handlers:
        assert hasattr(h, "filters")
