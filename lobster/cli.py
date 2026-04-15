"""Lobster v4 CLI.

Three modes:
  lobster                # interactive prompt (delegates to hermes if available)
  lobster gateway        # start message gateway (Telegram + Email)
  lobster loop           # start curiosity loop worker
  lobster migrate-memory # one-shot: copy identity/ into hermes MemoryManager format

Railway layout (see Procfile):
  web    -> lobster gateway
  worker -> lobster loop
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

logger = logging.getLogger("lobster.cli")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _cmd_gateway(_args) -> int:
    from lobster.bridge.gateway import run_gateway_sync
    run_gateway_sync()
    return 0


def _cmd_loop(_args) -> int:
    from lobster.brain.curiosity_loop import CuriosityLoop  # noqa: F401
    from lobster.scheduler.heartbeat import run_forever
    asyncio.run(run_forever())
    return 0


def _cmd_migrate_memory(_args) -> int:
    from lobster.bridge.memory import migrate_identity_to_hermes
    migrate_identity_to_hermes()
    return 0


def _cmd_chat(_args) -> int:
    # Placeholder interactive entrypoint. Real hermes TUI takes over once wired.
    print("lobster v4 — interactive chat not yet wired to hermes TUI.")
    print("For now use:  lobster gateway   (to chat via Telegram)")
    return 0


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    parser = argparse.ArgumentParser(prog="lobster", description="Lobster v4 research agent")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("gateway", help="Start the Telegram + Email gateway")
    sub.add_parser("loop", help="Start the curiosity loop worker")
    sub.add_parser("migrate-memory", help="One-shot: migrate identity/ into hermes memory")
    sub.add_parser("chat", help="Interactive chat (placeholder)")

    args = parser.parse_args(argv)
    cmd = args.cmd or "chat"
    handlers = {
        "gateway": _cmd_gateway,
        "loop": _cmd_loop,
        "migrate-memory": _cmd_migrate_memory,
        "chat": _cmd_chat,
    }
    return handlers[cmd](args)


if __name__ == "__main__":
    sys.exit(main())
