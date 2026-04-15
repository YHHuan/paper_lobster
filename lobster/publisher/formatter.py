"""Text formatting utilities for posts."""

import re


def clean_draft(text: str) -> str:
    """Clean a draft: strip markdown, normalize whitespace."""
    text = text.strip()
    # Strip markdown headers
    text = re.sub(r'^#+\s*\d*\.?\s*.*$', '', text, flags=re.MULTILINE).strip()
    # Strip bold markdown
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    # Strip section labels
    text = re.sub(r'^.*版[（(]\d+字[)）]：?\s*', '', text, flags=re.MULTILINE).strip()
    # Collapse multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text


def truncate_for_telegram(text: str, max_len: int = 4096) -> str:
    """Truncate text for Telegram's message limit."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."
