"""
tests/test_concurrency.py — Concurrency hardening tests (Milestone 26.5).

Proves that the synchronous provider/DAV work in the async handlers no longer
blocks the event loop, and that the wrapped routing paths have a bounded
request time (an intentional M26.5 behaviour change) that degrades cleanly on
timeout instead of hanging or 500ing.

Design:
  - No pytest-asyncio dependency: each test drives the ASGI app through
    ``httpx.AsyncClient`` inside a private ``asyncio.run(...)`` coroutine.
  - No real providers/network: the module-level ``_router`` / ``_memory``
    globals on the freshly-imported ``main`` are replaced with test doubles.
  - The app is imported fresh against the conftest ``tmp_project`` tree, exactly
    like the ``client`` fixture, but we set the manager globals ourselves rather
    than running the lifespan (the endpoints read those globals directly).
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import httpx
import pytest


# ---------------------------------------------------------------------------
# App fixture — fresh import against tmp_project, manager globals set by hand
# ---------------------------------------------------------------------------


@pytest.fixture
def app_module(tmp_project: Path, monkeypatch: pytest.MonkeyPatch):
    """Import ``main`` fresh against the tmp project and return the module."""
    monkeypatch.chdir(tmp_project)
    monkeypatch.setenv("ACTIVE_PROFILE", "athena")
    monkeypatch.setenv("APP_ENV", "test")

    for mod in ("main", "core.config", "core.loader", "core.logger",
                "providers.router", "memory.manager"):
        sys.modules.pop(mod, None)

    import core.config as cc  # noqa: PLC0415

    monkeypatch.setattr(cc, "APP_ROOT", tmp_project)
    cc.get_settings.cache_clear()

    import main as app_module  # noqa: PLC0415

    # Minimal profile so /chat has a system prompt and routing block.
    app_module._profile_data = {
        "system_prompt": "test",
        "routing": {"mode": "balanced", "preferred_provider": None},
    }
    yield app_module

    cc.get_settings.cache_clear()
    for mod in list(sys.modules.keys()):
        if mod == "main" or mod.startswith("main."):
            sys.modules.pop(mod, None)


def _run(app, coro_factory):
    """Run *coro_factory(client)* against *app* via an ASGI AsyncClient."""
    async def _driver():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            return await coro_factory(ac)

    return asyncio.run(_driver())


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _SleepyResponse:
    def __init__(self, content: str, success: bool = True) -> None:
        self.content = content
        self.provider_name = "fake"
        self.model = "fake-1"
        self.success = success
        self.error = None
        self.metadata: dict = {}


class _SleepyRouter:
    """route() blocks for `delay` seconds (in a thread, via the handler)."""

    def __init__(self, delay: float) -> None:
        self.delay = delay

    def route(self, messages, system_prompt, profile_config):
        time.sleep(self.delay)
        return _SleepyResponse("slow answer")

    def list_providers(self):
        time.sleep(self.delay)
        return [{"name": "fake", "enabled": True, "available": True,
                 "cost_tier": "low", "type": "api"}]


# ---------------------------------------------------------------------------
# 1. The core proof: a slow /chat does NOT block /health
# ---------------------------------------------------------------------------


def test_slow_chat_does_not_block_health(app_module):
    app_module._router = _SleepyRouter(delay=1.0)
    app_module._memory = None

    async def _scenario(ac: httpx.AsyncClient):
        # Kick off the slow chat, then time an immediate /health.
        chat_task = asyncio.create_task(
            ac.post("/chat", json={"message": "hi"})
        )
        await asyncio.sleep(0.05)  # let the chat reach route() in its thread
        t0 = time.perf_counter()
        health = await ac.get("/health")
        health_elapsed = time.perf_counter() - t0
        chat = await chat_task
        return health, health_elapsed, chat

    health, health_elapsed, chat = _run(app_module.app, _scenario)

    assert health.status_code == 200
    # If the loop were blocked by route()'s sleep, /health would take ~1s.
    assert health_elapsed < 0.5, f"/health blocked for {health_elapsed:.2f}s"
    assert chat.status_code == 200
    assert chat.json()["response"] == "slow answer"


# ---------------------------------------------------------------------------
# 2. Forced route timeout → clean success=False (no hang, no 500)
# ---------------------------------------------------------------------------


def test_route_timeout_returns_clean_failure(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "_ROUTE_TIMEOUT", 0.2)
    app_module._router = _SleepyRouter(delay=1.0)  # 1.0s > 0.2s cap
    app_module._memory = None

    async def _scenario(ac):
        return await ac.post("/chat", json={"message": "hi"})

    resp = _run(app_module.app, _scenario)

    assert resp.status_code == 200          # not a 500
    body = resp.json()
    assert body["success"] is False
    assert "timed out" in body["response"].lower()
    assert body["diagnostics"] is None


# ---------------------------------------------------------------------------
# 3. auto_extract timeout is non-fatal — the answer still returns
# ---------------------------------------------------------------------------


def test_auto_extract_timeout_is_non_fatal(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "_AUTO_EXTRACT_TIMEOUT", 0.2)
    app_module._router = _SleepyRouter(delay=0.0)

    class _HangingMemory:
        def auto_extract(self, user, assistant):
            time.sleep(1.0)  # > 0.2s cap

    app_module._memory = _HangingMemory()

    async def _scenario(ac):
        return await ac.post("/chat", json={"message": "hi"})

    resp = _run(app_module.app, _scenario)

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True          # answer survived the memory hang
    assert body["response"] == "slow answer"


# ---------------------------------------------------------------------------
# 4. /providers timeout → 503 (not 500)
# ---------------------------------------------------------------------------


def test_providers_timeout_returns_503(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "_PROVIDERS_TIMEOUT", 0.2)
    app_module._router = _SleepyRouter(delay=1.0)

    async def _scenario(ac):
        return await ac.get("/providers")

    resp = _run(app_module.app, _scenario)

    assert resp.status_code == 503
    assert "timed out" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 5. DAV endpoints run off-loop too — a slow CalDAV read does not block /health,
#    and a read past its timeout returns 504 (representative of all wrapped
#    CalDAV/CardDAV/Nextcloud endpoints).
# ---------------------------------------------------------------------------


class _SleepyCalDAV:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    def list_calendars(self):
        time.sleep(self.delay)
        return [{"name": "Cal", "url": "u", "color": None, "description": ""}]


def test_slow_dav_read_does_not_block_health(app_module):
    app_module._caldav = _SleepyCalDAV(delay=1.0)

    async def _scenario(ac):
        task = asyncio.create_task(ac.get("/caldav/calendars"))
        await asyncio.sleep(0.05)
        t0 = time.perf_counter()
        health = await ac.get("/health")
        elapsed = time.perf_counter() - t0
        dav = await task
        return health, elapsed, dav

    health, elapsed, dav = _run(app_module.app, _scenario)

    assert health.status_code == 200
    assert elapsed < 0.5, f"/health blocked for {elapsed:.2f}s during a DAV read"
    assert dav.status_code == 200


def test_dav_read_timeout_returns_504(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "_DAV_READ_TIMEOUT", 0.2)
    app_module._caldav = _SleepyCalDAV(delay=1.0)

    async def _scenario(ac):
        return await ac.get("/caldav/calendars")

    resp = _run(app_module.app, _scenario)

    assert resp.status_code == 504
    assert "did not respond" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 6. M26.14 — heavy LOCAL file I/O runs off-loop too: a slow /files/search
#    does not block /health (representative of the files_read / backup
#    create/list/inspect/diff offloads added in the same milestone).
# ---------------------------------------------------------------------------


class _SleepyFiles:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    def search_files(self, *a, **k):
        time.sleep(self.delay)
        return ["data/found.txt"]


def test_slow_files_search_does_not_block_health(app_module):
    app_module._files = _SleepyFiles(delay=1.0)

    async def _scenario(ac):
        task = asyncio.create_task(
            ac.post("/files/search", json={"pattern": "*.txt"})
        )
        await asyncio.sleep(0.05)
        t0 = time.perf_counter()
        health = await ac.get("/health")
        elapsed = time.perf_counter() - t0
        search = await task
        return health, elapsed, search

    health, elapsed, search = _run(app_module.app, _scenario)

    assert health.status_code == 200
    assert elapsed < 0.5, f"/health blocked for {elapsed:.2f}s during files search"
    assert search.status_code == 200
    assert search.json() == ["data/found.txt"]
