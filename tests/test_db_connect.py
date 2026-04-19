"""Database.connect() strict-mode behaviour tests.

Use a stub AsyncClient so we can force the health check to succeed or
fail without hitting Supabase.
"""
from __future__ import annotations

import asyncio

import pytest

from lobster.db import client as db_client


class _FakeResponse:
    def __init__(self, status: int = 200):
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"http {self.status}")


class _FakeClient:
    def __init__(self, *_args, healthy: bool = True, **_kwargs):
        self.healthy = healthy

    async def get(self, *_a, **_kw):
        return _FakeResponse(200 if self.healthy else 500)

    async def aclose(self):
        pass


@pytest.fixture
def supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "fake-anon-key")
    monkeypatch.delenv("ALLOW_DB_DEGRADED", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)


def _patch_httpx(monkeypatch, healthy: bool):
    def factory(*a, **kw):
        return _FakeClient(*a, healthy=healthy, **kw)
    monkeypatch.setattr(db_client.httpx, "AsyncClient", factory)


def test_strict_mode_raises_on_health_failure(monkeypatch, supabase_env):
    _patch_httpx(monkeypatch, healthy=False)
    db = db_client.Database()
    with pytest.raises(RuntimeError, match="DB health check failed"):
        asyncio.run(db.connect())


def test_strict_mode_passes_when_healthy(monkeypatch, supabase_env):
    _patch_httpx(monkeypatch, healthy=True)
    db = db_client.Database()
    asyncio.run(db.connect())
    asyncio.run(db.close())


def test_degraded_env_allows_failing_health_check(monkeypatch, supabase_env):
    monkeypatch.setenv("ALLOW_DB_DEGRADED", "1")
    _patch_httpx(monkeypatch, healthy=False)
    db = db_client.Database()
    # Should not raise — gateway/CLI can limp along in dev with bad creds.
    asyncio.run(db.connect())


def test_explicit_strict_false_overrides_env(monkeypatch, supabase_env):
    _patch_httpx(monkeypatch, healthy=False)
    db = db_client.Database()
    asyncio.run(db.connect(strict=False))


def test_explicit_strict_true_overrides_degraded_env(monkeypatch, supabase_env):
    monkeypatch.setenv("ALLOW_DB_DEGRADED", "1")
    _patch_httpx(monkeypatch, healthy=False)
    db = db_client.Database()
    with pytest.raises(RuntimeError):
        asyncio.run(db.connect(strict=True))
