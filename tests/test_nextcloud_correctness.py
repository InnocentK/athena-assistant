"""
tests/test_nextcloud_correctness.py — M26.15 Nextcloud/XML correctness.

Covers: DASL search body escaping (a query containing XML-special characters
no longer silently degrades to the local-filter fallback), the shared app
logger, and hardened XML parsing (defusedxml — a server response defining XML
entities is rejected instead of expanded, in both the Nextcloud and CardDAV
clients).

Self-contained: mocked requests; no network.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest


@pytest.fixture
def nc_client(monkeypatch):
    monkeypatch.setenv("NEXTCLOUD_URL", "https://cloud.example.com")
    monkeypatch.setenv("NEXTCLOUD_USERNAME", "alice")
    monkeypatch.setenv("NEXTCLOUD_PASSWORD", "secret")
    from nextcloud_integration.client import NextcloudClient

    return NextcloudClient()


EMPTY_MULTISTATUS = b'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:"></d:multistatus>'

ENTITY_BOMB = (
    b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lolololol">]>'
    b'<d:multistatus xmlns:d="DAV:"><d:response><d:href>&lol;</d:href>'
    b"</d:response></d:multistatus>"
)


class _Resp:
    def __init__(self, status_code=207, content=EMPTY_MULTISTATUS):
        self.status_code = status_code
        self.content = content
        self.text = content.decode("utf-8", errors="replace")

    @property
    def ok(self):
        return self.status_code < 400


def test_search_body_escapes_xml_special_chars(nc_client, monkeypatch):
    """A query with &, <, > produces a well-formed, escaped DASL body and the
    SEARCH result is used (no silent fallback to list_files)."""
    import nextcloud_integration.client as ncmod

    captured: dict = {}

    def _fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["body"] = kwargs.get("data", b"")
        return _Resp(207)

    monkeypatch.setattr(ncmod.requests, "request", _fake_request)

    def _fallback_must_not_run(*a, **k):  # pragma: no cover - failure path
        raise AssertionError("fell back to list_files — SEARCH body was malformed")

    monkeypatch.setattr(nc_client, "list_files", _fallback_must_not_run)

    results = nc_client.search_files("a&b <evil>")

    assert results == []
    body = captured["body"].decode("utf-8")
    assert "a&amp;b &lt;evil&gt;" in body
    assert "%a&amp;b &lt;evil&gt;%" in body  # LIKE wildcards survive escaping
    ET.fromstring(body)  # body must be well-formed XML


def test_nextcloud_uses_shared_logger():
    """M26.15: records must flow through Athena's handler/formatter."""
    import core.logger as cl
    import nextcloud_integration.client as ncmod

    assert ncmod.logger is cl.logger


def test_nextcloud_rejects_entity_defining_xml(nc_client, monkeypatch):
    """A (compromised) server response defining XML entities is rejected by
    defusedxml instead of being expanded."""
    import nextcloud_integration.client as ncmod

    monkeypatch.setattr(
        ncmod.requests, "request", lambda *a, **k: _Resp(207, ENTITY_BOMB)
    )

    from nextcloud_integration.client import NextcloudConnectionError

    with pytest.raises(NextcloudConnectionError):
        nc_client.list_files("/")


def test_carddav_rejects_entity_defining_xml(monkeypatch, tmp_path):
    monkeypatch.setenv("CARDDAV_URL", "https://dav.example.com")
    monkeypatch.setenv("CARDDAV_USERNAME", "u@example.com")
    monkeypatch.setenv("CARDDAV_PASSWORD", "secret")

    import carddav_integration.client as cmod

    client = cmod.CardDAVClient()
    client._staged_dir = tmp_path

    monkeypatch.setattr(
        cmod.requests, "request", lambda *a, **k: _Resp(207, ENTITY_BOMB)
    )

    with pytest.raises(cmod.CardDAVConnectionError):
        client.list_address_books()
