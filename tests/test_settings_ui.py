"""
tests/test_settings_ui.py — Template-presence tests for the Settings panel (Milestone 19).

The project intentionally does not test JS behavior (there is no JS runtime in
the suite). These tests verify that the read-only Settings panel markup is wired
into the served page and that the existing Memory panel is unaffected. The data
endpoints the panel consumes (/profile, /providers, /status/dav, /health) are
covered by test_api_core.py and test_dav_status.py.
"""

from __future__ import annotations


def test_index_includes_settings_panel(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    for needle in [
        'id="settings-btn"',
        'id="settings-panel"',
        'id="settings-panel-body"',
        'id="settings-close-btn"',
        'class="set-tab',
    ]:
        assert needle in html, f"missing {needle!r} in served page"


def test_settings_panel_has_three_tabs(client):
    html = client.get("/").text
    assert 'data-tab="profile"' in html
    assert 'data-tab="providers"' in html
    assert 'data-tab="integrations"' in html
    assert ">Profile<" in html
    assert ">Providers<" in html
    assert ">Integrations<" in html


def test_memory_panel_still_present(client):
    # Regression: the Settings panel must not disturb the existing Memory panel.
    html = client.get("/").text
    assert 'id="memory-panel"' in html
    assert 'id="memory-btn"' in html
