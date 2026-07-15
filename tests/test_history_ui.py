"""
tests/test_history_ui.py — Template-presence tests for the History & Attachments
panel (Milestone 20).

Consistent with the project's testing approach, JS behavior is not exercised
(there is no JS runtime in the suite). These verify the panel markup is wired
into the served page and that the existing Memory and Settings panels are
unaffected. The Files tab consumes existing endpoints (/files/search,
/files/read) already covered by test_files_api.py.
"""

from __future__ import annotations


def test_index_includes_history_panel(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    for needle in [
        'id="history-btn"',
        'id="history-panel"',
        'id="history-panel-body"',
        'id="history-close-btn"',
        'class="hist-tab',
    ]:
        assert needle in html, f"missing {needle!r} in served page"


def test_history_panel_has_two_tabs(client):
    html = client.get("/").text
    assert 'data-tab="conversation"' in html
    assert 'data-tab="files"' in html
    assert ">Conversation<" in html
    assert ">Files<" in html


def test_memory_and_settings_panels_still_present(client):
    # Regression: the History panel must not disturb the earlier panels.
    html = client.get("/").text
    assert 'id="memory-panel"' in html
    assert 'id="settings-panel"' in html
