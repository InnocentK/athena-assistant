"""
tests/test_dav_transport.py — M26.12 transport-timeout invariants for DAV clients.

Every outbound CardDAV HTTP call must flow through CardDAVClient._request and
carry an explicit socket timeout; CalDAV must construct caldav.DAVClient with a
timeout. asyncio.wait_for bounds the *route*, not the worker thread — without a
transport timeout a hung server pins a to_thread executor slot forever.

Self-contained: mocked requests / fake caldav module; no network.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def carddav_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """CardDAVClient backed by env vars and a tmp staging dir (no network)."""
    monkeypatch.setenv("CARDDAV_URL", "https://dav.example.com")
    monkeypatch.setenv("CARDDAV_USERNAME", "user@example.com")
    monkeypatch.setenv("CARDDAV_PASSWORD", "secret")

    from carddav_integration.client import CardDAVClient

    client = CardDAVClient()
    client._staged_dir = tmp_path / "data" / "carddav_staged"
    client._staged_dir.mkdir(parents=True)
    return client


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "") -> None:
        self.status_code = status_code
        self.text = text

    @property
    def ok(self) -> bool:
        return self.status_code < 400


# ---------------------------------------------------------------------------
# CardDAV: _request timeout + check semantics
# ---------------------------------------------------------------------------


def test_carddav_request_sets_default_timeout(carddav_client, monkeypatch):
    """_request always sends an explicit socket timeout by default."""
    import carddav_integration.client as cmod

    captured: dict = {}

    def _fake_request(method, url, **kwargs):
        captured.update(kwargs, method=method, url=url)
        return _FakeResponse(200)

    monkeypatch.setattr(cmod.requests, "request", _fake_request)
    carddav_client._request("GET", "https://dav.example.com/x")

    assert captured["timeout"] == cmod._HTTP_TIMEOUT
    assert captured["timeout"] > 0


def test_carddav_request_caller_can_override_timeout(carddav_client, monkeypatch):
    """An explicit caller timeout wins over the default (setdefault semantics)."""
    import carddav_integration.client as cmod

    captured: dict = {}

    def _fake_request(method, url, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(200)

    monkeypatch.setattr(cmod.requests, "request", _fake_request)
    carddav_client._request("GET", "https://dav.example.com/x", timeout=3)

    assert captured["timeout"] == 3


def test_carddav_request_check_false_returns_non_2xx(carddav_client, monkeypatch):
    """check=False hands the non-2xx response back instead of raising."""
    import carddav_integration.client as cmod

    monkeypatch.setattr(
        cmod.requests, "request", lambda *a, **k: _FakeResponse(500, "boom")
    )

    resp = carddav_client._request("GET", "https://dav.example.com/x", check=False)
    assert resp.status_code == 500

    with pytest.raises(cmod.CardDAVConnectionError):
        carddav_client._request("GET", "https://dav.example.com/x")


def test_carddav_request_network_error_still_raises_with_check_false(
    carddav_client, monkeypatch
):
    """Network-level failures raise CardDAVConnectionError regardless of check."""
    import carddav_integration.client as cmod

    def _boom(*a, **k):
        raise cmod.requests.ConnectionError("refused")

    monkeypatch.setattr(cmod.requests, "request", _boom)

    with pytest.raises(cmod.CardDAVConnectionError):
        carddav_client._request("GET", "https://dav.example.com/x", check=False)


def test_carddav_delete_contact_flows_through_request_with_timeout(
    carddav_client, monkeypatch
):
    """delete_contact uses the _request chokepoint (timeout applied) and keeps
    its status semantics: 204 → True, 404 → CardDAVConnectionError."""
    import carddav_integration.client as cmod

    captured: dict = {}

    def _fake_request(method, url, **kwargs):
        captured.update(kwargs, method=method, url=url)
        return _FakeResponse(204)

    monkeypatch.setattr(cmod.requests, "request", _fake_request)
    assert carddav_client.delete_contact(
        "https://dav.example.com/book", "/book/x.vcf"
    ) is True
    assert captured["method"] == "DELETE"
    assert captured["timeout"] == cmod._HTTP_TIMEOUT

    monkeypatch.setattr(
        cmod.requests, "request", lambda *a, **k: _FakeResponse(404)
    )
    with pytest.raises(cmod.CardDAVConnectionError):
        carddav_client.delete_contact("https://dav.example.com/book", "/book/x.vcf")


def test_carddav_no_raw_requests_outside_chokepoint():
    """Source invariant: requests.request appears exactly once in the module —
    inside _request — so the timeout (and future URL guards) can't be bypassed."""
    import inspect

    import carddav_integration.client as cmod

    source = inspect.getsource(cmod)
    assert source.count("requests.request(") == 1


# ---------------------------------------------------------------------------
# CalDAV: DAVClient constructed with a timeout
# ---------------------------------------------------------------------------


def test_caldav_connect_passes_timeout(monkeypatch):
    """_connect constructs caldav.DAVClient with an explicit timeout."""
    monkeypatch.setenv("CALDAV_URL", "https://dav.example.com")
    monkeypatch.setenv("CALDAV_USERNAME", "user@example.com")
    monkeypatch.setenv("CALDAV_PASSWORD", "secret")

    import caldav_integration.client as cc

    captured: dict = {}

    class _FakeDAVClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def principal(self):
            return object()

    fake_mod = types.ModuleType("caldav")
    fake_mod.DAVClient = _FakeDAVClient
    monkeypatch.setitem(sys.modules, "caldav", fake_mod)

    client = cc.CalDAVClient()
    client._connect()

    assert captured["timeout"] == cc._CONNECT_TIMEOUT
    assert captured["timeout"] > 0
