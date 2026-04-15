"""Lobster v4 memory bridge.

Two jobs:
  1. MemoryBridge — unified read/append/note_rating that evolve.py and the
     telegram bot can call. Mode is picked from config memory.mode.
  2. migrate_identity_to_hermes() — one-shot copier from lobster/identity/*.md
     into hermes's MemoryManager format with a timestamped backup.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import shutil
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("lobster.bridge.memory")

_ROOT = Path(__file__).parent.parent
_IDENTITY_DIR = _ROOT / "identity"
_CONFIG_PATH = _ROOT / "config" / "lobster.yaml"
_BACKUP_ROOT = _ROOT.parent / "data"


def _cfg() -> dict:
    try:
        return yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _mode() -> str:
    return (_cfg().get("memory", {}) or {}).get("mode", "lobster")


def _use_hermes() -> bool:
    return os.environ.get("LOBSTER_USE_HERMES", "").strip() in {"1", "true", "yes"}


class MemoryBridge:
    """Unified memory surface during the v3 → hermes migration.

    read():    returns concatenated identity md (lobster) — or hermes context if configured.
    append():  appends to memory.md (lobster); optionally also hermes.
    note_rating(): records a user rating event (delegates to DB if available).
    """

    def __init__(self, db=None):
        self.db = db
        self.mode = _mode()
        self._hermes = None
        if _use_hermes() and self.mode in {"hermes", "both"}:
            try:
                from agent.memory_manager import MemoryManager  # noqa: F401
                # TODO hermes-native: we don't yet know the construction args
                # expected by MemoryManager + BuiltinMemoryProvider in v4
                # context. Instantiate lazily in later phase.
                self._hermes = None
            except Exception as e:
                logger.info(f"Hermes memory unavailable ({e}); staying on lobster mode.")

    # ── Reads ──
    def read(self, which: str | None = None) -> str:
        """Return current identity/memory content. `which` is a filename stem
        like 'soul' / 'memory' / 'style' / 'curiosity'. None = concat all."""
        if which:
            p = _IDENTITY_DIR / f"{which}.md"
            return p.read_text(encoding="utf-8") if p.exists() else ""
        parts = []
        for p in sorted(_IDENTITY_DIR.glob("*.md")):
            parts.append(f"# {p.stem}\n\n{p.read_text(encoding='utf-8')}")
        return "\n\n".join(parts)

    # ── Writes ──
    def append(self, which: str, text: str) -> None:
        p = _IDENTITY_DIR / f"{which}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write("\n" + text.rstrip() + "\n")
        if self.mode == "both" and self._hermes is not None:
            # TODO hermes-native: write-through to hermes MemoryManager
            pass

    async def note_rating(self, item_id: str, score: int, note: str = "") -> None:
        if self.db:
            try:
                await self.db._insert("ratings", {
                    "item_id": item_id,
                    "score": int(score),
                    "note": note,
                    "created_at": _dt.datetime.utcnow().isoformat(),
                })
                return
            except Exception as e:
                logger.warning(f"note_rating DB write failed ({e}); falling back to file")
        self.append("memory", f"[rating] {item_id}={score} {note}")


def migrate_identity_to_hermes() -> None:
    """One-shot: copy lobster/identity/*.md into hermes MemoryManager store.

    Before writing anything, we create a timestamped backup of the source md
    files under data/migration_backup_<ts>/. Safe to run repeatedly."""
    ts = _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    backup = _BACKUP_ROOT / f"migration_backup_{ts}"
    backup.mkdir(parents=True, exist_ok=True)
    copied = []
    for md in sorted(_IDENTITY_DIR.glob("*.md")):
        shutil.copy2(md, backup / md.name)
        copied.append(md.name)

    print(f"[migrate-memory] Backed up {len(copied)} files → {backup}")
    for n in copied:
        print(f"  - {n}")

    if not _use_hermes():
        print("[migrate-memory] LOBSTER_USE_HERMES not set; skipping hermes write.")
        print("[migrate-memory] Re-run with LOBSTER_USE_HERMES=1 once hermes is installed.")
        return

    try:
        # TODO hermes-native: instantiate BuiltinMemoryProvider with a store
        # directory and call the provider's write path to import each md
        # under a stable key ('identity.soul', etc.).
        from agent.memory_manager import MemoryManager  # noqa: F401
        print("[migrate-memory] Hermes MemoryManager importable; actual import still TODO.")
        print("[migrate-memory] See MIGRATION_TODO.md 'full hermes memory integration'.")
    except Exception as e:
        print(f"[migrate-memory] Could not import hermes memory manager: {e}")
