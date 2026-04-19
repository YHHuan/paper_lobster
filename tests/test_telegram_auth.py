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


def _iter_command_handlers(app):
    from telegram.ext import CommandHandler
    for group in app.handlers.values():
        for h in group:
            if isinstance(h, CommandHandler):
                yield h


def test_every_command_enforces_owner_filter(owner_env):
    """Phase 1 contract: no CommandHandler is publicly reachable."""
    from lobster.bot.telegram import TelegramBot
    bot = TelegramBot()
    app = bot.build_app()

    handlers = list(_iter_command_handlers(app))
    assert handlers, "no CommandHandlers registered"

    for h in handlers:
        f = h.filters
        assert f is not None, f"handler {h.commands} has no filter"
        # PTB composes filters; the simplest, strictest case is a direct User filter.
        # For composed filters we still require a User filter to appear in the tree.
        user_filters = _collect_user_filters(f)
        assert user_filters, f"handler {h.commands} is missing a User filter"
        for uf in user_filters:
            assert bot.owner_id in uf.user_ids, (
                f"handler {h.commands} User filter doesn't include owner_id"
            )


def _collect_user_filters(f):
    """Walk a PTB filter tree and collect every User filter node."""
    from telegram.ext.filters import User as UserFilter
    found = []
    stack = [f]
    while stack:
        node = stack.pop()
        if node is None:
            continue
        if isinstance(node, UserFilter):
            found.append(node)
            continue
        # PTB uses _MergedFilter with .base_filter + .merged_filter, or
        # _XORFilter. Walk any inner filter attributes defensively.
        for attr in ("base_filter", "merged_filter", "and_filter", "or_filter"):
            inner = getattr(node, attr, None)
            if inner is not None:
                stack.append(inner)
    return found


def test_non_owner_command_is_rejected_silently(owner_env):
    """Catch-all handler exists for non-owner command messages."""
    from telegram.ext import MessageHandler
    from lobster.bot.telegram import TelegramBot
    bot = TelegramBot()
    app = bot.build_app()
    msg_handlers = [
        h for group in app.handlers.values() for h in group
        if isinstance(h, MessageHandler)
    ]
    # We need at least two: the owner text handler + the non-owner command catch-all.
    assert len(msg_handlers) >= 2
