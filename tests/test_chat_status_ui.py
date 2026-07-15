"""
tests/test_chat_status_ui.py — Web UI status/progress feedback (Milestone 24).

Backend: /chat forwards the (content-free) M22 diagnostics trace on
ChatResponse.diagnostics. Frontend: template-presence for the in-flight status
element. The JS summary/in-flight behaviour itself isn't exercised (no JS
runtime in the suite — consistent with M19/M20).
"""

from __future__ import annotations

from providers.base import ProviderResponse


class _FakeRouter:
    def __init__(self, diagnostics):
        self._diag = diagnostics

    def route(self, messages, system_prompt, profile_config):
        meta = {}
        if self._diag is not None:
            meta["diagnostics"] = self._diag
        return ProviderResponse(
            content="hi", provider_name="grok", model="m", success=True, metadata=meta
        )


def test_chat_forwards_diagnostics(client, monkeypatch):
    import main as app_module

    trace = {
        "request_id": "abc",
        "selected": "grok",
        "total_ms": 800.0,
        "mode": "balanced",
        "attempt_order": ["grok"],
        "records": [
            {"provider": "grok", "transport": "api", "outcome": "ok", "duration_ms": 800.0}
        ],
    }
    monkeypatch.setattr(app_module, "_router", _FakeRouter(trace))

    resp = client.post("/chat", json={"message": "hi"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["response"] == "hi"
    assert body["diagnostics"] == trace


def test_chat_diagnostics_null_when_absent(client, monkeypatch):
    import main as app_module

    monkeypatch.setattr(app_module, "_router", _FakeRouter(None))
    resp = client.post("/chat", json={"message": "hi"})
    assert resp.status_code == 200
    assert resp.json()["diagnostics"] is None


def test_index_includes_chat_status(client):
    html = client.get("/").text
    assert 'id="chat-status"' in html


def test_other_panels_still_present(client):
    # Regression — the status line must not disturb the existing panels.
    html = client.get("/").text
    for needle in ['id="memory-panel"', 'id="settings-panel"', 'id="history-panel"']:
        assert needle in html


# ---------------------------------------------------------------------------
# Cache-busting for static assets (Milestone 26.1)
# ---------------------------------------------------------------------------


def test_index_uses_versioned_static_assets(client):
    # Versioned ?v= URLs bust the browser cache on each release so JS/CSS changes
    # (editable settings, status behaviour) actually reach users.
    html = client.get("/").text
    assert "/static/js/chat.js?v=" in html
    assert "/static/css/chat.css?v=" in html


def test_static_assets_send_revalidation_header(client):
    resp = client.get("/static/js/chat.js")
    assert resp.status_code == 200
    assert "no-cache" in resp.headers.get("cache-control", "")
