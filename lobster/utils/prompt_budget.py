"""Small helpers for keeping prompt sizes predictable.

The Connect digester was sending every cluster at full size plus
indented JSON, which blows through the remote token budget once there
are 30+ clusters. These helpers give callers a cheap way to trim text
fields and pack JSON without changing the wire format.
"""

from __future__ import annotations

import json
from typing import Any, Iterable


def truncate_chars(text: str | None, limit: int) -> str:
    """Trim ``text`` to at most ``limit`` chars, appending an ellipsis."""
    if not text:
        return ""
    text = str(text)
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(limit - 1, 1)].rstrip() + "…"


def compact_json(value: Any) -> str:
    """Dump JSON without padding — saves ~30% vs indent=2 for big payloads."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def join_sections(sections: Iterable[str | None], sep: str = "\n\n---\n\n") -> str:
    """Join non-empty sections with ``sep``."""
    parts = [s.strip() for s in sections if s and str(s).strip()]
    return sep.join(parts)
