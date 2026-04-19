"""Unit tests for lobster.utils.prompt_budget."""
from __future__ import annotations

from lobster.utils.prompt_budget import compact_json, join_sections, truncate_chars


def test_truncate_chars_under_limit_returns_unchanged():
    assert truncate_chars("hello", 10) == "hello"


def test_truncate_chars_over_limit_adds_ellipsis():
    out = truncate_chars("a" * 100, 10)
    assert len(out) == 10
    assert out.endswith("…")


def test_truncate_chars_handles_none_and_empty():
    assert truncate_chars(None, 10) == ""
    assert truncate_chars("", 10) == ""


def test_truncate_chars_zero_or_negative_limit_noop():
    # A non-positive limit should pass the text through unchanged — callers
    # opt out of trimming by passing 0.
    assert truncate_chars("hello", 0) == "hello"
    assert truncate_chars("hello", -5) == "hello"


def test_compact_json_has_no_padding():
    payload = {"id": "c1", "gaps": ["a", "b"]}
    out = compact_json(payload)
    assert out == '{"id":"c1","gaps":["a","b"]}'


def test_compact_json_preserves_unicode():
    assert compact_json({"msg": "龍蝦"}) == '{"msg":"龍蝦"}'


def test_join_sections_skips_empty():
    joined = join_sections(["a", "", None, "  ", "b"])
    assert joined == "a\n\n---\n\nb"


def test_join_sections_custom_separator():
    assert join_sections(["a", "b"], sep=" | ") == "a | b"
