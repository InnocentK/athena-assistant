"""Tests for the installable-PWA surfaces (M26.28).

Covers the two things the backend is responsible for: the ``/sw.js`` route
(root-scoped service worker with the version substituted into its cache name)
and the static web-app manifest. The service worker's *runtime* caching logic
is JS and is not unit-tested here (jsdom has no real service-worker runtime);
the JS side covers the registration guard in ``tests/js/pwa.test.js``.
"""

import json

from core.version import __version__


def test_service_worker_served_at_root(client):
    """GET /sw.js → 200 as JavaScript, from the site root (scope '/')."""
    resp = client.get("/sw.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"].lower()


def test_service_worker_cache_name_carries_version(client):
    """The worker's cache name is release-scoped: the running version is
    substituted in, and the ``__ATHENA_VERSION__`` placeholder is gone."""
    body = client.get("/sw.js").text
    # placeholder fully substituted; version present; cache name is release-scoped
    # (the name is composed at runtime as "athena-shell-" + VERSION).
    assert "__ATHENA_VERSION__" not in body
    assert f'"{__version__}"' in body
    assert "athena-shell-" in body


def test_service_worker_is_not_http_cached(client):
    """The SW script sets a revalidating Cache-Control so an updated worker is
    picked up rather than served stale."""
    resp = client.get("/sw.js")
    assert "no-cache" in resp.headers.get("cache-control", "").lower()


def test_manifest_served_and_wellformed(client):
    """The web-app manifest is a valid static asset with the fields that make
    'install' work: standalone display, root start_url, and icons."""
    resp = client.get("/static/manifest.webmanifest")
    assert resp.status_code == 200
    data = json.loads(resp.text)
    assert data["display"] == "standalone"
    assert data["start_url"] == "/"
    assert data["scope"] == "/"
    assert isinstance(data.get("icons"), list) and data["icons"]
    # a maskable icon must be present for a good Android home-screen glyph
    assert any(i.get("purpose") == "maskable" for i in data["icons"])


def test_shell_icons_are_served(client):
    """The manifest/apple icons resolve (a broken icon URL kills installability)."""
    for path in (
        "/static/icons/icon-192.png",
        "/static/icons/icon-512.png",
        "/static/icons/icon-maskable-512.png",
        "/static/icons/apple-touch-icon.png",
    ):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert resp.headers["content-type"] == "image/png"


def test_index_wires_up_pwa(client):
    """The index HTML links the manifest and loads the registration script."""
    html = client.get("/").text
    assert 'rel="manifest"' in html
    assert "/static/js/pwa.js" in html
    assert 'name="theme-color"' in html
