"""Lobster v4 gateway bridge.

Entry point for `lobster gateway`. Spins up message delivery on Telegram +
Email. When LOBSTER_USE_HERMES=1 is set we try to route through Hermes's
gateway; otherwise we fall back to the v3 TelegramBot + a thin aiosmtplib
email sender. The fallback path must always work even if hermes is missing.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger("lobster.bridge.gateway")

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "lobster.yaml"


def _load_config() -> dict:
    try:
        return yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.warning(f"Failed to read lobster.yaml: {e}")
        return {}


def _use_hermes() -> bool:
    return os.environ.get("LOBSTER_USE_HERMES", "").strip() in {"1", "true", "yes"}


async def _send_email(cfg: dict, subject: str, body: str) -> bool:
    """Thin aiosmtplib shim. TODO hermes-native: route via hermes email adapter."""
    host = os.environ.get("SMTP_HOST")
    if not host:
        logger.info("SMTP_HOST not set — email disabled")
        return False
    try:
        import aiosmtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["From"] = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", "lobster@local"))
        msg["To"] = cfg.get("gateway", {}).get("email", {}).get("to", "")
        msg["Subject"] = subject
        msg.set_content(body)
        await aiosmtplib.send(
            msg,
            hostname=host,
            port=int(os.environ.get("SMTP_PORT", "587")),
            username=os.environ.get("SMTP_USER"),
            password=os.environ.get("SMTP_PASS"),
            start_tls=True,
        )
        return True
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return False


def _run_lobster_fallback_sync() -> None:
    """Fallback path: run the existing v3 Telegram bot + scheduler on main thread.
    PTB's Application.run_webhook installs signal handlers so it MUST be on the
    main thread — do not wrap in asyncio.to_thread."""
    from lobster import _legacy_main
    _legacy_main.main()


def _run_hermes_gateway_sync(cfg: dict) -> None:
    """Attempt to start hermes-native gateway. If API surface is missing,
    fall back to the lobster v3 path so the bot is never offline."""
    try:
        import importlib
        importlib.import_module("gateway.run")  # smoke import
        logger.warning(
            "LOBSTER_USE_HERMES=1 set but hermes-native gateway wiring is a TODO. "
            "Falling back to v3 Telegram bot. See MIGRATION_TODO.md."
        )
    except Exception as e:
        logger.warning(f"Hermes gateway unavailable ({e}); using v3 fallback")
    _run_lobster_fallback_sync()


def run_gateway_sync() -> None:
    """Start message gateway (Telegram + Email). Main CLI entry. Runs on main
    thread — PTB owns its own event loop + signal handlers."""
    cfg = _load_config()
    logger.info(f"Gateway config: platforms={cfg.get('gateway', {}).get('platforms')} "
                f"hermes={_use_hermes()}")
    if _use_hermes():
        _run_hermes_gateway_sync(cfg)
    else:
        _run_lobster_fallback_sync()


# Convenience helper so other modules can push an email notification
async def send_email_notification(subject: str, body: str) -> bool:
    return await _send_email(_load_config(), subject, body)
