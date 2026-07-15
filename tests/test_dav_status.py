"""
tests/test_dav_status.py — Tests for dav_status/store.py and /status/* endpoints.

Unit tests use a fresh DavStatusStore instance (not the singleton) for isolation.
API tests use the shared `client` fixture from conftest.py.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Unit tests — DavStatusStore
# ---------------------------------------------------------------------------


@pytest.fixture
def store():
    """Return a fresh DavStatusStore instance (not the singleton)."""
    from dav_status.store import DavStatusStore
    return DavStatusStore()


def test_store_init_has_all_integrations(store):
    """Store should be pre-populated with caldav, carddav, nextcloud records."""
    all_records = store.get_all()
    assert "caldav" in all_records
    assert "carddav" in all_records
    assert "nextcloud" in all_records


def test_store_default_not_enabled(store):
    """Default records should have enabled=False."""
    assert store.get("caldav")["enabled"] is False
    assert store.get("carddav")["enabled"] is False
    assert store.get("nextcloud")["enabled"] is False


def test_store_default_reachable_is_none(store):
    """Default records should have reachable=None (never checked)."""
    assert store.get("caldav")["reachable"] is None


def test_record_success_updates_fields(store):
    """record_success should update reachable, item_counts, and timestamps."""
    store.record_success("caldav", item_counts={"calendars": 3})
    record = store.get("caldav")
    assert record["reachable"] is True
    assert record["item_counts"]["calendars"] == 3
    assert record["last_success_at"] is not None
    assert record["last_check_at"] is not None


def test_record_error_updates_fields(store):
    """record_error should update reachable=False, last_error_msg, and timestamps."""
    store.record_error("caldav", "Connection refused")
    record = store.get("caldav")
    assert record["reachable"] is False
    assert record["last_error_msg"] is not None
    assert isinstance(record["last_error_msg"], str)
    assert record["last_error_at"] is not None
    assert record["last_check_at"] is not None


def test_record_error_clears_on_success(store):
    """After an error then a success, error fields should be cleared."""
    store.record_error("caldav", "Connection refused")
    store.record_success("caldav", item_counts={"calendars": 2})
    record = store.get("caldav")
    assert record["last_error_msg"] is None
    assert record["last_error_at"] is None
    assert record["reachable"] is True


def test_humanise_error_connection_refused(store):
    """ConnectionRefusedError should produce a plain English message about connection."""
    msg = store._humanise_error(ConnectionRefusedError("test"))
    assert "refused" in msg.lower() or "unreachable" in msg.lower()


def test_humanise_error_connection_error(store):
    """ConnectionError should produce a plain English message."""
    msg = store._humanise_error(ConnectionError("network error"))
    assert "refused" in msg.lower() or "unreachable" in msg.lower()


def test_humanise_error_401(store):
    """String containing '401' should mention authentication."""
    msg = store._humanise_error("401 Unauthorized")
    assert "authentication" in msg.lower() or "auth" in msg.lower()


def test_humanise_error_403(store):
    """String containing '403' should mention permissions."""
    msg = store._humanise_error("403 Forbidden")
    assert "denied" in msg.lower() or "permission" in msg.lower() or "access" in msg.lower()


def test_humanise_error_404(store):
    """String containing '404' should mention not found."""
    msg = store._humanise_error("404 Not Found")
    assert "not found" in msg.lower()


def test_humanise_error_timeout(store):
    """TimeoutError should mention timed out."""
    msg = store._humanise_error(TimeoutError("timed out"))
    assert "timed out" in msg.lower() or "timeout" in msg.lower()


def test_humanise_error_ssl(store):
    """String containing 'SSL' should mention SSL/TLS."""
    msg = store._humanise_error("SSL certificate verification failed")
    assert "ssl" in msg.lower() or "tls" in msg.lower() or "certificate" in msg.lower()


def test_humanise_error_config(store):
    """Config error string should mention configuration."""
    msg = store._humanise_error("Missing required environment variable(s): CALDAV_URL")
    assert "configured" in msg.lower() or "environment" in msg.lower() or "missing" in msg.lower()


def test_add_warning_capped(store):
    """Warnings should be capped at 10 entries."""
    for i in range(15):
        store.add_warning("caldav", f"Warning {i}")
    warnings = store.get("caldav")["warnings"]
    assert len(warnings) <= 10


def test_add_warning_keeps_most_recent(store):
    """After capping, the most recent warnings should be retained."""
    for i in range(15):
        store.add_warning("caldav", f"Warning {i}")
    warnings = store.get("caldav")["warnings"]
    # Most recent should be Warning 14
    assert "Warning 14" in warnings


def test_set_enabled(store):
    """set_enabled should update the enabled flag."""
    store.set_enabled("nextcloud", True)
    assert store.get("nextcloud")["enabled"] is True
    store.set_enabled("nextcloud", False)
    assert store.get("nextcloud")["enabled"] is False


def test_etags_stored(store):
    """record_success should store etags in the record."""
    store.record_success("caldav", etags={"https://example.com/cal/": '"etag123"'})
    record = store.get("caldav")
    assert record["etags"]["https://example.com/cal/"] == '"etag123"'


def test_ctags_stored(store):
    """record_success should store ctags in the record."""
    store.record_success("caldav", ctags={"https://example.com/cal/": "ctag-abc"})
    record = store.get("caldav")
    assert record["ctags"]["https://example.com/cal/"] == "ctag-abc"


def test_sync_tokens_stored(store):
    """record_success should store sync_tokens in the record."""
    store.record_success("caldav", sync_tokens={"https://example.com/cal/": "token-xyz"})
    record = store.get("caldav")
    assert record["sync_tokens"]["https://example.com/cal/"] == "token-xyz"


def test_get_returns_copy(store):
    """get() should return a copy, not the internal dict."""
    record = store.get("caldav")
    record["enabled"] = True  # mutate copy
    # Internal record should remain unchanged
    assert store.get("caldav")["enabled"] is False


def test_get_all_returns_copies(store):
    """get_all() should return copies of all records."""
    all_records = store.get_all()
    all_records["caldav"]["enabled"] = True
    assert store.get("caldav")["enabled"] is False


def test_reset_clears_state(store):
    """reset() should restore all records to defaults."""
    store.record_success("caldav", item_counts={"calendars": 5})
    store.set_enabled("caldav", True)
    store.reset()
    record = store.get("caldav")
    assert record["enabled"] is False
    assert record["reachable"] is None
    assert record["item_counts"] == {}


def test_item_counts_merge(store):
    """Multiple record_success calls should merge item_counts."""
    store.record_success("caldav", item_counts={"calendars": 3})
    store.record_success("caldav", item_counts={"events": 42})
    record = store.get("caldav")
    assert record["item_counts"]["calendars"] == 3
    assert record["item_counts"]["events"] == 42


# ---------------------------------------------------------------------------
# API tests — using TestClient via `client` fixture from conftest.py
# ---------------------------------------------------------------------------


def test_get_status_dav_returns_all(client):
    """GET /status/dav should return 200 with all three integrations."""
    response = client.get("/status/dav")
    assert response.status_code == 200
    data = response.json()
    assert "caldav" in data
    assert "carddav" in data
    assert "nextcloud" in data


def test_get_status_dav_has_required_fields(client):
    """Each integration dict should have the required fields."""
    response = client.get("/status/dav")
    data = response.json()
    for key in ("caldav", "carddav", "nextcloud"):
        rec = data[key]
        assert "integration" in rec
        assert "enabled" in rec
        assert "reachable" in rec
        assert "last_check_at" in rec


def test_get_status_dav_single_integration(client):
    """GET /status/dav/caldav should return 200 with the caldav record."""
    response = client.get("/status/dav/caldav")
    assert response.status_code == 200
    data = response.json()
    assert data["integration"] == "caldav"


def test_get_status_dav_carddav(client):
    """GET /status/dav/carddav should return 200 with the carddav record."""
    response = client.get("/status/dav/carddav")
    assert response.status_code == 200
    data = response.json()
    assert data["integration"] == "carddav"


def test_get_status_dav_nextcloud(client):
    """GET /status/dav/nextcloud should return 200 with the nextcloud record."""
    response = client.get("/status/dav/nextcloud")
    assert response.status_code == 200
    data = response.json()
    assert data["integration"] == "nextcloud"


def test_get_status_dav_unknown_returns_404(client):
    """GET /status/dav/unknown should return 404."""
    response = client.get("/status/dav/unknown_integration")
    assert response.status_code == 404


def test_status_dav_always_200_when_disabled(client):
    """GET /status/dav should always return 200, even when integrations are disabled."""
    response = client.get("/status/dav")
    assert response.status_code == 200
    data = response.json()
    # All integrations are disabled in test config
    assert data["caldav"]["enabled"] is False
    assert data["carddav"]["enabled"] is False
    assert data["nextcloud"]["enabled"] is False


def test_check_dav_caldav_returns_503_when_disabled(client):
    """POST /status/dav/caldav/check should return 503 when caldav is disabled."""
    response = client.post("/status/dav/caldav/check")
    assert response.status_code == 503


def test_check_dav_carddav_returns_503_when_disabled(client):
    """POST /status/dav/carddav/check should return 503 when carddav is disabled."""
    response = client.post("/status/dav/carddav/check")
    assert response.status_code == 503


def test_check_dav_nextcloud_returns_503_when_disabled(client):
    """POST /status/dav/nextcloud/check should return 503 when nextcloud is disabled."""
    response = client.post("/status/dav/nextcloud/check")
    assert response.status_code == 503


def test_check_dav_unknown_returns_404(client):
    """POST /status/dav/unknown/check should return 404."""
    response = client.post("/status/dav/unknown/check")
    assert response.status_code == 404


def test_status_dav_integration_field_matches(client):
    """The integration field in the response should match the URL parameter."""
    for integration in ("caldav", "carddav", "nextcloud"):
        response = client.get(f"/status/dav/{integration}")
        assert response.status_code == 200
        assert response.json()["integration"] == integration
