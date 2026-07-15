"""
tests/test_api_core.py — Tests for core API endpoints (health, profile, providers).
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


def test_health_returns_ok(client):
    """GET /health returns 200 with status=='ok', version, and profile keys."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "profile" in data


def test_health_version_is_string(client):
    """GET /health returns a non-empty version string."""
    response = client.get("/health")
    version = response.json()["version"]
    assert isinstance(version, str)
    assert len(version) > 0


# ---------------------------------------------------------------------------
# Providers endpoint
# ---------------------------------------------------------------------------


def test_providers_endpoint_returns_list(client):
    """GET /providers returns a 200 with a list body."""
    response = client.get("/providers")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ---------------------------------------------------------------------------
# Profile endpoint
# ---------------------------------------------------------------------------


def test_profile_endpoint_returns_dict(client):
    """GET /profile returns 200 with a dict containing 'name'."""
    response = client.get("/profile")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "name" in data


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------


def test_chat_returns_error_when_no_providers(client):
    """POST /chat with no real providers available returns 200 (not 500)."""
    response = client.post(
        "/chat",
        json={"message": "hello", "history": []},
    )
    # No live providers in sandbox — expect either success:false or success:true
    # but NEVER a 500 crash
    assert response.status_code != 500
    # If 200, check it has expected fields
    if response.status_code == 200:
        data = response.json()
        assert "success" in data
        assert "response" in data


# ---------------------------------------------------------------------------
# 404 for unknown routes
# ---------------------------------------------------------------------------


def test_unknown_route_returns_404(client):
    """GET /does_not_exist_xyz returns 404."""
    response = client.get("/does_not_exist_xyz")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Integration disabled → 503
# ---------------------------------------------------------------------------


def test_caldav_disabled_returns_503(client):
    """GET /caldav/calendars returns 503 when CalDAV is disabled."""
    response = client.get("/caldav/calendars")
    assert response.status_code == 503


def test_carddav_disabled_returns_503(client):
    """GET /carddav/addressbooks returns 503 when CardDAV is disabled."""
    response = client.get("/carddav/addressbooks")
    assert response.status_code == 503


def test_nextcloud_disabled_returns_503(client):
    """GET /nextcloud/ping returns 503 when Nextcloud is disabled."""
    response = client.get("/nextcloud/ping")
    assert response.status_code == 503
