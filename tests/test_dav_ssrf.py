"""
tests/test_dav_ssrf.py — M26.13 same-origin guard for caller-supplied DAV URLs.

The CalDAV/CardDAV endpoints accept full URLs and attach the configured
Basic-Auth credentials to the request. A crafted URL must never point those
credentials at another host (SSRF / credential exfiltration). Guard:
core.urlguard.ensure_same_origin — enforced in CardDAVClient._request (the
single chokepoint), CalDAV client methods, the import flows, and surfaced as
HTTP 400 via an app-level DAVSecurityError handler.

Self-contained: mocked requests; no network.
"""

from __future__ import annotations

import pytest

from core.urlguard import DAVSecurityError, ensure_same_origin

BASE = "https://dav.example.com/dav"


# ---------------------------------------------------------------------------
# Unit matrix: ensure_same_origin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://dav.example.com/dav/addressbooks/user/",
        "https://dav.example.com:443/other/path",   # default-port equivalence
        "https://DAV.EXAMPLE.COM/case",             # host is case-insensitive
        "/relative/href.vcf",                        # relative — joined on base
        "relative.vcf",
    ],
)
def test_same_origin_allowed(url):
    ensure_same_origin(url, BASE, "CardDAV")  # must not raise


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/dav",              # different host
        "http://dav.example.com/dav",                # different scheme (→ port)
        "https://dav.example.com:8443/dav",          # different port
        "https://dav.example.com@evil.example/x",    # userinfo trick
        "//evil.example/dav",                        # scheme-relative
        "http://169.254.169.254/latest/meta-data/",  # metadata service
        "https://dav.example.com:notaport/x",        # unparseable port
    ],
)
def test_cross_origin_rejected(url):
    with pytest.raises(DAVSecurityError):
        ensure_same_origin(url, BASE, "CardDAV")


# ---------------------------------------------------------------------------
# CardDAV: the _request chokepoint refuses off-origin URLs before any I/O
# ---------------------------------------------------------------------------


@pytest.fixture
def carddav_client(tmp_path, monkeypatch):
    monkeypatch.setenv("CARDDAV_URL", "https://dav.example.com")
    monkeypatch.setenv("CARDDAV_USERNAME", "user@example.com")
    monkeypatch.setenv("CARDDAV_PASSWORD", "secret")
    from carddav_integration.client import CardDAVClient

    client = CardDAVClient()
    client._staged_dir = tmp_path / "staged"
    client._staged_dir.mkdir(parents=True)
    return client


def test_carddav_request_rejects_off_origin_without_network(
    carddav_client, monkeypatch
):
    import carddav_integration.client as cmod

    def _must_not_be_called(*a, **k):  # pragma: no cover - failure path
        raise AssertionError("network I/O attempted for an off-origin URL")

    monkeypatch.setattr(cmod.requests, "request", _must_not_be_called)

    with pytest.raises(DAVSecurityError):
        carddav_client._request("GET", "https://attacker.example/steal")


def test_carddav_request_allows_configured_origin(carddav_client, monkeypatch):
    import carddav_integration.client as cmod

    class _Resp:
        status_code, text, ok = 200, "", True

    monkeypatch.setattr(cmod.requests, "request", lambda *a, **k: _Resp())
    carddav_client._request("GET", "https://dav.example.com/books/")  # no raise


def test_carddav_delete_contact_rejects_off_origin_href(carddav_client, monkeypatch):
    import carddav_integration.client as cmod

    def _must_not_be_called(*a, **k):  # pragma: no cover - failure path
        raise AssertionError("network I/O attempted for an off-origin href")

    monkeypatch.setattr(cmod.requests, "request", _must_not_be_called)

    with pytest.raises(DAVSecurityError):
        carddav_client.delete_contact(
            "https://dav.example.com/book", "https://attacker.example/x.vcf"
        )


# ---------------------------------------------------------------------------
# CalDAV: methods refuse off-origin calendar URLs before connecting
# ---------------------------------------------------------------------------


@pytest.fixture
def caldav_client(monkeypatch):
    monkeypatch.setenv("CALDAV_URL", "https://dav.example.com")
    monkeypatch.setenv("CALDAV_USERNAME", "user@example.com")
    monkeypatch.setenv("CALDAV_PASSWORD", "secret")
    from caldav_integration.client import CalDAVClient

    return CalDAVClient()


def test_caldav_list_events_rejects_off_origin(caldav_client):
    # Raised before _ensure_connected — no caldav library call happens, and the
    # broad except→CalDAVConnectionError wrappers never re-label the error.
    with pytest.raises(DAVSecurityError):
        caldav_client.list_events("https://attacker.example/cal")


def test_caldav_create_task_rejects_off_origin(caldav_client):
    with pytest.raises(DAVSecurityError):
        caldav_client.create_task("http://169.254.169.254/", summary="x")


# ---------------------------------------------------------------------------
# Import flows fail fast (they otherwise warn-and-continue)
# ---------------------------------------------------------------------------


def test_import_ics_rejects_off_origin(tmp_path):
    from unittest.mock import MagicMock

    from dav_io.ics_io import import_ics

    client = MagicMock()
    client._url = "https://dav.example.com"

    with pytest.raises(DAVSecurityError):
        import_ics("BEGIN:VCALENDAR", "https://attacker.example/cal", client, tmp_path)


def test_import_vcf_rejects_off_origin(tmp_path):
    from unittest.mock import MagicMock

    from dav_io.vcf_io import import_vcf

    client = MagicMock()
    client._url = "https://dav.example.com"

    with pytest.raises(DAVSecurityError):
        import_vcf(
            "BEGIN:VCARD\nVERSION:3.0\nFN:X\nEND:VCARD",
            "https://attacker.example/book",
            client,
            tmp_path,
        )


# ---------------------------------------------------------------------------
# API level: DAVSecurityError surfaces as HTTP 400 (not 5xx)
# ---------------------------------------------------------------------------


def test_api_caldav_events_off_origin_returns_400(client, monkeypatch):
    import main as app_module

    monkeypatch.setenv("CALDAV_URL", "https://dav.example.com")
    monkeypatch.setenv("CALDAV_USERNAME", "user@example.com")
    monkeypatch.setenv("CALDAV_PASSWORD", "secret")
    from caldav_integration.client import CalDAVClient

    monkeypatch.setattr(app_module, "_caldav", CalDAVClient())

    resp = client.get(
        "/caldav/events", params={"calendar_url": "https://attacker.example/cal"}
    )
    assert resp.status_code == 400
    assert "origin" in resp.json()["detail"]


def test_api_carddav_contacts_off_origin_returns_400(client, monkeypatch, tmp_path):
    import main as app_module

    monkeypatch.setenv("CARDDAV_URL", "https://dav.example.com")
    monkeypatch.setenv("CARDDAV_USERNAME", "user@example.com")
    monkeypatch.setenv("CARDDAV_PASSWORD", "secret")
    from carddav_integration.client import CardDAVClient

    c = CardDAVClient()
    c._staged_dir = tmp_path / "staged"
    monkeypatch.setattr(app_module, "_carddav", c)

    resp = client.get(
        "/carddav/contacts",
        params={"address_book_url": "http://169.254.169.254/latest/"},
    )
    assert resp.status_code == 400
    assert "origin" in resp.json()["detail"]
