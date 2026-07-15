"""
tests/test_provider_truthfulness.py — Provider/version truthfulness (M26.2).

The provider listing (Settings → Providers tab and `--list-providers`) must
report each provider's *effective* transport, not the static providers.yaml
`type`. For Grok that means "api" when the API transport is configured and "cli"
otherwise. Separately, the reported app version is the single FastAPI app
version (distinct from the profile's schema version).
"""

from __future__ import annotations


def test_providers_report_grok_api_transport(client, monkeypatch):
    monkeypatch.setenv("GROK_TRANSPORT", "api")
    rows = client.get("/providers").json()
    grok = next((r for r in rows if r["name"] == "grok"), None)
    assert grok is not None
    # Effective transport, not the static providers.yaml `type` (still "cli").
    assert grok["type"] == "api"


def test_providers_default_grok_transport_is_cli(client, monkeypatch):
    monkeypatch.delenv("GROK_TRANSPORT", raising=False)
    rows = client.get("/providers").json()
    grok = next((r for r in rows if r["name"] == "grok"), None)
    assert grok is not None
    assert grok["type"] == "cli"


def test_non_grok_provider_type_unchanged(client, monkeypatch):
    # A static-transport provider still reports its configured type.
    monkeypatch.delenv("GROK_TRANSPORT", raising=False)
    rows = client.get("/providers").json()
    chatgpt = next((r for r in rows if r["name"] == "chatgpt"), None)
    if chatgpt is not None:
        assert chatgpt["type"] == "api"


def test_health_version_is_the_app_version(client):
    import main as app_module

    health = client.get("/health").json()
    # The reported version is the single FastAPI app version (the exact string
    # is pinned by test_ops_hardening; here we assert the *sourcing*).
    assert health["version"] == app_module.app.version
