"""Tests for the remote model name resolver.

We want `set_active_model` to accept all of: friendly name, full
provider id, and bare-id-minus-prefix, because the YAML config +
Telegram `/model` command + DB-persisted value each use different
conventions and we don't want to hard-code the mapping in three places.
"""
from __future__ import annotations

import os

import pytest

from lobster.llm.remote_client import (
    AVAILABLE_MODELS,
    RemoteLLMClient,
    _resolve_model_name,
)


def test_resolve_friendly_name():
    assert _resolve_model_name("sonnet") == "sonnet"


def test_resolve_full_provider_id():
    assert _resolve_model_name("anthropic/claude-sonnet-4-5") == "sonnet"


def test_resolve_bare_id_without_prefix():
    assert _resolve_model_name("claude-sonnet-4-5") == "sonnet"


def test_resolve_unknown_returns_none():
    assert _resolve_model_name("totally-made-up-model") is None


def test_resolve_empty_string_returns_none():
    assert _resolve_model_name("") is None


def test_available_models_has_expected_friendly_names():
    # If this set shrinks, callers will start seeing set_active_model → False,
    # so surface the regression with a clear assertion instead.
    for name in ("sonnet", "opus", "gemini-2.5", "gemini-3", "gemini-3.1"):
        assert name in AVAILABLE_MODELS


def test_set_active_model_accepts_provider_id(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-key-for-test")
    client = RemoteLLMClient()
    try:
        assert client.set_active_model("claude-sonnet-4-5") is True
        assert client.active_model_name == "sonnet"
        assert client.set_active_model("not-a-real-model") is False
    finally:
        # close() is async, but the sync client isn't started so this is a noop
        try:
            import asyncio
            asyncio.run(client.close())
        except Exception:
            pass


def test_remote_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from lobster.llm.remote_client import RemoteLLMError
    with pytest.raises(RemoteLLMError):
        RemoteLLMClient()


# Sanity: pytest shouldn't accidentally leak a live OPENROUTER_API_KEY
# from the developer's environment into failures. This just documents
# intent, it doesn't enforce anything.
_ = os
