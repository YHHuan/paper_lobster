"""Config resolution tests for LocalLLMClient.

Priority: env > YAML-passed kwarg > code default. The router reads YAML once
and passes the results as kwargs, so as long as the client respects kwargs
when env is absent, `lobster.yaml` takes effect.
"""
from __future__ import annotations

import pytest

from lobster.llm.local_client import DEFAULT_LOCAL_MODEL, LocalLLMClient


@pytest.fixture
def clean_env(monkeypatch):
    for key in (
        "LOCAL_LLM_BASE_URL", "OPENAI_BASE_URL",
        "LOCAL_LLM_MODEL", "LLM_MODEL",
        "LOCAL_LLM_MAX_TOKENS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_kwargs_apply_when_env_missing(clean_env):
    c = LocalLLMClient(
        base_url="http://yaml-host:1234/v1",
        model="yaml-model",
        max_tokens_default=2048,
    )
    assert c.base_url == "http://yaml-host:1234/v1"
    assert c.model == "yaml-model"
    assert c.max_tokens_default == 2048


def test_env_overrides_kwargs(monkeypatch, clean_env):
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://env-host:9/v1")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "env-model")
    monkeypatch.setenv("LOCAL_LLM_MAX_TOKENS", "8192")
    c = LocalLLMClient(
        base_url="http://yaml-host:1234/v1",
        model="yaml-model",
        max_tokens_default=2048,
    )
    assert c.base_url == "http://env-host:9/v1"
    assert c.model == "env-model"
    assert c.max_tokens_default == 8192


def test_defaults_when_nothing_provided(clean_env):
    c = LocalLLMClient()
    assert c.base_url == ""
    assert c.model == DEFAULT_LOCAL_MODEL
    assert c.max_tokens_default == 4096


def test_router_loads_yaml(clean_env):
    """LLMRouter should pick up the packaged lobster.yaml defaults."""
    from lobster.llm.router import LLMRouter
    r = LLMRouter()
    # lobster/config/lobster.yaml ships default_local_model: "gemma-4" and
    # local_endpoint: "http://localhost:1234/v1".
    assert r.local.base_url == "http://localhost:1234/v1"
    assert r.local.model == "gemma-4"
